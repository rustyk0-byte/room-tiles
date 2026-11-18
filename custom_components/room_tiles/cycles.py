"""Report a problem: a whole cycle of an appliance, a pool or a robot
vacuum (a wash, a pump run, a clean), from HA's history or recorded live
(DESIGN.md "Privacy: what reports send" > Report a problem).

A problem report holds every entity of its devices (not only the ones Room
Tiles reads) and what Room Tiles showed over the same time, so "it said
Done while still running" can be seen in the data. Two ways in:

- a PAST cycle, found in HA's history (`async_find_cycles`,
  `async_history_cycle`): nothing is kept; it's read when the report is made.
- the NEXT cycle, recorded live (`Recordings`): Room Tiles listens to the
  device until the cycle is over (60 quiet minutes after it stopped, Stop on
  the Appliances page, or 12 hours - a pool 24), keeps it in .storage/room_tiles.recordings
  until the user sends or deletes it (deleted after 30 days anyway).

HA stopping and starting inside the cycle is part of the data either way
(the recorder's own run log for a past cycle; Room Tiles' own marks for a
live one - a crash shows as a stop that wasn't clean).

The rows here are raw (entity ids, epoch times); `problem_draft` turns them
into a report (roles, attribute changes) and report.scrub() cleans that.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import callback

from .appliance import RUNNING, classify

_LOGGER = logging.getLogger(__name__)

QUIET_S = 3600  # a cycle is over after this long with nothing happening
LIMIT_S = 12 * 3600  # a recording never runs longer
POOL_LIMIT_S = 24 * 3600  # (a pool's pump can run all day)
WINDOW_HOURS = (6, 24)  # a pool's problem isn't always one run: the last hours instead
WAIT_LIMIT_S = 7 * 86400  # "the next cycle" that never starts: given up
LEAD_S = 300  # what's kept from before the cycle started
NUMERIC_EVERY_S = 30  # a number that keeps changing: one row per this long
MAX_ROWS = 3000  # rows kept per recording (more: counted, not kept)
KEEP_DAYS = 30  # a recording nobody sent: deleted after this long
FIND_DAYS = 7  # how far back past cycles are looked for
MAX_CYCLES = 10
SAVE_EVERY_S = 60  # a recording's file is written at most this often

# marks in a cycle besides state changes (report.py EVENTS)
EVENTS = ("cycle_started", "ha_stopping", "ha_started", "ha_stopped_unclean", "room_tiles_reloaded", "stopped")
# how a recording ended (report.py ENDS)
ENDS = ("quiet", "stopped", "limit", "no_cycle", "history")
# where a report's data came from (report.py CYCLE_FROM)
FROM = ("history", "window", "recorded")

# attributes never worth a row (they don't say what the device does)
_SKIP_ATTRS = frozenset({"friendly_name", "icon", "entity_picture", "attribution", "supported_features", "assumed_state"})


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _plain(value: Any) -> bool:
    """A value worth keeping in a row (a word, number, yes/no, short list)."""
    if value is None or isinstance(value, (bool, int, float)):
        return True
    if isinstance(value, str):
        return len(value) <= 200
    if isinstance(value, (list, tuple)):
        return len(value) <= 64 and all(v is None or isinstance(v, (bool, int, float, str)) for v in value)
    return False


def row_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    """An entity's attributes as kept in a row: plain values only (times
    stay as given - the scrubber turns them into deltas)."""
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        if key in _SKIP_ATTRS or not _plain(value):
            continue
        out[key] = list(value) if isinstance(value, tuple) else value
    return out


def shown(attrs: dict[str, Any], unit_id: str) -> tuple[str, dict[str, Any]] | None:
    """What Room Tiles showed for one unit (its appliance sensor's
    attributes): (phase, {status, minutes_left, running}) - the minutes as a
    number ("1:05" would read as a time of day)."""
    for unit in attrs.get("units") or []:
        if isinstance(unit, dict) and unit.get("id") == unit_id:
            return str(unit.get("phase") or ""), {
                "status": unit.get("status"),
                "minutes_left": unit.get("minutes"),
                "running": bool(unit.get("running")),
            }
    return None


# ---- the rows of a cycle ---------------------------------------------------------------


@dataclass
class Rows:
    """A cycle's state changes, in time order: [t, entity, state, attrs]
    where attrs holds only what CHANGED since that entity's last row (a key
    that went away: None). Numbers that keep changing (a power reading every
    few seconds) are thinned to one row per NUMERIC_EVERY_S; past MAX_ROWS
    rows are counted in `trimmed`, not kept. `base`: each entity's state
    from before the rows (folded in by `forget_before`)."""

    rows: list[list[Any]] = field(default_factory=list)
    base: dict[str, list[Any]] = field(default_factory=dict)  # entity -> [t, state, attrs (whole)]
    trimmed: int = 0
    _last: dict[str, tuple[float, Any, dict[str, Any]]] = field(default_factory=dict)  # entity -> (t, state, attrs)
    _held: dict[str, list[Any]] = field(default_factory=dict)  # a thinned number's latest row

    def add(self, t: float, entity: str, state: Any, attrs: dict[str, Any]) -> bool:
        """Note a state; False when nothing changed."""
        last = self._last.get(entity)
        if last is None:
            diff = dict(attrs)
        else:
            old = last[2]
            diff = {k: v for k, v in attrs.items() if old.get(k) != v}
            diff.update({k: None for k in old if k not in attrs})
            if state == last[1] and not diff:
                return False
            if not diff and _num(state) is not None and _num(last[1]) is not None and t - last[0] < NUMERIC_EVERY_S:
                self._held[entity] = [t, entity, state, {}]
                return True
        self._held.pop(entity, None)
        self._last[entity] = (t, state, attrs)
        if len(self.rows) >= MAX_ROWS:
            self.trimmed += 1
            return True
        self.rows.append([t, entity, state, diff])
        return True

    def flush(self) -> None:
        """The cycle is over: a thinned number's last value counts."""
        for row in sorted(self._held.values(), key=lambda r: r[0]):
            if len(self.rows) >= MAX_ROWS:
                self.trimmed += 1
            else:
                self.rows.append(row)
                last = self._last.get(row[1])
                self._last[row[1]] = (row[0], row[2], last[2] if last else {})
        self._held.clear()
        self.rows.sort(key=lambda r: r[0])

    def forget_before(self, cut: float) -> None:
        """Waiting for a cycle: rows from before `cut` fold into `base`."""
        n = 0
        for t, entity, state, diff in self.rows:
            if t >= cut:
                break
            prev = self.base.get(entity)
            attrs = dict(prev[2]) if prev else {}
            for k, v in diff.items():
                if v is None:
                    attrs.pop(k, None)
                else:
                    attrs[k] = v
            self.base[entity] = [t, state, attrs]
            n += 1
        if n:
            del self.rows[:n]

    def all_rows(self, start: float | None = None) -> list[list[Any]]:
        """The base (at `start`, or its own time) then the rows."""
        out = [[max(b[0], start) if start is not None else b[0], e, b[1], b[2]] for e, b in self.base.items()]
        out.sort(key=lambda r: r[0])
        return out + [list(r) for r in self.rows]

    def as_dict(self) -> dict[str, Any]:
        return {"rows": self.rows, "base": self.base, "trimmed": self.trimmed}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Rows:
        r = cls(rows=[list(x) for x in d.get("rows") or []], base=dict(d.get("base") or {}), trimmed=int(d.get("trimmed") or 0))
        # each entity's latest state again (for what changes next)
        for entity, b in r.base.items():
            r._last[entity] = (b[0], b[1], dict(b[2]))
        for t, entity, state, diff in r.rows:
            last = r._last.get(entity)
            attrs = dict(last[2]) if last else {}
            for k, v in diff.items():
                if v is None:
                    attrs.pop(k, None)
                else:
                    attrs[k] = v
            r._last[entity] = (t, state, attrs)
        return r




