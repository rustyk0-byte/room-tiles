"""Edit operations (pure model)."""

import pytest

from custom_components.room_tiles import ops
from custom_components.room_tiles.model import CatalogEntry, Link, ModelError, RoomTilesData


TWO_LAYERS = [{"id": "house", "name": "House", "min_zoom": 1}, {"id": "rooms", "name": "Rooms", "min_zoom": 1.7}]


def _data():
    return RoomTilesData.from_dict(
        {
            "areas": [{"id": "kitchen", "name": "Kitchen"}],
            "maps": [{"id": "house", "name": "House", "bounds": [0, 0, 100, 100], "layers": TWO_LAYERS},
                     {"id": "yard", "name": "Yard", "bounds": [0, 0, 50, 50], "layers": TWO_LAYERS}],
            "catalog": {"entries": [{"entity": "light.counter", "kind": "dimmable_light", "short_name": "Counter"}]},
        }
    )


def test_set_tile_from_catalog():
    d = _data()
    assert ops.set_tile(d, "kitchen", "5x2", 3, entity="light.counter") == ("areas",)
    t = d.area("kitchen").tiles["5x2"][3]
    assert (t.kind, t.entity, t.name) == ("dimmable_light", "light.counter", None)  # None = catalog's


def test_set_tile_overrides_and_uncatalogued_entity():
    d = _data()
    ops.set_tile(d, "kitchen", "6x3", 17, entity="light.counter", name="Bench")
    assert d.area("kitchen").tiles["6x3"][17].name == "Bench"
    with pytest.raises(ModelError, match="not in the catalog"):
        ops.set_tile(d, "kitchen", "5x2", 0, entity="fan.attic")
    ops.set_tile(d, "kitchen", "5x2", 0, entity="fan.attic", kind="fan")
    assert d.area("kitchen").tiles["5x2"][0].name is None
    with pytest.raises(ModelError, match="longer than 15"):
        ops.set_tile(d, "kitchen", "5x2", 0, entity="light.counter", name="A very long tile name")


def test_map_tile_and_clear():
    d = _data()
    ops.set_tile(d, "kitchen", "5x2", 1, kind="map")
    t = d.area("kitchen").tiles["5x2"][1]
    assert (t.kind, t.entity, t.name) == ("map", None, None)
    ops.clear_tile(d, "kitchen", "5x2", 1)
    assert d.area("kitchen").tiles["5x2"][1].kind == "blank"


@pytest.mark.parametrize(
    "args, message",
    [
        (("attic", "5x2", 0), "no area"),
        (("kitchen", "4x4", 0), "layout must be"),
        (("kitchen", "5x2", 10), "slot must be 0-9"),
        (("kitchen", "6x3", -1), "slot must be 0-17"),
    ],
)
def test_set_tile_refusals(args, message):
    with pytest.raises(ModelError, match=message):
        ops.set_tile(_data(), *args, entity="light.counter")


def test_set_tile_needs_entity_for_entity_kinds():
    with pytest.raises(ModelError, match="needs an entity"):
        ops.set_tile(_data(), "kitchen", "5x2", 0, kind="fan")


def test_move_tile_swaps():
    d = _data()
    ops.set_tile(d, "kitchen", "5x2", 0, entity="light.counter")
    ops.move_tile(d, "kitchen", "5x2", 0, 9)
    grid = d.area("kitchen").tiles["5x2"]
    assert grid[0].kind == "blank" and grid[9].entity == "light.counter"


def test_markers_add_update_remove():
    d = _data()
    sections, mid = ops.add_marker(d, "house", "light.counter", 10, 20, layer="rooms")
    assert sections == ("markers",)
    m = d.markers[0]
    assert (m.id, m.x, m.y, m.layer, m.show_name) == (mid, 10.0, 20.0, "rooms", False)

    ops.update_marker(d, mid, x=11, y="12", show_name=1, map="yard")
    m = d.markers[0]
    assert (m.x, m.y, m.show_name, m.map) == (11.0, 12.0, True, "yard")

    ops.remove_marker(d, mid)
    assert d.markers == []


