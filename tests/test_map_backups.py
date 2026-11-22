"""Map backups (Map settings > Backups), inside a test HA."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import area_registry as ar
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.room_tiles import map_backups
from custom_components.room_tiles.const import DOMAIN


@pytest.fixture
async def entry(hass: HomeAssistant):
    ar.async_get(hass).async_create("Kitchen")
    e = MockConfigEntry(domain=DOMAIN)
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    return e


async def _call(hass, service, response=False, **data):
    return await hass.services.async_call(DOMAIN, service, data, blocking=True, return_response=response)


async def _yard(hass, entry) -> str:
    yard = (await _call(hass, "add_map", response=True, name="Yard"))["map"]
    await _call(hass, "set_map", map=yard, walls=[[0, 0, 50, 0]], bounds=[0, 0, 60, 40])
    layer = entry.runtime_data.data.map(yard).layers[0].id
    await _call(hass, "set_markers", map=yard, markers=[{"entity": "light.porch", "x": 10, "y": 5, "layer": layer}])
    return yard


async def test_backup_and_restore(hass: HomeAssistant, entry) -> None:
    yard = await _yard(hass, entry)
    first = (await _call(hass, "backup_map", response=True, map=yard))["backup"]
    # a big change: the drawing and the markers
    await _call(hass, "set_map", map=yard, walls=[], name="Garden")
    await _call(hass, "set_markers", map=yard, markers=[])
    listed = (await _call(hass, "map_backups", response=True, map=yard))["backups"]
    assert [(b["id"], b["auto"], b["markers"]) for b in listed] == [(first, False, 1)]

    before = (await _call(hass, "restore_map_backup", response=True, backup=first))["before"]
    data = entry.runtime_data.data
    m = data.map(yard)
    assert m.walls == [(0.0, 0.0, 50.0, 0.0)] and m.name == "Garden"  # (the name is a setting: it stays)
    assert [mk.entity for mk in data.markers if mk.map == yard] == ["light.porch"]
    # the map as it was is backed up first: restoring that undoes the restore
    listed = (await _call(hass, "map_backups", response=True, map=yard))["backups"]
    assert {b["id"]: b["auto"] for b in listed} == {first: False, before: True}
    await _call(hass, "restore_map_backup", backup=before)
    data = entry.runtime_data.data
    assert data.map(yard).walls == [] and not [mk for mk in data.markers if mk.map == yard]


async def test_delete_limit_and_map_removed(hass: HomeAssistant, entry) -> None:
    yard = await _yard(hass, entry)
    ids = [(await _call(hass, "backup_map", response=True, map=yard))["backup"] for _ in range(map_backups.MAX_PER_MAP + 2)]
    kept = [b["id"] for b in entry.runtime_data.map_backups.of_map(yard)]
    assert len(kept) == map_backups.MAX_PER_MAP and set(ids[:2]).isdisjoint(kept)  # (the oldest went)
    await _call(hass, "delete_map_backup", backup=kept[0])
    assert kept[0] not in [b["id"] for b in entry.runtime_data.map_backups.of_map(yard)]
    with pytest.raises(ServiceValidationError, match="no map backup"):
        await _call(hass, "restore_map_backup", backup=kept[0])
    await _call(hass, "remove_map", map=yard)
    assert entry.runtime_data.map_backups.of_map(yard) == []


async def test_restore_drops_links_to_gone_maps(hass: HomeAssistant, entry) -> None:
    yard = await _yard(hass, entry)
    shed = (await _call(hass, "add_map", response=True, name="Shed"))["map"]
    await _call(hass, "set_map", map=yard, links=[{"to": shed, "at": [5, 5]}])
    b = (await _call(hass, "backup_map", response=True, map=yard))["backup"]
    await _call(hass, "remove_map", map=shed)
    await _call(hass, "restore_map_backup", backup=b)
    assert entry.runtime_data.data.map(yard).links == []
