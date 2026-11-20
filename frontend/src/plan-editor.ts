// <rt-plan-editor>: draws / edits one map - walls, windows, openings
// (doorways), rooms (zones linked to HA areas), filled shapes (floor, water,
// grass...), links to other maps, and the map's settings (name, HA floor, wall
// thickness, marker layers). A trace PICTURE (a photo / scan of a floor plan)
// can sit under the drawing to trace over (kept in this browser only,
// trace-store.ts - not worth telling people).
//
// One draft per session: every change goes into it with undo / redo; Save
// changes writes it to HA in one step (room_tiles.set_map), Cancel drops it.
// Input conventions come from input.ts (docs/UI.md "Input"): touch builds a
// selection, mouse replaces it (Shift / Ctrl / Cmd add)...
//
// Events: "close" (after Save or Cancel), "open-map" {map} (another map was
// added: edit that one next), "map-removed".

import { fullName } from "./picker";
import { LitElement, css, html, nothing, svg, type PropertyValues, type TemplateResult } from "lit";
import { DialogPin } from "./dialog-pin";
import { EDGE_SPEED, applySelect, boxSelectMode, edgePull, keyIntent, selectMode, startsBox, typingIn, type SelectMode } from "./input";
import { bbox, cutWalls, dist, nearestOnSeg, pointIn, polyArea, snap, type Pt, type Seg, type SnapResult } from "./geom";
import { ARRANGE_OPS, anchorOf, arrange, numbered, type ArrangeOp } from "./arrange";
import { SheetDrag } from "./sheet-drag";
import { labelAt, planBase, planLabels, planStyles, poly, type VacuumView } from "./plan-draw";
import {
  SEG_KEY,
  SEG_KINDS,
  SHAPE_STYLES,
  NEW_SHAPE_STYLES,
  addLayer,
  addZone,
  cloneMap,
  convertSegs,
  cornersAt,
  deleteRefs,
  refsAfterDelete,
  exists,
  fitBounds,
  getPts,
  insertCorner,
  itemsOf,
  moveCorners,
  numberedName,
  parseRef,
  removeCorner,
  snapPoints,
  translate,
  type ItemKind,
  type SegKind,
} from "./plan-model";
import { MAX_LAYERS, MAX_MAPS, layersAt, layersLabel, layersOf, viewZoom, zoomStep, type MapData, type MapMarker, type MapShape } from "./map";
import { zoomBox, zoomLabel, zoomStyles } from "./zoom-box";
import type { HomeAssistant, RoomTilesDoc } from "./types";
import { dialogStyles, rowStyles, toggle, noSelectStyles, groupStyles, touchNote, touchNoteShown, touchNoteStyles, ScrollFades } from "./ui";
import { deleteTrace, loadTrace, saveTrace, type TracePicture } from "./trace-store";
import { picBox, picHandleAt, resizePic, tiltFrom, traceBlend, turn90, type PicBox, type PicHandle } from "./trace-geom";
import type { ThemeName } from "./theme";
import "./map-help";
import "./unsaved";
import { listOf, num, t as tr, th, tn } from "./i18n";

type Tool = "select" | SegKind | "zone" | "shape" | "link" | "picture";

interface Camera {
  x: number;
  y: number;
  w: number;
  h: number;
}

// a tool's name: editor.tool_<id> (its tooltip), editor.tool_<id>_short (the line under the bar)
const TOOLS: { id: Tool; icon: string; key: string }[] = [
  { id: "select", icon: "mdi:cursor-default-outline", key: "v" },
  { id: "wall", icon: "mdi:wall", key: "w" },
  { id: "window", icon: "mdi:window-closed-variant", key: "n" },
  { id: "opening", icon: "mdi:door-open", key: "d" },
  { id: "zone", icon: "mdi:vector-square", key: "r" },
  { id: "shape", icon: "mdi:shape-polygon-plus", key: "s" },
  { id: "link", icon: "mdi:stairs", key: "l" },
  { id: "picture", icon: "mdi:image-outline", key: "p" },
];

// the line under the toolbar: a few words - the details are on the Help page
const KINDS: Record<ItemKind, true> = { wall: true, window: true, opening: true, zone: true, shape: true, link: true };
// (editor.hint_<tool>; the picture tool has its own line)
const hint = (tool: Tool): string => (tool === "picture" ? "" : tr(`editor.hint_${tool}`));
const styleName = (style: MapShape["style"]): string => tr(`editor.style_${style}`);
/** an item kind's name, and "{n} walls" for a count */
const kindName = (kind: ItemKind): string => tr(`editor.kind_${kind}`);
const kindCount = (kind: ItemKind, n: number): string => tn(`editor.count_${kind}`, n);

interface Press {
  id: number;
  x: number;
  y: number;
  start: Pt;
  moved: boolean;
  touch: boolean;
  act: "pan" | "box" | "draw" | "move" | "corner" | "label" | "pic-move" | "pic-size" | "pic-turn" | "none";
  hit?: string;
  mode: SelectMode;
  base?: MapData; // the drawing before this drag (undo)
  work?: MapData; // the drawing the drag applies to
  ids?: string[];
  anchor?: Pt; // the grabbed corner (move snapping)
  corners?: [string, number][];
  skip?: Set<string>;
  from?: Pt; // draw: where it started (snapped)
  inserted?: boolean; // a mid-edge dot: a new corner
  pic?: TracePicture; // the picture before this drag
  picHandle?: PicHandle;
}

const DRAG_PX = 6;
const NUDGE = 0.5; // map units a nudge moves (the grid points are stored on)
// drags that follow the pointer - near the edge the map scrolls with them
const EDGE_ACTS = new Set<Press["act"]>(["box", "draw", "move", "corner", "label", "pic-move", "pic-size"]);
const HANDLE_PX = 7;
const KNOB_PX = 34; // the picture's turn knob, above its top edge
const TILT_STEP = 0.5; // degrees per press of the fine-turn buttons
const LABEL_HANDLE_DY = 18; // px below a room's name: drag it to move the name
const UNDO_MAX = 100;

export class RtPlanEditor extends LitElement {
  /** fades where a scrolling area has more (ui.ts ScrollFades) */
  protected readonly _scrollFades = new ScrollFades(this, ".list, .mapmenu");

  /** the dialog's top edge stays put while its content changes (dialog-pin.ts) */
  readonly dialogPin = new DialogPin(this);
  static properties = {
    hass: { attribute: false },
    doc: { attribute: false },
    map: { attribute: false },
    theme: { type: String },
    openDialog: { type: String },
    returnAfterSettings: { type: Boolean },
    screenButton: { attribute: false },
    settingsDot: { type: Boolean },
    _touchNote: { state: true },
    _draft: { state: true },
    _undo: { state: true },
    _redo: { state: true },
    _tool: { state: true },
    _sel: { state: true },
    _cam: { state: true },
    _size: { state: true },
    _chain: { state: true },
    _hover: { state: true },
    _drawPreview: { state: true },
    _box: { state: true },
    _snapOn: { state: true },
    _joinOn: { state: true },
    _boxMode: { state: true },
    _shapeStyle: { state: true },
    _trace: { state: true },
    _traceUrl: { state: true },
    _dialog: { state: true },
    _flashLayers: { state: true },
    _mapMenu: { state: true },
    _error: { state: true },
    _busy: { state: true },
    _confirmDelete: { state: true },
    _confirmClear: { state: true },
    _newMap: { state: true },
    _newFloor: { state: true },
    _vacuum: { state: true },
    _corner: { state: true },
  };

  hass?: HomeAssistant;
  doc?: RoomTilesDoc;
  map?: MapData;
  theme: ThemeName = "dark";
  /** open straight on a dialog (e.g. "settings": from marker editing's
   *  "change a layer's zoom setting") */
  openDialog?: "settings";
  /** opened on Map settings from the Layer Editor: closing it goes back there */
  returnAfterSettings = false;
  /** the top bar's first button, the same on every screen (the panel's:
   *  Home Assistant's menu / full screen) */
  screenButton?: TemplateResult | typeof nothing;
  /** the Settings button's dot: something in its menu needs attention */
  settingsDot = false;
  private _touchNote = touchNoteShown(); // "best on a tablet or computer" (phones)

  private _draft?: MapData;
  private _undo: MapData[] = [];
  private _redo: MapData[] = [];
  private _tool: Tool = "select";
  private _sel: string[] = [];
  /** the selection sheet can be dragged out of the way by its title row */
  private _sheetDrag = new SheetDrag(this, "room-tiles:sheet-plan");
  private _cam: Camera = { x: 0, y: 0, w: 1, h: 1 };
  private _size = { w: 1, h: 1 };
  /** a wall / room being drawn corner by corner */
  private _chain?: { kind: Tool; pts: Pt[] };
  /** the snapped pointer (mouse hover, or the end of a drag) */
  private _hover?: SnapResult;
  /** a drag in a drawing tool: from - to */
  private _drawPreview?: { a: Pt; b: Pt };
  private _box?: { x0: number; y0: number; x1: number; y1: number };
  private _snapOn = true;
  /** shared corners move together (off: a dragged / nudged corner moves only
   *  for its own item) */
  private _joinOn = true;
  private _boxMode = false;
  private _shapeStyle: MapShape["style"] = "grass";
  private _trace?: TracePicture;
  private _traceUrl?: string;
  private _justAdded?: string; // the room just drawn (its sheet shows in the Room tool)
  private _mapMenu = false; // the title's map picker
  private _afterDrag = false; // something was just dragged: the next tap selects afresh
  private _dragAt?: { x: number; y: number }; // the pointer during a drag (client px)
  private _edgeAnim?: number; // edge scrolling's animation frame
  /** the rooms / shapes under the last tap, when there were several (Select) */
  private _stack?: string[];
  private _traceAspect = 1; // natural height / width
  private _dialog?: "settings" | "help" | "unsaved" | "new-map";
  /** opened from an "Add layer" / Layer settings link: the Marker layers
   *  group is framed (and scrolled to) until Map settings closes */
  private _flashLayers = false;
  private _newFloor = ""; // the new map's HA floor
  private _error = "";
  private _busy = false;
  private _confirmDelete = false;
  private _confirmClear = false; // Map settings' Clear map: asking
  private _newMap = "";
  /** a room / shape corner picked by tapping its dot (Delete corner) */
  private _corner?: { ref: string; vi: number };
  /** the vacuum view: this vacuum's zones show, rooms it can't clean grey out */
  private _vacuum?: string;

  private _ro?: ResizeObserver;
  private _roOn?: Element; // (the svg it watches: a new observer after a reattach watches it again)
  private _pointers = new Map<number, { x: number; y: number }>();
  private _pinch?: { dist: number; mid: { x: number; y: number }; cam: Camera };
  private _press?: Press;

  // ---- lifecycle ----------------------------------------------------------------

  connectedCallback(): void {
    super.connectedCallback();
    window.addEventListener("keydown", this._onKey);
    window.addEventListener("beforeunload", this._onBeforeUnload);
    this._ro = new ResizeObserver(() => {
      const svgEl = this.renderRoot.querySelector("svg");
      const w = svgEl?.clientWidth || 1;
      const h = svgEl?.clientHeight || 1;
      if (w !== this._size.w || h !== this._size.h) this._size = { w, h };
    });
    if (this.hasUpdated) this.requestUpdate(); // (attached again: updated() hands the svg to the new observer)
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    window.removeEventListener("keydown", this._onKey);
    window.removeEventListener("beforeunload", this._onBeforeUnload);
    this._ro?.disconnect();
    this._roOn = undefined;
    if (this._traceUrl) URL.revokeObjectURL(this._traceUrl);
  }

  protected willUpdate(changed: PropertyValues): void {
    // the "Here:" row shows any selection: one it doesn't cover (Shift-click,
    // Select all...) becomes the row
    if (changed.has("_sel") && this._sel.length && !(this._stack && this._sel.every((r) => this._stack!.includes(r))))
      this._stack = [...this._sel];
    if (changed.has("map") && this.map && this._draft?.id !== this.map.id) {
      this._draft = cloneMap(this.map);
      this._draft.layers = this._draft.layers?.length ? this._draft.layers : [{ id: "house", name: tr("editor.layer_main"), min_zoom: 1 }];
      this._undo = [];
      this._redo = [];
      this._sel = [];
      this._stack = undefined;
      this._justAdded = undefined;
      this._chain = undefined;
      this._cam = this._overview();
      this._confirmDelete = false;
      void this._loadTrace(this.map.id);
    }
    if (changed.has("openDialog") && this.openDialog) {
      this._dialog = this.openDialog;
      this._flashLayers = true;
    }
    if (changed.has("_dialog") && this._dialog !== "settings") this._flashLayers = false;
  }

  get dirty(): boolean {
    return this._undo.length > 0;
  }

  private _onBeforeUnload = (e: BeforeUnloadEvent) => {
    if (this.dirty) e.preventDefault();
  };

  // ---- draft / undo -------------------------------------------------------------

  /** Apply a change to the drawing (undoable). */
  private _change(fn: (m: MapData) => void): void {
    if (!this._draft) return;
    const next = cloneMap(this._draft);
    fn(next);
    this._commit(this._draft, next);
  }

  private _commit(before: MapData, after: MapData): void {
    this._undo = [...this._undo, before].slice(-UNDO_MAX);
    this._redo = [];
    this._draft = after;
  }

  private _undoStep(): void {
    const c = this._chain;
    if (c && (c.kind === "zone" || c.kind === "shape" || c.kind === "window" || c.kind === "opening" || c.pts.length <= 1)) {
      // an unfinished room / shape / gap: take back its last corner
      c.pts.pop();
      this._chain = c.pts.length ? { ...c } : undefined;
      return;
    }
    if (!this._undo.length || !this._draft) return;
    if (c) this._chain = c.pts.length > 2 ? { ...c, pts: c.pts.slice(0, -1) } : undefined;
    this._redo = [...this._redo, this._draft];
    this._draft = this._undo[this._undo.length - 1];
    this._undo = this._undo.slice(0, -1);
    this._fixSel();
  }

  private _redoStep(): void {
    if (!this._redo.length || !this._draft) return;
    this._chain = undefined;
    this._undo = [...this._undo, this._draft];
    this._draft = this._redo[this._redo.length - 1];
    this._redo = this._redo.slice(0, -1);
    this._fixSel();
  }

