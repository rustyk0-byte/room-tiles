"""The Room Tiles sidebar panel (the dashboard's JavaScript bundle).

The bundle is built from frontend/ (TypeScript + Lit) into
custom_components/room_tiles/frontend/room-tiles-panel.js - by CI, and for
releases into the release zip. Registered only when HA's frontend is
running (tests run without it).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PANEL_URL_PATH = "room-tiles"
STATIC_URL = f"/{DOMAIN}_frontend"
BUNDLE = Path(__file__).parent / "frontend" / "room-tiles-panel.js"


def _bundle_version() -> str | None:
    if not BUNDLE.is_file():
        return None
    return hashlib.sha256(BUNDLE.read_bytes()).hexdigest()[:12]


async def async_register_panel(hass: HomeAssistant) -> None:
    if "frontend" not in hass.config.components:
        return
    version = await hass.async_add_executor_job(_bundle_version)
    if version is None:
        _LOGGER.warning(
            "Room Tiles dashboard bundle missing (%s) - the sidebar panel is not available",
            BUNDLE,
        )
        return
    # the files once per HA run (a static path can't be registered twice);
    # the sidebar panel each time Room Tiles is set up
    if not hass.data.get(f"{DOMAIN}_static"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(BUNDLE.parent), cache_headers=False)]
        )
        hass.data[f"{DOMAIN}_static"] = True
    # imported here: panel_custom is only an after-dependency
    from homeassistant.components import panel_custom

    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name="room-tiles-panel",
        sidebar_title="Room Tiles",
        sidebar_icon="mdi:view-grid-outline",
        module_url=f"{STATIC_URL}/{BUNDLE.name}?v={version}",
        require_admin=False,
        config={},
    )


def async_remove_panel(hass: HomeAssistant) -> None:
    """Room Tiles unloaded / removed: out of the sidebar."""
    from homeassistant.components import frontend

    if PANEL_URL_PATH in hass.data.get("frontend_panels", {}):
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
