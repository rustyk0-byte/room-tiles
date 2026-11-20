"""Room Tiles actions: import / export the whole setup as a JSON file."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.service import async_register_admin_service

from . import defaults, ops
from .appliances_ha import found_appliances
from .source_device import appliance_source, pool_source
from .backups import prune, unwrap
from .const import BACKUP_DIR, DOMAIN, KIND_APPLIANCE, KIND_SWITCH, KIND_VACUUM, KIND_WATER, LAYOUTS, TILE_KINDS
from .pool import switch_body, switch_keys, switch_name, switch_uid, tile_name
from .model import ModelError, RoomTilesData
from .kinds import infer_kind
from .shortnames import suggest
from .light import area_light_id
from .sync import sync_areas

SERVICE_EXPORT = "export_data"
SERVICE_IMPORT = "import_data"
DEFAULT_FILE = "room_tiles_export.json"

_SCHEMA = vol.Schema(
    {vol.Optional("file", default=DEFAULT_FILE): vol.All(cv.string, str.strip, vol.Length(min=1))}
)


def _config_file(hass: HomeAssistant, name: str) -> Path:
    """A path inside the config folder; anything that escapes it is refused."""
    root = Path(hass.config.config_dir).resolve()
    path = (root / name).resolve()
    if root not in path.parents:
        raise ServiceValidationError(f"'{name}' must be a file inside the config folder")
    return path


def _json_file(hass: HomeAssistant, name: str) -> Path:
    """Export / import: a .json file right in the config folder, or in
    room_tiles_backups/ (its removal and before-import copies) - nowhere
    else: HA's own files (.storage, .cloud, custom_components...) can't be
    overwritten or read."""
    path = _config_file(hass, name)
    if path.suffix.lower() != ".json":
        raise ServiceValidationError(f"'{name}' must be a .json file")
    root = Path(hass.config.config_dir).resolve()
    if path.parent not in (root, root / BACKUP_DIR):
        raise ServiceValidationError(f"'{name}' must be in the config folder itself or in {BACKUP_DIR}/")
    return path


def _write_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _store(hass: HomeAssistant):
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError("Room Tiles is not set up")
    return entries[0].runtime_data


async def _export(call: ServiceCall) -> dict[str, Any]:
    hass = call.hass
    store = _store(hass)
    path = _json_file(hass, call.data["file"])
    await hass.async_add_executor_job(_write_json, path, store.data.as_dict())
    return {"file": str(path)}


async def _import(call: ServiceCall) -> dict[str, Any]:
    """Replace the whole setup with a file's contents. The current data is
    saved to room_tiles_backups/ first; a file that doesn't validate changes
    nothing."""
    hass = call.hass
    store = _store(hass)
    path = _json_file(hass, call.data["file"])

    def read() -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        raw = await hass.async_add_executor_job(read)
    except FileNotFoundError as err:
        raise ServiceValidationError(f"'{call.data['file']}' not found") from err
    except json.JSONDecodeError as err:
        raise ServiceValidationError(f"'{call.data['file']}' is not valid JSON: {err}") from err
    try:
        # (a removal / upgrade copy: HA's storage file, maybe an older
        # version - unwrapped and migrated; an export as it is)
        data = RoomTilesData.from_dict(unwrap(raw))
    except (ModelError, TypeError, ValueError, KeyError) as err:
        raise ServiceValidationError(f"'{call.data['file']}' is not valid Room Tiles data: {err}") from err

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = _config_file(hass, f"{BACKUP_DIR}/before-import-{stamp}.json")
    await hass.async_add_executor_job(_write_json, backup, store.data.as_dict())
    await hass.async_add_executor_job(prune, backup.parent)

    # areas follow HA: names / floors refreshed, areas HA doesn't have dropped,
    # HA areas missing from the file added (hidden unless auto-add is on)
    sync_areas(hass, data)
    # panels follow HA too: one for every panel device there is now (a file
    # from before a panel was added, or another home's, has none for it)
    from . import panels

    panels.sync_panels(data, panels.find_panels(hass))
    ops.flag_short_names(data)
    store.data = data
    store.async_changed()
    from .arealights import resolve_all

    store.area_lights = resolve_all(hass, data)  # the imported areas' light sets
    store.async_notify(("area_lights",))
    return {
        "backup": str(backup),
        "areas": len(data.areas),
        "maps": len(data.maps),
        "markers": len(data.markers),
        "catalog": len(data.catalog.entries),
    }


# ---- edits --------------------------------------------------------------------


def _edit(call: ServiceCall, op) -> Any:
    """Run `op(work_copy)` on a copy of the data; only a copy that still
    validates replaces the live data (a refused edit changes nothing).
    `op` returns its sections, or (sections, result)."""
    store = _store(call.hass)
    work = RoomTilesData.from_dict(store.data.as_dict())
    try:
        out = op(work)
        work.validate()
    except ModelError as err:
        raise ServiceValidationError(str(err)) from err
    sections, result = out if out and isinstance(out[0], tuple) else (out, None)
    if not sections:
        return None  # nothing changed
    store.data = work
    store.async_changed(sections)
    return result


_AREA = {
    vol.Required("area"): cv.string,
    vol.Required("layout"): vol.In(list(LAYOUTS)),
}
_SLOT = vol.All(vol.Coerce(int), vol.Range(min=0))

SET_TILE_SCHEMA = vol.Schema(
    {
        **_AREA,
        vol.Required("slot"): _SLOT,
        vol.Optional("entity"): cv.entity_id,
        vol.Optional("kind"): vol.In(list(TILE_KINDS)),
        vol.Optional("name"): cv.string,
    }
)
CLEAR_TILE_SCHEMA = vol.Schema({**_AREA, vol.Required("slot"): _SLOT})
MOVE_TILE_SCHEMA = vol.Schema({**_AREA, vol.Required("from_slot"): _SLOT, vol.Required("to_slot"): _SLOT})
AUTO_BOARD_SCHEMA = vol.Schema(
    {
        vol.Optional("area"): cv.string,  # none: every area
        vol.Optional("layout"): vol.In(list(LAYOUTS)),  # none: both boards
    }
)
def _finite(v: float) -> float:
    import math

    if not math.isfinite(v):
        raise vol.Invalid("must be a finite number")
    return v


_COORD = vol.All(vol.Coerce(float), _finite)
ADD_MARKER_SCHEMA = vol.Schema(
    {
        vol.Required("map"): cv.string,
        vol.Required("entity"): cv.entity_id,
        vol.Required("x"): _COORD,
        vol.Required("y"): _COORD,
        vol.Optional("layer"): cv.string,
        vol.Optional("show_name", default=False): cv.boolean,
    }
)
UPDATE_MARKER_SCHEMA = vol.Schema(
    {
        vol.Required("marker"): cv.string,
        vol.Optional("map"): cv.string,
        vol.Optional("x"): _COORD,
        vol.Optional("y"): _COORD,
        vol.Optional("layer"): cv.string,
        vol.Optional("show_name"): cv.boolean,
    }
)
REMOVE_MARKER_SCHEMA = vol.Schema({vol.Required("marker"): cv.string})
SET_SHORT_NAME_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Exclusive("area", "target"): cv.string,
            vol.Exclusive("entity", "target"): cv.entity_id,
            vol.Required("short_name"): cv.string,
        }
    ),
    cv.has_at_least_one_key("area", "entity"),
)


async def _set_tile(call: ServiceCall) -> None:
    d = call.data
    _edit(
        call,
        lambda w: ops.set_tile(
            w, d["area"], d["layout"], d["slot"], d.get("entity"), d.get("kind"), d.get("name")
        ),
    )


async def _clear_tile(call: ServiceCall) -> None:
    d = call.data
    _edit(call, lambda w: ops.clear_tile(w, d["area"], d["layout"], d["slot"]))


async def _move_tile(call: ServiceCall) -> None:
    d = call.data
    _edit(call, lambda w: ops.move_tile(w, d["area"], d["layout"], d["from_slot"], d["to_slot"]))


async def _auto_board(call: ServiceCall) -> None:
    """"Auto configure": boards get their automatic tiles again, automatic
    from now on (new appliances / vacuums / pools join them by themselves).
    One board, both of an area's (no layout), or every area's (no area)."""
    d = call.data
    _edit(call, lambda w: tuple(sorted(defaults.auto_board(call.hass, w, d.get("area"), d.get("layout"), found_appliances(call.hass, w)))))


async def _add_marker(call: ServiceCall) -> dict[str, Any]:
    d = call.data
    mid = _edit(
        call,
        lambda w: ops.add_marker(
            w, d["map"], d["entity"], d["x"], d["y"], d.get("layer"), d["show_name"]
        ),
    )
    return {"marker": mid}


async def _update_marker(call: ServiceCall) -> None:
    changes = {k: v for k, v in call.data.items() if k != "marker"}
    _edit(call, lambda w: ops.update_marker(w, call.data["marker"], **changes))


async def _remove_marker(call: ServiceCall) -> None:
    _edit(call, lambda w: ops.remove_marker(w, call.data["marker"]))


SET_AREA_LIGHTS_SCHEMA = vol.Schema(
    {
        vol.Required("area"): cv.string,
        vol.Optional("entity"): vol.Any(None, "", cv.entity_id),
        vol.Optional("exclude"): vol.All(cv.ensure_list, [cv.entity_id]),
    }
)
SET_AREA_LIGHT_ENTITY_SCHEMA = vol.Schema({vol.Required("area"): cv.string, vol.Required("enabled"): cv.boolean})
AREA_LIGHTS_SCHEMA = vol.Schema(
    {
        vol.Required("area"): cv.string,
        vol.Optional("action", default="toggle"): vol.In(["turn_on", "turn_off", "toggle"]),
    }
)


async def _set_area_light_entity(call: ServiceCall) -> None:
    _edit(call, lambda w: ops.set_area_light_entity(w, call.data["area"], call.data["enabled"]))


async def _set_area_lights(call: ServiceCall) -> None:
    d = call.data
    _edit(call, lambda w: ops.set_area_lights(w, d["area"], d.get("entity") or None, d.get("exclude")))
    store = _store(call.hass)
    from .arealights import resolve_all

    store.area_lights = resolve_all(call.hass, store.data)
    store.async_notify(("area_lights",))


async def _area_lights(call: ServiceCall) -> None:
    """Switch an area's lights (its override entity, or every light in the
    area minus the exclusions). Toggle: any on -> all off, else all on."""
    hass = call.hass
    store = _store(hass)
    area = call.data["area"]
    if store.data.area(area) is None:
        raise ServiceValidationError(f"no area '{area}'")
    lights = store.area_lights.get(area, [])
    if not lights:
        raise ServiceValidationError(f"area '{area}' has no lights")
    action = call.data["action"]
    if action == "toggle":
        on = any((st := hass.states.get(e)) is not None and st.state == "on" for e in lights)
        action = "turn_off" if on else "turn_on"
    await hass.services.async_call(
        "homeassistant", action, {"entity_id": lights}, blocking=True, context=call.context
    )


CATALOG_ADD_SCHEMA = vol.Schema(
    {
        vol.Required("entity"): cv.entity_id,
        vol.Optional("kind"): vol.In([k for k in TILE_KINDS if k not in ("blank", "map")]),
        vol.Optional("short_name"): cv.string,
    }
)
CATALOG_REMOVE_SCHEMA = vol.Schema({vol.Required("entity"): cv.entity_id})
SET_AREA_SCHEMA = vol.Schema(
    {
        vol.Required("area"): cv.string,
        vol.Optional("hidden"): cv.boolean,
        vol.Optional("position"): vol.All(vol.Coerce(int), vol.Range(min=0)),
    }
)


def _full_name(hass: HomeAssistant, entity: str) -> str:
    reg = er.async_get(hass).async_get(entity)
    st = hass.states.get(entity)
    own = st.attributes.get("own_name") if st is not None else None
    if reg is not None and reg.platform == DOMAIN and isinstance(own, str) and own:
        return own  # Room Tiles' own: its name, not HA's (the device's name in front)
    if st is not None and st.name:
        return st.name
    return (reg.name or reg.original_name) if reg and (reg.name or reg.original_name) else entity


async def _catalog_add(call: ServiceCall) -> dict[str, Any]:
    """Offer an entity in the tile picker; kind inferred from HA when not given,
    short name suggested from its full name when not given."""
    hass = call.hass
    entity = call.data["entity"]
    kind = call.data.get("kind")
    if kind is None:
        st = hass.states.get(entity)
        kind = infer_kind(entity, dict(st.attributes) if st else None)
        if kind is None:
            raise ServiceValidationError(f"Room Tiles has no tile for '{entity}' - give its kind")
    entry = _edit(
        call,
        lambda w: ops.catalog_add(w, entity, kind, _full_name(hass, entity), call.data.get("short_name")),
    )
    if entry is None:  # already in the catalog: no change
        entry = _store(hass).data.catalog.get(entity)
    return {"entity": entity, "kind": entry.kind, "short_name": entry.short_name, "review": entry.review}


async def _catalog_remove(call: ServiceCall) -> None:
    _edit(call, lambda w: ops.catalog_remove(w, call.data["entity"]))


async def _set_area(call: ServiceCall) -> None:
    d = call.data
    _edit(call, lambda w: ops.set_area(w, d["area"], d.get("hidden"), d.get("position")))
    store = _store(call.hass)
    from .arealights import resolve_all

    store.area_lights = resolve_all(call.hass, store.data)  # hidden areas have none
    store.async_notify(("area_lights",))


SET_MARKERS_SCHEMA = vol.Schema(
    {
        vol.Required("map"): cv.string,
        vol.Required("markers"): [
            vol.Schema(
                {
                    vol.Optional("id"): cv.string,
                    vol.Required("entity"): cv.entity_id,
                    vol.Required("x"): _COORD,
                    vol.Required("y"): _COORD,
                    vol.Optional("layer"): cv.string,
                    vol.Optional("show_name", default=False): cv.boolean,
                },
                extra=vol.REMOVE_EXTRA,
            )
        ],
    }
)


async def _set_markers(call: ServiceCall) -> None:
    _edit(call, lambda w: ops.set_markers(w, call.data["map"], [dict(m) for m in call.data["markers"]]))


SET_MAP_SCHEMA = vol.Schema(
    {
        vol.Required("map"): cv.string,
        # the drawing itself is checked by the model (model.py Map)
        **{vol.Optional(f): object for f in ops.MAP_FIELDS},
    }
)
ADD_MAP_SCHEMA = vol.Schema({vol.Required("name"): cv.string, vol.Optional("ha_floor"): vol.Any(None, cv.string)})
REMOVE_MAP_SCHEMA = vol.Schema({vol.Required("map"): cv.string})
ORDER_MAPS_SCHEMA = vol.Schema({vol.Required("order"): [cv.string]})


async def _set_map(call: ServiceCall) -> None:
    fields = {k: v for k, v in call.data.items() if k != "map"}
    _edit(call, lambda w: ops.set_map(w, call.data["map"], fields))


async def _add_map(call: ServiceCall) -> dict[str, Any]:
    mid = _edit(call, lambda w: ops.add_map(w, call.data["name"], call.data.get("ha_floor")))
    return {"map": mid}


async def _remove_map(call: ServiceCall) -> None:
    _edit(call, lambda w: ops.remove_map(w, call.data["map"]))


async def _order_maps(call: ServiceCall) -> None:
    _edit(call, lambda w: ops.order_maps(w, list(call.data["order"])))


SET_SETTINGS_SCHEMA = vol.Schema(
    {vol.Optional("auto_add_areas"): cv.boolean, vol.Optional("auto_update_panels"): cv.boolean}
)


async def _set_settings(call: ServiceCall) -> None:
    _edit(call, lambda w: ops.set_settings(w, call.data.get("auto_add_areas"), call.data.get("auto_update_panels")))


ACCEPT_SHORT_NAMES_SCHEMA = vol.Schema({vol.Optional("entities"): vol.All(cv.ensure_list, [cv.entity_id])})


async def _accept_short_names(call: ServiceCall) -> dict[str, Any]:
    """Confirm the waiting short names as they are; those too wide stay."""
    left = _edit(call, lambda w: ops.accept_short_names(w, call.data.get("entities")))
    if left is None:  # nothing changed: everything asked for was too wide (or none waited)
        _, left = ops.accept_short_names(RoomTilesData.from_dict(_store(call.hass).data.as_dict()), call.data.get("entities"))
    return {"left": left}


RESET_SHORT_NAMES_SCHEMA = vol.Schema({vol.Optional("entities"): vol.All(cv.ensure_list, [cv.entity_id])})


async def _reset_short_names(call: ServiceCall) -> dict[str, Any]:
    """Catalog entities' short names back to what Room Tiles suggests from
    their full names - as setting up suggests them (an area's lights: its
    lights rule) - every entity's, or just `entities`."""
    data = _store(call.hass).data
    wanted = call.data.get("entities")
    names: dict[str, tuple[str, bool]] = {}
    for e in data.catalog.entries:
        if wanted is not None and e.entity not in wanted:
            continue
        area = next((a for a in data.areas if area_light_id(a.id) == e.entity), None)
        names[e.entity] = (defaults.short_lights(area), False) if area is not None else suggest(_full_name(call.hass, e.entity))
    changed = _edit(call, lambda w: ops.set_short_names(w, names))
    if changed:
        # names left waiting: the review notification again, even for ones
        # that were waiting before (a reset is a fresh look at all of them)
        from .repairs import async_report_review

        async_report_review(call.hass, _store(call.hass).data, set())
    return {"changed": changed or 0}


