"""Storage migrations."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.room_tiles.const import DOMAIN, STORAGE_MINOR_VERSION
from custom_components.room_tiles.migrate import migrate, migrate_1_1_to_1_2
from custom_components.room_tiles.model import RoomTilesData

V1_1 = {
    "areas": [
        {
            "id": "office",
            "name": "Robin's Office",
            "ha_area": "office",
            "tiles": {
                "5x2": [
                    {"kind": "dimmable_light", "entity": "light.main", "name": "Robin's Main Light"},
                    {"kind": "dimmable_light", "entity": "light.desk", "name": "Desk"},
                    {"kind": "onoff_light", "entity": "light.shelf", "name": "Shelf Lights"},
                    {"kind": "map", "name": "Map"},
                    None,
                ]
            },
        }
    ],
    "maps": [{"id": "home", "name": "Home", "bounds": [0, 0, 10, 10]}],
    "catalog": {
        "entries": [
            {"entity": "light.main", "kind": "dimmable_light", "name": "Robin's Main Light"},
            {"entity": "light.shelf", "kind": "onoff_light", "name": "Shelf Lights"},
        ]
    },
}


def test_1_1_to_1_2():
    doc = migrate_1_1_to_1_2(V1_1)
    data = RoomTilesData.from_dict(doc)
    a = data.areas[0]
    assert a.short_name == "Robin's Office" and not a.review
    names = [t.name for t in a.tiles["5x2"][:4]]
    # too long -> dropped; own name kept; same as catalog -> dropped; map -> dropped
    assert names == [None, "Desk", None, None]
    main = data.catalog.get("light.main")
    assert len(main.short_name) <= 15 and main.review
    shelf = data.catalog.get("light.shelf")
    assert (shelf.short_name, shelf.review) == ("Shelf Lights", False)
    assert "ha_area" not in doc["areas"][0]
    assert V1_1["areas"][0]["ha_area"] == "office"  # input untouched


def test_migrate_chain():
    assert migrate(1, STORAGE_MINOR_VERSION, {"x": 1}, STORAGE_MINOR_VERSION) == {"x": 1}
    doc = migrate(1, 1, V1_1, STORAGE_MINOR_VERSION)
    RoomTilesData.from_dict(doc)


async def test_store_loads_old_data(hass: HomeAssistant, hass_storage) -> None:
    office = ar.async_get(hass).async_create("Robin's Office")
    v = dict(V1_1)
    v["areas"] = [dict(V1_1["areas"][0], id=office.id)]
    hass_storage[DOMAIN] = {"version": 1, "minor_version": 1, "key": DOMAIN, "data": v}
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    data = entry.runtime_data.data
    assert data.area(office.id).tiles["5x2"][1].name is None  # tiles show their short name (1.8)
    assert data.catalog.get("light.main").review


# ---- every stored version ever released keeps loading ---------------------------

import json  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

FIXTURES = sorted((Path(__file__).parent / "fixtures" / "storage").glob("v*.json"))


def test_a_fixture_for_the_current_version():
    assert f"v1.{STORAGE_MINOR_VERSION}.json" in {f.name for f in FIXTURES}


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_migrates_and_loads(path):
    stored = json.loads(path.read_text())
    doc = migrate(stored["version"], stored["minor_version"], stored["data"], STORAGE_MINOR_VERSION)
    data = RoomTilesData.from_dict(doc)
    assert data.areas and data.maps


async def test_old_data_is_copied_before_migrating(hass: HomeAssistant, hass_storage) -> None:
    stored = json.loads((Path(__file__).parent / "fixtures" / "storage" / "v1.1.json").read_text())
    hass_storage[DOMAIN] = stored
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    copies = list(Path(hass.config.path("room_tiles_backups")).glob("before-migration-v1.1-*.json"))
    # (as HA stores it, with its version: the import action takes it back)
    assert any(json.loads(c.read_text()) == {**stored, "key": "room_tiles"} for c in copies)


async def test_newer_minor_data_loads_in_this_version(hass: HomeAssistant, hass_storage) -> None:
    """A downgrade: data written by a later Room Tiles (higher minor version,
    fields this version doesn't know) must still load."""
    stored = json.loads((Path(__file__).parent / "fixtures" / "storage" / f"v1.{STORAGE_MINOR_VERSION}.json").read_text())
    newer = json.loads(json.dumps(stored))
    newer["minor_version"] = STORAGE_MINOR_VERSION + 5
    newer["data"]["future_section"] = {"anything": True}
    newer["data"]["areas"][0]["future_field"] = 42
    newer["data"]["markers"][0]["future_flag"] = "x"
    office = ar.async_get(hass).async_create("Robin's Office")
    old_id = newer["data"]["areas"][0]["id"]
    newer["data"]["areas"][0]["id"] = office.id
    for z in newer["data"]["maps"][0]["zones"]:
        if z.get("area") == old_id:
            z["area"] = office.id
    hass_storage[DOMAIN] = newer
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.data.area(office.id).short_name == "Office"



def test_1_3_to_1_4_layers():
    from custom_components.room_tiles.migrate import migrate_1_3_to_1_4

    doc = migrate_1_3_to_1_4(
        {
            "maps": [{"id": "h", "name": "H", "bounds": [0, 0, 10, 10]}],
            "markers": [
                {"id": "a", "map": "h", "entity": "light.a", "x": 1, "y": 1, "detail": True},
                {"id": "b", "map": "h", "entity": "light.b", "x": 1, "y": 1, "detail": False},
            ],
        }
    )
    assert [m["layer"] for m in doc["markers"]] == ["rooms", "house"]
    assert "detail" not in doc["markers"][0]
    assert [lay["id"] for lay in doc["maps"][0]["layers"]] == ["house", "rooms"]
    RoomTilesData.from_dict(doc)



def test_1_4_to_1_5_drops_groups():
    from custom_components.room_tiles.migrate import migrate_1_4_to_1_5

    doc = migrate_1_4_to_1_5(
        {
            "markers": [{"id": "a", "map": "h", "entity": "light.a", "x": 1, "y": 1, "group": "light.g"}],
            "catalog": {"entries": [{"entity": "light.a", "kind": "onoff_light", "short_name": "A", "group": "light.g"}]},
        }
    )
    assert "group" not in doc["markers"][0] and "group" not in doc["catalog"]["entries"][0]


def test_1_8_tiles_lose_their_own_names():
    from custom_components.room_tiles.migrate import migrate_1_7_to_1_8

    doc = {"areas": [{"id": "y", "tiles": {"5x2": [{"kind": "onoff_light", "entity": "light.a", "name": "Front Yard"}, {"kind": "map", "name": "Map"}, None]}}]}
    out = migrate_1_7_to_1_8(doc)
    grid = out["areas"][0]["tiles"]["5x2"]
    assert "name" not in grid[0] and grid[1]["name"] == "Map"


def test_1_9_layers_get_an_end():
    """Layers now show from their start to their own end (several at once);
    each but the last ends where the next starts - the maps look as before."""
    from custom_components.room_tiles.migrate import migrate_1_8_to_1_9

    doc = {"maps": [{"layers": [{"id": "rooms", "name": "Rooms", "min_zoom": 2.0}, {"id": "house", "name": "House", "min_zoom": 1.0}]}]}
    layers = {lay["id"]: lay for lay in migrate_1_8_to_1_9(doc)["maps"][0]["layers"]}
    assert layers["house"]["max_zoom"] == 2.0 and layers["rooms"]["max_zoom"] is None


def test_1_10_existing_boards_count_as_changed():
    """Boards made before 1.10 can't tell whether the user changed them:
    a filled area's boards count as changed (no automatic tiles added)."""
    from custom_components.room_tiles.migrate import migrate_1_9_to_1_10

    doc = {"areas": [{"id": "a", "filled": True}, {"id": "b", "filled": False}]}
    out = {a["id"]: a["edited"] for a in migrate_1_9_to_1_10(doc)["areas"]}
    assert out == {"a": ["5x2", "6x3"], "b": []}
