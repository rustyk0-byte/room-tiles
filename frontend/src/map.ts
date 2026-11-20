// <rt-map>: a Room Tiles map (one floor / yard), drawn as SVG from the
// integration's map data - walls, windows, openings, filled shapes, zones and
// their labels - with the map's markers live on top.
//
// Camera = the SVG viewBox. Overview = the whole map; tap a zone to zoom into
// it (Back returns); wheel / pinch / drag zoom and pan freely. LAYERS: every
// marker layer whose zoom range (start .. end, no end = on and on) holds the
// current zoom shows - several at once (layersAt). Zoom 1 = the map drawn as big as when it just fits a panel's
// map area (viewZoom) - the same number gives the same marker spacing on a
// phone, a panel or a monitor. A new map has one layer. Markers keep a fixed
// on-screen size at any zoom.
//
// Taps (house rule: fewest presses): a marker always controls its OWN entity -
// a light group is simply placed as its own marker (e.g. on a "Groups"
// layer). Lights / switches / fans toggle, covers toggle; for safety
// garage doors, gates, doors and LOCKS never change on one tap - their tile
// opens - like thermostats, appliances, vacuums, pool / spa. A scene turns
// on, a script runs. A long press
// always opens the tile. Tiles are shown by the panel ("popup" event).

import { fullName } from "./picker";
import { anchorOf } from "./arrange";
import "./controls"; // (<rt-roller>: the viewing zoom box)
import { ZOOM_EPS, zoomBox, zoomLabel, zoomStyles } from "./zoom-box";
import { LitElement, css, html, nothing, svg, unsafeCSS, type PropertyValues } from "lit";
import { SHEET_COLS, SHEET_ROWS, STATIC_BASE, markerAnimation } from "./appliance";
import { assetUrl, iconArt, type ThemeName } from "./theme";
import type { HassEntity, HomeAssistant, RoomTilesDoc, TileKind } from "./types";
import { EDGE_SPEED, applySelect, boxSelectMode, edgePull, selectMode, startsBox, type SelectMode } from "./input";
import { bbox, pointIn, polyArea } from "./geom";
import { applianceIcon, vacuumIcon, vacuumStatus, isEntryCover, tileIcon } from "./rules";
import { LABEL_PX, planBase, planLabels, planStyles } from "./plan-draw";
import { queueBadges, queueRooms, queueStyles, type QueueView } from "./vacqueue";
import { noSelectStyles } from "./ui";
import { t, th } from "./i18n";

/** The Layer Editor's view choices (Names, State): as on the map, all on, all off. */
export type ViewChoice = "map" | "on" | "off";

export interface MapZone {
  id: string;
  name: string;
  points: [number, number][];
  area: string | null;
  label: [number, number] | null;
  outdoor: boolean;
  /** a vacuum zone: only on this vacuum's view of the map */
  vacuum?: string | null;
  /** the name reads bottom to top (narrow rooms) */
  label_vertical?: boolean;
}
export interface MapShape {
  style: "floor" | "water" | "grass" | "deck" | "paving";
  points: [number, number][];
}
export interface MapLayer {
  id: string;
  name: string;
  min_zoom: number;
  /** where it stops showing (none: no end) - layers overlap freely */
  max_zoom?: number | null;
}
export interface MapData {
  id: string;
  name: string;
  bounds: [number, number, number, number];
  ha_floor: string | null;
  generated: boolean;
  wall_width: number;
  walls: [number, number, number, number][];
  windows: [number, number, number, number][];
  openings: [number, number, number, number][];
  shapes: MapShape[];
  zones: MapZone[];
  links: { to: string; at: [number, number]; label: string }[];
  layers: MapLayer[];
}
export interface MapMarker {
  id: string;
  map: string;
  entity: string;
  x: number;
  y: number;
  layer: string;
  show_name: boolean;
}

export interface Camera {
  x: number;
  y: number;
  w: number;
  h: number;
}

// MIRRORED: firmware/components/room_tiles/map_markers.cpp MARKER_PX - a change here must be made there too.
const MARKER_PX = 40; // on-screen marker size, CSS px

// the integration's defaults (model.py default_layers)
const defaultLayers = (): MapLayer[] => [{ id: "house", name: t("editor.layer_main"), min_zoom: 1 }];

/** The most maps, and marker layers per map (const.py MAX_MAPS / MAX_LAYERS):
 *  map navigation has to fit a phone and the 1024x600 panels. */
export const MAX_MAPS = 8;
export const MAX_LAYERS = 6;

/** A map's marker layers in zoom order (maps without layers: the defaults). */
export function layersOf(map: MapData | undefined): MapLayer[] {
  return [...(map?.layers?.length ? map.layers : defaultLayers())].sort((a, b) => a.min_zoom - b.min_zoom);
}

// MIRRORED: firmware/components/room_tiles/map_markers.cpp (layers showing) - a change here must be made there too.
/** The layers showing at zoom `z`: every one whose range (start .. end, no
 *  end = on and on) holds it - several at once. Zoomed out past every
 *  start: the first layer(s), as if at their start. */
export function layersAt(map: MapData | undefined, z: number): MapLayer[] {
  const layers = layersOf(map);
  const shown = layers.filter((l) => l.min_zoom <= z + ZOOM_EPS && (l.max_zoom == null || z < l.max_zoom - ZOOM_EPS));
  if (shown.length || !layers.length) return shown;
  const first = layers[0].min_zoom;
  return z < first ? layers.filter((l) => l.min_zoom === first) : shown;
}

/** Is layer `l` showing at zoom `z`? */
export function layerShowsAt(l: MapLayer, z: number): boolean {
  return l.min_zoom <= z + ZOOM_EPS && (l.max_zoom == null || z < l.max_zoom - ZOOM_EPS);
}

/** "Rooms" / "Rooms +1": the main layer at a zoom and how many more show with it. */
export function layersLabel(main: MapLayer | undefined, shown: MapLayer[]): string {
  if (!main) return "";
  const more = shown.filter((l) => l.id !== main.id).length;
  return more ? `${main.name} +${more}` : main.name;
}

/** A marker's layer; data from before storage 1.4 had a `detail` flag instead. */
function markerLayer(mk: MapMarker): string {
  return mk.layer ?? ((mk as unknown as { detail?: boolean }).detail ? "rooms" : "house");
}
const LONG_PRESS_MS = 500;
const DRAG_PX = 8; // a press that moves further is a pan, not a tap
const ZOOM_MS = 280;
/** marker editing suggests a new layer from this many times the last layer's start */
const DEEP_ZOOM = 2;
/** how far the camera goes (_zoomAt): 1/14 .. 1.4x the whole map's width */
const CAM_IN = 14;
const CAM_OUT = 1.4;

/** Where each map was left (position + zoom, so also its layer, and the room
 *  zoomed into) - this browser only, per map. */
const VIEW_KEY = (id: string) => `room-tiles:map-view:${id}`;

export interface SavedView {
  x: number;
  y: number;
  w: number;
  h: number;
  zone?: string | null;
}

function readView(id: string): SavedView | undefined {
  try {
    const v = JSON.parse(localStorage.getItem(VIEW_KEY(id)) ?? "null");
    return v && [v.x, v.y, v.w, v.h].every(Number.isFinite) && v.w > 0 && v.h > 0 ? v : undefined;
  } catch {
    return undefined;
  }
}

/** A remembered view that still shows part of the map (else dropped). */
export function onMap(v: SavedView | undefined, full: { x: number; y: number; w: number; h: number }): SavedView | undefined {
  if (!v) return undefined;
  const overlaps = v.x < full.x + full.w && v.x + v.w > full.x && v.y < full.y + full.h && v.y + v.h > full.y;
  return overlaps ? v : undefined;
}

function writeView(id: string, v: SavedView): void {
  try {
    localStorage.setItem(VIEW_KEY(id), JSON.stringify(v));
  } catch {
    /* private mode etc.: just not remembered */
  }
}

// MIRRORED: firmware/components/room_tiles/map_view.cpp (zoom number) - a change here must be made there too.
/** The panels' map area (1024 x 600 less the 48 px top strip). Zoom 1 = the
 *  whole map just fits it. */
export const REF_VIEW = { w: 1024, h: 552 };

/** The zoom number (layers switch on it): how big the map is drawn compared
 *  with fitting a panel's map area - so the same number means the same
 *  spacing between the fixed-size markers on any screen. A phone starts
 *  below 1 (the whole map is squeezed into a narrow screen), a big monitor
 *  above. Sizes are CSS px (the browser's scaled pixels, not the device's).
 *  `size` unknown yet: the plain map-in-view ratio. */
export function viewZoom(full: { w: number; h: number }, cam: { w: number; h: number }, size: { w: number; h: number }): number {
  if (size.w <= 1 || size.h <= 1) return Math.max(full.w / cam.w, full.h / cam.h);
  const ref = Math.max(full.w / REF_VIEW.w, full.h / REF_VIEW.h); // map units per px: whole map on a panel
  return ref / Math.max(cam.w / size.w, cam.h / size.h);
}