async def _set_short_name(call: ServiceCall) -> None:
    d = call.data
    _edit(
        call,
        lambda w: ops.set_short_name(w, d["short_name"], area_id=d.get("area"), entity=d.get("entity")),
    )


SUGGEST_SHORT_NAME_SCHEMA = vol.Schema({vol.Optional("area"): cv.string, vol.Optional("entity"): cv.entity_id})


async def _suggest_short_name(call: ServiceCall) -> dict[str, Any]:
    """A short name suggested from the area's / entity's full name now (the
    Short names editor's Suggest) - nothing is stored."""
    d = call.data
    if d.get("area"):
        area = _store(call.hass).data.area(d["area"])
        if area is None:
            raise ServiceValidationError(f"no area '{d['area']}'")
        full = area.name
    elif d.get("entity"):
        full = _full_name(call.hass, d["entity"])
        # an area's lights (Room Tiles' own): the same rule that named them -
        # "<Area> Lights", or the area's short name when that doesn't fit
        data = _store(call.hass).data
        area = next((a for a in data.areas if area_light_id(a.id) == d["entity"]), None)
        if area is not None:
            return {"short_name": defaults.short_lights(area), "review": False, "full_name": full}
    else:
        raise ServiceValidationError("give an area or an entity")
    short, review = suggest(full)
    return {"short_name": short, "review": review, "full_name": full}


