"""Edit operations on RoomTilesData. Pure Python (no HA imports): the actions
in services.py and the tests call these. Each returns the document sections it
changed, so listeners only receive what's new.

Errors are ModelError with a message meant for the user.
"""

from __future__ import annotations

import uuid
from typing import Any

from .const import KIND_BLANK, LAYOUTS, MAX_LAYERS, MAX_MAPS, MAX_SHORT_NAME, NO_ENTITY_KINDS, TILE_KINDS
from .model import Appliance, Area, PoolSystem, RobotProfile, CatalogEntry, Map, Marker, ModelError, RoomTilesData, Tile
from .shortnames import fits, suggest
from . import wording

SECTION_AREAS = "areas"
SECTION_MAPS = "maps"
SECTION_MARKERS = "markers"
SECTION_CATALOG = "catalog"
SECTION_SETTINGS = "settings"
SECTION_APPLIANCES = "appliances"
SECTION_POOLS = "pools"
SECTION_ROBOTS = "robots"
SECTION_PANELS = "panels"
ALL_SECTIONS = (
    SECTION_AREAS,
    SECTION_MAPS,
    SECTION_MARKERS,
    SECTION_CATALOG,
    SECTION_SETTINGS,
    SECTION_APPLIANCES,
    SECTION_POOLS,
    SECTION_ROBOTS,
    SECTION_PANELS,
)


def _grid(data: RoomTilesData, area_id: str, layout: str) -> tuple[Area, list[Tile]]:
    area = data.area(area_id)
    if area is None:
        raise ModelError(f"no area '{area_id}'")
    if layout not in LAYOUTS:
        raise ModelError(f"layout must be one of {', '.join(LAYOUTS)}")
    return area, area.tiles[layout]


def _edited(area: Area, layout: str) -> None:
    """The user changed this board: it's theirs now (no automatic tiles)."""
    if layout not in area.edited:
        area.edited = [x for x in LAYOUTS if x in (*area.edited, layout)]


def _slot(grid: list[Tile], slot: int) -> int:
    if not 0 <= slot < len(grid):
        raise ModelError(f"slot must be 0-{len(grid) - 1}")
    return slot


def set_tile(
    data: RoomTilesData,
    area_id: str,
    layout: str,
    slot: int,
    entity: str | None = None,
    kind: str | None = None,
    name: str | None = None,
) -> tuple[str, ...]:
    """Put a tile in a slot. With only `entity`, the kind comes from the
    catalog. `name` overrides the catalog's short name for this tile only
    (None / "" = use the catalog's). No entity and no kind (or kind "blank")
    clears the slot; kind "map" needs no entity."""
    area, grid = _grid(data, area_id, layout)
    _slot(grid, slot)
    if kind is not None and kind not in TILE_KINDS:
        raise ModelError(f"unknown tile kind '{kind}'")
    name = " ".join(name.split()) if name else None
    if name and len(name) > MAX_SHORT_NAME:
        raise ModelError(f"tile name '{name}' is longer than {MAX_SHORT_NAME} characters")

    if kind in (None, KIND_BLANK) and not entity:
        grid[slot] = Tile()
    elif kind in NO_ENTITY_KINDS:
        grid[slot] = Tile(kind=kind, name=name)
    else:
        if not entity:
            raise ModelError(f"a '{kind}' tile needs an entity")
        entry = data.catalog.get(entity)
        if kind is None:
            if entry is None:
                raise ModelError(f"'{entity}' is not in the catalog - give its kind")
            kind = entry.kind
        grid[slot] = Tile(kind=kind, entity=entity, name=name)
    _edited(area, layout)
    return (SECTION_AREAS,)


def clear_tile(data: RoomTilesData, area_id: str, layout: str, slot: int) -> tuple[str, ...]:
    return set_tile(data, area_id, layout, slot)


def move_tile(
    data: RoomTilesData, area_id: str, layout: str, from_slot: int, to_slot: int
) -> tuple[str, ...]:
    """Swap two slots (moving onto a blank slot is a move)."""
    area, grid = _grid(data, area_id, layout)
    a, b = _slot(grid, from_slot), _slot(grid, to_slot)
    grid[a], grid[b] = grid[b], grid[a]
    _edited(area, layout)
    return (SECTION_AREAS,)


