"""Send feedback's extras - a panel bug's panel facts, a dashboard bug's
recent errors - and HA's Download diagnostics: what they hold, and that
nothing of the home goes with them."""

from __future__ import annotations

import base64

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.room_tiles.const import DOMAIN
from custom_components.room_tiles.report import scrub, summary

KEY = bytes(range(32))


def test_error_messages_are_masked_not_dropped():
    out = scrub(
        {
            "kind": "bug",
            "where": "dashboard",
            "errors": [
                {"ago_s": 40, "message": "Cannot read properties of undefined (reading 'state') at light.edith_lamp",
                 "where": "room-tiles-panel.js:3:51234"},
                {"ago_s": 5, "message": "fetch http://192.168.1.20:8123/api failed for Edith's Room at 13:05",
                 "where": "/local/x.js?v=1:1"},
                {"ago_s": 1700000000, "message": "x", "where": "room-tiles-panel.js:1"},
            ],
        },
        {"edith"},
    )
    e = out.doc["errors"]
    assert e[0] == {"ago_s": 40, "message": "Cannot read properties of undefined (reading 'state') at <entity>",
                    "where": "room-tiles-panel.js:3:51234"}
    assert e[1]["message"] == "fetch <url> failed for <name>'s Room at <time>" and "where" not in e[1]
    assert "ago_s" not in e[2]  # (a time of day, not seconds ago)
    assert "report.has.errors" in summary(out.doc)


async def _panel(hass: HomeAssistant) -> tuple[MockConfigEntry, str]:
    esp = MockConfigEntry(domain="esphome", data={"device_name": "panel-1", "noise_psk": base64.b64encode(KEY).decode()})
    esp.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(
        config_entry_id=esp.entry_id, connections={(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")},
        manufacturer="room-tiles", model="panel", name="Edith's panel",
    )
    reg = er.async_get(hass)
    for name, oid, state, attrs in (
        ("Reset Reason", "edith_panel_reset_reason", "Software Reset CPU", {}),
        ("Uptime", "edith_panel_uptime", "3600", {"unit_of_measurement": "s"}),
        ("Heap Free", "edith_panel_heap_free", "201234", {"unit_of_measurement": "B"}),
        ("PSRAM Free", "edith_panel_psram_free", "21000000", {"unit_of_measurement": "B"}),
    ):
        domain = "sensor"
        reg.async_get_or_create(domain, "esphome", f"aabbccddeeff-{oid}", device_id=dev.id, suggested_object_id=oid,
                                original_name=name)
        hass.states.async_set(f"{domain}.{oid}", state, attrs)
    reg.async_get_or_create("update", "esphome", "aabbccddeeff-wifi", device_id=dev.id,
                            suggested_object_id="edith_panel_wifi_chip", original_name="Wi-Fi Chip Firmware")
    hass.states.async_set("update.edith_panel_wifi_chip", "off", {"installed_version": "2.12.13"})
    e = MockConfigEntry(domain=DOMAIN)
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    return e, dev.id


async def test_a_panel_bug_holds_the_panels_facts(hass: HomeAssistant, hass_ws_client) -> None:
    _e, device_id = await _panel(hass)
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "room_tiles/report_preview", "kind": "bug", "draft": {
        "description": "The panel restarts at night.", "where": "panel", "panel_device": device_id}})
    msg = await ws.receive_json()
    assert msg["success"], msg
    panel = msg["result"]["report"]["panel"]
    assert panel["reset_reason"] == "Software Reset CPU" and panel["uptime_s"] == 3600
    assert panel["heap_free"] == 201234 and panel["psram_free"] == 21000000
    assert panel["wifi_chip"] == "2.12.13" and panel["online"] is True
    sent = repr(msg["result"]["report"]) + msg["result"]["issue"]["body"]
    for bad in ("Edith", "edith", device_id, "aa:bb", "sensor."):
        assert bad not in sent, bad
    # a panel Room Tiles doesn't know: nothing of it
    await ws.send_json({"id": 2, "type": "room_tiles/report_preview", "kind": "bug", "draft": {
        "description": "x", "where": "panel", "panel_device": "nope"}})
    msg = await ws.receive_json()
    assert msg["success"] and not msg["result"]["report"].get("panel")


async def test_diagnostics_hold_no_names(hass: HomeAssistant) -> None:
    from custom_components.room_tiles.diagnostics import async_get_config_entry_diagnostics
    from custom_components.room_tiles.model import Appliance, ApplianceUnit

    ar.async_get(hass).async_create("Edith's Room")
    e, _device_id = await _panel(hass)
    e.runtime_data.data.appliances.append(Appliance(id="edith_dryer", name="Edith's Dryer", units=[
        ApplianceUnit(id="u1", label="Dryer", appliance="dryer", preset="lg_thinq_dryer", status="sensor.edith_dryer")]))
    out = await async_get_config_entry_diagnostics(hass, e)
    assert out["versions"]["room_tiles"] is not None and out["versions"]["panel_schema"] >= 1
    assert out["appliances"][0]["appliance"] == "appliance_1"
    assert out["appliances"][0]["units"][0]["preset"] == "lg_thinq_dryer"
    assert all(a["area"].startswith("area_") for a in out["areas"])
    assert len(out["panels"]) == 1
    flat = repr(out).lower()
    for bad in ("edith", "sensor.", "aa:bb"):
        assert bad not in flat, bad
