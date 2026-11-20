"""Reports as tests (tools/report_to_test.py): every case in tests/reports/
- a user's recorded cycle - replays through today's logic to exactly what
it showed when it was taken in. A preset change that alters one fails
here: check the report again (docs/TODO.md "Formal procedure to clear a
beta flag")."""

import json
from pathlib import Path

import pytest

from custom_components.room_tiles.replay import ReplayError, replay

CASES = sorted((Path(__file__).parent / "reports").glob("*.json"))


@pytest.mark.parametrize("path", CASES, ids=[p.stem for p in CASES])
def test_a_report_replays_as_it_was_taken_in(path):
    case = json.loads(path.read_text(encoding="utf-8"))
    assert replay(case["report"]) == case["expect"], f"{path.name} ({case['source']}): the logic shows something else now"


def test_a_vacuums_report_replays_its_answers():
    report = {
        "kind_of_device": "vacuum",
        "preset": "matter",
        "answers": [{"role": "error", "state": "mystery_code", "answer": "needs_you"}],
        "recording": [
            {"t": 0, "role": "vacuum", "state": "docked"},
            {"t": 5, "role": "error", "state": "no_error"},
            {"t": 60, "role": "vacuum", "state": "cleaning"},
            {"t": 900, "role": "error", "state": "mystery_code"},
            {"t": 960, "role": "error", "state": "no_error"},
            {"t": 1500, "role": "vacuum", "state": "returning"},
            {"t": 1530, "role": "vacuum", "state": "docked"},
        ],
    }
    assert [s["shown"] for s in replay(report)] == ["docked", "cleaning", "attention", "cleaning", "returning", "docked"]


def _heater(mode, action, target=None):
    return {"state": mode, "attributes": {"hvac_action": action, "temperature": target}}


def test_a_shared_pools_report_replays_each_body():
    report = {
        "kind_of_device": "pool",
        "preset": "iaqualink",
        "layout": "shared",
        "recording": [
            # the start: every entity's state (one moment)
            {"t": 0, "role": "spa_mode", "state": "off"},
            {"t": 0, "role": "pump", "state": "on"},
            {"t": 0, "role": "pool_temp", "state": "80"},
            {"t": 0, "role": "pool_heater", **_heater("heat", "heating", 84)},
            {"t": 0, "role": "spa_heater", **_heater("off", "off", 100)},
            {"t": 600, "role": "pool_heater", **_heater("heat", "idle", 84)},
            # spa mode: the pool's sensor still reads for a moment (valves turning)
            {"t": 900, "role": "spa_mode", "state": "on"},
            {"t": 960, "role": "pool_temp", "state": "unavailable"},
            {"t": 961, "role": "spa_temp", "state": "92"},
            {"t": 962, "role": "spa_heater", **_heater("heat", "heating", 100)},
            # a short drop-out of the controller: the tiles keep what they had
            {"t": 1500, "role": "pump", "state": "unavailable"},
            {"t": 1530, "role": "pump", "state": "on"},
            # ... a long one: offline
            {"t": 2000, "role": "pump", "state": "unavailable"},
            {"t": 2200, "role": "spa_temp", "state": "93"},
        ],
    }
    assert [s["shown"] for s in replay(report)] == [
        "pool heating, spa standby",
        "pool idle, spa standby",
        "pool standby, spa switching",
        "pool standby, spa off",
        "pool standby, spa heating",
        "pool offline, spa offline",
    ]


def test_a_pool_with_its_own_pump_and_no_heater():
    report = {
        "kind_of_device": "pool",
        "layout": "pool",
        "recording": [
            {"t": 0, "role": "pool_pump", "state": "off"},
            {"t": 60, "role": "pool_pump", "state": "on"},
            {"t": 90, "role": "pool_temp", "state": "78"},
            {"t": 7200, "role": "pool_pump", "state": "off"},
        ],
    }
    assert [s["shown"] for s in replay(report)] == ["pool pump_off", "pool on", "pool pump_off"]


def test_what_cant_be_replayed_says_so():
    with pytest.raises(ReplayError, match="no recording"):
        replay({"kind_of_device": "dryer", "preset": "ge_home_dryer"})
    with pytest.raises(ReplayError, match="no pool layout"):
        replay({"kind_of_device": "pool", "recording": [{"t": 0, "role": "pump", "state": "on"}]})
    with pytest.raises(ReplayError, match="isn't supported yet"):
        replay({"kind_of_device": "fridge", "recording": [{"t": 0, "role": "status", "state": "on"}]})
