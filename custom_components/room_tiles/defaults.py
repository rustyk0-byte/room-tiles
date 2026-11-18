"""Default tile boards and map markers - so a new home starts usable, not
empty.

Each area is filled ONCE (`Area.filled`), when it's first shown (an area
hidden in Room Tiles waits): its boards that are completely empty get its
tiles, and its square on a generated map gets a marker. A
board with any tile is never touched, and a board the user empties later
stays empty. Runs once HA has started (every integration's entities known)
and for each new area after that.

A board: the area's lights together ("<Area> Lights", light.py) first when
it has one, then, grouped by
kind - lights (groups first, then colour / dimmable / on-off), thermostats,
fans, covers, locks, switches, then Room Tiles' own tiles (vacuums,
appliances, pool / spa) - each by name. When they don't all fit (5x2: 9-10
slots, 6x3: 17-18), the slots are first DEALT OUT over the kinds - one each
before any kind gets a second, Room Tiles' own tiles first in line - so a
room with 15 lights still shows its fans and locks (pick).
Only what can be a tile (the dashboard's canBeTile rule): never hidden /
disabled / settings entities, nor what Room Tiles' own tiles are made of
(set up, found or ignored).

A board the user never changed (not in `Area.edited`) stays automatic: an
appliance, vacuum or pool / spa set up later is added to it by itself
(place_new - the board is worked out again, so the new tile sits where its
kind goes). A changed board is the user's: the dashboard asks. "Auto
configure" in the tile editor (auto_board) makes a board automatic again.

The map: on a GENERATED map (one per floor, a square per area) each square
gets the area's lights marker - its "<Area> Lights" light, or its only light.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from . import arealights, ops, wording
from .const import (
    DOMAIN,
    KIND_APPLIANCE,
    KIND_BLANK,
    KIND_CLIMATE,
    KIND_COLOR_LIGHT,
    KIND_COVER,
    KIND_DIMMABLE_LIGHT,
    KIND_FAN,
    KIND_LOCK,
    KIND_ONOFF_LIGHT,
    KIND_SWITCH,
    KIND_VACUUM,
    KIND_WATER,
    LAYOUTS,
)
from .kinds import infer_kind
from .light import area_light_id, wanted
from .model import Area, RoomTilesData, Tile
from .pool import switch_body, switch_keys, switch_name, switch_uid, tile_name
from .source_device import appliance_source, pool_source, robot_source

ORDER = [
    KIND_WATER,
    KIND_APPLIANCE,
    KIND_VACUUM,
    KIND_CLIMATE,
    KIND_COLOR_LIGHT,
    KIND_DIMMABLE_LIGHT,
    KIND_ONOFF_LIGHT,
    KIND_FAN,
    KIND_COVER,
    KIND_LOCK,
    KIND_SWITCH,
]
TILE_DOMAINS = {"light", "switch", "input_boolean", "fan", "cover", "lock", "climate", "vacuum"}
LIGHT_KINDS = (KIND_COLOR_LIGHT, KIND_DIMMABLE_LIGHT, KIND_ONOFF_LIGHT)
# when a board can't hold everything, its slots are dealt out over these in
# turn (lights - all three kinds - are one share)
SHARES = [KIND_WATER, KIND_APPLIANCE, KIND_VACUUM, KIND_CLIMATE, "light", KIND_FAN, KIND_COVER, KIND_LOCK, KIND_SWITCH]

# where the chosen tiles sit: lights first, Room Tiles' own tiles (vacuums,
# appliances, pool / spa) last
PLACES = ["light", KIND_CLIMATE, KIND_FAN, KIND_COVER, KIND_LOCK, KIND_SWITCH, KIND_VACUUM, KIND_APPLIANCE, KIND_WATER]

# (entity, kind, full name, is a light group)
Item = tuple[str, str, str, bool]


def share(kind: str) -> str:
    return "light" if kind in LIGHT_KINDS else kind


def pick(items: list[Item], slots: int) -> list[Item]:
    """What fits in `slots`, in board order. Everything if it fits; else the
    slots are dealt out over the kinds in turn (SHARES order: every kind
    present gets one before any gets a second...), so a room with 15 lights
    still shows its fans and locks. Kinds past the slots go without (lowest
    first)."""
    if len(items) <= slots:
        return list(items)
    by: dict[str, list[Item]] = {}
    for it in items:
        by.setdefault(share(it[1]), []).append(it)
    take = dict.fromkeys(by, 0)
    left = slots
    while left:
        dealt = False
        for k in SHARES:
            if left and k in by and take[k] < len(by[k]):
                take[k] += 1
                left -= 1
                dealt = True
        if not dealt:
            break
    chosen = {it[0] for k, its in by.items() for it in its[: take[k]]}
    return [it for it in items if it[0] in chosen]


def board_order(items: list[Item]) -> list[Item]:
    """Where tiles sit: by kind (PLACES - lights first, Room Tiles' own
    last); lights: groups first (one tile, several lights), then colour /
    dimmable / on-off; each by name. (Which tiles make it onto a small board
    is pick's - SHARES order.)"""
    return sorted(items, key=lambda t: (PLACES.index(share(t[1])), not t[3], ORDER.index(t[1]), t[2].lower()))


def profile_sources(data: RoomTilesData, found: dict[str, Any]) -> set[str]:
    """What Room Tiles' own tiles are (or would be) made of - set up, found
    and ignored. (The dashboard's profileSources.)"""
    out: set[str] = set()

    def add(*ids: Any) -> None:
        out.update(i for i in ids if isinstance(i, str) and i)

    appliances = [a.as_dict() for a in data.appliances] + found.get("found", []) + found.get("found_ignored", [])
    for ap in appliances:
        for u in ap.get("units", []):
            add(u.get("status"), u.get("time"))
    pools = [p.as_dict() for p in data.pools] + found.get("pools", []) + found.get("pools_ignored", [])
    for p in pools:
        for b in (p.get("pool"), p.get("spa")):
            if b:
                add(b.get("temp"), b.get("heater"), b.get("pump"), b.get("heater_switch"))
        add(p.get("spa_mode"), p.get("pump"))
    robots = [r.as_dict() for r in data.robots] + found.get("robots", []) + found.get("robots_ignored", [])
    for r in robots:
        add(r.get("vacuum"), r.get("error"))
    return out


def owned_devices(hass: HomeAssistant, data: RoomTilesData, found: dict[str, Any]) -> set[str]:
    """Devices an appliance or vacuum tile stands for (set up, found or
    ignored): their other controls - sabbath mode, child lock, power - are
    the appliance's settings, not tiles of their own on a default board.
    (Pool / spa devices aren't: their lights and circuits are tiles.)"""
    reg = er.async_get(hass)
    ids: set[str] = set()
    appliances = [a.as_dict() for a in data.appliances] + found.get("found", []) + found.get("found_ignored", [])
    for ap in appliances:
        # every unit's own devices - a tile may combine brands (an LG dryer
        # and a Samsung washer, a smart plug): each one's controls count
        ids.update(x for u in ap.get("units", []) for x in (u.get("status"), u.get("time")) if x)
    robots = [r.as_dict() for r in data.robots] + found.get("robots", []) + found.get("robots_ignored", [])
    ids.update(r.get("vacuum") for r in robots if r.get("vacuum"))
    out: set[str] = set()
    for eid in ids:
        e = reg.async_get(eid)
        if e is not None and e.device_id:
            out.add(e.device_id)
    return out


ENTRY_COVERS = ("garage", "gate", "door")


def entry_devices(hass: HomeAssistant) -> set[str]:
    """Devices of garage doors, gates and doors (cover device class): their
    SWITCHES are the opener's settings (learn / pair remotes, toggle-only...),
    not tiles of their own on a default board. Their light and lock stay."""
    out: set[str] = set()
    for e in er.async_get(hass).entities.values():
        if e.domain != "cover" or not e.device_id:
            continue
        cls = e.device_class or e.original_device_class
        if cls is None:
            st = hass.states.get(e.entity_id)
            cls = st.attributes.get("device_class") if st is not None else None
        if cls in ENTRY_COVERS:
            out.add(e.device_id)
    return out


def _area_of(e: er.RegistryEntry, devices: dr.DeviceRegistry) -> str | None:
    if e.area_id:
        return e.area_id
    dev = devices.async_get(e.device_id) if e.device_id else None
    return dev.area_id if dev else None


def tile_kind(hass: HomeAssistant, data: RoomTilesData, e: er.RegistryEntry) -> str | None:
    """Its tile kind, or None if it can't be a tile (canBeTile)."""
    if e.disabled_by or e.hidden_by or e.entity_category:
        return None
    entry = data.catalog.get(e.entity_id)
    if e.domain == "sensor":
        # sensors that are tiles: Room Tiles' own (catalogued) or the `tile` contract
        if entry is not None:
            return entry.kind
        st = hass.states.get(e.entity_id)
        return infer_kind(e.entity_id, dict(st.attributes)) if st and "tile" in st.attributes else None
    if e.domain not in TILE_DOMAINS:
        return None
    if entry is not None:
        return entry.kind
    st = hass.states.get(e.entity_id)
    attrs = dict(st.attributes) if st else {"supported_color_modes": (e.capabilities or {}).get("supported_color_modes")}
    return infer_kind(e.entity_id, attrs)


def _full_name(hass: HomeAssistant, e: er.RegistryEntry) -> str:
    st = hass.states.get(e.entity_id)
    if e.platform == DOMAIN and st is not None and isinstance(st.attributes.get("own_name"), str) and st.attributes["own_name"]:
        # Room Tiles' own: the name it gave it ("Spa Mode") - HA's friendly
        # name has its device's name in front (the dashboard's fullName)
        return st.attributes["own_name"]
    return (st and st.attributes.get("friendly_name")) or e.name or e.original_name or e.entity_id


def area_tiles(
    hass: HomeAssistant,
    data: RoomTilesData,
    area: Area,
    sources: set[str],
    owned: frozenset[str] = frozenset(),
    entry: frozenset[str] = frozenset(),
) -> tuple[Item | None, list[Item]]:
    """The area's "<Area> Lights" light (first on every board, if any) and
    its other tiles in board order."""
    reg = er.async_get(hass)
    devices = dr.async_get(hass)
    found: list[Item] = []
    for e in reg.entities.values():
        if e.entity_id in sources or _area_of(e, devices) != area.id:
            continue
        if e.platform == DOMAIN and e.domain == "light":
            continue  # its lights together: first, below
        if e.device_id in owned and e.platform != DOMAIN:
            continue  # an appliance's own controls (its tile stands for it)
        if e.device_id in entry and e.domain == "switch":
            continue  # a garage door opener's settings (learn, toggle only...)
        kind = tile_kind(hass, data, e)
        if kind in ORDER:
            st = hass.states.get(e.entity_id)
            group = e.domain == "light" and (e.platform == "group" or bool(st and isinstance(st.attributes.get("entity_id"), list)))
            found.append((e.entity_id, kind, _full_name(hass, e), group))
    # the area's lights together are the lights button's (and the map's) -
    # never a tile: the board starts with the lights themselves (groups first)
    return None, board_order(found)


def area_lights_entity(hass: HomeAssistant, data: RoomTilesData, area: Area) -> tuple[str, str, str] | None:
    """Room Tiles' own "<Area> Lights" light (light.py), when there is (or
    will be) one: the lights button's, and the map's room marker (a full
    light tile on long-press) - never a board tile. (entity, kind, short name)"""
    members = arealights.resolve(hass, area, arealights.lights_by_area(hass))
    eid = area_light_id(area.id)
    entry = er.async_get(hass).async_get(eid)
    ours = (not entry.disabled_by) if entry is not None else wanted(area, members)
    if not ours:
        return None
    # its tile kind: what its lights can do (a long-press on the map shows a
    # full light tile, like any light group)
    modes: set[str] = set()
    for m in members:
        st = hass.states.get(m)
        if st is not None:
            modes |= set(st.attributes.get("supported_color_modes") or [])
    kind = infer_kind("light.x", {"supported_color_modes": list(modes)}) or KIND_ONOFF_LIGHT
    return (eid, kind, wording.t("names.area_lights", area=area.name))


def board_items(first: Item | None, items: list[Item], count: int) -> list[Item]:
    """What a `count`-slot board shows: the area's lights, then what fits of
    the rest (pick). (No Map tile: the map button sits by the area's name;
    a Map tile is placed by hand.)"""
    slots = count - (1 if first else 0)
    return ([first] if first else []) + pick(items, slots)


def default_board(first: Item | None, items: list[Item], count: int) -> list[Tile]:
    """`count` slots: board_items, then empty slots."""
    grid = [Tile(kind=it[1], entity=it[0]) for it in board_items(first, items, count)]
    return grid + [Tile() for _ in range(count - len(grid))]


def _fill(hass: HomeAssistant, data: RoomTilesData, area: Area, layout: str, first: Item | None, items: list[Item]) -> set[str]:
    """Make `layout` the area's automatic board; the changed sections."""
    count = LAYOUTS[layout]
    area.tiles[layout] = default_board(first, items, count)
    area.edited = [x for x in area.edited if x != layout]
    sections: set[str] = {ops.SECTION_AREAS}
    for eid, kind, name, _ in board_items(first, items, count):
        sections.update(ops.catalog_add(data, eid, kind, name)[0])
    return sections


Ctx = tuple[set[str], frozenset[str], frozenset[str]]


def _ctx(hass: HomeAssistant, data: RoomTilesData, found: dict[str, Any]) -> Ctx:
    return profile_sources(data, found), frozenset(owned_devices(hass, data, found)), frozenset(entry_devices(hass))


def _area_items(hass: HomeAssistant, data: RoomTilesData, area: Area, ctx: Ctx, extra: list[Item] = ()) -> tuple[Item | None, list[Item]]:
    """area_tiles plus Room Tiles' own tiles of the area (own_tiles - also
    those not registered yet, or whose source has an area but no device)
    and `extra`."""
    first, items = area_tiles(hass, data, area, *ctx)
    have = {it[0] for it in items}
    for it in [*(it for it, src in own_tiles(hass, data) if tile_area(hass, it[0], src) == area.id), *extra]:
        if it[0] not in have:
            have.add(it[0])
            items.append(it)
    return first, board_order(items)


def entity_area(hass: HomeAssistant, entity: str | None) -> str | None:
    """The HA area an entity is in (its own, else its device's)."""
    e = er.async_get(hass).async_get(entity) if entity else None
    return _area_of(e, dr.async_get(hass)) if e is not None else None


def tile_area(hass: HomeAssistant, entity: str, source: str | None) -> str | None:
    """A Room Tiles tile's area: its sensor's (an area set on it, or its
    device's), else - not registered yet / no device - its source's."""
    return entity_area(hass, entity) or entity_area(hass, source)


def _own_entity(hass: HomeAssistant, unique_id: str, object_id: str, platform: str = "sensor") -> str:
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id) or f"{platform}.room_tiles_{object_id}"