SET_APPLIANCE_SCHEMA = vol.Schema({vol.Required("appliance"): dict})
REMOVE_APPLIANCE_SCHEMA = vol.Schema({vol.Required("appliance"): cv.string})
CLEAR_APPLIANCE_SCHEMA = vol.Schema({vol.Required("appliance"): cv.string, vol.Optional("unit"): cv.string})
QUEUE_ACTIONS = ("add", "remove", "move", "clear", "start", "pause", "skip", "stop")
VACUUM_QUEUE_SCHEMA = vol.Schema(
    {
        vol.Required("robot"): cv.string,
        vol.Required("action"): vol.In(QUEUE_ACTIONS),
        vol.Optional("area"): cv.string,
        vol.Optional("index"): vol.Coerce(int),
        vol.Optional("start", default=False): cv.boolean,
    }
)


async def _vacuum_queue(call: ServiceCall) -> None:
    """A robot vacuum's room queue: add / remove / move an area, clear,
    start / pause / skip (the next room) / stop (and clear)."""
    d = call.data
    ent = _store(call.hass).robot_entities.get(d["robot"])
    if ent is None:
        raise ServiceValidationError(f"no robot vacuum '{d['robot']}'")
    if d["action"] in ("add", "remove", "move") and not d.get("area"):
        raise ServiceValidationError("an area is needed")
    await ent.queue_action(d["action"], d.get("area"), d.get("index"), d["start"])


