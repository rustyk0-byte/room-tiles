import { describe, expect, it } from "vitest";
import { ALL_AREAS, NO_AREA, areaChoices, canBeTile, candidatesIn, fullName, sameNamed, telling, type Candidate } from "./picker";
import type { HomeAssistant, RoomTilesDoc } from "./types";

describe("telling same-named entries apart", () => {
  const c = (entity: string, full: string, short?: string): Candidate => ({ entity, full, short });

  it("flags entries sharing a full or short name, nothing else", () => {
    const list = [
      c("sensor.laundry_tile", "Laundry Tile", "Laundry"),
      c("sensor.room_tiles_laundry", "Laundry2", "laundry"),
      c("light.lamp", "Living Lamp", "Lamp"),
      c("light.lamp_2", "Dining Lamp", "Kitchen"),
    ];
    expect([...sameNamed(list)].sort()).toEqual(["sensor.laundry_tile", "sensor.room_tiles_laundry"]);
  });

  it("says where it comes from and its entity id", () => {
    const hass = {
      entities: {
        "sensor.room_tiles_laundry": { entity_id: "sensor.room_tiles_laundry", platform: "room_tiles" },
        "sensor.laundry_tile": { entity_id: "sensor.laundry_tile", platform: "template" },
        "switch.x": { entity_id: "switch.x", platform: "lg_thinq" },
      },
    } as unknown as HomeAssistant;
    expect(telling(hass, "sensor.room_tiles_laundry")).toBe("Room Tiles · sensor.room_tiles_laundry");
    expect(telling(hass, "sensor.laundry_tile")).toBe("Template · sensor.laundry_tile");
    expect(telling(hass, "switch.x")).toBe("Lg thinq · switch.x");
    expect(telling(hass, "switch.unknown")).toBe("switch.unknown");
  });
});

describe("area filter", () => {
  const hass = {
    states: {
      "light.a": { attributes: { friendly_name: "Lamp A" } },
      "light.b": { attributes: { friendly_name: "Lamp B" } },
      "light.c": { attributes: { friendly_name: "Porch" } },
      "light.loose": { attributes: { friendly_name: "Loose" } },
    },
    entities: {
      "light.a": { entity_id: "light.a", area_id: "kitchen" },
      "light.b": { entity_id: "light.b", device_id: "d1" },
      "light.c": { entity_id: "light.c", area_id: "porch" },
      "light.loose": { entity_id: "light.loose" },
    },
    devices: { d1: { area_id: "kitchen" } },
    areas: { kitchen: { name: "Kitchen" }, porch: { name: "Back Porch" }, den: { name: "Den" } },
  } as unknown as HomeAssistant;
  const ids = (f: string) => candidatesIn(hass, undefined, f, "").map((c) => c.entity).sort();

  it("one area, all areas, or no area", () => {
    expect(ids("kitchen")).toEqual(["light.a", "light.b"]); // own area or the device's
    expect(ids(ALL_AREAS)).toEqual(["light.a", "light.b", "light.c", "light.loose"]);
    expect(ids(NO_AREA)).toEqual(["light.loose"]);
  });

  it("choices: All, the areas with something in them by name, No area - with counts", () => {
    expect(areaChoices(hass, undefined).map((o) => o.label)).toEqual(["All areas (4)", "Back Porch (1)", "Kitchen (2)", "No area (1)"]);
    // the current choice stays listed even when empty
    expect(areaChoices(hass, undefined, "den").map((o) => o.value)).toEqual([ALL_AREAS, "porch", "den", "kitchen", NO_AREA]);
  });
});

