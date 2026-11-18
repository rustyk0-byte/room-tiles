"""Generated maps: one per HA floor, a square room per area.

Used when no floor plan has been drawn (every install starts here) and to add
a room for a new area to a generated map. The rooms are packed edge to edge
like a floor plan - shared walls, an outer wall, doorways between
neighbours (every room in a row opens into the next; each row into the one
below, in the middle) and a front door - nothing like the real home, but it
reads as a floor plan at once. Pure Python, no HA imports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .const import MAX_MAPS
from .model import Map, Shape, Zone
from .wording import t

# Map units of a generated map. A square room is CELL x CELL; rooms touch
# (GAP 0: shared walls). Maps generated before walls had a 12 unit gap.
CELL = 100.0
GAP = 0.0
OLD_GAP = 12.0
MARGIN = 24.0
DOOR = 30.0  # doorway width
OUT_GAP = 40.0  # between the house and its outdoor areas
# a bay window on one room's outside (top) wall, and a lawn with a cut
# corner - to show rooms and areas needn't be rectangles
BAY_IN = 25.0  # from the room's corners to where the bay starts
BAY_SLANT = 10.0
BAY_DEPTH = 18.0
CUT = 35.0  # the lawn's cut corner
BAY_WORDS = ("living", "lounge", "family", "sitting", "den", "salon", "wohnzimmer", "soggiorno", "sala", "woonkamer")

# Outdoor areas, by name (HA areas aren't marked indoor / outdoor): they go
# beside the house, unwalled, filled by kind. Words in the languages Room
# Tiles has rules for; whole words, any case.
OUTDOOR_WORDS: dict[str, tuple[str, ...]] = {
    "water": ("pool", "spa", "hot tub", "piscina", "piscine", "zwembad", "schwimmbad"),
    "paving": ("driveway", "parking", "carport", "entrada", "allée", "einfahrt", "vialetto", "oprit"),
    "deck": (
        "patio", "deck", "decking", "porch", "veranda", "terrace", "balcony", "lanai",
        "terraza", "porche", "balcón", "terrasse", "balcon", "balkon", "terrazza", "balcone",
        "varanda", "terraço", "sacada", "terras", "veranda",
    ),
    "grass": (
        "yard", "backyard", "front yard", "garden", "lawn", "courtyard", "outside", "outdoor",
        "jardín", "jardin", "garten", "hof", "giardino", "cortile", "jardim", "quintal", "tuin", "gazon",
    ),
}


def outdoor_kind(name: str) -> str | None:
    """"water" / "paving" / "deck" / "grass" for an outdoor area's name, else
    None (a room). The first match in that order wins ("Pool Deck": water)."""
    import re

    low = f" {name.lower()} "
    for kind, words in OUTDOOR_WORDS.items():
        if any(re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", low) for w in words):
            return kind
    return None


def _outdoor_shapes(kind: str, x0: float, y0: float, x1: float, y1: float) -> list[Shape]:
    """How an outdoor area looks: grass, decking, paving - a pool is water on
    paving. A little inside its square, so neighbours of the same kind read
    as separate places."""
    x0, y0, x1, y1 = x0 + 3, y0 + 3, x1 - 3, y1 - 3
    box = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if kind == "water":
        # paving round an octagonal pool
        i, c = CELL * 0.18, CELL * 0.12
        a0, b0, a1, b1 = x0 + i, y0 + i, x1 - i, y1 - i
        pool = [(a0 + c, b0), (a1 - c, b0), (a1, b0 + c), (a1, b1 - c), (a1 - c, b1), (a0 + c, b1), (a0, b1 - c), (a0, b0 + c)]
        return [Shape("paving", box), Shape("water", pool)]
    return [Shape(kind, box)]


def _bay_room(m: Map) -> Zone | None:
    """The room that gets the bay window: in the top row, a living room if
    there is one, else the middle one."""
    top = sorted((z for z in m.zones if not z.outdoor and min(p[1] for p in z.points) < MARGIN + 1), key=lambda z: min(p[0] for p in z.points))
    if not top:
        return None
    return next((z for z in top if any(w in z.name.lower() for w in BAY_WORDS)), top[(len(top) - 1) // 2])


def _add_bay(z: Zone) -> None:
    """A bay window on the room's top wall: its outline steps out."""
    x0, y0 = min(p[0] for p in z.points), min(p[1] for p in z.points)
    x1, y1 = x0 + CELL, y0 + CELL
    a, b, top = x0 + BAY_IN, x1 - BAY_IN, y0 - BAY_DEPTH
    z.points = [(x0, y0), (a, y0), (a + BAY_SLANT, top), (b - BAY_SLANT, top), (b, y0), (x1, y0), (x1, y1), (x0, y1)]


