import { describe, expect, it } from "vitest";
import { anchorOf, arrange, MAX_ADD, numbered, pointBox, ringLayout, type Box } from "./arrange";

const apply = (boxes: Box[], moves: { dx: number; dy: number }[]) =>
  boxes.map((b, i) => ({ x0: b.x0 + moves[i].dx, y0: b.y0 + moves[i].dy, x1: b.x1 + moves[i].dx, y1: b.y1 + moves[i].dy }));

describe("group actions", () => {
  it("align left / top: to the FIRST selected, not the leftmost", () => {
    const pts = [pointBox(50, 10), pointBox(10, 40), pointBox(90, 70)];
    expect(apply(pts, arrange(pts, "left")).map((b) => b.x0)).toEqual([50, 50, 50]);
    expect(apply(pts, arrange(pts, "top")).map((b) => b.y0)).toEqual([10, 10, 10]);
    // y untouched by align left
    expect(apply(pts, arrange(pts, "left")).map((b) => b.y0)).toEqual([10, 40, 70]);
  });

  it("space across: points evenly between the outermost two, which stay", () => {
    const pts = [pointBox(0, 5), pointBox(70, 6), pointBox(20, 7), pointBox(100, 8)];
    const out = apply(pts, arrange(pts, "space-h"));
    expect(out.map((b) => b.x0)).toEqual([0, 66.5, 33.5, 100]);
    expect(out.map((b) => b.y0)).toEqual([5, 6, 7, 8]);
  });

  it("space down: boxes get equal GAPS (different sizes)", () => {
    const boxes: Box[] = [
      { x0: 0, y0: 0, x1: 10, y1: 20 }, // 0..20
      { x0: 0, y0: 25, x1: 10, y1: 35 }, // 10 tall
      { x0: 0, y0: 80, x1: 10, y1: 100 }, // 80..100
    ];
    const out = apply(boxes, arrange(boxes, "space-v"));
    // span 100, filled 50 -> gaps of 25
    expect(out.map((b) => [b.y0, b.y1])).toEqual([
      [0, 20],
      [45, 55],
      [80, 100],
    ]);
  });

  it("too few: nothing moves", () => {
    expect(arrange([pointBox(1, 1)], "left")).toEqual([{ dx: 0, dy: 0 }]);
    expect(arrange([pointBox(0, 0), pointBox(9, 9)], "space-h")).toEqual([
      { dx: 0, dy: 0 },
      { dx: 0, dy: 0 },
    ]);
  });

  it("the anchor (dashed outline) is the first selected, only with 2+ selected", () => {
    expect(anchorOf(["b", "a", "c"])).toBe("b");
    expect(anchorOf(["a"])).toBeUndefined();
    expect(anchorOf([])).toBeUndefined();
  });
});

describe("ringLayout (Add several markers)", () => {
  const dist = (a: [number, number], b: [number, number]) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  it("first in the middle, then rings of 6, 12, 18, 25", () => {
    const pts = ringLayout(1 + 6 + 12 + 18 + 25, 100, 50, 10);
    expect(pts[0]).toEqual([100, 50]);
    const ring = (p: [number, number]) => Math.round(dist(p, [100, 50]) / 15);
    const counts = new Map<number, number>();
    for (const p of pts.slice(1)) counts.set(ring(p), (counts.get(ring(p)) ?? 0) + 1);
    expect([...counts.entries()]).toEqual([
      [1, 6],
      [2, 12],
      [3, 18],
      [4, 25],
    ]);
  });
  it("every marker at least half a diameter clear of every other", () => {
    for (const n of [2, 5, 7, 13, 20, 33, MAX_ADD]) {
      const pts = ringLayout(n, 0, 0, 10);
      expect(pts.length).toBe(n);
      for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) expect(dist(pts[i], pts[j])).toBeGreaterThanOrEqual(15 - 1e-6);
    }
  });
  it("at most the centre and three full rings at once", () => {
    expect(MAX_ADD).toBe(37);
  });
  it("the last ring is spaced evenly", () => {
    const pts = ringLayout(1 + 6 + 3, 0, 0, 10).slice(7);
    const ds = [dist(pts[0], pts[1]), dist(pts[1], pts[2]), dist(pts[2], pts[0])];
    expect(Math.max(...ds) - Math.min(...ds)).toBeLessThan(1e-6);
  });
});

describe("numbered (the Here: row)", () => {
  it("numbers only the repeated labels", () => {
    expect(numbered(["Wall", "Deck", "Wall", "Window"])).toEqual(["Wall 1", "Deck", "Wall 2", "Window"]);
  });
});
