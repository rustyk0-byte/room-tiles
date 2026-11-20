"""Room Tiles' own sensors: one per appliance profile (store `appliances`).

Each runs the profile's units through appliance.py on the live raw entities
and publishes what the appliance tile shows. State: "active" / "idle";
attributes: `units` (per unit: phase, status, time left) and `tile` - the
same "label|phase|status|base|time;..." text the wall panels read today.
A finished unit (done / waiting) survives HA restarts.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Context, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .source_device import appliance_source, link, pool_source, robot_source
from .voice import is_new, own_defaults
from .appliance import HOLD, RUNNING, UnitLogic, format_minutes, known, minutes_left, power_raw, status_text, status_word
from .repairs import async_update_appliance_questions
from .appliance_presets import PRESETS
from .model import Appliance, ApplianceUnit
from .ops import SECTION_APPLIANCES, SECTION_POOLS, SECTION_ROBOTS
from .panels import LINK_ENTITY
from .robot import CLEAN_AREA, OURS_S, QueueStep, RoomQueue, idle_is_a_stop, unknown_code, alert_of, mode_option, tile_text, tile_words_of, view as robot_view
from .wording import minutes, tile_words, word_json
from .wording import t as words
from .pool import tile_name
from .pool_ha import PoolRuntime

ICONS = {"dishwasher": "mdi:dishwasher", "washer": "mdi:washing-machine", "dryer": "mdi:tumble-dryer"}
BASE = {"dishwasher": "plate", "washer": "shirt", "dryer": "shirt"}
OPEN = frozenset({"on", "open", "opening"})
TICK = timedelta(seconds=30)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    store = entry.runtime_data
    # the revision wall panels watch, and where to fetch from (panels.py)
    async_add_entities([PanelLinkSensor(store, is_new(hass, LINK_ENTITY))])
    live: dict[str, ApplianceSensor] = {}
    store.appliance_entities = live

    @callback
    def sync(sections: tuple[str, ...] | None = None) -> None:
        if sections is not None and SECTION_APPLIANCES not in sections:
            return
        want = {a.id: a for a in store.data.appliances}
        reg = er.async_get(hass)
        for aid in [a for a in live if a not in want]:
            ent = live.pop(aid)
            if ent.entity_id and reg.async_get(ent.entity_id):
                reg.async_remove(ent.entity_id)
            elif ent.hass:
                hass.async_create_task(ent.async_remove())
        new = []
        for aid, ap in want.items():
            if aid in live:
                live[aid].configure(ap)
            else:
                live[aid] = ApplianceSensor(ap)
                live[aid]._peers = live  # the other appliances (a washer waiting for a separate dryer)
                live[aid]._rt_fresh = is_new(hass, live[aid].entity_id)
                new.append(live[aid])
            link(hass, live[aid], appliance_source(ap))  # its device and area
        if new:
            async_add_entities(new)

    sync()
    entry.async_on_unload(store.async_add_listener(sync))

    # pool / spa systems: a runtime each, a sensor per body (+ combined)
    runtimes: dict[str, PoolRuntime] = {}
    store.pool_runtimes = runtimes  # the Spa Mode switch acts through them (switch.py)
    pool_sensors: dict[str, list[PoolSensor]] = {}
    store.pool_entities = {}  # entity id -> (runtime, body or None)

    @callback
    def sync_pools(sections: tuple[str, ...] | None = None) -> None:
        if sections is not None and SECTION_POOLS not in sections:
            return
        want = {p.id: p for p in store.data.pools}
        reg = er.async_get(hass)

        def drop(ent: PoolSensor) -> None:
            store.pool_entities.pop(ent.entity_id, None)
            if ent.entity_id and reg.async_get(ent.entity_id):
                reg.async_remove(ent.entity_id)
            elif ent.hass:
                hass.async_create_task(ent.async_remove())

        for pid in [p for p in runtimes if p not in want]:  # removed systems
            runtimes.pop(pid).stop()
            for ent in pool_sensors.pop(pid, []):
                drop(ent)
        new: list[PoolSensor] = []
        for pid, ps in want.items():
            rt = runtimes.get(pid)
            if rt is None:
                rt = runtimes[pid] = PoolRuntime(hass, ps)
            elif rt.ps.as_dict() != ps.as_dict():
                rt.reconfigure(ps)  # edited: same sensors where possible
            need: list[str | None] = list(ps.tiles())
            have = pool_sensors.setdefault(pid, [])
            for ent in [e for e in have if e.body not in need]:
                have.remove(ent)
                drop(ent)
            for body in need:
                if not any(e.body == body for e in have):
                    ent = PoolSensor(rt, body, store)
                    ent._rt_fresh = is_new(hass, ent.entity_id)
                    have.append(ent)
                    new.append(ent)
            for ent in have:
                link(hass, ent, pool_source(ps, ent.body))  # its device and area
        if new:
            async_add_entities(new)

    sync_pools()
    entry.async_on_unload(store.async_add_listener(sync_pools))

    # robot vacuums: a sensor each
    robots: dict[str, RobotSensor] = {}

    @callback
    def sync_robots(sections: tuple[str, ...] | None = None) -> None:
        if sections is not None and SECTION_ROBOTS not in sections:
            return
        want = {r.id: r for r in store.data.robots}
        reg = er.async_get(hass)
        for rid in [r for r in robots if r not in want]:
            ent = robots.pop(rid)
            if ent.entity_id and reg.async_get(ent.entity_id):
                reg.async_remove(ent.entity_id)
            elif ent.hass:
                hass.async_create_task(ent.async_remove())
        new = []
        for rid, rb in want.items():
            if rid in robots:
                robots[rid].configure(rb)
            else:
                robots[rid] = RobotSensor(rb)
                robots[rid]._rt_fresh = is_new(hass, robots[rid].entity_id)
                new.append(robots[rid])
            link(hass, robots[rid], robot_source(rb))  # its device and area
        if new:
            async_add_entities(new)

    sync_robots()
    store.robot_entities = robots  # the room queue's service reaches them here
    entry.async_on_unload(store.async_add_listener(sync_robots))

    @callback
    def stop_all() -> None:
        for rt in runtimes.values():
            rt.stop()

    entry.async_on_unload(stop_all)


class ApplianceSensor(SensorEntity, RestoreEntity):
    _attr_entity_registry_visible_default = False  # Room Tiles' own: hidden in HA
    _attr_should_poll = False

    def __init__(self, ap: Appliance) -> None:
        self._ap = ap
        self._logic: dict[str, UnitLogic] = {}
        # smart-plug units: since when the power has been below the threshold
        self._below: dict[str, float | None] = {}
        # raw states the preset doesn't know, per unit - asked once on the
        # Appliances page (answers become the unit's overrides)
        self._questions: dict[str, list[str]] = {}
        self._unsub: list = []
        self._attr_unique_id = f"appliance_{ap.id}"
        self.entity_id = f"sensor.room_tiles_{ap.id}"
        self._build(ap)

    # ---- configuration --------------------------------------------------------

    def _build(self, ap: Appliance) -> None:
        old = self._logic
        self._logic = {}
        for u in ap.units:
            prev = old.get(u.id)
            logic = UnitLogic(
                PRESETS[u.preset], finished=u.finished, overrides=dict(u.overrides), door_clears=u.door_clears
            )
            if prev is not None and prev.preset.id == u.preset:
                logic.restore(prev.phase, prev.running)
                logic.door = prev.door
            if logic.phase in ("done", "waiting") and logic.phase != u.finished:
                logic.phase = u.finished
            self._logic[u.id] = logic
        self._ap = ap
        self._attr_name = ap.name
        kinds = {u.appliance for u in ap.units}
        self._attr_icon = ICONS.get(next(iter(kinds)) if len(kinds) == 1 else "washer")

    @callback
    def configure(self, ap: Appliance) -> None:
        """The profile was edited."""
        if ap.as_dict() == self._ap.as_dict():
            return
        self._build(ap)
        self._prune_questions()
        if self.hass:
            self._update_issue()
            self._subscribe()
            self._read_all()
            self.async_write_ha_state()

    def _subscribe(self) -> None:
        for u in self._unsub:
            u()
        ents = sorted({e for u in self._ap.units for e in u.entities()})
        self._unsub = [async_track_state_change_event(self.hass, ents, self._changed)] if ents else []
        self._unsub.append(async_track_time_interval(self.hass, self._tick, TICK))

    # ---- HA lifecycle ---------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        own_defaults(self.hass, self.entity_id, getattr(self, "_rt_fresh", False))  # voice.py
        last = await self.async_get_last_state()
        if last is not None:
            for saved in last.attributes.get("units") or []:
                logic = self._logic.get(saved.get("id"))
                if logic is not None:
                    logic.restore(saved.get("phase"), bool(saved.get("running")))
            for q in last.attributes.get("questions") or []:
                if q.get("unit") in self._logic and q.get("state"):
                    self._questions.setdefault(q["unit"], []).append(str(q["state"]))
            self._prune_questions()
            self._update_issue()
        self._subscribe()
        self._read_all()

    async def async_will_remove_from_hass(self) -> None:
        for u in self._unsub:
            u()
        self._unsub = []
        async_update_appliance_questions(self.hass, self._ap.id, self._ap.name, [])

    # ---- events -----------------------------------------------------------------

    def _note(self, u: ApplianceUnit, state: str | None) -> None:
        """Remember a raw state the preset doesn't know (asked once)."""
        logic = self._logic[u.id]
        r = (state or "").strip()
        if not r or r.lower() in HOLD or known(logic.preset, r, u.overrides):
            return
        seen = self._questions.setdefault(u.id, [])
        if r.lower() not in (x.lower() for x in seen):
            seen.append(r)
            self._update_issue()

    def _prune_questions(self) -> None:
        """Answered ones (now overrides) and units that are gone drop out."""
        units = {u.id: u for u in self._ap.units}
        self._questions = {
            uid: [r for r in rs if not known(self._logic[uid].preset, r, units[uid].overrides)]
            for uid, rs in self._questions.items()
            if uid in units
        }
        self._questions = {k: v for k, v in self._questions.items() if v}

    def _question_list(self) -> list[dict[str, str]]:
        labels = {u.id: u.label for u in self._ap.units}
        return [{"unit": uid, "label": labels.get(uid, uid), "state": r} for uid, rs in self._questions.items() for r in rs]

    def _update_issue(self) -> None:
        if self.hass:
            async_update_appliance_questions(self.hass, self._ap.id, self._ap.name, self._question_list())

    def _raw(self, u: ApplianceUnit, state: str | None) -> str | None:
        """The unit's raw state - a smart plug's power turned into running /
        off (with its below-threshold timer), else the entity's state."""
        logic = self._logic[u.id]
        if not logic.preset.power:
            return state
        try:
            watts = float(state) if state is not None else None
        except ValueError:
            watts = None
        raw, self._below[u.id] = power_raw(
            watts,
            u.power_on_w,
            self._below.get(u.id),
            dt_util.utcnow().timestamp(),
            u.power_off_min * 60,
            logic.running,
        )
        return raw if raw is not None else "unavailable"

    def _read_all(self) -> None:
        for u in self._ap.units:
            logic = self._logic[u.id]
            if u.door and (st := self.hass.states.get(u.door)) is not None:
                logic.door = st.state in OPEN
            if (st := self.hass.states.get(u.status)) is not None:
                logic.update(self._raw(u, st.state))
                self._note(u, st.state)

    @callback
    def _changed(self, event: Event[EventStateChangedData]) -> None:
        entity = event.data["entity_id"]
        new: State | None = event.data["new_state"]
        old: State | None = event.data["old_state"]
        if new is None:
            return
        for u in self._ap.units:
            logic = self._logic[u.id]
            if entity == u.status:
                was = logic.running
                logic.update(self._raw(u, new.state))
                self._note(u, new.state)
                if logic.running and not was:  # this unit started
                    for other in self._ap.units:
                        if f"unit:{u.id}" in other.clear:
                            self._logic[other.id].clear()
                    # a washer on its own tile waiting for this (dryer) one
                    for peer in getattr(self, "_peers", {}).values():
                        if peer is not self and peer.hass and peer.clear_for(f"appliance:{self._ap.id}"):
                            peer.async_write_ha_state()
            if entity == u.door:
                logic.set_door(new.state in OPEN)
            if entity in u.clear and new.state in OPEN and (old is None or old.state not in OPEN):
                logic.clear()
        self.async_write_ha_state()

    @callback
    def _tick(self, _now) -> None:
        # smart plugs: the "stayed low long enough" check needs the clock
        before = [lg.shown for lg in self._logic.values()]
        for u in self._ap.units:
            if self._logic[u.id].preset.power and (st := self.hass.states.get(u.status)) is not None:
                self._logic[u.id].update(self._raw(u, st.state))
        changed = before != [lg.shown for lg in self._logic.values()]
        if changed or any(lg.phase in RUNNING for lg in self._logic.values()):
            self.async_write_ha_state()

    @callback
    def clear_for(self, rule: str) -> bool:
        """Empty the finished units that `rule` clears; any?"""
        hit = False
        for u in self._ap.units:
            if rule in u.clear:
                self._logic[u.id].clear()
                hit = True
        return hit

    def clear(self, unit: str | None = None) -> None:
        """A tap on the tile: empty the finished unit(s)."""
        for uid, logic in self._logic.items():
            if unit in (None, uid):
                logic.clear()
        self.async_write_ha_state()

    # ---- what the tile reads ------------------------------------------------------

    def _unit_view(self, u: ApplianceUnit) -> dict[str, Any]:
        logic = self._logic[u.id]
        phase = logic.shown
        raw_state = self.hass.states.get(u.status) if self.hass else None
        raw = raw_state.state if raw_state else None
        if logic.preset.power:  # a power reading isn't a status: "Running"
            raw = "running" if logic.running else None
        time_state = self.hass.states.get(u.time) if (self.hass and u.time) else None
        mins = minutes_left(
            logic.preset,
            phase,
            raw,
            time_state.state if time_state else None,
            time_state.attributes.get("unit_of_measurement") if time_state else None,
            dt_util.utcnow(),
            value_changed=time_state.last_changed if time_state else None,
            raw_changed=raw_state.last_changed if raw_state else None,
        )
        return {
            "id": u.id,
            "label": u.label,
            "appliance": u.appliance,
            "phase": phase,
            "status": status_text(logic.preset, phase, raw, drawer=u.drawer),
            "time_left": format_minutes(mins),
            "minutes": mins,
            "running": logic.running,
            # the same as words, for each display's own language (wording.py)
            "status_word": status_word(logic.preset, phase, raw, drawer=u.drawer),
            "time_word": minutes(mins),
        }

    @property
    def native_value(self) -> str:
        return "idle" if all(lg.shown == "idle" for lg in self._logic.values()) else "active"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        units = [self._unit_view(u) for u in self._ap.units]
        # MIRRORED: read by frontend/src/appliance.ts parseUnits and
        # firmware/components/room_tiles/board_kinds.cpp + map_markers.cpp - change the format in all three
        tile = ";".join(
            f"{v['label']}|{v['phase']}|{v['status']}|{BASE[v['appliance']]}|{v['time_left']}" for v in units
        )
        # its words, for each display to put in its own language
        words: dict[str, Any] = {}
        for i, v in enumerate(units):
            words[f"{i}.2"] = v["status_word"]
            words[f"{i}.4"] = v["time_word"]
            v["status_word"], v["time_word"] = word_json(v["status_word"]), word_json(v["time_word"])
        # own_name: Room Tiles' name for it - HA builds the friendly name its
        # own (instance-configurable) way, e.g. with the device's name in front
        return {
            "appliance": self._ap.id,
            "units": units,
            "tile": tile,
            "tile_words": tile_words(words),
            "questions": self._question_list(),
            "own_name": self._attr_name,
        }


