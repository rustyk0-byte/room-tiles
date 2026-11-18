"""Pool / spa profiles: what each body (pool, spa) is doing, for the Pool, Spa
and combined Pool / Spa tiles - from the controller's raw entities.

Pure logic, no HA (tested in tests/test_pool.py); sensor.py runs it on live
states. Ported from the author's hand-written template sensors (Jandy
iAquaLink, shared pool + spa, 2026-11-03..05).

Equipment LAYOUTS:
- "shared": the spa sits on the pool; one pump and one heater switch between
  them - the system is in pool mode OR spa mode (`spa_mode` switch on = spa),
  and only the ACTIVE body's temperature reads.
- "separate": each body has its own pump (and heater); both can run at once.
- "pool" / "spa": one body only.

Per body the result: state (heating / cooling / idle / off / switching /
pump_off / standby / offline, or "on" for a body without a heater), temperature (the last reading, with its age,
while the body isn't circulating), heater, target, status text, time to target.
"standby" = a shared system's other body (not the active one).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .wording import Word, minutes, render, t, w

LAYOUTS = ("shared", "separate", "pool", "spa")
BODIES = ("pool", "spa")
OFFLINE_GRACE_S = 120  # short integration drop-outs keep the last values
SAMPLE_MAX_AGE_S = 12 * 3600  # long enough for a slow pool to move 2 degrees
ETA_MAX_MIN = 4 * 24 * 60  # longer = the line is too flat to trust: no time shown
SLOPE_MIN = 1e-4  # degrees / min; flatter = no estimate (guards the division)
TREND_MIN = 1.5  # degrees the LINE must move across the readings (jitter alone doesn't)
SAMPLES_MAX = 8
NEW_RUN_GAP_S = 600

# raw values
ON_OFF = frozenset({"on", "off"})


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


@dataclass
class BodyInput:
    """One body's raw readings (states as strings / numbers)."""

    temp: Any = None  # the water temperature sensor's state
    heater_mode: str | None = None  # climate state: heat / cool / off / ...
    heater_action: str | None = None  # climate hvac_action: heating / cooling / idle / off
    target: Any = None  # climate `temperature`
    pump: str | None = None  # separate layout: this body's pump switch
    has_heater: bool = True  # a heater (climate) is set up for this body


@dataclass
class SystemInput:
    layout: str
    bodies: dict[str, BodyInput]
    spa_mode: str | None = None  # shared: the switch putting it in spa mode
    pump: str | None = None  # shared: the circulation pump
    now: float = 0.0  # unix time
    # when the most recent raw entity went unavailable (for the grace period)
    dropped_at: float | None = None


@dataclass
class BodyResult:
    state: str
    temp: int | None
    temp_age_s: float | None  # None = live reading
    heater: str  # heating / cooling / heat / cool / off / none (no heater set up)
    target: int | None
    active: bool  # circulating now (shared: this body is the active one)


def _heater(b: BodyInput) -> str:
    if not b.has_heater:
        return "none"
    if b.heater_action in ("heating", "cooling"):
        return b.heater_action
    if b.heater_mode in ("heat", "cool"):
        return b.heater_mode
    return "off"


def _rounded(v: Any) -> int | None:
    f = _num(v)
    return round(f) if f is not None else None


