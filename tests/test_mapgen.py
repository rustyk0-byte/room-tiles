"""Generated maps."""

from custom_components.room_tiles.mapgen import (
    AreaInfo,
    FloorInfo,
    add_area_zone,
    generate_maps,
    grid_shape,
)
from custom_components.room_tiles.model import RoomTilesData


def _areas(n, floor=None):
    return [AreaInfo(id=f"a{i}", name=f"Area {i}", floor=floor) for i in range(n)]


def test_grid_shape_landscape():
    cols, rows = grid_shape(10)
    assert cols * rows >= 10
    assert cols > rows  # landscape like the panels


def test_no_floors_one_home_map():
    maps = generate_maps(_areas(7), [])
    assert [m.id for m in maps] == ["home"]
    assert len(maps[0].zones) == 7
    assert all(z.area == z.id for z in maps[0].zones)
    assert maps[0].generated


def test_one_map_per_floor_in_level_order_plus_other():
    floors = [FloorInfo("up", "Upstairs", 1), FloorInfo("down", "Downstairs", 0)]
    areas = _areas(3, "up") + [AreaInfo("k", "Kitchen", "down"), AreaInfo("y", "Yard", None)]
    maps = generate_maps(areas, floors)
    assert [m.id for m in maps] == ["down", "up", "other"]
    assert maps[0].ha_floor == "down"
    assert [z.area for z in maps[2].zones] == ["y"]


def test_floor_without_areas_gets_no_map():
    floors = [FloorInfo("up", "Upstairs", 1), FloorInfo("down", "Downstairs", 0)]
    maps = generate_maps([AreaInfo("k", "Kitchen", "down")], floors)
    assert [m.id for m in maps] == ["down"]


def test_zones_inside_bounds_and_not_overlapping():
    m = generate_maps(_areas(11), [])[0]
    x0, y0, x1, y1 = m.bounds
    boxes = []
    for z in m.zones:
        xs = [p[0] for p in z.points]
        ys = [p[1] for p in z.points]
        assert min(xs) >= x0 and max(xs) <= x1 and min(ys) >= y0 and max(ys) <= y1
        boxes.append((min(xs), min(ys), max(xs), max(ys)))
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def test_add_area_keeps_existing_squares():
    m = generate_maps(_areas(4), [])[0]
    before = [list(z.points) for z in m.zones]
    add_area_zone(m, AreaInfo("new", "New room"))
    assert [list(z.points) for z in m.zones[:4]] == before
    assert m.zones[-1].area == "new"
    # still a valid map
    RoomTilesData.from_dict(
        {"areas": [{"id": z.area, "name": z.name} for z in m.zones], "maps": [m.as_dict()]}
    )


def test_add_area_grows_full_grid():
    m = generate_maps(_areas(6), [])[0]
    old_h = m.bounds[3]
    for i in range(10):
        add_area_zone(m, AreaInfo(f"n{i}", f"N{i}"))
    assert len(m.zones) == 16
    assert m.bounds[3] > old_h
    assert len({z.id for z in m.zones}) == 16


def test_add_area_ignores_drawn_maps_and_duplicates():
    m = generate_maps(_areas(2), [])[0]
    add_area_zone(m, AreaInfo("a0", "Area 0"))
    assert len(m.zones) == 2
    m.generated = False
    add_area_zone(m, AreaInfo("x", "X"))
    assert len(m.zones) == 2


def test_floors_past_the_map_limit_share_other():
    from custom_components.room_tiles.const import MAX_MAPS

    floors = [FloorInfo(f"f{i}", f"Floor {i}", i) for i in range(MAX_MAPS + 2)]
    areas = [AreaInfo(f"a{i}", f"Area {i}", f"f{i}") for i in range(MAX_MAPS + 2)]
    maps = generate_maps(areas, floors)
    assert len(maps) == MAX_MAPS
    assert maps[-1].id == "other"
    assert [z.area for z in maps[-1].zones] == [f"a{i}" for i in range(MAX_MAPS - 1, MAX_MAPS + 2)]


