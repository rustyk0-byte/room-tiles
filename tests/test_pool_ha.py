"""Pool / spa systems inside a test HA: a sensor per body (shared: one
combined sensor + the Spa Mode switch), the actions, the finder."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.room_tiles.const import DOMAIN

SHARED = {
    "id": "pool",
    "name": "Pool & Spa",
    "preset": "iaqualink",
    "layout": "shared",
    "pool": {"temp": "sensor.pool_temp", "heater": "climate.pool"},
    "spa": {"temp": "sensor.spa_temp", "heater": "climate.spa"},
    "spa_mode": "switch.spa_pump",
    "pump": "switch.pool_pump",
}


@pytest.fixture
async def entry(hass: HomeAssistant):
    e = MockConfigEntry(domain=DOMAIN)
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    return e


async def _call(hass, service, response=False, **data):
    return await hass.services.async_call(DOMAIN, service, data, blocking=True, return_response=response)


async def _spa_mode(hass, on: bool, entity: str = "switch.room_tiles_pool_spa_mode") -> None:
    """Turn Room Tiles' Spa Mode switch on / off through the entity itself:
    the tests mock the switch domain's services to record the RAW switches."""
    from homeassistant.helpers.entity_platform import async_get_platforms

    ent = next(p.entities[entity] for p in async_get_platforms(hass, DOMAIN) if p.domain == "switch" and entity in p.entities)
    await (ent.async_turn_on() if on else ent.async_turn_off())


def _pool_mode(hass, heating=False):
    hass.states.async_set("switch.spa_pump", "off")
    hass.states.async_set("switch.pool_pump", "on")
    hass.states.async_set("sensor.pool_temp", "79")
    hass.states.async_set("sensor.spa_temp", "unknown")
    hass.states.async_set(
        "climate.pool", "heat" if heating else "off", {"temperature": 85, "hvac_action": "heating" if heating else "off"}
    )
    hass.states.async_set("climate.spa", "off", {"temperature": 97, "hvac_action": "off"})


async def test_shared_system_sensors(hass: HomeAssistant, entry) -> None:
    _pool_mode(hass, heating=True)
    await _call(hass, "set_pool", pool=SHARED)
    await hass.async_block_till_done()
    # shared: one Pool / Spa tile + Spa Mode - no tile per body
    assert hass.states.get("sensor.room_tiles_pool_pool") is None
    assert hass.states.get("sensor.room_tiles_pool_spa") is None
    both = hass.states.get("sensor.room_tiles_pool")
    assert both.state == "heating" and both.attributes["mode"] == "pool"
    assert both.attributes["tile"] == "Pool|79|Heating|heating|85|on"
    # its words: the panels and the dashboard put them in their own language
    import json

    assert json.loads(both.attributes["tile_words"]) == {"0.0": {"k": "pool.body.pool"}, "0.2": {"k": "pool.short.heating"}}
    assert json.loads(both.attributes["status_word"]) == [{"k": "pool.heating_to", "p": {"target": "85°"}}, ""]
    assert both.attributes["heater_entity"] == "climate.pool"
    assert hass.states.get("switch.room_tiles_pool_spa_mode").state == "off"
    cat = entry.runtime_data.data.catalog
    assert [cat.get(e).kind for e in ("sensor.room_tiles_pool", "switch.room_tiles_pool_spa_mode")] == ["water", "switch"]
    assert cat.get("switch.room_tiles_pool_spa_mode").short_name == "Spa Mode"

    # spa mode: the switch follows, the combined tile switches to the spa
    hass.states.async_set("switch.spa_pump", "on")
    hass.states.async_set("sensor.pool_temp", "unknown")
    await hass.async_block_till_done()
    assert hass.states.get("switch.room_tiles_pool_spa_mode").state == "on"
    hass.states.async_set("sensor.spa_temp", "96")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.room_tiles_pool").attributes["mode"] == "spa"
    assert hass.states.get("sensor.room_tiles_pool").attributes["tile"].startswith("Spa|96|")


