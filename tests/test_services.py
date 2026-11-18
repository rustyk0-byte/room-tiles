"""room_tiles.export_data / import_data."""

import json
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import area_registry as ar
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.room_tiles.const import DOMAIN


@pytest.fixture
async def entry(hass: HomeAssistant):
    ar.async_get(hass).async_create("Kitchen")
    e = MockConfigEntry(domain=DOMAIN)
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    return e


async def _call(hass, service, **data):
    return await hass.services.async_call(DOMAIN, service, data, blocking=True, return_response=True)


async def test_export_then_import_round_trip(hass: HomeAssistant, entry) -> None:
    res = await _call(hass, "export_data", file="rt.json")
    path = Path(res["file"])
    doc = json.loads(path.read_text())
    assert [a["name"] for a in doc["areas"]] == ["Kitchen"]

    doc["areas"][0]["short_name"] = "Cook"
    doc["areas"].append({"id": "not_in_ha", "name": "Ghost"})
    path.write_text(json.dumps(doc))
    res = await _call(hass, "import_data", file="rt.json")
    assert res["areas"] == 1  # the area HA doesn't have was dropped
    assert entry.runtime_data.data.areas[0].short_name == "Cook"
    backup = json.loads(Path(res["backup"]).read_text())
    assert backup["areas"][0]["short_name"] == "Kitchen"


async def test_invalid_import_changes_nothing(hass: HomeAssistant, entry) -> None:
    Path(hass.config.path("bad.json")).write_text(json.dumps({"markers": [{"id": "m", "map": "nowhere", "entity": "light.x", "x": 1, "y": 1}]}))
    with pytest.raises(ServiceValidationError, match="not valid Room Tiles data"):
        await _call(hass, "import_data", file="bad.json")
    assert entry.runtime_data.data.areas[0].name == "Kitchen"


async def test_missing_and_non_json_files(hass: HomeAssistant, entry) -> None:
    with pytest.raises(ServiceValidationError, match="not found"):
        await _call(hass, "import_data", file="nope.json")
    Path(hass.config.path("text.json")).write_text("not json")
    with pytest.raises(ServiceValidationError, match="not valid JSON"):
        await _call(hass, "import_data", file="text.json")


async def test_paths_outside_config_refused(hass: HomeAssistant, entry) -> None:
    with pytest.raises(ServiceValidationError, match="inside the config folder"):
        await _call(hass, "export_data", file="../escape.json")


async def test_actions_refuse_without_setup(hass: HomeAssistant) -> None:
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError, match="not set up"):
        await _call(hass, "export_data")


async def test_import_trims_file_name_and_refreshes_area_lights(hass: HomeAssistant, entry) -> None:
    res = await _call(hass, "export_data", file="rt.json")
    doc = json.loads(Path(res["file"]).read_text())
    doc["areas"][0]["lights"] = "light.group"
    Path(res["file"]).write_text(json.dumps(doc))
    hass.states.async_set("light.group", "off")
    await _call(hass, "import_data", file="  rt.json  ")
    area_id = doc["areas"][0]["id"]
    assert entry.runtime_data.area_lights[area_id] == ["light.group"]


async def test_a_removal_copy_imports(hass: HomeAssistant, entry) -> None:
    """Undo a removal: the copy Room Tiles kept (HA's storage file, maybe
    from an older version) goes back in with import - unwrapped, migrated."""
    fixture = Path(__file__).parent / "fixtures" / "storage" / "v1.2.json"
    Path(hass.config.path("removed-old.json")).write_text(fixture.read_text())
    res = await _call(hass, "import_data", file="removed-old.json")
    assert res["maps"] >= 1 and res["markers"] >= 1
    stored = json.loads(fixture.read_text())
    newer = {**stored, "version": 2}
    Path(hass.config.path("removed-newer.json")).write_text(json.dumps(newer))
    with pytest.raises(ServiceValidationError, match="another Room Tiles"):
        await _call(hass, "import_data", file="removed-newer.json")


async def test_backups_keep_the_newest_few(hass: HomeAssistant, entry) -> None:
    import os

    from custom_components.room_tiles.backups import KEEP

    import shutil

    folder = Path(hass.config.path("room_tiles_backups"))
    shutil.rmtree(folder, ignore_errors=True)  # (the test HA's config folder is shared)
    folder.mkdir()
    for i in range(KEEP + 3):
        f = folder / f"removed-2026010{i}.json"
        f.write_text("{}")
        os.utime(f, (1_000_000 + i, 1_000_000 + i))
    (folder / "mine.json").write_text("{}")  # (not Room Tiles': left alone)
    await _call(hass, "export_data", file="rt.json")
    await _call(hass, "import_data", file="rt.json")  # (writes a before-import copy)
    await _call(hass, "import_data", file="rt.json")
    names = sorted(f.name for f in folder.iterdir())
    removed = [n for n in names if n.startswith("removed-")]
    assert removed == [f"removed-2026010{i}.json" for i in range(3, KEEP + 3)]  # the newest KEEP
    assert len([n for n in names if n.startswith("before-import-")]) == 2
    assert "mine.json" in names
    shutil.rmtree(folder, ignore_errors=True)
