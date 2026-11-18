import { describe, expect, it } from "vitest";
import "./pools";
import type { PoolProfile, RoomTilesDoc } from "./types";

const SHARED: PoolProfile = {
  id: "pool",
  name: "Pool & Spa",
  preset: "iaqualink",
  layout: "shared",
  pool: { temp: "sensor.pool_temp", heater: "climate.pool", pump: null, pump_with_heater: true },
  spa: { temp: "sensor.spa_temp", heater: "climate.spa", pump: null, pump_with_heater: true },
  spa_mode: "switch.spa_pump",
  pump: "switch.pool_pump",
  spa_heater_follows: true,
};

interface Ed {
  _layout(l: string): void;
  _view: PoolProfile;
  _missing: string;
  _dirty: boolean;
  _payload(): PoolProfile;
  _save(): Promise<void>;
  _change(fn: (p: PoolProfile) => void): void;
}

async function editor(profile: PoolProfile, adding = false, calls: unknown[][] = []) {
  const el = document.createElement("rt-pool-editor") as HTMLElement & {
    updateComplete: Promise<boolean>;
    hass: unknown;
    doc: RoomTilesDoc;
    profile: PoolProfile;
    adding: boolean;
  };
  el.hass = { states: {}, callService: async (...a: unknown[]) => void calls.push(a) };
  el.doc = { areas: [], maps: [], markers: [], catalog: { entries: [], hidden: [] }, settings: { auto_add_areas: false }, area_lights: {} };
  el.profile = JSON.parse(JSON.stringify(profile));
  el.adding = adding;
  document.body.append(el);
  await el.updateComplete;
  return { el, ed: el as unknown as Ed };
}

describe("rt-pool-editor", () => {
  it("adding: ready at once, stores the shared system as found", async () => {
    const calls: unknown[][] = [];
    const { el, ed } = await editor(SHARED, true, calls);
    expect([ed._dirty, ed._missing]).toEqual([true, ""]);
    await ed._save();
    expect(calls.map((c) => c.slice(0, 3))).toEqual([["room_tiles", "set_pool", { pool: SHARED }]]);
    el.remove();
  });

  it("a layout card only changes the draft; the payload keeps just that layout's fields", async () => {
    const calls: unknown[][] = [];
    const { el, ed } = await editor(SHARED, false, calls);
    expect(ed._dirty).toBe(false);
    ed._layout("pool");
    expect(ed._dirty).toBe(true);
    expect(calls).toEqual([]);
    const p = ed._payload();
    expect([p.layout, p.spa, p.spa_mode, p.pump, p.pool?.temp]).toEqual(["pool", null, null, null, "sensor.pool_temp"]);
    // back to shared: the spa's fields come back
    ed._layout("shared");
    expect(ed._view.spa?.temp).toBe("sensor.spa_temp");
    el.remove();
  });

  it("says what's missing before it can be saved", async () => {
    const { el, ed } = await editor(SHARED);
    ed._change((p) => (p.spa_mode = null));
    expect(ed._missing).toBe("Choose the switch that puts it in spa mode.");
    ed._change((p) => (p.spa_mode = "switch.spa_pump"));
    ed._change((p) => (p.spa!.temp = null));
    expect(ed._missing).toBe(""); // its heater reads it
    ed._change((p) => (p.spa!.heater = null));
    expect(ed._missing).toBe("Choose the spa's water temperature sensor (or a heater that reads it).");
    el.remove();
  });
});