def _place_new(hass: HomeAssistant, w: RoomTilesData, new: list, ask: list[str]) -> set[str]:
    """A new appliance / vacuum / pool tile onto its area's automatic boards
    (defaults.place_new); `ask` gets the areas whose own boards lack it."""
    sections, areas = defaults.place_new(hass, w, new, found_appliances(hass, w))
    ask[:] = areas
    return sections


def _appliance_entity(hass: HomeAssistant, appliance_id: str) -> str:
    """The appliance's sensor entity id (registered, else the one it'll get)."""
    found = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"appliance_{appliance_id}")
    return found or f"sensor.room_tiles_{appliance_id}"


async def _set_appliance(call: ServiceCall) -> dict[str, Any]:
    """Add / replace an appliance profile; a new one is offered in the tile
    picker at once."""
    ap = dict(call.data["appliance"])
    entity = _appliance_entity(call.hass, str(ap.get("id", "")))

    ask: list[str] = []

    def op(w):
        is_new = not any(a.id == ap.get("id") for a in w.appliances)
        before = next((a.name for a in w.appliances if a.id == ap.get("id")), None)
        sections = set(ops.set_appliance(w, ap))
        ops.unignore(w, ops.device_keys("appliance", ap))
        name = str(ap.get("name") or entity)
        added, _entry = ops.catalog_add(w, entity, KIND_APPLIANCE, name)
        renamed = ops.follow_appliance_name(w, entity, before, name)
        if is_new:
            made = next(a for a in w.appliances if a.id == ap.get("id"))
            sections |= _place_new(call.hass, w, [((entity, KIND_APPLIANCE, name, False), appliance_source(made))], ask)
        return tuple(sorted(sections | set(added) | set(renamed)))

    _edit(call, op)
    return {"entity": entity, "ask": ask}