describe("what Room Tiles' own tiles are made of isn't offered", () => {
  const hass = {
    states: {
      "vacuum.matic": { attributes: { friendly_name: "Matic" } },
      "sensor.room_tiles_matic": { attributes: { friendly_name: "Matic", tile: "docked|Docked||" } },
      "climate.pool_heater": { attributes: { friendly_name: "Pool Heater" } },
      "switch.spa_pump": { attributes: { friendly_name: "Spa" } },
      "switch.garden_lights": { attributes: { friendly_name: "Garden" } },
      "binary_sensor.dryer_door": { attributes: { friendly_name: "Dryer door" } },
    },
    entities: {},
  } as unknown as HomeAssistant;
  const doc = {
    catalog: { entries: [{ entity: "vacuum.matic", kind: "vacuum", short_name: "Matic" }], hidden: [] },
    robots: [{ id: "matic", name: "Matic", vacuum: "vacuum.matic", error: null, preset: "vacuum" }],
    pools: [{ id: "pool", pool: { temp: null, heater: "climate.pool_heater", pump: null }, spa: null, spa_mode: "switch.spa_pump", pump: null }],
    appliances: [{ id: "laundry", name: "Laundry", units: [{ status: "sensor.dryer_status", time: null, door: "binary_sensor.dryer_door" }] }],
  } as unknown as RoomTilesDoc;

  it("their sources are left out - even a catalogued one; our sensor and everything else stay", () => {
    const ids = candidatesIn(hass, doc, ALL_AREAS, "").map((c) => c.entity).sort();
    expect(ids).toEqual(["sensor.room_tiles_matic", "switch.garden_lights"]);
  });
});

describe("found and ignored devices' entities aren't offered either", () => {
  const hass = {
    states: {
      "vacuum.roomba": { attributes: { friendly_name: "Roomba" } },
      "climate.hot_tub": { attributes: { friendly_name: "Hot tub" } },
      "switch.lamp": { attributes: { friendly_name: "Lamp" } },
    },
    entities: {},
  } as unknown as HomeAssistant;
  const doc = {
    catalog: { entries: [], hidden: [] },
    robot_found: [{ id: "roomba", name: "Roomba", vacuum: "vacuum.roomba", error: null, preset: "vacuum", notes: [], clean_area: false }],
    ignored_found: { appliances: [], robots: [], pools: [{ id: "tub", pool: null, spa: { temp: null, heater: "climate.hot_tub", pump: null }, spa_mode: null, pump: null, notes: [] }] },
  } as unknown as RoomTilesDoc;

  it("waiting to be set up, or ignored: left out", () => {
    expect(candidatesIn(hass, doc, ALL_AREAS, "").map((c) => c.entity)).toEqual(["switch.lamp"]);
  });
});

describe("what can be a tile (and so a marker)", () => {
  const hass = {
    states: {
      "light.lamp": { attributes: {} },
      "light.living_lights": { attributes: { entity_id: ["light.lamp"] } },
      "scene.move_night": { attributes: { entity_id: ["light.lamp"] } },
      "script.bedtime": { attributes: {} },
      "script.say_this": { attributes: {} },
      "group.downstairs": { attributes: { entity_id: ["light.living_lights"] } },
      "sensor.room_tiles_laundry": { attributes: { tile: "x" } },
      "sensor.temperature": { attributes: {} },
    },
    entities: {},
    // a script that asks for inputs can't run from one tap
    services: { script: { bedtime: { fields: {} }, say_this: { fields: { message: { required: true } } } } },
  } as unknown as HomeAssistant;
  const doc = { catalog: { entries: [{ entity: "scene.move_night", kind: "switch", short_name: "Night" }], hidden: [] } } as unknown as RoomTilesDoc;

  it("tile domains, scenes, scripts (not ones that need inputs) and tile sensors yes; plain groups, other sensors no", () => {
    const yes = Object.keys(hass.states).filter((id) => canBeTile(hass, doc, id));
    expect(yes).toEqual(["light.lamp", "light.living_lights", "scene.move_night", "script.bedtime", "sensor.room_tiles_laundry"]);
  });
});

describe("Room Tiles' own entities", () => {
  const hass = {
    states: {
      "light.room_tiles_kitchen_area_lights": { attributes: { friendly_name: "Kitchen Area Lights (Room Tiles)", entity_id: ["light.a"] } },
      "sensor.room_tiles_laundry": { attributes: { friendly_name: "Laundry", tile: "x" } },
    },
    entities: {
      "light.room_tiles_kitchen_area_lights": { entity_id: "light.room_tiles_kitchen_area_lights", platform: "room_tiles", hidden: true },
      "sensor.room_tiles_laundry": { entity_id: "sensor.room_tiles_laundry", platform: "room_tiles", hidden: true },
    },
  } as unknown as HomeAssistant;
  const doc = { catalog: { entries: [], hidden: [] } } as unknown as RoomTilesDoc;

  it("hidden in HA but usable here; an area's lights only on the map, never a tile", () => {
    expect(canBeTile(hass, doc, "sensor.room_tiles_laundry")).toBe(true);
    expect(canBeTile(hass, doc, "light.room_tiles_kitchen_area_lights")).toBe(false);
    expect(canBeTile(hass, doc, "light.room_tiles_kitchen_area_lights", undefined, true)).toBe(true);
  });
});

