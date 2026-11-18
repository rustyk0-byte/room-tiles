"""HA side of appliance setup: describe the registries for the finder
(appliance_detect.py), which stays pure."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .appliance_detect import Dev, Ent, find_appliances, redetect
from .pool_detect import find_pools
from .robot_detect import Vac, find_robots
from .model import RoomTilesData

# the finders' integrations
PLATFORMS = frozenset(
    {
        "lg_thinq",
        "ge_home",
        "smartthings",
        "whirlpool",
        "home_connect",
        "miele",
        "matter",
        "iaqualink",
        "screenlogic",
        "omnilogic",
    }
)


def found_appliances(hass: HomeAssistant, data: RoomTilesData) -> dict[str, Any]:
    """Everything found and not set up, split into offered and IGNORED (the
    user's Ignore; they wait at the bottom of the Appliances page)."""
    from .ops import device_keys

    found = _found(hass, data)
    ignored = set(data.ignored)

    def split(items: list[dict[str, Any]], kind: str) -> tuple[list, list]:
        keep, skip = [], []
        for it in items:
            keys = device_keys(kind, it)
            (skip if keys and all(k in ignored for k in keys) else keep).append(it)
        return keep, skip

    found["found"], found["found_ignored"] = split(found["found"], "appliance")
    found["pools"], found["pools_ignored"] = split(found["pools"], "pool")
    found["robots"], found["robots_ignored"] = split(found["robots"], "robot")
    return found


def _found(hass: HomeAssistant, data: RoomTilesData) -> dict[str, Any]:
    """`found`: supported appliances in HA not set up in Room Tiles yet;
    `again`: appliance id -> a fresh setup of its hardware (Set up again);
    `pools`: pool / spa systems not set up yet; `robots`: vacuums not set up yet."""
    ents = [
        Ent(e.entity_id, e.platform, e.unique_id, e.translation_key, e.device_id, e.original_name)
        for e in er.async_get(hass).entities.values()
        if e.platform in PLATFORMS and not e.disabled_by
    ]
    robots = _robots(hass, data)
    if not ents:
        return {"found": [], "again": {}, "pools": [], "robots": robots}
    dev_reg = dr.async_get(hass)
    devs: dict[str, Dev] = {}
    for dev_id in {e.device_id for e in ents if e.device_id}:
        if (d := dev_reg.async_get(dev_id)) is not None:
            devs[dev_id] = Dev(d.id, d.name_by_user or d.name or "", d.manufacturer or "", d.model or "")
    known = {u.status for a in data.appliances for u in a.units}
    return {
        "found": find_appliances(
            ents,
            devs,
            known,
            {a.id for a in data.appliances},
            [a.id for a in data.appliances if len(a.units) == 1 and a.units[0].appliance == "dryer"],
        ),
        "again": redetect(ents, devs, [a.as_dict() for a in data.appliances]),
        "pools": find_pools(
            ents,
            devs,
            {b.temp or b.heater for p in data.pools for b in (p.pool, p.spa) if b and (b.temp or b.heater)},
            {p.id for p in data.pools},
        ),
        "robots": robots,
    }


def _robots(hass: HomeAssistant, data: RoomTilesData) -> list[dict[str, Any]]:
    """Every vacuum in HA (any brand) not set up yet; Matter ones with their
    operational-error sensor."""
    reg = er.async_get(hass)
    vac_entries = [e for e in reg.entities.values() if e.domain == "vacuum" and not e.disabled_by]
    if not vac_entries:
        return []
    dev_reg = dr.async_get(hass)
    devs: dict[str, Dev] = {}
    errors: dict[str, str] = {}
    for e in vac_entries:
        if e.device_id and (d := dev_reg.async_get(e.device_id)) is not None:
            devs[e.device_id] = Dev(d.id, d.name_by_user or d.name or "", d.manufacturer or "", d.model or "")
    wanted = {e.device_id for e in vac_entries if e.device_id}
    for x in reg.entities.values():
        if x.device_id in wanted and x.domain == "sensor" and x.translation_key == "operational_error" and not x.disabled_by:
            errors[x.device_id] = x.entity_id
    vacs = [
        Vac(e.entity_id, e.platform, e.device_id, int(e.supported_features or 0), e.name or e.original_name or "")
        for e in vac_entries
    ]
    return find_robots(vacs, errors, devs, {r.vacuum for r in data.robots}, {r.id for r in data.robots})
