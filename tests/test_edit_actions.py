"""Tile / marker actions and the websocket feed, inside a test HA."""

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


async def _call(hass, service, response=False, **data):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=response
    )


async def test_tile_actions(hass: HomeAssistant, entry) -> None:
    area_id = entry.runtime_data.data.areas[0].id
    await _call(hass, "set_tile", area=area_id, layout="5x2", slot=0, entity="light.counter", kind="dimmable_light", name="Counter")
    await _call(hass, "move_tile", area=area_id, layout="5x2", from_slot=0, to_slot=4)
    grid = entry.runtime_data.data.area(area_id).tiles["5x2"]
    assert grid[4].entity == "light.counter" and grid[0].kind == "blank"
    await _call(hass, "clear_tile", area=area_id, layout="5x2", slot=4)
    assert entry.runtime_data.data.area(area_id).tiles["5x2"][4].kind == "blank"


async def test_refused_edit_changes_nothing(hass: HomeAssistant, entry) -> None:
    before = entry.runtime_data.data.as_dict()
    with pytest.raises(ServiceValidationError, match="not in the catalog"):
        await _call(hass, "set_tile", area=before["areas"][0]["id"], layout="5x2", slot=0, entity="light.unknown")
    with pytest.raises(ServiceValidationError, match="no area"):
        await _call(hass, "clear_tile", area="attic", layout="5x2", slot=0)
    assert entry.runtime_data.data.as_dict() == before


async def test_marker_actions(hass: HomeAssistant, entry) -> None:
    map_id = entry.runtime_data.data.maps[0].id
    res = await _call(hass, "add_marker", response=True, map=map_id, entity="light.counter", x=40, y=50)
    mid = res["marker"]
    await _call(hass, "update_marker", marker=mid, x=41, show_name=True)
    m = entry.runtime_data.data.markers[0]
    assert (m.x, m.y, m.show_name, m.layer) == (41.0, 50.0, True, "house")  # the map's first layer
    await _call(hass, "remove_marker", marker=mid)
    assert entry.runtime_data.data.markers == []


async def test_websocket_feed(hass: HomeAssistant, entry, hass_ws_client) -> None:
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "room_tiles/subscribe"})
    msg = await client.receive_json()
    assert msg["success"]
    msg = await client.receive_json()
    assert msg["event"]["type"] == "full"
    assert msg["event"]["schema"] == 1
    assert set(msg["event"]["data"]) == {"areas", "maps", "markers", "catalog", "settings", "area_lights", "disabled", "vacuums", "appliances", "appliance_found", "appliance_again", "appliance_presets", "pools", "pool_found", "robots", "robot_found", "ignored", "ignored_found", "restart_needed", "version", "dev_build", "panels", "panel_firmware", "recordings", "beta", "themes"}

    area_id = msg["event"]["data"]["areas"][0]["id"]
    await _call(hass, "set_tile", area=area_id, layout="5x2", slot=2, kind="map")
    msg = await client.receive_json()
    assert msg["event"]["type"] == "update"
    assert set(msg["event"]["data"]) == {"areas"}  # only what changed
    assert msg["event"]["data"]["areas"][0]["tiles"]["5x2"][2] == {"kind": "map"}

    map_id = entry.runtime_data.data.maps[0].id
    await _call(hass, "add_marker", response=True, map=map_id, entity="fan.x", x=1, y=2)
    msg = await client.receive_json()
    assert set(msg["event"]["data"]) == {"markers"}

    await hass.config_entries.async_unload(entry.entry_id)
    msg = await client.receive_json()
    assert msg["event"]["type"] == "reset"


async def test_websocket_not_set_up(hass: HomeAssistant, hass_ws_client) -> None:
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "room_tiles/subscribe"})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_set_up"


async def test_set_short_name_action(hass: HomeAssistant, entry) -> None:
    area_id = entry.runtime_data.data.areas[0].id
    await _call(hass, "set_short_name", area=area_id, short_name="Cook")
    assert entry.runtime_data.data.area(area_id).short_name == "Cook"
    with pytest.raises(ServiceValidationError, match="longer than 15"):
        await _call(hass, "set_short_name", area=area_id, short_name="A very long short name")


async def test_review_notification(hass: HomeAssistant) -> None:
    """Short names to review: a notification when new ones come up (not for
    what's waiting at setup), linking to the Short names dialog; gone once
    nothing is waiting. No repair."""
    from unittest.mock import patch

    from homeassistant.helpers import issue_registry as ir

    from custom_components.room_tiles.repairs import ISSUE_SHORT_NAMES, REVIEW_NOTIFICATION

    pn = "homeassistant.components.persistent_notification"
    ar.async_get(hass).async_create("Master Bathroom Closet")
    e = MockConfigEntry(domain=DOMAIN)
    e.add_to_hass(hass)
    with patch(f"{pn}.async_create") as create, patch(f"{pn}.async_dismiss") as dismiss:
        assert await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()
        assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_SHORT_NAMES) is None
        assert not [c for c in create.call_args_list if c.kwargs.get("notification_id") == REVIEW_NOTIFICATION]

        # a new long name comes up: notified, with the link
        hass.states.async_set("light.a", "off", {"friendly_name": "Living Room Floor Lamp Corner"})
        await _call(hass, "catalog_add", entity="light.a")
        await hass.async_block_till_done()
        mine = [c for c in create.call_args_list if c.kwargs.get("notification_id") == REVIEW_NOTIFICATION]
        assert len(mine) == 1 and "/room-tiles?open=short-names" in mine[0].args[1]

        # all reviewed: dismissed
        await _call(hass, "accept_short_names")
        await hass.async_block_till_done()
        assert any(c.args[1:] == (REVIEW_NOTIFICATION,) for c in dismiss.call_args_list)


