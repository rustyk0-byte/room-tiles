"""Appliance profiles inside a test HA: the sensor follows a real cycle, the
finder offers supported devices, the tile picker gets the sensor."""

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.room_tiles.const import DOMAIN

LAUNDRY = {
    "id": "laundry",
    "name": "Laundry",
    "units": [
        {
            "id": "dryer",
            "label": "Dryer",
            "appliance": "dryer",
            "preset": "lg_thinq_dryer",
            "status": "sensor.dryer_status",
            "time": "sensor.dryer_finish",
            "clear": ["binary_sensor.laundry_door"],
        },
        {
            "id": "washer",
            "label": "Washer",
            "appliance": "washer",
            "preset": "lg_thinq_washer",
            "status": "sensor.washer_status",
            "finished": "waiting",
            "clear": ["unit:dryer"],
        },
    ],
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


async def _set(hass, entity, state, **attrs):
    hass.states.async_set(entity, state, attrs)
    await hass.async_block_till_done()


def _units(hass):
    st = hass.states.get("sensor.room_tiles_laundry")
    return st, {u["id"]: u for u in st.attributes["units"]}


async def test_laundry_cycle(hass: HomeAssistant, entry) -> None:
    for e in ("sensor.dryer_status", "sensor.washer_status"):
        hass.states.async_set(e, "power_off")
    hass.states.async_set("binary_sensor.laundry_door", "off")
    res = await _call(hass, "set_appliance", response=True, appliance=LAUNDRY)
    await hass.async_block_till_done()
    assert res == {"entity": "sensor.room_tiles_laundry", "ask": []}
    st, u = _units(hass)
    assert st.state == "idle"
    assert st.attributes["own_name"] == "Laundry"  # Room Tiles' name, whatever HA's friendly name is
    assert entry.runtime_data.data.catalog.get("sensor.room_tiles_laundry").kind == "appliance"

    finish = (dt_util.utcnow() + timedelta(minutes=30)).isoformat()
    await _set(hass, "sensor.dryer_finish", finish)
    await _set(hass, "sensor.washer_status", "running")
    st, u = _units(hass)
    assert st.state == "active"
    assert (u["washer"]["phase"], u["washer"]["status"]) == ("washing", "Running")

    await _set(hass, "sensor.washer_status", "end")
    st, u = _units(hass)
    assert (u["washer"]["phase"], u["washer"]["status"]) == ("waiting", "Switch Over")

    # starting the dryer empties the washer
    await _set(hass, "sensor.dryer_status", "running")
    st, u = _units(hass)
    assert u["washer"]["phase"] == "idle"
    assert u["dryer"]["phase"] == "drying"
    assert u["dryer"]["time_left"] in ("~30m", "~29m")
    assert st.attributes["tile"].startswith("Dryer|drying|Running|shirt|~")
    import json

    words = json.loads(st.attributes["tile_words"])
    assert words["0.2"] == {"k": "step.running"} and set(words["0.4"]) == {"min"}

    await _set(hass, "sensor.dryer_status", "end")
    _, u = _units(hass)
    assert (u["dryer"]["phase"], u["dryer"]["status"]) == ("done", "Done")
    # the picked door sensor opening empties it
    await _set(hass, "binary_sensor.laundry_door", "on")
    st, u = _units(hass)
    assert u["dryer"]["phase"] == "idle"
    assert st.state == "idle"


async def test_tap_clears(hass: HomeAssistant, entry) -> None:
    hass.states.async_set("sensor.dryer_status", "running")
    hass.states.async_set("sensor.washer_status", "power_off")
    await _call(hass, "set_appliance", appliance=LAUNDRY)
    await hass.async_block_till_done()
    await _set(hass, "sensor.dryer_status", "end")
    assert _units(hass)[1]["dryer"]["phase"] == "done"
    await _call(hass, "clear_appliance", appliance="laundry", unit="dryer")
    assert _units(hass)[1]["dryer"]["phase"] == "idle"
    with pytest.raises(ServiceValidationError):
        await _call(hass, "clear_appliance", appliance="attic")


async def test_bad_profile_is_refused(hass: HomeAssistant, entry) -> None:
    bad = {**LAUNDRY, "units": [{**LAUNDRY["units"][0], "preset": "acme_dryer"}]}
    with pytest.raises(ServiceValidationError, match="unknown appliance preset"):
        await _call(hass, "set_appliance", appliance=bad)
    assert entry.runtime_data.data.appliances == []


async def test_remove_appliance_removes_its_sensor(hass: HomeAssistant, entry) -> None:
    hass.states.async_set("sensor.dryer_status", "power_off")
    hass.states.async_set("sensor.washer_status", "power_off")
    await _call(hass, "set_appliance", appliance=LAUNDRY)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.room_tiles_laundry") is not None
    await _call(hass, "remove_appliance", appliance="laundry")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.room_tiles_laundry") is None
    assert er.async_get(hass).async_get("sensor.room_tiles_laundry") is None


async def test_finder_offers_supported_devices(hass: HomeAssistant, entry) -> None:
    other = MockConfigEntry(domain="lg_thinq")
    other.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    reg = er.async_get(hass)
    for key, model in (("w", "F3P2 (DEVICE_WASHER)"), ("d", "RV13 (DEVICE_DRYER)")):
        dev = dev_reg.async_get_or_create(
            config_entry_id=other.entry_id, identifiers={("lg_thinq", key)}, manufacturer="LGE", model=model
        )
        reg.async_get_or_create(
            "sensor", "lg_thinq", f"{key}_current_state", device_id=dev.id, translation_key="current_state"
        )
        reg.async_get_or_create("sensor", "lg_thinq", f"{key}_remain", device_id=dev.id, translation_key="remain")
    await hass.async_block_till_done()
    found = entry.runtime_data.appliance_found["found"]
    assert [f["id"] for f in found] == ["laundry"]
    # once set up, it's no longer offered - but can be set up again
    await _call(hass, "set_appliance", appliance={k: v for k, v in found[0].items() if k != "notes"})
    await hass.async_block_till_done()
    assert entry.runtime_data.appliance_found["found"] == []
    assert list(entry.runtime_data.appliance_found["again"]) == ["laundry"]
    # removed: offered again
    await _call(hass, "remove_appliance", appliance="laundry")
    await hass.async_block_till_done()
    assert [f["id"] for f in entry.runtime_data.appliance_found["found"]] == ["laundry"]


def _single(aid, kind, status):
    return {
        "id": aid,
        "name": kind.capitalize(),
        "units": [{"id": kind, "label": kind.capitalize(), "appliance": kind, "preset": f"lg_thinq_{kind}", "status": status}],
    }


async def test_combine_and_split(hass: HomeAssistant, entry) -> None:
    ar.async_get(hass).async_create("Laundry Room")
    await hass.async_block_till_done()
    hass.states.async_set("sensor.w", "power_off")
    hass.states.async_set("sensor.d", "power_off")
    await _call(hass, "set_appliance", appliance=_single("washer", "washer", "sensor.w"))
    await _call(hass, "set_appliance", appliance=_single("dryer", "dryer", "sensor.d"))
    await hass.async_block_till_done()
    data = entry.runtime_data.data
    # a tile showing the washer follows it into the combined tile
    area = data.areas[0].id
    await _call(hass, "set_tile", area=area, layout="5x2", slot=0, entity="sensor.room_tiles_washer")

    await _call(hass, "combine_appliances", appliance="dryer", **{"with": "washer"})
    await hass.async_block_till_done()
    data = entry.runtime_data.data
    [ap] = data.appliances
    assert (ap.id, ap.name, [u.id for u in ap.units]) == ("dryer", "Laundry", ["dryer", "washer"])
    washer = ap.units[1]
    assert (washer.finished, washer.clear) == ("waiting", ["unit:dryer"])
    assert hass.states.get("sensor.room_tiles_washer") is None
    assert data.catalog.get("sensor.room_tiles_washer") is None
    # the washer's tile now shows the combined one
    assert data.area(area).tiles["5x2"][0].entity == "sensor.room_tiles_dryer"

    res = await _call(hass, "split_appliance", response=True, appliance="dryer", unit="washer")
    await hass.async_block_till_done()
    assert res["appliance"] == "washer"
    data = entry.runtime_data.data
    assert [(a.id, len(a.units)) for a in data.appliances] == [("dryer", 1), ("washer", 1)]
    w = data.appliances[1].units[0]
    # the washer keeps Switch Over: the dryer's own tile starting empties it
    assert (w.finished, w.clear) == ("waiting", ["appliance:dryer"])
    assert hass.states.get("sensor.room_tiles_washer") is not None
    assert data.catalog.get("sensor.room_tiles_washer") is not None
    await _set(hass, "sensor.w", "running")
    await _set(hass, "sensor.w", "end")
    assert hass.states.get("sensor.room_tiles_washer").attributes["units"][0]["phase"] == "waiting"
    await _set(hass, "sensor.d", "running")
    assert hass.states.get("sensor.room_tiles_washer").attributes["units"][0]["phase"] == "idle"

    with pytest.raises(ServiceValidationError):
        await _call(hass, "split_appliance", appliance="dryer", unit="dryer")  # only one unit left



async def test_combine_puts_the_dryer_on_top(hass: HomeAssistant, entry) -> None:
    hass.states.async_set("sensor.w", "power_off")
    hass.states.async_set("sensor.d", "power_off")
    await _call(hass, "set_appliance", appliance=_single("washer", "washer", "sensor.w"))
    await _call(hass, "set_appliance", appliance=_single("dryer", "dryer", "sensor.d"))
    await hass.async_block_till_done()
    await _call(hass, "combine_appliances", appliance="washer", **{"with": "dryer"})
    [ap] = entry.runtime_data.data.appliances
    assert (ap.id, [u.id for u in ap.units]) == ("washer", ["dryer", "washer"])
    assert ap.units[1].clear == ["unit:dryer"]


async def test_live_settings_changes_apply_at_once(hass: HomeAssistant, entry) -> None:
    """The sensor follows the saved setup: edits re-apply to the running logic."""
    hass.states.async_set("sensor.dryer_status", "running")
    hass.states.async_set("sensor.washer_status", "power_off")
    hass.states.async_set("binary_sensor.laundry_door", "off")
    await _call(hass, "set_appliance", appliance=LAUNDRY)
    await hass.async_block_till_done()
    await _set(hass, "sensor.dryer_status", "end")
    assert _units(hass)[1]["dryer"]["phase"] == "done"

    # the picked sensor removed: opening the door no longer empties it
    no_door = {**LAUNDRY, "units": [{**LAUNDRY["units"][0], "clear": []}, LAUNDRY["units"][1]]}
    await _call(hass, "set_appliance", appliance=no_door)
    await hass.async_block_till_done()
    await _set(hass, "binary_sensor.laundry_door", "on")
    assert _units(hass)[1]["dryer"]["phase"] == "done"

    # "When it finishes, show: Idle" while it shows Done: back to idle at once
    idle = {**no_door, "units": [{**no_door["units"][0], "finished": "idle"}, no_door["units"][1]]}
    await _call(hass, "set_appliance", appliance=idle)
    await hass.async_block_till_done()
    assert _units(hass)[1]["dryer"]["phase"] == "idle"
    # ...and the next cycle ends straight in idle
    await _set(hass, "sensor.dryer_status", "running")
    await _set(hass, "sensor.dryer_status", "end")
    assert _units(hass)[1]["dryer"]["phase"] == "idle"

    # swapped order: the tile text follows
    swapped = {**idle, "units": list(reversed(idle["units"]))}
    await _call(hass, "set_appliance", appliance=swapped)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.room_tiles_laundry").attributes["tile"].startswith("Washer|")



async def test_renaming_an_appliance_renames_its_tile_picker_entry(hass: HomeAssistant, entry) -> None:
    hass.states.async_set("sensor.dryer_status", "power_off")
    hass.states.async_set("sensor.washer_status", "power_off")
    await _call(hass, "set_appliance", appliance=LAUNDRY)
    def short() -> str:  # each edit replaces the data: read it fresh
        return entry.runtime_data.data.catalog.get("sensor.room_tiles_laundry").short_name

    assert short() == "Laundry"
    await _call(hass, "set_appliance", appliance={**LAUNDRY, "name": "Utility Room"})
    assert short() == "Utility Room"
    # saving other changes keeps a short name set on the Short names page
    await _call(hass, "set_short_name", entity="sensor.room_tiles_laundry", short_name="Utility")
    await _call(hass, "set_appliance", appliance={**LAUNDRY, "name": "Utility Room", "units": list(reversed(LAUNDRY["units"]))})
    assert short() == "Utility"


async def test_smart_plug_washer(hass: HomeAssistant, entry, freezer) -> None:
    """Any appliance on a power-monitoring plug: running while it draws
    power, done once it has stayed low for its off-after minutes."""
    hass.states.async_set("sensor.washer_plug_power", "0")
    plug = {
        "id": "washer",
        "name": "Washer",
        "units": [
            {"id": "washer", "label": "Washer", "appliance": "washer", "preset": "power_washer",
             "status": "sensor.washer_plug_power", "power_on_w": 10, "power_off_min": 3}
        ],
    }
    await _call(hass, "set_appliance", appliance=plug)
    await hass.async_block_till_done()
    st = lambda: hass.states.get("sensor.room_tiles_washer").attributes["units"][0]  # noqa: E731
    assert st()["phase"] == "idle"
    await _set(hass, "sensor.washer_plug_power", "420")
    assert (st()["phase"], st()["status"]) == ("washing", "Running")
    await _set(hass, "sensor.washer_plug_power", "2")  # a soak
    freezer.tick(60)
    await _set(hass, "sensor.washer_plug_power", "1")
    assert st()["phase"] == "washing"
    freezer.tick(200)  # low for over 3 minutes: the minute check finishes it
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert st()["phase"] == "done"


async def test_ignore_and_add_back(hass: HomeAssistant, entry) -> None:
    """Ignore takes a set-up appliance out and keeps it under Ignored (not
    offered, not counted); adding it again brings it back."""
    other = MockConfigEntry(domain="lg_thinq")
    other.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    reg = er.async_get(hass)
    for key, model in (("w", "F3P2 (DEVICE_WASHER)"), ("d", "RV13 (DEVICE_DRYER)")):
        dev = dev_reg.async_get_or_create(config_entry_id=other.entry_id, identifiers={("lg_thinq", key)}, manufacturer="LGE", model=model)
        reg.async_get_or_create("sensor", "lg_thinq", f"{key}_current_state", device_id=dev.id, translation_key="current_state")
    await hass.async_block_till_done()
    rt = entry.runtime_data
    [laundry] = rt.appliance_found["found"]
    profile = {k: v for k, v in laundry.items() if k != "notes"}
    await _call(hass, "set_appliance", appliance=profile)
    await hass.async_block_till_done()
    # ignore the set-up one: gone from Room Tiles, listed as ignored, not offered
    await _call(hass, "ignore_device", kind="appliance", device=profile, set_up_id="laundry")
    await hass.async_block_till_done()
    assert rt.data.appliances == []
    assert rt.appliance_found["found"] == []
    assert [f["id"] for f in rt.appliance_found["found_ignored"]] == ["laundry"]
    # added back: no longer ignored
    await _call(hass, "set_appliance", appliance=profile)
    await hass.async_block_till_done()
    assert rt.data.ignored == []
    assert rt.appliance_found["found_ignored"] == []


async def test_unknown_state_is_asked_once_and_answered(hass: HomeAssistant, entry) -> None:
    from homeassistant.helpers import issue_registry as ir

    hass.states.async_set("sensor.dryer_status", "power_off")
    hass.states.async_set("sensor.washer_status", "power_off")
    await _call(hass, "set_appliance", appliance=LAUNDRY)
    await hass.async_block_till_done()
    await _set(hass, "sensor.dryer_status", "steam_fresh")  # not in the LG preset
    st, u = _units(hass)
    assert u["dryer"]["phase"] == "drying"  # counts as running meanwhile
    assert st.attributes["questions"] == [{"unit": "dryer", "label": "Dryer", "state": "steam_fresh"}]
    assert ir.async_get(hass).async_get_issue(DOMAIN, "appliance_question_laundry") is not None
    await _set(hass, "sensor.dryer_status", "steam_fresh")  # asked once
    assert len(hass.states.get("sensor.room_tiles_laundry").attributes["questions"]) == 1

    # answered (the Appliances page): "not running" -> it's off, question gone
    answered = {**LAUNDRY, "units": [{**LAUNDRY["units"][0], "overrides": {"steam_fresh": "off"}}, LAUNDRY["units"][1]]}
    await _call(hass, "set_appliance", appliance=answered)
    await hass.async_block_till_done()
    st, u = _units(hass)
    assert st.attributes["questions"] == []
    assert ir.async_get(hass).async_get_issue(DOMAIN, "appliance_question_laundry") is None
    # from now on "steam_fresh" means not running (it was running when answered,
    # so its next stop is a finished cycle - then the state no longer runs)
    await _call(hass, "clear_appliance", appliance="laundry", unit="dryer")
    await _set(hass, "sensor.dryer_status", "steam_fresh")
    _, u = _units(hass)
    assert (u["dryer"]["phase"], u["dryer"]["running"]) == ("idle", False)
