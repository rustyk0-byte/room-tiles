// Group actions for selections (map markers, map editor items): align to the
// FIRST selected item (the anchor), or space evenly between the outermost
// two. Pure: boxes in, a move per item out (tested in arrange.test.ts).
// Markers are boxes of zero size; rooms / shapes / walls / links use their
// outline box. The caller moves the items - and keeps the selection.

import { t } from "./i18n";

export type ArrangeOp = "left" | "top" | "space-h" | "space-v";

export interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface Move {
  dx: number;
  dy: number;
}

export const ARRANGE_OPS: { op: ArrangeOp; label: string; icon: string; min: number; title: string }[] = [
  // label / title read when drawn (the language can change)
  {
    op: "left",
    get label() {
      return t("arrange.left");
    },
    icon: "mdi:align-horizontal-left",
    min: 2,
    get title() {
      return t("arrange.left_tip");
    },
  },
  {
    op: "top",
    get label() {
      return t("arrange.top");
    },
    icon: "mdi:align-vertical-top",
    min: 2,
    get title() {
      return t("arrange.top_tip");
    },
  },
  {
    op: "space-h",
    get label() {
      return t("arrange.space_h");
    },
    icon: "mdi:distribute-horizontal-center",
    min: 3,
    get title() {
      return t("arrange.space_h_tip");
    },
  },
  {
    op: "space-v",
    get label() {
      return t("arrange.space_v");
    },
    icon: "mdi:distribute-vertical-center",
    min: 3,
    get title() {
      return t("arrange.space_v_tip");
    },
  },
];

/** The move for each box (same order); `anchor` = the first selected. */
export function arrange(boxes: Box[], op: ArrangeOp, anchor = 0): Move[] {
  const moves: Move[] = boxes.map(() => ({ dx: 0, dy: 0 }));
  if (boxes.length < 2) return moves;
  const a = boxes[anchor] ?? boxes[0];
  if (op === "left") return boxes.map((b) => ({ dx: a.x0 - b.x0, dy: 0 }));
  if (op === "top") return boxes.map((b) => ({ dx: 0, dy: a.y0 - b.y0 }));
  if (boxes.length < 3) return moves;
  const across = op === "space-h";
  const lo = (b: Box) => (across ? b.x0 : b.y0);
  const size = (b: Box) => (across ? b.x1 - b.x0 : b.y1 - b.y0);
  // in order along the axis; the first and the last stay where they are
  const order = boxes.map((_, i) => i).sort((i, j) => lo(boxes[i]) - lo(boxes[j]) || i - j);
  const first = boxes[order[0]];
  const last = boxes[order[order.length - 1]];
  const span = lo(last) + size(last) - lo(first);
  const filled = order.reduce((sum, i) => sum + size(boxes[i]), 0);
  const gap = (span - filled) / (order.length - 1);
  let at = lo(first);
  for (const i of order) {
    const d = Math.round((at - lo(boxes[i])) * 2) / 2; // whole / half map units
    moves[i] = across ? { dx: d, dy: 0 } : { dx: 0, dy: d };
    at += size(boxes[i]) + gap;
  }
  return moves;
}

/** A point as a box of zero size (markers). */
export const pointBox = (x: number, y: number): Box => ({ x0: x, y0: y, x1: x, y1: y });

/** The item Align lines the others up with (shown with a dashed outline):
 *  the first selected - only while there's more than one. */
export const anchorOf = (selected: string[]): string | undefined => (selected.length > 1 ? selected[0] : undefined);

/** Neighbours keep half a marker's diameter between them: centres this
 *  many diameters apart. */
const RING_GAP = 1.5;

/** How many markers ring k (1, 2, ...) holds: chord 2r sin(pi/m) >= gap. */
const ringFits = (k: number): number => Math.max(1, Math.floor(Math.PI / Math.asin(Math.min(1, 1 / (2 * k))) + 1e-9));

/** Most markers one Add places at once: the centre and three full rings (37). */
export const MAX_ADD = 1 + ringFits(1) + ringFits(2) + ringFits(3);

/** Where Add puts `n` markers at once: the first on (cx, cy), the rest in
 *  rings around it. `d` = a marker's diameter; neighbours keep at least half
 *  a diameter between them (centres 1.5d apart): ring k sits k * 1.5d out
 *  and holds as many as fit (6, 12, 18, 25, ...), evenly spaced from the
 *  top; the last ring spaces what's left evenly. */
export function ringLayout(n: number, cx: number, cy: number, d: number): [number, number][] {
  const out: [number, number][] = [];
  if (n <= 0) return out;
  out.push([cx, cy]);
  const gap = RING_GAP * d;
  for (let k = 1; out.length < n; k++) {
    const r = k * gap;
    const fits = ringFits(k);
    const m = Math.min(fits, n - out.length);
    for (let i = 0; i < m; i++) {
      const a = -Math.PI / 2 + (2 * Math.PI * i) / m;
      out.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
    }
  }
  return out;
}

/** "Wall", "Wall", "Deck" -> "Wall 1", "Wall 2", "Deck": the "Here:" row's
 *  buttons can be told apart. */
export function numbered(labels: string[]): string[] {
  const total = new Map<string, number>();
  for (const l of labels) total.set(l, (total.get(l) ?? 0) + 1);
  const seen = new Map<string, number>();
  return labels.map((l) => {
    if ((total.get(l) ?? 0) < 2) return l;
    const n = (seen.get(l) ?? 0) + 1;
    seen.set(l, n);
    return `${l} ${n}`;
  });
}