def add_marker(
    data: RoomTilesData,
    map_id: str,
    entity: str,
    x: float,
    y: float,
    layer: str | None = None,
    show_name: bool = False,
    marker_id: str | None = None,
) -> tuple[tuple[str, ...], str]:
    """Place an entity on a map layer (default: the map's first). Returns
    (sections, new marker id)."""
    m = data.map(map_id)
    if m is None:
        raise ModelError(f"no map '{map_id}'")
    layer = layer or m.layers[0].id
    if layer not in {lay.id for lay in m.layers}:
        raise ModelError(f"map '{map_id}' has no layer '{layer}'")
    if not entity or "." not in entity:
        raise ModelError("entity must be an entity id like light.kitchen")
    mid = marker_id or uuid.uuid4().hex
    if any(m.id == mid for m in data.markers):
        raise ModelError(f"marker '{mid}' already exists")
    data.markers.append(
        Marker(
            id=mid,
            map=map_id,
            entity=entity,
            x=float(x),
            y=float(y),
            layer=layer,
            show_name=show_name,
        )
    )
    return (SECTION_MARKERS,), mid


_MARKER_FIELDS = ("map", "x", "y", "layer", "show_name")


def update_marker(data: RoomTilesData, marker_id: str, **changes) -> tuple[str, ...]:
    """Change a marker's position / map / flags. Unknown fields are refused."""
    marker = next((m for m in data.markers if m.id == marker_id), None)
    if marker is None:
        raise ModelError(f"no marker '{marker_id}'")
    bad = set(changes) - set(_MARKER_FIELDS)
    if bad:
        raise ModelError(f"can't change {', '.join(sorted(bad))}")
    if "map" in changes and data.map(changes["map"]) is None:
        raise ModelError(f"no map '{changes['map']}'")
    target = data.map(changes.get("map", marker.map))
    layer = changes.get("layer", marker.layer)
    if layer not in {lay.id for lay in target.layers}:
        if "layer" in changes:
            raise ModelError(f"map '{target.id}' has no layer '{layer}'")
        changes["layer"] = target.layers[0].id  # moved to a map without that layer
    for key, value in changes.items():
        if key in ("x", "y"):
            value = float(value)
        elif key == "show_name":
            value = bool(value)
        setattr(marker, key, value)
    return (SECTION_MARKERS,)


def remove_marker(data: RoomTilesData, marker_id: str) -> tuple[str, ...]:
    before = len(data.markers)
    data.markers = [m for m in data.markers if m.id != marker_id]
    if len(data.markers) == before:
        raise ModelError(f"no marker '{marker_id}'")
    return (SECTION_MARKERS,)


def set_short_name(
    data: RoomTilesData,
    short_name: str,
    area_id: str | None = None,
    entity: str | None = None,
) -> tuple[str, ...]:
    """Set (and confirm) the short name of an area or a catalog entity."""
    if (area_id is None) == (entity is None):
        raise ModelError("give either an area or an entity")
    short = " ".join((short_name or "").split())
    if not short:
        raise ModelError("the short name can't be empty")
    if len(short) > MAX_SHORT_NAME:
        raise ModelError(f"'{short}' is longer than {MAX_SHORT_NAME} characters")
    if not fits(short):
        # it would be flagged again at once (flag_short_names)
        raise ModelError(f"'{short}': due to font width, this is still too wide. Try fewer or narrower characters.")
    if area_id is not None:
        area = data.area(area_id)
        if area is None:
            raise ModelError(f"no area '{area_id}'")
        area.short_name, area.review = short, False
        return (SECTION_AREAS,)
    entry = data.catalog.get(entity)
    if entry is None:
        raise ModelError(f"'{entity}' is not in the catalog")
    entry.short_name, entry.review = short, False
    return (SECTION_CATALOG,)


def accept_short_names(data: RoomTilesData, entities: list[str] | None = None) -> tuple[tuple[str, ...], list[str]]:
    """Confirm the short names waiting for review as they are - every area's
    and catalog entity's (or just `entities`). One too wide for a tile stays
    waiting - confirming it would only flag it again. Returns (sections, the
    ones left: entity ids / area ids)."""
    left: list[str] = []
    changed = False
    sections: set[str] = set()
    if entities is None:
        for a in data.areas:
            if a.review and not a.hidden:
                if fits(a.short_name):
                    a.review = False
                    sections.add(SECTION_AREAS)
                else:
                    left.append(a.id)
    for e in data.catalog.entries:
        if not e.review or (entities is not None and e.entity not in entities):
            continue
        if fits(e.short_name):
            e.review = False
            changed = True
        else:
            left.append(e.entity)
    if changed:
        sections.add(SECTION_CATALOG)
    return tuple(sorted(sections)), left


