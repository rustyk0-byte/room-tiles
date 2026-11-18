import { describe, expect, it } from "vitest";
import { planLabels, roomFloors, shapesInOrder } from "./plan-draw";
import type { MapData } from "./map";

describe("shape drawing order", () => {
  it("by type, bottom to top: grass, paving, deck, water, floor - not by when added", () => {
    const shapes = (["floor", "water", "grass", "deck", "paving", "grass"] as const).map((style, i) => ({ style, i }));
    expect(shapesInOrder(shapes).map((s) => `${s.style}${s.i}`)).toEqual(["grass2", "grass5", "paving4", "deck3", "water1", "floor0"]);
  });
});

describe("room floors", () => {
  it("every inside room has a floor following it; outside rooms and vacuum zones none", () => {
    const sq = (x: number) => [[x, 0], [x + 10, 0], [x + 10, 10], [x, 10]] as [number, number][];
    const m = {
      zones: [
        { id: "a", points: sq(0), outdoor: false },
        { id: "b", points: sq(20), outdoor: false },
        { id: "y", points: sq(40), outdoor: true },
        { id: "v", points: sq(60), outdoor: false, vacuum: "vacuum.x" },
      ],
      shapes: [{ style: "floor", points: sq(20) }],
    } as unknown as MapData;
    expect(roomFloors(m).map((z) => z.id)).toEqual(["a", "b"]);
  });
});

describe("unnamed rooms", () => {
  it("a room with no name has a floor but no label", () => {
    const sq = [[0, 0], [10, 0], [10, 10], [0, 10]] as [number, number][];
    const m = {
      zones: [
        { id: "a", name: "Kitchen", points: sq, area: null, label: null, outdoor: false },
        { id: "b", name: "", points: sq, area: null, label: null, outdoor: false },
      ],
    } as unknown as MapData;
    expect(roomFloors(m).map((z) => z.id)).toEqual(["a", "b"]);
    const labels = planLabels(m, 1).values[0] as unknown[];
    expect(labels.length).toBe(1);
  });
});