# ---- what a report is about: an appliance unit, a pool system, a robot vacuum -------------

SUBJECTS = ("appliance", "pool", "robot")
# what a pool tile / pump says about circulating (cycles: a pump run)
_POOL_ON = frozenset({"heating", "cooling", "switching"})
_POOL_OFF = frozenset({"pump_off", "standby"})
_ROBOT_ON = frozenset({"cleaning", "returning", "paused"})
_ROBOT_OFF = frozenset({"docked", "idle", "charging"})
# Room Tiles' own sensors' attributes that aren't what the device did (its
# name, ids, the panels' text, words for each display's language)
_OWN_SKIP = frozenset({"own_name", "pool", "robot", "vacuum", "appliance", "tile", "tile_words", "time_to_target_run", "questions"})


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    if s and not s[0].isalpha():
        s = "e_" + s
    return s[:32].rstrip("_")


def _own_sensor(hass: Any, unique_id: str) -> str | None:
    """One of Room Tiles' own sensors (what a tile shows), by unique id."""
    from homeassistant.helpers import entity_registry as er

    from .const import DOMAIN

    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, unique_id)


@dataclass
class Subject:
    """What a problem report is about. `own`: entity -> role for what Room
    Tiles reads and its own sensors (roles starting "room_tiles": what the
    tile showed); `roles()` adds every other entity of the same devices.
    `limit_s`: how long a recording may run."""

    kind: str  # SUBJECTS
    id: str
    unit: str  # an appliance's unit ("" otherwise)
    name: str  # the user's name for it (shown to them, never sent)
    main: str  # the entity whose device and integration the report names
    kind_of_device: str
    preset: str
    layout: str | None
    limit_s: int
    own: dict[str, str]
    profile: Any = None  # the appliance unit / pool system / robot profile
    pre: Any = None  # an appliance unit's preset

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.id}"

    def roles(self, hass: Any) -> dict[str, str]:
        """entity id -> its name in a report: Room Tiles' own words for what
        it reads, "room_tiles..." for what the tile showed, otherwise the
        integration's own word for the entity (its translation key, else the
        name it gave it) - never a name the user typed."""
        from homeassistant.helpers import entity_registry as er

        reg = er.async_get(hass)
        roles: dict[str, str] = {}
        used: set[str] = set()

        def put(entity: str, role: str) -> None:
            if entity in roles:
                return
            base = role or "entity"
            name, n = base, 2
            while name in used:
                name = f"{base[:29]}_{n}"
                n += 1
            roles[entity] = name
            used.add(name)

        for entity, role in self.own.items():
            put(entity, role)
        devices: list[str] = []
        for entity, role in self.own.items():
            ent = reg.async_get(entity)
            if ent is not None and ent.device_id and not role.startswith("room_tiles") and ent.device_id not in devices:
                devices.append(ent.device_id)
        for device_id in devices:
            for other in sorted(er.async_entries_for_device(reg, device_id), key=lambda e: e.entity_id):
                if other.entity_id in roles:
                    continue
                word = other.translation_key or (_slug(other.original_name) if other.original_name else "")
                put(other.entity_id, _slug(word) if word else other.domain)
        return roles

    def watch(self, roles: dict[str, str]) -> list[str]:
        """The entities that say whether it runs (for finding cycles)."""
        say = {"status", "vacuum", "pump", "pool_pump", "spa_pump", "pool_heater", "spa_heater"}
        return [e for e, r in roles.items() if r in say or r.startswith("room_tiles")]

    def active(self, role: str | None, state: Any, attrs: dict[str, Any]) -> bool | None:
        """Does this entity say it's running (a cycle, a pump run, a clean)?
        None: it doesn't say."""
        if role is None:
            return None
        st = str(state or "").lower()
        if self.kind == "appliance":
            unit = self.profile
            if role == "room_tiles":
                got = shown(attrs, unit.id)
                return None if got is None else (got[1]["running"] or got[0] in RUNNING)
            if role == "status" and self.pre is not None:
                if self.pre.power:
                    watts = _num(state)
                    return None if watts is None else watts >= unit.power_on_w
                phase = classify(self.pre, state, unit.overrides)
                return None if phase is None else phase in RUNNING
            return None
        if self.kind == "pool":
            if role.startswith("room_tiles"):
                return True if st in _POOL_ON else False if st in _POOL_OFF else None
            if role in ("pump", "pool_pump", "spa_pump"):
                return True if st == "on" else False if st == "off" else None
            if role in ("pool_heater", "spa_heater"):
                action = str(attrs.get("hvac_action") or "").lower()
                return True if action in ("heating", "cooling") else False if action in ("idle", "off") else None
            return None
        if role in ("vacuum", "room_tiles"):
            return True if st in _ROBOT_ON else False if st in _ROBOT_OFF else None
        return None

    def row(self, role: str | None, state: Any, attrs: dict[str, Any]) -> tuple[Any, dict[str, Any]] | None:
        """A state as a report row keeps it (Room Tiles' own sensors: what
        the tile showed - an appliance's: just this unit)."""
        if role is not None and role.startswith("room_tiles"):
            if self.kind == "appliance":
                return shown(attrs, self.unit)
            keep = {k: v for k, v in attrs.items() if k not in _OWN_SKIP and not k.endswith(("_word", "_words"))}
            return state, row_attrs(keep)
        return state, row_attrs(attrs)


