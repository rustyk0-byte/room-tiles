"""Find robot vacuums among HA's entities - what setup offers to add.

Pure (tested in tests/test_robot_detect.py). EVERY vacuum entity is offered
(any brand: the tile needs only HA's vacuum states); Matter robots also get
their operational-error sensor for alerts. Setup says what each one can do:
room cleaning needs HA's `clean_area` (the vacuum's supported features).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .appliance_detect import Dev
from .robot import CLEAN_AREA
from .wording import w as _w_note

@dataclass(frozen=True)
class Vac:
    entity_id: str
    platform: str
    device_id: str | None
    supported_features: int
    name: str


def find_robots(
    vacs: list[Vac], errors: dict[str, str], devs: dict[str, Dev], known: set[str], taken_ids: set[str]
) -> list[dict[str, Any]]:
    """`errors`: device id -> its Matter RVC operational-error sensor.
    `known`: vacuum entities already set up."""
    out = []
    taken = set(taken_ids)
    for v in vacs:
        if v.entity_id in known:
            continue
        dev = devs.get(v.device_id or "")
        error = errors.get(v.device_id or "")
        name = (dev.name if dev and dev.name else "") or v.name or "Robot vacuum"
        base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "vacuum"
        rid, n = base, 1
        while rid in taken:
            n += 1
            rid = f"{base}_{n}"
        taken.add(rid)
        # (words: each dashboard says them in its own language)
        notes = [_w_note("setup_note.rooms_yes" if v.supported_features & CLEAN_AREA else "setup_note.rooms_no")]
        if error:
            notes.append(_w_note("setup_note.alerts"))
        out.append(
            {
                "id": rid,
                "name": name,
                "vacuum": v.entity_id,
                "error": error,
                "preset": "matter" if error else "vacuum",
                "clean_area": bool(v.supported_features & CLEAN_AREA),
                "notes": notes,
            }
        )
    return out