async def _remove_appliance(call: ServiceCall) -> None:
    _edit(call, lambda w: ops.remove_appliance(w, call.data["appliance"]))


async def _clear_appliance(call: ServiceCall) -> None:
    """A tap on a finished appliance: it's been emptied."""
    ent = _store(call.hass).appliance_entities.get(call.data["appliance"])
    if ent is None:
        raise ServiceValidationError(f"no appliance '{call.data['appliance']}'")
    ent.clear(call.data.get("unit"))


COMBINE_APPLIANCES_SCHEMA = vol.Schema(
    {vol.Required("appliance"): cv.string, vol.Required("with"): cv.string, vol.Optional("name"): cv.string}
)
SPLIT_APPLIANCE_SCHEMA = vol.Schema({vol.Required("appliance"): cv.string, vol.Required("unit"): cv.string})


async def _combine_appliances(call: ServiceCall) -> None:
    """Two single appliances on one tile (the first on top)."""
    d = call.data
    ids = (d["appliance"], d["with"])
    entities = {i: _appliance_entity(call.hass, i) for i in ids}
    _edit(call, lambda w: ops.combine_appliances(w, ids[0], ids[1], entities, d.get("name")))


async def _split_appliance(call: ServiceCall) -> dict[str, Any]:
    """One unit of a two-unit appliance gets its own tile (offered in the
    tile picker at once)."""
    d = call.data

    def op(w):
        sections, new_id = ops.split_appliance(w, d["appliance"], d["unit"])
        ap = next(a for a in w.appliances if a.id == new_id)
        added, _e = ops.catalog_add(w, _appliance_entity(call.hass, new_id), KIND_APPLIANCE, ap.name)
        return tuple(sorted(set(sections) | set(added))), new_id

    new_id = _edit(call, op)
    return {"appliance": new_id, "entity": _appliance_entity(call.hass, new_id)}