async def test_actions(hass: HomeAssistant, entry) -> None:
    _pool_mode(hass)
    await _call(hass, "set_pool", pool=SHARED)
    await hass.async_block_till_done()
    temps = async_mock_service(hass, "climate", "set_temperature")
    modes = async_mock_service(hass, "climate", "set_hvac_mode")
    on = async_mock_service(hass, "switch", "turn_on")
    off = async_mock_service(hass, "switch", "turn_off")
    # the combined sensor acts on the active body (the pool)
    await _call(hass, "pool_set_target", entity="sensor.room_tiles_pool", temperature=86)
    assert temps[-1].data == {"entity_id": "climate.pool", "temperature": 86.0}
    await _call(hass, "pool_set_heater", entity="sensor.room_tiles_pool", heater=True)
    assert modes[-1].data == {"entity_id": "climate.pool", "hvac_mode": "heat"}
    # Spa Mode on = spa mode; the spa's heater comes along (the setting, on by default)
    n = len(modes)
    k = len(on)
    await _spa_mode(hass, True)
    assert [c.data["entity_id"] for c in on[k:]] == ["switch.spa_pump"]
    assert modes[-1].data == {"entity_id": "climate.spa", "hvac_mode": "heat"} and len(modes) == n + 1
    # setting off: just spa mode
    await _call(hass, "set_pool", pool={**SHARED, "spa_heater_follows": False})
    await hass.async_block_till_done()
    n = len(modes)
    await _call(hass, "pool_set_on", entity="sensor.room_tiles_pool", on=False)  # the active body: the pool
    assert off[-1].data == {"entity_id": "switch.pool_pump"}
    assert len(modes) == n
    # refused while switching
    hass.states.async_set("switch.spa_pump", "on")
    hass.states.async_set("sensor.pool_temp", "unknown")
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError, match="switching"):
        await _call(hass, "pool_set_target", entity="sensor.room_tiles_pool", temperature=100)


async def test_separate_system_has_a_tile_per_body(hass: HomeAssistant, entry) -> None:
    hass.states.async_set("sensor.pool_temp", "79")
    hass.states.async_set("sensor.spa_temp", "96")
    sep = {
        "id": "pool",
        "name": "Pool & Spa",
        "layout": "separate",
        "pool": {"temp": "sensor.pool_temp", "pump": "switch.pool_pump"},
        "spa": {"temp": "sensor.spa_temp", "pump": "switch.spa_pump", "heater": "climate.spa"},
    }
    hass.states.async_set("switch.spa_pump", "off")
    hass.states.async_set("climate.spa", "off", {"temperature": 100, "hvac_action": "off"})
    await _call(hass, "set_pool", pool=sep)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.room_tiles_pool_pool") is not None
    assert hass.states.get("sensor.room_tiles_pool_spa") is not None
    assert hass.states.get("sensor.room_tiles_pool") is None
    assert hass.states.get("switch.room_tiles_pool_spa_mode") is None
    # no Heater switch tiles: the tile's heater button (pool_set_heater)
    assert hass.states.get("switch.room_tiles_pool_spa_heater") is None
    spa = hass.states.get("sensor.room_tiles_pool_spa")
    assert (spa.attributes["has_heater"], spa.attributes["heater_next"]) == (True, "heat")
    # on: the spa's pump first (its setting), then the heater
    on = async_mock_service(hass, "switch", "turn_on")
    modes = async_mock_service(hass, "climate", "set_hvac_mode")
    await _call(hass, "pool_set_heater", entity="sensor.room_tiles_pool_spa", heater=True)
    assert [c.data["entity_id"] for c in on] == ["switch.spa_pump"]
    assert modes[-1].data == {"entity_id": "climate.spa", "hvac_mode": "heat"}
    # chilled last time: back on in cool
    hass.states.async_set("switch.spa_pump", "on")
    hass.states.async_set("climate.spa", "cool", {"temperature": 90, "hvac_action": "cooling"})
    await hass.async_block_till_done()
    hass.states.async_set("climate.spa", "off", {"temperature": 90, "hvac_action": "off"})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.room_tiles_pool_spa").attributes["heater_next"] == "cool"
    await _call(hass, "pool_set_heater", entity="sensor.room_tiles_pool_spa", heater=True)
    assert modes[-1].data == {"entity_id": "climate.spa", "hvac_mode": "cool"}