def subject(hass: Any, data: Any, kind: str, sid: str, unit: str = "") -> Subject | None:
    """The subject of a report, from Room Tiles' data (None: it's gone)."""
    from .appliance_presets import PRESETS

    if kind == "appliance":
        ap = next((a for a in data.appliances if a.id == sid), None)
        if ap is None:
            return None
        u = next((x for x in ap.units if x.id == unit), None) if unit else (ap.units[0] if ap.units else None)
        if u is None:
            return None
        own = {u.status: "status"}
        if u.time:
            own[u.time] = "time_left"
        if u.door:
            own[u.door] = "door"
        if (rt := _own_sensor(hass, f"appliance_{ap.id}")) is not None:
            own[rt] = "room_tiles"
        return Subject("appliance", ap.id, u.id, ap.name, u.status, u.appliance, u.preset, None, LIMIT_S, own, u, PRESETS.get(u.preset))
    if kind == "pool":
        ps = next((p for p in data.pools if p.id == sid), None)
        if ps is None:
            return None
        own = {}
        if ps.spa_mode:
            own[ps.spa_mode] = "spa_mode"
        if ps.pump:
            own[ps.pump] = "pump"
        for body in ("pool", "spa"):
            b = getattr(ps, body)
            if b is None:
                continue
            for field_, role in (("temp", "temp"), ("heater", "heater"), ("pump", "pump"), ("heater_switch", "heater_switch")):
                if (e := getattr(b, field_)) and e not in own:
                    own[e] = f"{body}_{role}"
        for suffix, role in (("", "room_tiles"), ("_pool", "room_tiles_pool"), ("_spa", "room_tiles_spa")):
            if (rt := _own_sensor(hass, f"pool_{ps.id}{suffix}")) is not None:
                own[rt] = role
        main = next((e for e, r in own.items() if r.endswith("heater")), None) or next(iter(own), "")
        return Subject("pool", ps.id, "", ps.name, main, "pool", ps.preset, ps.layout, POOL_LIMIT_S, own, ps)
    if kind == "robot":
        rb = next((r for r in data.robots if r.id == sid), None)
        if rb is None:
            return None
        own = {rb.vacuum: "vacuum"}
        if rb.error:
            own[rb.error] = "error"
        if (rt := _own_sensor(hass, f"robot_{rb.id}")) is not None:
            own[rt] = "room_tiles"
        return Subject("robot", rb.id, "", rb.name, rb.vacuum, "vacuum", rb.preset, None, LIMIT_S, own, rb)
    return None


