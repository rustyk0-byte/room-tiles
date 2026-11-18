"""Report a problem (cycles.py): a cycle's rows, when a live recording
starts and ends, HA restarts marked in it, and the report it makes."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, flush_store

from custom_components.room_tiles.cycles import (
    LEAD_S,
    LIMIT_S,
    MAX_ROWS,
    QUIET_S,
    Recording,
    Recordings,
    Rows,
    Subject,
    problem_draft,
    spans,
)
from custom_components.room_tiles.report import description_warnings, issue, scrub

T0 = 1_763_400_000.0  # (some afternoon: never in a report)


def test_rows_keep_changes_only_and_thin_chatty_numbers():
    r = Rows()
    assert r.add(T0, "sensor.st", "idle", {"options": ["idle", "drying"]})
    assert not r.add(T0 + 1, "sensor.st", "idle", {"options": ["idle", "drying"]})  # nothing changed
    assert r.add(T0 + 2, "sensor.st", "drying", {"options": ["idle", "drying"], "cycle": "cotton"})
    assert r.rows[-1][3] == {"cycle": "cotton"}  # (only what changed)
    r.add(T0 + 3, "sensor.st", "drying", {"options": ["idle", "drying"]})
    assert r.rows[-1][3] == {"cycle": None}  # (gone)
    # a power reading every 2 s: one row per 30 s, its last value kept at the end
    for i in range(30):
        r.add(T0 + 10 + 2 * i, "sensor.w", 500 + i, {})
    watts = [row for row in r.rows if row[1] == "sensor.w"]
    assert [w[0] - T0 for w in watts] == [10, 40]
    r.flush()
    assert [row for row in r.rows if row[1] == "sensor.w"][-1][2] == 529
    assert [row[0] for row in r.rows] == sorted(row[0] for row in r.rows)


def test_rows_stop_growing_at_the_limit():
    r = Rows()
    for i in range(MAX_ROWS + 5):
        r.add(T0 + 60 * i, "sensor.st", f"s{i}", {})
    assert len(r.rows) == MAX_ROWS and r.trimmed == 5


def test_rows_survive_a_save():
    r = Rows()
    r.add(T0, "sensor.st", "idle", {"a": 1})
    r.add(T0 + 100, "sensor.st", "drying", {"a": 1})
    r.forget_before(T0 + 50)
    back = Rows.from_dict(json.loads(json.dumps(r.as_dict())))
    assert back.base == {"sensor.st": [T0, "idle", {"a": 1}]}
    assert not back.add(T0 + 200, "sensor.st", "drying", {"a": 1})  # (knows the last state)
    assert back.all_rows(T0 + 40)[0] == [T0 + 40, "sensor.st", "idle", {"a": 1}]


def _rec() -> Recording:
    return Recording(kind="appliance", id="a1", unit="u1", armed=T0)


def test_waiting_for_the_next_cycle_keeps_only_the_lead_up():
    rec = _rec()
    rec.note(T0, "sensor.st", "idle", {}, False, None)
    rec.note(T0 + 3600, "sensor.door", "on", {}, None, "off")
    assert rec.status == "waiting"
    rec.note(T0 + 7200, "sensor.st", "drying", {}, True, "idle")
    assert rec.status == "recording" and rec.started == T0 + 7200
    assert rec.events == [[T0 + 7200, "cycle_started"]]
    # what came long before folded into the base; the base starts LEAD_S before
    rows = rec.rows.all_rows(rec.started - LEAD_S)
    assert rows[0][0] == T0 + 7200 - LEAD_S
    assert {r[1] for r in rows} == {"sensor.st", "sensor.door"}


def test_a_recording_ends_an_hour_after_the_cycle_went_quiet():
    rec = _rec()
    rec.note(T0, "sensor.st", "drying", {}, True, None)
    assert not rec.tick(T0 + 5 * 3600)  # (running: never quiet)
    rec.note(T0 + 5 * 3600, "sensor.st", "done", {}, False, "drying")
    # a power reading jittering after the end doesn't keep it going...
    for i in range(1, 50):
        rec.note(T0 + 5 * 3600 + 60 * i, "sensor.w", 0.3 + (i % 2) * 0.1, {}, None, 0.4 - (i % 2) * 0.1)
    assert not rec.tick(T0 + 5 * 3600 + QUIET_S - 60)
    # ...a word changing does (anti-wrinkle tumbling)
    rec.note(T0 + 5 * 3600 + 3000, "sensor.extra", "tumbling", {}, None, "off")
    assert not rec.tick(T0 + 5 * 3600 + QUIET_S + 60)
    assert rec.tick(T0 + 5 * 3600 + 3000 + QUIET_S)
    assert rec.status == "ready" and rec.end == "quiet"


def test_a_recording_never_runs_past_its_limit():
    rec = _rec()
    rec.note(T0, "sensor.st", "drying", {}, True, None)
    assert rec.tick(T0 + LIMIT_S) and rec.end == "limit"


def test_running_spans_merge_short_gaps():
    pts = [(0, False), (100, True), (200, False), (200 + QUIET_S - 10, True), (5000 + QUIET_S, False),
           (20000, True)]
    assert spans(pts, 30000) == [(100, 5000 + QUIET_S, False), (20000, 30000, True)]


def _sub(kind: str, own: dict[str, str]) -> Subject:
    preset = {"robot": "vacuum", "pool": "iaqualink"}.get(kind, "ge_home_dryer")  # (a real one: report.py _preset)
    return Subject(kind, "x", "", "Mine", next(iter(own)), {"robot": "vacuum"}.get(kind, kind), preset, None, LIMIT_S, own)


def test_what_says_a_pool_or_a_vacuum_runs():
    pool = _sub("pool", {"switch.p": "pump", "sensor.rt": "room_tiles"})
    assert pool.active("pump", "on", {}) is True and pool.active("pump", "off", {}) is False
    assert pool.active("room_tiles", "heating", {}) is True and pool.active("room_tiles", "pump_off", {}) is False
    assert pool.active("room_tiles", "offline", {}) is None  # (doesn't say)
    assert pool.active("spa_heater", "heat", {"hvac_action": "heating"}) is True
    assert pool.active("spa_heater", "heat", {"hvac_action": "idle"}) is False
    robot = _sub("robot", {"vacuum.v": "vacuum"})
    assert robot.active("vacuum", "cleaning", {}) is True and robot.active("vacuum", "docked", {}) is False
    assert robot.active("vacuum", "error", {}) is None  # (stuck mid-clean: still the same clean)
    # Room Tiles' own sensor: what the tile showed, less its names / ids / panel text
    got = robot.row("room_tiles", "cleaning", {"own_name": "Matic", "vacuum": "vacuum.v", "tile": "x", "status_word": "{}",
                                               "status": "Cleaning", "queue": ["kitchen"], "current": "office"})
    assert got == ("cleaning", {"status": "Cleaning", "queue": ["kitchen"], "current": "office"})


def test_a_vacuums_rooms_go_out_as_places():
    sub = _sub("robot", {"vacuum.v": "vacuum", "sensor.rt": "room_tiles"})
    cycle = {
        "subject": sub,
        "roles": {"vacuum.v": "vacuum", "sensor.rt": "room_tiles"},
        "rows": [
            [T0, "sensor.rt", "cleaning", {"current": "jamie_office", "queue": ["kitchen", "jamie_office"]}],
            [T0 + 600, "sensor.rt", "cleaning", {"current": "kitchen", "queue": []}],
            [T0 + 900, "vacuum.v", "docked", {}],
        ],
        "events": [],
        "trimmed": 0,
        "ended": "history",
        "from": "history",
    }
    d = problem_draft(cycle, "It skipped the kitchen.", {"kitchen", "jamie_office"})
    assert d["recording"][0]["attributes"] == {"current": "area_1", "queue": ["area_2", "area_1"]}
    assert d["recording"][1]["attributes"] == {"current": "area_2", "queue": []}
    assert d["kind_of_device"] == "vacuum"
    out = scrub({"kind": "problem", **d}, {"jamie", "jamie_office"})
    assert out.dropped == [] and "jamie" not in repr(out.doc)


def test_description_warnings_point_out_the_home():
    text = "Edith's dryer said Done at 1:05 pm. We're at 12 Main Street, call 555-123-4567 or me@example.com"
    got = description_warnings(text, {"edith", "edith's dryer"})
    assert [(w["text"], w["why"]) for w in got] == [
        ("Edith's dryer", "name"),
        ("1:05 pm", "time"),
        ("12 Main Street", "address"),
        ("555-123-4567", "phone"),
        ("me@example.com", "email"),
    ]
    assert description_warnings("It said Done but was still drying.", {"edith"}) == []
    assert description_warnings("Since Room Tiles 0.1.0 and HA 2026.11.2 it stops at 45 min.", set()) == []


def test_a_problem_report_keeps_the_users_words_and_the_whole_cycle():
    doc = {
        "kind": "problem",
        "description": "It said Done while it was still drying.\nTwice this week.",
        "kind_of_device": "dryer",
        "cycle": {"from": "recorded", "ended": "quiet", "trimmed": 0},
        "recording": [
            {"t": T0, "role": "status", "state": "drying", "attributes": {}},
            {"t": T0 + 60, "role": "room_tiles", "state": "done", "attributes": {"status": "Done", "minutes_left": None, "running": False}},
        ],
        "events": [{"t": T0 + 30, "event": "ha_stopped_unclean"}, {"t": T0 + 45, "event": "ha_started"}],
    }
    out = scrub(doc, set())
    assert out.dropped == [], out.dropped
    assert out.doc["description"].startswith("It said Done")
    assert [e["t"] for e in out.doc["events"]] == [30.0, 45.0]
    body = issue(out.doc, "problem")["body"]
    assert body.startswith("**What went wrong**") and "> Twice this week." in body
    # the JSON in the issue is the report (less the words above it), one row per line
    block = body.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
    assert json.loads(block) == {k: v for k, v in out.doc.items() if k != "description"}
    assert '    {"t": 60.0, "role": "room_tiles"' in block


async def _setup(hass: HomeAssistant) -> tuple[MockConfigEntry, str]:
    """Room Tiles with one dryer: its status, a power reading and an extra
    entity on the same device."""
    from custom_components.room_tiles.const import DOMAIN
    from custom_components.room_tiles.model import Appliance, ApplianceUnit

    e = MockConfigEntry(domain=DOMAIN)
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    ge = MockConfigEntry(domain="ge_home", title="GE Home")
    ge.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(
        config_entry_id=ge.entry_id, identifiers={("ge_home", "D9988776655")}, manufacturer="GE Appliances",
        model="PTD9000SN", name="Dryer",
    )
    dr.async_get(hass).async_update_device(dev.id, name_by_user="Edith's Dryer")
    reg = er.async_get(hass)
    reg.async_get_or_create("sensor", "ge_home", "D9988776655_status", device_id=dev.id, suggested_object_id="edith_dryer_status")
    reg.async_get_or_create("sensor", "ge_home", "D9988776655_w", device_id=dev.id, suggested_object_id="edith_dryer_power",
                            original_name="Power")
    reg.async_get_or_create("binary_sensor", "ge_home", "D9988776655_tumble", device_id=dev.id,
                            suggested_object_id="edith_dryer_tumble", translation_key="wrinkle_care")
    hass.states.async_set("sensor.edith_dryer_status", "standby")
    hass.states.async_set("sensor.edith_dryer_power", "0.3", {"unit_of_measurement": "W"})
    hass.states.async_set("binary_sensor.edith_dryer_tumble", "off")
    store = e.runtime_data
    store.data.appliances.append(
        Appliance(id="a1", name="Edith's Dryer", units=[ApplianceUnit(id="u1", label="Dryer", appliance="dryer", preset="ge_home_dryer", status="sensor.edith_dryer_status")])
    )
    store.async_changed(("appliances",))  # (its Room Tiles sensor: what the tile shows)
    await hass.async_block_till_done()
    return e, "a1"


async def test_record_the_next_cycle_then_send_it(hass: HomeAssistant, hass_ws_client) -> None:
    e, aid = await _setup(hass)
    ws = await hass_ws_client(hass)
    who = {"subject": "appliance", "target": aid}
    await ws.send_json({"id": 1, "type": "room_tiles/recording", "action": "start", **who, "unit": "u1",
                        "description": "Edith's dryer said Done while still drying."})
    assert (await ws.receive_json())["success"]
    recs = e.runtime_data.recordings
    key = f"appliance:{aid}"
    assert recs.doc[key]["status"] == "waiting"
    hass.states.async_set("sensor.edith_dryer_status", "run")
    hass.states.async_set("sensor.edith_dryer_power", "800", {"unit_of_measurement": "W"})
    await hass.async_block_till_done()
    assert recs.doc[key]["status"] == "recording"
    hass.states.async_set("sensor.edith_dryer_status", "finished")
    hass.states.async_set("binary_sensor.edith_dryer_tumble", "on")
    await hass.async_block_till_done()
    await ws.send_json({"id": 2, "type": "room_tiles/recording", "action": "stop", **who})
    assert (await ws.receive_json())["success"]
    assert recs.doc[key]["status"] == "ready"
    await ws.send_json({"id": 3, "type": "room_tiles/report_preview", "kind": "problem",
                        "draft": {**who, "unit": "u1", "recorded": True, "description": recs.doc[key]["description"]}})
    msg = await ws.receive_json()
    assert msg["success"], msg
    rep = msg["result"]["report"]
    roles = {r["role"] for r in rep["recording"]}
    assert {"status", "power", "wrinkle_care", "room_tiles"} <= roles, roles
    assert rep["recording"][0]["t"] == 0.0 and rep["cycle"]["from"] == "recorded"
    assert rep["device"]["manufacturer"] == "GE Appliances"
    assert rep["description"].startswith("Edith's dryer")  # (their words, as written...)
    assert msg["result"]["warnings"][0]["why"] == "name"  # (...with the name pointed out)
    data = repr({k: v for k, v in rep.items() if k != "description"})
    for bad in ("Edith", "edith", "D9988776655", "sensor."):
        assert bad not in data, bad
    # GitHub opened, then deleted
    await ws.send_json({"id": 4, "type": "room_tiles/recording", "action": "update", **who, "opened": True})
    assert (await ws.receive_json())["success"] and recs.doc[key]["opened"]
    await ws.send_json({"id": 5, "type": "room_tiles/recording", "action": "delete", **who})
    assert (await ws.receive_json())["success"] and key not in recs.doc


async def test_ha_restarts_are_marked_in_a_recording(hass: HomeAssistant) -> None:
    e, aid = await _setup(hass)
    recs = e.runtime_data.recordings
    recs.start(e.runtime_data.data, "appliance", aid, "u1", "", T0)
    key = f"appliance:{aid}"
    hass.states.async_set("sensor.edith_dryer_status", "run")
    await hass.async_block_till_done()
    await flush_store(recs._store)
    # HA went away without stopping cleanly (no "ha_stopping"): a new start
    again = Recordings(hass, lambda: None)
    await again.async_load(e.runtime_data.data, T0 + 7200, ha_starting=True)
    marks = [ev[1] for ev in again.items[key].events]
    assert marks[-2:] == ["ha_stopped_unclean", "ha_started"]
    # a clean stop is marked as one
    again._ha_stopping(None)
    await flush_store(again._store)
    third = Recordings(hass, lambda: None)
    await third.async_load(e.runtime_data.data, T0 + 9000, ha_starting=True)
    assert [ev[1] for ev in third.items[key].events][-2:] == ["ha_stopping", "ha_started"]
    for r in (again, third):
        r._unlisten()
        if r._stop_unsub:
            r._stop_unsub()


async def test_a_vacuums_clean_is_recorded_and_reported(hass: HomeAssistant, hass_ws_client) -> None:
    """A robot vacuum: its clean recorded (leaving the dock to docked), its
    device's other entities by the integration's own words, the tile's
    sensor in it."""
    from custom_components.room_tiles.const import DOMAIN
    from custom_components.room_tiles.model import RobotProfile

    e = MockConfigEntry(domain=DOMAIN)
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    m = MockConfigEntry(domain="matter", title="Matter")
    m.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(
        config_entry_id=m.entry_id, identifiers={("matter", "AB12CD34EF56")}, manufacturer="Matic Robots", model="Matic", name="Matic",
    )
    reg = er.async_get(hass)
    reg.async_get_or_create("vacuum", "matter", "AB12CD34EF56_vac", device_id=dev.id, suggested_object_id="jamies_matic")
    reg.async_get_or_create("sensor", "matter", "AB12CD34EF56_batt", device_id=dev.id, suggested_object_id="jamies_matic_battery",
                            original_name="Battery")
    hass.states.async_set("vacuum.jamies_matic", "docked")
    hass.states.async_set("sensor.jamies_matic_battery", "100", {"unit_of_measurement": "%"})
    store = e.runtime_data
    store.data.robots.append(RobotProfile(id="r1", name="Jamie's Matic", vacuum="vacuum.jamies_matic", preset="vacuum"))
    store.async_changed(("robots",))
    await hass.async_block_till_done()
    ws = await hass_ws_client(hass)
    who = {"subject": "robot", "target": "r1"}
    await ws.send_json({"id": 1, "type": "room_tiles/recording", "action": "start", **who, "description": "It stopped halfway."})
    assert (await ws.receive_json())["success"]
    recs = store.recordings
    assert recs.doc["robot:r1"]["status"] == "waiting"
    hass.states.async_set("vacuum.jamies_matic", "cleaning")
    await hass.async_block_till_done()
    assert recs.doc["robot:r1"]["status"] == "recording"
    hass.states.async_set("sensor.jamies_matic_battery", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("vacuum.jamies_matic", "docked")
    await hass.async_block_till_done()
    await ws.send_json({"id": 2, "type": "room_tiles/recording", "action": "stop", **who})
    assert (await ws.receive_json())["success"]
    await ws.send_json({"id": 3, "type": "room_tiles/report_preview", "kind": "problem",
                        "draft": {**who, "recorded": True, "description": "It stopped halfway."}})
    msg = await ws.receive_json()
    assert msg["success"], msg
    rep = msg["result"]["report"]
    assert rep["kind_of_device"] == "vacuum" and rep["device"]["manufacturer"] == "Matic Robots"
    assert {"vacuum", "battery", "room_tiles"} <= {r["role"] for r in rep["recording"]}
    assert "report.has.shown" in msg["result"]["summary"]
    data = repr({k: v for k, v in rep.items() if k != "description"})
    for bad in ("Jamie", "jamie", "AB12CD34EF56", "vacuum."):
        assert bad not in data, bad
    # a pool or vacuum that isn't set up: not found
    await ws.send_json({"id": 4, "type": "room_tiles/problem_cycles", "subject": "pool", "target": "nope"})
    msg = await ws.receive_json()
    assert not msg["success"] and msg["error"]["code"] == "not_found"
