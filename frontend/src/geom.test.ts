import { describe, expect, it } from "vitest";
import { cutWalls, snap, type Seg } from "./geom";

describe("snap", () => {
  const targets = { points: [[0, 0], [100, 0]] as [number, number][], segs: [[0, 0, 100, 0]] as Seg[] };

  it("an existing corner wins", () => {
    expect(snap([98, 3], targets, 10)).toEqual({ pt: [100, 0], to: "point" });
  });

  it("drawing on: 0 / 45 / 90 degree directions", () => {
    const r = snap([3, 60], { points: [], segs: [] }, 10, [0, 0]);
    expect(r).toEqual({ pt: [0, 60], to: "angle" });
    expect(snap([41, 39], { points: [], segs: [] }, 5, [0, 0]).pt).toEqual([40, 40]);
  });

  it("lands on a wall; along a direction, where it crosses it", () => {
    expect(snap([50, 4], targets, 10)).toEqual({ pt: [50, 0], to: "line" });
    expect(snap([52, 5], targets, 10, [50, 80])).toEqual({ pt: [50, 0], to: "line" });
  });

  it("lines up with a corner, else just rounds", () => {
    expect(snap([60, 103.2], { points: [[0, 100]], segs: [] }, 10)).toEqual({ pt: [60, 100], to: "align" });
    expect(snap([60.3, 233.26], { points: [], segs: [] }, 10)).toEqual({ pt: [60.5, 233.5] });
  });
});

describe("cutWalls", () => {
  it("a window on a wall cuts that piece out", () => {
    expect(cutWalls([[0, 0, 100, 0]], [40, 0, 60, 0], 2)).toEqual([
      [0, 0, 40, 0],
      [60, 0, 100, 0],
    ]);
  });
  it("at a wall's end, one piece stays; across or off the wall, nothing changes", () => {
    expect(cutWalls([[0, 0, 100, 0]], [80, 0, 120, 0], 2)).toEqual([[0, 0, 80, 0]]);
    expect(cutWalls([[0, 0, 100, 0]], [50, -10, 50, 10], 2)).toEqual([[0, 0, 100, 0]]);
    expect(cutWalls([[0, 0, 100, 0]], [10, 20, 30, 20], 2)).toEqual([[0, 0, 100, 0]]);
  });
});