/** How far a viewer zooms in (not an editor: CAM_IN / the plan editor's own):
 *  8x, or 1.25x the deepest layer's start, or what the map's smallest room
 *  needs to fill the view (as a tap on it zooms: ZONE_MARGIN round it) - in
 *  0.25 steps. The panels use the same rule (map_view view_max_zoom_). */
export const VIEW_MAX_ZOOM = 8;
// MIRRORED: firmware/components/room_tiles/map_view.cpp (max zoom) - a change here must be made there too.
/** The viewing zoom box's steps (map_view.cpp ZOOM_STEP): each a whole new
 *  set of panel map tiles. */
export const VIEW_ZOOM_STEP = 0.5;

/** The zoom box roller's steps: the map's zoom limit on top, then each
 *  whole step below it (where + and - stop) down to 1x. */
export function viewZoomSteps(max: number): number[] {
  const out = [Math.round(max * 100) / 100];
  for (let n = Math.ceil(max / VIEW_ZOOM_STEP - 1e-3) - 1; n * VIEW_ZOOM_STEP >= 1 - 1e-3; n--) out.push(n * VIEW_ZOOM_STEP);
  return out;
}

export function viewMaxZoom(map: MapData | undefined): number {
  let z = VIEW_MAX_ZOOM;
  if (!map) return z;
  for (const l of layersOf(map)) z = Math.max(z, l.min_zoom * 1.25);
  const [x0, y0, x1, y1] = map.bounds ?? [0, 0, 1, 1];
  const ref = Math.max(Math.max(1, x1 - x0) / REF_VIEW.w, Math.max(1, y1 - y0) / REF_VIEW.h);
  for (const zn of map.zones ?? []) {
    if (zn.vacuum || !zn.points?.length) continue; // (a vacuum's own zone: only its queue view)
    const xs = zn.points.map((p) => p[0]), ys = zn.points.map((p) => p[1]);
    const w = (Math.max(...xs) - Math.min(...xs)) * (1 + 2 * ZONE_MARGIN);
    const h = (Math.max(...ys) - Math.min(...ys)) * (1 + 2 * ZONE_MARGIN);
    if (w > 0 && h > 0) z = Math.max(z, ref / Math.max(w / REF_VIEW.w, h / REF_VIEW.h));
  }
  return Math.ceil(z * 4 - 1e-3) / 4;
}

/** The zoom buttons' next level: the next multiple of `step` up / down
 *  (1.7 -> 1.75 in, 1.5 out), never below one step. */
export function zoomStep(z: number, dir: 1 | -1, step = 0.25): number {
  const n = dir > 0 ? Math.floor(z / step + 1e-6) + 1 : Math.ceil(z / step - 1e-6) - 1;
  return Math.max(step, n * step);
}

export { zoomLabel } from "./zoom-box";
const ZONE_MARGIN = 0.18;

const ICON: Partial<Record<TileKind, string>> = {
  onoff_light: "icon_light",
  dimmable_light: "icon_light",
  color_light: "icon_light",
  switch: "icon_switch",
  fan: "icon_fan",
  cover: "icon_blind",
  lock: "icon_key",
  climate: "icon_ac",
  water: "icon_pool",
  scene: "icon_scene",
  script: "icon_script",
};

/** Off markers are gray - every icon the SAME gray: the art's own brightness
 *  differs a lot (the key is half as bright as the bulb), so each gets its
 *  own dimming to an average luminance of ~147 (the bulb at 0.8). From the
 *  icons' average luminance (assets: 60 px ui icons, opaque pixels):
 *  light 184, switch 122, fan 190, blind 159, key 90, ac 135, garage 124,
 *  dishwasher 203, laundry 184, matic 144, robot vacuum 185, pool 145, spa
 *  167, scene 154, script 200. Re-measure when
 *  the art changes. */
const OFF_BRIGHTNESS: Record<string, number> = {
  icon_light: 0.8,
  icon_switch: 1.2,
  icon_fan: 0.77,
  icon_blind: 0.92,
  icon_key: 1.63,
  icon_ac: 1.09,
  icon_garage: 1.19,
  icon_dishwasher: 0.72,
  icon_laundry: 0.8,
  icon_matic: 1.02,
  icon_robot_vacuum: 0.79,
  icon_pool: 1.01,
  icon_spa: 0.88,
  icon_scene: 0.95,
  icon_script: 0.73,
};

// theme token per kind for the "on" fill
const RUN_FLASH_MS = 1500; // a tapped scene / script marker lights this long (the tiles' too)

const ON_TOKEN: Partial<Record<TileKind, string>> = {
  onoff_light: "light",
  dimmable_light: "light",
  color_light: "light",
  switch: "switch",
  fan: "fan",
  cover: "cover",
  lock: "lock",
  climate: "heat",
  water: "map-water",
  appliance: "light",
  vacuum: "accent",
  scene: "scene",
  script: "script",
};

/** A vacuum marker's colour by its status (the tile's / queue's colours):
 *  cleaning green, heading home blue, paused amber, needs you orange, error
 *  red; docked / idle / offline gray (off). */
const VAC_TOKEN: Record<string, string> = {
  cleaning: "vac-cleaning",
  returning: "accent",
  paused: "vac-paused",
  attention: "vac-attention",
  error: "vac-error",
};

// MIRRORED: firmware/components/room_tiles/map_markers.cpp (what a marker is) - a change here must be made there too.
/** The colour token a marker uses while on. */
export function markerToken(kind: TileKind, st?: HassEntity): string {
  if (kind === "vacuum") return VAC_TOKEN[vacuumStatus(st).cls] ?? "accent";
  return ON_TOKEN[kind] ?? "accent";
}

// MIRRORED: firmware/components/room_tiles/map_markers.cpp (what a marker is) - a change here must be made there too.
export function kindFor(entity: string, doc?: RoomTilesDoc): TileKind {
  const entry = doc?.catalog.entries.find((e) => e.entity === entity);
  if (entry) return entry.kind;
  const domain = entity.split(".")[0];
  return (
    ({ light: "dimmable_light", switch: "switch", input_boolean: "switch", fan: "fan", cover: "cover", lock: "lock", climate: "climate", vacuum: "vacuum", scene: "scene", script: "script" } as Record<string, TileKind>)[domain] ??
    "appliance"
  );
}

/** The HA area of the map room at (x, y) - the smallest one there with an
 *  area (a Bar inside the Living Room wins); vacuum-only zones don't count.
 *  Where Add puts a marker, so the picker starts with that area. */
export function areaAt(map: MapData | undefined, x: number, y: number): string | undefined {
  return map?.zones
    .filter((z) => z.area && !z.vacuum && pointIn(x, y, z.points))
    .sort((a, b) => polyArea(a.points) - polyArea(b.points))[0]?.area ?? undefined;
}

// MIRRORED: firmware/components/room_tiles/map_markers.cpp (what a marker is) - a change here must be made there too.
/** Is the marker's entity "on" (coloured) - map_active in the firmware. */
export function markerActive(kind: TileKind, st?: HassEntity): boolean {
  if (!st) return false;
  switch (kind) {
    case "lock":
      return st.state === "unlocked"; // highlighted = needs attention
    case "cover":
      return st.state !== "closed";
    case "climate":
      return st.state !== "off";
    case "appliance":
    case "water":
      return !["idle", "off", "unavailable", "unknown"].includes(st.state);
    case "vacuum":
      return VAC_TOKEN[vacuumStatus(st).cls] !== undefined;
    case "scene":
      return false; // nothing to show: a scene has no state of its own
    case "script":
      return st.state === "on"; // running
    default:
      return st.state === "on";
  }
}

// MIRRORED: firmware/components/room_tiles/board.cpp icon_on_ - a change here must be made there too.
/** A tile's icon "on" (else the theme's off picture, when it has one): the
 *  markers' rule, so tile and marker agree - the switch's own value where
 *  there is one (a tap shows at once), a lock's inverted (unlocked = active,
 *  as on the map); a scene / script lit while its tap flashes. */
export function iconOn(kind: TileKind, st: HassEntity | undefined, switchOn: boolean, flashing: boolean): boolean {
  if (flashing) return true;
  switch (kind) {
    case "lock":
      return !switchOn;
    case "appliance":
    case "water":
    case "vacuum":
    case "scene":
    case "script":
      return markerActive(kind, st);
    default:
      return switchOn;
  }
}

