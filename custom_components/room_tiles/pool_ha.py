"""Pool / spa systems on live HA states: runs pool.py for each system and
feeds its sensors (sensor.py) - one per body, plus the combined Pool / Spa
one for a shared system. Also the actions' targets (services.py)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable

from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from .model import PoolSystem
from .pool import (
    body_name,
    ON_OFF,
    BodyInput,
    BodyResult,
    PoolLogic,
    SystemInput,
    TimeToTarget,
    body_word,
    eta_word,
    short_word,
    status_word,
)
from .wording import render, tile_words, w, word_json

TICK = timedelta(seconds=60)


HEATER_MODES = ("heat", "cool")
# a heater asked on / off (the tiles' heater button) is shown as on its way
# until HA reports it so, at most this long: pool controllers can take
# minutes (a heater's restart delay, a pump starting first, the cloud)
HEATER_WAIT_S = 300


class PoolRuntime:
    """One pool / spa system: its logic, its time-to-target runs, the latest
    per-body view, and the sensors to refresh."""

    def __init__(self, hass: HomeAssistant, ps: PoolSystem) -> None:
        self.hass = hass
        self.ps = ps
        self.logic = PoolLogic(ps.layout)
        self.tt: dict[str, TimeToTarget] = {b: TimeToTarget() for b in ps.bodies()}
        self.views: dict[str, dict[str, Any]] = {}
        self.mode: str | None = None
        self.listeners: list[Callable[[], None]] = []
        self._unsub: list[Callable[[], None]] = []
        # pumps Room Tiles started for a heater (they were off) - the spa
        # going off stops them again; kept while HA runs
        self.started_pumps: set[str] = set()
        # each body's heater mode last seen on (heat / cool): the tile's
        # heater button turns it back on in that mode
        self.heater_last: dict[str, str] = {}
        # a heater asked on / off and not there yet: body -> (on, asked at)
        self.heater_asked: dict[str, tuple[bool, float]] = {}

    # ---- lifecycle -------------------------------------------------------------

    @callback
    def start(self) -> None:
        if self._unsub:
            return
        ents = self.ps.entities()
        if ents:
            self._unsub.append(async_track_state_change_event(self.hass, ents, self._changed))
        # a @callback method: HA runs it in the event loop (a plain lambda
        # would go to a worker thread - state writes from there are unsafe)
        self._unsub.append(async_track_time_interval(self.hass, self._tick, TICK))
        self.refresh()

    @callback
    def stop(self) -> None:
        for u in self._unsub:
            u()
        self._unsub = []

    @callback
    def reconfigure(self, ps: PoolSystem) -> None:
        """The system was edited: new entities / layout; keeps each body's last
        reading and time-to-target run."""
        running = bool(self._unsub)
        self.stop()
        last_temp = self.logic.last_temp
        self.ps = ps
        self.logic = PoolLogic(ps.layout)
        self.logic.last_temp = {b: v for b, v in last_temp.items() if b in ps.bodies()}
        self.tt = {b: self.tt.get(b, TimeToTarget()) for b in ps.bodies()}
        self.views = {}
        if running:
            self.start()

    def restore(self, body: str, attrs: dict[str, Any]) -> None:
        """A body sensor's last state after an HA restart: its last water
        reading (shown while it isn't circulating), its time-to-target run and
        its heater's last mode."""
        temp, read = attrs.get("temperature"), attrs.get("temperature_read")
        when = dt_util.parse_datetime(read) if isinstance(read, str) else None
        if isinstance(temp, (int, float)) and when is not None and body not in self.logic.last_temp:
            self.logic.last_temp[body] = (int(temp), when.timestamp())
        if body in self.tt and attrs.get("time_to_target_run"):
            self.tt[body] = TimeToTarget.from_dict(attrs["time_to_target_run"])
        if attrs.get("heater_next") in HEATER_MODES and body not in self.heater_last:
            self.heater_last[body] = attrs["heater_next"]

    # ---- computing -------------------------------------------------------------

    def _state(self, entity: str | None) -> str | None:
        st = self.hass.states.get(entity) if entity else None
        return st.state if st else None

    def _input(self, now: float) -> SystemInput:
        ps = self.ps
        bodies = {}
        for name in ps.bodies():
            b = getattr(ps, name)
            clim = self.hass.states.get(b.heater) if b and b.heater else None
            # its own sensor, else the heater's reading (ScreenLogic)
            temp = self._state(b.temp) if b and b.temp else (clim.attributes.get("current_temperature") if clim else None)
            bodies[name] = BodyInput(
                temp=temp,
                heater_mode=clim.state if clim else None,
                heater_action=clim.attributes.get("hvac_action") if clim else None,
                target=clim.attributes.get("temperature") if clim else None,
                pump=self._state(b.pump) if b and b.pump else None,
                has_heater=bool(b and b.heater),
            )
        # when the system's switches dropped out (for the grace period)
        watch = [ps.spa_mode, ps.pump] if ps.layout == "shared" else [getattr(ps, n).pump for n in ps.bodies()]
        dropped = [
            st.last_changed.timestamp()
            for e in watch
            if e and (st := self.hass.states.get(e)) is not None and st.state not in ON_OFF
        ]
        return SystemInput(
            layout=ps.layout,
            bodies=bodies,
            spa_mode=self._state(ps.spa_mode),
            pump=self._state(ps.pump),
            now=now,
            dropped_at=max(dropped) if dropped else None,
        )

    @callback
    def refresh(self) -> None:
        now = dt_util.utcnow().timestamp()
        inp = self._input(now)
        results = self.logic.update(inp)
        self.mode = self.logic.mode(inp)
        for name, b in inp.bodies.items():
            if b.heater_mode in HEATER_MODES:
                self.heater_last[name] = b.heater_mode
        for name, r in results.items():
            running = r.state in ("heating", "cooling")
            live = r.temp if r.temp_age_s is None else None
            eta = self.tt[name].update(now, f"{name}:{r.state}", running, live, r.target)
            self.views[name] = self._view(name, r, eta, now)
        for listener in list(self.listeners):
            listener()

    def ask_heater(self, body: str, on: bool) -> None:
        """The tiles' heater button asked for it: shown as on its way until HA
        reports it (HEATER_WAIT_S at most)."""
        self.heater_asked[body] = (on, dt_util.utcnow().timestamp())
        self.refresh()

    def heater_pending(self, body: str, r: BodyResult, now: float) -> str:
        """ "on" / "off": asked for and not reported yet; "" otherwise."""
        asked = self.heater_asked.get(body)
        if asked is None:
            return ""
        on, at = asked
        if (r.heater in ("heating", "heat", "cooling", "cool")) == on or now - at > HEATER_WAIT_S:
            del self.heater_asked[body]
            return ""
        return "on" if on else "off"

    def _view(self, name: str, r: BodyResult, eta: int | None, now: float) -> dict[str, Any]:
        eta_w = eta_word(eta)
        text = render(eta_w)
        body = getattr(self.ps, name)
        has_pump = bool(body and body.pump) if self.ps.layout != "shared" else True
        pending = self.heater_pending(name, r, now)
        # (asked on, not reported yet: on its way - a chiller's in its words)
        starting = "chiller_starting" if self.heater_next(name) == "cool" else "heater_starting"
        short_w = short_word(r, eta_w, has_pump)
        if pending == "on":
            short_w = w(f"pool.short.{starting}")
        short = render(short_w)
        read = (
            dt_util.utc_from_timestamp(now - r.temp_age_s).isoformat() if r.temp_age_s is not None else None
        )
        heater_on = "on" if r.heater in ("heating", "heat") else "off"
        temp = "" if r.temp is None else str(r.temp)
        target = "" if r.target is None else str(r.target)
        return {
            "state": r.state,
            "body": name,
            "temperature": r.temp,
            "temperature_read": read,  # set while showing the last reading
            "target": r.target,
            "heater": r.heater,
            "active": r.active,
            "status": render(
                status_w := (
                    w(f"pool.{starting}")
                    if pending == "on"
                    else status_word(name, r, eta_w, shared_mode=self.mode, has_pump=has_pump)
                )
            ),
            "status_word": word_json(status_w),  # (each display's own language: wording.py)
            # what the tile can do: set the heater / target, turn the body on
            # (shared: the spa = spa mode, the pool = pool mode; else its pump)
            "has_heater": bool(body and body.heater),
            # the tile's details open this (HA's thermostat dialog: on / off,
            # set point) rather than Room Tiles' own sensor
            "heater_entity": body.heater if body else None,
            # the mode the heater button turns on (its last one; heat at first)
            "heater_next": self.heater_next(name),
            # "on" / "off": the heater button asked for it, not reported yet
            "heater_pending": pending,
            "can_turn_on": has_pump,
            "short": short,
            "time_to_target": eta,
            "time_to_target_text": text,
            "time_to_target_run": self.tt[name].as_dict(),
            # MIRRORED: read by frontend/src/room-tiles-panel.ts (water tile) and
            # firmware/components/room_tiles/board_kinds.cpp - change the format in all three
            # the panels' water tile text: title|temp|status|look|target|heater
            "tile": f"{body_name(name)}|{temp}|{short}|{r.state}|{target}|{heater_on}",
            # its words, for each display to put in its own language
            "tile_words": tile_words({"0.0": body_word(name), "0.2": short_w}),
        }

    @callback
    def _changed(self, _event: Event[EventStateChangedData]) -> None:
        self.refresh()

    @callback
    def _tick(self, _now: Any) -> None:
        self.refresh()

    # ---- what the actions act on -------------------------------------------------

    def heater_next(self, body: str) -> str:
        """The mode turning a body's heater on picks: the one it was last in,
        else heat (cool for a chiller that can't heat)."""
        if body in self.heater_last:
            return self.heater_last[body]
        b = getattr(self.ps, body)
        clim = self.hass.states.get(b.heater) if b and b.heater else None
        modes = (clim.attributes.get("hvac_modes") or []) if clim else []
        return "cool" if modes and "heat" not in modes and "cool" in modes else "heat"

    def body_for(self, body: str | None) -> str:
        """The combined sensor acts on the active body."""
        if body:
            return body
        return self.mode or self.ps.bodies()[0]