# ---- past cycles: HA's history ----------------------------------------------------------


def _ts(when: datetime) -> float:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.timestamp()


def _dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def has_history(hass: Any) -> bool:
    return "recorder" in hass.config.components


async def _history(hass: Any, entities: list[str], start: float, end: float) -> dict[str, list[Any]]:
    from homeassistant.components.recorder import get_instance, history

    def read() -> dict[str, list[Any]]:
        return history.get_significant_states(
            hass,
            _dt(start),
            _dt(end),
            entities,
            include_start_time_state=True,
            significant_changes_only=False,
            minimal_response=False,
            no_attributes=False,
        )

    return await get_instance(hass).async_add_executor_job(read)


async def _restarts(hass: Any, start: float, end: float) -> list[list[Any]]:
    """HA stopping and starting between start and end (the recorder's own
    log of its runs): [t, event]."""
    from homeassistant.components.recorder import get_instance

    def read() -> list[list[Any]]:
        from homeassistant.components.recorder.db_schema import RecorderRuns
        from homeassistant.components.recorder.util import session_scope

        out: list[list[Any]] = []
        with session_scope(hass=hass, read_only=True) as session:
            runs = (
                session.query(RecorderRuns.start, RecorderRuns.end, RecorderRuns.closed_incorrect)
                .filter(RecorderRuns.start <= _dt(end).replace(tzinfo=None))
                .filter((RecorderRuns.end.is_(None)) | (RecorderRuns.end >= _dt(start).replace(tzinfo=None)))
                .all()
            )
        for run_start, run_end, unclean in runs:
            s = _ts(run_start)
            if start < s <= end:
                out.append([s, "ha_started"])
            if run_end is not None and start <= _ts(run_end) < end:
                out.append([_ts(run_end), "ha_stopped_unclean" if unclean else "ha_stopping"])
        return sorted(out)

    try:
        return await get_instance(hass).async_add_executor_job(read)
    except Exception:  # noqa: BLE001 - an older / other recorder: no restart marks
        _LOGGER.debug("no recorder runs", exc_info=True)
        return []


def spans(points: Iterable[tuple[float, bool | None]], now: float) -> list[tuple[float, float, bool]]:
    """Running spans from (time, running?) points in time order, gaps under
    QUIET_S merged: (start, end, still running)."""
    out: list[list[Any]] = []
    on_since: float | None = None
    for t, running in points:
        if running is None:
            continue
        if running and on_since is None:
            on_since = t
        elif not running and on_since is not None:
            if out and on_since - out[-1][1] < QUIET_S:
                out[-1][1] = t
            else:
                out.append([on_since, t, False])
            on_since = None
    if on_since is not None:
        if out and on_since - out[-1][1] < QUIET_S:
            out[-1][1], out[-1][2] = now, True
        else:
            out.append([on_since, now, True])
    return [(a, b, c) for a, b, c in out]


