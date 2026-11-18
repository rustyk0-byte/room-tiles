import { describe, expect, it } from "vitest";
import "./map-help";

describe("rt-map-help", () => {
  it("shows the input tables and closes from X", async () => {
    const el = document.createElement("rt-map-help") as HTMLElement & { updateComplete: Promise<boolean> };
    document.body.append(el);
    await el.updateComplete;
    const root = el.shadowRoot!;
    expect(root.querySelectorAll("table").length).toBe(2);
    expect(root.textContent).toContain("Shift / Ctrl / Cmd + drag: add to it");
    let closed = false;
    el.addEventListener("close", () => (closed = true));
    (root.querySelector("button.x") as HTMLButtonElement).click();
    expect(closed).toBe(true);
    el.remove();
  });

  it("Layer Editor help explains layers and links to their settings", async () => {
    const el = document.createElement("rt-map-help") as HTMLElement & { updateComplete: Promise<boolean> };
    document.body.append(el);
    await el.updateComplete;
    const root = el.shadowRoot!;
    expect(root.querySelector(".section")?.textContent).toBe("Layers");
    let asked = false;
    el.addEventListener("layer-settings", () => (asked = true));
    (root.querySelector("button.link") as HTMLButtonElement).click();
    expect(asked).toBe(true);
    el.remove();
  });

  it("the map's own help: markers, moving around, buttons - no editor note", async () => {
    const el = document.createElement("rt-map-help") as HTMLElement & { mode: string; updateComplete: Promise<boolean> };
    el.mode = "view";
    document.body.append(el);
    await el.updateComplete;
    const root = el.shadowRoot!;
    expect([...root.querySelectorAll(".section")].map((x) => x.textContent)).toEqual(["Markers", "Moving around", "Buttons"]);
    expect(root.querySelector(".title")?.textContent).toBe("Map");
    expect(root.querySelector(".best")).toBeNull();
    el.remove();
  });

  it("the tiles' and the tile editor's pages", async () => {
    for (const [mode, title, first] of [
      ["tiles", "Room Tiles", "Tiles"],
      ["tile-edit", "Tile Editor", "Changing the board"],
    ]) {
      const el = document.createElement("rt-map-help") as HTMLElement & { mode: string; updateComplete: Promise<boolean> };
      el.mode = mode;
      document.body.append(el);
      await el.updateComplete;
      const root = el.shadowRoot!;
      expect(root.querySelector(".title")?.textContent).toBe(title);
      expect(root.querySelector(".section")?.textContent).toBe(first);
      el.remove();
    }
  });
});
