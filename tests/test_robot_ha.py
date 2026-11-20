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


async def test_room_queue_lets_go_of_a_vacuum_taken_over(hass: HomeAssistant, entry) -> None:
    """A vacuum command through HA that isn't Room Tiles' own (its vacuum card,
    a voice assistant) while a room is in progress: the queue is cleared and
    the status says so until the vacuum docks; Room Tiles' own commands and a
    pause never count."""
    sent: list = []

    async def record(call):
        sent.append((call.service, dict(call.data)))

    for name in ("clean_area", "start", "pause", "return_to_base"):
        hass.services.async_register("vacuum", name, record)
    hass.states.async_set("vacuum.matic", "docked", {"supported_features": 29212})
    await _call(hass, "set_robot", robot={"id": "matic", "name": "Matic", "vacuum": "vacuum.matic", "preset": "vacuum"})
    await hass.async_block_till_done()
    q = lambda: hass.states.get("sensor.room_tiles_matic").attributes  # noqa: E731

    for area in ("kitchen", "hall"):
        await _call(hass, "vacuum_queue", robot="matic", action="add", area=area)
    await _call(hass, "vacuum_queue", robot="matic", action="start")
    await hass.async_block_till_done()
    assert sent[-1][0] == "clean_area" and (q()["current"], q()["queue"]) == ("kitchen", ["hall"])
    hass.states.async_set("vacuum.matic", "cleaning", {"supported_features": 29212})
    await hass.async_block_till_done()

    # a pause through HA: the queue waits
    await hass.services.async_call("vacuum", "pause", {"entity_id": "vacuum.matic"}, blocking=True)
    await hass.async_block_till_done()
    assert (q()["current"], q()["taken_over"]) == ("kitchen", False)
    # someone else's command for ANOTHER vacuum: nothing
    await hass.services.async_call("vacuum", "return_to_base", {"entity_id": "vacuum.other"}, blocking=True)
    await hass.async_block_till_done()
    assert q()["current"] == "kitchen"
    # HA's vacuum card sends it home: let go
    await hass.services.async_call("vacuum", "return_to_base", {"entity_id": "vacuum.matic"}, blocking=True)
    await hass.async_block_till_done()
    assert (q()["current"], q()["queue"], q()["taken_over"]) == (None, [], True)
    hass.states.async_set("vacuum.matic", "returning", {"supported_features": 29212})
    await hass.async_block_till_done()
    assert "Queue cleared" in q()["status"] and sent[-1][0] == "return_to_base"  # (nothing of ours went out)
    hass.states.async_set("vacuum.matic", "docked", {"supported_features": 29212})
    await hass.async_block_till_done()
    assert q()["taken_over"] is False and q()["status"] == "Docked"



async def test_matic_turning_idle_by_itself_lets_go(hass: HomeAssistant, entry, monkeypatch) -> None:
    """A Matic (its HA device's maker) turning idle when Room Tiles didn't
    ask - a stop or a "go home" from its own app: the queue is cleared."""
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    import custom_components.room_tiles.sensor as sensor_mod

    other = MockConfigEntry(domain="matter")
    other.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("matter", "matic")}, manufacturer="Matic Robots, Inc", model="Matic"
    )
    er.async_get(hass).async_get_or_create("vacuum", "matter", "matic", suggested_object_id="matic", device_id=dev.id)

    async def record(call):
        pass

    hass.services.async_register("vacuum", "clean_area", record)
    hass.states.async_set("vacuum.matic", "docked", {"supported_features": 29212})
    await _call(hass, "set_robot", robot={"id": "matic", "name": "Matic", "vacuum": "vacuum.matic", "preset": "vacuum"})
    await hass.async_block_till_done()
    q = lambda: hass.states.get("sensor.room_tiles_matic").attributes  # noqa: E731
    for area in ("kitchen", "hall"):
        await _call(hass, "vacuum_queue", robot="matic", action="add", area=area)
    await _call(hass, "vacuum_queue", robot="matic", action="start")
    hass.states.async_set("vacuum.matic", "cleaning", {"supported_features": 29212})
    await hass.async_block_till_done()
    # just after Room Tiles' own command: an idle blip is its answer, not a takeover
    hass.states.async_set("vacuum.matic", "idle", {"supported_features": 29212})
    await hass.async_block_till_done()
    assert q()["current"] == "kitchen"
    hass.states.async_set("vacuum.matic", "cleaning", {"supported_features": 29212})
    await hass.async_block_till_done()
    monkeypatch.setattr(sensor_mod, "OURS_S", 0)  # (long after it)
    hass.states.async_set("vacuum.matic", "idle", {"supported_features": 29212})
    await hass.async_block_till_done()
    assert (q()["current"], q()["queue"], q()["taken_over"]) == (None, [], True)


