import { describe, expect, it } from "vitest";
import {
  applianceIcon,
  climateBand,
  climateTone,
  rollerCall,
  rollerRow,
  rollerSpec,
  switchCall,
  switchTrack,
  tileIcon,
  vacuumIcon,
} from "./rules";
import type { HomeAssistant } from "./types";

const hass = (manufacturer: string | null) =>
  ({
    states: {},
    entities: { "vacuum.robot": { entity_id: "vacuum.robot", device_id: "d1" } },
    devices: { d1: { manufacturer } },
  }) as unknown as HomeAssistant;

describe("vacuum icon", () => {
  it("Matic's own icon only for Matic robots; every other brand (or none known) the generic robot", () => {
    expect(vacuumIcon(hass("Matic Robots, Inc"), "vacuum.robot")).toBe("icon_matic");
    expect(vacuumIcon(hass("Roborock"), "vacuum.robot")).toBe("icon_robot_vacuum");
    expect(vacuumIcon(hass("Automatic Co"), "vacuum.robot")).toBe("icon_robot_vacuum");
    expect(vacuumIcon(hass(null), "vacuum.robot")).toBe("icon_robot_vacuum");
    expect(vacuumIcon(undefined, "vacuum.other")).toBe("icon_robot_vacuum");
    expect(tileIcon("vacuum", "vacuum.robot", hass("Matic Robots, Inc"))).toBe("icon_matic");
    expect(tileIcon("vacuum")).toBe("icon_robot_vacuum");
    // a tile sensor naming its vacuum
    const h = hass("Matic Robots, Inc") as unknown as { states: Record<string, unknown> };
    h.states["sensor.matic_tile"] = { entity_id: "sensor.matic_tile", state: "docked", attributes: { vacuum: "vacuum.robot" } };
    expect(vacuumIcon(h as unknown as HomeAssistant, "sensor.matic_tile")).toBe("icon_matic");
  });
});