def test_generated_rooms_connect_like_a_floor_plan():
    """Rooms share walls; doorways join every room to the next in its row and
    each row to the next; a front door in the outer wall."""
    m = generate_maps(_areas(5), [])[0]  # e.g. 3 + 2
    # each room's square, from its label (a room with a bay window steps out of it)
    boxes = sorted((z.label[0] - 50, z.label[1] - 50) for z in m.zones)
    xs = sorted({x for x, _ in boxes})
    assert all(b - a == 100 for a, b in zip(xs, xs[1:]))  # touching, no gap
    assert m.walls and m.openings
    # every room reachable from the first through doorways
    cells = {((x - 24) // 100, (y - 24) // 100) for x, y in boxes}

    def door_between(a, b):
        (c0, r0), (c1, r1) = a, b
        for x0, y0, x1, y1 in m.openings:
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            if r0 == r1 and abs(mx - (24 + max(c0, c1) * 100)) < 1 and 24 + r0 * 100 < my < 24 + (r0 + 1) * 100:
                return True
            if c0 == c1 and abs(my - (24 + max(r0, r1) * 100)) < 1 and 24 + c0 * 100 < mx < 24 + (c0 + 1) * 100:
                return True
        return False

    seen, todo = set(), [min(cells)]
    while todo:
        c = todo.pop()
        if c in seen:
            continue
        seen.add(c)
        for n in ((c[0] + 1, c[1]), (c[0] - 1, c[1]), (c[0], c[1] + 1), (c[0], c[1] - 1)):
            if n in cells and door_between(c, n):
                todo.append(n)
    assert seen == cells
    # a front door: an opening on the bottom outer wall
    bottom = max(y0 for _, y0, _, _ in m.walls)
    assert any(abs(y0 - bottom) < 1 and abs(y1 - bottom) < 1 for _, y0, _, y1 in m.openings)


def test_added_room_gets_walls_and_a_doorway():
    m = generate_maps(_areas(3), [])[0]
    before = len(m.openings)
    add_area_zone(m, AreaInfo("new", "New"))
    assert len(m.openings) > before


def test_outdoor_areas_go_beside_the_house_unwalled():
    from custom_components.room_tiles.mapgen import outdoor_kind

    assert outdoor_kind("Back Garden") == "grass"
    assert outdoor_kind("Pool Deck") == "water"  # first match wins
    assert outdoor_kind("Front Porch") == "deck"
    assert outdoor_kind("Terraza") == "deck"
    assert outdoor_kind("Gardener's Room") is None  # whole words only
    assert outdoor_kind("Kitchen") is None

    areas = [AreaInfo("k", "Kitchen"), AreaInfo("l", "Living Room"), AreaInfo("y", "Backyard"), AreaInfo("p", "Pool")]
    m = generate_maps(areas, [])[0]
    zones = {z.area: z for z in m.zones}
    house_right = max(p[0] for a in ("k", "l") for p in zones[a].points)
    assert zones["y"].outdoor and zones["p"].outdoor and not zones["k"].outdoor
    assert min(p[0] for p in zones["y"].points) > house_right  # beside the house
    # no walls round the outdoor areas
    yard_x0 = min(p[0] for p in zones["y"].points)
    assert all(max(x0, x1) <= house_right + 1 for x0, _, x1, _ in m.walls)
    assert sorted(s.style for s in m.shapes) == ["grass", "paving", "water"]

    add_area_zone(m, AreaInfo("g", "Garden"))
    add_area_zone(m, AreaInfo("b", "Bedroom"))
    zones = {z.area: z for z in m.zones}
    assert zones["g"].outdoor and min(p[0] for p in zones["g"].points) >= yard_x0
    assert not zones["b"].outdoor and max(p[0] for p in zones["b"].points) <= house_right


def test_starter_map_shows_off_shapes():
    """A bay window on one room's outside wall (windows, its outline stepping
    out), a lawn with a cut corner, an octagonal pool."""
    areas = [AreaInfo(f"r{i}", n) for i, n in enumerate(["Kitchen", "Living Room", "Hall", "Bedroom", "Backyard", "Pool"])]
    m = generate_maps(areas, [])[0]
    living = next(z for z in m.zones if z.name == "Living Room")
    assert len(living.points) == 8 and min(p[1] for p in living.points) < 24  # out past the outer wall
    assert len(m.windows) == 3
    lawn = next(z for z in m.zones if z.name == "Backyard")
    assert len(lawn.points) == 5
    assert len(next(s for s in m.shapes if s.style == "water").points) == 8
    # still a valid map, and adding a room keeps the bay
    add_area_zone(m, AreaInfo("new", "Study"))
    assert len(m.windows) == 3
    RoomTilesData.from_dict({"areas": [{"id": z.area, "name": z.name} for z in m.zones], "maps": [m.as_dict()]})
