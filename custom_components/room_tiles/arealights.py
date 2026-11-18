"""Area Lights: which lights an area's lights button switches.

Worked out live from HA's registries (nothing is stored but the exceptions):
every light in the HA area - its own area, or its device's - except what HA
itself leaves out of area targeting (hidden, disabled, config / diagnostic
entities) and the area's `lights_exclude`. An area with an override
(`lights`) switches just that entity, while it exists.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .model import Area, RoomTilesData


def is_light_group(hass: HomeAssistant, e: er.RegistryEntry) -> bool:
    """A light that is a group of other lights (HA's light groups, a hub's
    groups - they list their members in `entity_id`)."""
    if e.platform == "group":
        return True
    st = hass.states.get(e.entity_id)
    return st is not None and isinstance(st.attributes.get("entity_id"), list)


def is_display_backlight(e: er.RegistryEntry) -> bool:
    """A screen's backlight (a wall panel's, a display's) - a light entity,
    never a room's light: switching it off blanks the panel."""
    names = (e.entity_id, e.original_name or "", e.name or "")
    return any("backlight" in n.lower() for n in names)


def lights_by_area(hass: HomeAssistant) -> dict[str, list[str]]:
    """HA area id -> its INDIVIDUAL lights (before Room Tiles' exclusions):
    no light groups - they only repeat lights already here - not Room Tiles'
    own area lights (light.py), which ARE these lights, and no screens'
    backlights."""
    devices = dr.async_get(hass)
    out: dict[str, list[str]] = {}
    for e in er.async_get(hass).entities.values():
        if e.domain != "light" or e.platform == DOMAIN or e.disabled_by or e.hidden_by or e.entity_category:
            continue
        if is_light_group(hass, e) or is_display_backlight(e):
            continue
        area = e.area_id
        if area is None and e.device_id:
            dev = devices.async_get(e.device_id)
            area = dev.area_id if dev else None
        if area:
            out.setdefault(area, []).append(e.entity_id)
    for v in out.values():
        v.sort()
    return out


def entity_exists(hass: HomeAssistant, entity_id: str) -> bool:
    return er.async_get(hass).async_get(entity_id) is not None or hass.states.get(entity_id) is not None


def resolve(hass: HomeAssistant, area: Area, index: dict[str, list[str]]) -> list[str]:
    """What the area's lights button switches: one entity (the override),
    its ticked individual lights, or nothing ("None": `light_entity` off)."""
    if area.lights and entity_exists(hass, area.lights):
        return [area.lights]
    if not area.light_entity:
        return []  # "None": no lights button for this area
    excluded = set(area.lights_exclude)
    return [e for e in index.get(area.id, []) if e not in excluded]


def resolve_all(hass: HomeAssistant, data: RoomTilesData) -> dict[str, list[str]]:
    index = lights_by_area(hass)
    return {a.id: resolve(hass, a, index) for a in data.areas if not a.hidden}


def prune(hass: HomeAssistant, data: RoomTilesData, gone: frozenset[str] = frozenset()) -> list[str]:
    """Drop exclusions of lights no longer in the area (moved / deleted - a
    light moved back later is included again) and overrides whose entity is
    gone (the area falls back to all its lights). `gone`: entities just
    removed from the registry - their state can outlive the remove event.
    Returns the areas whose override was dropped."""
    index = lights_by_area(hass)
    dropped: list[str] = []
    for a in data.areas:
        here = set(index.get(a.id, []))
        kept = [e for e in a.lights_exclude if e in here]
        if kept != a.lights_exclude:
            a.lights_exclude = kept
        if a.lights and (a.lights in gone or not entity_exists(hass, a.lights)):
            dropped.append(f"{a.name} ({a.lights})")
            a.lights = None
    return dropped