describe("an appliance's own controls", () => {
  const hass = {
    states: {
      "switch.dw_sabbath_mode": { attributes: { friendly_name: "Sabbath mode" } },
      "sensor.room_tiles_dishwasher": { attributes: { friendly_name: "Dishwasher", tile: "x" } },
      "switch.lamp": { attributes: { friendly_name: "Lamp" } },
      "light.dw_light": { attributes: { friendly_name: "Dishwasher light" } },
      "switch.robot_dnd": { attributes: { friendly_name: "Robot do not disturb" } },
      "vacuum.robot": { attributes: { friendly_name: "Robot" } },
      "switch.pool_pump": { attributes: { friendly_name: "Pool pump" } },
      "climate.pool_heater": { attributes: { friendly_name: "Pool heater" } },
    },
    entities: {
      "light.dw_light": { entity_id: "light.dw_light", device_id: "dw" },
      "vacuum.robot": { entity_id: "vacuum.robot", device_id: "rb" },
      "switch.robot_dnd": { entity_id: "switch.robot_dnd", device_id: "rb" },
      "switch.pool_pump": { entity_id: "switch.pool_pump", device_id: "pool" },
      "climate.pool_heater": { entity_id: "climate.pool_heater", device_id: "pool" },
      "sensor.dw_state": { entity_id: "sensor.dw_state", device_id: "dw" },
      "switch.dw_sabbath_mode": { entity_id: "switch.dw_sabbath_mode", device_id: "dw" },
      "sensor.room_tiles_dishwasher": { entity_id: "sensor.room_tiles_dishwasher", device_id: "dw", platform: "room_tiles" },
      "switch.lamp": { entity_id: "switch.lamp", device_id: "lamp" },
    },
  } as unknown as HomeAssistant;
  const ap = { id: "dw", name: "Dishwasher", units: [{ status: "sensor.dw_state", time: null }] };
  const robot = { id: "rb", vacuum: "vacuum.robot", error: null };
  const pool = { id: "pool", pool: { temp: null, heater: "climate.pool_heater", pump: null }, spa: null, spa_mode: null, pump: null };
  for (const [what, doc] of [
    ["set up", { appliances: [ap], robots: [robot], pools: [pool] }],
    ["waiting to be set up", { appliance_found: [ap], robot_found: [robot], pool_found: [pool] }],
    ["ignored", { ignored_found: { appliances: [ap], robots: [robot], pools: [pool] } }],
  ] as const)
    it(`${what}: an appliance's / vacuum's own switches aren't offered (their tile is); lights and a pool's controls are`, () => {
      const d = { catalog: { entries: [], hidden: [] }, ...doc } as unknown as RoomTilesDoc;
      expect(candidatesIn(hass, d, ALL_AREAS, "", true).map((c) => c.entity)).toEqual([
        "sensor.room_tiles_dishwasher",
        "light.dw_light",
        "switch.lamp",
        "switch.pool_pump",
      ]);
    });
});

describe("fullName", () => {
  it("Room Tiles' own entities by the name Room Tiles gave them, never HA's composed one", () => {
    const hass = {
      states: {
        "sensor.room_tiles_dishwasher": { attributes: { friendly_name: "Fisher & Paykel Dual Dish Washer Dishwasher", own_name: "Dishwasher" } },
        "switch.lamp": { attributes: { friendly_name: "Desk Lamp" } },
      },
      entities: {
        "sensor.room_tiles_dishwasher": { entity_id: "sensor.room_tiles_dishwasher", platform: "room_tiles" },
        "switch.lamp": { entity_id: "switch.lamp", platform: "tplink" },
      },
    } as unknown as HomeAssistant;
    expect(fullName(hass, "sensor.room_tiles_dishwasher")).toBe("Dishwasher");
    expect(fullName(hass, "switch.lamp")).toBe("Desk Lamp");
    expect(fullName(hass, "switch.gone")).toBe("switch.gone");
  });
});
