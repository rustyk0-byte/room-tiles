"""Room Tiles data model.

Everything Room Tiles knows lives in one JSON document (store.py):

    {
      "areas":   [Area, ...],    # panel areas, in picker order
      "maps":    [Map, ...],     # floors / yards, in selector order
      "markers": [Marker, ...],  # entity icons placed on maps
      "catalog": Catalog,        # which entities can become tiles
      "appliances": [Appliance, ...],  # appliance profiles (their tile sensors)
      "pools": [PoolSystem, ...],      # pool / spa profiles (their tile sensors)
      "robots": [RobotProfile, ...],   # robot vacuum profiles (their tile sensors)
    }

Design rules (see the project plan):
- A map is always present. Without a drawn plan, maps are generated: one per
  HA floor, a square zone per area (mapgen.py).
- Markers belong to a MAP, not to a view; zooming is a camera over the map.
- Zones link to HA areas; that link drives "open this area's map" and the
  tile editor's filter (no floor-plan bitmasks).
- Coordinates are in the map's own units (its `bounds`), never screen pixels.

This module is pure Python (no Home Assistant imports) so it can be tested
and reused by tools without a running HA.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import wording
from .appliance import APPLIANCE_TYPES
from .const import (
    KIND_BLANK,
    MAX_SHORT_NAME,
    LAYOUTS,
    NO_ENTITY_KINDS,
    SHAPE_STYLES,
    TILE_KINDS,
)


class ModelError(ValueError):
    """Raised for data that doesn't fit the schema."""


def _req(d: dict[str, Any], key: str, typ: type | tuple[type, ...]) -> Any:
    if key not in d:
        raise ModelError(f"missing '{key}'")
    v = d[key]
    if not isinstance(v, typ):
        raise ModelError(f"'{key}' has the wrong type")
    return v


def _pt(v: Any) -> tuple[float, float]:
    if not (isinstance(v, (list, tuple)) and len(v) == 2):
        raise ModelError("a point must be [x, y]")
    return (float(v[0]), float(v[1]))


def _short(v: Any, what: str, required: bool = True) -> str | None:
    """A short name: what tiles and the map show. At most MAX_SHORT_NAME
    characters (shortnames.py also checks the pixel width, as a review flag)."""
    if v is None or v == "":
        if required:
            raise ModelError(f"{what} needs a short name")
        return None
    if not isinstance(v, str):
        raise ModelError(f"{what}: short name must be text")
    v = " ".join(v.split())
    if len(v) > MAX_SHORT_NAME:
        raise ModelError(f"{what}: short name '{v}' is longer than {MAX_SHORT_NAME} characters")
    return v


def _pts(v: Any, minimum: int) -> list[tuple[float, float]]:
    if not isinstance(v, list) or len(v) < minimum:
        raise ModelError(f"need at least {minimum} points")
    return [_pt(p) for p in v]


# ---- tiles --------------------------------------------------------------------


@dataclass
class Tile:
    """One grid cell. `entity` is None for kinds without an entity.
    `name`: this tile's own short name, overriding the catalog's (None = use
    the catalog entry's short name; "Map" for a map tile)."""

    kind: str = KIND_BLANK
    entity: str | None = None
    name: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Tile:
        if d is None:
            return cls()
        kind = _req(d, "kind", str)
        if kind not in TILE_KINDS:
            raise ModelError(f"unknown tile kind '{kind}'")
        entity = d.get("entity")
        if kind not in NO_ENTITY_KINDS and not entity:
            raise ModelError(f"a '{kind}' tile needs an entity")
        return cls(
            kind=kind,
            entity=entity or None,
            name=_short(d.get("name"), f"tile {entity or kind}", required=False),
        )

    def as_dict(self) -> dict[str, Any] | None:
        if self.kind == KIND_BLANK:
            return None
        out: dict[str, Any] = {"kind": self.kind}
        if self.entity:
            out["entity"] = self.entity
        if self.name:
            out["name"] = self.name
        return out


# ---- areas --------------------------------------------------------------------


