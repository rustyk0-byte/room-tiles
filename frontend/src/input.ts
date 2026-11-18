// Input conventions, in ONE place (docs/UI.md "Input"). Raw pointer / key
// events are turned into intents here; editors act on intents and never look
// at pointerType or modifier keys themselves. Decided per gesture (the event's
// pointerType), not per device - an iPad with a trackpad, a touchscreen laptop
// use both.

export type SelectMode = "replace" | "toggle" | "add";

export function isTouch(e: PointerEvent | MouseEvent): boolean {
  return "pointerType" in e && (e as PointerEvent).pointerType === "touch";
}

/** Tap / click on an item: touch builds up a selection (like the wall
 *  panels); mouse / trackpad / pen selects just it, Shift / Ctrl / Cmd adds or
 *  removes it. */
export function selectMode(e: PointerEvent | MouseEvent): SelectMode {
  if (isTouch(e)) return "toggle";
  return e.shiftKey || e.ctrlKey || e.metaKey ? "toggle" : "replace";
}

/** Drag on empty space: with a mouse, Shift or Alt held draws a selection box;
 *  on touch the editor's "Select" mode does (else it pans). */
export function startsBox(e: PointerEvent, selectModeOn: boolean): boolean {
  if (isTouch(e)) return selectModeOn;
  return e.shiftKey || e.altKey || selectModeOn;
}

/** A selection box: what's inside becomes the selection; with a mouse, the
 *  keys that add on a click (Shift / Ctrl / Cmd) held at release add it to
 *  the selection instead. */
export function boxSelectMode(e: PointerEvent | MouseEvent): SelectMode {
  return !isTouch(e) && (e.shiftKey || e.ctrlKey || e.metaKey) ? "add" : "replace";
}

/** Apply a selection change. */
export function applySelect(current: string[], ids: string[], mode: SelectMode): string[] {
  if (mode === "replace") return [...ids];
  const set = new Set(current);
  if (mode === "add") ids.forEach((i) => set.add(i));
  else ids.forEach((i) => (set.has(i) ? set.delete(i) : set.add(i)));
  return [...set];
}

export type KeyIntent =
  | { kind: "undo" }
  | { kind: "redo" }
  | { kind: "delete" }
  | { kind: "clear" }
  | { kind: "select-all" }
  | { kind: "nudge"; dx: number; dy: number; big: boolean };

/** Is the key going into a text field / dropdown (then it isn't a shortcut)? */
export function typingIn(e: KeyboardEvent): boolean {
  const t = e.composedPath()[0] as HTMLElement | undefined;
  return !!t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA" || !!t.isContentEditable);
}

/** Keyboard shortcuts - accelerators only: everything is also reachable with
 *  visible buttons. Ignored while typing in a field. */
export function keyIntent(e: KeyboardEvent): KeyIntent | undefined {
  if (typingIn(e)) return undefined;
  const mod = e.ctrlKey || e.metaKey;
  const k = e.key.toLowerCase();
  if (mod && k === "z" && !e.shiftKey) return { kind: "undo" };
  if (mod && (k === "y" || (k === "z" && e.shiftKey))) return { kind: "redo" };
  if (mod && k === "a") return { kind: "select-all" };
  if (!mod && (e.key === "Delete" || e.key === "Backspace")) return { kind: "delete" };
  if (e.key === "Escape") return { kind: "clear" };
  const arrows: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
  if (!mod && arrows[e.key]) return { kind: "nudge", dx: arrows[e.key][0], dy: arrows[e.key][1], big: e.shiftKey };
  return undefined;
}

/** Dragging near a map's edge scrolls it (every editor alike): within
 *  EDGE_PX of an edge, by up to EDGE_SPEED CSS px a frame - faster the
 *  closer. The pull per axis, -1..1 (+ = towards right / bottom). */
// MIRRORED: firmware/components/room_tiles/room_tiles.cpp guard_taps (TAP_SLOP_PX) - a change here must be made there too.
/** A tap is a tap only when the pointer stayed put: a press that slid
 *  further than this (a missed scroll, a slip) clicks nothing - the panels'
 *  rule, so a drag across a tile's button never switches it. */
export const TAP_SLOP_PX = 16;

/** Where a press started; `tapMoved` says whether a click came too far from
 *  it. A keyboard click (Enter / Space: detail 0) is always a tap. */
export class TapGuard {
  private x = 0;
  private y = 0;
  down(e: PointerEvent): void {
    this.x = e.clientX;
    this.y = e.clientY;
  }
  tapMoved(e: MouseEvent): boolean {
    if (e.detail === 0) return false;
    const dx = e.clientX - this.x;
    const dy = e.clientY - this.y;
    return dx * dx + dy * dy > TAP_SLOP_PX * TAP_SLOP_PX;
  }
}

export const EDGE_PX = 48;
export const EDGE_SPEED = 14;
export function edgePull(r: { left: number; top: number; right: number; bottom: number }, x: number, y: number): [number, number] {
  const pull = (d: number) => (d < EDGE_PX ? (EDGE_PX - Math.max(0, d)) / EDGE_PX : 0);
  return [pull(r.right - x) - pull(x - r.left), pull(r.bottom - y) - pull(y - r.top)];
}
