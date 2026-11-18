import { describe, expect, it } from "vitest";
import "./area-settings";
import "./controls";
import type { RtAreaSettings } from "./area-settings";

const doc = {
  areas: [
    { id: "kitchen", name: "Kitchen", floor: null, short_name: "Kitchen", review: false, hidden: false, lights: null, lights_exclude: [], tiles: { "5x2": [], "6x3": [] } },
  ],
  maps: [],
  markers: [],
  catalog: { entries: [], hidden: [] },
  settings: { auto_add_areas: false },
  area_lights: {},
};

const calls: unknown[] = [];
const hass = {
  states: {},
  callService: async (...args: unknown[]) => void calls.push(args),
  connection: { subscribeMessage: async () => async () => {} },
};

async function mount(): Promise<RtAreaSettings> {
  const el = document.createElement("rt-area-settings") as RtAreaSettings;
  (el as any).hass = hass;
  (el as any).doc = JSON.parse(JSON.stringify(doc)); // each test its own copy
  document.body.appendChild(el);
  await el.updateComplete;
  return el;
}

/** click an <rt-switch> (the panels' switch art) like a user would */
async function flip(sw: Element): Promise<void> {
  await (sw as any).updateComplete;
  (sw as HTMLElement).shadowRoot!.querySelector<HTMLButtonElement>("button")!.click();
}

const save = (el: HTMLElement) =>
  [...el.shadowRoot!.querySelectorAll<HTMLButtonElement>(".footer button")].find((b) => b.textContent?.includes("Save"))!;

describe("rt-area-settings", () => {
  it("enables Save changes after ticking 'include new areas automatically'", async () => {
    const el = await mount();
    expect(save(el).disabled).toBe(true);
    const sw = el.shadowRoot!.querySelector(".setting rt-switch")!;
    await flip(sw); // the user's tap
    await el.updateComplete;
    expect((sw as any).checked).toBe(true);
    expect(save(el).disabled).toBe(false);
  });

  it("enables Save changes after hiding an area", async () => {
    const el = await mount();
    await flip(el.shadowRoot!.querySelector(".show rt-switch")!);
    await el.updateComplete;
    expect(save(el).disabled).toBe(false);
  });

  it("X closes at once without changes, asks with changes; Cancel never asks", async () => {
    let closed = 0;
    const el = await mount();
    el.addEventListener("close", () => closed++);
    const x = () => el.shadowRoot!.querySelector<HTMLButtonElement>("button.x")!;
    x().click();
    await el.updateComplete;
    expect(closed).toBe(1);
    expect((el as any)._ask).toBe(false);

    await flip(el.shadowRoot!.querySelector(".setting rt-switch")!);
    await el.updateComplete;
    expect(save(el).disabled).toBe(false);
    x().click();
    await el.updateComplete;
    expect(closed).toBe(1); // not closed: asked instead
    // (happy-dom doesn't render a binding at a template's top level, so the
    // prompt itself is checked through the state that shows it)
    expect((el as any)._ask).toBe(true);

    [...el.shadowRoot!.querySelectorAll<HTMLButtonElement>(".footer button")].find((b) => b.textContent?.includes("Cancel"))!.click();
    expect(closed).toBe(2); // Cancel: discards without asking
  });
});

describe("Sort A-Z", () => {
  it("orders the areas by name as a draft; Save sends every position", async () => {
    const el = document.createElement("rt-area-settings") as RtAreaSettings;
    const area = (id: string, name: string) => ({ ...doc.areas[0], id, name, short_name: name });
    (el as any).hass = hass;
    (el as any).doc = { ...JSON.parse(JSON.stringify(doc)), areas: [area("p", "Patio"), area("b", "bedroom"), area("k", "Kitchen")] };
    document.body.appendChild(el);
    await el.updateComplete;
    const sort = el.shadowRoot!.querySelector<HTMLButtonElement>(".sort")!;
    expect(sort.disabled).toBe(false);
    sort.click();
    await el.updateComplete;
    expect([...el.shadowRoot!.querySelectorAll(".area .full")].map((x) => x.textContent)).toEqual(["bedroom", "Kitchen", "Patio"]);
    expect(sort.disabled).toBe(true); // already in order
    calls.length = 0;
    save(el).click();
    await new Promise((r) => setTimeout(r, 0));
    expect(calls.map((c) => (c as [string, string, { area: string; position: number }])[2])).toEqual([
      { area: "b", hidden: false, position: 0 },
      { area: "k", hidden: false, position: 1 },
      { area: "p", hidden: false, position: 2 },
    ]);
    el.remove();
  });
});

describe("turning an area back on", () => {
  it("notes when no map has a room for it", async () => {
    const el = document.createElement("rt-area-settings") as RtAreaSettings;
    (el as any).hass = hass;
    const d = JSON.parse(JSON.stringify(doc));
    d.areas[0].hidden = true;
    d.maps = [{ zones: [{ area: "garage" }] }];
    (el as any).doc = d;
    document.body.appendChild(el);
    await el.updateComplete;
    expect(el.shadowRoot!.querySelector(".note")).toBeNull();
    await flip(el.shadowRoot!.querySelector("rt-switch.show, .show rt-switch")!);
    await el.updateComplete;
    expect(el.shadowRoot!.querySelector(".note")?.textContent).toContain("Not on a map yet");
    el.remove();
  });
});
