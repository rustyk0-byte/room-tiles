"""Area lights as a light entity: "<Area> Area Lights (Room Tiles)"
(light.room_tiles_<area>_area_lights).

It IS the area's lights button (arealights.py): the same lights - every light
in the HA area minus the area's exclusions, or the area's override - switched
together, with brightness. So it can be a tile and a map marker like any
light (one to one), and a new home's boards and map start with it.

- Made for an area once it has a light and no override (with an override,
  the override is the area's lights). Every room with lights works alike -
  and a second lamp joins the group by itself. Once
  made it stays while the area exists and has lights - its lights follow
  the area's. An area with no lights has none.
- The user can say no per area (Area settings, `light_entity` off): none is
  made, and one already made is removed.
- It switches INDIVIDUAL lights only (arealights: no light groups), so it
  never repeats the home's own groups; it's Room Tiles' own - HIDDEN in HA,
  named "<Area> Area Lights (Room Tiles)" - the lights button and the map's room
  marker use it; it's never a board tile.
- Registry area: set to its area when made (it has no device).
- NOT exposed to voice assistants (voice.py) - set in the registry before
  it's added, so an assistant never announces it.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from . import arealights, wording
from .const import DOMAIN
from .ops import SECTION_AREAS
from .voice import is_new, not_exposed, own_defaults


def area_light_id(area_id: str) -> str:
    return f"light.room_tiles_{area_id}_area_lights"


def _old_light_id(area_id: str) -> str:
    """The id area lights had before "_area_lights" (kept data may hold it)."""
    return f"light.room_tiles_{area_id}_lights"


def light_name(area: Any) -> str:
    """Room Tiles' own - never mistaken for the home's "<Area> Lights" group."""
    return wording.t("names.area_lights_entity", area=area.name)


def wanted(area: Any, members: list[str]) -> bool:
    """Make one for this area (now)?"""
    return area.light_entity and not area.hidden and not area.lights and len(members) >= 1


def keep(area: Any, members: list[str]) -> bool:
    """Keep one that was made: while the user wants it and it has lights."""
    return area is not None and area.light_entity and bool(members)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    store = entry.runtime_data
    live: dict[str, AreaLight] = {}
    reg = er.async_get(hass)
    # made before (registry): keep them while their area exists
    for e in er.async_entries_for_config_entry(reg, entry.entry_id):
        if e.domain == "light" and e.unique_id.startswith("area_lights_"):
            live.setdefault(e.unique_id.removeprefix("area_lights_"), None)  # type: ignore[arg-type]

    @callback
    def sync(_sections: tuple[str, ...] | None = None) -> None:
        index = arealights.lights_by_area(hass)
        areas = {a.id: a for a in store.data.areas}
        # the area is gone, the user turned it off, or it has no lights left:
        # none (its tiles / markers go with it, like any deleted entity)
        gone = [a for a in live if not keep(areas.get(a), arealights.resolve(hass, areas[a], index) if a in areas else [])]
        for aid in gone:
            ent = live.pop(aid)
            eid = area_light_id(aid)
            if reg.async_get(eid):
                reg.async_remove(eid)
            elif ent is not None and ent.hass:
                hass.async_create_task(ent.async_remove())
        new: list[AreaLight] = []
        for aid, area in areas.items():
            members = arealights.resolve(hass, area, index)
            ent = live.get(aid)
            if ent is None and (aid in live or wanted(area, members)):
                fresh = is_new(hass, area_light_id(aid))
                ent = live[aid] = AreaLight(aid, light_name(area))
                # in the registry first - hidden (Room Tiles' own, not the
                # home's) - so it can be kept from the voice assistants
                # before they ever see it
                got = reg.async_get_or_create(
                    "light",
                    DOMAIN,
                    ent.unique_id,
                    suggested_object_id=f"room_tiles_{aid}_area_lights",
                    config_entry=entry,
                    hidden_by=er.RegistryEntryHider.INTEGRATION,
                )
                # one registered under the old id moves to the new one (a
                # user's own rename stays)
                if got.entity_id == _old_light_id(aid) and reg.async_get(area_light_id(aid)) is None:
                    reg.async_update_entity(got.entity_id, new_entity_id=area_light_id(aid))
                own_defaults(hass, area_light_id(aid), fresh)
                new.append(ent)
            # Room Tiles never disables its area lights (an old version made
            # some disabled, and HA hands those settings back when the light
            # is made again); one the USER disabled stays
            made = reg.async_get(area_light_id(aid))
            if made is not None and made.disabled_by == er.RegistryEntryDisabler.INTEGRATION:
                reg.async_update_entity(made.entity_id, disabled_by=None)
            if ent is not None:
                ent.set_members(members, light_name(area))
        if new:
            async_add_entities(new)

    sync()
    entry.async_on_unload(store.async_add_listener(lambda sections: SECTION_AREAS in sections and sync()))

    @callback
    def registry_changed(_event: Event) -> None:
        sync()

    for event_type in (er.EVENT_ENTITY_REGISTRY_UPDATED, dr.EVENT_DEVICE_REGISTRY_UPDATED, ar.EVENT_AREA_REGISTRY_UPDATED):
        entry.async_on_unload(hass.bus.async_listen(event_type, registry_changed))


class AreaLight(LightEntity):
    """The area's lights, together."""

    _attr_should_poll = False
    _attr_icon = "mdi:lightbulb-group"

    _attr_entity_registry_visible_default = False  # Room Tiles' own: hidden in HA

    def __init__(self, area_id: str, name: str) -> None:
        self._area = area_id
        self._members: list[str] = []
        self._unsub = None
        self._attr_unique_id = f"area_lights_{area_id}"
        self.entity_id = area_light_id(area_id)
        self._attr_name = name

    @callback
    def set_members(self, members: list[str], name: str) -> None:
        if members == self._members and name == self._attr_name:
            return
        self._members = list(members)
        self._attr_name = name
        if self.hass:
            self._subscribe()
            self.async_write_ha_state()

    def _subscribe(self) -> None:
        if self._unsub:
            self._unsub()
        self._unsub = async_track_state_change_event(self.hass, self._members, self._changed) if self._members else None

    @callback
    def _changed(self, _event: Event) -> None:
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        not_exposed(self.hass, self.entity_id)  # (one made before this rule too)
        self._subscribe()
        # it has no device: it sits in its area (unless the user moved it)
        reg = er.async_get(self.hass)
        entry = reg.async_get(self.entity_id)
        if entry is not None and entry.area_id is None and ar.async_get(self.hass).async_get_area(self._area):
            reg.async_update_entity(self.entity_id, area_id=self._area)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    def _states(self) -> list[Any]:
        return [s for m in self._members if (s := self.hass.states.get(m)) is not None]

    @property
    def available(self) -> bool:
        return bool(self._members)

    @property
    def is_on(self) -> bool:
        return any(s.state == STATE_ON for s in self._states())

    # like HA's light groups: what any of its lights can do
    @property
    def supported_color_modes(self) -> set[ColorMode]:
        modes: set[str] = set()
        for st in self._states():
            modes |= set(st.attributes.get("supported_color_modes") or [])
        out: set[ColorMode] = set()
        if modes & {"hs", "xy", "rgb", "rgbw", "rgbww"}:
            out.add(ColorMode.HS)
        if "color_temp" in modes:
            out.add(ColorMode.COLOR_TEMP)
        if out:
            return out
        return {ColorMode.BRIGHTNESS} if modes - {"onoff"} else {ColorMode.ONOFF}

    def _on(self) -> list[Any]:
        return [s for s in self._states() if s.state == STATE_ON]

    @property
    def color_mode(self) -> ColorMode:
        modes = self.supported_color_modes
        # the mode of its lights that are on (colour beats white), else any
        for st in self._on():
            cm = st.attributes.get("color_mode")
            if cm in ("hs", "xy", "rgb", "rgbw", "rgbww") and ColorMode.HS in modes:
                return ColorMode.HS
            if cm == "color_temp" and ColorMode.COLOR_TEMP in modes:
                return ColorMode.COLOR_TEMP
        for m in (ColorMode.HS, ColorMode.COLOR_TEMP, ColorMode.BRIGHTNESS, ColorMode.ONOFF):
            if m in modes:
                return m
        return ColorMode.ONOFF

    @property
    def brightness(self) -> int | None:
        if self.supported_color_modes == {ColorMode.ONOFF}:
            return None
        on = [s.attributes.get(ATTR_BRIGHTNESS) for s in self._on()]
        on = [b for b in on if isinstance(b, (int, float))]
        return round(sum(on) / len(on)) if on else None

    @property
    def hs_color(self) -> tuple[float, float] | None:
        for st in self._on():
            hs = st.attributes.get("hs_color")
            if isinstance(hs, (list, tuple)) and len(hs) == 2:
                return (float(hs[0]), float(hs[1]))
        return None

    @property
    def color_temp_kelvin(self) -> int | None:
        temps = [st.attributes.get("color_temp_kelvin") for st in self._on()]
        temps = [t for t in temps if isinstance(t, (int, float))]
        return round(sum(temps) / len(temps)) if temps else None

    @property
    def min_color_temp_kelvin(self) -> int:
        lows = [st.attributes.get("min_color_temp_kelvin") for st in self._states()]
        lows = [t for t in lows if isinstance(t, (int, float))]
        return int(min(lows)) if lows else 2000

    @property
    def max_color_temp_kelvin(self) -> int:
        highs = [st.attributes.get("max_color_temp_kelvin") for st in self._states()]
        highs = [t for t in highs if isinstance(t, (int, float))]
        return int(max(highs)) if highs else 6500

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # like HA's light groups: the members (the dashboard shows the groups
        # a light is in from this)
        # own_name: Room Tiles' name for it - HA builds the friendly name its
        # own (instance-configurable) way; the dashboard shows this one
        return {"entity_id": list(self._members), "area": self._area, "own_name": self._attr_name}

    async def async_turn_on(self, **kwargs: Any) -> None:
        if not self._members:
            return
        data: dict[str, Any] = {"entity_id": list(self._members)}
        # brightness and colour go on to its lights, like a light group (HA
        # leaves out what a light can't do)
        for key in (ATTR_BRIGHTNESS, "hs_color", "color_temp_kelvin", "transition"):
            if key in kwargs:
                data[key] = kwargs[key]
        await self.hass.services.async_call("light", "turn_on", data, blocking=True, context=self._context)

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self._members:
            await self.hass.services.async_call(
                "light", "turn_off", {"entity_id": list(self._members)}, blocking=True, context=self._context
            )
