import { describe, expect, it } from "vitest";
import "./unsaved";

describe("rt-unsaved", () => {
  it("one tap for each way out", async () => {
    const el = document.createElement("rt-unsaved") as HTMLElement & { updateComplete: Promise<boolean>; what: string };
    el.what = "map";
    document.body.append(el);
    await el.updateComplete;
    const root = el.shadowRoot!;
    expect(root.textContent).toContain("Save your map changes?");
    const got: string[] = [];
    for (const n of ["save", "discard", "keep"]) el.addEventListener(n, () => got.push(n));
    const buttons = [...root.querySelectorAll<HTMLButtonElement>(".footer button")];
    buttons.find((b) => b.textContent!.includes("Save"))!.click();
    buttons.find((b) => b.textContent!.includes("Discard"))!.click();
    buttons.find((b) => b.textContent!.includes("Keep"))!.click();
    root.querySelector<HTMLButtonElement>("button.x")!.click();
    expect(got).toEqual(["save", "discard", "keep", "keep"]);
    el.remove();
  });
});
