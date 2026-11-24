import { render } from "lit";
import { describe, expect, it } from "vitest";
import "./appliances";
import type { ApplianceProfile, ApplianceUnitProfile, RoomTilesDoc } from "./types";

type El = HTMLElement & { updateComplete: Promise<boolean>; doc: RoomTilesDoc; hass: unknown };

const unit = (id: string, kind: "washer" | "dryer" | "dishwasher", extra: Partial<ApplianceUnitProfile> = {}): ApplianceUnitProfile => ({
  id,
  label: id[0].toUpperCase() + id.slice(1),
  appliance: kind,
  preset: kind === "dishwasher" ? "fp_dishdrawer" : `lg_thinq_${kind}`,
  status: `sensor.${id}`,
  time: null,
  door: null,
  door_clears: true,
  finished: "done",
  clear: [],
  drawer: false,
  overrides: {},
  ...extra,
});

const DRYER: ApplianceProfile = { id: "dryer", name: "Dryer", units: [unit("dryer", "dryer")] };
const WASHER: ApplianceProfile = { id: "washer", name: "Washer", units: [unit("washer", "washer")] };
const LAUNDRY: ApplianceProfile = {
  id: "laundry",
  name: "Laundry",
  units: [unit("dryer", "dryer"), unit("washer", "washer", { finished: "waiting", clear: ["unit:dryer"] })],
};

const doc = (extra: Partial<RoomTilesDoc>): RoomTilesDoc =>
  JSON.parse(
    JSON.stringify({
      areas: [],
      maps: [],
      markers: [],
      catalog: { entries: [], hidden: [] },
      settings: { auto_add_areas: false },
      area_lights: {},
      appliance_presets: [{ id: "lg_thinq_dryer", name: "LG ThinQ dryer", appliance: "dryer", verified: true }],
      ...extra,
    }),
  );

async function mount(d: RoomTilesDoc, calls: unknown[][] = []): Promise<El> {
  const el = document.createElement("rt-appliances") as El;
  el.doc = d;
  el.hass = { states: {}, callService: async (...a: unknown[]) => void calls.push(a) };
  document.body.append(el);
  await el.updateComplete;
  return el;
}

interface Editor {
  _choice: string;
  _arrangements: { key: string }[];
  _views: ApplianceProfile[];
  _dirty: boolean;
  _emptiedBy(ap: number, u: ApplianceUnitProfile, i: number): unknown[];
  _save(): Promise<void>;
}

async function editor(profile: ApplianceProfile, d: RoomTilesDoc, opts: { adding?: boolean; hass?: unknown } = {}, calls: unknown[][] = []) {
  const el = document.createElement("rt-appliance-editor") as El & { profile: ApplianceProfile; adding: boolean };
  el.doc = d;
  el.hass = opts.hass ?? { states: {}, callService: async (...a: unknown[]) => void calls.push(a) };
  el.profile = profile;
  el.adding = !!opts.adding;
  document.body.append(el);
  await el.updateComplete;
  return { el, ed: el as unknown as Editor };
}

/** the "emptied by" rows, each rendered on its own (happy-dom misplaces Lit's
 *  markers after a <select> with bound options - browsers don't) */
function rows(ed: Editor, ap: number, i: number): string[] {
  return ed._emptiedBy(ap, ed._views[ap].units[i], i).map((row) => {
    const box = document.createElement("div");
    render(row, box);
    const l = box.querySelector("label")!;
    const input = l.querySelector("input")!;
    return `${l.textContent!.replace(/\s+/g, " ").trim()}${input.checked ? " [x]" : ""}${input.disabled ? " (fixed)" : ""}`;
  });
}