def _running(points: list[tuple[float, str, bool | None]]) -> list[tuple[float, bool | None]]:
    """(time, entity, says running?) -> (time, running by any of them)."""
    now_on: dict[str, bool] = {}
    out: list[tuple[float, bool | None]] = []
    for t, e, on in sorted(points, key=lambda p: p[0]):
        if on is None:
            continue
        now_on[e] = on
        out.append((t, any(now_on.values())))
    return out


async def async_find_cycles(hass: Any, sub: Subject, now: float) -> dict[str, Any]:
    """Its recent cycles in HA's history, newest first: {"history": recorder
    on?, "running": one going now?, "cycles": [{"start", "end"}], "windows":
    the last hours to pick instead (a pool) - seconds since 1970, shown to
    the user only}."""
    roles = sub.roles(hass)
    watch = sub.watch(roles)
    points = []
    for e in watch:
        st = hass.states.get(e)
        if st is not None:
            points.append((0.0, e, sub.active(roles.get(e), st.state, dict(st.attributes))))
    now_on = _running(points)
    running_now = bool(now_on) and now_on[-1][1] is True
    windows = [{"start": now - h * 3600, "end": now, "hours": h} for h in WINDOW_HOURS] if sub.kind == "pool" else []
    if not has_history(hass):
        return {"history": False, "running": running_now, "cycles": [], "windows": []}
    hist = await _history(hass, watch, now - FIND_DAYS * 86400, now)
    points = [
        (_ts(st.last_updated), e, sub.active(roles.get(e), st.state, dict(st.attributes)))
        for e, states in hist.items()
        for st in states
    ]
    cycles = [{"start": a, "end": b} for a, b, still in spans(_running(points), now) if not still and b - a >= 60]
    cycles.reverse()
    return {"history": True, "running": running_now, "cycles": cycles[:MAX_CYCLES], "windows": windows}


async def async_history_cycle(hass: Any, sub: Subject, start: float, end: float, now: float, *, window: bool = False) -> dict[str, Any] | None:
    """A past cycle's rows from HA's history: LEAD_S before it to up to
    QUIET_S after (not past now); a window (the last hours): just that."""
    if not has_history(hass):
        return None
    roles = sub.roles(hass)
    t0, t1 = (start, min(end, now)) if window else (start - LEAD_S, min(end + QUIET_S, now))
    hist = await _history(hass, list(roles), t0, t1)
    changes = [
        (max(_ts(st.last_updated), t0), e, st.state, dict(st.attributes))
        for e, states in hist.items()
        for st in states
    ]
    changes.sort(key=lambda c: c[0])
    rows = Rows()
    for t, e, state, attrs in changes:
        got = sub.row(roles.get(e), state, attrs)
        if got is not None:
            rows.add(t, e, got[0], got[1])
    rows.flush()
    return {
        "subject": sub,
        "roles": roles,
        "rows": rows.all_rows(),
        "events": await _restarts(hass, t0, t1),
        "trimmed": rows.trimmed,
        "ended": "history",
        "from": "window" if window else "history",
    }


# ---- the next cycle: recorded live ------------------------------------------------------


def _activity(old: Any, new: Any, ref: dict[str, float], entity: str) -> bool:
    """Did something happen? A word changing does; a number only when it
    moves a real step from where it last did (a power reading jittering by
    a fraction of a watt doesn't keep a recording going)."""
    a, b = _num(old), _num(new)
    if b is None or a is None:
        return old != new
    base = ref.get(entity, a)
    if abs(b - base) >= max(1.0, 0.2 * abs(base)):
        ref[entity] = b
        return True
    return False


