"""The report scrubber (DESIGN.md "Privacy: what reports send"): an allow-list
- only the report layout survives - and nothing that ties a report to the
user or their home, tried on real-looking data."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.room_tiles.report import MAX_LIST, scrub, secrets_from_hass, summary

# the home's own words (secrets_from_hass makes these from HA)
HOME = {"jamie", "robin", "9031qx47", "sensor.jamie_s_dryer_status", "jamie_s_dryer_status", "b1234a5678"}


def test_a_good_report_comes_through_whole():
    doc = {
        "kind": "recording",
        "room_tiles": "0.4.0",
        "home_assistant": "2026.11.2",
        "integration": {"domain": "ge_home", "version": "2026.10.1"},
        "device": {"manufacturer": "GE Appliances", "model": "PTD9000SN", "model_id": "PTD9000SN1WS", "sw_version": "1.0.0.12"},
        "kind_of_device": "dryer",
        "preset": "ge_home_dryer",
        "recording": [
            {"t": 0, "role": "status", "state": "idle"},
            {"t": 12.34, "role": "status", "state": "drying", "attributes": {"cycle": "cotton_60", "program": "program2"}},
            {"t": 3600, "role": "time_left", "state": 42},
        ],
        "answers": [{"role": "status", "state": "steam_fresh", "answer": "not_running"}],
        "checklist": {"door": "works", "time_left": "broken"},
        "outcome": "partly",
    }
    out = scrub(doc, HOME)
    assert out.dropped == []
    assert out.doc["device"]["sw_version"] == "1.0.0.12"  # (a version's dots aren't an IP address)
    assert out.doc["recording"][1] == {"t": 12.3, "role": "status", "state": "drying", "attributes": {"cycle": "cotton_60", "program": "program2"}}
    assert summary(out.doc) == [
        "report.has.device",
        "report.has.integration",
        "report.has.versions",
        "report.has.answers",
        "report.has.recording",
        "report.has.checklist",
    ]


def test_nothing_outside_the_layout():
    out = scrub(
        {
            "kind": "model",
            "entity_id": "sensor.jamie_s_dryer_status",
            "friendly_name": "Jamie's Dryer",
            "device": {"manufacturer": "Bosch", "serial_number": "FD9912345678", "name": "Dryer", "via_device": "abc"},
            "states": [{"role": "status", "state": "on", "entity_id": "sensor.x", "last_changed": "2026-11-17T13:00:00"}],
            "notes": "Jamie here, my house is at 12 Main St",
        },
        HOME,
    )
    assert out.doc == {"kind": "model", "device": {"manufacturer": "Bosch"}, "states": [{"role": "status", "state": "on"}]}
    gone = {path for path, _why in out.dropped}
    assert {"entity_id", "friendly_name", "device.serial_number", "device.name", "device.via_device", "notes",
            "states[0].entity_id", "states[0].last_changed"} <= gone


def test_states_and_attributes_keep_nothing_that_identifies():
    attrs = {
        # kept: raw device values
        "temperature": 31.5,
        "spin_speed": 1200,
        "door": "closed",
        "options": ["eco", "quick", "steam"],
        # dropped by their key: names, places, people, ids, times
        "friendly_name": "Jamie's Dryer",
        "serial_number": "B1234A5678",
        "mac": "aa:bb:cc:dd:ee:ff",
        "latitude": 38.1,
        "device_id": "0123456789abcdef0123456789abcdef",
        "finished_at": "13:05",  # (a clock time with no date: can't be placed - dropped)
        "user": "jamie",
        # dropped by their value
        "controller": "iAqualink B1234A5678",  # (a pool controller's serial)
        "wifi": "9031QX47",  # (the home's network)
        "ip": "192.168.1.195",
        "address": "fe80::1ff:fe23:4567:890a",
        "link": "https://example.com/my-dryer",
        "contact": "jamie@example.com",
        "id_hex": "9f8e7d6c5b4a39281706f5e4d3c2b1a0",
        "board": "PCB4A55B7C1D2E3F",  # (a serial-like code)
        "remaining": "1:05 pm",
        "note": "x" * 80,
        "linked": "sensor.jamie_s_dryer_status",
        "Bad Key": 1,
    }
    out = scrub({"states": [{"role": "status", "state": "drying", "attributes": attrs}]}, HOME)
    assert out.doc["states"][0]["attributes"] == {"temperature": 31.5, "spin_speed": 1200, "door": "closed", "options": ["eco", "quick", "steam"]}
    assert len(out.dropped) == len(attrs) - 4


def test_a_serial_hidden_in_an_entity_id_or_a_state():
    home = HOME | {"012345678901"}
    for bad in (
        "sensor.dishwasher_012345678901_status",  # an entity id - and a serial in it
        "012345678901",
        "DW-012345678901",
        "aa-bb-cc-dd-ee-ff",
        "AABBCCDDEEFF",
        "Jamie's office",
        "robin",
        "ws://192.168.1.76:8123",
        "13:05:44",
        "1:05 pm",
    ):
        out = scrub({"states": [{"role": "status", "state": bad}]}, home)
        assert out.doc == {"states": [{"role": "status"}]}, bad
        assert out.dropped and out.dropped[0][0] == "states[0].state", bad


def test_roles_are_room_tiles_words_never_the_homes():
    out = scrub(
        {"states": [{"role": "jamie_s_dryer_status", "state": "on"}, {"role": "Status!", "state": "on"}, {"role": "door", "state": "open"}]},
        HOME,
    )
    assert out.doc["states"] == [{"state": "on"}, {"state": "on"}, {"role": "door", "state": "open"}]


def test_a_renamed_device_keeps_its_brand():
    # the user named the device "John's Bosch": the brand still goes along
    out = scrub({"device": {"manufacturer": "Bosch", "model": "SMV68TX06E"}}, {"john's bosch", "john", "bosch"})
    assert out.doc == {"device": {"manufacturer": "Bosch", "model": "SMV68TX06E"}}
    # but never an address or an id, even there
    out = scrub({"device": {"manufacturer": "acme@example.com", "model": "aa:bb:cc:dd:ee:ff"}})
    assert out.doc == {"device": {}}


def test_answers_choices_and_times():
    out = scrub(
        {
            "answers": [
                {"role": "status", "state": "steam_fresh", "answer": "not_running"},
                {"role": "status", "state": "x", "answer": "my wife ran it"},  # (free text: not one of the choices)
            ],
            "recording": [{"t": -5, "role": "status", "state": "on"}, {"t": 1794941591, "role": "status", "state": "on"}],
            "outcome": "great!",
            "checklist": {"door": "yes", "time_left": "partly"},
        }
    )
    assert out.doc["answers"] == [{"role": "status", "state": "steam_fresh", "answer": "not_running"}, {"role": "status", "state": "x"}]
    # (a negative time goes; an absolute one becomes its distance from the earliest)
    assert out.doc["recording"] == [{"role": "status", "state": "on"}, {"t": 0.0, "role": "status", "state": "on"}]
    assert "outcome" not in out.doc and out.doc["checklist"] == {"time_left": "partly"}


def test_times_become_deltas_from_the_earliest():
    # a wall-clock time says when someone was home; how far apart two
    # moments are doesn't - every full timestamp becomes its distance from
    # the report's earliest (which isn't sent)
    out = scrub(
        {
            "recording": [
                {"t": "2026-11-17T13:00:00+00:00", "role": "status", "state": "washing"},
                {"t": 1794920400 + 90, "role": "status", "state": "rinsing"},  # (epoch seconds: 13:01:30 UTC)
                {"t": "2026-11-17 14:02:05.5", "role": "status", "state": "done",
                 "attributes": {"finished_at": "2026-11-17T14:02:00Z", "last_reset": 1794920400000, "started": "13:00"}},
            ],
            "states": [{"role": "time_left", "state": "2026-11-17T13:45:00-00:00"}],
        }
    )
    rec = out.doc["recording"]
    assert [r["t"] for r in rec] == [0.0, 90.0, 3725.5]
    # (other values: "+<seconds>s"; a clock time with no date still goes)
    assert rec[2]["attributes"] == {"finished_at": "+3720s", "last_reset": "+0s"}
    assert ("recording[2].attributes.started", "a time of day") in out.dropped
    assert out.doc["states"] == [{"role": "time_left", "state": "+2700s"}]
    # nothing in it says what day or time it was
    flat = repr(out.doc)
    assert "2026" not in flat and "13:" not in flat and "179492" not in flat


def test_long_lists_are_cut():
    out = scrub({"recording": [{"t": i, "role": "status", "state": "on"} for i in range(MAX_LIST + 100)]})
    assert len(out.doc["recording"]) == MAX_LIST and (f"recording[{MAX_LIST}:]", "too long") in out.dropped


async def test_the_homes_own_words(hass: HomeAssistant) -> None:
    hass.config.location_name = "Maple Cottage"
    ar.async_get(hass).async_create("Jamie's Office")
    entry = MockConfigEntry(domain="ge_home", title="GE Home", data={"host": "dryer.local", "username": "jamie@example.com"})
    entry.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("ge_home", "B1234A5678"), ("ge_home", "zone", "EXTRA9988")},  # (some integrations add parts)
        connections={(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")},
        manufacturer="GE Appliances",
        model="PTD9000SN",
        name="Dryer",
        serial_number="DRY0099887766",
    )
    dr.async_get(hass).async_update_device(dev.id, name_by_user="Grandma Edith's Dryer")
    er.async_get(hass).async_get_or_create("sensor", "ge_home", "B1234A5678_status", device_id=dev.id, suggested_object_id="edith_dryer_status")
    er.async_get(hass).async_get_or_create(
        "sensor", "ge_home", "B1234A5678_speed", device_id=dev.id, suggested_object_id="speed", original_name="Spin speed"
    )
    words = secrets_from_hass(hass)
    for word in ("maple", "maple cottage", "jamie", "edith", "grandma", "b1234a5678", "extra9988", "dry0099887766", "aa:bb:cc:dd:ee:ff",
                 "sensor.edith_dryer_status", "edith_dryer_status", "dryer.local", "jamie@example.com",
                 dev.id.lower(), entry.entry_id.lower()):
        assert word in words, word
    # everyday words never count as the home's (they'd drop real states)
    for word in ("office", "dryer", "status", "room", "spin", "speed", "spin speed"):
        assert word not in words, word  # (and the integration's own words: "Spin speed", sensor.speed)
    # and a report through them: the brand stays, the names go
    out = scrub(
        {"device": {"manufacturer": "GE Appliances", "model": "PTD9000SN"},
         "states": [{"role": "status", "state": "Edith's cycle"}, {"role": "status", "state": "drying"},
                    {"role": "spin", "state": "high_speed"}]},
        words,
    )
    assert out.doc == {"device": {"manufacturer": "GE Appliances", "model": "PTD9000SN"},
                       "states": [{"role": "status"}, {"role": "status", "state": "drying"}, {"role": "spin", "state": "high_speed"}]}


def test_every_summary_line_has_its_words():
    import json
    import re
    from pathlib import Path

    from custom_components.room_tiles import report

    words = json.loads((Path(__file__).parent.parent / "frontend" / "i18n" / "en.json").read_text(encoding="utf-8"))["strings"]
    keys = set(re.findall(r'"(report\.has\.[a-z_]+)"', Path(report.__file__).read_text(encoding="utf-8")))
    assert keys and all(k in words for k in keys), keys - set(words)


async def test_report_preview(hass: HomeAssistant, hass_ws_client) -> None:
    """The dashboard's check-before-sending step: the report as it would be
    sent, scrubbed with this home's words, versions added, the GitHub issue."""
    from homeassistant.setup import async_setup_component

    from custom_components.room_tiles.const import DOMAIN

    assert await async_setup_component(hass, "homeassistant", {})
    e = MockConfigEntry(domain=DOMAIN)
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    ws = await hass_ws_client(hass)
    # a developer build's test report: full of what must not go out
    await ws.send_json({"id": 1, "type": "room_tiles/report_preview", "kind": "test"})
    msg = await ws.receive_json()
    assert msg["success"], msg
    out = msg["result"]
    sent = repr(out["report"]) + out["issue"]["body"]
    for bad in ("DRY0099887766", "Grandma", "grandma", "aa:bb:cc", "192.168", "@example.com", "2026-11-17", "12 Main"):
        assert bad not in sent, bad
    assert out["report"]["device"] == {"manufacturer": "GE Appliances", "model": "PTD9000SN"}
    assert [r["t"] for r in out["report"]["recording"]] == [0.0, 90.0, 3725.0]
    assert out["report"]["home_assistant"] and out["report"]["room_tiles"] is not None
    assert "report.has.recording" in out["summary"] and out["dropped"]
    assert out["issue"]["url"].endswith("/issues/new") and out["issue"]["title"].startswith("Test report: GE Appliances")
    # a real kind: the draft the dashboard built, scrubbed the same way
    await ws.send_json({"id": 2, "type": "room_tiles/report_preview", "kind": "unknown_state",
                        "draft": {"device": {"manufacturer": "LG", "model": "WM4000HWA"},
                                  "answers": [{"role": "status", "state": "steam_fresh", "answer": "not_running"}],
                                  "entity_id": "sensor.my_washer"}})
    msg = await ws.receive_json()
    assert msg["success"]
    assert msg["result"]["report"]["kind"] == "unknown_state" and "entity_id" not in msg["result"]["report"]


