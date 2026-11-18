import { describe, expect, it } from "vitest";
import { queueInfo, queueMaps, roomsOf, tileMap, type QueueInfo } from "./vacqueue";
import type { MapData } from "./map";
import type { HomeAssistant, RoomTilesDoc } from "./types";

const sq = [[0, 0], [10, 0], [10, 10], [0, 10]] as [number, number][];
const zone = (id: string, area: string | null, vacuum: string | null = null) => ({ id, name: id, points: sq, area, label: null, outdoor: false, vacuum });
const maps = [
  { id: "up", name: "Upstairs", zones: [zone("bed", "bedroom")] },
  { id: "house", name: "House", zones: [zone("k", "kitchen"), zone("h", "hall"), zone("bar", "bar_area", "vacuum.matic")] },
  { id: "yard", name: "Yard", zones: [zone("lawn", "backyard")] },
] as unknown as MapData[];
const q = (over: Partial<QueueInfo> = {}): QueueInfo => ({
  robot: "matic", sensor: "sensor.room_tiles_matic", vacuum: "vacuum.matic", name: "Matic",
  queue: [], current: null, cleanable: ["kitchen", "hall", "bar_area", "bedroom"], ...over,
});

describe("the vacuum queue on the dashboard", () => {
  it("the maps it cleans on (not the yard)", () => {
    expect(queueMaps(maps, q()).map((m) => m.id)).toEqual(["up", "house"]);
  });
  it("the tile's map: the room being cleaned's, else the first queued's, else the first", () => {
    expect(tileMap(maps, q({ current: "kitchen" }))?.id).toBe("house");
    expect(tileMap(maps, q({ queue: ["bedroom", "hall"] }))?.id).toBe("up");
    expect(tileMap(maps, q())?.id).toBe("up");
  });
  it("an area's rooms include the vacuum's own zones (only its)", () => {
    expect(roomsOf(maps[1], "bar_area", "vacuum.matic").map((z) => z.id)).toEqual(["bar"]);
    expect(roomsOf(maps[1], "bar_area", "vacuum.other")).toEqual([]);
  });
  it("queueInfo: only for a vacuum with clean_area and mapped areas", () => {
    const hass = {
      states: {
        "sensor.room_tiles_matic": { entity_id: "sensor.room_tiles_matic", state: "docked", attributes: { robot: "matic", vacuum: "vacuum.matic", clean_area: true, queue: ["hall"], current: "kitchen", own_name: "Matic" } },
        "sensor.room_tiles_roomba": { entity_id: "sensor.room_tiles_roomba", state: "docked", attributes: { robot: "roomba", vacuum: "vacuum.roomba", clean_area: false } },
      },
    } as unknown as HomeAssistant;
    const doc = { vacuums: { "vacuum.matic": { name: "Matic", areas: ["kitchen", "hall"] } } } as unknown as RoomTilesDoc;
    expect(queueInfo(hass, doc, "sensor.room_tiles_matic")).toMatchObject({ robot: "matic", queue: ["hall"], current: "kitchen" });
    expect(queueInfo(hass, doc, "vacuum.matic")?.robot).toBe("matic");
    expect(queueInfo(hass, doc, "sensor.room_tiles_roomba")).toBeUndefined();
  });
});

describe("why a vacuum has no queue (its tile says)", () => {
  it("not supported / not linked to areas / not on a map / fine", async () => {
    const { queueProblem } = await import("./vacqueue");
    const st = (robot: string, vacuum: string, clean: boolean) => ({ entity_id: `sensor.room_tiles_${robot}`, state: "docked", attributes: { robot, vacuum, clean_area: clean } });
    const hass = {
      states: {
        "sensor.room_tiles_roomba": st("roomba", "vacuum.roomba", false),
        "sensor.room_tiles_robo": st("robo", "vacuum.robo", true),
        "sensor.room_tiles_far": st("far", "vacuum.far", true),
        "sensor.room_tiles_matic": st("matic", "vacuum.matic", true),
      },
    } as unknown as HomeAssistant;
    const doc = { vacuums: { "vacuum.far": { name: "Far", areas: ["attic"] }, "vacuum.matic": { name: "Matic", areas: ["kitchen"] } } } as unknown as RoomTilesDoc;
    expect(queueProblem(hass, doc, maps, "sensor.room_tiles_roomba")).toMatch(/isn't supported/);
    expect(queueProblem(hass, doc, maps, "sensor.room_tiles_robo")).toMatch(/haven't been set up/);
    expect(queueProblem(hass, doc, maps, "sensor.room_tiles_far")).toMatch(/aren't on a map/);
    expect(queueProblem(hass, doc, maps, "sensor.room_tiles_matic")).toBeUndefined();
  });
});

describe("roomState (the panels' colour key)", () => {
  it("queued rooms blue; the one being cleaned by what the vacuum is doing", async () => {
    const { roomState } = await import("./vacqueue");
    const q = (cls: string) => ({ queue: ["a", "b"], current: "c", cls });
    expect(roomState(q("cleaning"), "a")).toBe("queued");
    expect(roomState(q("cleaning"), "c")).toBe("cleaning");
    expect(roomState(q("paused"), "c")).toBe("paused");
    expect(roomState(q("attention"), "c")).toBe("attention");
    expect(roomState(q("error"), "c")).toBe("error");
    expect(roomState(q("docked"), "c")).toBe("starting"); // sent, not cleaning yet
    expect(roomState(q("cleaning"), "z")).toBeUndefined();
  });
});