@dataclass
class Recording:
    """One live recording (one at a time per appliance / pool / vacuum)."""

    kind: str
    id: str
    unit: str = ""
    description: str = ""
    armed: float = 0.0  # when the user asked for it
    started: float | None = None  # the cycle started (None: still waiting)
    ended: float | None = None
    end: str | None = None  # ENDS
    last_activity: float = 0.0
    limit_s: int = LIMIT_S
    opened: bool = False  # Open GitHub was pressed (ask "did it go through?")
    rows: Rows = field(default_factory=Rows)
    events: list[list[Any]] = field(default_factory=list)
    _ref: dict[str, float] = field(default_factory=dict)  # numbers' last real step
    _on: dict[str, bool] = field(default_factory=dict)  # who says it's running

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.id}"

    @property
    def status(self) -> str:
        if self.ended is not None:
            return "no_cycle" if self.end == "no_cycle" else "ready"
        return "recording" if self.started is not None else "waiting"

    def view(self) -> dict[str, Any]:
        """What the dashboard shows (times: the user's own, never sent)."""
        return {
            "unit": self.unit,
            "status": self.status,
            "armed": self.armed,
            "started": self.started,
            "ended": self.ended,
            "description": self.description,
            "opened": self.opened,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "unit": self.unit,
            "description": self.description,
            "armed": self.armed,
            "started": self.started,
            "ended": self.ended,
            "end": self.end,
            "last_activity": self.last_activity,
            "limit_s": self.limit_s,
            "opened": self.opened,
            "events": self.events,
            **self.rows.as_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Recording:
        return cls(
            kind=str(d["kind"]),
            id=str(d["id"]),
            unit=str(d.get("unit") or ""),
            description=str(d.get("description") or ""),
            armed=float(d.get("armed") or 0),
            started=d.get("started"),
            ended=d.get("ended"),
            end=d.get("end"),
            last_activity=float(d.get("last_activity") or 0),
            limit_s=int(d.get("limit_s") or LIMIT_S),
            opened=bool(d.get("opened")),
            events=[list(e) for e in d.get("events") or []],
            rows=Rows.from_dict(d),
        )

    # ---- what happens (pure: tested without HA) ----

    def note(self, t: float, entity: str, state: Any, attrs: dict[str, Any], active: bool | None, old_state: Any) -> None:
        """A state of one of its entities (`state`/`attrs`: as rows keep
        them; `active`: does it say it runs - None: it doesn't say;
        `old_state`: its state before, for what counts as activity)."""
        if self.ended is not None:
            return
        if active is not None:
            self._on[entity] = active
        changed = self.rows.add(t, entity, state, attrs)
        running = any(self._on.values())
        if self.started is None:
            if running:
                self.started = t
                self.last_activity = t
                self.events.append([t, "cycle_started"])
            else:
                self.rows.forget_before(t - LEAD_S)
            return
        if running or (changed and _activity(old_state, state, self._ref, entity)):
            self.last_activity = t

    def tick(self, t: float) -> bool:
        """The clock: over? (True: it just ended)."""
        if self.ended is not None:
            return False
        if self.started is None:
            if t - self.armed >= WAIT_LIMIT_S:
                self.finish(t, "no_cycle")
                return True
            self.rows.forget_before(t - LEAD_S)
            return False
        if any(self._on.values()):
            self.last_activity = t
        if t - self.started >= self.limit_s:
            self.finish(t, "limit")
            return True
        if t - self.last_activity >= QUIET_S:
            self.finish(t, "quiet")
            return True
        return False

    def finish(self, t: float, why: str) -> None:
        self.rows.flush()
        self.ended = t
        self.end = why
        if why == "stopped":
            self.events.append([t, "stopped"])


class Recordings:
    """The live recordings (.storage/room_tiles.recordings), kept by the
    integration - the dashboard can be closed meanwhile; keyed
    "<kind>:<id>" (appliance / pool / robot). HA stopping marks each one
    ("ha_stopping"); starting again marks it too, and a stop that never got
    marked (a crash) shows where the gap began. The file is written at most
    once a minute (and when HA stops)."""

    def __init__(self, hass: Any, changed: Callable[[], None]) -> None:
        from homeassistant.helpers.storage import Store

        from .const import RECORDINGS_KEY

        self.hass = hass
        self._changed = changed
        self._store: Store[dict[str, Any]] = Store(hass, 1, RECORDINGS_KEY)
        self.items: dict[str, Recording] = {}
        self._subjects: dict[str, Subject] = {}
        self._roles: dict[str, dict[str, str]] = {}  # (recordings still listening)
        self._unsub: list[Callable[[], None]] = []
        self._save_due = False
        self._saved_at = 0.0
        self._data_now: Any = None  # Room Tiles' data, as last synced
        self._stop_unsub: Callable[[], None] | None = None

    # ---- lifecycle ----

    async def async_load(self, data: Any, now: float, ha_starting: bool) -> None:
        raw = await self._store.async_load() or {}
        saved_at = float(raw.get("saved_at") or 0)
        for d in raw.get("recordings") or []:
            try:
                rec = Recording.from_dict(d)
            except (KeyError, TypeError, ValueError):
                continue
            if rec.ended is not None and now - rec.ended > KEEP_DAYS * 86400:
                continue
            if rec.ended is None:
                last = rec.events[-1][1] if rec.events else None
                if ha_starting:
                    if last != "ha_stopping" and saved_at:
                        rec.events.append([saved_at, "ha_stopped_unclean"])
                    rec.events.append([now, "ha_started"])
                else:
                    rec.events.append([now, "room_tiles_reloaded"])
            self.items[rec.key] = rec
        self.sync(data)
        # what changed while HA was down
        for rec in list(self.items.values()):
            self._read_all(rec, now)

    def _unlisten(self) -> None:
        for u in self._unsub:
            u()
        self._unsub = []

    async def async_unload(self) -> None:
        """Room Tiles unloading (a reload, HA stopping): written now."""
        self._unlisten()
        if self._stop_unsub is not None:
            self._stop_unsub()
            self._stop_unsub = None
        await self._store.async_save(self._data())

    @property
    def doc(self) -> dict[str, Any]:
        return {k: r.view() for k, r in self.items.items()}

    def _data(self) -> dict[str, Any]:
        import time

        self._save_due = False
        self._saved_at = time.time()
        return {"saved_at": self._saved_at, "recordings": [r.as_dict() for r in self.items.values()]}

    def _save(self, now: bool = False) -> None:
        if now:
            self._store.async_delay_save(self._data, 0)
            self._save_due = True
            return
        if self._save_due:  # (one write a minute at most: a later call doesn't push it back)
            return
        self._save_due = True
        self._store.async_delay_save(self._data, SAVE_EVERY_S)

    # ---- listening ----

    def sync(self, data: Any) -> None:
        """(Re)subscribe to every recording's entities; recordings of an
        appliance, unit, pool or vacuum that's gone are dropped."""
        from homeassistant.const import EVENT_HOMEASSISTANT_STOP
        from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval

        self._unlisten()
        self._data_now = data
        self._subjects, self._roles = {}, {}
        for key, rec in list(self.items.items()):
            sub = subject(self.hass, data, rec.kind, rec.id, rec.unit)
            if sub is None:
                del self.items[key]
                continue
            self._subjects[key] = sub
            if rec.ended is None:
                self._roles[key] = sub.roles(self.hass)
        watched = sorted({e for roles in self._roles.values() for e in roles})
        if watched:
            self._unsub.append(async_track_state_change_event(self.hass, watched, self._event))
        if any(r.ended is None for r in self.items.values()):
            self._unsub.append(async_track_time_interval(self.hass, self._tick, timedelta(minutes=1)))
        if self._stop_unsub is None:
            self._stop_unsub = self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._ha_stopping)

    def _feed(self, rec: Recording, t: float, entity: str, state: Any, attrs: dict[str, Any], old: Any) -> None:
        sub = self._subjects.get(rec.key)
        if sub is None:
            return
        role = (self._roles.get(rec.key) or {}).get(entity)
        got = sub.row(role, state, attrs)
        if got is None:
            return
        rec.note(t, entity, got[0], got[1], sub.active(role, state, attrs), old)

    def _read_all(self, rec: Recording, now: float) -> None:
        for entity in self._roles.get(rec.key) or {}:
            st = self.hass.states.get(entity)
            if st is not None:
                self._feed(rec, now, entity, st.state, dict(st.attributes), None)
        self._save()

    @callback
    def _event(self, event: Any) -> None:
        entity = event.data["entity_id"]
        new = event.data.get("new_state")
        old = event.data.get("old_state")
        if new is None:
            return
        t = new.last_updated.timestamp()
        hit = False
        for key, roles in self._roles.items():
            rec = self.items.get(key)
            sub = self._subjects.get(key)
            if rec is None or sub is None or rec.ended is not None or entity not in roles:
                continue
            was = rec.status
            prev = None
            if old is not None:
                got = sub.row(roles[entity], old.state, dict(old.attributes))
                prev = got[0] if got else None
            self._feed(rec, t, entity, new.state, dict(new.attributes), prev)
            hit = True
            if rec.status != was:
                self._changed()
        if hit:
            self._save()

    @callback
    def _tick(self, now: datetime) -> None:
        over = [rec for rec in self.items.values() if rec.tick(now.timestamp())]
        if over:
            for rec in over:
                self._ended(rec)
            self._save(now=True)
            self.sync_again()
            self._changed()
        elif any(r.ended is None for r in self.items.values()):
            self._save()

    def sync_again(self) -> None:
        if self._data_now is not None:
            self.sync(self._data_now)

    @callback
    def _ha_stopping(self, _event: Any) -> None:
        import time

        t = time.time()
        for rec in self.items.values():
            if rec.ended is None:
                rec.events.append([t, "ha_stopping"])
        self._stop_unsub = None
        self._save(now=True)  # (HA's final write saves it)

    def _notification_id(self, key: str) -> str:
        return "room_tiles_recording_" + key.replace(":", "_")

    def _ended(self, rec: Recording) -> None:
        """Tell the user (an HA notification linking to the Appliances page)."""
        from homeassistant.components import persistent_notification

        from .frontend import PANEL_URL_PATH
        from .wording import t as words

        sub = self._subjects.get(rec.key)
        name = sub.name if sub else rec.id
        key = "recording.none" if rec.end == "no_cycle" else "recording.ready"
        persistent_notification.async_create(
            self.hass,
            words(f"{key}_message", name=name, url=f"/{PANEL_URL_PATH}?open=appliances"),
            title=words(f"{key}_title", name=name),
            notification_id=self._notification_id(rec.key),
        )

    # ---- what the user does ----

    def start(self, data: Any, kind: str, sid: str, unit: str, description: str, now: float) -> Recording | None:
        """Record the next cycle (one going now: from now on)."""
        sub = subject(self.hass, data, kind, sid, unit)
        if sub is None:
            return None
        self.dismiss(sub.key)
        rec = Recording(kind=kind, id=sid, unit=sub.unit, description=description[:2000], armed=now, limit_s=sub.limit_s)
        self.items[rec.key] = rec
        self.sync(data)
        self._read_all(rec, now)
        self._save(now=True)
        self._changed()
        return rec

    def stop(self, key: str, now: float) -> bool:
        rec = self.items.get(key)
        if rec is None or rec.ended is not None:
            return False
        rec.finish(now, "stopped" if rec.started is not None else "no_cycle")
        self.sync_again()
        self._save(now=True)
        self._changed()
        return True

    def delete(self, key: str) -> bool:
        if self.items.pop(key, None) is None:
            return False
        self.dismiss(key)
        self.sync_again()
        self._save(now=True)
        self._changed()
        return True

    def update(self, key: str, *, description: str | None = None, opened: bool | None = None) -> bool:
        rec = self.items.get(key)
        if rec is None:
            return False
        if description is not None:
            rec.description = description[:2000]
        if opened is not None:
            rec.opened = opened
        self._save(now=True)
        self._changed()
        return True

    def dismiss(self, key: str) -> None:
        from homeassistant.components import persistent_notification

        persistent_notification.async_dismiss(self.hass, self._notification_id(key))

    def cycle(self, data: Any, key: str) -> dict[str, Any] | None:
        """A finished recording, as `async_history_cycle` gives one."""
        rec = self.items.get(key)
        if rec is None or rec.ended is None or rec.started is None:
            return None
        sub = subject(self.hass, data, rec.kind, rec.id, rec.unit)
        if sub is None:
            return None
        return {
            "subject": sub,
            "roles": sub.roles(self.hass),
            "rows": rec.rows.all_rows(rec.started - LEAD_S),
            "events": [e for e in rec.events if e[1] != "cycle_started"],
            "trimmed": rec.rows.trimmed,
            "ended": rec.end,
            "from": "recorded",
        }


