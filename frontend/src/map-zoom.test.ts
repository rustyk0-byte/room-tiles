import { describe, expect, it } from "vitest";
import { viewMaxZoom, type MapData } from "./map";

// a map as big as the reference view (1024 x 552): zoom = 1024 / a room's width
const map = (zones: [number, number][][], layers: { id: string; name: string; min_zoom: number }[] = []) =>
  ({
    id: "m",
    name: "M",
    bounds: [0, 0, 1024, 552],
    zones: zones.map((points, i) => ({ id: `z${i}`, name: `Z${i}`, points, area: null })),
    layers,
  }) as unknown as MapData;
const room = (w: number, h: number): [number, number][] => [[0, 0], [w, 0], [w, h], [0, h]];

describe("viewMaxZoom", () => {
  it("is 8x for a map whose rooms and layers need less", () => {
    expect(viewMaxZoom(map([room(100, 50)]))).toBe(8); // (a tap on it: ~7.5x)
  });
  it("reaches the smallest room, in 0.25 steps", () => {
    // 50 x 25 with the 18% margin round it: 68 x 34 -> 1024 / 68 = 15.06 -> 15.25
    expect(viewMaxZoom(map([room(50, 25)]))).toBe(15.25);
  });
  it("reaches past the deepest layer's start", () => {
    expect(viewMaxZoom(map([room(100, 50)], [{ id: "a", name: "A", min_zoom: 1 }, { id: "b", name: "B", min_zoom: 10 }]))).toBe(12.5);
  });
  it("leaves out a vacuum's own zones", () => {
    const m = map([room(100, 50), room(10, 10)]);
    (m.zones[1] as { vacuum?: string }).vacuum = "robot";
    expect(viewMaxZoom(m)).toBe(8);
  });
});