async def test_an_unknown_error_code_is_asked_about(hass: HomeAssistant, entry) -> None:
    """A code Room Tiles has no words for: listed for the Appliances page and
    in Repairs; answered, it shows as the user said - and an edit without
    the answers keeps them; "Also tell Room Tiles" has its report."""
    from homeassistant.helpers import issue_registry as ir

    from custom_components.room_tiles.report import build_unknown_robot_state

    hass.states.async_set("vacuum.matic", "cleaning", {"supported_features": 29212})
    hass.states.async_set("sensor.matic_operational_error", "no_error")
    robot = {"id": "matic", "name": "Matic", "vacuum": "vacuum.matic", "error": "sensor.matic_operational_error", "preset": "matter"}
    await _call(hass, "set_robot", robot=robot)
    await hass.async_block_till_done()
    q = lambda: hass.states.get("sensor.room_tiles_matic").attributes  # noqa: E731
    hass.states.async_set("sensor.matic_operational_error", "mystery_code")
    await hass.async_block_till_done()
    assert q()["questions"] == [{"code": "mystery_code"}] and q()["alert"] == "error"
    assert ir.async_get(hass).async_get_issue(DOMAIN, "appliance_question_robot_matic") is not None
    # answered: "it needs me"
    await _call(hass, "set_robot", robot={**robot, "overrides": {"mystery_code": "attention"}})
    await hass.async_block_till_done()
    assert q()["questions"] == [] and q()["alert"] == "attention"
    assert ir.async_get(hass).async_get_issue(DOMAIN, "appliance_question_robot_matic") is None
    # renamed on the dashboard (no answers in the edit): they stay
    await _call(hass, "set_robot", robot={**robot, "name": "Matic 2"})
    await hass.async_block_till_done()
    assert entry.runtime_data.data.robots[0].overrides == {"mystery_code": "attention"}
    draft = await build_unknown_robot_state(hass, entry.runtime_data.data, "matic", "mystery_code", "attention")
    assert draft["kind_of_device"] == "vacuum" and draft["answers"] == [{"role": "error", "state": "mystery_code", "answer": "needs_you"}]


async def test_a_vacuum_renamed_in_ha_is_followed_at_once(hass: HomeAssistant, entry) -> None:
    """Its tile sensor listens to the new entity id right away (no reload)."""
    from homeassistant.helpers import entity_registry as er

    source_entry = MockConfigEntry(domain="matter")
    source_entry.add_to_hass(hass)
    reg = er.async_get(hass)
    reg.async_get_or_create("vacuum", "matter", "robot-1", suggested_object_id="matic", config_entry=source_entry)
    hass.states.async_set("vacuum.matic", "docked", {"supported_features": 29212})
    await _call(hass, "set_robot", robot={"id": "matic", "name": "Matic", "vacuum": "vacuum.matic", "preset": "vacuum"})
    await hass.async_block_till_done()

    reg.async_update_entity("vacuum.matic", new_entity_id="vacuum.robot")
    await hass.async_block_till_done()
    assert entry.runtime_data.data.robots[0].vacuum == "vacuum.robot"
    hass.states.async_set("vacuum.robot", "cleaning", {"supported_features": 29212})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.room_tiles_matic").attributes["status"] == "Cleaning"


async def test_quick_presses_send_a_room_once_and_a_stop_wins(hass: HomeAssistant, entry) -> None:
    """clean_area takes a while to answer: a second Start meanwhile sends
    nothing more, and a Stop meanwhile leaves the queue stopped."""
    import asyncio

    sent: list = []
    gate = asyncio.Event()

    async def clean_area(call):
        sent.append(("clean_area", call.data["cleaning_area_id"]))
        await gate.wait()

    async def plain(call):
        sent.append((call.service, None))

    hass.services.async_register("vacuum", "clean_area", clean_area)
    for name in ("start", "pause", "return_to_base"):
        hass.services.async_register("vacuum", name, plain)
    hass.states.async_set("vacuum.matic", "docked", {"supported_features": 29212})
    await _call(hass, "set_robot", robot={"id": "matic", "name": "Matic", "vacuum": "vacuum.matic", "preset": "matter"})
    await hass.async_block_till_done()
    q = lambda: hass.states.get("sensor.room_tiles_matic").attributes  # noqa: E731
    await _call(hass, "vacuum_queue", robot="matic", action="add", area="kitchen")
    await _call(hass, "vacuum_queue", robot="matic", action="add", area="hall")

    first = hass.async_create_task(_call(hass, "vacuum_queue", robot="matic", action="start"))
    second = hass.async_create_task(_call(hass, "vacuum_queue", robot="matic", action="start"))
    await asyncio.sleep(0.05)
    gate.set()
    await first
    await second
    await hass.async_block_till_done()
    assert sent == [("clean_area", ["kitchen"])]
    assert (q()["queue"], q()["current"]) == (["hall"], "kitchen")

    # a Stop while the next room is on its way: stopped stays stopped
    gate.clear()
    hass.states.async_set("vacuum.matic", "cleaning", {"supported_features": 29212})
    await hass.async_block_till_done()
    hass.states.async_set("vacuum.matic", "returning", {"supported_features": 29212})  # kitchen done: hall goes
    await asyncio.sleep(0.05)
    assert sent[-1] == ("clean_area", ["hall"])
    stop = hass.async_create_task(_call(hass, "vacuum_queue", robot="matic", action="stop"))
    await asyncio.sleep(0.05)
    gate.set()
    await stop
    await hass.async_block_till_done()
    assert sent[-1] == ("return_to_base", None)
    assert (q()["queue"], q()["current"]) == ([], None)