  private _fixSel(): void {
    const d = this._draft;
    this._sel = d ? this._sel.filter((r) => exists(d, r)) : [];
    this._stack = undefined; // (its items may have moved)
  }

  // ---- camera -------------------------------------------------------------------

  private _overview(): Camera {
    const [x0, y0, x1, y1] = this.map?.bounds ?? [0, 0, 1000, 600];
    const mx = (x1 - x0) * 0.08;
    const my = (y1 - y0) * 0.08;
    return { x: x0 - mx, y: y0 - my, w: x1 - x0 + 2 * mx, h: y1 - y0 + 2 * my };
  }

  /** map units per CSS px */
  private _scaleOf(cam: Camera = this._cam): number {
    return Math.max(cam.w / this._size.w, cam.h / this._size.h);
  }

  private _toMap(cx: number, cy: number, cam: Camera = this._cam): Pt {
    const r = this.renderRoot.querySelector("svg")?.getBoundingClientRect() ?? { left: 0, top: 0 };
    const s = this._scaleOf(cam);
    const offX = (this._size.w * s - cam.w) / 2;
    const offY = (this._size.h * s - cam.h) / 2;
    return [cam.x - offX + (cx - r.left) * s, cam.y - offY + (cy - r.top) * s];
  }

  private _zoomAt(cx: number, cy: number, factor: number, base: Camera = this._cam): Camera {
    const [mx, my] = this._toMap(cx, cy, base);
    const full = this._overview();
    const w = Math.min(full.w * 4, Math.max(full.w / 40, base.w * factor));
    const k = w / base.w;
    return { x: mx - (mx - base.x) * k, y: my - (my - base.y) * k, w, h: base.h * k };
  }

  /** The zoom number (viewZoom, like marker editing): 1 = the whole map
   *  (its bounds) on a panel's screen. */
  private get _zoom(): number {
    const [x0, y0, x1, y1] = this._draft?.bounds ?? this.map?.bounds ?? [0, 0, 1000, 600];
    return viewZoom({ w: x1 - x0, h: y1 - y0 }, this._cam, this._size);
  }

  /** The zoom buttons: the next 0.25 step about the middle of the view. */
  private _zoomBy(dir: 1 | -1): void {
    this._zoomTo(zoomStep(this._zoom, dir));
  }

  /** The zoom box (zoom-box.ts, the same as marker editing's): the zoom and
   *  the layer people see at it - handy for the layers' zoom settings. */
  private _renderZoom(): TemplateResult {
    const z = this._zoom;
    const showing = layersAt(this._draft, z);
    const shown = showing[showing.length - 1] ?? layersOf(this._draft)[0];
    const full = this._overview();
    return zoomBox({
      z,
      layer: layersLabel(shown, showing),
      atIn: this._cam.w <= full.w / 40 + 1e-6,
      atOut: this._cam.w >= full.w * 4 - 1e-6,
      onIn: () => this._zoomBy(1),
      onOut: () => this._zoomBy(-1),
      start: shown?.min_zoom,
      onStart: shown ? () => this._zoomTo(shown.min_zoom) : undefined,
    });
  }

  /** To zoom `z` (viewZoom) about the middle of the view. */
  private _zoomTo(z: number): void {
    const now = this._zoom;
    const full = this._overview();
    const c = this._cam;
    const w = Math.min(full.w * 4, Math.max(full.w / 40, (c.w * now) / Math.max(0.05, z)));
    const k = w / c.w;
    this._cam = { x: c.x + (c.w - w) / 2, y: c.y + (c.h - c.h * k) / 2, w, h: c.h * k };
  }

  private _onWheel(e: WheelEvent): void {
    e.preventDefault();
    this._cam = this._zoomAt(e.clientX, e.clientY, Math.pow(1.0015, e.deltaY));
  }

  // ---- snapping -----------------------------------------------------------------

  private _tol(touch: boolean): number {
    return (touch ? 18 : 11) * this._scaleOf();
  }

  private _snap(p: Pt, touch: boolean, from?: Pt, skip?: Set<string>, base?: MapData): SnapResult {
    const m = base ?? this._draft;
    if (!this._snapOn || !m) return { pt: [Math.round(p[0] * 2) / 2, Math.round(p[1] * 2) / 2] };
    const points = snapPoints(m, skip);
    if (this._chain) points.push(...this._chain.pts);
    return snap(p, { points, segs: m.walls as Seg[] }, this._tol(touch), from);
  }

  // ---- hit tests ----------------------------------------------------------------

  /** a selection handle under p: a corner, a mid-edge "add corner" dot, a
   *  room's label */
  private _handleAt(p: Pt, touch: boolean): { act: "corner" | "label"; corners?: [string, number][]; insert?: [string, number] } | undefined {
    const d = this._draft;
    if (!d || this._sel.length !== 1) return undefined;
    const ref = this._sel[0];
    const tol = (touch ? 20 : HANDLE_PX + 4) * this._scaleOf();
    const { kind, i } = parseRef(ref);
    if (kind === "link") return undefined;
    const pts = getPts(d, ref);
    for (let vi = 0; vi < pts.length; vi++) if (dist(p, pts[vi]) <= tol) return { act: "corner", corners: this._cornersOf(d, ref, vi) };
    if (kind === "zone" || kind === "shape") {
      for (let k = 0; k < pts.length; k++) {
        const a = pts[k];
        const b = pts[(k + 1) % pts.length];
        if (dist(p, [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]) <= tol) return { act: "corner", insert: [ref, k] };
      }
    }
    if (kind === "zone") {
      const [lx, ly] = labelAt(d.zones[i]);
      if (dist(p, [lx, ly + LABEL_HANDLE_DY * this._scaleOf()]) <= tol) return { act: "label" };
    }
    return undefined;
  }

  /** Corner `vi` of `ref` and what moves with it: the corners joined to it
   *  (joinGroup) - or, with "Corners move together" off, it alone. */
  private _cornersOf(m: MapData, ref: string, vi: number): [string, number][] {
    if (!this._joinOn) return [[ref, vi]];
    return cornersAt(m, getPts(m, ref)[vi], undefined, ref);
  }

  /** the item under p: links, then lines, then the smallest room / shape */
  private _itemAt(p: Pt, touch: boolean): string | undefined {
    return this._stackAt(p, touch)[0];
  }

  /** What's under p, in the order a tap picks them (tapping again / the
   *  "Here:" buttons go on down it): on a line, the links and walls /
   *  windows / openings there, nearest first (a window over a wall, a door
   *  beside it); elsewhere the rooms and shapes, smallest first. */
  private _stackAt(p: Pt, touch: boolean): string[] {
    const d = this._draft;
    if (!d) return [];
    const s = this._scaleOf();
    const near = (touch ? 16 : 9) * s;
    const links: string[] = [];
    for (let i = d.links.length - 1; i >= 0; i--) if (dist(p, d.links[i].at) <= near * 1.6) links.push(`link:${i}`);
    const segs: { ref: string; d: number }[] = [];
    const lim = Math.max(near, d.wall_width / 2 + 2 * s);
    for (const k of SEG_KINDS) {
      d[SEG_KEY[k]].forEach((sg, i) => {
        const n = nearestOnSeg(p, sg as Seg);
        if (n.d <= lim) segs.push({ ref: `${k}:${i}`, d: n.d });
      });
    }
    segs.sort((a, b) => a.d - b.d);
    // on a line: just the lines (and links) there - the rooms either side
    // are a tap on their middle away; else the rooms and shapes
    const onLine = [...links, ...segs.map((x) => x.ref)];
    return onLine.length ? onLine : this._polysAt(p);
  }

  /** Rooms and shapes under p, smallest first - a room and a shape with the
   *  same outline (a porch: the room, and its deck) are both in it. */
  private _polysAt(p: Pt): string[] {
    const d = this._draft;
    if (!d) return [];
    return [
      ...d.zones.map((z, i) => ({ ref: `zone:${i}`, pts: z.points })).filter((it) => this._shown(it.ref)),
      ...d.shapes.map((sh, i) => ({ ref: `shape:${i}`, pts: sh.points })),
    ]
      .filter((it) => pointIn(p[0], p[1], it.pts))
      .sort((a, b) => polyArea(a.pts) - polyArea(b.pts))
      .map((it) => it.ref);
  }

  /** A tap on an item (Select or Box select): touch or mouse alike, the one
   *  beneath replaces the selected one; the first tap after a drag starts a
   *  new selection (touch adds otherwise); the "Here:" row lists what's there. */
  private _tapSelect(p: Press): void {
    const next = this._tapPick(p);
    const mode = this._afterDrag ? "replace" : p.mode;
    this._afterDrag = false;
    this._sel = next ? [next] : applySelect(this._sel, [p.hit!], mode);
    const stack = this._stackAt(p.start, p.touch);
    this._stack = stack.length && stack.includes(p.hit!) ? stack : undefined;
  }

  /** A tap on what's already selected (alone): the next room / shape under
   *  it - tap again to reach the one beneath (a deck under its porch room). */
  private _tapPick(p: Press): string | undefined {
    const hit = p.hit!;
    if (this._sel.length !== 1 || this._sel[0] !== hit) return undefined;
    const stack = this._stackAt(p.start, p.touch);
    const k = stack.indexOf(hit);
    return k >= 0 && stack.length > 1 ? stack[(k + 1) % stack.length] : undefined;
  }

  /** the trace picture's box on the map */
  private _picBox(t: TracePicture = this._trace!): PicBox {
    return picBox(t, this._traceAspect);
  }

  // ---- pointer input --------------------------------------------------------------