def set_short_names(data: RoomTilesData, names: dict[str, tuple[str, bool]]) -> tuple[tuple[str, ...], int]:
    """Catalog entities' short names (and their review flags) set as given -
    `names`: entity -> (short name, review). Returns (sections, how many changed)."""
    changed = 0
    for e in data.catalog.entries:
        new = names.get(e.entity)
        if new is not None and (e.short_name, e.review) != new:
            e.short_name, e.review = new
            changed += 1
    return ((SECTION_CATALOG,) if changed else ()), changed


def flag_short_names(data: RoomTilesData) -> bool:
    """Flag for review short names too wide for a tile even though within 15
    characters (capitals, W, M...). Shared short names are fine: "Lamp" in
    the Living Room and "Lamp" in the Dining Room are told apart by their
    area / place on the map. Returns True if a flag was added."""
    changed = False
    for it in [a for a in data.areas if not a.hidden] + list(data.catalog.entries):
        if not it.review and not fits(it.short_name):
            it.review = True
            changed = True
    return changed


def needs_review(data: RoomTilesData) -> list[tuple[str, str, str]]:
    """[(kind "area"/"entity", id, short name)] still waiting for review."""
    out = [("area", a.id, a.short_name) for a in data.areas if a.review and not a.hidden]
    out += [("entity", e.entity, e.short_name) for e in data.catalog.entries if e.review]
    return out


def set_area_lights(
    data: RoomTilesData,
    area_id: str,
    entity: str | None = None,
    exclude: list[str] | None = None,
) -> tuple[str, ...]:
    """Area Lights: `entity` = override (one entity, e.g. a group); None =
    every light in the HA area. `exclude` (None = unchanged) replaces the
    area's exclude list."""
    area = data.area(area_id)
    if area is None:
        raise ModelError(f"no area '{area_id}'")
    if entity is not None and "." not in entity:
        raise ModelError("entity must be an entity id like light.kitchen_lights")
    area.lights = entity or None
    if exclude is not None:
        area.lights_exclude = sorted(dict.fromkeys(e for e in exclude if e))
    return (SECTION_AREAS,)


def set_area_light_entity(data: RoomTilesData, area_id: str, enabled: bool) -> tuple[str, ...]:
    """Whether Room Tiles makes its "<Area> Lights" light for the area
    (light.py). Off removes it - and so its tiles and markers."""
    area = data.area(area_id)
    if area is None:
        raise ModelError(f"no area '{area_id}'")
    area.light_entity = bool(enabled)
    return (SECTION_AREAS,)


def rename_entity(data: RoomTilesData, old: str, new: str) -> tuple[str, ...]:
    """An entity id changed in HA: follow it everywhere it's referenced."""
    sections: set[str] = set()

    def sub(value: str | None) -> str | None:
        return new if value == old else value

    for a in data.areas:
        if a.lights == old or old in a.lights_exclude:
            a.lights = sub(a.lights)
            a.lights_exclude = sorted({new if x == old else x for x in a.lights_exclude})
            sections.add(SECTION_AREAS)
        for grid in a.tiles.values():
            for t in grid:
                if t.entity == old:
                    t.entity = new
                    sections.add(SECTION_AREAS)
    for m in data.markers:
        if m.entity == old:
            m.entity = new
            sections.add(SECTION_MARKERS)
    for e in data.catalog.entries:
        if e.entity == old:
            e.entity = new
            sections.add(SECTION_CATALOG)
    if old in data.catalog.hidden:
        data.catalog.hidden = [new if x == old else x for x in data.catalog.hidden]
        sections.add(SECTION_CATALOG)
    for mp in data.maps:
        for z in mp.zones:
            if z.vacuum == old:
                z.vacuum = new
                sections.add(SECTION_MAPS)
    for rb in data.robots:
        if old in rb.entities():
            rb.vacuum = new if rb.vacuum == old else rb.vacuum
            rb.error = sub(rb.error)
            sections.add(SECTION_ROBOTS)
    for ps in data.pools:
        if old in ps.entities():
            ps.spa_mode = sub(ps.spa_mode)
            ps.pump = sub(ps.pump)
            for b in (ps.pool, ps.spa):
                if b:
                    b.temp, b.heater, b.pump = sub(b.temp), sub(b.heater), sub(b.pump)
            sections.add(SECTION_POOLS)
    for ap in data.appliances:
        for u in ap.units:
            if old in u.entities():
                u.status = new if u.status == old else u.status
                u.time = sub(u.time)
                u.door = sub(u.door)
                u.clear = [new if c == old else c for c in u.clear]
                sections.add(SECTION_APPLIANCES)
    return tuple(sorted(sections))


