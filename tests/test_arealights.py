"""Area Lights: worked out from HA's registries, following HA's changes."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.room_tiles import ops
from custom_components.room_tiles.const import DOMAIN
from custom_components.room_tiles.model import RoomTilesData


@pytest.fixture
async def setup(hass: HomeAssistant):
    """Kitchen with: a light of its own, a light via its device, a hidden
    light, a config (settings) light; Den with one light."""
    areas = ar.async_get(hass)
    kitchen = areas.async_create("Kitchen")
    den = areas.async_create("Den")
    ents = er.async_get(hass)
    devs = dr.async_get(hass)
    owner = MockConfigEntry(domain="test")
    owner.add_to_hass(hass)
    dev = devs.async_get_or_create(config_entry_id=owner.entry_id, identifiers={("test", "d1")})
    devs.async_update_device(dev.id, area_id=kitchen.id)

    def light(uid, **kw):
        e = ents.async_get_or_create("light", "test", uid, config_entry=owner, **kw)
        hass.states.async_set(e.entity_id, "off")
        return e.entity_id

    own = light("own")
    ents.async_update_entity(own, area_id=kitchen.id)
    via_device = light("dev", device_id=dev.id)
    hidden = light("hidden")
    ents.async_update_entity(hidden, area_id=kitchen.id, hidden_by=er.RegistryEntryHider.USER)
    backlight = light("backlight", entity_category=er.EntityCategory.CONFIG)
    ents.async_update_entity(backlight, area_id=kitchen.id)
    den_light = light("den")
    ents.async_update_entity(den_light, area_id=den.id)

    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return {
        "entry": entry, "store": entry.runtime_data, "kitchen": kitchen.id, "den": den.id,
        "own": own, "via_device": via_device, "den_light": den_light, "ents": ents,
    }


async def _call(hass, service, **data):
    await hass.services.async_call(DOMAIN, service, data, blocking=True)
    await hass.async_block_till_done()


async def test_default_set_follows_ha_rules(hass: HomeAssistant, setup) -> None:
    lights = setup["store"].area_lights[setup["kitchen"]]
    # own + via device; not the hidden one, not the settings (config) one
    assert lights == sorted([setup["own"], setup["via_device"]])


async def test_exclude_and_override(hass: HomeAssistant, setup) -> None:
    k = setup["kitchen"]
    await _call(hass, "set_area_lights", area=k, exclude=[setup["via_device"]])
    assert setup["store"].area_lights[k] == [setup["own"]]
    await _call(hass, "set_area_lights", area=k, entity=setup["den_light"])
    assert setup["store"].area_lights[k] == [setup["den_light"]]
    await _call(hass, "set_area_lights", area=k, entity="")
    assert setup["store"].area_lights[k] == [setup["own"]]  # exclusion kept


async def test_toggle_action(hass: HomeAssistant, setup) -> None:
    on = async_mock_service(hass, "homeassistant", "turn_on")
    off = async_mock_service(hass, "homeassistant", "turn_off")
    k = setup["kitchen"]
    await _call(hass, "area_lights", area=k)  # all off -> on
    assert sorted(on[0].data["entity_id"]) == sorted([setup["own"], setup["via_device"]])
    hass.states.async_set(setup["own"], "on")
    await _call(hass, "area_lights", area=k)  # any on -> off
    assert len(off) == 1
    with pytest.raises(ServiceValidationError, match="no area"):
        await _call(hass, "area_lights", area="attic")


async def test_new_light_in_area_is_included(hass: HomeAssistant, setup) -> None:
    e = setup["ents"].async_get_or_create("light", "test", "new")
    setup["ents"].async_update_entity(e.entity_id, area_id=setup["kitchen"])
    await hass.async_block_till_done()
    assert e.entity_id in setup["store"].area_lights[setup["kitchen"]]


async def test_moved_light_drops_its_exclusion(hass: HomeAssistant, setup) -> None:
    k = setup["kitchen"]
    await _call(hass, "set_area_lights", area=k, exclude=[setup["own"]])
    setup["ents"].async_update_entity(setup["own"], area_id=setup["den"])
    await hass.async_block_till_done()
    store = setup["store"]
    assert store.data.area(k).lights_exclude == []
    assert setup["own"] in store.area_lights[setup["den"]]
    # moved back: included again
    setup["ents"].async_update_entity(setup["own"], area_id=k)
    await hass.async_block_till_done()
    assert setup["own"] in store.area_lights[k]


async def test_rename_follows_everywhere(hass: HomeAssistant, setup) -> None:
    store = setup["store"]
    k = setup["kitchen"]
    await _call(hass, "set_area_lights", area=k, exclude=[setup["own"]])
    await _call(hass, "set_tile", area=k, layout="5x2", slot=0, entity=setup["own"], kind="dimmable_light")
    setup["ents"].async_update_entity(setup["own"], new_entity_id="light.renamed")
    await hass.async_block_till_done()
    assert store.data.area(k).lights_exclude == ["light.renamed"]
    assert store.data.area(k).tiles["5x2"][0].entity == "light.renamed"


async def test_deleted_override_falls_back_and_tells(hass: HomeAssistant, setup) -> None:
    """Deleting the override entity: the area falls back to all its lights,
    and the removal notice lists it."""
    from unittest.mock import patch

    store = setup["store"]
    k = setup["kitchen"]
    await _call(hass, "set_area_lights", area=k, entity=setup["den_light"])
    with patch("homeassistant.components.persistent_notification.async_create") as notify:
        setup["ents"].async_remove(setup["den_light"])
        hass.states.async_remove(setup["den_light"])
        await hass.async_block_till_done()
    assert store.data.area(k).lights is None
    assert setup["den_light"] not in store.area_lights[k]
    assert "area lights" in notify.call_args.args[1]  # (worded: wording/en.json removed.area_lights)
    assert "Room Tiles removed it from" in notify.call_args.args[1]


async def test_vanished_override_without_delete_event_is_reported(hass: HomeAssistant, setup) -> None:
    """An override entity that simply isn't there any more (no registry
    entry, no state - e.g. a YAML group removed) still falls back + Repairs."""
    store = setup["store"]
    k = setup["kitchen"]
    hass.states.async_set("light.yaml_group", "off")
    await _call(hass, "set_area_lights", area=k, entity="light.yaml_group")
    hass.states.async_remove("light.yaml_group")
    setup["ents"].async_update_entity(setup["own"], name="nudge")  # any registry change re-checks
    await hass.async_block_till_done()
    assert store.data.area(k).lights is None
    assert ir.async_get(hass).async_get_issue(DOMAIN, "area_lights_override_removed")


async def test_missing_entity_issue(hass: HomeAssistant, setup) -> None:
    k = setup["kitchen"]
    await _call(hass, "set_tile", area=k, layout="5x2", slot=1, entity="fan.gone", kind="fan")
    setup["ents"].async_update_entity(setup["own"], name="nudge")  # any registry change re-checks
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "missing_entities")
    assert issue is not None
    assert "fan.gone" in issue.translation_placeholders["entities"]


def test_ops_rename_and_references():
    d = RoomTilesData.from_dict(
        {
            "areas": [{"id": "k", "name": "Kitchen", "lights": "light.a", "lights_exclude": ["light.a"],
                       "tiles": {"5x2": [{"kind": "onoff_light", "entity": "light.a"}]}}],
            "maps": [{"id": "h", "name": "House", "bounds": [0, 0, 1, 1]}],
            "markers": [{"id": "m", "map": "h", "entity": "light.a", "x": 0, "y": 0}],
            "catalog": {"entries": [{"entity": "light.a", "kind": "onoff_light", "short_name": "A"}], "hidden": ["light.a"]},
        }
    )
    assert set(ops.rename_entity(d, "light.a", "light.b")) == {"areas", "markers", "catalog"}
    assert "light.a" not in str(d.as_dict())
    assert set(ops.referenced_entities(d)) == {"light.b"}
    assert ops.rename_entity(d, "light.zzz", "light.y") == ()


async def test_deleted_entity_is_removed_everywhere_and_reported(hass: HomeAssistant, setup) -> None:
    from unittest.mock import patch

    store = setup["store"]
    k = setup["kitchen"]
    own = setup["own"]
    await _call(hass, "set_tile", area=k, layout="5x2", slot=0, entity=own, kind="dimmable_light")
    await _call(hass, "add_marker", map=store.data.maps[0].id, entity=own, x=1, y=1)
    with patch("homeassistant.components.persistent_notification.async_create") as notify:
        setup["ents"].async_remove(own)
        await hass.async_block_till_done()
    assert store.data.area(k).tiles["5x2"][0].kind == "blank"
    assert not any(m.entity == own for m in store.data.markers)
    assert notify.called
    assert "Room Tiles removed it from" in notify.call_args.args[1]


async def test_disabled_entity_is_kept_but_reported(hass: HomeAssistant, setup) -> None:
    store = setup["store"]
    k = setup["kitchen"]
    own = setup["own"]
    await _call(hass, "set_tile", area=k, layout="5x2", slot=0, entity=own, kind="dimmable_light")
    setup["ents"].async_update_entity(own, disabled_by=er.RegistryEntryDisabler.USER)
    await hass.async_block_till_done()
    assert store.data.area(k).tiles["5x2"][0].entity == own  # kept
    assert own in store.disabled
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "missing_entities")
    assert issue is None or own not in issue.translation_placeholders["entities"]
    setup["ents"].async_update_entity(own, disabled_by=None)
    await hass.async_block_till_done()
    assert own not in store.disabled


async def test_light_groups_are_not_area_lights_and_none_has_none(hass: HomeAssistant, setup) -> None:
    """The area's lights are its INDIVIDUAL lights (a group only repeats
    them); "None" (light_entity off): no lights at all."""
    from homeassistant.helpers import entity_registry as er

    from custom_components.room_tiles import arealights

    data = setup["store"].data
    area = data.area(setup["kitchen"])
    reg = er.async_get(hass)
    grp = MockConfigEntry(domain="group")
    grp.add_to_hass(hass)
    reg.async_get_or_create("light", "group", "g1", suggested_object_id="all_of_them", config_entry=grp)
    reg.async_update_entity("light.all_of_them", area_id=area.id)
    index = arealights.lights_by_area(hass)
    assert "light.all_of_them" not in index.get(area.id, [])
    area.light_entity = False
    assert arealights.resolve(hass, area, index) == []


async def test_a_screens_backlight_is_not_an_area_light(hass: HomeAssistant, setup) -> None:
    """A wall panel's backlight is a light entity in the room - but switching
    it off blanks the panel: never one of the area's lights."""
    from custom_components.room_tiles import arealights

    ents = setup["ents"]
    before = arealights.lights_by_area(hass).get(setup["kitchen"], [])
    owner = MockConfigEntry(domain="esphome")
    owner.add_to_hass(hass)
    added = []
    for uid, name in (("panel_bl", "Backlight"), ("old_bl", "LCD Backlight")):
        e = ents.async_get_or_create("light", "esphome", uid, config_entry=owner, original_name=name)
        ents.async_update_entity(e.entity_id, area_id=setup["kitchen"])
        hass.states.async_set(e.entity_id, "on")
        added.append(e.entity_id)
    kitchen = arealights.lights_by_area(hass).get(setup["kitchen"], [])
    assert setup["own"] in kitchen
    assert kitchen == before
    assert not set(added) & set(kitchen)
