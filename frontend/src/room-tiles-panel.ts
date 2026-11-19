// Room Tiles dashboard: the "Room Tiles" sidebar panel.
//
// First version: area picker + the area's tile grid (5x2 or 6x3), live from
// the integration's websocket feed, tiles controlling real entities.
// Map, editing and the map editor come next (see docs/DESIGN.md).

import { LitElement, css, html, nothing, type PropertyValues, type TemplateResult } from "lit";
import {
  LAYOUT_COLUMNS,
  PAYLOAD_SCHEMA,
  type Area,
  type CatalogEntry,
  type FeedMessage,
  type HassEntity,
  type HomeAssistant,
  type Layout,
  type RoomTilesDoc,
  type Tile,
} from "./types";
import {
  DEFAULT_THEME,
  hasArt,
  iconArt,
  type InstalledTheme,
  isInstalledId,
  setInstalledThemes,
  THEME_NAMES,
  themeCss,
  themeName,
  themeNames,
  type ThemeName,
} from "./theme";
import { LANG_NAMES, num, pct, setLanguage, t, th, tn } from "./i18n";
import { localText, localTile } from "./words";
import { STATIC_BASE, applianceStyles, parseUnits, renderAppliance } from "./appliance";
import { ARRANGE_OPS, arrange, MAX_ADD, numbered, pointBox, ringLayout, type ArrangeOp } from "./arrange";
import { fitBounds } from "./plan-model";
import { SheetDrag } from "./sheet-drag";
import { assetUrl } from "./theme";
import "./controls";
import { lightSwatch } from "./colorpicker";
import { areaAt, iconOn, layersOf, markerActive, MAX_LAYERS } from "./map";
import { queueInfo, queueMaps, queueProblem, queueView, roomState, ROOM_STATES, tileMap, type QueueInfo } from "./vacqueue";
import { areaName, canBeTile, fullName, profileSources } from "./picker";
import { NAV_IN_TOOLBAR_FROM, navFit, type NavFit } from "./nav-fit";
import "./editor";
import "./area-settings";
import "./panels-page";
import "./short-names";
import "./report";
import "./feedback";
import { watchErrors } from "./errors";
import "./appliances";
import { brandIcon, navRow, rowStyles, toggle, noSelectStyles, groupStyles, touchNote, touchNoteShown, touchNoteStyles, ScrollFades } from "./ui";
import type { Camera, MapData, MapLayer, MapMarker, MapZone, RtMap, ViewChoice } from "./map";
import "./map-help";
import "./unsaved";
import "./plan-editor";
import { TapGuard, keyIntent } from "./input";
import {
  CLIMATE_MAX_F,
  climateBand,
  climateCooling,
  climateRange,
  rollerCall,
  rollerRow,
  rollerSpec,
  settleMs,
  switchCall,
  isPoolSensor,
  detailsEntity,
  vacuumStatus,
  switchOn,
  switchTrack,
  tileIcon,
  type Call,
} from "./rules";

watchErrors(); // (Send feedback: the dashboard's recent errors)

/** A change the user made that HA hasn't confirmed yet (the panels' settle). */
interface Pending {
  row?: number;
  on?: boolean;
  until: number;
}

/** Roller placement on a 5x2 panel tile (tile.yaml): x offset from the
 *  centre and width, design px; selected-value font size. */
const ROLLER_GEOMETRY: Record<string, { x: number; w: number; font: number }> = {
  dimmable_light: { x: 44, w: 74, font: 28 },
  color_light: { x: 44, w: 74, font: 28 },
  fan: { x: 16, w: 72, font: 28 },
  cover: { x: 30, w: 84, font: 22 },
  lock: { x: 34, w: 96, font: 22 },
  climate: { x: 40, w: 70, font: 28 },
  water: { x: 40, w: 70, font: 28 },
};

// set by build.mjs; compared with the installed version.json
declare const BUILD_ID: string;

const STORE_AREA = "room-tiles:area";
const POPUP_MAX = 6; // a marker's pop-up row shows at most this many groups, and as many scenes
const UPDATED = "updated"; // _error: the integration sends newer data than this page reads
const RUN_FLASH_MS = 1500; // a scene / script button lights this long after a tap
// a newer dashboard: how often to look, and the quiet before reloading by itself
const VERSION_CHECK_MS = 60_000;
const RELOAD_QUIET_MS = 30_000;
const RELOAD_RETRY_MS = 5_000;
const STORE_RELOADED_FOR = "room-tiles:reloaded-for"; // (session) the build an auto reload went for
/** an undo / redo step of marker editing: the markers and the layers */
interface EditSnap {
  draft: MapMarker[];
  layers: MapLayer[];
}

const STORE_NAMES = "room-tiles:marker-names"; // the Layer Editor's Names / State choices (this browser)
const STORE_STATES = "room-tiles:marker-states";
const viewChoice = (key: string): ViewChoice => (["map", "on", "off"].includes(load(key) ?? "") ? (load(key) as ViewChoice) : "map");
const STORE_LAST_MAP = "room-tiles:last-map"; // the map open last (each map keeps its own view: map.ts)
/** marker editing's tools (the map editor's tool bar, smaller) */
type MarkerTool = "select" | "box" | "add";
const ADD_LAYER = "__add_layer"; // the layer list's "+ Add layer" entry

// (their words: layers.tool_<id> / layers.hint_<id>, read when drawn)
const MARKER_TOOLS: { id: MarkerTool; icon: string }[] = [
  { id: "select", icon: "mdi:cursor-default-outline" },
  { id: "box", icon: "mdi:selection-drag" },
  { id: "add", icon: "mdi:map-marker-plus-outline" },
];
// Tile layout PER AREA, per device (like the wall panels): {area id: "5x2" | "6x3"}
const STORE_LAYOUTS = "room-tiles:layouts";
// Animations, per device: follow the device's reduced-motion setting
// (default) / always / never. The one-time notice is shown when following a
// device that asks for reduced motion; choosing "follow" again re-arms it.
const STORE_MOTION = "room-tiles:animations";
const STORE_LANGUAGE = "room-tiles:language"; // this device's language ("" = Home Assistant's)
const STORE_THEME = "room-tiles:theme"; // this device's Room Tiles theme
const STORE_MOTION_NOTICE = "room-tiles:animations-notice-seen";
type MotionMode = "follow" | "always" | "never";
// Full screen in landscape (Room Tiles covers HA's sidebar + header), per
// device; default on for touch devices, off for mouse devices.
const STORE_COVER = "room-tiles:fullscreen-landscape";
// portrait: the grid turned - columns become rows (5x2 -> 2x5), scrolling
// down - or kept as on the panels (two columns, scrolling sideways); per
// device, turned unless switched off
const STORE_TURN = "room-tiles:portrait-turn";
const STORE_QUEUE_AUTOSTART = "room-tiles:queue-autostart"; // the room queue starts itself when a room is added (this browser)

// Grid geometry (CSS px). Portrait: tiles at the "2 wide" size, the panel's
// formation kept, panning both ways with snap; landscape: the whole grid
// fitted to the screen. TILE_ASPECT = the panel tile (198 x 254).
const GAP = 12;
const PAD = 16;
const PEEK = 28; // portrait: how much of the next column shows at the edge
const TILE_ASPECT = 198 / 254;
const TOOLBAR_H = 64;
// a narrow screen held upright: the top bar in two rows - the room's name
// across the top, the buttons under it (a one-row bar left the name no room)
const STACK_BELOW = 560; // px wide
const STACKED_H = TOOLBAR_H + 52;

function load(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function save(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode etc.: just not remembered */
  }
}

function forget(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    /* nothing remembered anyway */
  }
}


export class RoomTilesPanel extends LitElement {
  /** fades where a scrolling area has more (ui.ts ScrollFades) */
  protected readonly _scrollFades = new ScrollFades(this, ".menu[role=\"dialog\"], .picker, .navlist");

  static properties = {
    hass: { attribute: false },
    narrow: { type: Boolean },
    _doc: { state: true },
    _error: { state: true },
    _area: { state: true },
    _layouts: { state: true },
    _picker: { state: true },
    _pending: { state: true },
    _motion: { state: true },
    _language: { state: true },
    _reduced: { state: true },
    _menu: { state: true },
    _notice: { state: true },
    _tilesAsk: { state: true },
    _autoAsk: { state: true },
    _autoStart: { state: true },
    _box: { state: true },
    _cover: { state: true },
    _turn: { state: true },
    _coverOff: { state: true },
    _coverNow: { state: true },
    _view: { state: true },
    _colorFor: { state: true },
    _mapOpen: { state: true },
    _navFit: { state: true },
    _navOpen: { state: true },
    _mapZone: { state: true },
    _mapLayerId: { state: true },
    _mapLayersShown: { state: true },
    _mapEdit: { state: true },
    _sel: { state: true },
    _markerTool: { state: true },
    _touchNote: { state: true },
    _crossArea: { state: true },
    _mapHelp: { state: true },
    _help: { state: true },
    _mapPick: { state: true },
    _vacQueue: { state: true },
    _bandPreview: { state: true },
    _names: { state: true },
    _states: { state: true },
    _markerStack: { state: true },
    _askUnsaved: { state: true },
    _planDialog: { state: true },
    _planEdit: { state: true },
    _adding: { state: true },
    _popup: { state: true },
    _editing: { state: true },
    _editSlot: { state: true },
    _moveFrom: { state: true },
    _shortFocus: { state: true },
    _outdated: { state: true },
    _restartAsk: { state: true },
    _restarting: { state: true },
    _dialog: { state: true },
    _areaLightsFor: { state: true },
    _runFlash: { state: true },
    theme: { type: String },
  };

  hass?: HomeAssistant;
  narrow = false;
  /** This device's Room Tiles theme (⚙ → Theme). Never HA's theme colours. */
  theme: ThemeName = (() => {
    const saved = load(STORE_THEME) as ThemeName | null;
    // (an installed one: kept until the feed says whether it's still there)
    return saved && (THEME_NAMES.includes(saved) || isInstalledId(saved)) ? saved : DEFAULT_THEME;
  })();
  private _doc?: RoomTilesDoc;
  private _error?: string;
  private _area?: string;
  private _layouts: Record<string, Layout> = (() => {
    try {
      return JSON.parse(load(STORE_LAYOUTS) ?? "{}");
    } catch {
      return {};
    }
  })();

  /** The current area's layout on this device - until it picks one, the
   *  area's own (6x3 when its default tiles don't fit on 5x2), else 5x2. */
  private get _layout(): Layout {
    const id = this._current?.id;
    return (id && this._layouts[id]) || this._current?.layout || "5x2";
  }
  private _unsub?: Promise<() => Promise<void>>;
  private _picker = false; // the area picker overlay
  private _pending: Record<string, Pending> = {};
  private _motion: MotionMode = (load(STORE_MOTION) as MotionMode) || "follow";
  /** this device's language, overriding Home Assistant's ("" = follow HA) */
  private _language = load(STORE_LANGUAGE) ?? "";
  private _reduced = false;
  private _menu = false; // the settings menu
  private _notice = false; // the one-time reduced-motion notice
  // a device just set up whose tile wasn't added: its area's board is the user's
  private _tilesAsk?: { area: string; name: string };
  private _autoAsk?: "pick" | "all"; // "Auto configure" pressed: which boards, then (all) confirm
  private _autoStart = load(STORE_QUEUE_AUTOSTART) === "1"; // the room queue: adding a room starts it
  private _box = { w: 0, h: 0 }; // the panel's size
  private _cover =
    load(STORE_COVER) !== null ? load(STORE_COVER) === "1" : window.matchMedia("(pointer: coarse)").matches;
  private _coverOff = false; // "show HA" pressed: until the next turn to landscape
  private _coverNow = false; // full screen chosen with the button this visit
  private _view = { c0: 0, c1: 0, r0: 0, r1: 0 }; // portrait: visible tile range (as drawn)
  private _turn = load(STORE_TURN) !== "0"; // portrait: the grid turned (this device)
  private _resize?: ResizeObserver;
  private _colorFor?: { entity: string; name: string }; // the colour picker's light
  private _mapOpen?: string; // id of the map on screen
  private _mapFocus?: string; // the room to open zoomed into (the room picker)
  private _mapFocusArea?: string; // opened from a Map tile: its area's rooms, together
  private _mapRemember = true; // opened from the area picker: this visit saves the view
  private _navFit: NavFit = { maps: false, layers: false }; // map / layer groups collapsed to a button
  private _navOpen?: { which: "maps" | "layers"; left: number; top: number }; // a collapsed group's list
  private _mapZone?: MapZone | null; // the zone the map is zoomed into
  private _mapLayerId?: string; // the main layer showing (the latest to start)
  private _mapLayersShown: string[] = []; // every layer showing (lit in the layer group)
  /** map edit session: the map's markers as a draft, undo / redo history,
   *  the layer being edited (docs/UI.md: undo / redo) */
  /** placing markers: the draft (markers, and the layers - where each
   *  starts is set here), undo / redo snapshots of both */
  private _mapEdit?: { map: string; draft: MapMarker[]; layers: MapLayer[]; undo: EditSnap[]; redo: EditSnap[]; layer: string; next: number };
  private _editMapCache?: { base: MapData; layers: MapLayer[]; out: MapData };
  private _sel: string[] = []; // selected markers (map editing)
  private _addArea?: string; // the area the Add picker starts with
  /** the marker sheet can be dragged out of the way by its title row */
  private _sheetDrag = new SheetDrag(this, "room-tiles:sheet-markers");
  private _touchNote = touchNoteShown(); // marker editing: "best on a tablet or computer" (phones)
  private _markerTool: MarkerTool = "select"; // box: a drag draws a selection box; add: the crosshair
  private _crossArea?: string | null; // the area under the Add crosshair
  private _adding = false; // the Add picker
  private _mapHelp = false; // the map editor help dialog
  private _help?: "tiles" | "tile-edit"; // the tiles' / tile editor's Help page
  private _mapPick = false; // the map title's room picker
  private _vacQueue?: string; // a vacuum's room queue on the map: its robot sensor
  private _names: ViewChoice = viewChoice(STORE_NAMES);
  private _states: ViewChoice = viewChoice(STORE_STATES);
  private _markerStack?: string[]; // the Layer Editor's "Here:" row: markers under the last tap
  /** the Layer Editor to go back to after its layer settings link (the map editor) */
  private _returnTo?: { map: string; layer: string; layers: string[]; cam?: Camera };
  private _mapStartView?: Camera; // the map's view when it opens again (back from an editor)
  private _planEdit?: string; // the map open in the map editor (walls, rooms...)
  /** "Save your changes?" while placing markers: on closing the map, or on
   *  Cancel (leaving marker editing) - only when there are changes */
  private _askUnsaved: "" | "close-map" | "end-edit" | "layer-settings" | "go-room" | "leave" = "";
  private _afterAsk?: (ok: boolean) => void; // "leave": the menu's next screen may open
  private _goAfterAsk?: { map: string; zone: string }; // "go-room": where to, after Save / Discard
  private _planDialog?: "settings"; // the map editor opens on this dialog
  /** Browser close / reload while map edits are unsaved: the browser's own prompt. */
  private _onBeforeUnload = (e: BeforeUnloadEvent) => {
    if (this._mapEdit?.undo.length) e.preventDefault();
  };
  /** Map editing keys (input.ts): accelerators for what the buttons do. */
  private _onKey = (e: KeyboardEvent) => {
    const ed = this._mapEdit;
    if (!ed) return;
    if (this._mapHelp || this._adding || this._askUnsaved || this._mapPick) {
      if (e.key === "Escape") {
        this._mapHelp = this._adding = this._mapPick = false;
        this._askUnsaved = "";
      }
      return;
    }
    const k = keyIntent(e);
    if (!k) return;
    e.preventDefault();
    const map = this.renderRoot.querySelector<RtMap>("rt-map");
    switch (k.kind) {
      case "undo":
        return this._mapUndo();
      case "redo":
        return this._mapRedo();
      case "delete":
        return this._deleteSelected();
      case "clear":
        this._sel = [];
        return;
      case "select-all":
        this._sel = map?.visibleMarkerIds() ?? [];
        return;
      case "nudge": {
        if (!this._sel.length) return;
        // whole map units (markers are stored on them), whatever the zoom -
        // as the Map Editor's nudges: one marker lands exactly on another
        const step = k.big ? 10 : 1;
        const sel = new Set(this._sel);
        this._mapChange((d) =>
          d.map((m) => (sel.has(m.id) ? { ...m, x: Math.round(m.x) + k.dx * step, y: Math.round(m.y) + k.dy * step } : m)),
        );
        return;
      }
    }
  };
  private _popup?: { entity: string; kind: Tile["kind"]; x: number; y: number };
  private _popupTimer?: number;
  private _popupAt = 0; // when the pop-up tile opened
  private _editing = false; // tile edit mode
  private _editSlot?: number; // the slot whose editor is open
  private _moveFrom?: number; // the slot picked up for a swap
  private _shortFocus?: string; // the Short names dialog opened on this entity
  private _outdated = false; // a newer build is installed than this page runs
  private _restartAsk = false; // the Restart bar's confirm is open
  private _restarting = false; // Restart pressed: reload as soon as HA is back
  private _newBuild?: string; // ...that build
  private _lastInput = Date.now(); // the last touch / click / key (auto reload waits for quiet)
  // when the page / a linked dialog was shown: no input since = nothing to lose
  private _shownAt = Date.now();
  private _versionTimer?: number;
  private _reloadTimer?: number;
  private _onVisible = () => {
    if (document.visibilityState === "visible") void this._checkVersion();
  };
  private _onInput = () => {
    this._lastInput = Date.now();
  };
  // a long press (touch) / right-click is Room Tiles' own gesture: the
  // browser's menu never opens over it - except in text fields and links,
  // where copy / paste / open in a new tab are useful
  // a sideways swipe / touchpad scroll nothing here can scroll further:
  // swallowed, so Chrome's swipe-back (history) never fires over Room Tiles
  // (CSS overscroll-behavior misses touchpad / remote-desktop scrolls)
  private _onWheel = (e: WheelEvent) => {
    if (Math.abs(e.deltaX) <= Math.abs(e.deltaY)) return;
    for (const n of e.composedPath()) {
      if (!(n instanceof HTMLElement)) continue;
      const ox = getComputedStyle(n).overflowX;
      if ((ox === "auto" || ox === "scroll") && n.scrollWidth > n.clientWidth) {
        const atStart = n.scrollLeft <= 0;
        const atEnd = n.scrollLeft + n.clientWidth >= n.scrollWidth - 1;
        if ((e.deltaX < 0 && !atStart) || (e.deltaX > 0 && !atEnd)) return; // it scrolls
      }
      if (n === this) break;
    }
    e.preventDefault();
  };
  private _onContextMenu = (e: Event) => {
    const t = e.composedPath()[0] as HTMLElement | undefined;
    if (t?.closest?.("input, textarea, select, a[href], [contenteditable]")) return;
    e.preventDefault();
  };
  private _dialog?: "areas" | "short-names" | "appliances" | "panels" | "report-test" | "feedback"; // Room Tiles settings dialogs
  private _areaLightsFor?: string; // area whose lights settings are open
  private _pressTimer?: number;
  private _pressed?: { slot: number; long: boolean };
  private _lastSwatch: Record<string, string> = {}; // a light's colour while it's off
  // the colour picker's chosen colour per light until HA confirms it (groups
  // report in-between colours while their members change)
  private _swatchHold: Record<string, { colour: string; until: number }> = {};
  // a scene / script button's flash after a tap (until when)
  private _runFlash: Record<string, number> = {};
  // a pool / spa heater button's tap until HA confirms it (the water settle)
  private _heaterHold: Record<string, { on: boolean; until: number }> = {};
  private _mq?: MediaQueryList;
  private _onMq = () => {
    this._reduced = !!this._mq?.matches;
    this._checkNotice();
  };
  private _pendingTimer?: number;

  // the top bar's time (like the panels'): the user's own time format and
  // time zone from their HA profile; shown only when it fits whole
  private _clockTimer?: number;
  private _clockMinute = 0;
  private _clockFit?: ResizeObserver;
  private _clockBox?: HTMLElement;

