"""Report how it went (model_report.py): what's beta, the features to
check, and the report HA builds."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.room_tiles.model import Appliance, ApplianceUnit, PoolSystem, RoomTilesData
from custom_components.room_tiles.model_report import features, model_draft
from custom_components.room_tiles.report import issue, scrub, summary


def _laundry() -> Appliance:
    return Appliance(id="a1", name="Laundry", units=[
        ApplianceUnit(id="w", label="Washer", appliance="washer", preset="lg_thinq_washer", status="sensor.washer_status"),
        ApplianceUnit(id="d", label="Dryer", appliance="dryer", preset="lg_thinq_dryer", status="sensor.dryer_status"),
    ])


def test_features_by_kind():
    data = RoomTilesData(appliances=[_laundry()], pools=[PoolSystem(id="p", name="Pool", preset="iaqualink", layout="pool")])
    # a washer and a dryer on one tile: that's a feature to check too
    assert features(data, "appliance", "a1", "w") == ["running", "status_text", "time_left", "paused", "error", "door", "laundry_pair"]
    assert features(data, "pool", "p") == ["water_temp", "target", "heater", "chill", "pump", "time_to_target", "switching"]
    assert features(data, "appliance", "a1", "nope") == [] and features(data, "robot", "x") == []


def test_model_draft_keeps_only_this_kinds_features():
    d = model_draft(["running", "door"], "partly", {"running": "works", "door": "sideways", "zones": "works"}, "  ")
    assert d == {"outcome": "partly", "checklist": {"running": "works", "door": "not_tried"}}
    out = scrub({"kind": "model", **d, "device": {"manufacturer": "LG", "model": "WM4000HWA"}}, set())
    assert out.dropped == [] and "report.has.checklist" in summary(out.doc)
    got = issue(out.doc, "model")
    assert got["title"] == "Model report (partly works): LG WM4000HWA" and got["template"] == "model.yml"


async def _dryer(hass: HomeAssistant, model: str) -> MockConfigEntry:
    from custom_components.room_tiles.const import DOMAIN

    e = MockConfigEntry(domain=DOMAIN)
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    lg = MockConfigEntry(domain="lg_thinq", title="LG ThinQ")
    lg.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(
        config_entry_id=lg.entry_id, identifiers={("lg_thinq", "SN123456789")}, manufacturer="LGE", model=model, name="Dryer",
    )
    dr.async_get(hass).async_update_device(dev.id, name_by_user="Edith's Dryer")
    er.async_get(hass).async_get_or_create("sensor", "lg_thinq", "SN123456789_status", device_id=dev.id,
                                           suggested_object_id="dryer_status")
    hass.states.async_set("sensor.dryer_status", "power_off")
    e.runtime_data.data.appliances.append(Appliance(id="a1", name="Edith's Dryer", units=[
        ApplianceUnit(id="u1", label="Dryer", appliance="dryer", preset="lg_thinq_dryer", status="sensor.dryer_status")]))
    e.runtime_data.async_changed(("appliances",))
    await hass.async_block_till_done()
    return e


async def test_beta_and_the_report(hass: HomeAssistant, hass_ws_client) -> None:
    e = await _dryer(hass, "DLEX3900W (DEVICE_DRYER)")
    # not a confirmed model: beta - its card offers Report how it went
    assert e.runtime_data.payload()["beta"] == {"appliance:a1": ["u1"]}
    ws = await hass_ws_client(hass)
    who = {"subject": "appliance", "target": "a1", "unit": "u1"}
    await ws.send_json({"id": 1, "type": "room_tiles/problem_cycles", **who})
    msg = await ws.receive_json()
    assert msg["success"] and "time_left" in msg["result"]["features"]
    # how it went, each feature, the user's words - no cycle added
    await ws.send_json({"id": 2, "type": "room_tiles/report_preview", "kind": "model", "draft": {
        **who, "outcome": "works", "checklist": {"running": "works", "time_left": "partly"},
        "description": "Edith's dryer: time left jumps at the end."}})
    msg = await ws.receive_json()
    assert msg["success"], msg
    rep = msg["result"]["report"]
    assert rep["kind"] == "model" and rep["outcome"] == "works" and rep["preset"] == "lg_thinq_dryer"
    assert rep["checklist"]["running"] == "works" and rep["checklist"]["door"] == "not_tried"
    assert rep["device"]["model"] == "DLEX3900W (DEVICE_DRYER)" and "recording" not in rep
    assert msg["result"]["issue"]["title"] == "Model report (works): LGE DLEX3900W (DEVICE_DRYER)"
    assert any(w["why"] == "name" for w in msg["result"]["warnings"])  # ("Edith's" is a name here)
    for bad in ("SN123456789", "sensor."):
        assert bad not in repr(rep), bad
    # how it went is needed
    await ws.send_json({"id": 3, "type": "room_tiles/report_preview", "kind": "model", "draft": {**who, "checklist": {}}})
    msg = await ws.receive_json()
    assert not msg["success"] and msg["error"]["code"] == "invalid_format"


async def test_a_confirmed_model_isnt_beta(hass: HomeAssistant) -> None:
    e = await _dryer(hass, "RV13D4ASJW_D_US (DEVICE_DRYER)")
    assert e.runtime_data.payload()["beta"] == {}