SET_POOL_SCHEMA = vol.Schema({vol.Required("pool"): dict})
REMOVE_POOL_SCHEMA = vol.Schema({vol.Required("pool"): cv.string})
POOL_TARGET_SCHEMA = vol.Schema({vol.Required("entity"): cv.entity_id, vol.Required("temperature"): _COORD})
POOL_HEATER_SCHEMA = vol.Schema({vol.Required("entity"): cv.entity_id, vol.Required("heater"): cv.boolean})
POOL_ON_SCHEMA = vol.Schema(
    {vol.Required("entity"): cv.entity_id, vol.Required("on"): cv.boolean, vol.Optional("with_heater"): cv.boolean}
)


def _switch_entity(hass: HomeAssistant, pool_id: str, key: str) -> str:
    uid = switch_uid(pool_id, key)
    return er.async_get(hass).async_get_entity_id("switch", DOMAIN, uid) or f"switch.room_tiles_{uid[5:]}"


def _pool_entity(hass: HomeAssistant, pool_id: str, body: str | None) -> str:
    uid = f"pool_{pool_id}" + (f"_{body}" if body else "")
    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, uid) or f"sensor.room_tiles_{uid[5:]}"


async def _set_pool(call: ServiceCall) -> dict[str, Any]:
    """Add / replace a pool / spa system; new ones offer their tiles in the
    tile picker at once (Pool and / or Spa; shared: Pool / Spa + Spa Mode)."""
    d = dict(call.data["pool"])

    ask: list[str] = []

    def op(w):
        is_new = not any(p.id == d.get("id") for p in w.pools)
        sections = set(ops.set_pool(w, d))
        ops.unignore(w, ops.device_keys("pool", d))
        ps = next(p for p in w.pools if p.id == d.get("id"))
        new = []
        for body in ps.tiles():
            eid = _pool_entity(call.hass, ps.id, body)
            added, _e = ops.catalog_add(w, eid, KIND_WATER, tile_name(body))
            sections |= set(added)
            new.append(((eid, KIND_WATER, tile_name(body), False), pool_source(ps, body)))
        for key in switch_keys(ps):
            eid = _switch_entity(call.hass, ps.id, key)
            added, _e = ops.catalog_add(w, eid, KIND_SWITCH, switch_name(key))
            sections |= set(added)
            new.append(((eid, KIND_SWITCH, switch_name(key), False), pool_source(ps, switch_body(key))))
        if is_new:
            sections |= _place_new(call.hass, w, new, ask)
        return tuple(sorted(sections))

    _edit(call, op)
    return {"pool": d.get("id"), "ask": ask}


async def _remove_pool(call: ServiceCall) -> None:
    _edit(call, lambda w: ops.remove_pool(w, call.data["pool"]))


def _pool_target(call: ServiceCall):
    """(runtime, body) for the entity a pool action names; refused while the
    system is switching or offline (a set point could land on the wrong body)."""
    found = _store(call.hass).pool_entities.get(call.data["entity"])
    if found is None:
        raise ServiceValidationError(f"{call.data['entity']} is not a Room Tiles pool / spa sensor")
    rt, body = found
    body = rt.body_for(body)
    state = rt.views.get(body, {}).get("state")
    if state in ("switching", "offline"):
        raise ServiceValidationError(f"The {body} is {state} - try again in a moment")
    return rt, body


async def _pool_set_target(call: ServiceCall) -> None:
    rt, body = _pool_target(call)
    heater = getattr(rt.ps, body).heater
    if not heater:
        raise ServiceValidationError(f"The {body} has no heater set up")
    await call.hass.services.async_call(
        "climate", "set_temperature", {"entity_id": heater, "temperature": call.data["temperature"]}, blocking=True
    )


def _heater_pump(ps, body: str) -> str | None:
    """The pump a body's heater needs running (shared: the system's pump)."""
    return ps.pump if ps.layout == "shared" else getattr(ps, body).pump


async def _heater_on(hass: HomeAssistant, rt, body: str) -> None:
    """Turn a body's heater on, in its last mode (heat / cool:
    PoolRuntime.heater_next) - and its pump, when that body's setting says
    so (a heater does nothing without water flowing). A pump that was OFF
    and started here is remembered (`rt.started_pumps`) so turning the spa
    off can stop it again; one already running is never touched."""
    ps = rt.ps
    b = getattr(ps, body)
    pump = _heater_pump(ps, body)
    if b.pump_with_heater and pump:
        st = hass.states.get(pump)
        if st is None or st.state != "on":
            await hass.services.async_call(pump.split(".")[0], "turn_on", {"entity_id": pump}, blocking=True)
            rt.started_pumps.add(pump)
    await hass.services.async_call("climate", "set_hvac_mode", {"entity_id": b.heater, "hvac_mode": rt.heater_next(body)}, blocking=True)