export class RtMap extends LitElement {
  static properties = {
    hass: { attribute: false },
    doc: { attribute: false },
    map: { attribute: false },
    _flash: { state: true },
    theme: { type: String },
    focusZone: { type: String },
    focusArea: { type: String },
    editing: { type: Boolean },
    editLayer: { type: String },
    markersOverride: { attribute: false },
    names: { type: String },
    queueView: { attribute: false },
    states: { type: String },
    selectedIds: { attribute: false },
    boxMode: { type: Boolean },
    crosshair: { type: Boolean },
    remember: { type: Boolean },
    startView: { attribute: false },
    _drag: { state: true },
    _box: { state: true },
    _cam: { state: true },
    _size: { state: true },
    _zone: { state: true },
  };
  /** scene / script markers just tapped: lit until then (a scene has no
   *  state to show it went) - entity -> when */
  private _flash: Record<string, number> = {};

  hass?: HomeAssistant;
  doc?: RoomTilesDoc;
  map?: MapData;
  theme: ThemeName = "dark";
  /** zone to open zoomed into (e.g. the current area's) */
  focusZone?: string;
  /** open zoomed to ALL of this HA area's rooms on the map (a Map tile) */
  focusArea?: string;
  /** map edit mode: markers are dragged / tapped instead of toggled, only
   *  `editLayer`'s markers show (any zoom), from `markersOverride` (the draft) */
  editing = false;
  editLayer?: string;
  markersOverride?: MapMarker[];
  /** placing markers: names as each marker's "Show name" ("map"), on every
   *  marker ("on") or none ("off") - only while editing */
  names: ViewChoice = "map";
  /** a vacuum's queue mode: its view of the map (cleanable rooms lit, its
   *  zones), the queued areas numbered, the one being cleaned lit; a tap on a
   *  room it cleans fires "queue-tap" {area}; no markers. */
  queueView?: QueueView;
  /** placing markers: each marker's live state ("map"), all shown on ("on")
   *  or all off ("off") - only while editing */
  states: ViewChoice = "map";
  /** the edit selection (marker ids) */
  selectedIds: string[] = [];
  /** touch "Select" mode: a drag on empty map draws a selection box */
  boxMode = false;
  /** marker editing's Add tool: a crosshair in the middle of the view (where
   *  the new marker goes); "crosshair-area" {area} says when the area under
   *  it changes */
  crosshair = false;
  /** this visit saves where the map is left (opened from the area picker -
   *  not from a Map tile) */
  remember = true;
  /** open on exactly this view (back from an editor: where it was left) */
  startView?: Camera;
  private _crossArea?: string | null; // last announced (null = none)
  /** markers being dragged: their ids and how far they have moved (map units) */
  private _drag?: { ids: Set<string>; dx: number; dy: number; sel: boolean };
  private _dragAt?: { x: number; y: number }; // the pointer during an edit drag (client px)
  private _afterDrag = false; // markers were just dragged: the next tap selects afresh
  private _edgeAnim?: number; // edge scrolling's animation frame
  /** a selection box being drawn (map units) */
  private _box?: { x0: number; y0: number; x1: number; y1: number };
  private _cam: Camera = { x: 0, y: 0, w: 1, h: 1 };
  private _size = { w: 1, h: 1 };
  private _fitLayer = true; // the opening view still has to meet the first layer's zoom (size not known yet)
  private _saveTimer?: number;
  private _savedView = ""; // what was last written
  private _announceZone = false; // a remembered room view: tell the screen (title, Back)
  private _zoneShown: string | null = null; // the room the screen was last told about
  private _zone?: string; // the zone zoomed into, if any
  private _layerId?: string; // last announced layer
  private _ro?: ResizeObserver;
  private _anim?: number;
  private _suitPending?: string; // suitLayer(id) waiting for the size
  private _flyTo?: Camera; // where a running animation ends
  private _pointers = new Map<number, { x: number; y: number }>();
  private _press?: {
    id: number;
    x: number;
    y: number;
    marker?: MapMarker;
    zone?: string;
    moved: boolean;
    timer?: number;
    long: boolean;
    box?: boolean; // drawing a selection box
    start?: [number, number]; // map coords where the press started
    mode?: SelectMode; // the selection intent of this press
  };
  private _pinch?: { dist: number; cam: Camera; cx: number; cy: number };

  connectedCallback(): void {
    super.connectedCallback();
    this._ro = new ResizeObserver(() => {
      const w = this.clientWidth || 1;
      const h = this.clientHeight || 1;
      if (w !== this._size.w || h !== this._size.h) this._size = { w, h };
      if (this._fitLayer && w > 1 && h > 1) {
        this._fitLayer = false;
        this._cam = this._atFirstLayer(this._cam);
      }
      if (this._suitPending && w > 1 && h > 1) {
        const id = this._suitPending;
        this._suitPending = undefined;
        this.suitLayer(id);
      }
    });
    this._ro.observe(this);
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    this._ro?.disconnect();
    if (this._anim) cancelAnimationFrame(this._anim);
    this._anim = undefined;
    // (a zoom cut short: straight to where it was going - what the view
    // and the remembered view say match what's shown after a reattach)
    if (this._flyTo) {
      this._cam = this._flyTo;
      this._flyTo = undefined;
    }
  }

  protected willUpdate(changed: PropertyValues): void {
    if (changed.has("map") && this.map) {
      const prev = changed.get("map") as MapData | undefined;
      if (!prev || prev.id !== this.map.id) {
        this._zone = undefined;
        this._layerId = undefined;
        // a Map tile: every room of its area on this map, together
        const areaRooms = this.focusArea ? this.map.zones.filter((zz) => zz.area === this.focusArea && !zz.vacuum) : [];
        const z = this.focusZone ? this.map.zones.find((zz) => zz.id === this.focusZone) : areaRooms[0];
        // (a map redrawn elsewhere / resized: a view off the map is dropped;
        // the layer isn't stored - the zoom picks whichever layer covers it)
        const saved = z ? undefined : onMap(readView(this.map.id), this._overviewCam());
        if (this.queueView) {
          // the room queue: the whole map on screen - every room in reach, no scrolling
          this._cam = this._overviewCam();
          this._fitLayer = false;
        } else if (this.startView) {
          this._cam = { ...this.startView };
          this._fitLayer = false;
        } else if (saved) {
          // back where it was left (its zoom picks the layer again)
          const full = this._overviewCam();
          const w = Math.min(full.w * CAM_OUT, Math.max(full.w / CAM_IN, saved.w));
          const k = w / saved.w;
          this._cam = this._capped({ x: saved.x + (saved.w - w) / 2, y: saved.y + (saved.h - saved.h * k) / 2, w, h: saved.h * k });
          this._zone = saved.zone && this.map.zones.some((zz) => zz.id === saved.zone) ? saved.zone : undefined;
          this._announceZone = !!this._zone;
          this._fitLayer = false;
        } else {
          // a room (Map tile): all of it in view; the whole map: at least the
          // first layer's zoom (size not known yet: again once it is)
          this._cam = areaRooms.length ? this._zonesCam(areaRooms) : z ? this._zoneCam(z) : this._atFirstLayer(this._overviewCam());
          this._fitLayer = !z && this._size.w <= 1;
          if (z) {
            this._zone = z.id;
            this._announceZone = true; // the screen's title and Back follow
          }
        }
      }
    }
  }

  // ---- camera --------------------------------------------------------------------

  private _overviewCam(): Camera {
    const [x0, y0, x1, y1] = this.map?.bounds ?? [0, 0, 1, 1];
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }

  /** Where the map was left, written a moment after it stops moving. */
  private _rememberView(): void {
    const m = this.map;
    if (!m || this._size.w <= 1 || !this.remember) return;
    const c = this._flyTo ?? this._cam;
    const r = (n: number) => Math.round(n * 10) / 10;
    const v: SavedView = { x: r(c.x), y: r(c.y), w: r(c.w), h: r(c.h), zone: this._zone ?? null };
    const text = JSON.stringify(v);
    if (text === this._savedView) return;
    this._savedView = text;
    window.clearTimeout(this._saveTimer);
    this._saveTimer = window.setTimeout(() => writeView(m.id, v), 400);
  }

  /** A view at least at the zoom where the first layer starts (about its
   *  middle): a phone showing the whole map is far below 1 - its markers
   *  would sit on top of each other - so the map opens / goes back to the
   *  first layer's spacing instead, and you pan. Size unknown: as it is. */
  private _atFirstLayer(cam: Camera): Camera {
    if (this._size.w <= 1 || this._size.h <= 1) return cam;
    const first = layersOf(this.map)[0]?.min_zoom ?? 1;
    const z = viewZoom(this._overviewCam(), cam, this._size);
    if (z >= first - ZOOM_EPS) return cam;
    const k = z / first;
    const [cx, cy] = [cam.x + cam.w / 2, cam.y + cam.h / 2];
    return { x: cx - (cam.w * k) / 2, y: cy - (cam.h * k) / 2, w: cam.w * k, h: cam.h * k };
  }

  private _zoneCam(z: MapZone): Camera {
    return this._zonesCam([z]);
  }