async def test_catalog_add_action_infers_kind_and_name(hass: HomeAssistant, entry) -> None:
    hass.states.async_set("light.desk_lamp_left", "off", {"supported_color_modes": ["brightness"], "friendly_name": "Desk Lamp Left Side"})
    res = await _call(hass, "catalog_add", response=True, entity="light.desk_lamp_left")
    assert res["kind"] == "dimmable_light"
    assert len(res["short_name"]) <= 15
    again = await _call(hass, "catalog_add", response=True, entity="light.desk_lamp_left")
    assert again["short_name"] == res["short_name"]  # already there
    hass.states.async_set("sensor.outside_temp", "20")
    with pytest.raises(ServiceValidationError, match="no tile"):
        await _call(hass, "catalog_add", entity="sensor.outside_temp")
    await _call(hass, "catalog_remove", entity="light.desk_lamp_left")
    assert entry.runtime_data.data.catalog.get("light.desk_lamp_left") is None


async def test_set_area_action(hass: HomeAssistant, entry) -> None:
    area_id = entry.runtime_data.data.areas[0].id
    await _call(hass, "set_area", area=area_id, hidden=True)
    assert entry.runtime_data.data.area(area_id).hidden
    assert area_id not in entry.runtime_data.area_lights


async def test_set_settings_action(hass: HomeAssistant, entry) -> None:
    await _call(hass, "set_settings", auto_add_areas=True)
    assert entry.runtime_data.data.settings.auto_add_areas is True
    assert entry.runtime_data.data.settings.auto_update_panels is True  # (on by default)
    await _call(hass, "set_settings", auto_update_panels=False)
    assert entry.runtime_data.data.settings.auto_update_panels is False
    assert entry.runtime_data.data.settings.auto_add_areas is True  # (the other one kept)


async def test_map_actions(hass: HomeAssistant, entry) -> None:
    res = await _call(hass, "add_map", response=True, name="Yard")
    yard = res["map"]
    await _call(hass, "set_map", map=yard, walls=[[0, 0, 50, 0]], bounds=[0, 0, 60, 40], name="Back yard")
    m = entry.runtime_data.data.map(yard)
    assert (m.name, m.walls, m.bounds) == ("Back yard", [(0.0, 0.0, 50.0, 0.0)], (0.0, 0.0, 60.0, 40.0))
    with pytest.raises(ServiceValidationError, match="need at least 3 points"):
        await _call(hass, "set_map", map=yard, zones=[{"id": "z", "name": "Z", "points": [[0, 0]]}])
    first = entry.runtime_data.data.maps[0].id
    await _call(hass, "order_maps", order=[yard, first])
    assert entry.runtime_data.data.maps[0].id == yard
    await _call(hass, "remove_map", map=yard)
    assert [m.id for m in entry.runtime_data.data.maps] == [first]


async def test_accept_all_short_names(hass: HomeAssistant, entry) -> None:
    """Accept all: every waiting short name confirmed as it is - except one
    too wide for a tile, which stays waiting (and is reported)."""
    data = entry.runtime_data.data
    hass.states.async_set("light.a", "off", {"friendly_name": "Living Room Floor Lamp Corner"})
    hass.states.async_set("light.b", "off", {"friendly_name": "WWWWWWWWWWWWWWWWWW"})
    await _call(hass, "catalog_add", response=True, entity="light.a")
    await _call(hass, "catalog_add", response=True, entity="light.b", short_name="WWWWWWWWWWWWWWW")
    data = entry.runtime_data.data
    data.catalog.get("light.b").review = True  # (too wide: waiting)
    assert data.catalog.get("light.a").review
    res = await _call(hass, "accept_short_names", response=True)
    data = entry.runtime_data.data
    assert not data.catalog.get("light.a").review
    assert data.catalog.get("light.b").review and res["left"] == ["light.b"]


async def test_accept_all_covers_areas(hass: HomeAssistant, entry) -> None:
    data = entry.runtime_data.data
    area = data.areas[0] if data.areas else None
    if area is None:
        return
    area.review = True
    await _call(hass, "accept_short_names", response=True)
    assert not entry.runtime_data.data.area(area.id).review


async def test_suggest_short_name_changes_nothing(hass: HomeAssistant, entry) -> None:
    """The Short names editor's Suggest: a suggestion from the full name now."""
    hass.states.async_set("light.a", "off", {"friendly_name": "Master Bedroom Lights"})
    await _call(hass, "catalog_add", entity="light.a", short_name="Mine")
    res = await _call(hass, "suggest_short_name", response=True, entity="light.a")
    assert (res["short_name"], res["review"], res["full_name"]) == ("Master Bed Lts", True, "Master Bedroom Lights")
    assert entry.runtime_data.data.catalog.get("light.a").short_name == "Mine"  # untouched
    area = entry.runtime_data.data.areas[0]
    res = await _call(hass, "suggest_short_name", response=True, area=area.id)
    assert res["full_name"] == area.name
    # an area's lights: the rule that named them ("<Area> Area Lights" from
    # the area's short name - not "... (Room Tiles)")
    res = await _call(hass, "suggest_short_name", response=True, entity=f"light.room_tiles_{area.id}_area_lights")
    assert res["short_name"] == "Kit Area Lights"