async def test_edit_and_remove(hass: HomeAssistant, entry) -> None:
    _pool_mode(hass)
    await _call(hass, "set_pool", pool=SHARED)
    await hass.async_block_till_done()
    # pool only: the combined sensor and Spa Mode go, a pool sensor comes
    only = {**SHARED, "layout": "pool", "spa": None, "spa_mode": None, "pump": None, "pool": {**SHARED["pool"], "pump": "switch.pool_pump"}}
    await _call(hass, "set_pool", pool=only)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.room_tiles_pool") is None
    assert hass.states.get("switch.room_tiles_pool_spa_mode") is None
    assert hass.states.get("sensor.room_tiles_pool_pool").state == "off"
    await _call(hass, "remove_pool", pool="pool")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.room_tiles_pool_pool") is None


async def test_bad_shared_system_refused(hass: HomeAssistant, entry) -> None:
    with pytest.raises(ServiceValidationError, match="spa mode switch"):
        await _call(hass, "set_pool", pool={**SHARED, "spa_mode": None})



async def test_single_bodies_offer_only_what_they_have(hass: HomeAssistant, entry) -> None:
    """A pool with a pump and no heater; a spa with a heater and no pump."""
    hass.states.async_set("sensor.pool_temp", "78")
    hass.states.async_set("switch.pool_pump", "on")
    await _call(
        hass,
        "set_pool",
        pool={"id": "p", "name": "Pool", "layout": "pool", "pool": {"temp": "sensor.pool_temp", "pump": "switch.pool_pump"}},
    )
    hass.states.async_set("sensor.spa_temp", "100")
    hass.states.async_set("climate.spa", "heat", {"temperature": 102, "hvac_action": "heating"})
    await _call(
        hass,
        "set_pool",
        pool={"id": "s", "name": "Spa", "layout": "spa", "spa": {"temp": "sensor.spa_temp", "heater": "climate.spa"}},
    )
    await hass.async_block_till_done()
    pool = hass.states.get("sensor.room_tiles_p_pool")
    assert (pool.state, pool.attributes["status"], pool.attributes["has_heater"], pool.attributes["can_turn_on"]) == (
        "on",
        "Pump on",
        False,
        True,
    )
    spa = hass.states.get("sensor.room_tiles_s_spa")
    assert (spa.state, spa.attributes["has_heater"], spa.attributes["can_turn_on"]) == ("heating", True, False)
    assert hass.states.get("sensor.room_tiles_s") is None  # no combined tile without two bodies
    async_mock_service(hass, "switch", "turn_off")
    await _call(hass, "pool_set_on", entity="sensor.room_tiles_p_pool", on=False)  # its pump
    with pytest.raises(ServiceValidationError, match="no heater"):
        await _call(hass, "pool_set_heater", entity="sensor.room_tiles_p_pool", heater=True)
    with pytest.raises(ServiceValidationError, match="no pump"):
        await _call(hass, "pool_set_on", entity="sensor.room_tiles_s_spa", on=True)


async def test_time_to_target_while_heating(hass: HomeAssistant, entry, freezer) -> None:
    """Readings rising while heating give an estimate on the tile and status."""
    _pool_mode(hass)
    hass.states.async_set("switch.spa_pump", "on")
    hass.states.async_set("sensor.pool_temp", "unknown")
    hass.states.async_set("climate.spa", "heat", {"temperature": 100, "hvac_action": "heating"})
    hass.states.async_set("sensor.spa_temp", "90")
    await _call(hass, "set_pool", pool=SHARED)
    await hass.async_block_till_done()
    for temp in (91, 92, 93, 94):
        freezer.tick(180)  # 1° every 3 minutes
        hass.states.async_set("sensor.spa_temp", str(temp))
        await hass.async_block_till_done()
    spa = hass.states.get("sensor.room_tiles_pool")  # combined, in spa mode
    eta = spa.attributes["time_to_target"]
    assert eta is not None and 15 <= eta <= 21  # 6° to go at 1° / 3 min
    assert spa.attributes["status"].startswith("Heating to 100°, ~")
    assert spa.attributes["short"].startswith("Heating\n~")
    # heater off: no estimate
    hass.states.async_set("climate.spa", "off", {"temperature": 100, "hvac_action": "off"})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.room_tiles_pool").attributes["time_to_target"] is None


