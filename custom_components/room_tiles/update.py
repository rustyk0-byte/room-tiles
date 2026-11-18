"""Room Tiles firmware updates for its panels (firmware.py): one update entity
per panel, on the panel's own device. It offers the newest image for the
panel's board; Install asks the panel (its next payload names the build) and
the panel downloads, checks and installs it, then restarts - done once it
reports running that build. With "Update panels automatically" (Room Tiles'
settings, on by default) the panels do this by themselves when nobody's
using them (store.firmware_auto); the entity then shows it in progress.

Only generic panels (the installer's images) are updated this way; a
hand-built panel holds its own name and key in its image and is updated with
ESPHome - its entity shows what it runs and offers nothing.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .panels import find_panels


def running_label(running: Any, image: Any) -> str | None:
    """The version a panel runs: the image's label when it runs that very
    build (the image knows its release; older firmware doesn't say), else
    what the panel reports."""
    if running is None:
        return None
    return image.label if image is not None and image.build == running.build else running.label


def firmware_rows(hass: HomeAssistant, store: Any) -> dict[str, Any]:
    """The dashboard's Panels page (the feed's "panel_firmware"): each panel -
    its name, area, board, what it runs, the newest image for its board,
    its update entity and where it stands - and the images Room Tiles has."""
    ents = er.async_get(hass)
    areas = ar.async_get(hass)
    rows = []
    for dev in find_panels(hass).values():
        running = store.fw_reports.get(dev.device_id)
        image = store.fw_images.get(running.board) if running is not None else None
        if running is None:
            status = "unknown"  # (not heard from since HA started)
        elif not running.generic:
            status = "hand_built"
        elif dev.device_id in store.fw_install:
            status = "updating"
        elif image is not None and image.build != running.build:
            status = "available"
        else:
            status = "current"
        area = areas.async_get_area(dev.area_id) if dev.area_id else None
        rows.append(
            {
                "device_id": dev.device_id,
                "name": dev.name,
                "area": area.name if area else None,
                "board": running.board if running else None,
                "running": running_label(running, image),
                "latest": image.label if image is not None else None,
                "entity_id": ents.async_get_entity_id("update", DOMAIN, f"{dev.device_id}_firmware"),
                "status": status,
                "auto": dev.device_id in store.fw_auto,
            }
        )
    rows.sort(key=lambda r: (r["name"] or "").lower())
    images = [{"board": b, "label": i.label} for b, i in sorted(store.fw_images.items())]
    return {"panels": rows, "images": images}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    store = entry.runtime_data
    live: dict[str, PanelFirmwareUpdate] = {}

    # Room Tiles makes no devices of its own (its entities join existing ones;
    # a device belongs to one config entry): one on its entry is left over
    reg = dr.async_get(hass)
    for stale in dr.async_entries_for_config_entry(reg, entry.entry_id):
        reg.async_remove_device(stale.id)

    @callback
    def sync(_sections: tuple[str, ...] | None = None) -> None:
        """An entity for every panel HA knows (new panels too)."""
        reg = dr.async_get(hass)
        new = []
        for dev in find_panels(hass).values():
            if dev.device_id in live or (device := reg.async_get(dev.device_id)) is None:
                continue
            ent = live[dev.device_id] = PanelFirmwareUpdate(store, dev.device_id, device)
            new.append(ent)
        if new:
            async_add_entities(new)

    sync()
    entry.async_on_unload(store.async_add_listener(sync))


class PanelFirmwareUpdate(UpdateEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "firmware"
    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS

    def __init__(self, store: Any, device_id: str, device: dr.DeviceEntry) -> None:
        self._store = store
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_firmware"
        # on the panel's own (ESPHome) device, so it carries the panel's name and
        # area - device info would make a second device (HA scopes devices by entry)
        self.device_entry = device

    async def async_added_to_hass(self) -> None:
        self._store.fw_listeners.append(self._changed)

        def remove() -> None:
            if self._changed in self._store.fw_listeners:
                self._store.fw_listeners.remove(self._changed)

        self.async_on_remove(remove)

    @callback
    def _changed(self) -> None:
        self.async_write_ha_state()

    @property
    def _running(self) -> Any:
        return self._store.fw_reports.get(self._device_id)

    @property
    def _image(self) -> Any:
        running = self._running
        if running is None or not running.generic:
            return None
        return self._store.fw_images.get(running.board)

    @property
    def available(self) -> bool:
        return self._running is not None  # (firmware too old to report: nothing to say)

    @property
    def installed_version(self) -> str | None:
        running = self._running
        return running_label(running, self._store.fw_images.get(running.board) if running is not None else None)

    @property
    def latest_version(self) -> str | None:
        image = self._image
        return image.label if image is not None else self.installed_version

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        """An update is there when the image isn't the build the panel runs
        (the versions are labels: a release, or a build time and id)."""
        image, running = self._image, self._running
        return image is not None and running is not None and image.build != running.build

    @property
    def release_summary(self) -> str | None:
        running = self._running
        if running is not None and not running.generic:
            return "Built by hand: update it with ESPHome."
        return None

    @property
    def in_progress(self) -> bool:
        return self._device_id in self._store.fw_install

    @property
    def auto_update(self) -> bool:
        return self._store.data.settings.auto_update_panels

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        image = self._image
        running = self._running
        if image is None or running is None or image.build == running.build:
            return
        # the panel's next payload names the build; it installs and restarts
        self._store.firmware_install(self._device_id, image.build)


UPLOAD_URL = "/api/room_tiles/firmware"


class FirmwareUploadView(HomeAssistantView):
    """POST a panel firmware image (the dashboard's Panels page, Upload; the
    file as the body) - an admin's. Kept as its board's image in the upload
    folder (firmware.store_image); the panels on that board are offered it."""

    url = UPLOAD_URL
    name = "api:room_tiles:firmware"
    requires_auth = True

    def __init__(self, store_of: Any) -> None:
        self._store_of = store_of

    async def post(self, request: web.Request) -> web.Response:
        from . import firmware as fw
        from .panels import PANEL_SCHEMA

        if not request["hass_user"].is_admin:
            return web.json_response({"ok": False, "error": "admin"}, status=403)
        store = self._store_of()
        if store is None or store.fw_upload_dir is None:
            return web.json_response({"ok": False, "error": "not_set_up"}, status=503)
        data = await request.read()
        if not data or len(data) > fw.MAX_IMAGE:
            return web.json_response({"ok": False, "error": "not_firmware"})
        hass: HomeAssistant = request.app["hass"]
        uploaded = await hass.async_add_executor_job(fw.parse_image, data, store.fw_upload_dir / "upload.bin")
        kept = await hass.async_add_executor_job(fw.store_image, store.fw_upload_dir, data, PANEL_SCHEMA)
        if isinstance(kept, str):
            return web.json_response({"ok": False, "error": kept})
        if uploaded is not None and kept.build != uploaded.build:
            return web.json_response({"ok": False, "error": "older", "board": kept.board, "label": kept.label})
        if store.fw_rescan is not None:
            await store.fw_rescan()
        return web.json_response({"ok": True, "board": kept.board, "label": kept.label})
