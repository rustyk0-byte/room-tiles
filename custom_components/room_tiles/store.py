"""Persistent storage for Room Tiles (.storage/room_tiles)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .backups import prune, wrap
from .const import BACKUP_DIR, DEV_BUILD, FW_TRIES_KEY, PANEL_KEYS_KEY, STORAGE_KEY, STORAGE_MINOR_VERSION, STORAGE_VERSION
from .migrate import migrate
from .model import RoomTilesData
from .appliance_presets import PRESETS
from .ops import ALL_SECTIONS

# the version HA is running (read once, at import - an update shows after the restart)
VERSION: str = json.loads((Path(__file__).parent / "manifest.json").read_text(encoding="utf-8")).get("version", "")

# what setup can pick from (static)
APPLIANCE_PRESET_LIST = [
    {
        "id": p.id,
        "name": p.name,
        "appliance": p.appliance,
        "verified": p.verified,
        "power": p.power,
    }
    for p in PRESETS.values()
]

Listener = Callable[[tuple[str, ...]], None]

_LOGGER = logging.getLogger(__name__)

SAVE_DELAY = 2  # seconds: coalesce bursts of edits into one write


class _MigratingStore(Store[dict[str, Any]]):
    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict[str, Any]
    ) -> dict[str, Any]:
        # Keep the old-format data first: going back to an older Room Tiles
        # (a backup, a downgrade) can then import it again.
        await self.hass.async_add_executor_job(
            save_pre_migration_copy,
            self.hass.config.config_dir,
            old_major_version,
            old_minor_version,
            old_data,
        )
        return migrate(old_major_version, old_minor_version, old_data, STORAGE_MINOR_VERSION)


def save_pre_migration_copy(config_dir: str, major: int, minor: int, doc: dict[str, Any]) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")  # unique: never overwrite a copy
    path = Path(config_dir) / BACKUP_DIR / f"before-migration-v{major}.{minor}-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # (as HA stores it, with its version: the import action takes it back,
    # migrated - backups.py)
    path.write_text(json.dumps(wrap(major, minor, doc), indent=1, ensure_ascii=False), encoding="utf-8")
    prune(path.parent)
    _LOGGER.warning(
        "Room Tiles data upgraded from storage version %s.%s; the old data was saved to %s",
        major,
        minor,
        path,
    )
    return path


class RoomTilesStore:
    """Holds the live RoomTilesData and writes it back on change.

    Listeners (sensors, websocket subscribers) are told after every change so
    panels and the dashboard update immediately; the disk write is delayed.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store = _MigratingStore(
            hass, STORAGE_VERSION, STORAGE_KEY, minor_version=STORAGE_MINOR_VERSION
        )
        # the automatic installs' tries per (panel, build) - kept across HA
        # restarts, so a build that won't take isn't tried again after every
        # restart (firmware.AUTO_TRIES); its own small file
        self._fw_tries_store: Store[dict[str, Any]] = Store(hass, 1, FW_TRIES_KEY)
        self._fw_tries_pending = False
        # each panel's own key (made here, handed to the panel over its
        # ESPHome connection - panels.async_send_key): device id -> 64 hex.
        # Its own file: never in exports, the dashboard or a payload
        self._keys_store: Store[dict[str, Any]] = Store(hass, 1, PANEL_KEYS_KEY)
        self._keys_pending = False
        self.panel_keys: dict[str, str] = {}
        self.data = RoomTilesData()
        # worked out from HA, sent to clients, never saved: area id -> the
        # lights its button switches (arealights.py)
        self.area_lights: dict[str, list[str]] = {}
        # entities Room Tiles uses that are DISABLED in HA: their tiles show
        # empty and their markers hidden, but are kept for when re-enabled
        self.disabled: list[str] = []
        # vacuums that clean by HA area (vacuum.clean_area): entity id ->
        # {name, areas: the HA areas its segments are mapped to} (vacuums.py)
        self.vacuums: dict[str, dict[str, Any]] = {}
        # newer Room Tiles files installed than HA is running (update_watch.py)
        self.restart_needed = False
        # the revision wall panels watch (panels.py)
        from .panels import PanelLink

        self.panel_link = PanelLink()
        self.panel_packs: dict = {}  # theme packs + wording: headers only, the packs stay on disk (packs.py)
        # a developer build's demo home on panels (demo.py; DEV_BUILD only -
        # a released install never fills these)
        self.demo_names: set[str] = set()
        self.demo_home: dict | None = None
        self.demo_picks: dict[str, Any] = {}  # device id -> its settings with its demo picks (never saved)
        self.user_themes: Any = None  # the installed themes (user_themes.UserThemes), set at setup
        # panel firmware (firmware.py): the newest image per board, what each
        # panel reports it runs (device id -> PanelFirmware), the installs
        # asked for (device id -> build) - which of them Room Tiles asked for
        # itself ("Update panels automatically") - the downloads per (device,
        # build), and who to tell when these change
        self.fw_images: dict = {}
        self.fw_reports: dict = {}
        self.fw_install: dict[str, str] = {}
        self.fw_auto: set[str] = set()
        # the build each panel last fetched (PanelFirmwareView): an automatic
        # install has started once it's the one asked for (firmware_installing)
        self.fw_fetched: dict[str, str] = {}
        self.fw_tries: dict[tuple[str, str], int] = {}
        # a too-old panel's forced update: when it was fetched (this HA run
        # only, the last hour counts - never stuck for good)
        self.fw_forced: dict[tuple[str, str], list[float]] = {}
        self.fw_report_ts: dict[str, int] = {}  # (when each panel's last report was signed)
        self.fw_listeners: list[Callable[[], None]] = []
        self.fw_rescan: Callable[[], Any] | None = None  # (__init__: read the images again)
        self.fw_upload_dir: Any = None  # (<config>/room_tiles_firmware)
        # appliance setup (appliances_ha.py): {"found": not set up yet,
        # "again": appliance id -> a fresh setup of its hardware}
        self.appliance_found: dict[str, Any] = {
            "found": [], "again": {}, "pools": [], "robots": [],
            "found_ignored": [], "pools_ignored": [], "robots_ignored": [],
        }
        # pool / spa sensor entity id -> (its PoolRuntime, body or None) (sensor.py)
        self.pool_entities: dict[str, Any] = {}
        self.pool_runtimes: dict[str, Any] = {}  # pool id -> PoolRuntime (sensor.py)
        # appliance id -> its live sensor (sensor.py)
        self.appliance_entities: dict[str, Any] = {}
        self.robot_entities: dict[str, Any] = {}  # robot id -> its sensor (the room queue)
        self._listeners: list[Listener] = []
        self._unload_listeners: list[Callable[[], None]] = []
        # "Report a problem": appliances' next cycles being recorded (cycles.py)
        from .cycles import Recordings

        self.recordings = Recordings(hass, lambda: self.async_notify(("recordings",)))
        from .map_backups import MapBackups

        self.map_backups = MapBackups(hass)

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        self.data = RoomTilesData.from_dict(raw)
        await self.map_backups.async_load()
        keys = await self._keys_store.async_load() or {}
        self.panel_keys = {
            str(d): str(k).lower()
            for d, k in (keys.get("keys") or {}).items()
            if isinstance(k, str) and len(k) == 64 and all(c in "0123456789abcdefABCDEF" for c in k)
        }
        tries = await self._fw_tries_store.async_load() or {}
        for row in tries.get("tries", []):
            try:
                device_id, build, count = row
                self.fw_tries[(str(device_id), str(build))] = int(count)
            except (TypeError, ValueError):
                continue
        _LOGGER.debug(
            "Loaded %d areas, %d maps, %d markers",
            len(self.data.areas),
            len(self.data.maps),
            len(self.data.markers),
        )

    @callback
    def demo_shows(self, dev: Any) -> bool:
        """Does this panel show the demo home (demo.py)?"""
        from .demo import shows_demo

        return bool(self.demo_names) and shows_demo(self.demo_names, self.demo_home, dev)

    async def async_reload_packs(self) -> None:
        """The bundled packs' headers read again (panels.load_packs); the
        panels told when one changed."""
        from . import panels

        try:
            packs = await self.hass.async_add_executor_job(panels.load_packs)
        except (OSError, EOFError, ValueError):
            return  # (still being written: next time)
        changed = panels.pack_ids(packs) != panels.pack_ids(self.panel_packs)
        self.panel_packs = packs
        if changed:
            self.panel_link.bump()

    def all_packs(self) -> dict:
        """Every pack a panel may get: the bundled themes and wording, and the
        installed themes' (user_themes.py)."""
        if self.user_themes is None:
            return self.panel_packs
        return {**self.panel_packs, **self.user_themes.packs()}

    def async_changed(self, sections: tuple[str, ...] = ALL_SECTIONS) -> None:
        """Call after changing self.data: validates, schedules a save and
        tells listeners which document sections changed."""
        self.data.validate()
        self._store.async_delay_save(self.data.as_dict, SAVE_DELAY)
        for listener in list(self._listeners):
            listener(sections)

    @callback
    def async_notify(self, sections: tuple[str, ...]) -> None:
        """Tell listeners about derived data (no save, no validation)."""
        for listener in list(self._listeners):
            listener(sections)

    @callback
    def firmware_seen(self, device_id: str, report: Any, ts: int = 0) -> None:
        """A panel reported what it runs (firmware.PanelFirmware): an install
        asked for is done once it runs that build; update entities hear.
        `ts`: when it was signed - one older than the last taken is ignored."""
        if ts and ts < self.fw_report_ts.get(device_id, 0):
            return
        if ts:
            self.fw_report_ts[device_id] = ts
        changed = self.fw_reports.get(device_id) != report
        self.fw_reports[device_id] = report
        if self.fw_install.get(device_id) == report.build:
            del self.fw_install[device_id]
            self.fw_auto.discard(device_id)
            changed = True
        if not self.firmware_auto() and changed:
            self.firmware_changed()

    @callback
    def firmware_install(self, device_id: str, build: str) -> None:
        """An install asked for by hand (the update entity) or forced (a panel
        too old for this Room Tiles): right away, and tried afresh."""
        self.fw_install[device_id] = build
        self.fw_auto.discard(device_id)
        if self.fw_tries.pop((device_id, build), None) is not None:
            self._save_fw_tries()
        self.panel_link.bump()
        self.firmware_changed()

    @callback
    def firmware_auto(self) -> bool:
        """Bring the automatic installs up to date ("Update panels
        automatically", firmware.auto_installs) - after a panel's report, new
        images, a download, the setting. True when they changed (panels and
        update entities told)."""
        from .firmware import auto_installs

        want = auto_installs(self.fw_images, self.fw_reports, self.fw_tries) if self.data.settings.auto_update_panels else {}
        changed = False
        # an install (by hand too) of a build no longer offered (another image
        # came for its board): over - never "updating" for good
        offered = {img.build for img in self.fw_images.values()}
        for device_id, build in list(self.fw_install.items()):
            if build not in offered:
                del self.fw_install[device_id]
                self.fw_auto.discard(device_id)
                changed = True
        for device_id in list(self.fw_auto):
            if want.get(device_id) != self.fw_install.get(device_id):
                self.fw_auto.discard(device_id)
                self.fw_install.pop(device_id, None)
                changed = True
        for device_id, build in want.items():
            if device_id not in self.fw_install:  # (one asked for by hand stays)
                self.fw_install[device_id] = build
                self.fw_auto.add(device_id)
                changed = True
        if changed:
            self.panel_link.bump()
            self.firmware_changed()
        return changed

    @callback
    def firmware_may_fetch(self, device_id: str, build: str, forced: bool) -> bool:
        """May the panel have this image (again)? An install asked for by hand:
        at most INSTALL_TRIES fetches (then it's given up - Install again
        starts afresh); a too-old panel's forced one: INSTALL_TRIES within
        the last hour."""
        import time

        from .firmware import INSTALL_TRIES

        key = (device_id, build)
        if forced:
            recent = [t for t in self.fw_forced.get(key, []) if time.time() - t < 3600]
            self.fw_forced[key] = recent
            return len(recent) < INSTALL_TRIES
        if self.fw_install.get(device_id) == build and device_id not in self.fw_auto and self.fw_tries.get(key, 0) >= INSTALL_TRIES:
            del self.fw_install[device_id]  # (it doesn't take: given up)
            self.panel_link.bump()
            self.firmware_changed()
            return False
        return True

    @callback
    def firmware_downloaded(self, device_id: str, build: str, forced: bool = False) -> None:
        """A panel fetched an image: counted (firmware.AUTO_TRIES /
        INSTALL_TRIES) - and an install waiting for the panel to be unused
        has started."""
        import time

        key = (device_id, build)
        if forced:
            self.fw_forced.setdefault(key, []).append(time.time())
            return  # (a too-old panel: nothing else of it is kept)
        self.fw_tries[key] = self.fw_tries.get(key, 0) + 1
        self._save_fw_tries()
        started = self.fw_install.get(device_id) == build and self.fw_fetched.get(device_id) != build
        self.fw_fetched[device_id] = build
        if started:
            self.firmware_changed()

    def firmware_installing(self, device_id: str) -> bool:
        """An install is under way: one asked for by hand (the panel installs
        it right away), or an automatic one the panel has started fetching -
        not one still waiting for nobody to be using the panel."""
        build = self.fw_install.get(device_id)
        return build is not None and (device_id not in self.fw_auto or self.fw_fetched.get(device_id) == build)

    def _fw_tries_doc(self) -> dict[str, Any]:
        """The tries to keep - only for builds still offered: the file stays
        small, and an old build's count goes with it."""
        offered = {img.build for img in self.fw_images.values()}
        if offered:
            for key in [k for k in self.fw_tries if k[1] not in offered]:
                del self.fw_tries[key]
        return {"tries": [[d, b, n] for (d, b), n in sorted(self.fw_tries.items())]}

    @callback
    def panel_key(self, device_id: str, create: bool = False) -> str | None:
        """A panel's own key (64 hex) - made when there's none yet and `create`."""
        key = self.panel_keys.get(device_id)
        if key is None and create:
            import secrets

            key = self.panel_keys[device_id] = secrets.token_hex(32)
            self._save_keys()
        return key

    @callback
    def keep_panel_keys(self, device_ids: set[str]) -> None:
        """A panel gone from HA: its key goes too (re-added: a new one)."""
        gone = [d for d in self.panel_keys if d not in device_ids]
        for d in gone:
            del self.panel_keys[d]
        if gone:
            self._save_keys()

    @callback
    def _save_keys(self) -> None:
        self._keys_pending = True
        self._keys_store.async_delay_save(lambda: {"keys": dict(self.panel_keys)}, 1)

    @callback
    def _save_fw_tries(self) -> None:
        """The tries saved (delayed; written at once on unload)."""
        self._fw_tries_pending = True
        self._fw_tries_store.async_delay_save(self._fw_tries_doc, SAVE_DELAY)

    @callback
    def firmware_changed(self) -> None:
        for listener in list(self.fw_listeners):
            listener()
        self.async_notify(("panel_firmware",))  # (the dashboard's Panels page)

    def payload(self) -> dict[str, Any]:
        """What clients receive: the document plus derived sections."""
        from .model_report import beta_units
        from .update import firmware_rows
        return {
            **self.data.as_dict(),
            "area_lights": self.area_lights,
            "disabled": self.disabled,
            "vacuums": self.vacuums,
            "restart_needed": self.restart_needed,
            "version": VERSION,
            # a developer build (a source checkout): its test-only menu items
            "dev_build": DEV_BUILD,
            "appliance_found": self.appliance_found["found"],
            "appliance_again": self.appliance_found["again"],
            "pool_found": self.appliance_found["pools"],
            "robot_found": self.appliance_found["robots"],
            # ignored by the user: listed at the bottom of the Appliances page
            "ignored_found": {
                "appliances": self.appliance_found["found_ignored"],
                "pools": self.appliance_found["pools_ignored"],
                "robots": self.appliance_found["robots_ignored"],
            },
            "appliance_presets": APPLIANCE_PRESET_LIST,
            "panel_firmware": firmware_rows(self.hass, self),
            # "Report a problem" recordings: appliance id -> its status
            "recordings": self.recordings.doc,
            # what's beta ("Report how it went"): "<kind>:<id>" -> its beta units
            "beta": beta_units(self.hass, self.data),
            # the installed themes (user_themes.py): ready ones, getting ready, can't be used
            "themes": self.user_themes.for_dashboard() if self.user_themes is not None else {"themes": [], "building": [], "problems": []},
        }

    async def async_save_now(self) -> None:
        """Unloading: everything waiting to be saved, written now (a delayed
        write left behind would land after a removal deleted the file)."""
        await self._store.async_save(self.data.as_dict())
        if self._fw_tries_pending:
            self._fw_tries_pending = False
            await self._fw_tries_store.async_save(self._fw_tries_doc())
        if self._keys_pending:
            self._keys_pending = False
            await self._keys_store.async_save({"keys": dict(self.panel_keys)})

    @callback
    def async_add_listener(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    @callback
    def async_add_unload_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Told when this store goes away (entry unload / reload)."""
        self._unload_listeners.append(listener)

        def remove() -> None:
            if listener in self._unload_listeners:
                self._unload_listeners.remove(listener)

        return remove

    @callback
    def async_unloaded(self) -> None:
        for listener in list(self._unload_listeners):
            listener()
        self._unload_listeners.clear()
        self._listeners.clear()
