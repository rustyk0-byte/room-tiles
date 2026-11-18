"""Room Tiles: room-by-room control tiles and house maps for wall panels and
the Room Tiles dashboard."""

from __future__ import annotations

import logging
import struct
import zlib
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import floor_registry as fr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .defaults import fill_defaults
from .const import BACKUP_DIR, DEV_BUILD, DOMAIN, FW_TRIES_KEY, RECORDINGS_KEY, STORAGE_KEY, STORAGE_VERSION
from .frontend import async_register_panel, async_remove_panel
from . import arealights, firmware, ops, panels, shortnames, update_watch, wording
from .ops import flag_short_names
from .repairs import (
    async_report_dropped_overrides,
    FOUND_NOTIFICATION,
    async_report_found,
    async_report_removed_entity,
    ISSUE_SHORT_NAMES,
    REVIEW_NOTIFICATION,
    async_report_review,
    review_keys,
    async_update_missing,
)
from .services import async_register_services
from .sync import sync_areas
from .vacuums import vacuum_areas
from .appliances_ha import found_appliances
from .store import RoomTilesStore
from .websocket import async_register as async_register_websocket

type RoomTilesConfigEntry = ConfigEntry[RoomTilesStore]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = [Platform.LIGHT, Platform.SENSOR, Platform.SWITCH, Platform.UPDATE]
_LOGGER = logging.getLogger(__name__)
PACK_CHECK_EVERY = timedelta(seconds=10)  # (developing only: packs rebuilt on disk served live)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    # Actions are registered once, independent of the entry (HA's rule), and
    # refuse politely while Room Tiles isn't set up.
    async_register_services(hass)
    async_register_websocket(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: RoomTilesConfigEntry) -> bool:
    if DEV_BUILD:
        _LOGGER.warning("Room Tiles is a developer build (running from its source): development-only behavior is on")
    # short names are shortened by the rules for HA's language
    shortnames.set_language(hass.config.language)
    # ...and status lines are worded in it
    wording.set_language(hass.config.language)
    firmware.set_time_zone(dt_util.DEFAULT_TIME_ZONE)  # (build times shown in HA's)
    store = RoomTilesStore(hass)
    await store.async_load()
    changed = sync_areas(hass, store.data, first_setup=dict(entry.data))
    found_panels = panels.find_panels(hass)
    store.panel_link.devices_seen(found_panels)
    if panels.sync_panels(store.data, found_panels):
        changed = True
    if flag_short_names(store.data) or changed:
        store.async_changed()
    entry.runtime_data = store
    # recordings of an appliance's next cycle carry on (HA restarting marks them)
    import time

    await store.recordings.async_load(store.data, time.time(), ha_starting=not hass.is_running)

    store.panel_packs = await hass.async_add_executor_job(panels.load_packs)
    # developing (running from the Room Tiles source - never a released
    # install): packs rebuilt on disk are served live, no restart - checked
    # every few seconds, loaded once settled, panels told when one changed
    pack_watch = panels.PackWatch(await hass.async_add_executor_job(panels.packs_fingerprint))

    async def check_packs(_now: Any = None) -> None:
        now = await hass.async_add_executor_job(panels.packs_fingerprint)
        if not pack_watch.settled_change(now):
            return
        try:
            packs = await hass.async_add_executor_job(panels.load_packs)
        except (OSError, EOFError, ValueError, struct.error, zlib.error):
            return  # (still being written: next time)
        pack_watch.loaded = now
        if panels.pack_ids(packs) != panels.pack_ids(store.panel_packs):
            store.panel_packs = packs
            store.panel_link.bump()

    if DEV_BUILD:
        entry.async_on_unload(async_track_time_interval(hass, check_packs, PACK_CHECK_EVERY))

    # panel firmware images (firmware.py): read at setup (HA's Reload of the
    # integration reads them again) and after an upload; a developer build
    # also picks up builds dropped into the folder, like packs (each named
    # for its board, older builds of the board removed)
    upload_dir = Path(hass.config.path(firmware.UPLOAD_DIR_NAME))
    fw_dirs = [firmware.BUNDLED_DIR, upload_dir]

    async def rescan_firmware() -> None:
        store.fw_images = await hass.async_add_executor_job(firmware.scan_images, fw_dirs, panels.PANEL_SCHEMA)
        if not store.firmware_auto():
            store.firmware_changed()

    store.fw_rescan = rescan_firmware
    store.fw_upload_dir = upload_dir
    await rescan_firmware()
    fw_watch = panels.PackWatch(await hass.async_add_executor_job(firmware.images_fingerprint, fw_dirs))

    async def check_firmware(_now: Any = None) -> None:
        now = await hass.async_add_executor_job(firmware.images_fingerprint, fw_dirs)
        if not fw_watch.settled_change(now):
            return
        for line in await hass.async_add_executor_job(firmware.tidy_folder, upload_dir):
            _LOGGER.info("Panel firmware folder: %s", line)
        fw_watch.loaded = await hass.async_add_executor_job(firmware.images_fingerprint, fw_dirs)
        await rescan_firmware()

    if DEV_BUILD:
        entry.async_on_unload(async_track_time_interval(hass, check_firmware, PACK_CHECK_EVERY))

    @callback
    def settings_changed(sections: tuple[str, ...]) -> None:
        if "settings" in sections and not store.firmware_auto():  # ("Update panels automatically")
            store.firmware_changed()  # (the update entities say whether it's on)

    entry.async_on_unload(store.async_add_listener(settings_changed))
    # wall panels: the revision they watch follows what they show, and they
    # fetch their payload from HA's HTTP server (panels.py; registered once
    # per HA run - views can't be removed - and it finds the running store)
    entry.async_on_unload(store.async_add_listener(store.panel_link.sections_changed))
    if not hass.data.get(f"{DOMAIN}_panel_view"):
        hass.data[f"{DOMAIN}_panel_view"] = True

        def _running_store() -> RoomTilesStore | None:
            return next((e.runtime_data for e in hass.config_entries.async_loaded_entries(DOMAIN)), None)

        hass.http.register_view(panels.PanelView(_running_store))
        hass.http.register_view(panels.PanelPackView(_running_store))
        hass.http.register_view(panels.PanelFirmwareView(_running_store))
        hass.http.register_view(panels.PanelActionView(_running_store))
        hass.http.register_view(panels.PanelScreenshotView(_running_store))
        from .update import FirmwareUploadView

        hass.http.register_view(FirmwareUploadView(_running_store))

    # short names to review: a notification when new ones come up (what's
    # waiting at startup doesn't notify again); older versions' repair goes
    ir.async_delete_issue(hass, DOMAIN, ISSUE_SHORT_NAMES)
    review_seen = review_keys(store.data)

    @callback
    def review_changed(_sections: tuple[str, ...]) -> None:
        nonlocal review_seen
        review_seen = async_report_review(hass, store.data, review_seen)

    entry.async_on_unload(store.async_add_listener(review_changed))

    # an update installed (HACS or by hand) but HA still runs the old code:
    # the dashboard's Restart bar + a repair (update_watch.py)
    entry.async_on_unload(update_watch.async_start(hass, store))

    started = False  # set by async_at_started below

    @callback
    def refresh(sections: set[str], gone: frozenset[str] = frozenset()) -> None:
        """After any HA registry change: follow areas, prune Area Lights
        exceptions, recompute light sets, check for missing entities."""
        if sync_areas(hass, store.data):
            sections.add(ops.SECTION_AREAS)
        found_panels = panels.find_panels(hass)
        if panels.sync_panels(store.data, found_panels):
            sections.add(ops.SECTION_PANELS)
        store.panel_link.devices_seen(found_panels)
        before = [(a.lights, list(a.lights_exclude)) for a in store.data.areas]
        if started:  # overrides: only once every integration has its entities
            dropped = arealights.prune(hass, store.data, gone)
            if dropped:
                async_report_dropped_overrides(hass, dropped)
        else:
            for a in store.data.areas:  # exclusions only
                here = set(arealights.lights_by_area(hass).get(a.id, []))
                a.lights_exclude = [e for e in a.lights_exclude if e in here]
        if before != [(a.lights, list(a.lights_exclude)) for a in store.data.areas]:
            sections.add(ops.SECTION_AREAS)
        if started:
            # new areas (and, once, every area of a new / upgraded home):
            # their default boards and map markers (defaults.py)
            sections.update(fill_defaults(hass, store.data, found_appliances(hass, store.data)))
        if flag_short_names(store.data):
            sections.update((ops.SECTION_AREAS, ops.SECTION_CATALOG))
        if sections:
            store.async_changed(tuple(sorted(sections)))
        store.area_lights = arealights.resolve_all(hass, store.data)
        disabled = _disabled_entities(hass, store.data)
        notify = ["area_lights"]
        if disabled != store.disabled:
            store.disabled = disabled
            notify.append("disabled")
        vacs = vacuum_areas(hass)
        if vacs != store.vacuums:
            store.vacuums = vacs
            notify.append("vacuums")
        found = found_appliances(hass, store.data)
        if found != store.appliance_found:
            async_report_found(hass, store.appliance_found, found)
            store.appliance_found = found
            notify.extend(("appliance_found", "appliance_again", "pool_found", "robot_found", "ignored_found"))
        store.async_notify(tuple(notify))
        if started:
            async_update_missing(hass, store.data, set(disabled))

    @callback
    def registry_changed(_event: Event) -> None:
        refresh(set())

    @callback
    def entity_registry_changed(event: Event) -> None:
        sections: set[str] = set()
        old = event.data.get("old_entity_id")
        if event.data.get("action") == "update" and old:
            sections.update(ops.rename_entity(store.data, old, event.data["entity_id"]))
        gone = frozenset({event.data["entity_id"]}) if event.data.get("action") == "remove" else frozenset()
        if gone:
            # DELETED in HA: remove it everywhere in Room Tiles, and say what went
            removed, where = ops.forget_entity(store.data, event.data["entity_id"])
            sections.update(removed)
            # Room Tiles' own entities (an area's lights when its last light
            # goes...) leave quietly - it removed them itself
            own = event.data["entity_id"].split(".", 1)[-1].startswith("room_tiles_")
            if where and not own:
                async_report_removed_entity(hass, event.data["entity_id"], where)
        refresh(sections, gone)

    @callback
    def ha_started(_hass: HomeAssistant) -> None:
        nonlocal started
        started = True
        refresh(set())

    store.area_lights = arealights.resolve_all(hass, store.data)
    store.disabled = _disabled_entities(hass, store.data)
    store.vacuums = vacuum_areas(hass)
    store.appliance_found = found_appliances(hass, store.data)
    # areas renamed / added / removed, floors renamed, entities / devices
    # moved, renamed or removed: follow HA
    for event_type, handler in (
        (ar.EVENT_AREA_REGISTRY_UPDATED, registry_changed),
        (fr.EVENT_FLOOR_REGISTRY_UPDATED, registry_changed),
        (dr.EVENT_DEVICE_REGISTRY_UPDATED, registry_changed),
        (er.EVENT_ENTITY_REGISTRY_UPDATED, entity_registry_changed),
    ):
        entry.async_on_unload(hass.bus.async_listen(event_type, handler))
    # appliance edits change what setup still offers
    @callback
    def appliances_changed(sections: tuple[str, ...]) -> None:
        if ops.SECTION_APPLIANCES in sections or ops.SECTION_POOLS in sections or ops.SECTION_ROBOTS in sections:
            found = found_appliances(hass, store.data)
            if found != store.appliance_found:
                async_report_found(hass, store.appliance_found, found)
                store.appliance_found = found
                store.async_notify(("appliance_found", "appliance_again", "pool_found", "robot_found", "ignored_found"))
        if ops.SECTION_APPLIANCES in sections or ops.SECTION_POOLS in sections or ops.SECTION_ROBOTS in sections:
            store.recordings.sync(store.data)  # (an appliance, pool or vacuum edited or removed)

    entry.async_on_unload(store.async_add_listener(appliances_changed))

    @callback
    def areas_changed(sections: tuple[str, ...]) -> None:
        # an area shown for the first time gets its defaults then
        if started and ops.SECTION_AREAS in sections:
            filled = fill_defaults(hass, store.data, found_appliances(hass, store.data))
            if filled:
                store.async_changed(tuple(sorted(filled)))

    entry.async_on_unload(store.async_add_listener(areas_changed))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_register_panel(hass)  # the sidebar entry, while set up
    # now if HA is already running (integration reload), else once it is
    entry.async_on_unload(async_at_started(hass, ha_started))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RoomTilesConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    store = entry.runtime_data
    await store.async_save_now()
    await store.recordings.async_unload()
    store.async_unloaded()
    async_remove_panel(hass)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: RoomTilesConfigEntry) -> None:
    """Room Tiles REMOVED: its data goes (a copy is kept in
    room_tiles_backups/ - removing it by mistake can be undone), and so do its
    repairs. HA deletes its entities (and their voice-assistant settings).
    Adding it again starts fresh, like a new install."""
    import shutil
    from datetime import datetime

    from homeassistant.helpers.storage import Store

    src = Path(hass.config.path(".storage", STORAGE_KEY))
    if src.is_file():
        dest = Path(hass.config.path(BACKUP_DIR)) / f"removed-{datetime.now():%Y%m%d-%H%M%S}.json"

        def copy() -> None:
            from .backups import prune

            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            prune(dest.parent)

        await hass.async_add_executor_job(copy)
        await Store(hass, STORAGE_VERSION, STORAGE_KEY).async_remove()
    await Store(hass, 1, FW_TRIES_KEY).async_remove()
    await Store(hass, 1, RECORDINGS_KEY).async_remove()
    from homeassistant.components import persistent_notification

    persistent_notification.async_dismiss(hass, FOUND_NOTIFICATION)
    persistent_notification.async_dismiss(hass, REVIEW_NOTIFICATION)
    issues = ir.async_get(hass)
    for domain, issue_id in list(issues.issues):
        if domain == DOMAIN:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


def _disabled_entities(hass: HomeAssistant, data) -> list[str]:
    """Entities Room Tiles uses that are disabled in HA's entity registry."""
    reg = er.async_get(hass)
    return sorted(
        e for e in ops.referenced_entities(data) if (entry := reg.async_get(e)) is not None and entry.disabled_by
    )
