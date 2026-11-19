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


def test_what_cant_be_replayed_says_so():
    with pytest.raises(ReplayError, match="no recording"):
        replay({"kind_of_device": "dryer", "preset": "ge_home_dryer"})
    with pytest.raises(ReplayError, match="isn't supported yet"):
        replay({"kind_of_device": "pool", "recording": [{"t": 0, "role": "pump", "state": "on"}]})