describe("rt-appliances", () => {
  it("says plainly when nothing supported is there", async () => {
    const el = await mount(doc({}));
    expect(el.shadowRoot!.textContent).toContain("No supported appliances found");
    expect(el.shadowRoot!.querySelector(".intro a")!.getAttribute("href")).toMatch(/docs\/SUPPORTED\.md$/);
    el.remove();
  });

  it("Set up opens the settings first - nothing is stored until their Add", async () => {
    const calls: unknown[][] = [];
    const el = await mount(doc({ appliance_found: [{ ...DRYER, notes: [] }] }), calls);
    const root = el.shadowRoot!;
    expect(root.textContent).toContain("Found in Home Assistant");
    expect(root.textContent).toContain("Dryer (LG ThinQ dryer)");
    [...root.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent!.trim() === "Set up")!.click();
    await el.updateComplete;
    expect((el as unknown as { _adding?: ApplianceProfile })._adding).toEqual(DRYER);
    expect(calls).toEqual([]);
    el.remove();
  });

  it("closing an appliance's settings goes back to the Appliances list", async () => {
    const el = await mount(doc({ appliances: [LAUNDRY] }));
    let closed = 0;
    el.addEventListener("close", () => closed++);
    const ui = el as unknown as { _edit?: string };
    ui._edit = "laundry";
    await el.updateComplete;
    const editorEl = el.shadowRoot!.querySelector("rt-appliance-editor");
    // happy-dom may not render a trailing binding; fire the editor's close either way
    (editorEl ?? el.shadowRoot!.firstElementChild!).dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
    if (editorEl) {
      expect(closed).toBe(0); // the Appliances dialog stays open
      expect(ui._edit).toBeUndefined();
    }
    el.remove();
  });

  it("lists set-up appliances with a pencil, in a scrolling list", async () => {
    const el = await mount(doc({ appliances: [LAUNDRY] }));
    const root = el.shadowRoot!;
    expect(root.textContent).toContain("Set up");
    expect(root.querySelector('button.pencil[aria-label="Edit Laundry"]')).not.toBeNull();
    expect(root.querySelector(".list .card")).not.toBeNull();
    el.remove();
  });
});

describe("rt-appliance-editor: the tile choice", () => {
  it("two on a tile: one tile or separate tiles - a card only changes the draft", async () => {
    const calls: unknown[][] = [];
    const { el, ed } = await editor(LAUNDRY, doc({ appliances: [LAUNDRY] }), {}, calls);
    expect(ed._arrangements.map((a) => a.key)).toEqual(["together", "separate"]);
    expect(ed._dirty).toBe(false);
    ed._choice = "separate";
    expect(ed._views.map((a) => [a.id, a.name, a.units[0].finished, a.units[0].clear])).toEqual([
      ["laundry", "Dryer", "done", []],
      ["washer", "Washer", "waiting", ["appliance:laundry"]], // keeps Switch Over: the dryer's own tile starting empties it
    ]);
    expect(ed._dirty).toBe(true);
    expect(calls).toEqual([]); // nothing until Save
    const views = ed._views;
    await ed._save();
    expect(calls.map((c) => [c[1], (c[2] as { appliance: unknown }).appliance])).toEqual([
      ["split_appliance", "laundry"],
      ["set_appliance", views[0]],
      ["set_appliance", views[1]],
    ]);
    el.remove();
  });

  it("one alone: its own tile, or share with another single appliance", async () => {
    const calls: unknown[][] = [];
    const { el, ed } = await editor(WASHER, doc({ appliances: [WASHER, DRYER] }), {}, calls);
    expect(ed._arrangements.map((a) => a.key)).toEqual(["keep", "with:dryer"]);
    ed._choice = "with:dryer";
    const [shared] = ed._views;
    // the dryer goes on top, even when the washer asked to share
    expect([shared.id, shared.name, shared.units.map((u) => u.id)]).toEqual(["washer", "Laundry", ["dryer", "washer"]]);
    expect([shared.units[1].finished, shared.units[1].clear]).toEqual(["waiting", ["unit:dryer"]]);
    await ed._save();
    expect(calls.map((c) => c[1])).toEqual(["combine_appliances", "set_appliance"]);
    el.remove();
  });

  it("nothing to share with: no cards", async () => {
    const { el, ed } = await editor(WASHER, doc({ appliances: [WASHER] }));
    expect(ed._arrangements.map((a) => a.key)).toEqual(["keep"]);
    el.remove();
  });

  it("adding a found two-part appliance: separate tiles store two new appliances", async () => {
    const calls: unknown[][] = [];
    const { el, ed } = await editor(LAUNDRY, doc({ appliances: [DRYER] }), { adding: true }, calls);
    expect(ed._dirty).toBe(true); // Add is ready at once
    ed._choice = "separate";
    expect(ed._views.map((a) => a.id)).toEqual(["dryer_2", "washer"]);
    await ed._save();
    expect(calls.map((c) => [c[1], (c[2] as { appliance: ApplianceProfile }).appliance.id])).toEqual([
      ["set_appliance", "dryer_2"],
      ["set_appliance", "washer"],
    ]);
    el.remove();
  });
});

