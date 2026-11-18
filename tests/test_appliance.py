"""Appliance profile logic (appliance.py + presets) - the same behaviour as
the hand-written template sensors it replaces."""

from datetime import datetime, timedelta, timezone

from custom_components.room_tiles.appliance import (
    UnitLogic,
    classify,
    format_minutes,
    minutes_left,
    status_text,
)
from custom_components.room_tiles.appliance_presets import (
    FP_DISHDRAWER,
    GE_HOME_DISHWASHER,
    LG_THINQ_DRYER,
    LG_THINQ_WASHER,
)

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def test_classify_lg_washer():
    p = LG_THINQ_WASHER
    assert classify(p, "power_off") == "off"
    assert classify(p, "end") == "off"
    assert classify(p, "reserved") == "off"
    for raw in ("initial", "detecting", "running", "rinsing", "spinning"):
        assert classify(p, raw) == "washing"
    assert classify(p, "pause") == "paused"
    assert classify(p, "error") == "error"
    assert classify(p, "unavailable") is None
    assert classify(p, "something_new") == "washing"  # unknown never breaks the tile


def test_washer_waits_for_the_dryer():
    w = UnitLogic(LG_THINQ_WASHER, finished="waiting")
    assert w.update("power_off") == "idle"
    assert w.update("initial") == "washing"
    assert w.update("spinning") == "washing"
    assert w.update("end") == "waiting"
    assert w.update("power_off") == "waiting"  # stays until cleared
    assert w.clear() == "idle"  # the dryer started


def test_a_dropout_never_finishes_a_cycle():
    w = UnitLogic(LG_THINQ_WASHER)
    w.update("running")
    assert w.update("unavailable") == "washing"
    assert w.update("running") == "washing"


def test_error_then_off_is_idle_not_done():
    d = UnitLogic(LG_THINQ_DRYER)
    d.update("running")
    assert d.update("error") == "error"
    assert d.update("power_off") == "idle"


def test_paused_then_stopped_is_done():
    d = UnitLogic(LG_THINQ_DRYER)
    d.update("running")
    assert d.update("pause") == "paused"
    assert d.update("end") == "done"


def test_running_again_replaces_done():
    d = UnitLogic(LG_THINQ_DRYER)
    d.update("cooling")
    d.update("end")
    assert d.update("running") == "drying"


def test_dishwasher_drawer_door():
    u = UnitLogic(FP_DISHDRAWER)
    assert u.update("Main Wash") == "washing"
    assert u.update("Drying") == "drying"
    assert u.update("N/A") == "done"
    assert u.set_door(True) == "door_open"  # opening it empties it
    assert u.set_door(False) == "idle"
    # door open while running shows the door, running underneath
    u.update("Main Wash")
    assert u.set_door(True) == "door_open"
    assert u.set_door(False) == "washing"


def test_door_left_open_does_not_eat_the_next_done():
    u = UnitLogic(GE_HOME_DISHWASHER)
    u.set_door(True)
    u.update("Main Wash")
    u.set_door(False)
    assert u.update("N/A") == "done"


def test_status_text():
    assert status_text(FP_DISHDRAWER, "door_open", "N/A", drawer=True) == "Drawer Open"
    assert status_text(GE_HOME_DISHWASHER, "door_open", "N/A") == "Door Open"
    assert status_text(FP_DISHDRAWER, "done", "N/A") == "Clean"
    assert status_text(LG_THINQ_DRYER, "done", "end") == "Done"
    assert status_text(LG_THINQ_WASHER, "waiting", "end") == "Switch Over"
    assert status_text(LG_THINQ_WASHER, "paused", "pause") == "Paused"
    assert status_text(FP_DISHDRAWER, "washing", "Main Wash") == "Main Wash"
    assert status_text(LG_THINQ_WASHER, "washing", "rinsing") == "Rinsing"
    assert status_text(LG_THINQ_DRYER, "drying", "wrinkle_care") == "Wrinkle care"
    assert status_text(LG_THINQ_WASHER, "washing", "rinse_hold") == "Rinse hold"
    assert status_text(LG_THINQ_WASHER, "idle", "power_off") == ""


def test_time_left_finish_timestamp():
    finish = (NOW + timedelta(minutes=44, seconds=10)).isoformat()
    assert minutes_left(LG_THINQ_WASHER, "washing", "running", finish, None, NOW) == 45
    # placeholder while the load is being sized, and while paused
    assert minutes_left(LG_THINQ_WASHER, "washing", "detecting", finish, None, NOW) is None
    assert minutes_left(LG_THINQ_WASHER, "paused", "pause", finish, None, NOW) is None
    assert minutes_left(LG_THINQ_WASHER, "idle", "power_off", finish, None, NOW) is None
    assert minutes_left(LG_THINQ_WASHER, "washing", "running", "unknown", None, NOW) is None