class PoolSensor(SensorEntity, RestoreEntity):
    """A pool / spa body's sensor (`body` "pool" / "spa"), or a shared
    system's combined Pool / Spa sensor (`body` None: follows the active
    body). State: heating / cooling / idle / off / switching / pump_off /
    standby / offline; attributes: temperature, target, heater, status...,
    and `tile` (the panels' water tile text)."""

    _attr_entity_registry_visible_default = False  # Room Tiles' own: hidden in HA
    _attr_should_poll = False
    # the time-to-target run data changes with every reading: kept for
    # restarts (restore state), not written to the history database
    _unrecorded_attributes = frozenset({"time_to_target_run"})

    def __init__(self, rt: PoolRuntime, body: str | None, store) -> None:
        self.rt = rt
        self.body = body
        # handed over at creation: during HA's start-up the config entry
        # isn't "loaded" yet, so it can't be looked up from here
        self._store = store
        ps = rt.ps
        suffix = f"_{body}" if body else ""
        self._attr_unique_id = f"pool_{ps.id}{suffix}"
        self.entity_id = f"sensor.room_tiles_{ps.id}{suffix}"
        self._attr_name = tile_name(body)
        self._attr_icon = "mdi:hot-tub" if body == "spa" else "mdi:pool"

    def _view(self) -> dict[str, Any]:
        return self.rt.views.get(self.rt.body_for(self.body), {})

    async def async_added_to_hass(self) -> None:
        own_defaults(self.hass, self.entity_id, getattr(self, "_rt_fresh", False))  # voice.py
        if (last := await self.async_get_last_state()) is not None:
            # the combined sensor: the body it showed last
            body = self.body or last.attributes.get("body")
            if body in self.rt.ps.bodies():
                self.rt.restore(body, dict(last.attributes))
        self._store.pool_entities[self.entity_id] = (self.rt, self.body)
        self.rt.listeners.append(self.async_write_ha_state)
        self.rt.start()

    async def async_will_remove_from_hass(self) -> None:
        if self.async_write_ha_state in self.rt.listeners:
            self.rt.listeners.remove(self.async_write_ha_state)

    @property
    def native_value(self) -> str | None:
        return self._view().get("state")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        v = dict(self._view())
        v.pop("state", None)
        v["pool"] = self.rt.ps.id
        v["own_name"] = self._attr_name  # Room Tiles' name (not HA's friendly name)
        if self.body is None:
            # the combined tile's title is the active body
            v["mode"] = self.rt.mode
        return v