def referenced_entities(data: RoomTilesData) -> dict[str, list[str]]:
    """entity id -> where Room Tiles uses it ("Kitchen tile", "House map"...)."""
    used: dict[str, list[str]] = {}

    def add(entity: str | None, where: str) -> None:
        if entity:
            used.setdefault(entity, [])
            if where not in used[entity]:
                used[entity].append(where)

    for a in data.areas:
        add(a.lights, f"{a.name} area lights")
        for grid in a.tiles.values():
            for t in grid:
                add(t.entity, f"{a.name} tile")
    maps = {m.id: m.name for m in data.maps}
    for m in data.markers:
        add(m.entity, f"{maps.get(m.map, m.map)} map")
    for e in data.catalog.entries:
        add(e.entity, "catalog")
    for mp in data.maps:
        for z in mp.zones:
            add(z.vacuum, f"{mp.name} map vacuum zones")
    for ap in data.appliances:
        for u in ap.units:
            for e in u.entities():
                add(e, f"{ap.name} appliance ({u.label})")
    for ps in data.pools:
        for e in ps.entities():
            add(e, f"{ps.name} (pool / spa)")
    for rb in data.robots:
        for e in rb.entities():
            add(e, f"{rb.name} (robot vacuum)")
    return used


def catalog_add(
    data: RoomTilesData,
    entity: str,
    kind: str,
    full_name: str,
    short_name: str | None = None,
) -> tuple[tuple[str, ...], CatalogEntry]:
    """Offer an entity in the tile picker. Short name: the given one (checked),
    else suggested from its full name (review if shortened). An entity already
    in the catalog is returned unchanged; one the user removed earlier is
    un-hidden."""
    if kind not in TILE_KINDS or kind in NO_ENTITY_KINDS:
        raise ModelError(f"'{kind}' is not a tile kind for an entity")
    existing = data.catalog.get(entity)
    if existing is not None:
        return (), existing
    if short_name:
        short = " ".join(short_name.split())
        if len(short) > MAX_SHORT_NAME:
            raise ModelError(f"'{short}' is longer than {MAX_SHORT_NAME} characters")
        review = False
    else:
        short, review = suggest(full_name or entity)
    entry = CatalogEntry(entity=entity, kind=kind, short_name=short, review=review, auto=False)
    data.catalog.entries.append(entry)
    data.catalog.hidden = [h for h in data.catalog.hidden if h != entity]
    return (SECTION_CATALOG,), entry


def catalog_remove(data: RoomTilesData, entity: str) -> tuple[str, ...]:
    """Take an entity out of the tile picker (tiles already using it stay)."""
    entry = data.catalog.get(entity)
    if entry is None:
        raise ModelError(f"'{entity}' is not in the catalog")
    data.catalog.entries = [e for e in data.catalog.entries if e.entity != entity]
    if entry.auto and entity not in data.catalog.hidden:
        data.catalog.hidden.append(entity)  # an automatic one stays out on rebuilds
    return (SECTION_CATALOG,)


def set_area(
    data: RoomTilesData,
    area_id: str,
    hidden: bool | None = None,
    position: int | None = None,
) -> tuple[str, ...]:
    """Show / hide an area, or move it to `position` (0 = first) in the order."""
    area = data.area(area_id)
    if area is None:
        raise ModelError(f"no area '{area_id}'")
    if hidden is not None:
        area.hidden = bool(hidden)
    if position is not None:
        rest = [a for a in data.areas if a.id != area_id]
        pos = max(0, min(len(rest), int(position)))
        data.areas = rest[:pos] + [area] + rest[pos:]
    return (SECTION_AREAS,)


Where = tuple[str, dict]  # a wording token (wording/<lang>.json "removed.*") + its values


