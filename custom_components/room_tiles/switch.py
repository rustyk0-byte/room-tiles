"""Room Tiles' own pool / spa switches (pool.switch_keys): a shared system's
Spa Mode.

On = spa mode (its spa mode switch is on). Turning it on / off does what the
spa going on / off does (services.async_pool_on): spa mode - the valves -
and the spa's heater with it when its setting says so. The tiles never use
the brand's own switch; this routes to it.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .model import PoolSystem
from .ops import SECTION_POOLS
from .pool import switch_body, switch_keys, switch_name, switch_uid
from .services import async_pool_on
from .source_device import link, pool_source
from .voice import is_new, own_defaults

GONE = ("unavailable", "unknown")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    store = entry.runtime_data
    live: dict[tuple[str, str], PoolSwitch] = {}

    @callback
    def sync(sections: tuple[str, ...] | None = None) -> None:
        if sections is not None and SECTION_POOLS not in sections:
            return
        want = {(p.id, key): p for p in store.data.pools for key in switch_keys(p)}
        reg = er.async_get(hass)
        for k in [k for k in live if k not in want]:
            ent = live.pop(k)
            if ent.entity_id and reg.async_get(ent.entity_id):
                reg.async_remove(ent.entity_id)
            elif ent.hass:
                hass.async_create_task(ent.async_remove())
        new: list[PoolSwitch] = []
        for (pid, key), ps in want.items():
            ent = live.get((pid, key))
            if ent is None:
                ent = live[(pid, key)] = PoolSwitch(ps, key, store)
                ent._rt_fresh = is_new(hass, ent.entity_id)
                new.append(ent)
            elif ent.ps.as_dict() != ps.as_dict():
                ent.reconfigure(ps)
            link(hass, ent, pool_source(ps, switch_body(key)))
        if new:
            async_add_entities(new)

    sync()
    entry.async_on_unload(store.async_add_listener(sync))


class PoolSwitch(SwitchEntity):
    _attr_entity_registry_visible_default = False  # Room Tiles' own: hidden in HA
    _attr_should_poll = False
    _attr_icon = "mdi:hot-tub"

    def __init__(self, ps: PoolSystem, key: str, store) -> None:
        self.ps = ps
        self.key = key
        self._store = store
        self._unsub = None
        uid = switch_uid(ps.id, key)
        self._attr_unique_id = uid
        self.entity_id = f"switch.room_tiles_{uid[5:]}"
        self._attr_name = switch_name(key)

    async def async_added_to_hass(self) -> None:
        own_defaults(self.hass, self.entity_id, getattr(self, "_rt_fresh", False))  # voice.py
        self._follow()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    def _follow(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self.ps.spa_mode:

            @callback
            def changed(_event: Event[EventStateChangedData]) -> None:
                self.async_write_ha_state()

            self._unsub = async_track_state_change_event(self.hass, [self.ps.spa_mode], changed)

    @callback
    def reconfigure(self, ps: PoolSystem) -> None:
        self.ps = ps
        if self.hass:
            self._follow()
            self.async_write_ha_state()

    @property
    def available(self) -> bool:
        st = self.hass.states.get(self.ps.spa_mode) if self.ps.spa_mode else None
        return st is not None and st.state not in GONE

    @property
    def is_on(self) -> bool:
        st = self.hass.states.get(self.ps.spa_mode) if self.ps.spa_mode else None
        return st is not None and st.state == "on"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"pool": self.ps.id, "own_name": self._attr_name}

    async def _set(self, on: bool) -> None:
        rt = self._store.pool_runtimes.get(self.ps.id)
        if rt is None:
            raise ServiceValidationError("The spa isn't ready yet - try again in a moment")
        state = rt.views.get("spa", {}).get("state")
        if state in ("switching", "offline"):
            raise ServiceValidationError(f"The spa is {state} - try again in a moment")
        await async_pool_on(self.hass, rt, "spa", on)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