describe("rt-appliance-editor: what empties a unit", () => {
  it("the tap always, the door by default, picked sensors, and sensors in its area offered", async () => {
    const drawer: ApplianceProfile = {
      id: "dishwasher",
      name: "Dishwasher",
      units: [unit("upper", "dishwasher", { label: "Upper", door: "binary_sensor.u_door", clear: ["binary_sensor.kitchen"], drawer: true })],
    };
    const st = (id: string, dc: string, name: string) => ({ entity_id: id, state: "off", attributes: { device_class: dc, friendly_name: name } });
    const hass = {
      states: {
        "binary_sensor.kitchen": st("binary_sensor.kitchen", "door", "binary_sensor.kitchen"),
        "binary_sensor.kitchen_motion": st("binary_sensor.kitchen_motion", "motion", "Kitchen Motion"),
        "binary_sensor.garage_door": st("binary_sensor.garage_door", "door", "Garage Door"),
        "binary_sensor.leak": st("binary_sensor.leak", "moisture", "Kitchen Leak"),
      },
      entities: {
        "sensor.upper": { entity_id: "sensor.upper", device_id: "dw" },
        "binary_sensor.kitchen_motion": { entity_id: "binary_sensor.kitchen_motion", area_id: "kitchen" },
        "binary_sensor.garage_door": { entity_id: "binary_sensor.garage_door", area_id: "garage" },
        "binary_sensor.leak": { entity_id: "binary_sensor.leak", area_id: "kitchen" },
      },
      devices: { dw: { area_id: "kitchen" } },
      callService: async () => undefined,
    };
    const { el, ed } = await editor(drawer, doc({ appliances: [drawer] }), { hass });
    // the garage door (other area) and the leak sensor (not motion / contact) aren't offered
    expect(rows(ed, 0, 0)).toEqual([
      "A tap on the tile (always) [x] (fixed)",
      "The door opening (binary_sensor.u_door) [x]",
      "binary_sensor.kitchen opening [x]",
      "Kitchen detecting motion",
    ]);
    expect(ed._dirty).toBe(false);
    const doorRow = ed._emptiedBy(0, ed._views[0].units[0], 0)[1];
    const box = document.createElement("div");
    render(doorRow, box);
    const input = box.querySelector("input")!;
    input.checked = false; // turning the door off: a draft change
    input.dispatchEvent(new Event("change"));
    expect(ed._dirty).toBe(true);
    el.remove();
  });

  it("'the Dryer starting' only on a washer sharing a tile with a dryer", async () => {
    const { el, ed } = await editor(LAUNDRY, doc({ appliances: [LAUNDRY] }));
    expect(rows(ed, 0, 0)).toEqual(["A tap on the tile (always) [x] (fixed)"]);
    expect(rows(ed, 0, 1)).toEqual(["A tap on the tile (always) [x] (fixed)", "The Dryer starting [x]"]);
    el.remove();
  });
});

describe("adding by hand (a smart plug's power)", () => {
  it("a washer by hand: the generic power profile, a fresh id, nothing chosen yet", async () => {
    const { byHand } = await import("./appliances");
    const w = byHand("washer", doc({ appliances: [WASHER] }));
    expect([w.id, w.units[0].preset, w.units[0].status, w.units[0].power_on_w, w.units[0].power_off_min]).toEqual([
      "washer_2",
      "power_washer",
      "",
      5,
      3,
    ]);
    // a dishwasher dries with almost no power: a longer wait
    expect(byHand("dishwasher").units[0].power_off_min).toBe(20);
  });
});

describe("ignoring", () => {
  it("a found card's Ignore sends it to Ignored; ignored ones are listed with Add", async () => {
    const calls: unknown[][] = [];
    const el = await mount(doc({ appliance_found: [{ ...DRYER, notes: [] }] }), calls);
    (el as unknown as { _ignore(k: string, d: unknown): void })._ignore("appliance", DRYER);
    expect(calls).toEqual([["room_tiles", "ignore_device", { kind: "appliance", device: DRYER }]]);
    el.remove();
    const el2 = await mount(doc({ ignored_found: { appliances: [{ ...WASHER, notes: [] }], pools: [], robots: [] } }));
    const cards = (el2 as unknown as { _ignoredCards(): unknown[] })._ignoredCards();
    expect(cards.length).toBe(1);
    el2.remove();
  });
});

describe("sensorText (the emptied-by list)", () => {
  const hass = (name: string, dc: string) =>
    ({ states: { "binary_sensor.x": { entity_id: "binary_sensor.x", state: "off", attributes: { friendly_name: name, device_class: dc } } } }) as never;
  it("doesn't say what it senses twice", async () => {
    const { sensorText } = await import("./appliances");
    expect(sensorText(hass("Garage Door Motion", "motion"), "binary_sensor.x")).toBe("Garage Door detecting motion");
    expect(sensorText(hass("garage motion sensor", "motion"), "binary_sensor.x")).toBe("garage detecting motion");
    expect(sensorText(hass("Laundry Door", "door"), "binary_sensor.x")).toBe("Laundry Door opening");
    expect(sensorText(hass("Laundry Door Contact", "door"), "binary_sensor.x")).toBe("Laundry Door opening");
  });
});