@dataclass
class Area:
    """A Room Tiles area. It IS an HA area: `id` is the HA area id, and `name`
    and `floor` are copies of HA's, kept in sync by the integration (sync.py)
    so exports and clients don't need the registry.

    `short_name`: what tiles / the map / panel headers show (<= 15 chars);
    `review`: it was shortened automatically and the user hasn't confirmed it.
    `hidden`: not shown in Room Tiles (an HA area the user unticked); its tiles
    are kept so ticking it again restores them.
    `lights`: Area Lights OVERRIDE - one entity (e.g. a light group) the area's
    lights button switches. None (the default) = every light in the HA area
    (worked out live by the integration, arealights.py) minus
    `lights_exclude`.
    `tiles`: one list per layout, always exactly LAYOUTS[layout] long.
    `filled`: its default tiles were worked out (defaults.py) - done once, so
    a board the user empties stays empty.
    `layout`: the layout a device starts the area on until it picks its own
    (None: 5x2) - 6x3 when its default tiles don't fit on 5x2.
    `edited`: the layouts whose board the user changed (a tile set, cleared or
    moved). A board not in it is still the automatic one: a new appliance,
    vacuum or pool tile is added to it by itself (defaults.place_new).
    `light_entity`: Room Tiles may make its "<Area> Lights" light for the area
    (light.py) - off: the user doesn't want one (none is made / it's removed).
    """

    id: str
    name: str
    floor: str | None = None
    short_name: str = ""
    review: bool = False
    hidden: bool = False
    lights: str | None = None
    lights_exclude: list[str] = field(default_factory=list)
    tiles: dict[str, list[Tile]] = field(default_factory=dict)
    filled: bool = False
    light_entity: bool = True
    layout: str | None = None
    edited: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for layout, count in LAYOUTS.items():
            grid = self.tiles.get(layout, [])
            grid = (grid + [Tile() for _ in range(count)])[:count]
            self.tiles[layout] = grid
        if not self.short_name:
            from .shortnames import suggest  # local: model stays import-light

            self.short_name, self.review = suggest(self.name)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Area:
        tiles_in = d.get("tiles") or {}
        tiles: dict[str, list[Tile]] = {}
        for layout in LAYOUTS:
            tiles[layout] = [Tile.from_dict(t) for t in tiles_in.get(layout, [])]
        return cls(
            id=_req(d, "id", str),
            name=_req(d, "name", str),
            floor=d.get("floor"),
            short_name=_short(d.get("short_name"), f"area {d.get('id')}", required=False) or "",
            review=bool(d.get("review", False)),
            hidden=bool(d.get("hidden", False)),
            lights=d.get("lights"),
            lights_exclude=[str(x) for x in d.get("lights_exclude") or []],
            tiles=tiles,
            filled=bool(d.get("filled", False)),
            light_entity=bool(d.get("light_entity", True)),
            layout=d.get("layout") if d.get("layout") in LAYOUTS else None,
            edited=[x for x in LAYOUTS if x in (d.get("edited") or [])],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "floor": self.floor,
            "short_name": self.short_name,
            "review": self.review,
            "hidden": self.hidden,
            "lights": self.lights,
            "lights_exclude": list(self.lights_exclude),
            "tiles": {
                layout: [t.as_dict() for t in grid] for layout, grid in self.tiles.items()
            },
            "filled": self.filled,
            "light_entity": self.light_entity,
            "layout": self.layout,
            "edited": list(self.edited),
        }


# ---- maps ---------------------------------------------------------------------