def own_tiles(hass: HomeAssistant, data: RoomTilesData) -> list[tuple[Item, str | None]]:
    """Room Tiles' own tiles (appliances, vacuums, pool / spa) with the
    entity each is made from."""
    out: list[tuple[Item, str | None]] = []
    for ap in data.appliances:
        out.append(((_own_entity(hass, f"appliance_{ap.id}", ap.id), KIND_APPLIANCE, ap.name, False), appliance_source(ap)))
    for rb in data.robots:
        out.append(((_own_entity(hass, f"robot_{rb.id}", rb.id), KIND_VACUUM, rb.name, False), robot_source(rb)))
    for ps in data.pools:
        for body in ps.tiles():
            uid = f"pool_{ps.id}" + (f"_{body}" if body else "")
            out.append(((_own_entity(hass, uid, uid[5:]), KIND_WATER, tile_name(body), False), pool_source(ps, body)))
        for key in switch_keys(ps):
            uid = switch_uid(ps.id, key)
            out.append(((_own_entity(hass, uid, uid[5:], "switch"), KIND_SWITCH, switch_name(key), False), pool_source(ps, switch_body(key))))
    return out


def place_new(hass: HomeAssistant, data: RoomTilesData, new: list[tuple[Item, str | None]], found: dict[str, Any]) -> tuple[set[str], list[str]]:
    """New Room Tiles tiles (an appliance, vacuum or pool / spa just set up),
    each with the entity it's made from (its area is the tile's): the area's
    boards the user never changed are worked out again with it; the areas
    whose changed boards don't have it are returned - the dashboard asks
    about those. (Areas not filled yet get it when they're filled.)"""
    by_area: dict[str, list[Item]] = {}
    for item, source in new:
        aid = tile_area(hass, item[0], source)
        if aid:
            by_area.setdefault(aid, []).append(item)
    sections: set[str] = set()
    ask: list[str] = []
    for aid, extra in by_area.items():
        area = next((a for a in data.areas if a.id == aid), None)
        if area is None or area.hidden or not area.filled:
            continue
        first, items = _area_items(hass, data, area, _ctx(hass, data, found), extra)
        if not area.edited:
            # still all automatic: it starts on 6x3 when 5x2 can't hold it now
            area.layout = "5x2" if (1 if first else 0) + len(items) <= LAYOUTS["5x2"] else "6x3"
        for layout in LAYOUTS:
            if layout not in area.edited:
                sections |= _fill(hass, data, area, layout, first, items)
            elif not all(any(t.entity == it[0] for t in area.tiles[layout]) for it in extra) and aid not in ask:
                ask.append(aid)
    return sections, ask