def forget_entity(data: RoomTilesData, entity: str) -> tuple[tuple[str, ...], list[Where]]:
    """An entity was DELETED in HA: remove it everywhere - its tiles become
    empty, its markers go, its catalog entry goes, area-lights references are
    cleaned. Returns (sections, where it was removed from) for the notice -
    worded in HA's language when it's made (repairs.py)."""
    sections: set[str] = set()
    where: list[Where] = []
    for a in data.areas:
        n = 0
        for grid in a.tiles.values():
            for i, t in enumerate(grid):
                if t.entity == entity:
                    grid[i] = Tile()
                    n += 1
        if n:
            where.append(("removed.tiles", {"name": a.name, "n": n}))
            sections.add(SECTION_AREAS)
        if a.lights == entity:
            a.lights = None
            where.append(("removed.area_lights", {"name": a.name}))
            sections.add(SECTION_AREAS)
        if entity in a.lights_exclude:
            a.lights_exclude = [e for e in a.lights_exclude if e != entity]
            sections.add(SECTION_AREAS)
    maps = {m.id: m.name for m in data.maps}
    gone = [m for m in data.markers if m.entity == entity]
    if gone:
        data.markers = [m for m in data.markers if m.entity != entity]
        per_map: dict[str, int] = {}
        for m in gone:
            per_map[maps.get(m.map, m.map)] = per_map.get(maps.get(m.map, m.map), 0) + 1
        where += [("removed.markers", {"name": name, "n": n}) for name, n in per_map.items()]
        sections.add(SECTION_MARKERS)
    if data.catalog.get(entity) is not None or entity in data.catalog.hidden:
        data.catalog.entries = [e for e in data.catalog.entries if e.entity != entity]
        data.catalog.hidden = [h for h in data.catalog.hidden if h != entity]
        where.append(("removed.catalog", {}))
        sections.add(SECTION_CATALOG)
    for mp in data.maps:
        n = len([z for z in mp.zones if z.vacuum == entity])
        if n:
            mp.zones = [z for z in mp.zones if z.vacuum != entity]
            where.append(("removed.zones", {"name": mp.name, "n": n}))
            sections.add(SECTION_MAPS)
    for ap in data.appliances:
        for u in ap.units:
            # the status entity stays (a replaced appliance gets re-linked;
            # until then the missing-entities notice lists it)
            if entity in (u.time, u.door) or entity in u.clear:
                u.time = None if u.time == entity else u.time
                u.door = None if u.door == entity else u.door
                u.clear = [c for c in u.clear if c != entity]
                where.append(("removed.appliance", {"name": ap.name, "unit": u.label}))
                sections.add(SECTION_APPLIANCES)
    return tuple(sorted(sections)), where


def set_settings(
    data: RoomTilesData, auto_add_areas: bool | None = None, auto_update_panels: bool | None = None
) -> tuple[str, ...]:
    """Room Tiles' own settings."""
    if auto_add_areas is not None:
        data.settings.auto_add_areas = bool(auto_add_areas)
    if auto_update_panels is not None:
        data.settings.auto_update_panels = bool(auto_update_panels)
    return (SECTION_SETTINGS,)


def set_markers(data: RoomTilesData, map_id: str, markers: list[dict]) -> tuple[str, ...]:
    """Replace ALL of a map's markers in one step (the map editor's Save).
    Each item: entity, x, y, layer (default: the map's first), show_name,
    id (kept when given, else a new one). Validated as a whole."""
    m = data.map(map_id)
    if m is None:
        raise ModelError(f"no map '{map_id}'")
    layers = {lay.id for lay in m.layers}
    others = [mk for mk in data.markers if mk.map != map_id]
    used = {mk.id for mk in others}
    new: list[Marker] = []
    for item in markers:
        entity = str(item.get("entity") or "")
        if "." not in entity:
            raise ModelError(f"marker entity '{entity}' is not an entity id")
        layer = item.get("layer") or m.layers[0].id
        if layer not in layers:
            raise ModelError(f"map '{map_id}' has no layer '{layer}'")
        mid = str(item.get("id") or "") or uuid.uuid4().hex
        while mid in used:
            mid = uuid.uuid4().hex
        used.add(mid)
        new.append(
            Marker(
                id=mid,
                map=map_id,
                entity=entity,
                x=float(item["x"]),
                y=float(item["y"]),
                layer=layer,
                show_name=bool(item.get("show_name", False)),
            )
        )
    data.markers = others + new
    return (SECTION_MARKERS,)


# ---- maps (the map editor) ------------------------------------------------------

# what set_map may change; id / generated / the markers are not part of it
MAP_FIELDS = ("name", "bounds", "ha_floor", "wall_width", "walls", "windows", "openings",
              "shapes", "zones", "links", "layers")