async def test_temperature_read_from_the_heater(hass: HomeAssistant, entry) -> None:
    """Pentair ScreenLogic: the water temperature is on the thermostat."""
    hass.states.async_set("switch.spa", "off")
    hass.states.async_set("switch.pool", "on")
    hass.states.async_set("climate.pool_heat", "heat", {"current_temperature": 81, "temperature": 84, "hvac_action": "heating"})
    hass.states.async_set("climate.spa_heat", "off", {"current_temperature": 77, "temperature": 101, "hvac_action": "off"})
    await _call(
        hass,
        "set_pool",
        pool={
            "id": "pentair",
            "name": "Pool & Spa",
            "preset": "screenlogic",
            "layout": "shared",
            "pool": {"heater": "climate.pool_heat"},
            "spa": {"heater": "climate.spa_heat"},
            "spa_mode": "switch.spa",
            "pump": "switch.pool",
        },
    )
    await hass.async_block_till_done()
    pool = hass.states.get("sensor.room_tiles_pentair")  # shared: the combined sensor, in pool mode
    assert (pool.state, pool.attributes["temperature"], pool.attributes["target"]) == ("heating", 81, 84)
    assert pool.attributes["mode"] == "pool"



async def test_heater_on_starts_the_pump_by_setting(hass: HomeAssistant, entry) -> None:
    _pool_mode(hass)
    hass.states.async_set("switch.pool_pump", "off")
    await _call(hass, "set_pool", pool=SHARED)
    await hass.async_block_till_done()
    on = async_mock_service(hass, "switch", "turn_on")
    off = async_mock_service(hass, "switch", "turn_off")
    modes = async_mock_service(hass, "climate", "set_hvac_mode")
    # the combined tile's heater button: the active body (the pool)
    await _call(hass, "pool_set_heater", entity="sensor.room_tiles_pool", heater=True)
    assert [c.data["entity_id"] for c in on] == ["switch.pool_pump"]
    assert modes[-1].data == {"entity_id": "climate.pool", "hvac_mode": "heat"}
    # off: the heater only, the pump keeps running
    await _call(hass, "pool_set_heater", entity="sensor.room_tiles_pool", heater=False)
    assert off == [] and modes[-1].data["hvac_mode"] == "off"
    # the setting off: the heater alone
    no_pump = {**SHARED, "pool": {**SHARED["pool"], "pump_with_heater": False}}
    await _call(hass, "set_pool", pool=no_pump)
    await hass.async_block_till_done()
    await _call(hass, "pool_set_heater", entity="sensor.room_tiles_pool", heater=True)
    assert len(on) == 1



async def test_spa_off_stops_the_pump_only_if_spa_on_started_it(hass: HomeAssistant, entry) -> None:
    _pool_mode(hass)
    hass.states.async_set("switch.pool_pump", "off")
    await _call(hass, "set_pool", pool=SHARED)
    await hass.async_block_till_done()
    on = async_mock_service(hass, "switch", "turn_on")
    off = async_mock_service(hass, "switch", "turn_off")
    async_mock_service(hass, "climate", "set_hvac_mode")
    # the pump was off: spa on starts it...
    await _spa_mode(hass, True)
    assert "switch.pool_pump" in [c.data["entity_id"] for c in on]
    # ...and spa off stops it again
    await _spa_mode(hass, False)
    assert [c.data["entity_id"] for c in off] == ["switch.spa_pump", "switch.pool_pump"]
    # the pump already running: spa on doesn't touch it, spa off leaves it on
    hass.states.async_set("switch.pool_pump", "on")
    await hass.async_block_till_done()
    n_on, n_off = len(on), len(off)
    await _spa_mode(hass, True)
    assert [c.data["entity_id"] for c in on[n_on:]] == ["switch.spa_pump"]
    await _spa_mode(hass, False)
    assert [c.data["entity_id"] for c in off[n_off:]] == ["switch.spa_pump"]


