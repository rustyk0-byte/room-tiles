// The trace picture's geometry (pure; tested in trace-geom.test.ts): its box
// on the map, the handles - corners resize (keeping its shape), side dots
// stretch one way (phone photos are rarely to scale both ways), the knob
// above turns it in fine steps (photos are rarely straight) - and 90 degree
// turns.

import type { Pt } from "./geom";
import type { TracePicture } from "./trace-store";

/** The Picture tool's slider: a blend between the picture (0) and your
 *  drawing (1). In the middle both show in full; towards an end the other
 *  fades - down to MIN_SHOWN, so what you trace / move never vanishes. */
export const MIN_SHOWN = 0.12;
export function traceBlend(blend: number | undefined): { picture: number; drawing: number } {
  const b = Math.min(1, Math.max(0, blend ?? 0.5));
  return { picture: Math.max(MIN_SHOWN, Math.min(1, 2 * (1 - b))), drawing: Math.max(MIN_SHOWN, Math.min(1, 2 * b)) };
}

/** The picture's box: centre, size (after its quarter turns), fine tilt. */
export interface PicBox {
  cx: number;
  cy: number;
  w: number;
  h: number;
  tilt: number; // degrees, clockwise
}

export type PicHandle = { kind: "corner" | "side"; sx: -1 | 0 | 1; sy: -1 | 0 | 1 } | { kind: "turn" } | { kind: "move" };

/** `aspect` = the image's natural height / width. */
export function picBox(t: TracePicture, aspect: number): PicBox {
  const h = t.h ?? t.w * (t.rot % 2 ? 1 / aspect : aspect);
  return { cx: t.x + t.w / 2, cy: t.y + h / 2, w: t.w, h, tilt: t.tilt ?? 0 };
}

const rad = (deg: number) => (deg * Math.PI) / 180;

/** map point -> the box's own frame (centre 0,0, untilted) */
export function toLocal(b: PicBox, p: Pt): Pt {
  const dx = p[0] - b.cx;
  const dy = p[1] - b.cy;
  const c = Math.cos(-rad(b.tilt));
  const s = Math.sin(-rad(b.tilt));
  return [dx * c - dy * s, dx * s + dy * c];
}

export function toWorld(b: PicBox, q: Pt): Pt {
  const c = Math.cos(rad(b.tilt));
  const s = Math.sin(rad(b.tilt));
  return [b.cx + q[0] * c - q[1] * s, b.cy + q[0] * s + q[1] * c];
}

/** What's under p: the turn knob (`knob` above the top edge), a corner, a
 *  side dot, the picture itself. */
export function picHandleAt(b: PicBox, p: Pt, tol: number, knob: number): PicHandle | undefined {
  const [x, y] = toLocal(b, p);
  const hw = b.w / 2;
  const hh = b.h / 2;
  const near = (px: number, py: number) => Math.hypot(x - px, y - py) <= tol;
  if (near(0, -hh - knob)) return { kind: "turn" };
  for (const sx of [-1, 1] as const) for (const sy of [-1, 1] as const) if (near(sx * hw, sy * hh)) return { kind: "corner", sx, sy };
  for (const sx of [-1, 1] as const) if (near(sx * hw, 0)) return { kind: "side", sx, sy: 0 };
  for (const sy of [-1, 1] as const) if (near(0, sy * hh)) return { kind: "side", sx: 0, sy };
  if (Math.abs(x) <= hw && Math.abs(y) <= hh) return { kind: "move" };
  return undefined;
}

/** Drag a corner (resize, same shape) or a side dot (stretch that way) to p;
 *  the opposite corner / side stays put. Returns the new x, y, w, h. */
export function resizePic(b: PicBox, h: { sx: number; sy: number; kind: "corner" | "side" }, p: Pt, min: number): Pick<TracePicture, "x" | "y" | "w" | "h"> {
  const [qx, qy] = toLocal(b, p);
  const ax = -h.sx * (b.w / 2);
  const ay = -h.sy * (b.h / 2);
  let w = b.w;
  let hh = b.h;
  if (h.kind === "corner") {
    const k = Math.max((h.sx * (qx - ax)) / b.w, (h.sy * (qy - ay)) / b.h, min / Math.min(b.w, b.h));
    w = b.w * k;
    hh = b.h * k;
  } else if (h.sx) w = Math.max(min, h.sx * (qx - ax));
  else hh = Math.max(min, h.sy * (qy - ay));
  // the new centre, in the box's frame: from the fixed corner / side
  const lc: Pt = [h.sx ? ax + (h.sx * w) / 2 : 0, h.sy ? ay + (h.sy * hh) / 2 : 0];
  const [cx, cy] = toWorld(b, lc);
  return { x: cx - w / 2, y: cy - hh / 2, w, h: hh };
}

/** The tilt for the knob dragged to p: 0.1 degree steps, straight within 0.4. */
export function tiltFrom(b: PicBox, p: Pt): number {
  let a = (Math.atan2(p[1] - b.cy, p[0] - b.cx) * 180) / Math.PI + 90;
  if (a > 180) a -= 360;
  a = Math.round(a * 10) / 10;
  return Math.abs(a) < 0.4 ? 0 : a;
}

/** Turn 90 degrees clockwise around the centre (the box's sides swap). */
export function turn90(t: TracePicture, aspect: number): Partial<TracePicture> {
  const b = picBox(t, aspect);
  return { rot: (t.rot + 1) % 4, w: b.h, h: b.w, x: b.cx - b.h / 2, y: b.cy - b.w / 2 };
}