def test_marker_refusals():
    d = _data()
    with pytest.raises(ModelError, match="no map"):
        ops.add_marker(d, "attic", "light.counter", 0, 0)
    with pytest.raises(ModelError, match="entity id"):
        ops.add_marker(d, "house", "counter", 0, 0)
    _, mid = ops.add_marker(d, "house", "light.counter", 0, 0, marker_id="m1")
    with pytest.raises(ModelError, match="already exists"):
        ops.add_marker(d, "house", "light.counter", 0, 0, marker_id="m1")
    with pytest.raises(ModelError, match="no map"):
        ops.update_marker(d, mid, map="attic")
    with pytest.raises(ModelError, match="can't change"):
        ops.update_marker(d, mid, entity="light.other")
    with pytest.raises(ModelError, match="no marker"):
        ops.update_marker(d, "nope", x=1)
    with pytest.raises(ModelError, match="no marker"):
        ops.remove_marker(d, "nope")


def test_set_short_name():
    d = _data()
    d.catalog.entries[0].review = True
    assert ops.set_short_name(d, "  Bench  Light ", entity="light.counter") == ("catalog",)
    e = d.catalog.entries[0]
    assert (e.short_name, e.review) == ("Bench Light", False)
    assert ops.set_short_name(d, "Cook", area_id="kitchen") == ("areas",)
    assert d.area("kitchen").short_name == "Cook"
    for kwargs, msg in [
        (dict(short_name="x" * 16, area_id="kitchen"), "longer than 15"),
        (dict(short_name=" ", area_id="kitchen"), "can't be empty"),
        (dict(short_name="X"), "either an area or an entity"),
        (dict(short_name="X", area_id="kitchen", entity="light.counter"), "either an area or an entity"),
        (dict(short_name="X", entity="fan.nope"), "not in the catalog"),
        (dict(short_name="X", area_id="attic"), "no area"),
    ]:
        with pytest.raises(ModelError, match=msg):
            ops.set_short_name(d, **kwargs)


def test_flag_short_names_width_only():
    d = _data()
    # shared short names are fine (told apart by area / map position)
    d.catalog.entries.append(CatalogEntry(entity="light.other", kind="onoff_light", short_name="Counter"))
    d.catalog.entries.append(CatalogEntry(entity="light.wide", kind="onoff_light", short_name="WWWWWWWWWWWWW"))
    assert ops.flag_short_names(d)
    flagged = {e.entity for e in d.catalog.entries if e.review}
    assert flagged == {"light.wide"}
    assert [x[1] for x in ops.needs_review(d)] == ["light.wide"]
    assert not ops.flag_short_names(d)  # nothing new


def test_marker_layers():
    d = _data()
    _, mid = ops.add_marker(d, "house", "light.counter", 1, 1)
    assert d.markers[0].layer == "house"  # the map's first layer by default
    with pytest.raises(ModelError, match="no layer"):
        ops.add_marker(d, "house", "light.counter", 1, 1, layer="attic")
    ops.update_marker(d, mid, layer="rooms")
    assert d.markers[0].layer == "rooms"
    with pytest.raises(ModelError, match="no layer"):
        ops.update_marker(d, mid, layer="attic")
    assert [lay.id for lay in d.map("house").layers] == ["house", "rooms"]



def test_an_entity_may_have_many_markers():
    """Several placements of one entity: on several layers, and several times
    in one layer - each a marker with its own position."""
    d = _data()
    ops.add_marker(d, "house", "light.counter", 1, 1, layer="house")
    ops.add_marker(d, "house", "light.counter", 5, 5, layer="house")
    ops.add_marker(d, "house", "light.counter", 9, 9, layer="rooms")
    d.validate()
    assert [(m.layer, m.x) for m in d.markers if m.entity == "light.counter"] == [("house", 1.0), ("house", 5.0), ("rooms", 9.0)]