def auto_board(
    hass: HomeAssistant, data: RoomTilesData, area_id: str | None, layout: str | None, found: dict[str, Any]
) -> set[str]:
    """"Auto configure": boards get their automatic tiles again (what a new
    home gets) and are automatic from now on. `layout` None = both of the
    area's boards; `area_id` None = every shown area (hidden ones get theirs
    when they're shown)."""
    if area_id is None:
        areas = [a for a in data.areas if not a.hidden and a.filled]
    else:
        area = next((a for a in data.areas if a.id == area_id), None)
        if area is None:
            raise ops.ModelError(f"no area '{area_id}'")
        areas = [area]
    ctx = _ctx(hass, data, found)
    sections: set[str] = {ops.SECTION_AREAS}
    for area in areas:
        first, items = _area_items(hass, data, area, ctx)
        for lay in [layout] if layout else list(LAYOUTS):
            sections |= _fill(hass, data, area, lay, first, items)
        if not area.edited:
            # every board automatic: it starts on 6x3 when 5x2 can't hold all of it
            area.layout = "5x2" if (1 if first else 0) + len(items) <= LAYOUTS["5x2"] else "6x3"
    return sections


def _marker_entity(hass: HomeAssistant, data: RoomTilesData, area: Area) -> str | None:
    lights = area_lights_entity(hass, data, area)
    if lights:
        return lights[0]
    members = arealights.resolve(hass, area, arealights.lights_by_area(hass))
    return members[0] if len(members) == 1 else None