async def _pool_set_heater(call: ServiceCall) -> None:
    rt, body = _pool_target(call)
    await async_pool_heater(call.hass, rt, body, call.data["heater"])


async def async_pool_heater(hass: HomeAssistant, rt, body: str, on: bool) -> None:
    """A body's heater on (its pump first, per its setting) / off - the water
    tile's heater button (pool_set_heater)."""
    heater = getattr(rt.ps, body).heater
    if not heater:
        raise ServiceValidationError(f"The {body} has no heater set up")
    # shown as on its way until HA reports it (controllers can take minutes)
    rt.ask_heater(body, on)
    try:
        if on:
            await _heater_on(hass, rt, body)
        else:
            await hass.services.async_call("climate", "set_hvac_mode", {"entity_id": heater, "hvac_mode": "off"}, blocking=True)
    except Exception:
        rt.heater_asked.pop(body, None)  # (refused: nothing on its way)
        rt.refresh()
        raise


async def _pool_set_on(call: ServiceCall) -> None:
    rt, body = _pool_target(call)
    await async_pool_on(call.hass, rt, body, call.data["on"], call.data.get("with_heater"))


async def async_pool_on(hass: HomeAssistant, rt, body: str, on: bool, with_heater: bool | None = None) -> None:
    """A body on / off. Shared: the spa on = spa mode, off = back to the pool;
    the pool on = pool mode (and the pump on), off = the pump off. Separate /
    one body: that body's pump. Its heater follows when `with_heater` - by
    default for the spa, when its "turning the spa on heats it" setting is on.
    (Also the Spa Mode switch's action - switch.py.)"""
    ps = rt.ps

    async def switch(entity: str | None, turn_on: bool) -> None:
        if not entity:
            raise ServiceValidationError(f"The {body} has no pump / mode switch set up")
        service = "turn_on" if turn_on else "turn_off"
        await hass.services.async_call(entity.split(".")[0], service, {"entity_id": entity}, blocking=True)

    if ps.layout == "shared":
        if body == "spa":
            await switch(ps.spa_mode, on)
        elif on:
            await switch(ps.spa_mode, False)
            await switch(ps.pump, True)
        else:
            await switch(ps.pump, False)
    else:
        await switch(getattr(ps, body).pump, on)
    # its heater follows - on with it, off when it goes off (so it doesn't
    # heat next time by surprise): asked for, or the spa's setting
    heater = getattr(ps, body).heater
    follows = with_heater if with_heater is not None else (body == "spa" and ps.spa_heater_follows)
    if follows and heater:
        if on:
            await _heater_on(hass, rt, body)
        else:
            await hass.services.async_call("climate", "set_hvac_mode", {"entity_id": heater, "hvac_mode": "off"}, blocking=True)
            # the pump goes off with it - only if turning it on started it
            pump = _heater_pump(ps, body)
            if pump and pump in rt.started_pumps:
                rt.started_pumps.discard(pump)
                await switch(pump, False)


SET_ROBOT_SCHEMA = vol.Schema({vol.Required("robot"): dict})
REMOVE_ROBOT_SCHEMA = vol.Schema({vol.Required("robot"): cv.string})


async def _set_robot(call: ServiceCall) -> dict[str, Any]:
    """Add / replace a robot vacuum profile; a new one is offered in the
    tile picker at once."""
    d = dict(call.data["robot"])
    for k in ("notes", "clean_area"):
        d.pop(k, None)
    entity = er.async_get(call.hass).async_get_entity_id("sensor", DOMAIN, f"robot_{d.get('id')}") or f"sensor.room_tiles_{d.get('id')}"

    ask: list[str] = []

    def op(w):
        is_new = not any(r.id == d.get("id") for r in w.robots)
        sections = set(ops.set_robot(w, d))
        ops.unignore(w, ops.device_keys("robot", d))
        name = str(d.get("name") or entity)
        added, _e = ops.catalog_add(w, entity, KIND_VACUUM, name)
        if is_new:
            sections |= _place_new(call.hass, w, [((entity, KIND_VACUUM, name, False), d.get("vacuum"))], ask)
        return tuple(sorted(sections | set(added)))

    _edit(call, op)
    return {"entity": entity, "ask": ask}


async def _remove_robot(call: ServiceCall) -> None:
    _edit(call, lambda w: ops.remove_robot(w, call.data["robot"]))


IGNORE_SCHEMA = vol.Schema(
    {
        vol.Required("kind"): vol.In(["appliance", "pool", "robot"]),
        vol.Required("device"): dict,
        vol.Optional("set_up_id"): cv.string,
    }
)


async def _ignore_device(call: ServiceCall) -> None:
    """Ignore a found device (or one that's set up - it leaves Room Tiles);
    it waits under Ignored on the Appliances page."""
    d = call.data
    _edit(call, lambda w: ops.ignore_device(w, d["kind"], ops.device_keys(d["kind"], d["device"]), d.get("set_up_id")))


