import { describe, expect, it } from "vitest";
import { EDGE_PX, applySelect, boxSelectMode, edgePull, keyIntent, selectMode, startsBox } from "./input";

const pe = (pointerType: string, mods: Partial<PointerEvent> = {}) => ({ pointerType, shiftKey: false, ctrlKey: false, metaKey: false, altKey: false, ...mods }) as PointerEvent;

describe("input rules (docs/UI.md Input)", () => {
  it("touch taps build up a selection; mouse clicks replace it unless a modifier is held", () => {
    expect(selectMode(pe("touch"))).toBe("toggle");
    expect(selectMode(pe("mouse"))).toBe("replace");
    expect(selectMode(pe("pen"))).toBe("replace");
    expect(selectMode(pe("mouse", { shiftKey: true }))).toBe("toggle");
    expect(selectMode(pe("mouse", { ctrlKey: true }))).toBe("toggle");
    expect(selectMode(pe("mouse", { metaKey: true }))).toBe("toggle");
  });

  it("selection box: mouse with Shift / Alt, or Select mode; touch only in Select mode", () => {
    expect(startsBox(pe("mouse", { shiftKey: true }), false)).toBe(true);
    expect(startsBox(pe("mouse", { altKey: true }), false)).toBe(true);
    expect(startsBox(pe("mouse"), false)).toBe(false);
    expect(startsBox(pe("touch", { shiftKey: true }), false)).toBe(false);
    expect(startsBox(pe("touch"), true)).toBe(true);
  });

  it("applySelect", () => {
    expect(applySelect(["a", "b"], ["c"], "replace")).toEqual(["c"]);
    expect(applySelect(["a", "b"], ["b", "c"], "toggle").sort()).toEqual(["a", "c"]);
    expect(applySelect(["a"], ["a", "b"], "add").sort()).toEqual(["a", "b"]);
  });

  it("keyboard intents, never while typing in a field", () => {
    const key = (key: string, mods: Partial<KeyboardEvent> = {}, tag = "DIV") =>
      keyIntent({ key, ctrlKey: false, metaKey: false, shiftKey: false, ...mods, composedPath: () => [{ tagName: tag }] } as unknown as KeyboardEvent);
    expect(key("z", { ctrlKey: true })).toEqual({ kind: "undo" });
    expect(key("z", { metaKey: true, shiftKey: true })).toEqual({ kind: "redo" });
    expect(key("y", { ctrlKey: true })).toEqual({ kind: "redo" });
    expect(key("a", { ctrlKey: true })).toEqual({ kind: "select-all" });
    expect(key("Delete")).toEqual({ kind: "delete" });
    expect(key("Escape")).toEqual({ kind: "clear" });
    expect(key("ArrowLeft", { shiftKey: true })).toEqual({ kind: "nudge", dx: -1, dy: 0, big: true });
    expect(key("Backspace", {}, "INPUT")).toBeUndefined();
    expect(key("z", { ctrlKey: true }, "INPUT")).toBeUndefined();
  });
});

describe("edgePull (dragging near a map's edge scrolls it)", () => {
  const r = { left: 0, top: 0, right: 500, bottom: 300 };
  it("none in the middle; full at an edge; both ways in a corner", () => {
    expect(edgePull(r, 250, 150)).toEqual([0, 0]);
    expect(edgePull(r, 500, 150)).toEqual([1, 0]);
    expect(edgePull(r, 0, 150)).toEqual([-1, 0]);
    expect(edgePull(r, 500 - EDGE_PX / 2, 300)).toEqual([0.5, 1]);
  });
});

describe("boxSelectMode", () => {
  it("a box replaces the selection; Ctrl / Cmd with a mouse adds", () => {
    const ev = (o: Partial<PointerEvent>) => ({ pointerType: "mouse", ctrlKey: false, metaKey: false, ...o }) as PointerEvent;
    expect(boxSelectMode(ev({}))).toBe("replace");
    expect(boxSelectMode(ev({ ctrlKey: true }))).toBe("add");
    expect(boxSelectMode(ev({ shiftKey: true }))).toBe("add");
    expect(boxSelectMode(ev({ altKey: true }))).toBe("replace");
    expect(boxSelectMode(ev({ pointerType: "touch", ctrlKey: true }))).toBe("replace");
  });
});
