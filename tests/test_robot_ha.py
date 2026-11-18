"""Robot vacuum profiles inside a test HA."""

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.room_tiles.const import DOMAIN


@pytest.fixture
async def entry(hass: HomeAssistant):
    e = MockConfigEntry(domain=DOMAIN)
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    return e


async def _call(hass, service, **data):
    return await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def test_matic_tile_sensor(hass: HomeAssistant, entry) -> None:
    async def note(call):
        pass

    for name in ("create", "dismiss"):  # always there in a real HA
        hass.services.async_register("persistent_notification", name, note)
    hass.states.async_set("vacuum.matic", "docked", {"supported_features": 29212})
    hass.states.async_set("sensor.matic_operational_error", "no_error")
    await _call(hass, "set_robot", robot={"id": "matic", "name": "Matic", "vacuum": "vacuum.matic", "error": "sensor.matic_operational_error", "preset": "matter"})
    await hass.async_block_till_done()
    st = hass.states.get("sensor.room_tiles_matic")
    assert (st.state, st.attributes["status"], st.attributes["tile"], st.attributes["clean_area"]) == ("docked", "Docked", "docked|Docked||", True)
    assert st.attributes["tile_words"] == '{"0.1":{"k":"robot.docked"}}'
    assert st.attributes["vacuum"] == "vacuum.matic"
    assert st.attributes["own_name"] == "Matic"
    assert entry.runtime_data.data.catalog.get("sensor.room_tiles_matic").kind == "vacuum"

    hass.states.async_set("sensor.matic_operational_error", "water_tank_empty")
    await hass.async_block_till_done()
    st = hass.states.get("sensor.room_tiles_matic")
    assert (st.state, st.attributes["status"], st.attributes["alert"]) == ("attention", "Refill water tank", "attention")

    hass.states.async_set("sensor.matic_operational_error", "no_error")
    hass.states.async_set("vacuum.matic", "cleaning", {"supported_features": 29212})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.room_tiles_matic").attributes["status"] == "Cleaning"

    await _call(hass, "remove_robot", robot="matic")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.room_tiles_matic") is None


async def test_tile_sensor_sits_on_the_source_device(hass: HomeAssistant, entry) -> None:
    """Our sensor takes the vacuum's device - and so its area (the dashboard's
    area filters find it there)."""
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    source_entry = MockConfigEntry(domain="matter")
    source_entry.add_to_hass(hass)
    area = ar.async_get(hass).async_create("Living Room")
    dev = dr.async_get(hass).async_get_or_create(config_entry_id=source_entry.entry_id, identifiers={("matter", "robot")}, name="Matic")
    dr.async_get(hass).async_update_device(dev.id, area_id=area.id)
    er.async_get(hass).async_get_or_create("vacuum", "matter", "robot-1", suggested_object_id="matic", device_id=dev.id, config_entry=source_entry)
    hass.states.async_set("vacuum.matic", "docked", {"supported_features": 29212})

    await _call(hass, "set_robot", robot={"id": "matic", "name": "Matic", "vacuum": "vacuum.matic", "preset": "vacuum"})
    await hass.async_block_till_done()
    ours = er.async_get(hass).async_get("sensor.room_tiles_matic")
    assert ours is not None and ours.device_id == dev.id
    assert ours.area_id is None  # follows the device's area
    assert dr.async_get(hass).async_get(ours.device_id).area_id == area.id


async def test_room_queue_runs_like_the_matic_queue(hass: HomeAssistant, entry) -> None:
    """Add rooms, Start: clean_area per room, the next one the moment the
    vacuum turns to returning with no error; an alert pauses (notified);
    the queue survives in the sensor's attributes."""
    sent: list = []

    async def clean_area(call):
        sent.append(("clean_area", call.data["cleaning_area_id"]))

    async def plain(call):
        sent.append((call.service, None))

    hass.services.async_register("vacuum", "clean_area", clean_area)
    for name in ("start", "pause", "return_to_base"):
        hass.services.async_register("vacuum", name, plain)
    notes: list = []

    async def note(call):
        notes.append((call.service, dict(call.data)))

    hass.services.async_register("persistent_notification", "create", note)
    hass.services.async_register("persistent_notification", "dismiss", note)

    hass.states.async_set("vacuum.matic", "docked", {"supported_features": 29212})
    hass.states.async_set("sensor.matic_operational_error", "no_error")
    await _call(hass, "set_robot", robot={"id": "matic", "name": "Matic", "vacuum": "vacuum.matic", "error": "sensor.matic_operational_error", "preset": "matter"})
    await hass.async_block_till_done()

    q = lambda: hass.states.get("sensor.room_tiles_matic").attributes  # noqa: E731
    await _call(hass, "vacuum_queue", robot="matic", action="add", area="kitchen")
    await _call(hass, "vacuum_queue", robot="matic", action="add", area="hall")
    assert (q()["queue"], q()["current"], sent) == (["kitchen", "hall"], None, [])

    await _call(hass, "vacuum_queue", robot="matic", action="start")
    await hass.async_block_till_done()
    assert sent == [("clean_area", ["kitchen"])]
    assert (q()["queue"], q()["current"]) == (["hall"], "kitchen")
    assert q()["tile"].endswith("|kitchen|hall")

    hass.states.async_set("vacuum.matic", "cleaning", {"supported_features": 29212})
    await hass.async_block_till_done()
    # an alert mid-room: paused on that room, notified once
    hass.states.async_set("sensor.matic_operational_error", "stuck")
    await hass.async_block_till_done()
    assert notes[-1][0] == "create" and "kitchen" in notes[-1][1]["message"].lower()
    assert sent == [("clean_area", ["kitchen"])]  # paused on that room: nothing new sent
    hass.states.async_set("sensor.matic_operational_error", "no_error")
    await hass.async_block_till_done()
    assert notes[-1][0] == "dismiss"
    # the room done cleanly: the next one at once
    hass.states.async_set("vacuum.matic", "returning", {"supported_features": 29212})
    await hass.async_block_till_done()
    assert sent[-1] == ("clean_area", ["hall"])
    assert (q()["queue"], q()["current"]) == ([], "hall")
    hass.states.async_set("vacuum.matic", "cleaning", {"supported_features": 29212})
    await hass.async_block_till_done()
    hass.states.async_set("vacuum.matic", "returning", {"supported_features": 29212})
    await hass.async_block_till_done()
    assert (q()["queue"], q()["current"]) == ([], None)

    # stop and clear: back home, nothing queued
    await _call(hass, "vacuum_queue", robot="matic", action="add", area="bedroom")
    await _call(hass, "vacuum_queue", robot="matic", action="stop")
    assert sent[-1] == ("return_to_base", None) and q()["queue"] == []