def test_catalog_add_and_remove():
    d = _data()
    sections, e = ops.catalog_add(d, "light.master_bathroom_niche", "dimmable_light", "Master Bathroom Niche")
    assert sections == ("catalog",)
    assert len(e.short_name) <= 15 and e.review is True  # shortened -> review
    _, e2 = ops.catalog_add(d, "fan.den", "fan", "Den Fan")
    assert (e2.short_name, e2.review) == ("Den Fan", False)
    assert ops.catalog_add(d, "fan.den", "fan", "Other")[0] == ()  # already there: unchanged
    with pytest.raises(ModelError, match="longer than 15"):
        ops.catalog_add(d, "fan.x", "fan", "X", short_name="A very long short name")
    with pytest.raises(ModelError, match="not a tile kind"):
        ops.catalog_add(d, "fan.x", "map", "X")
    ops.catalog_remove(d, "fan.den")
    assert d.catalog.get("fan.den") is None
    with pytest.raises(ModelError, match="not in the catalog"):
        ops.catalog_remove(d, "fan.den")


def test_set_area_hide_and_order():
    d = RoomTilesData.from_dict({"areas": [{"id": a, "name": a} for a in "abc"]})
    ops.set_area(d, "c", position=0)
    assert [a.id for a in d.areas] == ["c", "a", "b"]
    ops.set_area(d, "c", position=99)
    assert [a.id for a in d.areas] == ["a", "b", "c"]
    ops.set_area(d, "b", hidden=True)
    assert d.area("b").hidden
    with pytest.raises(ModelError, match="no area"):
        ops.set_area(d, "z", hidden=True)


def test_infer_kind():
    from custom_components.room_tiles.kinds import infer_kind

    assert infer_kind("light.a", {"supported_color_modes": ["hs", "color_temp"]}) == "color_light"
    assert infer_kind("light.a", {"supported_color_modes": ["brightness"]}) == "dimmable_light"
    assert infer_kind("light.a", {"supported_color_modes": ["onoff"]}) == "onoff_light"
    assert infer_kind("sensor.dishwasher_tile", {"tile": "Upper|idle|...|plate|"}) == "appliance"
    assert infer_kind("sensor.temp", {}) is None
    assert infer_kind("lock.front", None) == "lock"
    assert infer_kind("scene.movie_time", {}) == "scene"
    assert infer_kind("script.goodnight", {}) == "script"


def test_forget_entity_removes_it_everywhere():
    d = RoomTilesData.from_dict(
        {
            "areas": [{"id": "k", "name": "Kitchen", "lights": "light.a", "lights_exclude": ["light.a"],
                       "tiles": {"5x2": [{"kind": "onoff_light", "entity": "light.a"}, {"kind": "map"}],
                                 "6x3": [{"kind": "onoff_light", "entity": "light.a"}]}}],
            "maps": [{"id": "h", "name": "House", "bounds": [0, 0, 1, 1]}],
            "markers": [{"id": "m1", "map": "h", "entity": "light.a", "x": 0, "y": 0},
                        {"id": "m2", "map": "h", "entity": "light.b", "x": 0, "y": 0}],
            "catalog": {"entries": [{"entity": "light.a", "kind": "onoff_light", "short_name": "A"}]},
        }
    )
    sections, where = ops.forget_entity(d, "light.a")
    assert set(sections) == {"areas", "markers", "catalog"}
    k = d.area("k")
    assert k.tiles["5x2"][0].kind == "blank" and k.tiles["5x2"][1].kind == "map"
    assert k.tiles["6x3"][0].kind == "blank"
    assert k.lights is None and k.lights_exclude == []
    assert [m.id for m in d.markers] == ["m2"]
    assert d.catalog.get("light.a") is None
    assert ("removed.tiles", {"name": "Kitchen", "n": 2}) in where
    assert ("removed.markers", {"name": "House", "n": 1}) in where
    assert ops.forget_entity(d, "light.a") == ((), [])  # nothing left to remove