@dataclass
class PoolLogic:
    """One pool / spa system over time: remembers each body's last reading
    (shown while it isn't circulating) and the previous results (kept through
    short drop-outs)."""

    layout: str
    last_temp: dict[str, tuple[int, float]] = field(default_factory=dict)  # body -> (temp, when)
    last: dict[str, BodyResult] = field(default_factory=dict)

    def bodies(self) -> tuple[str, ...]:
        return BODIES if self.layout in ("shared", "separate") else (self.layout,)

    def update(self, inp: SystemInput) -> dict[str, BodyResult]:
        out: dict[str, BodyResult] = {}
        for name in self.bodies():
            b = inp.bodies.get(name, BodyInput())
            t = _rounded(b.temp)
            if t is not None:
                self.last_temp[name] = (t, inp.now)
        offline = self._offline(inp)
        if offline and inp.dropped_at is not None and inp.now - inp.dropped_at < OFFLINE_GRACE_S and self.last:
            return dict(self.last)  # a short drop-out: keep what we had
        for name in self.bodies():
            out[name] = self._body(inp, name, offline)
        self.last = out
        return out

    def _offline(self, inp: SystemInput) -> bool:
        if self.layout == "shared":
            return inp.spa_mode not in ON_OFF or inp.pump not in ON_OFF
        pumps = [inp.bodies.get(n, BodyInput()).pump for n in self.bodies()]
        return any(p is not None and p not in ON_OFF for p in pumps)

    def mode(self, inp: SystemInput) -> str | None:
        """Shared: the active body ("pool" / "spa"); None otherwise."""
        if self.layout != "shared":
            return None
        return "spa" if inp.spa_mode == "on" else "pool"

    def _shown_temp(self, name: str, now: float, live: int | None) -> tuple[int | None, float | None]:
        if live is not None:
            return live, None
        if name in self.last_temp:
            t, when = self.last_temp[name]
            return t, max(0.0, now - when)
        return None, None

    def _body(self, inp: SystemInput, name: str, offline: bool) -> BodyResult:
        b = inp.bodies.get(name, BodyInput())
        live = _rounded(b.temp)
        temp, age = self._shown_temp(name, inp.now, live)
        heater = _heater(b)
        target = _rounded(b.target)
        if offline:
            return BodyResult("offline", temp, age, "off", target, False)
        if self.layout == "shared":
            active = self.mode(inp) == name
            if not active:
                return BodyResult("standby", temp, age, heater, target, False)
            other = "spa" if name == "pool" else "pool"
            old_reads = _num(inp.bodies.get(other, BodyInput()).temp) is not None
            if live is None:
                # switching: the active body has no reading yet while the pump
                # runs or the OLD body still reads (its valves haven't turned)
                state = "switching" if (inp.pump == "on" or old_reads) else "pump_off"
                return BodyResult(state, temp, age, heater, target, True)
        else:
            # its own pump (or none set up: then it's simply "on"); without a
            # reading the state still follows the heater, the temperature
            # shown is the last reading
            if b.pump == "off":
                return BodyResult("pump_off", temp, age, heater, target, False)
            active = True
        if heater == "none":
            return BodyResult("on", temp, age, heater, None, active)
        if heater in ("heating", "cooling"):
            state = heater
        elif heater in ("heat", "cool"):
            state = "idle"
        else:
            state = "off"
        return BodyResult(state, temp, age, heater, target, active)


# ---- display text (English for now; translations later) ------------------------

def tile_name(body: str | None) -> str:
    """A water tile's name - its sensor's in HA and the tile picker's: Pool,
    Spa, or a shared system's one tile, Pool / Spa (HA's language)."""
    return t("names.pool_spa") if body is None else t(f"pool.body.{body}")


# Room Tiles' own switches (switch.py): a shared system's Spa Mode. (The
# heaters are the water tiles' heater button - no switches.)
def switch_name(key: str) -> str:
    """An own switch's name (HA's language)."""
    return t(f"names.{key}")


def switch_keys(ps) -> list[str]:
    """Which own switches a system gets."""
    return ["spa_mode"] if ps.layout == "shared" else []


def switch_body(key: str) -> str:
    return "spa"


def switch_uid(pool_id: str, key: str) -> str:
    return f"pool_{pool_id}_{key}"


def body_word(name: str) -> Word:
    return w(f"pool.body.{name}")


def body_name(name: str) -> str:
    return render(body_word(name))


def status_word(name: str, r: BodyResult, eta: Word = "", shared_mode: str | None = None, has_pump: bool = False) -> Word:
    """The body's status line (what the panels' long text showed) as a word
    (wording.py: each display's language). `eta`: the time left (a word)."""
    set_to = f"{r.target}°" if r.target is not None else "--"
    left = w("pool.time_left", eta=eta) if eta else ""
    if r.state == "offline":
        return w("pool.offline")
    if r.state == "standby":
        return w("pool.off_other_running", body=body_word(shared_mode)) if shared_mode else w("pool.off")
    if r.state == "switching":
        return w("pool.switching_to", body=body_word(name))
    if r.state == "pump_off":
        # a heater only runs with water flowing through it; many controllers
        # (Jandy, ...) start the pump themselves when the heater goes on
        return w("pool.heater_waiting_for_pump") if r.heater in ("heat", "cool", "heating", "cooling") else w("pool.pump_off")
    if r.heater == "none":
        return w("pool.pump_on") if has_pump else ""
    if r.heater == "heating":
        return [w("pool.heating_to", target=set_to), left]
    if r.heater == "cooling":
        return [w("pool.chilling_to", target=set_to), left]
    if r.heater == "heat":
        return w("pool.heater_on_set", target=set_to)
    if r.heater == "cool":
        return w("pool.chiller_on_set", target=set_to)
    return w("pool.heater_off_set", target=set_to)


def status_text(name: str, r: BodyResult, eta: Word = "", shared_mode: str | None = None, has_pump: bool = False) -> str:
    """The body's status line in HA's language."""
    return render(status_word(name, r, eta, shared_mode, has_pump))


