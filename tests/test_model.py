"""Data model: round trips and validation."""

import pytest

from custom_components.room_tiles.const import LAYOUTS
from custom_components.room_tiles.model import (
    Area,
    ModelError,
    RoomTilesData,
    Tile,
)


def _doc():
    return {
        "areas": [
            {
                "id": "kitchen",
                "name": "Kitchen",
                "floor": "ground",
                "short_name": "Cook",
                "lights": "light.kitchen_lights",
                "tiles": {
                    "5x2": [
                        {"kind": "dimmable_light", "entity": "light.counter", "name": "Bench"},
                        None,
                        {"kind": "map"},
                    ]
                },
            }
        ],
        "maps": [
            {
                "id": "ground",
                "name": "Ground floor",
                "bounds": [0, 0, 400, 240],
                "walls": [[0, 0, 400, 0]],
                "shapes": [{"style": "water", "points": [[10, 10], [50, 10], [30, 40]]}],
                "zones": [
                    {
                        "id": "kitchen",
                        "name": "Kitchen",
                        "area": "kitchen",
                        "points": [[0, 0], [100, 0], [100, 100], [0, 100]],
                    }
                ],
            }
        ],
        "markers": [
            {"id": "m1", "map": "ground", "entity": "light.counter", "x": 50, "y": 50}
        ],
        "catalog": {
            "entries": [
                {"entity": "light.counter", "kind": "dimmable_light", "short_name": "Counter"}
            ]
        },
    }


def test_round_trip():
    data = RoomTilesData.from_dict(_doc())
    again = RoomTilesData.from_dict(data.as_dict())
    assert again.as_dict() == data.as_dict()


def test_grids_padded_to_layout_size():
    area = RoomTilesData.from_dict(_doc()).areas[0]
    for layout, count in LAYOUTS.items():
        assert len(area.tiles[layout]) == count
    assert area.tiles["5x2"][0].entity == "light.counter"
    assert area.tiles["5x2"][1].kind == "blank"
    assert area.tiles["6x3"][17].kind == "blank"


def test_blank_tile_serialises_as_none():
    assert Tile().as_dict() is None


def test_map_for_area():
    data = RoomTilesData.from_dict(_doc())
    found = data.map_for_area("kitchen")
    assert found is not None
    assert found[0].id == "ground"
    assert found[1].id == "kitchen"
    assert data.map_for_area("garage") is None


def test_empty_document():
    data = RoomTilesData.from_dict(None)
    assert data.areas == [] and data.maps == [] and data.markers == []


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["areas"].append(dict(d["areas"][0])), "duplicate area"),
        (lambda d: d["markers"][0].update(map="attic"), "unknown map"),
        (lambda d: d["maps"][0]["zones"][0].update(area="garage"), "unknown area"),
        (
            lambda d: d["maps"][0].update(links=[{"to": "attic", "at": [1, 1]}]),
            "unknown map",
        ),
        (lambda d: d["maps"][0].update(bounds=[0, 0, 0, 10]), "bounds are empty"),
        (
            lambda d: d["areas"][0]["tiles"]["5x2"].append({"kind": "fan"}),
            "needs an entity",
        ),
        (
            lambda d: d["areas"][0]["tiles"]["5x2"].append({"kind": "toaster", "entity": "x.y"}),
            "unknown tile kind",
        ),
        (
            lambda d: d["maps"][0]["shapes"].append({"style": "lava", "points": [[0, 0], [1, 0], [0, 1]]}),
            "unknown shape style",
        ),
    ],
)
def test_validation_errors(mutate, message):
    doc = _doc()
    mutate(doc)
    with pytest.raises(ModelError, match=message):
        RoomTilesData.from_dict(doc)


def test_area_defaults():
    a = Area(id="x", name="X")
    assert all(t.kind == "blank" for grid in a.tiles.values() for t in grid)


def test_area_display_name_and_settings():
    data = RoomTilesData.from_dict(_doc())
    assert data.areas[0].short_name == "Cook"
    assert data.areas[0].floor == "ground"
    assert data.settings.auto_add_areas is False
    doc = _doc()
    doc["settings"] = {"auto_add_areas": True}
    assert RoomTilesData.from_dict(doc).settings.auto_add_areas is True
    assert data.settings.auto_update_panels is True  # (panels update by themselves unless turned off)
    doc["settings"] = {"auto_update_panels": False}
    assert RoomTilesData.from_dict(doc).settings.auto_update_panels is False


def test_short_names_default_and_limits():
    from custom_components.room_tiles.model import Area, CatalogEntry

    a = Area(id="b", name="Master Bathroom Closet")
    assert len(a.short_name) <= 15 and a.review is True
    assert Area(id="k", name="Kitchen").short_name == "Kitchen"
    assert Area(id="k", name="Kitchen").review is False
    doc = _doc()
    doc["catalog"]["entries"][0]["short_name"] = "x" * 16
    with pytest.raises(ModelError, match="longer than 15"):
        RoomTilesData.from_dict(doc)
    doc = _doc()
    del doc["catalog"]["entries"][0]["short_name"]
    with pytest.raises(ModelError, match="needs a short name"):
        RoomTilesData.from_dict(doc)
    doc = _doc()
    doc["areas"][0]["tiles"]["5x2"][0]["name"] = "y" * 16
    with pytest.raises(ModelError, match="longer than 15"):
        RoomTilesData.from_dict(doc)


def test_zone_label_vertical_round_trip():
    from custom_components.room_tiles.model import Zone

    z = Zone.from_dict({"id": "h", "name": "Hall", "points": [[0, 0], [1, 0], [1, 9]], "label_vertical": True})
    assert z.label_vertical and Zone.from_dict(z.as_dict()).label_vertical
    assert not Zone.from_dict({"id": "k", "name": "K", "points": [[0, 0], [1, 0], [1, 1]]}).label_vertical



def test_separate_pool_and_spa_cannot_share_one_heater():
    import pytest

    from custom_components.room_tiles.model import ModelError, PoolSystem

    base = {
        "id": "p",
        "name": "Pool & Spa",
        "layout": "separate",
        "pool": {"temp": "sensor.a", "heater": "climate.h", "pump": "switch.a"},
        "spa": {"temp": "sensor.b", "heater": "climate.h", "pump": "switch.b"},
    }
    with pytest.raises(ModelError, match="share one heater"):
        PoolSystem.from_dict(base)
    ok = {**base, "pool": {**base["pool"], "heater": None}}
    assert PoolSystem.from_dict(ok).spa.heater == "climate.h"