@dataclass
class Zone:
    """A room or outdoor space on a map. `area` links to a panel area id.

    A VACUUM ZONE (`vacuum` = a vacuum entity id) is only drawn on that
    vacuum's view of the map: a piece of the floor the vacuum cleans on its
    own (e.g. "Bar" inside the Living Room), linked to the HA area its
    segment is mapped to. Ordinary rooms count for every vacuum whose segments
    are mapped to their area; vacuum zones add / refine on top (the smaller
    zone wins where they overlap)."""

    id: str
    name: str
    points: list[tuple[float, float]]
    area: str | None = None
    label: tuple[float, float] | None = None
    outdoor: bool = False
    vacuum: str | None = None
    label_vertical: bool = False  # the name reads bottom to top (narrow rooms)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Zone:
        return cls(
            id=_req(d, "id", str),
            name=_req(d, "name", str),
            points=_pts(d.get("points"), 3),
            area=d.get("area"),
            label=_pt(d["label"]) if d.get("label") is not None else None,
            outdoor=bool(d.get("outdoor", False)),
            vacuum=_vacuum(d.get("vacuum")),
            label_vertical=bool(d.get("label_vertical", False)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "points": [list(p) for p in self.points],
            "area": self.area,
            "label": list(self.label) if self.label else None,
            "outdoor": self.outdoor,
            "vacuum": self.vacuum,
            "label_vertical": self.label_vertical,
        }


def _vacuum(v: Any) -> str | None:
    if v in (None, ""):
        return None
    if not (isinstance(v, str) and v.startswith("vacuum.")):
        raise ModelError(f"'{v}' is not a vacuum entity")
    return v


@dataclass
class Shape:
    """A filled polygon: floor, water (pool), grass, deck, paving."""

    style: str
    points: list[tuple[float, float]]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Shape:
        style = _req(d, "style", str)
        if style not in SHAPE_STYLES:
            raise ModelError(f"unknown shape style '{style}'")
        return cls(style=style, points=_pts(d.get("points"), 3))

    def as_dict(self) -> dict[str, Any]:
        return {"style": self.style, "points": [list(p) for p in self.points]}


@dataclass
class Link:
    """A tappable spot that jumps to another map (stairs, a yard door)."""

    to: str
    at: tuple[float, float]
    label: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Link:
        return cls(to=_req(d, "to", str), at=_pt(d.get("at")), label=str(d.get("label", "")))

    def as_dict(self) -> dict[str, Any]:
        return {"to": self.to, "at": list(self.at), "label": self.label}


@dataclass
class Layer:
    """A marker layer of a map: a group of markers shown while the zoom (1 =
    the whole map in view, 2 = half its width...) is from its `min_zoom` up
    to its `max_zoom` (None: no end). Every layer in range shows - several
    at once (e.g. "Main" from 1x on, "Rooms" adding detail from 3x, an
    "Overview" 1x-3x for what goes when zoomed in)."""

    id: str
    name: str
    min_zoom: float = 1.0
    max_zoom: float | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Layer:
        z = float(d.get("min_zoom", 1.0))
        if z < 0:
            raise ModelError("a layer's min_zoom can't be negative")
        top = d.get("max_zoom")
        end = None if top is None else float(top)
        if end is not None and end <= z:
            raise ModelError("a layer's max_zoom must be above its min_zoom")
        return cls(id=_req(d, "id", str), name=_req(d, "name", str), min_zoom=z, max_zoom=end)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "min_zoom": self.min_zoom, "max_zoom": self.max_zoom}


LAYER_HOUSE = "house"
LAYER_ROOMS = "rooms"


def default_layers() -> list[Layer]:
    """A new map starts with ONE layer (no layer choice shown until someone
    adds a second). Maps from before layers got House + Rooms in migrate.py."""
    return [Layer(LAYER_HOUSE, wording.t("names.layer_main"), 1.0)]  # (HA's language: stored so)


Segment = tuple[float, float, float, float]


def _segs(v: Any) -> list[Segment]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ModelError("segments must be a list")
    out: list[Segment] = []
    for s in v:
        if not (isinstance(s, (list, tuple)) and len(s) == 4):
            raise ModelError("a segment must be [x1, y1, x2, y2]")
        out.append((float(s[0]), float(s[1]), float(s[2]), float(s[3])))
    return out


