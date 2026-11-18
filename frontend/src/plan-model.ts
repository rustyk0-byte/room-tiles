// The map editor's operations on a map drawing (MapData), as pure functions -
// the editor component only calls these (tested in plan-model.test.ts).
//
// Items are addressed by REFS: "<kind>:<index>" - "wall:3", "zone:0". Indexes
// shift when items are deleted, so a selection is only valid for the drawing
// it was made on.

import { bbox, type Pt, type Seg } from "./geom";
import type { MapData, MapLayer, MapShape } from "./map";
import { SHAPE_ORDER } from "./plan-draw";
import { t } from "./i18n";

export type SegKind = "wall" | "window" | "opening";
export type ItemKind = SegKind | "zone" | "shape" | "link";
export const SEG_KINDS: SegKind[] = ["wall", "window", "opening"];
export const SEG_KEY: Record<SegKind, "walls" | "windows" | "openings"> = { wall: "walls", window: "windows", opening: "openings" };
// the style pickers list them in drawing order (bottom to top) - one list
export const SHAPE_STYLES: MapShape["style"][] = SHAPE_ORDER;
/** what the Shape tool draws - a floor is a room's (plan-draw roomFloors) */
export const NEW_SHAPE_STYLES: MapShape["style"][] = SHAPE_ORDER.filter((s) => s !== "floor");

export interface Item {
  ref: string;
  kind: ItemKind;
  i: number;
  pts: Pt[];
}

export const parseRef = (ref: string) => {
  const [k, i] = ref.split(":");
  return { kind: k as ItemKind, i: Number(i) };
};

export const cloneMap = (m: MapData): MapData => JSON.parse(JSON.stringify(m)) as MapData;

/** Every item of the drawing, with its points. */
export function itemsOf(m: MapData): Item[] {
  const out: Item[] = [];
  for (const k of SEG_KINDS)
    m[SEG_KEY[k]].forEach((s, i) => out.push({ ref: `${k}:${i}`, kind: k, i, pts: [[s[0], s[1]], [s[2], s[3]]] }));
  m.zones.forEach((z, i) => out.push({ ref: `zone:${i}`, kind: "zone", i, pts: z.points }));
  m.shapes.forEach((sh, i) => out.push({ ref: `shape:${i}`, kind: "shape", i, pts: sh.points }));
  m.links.forEach((l, i) => out.push({ ref: `link:${i}`, kind: "link", i, pts: [l.at] }));
  return out;
}

export function exists(m: MapData, ref: string): boolean {
  const { kind, i } = parseRef(ref);
  const list = kind === "zone" ? m.zones : kind === "shape" ? m.shapes : kind === "link" ? m.links : m[SEG_KEY[kind as SegKind]];
  return Array.isArray(list) && i >= 0 && i < list.length;
}

export function getPts(m: MapData, ref: string): Pt[] {
  const { kind, i } = parseRef(ref);
  if (kind === "zone") return m.zones[i].points;
  if (kind === "shape") return m.shapes[i].points;
  if (kind === "link") return [m.links[i].at];
  const s = m[SEG_KEY[kind]][i];
  return [
    [s[0], s[1]],
    [s[2], s[3]],
  ];
}

/** Write an item's points back (in place on `m`). */
export function setPts(m: MapData, ref: string, pts: Pt[]): void {
  const { kind, i } = parseRef(ref);
  if (kind === "zone") m.zones[i].points = pts;
  else if (kind === "shape") m.shapes[i].points = pts;
  else if (kind === "link") m.links[i].at = pts[0];
  else m[SEG_KEY[kind]][i] = [pts[0][0], pts[0][1], pts[1][0], pts[1][1]];
}

/** Move items by dx, dy (in place). A room's label moves with it. */
export function translate(m: MapData, refs: Iterable<string>, dx: number, dy: number): void {
  for (const ref of refs) {
    setPts(m, ref, getPts(m, ref).map((p) => [p[0] + dx, p[1] + dy] as Pt));
    const { kind, i } = parseRef(ref);
    const z = kind === "zone" ? m.zones[i] : undefined;
    if (z?.label) z.label = [z.label[0] + dx, z.label[1] + dy];
  }
}

/** Delete items (in place). */
/** `refs` ("zone:3", "shape:1"...) after deleting `gone`: those go, and the
 *  later ones of the same kind move down (the lists are re-indexed). */
export function refsAfterDelete(refs: string[], gone: string[]): string[] {
  const goneBy = new Map<string, number[]>();
  for (const g of gone) {
    const [k, n] = g.split(":");
    goneBy.set(k, [...(goneBy.get(k) ?? []), Number(n)]);
  }
  return refs
    .filter((r) => !gone.includes(r))
    .map((r) => {
      const [k, n] = r.split(":");
      const i = Number(n);
      const before = (goneBy.get(k) ?? []).filter((g) => g < i).length;
      return `${k}:${i - before}`;
    });
}

export function deleteRefs(m: MapData, refs: Iterable<string>): void {
  const by = new Map<ItemKind, Set<number>>();
  for (const ref of refs) {
    const { kind, i } = parseRef(ref);
    if (!by.has(kind)) by.set(kind, new Set());
    by.get(kind)!.add(i);
  }
  const keep = <T>(list: T[], k: ItemKind) => list.filter((_, i) => !by.get(k)?.has(i));
  for (const k of SEG_KINDS) m[SEG_KEY[k]] = keep(m[SEG_KEY[k]], k);
  m.zones = keep(m.zones, "zone");
  m.shapes = keep(m.shapes, "shape");
  m.links = keep(m.links, "link");
}