describe("water tiles (Room Tiles pool / spa sensors)", () => {
  const st = (attrs: Record<string, unknown>, state = "idle") => ({ entity_id: "sensor.x", state, attributes: attrs });
  it("the Spa tile's switch = spa on (its heater per its setting); Pool and combined = the pool / pump, never a heater", async () => {
    const { switchCall, switchOn, rollerCall } = await import("./rules");
    const spa = st({ pool: "pool", body: "spa", active: false, has_heater: true, can_turn_on: true, tile: "Spa|96|Off|standby|100|off" }, "standby");
    expect(switchOn("water", spa)).toBe(false);
    expect(switchCall("water", "sensor.room_tiles_pool_spa", true, spa)).toEqual({
      domain: "room_tiles",
      service: "pool_set_on",
      data: { entity: "sensor.room_tiles_pool_spa", on: true },
    });
    // the pool heating: its switch shows the POOL (pump) on, and turns the pump off - not the heater
    const pool = st({ pool: "pool", body: "pool", active: true, has_heater: true, can_turn_on: true, tile: "Pool|79|Heating|heating|85|on" }, "heating");
    expect(switchOn("water", pool)).toBe(true);
    expect(switchCall("water", "sensor.room_tiles_pool_pool", false, pool)?.service).toBe("pool_set_on");
    // pump off with the heater on: the switch shows off (the pump), not the heater
    const waiting = st({ pool: "pool", body: "pool", active: true, has_heater: true, can_turn_on: true, tile: "Pool|79|Waiting for pump|pump_off|85|on" }, "pump_off");
    expect(switchOn("water", waiting)).toBe(false);
    // the combined tile: the active body on / off, never a heater
    const both = st({ pool: "pool", body: "spa", mode: "spa", active: true, has_heater: true, can_turn_on: true, tile: "Spa|99|Idle|idle|100|off" });
    expect(switchCall("water", "sensor.room_tiles_pool", false, both)?.service).toBe("pool_set_on");
    expect(rollerCall("water", "sensor.room_tiles_pool", 4)).toEqual({
      domain: "room_tiles",
      service: "pool_set_target",
      data: { entity: "sensor.room_tiles_pool", temperature: 100 },
    });
    // a hand-made tile sensor stays read-only
    expect(switchCall("water", "sensor.pool_spa_tile", true, st({ tile: "Pool|79|x|idle|85|off" }))).toBeUndefined();
  });

  it("bodies without a heater or a pump: the tile offers only what's there", async () => {
    const { switchCall, switchTrack, rollerSpec, waterSwitch } = await import("./rules");
    // a pool with a heater but no pump to switch: no switch at all (never the heater)
    const heaterOnly = st({ pool: "p", body: "pool", active: true, has_heater: true, can_turn_on: false, tile: "Pool|80|Idle|idle|85|on" }, "idle");
    expect(waterSwitch(heaterOnly)).toBeUndefined();
    expect(rollerSpec("water", heaterOnly)).toBeDefined(); // the target can still be set
    // a pool with a pump, no heater: switch = the pump, no roller
    const pumpOnly = st({ pool: "p", body: "pool", active: true, has_heater: false, can_turn_on: true, tile: "Pool|78|Pump on|on||off" }, "on");
    expect(waterSwitch(pumpOnly)).toBe("body");
    expect(switchCall("water", "sensor.p", false, pumpOnly)?.service).toBe("pool_set_on");
    expect(rollerSpec("water", pumpOnly)).toBeUndefined();
    // neither: no switch, no roller - just the temperature
    const bare = st({ pool: "p", body: "pool", active: true, has_heater: false, can_turn_on: false, tile: "Pool|78||on||off" }, "on");
    expect(waterSwitch(bare)).toBeUndefined();
    expect(switchTrack("water", bare)).toBeUndefined();
    expect(switchCall("water", "sensor.p", true, bare)).toBeUndefined();
    // a spa with a heater, no pump: its switch falls back to the heater
    const spaHeater = st({ pool: "p", body: "spa", active: true, has_heater: true, can_turn_on: false, tile: "Spa|101|Idle|idle|102|on" }, "idle");
    expect(switchCall("water", "sensor.s", false, spaHeater)?.service).toBe("pool_set_heater");
    expect(rollerSpec("water", spaHeater)).toBeDefined();
  });

  it("details open the body's heater (the sensor has no controls)", async () => {
    const { detailsEntity } = await import("./rules");
    expect(detailsEntity("water", "sensor.room_tiles_pool_spa", st({ pool: "p", heater_entity: "climate.spa" }))).toBe("climate.spa");
    expect(detailsEntity("water", "sensor.room_tiles_p_pool", st({ pool: "p", heater_entity: null }))).toBe("sensor.room_tiles_p_pool");
    expect(detailsEntity("switch", "switch.x", undefined)).toBe("switch.x");
  });

  it("vacuum tiles: the status line from the tile text, details open the vacuum", async () => {
    const { vacuumStatus, detailsEntity } = await import("./rules");
    const rb = st({ robot: "matic", vacuum: "vacuum.matic", tile: "attention|Refill water tank||" }, "attention");
    expect(vacuumStatus(rb)).toEqual({ text: "Refill water tank", cls: "attention" });
    expect(detailsEntity("vacuum", "sensor.room_tiles_matic", rb)).toBe("vacuum.matic");
    expect(detailsEntity("vacuum", "vacuum.roomba", st({}, "docked"))).toBe("vacuum.roomba");
    expect(vacuumStatus(st({}, "docked"))).toEqual({ text: "docked", cls: "docked" });
  });
});


describe("entry covers", () => {
  const h = {
    states: {
      "cover.garage": { attributes: { device_class: "garage" } },
      "cover.gate": { attributes: { device_class: "gate" } },
      "cover.blind": { attributes: { device_class: "blind" } },
      "cover.plain": { attributes: {} },
    },
  } as unknown as HomeAssistant;

  it("garage doors, gates and doors share the garage icon; blinds keep theirs", () => {
    expect(tileIcon("cover", "cover.garage", h)).toBe("icon_garage");
    expect(tileIcon("cover", "cover.gate", h)).toBe("icon_garage");
    expect(tileIcon("cover", "cover.blind", h)).toBe("icon_blind");
    expect(tileIcon("cover", "cover.plain", h)).toBe("icon_blind");
  });
});

