import { describe, expect, it } from "vitest";
import { browserFacts, feedbackDevices } from "./feedback";
import { issueUrl } from "./report";
import type { RoomTilesDoc } from "./types";

describe("browserFacts", () => {
  it("names the browser, its major version and the system - never the whole user agent", () => {
    const chrome = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.39 Mobile Safari/537.36";
    expect(browserFacts(chrome, 412.4, 915)).toEqual({ name: "chrome", version: "131", os: "android", window: "412x915" });
    const safari = "Mozilla/5.0 (iPad; CPU OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1";
    expect(browserFacts(safari, 1024, 768)).toMatchObject({ name: "safari", version: "18", os: "ios" });
    const edge = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.2903.51";
    expect(browserFacts(edge, 1920, 1080)).toMatchObject({ name: "edge", version: "131", os: "windows" });
    const firefox = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.1; rv:132.0) Gecko/20100101 Firefox/132.0";
    expect(browserFacts(firefox, 1440, 900)).toMatchObject({ name: "firefox", version: "132", os: "macos" });
    const app = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Home Assistant/2024.11.1";
    expect(browserFacts(app, 390, 844)).toMatchObject({ name: "ha_app", version: "2024", os: "ios" });
    expect(browserFacts("Something/1", 10, 10)).toEqual({ name: "other", os: "other", window: "10x10" });
  });
});

describe("feedbackDevices", () => {
  it("lists appliances, pools and vacuums by name, an appliance with its units", () => {
    const doc = {
      appliances: [{ id: "a1", name: "Washer", units: [{ id: "u1", label: "Washer", appliance: "washer" }] }],
      pools: [{ id: "p1", name: "Backyard Pool" }],
      robots: [{ id: "r1", name: "Matic" }],
    } as unknown as RoomTilesDoc;
    expect(feedbackDevices(doc)).toEqual([
      { subject: "pool", id: "p1", name: "Backyard Pool", units: [] },
      { subject: "robot", id: "r1", name: "Matic", units: [] },
      { subject: "appliance", id: "a1", name: "Washer", units: [{ id: "u1", label: "Washer" }] },
    ]);
    expect(feedbackDevices(undefined)).toEqual([]);
  });
});

describe("issueUrl", () => {
  const base = "https://github.com/o/r/issues/new";
  it("fills the kind's issue form field (the form applies its label)", () => {
    const url = new URL(issueUrl({ title: "Bug: it froze", body: "x", url: base, template: "bug.yml", field: "report" }, "a + b & c"));
    expect(url.searchParams.get("template")).toBe("bug.yml");
    expect(url.searchParams.get("title")).toBe("Bug: it froze");
    expect(url.searchParams.get("report")).toBe("a + b & c");
    expect(url.searchParams.has("body")).toBe(false);
    expect(url.search).not.toMatch(/\+/); // (spaces as %20: a literal + stays a plus)
  });
  it("uses the plain body without a form", () => {
    const url = new URL(issueUrl({ title: "Test report: X", body: "x", url: base }, "hello"));
    expect(url.searchParams.get("body")).toBe("hello");
    expect(url.searchParams.has("template")).toBe(false);
  });
});

describe("rt-feedback", () => {
  type El = HTMLElement & { updateComplete: Promise<boolean>; doc?: RoomTilesDoc; hass?: unknown };
  const openBug = async (doc: RoomTilesDoc): Promise<El> => {
    const el = document.createElement("rt-feedback") as El;
    el.doc = doc;
    el.hass = { states: {} };
    document.body.append(el);
    await el.updateComplete;
    const bug = [...el.shadowRoot!.querySelectorAll<HTMLButtonElement>("button.choice")].find((b) => b.textContent!.includes("Report a bug"))!;
    bug.click();
    await el.updateComplete;
    return el;
  };
  const choices = (el: El) => [...el.shadowRoot!.querySelectorAll("button.choice")].map((b) => b.textContent!.trim());
  const next = (el: El) => [...el.shadowRoot!.querySelectorAll<HTMLButtonElement>("button.primary")].at(-1)!;

  it("a home with only the web dashboard: no touch panel choice, the dashboard is enough", async () => {
    const el = await openBug({} as RoomTilesDoc);
    expect(choices(el)).toEqual(["This dashboard", "Somewhere else"]);
    const words = el.shadowRoot!.querySelector("textarea")!;
    words.value = "The map editor froze.";
    words.dispatchEvent(new Event("input"));
    el.shadowRoot!.querySelector<HTMLButtonElement>("button.choice")!.click();
    await el.updateComplete;
    expect(next(el).disabled).toBe(false);
    el.remove();
  });

  it("with panels: a touch panel is one choice among others, never required", async () => {
    const doc = { panel_firmware: { panels: [{ device_id: "d1", name: "Kitchen", board: "elecrow-p4", running: "1" }, { device_id: "d2", name: "Office", board: "elecrow-p4", running: "1" }], images: [] } } as unknown as RoomTilesDoc;
    const el = await openBug(doc);
    expect(choices(el)).toEqual(["This dashboard", "A touch panel", "Somewhere else"]);
    el.remove();
  });
});