async def test_unknown_state_report_is_built_from_the_appliance(hass: HomeAssistant, hass_ws_client) -> None:
    """"Also tell Room Tiles": the dashboard names the appliance, unit, state
    and answer; HA builds the report from the device - brand, model, the
    integration, the status sensor's own states - and scrubs it."""
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
        model="PTD9000SN", sw_version="1.2.3", name="Dryer", serial_number="D9988776655",
    )
    dr.async_get(hass).async_update_device(dev.id, name_by_user="Edith's Dryer")
    er.async_get(hass).async_get_or_create("sensor", "ge_home", "D9988776655_status", device_id=dev.id, suggested_object_id="edith_dryer_status")
    hass.states.async_set("sensor.edith_dryer_status", "steam_fresh", {"options": ["idle", "drying", "steam_fresh", "done"], "device_class": "enum"})
    store = e.runtime_data
    store.data.appliances.append(
        Appliance(id="a1", name="Edith's Dryer", units=[ApplianceUnit(id="u1", label="Dryer", appliance="dryer", preset="ge_home_dryer", status="sensor.edith_dryer_status")])
    )
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "room_tiles/report_preview", "kind": "unknown_state",
                        "draft": {"appliance": "a1", "unit": "u1", "state": "steam_fresh", "answer": "drying"}})
    msg = await ws.receive_json()
    assert msg["success"], msg
    rep = msg["result"]["report"]
    assert rep["kind"] == "unknown_state" and rep["kind_of_device"] == "dryer" and rep["preset"] == "ge_home_dryer"
    assert rep["device"] == {"manufacturer": "GE Appliances", "model": "PTD9000SN", "sw_version": "1.2.3"}
    assert rep["integration"]["domain"] == "ge_home"
    assert rep["answers"] == [{"role": "status", "state": "steam_fresh", "answer": "running"}]
    assert rep["states"] == [{"role": "status", "state": "steam_fresh", "attributes": {"options": ["idle", "drying", "steam_fresh", "done"]}}]
    sent = repr(rep) + msg["result"]["issue"]["body"]
    for bad in ("Edith", "edith", "D9988776655", "sensor."):
        assert bad not in sent, bad
    # no such appliance: an error, nothing built
    await ws.send_json({"id": 2, "type": "room_tiles/report_preview", "kind": "unknown_state",
                        "draft": {"appliance": "nope", "unit": "u1", "state": "x", "answer": "off"}})
    msg = await ws.receive_json()
    assert not msg["success"] and msg["error"]["code"] == "not_found"


