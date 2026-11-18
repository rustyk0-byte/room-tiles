"""Keep Room Tiles' areas in step with HA's area registry.

A Room Tiles area IS an HA area. On setup and on every area-registry change:
- names and floors are refreshed from HA;
- areas deleted in HA are removed (their map zones are unlinked);
- new HA areas are added - visible if "include new areas automatically" is on
  (or, on first setup, if the user ticked them), otherwise hidden.
A brand-new install also gets generated maps (one per floor, a square per
visible area).
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import floor_registry as fr

from .mapgen import AreaInfo, FloorInfo, add_area_zone, generate_maps
from .model import Area, RoomTilesData
from .shortnames import suggest


def ha_areas_and_floors(hass: HomeAssistant) -> tuple[list[AreaInfo], list[FloorInfo]]:
    """HA's areas (sorted by floor then name) and floors."""
    floors = [
        FloorInfo(id=f.floor_id, name=f.name, level=f.level)
        for f in fr.async_get(hass).async_list_floors()
    ]
    areas = sorted(
        (
            AreaInfo(id=a.id, name=a.name, floor=a.floor_id)
            for a in ar.async_get(hass).async_list_areas()
        ),
        key=lambda a: (a.floor or "￿", a.name.lower()),
    )
    return areas, floors


def sync_areas(
    hass: HomeAssistant,
    data: RoomTilesData,
    first_setup: dict | None = None,
) -> bool:
    """Bring data.areas in line with HA. `first_setup` = the config flow's
    choices ({"areas": [ids], "auto_add_areas": bool}), used only when the
    document has no areas yet. Returns True if anything changed."""
    changed = False
    ha_areas, floors = ha_areas_and_floors(hass)
    by_id = {a.id: a for a in ha_areas}

    fresh = not data.areas
    if fresh and first_setup is not None:
        data.settings.auto_add_areas = bool(first_setup.get("auto_add_areas", False))
        chosen = set(first_setup.get("areas") or by_id)
        changed = True
    else:
        chosen = None

    # removed in HA
    gone = {a.id for a in data.areas if a.id not in by_id}
    if gone:
        data.areas = [a for a in data.areas if a.id not in gone]
        for m in data.maps:
            for z in m.zones:
                if z.area in gone:
                    z.area = None
        changed = True

    # renamed / moved to another floor
    for a in data.areas:
        h = by_id[a.id]
        if (a.name, a.floor) != (h.name, h.floor):
            if a.name != h.name and a.short_name == suggest(a.name)[0]:
                # the short name was the automatic one: follow the rename
                a.short_name, a.review = suggest(h.name)
            a.name, a.floor = h.name, h.floor
            changed = True

    # new in HA
    known = {a.id for a in data.areas}
    added: list[Area] = []
    for h in ha_areas:
        if h.id in known:
            continue
        if chosen is not None:
            visible = h.id in chosen
        else:
            visible = fresh or data.settings.auto_add_areas
        area = Area(id=h.id, name=h.name, floor=h.floor, hidden=not visible)
        data.areas.append(area)
        added.append(area)
        changed = True

    if not data.maps:
        visible = [AreaInfo(a.id, a.name, a.floor) for a in data.areas if not a.hidden]
        data.maps = generate_maps(visible, floors)
        changed = True
    else:
        # a new visible area gets a square on its floor's generated map
        for area in added:
            if area.hidden:
                continue
            target = next(
                (m for m in data.maps if m.generated and m.ha_floor == area.floor), None
            )
            if target is not None:
                add_area_zone(target, AreaInfo(area.id, area.name, area.floor))
    return changed
