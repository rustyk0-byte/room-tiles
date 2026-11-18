// Movable sheets: the map editor's selection sheet and the marker sheet sit
// over the map and can be in the way, so their title row is a handle - drag
// it to move the sheet anywhere inside the map area (a double-click / double
// tap on the title row puts it back). Where it was left is remembered in this
// browser (per sheet). The sheet's CSS reads the offset:
//   transform: translate(calc(-50% + var(--sheet-dx, 0px)), var(--sheet-dy, 0px));

import type { ReactiveController, ReactiveControllerHost } from "lit";

export interface Offset {
  x: number;
  y: number;
}

export interface Rect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

const MARGIN = 4;

/** The offset nearest `want` that keeps the sheet inside `bounds`. `rect` is
 *  where the sheet is drawn now, at offset `at`. Too big to fit: its top /
 *  left edge stays in view. */
export function clampOffset(want: Offset, at: Offset, rect: Rect, bounds: Rect): Offset {
  const fit = (v: number, lo: number, hi: number) => (hi < lo ? lo : Math.min(hi, Math.max(lo, v)));
  return {
    x: Math.round(fit(want.x, bounds.left + MARGIN - (rect.left - at.x), bounds.right - MARGIN - (rect.right - at.x))),
    y: Math.round(fit(want.y, bounds.top + MARGIN - (rect.top - at.y), bounds.bottom - MARGIN - (rect.bottom - at.y))),
  };
}

function read(key: string): Offset {
  try {
    const o = JSON.parse(localStorage.getItem(key) ?? "null");
    if (o && Number.isFinite(o.x) && Number.isFinite(o.y)) return { x: o.x, y: o.y };
  } catch {
    /* nothing remembered */
  }
  return { x: 0, y: 0 };
}

function write(key: string, o: Offset): void {
  try {
    if (o.x || o.y) localStorage.setItem(key, JSON.stringify(o));
    else localStorage.removeItem(key);
  } catch {
    /* private mode etc.: just not remembered */
  }
}

export class SheetDrag implements ReactiveController {
  offset: Offset;
  private _drag?: { id: number; px: number; py: number; at: Offset; rect: Rect; bounds: Rect };

  constructor(
    private host: ReactiveControllerHost & { renderRoot: ParentNode },
    private key: string,
  ) {
    this.offset = read(key);
    host.addController(this);
  }

  hostConnected(): void {
    window.addEventListener("resize", this._fit);
  }

  hostDisconnected(): void {
    window.removeEventListener("resize", this._fit);
  }

  /** A moved sheet that no longer fits (smaller window, taller content)
   *  is pulled back in. */
  hostUpdated(): void {
    if (this.offset.x || this.offset.y) this._fit();
  }

  /** For the sheet's style attribute. */
  get style(): string {
    return `--sheet-dx:${this.offset.x}px;--sheet-dy:${this.offset.y}px`;
  }

  /** On the title row: @pointerdown=${drag.down} @dblclick=${drag.reset} */
  down = (e: PointerEvent): void => {
    if ((e.target as Element).closest("button, select, input, a, ha-switch")) return;
    const head = e.currentTarget as HTMLElement;
    const sheet = head.closest(".sheet") as HTMLElement | null;
    const area = sheet?.offsetParent as HTMLElement | null;
    if (!sheet || !area) return;
    e.preventDefault();
    e.stopPropagation();
    this._drag = { id: e.pointerId, px: e.clientX, py: e.clientY, at: { ...this.offset }, rect: sheet.getBoundingClientRect(), bounds: area.getBoundingClientRect() };
    head.setPointerCapture?.(e.pointerId);
    head.addEventListener("pointermove", this._move);
    head.addEventListener("pointerup", this._up);
    head.addEventListener("pointercancel", this._up);
  };

  reset = (): void => {
    this.offset = { x: 0, y: 0 };
    write(this.key, this.offset);
    this.host.requestUpdate();
  };

  private _move = (e: PointerEvent): void => {
    const d = this._drag;
    if (!d || e.pointerId !== d.id) return;
    e.stopPropagation();
    this.offset = clampOffset({ x: d.at.x + e.clientX - d.px, y: d.at.y + e.clientY - d.py }, d.at, d.rect, d.bounds);
    this.host.requestUpdate();
  };

  private _up = (e: PointerEvent): void => {
    const head = e.currentTarget as HTMLElement;
    head.removeEventListener("pointermove", this._move);
    head.removeEventListener("pointerup", this._up);
    head.removeEventListener("pointercancel", this._up);
    if (!this._drag) return;
    this._drag = undefined;
    write(this.key, this.offset);
  };

  private _fit = (): void => {
    if (this._drag) return;
    const sheet = this.host.renderRoot.querySelector?.(".sheet") as HTMLElement | null;
    const area = sheet?.offsetParent as HTMLElement | null;
    if (!sheet || !area) return;
    const next = clampOffset(this.offset, this.offset, sheet.getBoundingClientRect(), area.getBoundingClientRect());
    if (next.x !== this.offset.x || next.y !== this.offset.y) {
      this.offset = next;
      this.host.requestUpdate();
    }
  };
}
