import { describe, expect, it } from "vitest";
import { clampOffset } from "./sheet-drag";

// the map area 0..1000 x 0..600; the sheet 380 x 200, centred at the bottom
const AREA = { left: 0, top: 0, right: 1000, bottom: 600 };
const SHEET = { left: 310, top: 384, right: 690, bottom: 584 };
const AT = { x: 0, y: 0 };

describe("movable sheet", () => {
  it("moves freely inside the map area", () => {
    expect(clampOffset({ x: -200, y: -300 }, AT, SHEET, AREA)).toEqual({ x: -200, y: -300 });
  });

  it("stops at the edges (4 px in)", () => {
    expect(clampOffset({ x: -999, y: 0 }, AT, SHEET, AREA)).toEqual({ x: -306, y: 0 });
    expect(clampOffset({ x: 999, y: 999 }, AT, SHEET, AREA)).toEqual({ x: 306, y: 12 });
    expect(clampOffset({ x: 0, y: -999 }, AT, SHEET, AREA)).toEqual({ x: 0, y: -380 });
  });

  it("measured while already moved: limits are the same place", () => {
    const moved = { left: 110, top: 184, right: 490, bottom: 384 }; // at -200, -200
    expect(clampOffset({ x: -999, y: -999 }, { x: -200, y: -200 }, moved, AREA)).toEqual({ x: -306, y: -380 });
  });

  it("too tall for the area: its top stays in view", () => {
    const tall = { left: 310, top: -100, right: 690, bottom: 584 };
    expect(clampOffset({ x: 0, y: 50 }, AT, tall, AREA).y).toBe(104);
  });
});