@callback
def _vacuum_call(data) -> bool:
    return data.get("domain") == "vacuum"


class RobotSensor(SensorEntity, RestoreEntity):
    """A robot vacuum's tile sensor (robot.py): state = the tile's class
    (attention / error / cleaning / paused / returning / docked / idle /
    offline); attributes: status line, alert, `vacuum` (the tile's brand icon
    and details follow it), `clean_area`, and `tile` - the panels' text.

    It also runs the vacuum's ROOM QUEUE (robot.RoomQueue - the YAML Matic
    queue's rules) for a vacuum with HA's clean_area: `queue` (HA area ids
    waiting, in order) and `current` (the area being cleaned) are attributes,
    kept across restarts."""

    _attr_entity_registry_visible_default = False  # Room Tiles' own: hidden in HA
    _attr_should_poll = False
    _attr_icon = "mdi:robot-vacuum"

    def __init__(self, rb) -> None:
        self._rb = rb
        self._unsub = None
        self.rq = RoomQueue(queue=[])
        self._sending = asyncio.Lock()  # (one queue step out at a time: _do)
        self._alert = "none"  # the alert last seen (an episode starts on a change from none)
        self._unsub_calls = None
        # Room Tiles' own commands to the vacuum: their contexts, the last one's time
        self._ours: deque[str] = deque(maxlen=20)
        self._sent_at = 0.0
        # error codes it reported that Room Tiles has no words for and the
        # user hasn't answered yet (the Appliances page asks; Repairs says so)
        self._questions: list[str] = []
        self._attr_unique_id = f"robot_{rb.id}"
        self.entity_id = f"sensor.room_tiles_{rb.id}"
        self._attr_name = rb.name

    @callback
    def configure(self, rb) -> None:
        if rb.as_dict() == self._rb.as_dict():
            return
        self._rb = rb
        self._attr_name = rb.name
        if self.hass:
            self._subscribe()
            self._ask()  # (an answer takes its question away)
            self.async_write_ha_state()

    @callback
    def _ask(self, code: str | None = None) -> None:
        """A code to ask about (when it's unknown and unanswered), and the
        Repairs notice in step with what's still asked."""
        c = (code or "").strip().lower()
        if c and unknown_code(c) and c not in self._rb.overrides and c not in self._questions:
            self._questions.append(c)
        self._questions = [q for q in self._questions if q not in self._rb.overrides and unknown_code(q)]
        async_update_appliance_questions(
            self.hass, f"robot_{self._rb.id}", self._attr_name, [{"label": self._attr_name, "state": q} for q in self._questions]
        )

    def _subscribe(self) -> None:
        if self._unsub:
            self._unsub()
        self._unsub = async_track_state_change_event(self.hass, self._rb.entities(), self._changed)
        if self._unsub_calls is None:
            self._unsub_calls = self.hass.bus.async_listen(EVENT_CALL_SERVICE, self._call, event_filter=_vacuum_call)

    async def async_added_to_hass(self) -> None:
        own_defaults(self.hass, self.entity_id, getattr(self, "_rt_fresh", False))  # voice.py
        last = await self.async_get_last_state()
        if last is not None:
            a = last.attributes
            queue = [x for x in (a.get("queue") or []) if isinstance(x, str)]
            cur = a.get("current")
            self.rq = RoomQueue(queue=queue, current=cur if isinstance(cur, str) and cur else None)
            self.rq.taken_over = a.get("taken_over") is True
            since = a.get("queue_error_since")
            self.rq.error_since = float(since) if isinstance(since, (int, float)) else None
            self._questions = [str(q["code"]) for q in a.get("questions") or [] if isinstance(q, dict) and q.get("code")]
        self._alert = self._view()[0].alert
        self._subscribe()
        err = self.hass.states.get(self._rb.error) if self._rb.error else None
        self._ask(err.state if err else None)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._unsub_calls:
            self._unsub_calls()
            self._unsub_calls = None
        async_update_appliance_questions(self.hass, f"robot_{self._rb.id}", self._attr_name, [])  # (gone: its notice too)

    @callback
    def _changed(self, event) -> None:
        """The vacuum / its error sensor changed: the queue moves on when a
        room finished cleanly; an alert pauses it (and is reported)."""
        v, vac = self._view()
        if event.data.get("entity_id") == self._rb.vacuum:
            old = event.data.get("old_state")
            ours = event.context.id in self._ours or time.monotonic() - self._sent_at < OURS_S
            step = self.rq.on_state(
                old.state if old else None, vac.state if vac else None, v.alert, ours, idle_is_a_stop(self._maker())
            )
            if step is not None:
                self.hass.async_create_task(self._next_room(step, self.rq.stamp()))
        if event.data.get("entity_id") == self._rb.error:
            new = event.data.get("new_state")
            self._ask(new.state if new else None)
        self._watch_alert(v)
        self.async_write_ha_state()

    # vacuum commands that take it over from the queue (pause doesn't: the
    # queue waits; start doesn't while paused: that's a resume)
    TAKEOVER = frozenset({"start", "stop", "return_to_base", "clean_area", "clean_spot", "send_command"})

    @callback
    def _call(self, event) -> None:
        """A vacuum command through HA (its vacuum card, a voice assistant,
        an automation) that isn't Room Tiles' own, while a room of the queue
        is in progress: something else took the vacuum over - let go."""
        if not self.rq.current or event.context.id in self._ours:
            return
        service = event.data.get("service")
        if service not in self.TAKEOVER or not self._targets_vacuum(event.data.get("service_data") or {}):
            return
        vac = self.hass.states.get(self._rb.vacuum)
        if service == "start" and vac is not None and vac.state == "paused":
            return
        self.rq.let_go()
        self.async_write_ha_state()

    def _maker(self) -> str | None:
        """The vacuum's manufacturer (its HA device)."""
        reg = er.async_get(self.hass).async_get(self._rb.vacuum)
        if reg is None or not reg.device_id:
            return None
        dev = dr.async_get(self.hass).async_get(reg.device_id)
        return dev.manufacturer if dev else None

    def _targets_vacuum(self, data: dict) -> bool:
        """Does a service call's data name this vacuum (its entity, device or area)?"""

        def ids(key: str) -> list[str]:
            v = data.get(key)
            if isinstance(v, str):
                return [x.strip() for x in v.split(",")]
            return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []

        entities = ids("entity_id")
        if self._rb.vacuum in entities or "all" in entities:
            return True
        reg = er.async_get(self.hass).async_get(self._rb.vacuum)
        if reg is None:
            return False
        if reg.device_id and reg.device_id in ids("device_id"):
            return True
        areas = ids("area_id")
        if not areas:
            return False
        area = reg.area_id
        if area is None and reg.device_id:
            dev = dr.async_get(self.hass).async_get(reg.device_id)
            area = dev.area_id if dev else None
        return area is not None and area in areas

    @callback
    def _watch_alert(self, v) -> None:
        """An alert while a room is in progress: notify once per episode;
        cleared: dismiss; 12 h unresolved: cancel and clear the queue."""
        was, self._alert = self._alert, v.alert
        nid = f"room_tiles_vacuum_{self._rb.id}"
        if v.alert == "none":
            self.rq.on_alert("none", dt_util.utcnow().timestamp())
            if was != "none":
                self.hass.async_create_task(
                    self.hass.services.async_call("persistent_notification", "dismiss", {"notification_id": nid})
                )
            return
        if not self.rq.current:
            return  # docked and lifting the lid is no queue problem
        if self.rq.on_alert(v.alert, dt_util.utcnow().timestamp()):
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "notification_id": nid,
                        "title": words("robot.queue.cancelled_title", name=self._attr_name),
                        "message": words("robot.queue.cancelled_message", alert=v.alert_text or v.code),
                    },
                )
            )
            return
        if was == "none":
            key = "robot.queue.needs_you_title" if v.alert == "attention" else "robot.queue.error_title"
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "notification_id": nid,
                        "title": words(key, name=self._attr_name),
                        "message": words("robot.queue.paused_message", alert=v.alert_text or v.code, room=self._area_name(self.rq.current)),
                    },
                )
            )

    def _area_name(self, area: str | None) -> str:
        if not area:
            return ""
        from homeassistant.helpers import area_registry as ar

        a = ar.async_get(self.hass).async_get_area(area)
        return a.name if a else area

    async def _next_room(self, step: QueueStep, stamp: tuple[int, int]) -> None:
        """The queue moving on by itself (no one waits for it): a refusal is
        logged - the room stays queued, as a refused Start leaves it."""
        from homeassistant.exceptions import HomeAssistantError

        try:
            await self._do(step, stamp)
        except HomeAssistantError as err:
            _LOGGER.warning("%s: the next room wasn't sent: %s", self._rb.name, err)

    async def _do(self, step: QueueStep, stamp: tuple[int, int]) -> None:
        """Send the queue's step to the vacuum. clean_area goes out BEFORE the
        room leaves the queue: a refused command leaves the queue as it was.
        One step at a time; a room decided before the queue moved on (another
        room went out, or it was stopped / cleared / let go meanwhile) is
        never sent - two quick Starts send it once."""
        async with self._sending:
            if step.action == "clean" and self.rq.stamp() != stamp:
                return
            await self._send(step, stamp)

    async def _send(self, step: QueueStep, stamp: tuple[int, int]) -> None:
        target = {"entity_id": self._rb.vacuum}
        # (its own context: a command of ours is never taken for a takeover)
        ctx = Context()
        self._ours.append(ctx.id)
        self._sent_at = time.monotonic()
        if step.action == "clean" and step.area:
            await self._set_clean_mode(step.mode, ctx)
            await self.hass.services.async_call(
                "vacuum", "clean_area", {**target, "cleaning_area_id": [step.area]}, blocking=True, context=ctx
            )
            if self.rq.gen == stamp[0]:  # (stopped meanwhile: the queue stays empty)
                self.rq.sent(step.area)
        elif step.action in ("resume", "pause"):
            await self.hass.services.async_call(
                "vacuum", "start" if step.action == "resume" else "pause", target, blocking=True, context=ctx
            )
        elif step.action == "dock":
            await self.hass.services.async_call("vacuum", "return_to_base", target, blocking=True, context=ctx)
        self.async_write_ha_state()

    def _clean_mode_select(self) -> str | None:
        """The vacuum's clean-mode select (Matter RVC "Clean mode"), on its
        device - none for vacuums without one."""
        reg = er.async_get(self.hass)
        vac = reg.async_get(self._rb.vacuum)
        if vac is None or not vac.device_id:
            return None
        for e in er.async_entries_for_device(reg, vac.device_id):
            if e.domain == "select" and not e.disabled_by and (
                e.translation_key == "clean_mode" or "clean mode" in (e.original_name or e.name or "").lower()
            ):
                return e.entity_id
        return None

    async def _set_clean_mode(self, mode: str, ctx: Context | None = None) -> None:
        """Before a room: the vacuum's clean mode for it (vacuum / mop / both),
        when it has one and an option for that mode."""
        sel = self._clean_mode_select()
        st = self.hass.states.get(sel) if sel else None
        option = mode_option(list(st.attributes.get("options") or []), mode) if st else None
        if option and st.state != option:
            await self.hass.services.async_call(
                "select", "select_option", {"entity_id": sel, "option": option}, blocking=True, context=ctx
            )

    async def queue_action(self, action: str, area: str | None = None, index: int | None = None, start: bool = False) -> None:
        """The room queue's service (services.py vacuum_queue)."""
        v, vac = self._view()
        state = vac.state if vac else None
        step: QueueStep | None = None
        self.rq.taken_over = False  # (the queue is in use again: the note goes)
        if action == "add" and area:
            self.rq.add(area)
            # adding never resumes a paused vacuum; it starts only an idle queue
            if start and (state or "").lower() != "paused":
                step = self.rq.start(state, v.alert, manual=False)
        elif action == "remove" and area:
            self.rq.remove(area)
        elif action == "move" and area and index is not None:
            self.rq.move(area, index)
        elif action == "clear":
            self.rq.clear()
        elif action == "start":
            step = self.rq.start(state, v.alert, manual=True)
        elif action == "pause":
            step = QueueStep("pause")
        elif action == "skip":
            step = self.rq.skip()
        elif action == "stop":
            step = self.rq.stop_and_clear()
        self.async_write_ha_state()
        if step is not None:
            await self._do(step, self.rq.stamp())

    def _view(self):
        vac = self.hass.states.get(self._rb.vacuum) if self.hass else None
        err = self.hass.states.get(self._rb.error) if (self.hass and self._rb.error) else None
        room = self._area_name(self.rq.current) if self.hass else ""
        return robot_view(vac.state if vac else None, err.state if err else None, room, self.rq.taken_over, self._rb.overrides), vac

    @property
    def native_value(self) -> str:
        return self._view()[0].cls

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        v, vac = self._view()
        return {
            "own_name": self._attr_name,  # Room Tiles' name (not HA's friendly name)
            "robot": self._rb.id,
            "vacuum": self._rb.vacuum,
            "status": v.status,
            "status_word": word_json(v.status_word),  # (each display's own language: wording.py)
            "alert": v.alert,
            "alert_text": v.alert_text,
            "alert_word": word_json(v.alert_word),
            "code": v.code,
            "clean_area": bool(vac and int(vac.attributes.get("supported_features") or 0) & CLEAN_AREA),
            # the room queue: HA area ids waiting (in order), the one being cleaned
            "queue": list(self.rq.queue),
            "current": self.rq.current,
            "queue_error_since": self.rq.error_since,
            # cleared because something else took the vacuum over (shown until it docks)
            "taken_over": self.rq.taken_over,
            # error codes to ask the user about (Room Tiles has no words for them)
            "questions": [{"code": q} for q in self._questions],
            "tile": tile_text(v, self.rq.current or "", self.rq.queue),
            # its words, for each display to put in its own language
            "tile_words": tile_words_of(v),
        }


class PanelLinkSensor(SensorEntity):
    """Wall panels watch this (docs/DESIGN.md "Panel firmware"): its state is
    a revision that changes whenever what panels show may have changed; its
    `url` attribute is where HA answers their payload requests. The entity id
    is fixed - the panels' firmware asks for it by name."""

    _attr_entity_registry_visible_default = False  # Room Tiles' own: hidden in HA
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_name = "Room Tiles panel link"
    _attr_unique_id = "room_tiles_panel_link"
    _attr_icon = "mdi:tablet-dashboard"
    _unrecorded_attributes = frozenset({"url"})

    def __init__(self, store: Any, fresh: bool) -> None:
        self._store = store
        self._rt_fresh = fresh
        self.entity_id = LINK_ENTITY

    async def async_added_to_hass(self) -> None:
        own_defaults(self.hass, self.entity_id, self._rt_fresh)  # voice.py
        self.async_on_remove(self._store.panel_link.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> str:
        return str(self._store.panel_link.revision)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        from homeassistant.helpers.network import NoURLAvailableError, get_url

        try:
            url = get_url(self.hass, allow_external=False, allow_cloud=False)
        except NoURLAvailableError:
            url = None
        return {"url": url}
