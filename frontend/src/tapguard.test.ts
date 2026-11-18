import { describe, expect, it } from "vitest";
import { TAP_SLOP_PX, TapGuard } from "./input";

const at = (x: number, y: number, detail = 1) => ({ clientX: x, clientY: y, detail }) as unknown as PointerEvent & MouseEvent;

describe("a tap stays put (the panels' rule)", () => {
  it("lets a press that stayed within the slop click", () => {
    const g = new TapGuard();
    g.down(at(100, 100));
    expect(g.tapMoved(at(100 + TAP_SLOP_PX - 1, 100))).toBe(false);
  });
  it("stops a press that slid further (a missed scroll)", () => {
    const g = new TapGuard();
    g.down(at(100, 100));
    expect(g.tapMoved(at(100, 100 + TAP_SLOP_PX + 4))).toBe(true);
  });
  it("never stops a keyboard click", () => {
    const g = new TapGuard();
    g.down(at(500, 500));
    expect(g.tapMoved(at(0, 0, 0))).toBe(false);
  });
});