describe("cover roller", () => {
  it("only for covers that can be set to a position (HA feature bit 4)", () => {
    const cover = (features: number) => ({ entity_id: "cover.x", state: "closed", attributes: { supported_features: features } }) as never;
    expect(rollerSpec("cover", cover(1 | 2 | 4))).toBeDefined(); // open, close, set position
    expect(rollerSpec("cover", cover(1 | 2))).toBeUndefined(); // open / close only: no roller
    expect(switchTrack("cover", cover(1 | 2))).toBeDefined(); // ...the open / close switch stays
  });
});

describe("thermostat in auto (heat / cool)", () => {
  it("no roller (it has two targets) - the switch stays; heat / cool keep theirs", () => {
    const st = (attributes: Record<string, unknown>, state = "heat_cool") => ({ entity_id: "climate.x", state, attributes }) as never;
    expect(rollerSpec("climate", st({ target_temp_low: 68, target_temp_high: 76 }))?.prefix).toBe("Auto");
    expect(switchTrack("climate", st({ target_temp_low: 68, target_temp_high: 76 }))).toBeDefined();
    expect(rollerSpec("climate", st({ temperature: 72 }, "heat"))).toBeDefined();
    expect(rollerSpec("climate", st({ temperature: 72 }, "cool"))?.prefix).toBe("Cool");
  });
});

describe("thermostat: colour by mode, auto's band", () => {
  const st = (state: string, attributes: Record<string, unknown> = {}) => ({ entity_id: "climate.x", state, attributes }) as never;
  it("the colour follows the mode; auto by what it's doing", () => {
    expect(climateTone(st("heat", { hvac_action: "idle" }))).toBe("heat");
    expect(climateTone(st("cool", { hvac_action: "idle" }))).toBe("cool");
    expect(climateTone(st("heat_cool", { hvac_action: "heating" }))).toBe("heat");
    expect(climateTone(st("heat_cool", { hvac_action: "cooling" }))).toBe("cool");
    expect(climateTone(st("heat_cool", { hvac_action: "idle" }))).toBe("neutral");
    expect(switchTrack("climate", st("heat_cool", { hvac_action: "idle", target_temp_low: 68, target_temp_high: 74 }))?.on).toBe("track_switch_on_slate");
  });
  it("the roller is the band's middle; moving it keeps the width, within the limits", () => {
    const auto = st("heat_cool", { target_temp_low: 68, target_temp_high: 74, min_temp: 50, max_temp: 90 });
    expect(rollerRow("climate", auto)).toBe(rollerRow("climate", st("heat", { temperature: 71 })));
    expect(climateBand(auto, 75)).toEqual({ low: 72, high: 78 });
    expect(climateBand(auto, 89)).toEqual({ low: 84, high: 90 }); // stops at max_temp, width kept
    const call = rollerCall("climate", "climate.x", rollerRow("climate", st("heat", { temperature: 73 })), auto);
    expect(call?.data).toEqual({ entity_id: "climate.x", target_temp_low: 70, target_temp_high: 76 });
  });
});

describe("switch tiles", () => {
  it("a switch uses switch.*, a helper (input_boolean) its own actions", () => {
    expect(switchCall("switch", "switch.lamp", false)).toEqual({ domain: "switch", service: "turn_off", data: { entity_id: "switch.lamp" } });
    expect(switchCall("switch", "input_boolean.guest_mode", false)).toEqual({
      domain: "input_boolean",
      service: "turn_off",
      data: { entity_id: "input_boolean.guest_mode" },
    });
  });
});

describe("applianceIcon", () => {
  const hass = (units: unknown) =>
    ({ states: { "sensor.a": { entity_id: "sensor.a", state: "idle", attributes: { units } } } }) as unknown as HomeAssistant;
  it("is the laundry with a washer or dryer, else the dishwasher", () => {
    expect(applianceIcon(hass([{ appliance: "washer" }, { appliance: "dryer" }]), "sensor.a")).toBe("icon_laundry");
    expect(applianceIcon(hass([{ appliance: "dryer" }]), "sensor.a")).toBe("icon_laundry");
    expect(applianceIcon(hass([{ appliance: "dishwasher" }]), "sensor.a")).toBe("icon_dishwasher");
    expect(applianceIcon(hass(undefined), "sensor.a")).toBe("icon_dishwasher");
    expect(applianceIcon(undefined, "sensor.a")).toBe("icon_dishwasher");
  });
});