async def test_pool_sensors_come_back_after_a_restart(hass: HomeAssistant, hass_storage) -> None:
    """Set up from stored data at HA start (the entry isn't 'loaded' yet while
    its sensors are added) - the bug that left pool tiles empty."""
    import json
    from pathlib import Path

    stored = json.loads((Path(__file__).parent / "fixtures" / "storage" / "v1.7.json").read_text())
    hass_storage[DOMAIN] = stored
    _pool_mode(hass)
    e = MockConfigEntry(domain=DOMAIN)
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    # shared: the combined sensor and Spa Mode (no sensor per body)
    for ent in ("sensor.room_tiles_pool", "switch.room_tiles_pool_spa_mode"):
        assert hass.states.get(ent) is not None, ent
    assert "sensor.room_tiles_pool" in e.runtime_data.pool_entities


async def test_short_names_use_room_tiles_own_name(hass: HomeAssistant, entry) -> None:
    """HA's friendly name has the controller device's name in front ("Spa
    Set Point Spa Mode"): suggested short names come from Room Tiles' own
    name, as the dashboard shows it."""
    _pool_mode(hass)
    await _call(hass, "set_pool", pool=SHARED)
    await hass.async_block_till_done()
    sw = "switch.room_tiles_pool_spa_mode"
    st = hass.states.get(sw)
    hass.states.async_set(sw, st.state, {**st.attributes, "friendly_name": "Spa Set Point Spa Mode"})
    res = await _call(hass, "suggest_short_name", response=True, entity=sw)
    assert res["full_name"] == "Spa Mode" and res["short_name"] == "Spa Mode"
    await _call(hass, "reset_short_names", response=True, entities=[sw])
    assert entry.runtime_data.data.catalog.get(sw).short_name == "Spa Mode"


async def test_heater_asked_shows_until_reported(hass: HomeAssistant, entry, freezer) -> None:
    """A heater asked on (the tiles' button) is on its way until HA reports
    it - controllers can take minutes - at most 5 minutes."""
    import json

    _pool_mode(hass)
    await _call(hass, "set_pool", pool=SHARED)
    await hass.async_block_till_done()
    async_mock_service(hass, "climate", "set_hvac_mode")  # (the heater stays off: nothing reports it)
    await _call(hass, "pool_set_heater", entity="sensor.room_tiles_pool", heater=True)
    await hass.async_block_till_done()
    st = hass.states.get("sensor.room_tiles_pool")
    assert st.attributes["heater_pending"] == "on"
    assert json.loads(st.attributes["tile_words"])["0.2"] == {"k": "pool.short.heater_starting"}
    assert json.loads(st.attributes["status_word"]) == {"k": "pool.heater_starting"}
    # still not there after 4 minutes: still on its way
    freezer.tick(240)
    hass.states.async_set("sensor.pool_temp", "80")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.room_tiles_pool").attributes["heater_pending"] == "on"
    # reported: done
    hass.states.async_set("climate.pool", "heat", {"temperature": 85, "hvac_action": "heating"})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.room_tiles_pool").attributes["heater_pending"] == ""
    # asked off and never reported: given up after 5 minutes
    await _call(hass, "pool_set_heater", entity="sensor.room_tiles_pool", heater=False)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.room_tiles_pool").attributes["heater_pending"] == "off"
    freezer.tick(301)
    hass.states.async_set("sensor.pool_temp", "81")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.room_tiles_pool").attributes["heater_pending"] == ""


async def test_chiller_asked_says_chiller(hass: HomeAssistant, entry) -> None:
    """A chiller (cool mode) on its way says so - not "Heater starting"."""
    import json

    _pool_mode(hass)
    hass.states.async_set("climate.pool", "off", {"temperature": 85, "hvac_action": "off", "hvac_modes": ["off", "cool"]})
    await _call(hass, "set_pool", pool=SHARED)
    await hass.async_block_till_done()
    async_mock_service(hass, "climate", "set_hvac_mode")
    await _call(hass, "pool_set_heater", entity="sensor.room_tiles_pool", heater=True)
    await hass.async_block_till_done()
    st = hass.states.get("sensor.room_tiles_pool")
    assert json.loads(st.attributes["tile_words"])["0.2"] == {"k": "pool.short.chiller_starting"}
    assert json.loads(st.attributes["status_word"]) == {"k": "pool.chiller_starting"}
