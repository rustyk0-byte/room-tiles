import { describe, expect, it } from "vitest";
import { REF_VIEW, areaAt, layersAt, layersLabel, onMap, viewZoom, zoomLabel, zoomStep, type MapData } from "./map";

describe("zoom buttons", () => {
  it("step to the next 0.25 up / down", () => {
    expect(zoomStep(1, 1)).toBe(1.25);
    expect(zoomStep(1.7, 1)).toBe(1.75);
    expect(zoomStep(1.7, -1)).toBe(1.5);
    expect(zoomStep(1.75, -1)).toBe(1.5);
    expect(zoomStep(1.7500001, 1)).toBe(2); // a hair over a step counts as on it
  });

  it("never below one step", () => {
    expect(zoomStep(0.8, -1)).toBe(0.75);
    expect(zoomStep(0.25, -1)).toBe(0.25);
    expect(zoomStep(0.3, -1)).toBe(0.25);
  });

  it("label like the layer settings", () => {
    expect(zoomLabel(1.7)).toBe("1.7x");
    expect(zoomLabel(1.8349)).toBe("1.83x");
    expect(zoomLabel(2)).toBe("2x");
  });
});

describe("Add: the area in the middle of the view", () => {
  const zone = (id: string, area: string | null, x0: number, x1: number, vacuum?: string) => ({
    id, name: id, area, label: null, outdoor: false, vacuum,
    points: [[x0, 0], [x1, 0], [x1, 100], [x0, 100]] as [number, number][],
  });
  const map = { zones: [zone("living", "living", 0, 100), zone("bar", "bar", 60, 80), zone("vz", "vac", 0, 50, "vacuum.x"), zone("hall", null, 100, 200)] } as unknown as MapData;

  it("the smallest room there with an area; vacuum zones and area-less rooms don't count", () => {
    expect(areaAt(map, 70, 50)).toBe("bar");
    expect(areaAt(map, 20, 50)).toBe("living");
    expect(areaAt(map, 150, 50)).toBeUndefined();
    expect(areaAt(map, 500, 50)).toBeUndefined();
  });
});

describe("zoom number = marker spacing, the same on any screen", () => {
  const full = { w: 2000, h: 1000 }; // a wide house
  const whole = { w: 2000, h: 1000 }; // camera on the whole map

  it("a panel's map area showing the whole map: 1", () => {
    expect(viewZoom(full, whole, REF_VIEW)).toBeCloseTo(1);
  });

  it("a portrait phone showing the whole map: well below 1 - it must zoom in further before a layer switches", () => {
    expect(viewZoom(full, whole, { w: 390, h: 640 })).toBeCloseTo(390 / 1024);
  });

  it("a big monitor showing the whole map: above 1", () => {
    expect(viewZoom(full, whole, { w: 1900, h: 900 })).toBeCloseTo(1.758, 2); // limited by its height
  });

  it("zooming in doubles it anywhere", () => {
    const half = { w: 1000, h: 500 };
    expect(viewZoom(full, half, { w: 390, h: 640 }) / viewZoom(full, whole, { w: 390, h: 640 })).toBeCloseTo(2);
  });

  it("size not known yet: the plain map-in-view ratio", () => {
    expect(viewZoom(full, { w: 1000, h: 500 }, { w: 1, h: 1 })).toBe(2);
  });
});

describe("a remembered map view", () => {
  const full = { x: 0, y: 0, w: 1000, h: 600 };
  it("kept while it shows part of the map", () => {
    expect(onMap({ x: 900, y: 500, w: 400, h: 300 }, full)).toBeDefined();
  });
  it("dropped when the map moved away from it", () => {
    expect(onMap({ x: 1200, y: 0, w: 400, h: 300 }, full)).toBeUndefined();
    expect(onMap(undefined, full)).toBeUndefined();
  });
});

describe("layers: each over its own zoom range, several at once", () => {
  const map = {
    layers: [
      { id: "main", name: "Main", min_zoom: 1, max_zoom: null },
      { id: "overview", name: "Overview", min_zoom: 1, max_zoom: 3 },
      { id: "rooms", name: "Rooms", min_zoom: 3, max_zoom: null },
    ],
  } as unknown as MapData;
  const at = (z: number) => layersAt(map, z).map((l) => l.id).sort();
  it("every layer whose range holds the zoom shows", () => {
    expect(at(1)).toEqual(["main", "overview"]);
    expect(at(2.99)).toEqual(["main", "overview"]);
    expect(at(3)).toEqual(["main", "rooms"]); // Overview ends where Rooms starts
    expect(at(8)).toEqual(["main", "rooms"]); // no end: on and on
    expect(at(1.998)).toEqual(["main", "overview"]);
    expect(at(2.998)).toEqual(["main", "rooms"]); // shown as 3x: counts as 3x
  });
  it("zoomed out past every start: the first layers", () => {
    expect(at(0.5)).toEqual(["main", "overview"]);
  });
  it("the label: the main layer and how many more", () => {
    const shown = layersAt(map, 4);
    expect(layersLabel(shown[shown.length - 1], shown)).toBe("Rooms +1");
  });
});