def set_map(data: RoomTilesData, map_id: str, fields: dict) -> tuple[str, ...]:
    """Replace a map's drawing in one step (the map editor's Save): any of
    MAP_FIELDS, the rest kept. An edited map is no longer `generated` (new
    areas don't get squares added to it any more) - its `bounds` and
    `layers` alone (the Layer Editor's Save: the bounds refitted to the
    markers, where the layers start) aren't an edit of the drawing. Markers on a layer that was removed move to the map's first
    layer."""
    old = data.map(map_id)
    if old is None:
        raise ModelError(f"no map '{map_id}'")
    unknown = set(fields) - set(MAP_FIELDS)
    if unknown:
        raise ModelError(f"unknown map field(s): {', '.join(sorted(unknown))}")
    d = old.as_dict()
    d.update(fields)
    d["id"] = map_id
    if set(fields) - {"bounds", "layers"}:
        d["generated"] = False
    if not str(d.get("name") or "").strip():
        raise ModelError("a map needs a name")
    if not d.get("layers"):
        raise ModelError(f"map '{map_id}' needs at least one layer")
    if len(d["layers"]) > MAX_LAYERS:
        raise ModelError(f"at most {MAX_LAYERS} layers on a map")
    new = Map.from_dict(d)
    data.maps = [new if m.id == map_id else m for m in data.maps]
    layers = {lay.id for lay in new.layers}
    sections = [SECTION_MAPS]
    for mk in data.markers:
        if mk.map == map_id and mk.layer not in layers:
            mk.layer = new.layers[0].id
            if SECTION_MARKERS not in sections:
                sections.append(SECTION_MARKERS)
    return tuple(sections)


def _map_id(data: RoomTilesData, name: str) -> str:
    base = "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_") or "map"
    mid, n = base, 2
    while data.map(mid) is not None:
        mid, n = f"{base}_{n}", n + 1
    return mid


def add_map(data: RoomTilesData, name: str, ha_floor: str | None = None) -> tuple[tuple[str, ...], str]:
    """A new, empty map (a floor, a yard...) at the end of the list."""
    name = " ".join(str(name or "").split())
    if not name:
        raise ModelError("a map needs a name")
    if len(data.maps) >= MAX_MAPS:
        raise ModelError(f"at most {MAX_MAPS} maps")
    mid = _map_id(data, name)
    data.maps.append(Map(id=mid, name=name, bounds=(0.0, 0.0, 1000.0, 600.0), ha_floor=ha_floor or None))
    return (SECTION_MAPS,), mid


def remove_map(data: RoomTilesData, map_id: str) -> tuple[str, ...]:
    """Delete a map with its markers; links to it from other maps go too. The
    last map can't go (Room Tiles always has a map)."""
    if data.map(map_id) is None:
        raise ModelError(f"no map '{map_id}'")
    if len(data.maps) == 1:
        raise ModelError("the last map can't be deleted")
    data.maps = [m for m in data.maps if m.id != map_id]
    for m in data.maps:
        m.links = [lk for lk in m.links if lk.to != map_id]
    data.markers = [mk for mk in data.markers if mk.map != map_id]
    return (SECTION_MAPS, SECTION_MARKERS)


def order_maps(data: RoomTilesData, order: list[str]) -> tuple[str, ...]:
    """Put the maps in this order (the map selector's); every map exactly once."""
    if sorted(order) != sorted(m.id for m in data.maps):
        raise ModelError("the order must list every map exactly once")
    by_id = {m.id: m for m in data.maps}
    data.maps = [by_id[i] for i in order]
    return (SECTION_MAPS,)


# ---- appliance profiles -------------------------------------------------------


def set_appliance(data: RoomTilesData, appliance: dict[str, Any]) -> tuple[str, ...]:
    """Add an appliance profile, or replace the one with the same id."""
    from .appliance_presets import PRESETS

    ap = Appliance.from_dict(appliance)
    for u in ap.units:
        if u.preset not in PRESETS:
            raise ModelError(f"unknown appliance preset '{u.preset}'")
    i = next((k for k, a in enumerate(data.appliances) if a.id == ap.id), None)
    if i is None:
        data.appliances.append(ap)
    else:
        data.appliances[i] = ap
    return (SECTION_APPLIANCES,)


