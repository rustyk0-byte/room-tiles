"""Storage migrations. Each step takes the raw stored document (a dict) of one
version and returns the next. Pure Python, so it's tested without HA."""

from __future__ import annotations

from typing import Any

from .const import MAX_SHORT_NAME
from .shortnames import suggest


def migrate_1_1_to_1_2(doc: dict[str, Any]) -> dict[str, Any]:
    """1.1 -> 1.2 (2026-11-07): short names.
    - catalog entries: `name` becomes `short_name` (suggested; review if
      shortened)
    - areas: `ha_area` dropped (an area IS an HA area now); `short_name`
      filled in if missing
    - tiles: a name equal to its entity's old catalog name, or longer than a
      short name may be, is dropped (the tile shows the entity's short name)
    """
    doc = dict(doc)
    catalog = dict(doc.get("catalog") or {})
    old_names: dict[str, str] = {}
    entries = []
    for e in catalog.get("entries") or []:
        e = dict(e)
        old = e.pop("name", None)
        if old is not None:
            old_names[e.get("entity", "")] = old
        if not e.get("short_name"):
            e["short_name"], e["review"] = suggest(old or e.get("entity", "?"))
        entries.append(e)
    catalog["entries"] = entries
    doc["catalog"] = catalog

    areas = []
    for a in doc.get("areas") or []:
        a = dict(a)
        a.pop("ha_area", None)
        if not a.get("short_name"):
            a["short_name"], a["review"] = suggest(a.get("name") or a.get("id", "?"))
        tiles = {}
        for layout, grid in (a.get("tiles") or {}).items():
            out = []
            for t in grid:
                if t is not None:
                    t = dict(t)
                    name = (t.get("name") or "").strip()
                    if (
                        not name
                        or len(name) > MAX_SHORT_NAME
                        or name == old_names.get(t.get("entity") or "")
                        or t.get("kind") == "map"
                    ):
                        t.pop("name", None)
                out.append(t)
            tiles[layout] = out
        a["tiles"] = tiles
        areas.append(a)
    doc["areas"] = areas
    return doc


def migrate_1_2_to_1_3(doc: dict[str, Any]) -> dict[str, Any]:
    """1.2 -> 1.3 (2026-11-07): areas gain `lights_exclude` (additive - the
    model defaults it to empty; nothing to convert)."""
    return doc


def migrate_1_3_to_1_4(doc: dict[str, Any]) -> dict[str, Any]:
    """1.3 -> 1.4 (2026-11-07): marker layers. Maps get the default layers
    (House from 1x, Rooms from 1.7x); a marker's `detail` flag becomes its
    layer (True -> rooms, else house)."""
    doc = dict(doc)
    maps = []
    for m in doc.get("maps") or []:
        m = dict(m)
        m.setdefault("layers", [
            {"id": "house", "name": "House", "min_zoom": 1.0},
            {"id": "rooms", "name": "Rooms", "min_zoom": 1.7},
        ])
        maps.append(m)
    doc["maps"] = maps
    markers = []
    for mk in doc.get("markers") or []:
        mk = dict(mk)
        detail = mk.pop("detail", False)
        mk.setdefault("layer", "rooms" if detail else "house")
        markers.append(mk)
    doc["markers"] = markers
    return doc


def migrate_1_4_to_1_5(doc: dict[str, Any]) -> dict[str, Any]:
    """1.4 -> 1.5 (2026-11-07): no more "tap group" logic - a marker always
    controls its own entity; markers and catalog entries lose `group`."""
    doc = dict(doc)
    doc["markers"] = [{k: v for k, v in mk.items() if k != "group"} for mk in doc.get("markers") or []]
    cat = dict(doc.get("catalog") or {})
    cat["entries"] = [{k: v for k, v in e.items() if k != "group"} for e in cat.get("entries") or []]
    doc["catalog"] = cat
    return doc


# (major, minor) of the stored data -> step to the next minor version
def migrate_1_5_to_1_6(doc: dict[str, Any]) -> dict[str, Any]:
    """1.5 -> 1.6 (2026-11-08): zones get an optional `vacuum` (vacuum zones)
    and `label_vertical`.
    Additive - nothing to convert; older Room Tiles ignores the field (and
    would draw a vacuum zone as an ordinary room)."""
    return doc


def migrate_1_6_to_1_7(doc: dict[str, Any]) -> dict[str, Any]:
    """1.6 -> 1.7 (2026-11-09): `appliances` and `pools` - appliance and pool /
    spa profiles (Room Tiles' own sensors for those tiles). Additive - older
    Room Tiles ignores them (those tiles' sensors just go unavailable)."""
    return doc


def migrate_1_7_to_1_8(doc: dict[str, Any]) -> dict[str, Any]:
    """1.7 -> 1.8 (2026-11-10): a tile no longer has its own name - every
    tile shows its entity's short name (one name per thing, changed in one
    place). Tiles' own names are dropped."""
    for a in doc.get("areas") or []:
        for grid in (a.get("tiles") or {}).values():
            for t in grid:
                if isinstance(t, dict) and t.get("entity"):
                    t.pop("name", None)
    return doc


def migrate_1_8_to_1_9(doc: dict[str, Any]) -> dict[str, Any]:
    """1.8 -> 1.9 (2026-11-11): a layer shows from its min_zoom to its own
    max_zoom (none: no end), several at once - before, one at a time, each
    up to where the next started. Each layer but the last gets that as its
    end, so maps look as they did."""
    for m in doc.get("maps") or []:
        layers = sorted(m.get("layers") or [], key=lambda lay: float(lay.get("min_zoom", 1.0)))
        for k, lay in enumerate(layers):
            nxt = layers[k + 1] if k + 1 < len(layers) else None
            lay["max_zoom"] = float(nxt["min_zoom"]) if nxt and float(nxt["min_zoom"]) > float(lay.get("min_zoom", 1.0)) else None
    return doc


def migrate_1_9_to_1_10(doc: dict[str, Any]) -> dict[str, Any]:
    """1.9 -> 1.10 (2026-11-11): an area remembers which boards the user
    changed (`edited`) - the others get new appliance / vacuum / pool tiles
    by themselves. Boards made before can't tell, so every filled area's
    boards count as changed (nothing moves without asking)."""
    for a in doc.get("areas") or []:
        a["edited"] = ["5x2", "6x3"] if a.get("filled") else []
    return doc


def migrate_1_10_to_1_11(doc: dict[str, Any]) -> dict[str, Any]:
    """1.10 -> 1.11 (2026-11-12): wall panels on Room Tiles firmware keep
    their own settings (`panels`, additive - none yet)."""
    doc.setdefault("panels", [])
    return doc


MIGRATIONS = {
    (1, 1): migrate_1_1_to_1_2,
    (1, 2): migrate_1_2_to_1_3,
    (1, 3): migrate_1_3_to_1_4,
    (1, 4): migrate_1_4_to_1_5,
    (1, 5): migrate_1_5_to_1_6,
    (1, 6): migrate_1_6_to_1_7,
    (1, 7): migrate_1_7_to_1_8,
    (1, 8): migrate_1_8_to_1_9,
    (1, 9): migrate_1_9_to_1_10,
    (1, 10): migrate_1_10_to_1_11,
}


def migrate(major: int, minor: int, doc: dict[str, Any], target_minor: int) -> dict[str, Any]:
    while minor < target_minor:
        step = MIGRATIONS.get((major, minor))
        if step is None:
            raise ValueError(f"no migration from {major}.{minor}")
        doc = step(doc)
        minor += 1
    return doc
