"""Areas the user hid on their HA dashboards (the Areas dashboard's
`areas_display.hidden`, the overview strategy's `areas.hidden`). HA areas
themselves can't be hidden; first-time setup starts these unticked - hidden
in Room Tiles. After that Room Tiles' own Hidden (the area editor) is
independent of HA's dashboards.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant


def hidden_in(config: Any) -> set[str]:
    """The area ids a dashboard config hides (pure)."""
    out: set[str] = set()
    strategy = (config or {}).get("strategy") if isinstance(config, dict) else None
    if isinstance(strategy, dict):
        for key in ("areas_display", "areas"):
            hidden = (strategy.get(key) or {}).get("hidden") if isinstance(strategy.get(key), dict) else None
            if isinstance(hidden, list):
                out.update(h for h in hidden if isinstance(h, str))
    return out


async def dashboard_hidden_areas(hass: HomeAssistant) -> set[str]:
    """Every area hidden on any of the user's dashboards (none: empty)."""
    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA

        dashboards = hass.data[LOVELACE_DATA].dashboards
    except Exception:  # noqa: BLE001 - no dashboards loaded (tests, recovery)
        return set()
    out: set[str] = set()
    for dash in list(dashboards.values()):
        try:
            out |= hidden_in(await dash.async_load(False))
        except Exception:  # noqa: BLE001 - an auto / missing dashboard
            continue
    return out