/** Turn walls / windows / openings into another of the three (in place);
 *  returns their new refs. */
export function convertSegs(m: MapData, refs: string[], to: SegKind): string[] {
  const moving: Seg[] = [];
  const del: string[] = [];
  for (const ref of refs) {
    const { kind, i } = parseRef(ref);
    if (!SEG_KINDS.includes(kind as SegKind) || kind === to) continue;
    moving.push(m[SEG_KEY[kind as SegKind]][i]);
    del.push(ref);
  }
  const unchanged = refs.filter((r) => parseRef(r).kind === to);
  deleteRefs(m, del);
  const target = m[SEG_KEY[to]];
  const start = target.length;
  target.push(...moving);
  // the unchanged ones' indexes in `to` didn't move (only other lists lost items)
  return [...unchanged, ...moving.map((_, k) => `${to}:${start + k}`)];
}

/** What an item's corners join with: the house drawing (walls, windows,
 *  openings, rooms, shapes) together; a vacuum's areas only with that
 *  vacuum's other areas - drawn over the house, they snap to it but are
 *  never welded to it (or to another vacuum's, which aren't even shown). */
export function joinGroup(m: MapData, ref: string): string {
  const { kind, i } = parseRef(ref);
  const vacuum = kind === "zone" ? m.zones[i]?.vacuum : undefined;
  return vacuum ? `vacuum:${vacuum}` : "house";
}

/** Every corner (vertex) at `p` (within eps): [ref, vertex index]. Joined
 *  corners - a wall end on a room corner - move together. `of`: only the
 *  corners that join with this item's (joinGroup). */
export function cornersAt(m: MapData, p: Pt, eps = 0.01, of?: string): [string, number][] {
  const out: [string, number][] = [];
  const group = of === undefined ? undefined : joinGroup(m, of);
  for (const it of itemsOf(m)) {
    if (it.kind === "link") continue;
    if (group !== undefined && joinGroup(m, it.ref) !== group) continue;
    it.pts.forEach((q, vi) => {
      if (Math.abs(q[0] - p[0]) <= eps && Math.abs(q[1] - p[1]) <= eps) out.push([it.ref, vi]);
    });
  }
  return out;
}

/** Move the given corners to p (in place). */
export function moveCorners(m: MapData, corners: [string, number][], p: Pt): void {
  for (const [ref, vi] of corners) {
    const pts = getPts(m, ref).map((q) => [q[0], q[1]] as Pt);
    pts[vi] = [p[0], p[1]];
    setPts(m, ref, pts);
  }
}

/** Insert a corner into a room / shape after vertex `after` (in place). */
export function insertCorner(m: MapData, ref: string, after: number, p: Pt): void {
  const pts = getPts(m, ref).map((q) => [q[0], q[1]] as Pt);
  pts.splice(after + 1, 0, [p[0], p[1]]);
  setPts(m, ref, pts);
}

/** Remove corner `vi` from a room / shape (in place); refused below 3. */
export function removeCorner(m: MapData, ref: string, vi: number): boolean {
  const pts = getPts(m, ref);
  if (pts.length <= 3 || vi < 0 || vi >= pts.length) return false;
  setPts(m, ref, pts.filter((_, k) => k !== vi).map((q) => [q[0], q[1]] as Pt));
  return true;
}

/** Corners to snap to, leaving out the ones being moved ("ref#vi" keys). */
export function snapPoints(m: MapData, skip: Set<string> = new Set()): Pt[] {
  const out: Pt[] = [];
  for (const it of itemsOf(m)) {
    if (it.kind === "link") continue;
    it.pts.forEach((p, vi) => {
      if (!skip.has(`${it.ref}#${vi}`) && !skip.has(it.ref)) out.push(p);
    });
  }
  return out;
}

const unique = (base: string, taken: Set<string>) => {
  let n = 1;
  while (taken.has(`${base}${n}`)) n++;
  return `${base}${n}`;
};

/** A new room (zone) - returns its ref. */
export function addZone(m: MapData, pts: Pt[]): string {
  const id = unique("room_", new Set(m.zones.map((z) => z.id)));
  const name = numberedName("editor.new_room", new Set(m.zones.map((z) => z.name)));
  m.zones.push({ id, name, points: pts, area: null, label: null, outdoor: false });
  return `zone:${m.zones.length - 1}`;
}

/** "Room 3" in the language (`key` with {n}): the first not taken. */
export function numberedName(key: string, taken: Set<string>): string {
  for (let n = 1; ; n++) {
    const name = t(key, { n });
    if (!taken.has(name)) return name;
  }
}

export function addLayer(m: MapData): MapLayer {
  const id = unique("layer_", new Set(m.layers.map((l) => l.id)));
  const top = Math.max(1, ...m.layers.map((l) => l.min_zoom));
  const layer = { id, name: numberedName("editor.new_layer", new Set(m.layers.map((l) => l.name))), min_zoom: Math.round((top + 1) * 10) / 10 };
  m.layers.push(layer);
  return layer;
}

/** The whole-map view's bounds: everything drawn plus the map's markers, with
 *  a margin. Unchanged if there's nothing at all. */
export function fitBounds(m: MapData, markers: Pt[]): [number, number, number, number] {
  const pts = [...itemsOf(m).flatMap((it) => it.pts), ...markers];
  if (!pts.length) return m.bounds;
  const b = bbox(pts);
  const pad = Math.max(10, Math.round(Math.max(b.x1 - b.x0, b.y1 - b.y0) * 0.04));
  const r = (v: number) => Math.round(v);
  return [r(b.x0 - pad), r(b.y0 - pad), r(b.x1 + pad), r(b.y1 + pad)];
}
