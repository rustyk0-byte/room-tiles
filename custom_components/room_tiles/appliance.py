"""Appliance profiles: what a washer / dryer / dishwasher is doing, for the
appliance tiles - from the brand's raw entities, through a PRESET.

Pure logic, no HA (tested in tests/test_appliance.py); appliances_ha.py runs
it on live entities. The tiles only ever see the result (the contract): per
unit a PHASE, a status text and the time left.

Phases: idle, washing, drying, paused, error, done (finished - take it out),
waiting (washer finished - move the load to the dryer), door_open.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from .wording import Word, has, render, w
from .wording import format_minutes as _format_minutes

APPLIANCE_TYPES = ("washer", "dryer", "dishwasher")
PHASES = ("idle", "washing", "drying", "paused", "error", "done", "waiting", "door_open")
RUNNING = frozenset({"washing", "drying", "paused"})
FINISHED = frozenset({"done", "waiting"})

# raw states that always mean "not running"
OFF_ALWAYS = frozenset({"", "n/a", "off", "power_off", "standby", "end", "none"})
# raw states that mean "no news" - the integration dropped out for a moment:
# keep what we had (never turn a running appliance "done")
HOLD = frozenset({"unavailable", "unknown"})


@dataclass(frozen=True)
class Preset:
    """How one brand's appliance reports itself. Raw states compare lower-case.

    `phases`: raw state -> phase, for running states that aren't the type's
    default (washing; drying for a dryer). Raw states not listed anywhere are
    RUNNING (safe default: unknown never breaks the tile). `no_time`: running
    states whose time left is a placeholder (load not sized yet, paused).
    `time`: what the time-left entity holds - "finish" (a timestamp) or
    "duration" (in its unit_of_measurement, else `duration_unit`).
    `countdown_must_move`: a duration only counts while it really counts down
    (over 3 min and changed in the last 3 min) - some drawers hold a 1 min
    placeholder for a whole cycle. `phase_estimates`: minutes a raw phase
    lasts, counted from its start, used when there's no real countdown.
    `labels`: raw state -> a "step.*" wording token (wording/<lang>.json);
    `verified`: someone with the hardware confirmed it (else beta);
    `confirmed_models`: model numbers confirmed - any other model is beta."""

    id: str
    name: str
    appliance: str
    off: frozenset[str] = frozenset()
    phases: dict[str, str] = field(default_factory=dict)
    paused: frozenset[str] = frozenset({"pause", "paused"})
    error: frozenset[str] = frozenset({"error"})
    no_time: frozenset[str] = frozenset()
    time: str = "finish"
    duration_unit: str = "min"
    countdown_must_move: bool = False
    phase_estimates: dict[str, int] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    verified: bool = False
    confirmed_models: tuple[str, ...] = ()
    # raw states that mean "no news" for this brand too (e.g. not connected)
    hold: frozenset[str] = frozenset()
    # a POWER reading (smart plug), not a state: running while above the
    # unit's threshold; finished after it stays below for a while
    power: bool = False
    # running states named in the integration's source (with off / paused /
    # error / phases / labels / no_time: every state this preset KNOWS) -
    # anything else is asked about once (Appliances page), still counted as
    # running until answered
    running: frozenset[str] = frozenset()



def confirmed(p: Preset, model: str | None) -> bool:
    """Is this device model confirmed on real hardware (docs/SUPPORTED.md
    "Confirmed models")? Anything else is beta."""
    m = (model or "").upper()
    return bool(m) and any(c.upper() in m for c in p.confirmed_models)


def default_running(appliance: str) -> str:
    return "drying" if appliance == "dryer" else "washing"


def classify(p: Preset, raw: str | None, overrides: dict[str, str] | None = None) -> str | None:
    """A raw state -> "off", a running phase, "error" - or None for "no news".
    `overrides`: the user's own answers (raw lower-case -> phase / "off")."""
    r = (raw or "").strip().lower()
    if r in HOLD or r in p.hold:
        return None
    if overrides and r in overrides:
        return overrides[r]
    if r in OFF_ALWAYS or r in p.off:
        return "off"
    if r in p.error:
        return "error"
    if r in p.paused:
        return "paused"
    return p.phases.get(r, default_running(p.appliance))


def known(p: Preset, raw: str | None, overrides: dict[str, str] | None = None) -> bool:
    """Does the preset (or the user's own answers) know this raw state?"""
    if p.power:
        return True
    r = (raw or "").strip().lower()
    return (
        r in HOLD
        or r in OFF_ALWAYS
        or r in p.off
        or r in p.error
        or r in p.paused
        or r in p.phases
        or r in p.labels
        or r in p.no_time
        or r in p.running
        or r in p.hold
        or bool(overrides and r in overrides)
    )