def test_feedback_bug_keeps_where_panel_and_browser_only():
    """Send feedback, a bug: the words, where, the panel's board and firmware,
    the browser - anything else (a panel's name, a user agent) is dropped."""
    from custom_components.room_tiles.report import issue

    out = scrub(
        {
            "kind": "bug",
            "description": "The clock froze after the router restarted.\nTwice now.",
            "where": "panel",
            "panel": {"board": "elecrow-p4-10in", "firmware": "2026.11.15", "name": "Kitchen Panel"},
            "browser": {"name": "chrome", "version": "131", "os": "android", "window": "1280x800", "agent": "Mozilla/5.0 (Linux)"},
        },
        {"kitchen"},
    )
    assert out.doc["where"] == "panel"
    assert out.doc["panel"] == {"board": "elecrow-p4-10in", "firmware": "2026.11.15"}
    assert out.doc["browser"] == {"name": "chrome", "version": "131", "os": "android", "window": "1280x800"}
    assert {"report.has.description", "report.has.where", "report.has.panel", "report.has.browser"} <= set(summary(out.doc))
    bad = scrub({"kind": "bug", "where": "garage", "browser": {"window": "big"}, "panel": {"board": "Jamie's Panel"}}, set())
    assert "where" not in bad.doc and not bad.doc.get("browser") and not bad.doc.get("panel")
    assert summary(bad.doc) == []
    got = issue(out.doc, "bug")
    # the title: the first line of the user's words; the issue form applies the label
    assert got["title"] == "Bug: The clock froze after the router restarted."
    assert got["template"] == "bug.yml" and got["field"] == "report"
    assert got["body"].startswith("**What happened**") and "> Twice now." in got["body"]