def _cut_lawn(m: Map) -> None:
    """The first lawn gets a cut corner (its grass too)."""
    for z in m.zones:
        if z.outdoor and outdoor_kind(z.name) == "grass":
            x0, y0 = min(p[0] for p in z.points), min(p[1] for p in z.points)
            x1, y1 = x0 + CELL, y0 + CELL
            z.points = [(x0, y0), (x1 - CUT, y0), (x1, y0 + CUT), (x1, y1), (x0, y1)]
            for s in m.shapes:
                if s.style == "grass" and min(p[0] for p in s.points) > x0 and min(p[1] for p in s.points) > y0 and max(p[0] for p in s.points) < x1 and max(p[1] for p in s.points) < y1:
                    s.points = [(x0 + 3, y0 + 3), (x1 - CUT - 1, y0 + 3), (x1 - 3, y0 + CUT + 1), (x1 - 3, y1 - 3), (x0 + 3, y1 - 3)]
                    break
            return
# Panels and most tablets are landscape (1024x600); pack the grid toward it.
TARGET_ASPECT = 1024 / 600

OTHER_MAP_ID = "other"
HOME_MAP_ID = "home"


@dataclass(frozen=True)
class AreaInfo:
    """What the generator needs to know about a panel area."""

    id: str
    name: str
    floor: str | None = None


@dataclass(frozen=True)
class FloorInfo:
    """An HA floor. `level` orders floors (lower first); None sorts last."""

    id: str
    name: str
    level: int | None = None


def grid_shape(count: int, aspect: float = TARGET_ASPECT) -> tuple[int, int]:
    """Columns and rows for `count` equal squares, closest to `aspect`."""
    if count <= 0:
        return (1, 1)
    best: tuple[float, int, int] | None = None
    for cols in range(1, count + 1):
        rows = math.ceil(count / cols)
        w = cols * CELL + (cols - 1) * GAP
        h = rows * CELL + (rows - 1) * GAP
        # prefer the aspect match, then fewer empty cells
        score = abs(math.log((w / h) / aspect)) + 0.01 * (cols * rows - count)
        if best is None or score < best[0]:
            best = (score, cols, rows)
    assert best is not None
    return best[1], best[2]


