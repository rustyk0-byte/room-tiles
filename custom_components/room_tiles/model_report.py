"""Report how it went: a model report (DESIGN.md "Privacy: what reports
send" > Model reports; docs/SUPPORTED.md "Help confirm a beta model").

A beta device - a model (or a pool setup) not confirmed on real hardware -
has "Report how it went" on its card: how it went overall (works / partly /
doesn't work), each feature of its kind as works / partly / broken / not
tried (SUPPORTED.md's "Features by model" rows), the user's own words, and -
with their OK - what it did over a recent cycle, pump run or clean (the
same data as Report a problem: cycles.py). A maintainer moves a confirmed
model to "Confirmed models" from it.
"""

from __future__ import annotations

from typing import Any

from .appliance import confirmed
from .appliance_presets import PRESETS

ANSWERS = ("works", "partly", "broken", "not_tried")

# what to check, by Room Tiles' own kind of device (SUPPORTED.md "Features
# by model" / "Features by setup" - a row there is a feature here)
_APPLIANCE = ("running", "status_text", "time_left", "paused", "error", "door")
FEATURES: dict[str, tuple[str, ...]] = {
    "washer": _APPLIANCE,
    "dryer": _APPLIANCE,
    "dishwasher": _APPLIANCE,
    "pool": ("water_temp", "target", "heater", "chill", "spa_mode", "pump", "time_to_target", "switching"),
    "vacuum": ("tile", "clean_rooms", "queue", "zones", "alerts", "interrupted"),
}

# confirmed on real hardware (SUPPORTED.md "Confirmed models" / "Confirmed
# setups"): a robot vacuum by its preset and device model, a pool system by
# its preset and layout (its devices have no model) - nothing else is
# confirmed yet; anything not listed is beta
CONFIRMED_ROBOTS: dict[str, tuple[str, ...]] = {"matter": ("Matic",)}
CONFIRMED_POOLS: dict[str, tuple[str, ...]] = {}


def features(data: Any, kind: str, sid: str, unit: str = "") -> list[str]:
    """The features to check for one appliance unit, pool or vacuum."""
    if kind == "appliance":
        a = next((x for x in data.appliances if x.id == sid), None)
        u = next((x for x in a.units if x.id == unit), None) if a else None
        if u is None:
            return []
        out = list(FEATURES.get(u.appliance, _APPLIANCE))
        if {x.appliance for x in a.units} == {"washer", "dryer"}:
            out.append("laundry_pair")  # (a washer and a dryer on one tile)
        return out
    if kind == "pool":
        p = next((x for x in data.pools if x.id == sid), None)
        if p is None:
            return []
        out = list(FEATURES["pool"])
        if p.layout == "pool":
            out.remove("spa_mode")  # (no spa)
        return out
    if kind == "robot":
        return list(FEATURES["vacuum"]) if any(r.id == sid for r in data.robots) else []
    return []


def _model(hass: Any, entity_id: str | None) -> str:
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    ent = er.async_get(hass).async_get(entity_id) if entity_id else None
    dev = dr.async_get(hass).async_get(ent.device_id) if ent and ent.device_id else None
    return (dev.model or "") if dev else ""


def beta_units(hass: Any, data: Any) -> dict[str, list[str]]:
    """What is beta here: "<kind>:<id>" -> its beta units ("" for a pool or
    a vacuum). Not listed: confirmed."""
    out: dict[str, list[str]] = {}
    for a in data.appliances:
        units = [
            u.id for u in a.units if u.preset not in PRESETS or not confirmed(PRESETS[u.preset], _model(hass, u.status))
        ]
        if units:
            out[f"appliance:{a.id}"] = units
    for p in data.pools:
        if p.layout not in CONFIRMED_POOLS.get(p.preset, ()):
            out[f"pool:{p.id}"] = [""]
    for r in data.robots:
        model = _model(hass, r.vacuum).upper()
        if not model or not any(c.upper() in model for c in CONFIRMED_ROBOTS.get(r.preset, ())):
            out[f"robot:{r.id}"] = [""]
    return out


def model_draft(feats: list[str], outcome: str, checklist: dict[str, Any], description: str) -> dict[str, Any]:
    """A model report's own part (before scrubbing): how it went, each
    feature's answer (only this kind's features, only known answers - "not
    tried" when none), the user's words."""
    draft: dict[str, Any] = {
        "outcome": outcome,
        "checklist": {f: (checklist.get(f) if checklist.get(f) in ANSWERS else "not_tried") for f in feats},
    }
    if description.strip():
        draft["description"] = description
    return draft