@dataclass
class Map:
    """One floor / yard. `generated` = built from areas (squares), not drawn."""

    id: str
    name: str
    bounds: tuple[float, float, float, float]
    ha_floor: str | None = None
    generated: bool = False
    wall_width: float = 6.0
    walls: list[Segment] = field(default_factory=list)
    windows: list[Segment] = field(default_factory=list)
    openings: list[Segment] = field(default_factory=list)
    shapes: list[Shape] = field(default_factory=list)
    zones: list[Zone] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    layers: list[Layer] = field(default_factory=default_layers)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Map:
        b = d.get("bounds")
        if not (isinstance(b, (list, tuple)) and len(b) == 4):
            raise ModelError("map bounds must be [x0, y0, x1, y1]")
        x0, y0, x1, y1 = (float(v) for v in b)
        if x1 <= x0 or y1 <= y0:
            raise ModelError("map bounds are empty")
        return cls(
            id=_req(d, "id", str),
            name=_req(d, "name", str),
            bounds=(x0, y0, x1, y1),
            ha_floor=d.get("ha_floor"),
            generated=bool(d.get("generated", False)),
            wall_width=float(d.get("wall_width", 6.0)),
            walls=_segs(d.get("walls")),
            windows=_segs(d.get("windows")),
            openings=_segs(d.get("openings")),
            shapes=[Shape.from_dict(s) for s in d.get("shapes") or []],
            zones=[Zone.from_dict(z) for z in d.get("zones") or []],
            links=[Link.from_dict(lk) for lk in d.get("links") or []],
            layers=sorted(
                (Layer.from_dict(lay) for lay in d["layers"]), key=lambda lay: lay.min_zoom
            )
            if d.get("layers")
            else default_layers(),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "bounds": list(self.bounds),
            "ha_floor": self.ha_floor,
            "generated": self.generated,
            "wall_width": self.wall_width,
            "walls": [list(s) for s in self.walls],
            "windows": [list(s) for s in self.windows],
            "openings": [list(s) for s in self.openings],
            "shapes": [s.as_dict() for s in self.shapes],
            "zones": [z.as_dict() for z in self.zones],
            "links": [lk.as_dict() for lk in self.links],
            "layers": [lay.as_dict() for lay in self.layers],
        }

    def zone_for_area(self, area_id: str) -> Zone | None:
        return next((z for z in self.zones if z.area == area_id), None)


