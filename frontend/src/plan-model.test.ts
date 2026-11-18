import { describe, expect, it } from "vitest";
import type { MapData } from "./map";
import { addLayer, addZone, removeCorner, convertSegs, cornersAt, deleteRefs, fitBounds, insertCorner, itemsOf, moveCorners, translate, refsAfterDelete } from "./plan-model";

const map = (): MapData => ({
  id: "house",
  name: "House",
  bounds: [0, 0, 100, 100],
  ha_floor: null,
  generated: false,
  wall_width: 6,
  walls: [
    [0, 0, 100, 0],
    [100, 0, 100, 50],
  ],
  windows: [],
  openings: [],
  shapes: [],
  zones: [{ id: "k", name: "Kitchen", points: [[0, 0], [100, 0], [100, 50], [0, 50]], area: null, label: [50, 25], outdoor: false }],
  links: [],
  layers: [{ id: "house", name: "House", min_zoom: 1 }],
});

describe("plan model", () => {
  it("joined corners move together", () => {
    const m = map();
    const corners = cornersAt(m, [100, 0]);
    expect(corners).toEqual([["wall:0", 1], ["wall:1", 0], ["zone:0", 1]]);
    moveCorners(m, corners, [110, 0]);
    expect(m.walls).toEqual([[0, 0, 110, 0], [110, 0, 100, 50]]);
    expect(m.zones[0].points[1]).toEqual([110, 0]);
  });

  it("a vacuum's areas join only each other, never the house drawing", () => {
    const m = map();
    const zone = (id: string, vacuum?: string) => ({
      id, name: id, points: [[100, 0], [150, 0], [150, 50]] as [number, number][], area: null, label: [0, 0] as [number, number], outdoor: false, vacuum,
    });
    m.zones.push(zone("bar", "vacuum.a"), zone("hall", "vacuum.a"), zone("den", "vacuum.b"));
    // the room's corner: the walls and the room - not the vacuum areas on it
    expect(cornersAt(m, [100, 0], undefined, "zone:0")).toEqual([["wall:0", 1], ["wall:1", 0], ["zone:0", 1]]);
    // a vacuum area's corner: that vacuum's areas only
    expect(cornersAt(m, [100, 0], undefined, "zone:1")).toEqual([["zone:1", 0], ["zone:2", 0]]);
    expect(cornersAt(m, [100, 0], undefined, "zone:3")).toEqual([["zone:3", 0]]);
    // (no item given: everything there)
    expect(cornersAt(m, [100, 0]).length).toBe(6);
  });

  it("move, insert a corner, delete", () => {
    const m = map();
    translate(m, ["zone:0"], 5, 5);
    expect(m.zones[0].points[0]).toEqual([5, 5]);
    expect(m.zones[0].label).toEqual([55, 30]);
    insertCorner(m, "zone:0", 0, [50, 0]);
    expect(m.zones[0].points.length).toBe(5);
    deleteRefs(m, ["wall:0", "zone:0"]);
    expect(itemsOf(m).map((i) => i.ref)).toEqual(["wall:0"]);
  });

  it("a corner can go, down to 3", () => {
    const m = map();
    expect(removeCorner(m, "zone:0", 1)).toBe(true);
    expect(m.zones[0].points).toEqual([[0, 0], [100, 50], [0, 50]]);
    expect(removeCorner(m, "zone:0", 0)).toBe(false);
  });

  it("walls become windows and back; new refs", () => {
    const m = map();
    expect(convertSegs(m, ["wall:1"], "window")).toEqual(["window:0"]);
    expect(m.walls.length).toBe(1);
    expect(m.windows).toEqual([[100, 0, 100, 50]]);
  });

  it("new rooms and layers get free ids / names", () => {
    const m = map();
    expect(addZone(m, [[0, 0], [1, 0], [1, 1]])).toBe("zone:1");
    expect([m.zones[1].id, m.zones[1].name, m.zones[1].area]).toEqual(["room_1", "Room 1", null]);
    expect(addLayer(m)).toEqual({ id: "layer_1", name: "Layer 1", min_zoom: 2 });
  });

  it("bounds fit everything plus a margin", () => {
    expect(fitBounds(map(), [[150, 80]])).toEqual([-10, -10, 160, 90]);
    const empty = { ...map(), walls: [], zones: [] };
    expect(fitBounds(empty, [])).toEqual([0, 0, 100, 100]);
  });
});

describe("refsAfterDelete", () => {
  it("drops the deleted and moves later ones of the same kind down", () => {
    expect(refsAfterDelete(["zone:2", "shape:1", "shape:3", "shape:4"], ["shape:3"])).toEqual(["zone:2", "shape:1", "shape:3"]);
    expect(refsAfterDelete(["zone:0", "shape:0", "shape:2"], ["shape:1", "zone:5"])).toEqual(["zone:0", "shape:0", "shape:1"]);
  });
});