def square_map(map_id: str, name: str, areas: list[AreaInfo], ha_floor: str | None) -> Map:
    """A starter map: the rooms edge to edge behind an outer wall (row by row
    in the given order, doorways between them), and the outdoor areas
    (outdoor_kind) beside the house - open, filled with grass, decking,
    paving or water."""
    indoor = [a for a in areas if outdoor_kind(a.name) is None]
    outdoor = [a for a in areas if outdoor_kind(a.name) is not None]
    cols, rows = grid_shape(len(indoor)) if indoor else (0, 0)
    m = Map(id=map_id, name=name, bounds=(0.0, 0.0, 1.0, 1.0), ha_floor=ha_floor, generated=True)
    for i, a in enumerate(indoor):
        _add_room(m, a, MARGIN + (i % cols) * CELL, MARGIN + (i // cols) * CELL)
    height = max(rows, 2)
    ox = MARGIN + cols * CELL + (OUT_GAP if cols else 0)
    for i, a in enumerate(outdoor):
        _add_room(m, a, ox + (i // height) * CELL, MARGIN + (i % height) * CELL)
    bay = _bay_room(m)
    if bay is not None:
        _add_bay(bay)
    _cut_lawn(m)
    _fit_bounds(m)
    build_walls(m)
    return m


def _add_room(m: Map, a: AreaInfo, x0: float, y0: float) -> None:
    x1, y1 = x0 + CELL, y0 + CELL
    zone_id = a.id
    while any(z.id == zone_id for z in m.zones):
        zone_id += "_"
    kind = outdoor_kind(a.name)
    m.zones.append(
        Zone(
            id=zone_id,
            name=a.name,
            points=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            area=a.id,
            label=((x0 + x1) / 2, (y0 + y1) / 2),
            outdoor=kind is not None,
        )
    )
    if kind is not None:
        m.shapes.extend(_outdoor_shapes(kind, x0, y0, x1, y1))


def _fit_bounds(m: Map) -> None:
    xs = [p[0] for z in m.zones for p in z.points] or [0.0]
    ys = [p[1] for z in m.zones for p in z.points] or [0.0]
    m.bounds = (0.0, 0.0, max(m.bounds[2], max(xs) + MARGIN), max(m.bounds[3], max(ys) + MARGIN))


def _cells(m: Map, pitch: float, outdoor: bool = False) -> set[tuple[int, int]]:
    """Grid cells of the rooms (or, `outdoor`, of the outdoor areas)."""
    return {
        (round((min(p[0] for p in z.points) - MARGIN) / pitch), round((min(p[1] for p in z.points) - MARGIN) / pitch))
        for z in m.zones
        if not z.vacuum and z.outdoor == outdoor
    }


def _with_door(x0: float, y0: float, x1: float, y1: float) -> tuple[list, list]:
    """A wall from (x0, y0) to (x1, y1) with a doorway in its middle: the two
    wall pieces, and the doorway (an opening)."""
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    length = max(abs(x1 - x0), abs(y1 - y0))
    hx, hy = (x1 - x0) / length * DOOR / 2, (y1 - y0) / length * DOOR / 2
    return [(x0, y0, mx - hx, my - hy), (mx + hx, my + hy, x1, y1)], [(mx - hx, my - hy, mx + hx, my + hy)]


def build_walls(m: Map) -> None:
    """The walls and doorways of a generated map, from its rooms (redone
    whenever a room is added)."""
    cells = _cells(m, CELL + GAP)
    walls: list = []
    openings: list = []
    windows: list = []
    # rooms whose outline steps out above their square: a bay window there
    bays = {
        (round((min(p[0] for p in z.points) - MARGIN) / CELL), round((min(p[1] for p in z.points) + BAY_DEPTH - MARGIN) / CELL)): z
        for z in m.zones
        if not z.outdoor and not z.vacuum and len(z.points) > 4
    }
    by_row: dict[int, list[int]] = {}
    for c, r in cells:
        by_row.setdefault(r, []).append(c)
    # one doorway from each row into the next, in the middle of what they share
    down: dict[int, int] = {}
    for r in by_row:
        shared = sorted(set(by_row[r]) & set(by_row.get(r + 1, [])))
        if shared:
            down[r] = shared[(len(shared) - 1) // 2]
    last = max(by_row) if by_row else 0
    front = sorted(by_row.get(last, []))
    front_door = front[(len(front) - 1) // 2] if front else None

    def edge(x0: float, y0: float, x1: float, y1: float, door: bool) -> None:
        if door:
            w, o = _with_door(x0, y0, x1, y1)
            walls.extend(w)
            openings.extend(o)
        else:
            walls.append((x0, y0, x1, y1))

    for c, r in sorted(cells):
        x0, y0 = MARGIN + c * CELL, MARGIN + r * CELL
        x1, y1 = x0 + CELL, y0 + CELL
        # top: an outer wall when there's no room above (shared ones are drawn
        # from above) - with the bay window, if this room has it
        if (c, r - 1) not in cells:
            if (c, r) in bays:
                a, b, top = x0 + BAY_IN, x1 - BAY_IN, y0 - BAY_DEPTH
                walls.extend([(x0, y0, a, y0), (b, y0, x1, y0)])
                windows.extend([(a, y0, a + BAY_SLANT, top), (a + BAY_SLANT, top, b - BAY_SLANT, top), (b - BAY_SLANT, top, b, y0)])
            else:
                edge(x0, y0, x1, y0, False)
        # left: an outer wall when there's no room to the left
        if (c - 1, r) not in cells:
            edge(x0, y0, x0, y1, False)
        # right: shared with the next room in the row (a doorway), or outer
        edge(x1, y0, x1, y1, (c + 1, r) in cells)
        # bottom: shared with the room below (a doorway in one place per row),
        # or outer (the front door in the middle of the last row)
        if (c, r + 1) in cells:
            edge(x0, y1, x1, y1, down.get(r) == c)
        else:
            edge(x0, y1, x1, y1, r == last and c == front_door)
    m.walls = [tuple(float(v) for v in s) for s in walls]
    m.openings = [tuple(float(v) for v in s) for s in openings]
    m.windows = [tuple(float(v) for v in s) for s in windows]


def generate_maps(areas: list[AreaInfo], floors: list[FloorInfo]) -> list[Map]:
    """One generated map per HA floor that has areas, in floor order; areas
    without a floor go on an "Other" map. With no floors at all, a single
    "Home" map holds every area."""
    if not areas:
        return [Map(id=HOME_MAP_ID, name=t("names.map_home"), bounds=(0.0, 0.0, 400.0, 240.0), generated=True)]

    floor_ids = {f.id for f in floors}
    if not any(a.floor in floor_ids for a in areas):
        return [square_map(HOME_MAP_ID, t("names.map_home"), areas, None)]

    ordered = sorted(floors, key=lambda f: (f.level is None, f.level or 0, f.name.lower()))
    with_areas = [f for f in ordered if any(a.floor == f.id for a in areas)]
    # MAX_MAPS: the floors past it share "Other" (always room for that one)
    own = with_areas if len(with_areas) <= MAX_MAPS else with_areas[: MAX_MAPS - 1]
    own_ids = {f.id for f in own}
    maps: list[Map] = []
    for f in own:
        maps.append(square_map(f.id, f.name, [a for a in areas if a.floor == f.id], f.id))
    rest = [a for a in areas if a.floor not in own_ids]
    if rest:
        maps.append(square_map(OTHER_MAP_ID, t("names.map_other"), rest, None))
    return maps


def add_area_zone(m: Map, area: AreaInfo) -> None:
    """Give a GENERATED map a square for one more area: a room in the house's
    next free slot (walls and doorways redrawn), an outdoor area in the next
    free slot beside it. Existing squares never move, so markers placed in
    them stay put; the house grows by a row when full. Drawn maps are left
    alone: the user places the zone in the map editor."""
    if not m.generated or any(z.area == area.id for z in m.zones):
        return
    if not m.walls and not any(z.outdoor for z in m.zones):
        _add_legacy(m, area)  # a map generated before walls
        return
    rooms = _cells(m, CELL)
    cols = max((c for c, _ in rooms), default=-1) + 1
    rows = max((r for _, r in rooms), default=-1) + 1
    ox = MARGIN + cols * CELL + (OUT_GAP if cols else 0)
    if outdoor_kind(area.name) is None:
        if not cols:  # the first room of a map of outdoor areas only: beside them
            out_x = [p[0] for z in m.zones for p in z.points]
            x0 = (max(out_x) + OUT_GAP) if out_x else MARGIN
            _add_room(m, area, x0, MARGIN)
        else:
            i = 0
            while (i % cols, i // cols) in rooms:
                i += 1
            _add_room(m, area, MARGIN + (i % cols) * CELL, MARGIN + (i // cols) * CELL)
    else:
        height = max(rows, 2)
        taken = {(round(min(p[0] for p in z.points)), round(min(p[1] for p in z.points))) for z in m.zones if z.outdoor}
        i = 0
        while (round(ox + (i // height) * CELL), round(MARGIN + (i % height) * CELL)) in taken:
            i += 1
        _add_room(m, area, ox + (i // height) * CELL, MARGIN + (i % height) * CELL)
    _fit_bounds(m)
    build_walls(m)  # the rooms' walls and doorways


def _add_legacy(m: Map, area: AreaInfo) -> None:
    """Maps generated before walls: separate squares with a gap."""
    pitch = CELL + OLD_GAP
    width = m.bounds[2] - m.bounds[0]
    cols = max(1, round((width - 2 * MARGIN + OLD_GAP) / pitch))
    taken = _cells(m, pitch)
    i = 0
    while (i % cols, i // cols) in taken:
        i += 1
    x0 = MARGIN + (i % cols) * pitch
    y0 = MARGIN + (i // cols) * pitch
    zone_id = area.id
    while any(z.id == zone_id for z in m.zones):
        zone_id += "_"
    m.zones.append(
        Zone(
            id=zone_id,
            name=area.name,
            points=[(x0, y0), (x0 + CELL, y0), (x0 + CELL, y0 + CELL), (x0, y0 + CELL)],
            area=area.id,
            label=(x0 + CELL / 2, y0 + CELL / 2),
        )
    )
    m.bounds = (m.bounds[0], m.bounds[1], max(m.bounds[2], x0 + CELL + MARGIN), max(m.bounds[3], y0 + CELL + MARGIN))