@dataclass
class UnitLogic:
    """One unit's phase over time (a washer, one dishwasher drawer...).

    `finished`: what a finished cycle turns into - "done", "idle" (no
    finished state at all), or "waiting" for a
    washer whose load goes on to a dryer. It stays until CLEARED (the unit's
    door opens, a sensor the user picked, another unit starting, a tap) or the
    unit runs again."""

    preset: Preset
    finished: str = "done"
    overrides: dict[str, str] = field(default_factory=dict)
    door_clears: bool = True
    phase: str = "idle"
    running: bool = False
    door: bool = False

    def update(self, raw: str | None) -> str:
        """The raw state changed (or was re-read)."""
        rp = classify(self.preset, raw, self.overrides)
        if rp is None:
            return self.shown
        now_running = rp in RUNNING
        if now_running or rp == "error":
            self.phase = rp
        elif self.running:
            self.phase = self.finished  # it just stopped
        elif self.phase not in FINISHED:
            self.phase = "idle"
        self.running = now_running
        return self.shown

    def set_door(self, is_open: bool) -> str:
        """The unit's own door: shown while open; opening it empties a
        finished unit (unless the user turned that off)."""
        if is_open and not self.door and self.door_clears and self.phase in FINISHED:
            self.phase = "idle"
        self.door = is_open
        return self.shown

    def restore(self, phase: str | None, running: bool) -> None:
        """Back after an HA restart: a finished unit stays finished."""
        if phase in PHASES and phase != "door_open":
            self.phase = phase
        self.running = running

    def clear(self) -> str:
        """Unloaded (picked sensor, other unit started, tap)."""
        if self.phase in FINISHED:
            self.phase = "idle"
        return self.shown

    @property
    def shown(self) -> str:
        return "door_open" if self.door else self.phase


def nice(raw: str) -> str:
    """'main wash' / 'rinse_hold' -> 'Main wash' / 'Rinse hold'; already
    capitalised text ('Main Wash') stays as it is."""
    t = raw.replace("_", " ").strip()
    return t[:1].upper() + t[1:]


def status_word(p: Preset, phase: str, raw: str | None, *, drawer: bool = False) -> Word:
    """The unit's status line as a word (wording.py: each display's language)."""
    if phase == "door_open":
        return w("appliance.drawer_open") if drawer else w("appliance.door_open")
    if phase == "done":
        return w("appliance.clean") if p.appliance == "dishwasher" else w("appliance.done")
    if phase == "waiting":
        return w("appliance.switch_over")
    if phase == "paused":
        return w("appliance.paused")
    if phase == "error":
        return w("appliance.error")
    if phase in RUNNING and raw:
        r = raw.strip()
        # a cycle step: the preset's label, or the raw state itself, as a
        # "step.*" token when the wording knows it; else the brand's own
        # wording as it comes ("Main Wash")
        step = p.labels.get(r.lower()) or r.lower().replace(" ", "_")
        return w(f"step.{step}") if has(f"step.{step}") else nice(r)
    return ""


def status_text(p: Preset, phase: str, raw: str | None, *, drawer: bool = False) -> str:
    """The unit's status line, in HA's language."""
    return render(status_word(p, phase, raw, drawer=drawer))


_UNIT_MIN = {"d": 1440, "h": 60, "min": 1, "s": 1 / 60}


def minutes_left(
    p: Preset,
    phase: str,
    raw: str | None,
    value: str | None,
    unit: str | None,
    now: datetime,
    *,
    value_changed: datetime | None = None,
    raw_changed: datetime | None = None,
) -> int | None:
    """Minutes left while running, or None when unknown / misleading."""
    if phase not in ("washing", "drying"):
        return None
    r = (raw or "").strip().lower()
    if r in p.no_time:
        return None
    m: float | None = None
    if p.time == "finish":
        try:
            ts = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            ts = None
        if ts is not None:
            if ts.tzinfo is None and now.tzinfo is not None:
                ts = ts.replace(tzinfo=now.tzinfo)
            m = math.ceil((ts - now).total_seconds() / 60)
    else:
        try:
            v = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            v = None
        if v is not None:
            m = math.ceil(v * _UNIT_MIN.get(unit or p.duration_unit, 1))
            if p.countdown_must_move and not (
                m > 3 and value_changed is not None and (now - value_changed).total_seconds() <= 180
            ):
                m = None
        if m is None and r in p.phase_estimates and raw_changed is not None:
            m = math.ceil(((raw_changed - now).total_seconds() + p.phase_estimates[r] * 60) / 60)
    return int(m) if m is not None and m > 0 else None


def format_minutes(m: int | None) -> str:
    """Time left in HA's language ("~45m" / "~1h 05m"; wording.format_minutes)."""
    return _format_minutes(m)


def power_raw(watts: float | None, threshold: float, below_since: float | None, now: float, off_after_s: float, running: bool) -> tuple[str | None, float | None]:
    """A smart plug's power as a raw state: "running" above the threshold;
    below it, still "running" until it has stayed low for `off_after_s` (a
    soak, a pause, a dishwasher drying cold), then "off". Returns (raw, the new
    below-since time); raw None = no reading (no news)."""
    if watts is None:
        return None, below_since
    if watts >= threshold:
        return "running", None
    since = below_since if below_since is not None else now
    if running and now - since < off_after_s:
        return "running", since
    return "off", since
