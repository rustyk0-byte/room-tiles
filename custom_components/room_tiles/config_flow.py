"""Config flow for Room Tiles: pick which HA areas appear."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.selector import AreaSelector, AreaSelectorConfig, BooleanSelector

from .const import DOMAIN
from .dashboards import dashboard_hidden_areas
from .appliances_ha import found_appliances
from .frontend import PANEL_URL_PATH
from .model import RoomTilesData


class RoomTilesConfigFlow(ConfigFlow, domain=DOMAIN):
    """One Room Tiles entry per HA (single_config_entry in the manifest).

    The choices are stored in entry.data and applied once, when Room Tiles
    has no areas yet; afterwards areas are shown / hidden / reordered in the
    Room Tiles dashboard."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            areas = list(user_input.get("areas") or [])
            # the closing message: what was made and a link straight into the
            # dashboard (create_entry.default), plus a line when supported
            # appliances were found (create_entry.found)
            found = found_appliances(self.hass, RoomTilesData())
            any_found = bool(found.get("found") or found.get("pools") or found.get("robots"))
            return self.async_create_entry(
                title="Room Tiles",
                data={"areas": areas, "auto_add_areas": bool(user_input.get("auto_add_areas", False))},
                description="found" if any_found else None,
                description_placeholders={"areas": str(len(areas)), "url": f"/{PANEL_URL_PATH}"},
            )
        # every area, except those hidden on the user's dashboards
        hidden = await dashboard_hidden_areas(self.hass)
        all_areas = [a.id for a in ar.async_get(self.hass).async_list_areas() if a.id not in hidden]
        schema = vol.Schema(
            {
                vol.Required("areas", default=all_areas): AreaSelector(
                    AreaSelectorConfig(multiple=True)
                ),
                vol.Required("auto_add_areas", default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)