def async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_EXPORT):
        return
    optional = SupportsResponse.OPTIONAL
    # export / import write and replace files: admins only (the setup edits
    # below are every user's, as on the dashboard)
    for name, handler in ((SERVICE_EXPORT, _export), (SERVICE_IMPORT, _import)):
        async_register_admin_service(hass, DOMAIN, name, handler, _SCHEMA, optional)
    for name, handler, schema, response in (
        ("set_tile", _set_tile, SET_TILE_SCHEMA, SupportsResponse.NONE),
        ("clear_tile", _clear_tile, CLEAR_TILE_SCHEMA, SupportsResponse.NONE),
        ("move_tile", _move_tile, MOVE_TILE_SCHEMA, SupportsResponse.NONE),
        ("auto_board", _auto_board, AUTO_BOARD_SCHEMA, SupportsResponse.NONE),
        ("add_marker", _add_marker, ADD_MARKER_SCHEMA, optional),
        ("update_marker", _update_marker, UPDATE_MARKER_SCHEMA, SupportsResponse.NONE),
        ("remove_marker", _remove_marker, REMOVE_MARKER_SCHEMA, SupportsResponse.NONE),
        ("set_short_name", _set_short_name, SET_SHORT_NAME_SCHEMA, SupportsResponse.NONE),
        ("reset_short_names", _reset_short_names, RESET_SHORT_NAMES_SCHEMA, SupportsResponse.OPTIONAL),
        ("suggest_short_name", _suggest_short_name, SUGGEST_SHORT_NAME_SCHEMA, SupportsResponse.ONLY),
        ("accept_short_names", _accept_short_names, ACCEPT_SHORT_NAMES_SCHEMA, SupportsResponse.OPTIONAL),
        ("set_area_lights", _set_area_lights, SET_AREA_LIGHTS_SCHEMA, SupportsResponse.NONE),
        ("area_lights", _area_lights, AREA_LIGHTS_SCHEMA, SupportsResponse.NONE),
        ("set_area_light_entity", _set_area_light_entity, SET_AREA_LIGHT_ENTITY_SCHEMA, SupportsResponse.NONE),
        ("catalog_add", _catalog_add, CATALOG_ADD_SCHEMA, optional),
        ("catalog_remove", _catalog_remove, CATALOG_REMOVE_SCHEMA, SupportsResponse.NONE),
        ("set_area", _set_area, SET_AREA_SCHEMA, SupportsResponse.NONE),
        ("set_settings", _set_settings, SET_SETTINGS_SCHEMA, SupportsResponse.NONE),
        ("set_markers", _set_markers, SET_MARKERS_SCHEMA, SupportsResponse.NONE),
        ("set_map", _set_map, SET_MAP_SCHEMA, SupportsResponse.NONE),
        ("add_map", _add_map, ADD_MAP_SCHEMA, optional),
        ("remove_map", _remove_map, REMOVE_MAP_SCHEMA, SupportsResponse.NONE),
        ("order_maps", _order_maps, ORDER_MAPS_SCHEMA, SupportsResponse.NONE),
        ("set_appliance", _set_appliance, SET_APPLIANCE_SCHEMA, optional),
        ("remove_appliance", _remove_appliance, REMOVE_APPLIANCE_SCHEMA, SupportsResponse.NONE),
        ("clear_appliance", _clear_appliance, CLEAR_APPLIANCE_SCHEMA, SupportsResponse.NONE),
        ("vacuum_queue", _vacuum_queue, VACUUM_QUEUE_SCHEMA, SupportsResponse.NONE),
        ("combine_appliances", _combine_appliances, COMBINE_APPLIANCES_SCHEMA, SupportsResponse.NONE),
        ("split_appliance", _split_appliance, SPLIT_APPLIANCE_SCHEMA, optional),
        ("set_pool", _set_pool, SET_POOL_SCHEMA, optional),
        ("remove_pool", _remove_pool, REMOVE_POOL_SCHEMA, SupportsResponse.NONE),
        ("pool_set_target", _pool_set_target, POOL_TARGET_SCHEMA, SupportsResponse.NONE),
        ("pool_set_heater", _pool_set_heater, POOL_HEATER_SCHEMA, SupportsResponse.NONE),
        ("pool_set_on", _pool_set_on, POOL_ON_SCHEMA, SupportsResponse.NONE),
        ("set_robot", _set_robot, SET_ROBOT_SCHEMA, optional),
        ("remove_robot", _remove_robot, REMOVE_ROBOT_SCHEMA, SupportsResponse.NONE),
        ("ignore_device", _ignore_device, IGNORE_SCHEMA, SupportsResponse.NONE),
    ):
        hass.services.async_register(DOMAIN, name, handler, schema=schema, supports_response=response)
