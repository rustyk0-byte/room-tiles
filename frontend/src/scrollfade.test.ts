import { describe, expect, it } from "vitest";
import { moreBeyond, rowAt } from "./ui";

describe("scroll fades", () => {
  it("fade where there's more", () => {
    expect(moreBeyond(400, 800, 0)).toEqual({ above: false, below: true });
    expect(moreBeyond(400, 800, 200)).toEqual({ above: true, below: true });
    expect(moreBeyond(400, 800, 400)).toEqual({ above: true, below: false });
  });

  it("nothing when it all fits, nor for a pixel's rounding", () => {
    expect(moreBeyond(400, 400, 0)).toEqual({ above: false, below: false });
    expect(moreBeyond(400, 401, 0)).toEqual({ above: false, below: false });
    expect(moreBeyond(400, 800, 399.5)).toEqual({ above: true, below: false });
  });
});

// a fake element: its box (top, bottom; full width) and children
const box = (top: number, bottom: number, kids: Element[] = []): Element =>
  ({ children: kids, getBoundingClientRect: () => ({ top, bottom, height: bottom - top, left: 0, right: 100, width: 100 }) }) as unknown as Element;
// a row: icon, label, arrow side by side
const row = (top: number, bottom: number): Element => box(top, bottom, [box(top + 8, bottom - 8), box(top + 4, bottom - 4), box(top + 8, bottom - 8)]);

describe("the row at a fade's edge", () => {
  // a menu: a group of rows (head + 4 rows of 50), then a lone row
  const group = box(0, 260, [box(0, 40), row(40, 90), row(90, 140), row(140, 190), row(190, 240)]);
  const menu = box(0, 400, [group, row(270, 320)]);

  it("is the row the edge crosses - inside a group, never the whole group", () => {
    const r = rowAt(menu, 165, true)!;
    expect([r.top, r.bottom]).toEqual([140, 190]);
  });

  it("between rows: the last one above the bottom edge, fully", () => {
    const r = rowAt(menu, 255, true)!; // (the gap after the group)
    expect([r.top, r.bottom]).toEqual([190, 240]);
  });

  it("at the top edge: the first row below it", () => {
    const r = rowAt(menu, 245, false)!;
    expect([r.top, r.bottom]).toEqual([270, 320]);
  });

  it("a row's parts side by side are one row", () => {
    const r = rowAt(box(0, 100, [row(0, 50), row(50, 100)]), 70, true)!;
    expect([r.top, r.bottom]).toEqual([50, 100]);
  });
});
