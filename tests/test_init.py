"""Config flow, first setup and the area-registry sync, inside a test HA."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import floor_registry as fr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.room_tiles.const import DOMAIN


async def _setup(hass, data=None):
    entry = MockConfigEntry(domain=DOMAIN, data=data or {})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_config_flow_picks_areas(hass: HomeAssistant) -> None:
    areas = ar.async_get(hass)
    kitchen = areas.async_create("Kitchen")
    areas.async_create("Cameras")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"areas": [kitchen.id], "auto_add_areas": True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"areas": [kitchen.id], "auto_add_areas": True}
    # the closing message: how many areas, a link into the dashboard
    assert result["description_placeholders"] == {"areas": "1", "url": "/room-tiles"}


async def test_single_instance(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT


async def test_first_setup_uses_choices_and_floor_maps(hass: HomeAssistant) -> None:
    floors = fr.async_get(hass)
    down = floors.async_create("Downstairs", level=0)
    up = floors.async_create("Upstairs", level=1)
    areas = ar.async_get(hass)
    kitchen = areas.async_create("Kitchen", floor_id=down.floor_id)
    bedroom = areas.async_create("Bedroom", floor_id=up.floor_id)
    garage = areas.async_create("Garage")
    cameras = areas.async_create("Cameras")

    entry = await _setup(
        hass, {"areas": [kitchen.id, bedroom.id, garage.id], "auto_add_areas": False}
    )
    data = entry.runtime_data.data
    shown = {a.id: a for a in data.areas if not a.hidden}
    assert set(shown) == {kitchen.id, bedroom.id, garage.id}
    assert data.area(cameras.id).hidden  # unticked: present but hidden
    assert shown[kitchen.id].floor == down.floor_id
    assert [m.name for m in data.maps] == ["Downstairs", "Upstairs", "Other"]
    assert data.map_for_area(kitchen.id)[0].name == "Downstairs"
    assert data.map_for_area(cameras.id) is None  # hidden areas get no square


async def test_no_choices_means_all_areas(hass: HomeAssistant) -> None:
    ar.async_get(hass).async_create("Kitchen")
    entry = await _setup(hass)
    assert [a.hidden for a in entry.runtime_data.data.areas] == [False]


async def test_registry_sync(hass: HomeAssistant) -> None:
    areas = ar.async_get(hass)
    kitchen = areas.async_create("Kitchen")
    den = areas.async_create("Den")
    entry = await _setup(hass)
    data = entry.runtime_data.data
    home = data.maps[0]
    assert home.generated

    # renamed in HA -> follows
    areas.async_update(kitchen.id, name="Cook room")
    await hass.async_block_till_done()
    assert entry.runtime_data.data.area(kitchen.id).name == "Cook room"

    # new area, auto-add off -> hidden, no square
    porch = areas.async_create("Porch")
    await hass.async_block_till_done()
    data = entry.runtime_data.data
    assert data.area(porch.id).hidden
    assert data.map_for_area(porch.id) is None

    # deleted in HA -> removed, its zone unlinked
    areas.async_delete(den.id)
    await hass.async_block_till_done()
    data = entry.runtime_data.data
    assert data.area(den.id) is None
    assert all(z.area != den.id for m in data.maps for z in m.zones)


async def test_auto_add_new_area_gets_a_square(hass: HomeAssistant) -> None:
    areas = ar.async_get(hass)
    areas.async_create("Kitchen")
    entry = await _setup(hass, {"auto_add_areas": True})
    attic = areas.async_create("Attic")
    await hass.async_block_till_done()
    data = entry.runtime_data.data
    assert not data.area(attic.id).hidden
    assert data.map_for_area(attic.id) is not None


async def test_setup_keeps_existing_data(hass: HomeAssistant, hass_storage) -> None:
    kitchen = ar.async_get(hass).async_create("Kitchen")
    hass_storage[DOMAIN] = {
        "version": 1,
        "minor_version": 1,
        "key": DOMAIN,
        "data": {
            "areas": [{"id": kitchen.id, "name": "Old name", "short_name": "K"}],
            "maps": [{"id": "home", "name": "Home", "bounds": [0, 0, 10, 10]}],
        },
    }
    entry = await _setup(hass, {"areas": [], "auto_add_areas": False})
    data = entry.runtime_data.data
    assert [(a.id, a.name, a.short_name) for a in data.areas] == [(kitchen.id, "Kitchen", "K")]
    assert [m.id for m in data.maps] == ["home"]


async def test_removing_room_tiles_starts_fresh_with_a_backup(hass: HomeAssistant, hass_storage) -> None:
    """Removed: its data goes (a copy in room_tiles_backups/), its entities
    and sidebar entry go; added again, it starts like a new install."""
    import os
    import shutil

    from homeassistant.helpers import entity_registry as er

    areas = ar.async_get(hass)
    kitchen = areas.async_create("Kitchen")
    entry = await _setup(hass)
    entry.runtime_data.data.area(kitchen.id).short_name = "Kitch"
    entry.runtime_data.async_changed()
    await entry.runtime_data.async_save_now()
    assert "room_tiles" in hass_storage  # (the test HA keeps storage in memory)
    # (no frontend in the test HA: the sidebar entry isn't checked here)
    # a stand-in for the file on disk, for the backup copy
    store_file = hass.config.path(".storage", "room_tiles")
    os.makedirs(os.path.dirname(store_file), exist_ok=True)
    with open(store_file, "w") as f:
        f.write('{"data": {}}')
    backups_dir = hass.config.path("room_tiles_backups")
    try:
        assert await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()
        assert "room_tiles" not in hass_storage
        assert any(b.startswith("removed-") for b in os.listdir(backups_dir))
    finally:
        os.remove(store_file) if os.path.isfile(store_file) else None
        shutil.rmtree(backups_dir, ignore_errors=True)
    assert not [e for e in er.async_get(hass).entities.values() if e.platform == DOMAIN]

    again = await _setup(hass)
    assert again.runtime_data.data.area(kitchen.id).short_name != "Kitch"  # fresh