  private _clockText(): string {
    const loc = this.hass?.locale;
    const hour12 = loc?.time_format === "12" ? true : loc?.time_format === "24" ? false : undefined;
    const lang = loc?.time_format === "system" ? undefined : (loc?.language ?? this.hass?.language);
    const timeZone = loc?.time_zone === "server" ? this.hass?.config?.time_zone : undefined;
    const opts: Intl.DateTimeFormatOptions = { hour: "numeric", minute: "2-digit", hour12, timeZone };
    try {
      return new Intl.DateTimeFormat(lang, opts).format(new Date());
    } catch {
      return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date());
    }
  }

  /** The time hidden (not cut) when the room between the buttons is too small. */
  private _fitClock(): void {
    const box = this.renderRoot.querySelector<HTMLElement>(".bar-clock");
    if (box !== this._clockBox) {
      this._clockFit?.disconnect();
      this._clockBox = box ?? undefined;
      if (box) {
        this._clockFit ??= new ResizeObserver(() => this._fitClock());
        this._clockFit.observe(box);
      }
    }
    const text = box?.firstElementChild as HTMLElement | null;
    if (box && text) text.style.visibility = text.scrollWidth <= box.clientWidth ? "" : "hidden";
  }

  connectedCallback(): void {
    super.connectedCallback();
    // the top bar's time: redrawn when the minute changes
    this._clockTimer = window.setInterval(() => {
      const minute = Math.floor(Date.now() / 60000);
      if (minute !== this._clockMinute) {
        this._clockMinute = minute;
        this.requestUpdate();
      }
    }, 1000);
    this._shownAt = Date.now(); // (HA shows the panel again: same element)
    this._resize = new ResizeObserver(() => this._measure());
    this._resize.observe(this);
    window.addEventListener("resize", this._onWindowResize);
    document.addEventListener("visibilitychange", this._onVisible);
    window.addEventListener("pointerdown", this._onInput, true);
    this.addEventListener("pointerdown", this._onTapDown, true);
    this.addEventListener("click", this._onTapClick, true);
    this.addEventListener("contextmenu", this._onContextMenu);
    this.addEventListener("wheel", this._onWheel, { passive: false });
    window.addEventListener("keydown", this._onInput, true);
    // a newer dashboard installed (an update, a rebuild): checked every minute while on screen
    this._versionTimer = window.setInterval(() => {
      if (document.visibilityState === "visible") void this._checkVersion();
    }, VERSION_CHECK_MS);
    window.addEventListener("keydown", this._onKey);
    window.addEventListener("beforeunload", this._onBeforeUnload);
    this.addEventListener("tiles-ask", this._onTilesAsk as EventListener);
    this._mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    this._mq.addEventListener("change", this._onMq);
    this._onMq();
    const params = new URLSearchParams(location.search);
    const fromUrl = params.get("area");
    this._area = fromUrl || load(STORE_AREA) || undefined;
    this._openFromUrl();
    // HA's own links (a notification's) navigate without reloading - also
    // while Room Tiles is the page already open
    window.addEventListener("location-changed", this._openFromUrl);
    window.addEventListener("popstate", this._openFromUrl);
    if (this.hass) this._subscribe();
  }

  /** `?open=appliances` / `?open=short-names` (links from HA: setup's closing
   *  message, the notifications): that dialog opens, the parameter goes. */
  private _openFromUrl = (): void => {
    const params = new URLSearchParams(location.search);
    const open = params.get("open");
    if (open !== "appliances" && open !== "short-names") return;
    this._menu = false;
    this._dialog = open;
    this._shownAt = Date.now();
    params.delete("open");
    const q = params.toString();
    history.replaceState(history.state, "", location.pathname + (q ? `?${q}` : "") + location.hash);
  };

  // the tiles: a click only when the press stayed put (input.ts TAP_SLOP_PX -
  // the panels' rule); the map and the editors read their own gestures
  private _tap = new TapGuard();
  private _onTapDown = (e: PointerEvent): void => this._tap.down(e);
  private _onTapClick = (e: MouseEvent): void => {
    const onTiles = e.composedPath().some((n) => n instanceof HTMLElement && n.classList.contains("grid-wrap"));
    if (onTiles && this._tap.tapMoved(e)) {
      e.stopPropagation();
      e.preventDefault();
    }
  };

  disconnectedCallback(): void {
    super.disconnectedCallback();
    window.clearInterval(this._clockTimer);
    this._clockFit?.disconnect();
    this._clockBox = undefined;
    this._mq?.removeEventListener("change", this._onMq);
    this._resize?.disconnect();
    window.removeEventListener("resize", this._onWindowResize);
    document.removeEventListener("visibilitychange", this._onVisible);
    window.removeEventListener("pointerdown", this._onInput, true);
    this.removeEventListener("pointerdown", this._onTapDown, true);
    this.removeEventListener("click", this._onTapClick, true);
    this.removeEventListener("contextmenu", this._onContextMenu);
    this.removeEventListener("wheel", this._onWheel);
    window.removeEventListener("keydown", this._onInput, true);
    window.clearInterval(this._versionTimer);
    window.clearTimeout(this._reloadTimer);
    window.removeEventListener("keydown", this._onKey);
    window.removeEventListener("beforeunload", this._onBeforeUnload);
    this.removeEventListener("tiles-ask", this._onTilesAsk as EventListener);
    window.removeEventListener("location-changed", this._openFromUrl);
    window.removeEventListener("popstate", this._openFromUrl);
    this._unsubscribe();
  }

  protected willUpdate(changed: PropertyValues): void {
    // HA's language: the dashboard's wording (i18n.ts) - set before anything
    // renders with it (the dialogs read it when they draw)
    if (changed.has("hass") || changed.has("_language"))
      setLanguage(this._language || this.hass?.locale?.language || this.hass?.language);
    // placing markers: the "Here:" row shows any selection - one it doesn't
    // cover (Shift-click, Select all...) becomes the row
    // the settings menu opened: Room Tiles looks for new or changed installed themes
    if (changed.has("_menu") && this._menu) void this.hass?.connection.sendMessagePromise?.({ type: "room_tiles/themes_check" }).catch(() => undefined);
    const st = this._markerStack;
    if (changed.has("_sel") && this._mapEdit && this._sel.length && !(st && this._sel.every((id) => st.includes(id))))
      this._markerStack = [...this._sel];
  }

  protected updated(changed: PropertyValues): void {
    this._fitClock(); // (the top bar's time: shown only when it fits)
    if (changed.has("hass") && this.hass && !this._unsub) this._subscribe();
    if (changed.has("_mapOpen") && this._mapOpen && this._mapRemember) save(STORE_LAST_MAP, this._mapOpen);
    if (changed.has("theme")) {
      this.setAttribute("style", themeCss(this.theme));
      this._measure(); // re-apply --rt-top (setAttribute replaced the style)
      this.setAttribute("data-theme", this.theme);
    }
    if (changed.has("_cover") || changed.has("_coverOff") || changed.has("_coverNow") || changed.has("_box")) {
      this.toggleAttribute("data-cover", this._covering);
    }
    requestAnimationFrame(() => this._updateView());
    if (changed.has("_picker") && this._picker)
      // the area you're in, in view (a long list scrolls)
      this.renderRoot.querySelector(".picker .pick.selected")?.scrollIntoView({ block: "nearest" });
    this._fitNav(); // (no map screen: nothing to measure)
    if (changed.has("_motion") || changed.has("_reduced")) {
      this.setAttribute("data-motion", this._motionOn ? "on" : "off");
    }
  }

  // ---- data feed --------------------------------------------------------------

  private _subscribe(): void {
    if (!this.hass || this._unsub) return;
    this._unsub = this.hass.connection.subscribeMessage<FeedMessage>(
      (msg) => this._onFeed(msg),
      { type: "room_tiles/subscribe" },
    );
    this._unsub.catch((err: { message?: string }) => {
      this._error = err?.message || "not set up"; // (the screen says it in the language)
      this._unsub = undefined;
    });
  }

  private _unsubscribe(): void {
    const unsub = this._unsub;
    this._unsub = undefined;
    unsub?.then((fn) => fn()).catch(() => undefined);
  }

  private _onFeed(msg: FeedMessage): void {
    if (msg.type === "reset") {
      // Room Tiles was reloaded: subscribe again
      this._unsubscribe();
      window.setTimeout(() => this._subscribe(), 1000);
      return;
    }
    if (msg.schema > PAYLOAD_SCHEMA) {
      this._error = UPDATED;
      return;
    }
    this._error = undefined;
    if (msg.type === "full") void this._checkVersion(); // (re)connected: maybe HA was restarted / updated
    this._doc = msg.type === "full" ? msg.data : ({ ...this._doc, ...msg.data } as RoomTilesDoc);
    if (msg.data.themes) this._installedThemes(msg.data.themes.themes);
    // back after the Restart bar's restart: onto the new dashboard
    if (msg.type === "full" && this._restarting && !this._doc?.restart_needed) location.reload();
    const waiting = this._docWaiters;
    this._docWaiters = [];
    for (const w of waiting) w();
  }

  private _docWaiters: (() => void)[] = [];

  /** Resolves once HA has sent the document again (or after `ms`). */
  private _nextDoc(ms = 4000): Promise<void> {
    return new Promise((resolve) => {
      const t = window.setTimeout(resolve, ms);
      this._docWaiters.push(() => {
        window.clearTimeout(t);
        resolve();
      });
    });
  }

  // ---- stale page check ----------------------------------------------------------

  /** Is a newer dashboard installed than this page is running? (An open page
   *  keeps its code across HA restarts and updates.) */
  private async _checkVersion(): Promise<void> {
    try {
      const r = await fetch(`${STATIC_BASE}/version.json`, { cache: "no-store" });
      if (!r.ok) return;
      const { build } = await r.json();
      this._outdated = typeof BUILD_ID !== "undefined" && !!build && build !== BUILD_ID;
      this._newBuild = this._outdated ? build : undefined;
      // (HA still runs the old backend: stay on this page until it restarts)
      if (this._outdated && !this._doc?.restart_needed) this._autoReload();
    } catch {
      /* offline etc.: try again next time */
    }
  }

  /** The bar on top after an update: restart HA to finish (the backend is
   *  behind - admins get a Restart button), else reload onto the new build. */
  private _updateBar(): unknown {
    if (this._doc?.restart_needed || this._restarting) {
      const admin = !!this.hass?.user?.is_admin;
      return html`<div class="outdated" role="status">
          ${this._restarting ? t("screen.restarting") : t("screen.restart_bar")}
          ${admin && !this._restarting
            ? html`<button @click=${() => (this._restartAsk = true)}>${t("screen.restart")}</button>`
            : nothing}
        </div>
        ${this._restartAsk
          ? html`<div class="scrim dim" style="z-index:40" @click=${() => (this._restartAsk = false)}></div>
              <div class="notice" style="z-index:41" role="alertdialog" aria-labelledby="restart-title">
                <div class="menu-title" id="restart-title">${t("screen.restart_title")}</div>
                <div class="actions">
                  <button class="secondary" @click=${() => (this._restartAsk = false)}>${t("common.cancel")}</button>
                  <button class="primary" @click=${() => this._restart()}>${t("screen.restart")}</button>
                </div>
              </div>`
          : nothing}`;
    }
    return this._outdated
      ? html`<div class="outdated" role="status">
          ${t("screen.updated_bar")}
          <button @click=${() => location.reload()}>${t("screen.reload")}</button>
        </div>`
      : nothing;
  }

  private _restart(): void {
    this._restartAsk = false;
    this._restarting = true;
    void this.hass?.callService("homeassistant", "restart").catch(() => {
      /* the connection drops as HA goes down: expected */
    });
  }

  /** Nothing the user could lose: no editor, dialog, menu or Help open. */
  private get _atRest(): boolean {
    return !(
      this._editing ||
      this._editSlot !== undefined ||
      this._menu ||
      this._picker ||
      this._dialog ||
      this._autoAsk ||
      this._tilesAsk ||
      this._colorFor ||
      this._help ||
      this._mapHelp ||
      this._mapEdit ||
      this._mapPick ||
      this._planDialog ||
      this._planEdit ||
      this._popup ||
      this._areaLightsFor ||
      this._askUnsaved ||
      this._adding ||
      this._restartAsk
    );
  }

  /** A newer build is installed: reload by itself - right away while
   *  nothing was touched since the page / a linked dialog showed, else once
   *  it's at rest and quiet a while (the Reload bar shows meanwhile). Once per
   *  build - if the reload didn't pick it up (a cache), the bar stays. */
  private _autoReload(): void {
    window.clearTimeout(this._reloadTimer);
    const build = this._newBuild;
    if (!this._outdated || !build) return;
    let tried: string | null = null;
    try {
      tried = sessionStorage.getItem(STORE_RELOADED_FOR);
    } catch {
      /* no storage: just reload */
    }
    if (tried === build) return;
    // untouched since it was shown (e.g. opened from a link after an
    // install): reload now, onto the same dialog
    const untouched = this._lastInput <= this._shownAt;
    const quiet = this._atRest && Date.now() - this._lastInput >= RELOAD_QUIET_MS;
    if ((untouched || quiet || this._restarting) && document.visibilityState === "visible") {
      try {
        sessionStorage.setItem(STORE_RELOADED_FOR, build);
      } catch {
        /* reloads anyway */
      }
      if (this._dialog === "appliances" || this._dialog === "short-names") {
        const url = new URL(location.href);
        url.searchParams.set("open", this._dialog);
        history.replaceState(history.state, "", url.pathname + url.search + url.hash);
      }
      location.reload();
      return;
    }
    this._reloadTimer = window.setTimeout(() => this._autoReload(), RELOAD_RETRY_MS);
  }

  // ---- layout: portrait panning / landscape fit / full screen -----------------

  private _onWindowResize = () => {
    const wasPortrait = this._portraitWindow;
    this._portraitWindow = window.innerHeight > window.innerWidth;
    if (wasPortrait && !this._portraitWindow) this._coverOff = false; // turned to landscape
    this._measure();
  };
  private _portraitWindow = window.innerHeight > window.innerWidth;

  private _measure(): void {
    const w = this.clientWidth;
    const h = this.clientHeight;
    if (w !== this._box.w || h !== this._box.h) this._box = { w, h };
    // where this page starts on screen (below a phone's status bar in the HA
    // app): dialogs stay below it (ui.ts dialogStyles, --rt-top)
    const rect = this.getBoundingClientRect();
    const top = Math.max(0, Math.round(rect.top));
    this.style.setProperty("--rt-top", `${top}px`);
    // ...and across: dialogs centre on this page, not the window (HA's
    // sidebar would cover a wide one's left side)
    this.style.setProperty("--rt-left", `${Math.max(0, Math.round(rect.left))}px`);
    this.style.setProperty("--rt-width", `${Math.round(rect.width)}px`);
  }

  private get _portrait(): boolean {
    return this._portraitWindow;
  }

  /** Room Tiles covers HA's sidebar and header (landscape, setting on). */
  private get _covering(): boolean {
    return !this._portrait && (this._cover || this._coverNow) && !this._coverOff;
  }

  /** The way back to HA: in full screen, leave it (HA's sidebar returns);
   *  otherwise open HA's menu drawer (portrait / collapsed sidebar), the same
   *  as HA's own menu button. */
  private _haMenu(): void {
    if (this._covering) {
      this._coverOff = true;
      return;
    }
    this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }));
  }

  /** Landscape: back to full screen (kiosk) - for this visit, also on a
   *  device whose setting is off (the setting itself doesn't change). */
  private _fullScreen(): void {
    this._coverOff = false;
    this._coverNow = true;
  }

  private _setTurn(on: boolean): void {
    this._turn = on;
    save(STORE_TURN, on ? "1" : "0");
    this.renderRoot.querySelector(".grid-wrap")?.scrollTo(0, 0);
  }

  /** A narrow screen held upright: the top bar in two rows (STACK_BELOW). */
  private get _stacked(): boolean {
    return this._portrait && this._box.w > 0 && this._box.w < STACK_BELOW;
  }

  /** Portrait with the grid turned: slot (column c, row r) drawn at
   *  column r, row c - the tiles keep their slots, only the drawing turns. */
  private get _turned(): boolean {
    return this._portrait && this._turn;
  }

  private _setCover(on: boolean): void {
    this._cover = on;
    this._coverOff = false;
    save(STORE_COVER, on ? "1" : "0");
  }

  /** Tile width in CSS px for the current orientation and layout. */
  private _tileWidth(cols: number, rows: number): number {
    const { w, h } = this._box;
    if (!w || !h) return 0;
    if (this._turned) {
      // turned: every column across the screen (2 or 3), scrolling down
      return Math.max(80, (w - 2 * PAD - (cols - 1) * GAP) / cols);
    }
    if (this._portrait) {
      // the "2 wide" size, the next column peeking in when there is one
      const peek = cols > 2 ? PEEK : 0;
      return Math.max(100, (w - 2 * PAD - GAP - peek) / 2);
    }
    const byWidth = (w - 2 * PAD - (cols - 1) * GAP) / cols;
    const byHeight = ((h - TOOLBAR_H - PAD - (rows - 1) * GAP) / rows) * TILE_ASPECT;
    return Math.max(80, Math.min(byWidth, byHeight));
  }

  private _grid = { tileW: 0, cols: 1, rows: 1 }; // from the last render

  private _updateView(): void {
    const el = this.renderRoot.querySelector<HTMLElement>(".grid-wrap");
    if (!el) return;
    const { tileW, cols, rows } = this._grid;
    const stepX = tileW + GAP;
    const stepY = tileW / TILE_ASPECT + GAP;
    const view = {
      c0: Math.max(0, Math.floor((el.scrollLeft + GAP) / stepX)),
      c1: Math.min(cols - 1, Math.floor((el.scrollLeft + el.clientWidth - PAD - 1) / stepX)),
      r0: Math.max(0, Math.floor((el.scrollTop + GAP) / stepY)),
      r1: Math.min(rows - 1, Math.floor((el.scrollTop + el.clientHeight - PAD - 1) / stepY)),
    };
    const v = this._view;
    if (v.c0 !== view.c0 || v.c1 !== view.c1 || v.r0 !== view.r0 || v.r1 !== view.r1) this._view = view;
  }

  /** A dialog, menu or picker over the tiles: the tiles can't be scrolled
   *  meanwhile (on a phone a drag on a part of the dialog that doesn't
   *  scroll - its title, a short list - would scroll the tiles behind it). */
  private _modalOpen(): boolean {
    return !!(
      this._dialog ||
      this._menu ||
      this._picker ||
      this._help ||
      this._editSlot !== undefined ||
      this._colorFor ||
      this._areaLightsFor ||
      this._autoAsk ||
      this._tilesAsk ||
      this._restartAsk ||
      this._vacQueue
    );
  }

  private _renderIndicator(cols: number, rows: number, tileW: number): TemplateResult | typeof nothing {
    if (!this._portrait || !tileW) return nothing;
    const { w, h } = this._box;
    const fitsX = cols * tileW + (cols - 1) * GAP + 2 * PAD <= w;
    const fitsY = rows * (tileW / TILE_ASPECT) + (rows - 1) * GAP + (this._stacked ? STACKED_H : TOOLBAR_H) + PAD <= h;
    if (fitsX && fitsY) return nothing;
    const v = this._view;
    return html`<div class="where" style="--cols:${cols}" aria-hidden="true">
      ${Array.from({ length: cols * rows }, (_, i) => {
        const c = i % cols;
        const r = Math.floor(i / cols);
        const seen = c >= v.c0 && c <= v.c1 && r >= v.r0 && r <= v.r1;
        return html`<span class=${seen ? "seen" : ""}></span>`;
      })}
    </div>`;
  }

  // ---- tile edit mode ------------------------------------------------------------
  // Tap a tile: its editor. Long press: pick it up, then tap another slot to
  // swap the two (like the panels). Changes go through the room_tiles actions.

  private _editDown(slot: number): void {
    window.clearTimeout(this._pressTimer);
    this._pressed = { slot, long: false };
    this._pressTimer = window.setTimeout(() => {
      if (this._pressed?.slot === slot) {
        this._pressed.long = true;
        this._moveFrom = this._moveFrom === slot ? undefined : slot;
        navigator.vibrate?.(20);
      }
    }, 450);
  }

  private _editUp(): void {
    window.clearTimeout(this._pressTimer);
  }

  /** On the CLICK, not on pointer-up: on touch screens the click comes after
   *  the finger lifts, so an editor opened on pointer-up would get that click
   *  on its backdrop and close at once. */
  private _editTap(slot: number): void {
    const pressed = this._pressed;
    this._pressed = undefined;
    if (pressed?.long) return; // that press picked the tile up
    const from = this._moveFrom;
    if (from !== undefined) {
      this._moveFrom = undefined;
      if (from !== slot) {
        this.hass?.callService("room_tiles", "move_tile", { area: this._current!.id, layout: this._layout, from_slot: from, to_slot: slot });
      }
      return;
    }
    this._editSlot = slot;
  }

  private _onTilesAsk = (e: CustomEvent<{ areas: string[]; name: string }>) => {
    this._tilesAsk = { area: e.detail.areas[0], name: e.detail.name };
  };

  /** "Open tile editor" on the ask: that area's board, in the tile editor. */
  private _addTileThere(area: string): void {
    this._tilesAsk = undefined;
    this._dialog = undefined;
    this._menu = false;
    this._mapOpen = undefined;
    this._selectArea(area);
    if (!this._editing) this._toggleEditing();
  }

  /** Auto configure: this board, both of this area's, or every area's. */
  private _autoConfigure(scope: "board" | "area" | "all"): void {
    const area = this._current;
    this._autoAsk = undefined;
    if (scope !== "all" && !area) return;
    const data = scope === "board" ? { area: area!.id, layout: this._layout } : scope === "area" ? { area: area!.id } : {};
    void this.hass?.callService("room_tiles", "auto_board", data);
  }

  private _renderAsks(): TemplateResult {
    const ask = this._tilesAsk;
    const areaName = ask && (this._doc?.areas.find((a) => a.id === ask.area)?.name ?? ask.area);
    return html`${ask
      ? html`<div class="scrim dim" style="z-index:40"></div>
          <div class="notice" style="z-index:41" role="alertdialog" aria-labelledby="ask-title">
            <div class="menu-title" id="ask-title">${t("panel.add_to_area", { name: ask.name, area: areaName ?? "" })}</div>
            <div class="actions">
              <button class="secondary" @click=${() => (this._tilesAsk = undefined)}>${t("panel.not_now")}</button>
              <button class="primary" @click=${() => this._addTileThere(ask.area)}>${t("panel.open_tile_editor")}</button>
            </div>
          </div>`
      : nothing}
    ${this._autoAsk === "pick"
      ? html`<div class="scrim dim" style="z-index:40"></div>
          <div class="notice" style="z-index:41" role="alertdialog" aria-labelledby="auto-title">
            <div class="menu-title" id="auto-title">${t("panel.auto")}</div>
            <p>${t("panel.auto_intro")}</p>
            <div class="choices">
              <button class="secondary" @click=${() => this._autoConfigure("board")}>${t("panel.auto_board")}</button>
              <button class="secondary" @click=${() => this._autoConfigure("area")}>
                ${t("panel.auto_area", { area: this._current?.short_name ?? "" })}
              </button>
              <button class="secondary" @click=${() => (this._autoAsk = "all")}>${t("panel.auto_all")}</button>
            </div>
            <div class="actions">
              <button class="secondary" @click=${() => (this._autoAsk = undefined)}>${t("common.cancel")}</button>
            </div>
          </div>`
      : this._autoAsk === "all"
      ? html`<div class="scrim dim" style="z-index:40"></div>
          <div class="notice" style="z-index:41" role="alertdialog" aria-labelledby="auto-title">
            <div class="menu-title" id="auto-title">${t("panel.auto_all_title")}</div>
            <p>${t("panel.auto_all_intro")}</p>
            <div class="actions">
              <button class="secondary" @click=${() => (this._autoAsk = undefined)}>${t("common.cancel")}</button>
              <button class="primary" @click=${() => this._autoConfigure("all")}>${t("panel.auto_all_go")}</button>
            </div>
          </div>`
      : nothing}`;
  }

  private _toggleEditing(): void {
    this._editing = !this._editing;
    this._moveFrom = undefined;
    this._editSlot = undefined;
  }

  // ---- the map ----------------------------------------------------------------

  private get _maps(): MapData[] {
    return (this._doc?.maps as MapData[] | undefined) ?? [];
  }

  /** The maps the map view offers: not one whose rooms ALL belong to areas
   *  hidden in Room Tiles (a starter map of hidden areas) - it's back once
   *  one of them is shown again. The editors list every map. */
  private get _viewMaps(): MapData[] {
    const hidden = new Set((this._doc?.areas ?? []).filter((a) => a.hidden).map((a) => a.id));
    const shown = (m: MapData) => {
      const rooms = m.zones.filter((z) => !z.vacuum);
      return !rooms.length || !rooms.every((z) => z.area && hidden.has(z.area));
    };
    const out = this._maps.filter(shown);
    return out.length ? out : this._maps;
  }

  /** Open the map. From the area picker ("picker"): the map and view left
   *  last time (this browser), and only such a visit saves the view as you
   *  pan / zoom / change maps. From a Map tile ("tile"): the map holding the
   *  board's area, zoomed so the area is in full view - and it never saves
   *  (a stray drag there can't overwrite the saved view). */
  private _openMap(from: "picker" | "tile" = "picker"): void {
    const area = this._current;
    const maps = this._viewMaps;
    const last = maps.find((m) => m.id === load(STORE_LAST_MAP));
    const roomOf = (m: MapData) => (area ? m.zones.find((z) => z.area === area.id && !z.vacuum) : undefined);
    this._mapZone = null;
    this._mapRemember = from === "picker";
    if (from === "tile") {
      // the map used last (this browser), if this area has a room on it -
      // else the first map (in the maps' order) that does; all of the area's
      // rooms on it in view together
      const map = (last && roomOf(last) ? last : undefined) ?? maps.find((m) => roomOf(m));
      if (map) {
        this._mapOpen = map.id;
        this._mapFocus = undefined;
        this._mapFocusArea = area!.id;
        return;
      }
    }
    // the map you had open last, else the one with this area
    this._mapFocus = undefined;
    this._mapFocusArea = undefined;
    const withArea = maps.find((m) => roomOf(m));
    this._mapOpen = (last ?? withArea ?? maps[0])?.id;
  }

  /** Settings menu "Edit map": the map editor on the map holding the current
   *  area (closing it leaves that map open). */
  /** Settings menu "Layer editor": the map (where it was left), placing
   *  markers. */
  private _openLayerEditor(): void {
    if (this._mapEdit) return;
    if (this._editing) this._toggleEditing();
    if (!this._mapOpen) this._openMap(); // the open map stays where it is
    const map = this._maps.find((m) => m.id === this._mapOpen);
    if (map) void this.updateComplete.then(() => this._startMapEdit(map));
  }

  /** The Short names dialog - THE place short names change - on an entity. */
  private _openShortNames(entity?: string): void {
    this._shortFocus = entity;
    this._dialog = "short-names";
  }

  private _openMapEditor(): void {
    if (this._mapEdit) return; // placing markers: finish that first
    if (this._editing) this._toggleEditing();
    if (this._mapOpen) this._mapZone = null;
    else this._openMap();
    this._planEdit = this._mapOpen;
  }

  // ---- map editing (markers): a draft with undo / redo; Save = set_markers --------

  private _startMapEdit(map: MapData, want?: string, suit = true): void {
    const draft = ((this._doc?.markers as MapMarker[] | undefined) ?? []).filter((m) => m.map === map.id).map((m) => ({ ...m }));
    const pick = want ?? this._mapLayerId;
    const layer = pick && map.layers?.some((l) => l.id === pick) ? pick : map.layers?.[0]?.id ?? "house";
    this._mapEdit = { map: map.id, draft, layers: layersOf(map).map((l) => ({ ...l })), undo: [], redo: [], layer, next: 1 };
    this._popup = undefined;
    // a zoom that doesn't suit the layer (e.g. a Map tile's room view): to
    // where the layer starts
    if (suit) void this.updateComplete.then(() => this.renderRoot.querySelector<RtMap>("rt-map")?.suitLayer(layer));
  }

  /** One undoable step: snapshot, then change a copy of the draft. */
  private _mapChange(fn: (draft: MapMarker[]) => MapMarker[] | void): void {
    const ed = this._mapEdit;
    if (!ed) return;
    const copy = ed.draft.map((m) => ({ ...m }));
    const out = fn(copy) ?? copy;
    this._mapEdit = { ...ed, draft: out, undo: [...ed.undo, { draft: ed.draft, layers: ed.layers }].slice(-100), redo: [] };
  }

  /** Where layer `id` starts / ends (its zoom range; null end: no end) -
   *  an undoable step of the draft. Layers overlap freely; a start stays
   *  under its end, an end above its start. */
  private _setLayerRange(id: string, patch: { min_zoom?: number; max_zoom?: number | null }): void {
    const ed = this._mapEdit;
    const l = ed?.layers.find((x) => x.id === id);
    if (!ed || !l) return;
    const r2 = (v: number) => Math.round(v * 100) / 100;
    let min = l.min_zoom;
    let max = l.max_zoom ?? null;
    if (patch.min_zoom !== undefined && Number.isFinite(patch.min_zoom)) min = r2(Math.min(max ?? 20, 20, Math.max(0.25, patch.min_zoom)) - (max != null && patch.min_zoom >= max ? 0.05 : 0));
    if (patch.max_zoom !== undefined) max = patch.max_zoom == null || !Number.isFinite(patch.max_zoom) ? null : r2(Math.max(min + 0.05, Math.min(40, patch.max_zoom)));
    if (min === l.min_zoom && max === (l.max_zoom ?? null)) return;
    const layers = ed.layers.map((x) => (x.id === id ? { ...x, min_zoom: min, max_zoom: max } : x));
    this._mapEdit = { ...ed, layers, undo: [...ed.undo, { draft: ed.draft, layers: ed.layers }].slice(-100), redo: [] };
  }

  /** A layer button lit: that layer is showing now (several can be). */
  private _layerLit(id: string): boolean {
    return this._mapLayersShown.length ? this._mapLayersShown.includes(id) : id === this._mapLayerId;
  }

  /** The open map with the draft's layers (rt-map: the zoom box, warnings) -
   *  the same object while nothing changed. */
  private _editMap(map: MapData): MapData {
    const ed = this._mapEdit;
    if (!ed || ed.map !== map.id) return map;
    const c = this._editMapCache;
    if (c && c.base === map && c.layers === ed.layers) return c.out;
    const out = { ...map, layers: ed.layers };
    this._editMapCache = { base: map, layers: ed.layers, out };
    return out;
  }

  private _mapUndo(): void {
    const ed = this._mapEdit;
    if (!ed?.undo.length) return;
    const prev = ed.undo[ed.undo.length - 1];
    this._mapEdit = { ...ed, draft: prev.draft, layers: prev.layers, undo: ed.undo.slice(0, -1), redo: [...ed.redo, { draft: ed.draft, layers: ed.layers }] };
  }

  private _mapRedo(): void {
    const ed = this._mapEdit;
    if (!ed?.redo.length) return;
    const next = ed.redo[ed.redo.length - 1];
    this._mapEdit = { ...ed, draft: next.draft, layers: next.layers, redo: ed.redo.slice(0, -1), undo: [...ed.undo, { draft: ed.draft, layers: ed.layers }] };
  }

  /** Marker editing's "change a layer's zoom setting here": the map editor,
   *  on Map settings (the layers). Unsaved marker edits: ask first. */
  private _openLayerSettings(): void {
    const map = this._mapOpen;
    if (!map) return;
    // back to the Layer Editor afterwards - same map, layer and view
    if (this._mapEdit && !this._returnTo)
      this._returnTo = {
        map,
        layer: this._mapEdit.layer,
        layers: this._mapEdit.layers.map((l) => l.id), // one added meanwhile: back on it
        cam: this.renderRoot.querySelector<RtMap>("rt-map")?.camera(),
      };
    if (this._mapEdit?.undo.length) {
      this._askUnsaved = "layer-settings";
      return;
    }
    this._endMapEdit();
    this._mapZone = null;
    this._planDialog = "settings";
    this._planEdit = map;
  }

  /** Close the map; with unsaved marker edits, ask first (Save / Discard / Keep editing). */
  // ---- the vacuum room queue (vacqueue.ts; the integration runs it) ----------

  /** A vacuum tile: its room queue - the map it cleans on, in queue mode. */
  private _openQueue(entity: string): void {
    const q = queueInfo(this.hass, this._doc, entity);
    if (!q) return;
    // none of its rooms on a map yet: any map - its area buttons still queue
    const map = tileMap(this._maps, q) ?? this._maps[0];
    if (!map) return;
    if (this._editing) this._toggleEditing();
    this._vacQueue = q.sensor;
    this._mapFocus = undefined;
    this._mapFocusArea = undefined;
    this._mapRemember = false; // a queue visit never moves the map's saved view
    this._mapZone = null;
    this._mapOpen = map.id;
  }

  private _closeQueue(): void {
    this._vacQueue = undefined;
    this._mapOpen = undefined;
  }

  private _queue(q: QueueInfo, action: string, area?: string, index?: number, start = false): void {
    void this.hass?.callService("room_tiles", "vacuum_queue", {
      robot: q.robot,
      action,
      ...(area ? { area } : {}),
      ...(index !== undefined ? { index } : {}),
      ...(start ? { start: true } : {}),
    });
  }

  /** A tap on a room in queue mode: queue its area, or take it off. (The
   *  room being cleaned stays - Skip moves on from it.) */
  private _queueTap(q: QueueInfo, area: string): void {
    if (area === q.current) return;
    if (q.queue.includes(area)) this._queue(q, "remove", area);
    else this._queue(q, "add", area, undefined, this._autoStart); // "Start queue automatically": no Start press needed
  }

  /** Every area the vacuum cleans, in the areas' order - the queue's
   *  buttons (rooms on another map, or on none, too). */
  private _queueAreas(q: QueueInfo): string[] {
    const order = new Map((this._doc?.areas ?? []).map((a, i) => [a.id, i]));
    return [...q.cleanable].sort((a, b) => (order.get(a) ?? 999) - (order.get(b) ?? 999) || this._areaLabel(a).localeCompare(this._areaLabel(b)));
  }

  private _areaLabel(area: string): string {
    return this._doc?.areas.find((a) => a.id === area)?.short_name ?? this.hass?.areas?.[area]?.name ?? area;
  }

  /** Queue mode's map toggle: only the maps with rooms the vacuum cleans. */
  private _renderQueueMaps(maps: MapData[], map: MapData | undefined): TemplateResult | typeof nothing {
    if (maps.length < 2) return nothing;
    return html`<div class="navgroup" role="group" aria-label=${t("editor.maps")}>
      <span class="navlabel"><ha-icon icon="mdi:map-outline"></ha-icon></span>
      ${maps.map(
        (m) => html`<button class="floor ${m.id === map?.id ? "on" : ""}" aria-pressed=${m.id === map?.id} @click=${() => {
          this._mapZone = null;
          this._mapOpen = m.id;
        }}>${m.name}</button>`,
      )}
    </div>`;
  }

  /** Queue mode's bar: the status, Start / Pause / Skip / Stop, and the
   *  queue in order (each: move earlier / later, remove). */
  private _renderQueueBar(q: QueueInfo): TemplateResult {
    const st = this.hass?.states[q.sensor];
    const status = vacuumStatus(st);
    const vac = this.hass?.states[q.vacuum]?.state;
    const running = vac === "cleaning";
    const paused = vac === "paused";
    const n = q.queue.length;
    return html`<div class="editbar queuebar">
        <span class="qstatus vac-${status.cls}">${status.text}</span>
        <button class="pill primary" ?disabled=${!n && !paused && !(st?.attributes.alert !== "none" && q.current)} @click=${() => this._queue(q, "start")}>
          <ha-icon icon="mdi:play"></ha-icon> ${paused ? t("queue.resume") : t("queue.start")}
        </button>
        <button class="layout" title=${t("queue.pause")} ?disabled=${!running} @click=${() => this._queue(q, "pause")}><ha-icon icon="mdi:pause"></ha-icon></button>
        <button class="layout" title=${t("queue.skip")} ?disabled=${!q.current} @click=${() => this._queue(q, "skip")}>
          <ha-icon icon="mdi:skip-next"></ha-icon>
        </button>
        <button class="layout" title=${t("queue.stop")} ?disabled=${!q.current && !n && !running && !paused} @click=${() => this._queue(q, "stop")}>
          <ha-icon icon="mdi:stop"></ha-icon>
        </button>
        <span class="qauto">
          <span>${t("queue.auto_start")}</span>
          ${toggle(this._autoStart, (on) => {
            this._autoStart = on;
            save(STORE_QUEUE_AUTOSTART, on ? "1" : "0");
          }, t("queue.auto_start"), this.theme)}
        </span>
        <span class="grow"></span>
        <button class="pill" title=${t("queue.ha_card_tip")} @click=${() => this._moreInfo(q.vacuum)}>${t("queue.ha_card")}</button>
      </div>
      <div class="context queue-areas">
        <span class="tool-name"><ha-icon icon="mdi:floor-plan"></ha-icon>${t("queue.rooms")}</span>
        <span class="qchips">
          ${this._queueAreas(q).map((a) => {
            const k = q.queue.indexOf(a);
            const cur = a === q.current;
            return html`<button
              class="qarea ${roomState(q, a) ?? ""} ${cur ? "current" : ""}"
              aria-pressed=${k >= 0 || cur}
              title=${cur ? t("queue.being_cleaned") : k >= 0 ? t("queue.take_off") : t("queue.add_to")}
              @click=${() => this._queueTap(q, a)}
            >
              ${cur ? html`<ha-icon icon="mdi:play"></ha-icon>` : k >= 0 ? html`<b>${k + 1}</b>` : nothing}${this._areaLabel(a)}
            </button>`;
          })}
        </span>
      </div>
      <div class="context queue-line">
        <span class="tool-name"><ha-icon icon="mdi:format-list-numbered"></ha-icon>${t("queue.queue")}</span>
        ${q.current
          ? html`<span class="qchip current ${roomState(q, q.current) ?? ""}" title=${t("queue.being_cleaned")}><ha-icon icon="mdi:play"></ha-icon>${this._areaLabel(q.current)}</span>`
          : nothing}
        ${n
          ? html`<span class="qchips">
              ${q.queue.map(
                (a, k) => html`<span class="qchip">
                  <b>${k + 1}</b> ${this._areaLabel(a)}
                  ${k > 0 ? html`<button class="qmini" title=${t("common.earlier")} @click=${() => this._queue(q, "move", a, k - 1)}><ha-icon icon="mdi:chevron-left"></ha-icon></button>` : nothing}
                  ${k < n - 1 ? html`<button class="qmini" title=${t("common.later")} @click=${() => this._queue(q, "move", a, k + 1)}><ha-icon icon="mdi:chevron-right"></ha-icon></button>` : nothing}
                  <button class="qmini" title=${t("common.remove")} @click=${() => this._queue(q, "remove", a)}><ha-icon icon="mdi:close"></ha-icon></button>
                </span>`,
              )}
            </span>
            <button class="pill" title=${t("queue.clear_tip")} @click=${() => this._queue(q, "clear")}>${t("queue.clear")}</button>`
          : html`<span class="hint">${q.current ? t("queue.nothing_next") : t("queue.tap_rooms")}</span>`}
      </div>`;
  }

  private _closeMap(): void {
    if (this._mapEdit?.undo.length) {
      this._askUnsaved = "close-map";
      return;
    }
    this._endMapEdit();
    this._mapOpen = undefined;
  }

  /** Cancel (leave marker editing): with changes, ask first - a whole
   *  session is never dropped by one tap (docs/UI.md). */
  private _cancelMapEdit(): void {
    if (this._mapEdit?.undo.length) this._askUnsaved = "end-edit";
    else this._endMapEdit();
  }

  private _endMapEdit(): void {
    this._mapEdit = undefined;
    this._sel = [];
    this._markerStack = undefined;
    this._markerTool = "select";
    this._mapHelp = false;
    this._askUnsaved = "";
    this._adding = false;
  }

  private _deleteSelected(): void {
    if (!this._sel.length) return;
    const sel = new Set(this._sel);
    const stack = this._markerStack;
    const at = stack && this._sel.length === 1 ? stack.indexOf(this._sel[0]) : -1;
    this._mapChange((d) => d.filter((m) => !sel.has(m.id)));
    this._sel = [];
    if (stack) {
      // the "Here:" row stays without it, the next one selected (as in the Map Editor)
      const left = stack.filter((id) => !sel.has(id));
      this._markerStack = left.length ? left : undefined;
      if (at >= 0 && left.length) this._sel = [left[Math.min(at, left.length - 1)]];
    }
  }

  /** Save the markers (and where the layers start). `stay`: the Save
   *  changes button - editing goes on (new markers get their ids from HA
   *  first); else (leaving, after "Save your changes?") the editor ends. */
  private async _saveMapEdit(stay = false): Promise<void> {
    const ed = this._mapEdit;
    if (!ed || !this.hass) return;
    const markers = ed.draft.map((m) => ({
      ...(m.id.startsWith("new-") ? {} : { id: m.id }), // new ones get their id from HA
      entity: m.entity,
      x: Math.round(m.x),
      y: Math.round(m.y),
      layer: m.layer,
      show_name: m.show_name,
    }));
    try {
      await this.hass.callService("room_tiles", "set_markers", { map: ed.map, markers });
      // the whole-map view takes in every marker: refit the bounds as the
      // Map Editor's Save does - bigger when one went outside, smaller
      // again when it came back in
      const map = (this._doc?.maps as MapData[] | undefined)?.find((m) => m.id === ed.map);
      if (map) {
        const fields: Record<string, unknown> = {};
        const bounds = fitBounds(map, markers.map((m) => [m.x, m.y] as [number, number]));
        if (bounds.some((v, i) => v !== map.bounds[i])) fields.bounds = bounds;
        // where the layers start (set here) - names / order / adding stay in Map settings
        if (JSON.stringify(layersOf({ ...map, layers: ed.layers })) !== JSON.stringify(layersOf(map))) fields.layers = ed.layers;
        if (Object.keys(fields).length) await this.hass.callService("room_tiles", "set_map", { map: ed.map, ...fields });
      }
      if (stay) {
        // go on editing the saved markers: same layer, tool, view; the
        // selection / "Here:" row keep the markers that kept their ids
        const tool = this._markerTool;
        const sel = this._sel;
        const stack = this._markerStack;
        await this._nextDoc();
        const fresh = (this._doc?.maps as MapData[] | undefined)?.find((m) => m.id === ed.map);
        if (!fresh || this._mapEdit?.map !== ed.map) return;
        const ids = new Set(((this._doc?.markers as MapMarker[] | undefined) ?? []).map((m) => m.id));
        this._startMapEdit(fresh, ed.layer, false);
        this._markerTool = tool;
        this._sel = sel.filter((id) => ids.has(id));
        const left = stack?.filter((id) => ids.has(id));
        this._markerStack = left?.length ? left : undefined;
        return;
      }
      this._endMapEdit();
    } catch (err) {
      alert(t("panel.err_save_map", { error: String((err as { message?: string })?.message ?? err) }));
    }
  }

  /** Add: the picker starts with the area of the map room in the middle of
   *  the view (where the marker goes), else the room zoomed into, else the
   *  room board you came from. */
  private _startAdd(map: MapData): void {
    const [x, y] = this.renderRoot.querySelector<RtMap>("rt-map")?.viewCenter() ?? [0, 0];
    this._addArea = areaAt(map, x, y) ?? this._mapZone?.area ?? this._current?.id;
    this._adding = true;
  }

  /** Insert: the first marker on the dotted circle, the rest in rings
   *  around it (ringLayout) - all selected, ready to drag; one undo step. */
  private _addMarkers(entities: string[]): void {
    const ed = this._mapEdit;
    const rtMap = this.renderRoot.querySelector<RtMap>("rt-map");
    if (!ed || !entities.length) return;
    const [x, y] = rtMap?.viewCenter() ?? [0, 0];
    const spots = ringLayout(entities.length, x, y, rtMap?.markerSize() ?? 0);
    const added: MapMarker[] = entities.map((entity, i) => ({
      id: `new-${ed.next + i}`,
      map: ed.map,
      entity,
      x: Math.round(spots[i][0]),
      y: Math.round(spots[i][1]),
      layer: ed.layer,
      show_name: false,
    }));
    this._mapChange((d) => [...d, ...added]);
    this._mapEdit = { ...this._mapEdit!, next: ed.next + added.length };
    this._adding = false;
    this._sel = added.map((m) => m.id);
    this._markerTool = "select"; // ready to drag them
  }

  /** Nudge the selected markers one whole map unit (the Map Editor's arrows):
   *  a tap once; held, it repeats - faster - as one undo step. */
  private _markerNudge(dx: number, dy: number, again = false, times = 1): void {
    const ed = this._mapEdit;
    if (!ed || !this._sel.length) return;
    const sel = new Set(this._sel);
    const move = (d: MapMarker[]) => d.map((m) => (sel.has(m.id) ? { ...m, x: Math.round(m.x) + dx * times, y: Math.round(m.y) + dy * times } : m));
    if (!again) this._mapChange(move);
    else this._mapEdit = { ...ed, draft: move(ed.draft) };
  }

  private _markerNudgeTimer?: number;

  private _renderMarkerNudge(): TemplateResult {
    const stop = () => window.clearTimeout(this._markerNudgeTimer);
    const arrow = (dx: number, dy: number, icon: string, label: string) =>
      html`<button
        class="icon nudge"
        aria-label=${label}
        title=${label}
        @pointerdown=${(e: PointerEvent) => {
          e.preventDefault();
          this._markerNudge(dx, dy);
          stop();
          let n = 0;
          const again = () => {
            n++;
            this._markerNudge(dx, dy, true, n < 20 ? 1 : n < 40 ? 2 : 4);
            this._markerNudgeTimer = window.setTimeout(again, 60);
          };
          this._markerNudgeTimer = window.setTimeout(again, 400);
        }}
        @pointerup=${stop}
        @pointerleave=${stop}
        @pointercancel=${stop}
        @contextmenu=${(e: Event) => e.preventDefault()}
      >
        <ha-icon icon=${icon}></ha-icon>
      </button>`;
    return html`<div class="setting">
      <span class="label">${t("editor.nudge")}</span>
      <span class="nudges">
        ${arrow(-1, 0, "mdi:arrow-left", t("editor.left"))}${arrow(0, -1, "mdi:arrow-up", t("editor.up"))}${arrow(0, 1, "mdi:arrow-down", t("editor.down"))}${arrow(1, 0, "mdi:arrow-right", t("editor.right"))}
      </span>
    </div>`;
  }

  /** Settings for the selection (one marker or several). */
  private _renderMarkerSheet(map: MapData): TemplateResult {
    const ed = this._mapEdit!;
    const chosen = ed.draft.filter((m) => this._sel.includes(m.id));
    if (!chosen.length) return html``;
    const one = chosen.length === 1 ? chosen[0] : undefined;
    const sel = new Set(this._sel);
    const set = (patch: Partial<MapMarker>) => this._mapChange((d) => d.map((m) => (sel.has(m.id) ? { ...m, ...patch } : m)));
    const sameLayer = chosen.every((m) => m.layer === chosen[0].layer) ? chosen[0].layer : "";
    const allNamed = chosen.every((m) => m.show_name);
    return html`
      <div class="sheet" role="dialog" aria-label=${t("layers.selected_markers")} style=${this._sheetDrag.style}>
        <div class="sheet-head" @pointerdown=${this._sheetDrag.down} @dblclick=${this._sheetDrag.reset}>
          <ha-icon class="grip" icon="mdi:drag"></ha-icon>
          <div>
            <div class="sheet-title">
              ${one ? this._catalog(one.entity)?.short_name ?? fullName(this.hass, one.entity) : tn("layers.n_selected", chosen.length)}
            </div>
            ${one ? html`<div class="hint">${fullName(this.hass, one.entity)}</div>` : nothing}
          </div>
        </div>
        ${chosen.length > 1 ? this._arrangeMarkers() : nothing}
        <div class="group">
        <div class="group-head"><ha-icon icon="mdi:map-marker-outline"></ha-icon>${one ? t("layers.marker") : t("layers.markers")}</div>
        <div class="setting">
          <span class="label">${t("layers.layer")}</span>
          <select @change=${(e: Event) => set({ layer: (e.target as HTMLSelectElement).value })}>
            ${sameLayer ? nothing : html`<option value="" selected disabled>${t("editor.mixed")}</option>`}
            ${(map.layers ?? []).map((l) => html`<option value=${l.id} ?selected=${l.id === sameLayer}>${l.name}</option>`)}
          </select>
        </div>
        <div class="setting">
          <span class="label">${one ? t("layers.show_its_name") : t("layers.show_names")}</span>
          ${toggle(allNamed, (on) => set({ show_name: on }), t("layers.show_names"), this.theme)}
        </div>
        ${this._renderMarkerNudge()}
        </div>
        <div class="sheet-foot">
          <button class="danger" @click=${() => this._deleteSelected()}>
            <ha-icon icon="mdi:delete"></ha-icon> ${one ? t("layers.delete_marker") : t("layers.delete_n", { n: chosen.length })}
          </button>
          <button class="pill primary" @click=${() => (this._sel = [])}>${t("common.done")}</button>
        </div>
      </div>
    `;
  }

  /** Group actions on the selected markers: align to the FIRST selected,
   *  space evenly. One undo step; the selection stays. */
  private _arrangeMarkers(): TemplateResult {
    const ids = [...this._sel];
    const run = (op: ArrangeOp) =>
      this._mapChange((d) => {
        const picked = ids.map((id) => d.find((m) => m.id === id)).filter((m): m is MapMarker => !!m);
        const moves = arrange(picked.map((m) => pointBox(m.x, m.y)), op);
        picked.forEach((m, k) => {
          m.x += moves[k].dx;
          m.y += moves[k].dy;
        });
      });
    return html`<div class="arrange" role="group" aria-label=${t("editor.arrange")}>
      ${ARRANGE_OPS.filter((a) => ids.length >= a.min).map(
        (a) => html`<button class="arrange-btn" title=${a.title} @click=${() => run(a.op)}>
          <ha-icon icon=${a.icon}></ha-icon> ${a.label}
        </button>`,
      )}
      <div class="arrange-note">${t("layers.arrange_note")}</div>
    </div>`;
  }

  private _openPopup(detail: { entity: string; kind: Tile["kind"]; x: number; y: number }): void {
    this._popup = detail;
    this._popupAt = Date.now();
    window.clearTimeout(this._popupTimer);
    this._popupTimer = window.setTimeout(() => (this._popup = undefined), 10000); // idle: close
  }

  /** The map editor, over the map screen. */
  private _renderPlanEditor(): TemplateResult {
    const id = this._planEdit!;
    const map = this._maps.find((m) => m.id === id);
    if (!map) return html`<div class="mapscreen">${this._screen(t("screen.loading_map"), undefined, undefined, true)}</div>`; // just added
    return html`<rt-plan-editor
      .hass=${this.hass}
      .doc=${this._doc}
      .map=${map}
      .theme=${this.theme}
      .openDialog=${this._planDialog}
      .returnAfterSettings=${!!this._returnTo}
      .screenButton=${this._screenButton()}
      .settingsDot=${this._settingsDot()}
      @close=${() => {
        this._planEdit = undefined;
        this._planDialog = undefined;
        this._returnFromPlan();
      }}
      @open-map=${(e: CustomEvent) => {
        this._planEdit = e.detail.map;
        this._mapOpen = e.detail.map;
      }}
      @settings-menu=${() => (this._menu = !this._menu)}
      @map-removed=${() => {
        this._returnTo = undefined; // its map is gone
        this._planEdit = undefined;
        this._mapOpen = this._maps.find((m) => m.id !== id)?.id;
      }}
    ></rt-plan-editor>`;
  }

  private _resolveAsk(ok: boolean): void {
    const r = this._afterAsk;
    this._afterAsk = undefined;
    r?.(ok);
  }

  /** Close whichever map editor is open - asking about unsaved changes
   *  (Save changes / Discard / Keep editing) - before another screen opens.
   *  False: Keep editing (stay). */
  private async _leaveEditors(): Promise<boolean> {
    if (this._planEdit) {
      const el = this.renderRoot.querySelector<HTMLElement & { leave(): Promise<boolean> }>("rt-plan-editor");
      if (el && !(await el.leave())) return false;
      this._planEdit = undefined;
      this._planDialog = undefined;
      this._returnTo = undefined;
    }
    if (this._mapEdit) {
      if (this._mapEdit.undo.length) {
        const ok = await new Promise<boolean>((resolve) => {
          this._afterAsk = resolve;
          this._askUnsaved = "leave";
        });
        if (!ok) return false;
      }
      this._endMapEdit();
    }
    return true;
  }

  /** After "go-room"'s Save / Discard: the room on the other map, still in
   *  the Layer Editor. */
  private _goAfterUnsaved(): void {
    const g = this._goAfterAsk;
    this._goAfterAsk = undefined;
    const next = g && this._maps.find((x) => x.id === g.map);
    if (!g || !next) return;
    this._endMapEdit();
    this._openRoomOn(g.map, g.zone);
    void this.updateComplete.then(() => this._startMapEdit(next));
  }

  /** Back from the map editor to the Layer Editor it was opened from (its
   *  layer settings link): the same map, layer and view. */
  private _returnFromPlan(): void {
    const r = this._returnTo;
    this._returnTo = undefined;
    if (!r) return;
    const map = this._maps.find((m) => m.id === r.map);
    if (!map) return;
    this._mapOpen = map.id;
    this._mapFocus = undefined;
    this._mapFocusArea = undefined;
    this._mapStartView = r.cam;
    // a layer added there (e.g. from the "+ Add layer" link): edit that one
    const added = (map.layers ?? []).map((l) => l.id).filter((id) => !r.layers.includes(id));
    void this.updateComplete.then(() => {
      this._mapStartView = undefined;
      this._startMapEdit(map, added[added.length - 1] ?? r.layer);
    });
  }

  /** The top bar's first button - the same in the tile view and on the map:
   *  Home Assistant's menu, or full screen (covering HA's sidebar). */
  private _screenButton(): TemplateResult | typeof nothing {
    if (this._portrait)
      return this.narrow
        ? html`<button class="layout back" title=${t("panel.ha_menu")} @click=${() => this._haMenu()}>
            <ha-icon icon="mdi:menu"></ha-icon>
          </button>`
        : nothing;
    return this._covering
      ? html`<button class="layout back" title=${t("panel.show_ha_menu")} @click=${() => this._haMenu()}>
          <ha-icon icon="mdi:menu"></ha-icon>
        </button>`
      : html`<button class="layout back" title=${t("panel.full_screen")} @click=${() => this._fullScreen()}>
          <ha-icon icon="mdi:fullscreen"></ha-icon>
        </button>`;
  }

  private _renderMapScreen(): TemplateResult {
    // a vacuum's room queue: the maps it cleans on, its view of them
    const q = this._vacQueue ? queueInfo(this.hass, this._doc, this._vacQueue) : undefined;
    // placing markers: on whichever map it is; else the maps people see
    const maps = q ? (queueMaps(this._maps, q).length ? queueMaps(this._maps, q) : this._maps) : this._mapEdit ? this._maps : this._viewMaps;
    const map = maps.find((m) => m.id === this._mapOpen) ?? maps[0];
    const zone = this._mapZone;
    // wide (panels, tablets, desktop): the map / layer groups in the top bar
    const wide = this._box.w >= NAV_IN_TOOLBAR_FROM;
    const nav = q ? this._renderQueueMaps(maps, map) : this._renderMapNav(maps, map);
    return html`
      <div class="mapscreen ${wide ? "wide" : ""}">
        <div class="toolbar">
          ${this._screenButton()}
          ${zone
            ? html`<button class="layout back" title=${t("panel.whole_map")} @click=${() => this.renderRoot.querySelector<RtMap>("rt-map")?.zoomToZone(undefined)}>
                <ha-icon icon="mdi:arrow-left"></ha-icon>
              </button>`
            : nothing}
          ${q
            ? html`<div class="map-title">${q.name} <span class="of-mode">· ${t("help.title.queue")}</span></div>`
            : this._mapEdit
            ? html`<div class="map-title">
                ${t("help.title.markers")}
                <button class="of-mode room-pick" title=${t("panel.go_to_room")} @click=${() => (this._mapPick = !this._mapPick)}>
                  · ${this._roomTitle(zone) || map?.name || t("help.title.view")}<ha-icon icon="mdi:menu-down"></ha-icon>
                </button>
              </div>`
            : // like the tiles' area name: tap it to go to another room (any map)
              html`<button class="map-title area-name" title=${t("panel.go_to_room")} @click=${() => (this._mapPick = !this._mapPick)}>
                <span class="area-text">${this._roomTitle(zone) || map?.name || t("help.title.view")}</span>
                <ha-icon icon="mdi:menu-down"></ha-icon>
              </button>`}
          ${wide ? html`<div class="navslot in-bar">${this._mapEdit ? nothing : nav}</div>` : nothing}
          <div class="tools">
            ${this._mapEdit
              ? // the same top-right buttons as every screen: Help, Settings
                html`<button class="layout" title=${t("help.dialog")} @click=${() => (this._mapHelp = true)}>
                    ${this._helpIcon()}
                  </button>
                  ${this._settingsButton()}`
              : // the tiles' top-right buttons: Help, Settings (the editors are in its menu)
                html`<button class="layout" title=${t("help.dialog")} @click=${() => (this._mapHelp = true)}>
                    ${this._helpIcon()}
                  </button>
                  ${this._settingsButton()}`}
            <button
              class="layout"
              title=${q ? t("panel.close_queue") : this._mapEdit ? t("panel.close_layers") : t("panel.close_map")}
              @click=${() => (q ? this._closeQueue() : this._mapEdit ? this._cancelMapEdit() : this._closeMap())}
            >
              <ha-icon icon="mdi:close"></ha-icon>
            </button>
          </div>
        </div>
        ${q
          ? html`${!wide && nav !== nothing ? html`<div class="navslot row">${nav}</div>` : nothing}${this._renderQueueBar(q)}`
          : this._mapEdit && map
            ? this._renderMapEditBar(map)
            : !wide && nav !== nothing
              ? html`<div class="navslot row">${nav}</div>`
              : nothing}
        <rt-map
          .hass=${this.hass}
          .doc=${this._doc}
          .map=${map ? this._editMap(map) : map}
          .focusZone=${this._mapFocus}
          .focusArea=${this._mapFocusArea}
          .remember=${this._mapRemember}
          .startView=${this._mapStartView}
          .theme=${this.theme}
          .editing=${!!this._mapEdit}
          .editLayer=${this._mapEdit?.layer}
          .markersOverride=${this._mapEdit?.draft}
          .names=${this._names}
          .states=${this._states}
          .queueView=${q ? queueView(q) : undefined}
          @queue-tap=${(e: CustomEvent) => q && this._queueTap(q, e.detail.area)}
          .selectedIds=${this._sel}
          .boxMode=${this._markerTool === "box"}
          .crosshair=${this._markerTool === "add"}
          @crosshair-area=${(e: CustomEvent) => (this._crossArea = e.detail.area)}
          @select=${(e: CustomEvent) => (this._sel = e.detail.ids)}
          @stack=${(e: CustomEvent) => (this._markerStack = e.detail.ids.length ? e.detail.ids : undefined)}
          @markers-moved=${(e: CustomEvent) => {
            const ids = new Set<string>(e.detail.ids);
            this._mapChange((d) => d.map((m) => (ids.has(m.id) ? { ...m, x: m.x + e.detail.dx, y: m.y + e.detail.dy } : m)));
          }}
          @zone=${(e: CustomEvent) => (this._mapZone = e.detail.zone)}
          @layer=${(e: CustomEvent) => {
            this._mapLayerId = e.detail.layer.id;
            this._mapLayersShown = e.detail.shown ?? [e.detail.layer.id];
          }}
          @popup=${(e: CustomEvent) => this._openPopup(e.detail)}
          @layer-settings=${() => this._openLayerSettings()}
          @edit-layer=${(e: CustomEvent) => this._mapEdit && (this._mapEdit = { ...this._mapEdit, layer: e.detail.layer })}
          @go-map=${(e: CustomEvent) => {
            if (this._mapEdit || !this._maps.some((m) => m.id === e.detail.to)) return;
            this._mapOpen = e.detail.to;
            this._mapZone = null;
          }}
        ></rt-map>
        ${q
          ? html`<div class="qlegend" aria-label=${t("queue.colors")}>
              ${ROOM_STATES.map(([st, label]) => html`<span class="${st}"><i></i>${t(label)}</span>`)}
            </div>`
          : nothing}
        ${this._mapEdit && this._sel.length && map ? this._renderMarkerSheet(map) : nothing}
        ${this._mapPick ? this._renderRoomPicker(maps, map, zone) : nothing}
        ${this._mapEdit ? nothing : this._renderNavMenu(maps, map)}
        ${this._adding
          ? html`<rt-entity-picker
              .hass=${this.hass}
              .doc=${this._doc}
              .area=${this._addArea}
              .forMap=${true}
              .multiple=${true}
              .max=${MAX_ADD}
              .placed=${new Set(this._mapEdit?.draft.filter((m) => m.map === this._mapEdit!.map && m.layer === this._mapEdit!.layer).map((m) => m.entity))}
              heading=${t("picker.add_markers")}
              @pick-many=${(e: CustomEvent) => this._addMarkers(e.detail.entities)}
              @close=${() => (this._adding = false)}
            ></rt-entity-picker>`
          : nothing}
        ${this._mapHelp ? html`<rt-map-help
              mode=${this._vacQueue ? "queue" : this._mapEdit ? "markers" : "view"}
              @close=${() => (this._mapHelp = false)}
              @layer-settings=${() => {
                this._mapHelp = false;
                this._openLayerSettings();
              }}
            ></rt-map-help>` : nothing}
        ${this._askUnsaved
          ? html`<rt-unsaved
              what="map"
              @keep=${() => {
                this._askUnsaved = "";
                this._resolveAsk(false);
              }}
              @discard=${() => {
                const then = this._askUnsaved;
                if (then === "leave") {
                  this._endMapEdit();
                  this._resolveAsk(true);
                  return;
                }
                this._endMapEdit();
                if (then === "close-map") this._mapOpen = undefined;
                if (then === "layer-settings") this._openLayerSettings();
                if (then === "go-room") this._goAfterUnsaved();
              }}
              @save=${async () => {
                const then = this._askUnsaved;
                this._askUnsaved = "";
                await this._saveMapEdit();
                if (this._mapEdit) {
                  this._resolveAsk(false);
                  return; // not saved: stay
                }
                if (then === "leave") this._resolveAsk(true);
                if (then === "close-map") this._mapOpen = undefined;
                if (then === "layer-settings") this._openLayerSettings();
                if (then === "go-room") this._goAfterUnsaved();
              }}
            ></rt-unsaved>`
          : nothing}
      </div>
    `;
  }

  /** The groups an entity is in - directly or through another group (a
   *  fixture -> "Art Lights" -> "Living Room Lights") - smallest first. Found
   *  through anything listing members in `entity_id` (light / fan / cover /
   *  switch groups, group.*), but only what can be a TILE is shown. A scene
   *  lists what it sets, but it isn't a group: left out. */
  private _groupsOf(entity: string): string[] {
    const states = this.hass?.states ?? {};
    const members = new Map<string, string[]>();
    for (const [id, st] of Object.entries(states)) {
      const m = st.attributes.entity_id;
      if (Array.isArray(m) && m.length && !id.startsWith("scene.")) members.set(id, m as string[]);
    }
    const found = new Set<string>();
    const queue = [entity];
    while (queue.length) {
      const e = queue.shift()!;
      for (const [g, m] of members) {
        if (g !== entity && !found.has(g) && m.includes(e)) {
          found.add(g);
          queue.push(g);
        }
      }
    }
    // only what can be a tile (a scene / script / plain group isn't one)
    const sources = profileSources(this._doc, this.hass);
    return [...found]
      .filter((g) => canBeTile(this.hass, this._doc, g, sources, true))
      .sort((a, b) => (members.get(a)?.length ?? 0) - (members.get(b)?.length ?? 0));
  }

  /** The scenes that set an entity or one of its groups (`groups`, closest
   *  first) - for the end of its pop-up row: the most specific first (it
   *  directly, then its smallest group...), then by name; at most
   *  POPUP_MAX, with how many more there are. */
  private _scenesOf(entity: string, groups: string[]): { shown: string[]; more: number } {
    const states = this.hass?.states ?? {};
    const sources = profileSources(this._doc, this.hass);
    const rank = (members: string[]): number => {
      if (members.includes(entity)) return 0;
      const i = groups.findIndex((g) => members.includes(g));
      return i < 0 ? -1 : i + 1;
    };
    const all = Object.entries(states)
      .filter(([id, st]) => id.startsWith("scene.") && Array.isArray(st.attributes.entity_id))
      .map(([id, st]) => ({ id, r: rank(st.attributes.entity_id as string[]) }))
      .filter((x) => x.r >= 0 && canBeTile(this.hass, this._doc, x.id, sources, true))
      .sort((a, b) => a.r - b.r || fullName(this.hass, a.id).localeCompare(fullName(this.hass, b.id)))
      .map((x) => x.id);
    return { shown: all.slice(0, POPUP_MAX), more: Math.max(0, all.length - POPUP_MAX) };
  }

  /** A tile kind for an entity: the catalog's, else from HA's state (lights:
   *  colour / dimmable / on-off from their colour modes). */
  private _kindOf(entity: string, fallback: Tile["kind"]): Tile["kind"] {
    const entry = this._catalog(entity);
    if (entry) return entry.kind;
    const st = this.hass?.states[entity];
    if (entity.startsWith("light.")) {
      const modes: string[] = st?.attributes.supported_color_modes ?? [];
      if (modes.some((m) => ["hs", "xy", "rgb", "rgbw", "rgbww", "color_temp"].includes(m))) return "color_light";
      if (modes.includes("brightness")) return "dimmable_light";
      return "onoff_light";
    }
    return fallback;
  }

  /** Where you are: every map and every layer of this one, the current
   *  ones lit - the same pills for both. A tap on a map opens it; on a layer,
   *  zooms to where it starts. Each group only when there's a choice. */
  /** Where you are: every map and every layer of this one, the current
   *  ones lit - the same framed pill groups for both. A tap on a map opens it;
   *  on a layer, zooms to where it starts. Each group only when there's a
   *  choice; a group that doesn't fit collapses to one button that opens its
   *  list (nav-fit.ts). Hidden full + collapsed copies are measured. */
  private _renderMapNav(maps: MapData[], map: MapData | undefined): TemplateResult | typeof nothing {
    const layers = layersOf(map);
    const showMaps = maps.length > 1;
    const showLayers = !!map && layers.length > 1;
    if (!showMaps && !showLayers) return nothing;
    const fit = this._navFit;
    const mapPill = (m: MapData) =>
      html`<button class="floor ${m.id === map?.id ? "on" : ""}" aria-pressed=${m.id === map?.id} @click=${() => this._pickMap(m.id)}>${m.name}</button>`;
    const layerPill = (l: MapLayer) =>
      html`<button class="floor ${this._layerLit(l.id) ? "on" : ""}" aria-pressed=${this._layerLit(l.id)} @click=${() => this._pickLayer(l)}>
        ${l.name}
      </button>`;
    const group = (which: "maps" | "layers", collapsed: boolean, measure = false) => {
      const isMaps = which === "maps";
      const current = isMaps ? map?.name : layers.find((l) => l.id === this._mapLayerId)?.name ?? layers[0]?.name;
      return html`<div
        class="navgroup ${collapsed ? "collapsed" : ""}"
        role=${measure ? "presentation" : "group"}
        aria-label=${isMaps ? t("editor.maps") : t("panel.layers")}
        data-k=${`${which}-${collapsed ? "menu" : "full"}`}
        @click=${collapsed && !measure ? (e: Event) => this._openNav(which, e) : null}
      >
        <span class="navlabel"><ha-icon icon=${isMaps ? "mdi:floor-plan" : "mdi:layers-outline"}></ha-icon>${isMaps ? t("help.title.view") : t("layers.layer")}</span>
        ${collapsed
          ? html`<button class="floor on menu" aria-haspopup="true">
              ${current}<ha-icon icon="mdi:chevron-down"></ha-icon>
            </button>`
          : isMaps
          ? maps.map(mapPill)
          : layers.map(layerPill)}
      </div>`;
    };
    return html`
      ${showMaps ? group("maps", fit.maps) : nothing}
      ${showLayers ? group("layers", fit.layers) : nothing}
      <div class="navmeasure" aria-hidden="true">
        ${showMaps ? html`${group("maps", false, true)}${group("maps", true, true)}` : nothing}
        ${showLayers ? html`${group("layers", false, true)}${group("layers", true, true)}` : nothing}
      </div>
    `;
  }

  /** The map title's picker: the whole map, then this map's rooms (linked
   *  to an HA area or not; not a hidden area's, in the map view) by name -
   *  the same as tapping them on the map. In the Layer Editor (which has no
   *  Map buttons) a Maps row first: another map's markers. */
  private _renderRoomPicker(maps: MapData[], map: MapData | undefined, zone: MapZone | null | undefined): TemplateResult {
    const hiddenAreas = new Set((this._doc?.areas ?? []).filter((a) => a.hidden).map((a) => a.id));
    const rooms = (map?.zones ?? [])
      .filter((z) => !z.vacuum && this._roomTitle(z) && (this._mapEdit || !(z.area && hiddenAreas.has(z.area))))
      .sort((a, b) => this._roomTitle(a).localeCompare(this._roomTitle(b)));
    const close = () => (this._mapPick = false);
    const editing = !!this._mapEdit;
    return html`
      <div class="scrim" style="z-index:6" @click=${close}></div>
      <div class="picker" style="z-index:7" role="dialog" aria-label=${t("panel.go_to_room")}>
        ${editing && maps.length > 1
          ? html`<div class="pick-head">${t("editor.maps")}</div>
              ${maps.map(
                (m) => html`<button class="pick map ${m.id === map?.id ? "selected" : ""}" @click=${() => this._goToMap(m.id)}>
                  <ha-icon icon="mdi:map"></ha-icon> ${m.name}
                </button>`,
              )}
              <div class="pick-head">${t("panel.rooms_on", { name: map?.name ?? "" })}</div>`
          : nothing}
        ${map
          ? html`<button
              class="pick map ${zone ? "" : "selected"}"
              @click=${() => {
                close();
                // placing markers: the whole map stays at the zoom too (the layer stays)
                if (editing) this.renderRoot.querySelector<RtMap>("rt-map")?.centerOnWhole();
                else this.renderRoot.querySelector<RtMap>("rt-map")?.zoomToZone(undefined);
              }}
            >
              <ha-icon icon="mdi:map"></ha-icon> ${editing ? t("panel.whole_map") : map.name}
            </button>`
          : nothing}
        ${rooms.map(
          (z) => html`<button class="pick ${zone?.id === z.id ? "selected" : ""}" title=${this._roomTitle(z)} @click=${() => this._goToRoom(z)}>
            ${this._roomTitle(z)}
          </button>`,
        )}
      </div>
    `;
  }

  /** The Layer Editor's Maps row: that map's markers next (this map's
   *  unsaved changes: Save changes / Discard / Keep editing first). */
  private _goToMap(id: string): void {
    this._mapPick = false;
    if (id === this._mapOpen) return;
    if (this._mapEdit?.undo.length) {
      this._goAfterAsk = { map: id, zone: "" };
      this._askUnsaved = "go-room";
      return;
    }
    this._goAfterAsk = { map: id, zone: "" };
    this._goAfterUnsaved();
  }

  /** A room's name to show: its own, else its area's (a room left
   *  unlabeled on the map). */
  private _roomTitle(z: MapZone | null | undefined): string {
    if (!z) return "";
    return z.name.trim() || (z.area ? this._doc?.areas.find((a) => a.id === z.area)?.name ?? "" : "");
  }

  /** A room on the open map: zoomed into - placing markers, centered at
   *  the same zoom (the layer being edited stays shown). */
  private _goToRoom(z: MapZone): void {
    this._mapPick = false;
    const rtMap = this.renderRoot.querySelector<RtMap>("rt-map");
    if (this._mapEdit) rtMap?.centerOnZone(z.id);
    else rtMap?.zoomToZone(z.id);
  }

  /** Open map `map` zoomed into room `zone` (rt-map: focusZone). */
  private _openRoomOn(map: string, zone: string): void {
    this._navOpen = undefined;
    this._mapFocus = zone || undefined; // "": the map as it opens (its last view)
    this._mapFocusArea = undefined;
    this._mapOpen = map;
    this._mapZone = null;
  }

  private _pickMap(id: string): void {
    this._navOpen = undefined;
    this._mapFocus = undefined;
    this._mapFocusArea = undefined;
    this._mapOpen = id;
    this._mapZone = null;
  }

  private _pickLayer(l: MapLayer): void {
    this._navOpen = undefined;
    this.renderRoot.querySelector<RtMap>("rt-map")?.zoomTo(l.min_zoom);
  }

  /** A collapsed group's list, under its button. */
  private _openNav(which: "maps" | "layers", e: Event): void {
    const b = ((e.currentTarget as HTMLElement).closest(".navgroup") ?? (e.currentTarget as HTMLElement)).getBoundingClientRect();
    const host = this.renderRoot.querySelector(".mapscreen")?.getBoundingClientRect();
    if (!host) return;
    this._navOpen = { which, left: Math.max(8, Math.min(b.left - host.left, host.width - 220)), top: b.bottom - host.top + 6 };
  }

  private _renderNavMenu(maps: MapData[], map: MapData | undefined): TemplateResult | typeof nothing {
    const o = this._navOpen;
    if (!o) return nothing;
    const items =
      o.which === "maps"
        ? maps.map(
            (m) => html`<button class="floor ${m.id === map?.id ? "on" : ""}" aria-pressed=${m.id === map?.id} @click=${() => this._pickMap(m.id)}>${m.name}</button>`,
          )
        : layersOf(map).map(
            (l) => html`<button class="floor ${this._layerLit(l.id) ? "on" : ""}" aria-pressed=${this._layerLit(l.id)} @click=${() => this._pickLayer(l)}>
              ${l.name}
            </button>`,
          );
    return html`<div class="scrim" style="z-index:9" @click=${() => (this._navOpen = undefined)}></div>
      <div class="navlist" style="left:${o.left}px;top:${o.top}px" role="menu" aria-label=${o.which === "maps" ? t("editor.maps") : t("panel.layers")}>${items}</div>`;
  }

  /** After a render: measure the hidden copies, collapse what doesn't fit. */
  private _fitNav(): void {
    const slot = this.renderRoot.querySelector<HTMLElement>(".navslot");
    if (!slot) return;
    const width = (k: string) => slot.querySelector<HTMLElement>(`.navmeasure [data-k="${k}"]`)?.offsetWidth;
    const widths = (g: string) => {
      const full = width(`${g}-full`);
      const menu = width(`${g}-menu`);
      return full !== undefined && menu !== undefined ? { full, menu } : undefined;
    };
    const fit = navFit(slot.clientWidth, 12, widths("maps"), widths("layers"));
    if (fit.maps !== this._navFit.maps || fit.layers !== this._navFit.layers) this._navFit = fit;
  }

  /** "Starts at [2]x  Ends at [ ]x" - the edited layer's zoom range (it
   *  shows from its start to its end; no end: on and on). */
  private _renderLayerStart(ed: NonNullable<RoomTilesPanel["_mapEdit"]>): TemplateResult {
    const l = ed.layers.find((x) => x.id === ed.layer);
    if (!l) return html``;
    const rtMap = this.renderRoot.querySelector<RtMap>("rt-map");
    return html`<label class="viewchoice" title=${t("layers.starts_tip", { name: l.name })}>
        <span>${t("layers.starts_label")}</span>
        <input
          class="zoomin"
          type="number"
          inputmode="decimal"
          min="0.25"
          step="0.25"
          aria-label=${t("layers.starts_aria", { name: l.name })}
          .value=${String(l.min_zoom)}
          @change=${(e: Event) => {
            const input = e.target as HTMLInputElement;
            this._setLayerRange(l.id, { min_zoom: Number(input.value) });
            const now = this._mapEdit?.layers.find((x) => x.id === l.id)?.min_zoom ?? l.min_zoom;
            input.value = String(now);
            // see it where it now starts (as picking a layer does)
            if (now !== l.min_zoom) rtMap?.zoomTo(now);
          }}
        />
        <span>x</span>
      </label>
      <label class="viewchoice" title=${t("layers.ends_tip", { name: l.name })}>
        <span>${t("layers.ends_label")}</span>
        <input
          class="zoomin"
          type="number"
          inputmode="decimal"
          min="0.25"
          step="0.25"
          placeholder=${t("layers.ends_none")}
          aria-label=${t("layers.ends_aria", { name: l.name })}
          .value=${l.max_zoom == null ? "" : String(l.max_zoom)}
          @change=${(e: Event) => {
            const input = e.target as HTMLInputElement;
            const v = input.value.trim();
            this._setLayerRange(l.id, { max_zoom: v === "" ? null : Number(v) });
            const now = this._mapEdit?.layers.find((x) => x.id === l.id)?.max_zoom;
            input.value = now == null ? "" : String(now);
          }}
        />
        <span>x</span>
      </label>`;
  }

  /** "Names: [Map | On | Off]" - a Layer Editor view choice (this browser). */
  private _viewChoice(label: string, title: string, value: ViewChoice, set: (v: ViewChoice) => void): TemplateResult {
    return html`<label class="viewchoice" title=${title}>
      <span>${t("layers.choice_label", { label })}</span>
      <select aria-label=${label} @change=${(e: Event) => set((e.target as HTMLSelectElement).value as ViewChoice)}>
        ${(
          [
            ["map", t("layers.view_map")],
            ["on", t("layers.view_on")],
            ["off", t("layers.view_off")],
          ] as const
        ).map(([v, l]) => html`<option value=${v} ?selected=${value === v}>${l}</option>`)}
      </select>
    </label>`;
  }

  private _renderMapEditBar(map: MapData): TemplateResult {
    const ed = this._mapEdit!;
    return html`
      <div class="editbar">
        <select
          aria-label=${t("layers.layer_to_edit")}
          @change=${(e: Event) => {
            const sel = e.target as HTMLSelectElement;
            const id = sel.value;
            if (id === ADD_LAYER) {
              // its last entry: Map settings, at the layers (framed)
              sel.value = ed.layer;
              this._openLayerSettings();
              return;
            }
            this._mapEdit = { ...ed, layer: id };
            // start at the zoom where that layer shows
            const layer = (map.layers ?? []).find((l) => l.id === id);
            if (layer) this.renderRoot.querySelector<RtMap>("rt-map")?.zoomTo(layer.min_zoom);
          }}
        >
          ${layersOf({ ...map, layers: ed.layers }).map((l) => html`<option value=${l.id} ?selected=${l.id === ed.layer}>${t("layers.layer_option", { name: l.name })}</option>`)}
          ${layersOf({ ...map, layers: ed.layers }).length < MAX_LAYERS ? html`<option value=${ADD_LAYER}>${t("map.add_layer")}</option>` : nothing}
        </select>
        ${this._renderLayerStart(ed)}
        <div class="modes" role="toolbar" aria-label=${t("editor.tools")}>
          ${MARKER_TOOLS.map(
            (tool) => html`<button
              class="mode ${this._markerTool === tool.id ? "on" : ""}"
              title=${t(`layers.tool_${tool.id}`)}
              aria-pressed=${this._markerTool === tool.id}
              @click=${() => (this._markerTool = tool.id)}
            >
              <ha-icon icon=${tool.icon}></ha-icon>
            </button>`,
          )}
        </div>
        <button class="layout" title=${t("editor.undo_tip")} ?disabled=${!ed.undo.length} @click=${() => this._mapUndo()}><ha-icon icon="mdi:undo"></ha-icon></button>
        <button class="layout" title=${t("editor.redo_tip")} ?disabled=${!ed.redo.length} @click=${() => this._mapRedo()}><ha-icon icon="mdi:redo"></ha-icon></button>
        ${this._viewChoice(t("layers.names"), t("layers.names_tip"), this._names, (v) => {
          this._names = v;
          save(STORE_NAMES, v);
        })}
        ${this._viewChoice(t("layers.state"), t("layers.state_tip"), this._states, (v) => {
          this._states = v;
          save(STORE_STATES, v);
        })}
        <span class="grow"></span>
        <button class="pill" @click=${() => this._cancelMapEdit()}>${t("common.cancel")}</button>
        <button class="pill primary" ?disabled=${!ed.undo.length} @click=${() => this._saveMapEdit(true)}>${t("common.save_changes")}</button>
      </div>
      ${(() => {
        // the line under the bar, like the map editor's: the tool and what it does
        const tool = MARKER_TOOLS.find((x) => x.id === this._markerTool)!;
        const adding = tool.id === "add";
        return html`<div class="context">
          <span class="tool-name"><ha-icon icon=${tool.icon}></ha-icon>${t(`layers.tool_${tool.id}`)}</span>
          ${(tool.id === "select" || tool.id === "box") && this._markerStack?.length && this._sel.every((id) => this._markerStack!.includes(id))
            ? // what's under the last tap - one marker or several on top of each other (the Map Editor's row)
              html`<span class="stack" role="group" aria-label=${t("editor.here")}>
                <span class="stack-label">${t("editor.here_label")}</span>
                <span class="stack-items">${(() => {
                  const ids = this._markerStack!.filter((id) => ed.draft.some((m) => m.id === id));
                  // all of them selected again (after narrowing to one)
                  const all = ids.length > 1 && ids.every((id) => this._sel.includes(id));
                  const allBtn =
                    ids.length > 1
                      ? html`<button class="pill all ${all ? "on" : ""}" aria-pressed=${all} @click=${() => (this._sel = [...ids])}>${t("editor.all_n", { n: ids.length })}</button>`
                      : nothing;
                  const labels = numbered(
                    ids.map((id) => {
                      const mk = ed.draft.find((m) => m.id === id)!;
                      return this._catalog(mk.entity)?.short_name ?? fullName(this.hass, mk.entity);
                    }),
                  );
                  return [
                    allBtn,
                    ...ids.map((id, k) => {
                      const on = this._sel.includes(id);
                      return html`<button class="pill ${on ? "on" : ""}" aria-pressed=${on} @click=${() => (this._sel = [id])}>${labels[k]}</button>`;
                    }),
                  ];
                })()}</span>
              </span>`
            : html`<span class="hint">${t(`layers.hint_${tool.id}`)}</span>`}
          ${adding
            ? html`<span class="area-at">${this._crossArea ? areaName(this.hass, this._doc, this._crossArea) : t("layers.no_area_here")}</span>
                <button class="pill primary" @click=${() => this._startAdd(map)}>${t("layers.insert_here")}</button>`
            : nothing}
        </div>`;
      })()}
      ${this._touchNote ? touchNote(() => (this._touchNote = false)) : nothing}
    `;
  }

  private _renderPopup(): TemplateResult {
    const p = this._popup!;
    // its own tile, then every group it's in (closest first), then the
    // scenes that set it or one of those groups
    const allGroups = this._groupsOf(p.entity);
    const groups = allGroups.slice(0, POPUP_MAX);
    const moreGroups = allGroups.length - groups.length;
    const { shown: scenes, more } = this._scenesOf(p.entity, allGroups);
    const entities = [p.entity, ...groups, ...scenes];
    const tiles: Tile[] = entities.map((e, i) => ({
      kind: this._kindOf(e, i === 0 ? p.kind : e.startsWith("scene.") ? "scene" : "switch"),
      entity: e,
    }));
    const w = Math.min(200, this._box.w * 0.42);
    const h = w / TILE_ASPECT;
    const gap = 10;
    const fit = Math.min(tiles.length, 3, Math.floor((this._box.w - 16 + gap) / (w + gap)) || 1);
    const scrolls = tiles.length > fit || more > 0 || moreGroups > 0;
    // the next tile peeks in when the row scrolls
    const boxW = fit * w + (fit - 1) * gap + (scrolls ? w * 0.35 : 0) + 2 * gap;
    const left = Math.max(8, Math.min(this._box.w - boxW - 8, p.x - (w + 2 * gap) / 2));
    const top = Math.max(8, Math.min(this._box.h - h - 2 * gap - 8, p.y - h - 2 * gap - 24));
    return html`
      <!-- the tap that opened it ends with a click right here: not a close -->
      <div class="scrim" style="z-index:8" @click=${() => Date.now() - this._popupAt > 400 && (this._popup = undefined)}></div>
      <div
        class="popup ${scrolls ? "scrolls" : ""}"
        style="left:${left}px;top:${top}px;width:${boxW}px;--pw:${w}px;--pg:${gap}px"
        @pointerdown=${() => {
          window.clearTimeout(this._popupTimer);
          this._popupTimer = window.setTimeout(() => (this._popup = undefined), 10000);
        }}
        @scroll=${() => {
          window.clearTimeout(this._popupTimer);
          this._popupTimer = window.setTimeout(() => (this._popup = undefined), 10000);
        }}
      >
        ${tiles.map(
          (tile, i) => html`<div class="popup-item">
              ${this._renderTile(tile)}
              ${i > 0 ? html`<div class="popup-tag">${tile.kind === "scene" ? t("popup.scene") : t("popup.group")}</div>` : nothing}
            </div>
            ${
              // the groups / scenes left out: just how many (any of them can
              // still go on a board or the map)
              i === groups.length && moreGroups
                ? html`<div class="popup-more" role="note">${tn("popup.more_groups", moreGroups)}</div>`
                : nothing
            }`,
        )}
        ${more ? html`<div class="popup-more" role="note">${tn("popup.more_scenes", more)}</div>` : nothing}
      </div>
    `;
  }

  // ---- animations setting ------------------------------------------------------

  private get _motionOn(): boolean {
    return this._motion === "always" || (this._motion === "follow" && !this._reduced);
  }

  private _checkNotice(): void {
    this._notice = this._motion === "follow" && this._reduced && !load(STORE_MOTION_NOTICE);
  }

  /** This device's language: one of LANG_NAMES, or "" for Home Assistant's. */
  private _setLanguage(code: string): void {
    this._language = code;
    save(STORE_LANGUAGE, code);
  }

  private _themeLink = "";
  private _themeLinkBusy = false;
  private _themeLinkMsg?: { text: string; replace?: boolean };

  /** "Add a theme from a link" (administrators: it writes into HA's
   *  config folder): a theme zip or a GitHub repository (user_themes.py). */
  private _themeLinkRow(): TemplateResult {
    const msg = this._themeLinkMsg;
    return html`<div class="setting theme-link">
        <input
          type="url"
          inputmode="url"
          aria-label=${t("theme.add_link")}
          placeholder=${t("theme.link_hint")}
          .value=${this._themeLink}
          @input=${(e: Event) => {
            this._themeLink = (e.target as HTMLInputElement).value;
            this._themeLinkMsg = undefined;
          }}
          @keydown=${(e: KeyboardEvent) => e.key === "Enter" && void this._addThemeLink(false)}
        />
        <button class="pill" ?disabled=${this._themeLinkBusy || !this._themeLink.trim()} @click=${() => void this._addThemeLink(false)}>
          ${t("theme.add")}
        </button>
      </div>
      ${msg
        ? html`<div class="hint">
            ${msg.text}
            ${msg.replace ? html`<button class="pill" ?disabled=${this._themeLinkBusy} @click=${() => void this._addThemeLink(true)}>${t("theme.replace")}</button>` : nothing}
          </div>`
        : nothing}`;
  }

  private async _addThemeLink(replace: boolean): Promise<void> {
    const url = this._themeLink.trim();
    const send = this.hass?.connection.sendMessagePromise;
    if (!url || !send || this._themeLinkBusy) return;
    this._themeLinkBusy = true;
    this.requestUpdate();
    let r: { id?: string; name?: string; error?: string } = {};
    try {
      r = (await send.call(this.hass!.connection, { type: "room_tiles/theme_add", url, replace })) as typeof r;
    } catch {
      r = { error: "download_failed" };
    }
    this._themeLinkBusy = false;
    const name = r.name ?? "";
    if (r.error) {
      const known = ["not_https", "not_found", "too_big", "not_a_theme", "exists", "exists_folder"].includes(r.error);
      this._themeLinkMsg = { text: t(`theme.err.${known ? r.error : "download_failed"}`, { name }), replace: r.error === "exists" };
    } else {
      this._themeLinkMsg = { text: t("theme.added", { name }) };
      this._themeLink = "";
    }
    this.requestUpdate();
  }

  /** Under the Theme setting: installed themes getting ready, or that can't
   *  be used (Repairs has why). */
  private _themeNotes(): TemplateResult | typeof nothing {
    const st = this._doc?.themes;
    if (!st) return nothing;
    const ready = st.building.join(", ");
    const broken = st.problems.map((p) => p.theme.replace(/\.zip$/i, "")).join(", ");
    if (!ready && !broken) return nothing;
    return html`${ready ? html`<div class="hint">${t("theme.getting_ready", { names: ready })}</div>` : nothing}
      ${broken ? html`<div class="hint">${t("theme.cant_use", { names: broken })}</div>` : nothing}`;
  }

  /** The installed themes changed (or arrived): the lists take them; this
   *  device's theme drawn again - or the default, when its theme is gone. */
  private _installedThemes(list: InstalledTheme[]): void {
    setInstalledThemes(list);
    // the saved choice stays: an installed theme that's back is used again
    const saved = load(STORE_THEME) as ThemeName | null;
    if (saved && saved !== this.theme && themeNames().includes(saved)) {
      this.theme = saved;
      return;
    }
    if (!themeNames().includes(this.theme)) {
      this.theme = DEFAULT_THEME;
      return;
    }
    if (isInstalledId(this.theme)) {
      this.setAttribute("style", themeCss(this.theme));
      this._measure();
    }
    this.requestUpdate();
  }

  private _setTheme(name: ThemeName): void {
    this.theme = name;
    save(STORE_THEME, name);
  }

  private _setMotion(mode: MotionMode): void {
    this._motion = mode;
    save(STORE_MOTION, mode);
    if (mode === "follow") forget(STORE_MOTION_NOTICE); // re-arm the notice
    this._checkNotice();
  }

  private _dismissNotice(): void {
    save(STORE_MOTION_NOTICE, "1");
    this._notice = false;
  }

  // ---- helpers ----------------------------------------------------------------

  private get _areas(): Area[] {
    return (this._doc?.areas ?? []).filter((a) => !a.hidden);
  }

  private get _current(): Area | undefined {
    const areas = this._areas;
    return areas.find((a) => a.id === this._area) ?? areas[0];
  }

  private _catalog(entity?: string): CatalogEntry | undefined {
    return entity ? this._doc?.catalog.entries.find((e) => e.entity === entity) : undefined;
  }

  private _name(tile: Tile, stateObj?: HassEntity): string {
    if (tile.name) return tile.name;
    if (tile.kind === "map") return t("help.title.view");
    return this._catalog(tile.entity)?.short_name ?? (tile.entity ? fullName(this.hass, tile.entity) : "");
  }

  private _fullName(tile: Tile, stateObj?: HassEntity): string {
    return tile.entity ? fullName(this.hass, tile.entity) : "";
  }

  private _selectArea(id: string): void {
    this._area = id;
    this._picker = false;
    save(STORE_AREA, id);
  }

  private _setLayout(layout: Layout): void {
    const id = this._current?.id;
    if (!id) return;
    this._layouts = { ...this._layouts, [id]: layout };
    save(STORE_LAYOUTS, JSON.stringify(this._layouts));
  }

  // ---- actions ----------------------------------------------------------------

  private _call(c?: Call): void {
    if (c && this.hass) this.hass.callService(c.domain, c.service, c.data);
  }

  /** A tap on a finished unit (done / switch over) of a Room Tiles appliance
   *  empties it; any other tap opens the more-info dialog as before. */
  private _applianceTap(entity: string, index: number, e: Event): void {
    const st = this.hass?.states[entity];
    const id = st?.attributes.appliance as string | undefined;
    const unit = (st?.attributes.units as { id: string; phase: string }[] | undefined)?.[index];
    if (!id || !unit || !["done", "waiting"].includes(unit.phase)) return;
    e.stopPropagation();
    void this.hass!.callService("room_tiles", "clear_appliance", { appliance: id, unit: unit.id });
  }

  private _moreInfo(entity?: string): void {
    if (!entity) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId: entity }, bubbles: true, composed: true }));
  }

  private _hold(entity: string, p: Omit<Pending, "until">, ms: number): void {
    this._pending = { ...this._pending, [entity]: { ...this._pending[entity], ...p, until: Date.now() + ms } };
    window.clearTimeout(this._pendingTimer);
    this._pendingTimer = window.setTimeout(() => this._expirePending(), ms + 50);
  }

  private _expirePending(): void {
    const now = Date.now();
    const kept = Object.fromEntries(Object.entries(this._pending).filter(([, p]) => p.until > now));
    this._pending = kept;
    const next = Math.min(...Object.values(kept).map((p) => p.until));
    if (Number.isFinite(next)) this._pendingTimer = window.setTimeout(() => this._expirePending(), next - now + 50);
  }

  /** The row / switch value to show: the user's pending change until HA
   *  confirms it (or its settle window runs out), else HA's. */
  private _shown(tile: Tile, stateObj?: HassEntity): { row: number; on: boolean } {
    const ha = { row: rollerRow(tile.kind, stateObj), on: switchOn(tile.kind, stateObj) };
    const p = tile.entity ? this._pending[tile.entity] : undefined;
    if (!p || p.until <= Date.now()) return ha;
    const confirmed = (p.row === undefined || p.row === ha.row) && (p.on === undefined || p.on === ha.on);
    if (confirmed) return ha;
    return { row: p.row ?? ha.row, on: p.on ?? ha.on };
  }

  private _onSwitch(tile: Tile, on: boolean): void {
    if (!tile.entity) return;
    this._hold(tile.entity, { on }, settleMs(tile.kind, false, 0));
    this._call(switchCall(tile.kind, tile.entity, on, this.hass?.states[tile.entity]));
  }

  /** Auto thermostats: the band the roller is on while rolling (its labels
   *  follow), kept until HA shows that band (or a few seconds pass). */
  private _bandPreview: Record<string, { mid: number; until: number }> = {};

  private _onRolling(tile: Tile, row: number): void {
    if (tile.kind !== "climate" || !tile.entity || !climateRange(this.hass?.states[tile.entity])) return;
    this._bandPreview = { ...this._bandPreview, [tile.entity]: { mid: CLIMATE_MAX_F - row, until: Date.now() + 6000 } };
  }

  /** The band an auto thermostat's tile shows: the one being rolled to,
   *  else HA's. */
  private _bandShown(entity: string, stateObj?: HassEntity): { low: number; high: number } | undefined {
    const now = climateBand(stateObj);
    const p = this._bandPreview[entity];
    if (!now || !p || Date.now() > p.until) return now;
    if (Math.round((now.low + now.high) / 2) === p.mid) return now; // HA has it
    return climateBand(stateObj, p.mid);
  }

  private _onRoller(tile: Tile, row: number): void {
    if (!tile.entity) return;
    const spec = rollerSpec(tile.kind);
    // the row decides on / off too (Off / Closed / Unlocked rows)
    const last = spec ? spec.options.length - 1 : 0;
    const on =
      tile.kind === "lock"
        ? row === 1
        : tile.kind === "cover"
          ? row !== last
          : tile.kind === "climate" || tile.kind === "water" // a temperature: the bottom row isn't "off"
            ? undefined
            : row !== last;
    this._hold(tile.entity, { row, ...(on === undefined ? {} : { on }) }, settleMs(tile.kind, true, row));
    this._call(rollerCall(tile.kind, tile.entity, row, this.hass?.states[tile.entity]));
  }

  private _areaLights(area: Area): string[] {
    return this._doc?.area_lights?.[area.id] ?? [];
  }

  private _toggleAreaLights(area: Area): void {
    // the integration decides on / off for the whole set (any on -> all off)
    this.hass?.callService("room_tiles", "area_lights", { area: area.id, action: "toggle" });
  }

  // ---- rendering --------------------------------------------------------------

  /** A whole-page message with the Room Tiles icon: loading, not running,
   *  updated, no areas. */
  private _screen(text: string, sub?: string, action?: TemplateResult, busy = false): TemplateResult {
    return html`<div class="screen ${busy ? "busy" : ""}" role="status">
      ${brandIcon(88)}
      <div class="screen-text">${text}</div>
      ${sub ? html`<div class="screen-sub">${sub}</div>` : nothing}
      ${action ?? nothing}
    </div>`;
  }

  protected render(): TemplateResult {
    if (this._error === UPDATED)
      return this._screen(t("screen.updated"), undefined, html`<button class="screen-btn primary" @click=${() => location.reload()}>${t("screen.reload")}</button>`);
    if (this._error) return this._screen(t("screen.not_running"), t("screen.not_running_sub"));
    if (!this._doc) return this._screen(t("screen.loading"), undefined, undefined, true);
    const area = this._current;
    if (!area)
      return html`${this._screen(
          t("screen.no_areas"),
          undefined,
          html`<button class="screen-btn primary" @click=${() => (this._dialog = "areas")}>${t("screen.choose_areas")}</button>`,
        )}
        ${this._dialog === "areas"
          ? html`<rt-area-settings .hass=${this.hass} .doc=${this._doc} @close=${() => (this._dialog = undefined)}></rt-area-settings>`
          : nothing}`;
    const grid = area.tiles[this._layout];
    const slotCols = LAYOUT_COLUMNS[this._layout];
    const slotRows = Math.ceil(grid.length / slotCols);
    // as drawn: turned in portrait (_turned) - columns become rows
    const turned = this._turned;
    const cols = turned ? slotRows : slotCols;
    const rows = turned ? slotCols : slotRows;
    const tileW = this._tileWidth(cols, rows);
    this._grid = { tileW, cols, rows };
    const lights = this._areaLights(area);
    const lightsOn = lights.some((e) => this.hass?.states[e]?.state === "on");

    return html`
      ${this._updateBar()}
      <div class="toolbar ${this._stacked ? "stacked" : ""}">
        ${this._screenButton()}
        <!-- like the panels: the area's name opens the area picker -->
        <button class="area-name" title=${area.name} @click=${() => (this._picker = true)}>
          <span class="area-text">${area.short_name}</span>
          <ha-icon icon="mdi:menu-down"></ha-icon>
        </button>
        ${this._editing
          ? nothing
          : // like the panels: more tiles (5x2 <-> 6x3, lit on 6x3), then the map
            html`<button
                class="layout head-btn ${this._layout === "6x3" ? "on" : ""} ${hasArt(this.theme, "bar_grid") ? "art" : ""}"
                title=${this._layout === "6x3" ? t("panel.fewer_tiles") : t("panel.more_tiles")}
                @click=${() => this._setLayout(this._layout === "6x3" ? "5x2" : "6x3")}
              >
                ${hasArt(this.theme, "bar_grid")
                  ? html`<img class="bar-art" alt="" src=${this._art("bar_grid")} />`
                  : html`<ha-icon icon="mdi:grid"></ha-icon>`}
              </button>
              <button class="layout head-btn" title=${t("help.title.view")} @click=${() => this._openMap("tile")}>
                ${hasArt(this.theme, "bar_map")
                  ? html`<img class="bar-art" alt="" src=${this._art("bar_map")} />`
                  : html`<ha-icon icon="mdi:floor-plan"></ha-icon>`}
              </button>
              <!-- MIRRORED: firmware/components/room_tiles/board.cpp paint_clock (the panels' top-bar time) - a change here must be made there too. -->
              <!-- the time, centred between the buttons - hidden whole when it doesn't fit (_fitClock) -->
              <div class="bar-clock"><span>${this._clockText()}</span></div>`}
        <div class="tools">
          ${this._editing
            ? html`<button class="layout" title=${t("panel.auto")} @click=${() => (this._autoAsk = "pick")}>
                  <ha-icon icon="mdi:auto-fix"></ha-icon>
                </button>
                <button class="done" title=${t("panel.done_editing")} @click=${() => this._toggleEditing()}>
                <ha-icon icon="mdi:check"></ha-icon> ${t("common.done")}
              </button>`
            : lights.length
            ? html`<button
                class="lights ${lightsOn ? "on" : ""}"
                title=${t("panel.area_lights", { area: area.short_name, n: lights.length })}
                @click=${() => this._toggleAreaLights(area)}
              >
                ${hasArt(this.theme, "bar_area_lights")
                  ? // (the theme's own picture: lit / dark like the glyph's colour)
                    html`<img class="bar-art" alt="" src=${this._art(iconArt("bar_area_lights", lightsOn, this.theme))} />`
                  : html`<ha-icon icon=${lightsOn ? "mdi:lightbulb-group" : "mdi:lightbulb-group-outline"}></ha-icon>`}
              </button>`
            : nothing}
          <button class="layout" title=${t("help.dialog")} @click=${() => (this._help = this._editing ? "tile-edit" : "tiles")}>
            ${this._helpIcon()}
          </button>
          ${this._settingsButton()}
        </div>
      </div>
      ${this._editing && this._moveFrom !== undefined
        ? // moving a tile: what happens next (the how-to is on the Help page)
          html`<div class="move-hint" role="status">${th("panel.move_hint", { now: html`<b>${t("panel.move_now")}</b>` })}</div>`
        : nothing}
      ${this._picker ? this._renderPicker(area) : nothing}
      ${this._notice ? this._renderNotice() : nothing}
      ${this._renderAsks()}
      ${this._renderIndicator(cols, rows, tileW)}
      ${this._mapOpen ? (this._planEdit ? this._renderPlanEditor() : this._renderMapScreen()) : nothing}
      ${this._menu ? this._renderMenu() : nothing}
      ${this._help ? html`<rt-map-help mode=${this._help} @close=${() => (this._help = undefined)}></rt-map-help>` : nothing}
      ${this._editSlot !== undefined
        ? html`<rt-tile-editor
            .hass=${this.hass}
            .doc=${this._doc}
            .area=${area}
            .layout=${this._layout}
            .slotIndex=${this._editSlot}
            @close=${() => (this._editSlot = undefined)}
            @edit-short-name=${(e: CustomEvent) => this._openShortNames(e.detail.entity)}
          ></rt-tile-editor>`
        : nothing}
      ${this._dialog === "areas"
        ? html`<rt-area-settings
            .hass=${this.hass}
            .doc=${this._doc}
            @close=${() => (this._dialog = undefined)}
            @area-lights=${(e: CustomEvent) => (this._areaLightsFor = e.detail.area)}
          ></rt-area-settings>`
        : nothing}
      ${this._dialog === "panels"
        ? html`<rt-panels .hass=${this.hass} .doc=${this._doc} .theme=${this.theme} @close=${() => (this._dialog = undefined)}></rt-panels>`
        : nothing}
      ${this._dialog === "appliances"
        ? html`<rt-appliances .hass=${this.hass} .doc=${this._doc} @close=${() => (this._dialog = undefined)}></rt-appliances>`
        : nothing}
      ${this._dialog === "feedback"
        ? html`<rt-feedback .hass=${this.hass} .doc=${this._doc} @close=${() => (this._dialog = undefined)}></rt-feedback>`
        : nothing}
      ${this._dialog === "report-test"
        ? // (a developer build: the report flow with a sample full of what must not go out)
          html`<rt-report .hass=${this.hass} kind="test" about="Grandma's Dryer" @close=${() => (this._dialog = undefined)}></rt-report>`
        : nothing}
      ${this._dialog === "short-names"
        ? html`<rt-short-names
            .hass=${this.hass}
            .doc=${this._doc}
            .theme=${this.theme}
            .focusEntity=${this._shortFocus}
            @close=${() => {
              this._dialog = undefined;
              this._shortFocus = undefined;
            }}
          ></rt-short-names>`
        : nothing}
      ${this._areaLightsFor
        ? html`<rt-area-lights
            .hass=${this.hass}
            .doc=${this._doc}
            .area=${this._areaLightsFor}
            @close=${() => (this._areaLightsFor = undefined)}
          ></rt-area-lights>`
        : nothing}
      ${this._popup ? this._renderPopup() : nothing}
      ${this._colorFor
        ? html`<rt-color-picker
            .hass=${this.hass}
            .entity=${this._colorFor.entity}
            .name=${this._colorFor.name}
            style="--rt-temp-track:url(${this._art("temp_track")})"
            @close=${() => (this._colorFor = undefined)}
            @hold=${(e: CustomEvent) => {
              const { entity, colour, until } = e.detail;
              if (colour) this._swatchHold = { ...this._swatchHold, [entity]: { colour, until } };
              else {
                const rest = { ...this._swatchHold };
                delete rest[entity];
                this._swatchHold = rest;
              }
              this.requestUpdate();
            }}
          ></rt-color-picker>`
        : nothing}
      <div
        class="grid-wrap ${this._portrait ? "portrait" : "landscape"} ${this._modalOpen() ? "locked" : ""}"
        @scroll=${() => this._updateView()}
      >
        <div class="grid" style="--cols:${cols};--tile-w:${tileW}px">
          ${tileW
            ? grid.map(
                (tile, i) => html`<div
                  class="cell ${this._editing ? "editing" : ""} ${this._moveFrom === i ? "picked" : ""}"
                  style=${turned ? `grid-column:${Math.floor(i / slotCols) + 1};grid-row:${(i % slotCols) + 1}` : ""}
                >
                  ${this._renderTile(tile)}
                  ${this._editing
                    ? html`<div
                        class="edit-overlay"
                        @pointerdown=${() => this._editDown(i)}
                        @pointerup=${() => this._editUp()}
                        @pointercancel=${() => this._editUp()}
                        @click=${() => this._editTap(i)}
                        @contextmenu=${(e: Event) => {
                          // right-click = long press (docs/UI.md): pick the tile up / put it back
                          e.preventDefault();
                          window.clearTimeout(this._pressTimer);
                          this._pressed = { slot: i, long: true };
                          this._moveFrom = this._moveFrom === i ? undefined : i;
                        }}
                      >
                        ${!tile || tile.kind === "blank" ? html`<ha-icon icon="mdi:plus"></ha-icon>` : nothing}
                      </div>`
                    : nothing}
                </div>`,
              )
            : nothing}
        </div>
      </div>
    `;
  }

  /** The Appliances row's dot: lit whenever ANYTHING on the Appliances page
   *  isn't set up yet (docs/UI.md) - a new kind of device there must be
   *  counted here too - or an appliance asks what a state means. */
  private _appliancesBadge(): boolean {
    const d = this._doc;
    return (
      (d?.appliance_found ?? []).length + (d?.pool_found ?? []).length + (d?.robot_found ?? []).length > 0 ||
      Object.values(this.hass?.states ?? {}).some(
        (st) => st.attributes.appliance !== undefined && ((st.attributes.questions as unknown[] | undefined)?.length ?? 0) > 0,
      )
    );
  }

  private _shortNamesBadge(): boolean {
    return (this._doc?.catalog.entries ?? []).some((e) => e.review);
  }

  /** Any row in the Settings menu has a dot - every menu badge counts here. */
  /** Panels: an update waiting for Install (with "Update panels
   *  automatically" on, the panels take it themselves - nothing to do) */
  private _panelsBadge(): boolean {
    if (this._doc?.settings.auto_update_panels !== false) return false;
    return !!this._doc?.panel_firmware?.panels.some((p) => p.status === "available");
  }

  private _settingsDot(): boolean {
    return this._appliancesBadge() || this._shortNamesBadge() || this._panelsBadge();
  }

  // MIRRORED: firmware/components/room_tiles/board.cpp gear_dot + board_edit.cpp settings line
  // (the panel's dot: devices found to set up) - a change here must be made there too.
  /** Settings (the gear), on every screen: lit with a dot when its menu
   *  has one. */
  /** The top bars' Help button's picture: the theme's own (bar_help), else
   *  the icon. MIRRORED: firmware/components/room_tiles/board.cpp (the Help button) - a change here must be made there too. */
  private _helpIcon(): TemplateResult {
    return hasArt(this.theme, "bar_help")
      ? html`<img class="bar-art" alt="" src=${this._art("bar_help")} />`
      : html`<ha-icon icon="mdi:help-circle-outline"></ha-icon>`;
  }

  private _settingsButton(): TemplateResult {
    const dot = this._settingsDot();
    return html`<button class="layout gear" title=${t("common.settings")} @click=${() => (this._menu = !this._menu)}>
      ${hasArt(this.theme, "icon_settings")
        ? html`<img class="bar-art gear-art" alt="" src=${this._art("icon_settings")} />`
        : html`<ha-icon icon="mdi:cog"></ha-icon>`}
      ${dot ? html`<span class="gear-dot" aria-label=${t("common.needs_attention")}></span>` : nothing}
    </button>`;
  }

  private _renderMenu(): TemplateResult {
    const open = (fn: () => void) => () => {
      this._menu = false;
      fn();
    };
    // an editor from the menu: the editor that's open closes first (its
    // unsaved changes: Save changes / Discard / Keep editing)
    const leaving = (fn: () => void, here: boolean) => () => {
      this._menu = false;
      if (here) return; // that editor is the one open
      void this._leaveEditors().then((ok) => ok && fn());
    };
    return html`
      <!-- over the map screen too (it opens from there) -->
      <div class="scrim" style="z-index:6" @click=${() => (this._menu = false)}></div>
      <div class="menu" style="z-index:7" role="dialog" aria-label=${t("common.settings")}>
        <div class="group">
        <div class="group-head">${brandIcon(22)}${t("help.title.tiles")}</div>
        ${navRow(
          "mdi:view-grid-outline",
          t("menu.tile_editor"),
          leaving(() => {
            this._mapOpen = undefined; // from the map: back to the tiles
            if (!this._editing) this._toggleEditing();
          }, this._editing && !this._mapOpen),
        )}
        ${navRow("mdi:layers-edit", t("menu.layer_editor"), leaving(() => this._openLayerEditor(), !!this._mapEdit))}
        ${navRow("mdi:pencil-ruler", t("menu.map_editor"), leaving(() => this._openMapEditor(), !!this._planEdit))}
        ${navRow("mdi:floor-plan", t("areas.title"), open(() => (this._dialog = "areas")))}
        ${navRow(
          "mdi:washing-machine",
          t("appliances.title"),
          open(() => (this._dialog = "appliances")),
          this._appliancesBadge(),
        )}
        ${navRow(
          "mdi:form-textbox",
          t("short.title"),
          open(() => (this._dialog = "short-names")),
          this._shortNamesBadge(),
        )}
        ${this._doc?.dev_build
          ? // (a developer build only - DEV_BUILD)
            navRow("mdi:bug-check-outline", t("report.test"), open(() => (this._dialog = "report-test")))
          : nothing}
        ${this._doc?.panel_firmware?.panels.length
          ? navRow(
              "mdi:tablet",
              t("panels.title"),
              open(() => (this._dialog = "panels")),
              this._panelsBadge(),
            )
          : nothing}
        ${navRow("mdi:message-text-outline", t("feedback.title"), open(() => (this._dialog = "feedback")))}
        </div>
        <div class="group">
        <div class="group-head"><ha-icon icon="mdi:tablet-cellphone"></ha-icon>${t("menu.this_device")}</div>
        <div class="setting">
          <span class="label">${t("menu.animations")}</span>
          <select aria-label=${t("menu.animations")} @change=${(e: Event) => this._setMotion((e.target as HTMLSelectElement).value as MotionMode)}>
            ${(
              [
                ["follow", t("menu.motion_follow")],
                ["always", t("menu.motion_always")],
                ["never", t("menu.motion_never")],
              ] as [MotionMode, string][]
            ).map(([mode, label]) => html`<option value=${mode} ?selected=${this._motion === mode}>${label}</option>`)}
          </select>
        </div>
        ${this._motion === "follow" && this._reduced
          ? html`<div class="hint">${t("menu.reduced")}</div>`
          : nothing}
        <!-- MIRRORED: firmware/components/room_tiles/board_edit.cpp open_settings_ / open_theme_list_ (the Theme row) - a change here must be made there too. -->
        <div class="setting">
          <span class="label">${t("menu.theme")}</span>
          <select aria-label=${t("menu.theme")} @change=${(e: Event) => this._setTheme((e.target as HTMLSelectElement).value as ThemeName)}>
            ${themeNames().map(
              (name) =>
                html`<option value=${name} ?selected=${this.theme === name}>
                  ${name === DEFAULT_THEME ? t("theme.default", { name: themeName(name) }) : themeName(name)}
                </option>`,
            )}
          </select>
        </div>
        ${this._themeNotes()}
        ${this.hass?.user?.is_admin ? this._themeLinkRow() : nothing}
        <div class="setting">
          <span class="label">${t("menu.cover")}</span>
          ${toggle(this._cover, (on) => this._setCover(on), t("menu.cover"), this.theme)}
        </div>
        <div class="setting">
          <span class="label">${t("menu.turn")}</span>
          ${toggle(this._turn, (on) => this._setTurn(on), t("menu.turn"), this.theme)}
        </div>
        <div class="setting">
          <span class="label">${t("menu.language")}</span>
          <select aria-label=${t("menu.language")} @change=${(e: Event) => this._setLanguage((e.target as HTMLSelectElement).value)}>
            <option value="" ?selected=${!this._language}>${t("menu.language_ha")}</option>
            ${Object.entries(LANG_NAMES).map(([code, name]) => html`<option value=${code} ?selected=${this._language === code}>${name}</option>`)}
          </select>
        </div>
        </div>
        ${this._doc?.version ? html`<div class="about">${brandIcon(16)}${t("menu.about", { version: this._doc.version })}</div>` : nothing}
      </div>
    `;
  }

  private _renderNotice(): TemplateResult {
    return html`
      <div class="scrim dim"></div>
      <div class="notice" role="alertdialog" aria-labelledby="motion-title">
        <div class="menu-title" id="motion-title">${t("motion.title")}</div>
        <p>${t("motion.intro")}</p>
        <ul>
          <li><b>Windows:</b> ${t("motion.windows")}</li>
          <li><b>macOS:</b> ${t("motion.macos")}</li>
          <li><b>iPhone / iPad:</b> ${t("motion.ios")}</li>
          <li><b>Android:</b> ${t("motion.android")}</li>
        </ul>
        <p>
          <b>${t("motion.only_q")}</b>
          ${th("motion.only", { always: html`<b>${t("motion.always_btn")}</b>`, setting: html`<b>${t("menu.motion_always")}</b>` })}
        </p>
        <div class="actions">
          <button class="secondary" @click=${() => this._dismissNotice()}>${t("motion.keep")}</button>
          <button class="primary" @click=${() => { this._setMotion("always"); this._dismissNotice(); }}>${t("motion.always_btn")}</button>
        </div>
      </div>
    `;
  }

  private _renderPicker(current: Area): TemplateResult {
    return html`
      <div class="scrim" @click=${() => (this._picker = false)}></div>
      <div class="picker" role="dialog" aria-label=${t("panel.choose_area")}>
        ${this._maps.length
          ? html`<button
              class="pick map"
              title=${t("panel.map_tip")}
              @click=${() => {
                this._picker = false;
                this._openMap();
              }}
            >
              <ha-icon icon="mdi:map"></ha-icon> ${t("help.title.view")}
            </button>`
          : nothing}
        ${this._areas.map(
          (a) => html`<button
            class="pick ${a.id === current.id ? "selected" : ""}"
            title=${a.name}
            @click=${() => this._selectArea(a.id)}
          >
            ${a.short_name}
          </button>`,
        )}
      </div>
    `;
  }

  private _art(name: string): string {
    return assetUrl(STATIC_BASE, `ui/${name}.png`, this.theme);
  }

  private _renderTile(tile: Tile | null): TemplateResult {
    if (!tile || tile.kind === "blank") return html`<div class="tile blank"></div>`;
    // disabled in HA: an empty space for now (kept for when it's re-enabled)
    if (tile.entity && this._doc?.disabled?.includes(tile.entity)) {
      return html`<div class="tile blank" title=${t("panel.disabled", { name: tile.entity ?? "" })}></div>`;
    }
    const stateObj = tile.entity ? this.hass?.states[tile.entity] : undefined;
    const unavailable = !!tile.entity && (!stateObj || stateObj.state === "unavailable");
    const name = this._name(tile, stateObj);
    const full = this._fullName(tile, stateObj);

    if (tile.kind === "appliance") {
      return html`<div class="tile kind-appliance ${unavailable ? "unavailable" : ""}" title=${full} @click=${() => this._moreInfo(tile.entity)}>
        <div class="name">${name}</div>
        <div class="appliance-body">${renderAppliance(parseUnits(localTile(stateObj?.attributes)), this.theme, (i, e) => this._applianceTap(tile.entity!, i, e))}</div>
      </div>`;
    }
    if (tile.kind === "vacuum") {
      // MIRRORED: firmware/components/room_tiles/board_kinds.cpp build_vacuum_ / draw_vacuum_map_ - a change here must be made there too.
      // a vacuum with a room queue: its map, the queue on it; a tap opens the queue
      const q = queueInfo(this.hass, this._doc, tile.entity);
      const m = q ? tileMap(this._maps, q) : undefined;
      if (q) {
        const status = vacuumStatus(stateObj);
        const icon = tileIcon(tile.kind, tile.entity ?? undefined, this.hass);
        const why = m ? undefined : queueProblem(this.hass, this._doc, this._maps, tile.entity);
        return html`<div class="tile kind-vacuum queue ${unavailable ? "unavailable" : ""}" title=${full} @click=${() => this._openQueue(tile.entity!)}>
          <div class="name">${name}</div>
          ${m
            ? html`<rt-tile-map class="tile-map-box" .map=${m} .q=${q}></rt-tile-map>`
            : html`<div class="vac-note"><ha-icon icon="mdi:alert-outline"></ha-icon><span>${why}</span></div>`}
          <div class="vac-line vac-${status.cls}">${status.text}</div>
          ${icon ? html`<img class="icon lit" alt="" src=${this._art(iconArt(icon, markerActive("vacuum", stateObj), this.theme))} />` : nothing}
        </div>`;
      }
    }
    if (tile.kind === "map") {
      return html`<div class="tile kind-map" title=${t("help.title.view")} @click=${() => this._openMap("tile")}>
        <div class="name">${name}</div>
        ${hasArt(this.theme, "tile_map")
          ? html`<img class="map-icon map-art" alt="" src=${this._art("tile_map")} />`
          : html`<ha-icon class="map-icon" icon="mdi:floor-plan"></ha-icon>`}
      </div>`;
    }

    const shown = this._shown(tile, stateObj);
    const track = switchTrack(tile.kind, stateObj);
    const spec = rollerSpec(tile.kind, stateObj);
    const geo = ROLLER_GEOMETRY[tile.kind];
    const icon = tileIcon(tile.kind, tile.entity ?? undefined, this.hass);
    // water: Room Tiles' own pool / spa sensors are controlled; a hand-made
    // sensor following the old tile contract stays read-only
    // a pool / spa switching between pool and spa (minutes) or offline: its
    // controls dimmed and locked - a change made then could settle long after
    // the user has gone (user, 2026-11-12); the temperature + status stay
    const busy = tile.kind === "water" && ["switching", "offline"].includes(stateObj?.state ?? "");
    const readOnly = unavailable || busy || (tile.kind === "water" && !isPoolSensor(stateObj));
    const thermo = tile.kind === "climate" || tile.kind === "water";
    const run = tile.kind === "scene" || tile.kind === "script";
    return html`
      <div
        class="tile kind-${tile.kind} ${shown.on ? "on" : ""} ${unavailable ? "unavailable" : ""} ${busy ? "busy" : ""}"
        style=${spec ? `--rt-roller-color:var(--rt-${spec.color.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase())})` : ""}
        title=${full}
        @click=${() => this._moreInfo(detailsEntity(tile.kind, tile.entity, stateObj))}
      >
        <div class="name">${name}</div>
        ${track
          ? html`<rt-switch
              class="sw"
              .w=${track.w}
              .trackOff=${this._art(track.off)}
              .trackOn=${this._art(track.on)}
              .knob=${this._art("knob_switch")}
              .checked=${shown.on}
              .label=${t("panel.on_off", { name })}
              ?disabled=${readOnly}
              @change=${(e: CustomEvent) => this._onSwitch(tile, e.detail.checked)}
            ></rt-switch>`
          : nothing}
        ${tile.kind === "color_light" && geo
          ? this._renderSwatch(tile, stateObj, name, geo, readOnly)
          : spec && geo && !busy
          ? html`${thermo
                ? (() => {
                    // auto: the band's low and high, small, either side under the big middle
                    const band = tile.kind === "climate" && climateRange(stateObj) ? this._bandShown(tile.entity!, stateObj) : undefined;
                    return band
                      ? html`<div class="band" style="--x:${geo.x};--rw:${geo.w}">
                          <span>${Math.round(band.low)}</span><span>${Math.round(band.high)}</span>
                        </div>`
                      : nothing;
                  })()
                : html`<div class="prefix" style="--x:${geo.x};--rw:${geo.w}">${spec.prefix}</div>`}
              <rt-roller
                class="roller"
                style="--x:${geo.x};--rw:${geo.w};--rt-roller-selected-size:calc(${geo.font} * var(--u))"
                .options=${spec.options}
                .selected=${tile.kind === "water" ? this._waterRow(stateObj) : shown.row}
                .label=${`${name} ${spec.prefix}`}
                ?disabled=${readOnly}
                @change=${(e: CustomEvent) => this._onRoller(tile, e.detail.row)}
                @rolling=${(e: CustomEvent) => this._onRolling(tile, e.detail.row)}
              ></rt-roller>`
          : nothing}
        ${thermo ? this._renderThermo(tile, stateObj) : nothing}
        ${tile.kind === "water" && spec ? this._renderHeater(tile, stateObj, name, readOnly) : nothing}
        ${run ? this._renderRun(tile, stateObj, name, unavailable) : nothing}
        ${!spec && !track && !thermo && !run
          ? tile.kind === "vacuum"
            ? html`<div class="state-center vac-${vacuumStatus(stateObj).cls}">${vacuumStatus(stateObj).text}</div>
                ${(() => {
                  // no room queue: why, on the tile (its settings say it too)
                  const why = queueProblem(this.hass, this._doc, this._maps, tile.entity);
                  return why ? html`<div class="vac-note"><ha-icon icon="mdi:alert-outline"></ha-icon><span>${why}</span></div>` : nothing;
                })()}`
            : html`<div class="state-center">${this._stateText(tile, stateObj)}</div>`
          : nothing}
        ${icon
          ? // a thermostat's / scene's / script's icon is the same in every state (its switch / roller / button show it)
            // (a theme may have its own picture for "off": iconArt)
            html`<img class="icon ${shown.on || tile.kind === "climate" || run ? "lit" : ""}" alt="" src=${this._art(
              iconArt(icon, iconOn(tile.kind, stateObj, shown.on, run && (this._runFlash[tile.entity ?? ""] ?? 0) > Date.now()), this.theme),
            )} />`
          : nothing}
      </div>
    `;
  }

  /** Scene / script: one big play button - a tap turns the scene on / runs
   *  the script. Lit while a script runs; a scene (no state of its own)
   *  lights for a moment to say it went. */
  private _renderRun(tile: Tile, stateObj: HassEntity | undefined, name: string, disabled: boolean): TemplateResult {
    const entity = tile.entity ?? "";
    const flashing = (this._runFlash[entity] ?? 0) > Date.now();
    const lit = flashing || (tile.kind === "script" && stateObj?.state === "on");
    const what = tile.kind === "scene" ? t("panel.turn_on") : t("panel.run");
    return html`<button
      class="run ${lit ? "lit" : ""}"
      aria-label=${t("panel.what_name", { what, name })}
      title=${what}
      ?disabled=${disabled}
      @click=${(e: Event) => {
        e.stopPropagation();
        const until = Date.now() + RUN_FLASH_MS;
        this._runFlash = { ...this._runFlash, [entity]: until }; // (reactive: lights now)
        window.setTimeout(() => this.requestUpdate(), RUN_FLASH_MS + 50);
        this.hass?.callService(tile.kind, "turn_on", { entity_id: entity });
      }}
    >
      ${hasArt(this.theme, "run_gift")
        ? html`<img class="run-art" alt="" src=${this._art("run_gift")} />`
        : html`<ha-icon icon="mdi:play"></ha-icon>`}
    </button>`;
  }

  /** Pool / spa: the heater button, bottom right under the roller - a flame
   *  (heat) or snowflake (chill), lit while on, gray while off (showing the
   *  mode a tap turns back on). One tap on / off; the combined tile's acts on
   *  the active body. Only with a heater (= with the roller). */
  private _renderHeater(tile: Tile, stateObj: HassEntity | undefined, name: string, readOnly: boolean): TemplateResult | typeof nothing {
    const a = stateObj?.attributes;
    if (!a || a.has_heater === false) return nothing;
    const entity = tile.entity ?? "";
    const heater = String(a.heater ?? "off");
    const held = this._heaterHold[entity];
    const holding = held && held.until > Date.now();
    // MIRRORED: firmware/components/room_tiles/board_kinds.cpp paint_heater_ (heater_pending) - a change here must be made there too.
    // the tap just made (held), else what was asked and isn't there yet
    // (heater_pending: up to 5 minutes - controllers can take that), else HA's
    const pending = String(a.heater_pending ?? "");
    const actual = ["heat", "heating", "cool", "cooling"].includes(heater);
    const on = holding ? held.on : pending ? pending === "on" : actual;
    const waiting = pending !== "" || (holding && held.on !== actual);
    const cool = ["cool", "cooling"].includes(heater) || (!["heat", "heating"].includes(heater) && a.heater_next === "cool");
    const locked = readOnly || ["switching", "offline"].includes(stateObj?.state ?? "");
    const what = cool ? "chiller" : "heater"; // (panel.<what>_on / _off)
    return html`<button
      class="heater ${on ? (cool ? "cool" : "heat") : ""} ${waiting ? "waiting" : ""}"
      aria-label=${t(`panel.${what}_state_${on ? "on" : "off"}`, { name })}
      title=${t(`panel.${what}_turn_${on ? "off" : "on"}`)}
      aria-pressed=${on ? "true" : "false"}
      ?disabled=${locked}
      @click=${(e: Event) => {
        e.stopPropagation();
        const until = Date.now() + settleMs("water", false, 0);
        this._heaterHold = { ...this._heaterHold, [entity]: { on: !on, until } };
        window.setTimeout(() => this.requestUpdate(), until - Date.now() + 50);
        this.hass?.callService("room_tiles", "pool_set_heater", { entity, heater: !on });
      }}
    >
      <ha-icon icon=${waiting ? "mdi:timer-outline" : cool ? "mdi:snowflake" : "mdi:fire"}></ha-icon>
    </button>`;
  }

  /** Colour lights: the panels' swatch where the brightness roller would be;
   *  it opens the colour picker. Keeps the last colour while the light is off. */
  private _renderSwatch(
    tile: Tile,
    stateObj: HassEntity | undefined,
    name: string,
    geo: { x: number; w: number },
    disabled: boolean,
  ): TemplateResult {
    const entity = tile.entity ?? "";
    const held = this._swatchHold[entity];
    const holding = held && held.until > Date.now();
    const now = holding ? held.colour : lightSwatch(stateObj);
    if (now) this._lastSwatch[entity] = now;
    const colour = now ?? this._lastSwatch[entity];
    const on = stateObj?.state === "on";
    return html`<button
      class="swatch ${on ? "" : "off"}"
      style="--x:${geo.x};--sw:${colour ?? "transparent"}"
      aria-label=${t("color.dialog", { name })}
      ?disabled=${disabled}
      @click=${(e: Event) => {
        e.stopPropagation();
        this._colorFor = { entity, name };
      }}
    >
      <img alt="" src=${this._art("swatch_ring")} />
    </button>`;
  }

  /** Thermostat / pool layout: current temperature left of the roller, status under it. */
  private _renderThermo(tile: Tile, stateObj?: HassEntity): TemplateResult {
    let temp: unknown;
    let status = "";
    let tone = "";
    if (tile.kind === "water") {
      const f = localTile(stateObj?.attributes).split("|"); // title|temp|status|look|target|heater (this device's language)
      temp = f[1];
      // switching / offline: no roller - the full status line has its room
      const busy = ["switching", "offline"].includes(stateObj?.state ?? "");
      status = busy ? localText(stateObj?.attributes.status_word, stateObj?.attributes.status ?? f[2]) : (f[2] ?? "");
      tone = f[3] === "heating" ? "heat" : f[3] === "cooling" ? "cool" : "";
      // not circulating: its last reading, dimmed
      if (stateObj?.attributes.temperature_read) tone += " stale";
    } else {
      temp = stateObj?.attributes.current_temperature;
      const action = String(stateObj?.attributes.hvac_action ?? stateObj?.state ?? "");
      status = action.replace(/_/g, " ");
      tone = action === "heating" ? "heat" : action === "cooling" || climateCooling(stateObj) ? "cool" : "";
    }
    const t = temp === undefined || temp === null || temp === "" ? "--" : `${Math.round(Number(temp))}°`;
    return html`<div class="thermo-temp ${tone}">${t}</div>
      <div class="thermo-status">${status}</div>`;
  }

  private _waterRow(stateObj?: HassEntity): number {
    const target = Number(String(stateObj?.attributes.tile ?? "").split("|")[4]);
    return Number.isFinite(target) && target > 0 ? Math.min(24, Math.max(0, 104 - Math.round(target))) : 6;
  }

  private _stateText(tile: Tile, stateObj?: HassEntity): string {
    if (tile.kind === "map") return "";
    if (!stateObj) return t("panel.not_found");
    const a = stateObj.attributes;
    // HA's own word for a state, in its language (falls back to the raw state)
    const word = (): string => this.hass?.formatEntityState?.(stateObj) ?? stateObj.state;
    switch (tile.kind) {
      case "dimmable_light":
      case "color_light":
        return stateObj.state === "on" && a.brightness ? pct(Math.round((a.brightness / 255) * 100)) : word();
      case "fan":
        return stateObj.state === "on" && a.percentage ? pct(a.percentage) : word();
      case "cover":
        return a.current_position !== undefined && stateObj.state !== "closed"
          ? pct(a.current_position)
          : word();
      case "climate":
        return a.current_temperature !== undefined
          ? `${num(Number(a.current_temperature))}° → ${a.temperature == null ? "--" : num(Number(a.temperature))}°`
          : word();
      case "appliance":
      case "water":
      case "vacuum":
        return word();
      default:
        return word();
    }
  }

  static styles = [noSelectStyles, groupStyles, applianceStyles, rowStyles, touchNoteStyles, css`
    /* colours only from the --rt-* theme variables (theme.ts) */
    :host {
      position: relative;
      display: flex;
      flex-direction: column;
      height: 100dvh;
      overflow: hidden;
      background: var(--rt-page);
      color: var(--rt-text);
      font-family: Roboto, "Noto Sans", sans-serif;
      --rt-tile-on: var(--rt-light);
    }
    /* loading / not running / no areas: the Room Tiles icon, centred */
    .screen {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 14px;
      padding: 32px 16px;
      text-align: center;
    }
    .screen-text {
      font-size: 1.15rem;
      color: var(--rt-text);
    }
    .screen-sub {
      font-size: 0.9rem;
      color: var(--rt-text-secondary);
      max-width: 360px;
    }
    .screen-btn {
      margin-top: 6px;
      border-radius: 10px;
      padding: 10px 18px;
      font-size: 1rem;
      border: 1px solid var(--rt-accent);
      background: var(--rt-accent);
      color: var(--rt-on-accent);
      cursor: pointer;
    }
    /* loading: the icon breathes (not with reduced motion) */
    .screen.busy .brand {
      animation: rt-breathe 1.6s ease-in-out infinite;
    }
    @keyframes rt-breathe {
      50% {
        opacity: 0.45;
        transform: scale(0.94);
      }
    }
    :host([data-motion="off"]) .screen.busy .brand {
      animation: none;
    }
    @media (prefers-reduced-motion: reduce) {
      .screen.busy .brand {
        animation: none;
      }
    }
    .toolbar {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 16px;
    }
    .toolbar {
      position: relative;
    }
    /* every button: the page's font and text colour, not the browser's */
    button {
      font: inherit;
      color: inherit;
      cursor: pointer;
    }
    .area-text {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      min-width: 0;
    }
    .done {
      display: flex;
      align-items: center;
      gap: 4px;
      border: none;
      border-radius: 8px;
      padding: 0 12px;
      height: 36px;
      font-weight: 700;
      background: var(--rt-light);
      color: var(--rt-on-bright);
    }
    .area-name {
      display: flex;
      align-items: center;
      gap: 2px;
      border: none;
      background: none;
      font-size: 1.6rem;
      font-weight: 700;
      padding: 4px 4px;
      flex: 0 1 auto;
      min-width: 0;
      justify-content: flex-start;
      white-space: nowrap;
    }
    .head-btn {
      flex: none;
    }
    /* a narrow screen held upright (_stacked): the room's name across the
       whole first row (after the menu button), the buttons in the row under it */
    .toolbar.stacked {
      flex-wrap: wrap;
      row-gap: 4px;
      padding-bottom: 4px;
    }
    .toolbar.stacked .area-name {
      flex: 1 1 calc(100% - 64px);
    }
    .head-btn.on {
      color: var(--rt-light);
    }
    .scrim {
      position: fixed;
      inset: 0;
      /* above the tiles' edit overlays (3): a tap beside an open menu or
         picker closes it - it never reaches a tile behind */
      z-index: 4;
    }
    .scrim.dim {
      background: var(--rt-page);
      opacity: 0.6;
    }
    .menu,
    .notice {
      position: absolute;
      z-index: 5; /* above the scrim and the tiles' edit overlays */
      background: var(--rt-dialog);
      border: 1px solid var(--rt-tile-border);
      border-radius: 16px;
      padding: 16px;
    }
    .menu select {
      font: inherit;
      color: var(--rt-text);
      background: var(--rt-button);
      border: 1px solid var(--rt-tile-border);
      border-radius: 8px;
      padding: 6px 8px;
    }
    .menu .hint {
      font-size: 0.82rem;
      color: var(--rt-text-secondary);
      margin-top: -4px;
    }
    .menu .theme-link {
      gap: 8px;
    }
    .menu .theme-link input {
      flex: 1;
      min-width: 0;
      font: inherit;
      font-size: 0.9rem;
      color: var(--rt-text);
      background: var(--rt-button);
      border: 1px solid var(--rt-tile-border);
      border-radius: 8px;
      padding: 6px 8px;
    }
    .menu .hint .pill {
      margin-left: 6px;
    }
    .menu {
      top: 60px;
      right: 16px;
      width: min(320px, calc(100% - 32px));
      /* a short window: the menu scrolls (every row reachable) */
      max-height: calc(100% - 110px); /* (60 above, its padding + border, 16 below) */
      overflow-y: auto;
      overscroll-behavior: contain;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .menu > * {
      flex-shrink: 0; /* (scrolls instead of squeezing its rows) */
    }
    /* the menu's last line: which Room Tiles this is */
    .about {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      font-size: 0.8rem;
      color: var(--rt-text-secondary);
    }
    .notice {
      top: 80px;
      left: 50%;
      transform: translateX(-50%);
      width: min(520px, calc(100% - 32px));
      line-height: 1.4;
    }
    .notice ul {
      padding-left: 20px;
      color: var(--rt-text-secondary);
    }
    .menu-title {
      font-weight: 700;
      font-size: 1.05rem;
    }
    .hint {
      font-size: 0.85rem;
      color: var(--rt-text-secondary);
    }
    .actions {
      display: flex;
      gap: 8px;
      justify-content: flex-end;
      flex-wrap: wrap;
    }
    /* a confirm's options, one per line (Auto configure) */
    .choices {
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-bottom: 12px;
    }
    .actions button,
    .choices button {
      border-radius: 10px;
      padding: 8px 14px;
      border: 1px solid var(--rt-tile-border);
      background: var(--rt-button);
    }
    .actions .primary {
      background: var(--rt-accent);
      color: var(--rt-on-accent);
      border-color: var(--rt-accent);
    }
    .picker {
      position: absolute;
      z-index: 5;
      top: 60px;
      left: 16px;
      right: 16px;
      max-width: 900px;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
      gap: 8px;
      padding: 12px;
      border-radius: 16px;
      background: var(--rt-dialog);
      border: 1px solid var(--rt-tile-border);
      /* many areas / a small screen: it stops at the bottom and scrolls */
      max-height: calc(100% - 76px);
      overflow-y: auto;
      overscroll-behavior: contain;
      box-sizing: border-box;
    }
    .pick {
      border: 1px solid var(--rt-tile-border);
      background: var(--rt-button);
      border-radius: 12px;
      padding: 14px 8px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .pick.map {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      --mdc-icon-size: 20px;
    }
    .pick.selected {
      background: var(--rt-accent);
      color: var(--rt-on-accent);
      border-color: var(--rt-accent);
    }
    .tools {
      display: flex;
      gap: 6px;
      flex: none;
      margin-left: auto;
    }
    /* the time: the room between the left and right buttons, centred in it */
    .bar-clock {
      flex: 1 1 0;
      min-width: 0;
      overflow: hidden;
      display: flex;
      justify-content: center;
      font-size: 1.25rem;
      font-variant-numeric: tabular-nums;
      color: var(--rt-text);
    }
    .bar-clock span {
      white-space: nowrap;
      flex: none;
    }
    .lights,
    .layout {
      border: 1px solid var(--rt-tile-border);
      background: var(--rt-button);
      border-radius: 8px;
      min-width: 40px;
      height: 36px;
    }
    .lights.on {
      color: var(--rt-light);
    }
    /* a theme's own top-bar picture: one box for every button - the
       builders fit each into it (assets/theme_format.py BAR_BOX_WEB, at 2x)
       MIRRORED: assets/theme_format.py BAR_BOX_WEB - a change here must be made there too. */
    .lights .bar-art,
    .layout .bar-art {
      display: block;
      width: 24px;
      height: 20px;
    }
    /* its own grid picture can't be lit like the icon: on 6x3 its border is */
    .head-btn.on.art {
      border-color: var(--rt-light);
    }
    /* landscape + "full screen": cover HA's sidebar and header */
    :host([data-cover]) {
      position: fixed;
      inset: 0;
      z-index: 10;
    }
    .grid-wrap {
      flex: 1;
      min-height: 0;
      overflow: auto;
      scrollbar-width: none;
      overscroll-behavior: contain;
    }
    .grid-wrap::-webkit-scrollbar {
      display: none;
    }
    /* a dialog / menu open over the tiles: they stay where they are */
    .grid-wrap.locked {
      overflow: hidden;
      touch-action: none;
    }
    .grid-wrap.portrait {
      /* panning both ways, always coming to rest on whole tiles */
      scroll-snap-type: both proximity;
      scroll-padding: ${GAP}px ${PAD}px;
    }
    .grid-wrap.portrait .cell {
      scroll-snap-align: start;
    }
    .cell {
      position: relative;
      min-width: 0;
    }
    .cell.editing .tile {
      border-style: dashed;
      border-color: var(--rt-light);
    }
    .cell.picked .tile {
      border-color: var(--rt-accent);
      border-width: 3px;
      opacity: 0.8;
    }
    .edit-overlay {
      position: absolute;
      inset: 0;
      z-index: 3;
      /* its own layer, above the tiles' animation layers (Safari) */
      transform: translateZ(0);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      --mdc-icon-size: 40px;
      color: var(--rt-light);
      user-select: none;
      -webkit-touch-callout: none;
    }
    .outdated {
      flex: none;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 12px;
      padding: 8px 16px;
      background: var(--rt-accent);
      color: var(--rt-on-accent);
      font-weight: 700;
    }
    .outdated button {
      border: 1px solid var(--rt-text);
      background: none;
      border-radius: 8px;
      padding: 4px 12px;
    }
    /* tile edit mode's instruction line */
    .menu .setting.off {
      opacity: 0.45;
    }
    .move-hint {
      /* over the board, not above it: the tiles don't move when it shows */
      position: fixed;
      left: calc(var(--rt-left, 0px) + var(--rt-width, 100vw) / 2); /* this page's middle */
      bottom: 16px;
      transform: translateX(-50%);
      z-index: 4;
      max-width: calc(100% - 32px);
      box-shadow: 0 8px 30px var(--rt-page);
      padding: 8px 12px;
      border-radius: 10px;
      text-align: center;
      font-size: 0.95rem;
      background: var(--rt-dialog);
      border: 1px dashed var(--rt-light);
      color: var(--rt-text);
    }
    /* marker editing's tools + the line under them (the map editor's look) */
    .modes {
      display: flex;
      gap: 2px;
      padding: 2px;
      border-radius: 12px;
      background: var(--rt-button);
    }
    .mode {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 38px;
      height: 34px;
      border-radius: 10px;
      border: none;
      background: none;
      --mdc-icon-size: 22px;
    }
    .mode.on {
      background: var(--rt-accent);
      color: var(--rt-on-accent);
    }
    .nudges {
      display: inline-flex;
      gap: 4px;
    }
    .nudge {
      touch-action: none;
      width: 40px;
      height: 36px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 8px;
      border: 1px solid var(--rt-tile-border);
      background: var(--rt-button);
      color: var(--rt-text);
      --mdc-icon-size: 20px;
    }
    .context .stack {
      /* one line: many items scroll sideways, the label stays */
      display: flex;
      align-items: center;
      gap: 6px;
      flex: 1 1 0;
      min-width: 0;
    }
    .context .stack-items {
      display: flex;
      gap: 6px;
      overflow-x: auto;
      overscroll-behavior-x: contain; /* a swipe past its end: not the browser's swipe-back */
      min-width: 0;
      padding-bottom: 2px;
      scrollbar-width: thin;
    }
    .context .stack-items .pill {
      flex: none;
      white-space: nowrap;
    }
    .context .stack-label {
      color: var(--rt-text-secondary);
      font-size: 0.9rem;
    }
    .context .stack .pill.on {
      border-color: var(--rt-accent);
      color: var(--rt-accent);
    }
    .context.ask {
      color: var(--rt-light);
      --mdc-icon-size: 18px;
    }
    .context.ask .hint {
      color: var(--rt-text);
    }
    .context {
      flex: none;
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 6px;
      min-height: 32px;
      padding: 0 16px 6px;
    }
    .context .hint {
      flex: 1 1 200px;
    }
    .tool-name {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-weight: 700;
      white-space: nowrap;
      --mdc-icon-size: 20px;
    }
    .tool-name ha-icon {
      color: var(--rt-accent);
    }
    .area-at {
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 10px;
      border: 1px solid var(--rt-tile-border);
      background: var(--rt-panel-dark);
      white-space: nowrap;
    }
    .grid-wrap.landscape {
      display: flex;
      justify-content: center;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(var(--cols), var(--tile-w));
      gap: ${GAP}px;
      padding: 4px ${PAD}px ${PAD}px;
      width: max-content;
      height: max-content;
    }
    .mapscreen {
      position: absolute;
      inset: 0;
      z-index: 5;
      display: flex;
      flex-direction: column;
      background: var(--rt-page);
      /* the map pans itself; a drag anywhere here (also on a dialog over
         it, e.g. Help) must not scroll the page behind - which looks like
         the map moving. Scrolling lists inside dialogs still scroll. */
      touch-action: none;
      overscroll-behavior: none;
    }
    .mapscreen rt-map {
      flex: 1;
      min-height: 0;
    }
    .area-name.static {
      cursor: default;
      gap: 10px;
    }
    .layout.gear {
      position: relative;
    }
    .gear-dot {
      position: absolute;
      top: 4px;
      right: 4px;
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: var(--rt-light);
      pointer-events: none;
    }
    .layout.labelled {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 0 10px;
      font-size: 0.9rem;
      white-space: nowrap;
    }
    /* the map screen's title: one line of text (an editor's name first, the
       map's / room's lighter) - never squeezed into the buttons beside it */
    .map-title {
      flex: 1 1 auto;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 1.6rem;
      font-weight: 700;
      padding: 4px;
    }
    .map-title.area-name {
      /* the button version (the map view): the area name's look, one line */
      color: var(--rt-text);
      cursor: pointer;
    }
    .room-pick {
      /* the Layer Editor's room picker: the "· Kitchen" part of its title */
      border: none;
      background: none;
      padding: 0;
      font: inherit;
      font-weight: 400;
      color: var(--rt-text-secondary);
      cursor: pointer;
      --mdc-icon-size: 24px;
    }
    .pick-head {
      grid-column: 1 / -1;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--rt-text-secondary);
      padding: 4px 4px 0;
    }
    .pick-map {
      display: block;
      font-size: 0.75rem;
      color: var(--rt-text-secondary);
    }
    .map-title .of-mode {
      font-weight: 400;
      color: var(--rt-text-secondary);
    }
    .layout.back {
      flex: none;
    }
    .navslot {
      position: relative;
      overflow: hidden; /* the hidden measuring copies stay inside */
      display: flex;
      align-items: center;
      gap: 8px 12px;
      min-width: 0;
    }
    .navslot.row {
      flex: none;
      padding: 0 16px 8px;
    }
    .navslot.in-bar {
      /* the top bar's middle: whatever the title and the buttons leave */
      flex: 1 1 0;
      justify-content: center;
    }
    .wide .map-title {
      flex: 0 1 auto;
      max-width: 40%;
    }
    .navmeasure {
      /* natural widths: never squeezed to the slot (max-content, no shrink) */
      position: absolute;
      left: 0;
      top: 0;
      width: max-content;
      visibility: hidden;
      pointer-events: none;
      display: flex;
      gap: 12px;
      white-space: nowrap;
    }
    .navmeasure .navgroup {
      flex: none;
      overflow: visible;
      max-width: none;
    }
    .navgroup.collapsed {
      cursor: pointer;
    }
    .navgroup .floor {
      white-space: nowrap;
    }
    .floor.menu {
      display: flex;
      align-items: center;
      gap: 2px;
      --mdc-icon-size: 18px;
    }
    .navlist {
      position: absolute;
      z-index: 10;
      display: flex;
      flex-direction: column;
      align-items: stretch;
      gap: 6px;
      min-width: 160px;
      max-width: 220px;
      max-height: 60%;
      overflow-y: auto;
      padding: 8px;
      border: 1px solid var(--rt-tile-border);
      border-radius: 14px;
      background: var(--rt-panel-dark);
      box-shadow: 0 8px 30px var(--rt-page);
    }
    .navlist .floor {
      text-align: left;
    }
    .navgroup {
      /* the framed-group look (ui.ts groupStyles), laid out in a line */
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
      max-width: 100%;
      overflow-x: auto;
      overscroll-behavior-x: contain; /* a swipe past its end: not the browser's swipe-back */
      scrollbar-width: none;
      padding: 4px 6px 4px 10px;
      border: 1px solid var(--rt-tile-border);
      border-radius: 14px;
      background: var(--rt-panel-dark);
    }
    .navlabel {
      flex: none;
      display: flex;
      align-items: center;
      gap: 6px;
      font-weight: 500;
      padding-right: 8px;
      margin-right: 2px;
      border-right: 1px solid var(--rt-tile-border);
      --mdc-icon-size: 20px;
    }
    .navlabel ha-icon {
      color: var(--rt-accent);
    }
    .floor {
      flex: none;
      border: 1px solid var(--rt-tile-border);
      background: var(--rt-button);
      border-radius: 16px;
      padding: 6px 12px;
    }
    .floor.on {
      background: var(--rt-accent);
      color: var(--rt-on-accent);
      border-color: var(--rt-accent);
    }
    .editbar {
      flex: none;
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 0 16px 6px;
      flex-wrap: wrap;
    }
    .viewchoice {
      display: inline-flex;
      flex: none;
      align-items: center;
      gap: 4px;
      font-size: 0.85rem;
      color: var(--rt-text-secondary);
    }
    /* its own width (the bar's 50% cap is for the layer list) */
    .editbar .viewchoice .zoomin {
      width: 4.5em;
      font: inherit;
      color: var(--rt-text);
      background: var(--rt-button);
      border: 1px solid var(--rt-tile-border);
      border-radius: 8px;
      padding: 6px 6px;
    }
    .editbar .viewchoice select {
      max-width: none;
      flex: none;
    }
    .editbar select {
      font: inherit;
      color: var(--rt-text);
      background: var(--rt-button);
      border: 1px solid var(--rt-tile-border);
      border-radius: 8px;
      padding: 6px 8px;
      max-width: 50%;
    }
    .editbar .grow {
      flex: 1;
    }
    .pill {
      border-radius: 10px;
      padding: 7px 12px;
      border: 1px solid var(--rt-tile-border);
      background: var(--rt-button);
    }
    .pill.primary {
      background: var(--rt-accent);
      color: var(--rt-on-accent);
      border-color: var(--rt-accent);
    }
    button:disabled {
      opacity: 0.4;
      cursor: default;
    }
    .sheet {
      position: absolute;
      z-index: 9;
      left: 50%;
      bottom: 16px;
      transform: translate(calc(-50% + var(--sheet-dx, 0px)), var(--sheet-dy, 0px));
      width: min(380px, calc(100% - 24px));
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 12px 14px;
      border-radius: 16px;
      background: var(--rt-dialog);
      border: 1px solid var(--rt-tile-border);
      box-sizing: border-box;
    }
    .sheet-foot {
      display: flex;
      gap: 8px;
      justify-content: space-between;
      margin-top: 4px;
    }
    .sheet-head {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      cursor: grab;
      touch-action: none;
    }
    .grip {
      --mdc-icon-size: 20px;
      color: var(--rt-text-secondary);
      margin: 1px 0 0 -4px;
      flex: none;
    }
    .sheet-head > div {
      flex: 1;
      min-width: 0;
    }
    .sheet-title {
      font-weight: 700;
    }
    .sheet select {
      font: inherit;
      color: var(--rt-text);
      background: var(--rt-button);
      border: 1px solid var(--rt-tile-border);
      border-radius: 8px;
      padding: 6px 8px;
    }
    .danger {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 8px;
      border-radius: 10px;
      border: 1px solid var(--rt-heat-strong);
      background: none;
      color: var(--rt-heat-strong);
      --mdc-icon-size: 18px;
    }
    .popup {
      position: absolute;
      z-index: 9;
      display: flex;
      gap: var(--pg);
      padding: var(--pg);
      border-radius: 14px;
      background: var(--rt-dialog);
      border: 1px solid var(--rt-tile-border);
      box-shadow: 0 8px 30px var(--rt-page);
      overflow-x: auto;
      /* a swipe past either end stays here: never the page's scroll or the
         browser's swipe-back (which left the map and closed this) */
      overscroll-behavior: contain;
      scrollbar-width: none;
      box-sizing: border-box;
    }
    .popup::-webkit-scrollbar {
      display: none;
    }
    .popup.scrolls {
      scroll-snap-type: x mandatory;
      scroll-padding: var(--pg);
    }
    .popup-item {
      position: relative;
      flex: none;
      width: var(--pw);
      scroll-snap-align: start;
    }
    .popup-item .tile {
      width: 100%;
    }
    .popup-more {
      flex: none;
      align-self: center;
      padding: 10px 14px;
      border-radius: 12px;
      border: 1px dashed var(--rt-tile-border);
      color: var(--rt-text-secondary);
      font-size: 0.9rem;
      white-space: nowrap;
      scroll-snap-align: end;
    }
    .popup-tag {
      position: absolute;
      top: 4px;
      right: 6px;
      font-size: 0.7rem;
      padding: 1px 6px;
      border-radius: 8px;
      background: var(--rt-button);
      color: var(--rt-text-secondary);
      pointer-events: none;
    }
    /* portrait: which part of the area is on screen - floating at the bottom */
    .where {
      position: absolute;
      left: 50%;
      bottom: 14px;
      transform: translateX(-50%);
      z-index: 2;
      padding: 6px 8px;
      border-radius: 10px;
      background: var(--rt-dialog);
      opacity: 0.85;
      pointer-events: none;
      display: grid;
      grid-template-columns: repeat(var(--cols), 7px);
      gap: 3px;
      flex: none;
    }
    .where span {
      width: 7px;
      height: 9px;
      border-radius: 2px;
      background: var(--rt-button);
    }
    .where span.seen {
      background: var(--rt-accent);
      color: var(--rt-on-accent);
    }
    /* A tile is the panel's 198 x 254 design (tile.yaml), scaled to its
       width: --u = one design pixel. */
    .tile {
      position: relative;
      aspect-ratio: 198 / 254;
      container-type: inline-size;
      border-radius: 8px;
      border: 1px solid var(--rt-tile-border);
      background: var(--rt-tile);
      min-width: 0;
      overflow: hidden;
      cursor: pointer;
    }
    .tile > * {
      --u: calc(100cqw / 198);
    }
    .tile.blank {
      background: transparent;
      border-color: transparent;
      cursor: default;
    }
    .tile.unavailable {
      opacity: 0.45;
    }
    /* switching / offline: the controls dimmed, no roller - the reading and
       the full status across the tile */
    .tile.busy .name,
    .tile.busy .sw,
    .tile.busy .heater,
    .tile.busy .icon {
      opacity: 0.45;
    }
    .tile.busy .thermo-temp,
    .tile.busy .thermo-status {
      left: calc(12 * var(--u));
      right: calc(12 * var(--u));
      width: auto;
      text-transform: none;
    }
    .name {
      position: absolute;
      top: calc(12 * var(--u));
      left: calc(8 * var(--u));
      right: calc(8 * var(--u));
      font-size: calc(22 * var(--u));
      line-height: calc(26 * var(--u));
      text-align: center;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      color: var(--rt-text);
    }
    .sw {
      position: absolute;
      top: calc(58 * var(--u));
      left: 50%;
      transform: translateX(-50%);
    }
    .roller {
      position: absolute;
      top: calc(114 * var(--u));
      left: calc(50% + (var(--x) - var(--rw) / 2) * var(--u));
      width: calc(var(--rw) * var(--u));
    }
    .prefix {
      position: absolute;
      top: calc(162 * var(--u));
      right: calc(50% - (var(--x) - var(--rw) / 2 - 6) * var(--u));
      transform: translateY(-50%);
      font-size: calc(16 * var(--u));
      font-weight: 300;
      color: var(--rt-roller-color);
      white-space: nowrap;
    }
    .swatch {
      position: absolute;
      top: calc(128 * var(--u));
      left: calc(50% + (var(--x) - 30) * var(--u));
      width: calc(60 * var(--u));
      height: calc(60 * var(--u));
      padding: 0;
      border: none;
      border-radius: 50%;
      background: var(--sw);
    }
    .swatch.off {
      opacity: 0.45;
    }
    .swatch img {
      width: 100%;
      height: 100%;
      display: block;
    }
    .icon {
      position: absolute;
      left: calc(5 * var(--u));
      bottom: calc(10 * var(--u));
      width: calc(60 * var(--u));
      height: calc(60 * var(--u));
    }
    /* pool / spa heater button: bottom right, under the roller */
    .heater {
      position: absolute;
      right: calc(14 * var(--u));
      bottom: calc(10 * var(--u));
      width: calc(44 * var(--u));
      height: calc(44 * var(--u));
      padding: 0;
      border-radius: 50%;
      border: 1px solid var(--rt-tile-border);
      background: var(--rt-button);
      color: var(--rt-text-secondary);
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      --mdc-icon-size: calc(28 * var(--u));
    }
    /* the rollers' strong red / blue (user, 2026-11-12: the soft ones read grayish) */
    .heater.heat {
      color: var(--rt-heat-strong);
      border-color: var(--rt-heat-strong);
    }
    .heater.cool {
      color: var(--rt-cool-strong);
      border-color: var(--rt-cool-strong);
    }
    /* asked for, not there yet: a stopwatch (the panels' look), ring in the asked colour */
    .heater.waiting {
      color: var(--rt-accent);
    }
    .heater:disabled {
      opacity: 0.45;
      cursor: default;
    }
    /* scene / script: one big play button in the middle */
    .run {
      position: absolute;
      left: 50%;
      top: calc(128 * var(--u));
      transform: translate(-50%, -50%);
      width: calc(96 * var(--u));
      height: calc(96 * var(--u));
      padding: 0;
      border-radius: 50%;
      border: calc(4 * var(--u)) solid var(--run);
      background: var(--rt-button);
      color: var(--run);
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: background 0.15s, color 0.15s;
      --mdc-icon-size: calc(52 * var(--u));
    }
    .kind-scene .run {
      --run: var(--rt-scene);
    }
    .kind-script .run {
      --run: var(--rt-script);
    }
    .run.lit {
      background: var(--run);
      color: var(--rt-on-accent);
    }
    .run:disabled {
      opacity: 0.45;
      cursor: default;
    }
    .band {
      position: absolute;
      top: calc(162 * var(--u));
      left: calc(50% + (var(--x) - var(--rw) / 2) * var(--u));
      width: calc(var(--rw) * var(--u));
      display: flex;
      justify-content: space-between;
      font-size: calc(16 * var(--u));
      color: var(--rt-text-secondary);
      pointer-events: none;
    }
    .thermo-temp {
      position: absolute;
      top: calc(98 * var(--u));
      left: calc(12 * var(--u));
      width: calc(92 * var(--u));
      text-align: center;
      font-size: calc(44 * var(--u));
      font-weight: 700;
      color: var(--rt-text);
    }
    .thermo-temp.heat {
      color: var(--rt-heat-strong);
    }
    .thermo-temp.cool {
      color: var(--rt-cool-strong);
    }
    .thermo-temp.stale {
      opacity: 0.45;
    }
    .thermo-status {
      position: absolute;
      top: calc(152 * var(--u));
      left: calc(12 * var(--u));
      width: calc(92 * var(--u));
      text-align: center;
      font-size: calc(16 * var(--u));
      line-height: calc(20 * var(--u));
      color: var(--rt-text-secondary);
      text-transform: capitalize;
    }
    .arrange {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin: 2px 0 4px;
      --mdc-icon-size: 18px;
    }
    .arrange-note {
      flex-basis: 100%;
      font-size: 12px;
      color: var(--rt-text-secondary);
    }
    .arrange-btn {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      border: 1px solid var(--rt-tile-border);
      background: var(--rt-button);
      color: var(--rt-text);
      border-radius: 999px;
      padding: 5px 10px;
      font-size: 0.85rem;
    }
    /* vacuum tile: its own wording (no Title Case); "needs you" amber, a fault red */
    .state-center[class*="vac-"] {
      text-transform: none;
    }
    .state-center.vac-attention {
      color: var(--rt-vac-attention);
    }
    .state-center.vac-error {
      color: var(--rt-vac-error);
    }
    .state-center.vac-cleaning,
    .state-center.vac-returning {
      color: var(--rt-text);
    }
    /* a vacuum with a room queue: its map (the queue on it), the status
       beside the icon */
    .tile-map-box {
      position: absolute;
      top: calc(44 * var(--u));
      left: calc(8 * var(--u));
      right: calc(8 * var(--u));
      height: calc(138 * var(--u));
    }
    .vac-note {
      position: absolute;
      top: calc(138 * var(--u));
      left: calc(10 * var(--u));
      right: calc(10 * var(--u));
      display: flex;
      gap: calc(4 * var(--u));
      align-items: flex-start;
      justify-content: center;
      text-align: left;
      font-size: calc(13 * var(--u));
      line-height: calc(16 * var(--u));
      color: var(--rt-light);
      --mdc-icon-size: calc(16 * var(--u));
    }
    .vac-line {
      position: absolute;
      left: calc(70 * var(--u));
      right: calc(8 * var(--u));
      bottom: calc(14 * var(--u));
      height: calc(44 * var(--u));
      display: flex;
      align-items: center;
      font-size: calc(15 * var(--u));
      line-height: calc(19 * var(--u));
      color: var(--rt-text-secondary);
      overflow: hidden;
    }
    .queuebar .qauto {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 0.85rem;
      color: var(--rt-text-secondary);
      margin-left: 6px;
    }
    .queuebar .qstatus {
      font-size: 0.95rem;
      color: var(--rt-text-secondary);
      margin-right: 6px;
    }
    /* the status in the queue's colours (the panels') */
    .vac-cleaning.vac-line,
    .qstatus.vac-cleaning {
      color: var(--rt-vac-cleaning);
    }
    .vac-paused.vac-line,
    .qstatus.vac-paused {
      color: var(--rt-vac-paused);
    }
    .vac-attention.vac-line,
    .qstatus.vac-attention {
      color: var(--rt-vac-attention);
    }
    .vac-error.vac-line,
    .qstatus.vac-error {
      color: var(--rt-vac-error);
    }
    .queue-line .qchips {
      display: flex;
      gap: 6px;
      overflow-x: auto;
      overscroll-behavior-x: contain; /* a swipe past its end: not the browser's swipe-back */
      min-width: 0;
      flex: 0 1 auto;
      scrollbar-width: thin;
    }
    .qchip {
      flex: none;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 3px 4px 3px 10px;
      border-radius: 999px;
      background: var(--rt-button);
      border: 1px solid var(--rt-tile-border);
      font-size: 0.9rem;
      white-space: nowrap;
      --mdc-icon-size: 16px;
    }
    .qchip.current {
      border-color: var(--q);
      color: var(--q);
      padding-right: 10px;
    }
    .qarea {
      flex: none;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 5px 12px;
      border-radius: 999px;
      border: 1px solid var(--rt-tile-border);
      background: var(--rt-button);
      color: var(--rt-text);
      font-size: 0.9rem;
      white-space: nowrap;
      cursor: pointer;
      --mdc-icon-size: 16px;
    }
    /* the queue's colours (vacqueue.ts ROOM_STATES - the panels' key) */
    .queued {
      --q: var(--rt-vac-queued);
    }
    .starting {
      --q: var(--rt-vac-starting);
    }
    .cleaning {
      --q: var(--rt-vac-cleaning);
    }
    .paused {
      --q: var(--rt-vac-paused);
    }
    .attention {
      --q: var(--rt-vac-attention);
    }
    .error {
      --q: var(--rt-vac-error);
    }
    .qarea.queued {
      background: var(--q);
      border-color: var(--q);
    }
    .qarea.current {
      border-color: var(--q);
      color: var(--q);
    }
    .qlegend {
      position: absolute;
      left: 8px;
      bottom: calc(8px + env(safe-area-inset-bottom, 0px));
      display: flex;
      flex-wrap: wrap;
      gap: 4px 10px;
      max-width: calc(100% - 16px);
      padding: 4px 10px;
      border-radius: 10px;
      background: var(--rt-dialog);
      font-size: 0.75rem;
      color: var(--rt-text-secondary);
      pointer-events: none;
    }
    .qlegend span {
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .qlegend i {
      width: 10px;
      height: 10px;
      border-radius: 3px;
      background: var(--q);
    }
    .queue-areas .qchips {
      display: flex;
      gap: 6px;
      overflow-x: auto;
      overscroll-behavior-x: contain; /* a swipe past its end: not the browser's swipe-back */
      min-width: 0;
      flex: 1 1 0;
      scrollbar-width: thin;
    }
    .qmini {
      border: none;
      background: none;
      color: var(--rt-text-secondary);
      padding: 2px;
      cursor: pointer;
      display: inline-flex;
    }
    .state-center {
      position: absolute;
      top: calc(110 * var(--u));
      left: 0;
      right: 0;
      text-align: center;
      font-size: calc(16 * var(--u));
      color: var(--rt-text-secondary);
      text-transform: capitalize;
    }
    .appliance-body {
      position: absolute;
      top: calc(50 * var(--u));
      left: calc(12 * var(--u));
      right: calc(12 * var(--u));
      bottom: calc(12 * var(--u));
      font-size: calc(16 * var(--u));
    }
    .map-art {
      top: calc(98 * var(--u));
      width: calc(76 * var(--u));
      height: calc(58 * var(--u));
    }
    .run-art {
      width: calc(60 * var(--u));
      height: calc(60 * var(--u));
    }
    .map-icon {
      position: absolute;
      top: calc(90 * var(--u));
      left: 50%;
      transform: translateX(-50%);
      --mdc-icon-size: calc(80 * var(--u));
      color: var(--rt-accent);
    }
  `];
}

if (!customElements.get("room-tiles-panel")) {
  customElements.define("room-tiles-panel", RoomTilesPanel);
}
