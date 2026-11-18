"""Which HA areas each vacuum can clean.

HA maps a vacuum's own segments (rooms in its app) to HA areas ("Map vacuum
segments to areas" on the vacuum entity), and `vacuum.clean_area` takes those
area ids. Room Tiles reads that mapping - it is never entered twice - so a map
room whose area is mapped is cleanable by that vacuum, and a vacuum zone
(model.Zone.vacuum) adds pieces like "Bar" that are their own area only for
the vacuum.

The mapping is stored by HA in the vacuum's entity-registry options
(`options["vacuum"]["area_mapping"]`: area id -> segment ids); read
defensively, it's HA's own data.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


def vacuum_areas(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """entity id -> {"name", "areas": [area ids with mapped segments],
    "unmapped": a room it reports isn't mapped}, for every vacuum that has a
    segment-to-area mapping."""
    out: dict[str, dict[str, Any]] = {}
    for entry in er.async_get(hass).entities.values():
        if entry.domain != "vacuum" or entry.disabled_by:
            continue
        opts = entry.options.get("vacuum") or {}
        mapping = opts.get("area_mapping") if isinstance(opts, dict) else None
        if not isinstance(mapping, dict):
            continue
        areas = sorted(a for a, segs in mapping.items() if isinstance(a, str) and segs)
        if not areas:
            continue
        # a room the vacuum reports (HA's `last_seen_segments`) that isn't
        # mapped to an area: it can't be cleaned from Room Tiles
        mapped = {str(seg) for segs in mapping.values() if isinstance(segs, list) for seg in segs}
        seen = opts.get("last_seen_segments")
        unmapped = isinstance(seen, list) and any(
            isinstance(seg, dict) and seg.get("id") is not None and str(seg["id"]) not in mapped for seg in seen
        )
        state = hass.states.get(entry.entity_id)
        name = (state.name if state else None) or entry.name or entry.original_name or entry.entity_id
        out[entry.entity_id] = {"name": name, "areas": areas, "unmapped": unmapped}
    return out