def fill_defaults(hass: HomeAssistant, data: RoomTilesData, found: dict[str, Any]) -> set[str]:
    """Fill every area not filled yet; the changed sections."""
    # hidden in Room Tiles: left empty until it's shown (then it's filled)
    todo = [a for a in data.areas if not a.filled and not a.hidden]
    if not todo:
        return set()
    ctx = _ctx(hass, data, found)
    sections: set[str] = {ops.SECTION_AREAS}
    for area in todo:
        first, items = _area_items(hass, data, area, ctx)
        placed: dict[str, Item] = {}
        for layout, count in LAYOUTS.items():
            if all(t.kind == KIND_BLANK for t in area.tiles[layout]):
                area.tiles[layout] = default_board(first, items, count)
                placed.update((it[0], it) for it in board_items(first, items, count))
        if placed and area.layout is None:
            # it starts on 6x3 when 5x2 can't hold all of it
            fits = (1 if first else 0) + len(items) <= LAYOUTS["5x2"]
            area.layout = "5x2" if fits else "6x3"
        for eid, kind, name, _ in placed.values():
            sections.update(ops.catalog_add(data, eid, kind, name)[0])
        sections.update(_place_marker(hass, data, area))
        area.filled = True
    return sections


def _place_marker(hass: HomeAssistant, data: RoomTilesData, area: Area) -> set[str]:
    """The area's lights marker in its square on a generated map."""
    eid = _marker_entity(hass, data, area)
    if not eid:
        return set()
    for m in data.maps:
        if not m.generated:
            continue
        zone = next((z for z in m.zones if z.area == area.id and not z.vacuum), None)
        if zone is None or any(mk.map == m.id and mk.entity == eid for mk in data.markers):
            continue
        xs = [p[0] for p in zone.points]
        ys = [p[1] for p in zone.points]
        # below the middle: the room's name sits in the middle
        x, y = (min(xs) + max(xs)) / 2, min(ys) + (max(ys) - min(ys)) * 0.68
        sections = set(ops.add_marker(data, m.id, eid, round(x, 1), round(y, 1))[0])
        lights = area_lights_entity(hass, data, area)
        if lights and lights[0] == eid:
            # its short name: "<Area> Lights" (not "...(Room Tiles)")
            sections.update(ops.catalog_add(data, eid, lights[1], lights[2], short_name=short_lights(area))[0])
        return sections
    return set()


def short_lights(area: Area) -> str:
    """An area's lights' short name: "<Area> Area Lights" by the usual
    shortening ("Ella's Ofc Area", "Kit Area Lights") - from the area's
    short name, so the room reads the same as on its board; "Area" says it's
    the whole room's lights (also Short names' Suggest for them)."""
    from .shortnames import suggest

    return suggest(wording.t("names.area_lights_short", area=area.short_name or area.name), wording.language())[0]
