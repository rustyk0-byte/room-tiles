// Plane geometry for the map and the map editor: hit tests, snapping, cutting
// a doorway / window out of a wall. Pure functions (tested in geom.test.ts).

export type Pt = [number, number];
export type Seg = [number, number, number, number];

export const bbox = (pts: Pt[]) => {
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  return { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
};

export const pointIn = (x: number, y: number, pts: Pt[]): boolean => {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i];
    const [xj, yj] = pts[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
};

export const dist = (a: Pt, b: Pt) => Math.hypot(a[0] - b[0], a[1] - b[1]);

/** Polygon area (absolute). */
export function polyArea(pts: Pt[]): number {
  let a = 0;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) a += (pts[j][0] + pts[i][0]) * (pts[j][1] - pts[i][1]);
  return Math.abs(a / 2);
}

/** The closest point on segment s to p, and where along it (0..1). */
export function nearestOnSeg(p: Pt, s: Seg): { pt: Pt; t: number; d: number } {
  const [x1, y1, x2, y2] = s;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len2 = dx * dx + dy * dy;
  const t = len2 ? Math.max(0, Math.min(1, ((p[0] - x1) * dx + (p[1] - y1) * dy) / len2)) : 0;
  const pt: Pt = [x1 + t * dx, y1 + t * dy];
  return { pt, t, d: dist(p, pt) };
}

/** Where line a->a+da meets line b->b+db (undefined if parallel). */
function lineHit(a: Pt, da: Pt, b: Pt, db: Pt): Pt | undefined {
  const den = da[0] * db[1] - da[1] * db[0];
  if (Math.abs(den) < 1e-9) return undefined;
  const t = ((b[0] - a[0]) * db[1] - (b[1] - a[1]) * db[0]) / den;
  return [a[0] + t * da[0], a[1] + t * da[1]];
}

export interface SnapTargets {
  points: Pt[]; // corners: wall ends, room corners...
  segs: Seg[]; // walls to land on
}

export interface SnapResult {
  pt: Pt;
  /** what it snapped to (for the on-screen hint) */
  to?: "point" | "line" | "angle" | "align";
}

const ANGLE_STEP = Math.PI / 4; // 45 degrees
const ANGLE_TOL = (7 * Math.PI) / 180;

/** Snap a point while drawing / dragging. `tol` = how close counts, in map
 *  units (a fixed number of screen px). Order: an existing corner; else, when
 *  drawing on from `from`, a 0 / 45 / 90 degree direction; then landing on a
 *  wall (where that direction crosses it, or the nearest point); else lining up
 *  with a corner's x / y. Always rounded to whole map units. */
export function snap(p: Pt, t: SnapTargets, tol: number, from?: Pt): SnapResult {
  const r = (q: Pt): Pt => [Math.round(q[0] * 2) / 2, Math.round(q[1] * 2) / 2];
  let best: Pt | undefined;
  let bd = tol;
  for (const c of t.points) {
    const d = dist(p, c);
    if (d <= bd) {
      bd = d;
      best = c;
    }
  }
  if (best) return { pt: [best[0], best[1]], to: "point" };

  let q: Pt = p;
  let dir: Pt | undefined;
  if (from && dist(p, from) > tol) {
    const a = Math.atan2(p[1] - from[1], p[0] - from[0]);
    const k = Math.round(a / ANGLE_STEP);
    if (Math.abs(a - k * ANGLE_STEP) < ANGLE_TOL) {
      dir = [Math.round(Math.cos(k * ANGLE_STEP) * 1e6) / 1e6, Math.round(Math.sin(k * ANGLE_STEP) * 1e6) / 1e6];
      const len = (p[0] - from[0]) * dir[0] + (p[1] - from[1]) * dir[1];
      q = [from[0] + dir[0] * len, from[1] + dir[1] * len];
    }
  }

  let segBest: Pt | undefined;
  let sd = tol * 0.7;
  for (const s of t.segs) {
    const n = nearestOnSeg(q, s);
    if (n.d > sd) continue;
    let hit: Pt | undefined = n.pt;
    if (dir && from) {
      const h = lineHit(from, dir, [s[0], s[1]], [s[2] - s[0], s[3] - s[1]]);
      hit = h && nearestOnSeg(h, s).d < 1e-6 && dist(h, q) <= tol ? h : undefined;
    }
    if (hit) {
      sd = n.d;
      segBest = hit;
    }
  }
  if (segBest) return { pt: r(segBest), to: "line" };
  if (dir) return { pt: r(q), to: "angle" };

  // line up with a corner horizontally / vertically
  let ax: number | undefined;
  let ay: number | undefined;
  let dx = tol * 0.6;
  let dy = tol * 0.6;
  for (const c of t.points) {
    if (Math.abs(c[0] - p[0]) < dx) {
      dx = Math.abs(c[0] - p[0]);
      ax = c[0];
    }
    if (Math.abs(c[1] - p[1]) < dy) {
      dy = Math.abs(c[1] - p[1]);
      ay = c[1];
    }
  }
  if (ax !== undefined || ay !== undefined) return { pt: r([ax ?? p[0], ay ?? p[1]]), to: "align" };
  return { pt: r(p) };
}

/** Cut the part of every wall that `gap` lies along (a window or doorway drawn
 *  on a wall replaces that piece of it). Walls not in line with it stay. */
export function cutWalls(walls: Seg[], gap: Seg, tol: number): Seg[] {
  const out: Seg[] = [];
  const g0: Pt = [gap[0], gap[1]];
  const g1: Pt = [gap[2], gap[3]];
  for (const w of walls) {
    const len = Math.hypot(w[2] - w[0], w[3] - w[1]);
    // both ends of the gap on the wall's line (projection unclamped)
    const lineD = (p: Pt) => {
      if (!len) return Infinity;
      return Math.abs((w[2] - w[0]) * (w[1] - p[1]) - (w[0] - p[0]) * (w[3] - w[1])) / len;
    };
    if (lineD(g0) > tol || lineD(g1) > tol || !len) {
      out.push(w);
      continue;
    }
    const tAt = (p: Pt) => ((p[0] - w[0]) * (w[2] - w[0]) + (p[1] - w[1]) * (w[3] - w[1])) / (len * len);
    let a = tAt(g0);
    let b = tAt(g1);
    if (a > b) [a, b] = [b, a];
    if (b <= 0 || a >= 1 || (b - a) * len < tol) {
      out.push(w);
      continue;
    }
    const at = (t: number): Pt => [w[0] + (w[2] - w[0]) * t, w[1] + (w[3] - w[1]) * t];
    if (a * len > tol) out.push([w[0], w[1], ...at(a)] as Seg);
    if ((1 - b) * len > tol) out.push([...at(b), w[2], w[3]] as Seg);
  }
  return out;
}