  /** Several rooms in view together (an area drawn as more than one room):
   *  their combined box, with the room margin. */
  private _zonesCam(zones: MapZone[]): Camera {
    const b = bbox(zones.flatMap((z) => z.points));
    const mx = (b.x1 - b.x0) * ZONE_MARGIN;
    const my = (b.y1 - b.y0) * ZONE_MARGIN;
    return { x: b.x0 - mx, y: b.y0 - my, w: b.x1 - b.x0 + 2 * mx, h: b.y1 - b.y0 + 2 * my };
  }

  /** The zoom number (viewZoom): 1 = drawn as big as the whole map on a panel. */
  private get _zoom(): number {
    return viewZoom(this._overviewCam(), this._cam, this._size);
  }

  /** The layers showing at the current zoom (layersAt). */
  private get _shownLayers(): MapLayer[] {
    return layersAt(this.map, this._zoom);
  }

  /** The main one of them: the latest to start (the most detailed). (Maps
   *  from before storage 1.4 have no layers: the defaults apply.) */
  private get _layer(): MapLayer | undefined {
    const shown = this._shownLayers;
    return shown[shown.length - 1] ?? layersOf(this.map)[0];
  }

  protected updated(): void {
    // the screen's title and Back follow the room zoomed into - also when
    // the map leaves it by zooming / panning / an editor moving the view
    if (this._announceZone || (this._zone ?? null) !== this._zoneShown) {
      this._announceZone = false;
      this._zoneShown = this._zone ?? null;
      const zone = this.map?.zones.find((zz) => zz.id === this._zone) ?? null;
      this.dispatchEvent(new CustomEvent("zone", { detail: { zone }, bubbles: true, composed: true }));
    }
    this._rememberView();
    if (this.crosshair && this.map) {
      const c = this._cam;
      const area = areaAt(this.map, c.x + c.w / 2, c.y + c.h / 2) ?? null;
      if (area !== this._crossArea) {
        this._crossArea = area;
        this.dispatchEvent(new CustomEvent("crosshair-area", { detail: { area }, bubbles: true, composed: true }));
      }
    } else this._crossArea = undefined; // announce again when it comes back
    const layer = this._layer;
    const shown = this._shownLayers.map((l) => l.id);
    const key = `${layer?.id}|${shown.join()}`;
    if (layer && key !== this._layerId) {
      this._layerId = key;
      // the main layer, and every layer showing (several at once)
      this.dispatchEvent(new CustomEvent("layer", { detail: { layer, shown }, bubbles: true, composed: true }));
    }
  }

  /** map units per CSS px (preserveAspectRatio meet: the larger ratio) */
  private get _scale(): number {
    return Math.max(this._cam.w / this._size.w, this._cam.h / this._size.h);
  }

  /** Viewing (not editing): no deeper than viewMaxZoom - kept centred. */
  private _capped(c: Camera): Camera {
    if (this.editing || this._size.w <= 1 || this._size.h <= 1) return c;
    const max = viewMaxZoom(this.map);
    const z = viewZoom(this._overviewCam(), c, this._size);
    if (z <= max + ZOOM_EPS) return c;
    const k = z / max;
    return { x: c.x + (c.w - c.w * k) / 2, y: c.y + (c.h - c.h * k) / 2, w: c.w * k, h: c.h * k };
  }