def test_set_markers_replaces_one_map():
    d = _data()
    ops.add_marker(d, "yard", "light.counter", 1, 1, marker_id="keep-me")
    ops.add_marker(d, "house", "light.counter", 1, 1, marker_id="old")
    ops.set_markers(d, "house", [
        {"id": "old", "entity": "light.counter", "x": 5, "y": 6, "layer": "rooms", "show_name": True},
        {"entity": "fan.den", "x": 7, "y": 8},
    ])
    house = [m for m in d.markers if m.map == "house"]
    assert [(m.id, m.x, m.layer, m.show_name) for m in house][0] == ("old", 5.0, "rooms", True)
    assert house[1].entity == "fan.den" and house[1].layer == "house" and house[1].id
    assert [m.id for m in d.markers if m.map == "yard"] == ["keep-me"]  # other maps untouched
    with pytest.raises(ModelError, match="no layer"):
        ops.set_markers(d, "house", [{"entity": "fan.den", "x": 0, "y": 0, "layer": "attic"}])
    with pytest.raises(ModelError, match="no map"):
        ops.set_markers(d, "attic", [])
    ops.set_markers(d, "house", [])
    assert [m.map for m in d.markers] == ["yard"]


def test_set_map_replaces_the_drawing():
    d = _data()
    ops.add_marker(d, "house", "light.counter", 1, 1, layer="rooms", marker_id="r")
    ops.add_marker(d, "yard", "light.counter", 1, 1, layer="rooms", marker_id="y")
    out = ops.set_map(d, "house", {
        "name": "Ground",
        "walls": [[0, 0, 10, 0]],
        "zones": [{"id": "k", "name": "Kitchen", "points": [[0, 0], [10, 0], [10, 10]], "area": "kitchen"}],
        "layers": [{"id": "house", "name": "House", "min_zoom": 1}],
    })
    m = d.map("house")
    assert (m.name, m.walls, m.generated, m.zones[0].area) == ("Ground", [(0.0, 0.0, 10.0, 0.0)], False, "kitchen")
    assert m.bounds == (0, 0, 100, 100)  # not given: kept
    # the "rooms" layer went: its marker moved to the first layer; other maps untouched
    assert out == ("maps", "markers")
    assert {mk.id: mk.layer for mk in d.markers} == {"r": "house", "y": "rooms"}
    with pytest.raises(ModelError, match="unknown area"):
        ops.set_map(d, "house", {"zones": [{"id": "x", "name": "X", "points": [[0, 0], [1, 0], [1, 1]], "area": "attic"}]})
        d.validate()
    # a room with no name (a closet that's just floor): allowed
    ops.set_map(d, "house", {"zones": [{"id": "c", "name": "", "points": [[0, 0], [1, 0], [1, 1]]}]})
    assert d.map("house").zones[0].name == ""
    with pytest.raises(ModelError, match="unknown map field"):
        ops.set_map(d, "house", {"generated": True})
    # only the bounds refitted (to the markers) / where the layers start
    # (the Layer Editor): still the generated map
    d.map("yard").generated = True
    ops.set_map(d, "yard", {"bounds": [-50, 0, 100, 100]})
    assert (d.map("yard").bounds, d.map("yard").generated) == ((-50, 0, 100, 100), True)
    ops.set_map(d, "yard", {"layers": [{"id": "house", "name": "House", "min_zoom": 1.5}]})
    assert (d.map("yard").layers[0].min_zoom, d.map("yard").generated) == (1.5, True)
    ops.set_map(d, "yard", {"name": "Garden"})
    assert d.map("yard").generated is False
    with pytest.raises(ModelError, match="at least one layer"):
        ops.set_map(d, "house", {"layers": []})
    with pytest.raises(ModelError, match="needs a name"):
        ops.set_map(d, "house", {"name": " "})