# state -> its short token (pool.short.*)
SHORT = {
    "heating": "heating",
    "cooling": "chilling",
    "idle": "idle",
    "off": "heater_off",
    "switching": "switching",
    "pump_off": "pump_off",
    "offline": "offline",
    "standby": "standby",
}


def short_word(r: BodyResult, eta: Word = "", has_pump: bool = False) -> Word:
    """One or two words for the tile (the set point is on its roller), as a
    word; `eta`: the time left (a word)."""
    if r.state == "on":
        return w("pool.short.pump_on") if has_pump else ""
    if r.state == "pump_off" and r.heater in ("heat", "cool", "heating", "cooling"):
        return w("pool.short.waiting_for_pump")
    s = w(f"pool.short.{SHORT[r.state]}") if r.state in SHORT else ""
    return [s, "\n", eta] if eta and r.state in ("heating", "cooling") else s


def short_text(r: BodyResult, eta: Word = "", has_pump: bool = False) -> str:
    """The tile's words in HA's language."""
    return render(short_word(r, eta, has_pump))


# ---- time to target ------------------------------------------------------------


@dataclass
class TimeToTarget:
    """Minutes until the target, from a least-squares line through the
    temperature CHANGES of the current heating / chilling run (the sensors
    read whole degrees with jitter). A new run (other body, heat <-> chill,
    or 10+ min not running) starts fresh. Needs >= 3 samples spanning >= 2
    degrees; shown only while running toward the target. Chilling = a
    falling line (target and slope both below zero, so the time is still
    positive). No time when the line is flat or the wrong way, the target is
    already reached, or it would be more than ETA_MAX_MIN (a few days - a
    big pool can take more than one; hours keep counting past 24)."""

    samples: list[tuple[float, int]] = field(default_factory=list)
    run_key: str = ""
    last_run: float = 0.0

    def update(self, now: float, run_key: str, running: bool, temp: int | None, target: int | None) -> int | None:
        if not running or temp is None or target is None:
            return None
        if run_key != self.run_key or now - self.last_run >= NEW_RUN_GAP_S:
            self.samples = []
        self.run_key, self.last_run = run_key, now
        self.samples = [p for p in self.samples if now - p[0] < SAMPLE_MAX_AGE_S]
        if len(self.samples) >= 2 and self.samples[-2][1] == temp and abs(self.samples[-1][1] - temp) == 1:
            self.samples.pop()  # a 1-degree flicker back: jitter, not a step (keeps hours of a slow pool)
        elif not self.samples or self.samples[-1][1] != temp:
            self.samples.append((now, temp))
        self.samples = self.samples[-SAMPLES_MAX:]
        return self.eta(now, temp, target, cooling=run_key.endswith(":cooling"))

    def eta(self, now: float, temp: int, target: int, cooling: bool) -> int | None:
        if (temp <= target) if cooling else (temp >= target):
            return None  # there already (or past it)
        pts = self.samples
        if len(pts) < 3 or max(p[1] for p in pts) - min(p[1] for p in pts) < 2:
            return None
        x0 = pts[0][0]
        xs = [(p[0] - x0) / 60 for p in pts]
        ys = [p[1] for p in pts]
        n = len(pts)
        sx, sy = sum(xs), sum(ys)
        sxx = sum(x * x for x in xs)
        sxy = sum(x * y for x, y in zip(xs, ys))
        d = n * sxx - sx * sx
        if d <= 0:
            return None
        slope = (n * sxy - sx * sy) / d
        icpt = (sy - slope * sx) / n
        est = icpt + slope * ((now - x0) / 60)
        est = min(max(est, temp - 0.5), temp + 0.5)
        if (slope > -SLOPE_MIN) if cooling else (slope < SLOPE_MIN):
            return None  # flat or going the wrong way
        if abs(slope) * (xs[-1] - xs[0]) < TREND_MIN:
            return None  # jitter around a level, not a trend
        left = (target - est) / slope
        if left > ETA_MAX_MIN:
            return None  # nearly flat: a huge number means nothing
        return max(round(left), 1)

    def as_dict(self) -> dict[str, Any]:
        return {"samples": [list(p) for p in self.samples], "run_key": self.run_key, "last_run": self.last_run}

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> TimeToTarget:
        d = d or {}
        return cls(
            samples=[(float(p[0]), int(p[1])) for p in d.get("samples") or [] if len(p) == 2],
            run_key=str(d.get("run_key") or ""),
            last_run=float(d.get("last_run") or 0),
        )


def eta_word(m: int | None) -> Word:
    """Time to the target as a word, the same way as appliances' time left
    ("~55m" / "~1h 10m"); "" when there's no estimate."""
    return minutes(max(m, 1)) if m is not None else ""


def eta_text(m: int | None) -> str:
    """Time to the target in HA's language."""
    return render(eta_word(m))
