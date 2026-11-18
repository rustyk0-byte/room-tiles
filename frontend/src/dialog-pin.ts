// Dialogs (ui.ts dialogStyles) open centred. After that their TOP EDGE stays
// where it is while the content changes height - a filter that changes a
// list must not move the control you're using (docs/UI.md). The top only
// moves UP, when the dialog would otherwise run off the bottom of the screen.
// A window resize / rotation centres them again.
//
//   readonly dialogPin = new DialogPin(this);   // in any element with a .dialog

import type { ReactiveController, ReactiveControllerHost } from "lit";

const MARGIN = 12; // dialogStyles keeps 12 px clear above and below

/** Where the top goes: where it opened, unless the dialog would run past
 *  `maxBottom` - then up just enough, never above `minTop`. */
export function pinnedTop(opened: number, height: number, minTop: number, maxBottom: number): number {
  return opened + height > maxBottom ? Math.max(minTop, maxBottom - height) : opened;
}

export class DialogPin implements ReactiveController {
  private _ro?: ResizeObserver;
  private _tops = new Map<HTMLElement, number>();

  constructor(private host: ReactiveControllerHost & { renderRoot?: ParentNode }) {
    host.addController(this);
  }

  hostConnected(): void {
    window.addEventListener("resize", this._recentre);
  }

  hostDisconnected(): void {
    window.removeEventListener("resize", this._recentre);
    this._ro?.disconnect();
    this._ro = undefined;
    this._tops.clear();
  }

  hostUpdated(): void {
    if (typeof ResizeObserver === "undefined") return;
    for (const el of this.host.renderRoot?.querySelectorAll<HTMLElement>(".dialog") ?? []) {
      if (this._tops.has(el)) continue;
      this._tops.set(el, NaN); // seen; placed on its first size
      (this._ro ??= new ResizeObserver((entries) => entries.forEach((e) => this._place(e.target as HTMLElement)))).observe(el);
    }
    for (const el of [...this._tops.keys()]) if (!el.isConnected) this._forget(el);
  }

  private _place(el: HTMLElement): void {
    if (!el.isConnected) return this._forget(el);
    const r = el.getBoundingClientRect();
    if (!r.height) return;
    const known = this._tops.get(el);
    const opened = known === undefined || Number.isNaN(known) ? r.top : known; // first time: where CSS centred it
    const minTop = (parseFloat(getComputedStyle(el).getPropertyValue("--rt-top")) || 0) + MARGIN;
    const maxBottom = (window.visualViewport?.height ?? window.innerHeight) - MARGIN;
    const top = pinnedTop(opened, r.height, minTop, maxBottom);
    this._tops.set(el, top);
    el.style.top = `${top}px`;
    el.style.transform = "translate(-50%, 0)";
  }

  private _forget(el: HTMLElement): void {
    this._ro?.unobserve(el);
    this._tops.delete(el);
  }

  private _recentre = (): void => {
    for (const el of this._tops.keys()) {
      el.style.top = "";
      el.style.transform = "";
      this._tops.set(el, NaN);
    }
    requestAnimationFrame(() => [...this._tops.keys()].forEach((el) => this._place(el)));
  };
}
