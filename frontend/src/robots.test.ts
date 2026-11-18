import { describe, expect, it } from "vitest";
import "./robots";
import type { RobotProfile } from "./types";

describe("rt-robot-editor", () => {
  it("adding stores the robot as found", async () => {
    const calls: unknown[][] = [];
    const matic: RobotProfile = { id: "matic", name: "Matic", vacuum: "vacuum.matic", error: "sensor.matic_operational_error", preset: "matter" };
    const el = document.createElement("rt-robot-editor") as HTMLElement & {
      updateComplete: Promise<boolean>;
      hass: unknown;
      profile: RobotProfile;
      adding: boolean;
    };
    el.hass = { states: { "vacuum.matic": { entity_id: "vacuum.matic", state: "docked", attributes: { supported_features: 29212 } } }, callService: async (...a: unknown[]) => void calls.push(a) };
    el.profile = matic;
    el.adding = true;
    document.body.append(el);
    await el.updateComplete;
    expect(el.shadowRoot!.textContent).toContain("one or more rooms haven't been set up");
    await (el as unknown as { _save(): Promise<void> })._save();
    expect(calls.map((c) => c.slice(0, 3))).toEqual([["room_tiles", "set_robot", { robot: matic }]]);
    el.remove();
  });

  it("asks the panel when the area's board was changed by the user", async () => {
    const matic: RobotProfile = { id: "matic", name: "Matic", vacuum: "vacuum.matic", error: null, preset: "matter" };
    const el = document.createElement("rt-robot-editor") as HTMLElement & { updateComplete: Promise<boolean>; hass: unknown; profile: RobotProfile; adding: boolean };
    el.hass = { states: {}, callService: async () => ({ response: { entity: "sensor.room_tiles_matic", ask: ["office"] } }) };
    el.profile = matic;
    el.adding = true;
    const asked: unknown[] = [];
    document.body.addEventListener("tiles-ask", (e) => asked.push((e as CustomEvent).detail), { once: true });
    document.body.append(el);
    await el.updateComplete;
    await (el as unknown as { _save(): Promise<void> })._save();
    expect(asked).toEqual([{ areas: ["office"], name: "Matic" }]);
    el.remove();
  });
});