@dataclass
class Marker:
    """One placement of an entity on a map layer. An entity may have any
    number of markers: on several layers (each with its own position) and
    several times in one layer. A marker always controls its own entity - a
    light group is simply placed as its own entity (e.g. on a "Groups" layer).

    `layer`: the map layer it belongs to (shown only while that layer is).
    `show_name`: draw the entity's name above the icon."""

    id: str
    map: str
    entity: str
    x: float
    y: float
    layer: str = LAYER_HOUSE
    show_name: bool = False

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Marker:
        return cls(
            id=_req(d, "id", str),
            map=_req(d, "map", str),
            entity=_req(d, "entity", str),
            x=float(_req(d, "x", (int, float))),
            y=float(_req(d, "y", (int, float))),
            layer=str(d.get("layer") or LAYER_HOUSE),
            show_name=bool(d.get("show_name", False)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "map": self.map,
            "entity": self.entity,
            "x": self.x,
            "y": self.y,
            "layer": self.layer,
            "show_name": self.show_name,
        }


# ---- catalog ------------------------------------------------------------------


@dataclass
class CatalogEntry:
    """An entity offered in the tile picker. Its full name is HA's (shown in
    the picker); `short_name` (<= 15 chars) is what tiles and the map show,
    `review` = shortened automatically, not yet confirmed. `auto` entries come
    from the chosen HA areas; manual ones were added by the user."""

    entity: str
    kind: str
    short_name: str
    review: bool = False
    auto: bool = True

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CatalogEntry:
        kind = _req(d, "kind", str)
        if kind not in TILE_KINDS:
            raise ModelError(f"unknown tile kind '{kind}'")
        return cls(
            entity=_req(d, "entity", str),
            kind=kind,
            short_name=_short(d.get("short_name"), f"catalog entry {d.get('entity')}"),
            review=bool(d.get("review", False)),
            auto=bool(d.get("auto", True)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "kind": self.kind,
            "short_name": self.short_name,
            "review": self.review,
            "auto": self.auto,
        }


@dataclass
class Catalog:
    """`entries`: the picker list. `hidden`: auto entities the user removed
    (kept so a rebuild doesn't bring them back)."""

    entries: list[CatalogEntry] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Catalog:
        d = d or {}
        return cls(
            entries=[CatalogEntry.from_dict(e) for e in d.get("entries") or []],
            hidden=[str(h) for h in d.get("hidden") or []],
        )

    def as_dict(self) -> dict[str, Any]:
        return {"entries": [e.as_dict() for e in self.entries], "hidden": list(self.hidden)}

    def get(self, entity: str) -> CatalogEntry | None:
        return next((e for e in self.entries if e.entity == entity), None)


# ---- appliance profiles -------------------------------------------------------

# "idle": no finished state - straight back to idle when a cycle ends
FINISHED_PHASES = ("done", "waiting", "idle")


def _entity(v: Any, what: str, required: bool = False) -> str | None:
    if v is None or v == "":
        if required:
            raise ModelError(f"{what} is required")
        return None
    if not isinstance(v, str) or "." not in v:
        raise ModelError(f"{what} must be an entity id")
    return v


RULE_PREFIXES = ("unit:", "appliance:")  # clear rules that aren't entities


@dataclass
class ApplianceUnit:
    """One unit of an appliance tile (a washer, one dishwasher drawer...).

    `preset`: the brand preset (appliance_presets.py) reading `status` (the
    raw cycle / status entity), `time` (time left: a finish timestamp or a
    duration, as the preset says) and `door` (its own door sensor - shown as
    "door open"; with `door_clears`, opening it empties a finished unit).
    `finished`: what a finished cycle shows - "idle" = nothing (straight
    back to idle);
    "done", or "waiting" (washer: move the load on). `clear`: what else
    empties it - entities that turn on / open (a door contact the user
    picked), "unit:<id>" = that unit starting (the dryer, for a washer, on
    the same tile), or "appliance:<id>" = that appliance (its own tile - a
    separate dryer) starting.
    A tap on the tile always does too. `drawer`: a dishwasher drawer
    ("Drawer Open"). `overrides`: the user's answers for raw states the
    preset didn't know (raw lower-case -> phase)."""

    id: str
    label: str
    appliance: str
    preset: str
    status: str
    time: str | None = None
    door: str | None = None
    door_clears: bool = True
    finished: str = "done"
    clear: list[str] = field(default_factory=list)
    drawer: bool = False
    overrides: dict[str, str] = field(default_factory=dict)
    # smart-plug (power) presets: running above `power_on_w` watts; finished
    # after `power_off_min` minutes below it
    power_on_w: float = 5.0
    power_off_min: float = 3.0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ApplianceUnit:
        appliance = _req(d, "appliance", str)
        if appliance not in APPLIANCE_TYPES:
            raise ModelError(f"unknown appliance type '{appliance}'")
        finished = str(d.get("finished") or "done")
        if finished not in FINISHED_PHASES:
            raise ModelError(f"'finished' must be one of {FINISHED_PHASES}")
        clear = d.get("clear") or []
        if not isinstance(clear, list) or not all(isinstance(c, str) for c in clear):
            raise ModelError("'clear' must be a list")
        overrides = d.get("overrides") or {}
        if not isinstance(overrides, dict):
            raise ModelError("'overrides' must be a mapping")
        return cls(
            id=_req(d, "id", str),
            label=_short(d.get("label"), f"appliance unit {d.get('id')}"),
            appliance=appliance,
            preset=_req(d, "preset", str),
            status=_entity(d.get("status"), "unit status", required=True),
            time=_entity(d.get("time"), "unit time"),
            door=_entity(d.get("door"), "unit door"),
            door_clears=bool(d.get("door_clears", True)),
            finished=finished,
            clear=list(clear),
            drawer=bool(d.get("drawer", False)),
            overrides={str(k).lower(): str(v) for k, v in overrides.items()},
            power_on_w=float(d.get("power_on_w", 5.0)),
            power_off_min=float(d.get("power_off_min", 3.0)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "appliance": self.appliance,
            "preset": self.preset,
            "status": self.status,
            "time": self.time,
            "door": self.door,
            "door_clears": self.door_clears,
            "finished": self.finished,
            "clear": list(self.clear),
            "drawer": self.drawer,
            "overrides": dict(self.overrides),
            "power_on_w": self.power_on_w,
            "power_off_min": self.power_off_min,
        }

    def entities(self) -> list[str]:
        """Every HA entity this unit reads."""
        return [e for e in (self.status, self.time, self.door, *self.clear) if e and not e.startswith(RULE_PREFIXES)]


@dataclass
class Appliance:
    """An appliance tile's data: one or two units (dual-drawer dishwasher,
    washer + dryer). Room Tiles publishes it as a sensor the tile points at."""

    id: str
    name: str
    units: list[ApplianceUnit] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Appliance:
        units = [ApplianceUnit.from_dict(u) for u in d.get("units") or []]
        if not 1 <= len(units) <= 2:
            raise ModelError(f"appliance '{d.get('id')}' needs one or two units")
        return cls(id=_req(d, "id", str), name=_req(d, "name", str), units=units)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "units": [u.as_dict() for u in self.units]}


# ---- pool / spa profiles -------------------------------------------------------


@dataclass
class PoolBody:
    """One body's raw entities: `temp` (water temperature sensor - without
    one, the heater's `current_temperature` is used), `heater` (its climate
    entity: set point, heat / off, running or not), `pump`
    (separate layout: this body's own pump switch), `heater_switch` (a
    brand's own heater on / off switch, when it has one besides the
    thermostat - Jandy: kept off the tiles, Room Tiles' Heater switch or the
    Pool / Spa tile does it)."""

    temp: str | None = None
    heater: str | None = None
    pump: str | None = None
    heater_switch: str | None = None
    # turning its heater on (from Room Tiles) also turns the pump on - a
    # heater only heats with water flowing; some controllers start the pump
    # themselves, some don't (default on)
    pump_with_heater: bool = True

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> PoolBody | None:
        if d is None:
            return None
        return cls(
            temp=_entity(d.get("temp"), "body temperature"),
            heater=_entity(d.get("heater"), "body heater"),
            pump=_entity(d.get("pump"), "body pump"),
            heater_switch=_entity(d.get("heater_switch"), "body heater switch"),
            pump_with_heater=bool(d.get("pump_with_heater", True)),
        )

    def as_dict(self) -> dict[str, Any]:
        out = {"temp": self.temp, "heater": self.heater, "pump": self.pump, "pump_with_heater": self.pump_with_heater}
        if self.heater_switch:
            out["heater_switch"] = self.heater_switch
        return out


@dataclass
class PoolSystem:
    """A pool / spa system (pool.py has the logic). `layout`: "shared" (one
    pump + heater switching between pool and spa - `spa_mode` is the switch
    that puts it in spa mode, `pump` the circulation pump), "separate" (each
    body its own pump), "pool" / "spa" (one body). `spa_heater_follows`:
    turning the spa on (its tile's switch) turns its heater on too, and off
    with it (default on). Room Tiles publishes a
    sensor per body (shared: one combined Pool / Spa sensor) and its own
    switches (pool.switch_keys: Spa Mode, or a Heater per body)."""

    id: str
    name: str
    preset: str
    layout: str
    pool: PoolBody | None = None
    spa: PoolBody | None = None
    spa_mode: str | None = None
    pump: str | None = None
    spa_heater_follows: bool = True

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PoolSystem:
        from .pool import LAYOUTS

        layout = _req(d, "layout", str)
        if layout not in LAYOUTS:
            raise ModelError(f"unknown pool layout '{layout}'")
        sys_ = cls(
            id=_req(d, "id", str),
            name=_req(d, "name", str),
            preset=str(d.get("preset") or "manual"),
            layout=layout,
            pool=PoolBody.from_dict(d.get("pool")),
            spa=PoolBody.from_dict(d.get("spa")),
            spa_mode=_entity(d.get("spa_mode"), "spa mode switch"),
            pump=_entity(d.get("pump"), "pump"),
            spa_heater_follows=bool(d.get("spa_heater_follows", True)),
        )
        for body in sys_.bodies():
            b = getattr(sys_, body)
            # the water temperature: its own sensor, or its heater's reading
            # (Pentair ScreenLogic keeps it on the thermostat)
            if b is None or not (b.temp or b.heater):
                raise ModelError(f"the {body} needs its water temperature sensor (or a heater that reads it)")
        if layout == "shared" and not (sys_.spa_mode and sys_.pump):
            raise ModelError("a shared system needs its spa mode switch and its pump")
        if layout == "separate" and sys_.pool and sys_.spa and sys_.pool.heater and sys_.pool.heater == sys_.spa.heater:
            raise ModelError(
                "the pool and the spa can't share one heater when they run separately - "
                "pick it for the body it heats (or choose the shared layout)"
            )
        return sys_

    def bodies(self) -> tuple[str, ...]:
        return ("pool", "spa") if self.layout in ("shared", "separate") else (self.layout,)

    def tiles(self) -> tuple[str | None, ...]:
        """The bodies that get a sensor (= a tile): shared = one combined
        Pool / Spa (None) - it follows whichever body is active."""
        return (None,) if self.layout == "shared" else self.bodies()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "preset": self.preset,
            "layout": self.layout,
            "pool": self.pool.as_dict() if self.pool else None,
            "spa": self.spa.as_dict() if self.spa else None,
            "spa_mode": self.spa_mode,
            "pump": self.pump,
            "spa_heater_follows": self.spa_heater_follows,
        }

    def entities(self) -> list[str]:
        """Every HA entity this system reads."""
        out = [self.spa_mode, self.pump]
        for b in (self.pool, self.spa):
            if b:
                out += [b.temp, b.heater, b.pump]
        return [e for e in out if e]


# ---- robot vacuum profiles ------------------------------------------------------


@dataclass
class RobotProfile:
    """A robot vacuum's tile data (robot.py has the logic): `vacuum` (its HA
    vacuum entity), `error` (Matter's RVC operational error sensor, for
    "needs you" / fault alerts - None for robots that don't report one),
    `preset` ("matter" or "vacuum" - plain HA vacuum states)."""

    id: str
    name: str
    vacuum: str
    error: str | None = None
    preset: str = "vacuum"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RobotProfile:
        vac = _entity(d.get("vacuum"), "robot vacuum", required=True)
        if not vac.startswith("vacuum."):
            raise ModelError("a robot vacuum profile needs a vacuum entity")
        return cls(
            id=_req(d, "id", str),
            name=_req(d, "name", str),
            vacuum=vac,
            error=_entity(d.get("error"), "robot error sensor"),
            preset=str(d.get("preset") or "vacuum"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "vacuum": self.vacuum, "error": self.error, "preset": self.preset}

    def entities(self) -> list[str]:
        return [e for e in (self.vacuum, self.error) if e]


# ---- wall panels ----------------------------------------------------------------


@dataclass
class Panel:
    """A wall panel running Room Tiles firmware, with ITS OWN settings - never
    its room's (several panels can share a room). `id` = the panel's HA device
    id. Unset (None) = the default: `area` the panel's HA area at setup -
    taken once as its own (panels.adopt_ha_area), else the first shown and
    the panel asks; `layout` the area's starting layout, `theme` the house
    theme, `language` HA's language."""

    id: str
    area: str | None = None
    layout: str | None = None
    theme: str | None = None
    language: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Panel:
        return cls(
            id=_req(d, "id", str),
            area=d.get("area") or None,
            layout=d.get("layout") if d.get("layout") in LAYOUTS else None,
            theme=d.get("theme") or None,
            language=d.get("language") or None,
        )

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "area": self.area, "layout": self.layout, "theme": self.theme, "language": self.language}


# ---- the whole document -------------------------------------------------------


@dataclass
class Settings:
    """`auto_add_areas`: new HA areas appear in Room Tiles at once (otherwise
    they arrive hidden). `auto_update_panels`: panels install a newer
    firmware on their own (update.py; on by default)."""

    auto_add_areas: bool = False
    auto_update_panels: bool = True

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Settings:
        d = d or {}
        return cls(
            auto_add_areas=bool(d.get("auto_add_areas", False)),
            auto_update_panels=bool(d.get("auto_update_panels", True)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {"auto_add_areas": self.auto_add_areas, "auto_update_panels": self.auto_update_panels}


@dataclass
class RoomTilesData:
    areas: list[Area] = field(default_factory=list)
    maps: list[Map] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    catalog: Catalog = field(default_factory=Catalog)
    settings: Settings = field(default_factory=Settings)
    appliances: list[Appliance] = field(default_factory=list)
    pools: list[PoolSystem] = field(default_factory=list)
    robots: list[RobotProfile] = field(default_factory=list)
    # found devices the user ignored (Appliances page): their key entities -
    # appliance status entities, pool temperature / heater, vacuum entities
    ignored: list[str] = field(default_factory=list)
    # wall panels on Room Tiles firmware (their own settings)
    panels: list[Panel] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> RoomTilesData:
        d = d or {}
        data = cls(
            areas=[Area.from_dict(a) for a in d.get("areas") or []],
            maps=[Map.from_dict(m) for m in d.get("maps") or []],
            markers=[Marker.from_dict(m) for m in d.get("markers") or []],
            catalog=Catalog.from_dict(d.get("catalog")),
            settings=Settings.from_dict(d.get("settings")),
            appliances=[Appliance.from_dict(a) for a in d.get("appliances") or []],
            pools=[PoolSystem.from_dict(p) for p in d.get("pools") or []],
            robots=[RobotProfile.from_dict(r) for r in d.get("robots") or []],
            ignored=[str(e) for e in d.get("ignored") or []],
            panels=[Panel.from_dict(p) for p in d.get("panels") or []],
        )
        data.validate()
        return data

    def as_dict(self) -> dict[str, Any]:
        return {
            "areas": [a.as_dict() for a in self.areas],
            "maps": [m.as_dict() for m in self.maps],
            "markers": [m.as_dict() for m in self.markers],
            "catalog": self.catalog.as_dict(),
            "settings": self.settings.as_dict(),
            "appliances": [a.as_dict() for a in self.appliances],
            "pools": [p.as_dict() for p in self.pools],
            "robots": [r.as_dict() for r in self.robots],
            "ignored": list(self.ignored),
            "panels": [p.as_dict() for p in self.panels],
        }

    def validate(self) -> None:
        """Cross-checks: unique ids, references that point somewhere."""
        _unique([a.id for a in self.areas], "area")
        _unique([m.id for m in self.maps], "map")
        _unique([m.id for m in self.markers], "marker")
        _unique([a.id for a in self.appliances], "appliance")
        _unique([p.id for p in self.pools], "pool")
        _unique([r.id for r in self.robots], "robot vacuum")
        _unique([p.id for p in self.panels], "panel")
        for ap in self.appliances:
            _unique([u.id for u in ap.units], f"unit in appliance '{ap.id}'")
            ids = {u.id for u in ap.units}
            for u in ap.units:
                for c in u.clear:
                    if c.startswith("unit:") and (c[5:] not in ids or c[5:] == u.id):
                        raise ModelError(f"unit '{u.id}' is cleared by unknown unit '{c[5:]}'")
        area_ids = {a.id for a in self.areas}
        map_ids = {m.id for m in self.maps}
        for m in self.maps:
            _unique([z.id for z in m.zones], f"zone in map '{m.id}'")
            for z in m.zones:
                if z.area is not None and z.area not in area_ids:
                    raise ModelError(f"zone '{z.id}' links to unknown area '{z.area}'")
            for lk in m.links:
                if lk.to not in map_ids:
                    raise ModelError(f"link in map '{m.id}' goes to unknown map '{lk.to}'")
        maps = {m.id: m for m in self.maps}
        for m in self.maps:
            _unique([lay.id for lay in m.layers], f"layer in map '{m.id}'")
            if not m.layers:
                raise ModelError(f"map '{m.id}' needs at least one layer")
        for mk in self.markers:
            if mk.map not in map_ids:
                raise ModelError(f"marker '{mk.id}' is on unknown map '{mk.map}'")
            if mk.layer not in {lay.id for lay in maps[mk.map].layers}:
                raise ModelError(f"marker '{mk.id}' is on unknown layer '{mk.layer}'")

    # lookups
    def panel(self, panel_id: str) -> Panel | None:
        return next((p for p in self.panels if p.id == panel_id), None)

    def area(self, area_id: str) -> Area | None:
        return next((a for a in self.areas if a.id == area_id), None)

    def map(self, map_id: str) -> Map | None:
        return next((m for m in self.maps if m.id == map_id), None)

    def map_for_area(self, area_id: str) -> tuple[Map, Zone] | None:
        """The map and zone an area opens to, if it has one."""
        for m in self.maps:
            z = m.zone_for_area(area_id)
            if z is not None:
                return m, z
        return None


def _unique(ids: list[str], what: str) -> None:
    seen: set[str] = set()
    for i in ids:
        if i in seen:
            raise ModelError(f"duplicate {what} id '{i}'")
        seen.add(i)