def remove_appliance(data: RoomTilesData, appliance_id: str) -> tuple[str, ...]:
    before = len(data.appliances)
    data.appliances = [a for a in data.appliances if a.id != appliance_id]
    if len(data.appliances) == before:
        raise ModelError(f"no appliance '{appliance_id}'")
    _drop_appliance_rules(data, appliance_id)
    return (SECTION_APPLIANCES,)


def _drop_appliance_rules(data: RoomTilesData, appliance_id: str) -> None:
    """An appliance went: nothing waits for it to start any more."""
    for ap in data.appliances:
        for u in ap.units:
            u.clear = [c for c in u.clear if c != f"appliance:{appliance_id}"]


def _replace_entity(data: RoomTilesData, old: str, new: str) -> set[str]:
    """Point tiles and markers using `old` at `new` (an appliance merged into
    another); `old`'s catalog entry goes."""
    sections: set[str] = set()
    for a in data.areas:
        for grid in a.tiles.values():
            for t in grid:
                if t.entity == old:
                    t.entity = new
                    sections.add(SECTION_AREAS)
    for m in data.markers:
        if m.entity == old:
            m.entity = new
            sections.add(SECTION_MARKERS)
    if data.catalog.get(old) is not None:
        data.catalog.entries = [e for e in data.catalog.entries if e.entity != old]
        sections.add(SECTION_CATALOG)
    return sections


def _pair_rules(units: list) -> None:
    """A washer sharing a tile with a dryer waits for it (switch over until the
    dryer starts) - the same as setup's automatic pairing."""
    dryer = next((u for u in units if u.appliance == "dryer"), None)
    for u in units:
        u.clear = [c for c in u.clear if not c.startswith("appliance:")]  # now on this tile
        if u.appliance == "washer" and dryer is not None and u.finished != "idle" and f"unit:{dryer.id}" not in u.clear:
            u.finished = "waiting"
            u.clear = [*u.clear, f"unit:{dryer.id}"]


def combine_appliances(
    data: RoomTilesData,
    first: str,
    second: str,
    entities: dict[str, str],
    name: str | None = None,
) -> tuple[str, ...]:
    """Put two one-unit appliances on one tile: `second`'s unit joins `first`
    (first on top - except a dryer always goes above a washer), `second` goes; its tiles / markers move to `first`'s
    sensor. `entities`: appliance id -> its sensor entity id."""
    a = next((x for x in data.appliances if x.id == first), None)
    b = next((x for x in data.appliances if x.id == second), None)
    if a is None or b is None or a is b:
        raise ModelError("pick two different appliances")
    if len(a.units) != 1 or len(b.units) != 1:
        raise ModelError("only two single appliances can share a tile")
    unit = b.units[0]
    if unit.id == a.units[0].id:
        unit.id = f"{unit.id}_2"
    unit.clear = [c for c in unit.clear if not c.startswith(("unit:", "appliance:"))]
    a.units.append(unit)
    # a dryer always goes above its washer (Swap order changes it later)
    a.units.sort(key=lambda u: 0 if u.appliance == "dryer" else 1)
    _pair_rules(a.units)
    kinds = {u.appliance for u in a.units}
    a.name = (name or "").strip() or (
        wording.t("names.laundry") if kinds == {"washer", "dryer"} else wording.t("names.dishwashers") if kinds == {"dishwasher"} else f"{a.name} + {b.name}"
    )
    data.appliances = [x for x in data.appliances if x.id != second]
    _drop_appliance_rules(data, second)
    sections = {SECTION_APPLIANCES}
    if second in entities and first in entities:
        sections |= _replace_entity(data, entities[second], entities[first])
    return tuple(sorted(sections))


def split_appliance(data: RoomTilesData, appliance_id: str, unit_id: str) -> tuple[tuple[str, ...], str]:
    """Give one unit of a two-unit appliance its own tile: it becomes a new
    appliance (named after the unit); the tile(s) stay with the other unit.
    Returns (sections, the new appliance id)."""
    a = next((x for x in data.appliances if x.id == appliance_id), None)
    if a is None:
        raise ModelError(f"no appliance '{appliance_id}'")
    unit = next((u for u in a.units if u.id == unit_id), None)
    if unit is None or len(a.units) != 2:
        raise ModelError("only a unit of a two-unit appliance can be split off")
    a.units = [u for u in a.units if u.id != unit_id]
    taken = {x.id for x in data.appliances}
    new_id, n = unit.id, 1
    while new_id in taken:
        n += 1
        new_id = f"{unit.id}_{n}"
    # a washer keeps its Switch Over: now emptied by the dryer's own tile starting
    tile_of = {id(u): (a.id if u is not unit else new_id) for u in (*a.units, unit)}
    dryer = next((u for u in (*a.units, unit) if u.appliance == "dryer"), None)
    for u in (*a.units, unit):
        was_waiting = u.finished == "waiting" and dryer is not None and u is not dryer
        u.clear = [c for c in u.clear if not c.startswith("unit:")]
        if was_waiting:
            u.clear.append(f"appliance:{tile_of[id(dryer)]}")
        elif u.finished == "waiting":
            u.finished = "done"
    data.appliances.append(Appliance(id=new_id, name=unit.label, units=[unit]))
    return (SECTION_APPLIANCES,), new_id