def test_time_left_drawer_countdown_must_move():
    p = FP_DISHDRAWER
    moving = NOW - timedelta(minutes=1)
    stale = NOW - timedelta(minutes=10)
    # a real countdown: 1.5 h
    assert minutes_left(p, "washing", "Main Wash", "1.5", "h", NOW, value_changed=moving) == 90
    # the held placeholder: no time in Main Wash...
    assert minutes_left(p, "washing", "Main Wash", "0.0167", "h", NOW, value_changed=stale) is None
    # ...an estimate from the phase start in Rinsing / Drying
    started = NOW - timedelta(minutes=20)
    assert (
        minutes_left(p, "washing", "Rinsing", "0.0167", "h", NOW, value_changed=stale, raw_changed=started)
        == 46
    )
    assert (
        minutes_left(p, "drying", "Drying", "0.0167", "h", NOW, value_changed=stale, raw_changed=started)
        == 12
    )
    # an estimate that ran out shows nothing
    long_ago = NOW - timedelta(minutes=40)
    assert (
        minutes_left(p, "drying", "Drying", "0.0167", "h", NOW, value_changed=stale, raw_changed=long_ago)
        is None
    )


def test_time_left_plain_duration_uses_its_unit():
    p = GE_HOME_DISHWASHER
    assert minutes_left(p, "washing", "Main Wash", "50", "min", NOW) == 50
    assert minutes_left(p, "washing", "Main Wash", "0.5", "h", NOW) == 30


def test_format_minutes():
    assert format_minutes(None) == ""
    assert format_minutes(0) == ""
    assert format_minutes(45) == "~45m"
    assert format_minutes(65) == "~1h 05m"
    assert format_minutes(179) == "~2h 59m"


def test_format_minutes_in_the_language():
    from custom_components.room_tiles import wording

    wording.set_language("de")
    try:
        assert format_minutes(45) == "~45 Min."
        assert format_minutes(65) == "~1:05 h"
    finally:
        wording.set_language("en")


def test_door_that_does_not_empty_it():
    u = UnitLogic(FP_DISHDRAWER, door_clears=False)
    u.update("Drying")
    u.update("N/A")
    assert u.set_door(True) == "door_open"  # still shown
    assert u.set_door(False) == "done"  # but it stays done


def test_finished_can_be_plain_idle():
    d = UnitLogic(LG_THINQ_DRYER, finished="idle")
    d.update("running")
    assert d.update("end") == "idle"


def test_beta_presets_read_their_brands_states():
    from custom_components.room_tiles.appliance_presets import (
        GE_HOME_WASHER,
        HOME_CONNECT_DISHWASHER,
        MIELE_WASHER,
        SMARTTHINGS_WASHER,
        WHIRLPOOL_DRYER,
    )

    def cycle(preset, steps, finished="done"):
        u = UnitLogic(preset, finished=finished)
        return [u.update(s) for s in steps]

    assert cycle(SMARTTHINGS_WASHER, ["none", "weight_sensing", "wash", "rinse", "spin", "finish", "none"]) == [
        "idle", "washing", "washing", "washing", "washing", "done", "done",
    ]
    assert cycle(WHIRLPOOL_DRYER, ["standby", "running_maincycle", "pause", "running_maincycle", "complete"]) == [
        "idle", "drying", "paused", "drying", "done",
    ]
    assert cycle(HOME_CONNECT_DISHWASHER, ["ready", "run", "actionrequired", "run", "finished", "ready"]) == [
        "idle", "washing", "paused", "washing", "done", "done",
    ]
    # Miele: not connected is "no news", never the end of a cycle
    assert cycle(MIELE_WASHER, ["off", "in_use", "not_connected", "in_use", "program_ended"]) == [
        "idle", "washing", "washing", "washing", "done",
    ]
    assert cycle(GE_HOME_WASHER, ["Standby", "Run", "Paused", "Run", "Finished"]) == [
        "idle", "washing", "paused", "washing", "done",
    ]
    assert status_text(HOME_CONNECT_DISHWASHER, "paused", "actionrequired") == "Paused"
    assert status_text(WHIRLPOOL_DRYER, "drying", "running_postcycle") == "Finishing"
    assert status_text(SMARTTHINGS_WASHER, "washing", "ai_wash") == "AI wash"


def test_matter_operational_state():
    from custom_components.room_tiles.appliance_presets import MATTER_WASHER

    u = UnitLogic(MATTER_WASHER)
    assert [u.update(s) for s in ("stopped", "running", "paused", "running", "error", "stopped")] == [
        "idle",
        "washing",
        "paused",
        "washing",
        "error",
        "idle",
    ]
    assert [u.update(s) for s in ("running", "stopped")] == ["washing", "done"]


def test_power_raw_smart_plug():
    from custom_components.room_tiles.appliance import power_raw

    # above the threshold: running
    assert power_raw(450, 5, None, 0, 180, False) == ("running", None)
    # dips below (a soak): still running until it has stayed low 3 minutes
    assert power_raw(1, 5, None, 100, 180, True) == ("running", 100)
    assert power_raw(1, 5, 100, 250, 180, True) == ("running", 100)
    assert power_raw(1, 5, 100, 281, 180, True) == ("off", 100)
    # never ran: low is just off
    assert power_raw(0, 5, None, 0, 180, False) == ("off", 0)
    # no reading: no news
    assert power_raw(None, 5, 100, 400, 180, True) == (None, 100)