# ---- the report ---------------------------------------------------------------------------


def _areas_as_places(rows: list[dict[str, Any]], areas: Collection[str]) -> None:
    """HA area ids (a vacuum's room queue) -> "area_1", "area_2"... in the
    order they first show - the queue's moves stay readable, the home's
    rooms don't go out."""
    names: dict[str, str] = {}

    def swap(v: Any) -> Any:
        if isinstance(v, str) and v in areas:
            if v not in names:
                names[v] = f"area_{len(names) + 1}"
            return names[v]
        if isinstance(v, list):
            return [swap(x) for x in v]
        return v

    for row in rows:
        row["state"] = swap(row["state"])
        row["attributes"] = {k: swap(v) for k, v in row["attributes"].items()}


def problem_draft(cycle: dict[str, Any], description: str, areas: Collection[str] = ()) -> dict[str, Any]:
    """A cycle's report before scrubbing: rows with their roles (an entity
    no role was found for is left out), Room Tiles' own as "room_tiles..."."""
    roles: dict[str, str] = cycle["roles"]
    sub: Subject = cycle["subject"]
    rows = []
    for t, entity, state, attrs in cycle["rows"]:
        role = roles.get(entity)
        if role is None:
            continue
        rows.append({"t": t, "role": role, "state": state, "attributes": dict(attrs)})
    if areas:
        _areas_as_places(rows, set(areas))
    draft: dict[str, Any] = {
        "description": description,
        "kind_of_device": sub.kind_of_device,
        "preset": sub.preset,
        "cycle": {"from": cycle["from"], "ended": cycle["ended"], "trimmed": cycle.get("trimmed", 0)},
        "recording": rows,
    }
    if sub.layout:
        draft["layout"] = sub.layout
    if cycle["events"]:
        draft["events"] = [{"t": t, "event": e} for t, e in cycle["events"]]
    return draft