def test_feedback_titles_are_cut_at_a_word():
    from custom_components.room_tiles.report import issue

    words = "It would be great if the map could show the garage door state and the lights in the yard too"
    got = issue({"kind": "idea", "description": words}, "idea")
    assert got["title"].startswith("Idea: It would be great") and got["title"].endswith("…")
    assert len(got["title"]) <= len("Idea: ") + 61 and " too" not in got["title"]
    assert issue({"kind": "question"}, "question")["title"] == "Question"
    assert issue({"kind": "idea", "description": "x"}, "idea")["template"] == "idea.yml"
    # a test report has no issue form
    assert "template" not in issue({"kind": "test"}, "test")


async def test_feedback_preview(hass: HomeAssistant, hass_ws_client) -> None:
    from custom_components.room_tiles.const import DOMAIN

    e = MockConfigEntry(domain=DOMAIN)
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "room_tiles/report_preview", "kind": "question",
                        "draft": {"description": "Can a tile show two lights?"}})
    msg = await ws.receive_json()
    assert msg["success"], msg
    res = msg["result"]
    assert res["report"]["kind"] == "question" and res["report"]["description"] == "Can a tile show two lights?"
    assert res["issue"]["template"] == "question.yml" and res["issue"]["title"] == "Question: Can a tile show two lights?"