def follow_appliance_name(data: RoomTilesData, entity: str, old: str | None, new: str) -> tuple[str, ...]:
    """An appliance was renamed: its tile-picker entry (what tiles show) takes
    the new name - renaming is renaming the tile. Shortened if needed (and
    then flagged for review, like any suggested short name)."""
    entry = data.catalog.get(entity)
    if entry is None or old is None or old == new:
        return ()
    entry.short_name, entry.review = suggest(new)
    return (SECTION_CATALOG,)


# ---- pool / spa profiles -------------------------------------------------------


def set_pool(data: RoomTilesData, pool: dict[str, Any]) -> tuple[str, ...]:
    """Add a pool / spa system, or replace the one with the same id."""
    ps = PoolSystem.from_dict(pool)
    i = next((k for k, p in enumerate(data.pools) if p.id == ps.id), None)
    if i is None:
        data.pools.append(ps)
    else:
        data.pools[i] = ps
    return (SECTION_POOLS,)


def remove_pool(data: RoomTilesData, pool_id: str) -> tuple[str, ...]:
    before = len(data.pools)
    data.pools = [p for p in data.pools if p.id != pool_id]
    if len(data.pools) == before:
        raise ModelError(f"no pool '{pool_id}'")
    return (SECTION_POOLS,)


# ---- robot vacuum profiles ------------------------------------------------------


def set_robot(data: RoomTilesData, robot: dict[str, Any]) -> tuple[str, ...]:
    rb = RobotProfile.from_dict(robot)
    i = next((k for k, r in enumerate(data.robots) if r.id == rb.id), None)
    if i is None:
        data.robots.append(rb)
    else:
        data.robots[i] = rb
    return (SECTION_ROBOTS,)


def remove_robot(data: RoomTilesData, robot_id: str) -> tuple[str, ...]:
    before = len(data.robots)
    data.robots = [r for r in data.robots if r.id != robot_id]
    if len(data.robots) == before:
        raise ModelError(f"no robot vacuum '{robot_id}'")
    return (SECTION_ROBOTS,)


# ---- ignoring found devices (Appliances page) ---------------------------------


def device_keys(kind: str, profile: dict[str, Any]) -> list[str]:
    """The entities that identify a found / set-up device: an appliance's
    unit status entities, a pool's water temperature (or heater) per body, a
    vacuum's entity."""
    if kind == "appliance":
        return [u["status"] for u in profile.get("units") or [] if u.get("status")]
    if kind == "pool":
        out = []
        for b in ("pool", "spa"):
            body = profile.get(b) or {}
            if body.get("temp") or body.get("heater"):
                out.append(body.get("temp") or body.get("heater"))
        return out
    if kind == "robot":
        return [profile["vacuum"]] if profile.get("vacuum") else []
    raise ModelError(f"unknown kind '{kind}'")


def ignore_device(data: RoomTilesData, kind: str, entities: list[str], set_up_id: str | None = None) -> tuple[str, ...]:
    """Ignore a device: it leaves Room Tiles if it was set up (its sensor goes,
    its tiles go empty) and waits under Ignored - the dot doesn't count it."""
    sections: set[str] = {SECTION_APPLIANCES}  # the found lists are recomputed
    if set_up_id is not None:
        sections |= set(
            {"appliance": remove_appliance, "pool": remove_pool, "robot": remove_robot}[kind](data, set_up_id)
        )
    for e in entities:
        if e not in data.ignored:
            data.ignored.append(e)
    return tuple(sorted(sections))


def unignore(data: RoomTilesData, entities: list[str]) -> bool:
    """Set up again: its entities leave the ignored list (True if any did)."""
    before = len(data.ignored)
    data.ignored = [e for e in data.ignored if e not in set(entities)]
    return len(data.ignored) != before
