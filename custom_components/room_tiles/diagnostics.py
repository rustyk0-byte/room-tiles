"""Home Assistant's "Download diagnostics" for Room Tiles (Settings ›
Devices & services › Room Tiles › ⋮ › Download diagnostics).

The setup's SHAPE, for a bug report - versions; each area's settings and its
boards' tile kinds; how many maps, walls, rooms and markers; the panels
(board, firmware, layout, theme, language); the appliances', pools' and
robots' presets; what's beta; the recordings' status. Never a name, an
entity id or a device id (DESIGN.md "Privacy: what reports send"): areas
are area_1, area_2... in their order, floors floor_1..., appliances,
pools and robots appliance_1, pool_1, robot_1...
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant

from .const import DEV_BUILD, PAYLOAD_SCHEMA


class _Names:
    """Stand-ins: the same id always gets the same "<prefix>_<n>"."""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.seen: dict[str, str] = {}

    def __call__(self, value: str | None) -> str | None:
        if not value:
            return None
        if value not in self.seen:
            self.seen[value] = f"{self.prefix}_{len(self.seen) + 1}"
        return self.seen[value]


def _kind_of(entity: str | None) -> str | None:
    """An entity as its domain only (light, switch...)."""
    return entity.split(".", 1)[0] if entity and "." in entity else None


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    from .model_report import beta_units
    from .panels import PANEL_SCHEMA
    from .store import VERSION
    from .update import firmware_rows

    store = entry.runtime_data
    data = store.data
    area, floor = _Names("area"), _Names("floor")
    ids = {"appliance": _Names("appliance"), "pool": _Names("pool"), "robot": _Names("robot")}
    for a in data.areas:
        area(a.id)
    areas = []
    for a in data.areas:
        areas.append({
            "area": area(a.id),
            "floor": floor(a.floor),
            "hidden": a.hidden,
            "layout": a.layout,
            # its lights button: the user's own entity, every light in it, or none
            "lights": "override" if a.lights else "all" if a.light_entity else "none",
            "lights_excluded": len(a.lights_exclude),
            "short_name": bool(a.short_name),
            "filled": a.filled,
            "tiles": {
                layout: [t.kind if t else None for t in grid] for layout, grid in sorted(a.tiles.items())
            },
        })
    maps = [
        {
            "walls": len(m.walls),
            "windows": len(m.windows),
            "openings": len(m.openings),
            "rooms": len(m.shapes),
            "zones": len(m.zones),
            "links": len(m.links),
            "layers": len(m.layers),
            "generated": m.generated,
            "on_a_floor": bool(m.ha_floor),
        }
        for m in data.maps
    ]
    markers = Counter(str(_kind_of(mk.entity)) for mk in data.markers)
    appliances = [
        {
            "appliance": ids["appliance"](a.id),
            "units": [
                {
                    "appliance": u.appliance,
                    "preset": u.preset,
                    "time": bool(u.time),
                    "door": bool(u.door),
                    "door_clears": u.door_clears,
                    "finished": u.finished,
                    "drawer": u.drawer,
                    "answers": len(u.overrides),  # (the user's own answers for unknown states)
                    "clears": len(u.clear),
                }
                for u in a.units
            ],
        }
        for a in data.appliances
    ]
    pools = [
        {
            "pool": ids["pool"](p.id),
            "preset": p.preset,
            "layout": p.layout,
            "pool_body": p.pool is not None,
            "spa_body": p.spa is not None,
            "spa_mode": bool(p.spa_mode),
            "pump": bool(p.pump),
            "spa_heater_follows": p.spa_heater_follows,
        }
        for p in data.pools
    ]
    robots = [{"robot": ids["robot"](r.id), "preset": r.preset, "error": bool(r.error)} for r in data.robots]
    own = {p.id: p for p in data.panels}
    panels = []
    for row in firmware_rows(hass, store)["panels"]:
        p = own.get(row["device_id"])
        panels.append({
            "board": row["board"],
            "firmware": row["running"],
            "latest": row["latest"],
            "status": row["status"],
            "auto_update": row["auto"],
            "area_set": bool(p and p.area),
            "layout": p.layout if p else None,
            "theme": p.theme if p else None,
            "language": p.language if p else None,
        })

    def subject(key: str) -> str:
        kind, _, sid = key.partition(":")
        return ids[kind](sid) if kind in ids else kind

    return {
        "versions": {
            "room_tiles": VERSION,
            "home_assistant": HA_VERSION,
            "panel_schema": PANEL_SCHEMA,
            "payload_schema": PAYLOAD_SCHEMA,
            "dev_build": DEV_BUILD,
        },
        "settings": {
            "auto_add_areas": data.settings.auto_add_areas,
            "auto_update_panels": data.settings.auto_update_panels,
        },
        "areas": areas,
        "maps": maps,
        "markers": dict(sorted(markers.items())),
        "catalog": dict(sorted(Counter(c.kind for c in data.catalog.entries).items())),
        "catalog_review": sum(1 for c in data.catalog.entries if c.review),
        "appliances": appliances,
        "pools": pools,
        "robots": robots,
        "beta": {subject(k): len(v) for k, v in beta_units(hass, data).items()},  # (its beta units: how many)
        "recordings": {subject(k): r.get("status") for k, r in (store.recordings.doc or {}).items()},
        "panels": panels,
        "firmware_images": [{"board": b, "label": i.label} for b, i in sorted(store.fw_images.items())],
        "ignored_found": len(data.ignored),
        "disabled_entities": len(store.disabled),
        "restart_needed": store.restart_needed,
    }