  private _fly(to: Camera): void {
    to = this._capped(to);
    if (this._anim) cancelAnimationFrame(this._anim);
    const from = { ...this._cam };
    this._flyTo = to;
    const reduce = this.closest("[data-motion='off']") !== null || getRootHost(this)?.getAttribute("data-motion") === "off";
    if (reduce) {
      this._cam = to;
      this._flyTo = undefined;
      return;
    }
    const t0 = performance.now();
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / ZOOM_MS);
      const e = 1 - Math.pow(1 - k, 3);
      this._cam = {
        x: from.x + (to.x - from.x) * e,
        y: from.y + (to.y - from.y) * e,
        w: from.w + (to.w - from.w) * e,
        h: from.h + (to.h - from.h) * e,
      };
      if (k < 1) this._anim = requestAnimationFrame(step);
      else this._flyTo = undefined;
    };
    this._anim = requestAnimationFrame(step);
  }

  /** The zoom number now (where an animation ends, if one is running). */
  currentZoom(): number {
    return viewZoom(this._overviewCam(), this._flyTo ?? this._cam, this._size);
  }

  /** The current view (where an animation ends, if one is running). */
  camera(): Camera {
    return { ...(this._flyTo ?? this._cam) };
  }

  /** The middle of the current view, in map units (where "Add" places a marker). */
  viewCenter(): [number, number] {
    return [this._cam.x + this._cam.w / 2, this._cam.y + this._cam.h / 2];
  }

  /** A marker's diameter in map units at the current zoom (markers keep
   *  their on-screen size). */
  markerSize(): number {
    const c = this._flyTo ?? this._cam;
    return MARKER_PX * Math.max(c.w / this._size.w, c.h / this._size.h);
  }

  /** The zoom buttons: to the next 0.25 step, about the middle of the view
   *  (quick taps step on from where the running animation ends). */
  zoomBy(dir: 1 | -1): void {
    const c = this._flyTo ?? this._cam;
    this.zoomTo(zoomStep(viewZoom(this._overviewCam(), c, this._size), dir));
  }

  /** Fly to zoom `z` (viewZoom) about the middle of the view - about the
   *  middle of the map once the whole map is in view (picking a layer
   *  starts at its zoom). Inside the camera's limits. */
  zoomTo(z: number): void {
    if (!this.editing) z = Math.max(1, z); // (viewing: never past the whole map)
    const c = this._flyTo ?? this._cam;
    const full = this._overviewCam();
    let k = viewZoom(full, c, this._size) / Math.max(0.05, z);
    k = Math.min(full.w * CAM_OUT, Math.max(full.w / CAM_IN, c.w * k)) / c.w;
    const w = c.w * k;
    const h = c.h * k;
    const whole = w >= full.w - 1e-6 && h >= full.h - 1e-6;
    const [cx, cy] = whole ? [full.x + full.w / 2, full.y + full.h / 2] : [c.x + c.w / 2, c.y + c.h / 2];
    this._zone = undefined;
    this._fly({ x: cx - w / 2, y: cy - h / 2, w, h });
  }

  /** Entering the Layer Editor on layer `id`: if the zoom doesn't suit it
   *  (people see another layer here, or it's far past where the last layer
   *  starts - DEEP_ZOOM), fly to where it starts; a zoom that suits it stays. */
  suitLayer(id: string): void {
    // the zoom needs the size on screen: not measured yet (just opened) -
    // once it is (a zoom from a 1 x 1 px size would be near 0: fly all the way in)
    if (this._size.w <= 1 || this._size.h <= 1) {
      this._suitPending = id;
      return;
    }
    const layers = layersOf(this.map);
    const l = layers.find((x) => x.id === id);
    if (!l) return;
    const z = viewZoom(this._overviewCam(), this._flyTo ?? this._cam, this._size);
    // far past where an endless layer starts: markers placed there would crowd at its start
    const deep = l.max_zoom == null && z >= Math.max(1, l.min_zoom) * DEEP_ZOOM;
    if (!layerShowsAt(l, z) || deep) this.zoomTo(l.min_zoom);
  }

  /** The camera can't go further in / out. */
  private get _camLimits(): { atIn: boolean; atOut: boolean } {
    const c = this._flyTo ?? this._cam;
    const full = this._overviewCam();
    if (!this.editing) {
      // viewing: from the whole map in to the map's deepest zoom (_capped)
      const z = viewZoom(full, c, this._size);
      return { atIn: z >= viewMaxZoom(this.map) - ZOOM_EPS, atOut: z <= 1 + ZOOM_EPS };
    }
    return { atIn: c.w <= full.w / CAM_IN + 1e-6, atOut: c.w >= full.w * CAM_OUT - 1e-6 };
  }

  zoomToZone(id: string | undefined): void {
    const z = id ? this.map?.zones.find((zz) => zz.id === id) : undefined;
    this._zone = z?.id;
    this._fly(this._atFirstLayer(z ? this._zoneCam(z) : this._overviewCam()));
    this.dispatchEvent(new CustomEvent("zone", { detail: { zone: z ?? null }, bubbles: true, composed: true }));
  }

  /** Marker editing's room picker, "the whole map": its middle in the view at
   *  the same zoom. */
  centerOnWhole(): void {
    const full = this._overviewCam();
    const c = this._flyTo ?? this._cam;
    this._zone = undefined;
    this._fly({ x: full.x + full.w / 2 - c.w / 2, y: full.y + full.h / 2 - c.h / 2, w: c.w, h: c.h });
    this.dispatchEvent(new CustomEvent("zone", { detail: { zone: null }, bubbles: true, composed: true }));
  }

  /** Marker editing's room picker: the room in the middle of the view at the
   *  SAME zoom - the layer being edited stays the one shown. */
  centerOnZone(id: string): void {
    const z = this.map?.zones.find((zz) => zz.id === id);
    if (!z) return;
    const b = bbox(z.points);
    const c = this._flyTo ?? this._cam;
    const [cx, cy] = [(b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2];
    this._zone = z.id;
    this._fly({ x: cx - c.w / 2, y: cy - c.h / 2, w: c.w, h: c.h });
    this.dispatchEvent(new CustomEvent("zone", { detail: { zone: z }, bubbles: true, composed: true }));
  }

  /** client px -> map units */
  private _toMap(cx: number, cy: number): [number, number] {
    const r = this.getBoundingClientRect();
    const s = this._scale;
    // meet: the viewBox is centred in the element
    const offX = (this._size.w * s - this._cam.w) / 2;
    const offY = (this._size.h * s - this._cam.h) / 2;
    return [this._cam.x - offX + (cx - r.left) * s, this._cam.y - offY + (cy - r.top) * s];
  }

  private _zoomAt(cx: number, cy: number, factor: number, base: Camera = this._cam): void {
    const [mx, my] = this._toMap(cx, cy);
    const full = this._overviewCam();
    let w = Math.min(full.w * CAM_OUT, Math.max(full.w / CAM_IN, base.w * factor));
    if (!this.editing && this._size.w > 1 && this._size.h > 1) {
      // viewing: no deeper than viewMaxZoom (the zoom number goes as 1 / width)
      const z = viewZoom(full, { w, h: (base.h * w) / base.w }, this._size);
      const max = viewMaxZoom(this.map);
      if (z > max) w = (w * z) / max;
    }
    const k = w / base.w;
    this._cam = { x: mx - (mx - base.x) * k, y: my - (my - base.y) * k, w, h: base.h * k };
    this._zone = undefined;
  }

  // ---- input -----------------------------------------------------------------------

  private _onWheel(e: WheelEvent): void {
    e.preventDefault();
    this._zoomAt(e.clientX, e.clientY, Math.pow(1.0015, e.deltaY));
  }

  /** Forget every tracked finger (a pop-up took over, a stale pointer...). */
  private _resetPointers(): void {
    for (const t of [this._press?.timer]) clearTimeout(t);
    this._pointers.clear();
    this._press = undefined;
    this._pinch = undefined;
    this._dropDrag();
  }

  /** An edit drag or box given up (a pinch began, the fingers were reset):
   *  nothing left drawn that won't be saved. */
  private _dropDrag(): void {
    if (this._edgeAnim) cancelAnimationFrame(this._edgeAnim);
    this._edgeAnim = undefined;
    this._dragAt = undefined;
    this._drag = undefined;
    this._box = undefined;
  }

  private _down(e: PointerEvent, marker?: MapMarker): void {
    // The first finger down: anything still tracked is stale (its "up" went
    // to something that covered the map, e.g. a pop-up) - otherwise this
    // finger would count as the second finger of a pinch.
    if (e.isPrimary) this._resetPointers();
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
    this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (this._pointers.size === 2) {
      // pinch
      clearTimeout(this._press?.timer);
      this._press = undefined;
      this._dropDrag(); // (a marker drag or box under way: given up)
      const [a, b] = [...this._pointers.values()];
      this._pinch = { dist: Math.hypot(a.x - b.x, a.y - b.y), cam: { ...this._cam }, cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2 };
      return;
    }
    const [mx, my] = this._toMap(e.clientX, e.clientY);
    const zone = marker ? undefined : this._zoneAt(mx, my);
    // Box select (or Shift / Alt-drag): a drag draws a box even from a
    // marker - a tap still selects it
    const box = this.editing && startsBox(e, this.boxMode);
    this._press = {
      id: e.pointerId,
      x: e.clientX,
      y: e.clientY,
      marker,
      zone,
      moved: false,
      long: false,
      box,
      start: [mx, my],
      mode: selectMode(e),
    };
    if (marker && !this.editing) {
      this._press.timer = window.setTimeout(() => {
        if (this._press && !this._press.moved) {
          this._press.long = true;
          this._popup(marker, e.clientX, e.clientY);
        }
      }, LONG_PRESS_MS);
    }
  }

  private _move(e: PointerEvent): void {
    const prev = this._pointers.get(e.pointerId);
    if (!prev) return;
    this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (this._pinch && this._pointers.size === 2) {
      const [a, b] = [...this._pointers.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y) || 1;
      this._zoomAt(this._pinch.cx, this._pinch.cy, this._pinch.dist / d, this._pinch.cam);
      return;
    }
    const p = this._press;
    if (!p || p.id !== e.pointerId) return;
    if (!p.moved && Math.hypot(e.clientX - p.x, e.clientY - p.y) > DRAG_PX) {
      p.moved = true;
      clearTimeout(p.timer);
    }
    if (p.moved && this.editing && (p.box || p.marker) && p.start) {
      this._dragAt = { x: e.clientX, y: e.clientY };
      this._followDrag(p);
      this._edgeScroll();
      return;
    }
    if (p.moved) {
      const s = this._scale;
      this._cam = { ...this._cam, x: this._cam.x - (e.clientX - prev.x) * s, y: this._cam.y - (e.clientY - prev.y) * s };
      this._zone = undefined;
    }
  }

  /** Edit mode, a drag in progress: the selection box, or the dragged
   *  markers (the selection follows the finger; an unselected marker moves
   *  on its own and is NOT selected by it) - from the last pointer position. */
  private _followDrag(p: NonNullable<RtMap["_press"]>): void {
    const at = this._dragAt;
    if (!at || !p.start) return;
    const [mx, my] = this._toMap(at.x, at.y);
    if (p.box) {
      this._box = { x0: p.start[0], y0: p.start[1], x1: mx, y1: my };
      return;
    }
    if (!p.marker) return;
    const inSel = this.selectedIds.includes(p.marker.id);
    this._drag = {
      ids: inSel ? new Set(this.selectedIds) : new Set([p.marker.id]),
      dx: Math.round(mx - p.start[0]),
      dy: Math.round(my - p.start[1]),
      sel: inSel,
    };
  }

  /** Dragging near the map's edge scrolls it that way - faster the closer
   *  - and the drag goes on with it (markers / the box follow). */
  private _edgeScroll(): void {
    if (this._edgeAnim) return;
    const step = () => {
      this._edgeAnim = undefined;
      const p = this._press;
      const at = this._dragAt;
      if (!p || !p.moved || !at || !(p.box || p.marker)) return;
      const [vx, vy] = edgePull(this.getBoundingClientRect(), at.x, at.y);
      if (!vx && !vy) return;
      const s = this._scale;
      this._cam = { ...this._cam, x: this._cam.x + vx * EDGE_SPEED * s, y: this._cam.y + vy * EDGE_SPEED * s };
      this._zone = undefined;
      this._followDrag(p);
      this._edgeAnim = requestAnimationFrame(step);
    };
    this._edgeAnim = requestAnimationFrame(step);
  }

  private _up(e: PointerEvent): void {
    this._pointers.delete(e.pointerId);
    if (this._edgeAnim) cancelAnimationFrame(this._edgeAnim);
    this._edgeAnim = undefined;
    this._dragAt = undefined;
    if (this._pointers.size < 2) this._pinch = undefined;
    const p = this._press;
    if (!p || p.id !== e.pointerId) return;
    clearTimeout(p.timer);
    this._press = undefined;
    if (this.editing && p.box && !(p.marker && !p.moved)) {
      const box = this._box;
      this._box = undefined;
      if (e.type === "pointercancel") return;
      if (p.moved && box) {
        const [x0, x1] = [Math.min(box.x0, box.x1), Math.max(box.x0, box.x1)];
        const [y0, y1] = [Math.min(box.y0, box.y1), Math.max(box.y0, box.y1)];
        const ids = this._visibleMarkers()
          .filter((m) => m.x >= x0 && m.x <= x1 && m.y >= y0 && m.y <= y1)
          .map((m) => m.id);
        const sel = applySelect(this.selectedIds, ids, boxSelectMode(e));
        this._emit("select", { ids: sel });
        // the row lists what the box selected (a button narrows to one)
        this._emit("stack", { ids: sel });
      } else {
        this._emit("select", { ids: [] });
        this._emit("stack", { ids: [] });
      }
      this._afterDrag = false;
      return;
    }
    if (this.editing && p.marker) {
      const drag = this._drag;
      this._drag = undefined;
      if (e.type === "pointercancel") return;
      if (p.moved && drag) {
        this._emit("markers-moved", { ids: [...drag.ids], dx: drag.dx, dy: drag.dy });
        // the selection was dragged: the next tap starts a new one
        if (drag.sel) this._afterDrag = true;
      } else if (!p.moved) {
        // the markers under the tap (the Map Editor's "Here:" row): tapping
        // the selected one again selects the next one under it
        const stack = p.start ? this._markersAt(p.start) : [p.marker.id];
        const k = stack.indexOf(p.marker.id);
        const sole = this.selectedIds.length === 1 && this.selectedIds[0] === p.marker.id;
        this._emit("stack", { ids: stack });
        if (sole && stack.length > 1 && k >= 0) {
          this._afterDrag = false;
          this._emit("select", { ids: [stack[(k + 1) % stack.length]] });
        } else {
          // the first tap after a drag starts a new selection (touch adds to
          // a selection otherwise) - what was just moved isn't kept by it
          const mode = this._afterDrag ? "replace" : (p.mode ?? "replace");
          this._afterDrag = false;
          this._emit("select", { ids: applySelect(this.selectedIds, [p.marker.id], mode) });
        }
      }
      return;
    }
    if (this.editing && !p.moved && e.type !== "pointercancel" && this.selectedIds.length) {
      this._afterDrag = false;
      this._emit("stack", { ids: [] });
      this._emit("select", { ids: [] }); // a tap on empty map clears the selection
      return;
    }
    if (p.moved || p.long || e.type === "pointercancel") return;
    if (this.queueView) {
      // queue mode: a tap on a room the vacuum cleans adds / removes its area
      const z = p.zone ? this.map?.zones.find((zz) => zz.id === p.zone) : undefined;
      if (z?.area && this.queueView.vacuum.areas.includes(z.area)) this._emit("queue-tap", { area: z.area });
      return;
    }
    if (p.marker) this._tap(p.marker, e.clientX, e.clientY);
    // (placing markers: a tap on a room never zooms - the zoom picks the
    // layer being edited; the title's room picker keeps the zoom)
    else if (!this.editing && p.zone && p.zone !== this._zone) this.zoomToZone(p.zone);
  }

  /** the markers shown right now (map, layer, not disabled) - also what a
   *  selection box / select-all pick from */
  /** The markers (on the layer shown / edited) under map point p, nearest
   *  first - overlapping ones all count. */
  private _markersAt(p: [number, number]): string[] {
    const r = (MARKER_PX / 2) * this._scale;
    return this._visibleMarkers()
      .map((mk) => ({ id: mk.id, d: Math.hypot(mk.x - p[0], mk.y - p[1]) }))
      .filter((x) => x.d <= r)
      .sort((a, b) => a.d - b.d)
      .map((x) => x.id);
  }

  private _visibleMarkers(): MapMarker[] {
    const m = this.map;
    if (!m) return [];
    const disabled = new Set(this.doc?.disabled ?? []);
    // editing: the edited layer's (any zoom); else every layer showing now
    const layers = new Set(this.editing ? [this.editLayer ?? this._layer?.id] : this._shownLayers.map((l) => l.id));
    const source = this.markersOverride ?? (this.doc?.markers as MapMarker[] | undefined) ?? [];
    return source.filter((mk) => mk.map === m.id && layers.has(markerLayer(mk)) && !disabled.has(mk.entity));
  }

  /** Placing markers: the OTHER layers showing at this zoom - drawn faded,
   *  not to be touched (only the edited layer's markers change). */
  private _ghostMarkers(): MapMarker[] {
    const m = this.map;
    if (!m || !this.editing) return [];
    const disabled = new Set(this.doc?.disabled ?? []);
    const others = new Set(this._shownLayers.map((l) => l.id).filter((id) => id !== this.editLayer));
    const source = this.markersOverride ?? (this.doc?.markers as MapMarker[] | undefined) ?? [];
    return source.filter((mk) => mk.map === m.id && others.has(markerLayer(mk)) && !disabled.has(mk.entity));
  }

  /** visible marker ids (the panel's Ctrl+A) */
  visibleMarkerIds(): string[] {
    return this._visibleMarkers().map((m) => m.id);
  }

  /** screen pixels -> map units at the current zoom (arrow-key nudges) */
  pxToMap(px: number): number {
    return px * this._scale;
  }

  private _emit(name: string, detail: Record<string, unknown>): void {
    this.dispatchEvent(new CustomEvent(name, { detail, bubbles: true, composed: true }));
  }

  private _zoneAt(x: number, y: number): string | undefined {
    // the smallest zone containing the point (rooms inside a yard win)
    let best: { id: string; area: number } | undefined;
    const qv = this.queueView?.vacuum;
    for (const z of this.map?.zones ?? []) {
      // a room with no name and no area is floor only - not a room to tap;
      // vacuum zones only in that vacuum's queue mode
      if ((z.vacuum && z.vacuum !== qv?.id) || (!z.name.trim() && !z.area) || !pointIn(x, y, z.points)) continue;
      const b = bbox(z.points);
      const area = (b.x1 - b.x0) * (b.y1 - b.y0);
      if (!best || area < best.area) best = { id: z.id, area };
    }
    return best?.id;
  }

  // ---- actions ---------------------------------------------------------------------

  private _popup(m: MapMarker, x: number, y: number): void {
    this._resetPointers(); // the pop-up covers the map: this finger's "up" won't come here
    this.dispatchEvent(
      new CustomEvent("popup", { detail: { entity: m.entity, kind: kindFor(m.entity, this.doc), x, y }, bubbles: true, composed: true }),
    );
  }

  private _tap(m: MapMarker, x: number, y: number): void {
    const hass = this.hass;
    if (!hass) return;
    const kind = kindFor(m.entity, this.doc);
    const t = { entity_id: m.entity };
    switch (kind) {
      case "onoff_light":
      case "dimmable_light":
      case "color_light":
      case "switch":
      case "fan":
        hass.callService("homeassistant", "toggle", t);
        return;
      case "cover":
        if (isEntryCover(hass, m.entity)) return this._popup(m, x, y);
        hass.callService("cover", "toggle", t);
        return;
      case "lock":
        // safety: a lock is never changed by one tap on the map - its tile
        // opens (like garage doors, gates and doors)
        return this._popup(m, x, y);
      case "scene":
      case "script": {
        hass.callService(kind, "turn_on", t);
        this._flash = { ...this._flash, [m.entity]: Date.now() + RUN_FLASH_MS };
        window.setTimeout(() => this.requestUpdate(), RUN_FLASH_MS + 50);
        return;
      }
      default:
        this._popup(m, x, y);
    }
  }

  // ---- rendering -------------------------------------------------------------------

  private _art(name: string): string {
    return assetUrl(STATIC_BASE, `ui/${name}.png`, this.theme);
  }

  render() {
    const m = this.map;
    if (!m) return html`<div class="empty">${t("map.no_map")}</div>`;
    const c = this._cam;
    const s = this._scale;
    const layer = this._layer?.id;
    void layer;
    const drag = this._drag;
    const markers = this._visibleMarkers().map((mk) => (drag?.ids.has(mk.id) ? { ...mk, x: mk.x + drag.dx, y: mk.y + drag.dy } : mk));
    const box = this._box;
    return html`
      <svg
        viewBox="${c.x} ${c.y} ${c.w} ${c.h}"
        preserveAspectRatio="xMidYMid meet"
        @wheel=${this._onWheel}
        @pointerdown=${(e: PointerEvent) => this._down(e)}
        @pointermove=${this._move}
        @pointerup=${this._up}
        @pointercancel=${this._up}
        @lostpointercapture=${(e: PointerEvent) => this._pointers.delete(e.pointerId)}
      >
        ${svg`
          ${planBase(m, { s, focusZone: this._zone, outlineZones: m.generated, vacuum: this.queueView?.vacuum }, c)}
          ${this.queueView ? queueRooms(m, this.queueView) : nothing}
          ${planLabels(m, s, this.queueView?.vacuum)}
          ${this.queueView ? queueBadges(m, this.queueView, 13 * s, LABEL_PX * s + 13 * s * 0.4, 15 * s) : nothing}
          ${this.queueView ? nothing : this._renderLinks(m, s)}
          ${this.queueView ? nothing : this._ghostMarkers().map((mk) => this._renderMarker(mk, s, true))}
          ${this.queueView ? nothing : markers.map((mk) => this._renderMarker(mk, s))}
          ${box
            ? svg`<rect class="selbox" x=${Math.min(box.x0, box.x1)} y=${Math.min(box.y0, box.y1)}
                width=${Math.abs(box.x1 - box.x0)} height=${Math.abs(box.y1 - box.y0)}></rect>`
            : nothing}
        `}
      </svg>
      ${this.editing && this.crosshair ? this._renderCrosshair() : nothing}
      ${this.editing ? this._renderZoom() : this.queueView ? nothing : this._renderViewZoom()}
    `;
  }

  /** Marker editing's Add tool: where the new marker lands - a dotted
   *  outline the size of a marker, with a dot in the middle (the Add picker
   *  starts with the area there). The view is centred in the element, so the
   *  middle of the element is the middle of the view. */
  private _renderCrosshair() {
    const r = MARKER_PX / 2;
    return html`<div class="crosshair" aria-hidden="true">
      <svg viewBox="${-r - 2} ${-r - 2} ${2 * r + 4} ${2 * r + 4}" style="--d:${2 * r + 4}px">
        <circle class="ring" r=${r}></circle>
        <circle class="dot" r="2.5"></circle>
      </svg>
    </div>`;
  }

  /** The viewing zoom box - the panels' own: + on top, a roller of the zoom
   *  steps (the deepest on top, like + above it - roll it and the map jumps
   *  to that zoom), - under it. Zooms without pinching (a mouse, one hand).
   *  MIRRORED: firmware/components/room_tiles/map_view.cpp build_zoom_box_ / set_zoom_steps_ / zoom_by_ - a change here must be made there too. */
  private _renderViewZoom() {
    const max = viewMaxZoom(this.map);
    const steps = viewZoomSteps(max);
    const z = viewZoom(this._overviewCam(), this._flyTo ?? this._cam, this._size);
    let row = 0;
    steps.forEach((st, i) => {
      if (Math.abs(st - z) < Math.abs(steps[row] - z)) row = i;
    });
    const by = (dir: 1 | -1) => {
      const n = dir > 0 ? Math.floor(z / VIEW_ZOOM_STEP + 1e-3) + 1 : Math.ceil(z / VIEW_ZOOM_STEP - 1e-3) - 1;
      this.zoomTo(Math.max(1, Math.min(max, n * VIEW_ZOOM_STEP)));
    };
    return html`<div class="vzoom" role="group" aria-label=${t("zoom.zoom")}>
      <button aria-label=${t("zoom.in")} ?disabled=${z >= max - ZOOM_EPS} @click=${() => by(1)}><ha-icon icon="mdi:plus"></ha-icon></button>
      <rt-roller
        .options=${steps.map(zoomLabel)}
        .selected=${row}
        .label=${t("zoom.zoom")}
        @change=${(e: CustomEvent) => this.zoomTo(steps[e.detail.row])}
      ></rt-roller>
      <button aria-label=${t("zoom.out")} ?disabled=${z <= 1 + ZOOM_EPS} @click=${() => by(-1)}><ha-icon icon="mdi:minus"></ha-icon></button>
    </div>`;
  }

  /** Marker editing: zoom buttons and the zoom level, with the layer people
   *  see at this zoom - to pick the layers' zoom settings (and to show that
   *  the map zooms at all). */
  private _renderZoom() {
    const z = this._zoom;
    const lim = this._camLimits;
    const shownLayers = this._shownLayers;
    const edited = layersOf(this.map).find((l) => l.id === this.editLayer);
    // the edited layer isn't showing at this zoom
    const off = !!(edited && !shownLayers.some((l) => l.id === edited.id));
    // an endless layer, zoomed to twice where it starts or more: markers
    // placed for this zoom crowd together where it starts - a new layer suits
    const deep = !off && !!edited && edited.max_zoom == null && z >= Math.max(1, edited.min_zoom) * DEEP_ZOOM;
    // the label: the edited layer (+ how many others show with it) - or what shows
    const main = edited && !off ? edited : this._layer;
    const target = edited ?? this._layer;
    return html`<div class="zoomwrap">
      ${zoomBox({
        z,
        layer: off ? layersLabel(this._layer, shownLayers) : layersLabel(main, shownLayers),
        off,
        atIn: lim.atIn,
        atOut: lim.atOut,
        onIn: () => this.zoomBy(1),
        onOut: () => this.zoomBy(-1),
        // to where the edited layer starts
        start: target?.min_zoom,
        startName: target?.name,
        onStart: target ? () => this.zoomTo(target.min_zoom) : undefined,
      })}
      ${deep
        ? (() => {
            // a layer that shows here and starts further in: the one for this zoom
            const better = shownLayers
              .filter((l) => l.id !== edited!.id && l.min_zoom > edited!.min_zoom)
              .sort((a, b) => b.min_zoom - a.min_zoom)[0];
            const addLink = html`<a
              href="#"
              @click=${(e: Event) => {
                e.preventDefault();
                this.dispatchEvent(new CustomEvent("layer-settings", { bubbles: true, composed: true }));
              }}
              >${t("map.add_layer")}</a
            >`;
            return html`<div class="znote" role="status">
              <ha-icon icon="mdi:layers-plus"></ha-icon>
              <span
                >${th("map.too_far_in", { layer: html`<b>${edited!.name}</b>`, zoom: zoomLabel(edited!.min_zoom) })}
                ${better
                  ? th("map.switch_layer", {
                      layer: html`<a
                        href="#"
                        @click=${(e: Event) => {
                          e.preventDefault();
                          this._emit("edit-layer", { layer: better.id });
                        }}
                        >${better.name}</a
                      >`,
                      add: addLink,
                    })
                  : th("map.add_layer_here", { add: addLink })}</span
              >
            </div>`;
          })()
        : nothing}
      ${off
        ? html`<div class="znote" role="status">
            <ha-icon icon="mdi:alert-outline"></ha-icon>
            <span
              >${th("map.layer_not_here", {
                layer: html`<b>${edited!.name}</b>`,
                starts: html`<b>${t("layer.starts_at")}</b>`,
                ends: html`<b>${t("layer.ends_at")}</b>`,
              })}</span
            >
          </div>`
        : nothing}
    </div>`;
  }

  /** Links to other maps (stairs, a yard door): a tap opens that map
   *  ("go-map" {to}); not while editing markers. */
  private _renderLinks(m: MapData, s: number) {
    const names = new Map(((this.doc?.maps as MapData[] | undefined) ?? []).map((x) => [x.id, x.name]));
    return svg`${m.links.map((l) => {
      const text = `↗ ${l.label || names.get(l.to) || l.to}`;
      const w = (text.length * 7.5 + 20) * s;
      const h = 26 * s;
      return svg`<g
        class="link ${this.editing ? "editing" : ""}"
        transform="translate(${l.at[0]} ${l.at[1]})"
        @pointerdown=${(e: PointerEvent) => !this.editing && e.stopPropagation()}
        @pointerup=${(e: PointerEvent) => {
          if (this.editing) return;
          e.stopPropagation();
          this._resetPointers();
          this._emit("go-map", { to: l.to });
        }}
      >
        <rect x=${-w / 2} y=${-h / 2} width=${w} height=${h} rx=${h / 2}></rect>
        <text font-size=${13 * s}>${text}</text>
      </g>`;
    })}`;
  }

  /** An appliance marker plays its tile's animation over the icon (the top
   *  unit's wins - markerAnimation): the tiles' sprite sheet in a 1 x 1
   *  window, stepped by CSS like on the tiles (appliance.ts). Paused - the
   *  first frame - when the panel's animations are off. */
  private _renderMarkerAnim(st: HassEntity | undefined, r: number) {
    const anim = markerAnimation(st?.attributes.tile);
    if (!anim) return nothing;
    const still = this.closest("[data-motion='off']") !== null || getRootHost(this)?.getAttribute("data-motion") === "off";
    const d = r * 1.5;
    return svg`<svg class="m-anim ${still ? "still" : ""}" x=${-d / 2} y=${-d / 2} width=${d} height=${d} viewBox="0 0 1 1">
      <g class="m-rows"><image class="m-sheet" href=${assetUrl(STATIC_BASE, `appliances/${anim}.webp`, this.theme)}
        width=${SHEET_COLS} height=${SHEET_ROWS} preserveAspectRatio="none"></image></g>
    </svg>`;
  }

  /** A marker's name (its "Show name"): a small label above it, on its own
   *  backing so it reads on any floor colour. Width from the text length
   *  (Roboto ~0.55 em a character), like the links' labels. */
  private _renderMarkerName(name: string, r: number, s: number) {
    const h = 18 * s;
    const w = (name.length * 7 + 12) * s;
    const y = -r - 4 * s - h / 2;
    return svg`<g class="mname" transform="translate(0 ${y})">
      <rect x=${-w / 2} y=${-h / 2} width=${w} height=${h} rx=${h / 2}></rect>
      <text font-size=${12.5 * s}>${name}</text>
    </g>`;
  }

  private _renderMarker(mk: MapMarker, s: number, ghost = false) {
    const kind = kindFor(mk.entity, this.doc);
    const st = this.hass?.states[mk.entity];
    const flashing = (this._flash[mk.entity] ?? 0) > Date.now();
    const on = this.editing && this.states !== "map" ? this.states === "on" : flashing || markerActive(kind, st);
    const r = (MARKER_PX / 2) * s;
    const icon =
      kind === "vacuum"
        ? vacuumIcon(this.hass, mk.entity)
        : kind === "water"
          ? tileIcon("water", mk.entity, this.hass) ?? "icon_pool" // the pool or the spa (the combined one: its mode)
        : kind === "cover" && isEntryCover(this.hass, mk.entity)
          ? "icon_garage"
          : kind === "appliance"
            ? applianceIcon(this.hass, mk.entity)
            : ICON[kind] ?? "icon_switch";
    const name =
      this.doc?.catalog.entries.find((e) => e.entity === mk.entity)?.short_name ?? fullName(this.hass, mk.entity);
    return svg`
      <g
        class="marker ${on ? "on" : ""} ${st ? "" : "missing"} ${this.editing && !ghost ? "editing" : ""} ${ghost ? "ghost" : ""} ${this.selectedIds.includes(mk.id) ? "selected" : ""}"
        transform="translate(${mk.x} ${mk.y})"
        style="--on:var(--rt-${markerToken(kind, st)})"
        @pointerdown=${(e: PointerEvent) => {
          e.stopPropagation();
          this._down(e, mk);
        }}
        @pointermove=${this._move}
        @pointerup=${(e: PointerEvent) => {
          e.stopPropagation();
          this._up(e);
        }}
        @pointercancel=${this._up}
        @contextmenu=${(e: MouseEvent) => {
          // right-click = long press (docs/UI.md)
          e.preventDefault();
          e.stopPropagation();
          this._resetPointers();
          if (this.editing) this._emit("select", { ids: applySelect(this.selectedIds, [mk.id], selectMode(e)) });
          else this._popup(mk, e.clientX, e.clientY);
        }}
      >
        <title>${fullName(this.hass, mk.entity)}</title>
        <circle class="face" r=${r} stroke-width=${s * 1.5}></circle>
        ${this.editing && anchorOf(this.selectedIds) === mk.id
          ? svg`<circle class="anchor" r=${r + 6 * s}></circle>`
          : nothing}
        <image
          href=${this._art(iconArt(icon, on, this.theme))}
          style="--off-b:${OFF_BRIGHTNESS[icon] ?? 0.8}"
          x=${-r * 0.75}
          y=${-r * 0.75}
          width=${r * 1.5}
          height=${r * 1.5}
        ></image>
        ${kind === "appliance" && !(this.editing && this.states === "off") ? this._renderMarkerAnim(st, r) : nothing}
        ${(this.editing && this.names !== "map" ? this.names === "on" : mk.show_name) ? this._renderMarkerName(name, r, s) : nothing}
      </g>
    `;
  }

  static styles = [noSelectStyles, zoomStyles, queueStyles, 
    planStyles,
    css`
    /* the viewing zoom box (_renderViewZoom): the panels' - 88 wide in the
       map's top-right corner, +, the steps' roller, - */
    .vzoom {
      position: absolute;
      top: 10px;
      right: 10px;
      width: 88px;
      display: flex;
      flex-direction: column;
      align-items: stretch;
      border-radius: 12px;
      background: var(--rt-dialog);
      border: 1px solid var(--rt-tile-border);
      overflow: hidden;
      --mdc-icon-size: 24px;
      --u: 1px;
    }
    .vzoom button {
      height: 48px;
      border: 0;
      background: none;
      color: var(--rt-text);
      cursor: pointer;
      padding: 0;
    }
    .vzoom button:disabled {
      opacity: 0.35;
      cursor: default;
    }
    .vzoom rt-roller {
      margin: 0 6px;
      --rt-roller-selected-size: 22px;
    }
    :host {
      display: block;
      position: relative;
      width: 100%;
      height: 100%;
      background: var(--rt-map-bg);
      overflow: hidden;
      touch-action: none;
      user-select: none;
    }
    svg {
      display: block;
      width: 100%;
      height: 100%;
    }
    .empty {
      padding: 32px;
      text-align: center;
      color: var(--rt-text-secondary);
    }
    .zone {
      cursor: zoom-in;
    }
    .zone.focus {
      cursor: default;
    }
    /* the room queue: a tap adds / removes a room, nothing zooms */
    .zone.clean {
      cursor: pointer;
    }
    .zone.noclean,
    .zone.vzone {
      cursor: default;
    }
    .marker {
      cursor: pointer;
    }
    .link {
      cursor: pointer;
    }
    .link.editing {
      pointer-events: none;
      opacity: 0.5;
    }
    .link rect {
      fill: var(--rt-dialog);
      stroke: var(--rt-accent);
      stroke-width: 1.5px;
      vector-effect: non-scaling-stroke;
    }
    .link text {
      fill: var(--rt-text);
      text-anchor: middle;
      dominant-baseline: central;
      font-family: Roboto, sans-serif;
      pointer-events: none;
    }
    /* MIRRORED: firmware/components/room_tiles/map_markers.cpp paint_marker_ (the ring) - a change here must be made there too. */
    /* off: the plain face, its ring in the type's full colour (the tiles' off
       icons have it as their outline) - gray icon = off, the colour = what it is */
    .marker .face {
      fill: var(--rt-map-marker);
      stroke: var(--on);
    }
    .marker.on .face {
      fill: var(--on);
      fill-opacity: 0.5;
      stroke: var(--on);
    }
    .marker image {
      filter: grayscale(1) brightness(var(--off-b, 0.8));
      pointer-events: none;
    }
    .marker.on image {
      filter: none;
    }
    /* an appliance's animation over its icon: in SVG user units (the window
       is 1 x 1, the sheet SHEET_COLS x SHEET_ROWS) - rows step down once per
       loop, columns step across once per row, 16 fps like the tiles */
    .m-anim {
      overflow: hidden;
      pointer-events: none;
    }
    .marker .m-anim image {
      filter: none;
    }
    .m-rows {
      animation: rt-m-rows ${unsafeCSS((SHEET_COLS * SHEET_ROWS) / 16)}s steps(${unsafeCSS(SHEET_ROWS)}) infinite;
    }
    .m-sheet {
      animation: rt-m-cols ${unsafeCSS(SHEET_COLS / 16)}s steps(${unsafeCSS(SHEET_COLS)}) infinite;
    }
    .m-anim.still .m-rows,
    .m-anim.still .m-sheet {
      animation: none;
    }
    @keyframes rt-m-rows {
      to {
        transform: translateY(${unsafeCSS(-SHEET_ROWS)}px);
      }
    }
    @keyframes rt-m-cols {
      to {
        transform: translateX(${unsafeCSS(-SHEET_COLS)}px);
      }
    }
    /* placing markers: another layer showing at this zoom - seen, not touched */
    .marker.ghost {
      opacity: 0.35;
      pointer-events: none;
    }
    .marker.missing {
      opacity: 0.4;
    }
    .marker.editing {
      cursor: grab;
    }
    .marker.editing .face {
      stroke: var(--rt-light);
      stroke-dasharray: 4 3;
    }
    .selbox {
      fill: var(--rt-accent);
      fill-opacity: 0.15;
      stroke: var(--rt-accent);
      stroke-width: 1.5px;
      vector-effect: non-scaling-stroke;
      stroke-dasharray: 5 4;
      pointer-events: none;
    }
    .marker.selected .face {
      stroke: var(--rt-accent);
      stroke-dasharray: none;
      stroke-width: 3px;
      vector-effect: non-scaling-stroke;
    }
    .crosshair {
      position: absolute;
      left: 50%;
      top: 50%;
      width: 0;
      height: 0;
      pointer-events: none;
    }
    .crosshair svg {
      position: absolute;
      left: calc(var(--d) / -2);
      top: calc(var(--d) / -2);
      width: var(--d); /* not the map's svg rule (100%) */
      height: var(--d);
      overflow: visible;
    }
    .crosshair .ring {
      fill: none;
      stroke: var(--rt-accent);
      stroke-width: 2;
      stroke-dasharray: 4 3;
    }
    .crosshair .dot {
      fill: var(--rt-accent);
    }
    .anchor {
      /* the first selected: what Align lines the others up with */
      fill: none;
      stroke: var(--rt-accent);
      stroke-width: 2.5px;
      stroke-dasharray: 5 4;
      vector-effect: non-scaling-stroke;
      pointer-events: none;
    }
    .mname {
      pointer-events: none;
    }
    .mname rect {
      fill: var(--rt-dialog);
      fill-opacity: 0.9;
      stroke: var(--rt-tile-border);
      stroke-width: 1px;
      vector-effect: non-scaling-stroke;
    }
    .mname text {
      /* no outline: the marker's own stroke must not reach the letters */
      stroke: none;
      fill: var(--rt-text);
      text-anchor: middle;
      dominant-baseline: central;
      font-family: Roboto, sans-serif;
    }
  `,
  ];
}

function getRootHost(el: Element): Element | null {
  const root = el.getRootNode() as ShadowRoot;
  return root && "host" in root ? (root.host as Element) : null;
}

if (!customElements.get("rt-map")) customElements.define("rt-map", RtMap);