def test_add_remove_order_maps():
    d = _data()
    ops.add_marker(d, "yard", "light.counter", 1, 1)
    d.map("house").links = [Link("yard", (1, 1))]
    sections, mid = ops.add_map(d, "Up stairs", "upstairs")
    assert (mid, d.map(mid).ha_floor, d.map(mid).generated) == ("up_stairs", "upstairs", False)
    assert ops.add_map(d, "Up stairs")[1] == "up_stairs_2"
    ops.order_maps(d, ["yard", "up_stairs", "house", "up_stairs_2"])
    assert [m.id for m in d.maps] == ["yard", "up_stairs", "house", "up_stairs_2"]
    with pytest.raises(ModelError, match="every map exactly once"):
        ops.order_maps(d, ["yard"])
    ops.remove_map(d, "yard")
    assert d.markers == [] and d.map("house").links == []
    for mid in ("up_stairs", "up_stairs_2"):
        ops.remove_map(d, mid)
    with pytest.raises(ModelError, match="last map"):
        ops.remove_map(d, "house")


def test_vacuum_zones_follow_their_vacuum():
    d = _data()
    zone = {"id": "bar", "name": "Bar", "points": [[0, 0], [5, 0], [5, 5]], "area": "kitchen", "vacuum": "vacuum.matic"}
    ops.set_map(d, "house", {"zones": [zone]})
    assert d.map("house").zones[0].vacuum == "vacuum.matic"
    assert "House map vacuum zones" in ops.referenced_entities(d)["vacuum.matic"]
    assert ops.rename_entity(d, "vacuum.matic", "vacuum.robot") == ("maps",)
    assert d.map("house").zones[0].vacuum == "vacuum.robot"
    sections, where = ops.forget_entity(d, "vacuum.robot")
    assert sections == ("maps",) and where == [("removed.zones", {"name": "House", "n": 1})]
    assert d.map("house").zones == []
    with pytest.raises(ModelError, match="not a vacuum"):
        ops.set_map(d, "house", {"zones": [{**zone, "vacuum": "light.x"}]})


def test_map_and_layer_limits():
    from custom_components.room_tiles.const import MAX_LAYERS, MAX_MAPS

    d = _data()  # two maps
    for i in range(MAX_MAPS - 2):
        ops.add_map(d, f"Floor {i}")
    with pytest.raises(ModelError, match=f"at most {MAX_MAPS} maps"):
        ops.add_map(d, "One too many")
    too_many = [{"id": f"l{i}", "name": f"L{i}", "min_zoom": 1 + i} for i in range(MAX_LAYERS + 1)]
    with pytest.raises(ModelError, match=f"at most {MAX_LAYERS} layers"):
        ops.set_map(d, "house", {"layers": too_many})
    ops.set_map(d, "house", {"layers": too_many[:MAX_LAYERS]})
    assert len(d.map("house").layers) == MAX_LAYERS


def test_layers_have_a_start_and_an_end():
    d = _data()
    ops.set_map(d, "house", {"layers": [
        {"id": "main", "name": "Main", "min_zoom": 1, "max_zoom": None},
        {"id": "overview", "name": "Overview", "min_zoom": 1, "max_zoom": 3},
        {"id": "rooms", "name": "Rooms", "min_zoom": 3},
    ]})
    ends = {lay.id: lay.max_zoom for lay in d.map("house").layers}
    assert ends == {"main": None, "overview": 3.0, "rooms": None}
    with pytest.raises(ModelError, match="max_zoom must be above"):
        ops.set_map(d, "house", {"layers": [{"id": "x", "name": "X", "min_zoom": 2, "max_zoom": 2}]})


def test_a_new_map_has_one_layer():
    d = _data()
    _, mid = ops.add_map(d, "Attic")
    assert [(lay.id, lay.min_zoom) for lay in d.map(mid).layers] == [("house", 1.0)]


def test_set_short_names():
    d = _data()
    # changed: counted, the catalog section saved; the same again: nothing
    assert ops.set_short_names(d, {"light.counter": ("Ctr Light", True)}) == (("catalog",), 1)
    e = d.catalog.entries[0]
    assert (e.short_name, e.review) == ("Ctr Light", True)
    assert ops.set_short_names(d, {"light.counter": ("Ctr Light", True)}) == ((), 0)
    # an entity not in the catalog is left alone
    assert ops.set_short_names(d, {"fan.attic": ("Attic", False)}) == ((), 0)
