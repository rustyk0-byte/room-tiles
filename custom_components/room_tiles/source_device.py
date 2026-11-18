"""Room Tiles' own tile sensors (appliances, pool / spa, robot vacuums) sit
on the device of the entities they're made from - the way HA's helper
sensors do (`device_entry`, HA 2025.8+). So they show on that device's page
and take its AREA (and follow it when the device moves) - the dashboard's
area filters find them there. An area set on the sensor itself still wins.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device import async_entity_id_to_device


def appliance_source(ap: Any) -> str | None:
    """The first unit's state entity (a washer + dryer tile: the first unit)."""
    return ap.units[0].status if ap.units else None


def pool_source(ps: Any, body: str | None) -> str | None:
    """The body's own equipment, else the system's (combined tile: the pool's)."""
    b = getattr(ps, body) if body else (ps.pool or ps.spa)
    for ent in (*((b.heater, b.temp, b.pump) if b else ()), ps.pump, ps.spa_mode):
        if ent:
            return ent
    return None


def robot_source(rb: Any) -> str | None:
    return rb.vacuum


@callback
def link(hass: HomeAssistant, entity: Any, source: str | None) -> None:
    """Put `entity` on `source`'s device (none: no device). Before the entity
    is added this just sets `device_entry`; once registered, the registry
    entry is moved when the source's device changed (profile edited)."""
    device = async_entity_id_to_device(hass, source) if source else None
    entity.device_entry = device
    if not entity.entity_id:
        return
    reg = er.async_get(hass)
    entry = reg.async_get(entity.entity_id)
    want = device.id if device else None
    if entry is not None and entry.device_id != want:
        reg.async_update_entity(entity.entity_id, device_id=want)
