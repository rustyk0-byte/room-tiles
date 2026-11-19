"""A report's recorded cycle replayed through Room Tiles' logic: what the
tile shows, step by step (docs/TODO.md "Formal procedure to clear a beta
flag" - the evidence). Pure: no Home Assistant. Used by
tools/report_to_test.py (a report becomes a test case) and
tests/test_reports.py (every case replays the same, release after release).

A report (report.py) has `kind_of_device`, `preset`, its user's `answers`
and `recording`: rows of {"t": seconds from the start, "role", "state"}.
The roles are Room Tiles' own (cycles.py subject): an appliance's
"status" / "door" / "time_left", a vacuum's "vacuum" / "error".
"""

from __future__ import annotations

from typing import Any

APPLIANCES = ("washer", "dryer", "dishwasher")
_OPEN = frozenset({"on", "open", "opened", "true"})


class ReplayError(Exception):
    """A report that can't be replayed (say why)."""


def _running(kind: str) -> str:
    return "drying" if kind == "dryer" else "washing"


def _overrides(report: dict[str, Any], kind: str) -> dict[str, str]:
    """The user's answers (an unknown state's meaning) as the logic's overrides."""
    out: dict[str, str] = {}
    for a in report.get("answers") or []:
        state, answer = str(a.get("state") or "").strip().lower(), a.get("answer")
        if kind in APPLIANCES:
            phase = {"running": _running(kind), "paused": "paused", "off": "off", "not_running": "off", "error": "error"}.get(answer)
        else:
            phase = {"needs_you": "attention", "error": "error", "nothing": "none"}.get(answer)
        if state and phase:
            out[state] = phase
    return out


def replay(report: dict[str, Any]) -> list[dict[str, Any]]:
    """What the tile showed after each change: [{"t", "shown"}] - only the
    changes (an appliance: its phase; a vacuum: its tile's class)."""
    kind = report.get("kind_of_device")
    rows = sorted(
        (r for r in report.get("recording") or [] if isinstance(r, dict) and "role" in r),
        key=lambda r: float(r.get("t") or 0),
    )
    if not rows:
        raise ReplayError("the report has no recording")
    out: list[dict[str, Any]] = []

    def note(t: Any, shown: str) -> None:
        if not out or out[-1]["shown"] != shown:
            out.append({"t": t, "shown": shown})

    if kind in APPLIANCES:
        from .appliance import UnitLogic
        from .appliance_presets import PRESETS

        preset = PRESETS.get(str(report.get("preset")))
        if preset is None:
            raise ReplayError(f"no preset {report.get('preset')!r}")
        logic = UnitLogic(preset, overrides=_overrides(report, kind))
        note(rows[0]["t"], logic.shown)
        for r in rows:
            if r["role"] == "status":
                note(r["t"], logic.update(r.get("state")))
            elif r["role"] == "door":
                note(r["t"], logic.set_door(str(r.get("state") or "").lower() in _OPEN))
        return out
    if kind == "vacuum":
        from .robot import view

        overrides = _overrides(report, kind)
        vac: str | None = None
        err: str | None = None
        for r in rows:
            if r["role"] == "vacuum":
                vac = r.get("state")
            elif r["role"] == "error":
                err = r.get("state")
            else:
                continue
            note(r["t"], view(vac, err, overrides=overrides).cls)
        return out
    raise ReplayError(f"replaying a {kind or 'device'}'s report isn't supported yet")