  private _down(e: PointerEvent): void {
    if (e.button === 2) return; // right-click: contextmenu
    if (e.isPrimary) {
      this._pointers.clear();
      this._pinch = undefined;
    }
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
    this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (this._pointers.size === 2) {
      // a second finger: pinch / two-finger pan; whatever the first one started is dropped
      const p = this._press;
      if (p?.base && (p.act === "move" || p.act === "corner" || p.act === "label")) this._draft = p.base;
      if (p?.pic) this._trace = p.pic;
      this._press = undefined;
      this._drawPreview = undefined;
      this._box = undefined;
      const [a, b] = [...this._pointers.values()];
      this._pinch = { dist: Math.hypot(a.x - b.x, a.y - b.y) || 1, mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }, cam: { ...this._cam } };
      return;
    }
    const touch = e.pointerType === "touch";
    const p = this._toMap(e.clientX, e.clientY);
    const press: Press = { id: e.pointerId, x: e.clientX, y: e.clientY, start: p, moved: false, touch, act: "pan", mode: selectMode(e) };
    this._press = press;
    if (e.button === 1) return; // middle button: pan
    const tool = this._tool;
    if (tool === "picture") {
      const t = this._trace;
      if (t && !t.hidden) {
        const s = this._scaleOf();
        const h = picHandleAt(this._picBox(t), p, (touch ? 22 : 12) * s, KNOB_PX * s);
        if (h) {
          press.act = h.kind === "move" ? "pic-move" : h.kind === "turn" ? "pic-turn" : "pic-size";
          press.picHandle = h;
          press.pic = { ...t };
        }
      }
      return;
    }
    if (tool === "select") {
      const h = this._handleAt(p, touch);
      if (h) {
        press.act = h.act;
        press.base = this._draft;
        press.work = cloneMap(this._draft!);
        if (h.insert) {
          const [ref, k] = h.insert;
          const pts = getPts(press.work, ref);
          const a = pts[k];
          const b = pts[(k + 1) % pts.length];
          const mid: Pt = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
          insertCorner(press.work, ref, k, mid);
          press.corners = [[ref, k + 1]];
          press.inserted = true;
        } else press.corners = h.corners;
        press.skip = new Set((press.corners ?? []).map(([r, vi]) => `${r}#${vi}`));
        return;
      }
      const hit = this._itemAt(p, touch);
      // Box select (or Shift / Alt-drag): a drag draws a box even from an
      // item - a tap still selects it
      if (startsBox(e, this._boxMode)) {
        press.act = "box";
        press.hit = hit;
        return;
      }
      if (hit) {
        press.act = "move";
        press.hit = hit;
      }
      return;
    }
    // drawing tools
    press.act = "draw";
    const last = this._chain?.pts[this._chain.pts.length - 1];
    press.from = this._snap(p, touch, last).pt;
    this._hover = this._snap(p, touch, last);
  }

  private _move(e: PointerEvent): void {
    const prev = this._pointers.get(e.pointerId);
    const touch = e.pointerType === "touch";
    if (!prev) {
      // a mouse / pen hovering: show where a drawing tool would put a corner
      if (!touch && !this._press && this._isDrawTool()) {
        const last = this._chain?.pts[this._chain.pts.length - 1];
        this._hover = this._snap(this._toMap(e.clientX, e.clientY), false, last);
      }
      return;
    }
    this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (this._pinch && this._pointers.size === 2) {
      const [a, b] = [...this._pointers.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y) || 1;
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      const z = this._zoomAt(this._pinch.mid.x, this._pinch.mid.y, this._pinch.dist / d, this._pinch.cam);
      const s = this._scaleOf(z);
      this._cam = { ...z, x: z.x - (mid.x - this._pinch.mid.x) * s, y: z.y - (mid.y - this._pinch.mid.y) * s };
      return;
    }
    const p = this._press;
    if (!p || p.id !== e.pointerId) return;
    if (!p.moved && Math.hypot(e.clientX - p.x, e.clientY - p.y) > DRAG_PX) p.moved = true;
    if (!p.moved) return;
    if (p.act === "pan") {
      const s = this._scaleOf();
      this._cam = { ...this._cam, x: this._cam.x - (e.clientX - prev.x) * s, y: this._cam.y - (e.clientY - prev.y) * s };
      return;
    }
    this._dragAt = { x: e.clientX, y: e.clientY };
    this._dragTo(p, e.clientX, e.clientY);
    if (EDGE_ACTS.has(p.act)) this._edgeScroll();
  }

  /** Dragging near the map's edge scrolls it that way (as the Layer Editor
   *  does) - the drag goes on with it: what's moved / drawn / boxed follows. */
  private _edgeScroll(): void {
    if (this._edgeAnim) return;
    const step = () => {
      this._edgeAnim = undefined;
      const p = this._press;
      const at = this._dragAt;
      const svgEl = this.renderRoot.querySelector("svg");
      if (!p || !p.moved || !at || !svgEl || !EDGE_ACTS.has(p.act)) return;
      const [vx, vy] = edgePull(svgEl.getBoundingClientRect(), at.x, at.y);
      if (!vx && !vy) return;
      const s = this._scaleOf();
      this._cam = { ...this._cam, x: this._cam.x + vx * EDGE_SPEED * s, y: this._cam.y + vy * EDGE_SPEED * s };
      this._dragTo(p, at.x, at.y);
      this._edgeAnim = requestAnimationFrame(step);
    };
    this._edgeAnim = requestAnimationFrame(step);
  }

  /** A drag (not a pan) to the pointer at client (x, y). */
  private _dragTo(p: Press, x: number, y: number): void {
    const at = this._toMap(x, y);
    switch (p.act) {
      case "box":
        this._box = { x0: p.start[0], y0: p.start[1], x1: at[0], y1: at[1] };
        return;
      case "draw":
        this._hover = this._snap(at, p.touch, p.from);
        this._drawPreview = { a: p.from!, b: this._hover.pt };
        return;
      case "move": {
        if (!p.base) {
          // the drag starts: what moves - the selection, or just this item
          // (an unselected item moves on its own and isn't selected by it)
          p.base = this._draft!;
          const inSel = this._sel.includes(p.hit!);
          p.ids = inSel ? [...this._sel] : [p.hit!];
          // the grabbed item's nearest corner snaps
          const pts = getPts(p.base, p.hit!);
          p.anchor = pts.reduce((b, q) => (dist(q, p.start) < dist(b, p.start) ? q : b), pts[0]);
          p.skip = new Set(p.ids);
        }
        const raw: Pt = [p.anchor![0] + at[0] - p.start[0], p.anchor![1] + at[1] - p.start[1]];
        const sn = this._snap(raw, p.touch, undefined, p.skip, p.base);
        this._hover = sn.to ? sn : undefined;
        const work = cloneMap(p.base);
        translate(work, p.ids!, sn.pt[0] - p.anchor![0], sn.pt[1] - p.anchor![1]);
        this._draft = work;
        return;
      }
      case "corner": {
        const sn = this._snap(at, p.touch, undefined, p.skip, p.work);
        this._hover = sn.to ? sn : undefined;
        const work = cloneMap(p.work!);
        moveCorners(work, p.corners!, sn.pt);
        this._draft = work;
        return;
      }
      case "label": {
        const work = cloneMap(p.base!);
        work.zones[parseRef(this._sel[0]).i].label = [Math.round(at[0]), Math.round(at[1] - LABEL_HANDLE_DY * this._scaleOf())];
        this._draft = work;
        return;
      }
      case "pic-move": {
        const t = p.pic!;
        this._trace = { ...t, x: t.x + at[0] - p.start[0], y: t.y + at[1] - p.start[1] };
        return;
      }
      case "pic-size": {
        const t = p.pic!;
        const h = p.picHandle as Extract<PicHandle, { kind: "corner" | "side" }>;
        this._trace = { ...t, ...resizePic(this._picBox(t), h, at, 20 * this._scaleOf()) };
        return;
      }
      case "pic-turn":
        this._trace = { ...p.pic!, tilt: tiltFrom(this._picBox(p.pic!), at) };
        return;
    }
  }

  private _up(e: PointerEvent): void {
    this._pointers.delete(e.pointerId);
    if (this._pointers.size < 2) this._pinch = undefined;
    const p = this._press;
    if (!p || p.id !== e.pointerId) return;
    this._press = undefined;
    if (this._edgeAnim) cancelAnimationFrame(this._edgeAnim);
    this._edgeAnim = undefined;
    this._dragAt = undefined;
    const cancel = e.type === "pointercancel";
    switch (p.act) {
      case "pan":
        if (!p.moved && !cancel && this._tool === "select") {
          this._sel = [];
          this._stack = undefined;
          this._afterDrag = false;
        }
        return;
      case "box": {
        const box = this._box;
        this._box = undefined;
        if (cancel) return;
        if (!p.moved || !box) {
          // a tap: on an item selects it (as in Select), on empty map clears
          if (p.hit) this._tapSelect(p);
          else {
            this._sel = [];
            this._stack = undefined;
          }
          return;
        }
        const [x0, x1] = [Math.min(box.x0, box.x1), Math.max(box.x0, box.x1)];
        const [y0, y1] = [Math.min(box.y0, box.y1), Math.max(box.y0, box.y1)];
        const inside = itemsOf(this._draft!)
          .filter((it) => this._shown(it.ref))
          .filter((it) => it.pts.every(([x, y]) => x >= x0 && x <= x1 && y >= y0 && y <= y1))
          .map((it) => it.ref);
        this._sel = applySelect(this._sel, inside, boxSelectMode(e));
        // the row lists what the box selected (a button narrows to one)
        this._stack = this._sel.length ? [...this._sel] : undefined;
        return;
      }
      case "move":
        this._hover = undefined;
        if (cancel) {
          if (p.base) this._draft = p.base;
          return;
        }
        if (p.moved && p.base) {
          if (this._draft !== p.base) this._commit(p.base, this._draft!);
          // the selection was dragged: the next tap starts a new one
          if (p.ids?.every((r) => this._sel.includes(r))) this._afterDrag = true;
        } else if (!p.moved) this._tapSelect(p);
        return;
      case "corner":
      case "label":
        this._hover = undefined;
        if (cancel || !p.moved) {
          this._draft = p.base;
          if (!cancel && p.act === "corner" && !p.inserted) {
            // a tap on a corner / end dot picks it (nudge it; a room's /
            // shape's: Delete corner); again: unpick
            const ref = this._sel[0];
            const vi = p.corners?.find(([r]) => r === ref)?.[1];
            const { kind } = parseRef(ref ?? "x:0");
            if (vi !== undefined && kind !== "link")
              this._corner = this._corner?.ref === ref && this._corner.vi === vi ? undefined : { ref, vi };
          }
          return;
        }
        this._corner = undefined;
        this._commit(p.base!, this._draft!);
        return;
      case "pic-move":
      case "pic-size":
      case "pic-turn":
        if (cancel) this._trace = p.pic;
        else if (p.act === "pic-turn" && !p.moved) this._patchTrace({ tilt: 0 }); // a tap on the knob: straight again
        else this._storeTrace();
        return;
      case "draw": {
        this._drawPreview = undefined;
        if (cancel) return;
        const at = this._toMap(e.clientX, e.clientY);
        const b = p.moved ? this._snap(at, p.touch, p.from).pt : p.from!;
        this._drawAt(p.from!, b, p.moved, p.touch);
        if (p.touch) this._hover = undefined;
        return;
      }
    }
  }

  /** Is this item on screen? Vacuum zones only in their vacuum's view. */
  private _shown(ref: string): boolean {
    const { kind, i } = parseRef(ref);
    if (kind !== "zone") return true;
    const v = this._draft?.zones[i]?.vacuum;
    return !v || v === this._vacuum;
  }

  /** Every vacuum to offer a view for: those HA has a segment-to-area
   *  mapping for (any brand, any number - often none), plus any that already
   *  have vacuum zones (so a mapping removed in HA never hides zones from
   *  editing). */
  private _vacuums(): { id: string; name: string; areas: string[] }[] {
    const out = new Map(Object.entries(this.doc?.vacuums ?? {}).map(([id, v]) => [id, { id, name: v.name, areas: v.areas }]));
    const maps = ((this.doc?.maps as MapData[] | undefined) ?? []).map((m) => (m.id === this._draft?.id ? this._draft! : m));
    for (const m of maps)
      for (const z of m.zones)
        if (z.vacuum && !out.has(z.vacuum))
          out.set(z.vacuum, { id: z.vacuum, name: fullName(this.hass, z.vacuum), areas: [] });
    return [...out.values()];
  }

  private get _vacuumView(): VacuumView | undefined {
    const v = this._vacuum ? this._vacuums().find((x) => x.id === this._vacuum) : undefined;
    return v ? { id: v.id, areas: v.areas } : undefined;
  }

  private _toggleVacuum(): void {
    this._vacuum = this._vacuum ? undefined : this._vacuums()[0]?.id;
    this._sel = this._sel.filter((r) => this._shown(r));
  }

  private _isDrawTool(): boolean {
    return this._tool !== "select" && this._tool !== "picture";
  }

  // ---- drawing -----------------------------------------------------------------

  /** A tap (a) or a drag (a -> b) in a drawing tool. */
  private _drawAt(a: Pt, b: Pt, dragged: boolean, touch: boolean): void {
    const tool = this._tool;
    const same = (p: Pt, q: Pt) => dist(p, q) <= this._tol(touch) * 0.5;
    const chain = this._chain?.kind === tool ? this._chain : undefined;
    if (tool === "link") {
      const to = (this.doc?.maps as MapData[] | undefined)?.find((m) => m.id !== this._draft?.id)?.id;
      if (!to) {
        this._error = tr("editor.need_other_map");
        return;
      }
      this._change((m) => m.links.push({ to, at: a, label: "" }));
      this._sel = [`link:${this._draft!.links.length - 1}`];
      this._tool = "select";
      return;
    }
    if (tool === "wall") {
      if (dragged) {
        if (!same(a, b)) this._addSeg("wall", a, b);
        this._chain = { kind: "wall", pts: [a, b] };
        return;
      }
      if (!chain) {
        this._chain = { kind: "wall", pts: [a] };
        return;
      }
      const last = chain.pts[chain.pts.length - 1];
      if (same(a, last)) {
        this._chain = undefined; // the last corner again: done
        return;
      }
      this._addSeg("wall", last, a);
      this._chain = chain.pts.length > 1 && same(a, chain.pts[0]) ? undefined : { kind: "wall", pts: [...chain.pts, a] };
      return;
    }
    if (tool === "window" || tool === "opening") {
      if (dragged) {
        if (!same(a, b)) this._addGap(tool, a, b);
        this._chain = undefined;
      } else if (!chain) this._chain = { kind: tool, pts: [a] };
      else {
        if (!same(a, chain.pts[0])) this._addGap(tool, chain.pts[0], a);
        this._chain = undefined;
      }
      return;
    }
    // room / shape
    if (!chain) {
      // the next one: the last one's sheet closes
      this._sel = [];
      this._justAdded = undefined;
    }
    if (dragged && !chain) {
      const tol = this._tol(touch);
      if (Math.abs(a[0] - b[0]) > tol && Math.abs(a[1] - b[1]) > tol)
        this._addPoly([a, [b[0], a[1]], b, [a[0], b[1]]]);
      return;
    }
    const p = dragged ? b : a;
    if (!chain) {
      this._chain = { kind: tool, pts: [p] };
      return;
    }
    if (chain.pts.length >= 3 && (same(p, chain.pts[0]) || same(p, chain.pts[chain.pts.length - 1]))) {
      this._finish();
      return;
    }
    if (same(p, chain.pts[chain.pts.length - 1])) return;
    this._chain = { ...chain, pts: [...chain.pts, p] };
  }

  /** Done: close an unfinished room / shape (3+ corners), stop a wall. */
  private _finish(): void {
    const c = this._chain;
    this._chain = undefined;
    if (c && (c.kind === "zone" || c.kind === "shape") && c.pts.length >= 3) this._addPoly(c.pts, c.kind);
  }

  private _addSeg(kind: SegKind, a: Pt, b: Pt): void {
    this._change((m) => m[SEG_KEY[kind]].push([a[0], a[1], b[0], b[1]]));
  }

  private _addGap(kind: "window" | "opening", a: Pt, b: Pt): void {
    const tol = Math.max(this._draft!.wall_width / 2, 3 * this._scaleOf());
    this._change((m) => {
      const g: Seg = [a[0], a[1], b[0], b[1]];
      m.walls = cutWalls(m.walls as Seg[], g, tol);
      m[SEG_KEY[kind]].push(g);
    });
  }

  private _addPoly(pts: Pt[], kind: Tool = this._tool): void {
    let ref = "";
    this._change((m) => {
      if (kind === "zone") {
        ref = addZone(m, pts);
        if (this._vacuum) {
          const z = m.zones[m.zones.length - 1];
          z.vacuum = this._vacuum;
          z.name = numberedName("editor.vacuum_area_n", new Set(m.zones.filter((x) => x !== z).map((x) => x.name)));
        }
      }
      else {
        m.shapes.push({ style: this._shapeStyle, points: pts });
        ref = `shape:${m.shapes.length - 1}`;
      }
    });
    this._sel = [ref];
    // a new room / shape: its sheet opens (name and area / style) - the tool
    // stays (the next one is drawn straight away; that closes the sheet)
    this._justAdded = ref;
  }

  /** The selection sheet: in Select - and in the Room tool for the room just drawn. */
  private get _sheetOpen(): boolean {
    if (!this._sel.length) return false;
    return this._tool === "select" || ((this._tool === "zone" || this._tool === "shape") && this._sel.length === 1 && this._sel[0] === this._justAdded);
  }

  // ---- selection actions ----------------------------------------------------------

  private _deleteSel(): void {
    if (!this._sel.length) return;
    const refs = this._sel;
    const stack = this._stack;
    const at = stack && refs.length === 1 ? stack.indexOf(refs[0]) : -1;
    this._change((m) => deleteRefs(m, refs));
    this._sel = [];
    if (stack) {
      // the "Here:" row stays without it, the next one selected - to keep
      // going through what's stacked there
      const left = refsAfterDelete(stack, refs);
      this._stack = left.length ? left : undefined;
      if (at >= 0 && left.length) this._sel = [left[Math.min(at, left.length - 1)]];
    }
  }

  /** the picked corner, if it still belongs to the (single) selection */
  private _activeCorner(): { ref: string; vi: number } | undefined {
    const c = this._corner;
    const d = this._draft;
    if (!c || !d || this._sel.length !== 1 || this._sel[0] !== c.ref || !exists(d, c.ref)) return undefined;
    return c.vi < getPts(d, c.ref).length ? c : undefined;
  }

  private _deleteCorner(): void {
    const c = this._activeCorner();
    if (!c) return;
    this._change((m) => removeCorner(m, c.ref, c.vi));
    this._corner = undefined;
  }

  /** Nudge: a picked corner / end (and what's joined to it there), else the
   *  selection - by NUDGE map units, whatever the zoom (`big`: ten of them),
   *  on the 0.5-unit grid every point is stored on: a nudged corner lands
   *  exactly on another, never just beside it. `again`: part of a held
   *  arrow - the same undo step as the first. */
  private _nudge(dx: number, dy: number, big: boolean, again = false, times = 1): void {
    if (!this._sel.length || !this._draft) return;
    const step = NUDGE * (big ? 10 : 1) * times;
    const refs = this._sel;
    const c = this._activeCorner();
    const grid = (v: number) => Math.round(v * 2) / 2;
    const apply = (m: MapData) => {
      if (c) {
        const q = getPts(m, c.ref)[c.vi];
        moveCorners(m, this._cornersOf(m, c.ref, c.vi), [grid(q[0] + dx * step), grid(q[1] + dy * step)]);
      } else translate(m, refs, dx * step, dy * step);
    };
    if (!again) {
      this._change(apply);
      return;
    }
    const next = cloneMap(this._draft);
    apply(next);
    this._draft = next;
  }

  /** The sheet's arrows: a tap nudges once; held, it repeats (one undo step). */
  private _nudgeHold(dx: number, dy: number): void {
    this._nudge(dx, dy, false);
    window.clearTimeout(this._nudgeTimer);
    // held: repeats, a step at a time at first, then faster (still whole steps)
    let n = 0;
    const again = () => {
      n++;
      this._nudge(dx, dy, false, true, n < 20 ? 1 : n < 40 ? 2 : 4);
      this._nudgeTimer = window.setTimeout(again, 60);
    };
    this._nudgeTimer = window.setTimeout(again, 400);
  }

  private _nudgeStop(): void {
    window.clearTimeout(this._nudgeTimer);
    this._nudgeTimer = undefined;
  }

  private _nudgeTimer?: number;

  private _renderNudge(): TemplateResult {
    const c = this._activeCorner();
    const arrow = (dx: number, dy: number, icon: string, label: string) =>
      html`<button
        class="icon nudge"
        aria-label=${label}
        title=${label}
        @pointerdown=${(e: PointerEvent) => {
          e.preventDefault();
          this._nudgeHold(dx, dy);
        }}
        @pointerup=${() => this._nudgeStop()}
        @pointerleave=${() => this._nudgeStop()}
        @pointercancel=${() => this._nudgeStop()}
        @contextmenu=${(e: Event) => e.preventDefault()}
      >
        <ha-icon icon=${icon}></ha-icon>
      </button>`;
    return html`<div class="setting nudge-row">
      <span class="label">${c ? tr("editor.nudge_corner") : tr("editor.nudge")}</span>
      <span class="nudges">
        ${arrow(-1, 0, "mdi:arrow-left", tr("editor.left"))}${arrow(0, -1, "mdi:arrow-up", tr("editor.up"))}${arrow(0, 1, "mdi:arrow-down", tr("editor.down"))}${arrow(1, 0, "mdi:arrow-right", tr("editor.right"))}
      </span>
    </div>`;
  }

  // ---- keys -----------------------------------------------------------------------

  private _onKey = (e: KeyboardEvent) => {
    if (this._mapMenu) {
      if (e.key === "Escape") this._mapMenu = false;
      return;
    }
    if (this._dialog) {
      if (e.key === "Escape") {
        if (this._dialog === "settings") this._closeSettings();
        else this._dialog = undefined;
      }
      return;
    }
    if (typingIn(e)) return;
    if (e.key === "Enter" && this._chain) {
      e.preventDefault();
      this._finish();
      return;
    }
    if (e.key === "Escape" && this._chain) {
      // stop drawing: walls so far stay, an unfinished room / shape / gap is dropped
      e.preventDefault();
      this._chain = undefined;
      return;
    }
    if (!e.ctrlKey && !e.metaKey && !e.altKey && e.key.length === 1) {
      if (e.key.toLowerCase() === "b") {
        e.preventDefault();
        this._setBox();
        return;
      }
      const t = TOOLS.find((x) => x.key === e.key.toLowerCase());
      if (t) {
        e.preventDefault();
        this._setTool(t.id);
        return;
      }
    }
    const k = keyIntent(e);
    if (!k) return;
    e.preventDefault();
    switch (k.kind) {
      case "undo":
        return this._undoStep();
      case "redo":
        return this._redoStep();
      case "delete":
        return this._activeCorner() ? this._deleteCorner() : this._deleteSel();
      case "clear":
        this._sel = [];
        return;
      case "select-all":
        this._tool = "select";
        this._sel = itemsOf(this._draft!)
          .map((it) => it.ref)
          .filter((r) => this._shown(r));
        return;
      case "nudge":
        return this._nudge(k.dx, k.dy, k.big);
    }
  };

  private _setTool(t: Tool): void {
    if (this._chain) this._finish();
    this._tool = t;
    this._hover = undefined;
    this._error = "";
    this._boxMode = false;
  }

  /** Box select: Select, dragging draws a selection box. */
  private _setBox(): void {
    this._setTool("select");
    this._boxMode = true;
  }

  // ---- trace picture ---------------------------------------------------------------

  private async _loadTrace(mapId: string): Promise<void> {
    const t = await loadTrace(mapId);
    if (this._draft?.id !== mapId) return;
    this._setTraceUrl(t?.blob);
    if (t) this._traceAspect = await this._aspectOf(t.blob);
    this._trace = t;
  }

  private _setTraceUrl(blob?: Blob): void {
    if (this._traceUrl) URL.revokeObjectURL(this._traceUrl);
    this._traceUrl = blob ? URL.createObjectURL(blob) : undefined;
  }

  private _aspectOf(blob: Blob): Promise<number> {
    return new Promise((resolve) => {
      const img = new Image();
      const url = URL.createObjectURL(blob);
      img.onload = () => {
        resolve(img.naturalWidth ? img.naturalHeight / img.naturalWidth : 1);
        URL.revokeObjectURL(url);
      };
      img.onerror = () => {
        resolve(1);
        URL.revokeObjectURL(url);
      };
      img.src = url;
    });
  }

  private async _openPicture(e: Event): Promise<void> {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = "";
    if (!file) return;
    this._traceAspect = await this._aspectOf(file);
    // fit it into the current view
    const c = this._cam;
    const w = Math.min(c.w * 0.9, (c.h * 0.9) / this._traceAspect);
    const h = w * this._traceAspect;
    this._setTraceUrl(file);
    this._trace = { blob: file, x: c.x + (c.w - w) / 2, y: c.y + (c.h - h) / 2, w, h, rot: 0, tilt: 0, opacity: 1, blend: this._trace?.blend ?? 0.5 };
    this._tool = "picture";
    this._storeTrace();
  }

  private _patchTrace(patch: Partial<TracePicture>): void {
    if (!this._trace) return;
    this._trace = { ...this._trace, ...patch };
    this._storeTrace();
  }

  /** Fine turn: a little at a time (the knob above the picture drags it). */
  private _tiltTrace(by: number): void {
    const now = this._trace?.tilt ?? 0;
    this._patchTrace({ tilt: Math.round((now + by) * 10) / 10 });
  }

  private _rotateTrace(): void {
    if (this._trace) this._patchTrace(turn90(this._trace, this._traceAspect));
  }

  private _storeTrace(): void {
    const id = this._draft?.id;
    if (id && this._trace) void saveTrace(id, this._trace);
  }

  private _removeTrace(): void {
    const id = this._draft?.id;
    this._trace = undefined;
    this._setTraceUrl(undefined);
    if (id) void deleteTrace(id);
  }

  // ---- save / close / maps ------------------------------------------------------------

  private _markerPts(): Pt[] {
    const id = this._draft?.id;
    return ((this.doc?.markers as MapMarker[] | undefined) ?? []).filter((m) => m.map === id).map((m) => [m.x, m.y] as Pt);
  }

  private async _save(): Promise<boolean> {
    const d = this._draft;
    if (!d || !this.hass) return false;
    if (this._chain) this._finish();
    this._busy = true;
    this._error = "";
    try {
      const m = this._draft!;
      await this.hass.callService("room_tiles", "set_map", {
        map: m.id,
        name: m.name,
        ha_floor: m.ha_floor,
        wall_width: m.wall_width,
        bounds: fitBounds(m, this._markerPts()),
        walls: m.walls,
        windows: m.windows,
        openings: m.openings,
        shapes: m.shapes,
        zones: m.zones,
        links: m.links,
        layers: m.layers,
      });
      this._undo = [];
      this._redo = [];
      return true;
    } catch (err) {
      this._error = tr("editor.err_save", { error: String((err as { message?: string })?.message ?? err) });
      return false;
    } finally {
      this._busy = false;
    }
  }

  /** Duplicate map: "<name> copy" - the drawing, layers and markers - last in
   *  the map order (lookups by area keep finding the original first); then
   *  it opens here. Unsaved changes are saved first. */
  private async _duplicateMap(): Promise<void> {
    if (!this.hass || !this._draft) return;
    if (this.dirty && !(await this._save())) return;
    const d = this._draft;
    const maps = (this.doc?.maps as MapData[] | undefined) ?? [];
    const names = new Set(maps.map((x) => x.name));
    let name = tr("editor.copy_name", { name: d.name });
    for (let k = 2; names.has(name); k++) name = tr("editor.copy_name_n", { name: d.name, n: k });
    this._busy = true;
    try {
      const res = await this.hass.connection.sendMessagePromise?.<{ response?: { map?: string } }>({
        type: "call_service",
        domain: "room_tiles",
        service: "add_map",
        service_data: { name },
        return_response: true,
      });
      const id = res?.response?.map;
      if (!id) return;
      await this.hass.callService("room_tiles", "set_map", {
        map: id,
        wall_width: d.wall_width,
        bounds: d.bounds,
        walls: d.walls,
        windows: d.windows,
        openings: d.openings,
        shapes: d.shapes,
        zones: d.zones,
        links: d.links.filter((l) => l.to !== id),
        layers: d.layers,
      });
      const markers = ((this.doc?.markers as MapMarker[] | undefined) ?? [])
        .filter((mk) => mk.map === d.id)
        .map((mk) => ({ entity: mk.entity, x: mk.x, y: mk.y, layer: mk.layer, show_name: mk.show_name }));
      if (markers.length) await this.hass.callService("room_tiles", "set_markers", { map: id, markers });
      this._dialog = undefined;
      this._emit("open-map", { map: id });
    } catch (err) {
      this._error = tr("editor.err_duplicate", { error: String((err as { message?: string })?.message ?? err) });
    } finally {
      this._busy = false;
    }
  }

  private _emit(name: string, detail: Record<string, unknown> = {}): void {
    this.dispatchEvent(new CustomEvent(name, { detail, bubbles: true, composed: true }));
  }

  private _close(): void {
    if (this.dirty) this._dialog = "unsaved";
    else this._emit("close");
  }

  private _leaving?: (ok: boolean) => void;

  /** Leaving for another screen (the settings menu): true once it may go -
   *  saved or discarded, if anything was unsaved - false on Keep editing. */
  leave(): Promise<boolean> {
    if (!this.dirty) return Promise.resolve(true);
    return new Promise((resolve) => {
      this._leaving = (ok) => {
        this._leaving = undefined;
        this._dialog = undefined;
        resolve(ok);
      };
      this._dialog = "unsaved";
    });
  }

  /** Map settings closes (Done, X, backdrop, Esc). Opened from the Layer
   *  Editor's layer settings link: the map editor closes too - back there
   *  (unsaved changes: Save changes / Discard / Keep editing first). */
  private _closeSettings(): void {
    this._dialog = undefined;
    if (this.returnAfterSettings) this._close();
  }

  private async _addMap(): Promise<void> {
    const name = this._newMap.trim();
    if (!name || !this.hass) return;
    if (this.dirty && !(await this._save())) return;
    this._busy = true;
    try {
      const res = await this.hass.connection.sendMessagePromise?.<{ response?: { map?: string } }>({
        type: "call_service",
        domain: "room_tiles",
        service: "add_map",
        service_data: { name, ...(this._newFloor ? { ha_floor: this._newFloor } : {}) },
        return_response: true,
      });
      const id = res?.response?.map;
      this._newMap = "";
      this._newFloor = "";
      this._dialog = undefined;
      if (id) this._emit("open-map", { map: id });
    } catch (err) {
      this._error = tr("editor.err_add", { error: String((err as { message?: string })?.message ?? err) });
    } finally {
      this._busy = false;
    }
  }

  private async _removeMap(): Promise<void> {
    if (!this._confirmDelete) {
      this._confirmDelete = true;
      return;
    }
    if (!this.hass || !this._draft) return;
    try {
      await this.hass.callService("room_tiles", "remove_map", { map: this._draft.id });
      void deleteTrace(this._draft.id);
      this._undo = [];
      this._dialog = undefined;
      this._emit("map-removed");
    } catch (err) {
      this._error = tr("editor.err_delete", { error: String((err as { message?: string })?.message ?? err) });
    }
  }

  private _orderShown = "";

  /** Map settings' map order: the lit map scrolled into view (the row only,
   *  sideways) when the dialog opens or the order changes. */
  protected updated(changed: PropertyValues): void {
    // the map's size watched - after every attach (HA detaches a panel left
    // in a hidden tab, then attaches it again: a new observer)
    const svgEl = this.renderRoot.querySelector("svg");
    if (svgEl && svgEl !== this._roOn) {
      this._roOn = svgEl;
      this._ro?.observe(svgEl);
    }
    if (changed.has("_flashLayers") && this._flashLayers)
      this.renderRoot.querySelector("#marker-layers")?.scrollIntoView({ block: "nearest" });
    const row = this.renderRoot.querySelector<HTMLElement>(".order-row");
    const pill = row?.querySelector<HTMLElement>(".order-pill.on");
    const key = row ? `${this._draft?.id}|${((this.doc?.maps as MapData[] | undefined) ?? []).map((m) => m.id).join()}` : "";
    if (key === this._orderShown) return;
    this._orderShown = key;
    if (!row || !pill) return;
    const left = pill.offsetLeft - row.offsetLeft;
    if (left < row.scrollLeft) row.scrollLeft = left - 8;
    else if (left + pill.offsetWidth > row.scrollLeft + row.clientWidth) row.scrollLeft = left + pill.offsetWidth - row.clientWidth + 8;
  }

  private async _moveMap(by: number): Promise<void> {
    const maps = (this.doc?.maps as MapData[] | undefined) ?? [];
    const order = maps.map((m) => m.id);
    const i = order.indexOf(this._draft!.id);
    const j = i + by;
    if (i < 0 || j < 0 || j >= order.length) return;
    [order[i], order[j]] = [order[j], order[i]];
    await this.hass?.callService("room_tiles", "order_maps", { order });
  }

  // ---- rendering ----------------------------------------------------------------------

  render() {
    const d = this._draft;
    if (!d) return html`<div class="empty">${tr("map.no_map")}</div>`;
    const c = this._cam;
    const s = this._scaleOf();
    return html`
      <div class="top">
        ${this.screenButton ?? nothing}
        <div class="title">
          ${tr("help.title.plan")}
          <!-- like the map's title: pick another map to edit -->
          <button class="of-mode map-pick" title=${tr("editor.edit_other_map")} @click=${() => (this._mapMenu = !this._mapMenu)}>
            · ${d.name}<ha-icon icon="mdi:menu-down"></ha-icon>
          </button>
        </div>
        <button class="pill" title=${tr("editor.map_settings_tip")} @click=${() => (this._dialog = "settings")}>
          <ha-icon icon="mdi:pencil"></ha-icon> ${tr("editor.map_settings")}
        </button>
        <button class="pill" title=${tr("editor.new_map_tip")} @click=${() => (this._dialog = "new-map")}>
          <ha-icon icon="mdi:plus"></ha-icon> ${tr("editor.new_map")}
        </button>
        <button class="layout" title=${tr("help.dialog")} @click=${() => (this._dialog = "help")}><ha-icon icon="mdi:help-circle-outline"></ha-icon></button>
        <button class="layout gear" title=${tr("common.settings")} @click=${() => this._emit("settings-menu")}><ha-icon icon="mdi:cog"></ha-icon>${this.settingsDot ? html`<span class="gear-dot" aria-label=${tr("common.needs_attention")}></span>` : nothing}</button>
        <button class="layout" title=${tr("editor.close")} @click=${() => this._close()}><ha-icon icon="mdi:close"></ha-icon></button>
      </div>
      <div class="bar">
        <div class="tools" role="toolbar" aria-label=${tr("editor.tools")}>
          ${TOOLS.map((t) => {
            const on = this._tool === t.id && !(t.id === "select" && this._boxMode);
            const btn = html`<button
              class="icon ${on ? "on" : ""}"
              title=${tr("editor.tool_tip", { name: tr(`editor.tool_${t.id}`), key: t.key.toUpperCase() })}
              aria-pressed=${on}
              @click=${() => this._setTool(t.id)}
            >
              <ha-icon icon=${t.icon}></ha-icon>
            </button>`;
            // Box select: Select's box mode, as its own button (the Layer Editor's tools)
            return t.id !== "select"
              ? btn
              : html`${btn}<button
                    class="icon ${this._boxMode ? "on" : ""}"
                    title=${tr("editor.box_tip")}
                    aria-pressed=${this._boxMode}
                    @click=${() => this._setBox()}
                  >
                    <ha-icon icon="mdi:selection-drag"></ha-icon>
                  </button>`;
          })}
        </div>
        ${this._vacuums().length
          ? html`<button
              class="icon ${this._vacuum ? "on" : ""}"
              title=${tr("editor.vacuum_tip")}
              aria-pressed=${!!this._vacuum}
              @click=${() => this._toggleVacuum()}
            >
              <ha-icon icon="mdi:robot-vacuum"></ha-icon>
            </button>`
          : nothing}
        <button class="icon ${this._snapOn ? "on" : ""}" title=${tr("editor.snap_tip")} aria-pressed=${this._snapOn} @click=${() => (this._snapOn = !this._snapOn)}>
          <ha-icon icon="mdi:magnet"></ha-icon>
        </button>
        <button class="icon ${this._joinOn ? "on" : ""}" title=${tr("editor.join_tip")} aria-pressed=${this._joinOn} @click=${() => (this._joinOn = !this._joinOn)}>
          <ha-icon icon=${this._joinOn ? "mdi:link-variant" : "mdi:link-variant-off"}></ha-icon>
        </button>
        <button class="icon" title=${tr("editor.undo_tip")} ?disabled=${!this._undo.length && !this._chain} @click=${() => this._undoStep()}><ha-icon icon="mdi:undo"></ha-icon></button>
        <button class="icon" title=${tr("editor.redo_tip")} ?disabled=${!this._redo.length} @click=${() => this._redoStep()}><ha-icon icon="mdi:redo"></ha-icon></button>
        <span class="grow"></span>
        <!-- saves and goes on editing (X / Done leave) -->
        <button class="pill primary" ?disabled=${!this.dirty || this._busy} @click=${() => this._save()}>${tr("common.save_changes")}</button>
      </div>
      ${this._renderContext()}
      ${this._touchNote ? touchNote(() => (this._touchNote = false)) : nothing}
      ${this._error ? html`<div class="error">${this._error}</div>` : nothing}
      <div class="canvas">
        <svg
          class="${this._trace && !this._trace.hidden ? "tracing" : ""} tool-${this._tool}"
          viewBox="${c.x} ${c.y} ${c.w} ${c.h}"
          preserveAspectRatio="xMidYMid meet"
          @wheel=${this._onWheel}
          @pointerdown=${this._down}
          @pointermove=${this._move}
          @pointerup=${this._up}
          @pointercancel=${this._up}
          @pointerleave=${() => !this._press && (this._hover = undefined)}
          @lostpointercapture=${(e: PointerEvent) => this._pointers.delete(e.pointerId)}
          @contextmenu=${(e: Event) => e.preventDefault()}
        >
          ${svg`
            <rect class="ground" x=${c.x - c.w} y=${c.y - c.h} width=${c.w * 3} height=${c.h * 3}></rect>
            ${this._renderTrace(s)}
            <!-- the drawing fades as the Picture slider goes to the picture
                 (what's selected / being drawn stays in full) -->
            <g opacity=${this._trace && !this._trace.hidden ? traceBlend(this._trace.blend).drawing : 1}>
              ${planBase(d, { s, outlineZones: true, ground: false, vacuum: this._vacuumView }, c)}
              ${planLabels(d, s, this._vacuumView)}
              ${this._renderLinks(d, s)}
            </g>
            ${this._renderSelection(d, s)}
            ${this._renderDrawing(s)}
          `}
        </svg>
        <div class="zoomwrap">${this._renderZoom()}</div>
      </div>
      ${this._sheetOpen ? this._renderSheet(d) : nothing}
      ${this._mapMenu ? this._renderMapMenu(d) : nothing}
      ${this._dialog === "settings" ? this._renderSettings(d) : nothing}
      ${this._dialog === "settings" && this._confirmClear ? this._renderClearConfirm(d) : nothing}
      ${this._dialog === "new-map" ? this._renderNewMap() : nothing}
      ${this._dialog === "help" ? html`<rt-map-help mode="plan" @close=${() => (this._dialog = undefined)}></rt-map-help>` : nothing}
      ${this._dialog === "unsaved"
        ? html`<rt-unsaved
            what="map"
            @keep=${() => {
              this._dialog = undefined;
              this._leaving?.(false);
            }}
            @discard=${() => (this._leaving ? this._leaving(true) : this._emit("close"))}
            @save=${async () => {
              this._dialog = undefined;
              if (await this._save()) {
                if (this._leaving) this._leaving(true);
                else this._emit("close");
              }
            }}
          ></rt-unsaved>`
        : nothing}
    `;
  }

  /** The line under the bar: what the tool does, its options, Done. */
  private _renderContext(): TemplateResult {
    const t = this._tool;
    const chain = this._chain;
    const tool = TOOLS.find((x) => x.id === t)!;
    const vacZone = !!this._vacuum && t === "zone";
    return html`<div class="context">
      <span class="tool-name">
        <ha-icon icon=${vacZone ? "mdi:robot-vacuum" : this._boxMode ? "mdi:selection-drag" : tool.icon}></ha-icon>
        ${vacZone ? tr("editor.vacuum_area") : this._boxMode ? tr("editor.box") : tr(`editor.tool_${tool.id}_short`)}
      </span>
      ${t === "shape"
        ? html`<select aria-label=${tr("editor.shape_style")} @change=${(e: Event) => (this._shapeStyle = (e.target as HTMLSelectElement).value as MapShape["style"])}>
            ${NEW_SHAPE_STYLES.map((st) => html`<option value=${st} ?selected=${st === this._shapeStyle}>${styleName(st)}</option>`)}
          </select>`
        : nothing}
      ${t === "picture" ? this._renderPictureControls() : nothing}
      ${t === "select" && this._stack?.length && this._sel.every((r) => this._stack!.includes(r))
        ? html`<span class="stack" role="group" aria-label=${tr("editor.here")}>
            <span class="stack-label">${tr("editor.here_label")}</span>
            <span class="stack-items">
              ${this._stack.length > 1
                ? (() => {
                    // all of them selected again (after narrowing to one)
                    const all = this._stack!.every((r) => this._sel.includes(r));
                    return html`<button class="pill all ${all ? "on" : ""}" aria-pressed=${all} @click=${() => (this._sel = [...this._stack!])}>
                      ${tr("editor.all_n", { n: this._stack!.length })}
                    </button>`;
                  })()
                : nothing}
              ${numbered(this._stack.map((ref) => this._refLabel(ref))).map((label, k) => {
                const ref = this._stack![k];
                const on = this._sel.includes(ref);
                return html`<button class="pill ${on ? "on" : ""}" aria-pressed=${on} @click=${() => (this._sel = [ref])}>${label}</button>`;
              })}
            </span>
          </span>`
        : html`<span class="hint"
            >${t === "picture" && !this._trace
              ? tr("editor.hint_picture")
              : vacZone
                ? tr("editor.hint_vacuum_area")
                : this._boxMode
                  ? tr("editor.hint_box")
                  : hint(t)}</span
          >`}
      ${chain && (chain.kind === "zone" || chain.kind === "shape")
        ? html`<button class="pill" title=${tr("editor.last_corner_tip")} ?disabled=${!chain.pts.length} @click=${() => this._undoStep()}>
            <ha-icon icon="mdi:undo"></ha-icon> ${tr("editor.last_corner")}
          </button>`
        : nothing}
      ${chain && chain.kind !== "wall"
        ? html`<button class="pill" title=${tr("editor.drop_unfinished")} @click=${() => (this._chain = undefined)}>${tr("common.cancel")}</button>`
        : nothing}
      ${chain ? html`<button class="pill primary" title=${tr("editor.finish_tip")} @click=${() => this._finish()}>${tr("common.done")}</button>` : nothing}
    </div>
    ${this._vacuum ? this._renderVacuumLine() : nothing}`;
  }

  /** The title's map picker: every map; another one is edited next (this
   *  one's unsaved changes: Save changes / Discard / Keep editing first). */
  private _renderMapMenu(d: MapData): TemplateResult {
    const maps = (this.doc?.maps as MapData[] | undefined) ?? [];
    const close = () => (this._mapMenu = false);
    return html`<div class="menu-scrim" @click=${close}></div>
      <div class="mapmenu" role="menu" aria-label=${tr("editor.maps")}>
        ${maps.map(
          (m) => html`<button
            class=${m.id === d.id ? "on" : ""}
            aria-pressed=${m.id === d.id}
            @click=${async () => {
              close();
              if (m.id === d.id || !(await this.leave())) return;
              this._emit("open-map", { map: m.id });
            }}
          >
            ${m.name}
          </button>`,
        )}
      </div>`;
  }

  /** A room / shape for the "Here:" buttons: "Room · Back Porch", "Deck". */
  private _refLabel(ref: string): string {
    const d = this._draft;
    const [kind, n] = ref.split(":");
    const i = Number(n);
    if (kind === "zone") {
      const z = d?.zones[i];
      const area = z?.area ? this.doc?.areas.find((a) => a.id === z.area)?.name : undefined;
      return tr("editor.ref_room", { name: z?.name.trim() || area || tr("editor.no_label_lc") });
    }
    if (kind === "shape") return styleName(d?.shapes[i]?.style ?? "grass");
    if (kind === "link") {
      const to = d?.links[i]?.to;
      const name = ((this.doc?.maps as MapData[] | undefined) ?? []).find((m) => m.id === to)?.name;
      return tr("editor.ref_link", { name: d?.links[i]?.label || name || to || "" });
    }
    return kind in KINDS ? kindName(kind as ItemKind) : ref;
  }

  /** The vacuum view's line: which vacuum, and the areas it cleans that
   *  aren't on any map yet (no room or vacuum zone with that area). */
  private _renderVacuumLine(): TemplateResult {
    const vacs = this._vacuums();
    const v = vacs.find((x) => x.id === this._vacuum);
    if (!v) return html``;
    const maps = ((this.doc?.maps as MapData[] | undefined) ?? []).map((m) => (m.id === this._draft?.id ? this._draft! : m));
    const placed = new Set(maps.flatMap((m) => m.zones.filter((z) => !z.vacuum || z.vacuum === this._vacuum).map((z) => z.area)));
    const missing = v.areas.filter((a) => !placed.has(a));
    const name = (a: string) => this.doc?.areas.find((x) => x.id === a)?.name ?? this.hass?.areas?.[a]?.name ?? a;
    return html`<div class="context vac">
      <ha-icon icon="mdi:robot-vacuum"></ha-icon>
      ${(() => {
        const who = vacs.length > 1
        ? html`<select
            aria-label=${tr("robot.title")}
            @change=${(e: Event) => {
              this._vacuum = (e.target as HTMLSelectElement).value;
              this._sel = this._sel.filter((r) => this._shown(r));
            }}
          >
            ${vacs.map((x) => html`<option value=${x.id} ?selected=${x.id === this._vacuum}>${x.name}</option>`)}
          </select>`
        : html`<b>${v.name}</b>`;
        return html`<span class="hint">
          ${v.areas.length ? th("editor.vac_cleans", { name: who }) : th("editor.vac_not_set_up", { name: who })}
          ${v.areas.length && missing.length
            ? th(missing.length === 1 ? "editor.vac_missing_one" : "editor.vac_missing_many", { areas: html`<b>${listOf(missing.map(name))}</b>` })
            : nothing}
        </span>`;
      })()}
    </div>`;
  }

  private _renderPictureControls(): TemplateResult {
    const t = this._trace;
    return html`
      <label class="pill file">
        <ha-icon icon="mdi:folder-image"></ha-icon> ${t ? tr("editor.pic_replace") : tr("editor.pic_open")}
        <input type="file" accept="image/*" @change=${this._openPicture} />
      </label>
      ${t
        ? html`
            <label class="fade" title=${tr("editor.pic_fade_tip")}>
              <ha-icon icon="mdi:image-outline"></ha-icon>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                .value=${String(t.blend ?? 0.5)}
                aria-label=${tr("editor.pic_fade")}
                @input=${(e: Event) => (this._trace = { ...t, blend: Number((e.target as HTMLInputElement).value) })}
                @change=${() => this._storeTrace()}
              />
              <ha-icon icon="mdi:wall"></ha-icon>
            </label>
            <span class="turn" role="group" aria-label=${tr("editor.pic_turn")}>
              <button class="icon" title=${tr("editor.pic_left")} aria-label=${tr("editor.pic_left")} @click=${() => this._tiltTrace(-TILT_STEP)}>
                <ha-icon icon="mdi:rotate-left-variant"></ha-icon>
              </button>
              <button class="tilt-value" title=${tr("editor.pic_level")} aria-label=${tr("editor.pic_level_full")} @click=${() => this._patchTrace({ tilt: 0 })}>
                ${num(t.tilt ?? 0, 1, 1)}°
              </button>
              <button class="icon" title=${tr("editor.pic_right")} aria-label=${tr("editor.pic_right")} @click=${() => this._tiltTrace(TILT_STEP)}>
                <ha-icon icon="mdi:rotate-right-variant"></ha-icon>
              </button>
            </span>
            <button class="icon" title=${tr("editor.pic_90")} @click=${() => this._rotateTrace()}><ha-icon icon="mdi:rotate-right"></ha-icon></button>
            <button class="icon" title=${t.hidden ? tr("editor.pic_show") : tr("editor.pic_hide")} @click=${() => this._patchTrace({ hidden: !t.hidden })}>
              <ha-icon icon=${t.hidden ? "mdi:eye-off" : "mdi:eye"}></ha-icon>
            </button>
            <button class="icon" title=${tr("editor.pic_remove")} @click=${() => this._removeTrace()}><ha-icon icon="mdi:delete"></ha-icon></button>
          `
        : nothing}
    `;
  }

  private _renderTrace(s: number) {
    const t = this._trace;
    if (!t || t.hidden || !this._traceUrl) return nothing;
    const b = this._picBox(t);
    const hw = b.w / 2;
    const hh = b.h / 2;
    // the image's own (unturned) size
    const iw = t.rot % 2 ? b.h : b.w;
    const ih = t.rot % 2 ? b.w : b.h;
    const active = this._tool === "picture";
    const r = HANDLE_PX * s;
    const knobY = -hh - KNOB_PX * s;
    const turning = this._press?.act === "pic-turn" && this._press.moved;
    return svg`
      <g transform="translate(${b.cx} ${b.cy}) rotate(${b.tilt})">
        <g transform="rotate(${t.rot * 90})" opacity=${traceBlend(t.blend).picture} class="trace">
          <image href=${this._traceUrl} x=${-iw / 2} y=${-ih / 2} width=${iw} height=${ih} preserveAspectRatio="none"></image>
        </g>
        ${active
          ? svg`
            <rect class="trace-box" x=${-hw} y=${-hh} width=${b.w} height=${b.h}></rect>
            <line class="knob-arm" x1="0" y1=${-hh} x2="0" y2=${knobY}></line>
            <circle class="handle knob" cx="0" cy=${knobY} r=${r * 1.6}></circle>
            <path
              class="knob-mark"
              transform="translate(0 ${knobY}) scale(${r / 8})"
              d="M -4.5 -2.5 A 5 5 0 1 1 -4.5 2.5 M -4.5 2.5 l -1.6 -2.6 M -4.5 2.5 l 2.9 -0.6"
            ></path>
            ${[-1, 1].flatMap((sx) => [-1, 1].map((sy) => svg`<rect class="handle" x=${sx * hw - r} y=${sy * hh - r} width=${r * 2} height=${r * 2}></rect>`))}
            ${[
              [-hw, 0],
              [hw, 0],
              [0, -hh],
              [0, hh],
            ].map(([x, y]) => svg`<circle class="mid" cx=${x} cy=${y} r=${r * 0.8}></circle>`)}
            ${b.tilt || turning
              ? svg`<text class="tilt" x=${r * 2} y=${knobY} font-size=${13 * s}>${num(b.tilt, 1, 1)}°</text>`
              : nothing}`
          : nothing}
      </g>
    `;
  }

  private _renderLinks(d: MapData, s: number) {
    const names = new Map(((this.doc?.maps as MapData[] | undefined) ?? []).map((m) => [m.id, m.name]));
    return svg`${d.links.map((l) => {
      const text = `↗ ${l.label || names.get(l.to) || l.to}`;
      return svg`<g class="link" transform="translate(${l.at[0]} ${l.at[1]})">
        <circle r=${5 * s}></circle>
        <text y=${-9 * s} font-size=${13 * s}>${text}</text>
      </g>`;
    })}`;
  }

  private _renderSelection(d: MapData, s: number) {
    const sel = this._sel.filter((r) => exists(d, r));
    const one = sel.length === 1 && this._tool === "select" ? sel[0] : undefined;
    return svg`
      ${sel.map((ref) => {
        const { kind } = parseRef(ref);
        const pts = getPts(d, ref);
        if (kind === "link") return svg`<circle class="sel" cx=${pts[0][0]} cy=${pts[0][1]} r=${12 * s}></circle>`;
        if (kind === "zone" || kind === "shape") return svg`<polygon class="sel" points=${poly(pts)}></polygon>`;
        return svg`<line class="sel seg" x1=${pts[0][0]} y1=${pts[0][1]} x2=${pts[1][0]} y2=${pts[1][1]}
          stroke-width=${(kind === "opening" ? 4 * s : d.wall_width) + 6 * s}></line>`;
      })}
      ${anchorOf(sel) && this._tool === "select" ? this._renderAnchor(d, anchorOf(sel)!, s) : nothing}
      ${one ? this._renderHandles(d, one, s) : nothing}
    `;
  }

  /** The first selected - what Align lines the others up with: a dashed box. */
  private _renderAnchor(d: MapData, ref: string, s: number) {
    const b = bbox(getPts(d, ref));
    const pad = (parseRef(ref).kind === "link" ? 16 : 8) * s;
    return svg`<rect class="anchor" x=${b.x0 - pad} y=${b.y0 - pad} width=${b.x1 - b.x0 + 2 * pad}
      height=${b.y1 - b.y0 + 2 * pad} rx=${4 * s}></rect>`;
  }

  private _renderHandles(d: MapData, ref: string, s: number) {
    const { kind, i } = parseRef(ref);
    if (kind === "link") return nothing;
    const pts = getPts(d, ref);
    const r = HANDLE_PX * s;
    const mids =
      kind === "zone" || kind === "shape"
        ? pts.map((a, k) => {
            const b = pts[(k + 1) % pts.length];
            return svg`<circle class="mid" cx=${(a[0] + b[0]) / 2} cy=${(a[1] + b[1]) / 2} r=${r * 0.7}></circle>`;
          })
        : [];
    const label = kind === "zone" && d.zones[i].name.trim() ? labelAt(d.zones[i]) : undefined;
    return svg`
      ${mids}
      ${pts.map((p, vi) => {
        const on = this._activeCorner()?.vi === vi;
        return svg`<circle class="handle ${on ? "active" : ""}" cx=${p[0]} cy=${p[1]} r=${on ? r * 1.35 : r}></circle>`;
      })}
      ${label ? svg`<rect class="label-handle" x=${label[0] - r} y=${label[1] + LABEL_HANDLE_DY * s - r * 0.6} width=${r * 2} height=${r * 1.2} rx=${r * 0.4}></rect>` : nothing}
    `;
  }

  /** what's being drawn: the chain so far, the drag, the snapped cursor */
  private _renderDrawing(s: number) {
    const c = this._chain;
    const h = this._hover;
    const pv = this._drawPreview;
    const tool = this._tool;
    const polyTool = tool === "zone" || tool === "shape";
    const box = this._box;
    let preview: unknown = nothing;
    if (pv && polyTool && !c) {
      preview = svg`<rect class="draft-shape" x=${Math.min(pv.a[0], pv.b[0])} y=${Math.min(pv.a[1], pv.b[1])}
        width=${Math.abs(pv.b[0] - pv.a[0])} height=${Math.abs(pv.b[1] - pv.a[1])}></rect>`;
    } else if (pv) {
      preview = svg`<line class="draft-line" x1=${pv.a[0]} y1=${pv.a[1]} x2=${pv.b[0]} y2=${pv.b[1]} stroke-width=${tool === "wall" ? this._draft!.wall_width : 4 * s}></line>`;
    }
    const last = c?.pts[c.pts.length - 1];
    return svg`
      ${c && (c.kind === "zone" || c.kind === "shape")
        ? svg`<polygon class="draft-shape" points=${poly(h && !pv ? [...c.pts, h.pt] : c.pts)}></polygon>`
        : nothing}
      ${c && last && h && !pv && !polyTool
        ? svg`<line class="draft-line ghost" x1=${last[0]} y1=${last[1]} x2=${h.pt[0]} y2=${h.pt[1]} stroke-width=${tool === "wall" ? this._draft!.wall_width : 4 * s}></line>`
        : nothing}
      ${c?.pts.map((p, k) => svg`<circle class="chain-pt ${k === 0 ? "first" : ""}" cx=${p[0]} cy=${p[1]} r=${(k === 0 ? 6 : 4) * s}></circle>`)}
      ${preview}
      ${h && (this._isDrawTool() || h.to)
        ? svg`<circle class="snap ${h.to ?? "free"}" cx=${h.pt[0]} cy=${h.pt[1]} r=${(h.to === "point" ? 8 : 5) * s}></circle>`
        : nothing}
      ${box
        ? svg`<rect class="selbox" x=${Math.min(box.x0, box.x1)} y=${Math.min(box.y0, box.y1)} width=${Math.abs(box.x1 - box.x0)} height=${Math.abs(box.y1 - box.y0)}></rect>`
        : nothing}
    `;
  }

  // ---- the selection sheet ------------------------------------------------------------

  /** Group actions on the selection (rooms, shapes, walls, links - by their
   *  outline box): align to the FIRST selected, space evenly. One undo step;
   *  the selection stays. */
  private _arrangeRow(sel: string[]): TemplateResult {
    const run = (op: ArrangeOp) =>
      this._change((m) => {
        const moves = arrange(sel.map((r) => bbox(getPts(m, r))), op);
        sel.forEach((r, k) => (moves[k].dx || moves[k].dy) && translate(m, [r], moves[k].dx, moves[k].dy));
      });
    return html`<div class="arrange" role="group" aria-label=${tr("editor.arrange")}>
      ${ARRANGE_OPS.filter((a) => sel.length >= a.min).map(
        (a) => html`<button class="pill" title=${a.title} @click=${() => run(a.op)}>
          <ha-icon icon=${a.icon}></ha-icon> ${a.label}
        </button>`,
      )}
      <div class="arrange-note">${tr("editor.arrange_note")}</div>
    </div>`;
  }

  private _renderSheet(d: MapData): TemplateResult {
    const sel = this._sel.filter((r) => exists(d, r));
    if (!sel.length) return html``;
    const kinds = new Set(sel.map((r) => parseRef(r).kind));
    const only = kinds.size === 1 ? [...kinds][0] : undefined;
    const segsOnly = [...kinds].every((k) => (SEG_KINDS as string[]).includes(k));
    const one = sel.length === 1 ? parseRef(sel[0]) : undefined;
    const title = one
      ? one.kind === "zone"
        ? d.zones[one.i].name
        : one.kind === "shape"
          ? tr("editor.style_shape", { style: styleName(d.shapes[one.i].style) })
          : kindName(one.kind)
      : only
        ? kindCount(only, sel.length)
        : tn("editor.count_items", sel.length);
    return html`
      <div class="sheet" role="dialog" aria-label=${tr("editor.selection")} style=${this._sheetDrag.style}>
        <div class="sheet-head" @pointerdown=${this._sheetDrag.down} @dblclick=${this._sheetDrag.reset}>
          <ha-icon class="grip" icon="mdi:drag"></ha-icon>
          <div class="sheet-title">${title}</div>
        </div>
        ${sel.length > 1 ? this._arrangeRow(sel) : nothing}
        ${one?.kind === "zone" ? this._zoneFields(d, one.i) : nothing}
        ${one?.kind === "shape"
          ? html`<div class="setting">
              <span class="label">${tr("editor.style")}</span>
              <select @change=${(e: Event) => this._change((m) => (m.shapes[one.i].style = (e.target as HTMLSelectElement).value as MapShape["style"]))}>
                ${(d.shapes[one.i].style === "floor" ? SHAPE_STYLES : NEW_SHAPE_STYLES).map(
                  (st) => html`<option value=${st} ?selected=${st === d.shapes[one.i].style}>${styleName(st)}</option>`,
                )}
              </select>
            </div>`
          : nothing}
        ${one?.kind === "link" ? this._linkFields(d, one.i) : nothing}
        ${one && (one.kind === "zone" || one.kind === "shape")
          ? (() => {
              const c = this._activeCorner();
              const n = getPts(d, sel[0]).length;
              return c
                ? html`<div class="setting">
                    <span class="label">${tr("editor.corner_of", { i: c.vi + 1, n })}</span>
                    <button class="pill" ?disabled=${n <= 3} title=${n <= 3 ? tr("editor.corner_min") : tr("editor.corner_delete_tip")} @click=${() => this._deleteCorner()}>
                      <ha-icon icon="mdi:vector-point-minus"></ha-icon> ${tr("editor.corner_delete")}
                    </button>
                  </div>`
                : html`<div class="hint">${tr("editor.corner_hint")}</div>`;
            })()
          : nothing}
        ${one && one.kind !== "zone" && one.kind !== "shape" && one.kind !== "link"
          ? this._activeCorner()
            ? html`<div class="setting"><span class="label">${tr("editor.end_of", { i: this._activeCorner()!.vi + 1 })}</span></div>`
            : html`<div class="hint">${tr("editor.end_hint")}</div>`
          : nothing}
        ${this._renderNudge()}
        ${segsOnly
          ? html`<div class="setting">
              <span class="label">${tr("editor.type")}</span>
              <select
                @change=${(e: Event) => {
                  const to = (e.target as HTMLSelectElement).value as SegKind;
                  let refs: string[] = [];
                  this._change((m) => (refs = convertSegs(m, sel, to)));
                  this._sel = refs;
                }}
              >
                ${only ? nothing : html`<option value="" selected disabled>${tr("editor.mixed")}</option>`}
                ${SEG_KINDS.map((k) => html`<option value=${k} ?selected=${k === only}>${kindName(k)}</option>`)}
              </select>
            </div>`
          : nothing}
        <div class="sheet-foot">
          <button class="danger" @click=${() => this._deleteSel()}>
            <ha-icon icon="mdi:delete"></ha-icon> ${sel.length > 1 ? tr("editor.delete_n", { n: sel.length }) : tr("editor.delete")}
          </button>
          <button class="pill primary" title=${tr("editor.done_selection")} @click=${() => (this._sel = [])}>${tr("common.done")}</button>
        </div>
      </div>
    `;
  }

  private _zoneFields(d: MapData, i: number): TemplateResult {
    const z = d.zones[i];
    const areas = this.doc?.areas ?? [];
    const maps = ((this.doc?.maps as MapData[] | undefined) ?? []).map((m) => (m.id === d.id ? d : m));
    const vac = this._vacuums().find((x) => x.id === (z.vacuum ?? this._vacuum));
    const vacName = vac?.name ?? z.vacuum ?? "";
    const cleans = (a: string) => !!vac?.areas.includes(a);
    // where else this area already has a room (a room) / a zone of the same vacuum
    const elsewhere = (areaId: string) => {
      for (const m of maps) {
        const zones = m.zones.filter((zz, k) => !(m === d && k === i) && (zz.vacuum ?? null) === (z.vacuum ?? null));
        if (zones.some((zz) => zz.area === areaId)) return m.name;
      }
      return undefined;
    };
    const setArea = (areaId: string) =>
      this._change((m) => {
        const zz = m.zones[i];
        const oldName = areas.find((a) => a.id === zz.area)?.name;
        const area = areas.find((a) => a.id === areaId);
        zz.area = area ? area.id : null;
        // the name follows the area unless it was renamed by hand
        if (area && (!zz.name || /^(Room|Zone) \d+$/.test(zz.name) || zz.name === oldName)) zz.name = area.name;
      });
    const option = (a: { id: string; name: string }) => {
      const other = elsewhere(a.id);
      return html`<option value=${a.id} ?selected=${a.id === z.area}>${a.name}${other ? ` (also on ${other})` : ""}</option>`;
    };
    // a vacuum zone lists the areas the vacuum cleans first
    const first = z.vacuum ? areas.filter((a) => cleans(a.id)) : [];
    const rest = areas.filter((a) => !first.includes(a));
    return html`
      ${z.vacuum
        ? html`<div class="hint">
            <ha-icon class="inline" icon="mdi:robot-vacuum"></ha-icon> ${tr("editor.vac_area_only", { name: vacName })}
            ${z.area && !cleans(z.area) ? html`<span class="warn">${tr("editor.vac_cant_clean", { name: vacName })}</span>` : nothing}
          </div>`
        : vac && this._vacuum
          ? html`<div class="hint">
              <ha-icon class="inline" icon="mdi:robot-vacuum"></ha-icon>
              ${z.area && cleans(z.area) ? tr("editor.vac_cleans_room", { name: vacName }) : tr("editor.vac_not_room", { name: vacName })}
            </div>`
          : nothing}
      <div class="setting">
        <span class="label">${tr("editor.ha_area")}</span>
        <select @change=${(e: Event) => setArea((e.target as HTMLSelectElement).value)}>
          <option value="" ?selected=${!z.area}>${tr("common.none")}</option>
          ${first.length
            ? html`<optgroup label=${tr("editor.cleaned_by", { name: vacName })}>${first.map(option)}</optgroup>
                <optgroup label=${tr("editor.other_areas")}>${rest.map(option)}</optgroup>`
            : rest.map(option)}
        </select>
      </div>
      <div class="setting">
        <span class="label">${tr("common.name")}</span>
        <input
          type="text"
          .value=${z.name}
          placeholder=${tr("editor.no_label")}
          @change=${(e: Event) => {
            // empty: no label (a closet that's just floor)
            const v = (e.target as HTMLInputElement).value.trim();
            if (v !== z.name) this._change((m) => (m.zones[i].name = v));
          }}
        />
      </div>
      <div class="setting">
        <span class="label">${tr("editor.name_reads")}</span>
        <div class="segmented">
          ${([false, true] as const).map(
            (v) => html`<button
              class=${!!z.label_vertical === v ? "on" : ""}
              aria-pressed=${!!z.label_vertical === v}
              @click=${() => !!z.label_vertical !== v && this._change((m) => (m.zones[i].label_vertical = v))}
            >
              ${v ? tr("editor.vertical") : tr("editor.horizontal")}
            </button>`,
          )}
        </div>
      </div>
      ${z.vacuum
        ? nothing
        : html`<div class="setting" title=${tr("editor.outside_tip")}>
            <span class="label">${tr("editor.outside")}</span>
            ${toggle(z.outdoor, (on) => this._change((m) => (m.zones[i].outdoor = on)), tr("editor.outside"), this.theme)}
          </div>`}
    `;
  }

  private _linkFields(d: MapData, i: number): TemplateResult {
    const l = d.links[i];
    const maps = ((this.doc?.maps as MapData[] | undefined) ?? []).filter((m) => m.id !== d.id);
    return html`
      <div class="setting">
        <span class="label">${tr("editor.opens")}</span>
        <select @change=${(e: Event) => this._change((m) => (m.links[i].to = (e.target as HTMLSelectElement).value))}>
          ${maps.map((m) => html`<option value=${m.id} ?selected=${m.id === l.to}>${m.name}</option>`)}
        </select>
      </div>
      <div class="setting">
        <span class="label">${tr("editor.label")}</span>
        <input
          type="text"
          placeholder=${tr("editor.label_placeholder")}
          .value=${l.label}
          @change=${(e: Event) => this._change((m) => (m.links[i].label = (e.target as HTMLInputElement).value.trim()))}
        />
      </div>
    `;
  }

  // ---- new map dialog -------------------------------------------------------------------

  private _floors(): { floor_id: string; name: string }[] {
    return Object.values((this.hass as unknown as { floors?: Record<string, { floor_id: string; name: string }> })?.floors ?? {});
  }

  private _renderNewMap(): TemplateResult {
    const name = this._newMap.trim();
    const taken = ((this.doc?.maps as MapData[] | undefined) ?? []).map((m) => m.ha_floor);
    const full = taken.length >= MAX_MAPS;
    return html`
      <div class="scrim" @click=${() => (this._dialog = undefined)}></div>
      <div class="dialog" role="dialog" aria-label=${tr("editor.new_map")} style="--dialog-w:420px">
        <div class="head">
          <div class="title">${tr("editor.new_map")}</div>
          <button class="x" aria-label=${tr("common.close")} @click=${() => (this._dialog = undefined)}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        <div class="intro">${tr("editor.new_map_intro")}</div>
        <div class="group">
        <div class="group-head"><ha-icon icon="mdi:map-plus"></ha-icon>${tr("editor.the_new_map")}</div>
        <div class="setting">
          <span class="label">${tr("common.name")}</span>
          <input
            type="text"
            placeholder=${tr("editor.new_map_placeholder")}
            .value=${this._newMap}
            @input=${(e: Event) => (this._newMap = (e.target as HTMLInputElement).value)}
            @keydown=${(e: KeyboardEvent) => e.key === "Enter" && name && this._addMap()}
          />
        </div>
        <div class="setting">
          <span class="label">${tr("editor.ha_floor")}</span>
          <select @change=${(e: Event) => (this._newFloor = (e.target as HTMLSelectElement).value)}>
            <option value="" ?selected=${!this._newFloor}>${tr("common.none")}</option>
            ${this._floors().map(
              (f) => html`<option value=${f.floor_id} ?selected=${f.floor_id === this._newFloor}>${taken.includes(f.floor_id) ? tr("editor.floor_has_map", { name: f.name }) : f.name}</option>`,
            )}
          </select>
        </div>
        </div>
        ${full ? html`<div class="hint warn">${tr("editor.maps_full", { n: MAX_MAPS })}</div>` : nothing}
        ${this.dirty && !full ? html`<div class="hint">${tr("editor.saved_first", { name: this._draft?.name ?? "" })}</div>` : nothing}
        <div class="footer">
          <button @click=${() => (this._dialog = undefined)}>${tr("common.cancel")}</button>
          <button class="primary" ?disabled=${!name || this._busy || full} @click=${() => this._addMap()}>
            ${this.dirty ? tr("editor.save_create") : tr("editor.create")}
          </button>
        </div>
      </div>
    `;
  }

  /** Clear map: everything drawn goes - walls, windows, doorways, rooms,
   *  shapes, links; the name, floor, layers, markers (and a traced picture)
   *  stay. One undo step, nothing saved until Save changes. */
  private _clearMap(): void {
    this._change((m) => {
      m.walls = [];
      m.windows = [];
      m.openings = [];
      m.zones = [];
      m.shapes = [];
      m.links = [];
    });
    this._sel = [];
    this._chain = undefined;
    this._confirmClear = false;
  }

  private _renderClearConfirm(d: MapData): TemplateResult {
    return html`
      <div class="scrim" style="--z:40" @click=${() => (this._confirmClear = false)}></div>
      <div class="dialog" style="--z:40;--dialog-w:400px" role="alertdialog" aria-label=${tr("editor.clear_map")}>
        <div class="head"><div class="title">${tr("editor.clear_title", { name: d.name })}</div></div>
        <div class="intro">${tr("editor.clear_intro")}</div>
        <div class="footer">
          <button @click=${() => (this._confirmClear = false)}>${tr("common.cancel")}</button>
          <button class="primary" @click=${() => this._clearMap()}>${tr("editor.clear_map")}</button>
        </div>
      </div>
    `;
  }

  // ---- map settings dialog ------------------------------------------------------------

  private _renderSettings(d: MapData): TemplateResult {
    const floors = this._floors();
    const maps = (this.doc?.maps as MapData[] | undefined) ?? [];
    const pos = maps.findIndex((m) => m.id === d.id);
    const layers = [...d.layers].sort((a, b) => a.min_zoom - b.min_zoom);
    const setLayer = (id: string, patch: Partial<{ name: string; min_zoom: number }>) =>
      this._change((m) => {
        m.layers = m.layers.map((l) => (l.id === id ? { ...l, ...patch } : l)).sort((a, b) => a.min_zoom - b.min_zoom);
      });
    const markerCount = this._markerPts().length;
    return html`
      <div class="scrim" @click=${() => this._closeSettings()}></div>
      <div class="dialog" role="dialog" aria-label=${tr("editor.map_settings")}>
        <div class="head">
          <div class="title">${tr("editor.map_settings")}</div>
          <button class="x" aria-label=${tr("common.close")} @click=${() => this._closeSettings()}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        <div class="list">
          <div class="group">
          <div class="group-head"><ha-icon icon="mdi:map-outline"></ha-icon>${tr("editor.this_map")}</div>
          <div class="setting">
            <span class="label">${tr("common.name")}</span>
            <input
              type="text"
              .value=${d.name}
              @change=${(e: Event) => {
                const v = (e.target as HTMLInputElement).value.trim();
                if (v && v !== d.name) this._change((m) => (m.name = v));
              }}
            />
          </div>
          <div class="setting">
            <span class="label">${tr("editor.ha_floor")}</span>
            <select @change=${(e: Event) => this._change((m) => (m.ha_floor = (e.target as HTMLSelectElement).value || null))}>
              <option value="" ?selected=${!d.ha_floor}>${tr("common.none")}</option>
              ${floors.map((f) => html`<option value=${f.floor_id} ?selected=${f.floor_id === d.ha_floor}>${f.name}</option>`)}
            </select>
          </div>
          <div class="setting">
            <span class="label">${tr("editor.wall_thickness")}</span>
            <input
              type="number"
              min="1"
              max="60"
              step="0.5"
              class="num"
              .value=${String(d.wall_width)}
              @change=${(e: Event) => {
                const v = Number((e.target as HTMLInputElement).value);
                if (v > 0 && v !== d.wall_width) this._change((m) => (m.wall_width = v));
              }}
            />
          </div>
          </div>

          <div class="group ${this._flashLayers ? "flash" : ""}" id="marker-layers">
          <div class="group-head"><ha-icon icon="mdi:layers-outline"></ha-icon>${tr("editor.marker_layers")}</div>
          <div class="hint">${tr("editor.layers_hint")}</div>
          ${layers.map(
            (l, k) => html`<div class="setting layer">
              <input
                type="text"
                aria-label=${tr("editor.layer_name")}
                .value=${l.name}
                @change=${(e: Event) => {
                  const v = (e.target as HTMLInputElement).value.trim();
                  if (v && v !== l.name) setLayer(l.id, { name: v });
                }}
              />
              <!-- its zoom range is set in the Layer Editor (Starts at / Ends at) -->
              <span class="from" title=${tr("editor.layer_range_tip")}
                >${l.max_zoom == null ? tr("editor.layer_from", { zoom: zoomLabel(l.min_zoom) }) : `${zoomLabel(l.min_zoom)} - ${zoomLabel(l.max_zoom)}`}</span
              >
              <button
                class="icon"
                title=${tr("editor.layer_delete_tip")}
                ?disabled=${layers.length < 2}
                @click=${() => this._change((m) => (m.layers = m.layers.filter((x) => x.id !== l.id)))}
              >
                <ha-icon icon="mdi:delete"></ha-icon>
              </button>
            </div>`,
          )}
          ${d.layers.length < MAX_LAYERS
            ? html`<button class="link" @click=${() => this._change((m) => addLayer(m))}>${tr("map.add_layer")}</button>`
            : html`<div class="hint">${tr("editor.layers_full", { n: MAX_LAYERS })}</div>`}
          </div>

          <div class="group">
          <div class="group-head"><ha-icon icon="mdi:sort"></ha-icon>${tr("editor.map_order")}</div>
          <!-- the maps in their order, this one lit; the arrows move it among them -->
          <div class="setting map-order">
            <button class="icon" title=${tr("common.earlier")} ?disabled=${pos <= 0} @click=${() => this._moveMap(-1)}><ha-icon icon="mdi:chevron-left"></ha-icon></button>
            <div class="order-row" aria-label=${tr("editor.map_order")}>
              ${maps.map(
                (m) => html`<span class="order-pill ${m.id === d.id ? "on" : ""}" aria-current=${m.id === d.id ? "true" : "false"}>${m.name}</span>`,
              )}
            </div>
            <button class="icon" title=${tr("common.later")} ?disabled=${pos < 0 || pos >= maps.length - 1} @click=${() => this._moveMap(1)}><ha-icon icon="mdi:chevron-right"></ha-icon></button>
          </div>
          </div>

          <!-- on their own: start over / delete this map -->
          <div class="map-danger">
          <button
            class="plain"
            title=${tr("editor.duplicate_tip")}
            ?disabled=${maps.length >= MAX_MAPS || this._busy}
            @click=${() => this._duplicateMap()}
          >
            <ha-icon icon="mdi:content-copy"></ha-icon> ${maps.length >= MAX_MAPS ? tr("editor.maps_max", { n: MAX_MAPS }) : tr("editor.duplicate")}
          </button>
          <button class="danger" @click=${() => (this._confirmClear = true)}>
            <ha-icon icon="mdi:eraser"></ha-icon> ${tr("editor.clear_map")}
          </button>
          <button class="danger" ?disabled=${maps.length < 2} @click=${() => this._removeMap()}>
            <ha-icon icon="mdi:delete"></ha-icon>
            ${this._confirmDelete
              ? markerCount
                ? tr("editor.delete_again_markers", { name: d.name, layers: tn("editor.n_layers", d.layers.length), markers: tn("editor.n_markers", markerCount) })
                : tr("editor.delete_again", { name: d.name, layers: tn("editor.n_layers", d.layers.length) })
              : maps.length < 2
                ? tr("editor.only_map")
                : tr("editor.delete_map")}
          </button>
          </div>
        </div>
        <div class="footer">
          <button class="primary" @click=${() => this._closeSettings()}>${tr("common.done")}</button>
        </div>
      </div>
    `;
  }

  static styles = [noSelectStyles, groupStyles, zoomStyles, touchNoteStyles, 
    dialogStyles,
    rowStyles,
    planStyles,
    css`
      :host {
        position: absolute;
        inset: 0;
        z-index: 6;
        display: flex;
        flex-direction: column;
        background: var(--rt-page);
        color: var(--rt-text);
      }
      .empty {
        padding: 32px;
        text-align: center;
      }
      .top,
      .bar,
      .context {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 6px 12px 0;
        flex-wrap: wrap;
        flex: none;
      }
      /* the editor's name: title text, not a button - then the map's, lighter */
      /* the top bar's buttons (the first - HA menu / full screen - comes
         from the panel; Help, Close): the panel's button look, as on the map */
      /* followed an "Add layer" link: where to find it */
      .group.flash {
        border: 2px solid var(--rt-accent);
      }
      .top .layout.gear {
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
      .top .layout {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        flex: none;
        min-width: 40px;
        height: 36px;
        padding: 0 6px;
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        border-radius: 8px;
        color: var(--rt-text);
        cursor: pointer;
      }
      .top .title .of-mode {
        font-weight: 400;
        color: var(--rt-text-secondary);
      }
      .map-danger .plain {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        padding: 10px 14px;
        border-radius: 10px;
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        color: var(--rt-text);
      }
      .map-danger {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .map-order {
        gap: 6px;
      }
      .order-row {
        /* one line: many maps scroll sideways; this one kept in view */
        flex: 1 1 0;
        min-width: 0;
        display: flex;
        gap: 6px;
        overflow-x: auto;
        overscroll-behavior-x: contain; /* a swipe past its end: not the browser's swipe-back */
        scrollbar-width: thin;
        padding-bottom: 2px;
      }
      .order-pill {
        flex: none;
        white-space: nowrap;
        padding: 5px 12px;
        border-radius: 999px;
        background: var(--rt-button);
        color: var(--rt-text-secondary);
        border: 1px solid var(--rt-tile-border);
        font-size: 0.9rem;
      }
      .order-pill.on {
        background: var(--rt-accent);
        border-color: var(--rt-accent);
        color: var(--rt-on-accent);
      }
      .map-pick {
        border: none;
        background: none;
        padding: 0;
        font: inherit;
        font-weight: 400;
        color: var(--rt-text-secondary);
        cursor: pointer;
        --mdc-icon-size: 22px;
      }
      .menu-scrim {
        /* a tap beside the map picker closes it (not dimmed: it's a menu) */
        position: fixed;
        inset: 0;
        z-index: 8;
      }
      .mapmenu {
        position: absolute;
        top: 56px;
        left: 16px;
        z-index: 9;
        display: flex;
        flex-direction: column;
        gap: 4px;
        padding: 8px;
        min-width: 180px;
        max-height: calc(100% - 72px);
        overflow-y: auto;
        border-radius: 12px;
        background: var(--rt-dialog);
        border: 1px solid var(--rt-tile-border);
      }
      .mapmenu button {
        text-align: left;
        padding: 10px 12px;
        border-radius: 8px;
        border: 1px solid transparent;
        background: var(--rt-button);
        color: var(--rt-text);
      }
      .mapmenu button.on {
        border-color: var(--rt-accent);
      }
      .top .title {
        flex: 1;
        font-weight: 700;
        font-size: 1.1rem;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .tools {
        display: flex;
        gap: 2px;
        padding: 2px;
        border-radius: 12px;
        background: var(--rt-button);
        flex-wrap: wrap;
      }
      .grow {
        flex: 1;
      }
      button.icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 38px;
        height: 38px;
        border-radius: 10px;
        border: none;
        background: none;
        --mdc-icon-size: 22px;
      }
      .bar > button.icon {
        background: var(--rt-button);
      }
      button.icon.on {
        background: var(--rt-accent);
        color: var(--rt-on-accent);
      }
      .pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        border-radius: 10px;
        padding: 8px 12px;
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        --mdc-icon-size: 18px;
        cursor: pointer;
      }
      .pill.primary {
        background: var(--rt-accent);
        color: var(--rt-on-accent);
        border-color: var(--rt-accent);
      }
      .file input {
        display: none;
      }
      .fade {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        --mdc-icon-size: 20px;
      }
      .fade input {
        width: 110px;
        accent-color: var(--rt-accent);
      }
      .context {
        min-height: 40px;
        padding-bottom: 4px;
      }
      .stack {
        /* one line: many items scroll sideways, the label stays */
        display: flex;
        align-items: center;
        gap: 6px;
        flex: 1 1 0;
        min-width: 0;
      }
      .stack-items {
        display: flex;
        gap: 6px;
        overflow-x: auto;
        overscroll-behavior-x: contain; /* a swipe past its end: not the browser's swipe-back */
        min-width: 0;
        padding-bottom: 2px;
        scrollbar-width: thin;
      }
      .stack-items .pill {
        flex: none;
        white-space: nowrap;
      }
      .stack-label {
        color: var(--rt-text-secondary);
        font-size: 0.9rem;
      }
      .stack .pill.on {
        border-color: var(--rt-accent);
        color: var(--rt-accent);
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
        color: var(--rt-accent);
      }
      .error {
        margin: 4px 12px 0;
        color: var(--rt-light);
        font-size: 0.88rem;
      }
      .canvas {
        flex: 1;
        min-height: 0;
        position: relative;
        margin-top: 6px;
        background: var(--rt-map-bg);
        touch-action: none;
        user-select: none;
        overflow: hidden;
      }
      svg {
        display: block;
        width: 100%;
        height: 100%;
        cursor: grab;
      }
      svg.tool-wall,
      svg.tool-window,
      svg.tool-opening,
      svg.tool-zone,
      svg.tool-shape,
      svg.tool-link {
        cursor: crosshair;
      }
      svg.tool-picture {
        cursor: move;
      }
      svg.tracing .shape {
        fill-opacity: 0.35;
      }
      .zone.outlined {
        stroke-dasharray: 6 4;
      }
      .link circle {
        fill: var(--rt-accent);
      }
      .link text {
        fill: var(--rt-text);
        text-anchor: middle;
        paint-order: stroke;
        stroke: var(--rt-map-bg);
        stroke-width: 3px;
        font-family: Roboto, sans-serif;
        pointer-events: none;
      }
      .sel {
        fill: var(--rt-accent);
        fill-opacity: 0.18;
        stroke: var(--rt-accent);
        stroke-width: 2px;
        vector-effect: non-scaling-stroke;
        pointer-events: none;
      }
      .anchor {
        fill: none;
        stroke: var(--rt-accent);
        stroke-width: 2.5px;
        stroke-dasharray: 6 4;
        vector-effect: non-scaling-stroke;
        pointer-events: none;
      }
      .sel.seg {
        fill: none;
        stroke-opacity: 0.45;
        vector-effect: none;
        stroke-linecap: round;
      }
      .handle,
      .label-handle {
        fill: var(--rt-dialog);
        stroke: var(--rt-accent);
        stroke-width: 2px;
        vector-effect: non-scaling-stroke;
      }
      .mid {
        fill: var(--rt-accent);
        opacity: 0.6;
      }
      .handle.active {
        fill: var(--rt-accent);
        stroke: var(--rt-text);
      }
      .draft-line {
        stroke: var(--rt-accent);
        stroke-opacity: 0.7;
        stroke-linecap: round;
        pointer-events: none;
      }
      .draft-line.ghost {
        stroke-opacity: 0.35;
      }
      .draft-shape {
        fill: var(--rt-accent);
        fill-opacity: 0.15;
        stroke: var(--rt-accent);
        stroke-width: 2px;
        stroke-dasharray: 5 4;
        vector-effect: non-scaling-stroke;
        pointer-events: none;
      }
      .chain-pt {
        fill: var(--rt-accent);
        pointer-events: none;
      }
      .chain-pt.first {
        fill: var(--rt-dialog);
        stroke: var(--rt-accent);
        stroke-width: 2px;
        vector-effect: non-scaling-stroke;
      }
      .snap {
        fill: none;
        stroke: var(--rt-text);
        stroke-width: 1.5px;
        vector-effect: non-scaling-stroke;
        pointer-events: none;
      }
      .snap.point {
        stroke: var(--rt-light);
        stroke-width: 2.5px;
      }
      .snap.line,
      .snap.angle,
      .snap.align {
        stroke: var(--rt-accent);
      }
      .trace {
        pointer-events: none;
      }
      .knob-mark {
        /* a turn arrow on the knob: it turns the picture (not a resize dot) */
        fill: none;
        stroke: var(--rt-accent);
        stroke-width: 1.6px;
        vector-effect: non-scaling-stroke;
        pointer-events: none;
      }
      .turn {
        display: inline-flex;
        align-items: center;
        gap: 2px;
      }
      .tilt-value {
        min-width: 3.4em;
        padding: 6px 4px;
        border: none;
        background: none;
        color: var(--rt-text);
        font-variant-numeric: tabular-nums;
      }
      .knob-arm {
        stroke: var(--rt-accent);
        stroke-width: 1.5px;
        vector-effect: non-scaling-stroke;
      }
      .tilt {
        fill: var(--rt-text);
        dominant-baseline: middle;
        paint-order: stroke;
        stroke: var(--rt-map-bg);
        stroke-width: 3px;
        font-family: Roboto, sans-serif;
        pointer-events: none;
      }
      .trace-box {
        fill: none;
        stroke: var(--rt-accent);
        stroke-width: 1.5px;
        stroke-dasharray: 6 4;
        vector-effect: non-scaling-stroke;
        pointer-events: none;
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
      .sheet {
        position: absolute;
        z-index: 9;
        left: 50%;
        bottom: 16px;
        transform: translate(calc(-50% + var(--sheet-dx, 0px)), var(--sheet-dy, 0px));
        width: min(380px, calc(100% - 24px));
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding: 12px 14px;
        border-radius: 16px;
        background: var(--rt-dialog);
        border: 1px solid var(--rt-tile-border);
        box-sizing: border-box;
      }
      .sheet-head {
        display: flex;
        align-items: center;
        gap: 6px;
        cursor: grab;
        touch-action: none;
      }
      .grip {
        --mdc-icon-size: 20px;
        color: var(--rt-text-secondary);
        margin-left: -4px;
      }
      .sheet-title {
        flex: 1;
        font-weight: 700;
      }
      .nudges {
        display: inline-flex;
        gap: 4px;
      }
      .nudge {
        touch-action: none;
      }
      .sheet-foot {
        display: flex;
        gap: 8px;
        justify-content: space-between;
        margin-top: 4px;
      }
      .setting input[type="text"] {
        flex: 1;
        min-width: 0;
      }
      .setting select {
        max-width: 60%;
      }
      input.num:disabled {
        /* the first layer always starts at 1 */
        opacity: 0.45;
        cursor: not-allowed;
        background: none;
        border-style: dashed;
      }
      input.num {
        width: 72px;
        font: inherit;
        color: var(--rt-text);
        background: var(--rt-button);
        border: 1px solid var(--rt-tile-border);
        border-radius: 8px;
        padding: 7px 9px;
      }
      .layer .from {
        color: var(--rt-text-secondary);
        font-size: 0.85rem;
      }
      .arrange {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin: 4px 0 6px;
        --mdc-icon-size: 18px;
      }
      .arrange-note {
        flex-basis: 100%;
        font-size: 12px;
        color: var(--rt-text-secondary);
      }
      .danger {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        border-radius: 10px;
        padding: 8px 12px;
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        color: var(--rt-light);
        --mdc-icon-size: 18px;
      }
      .dialog .list {
        gap: 4px;
      }
      .context.vac {
        --mdc-icon-size: 20px;
        padding-top: 0;
      }
      .sheet .warn {
        display: block;
        margin-top: 4px;
      }
      ha-icon.inline {
        --mdc-icon-size: 16px;
        vertical-align: -2px;
      }
    `,
  ];
}

if (!customElements.get("rt-plan-editor")) customElements.define("rt-plan-editor", RtPlanEditor);
