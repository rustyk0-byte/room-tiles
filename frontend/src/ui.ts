// Shared UI building blocks - every dialog, settings row and on/off switch in
// the dashboard uses these, so they all look and behave the same
// (rules: docs/UI.md). Colours only from the --rt-* theme variables.

import { css, html, svg, type ReactiveController, type ReactiveControllerHost, type TemplateResult } from "lit";
import { STATIC_BASE } from "./appliance";
import "./controls";
import { assetUrl, DEFAULT_THEME, type ThemeName } from "./theme";
import { t } from "./i18n";

/** Dialog layers: a dialog 20/21; a dialog opened from a dialog 30/31. */
export const dialogStyles = css`
  /* MIRRORED: firmware/components/room_tiles/board_edit.cpp dialog_ + picker.cpp build_ (the scrim) - a change here must be made there too. */
  .scrim {
    position: fixed;
    inset: 0;
    z-index: var(--z, 20);
    background: var(--rt-page);
    opacity: 0.6;
  }
  .dialog {
    position: fixed;
    z-index: calc(var(--z, 20) + 1);
    /* Inside the visible page: --rt-top is where the Room Tiles page starts on
       screen (measured by the panel - below a phone's status bar, which the HA
       app doesn't report as a safe area), plus the standard safe-area insets. */
    --top: max(var(--rt-top, 0px), env(safe-area-inset-top, 0px));
    --bottom: env(safe-area-inset-bottom, 0px);
    /* centred on the Room Tiles page (--rt-left / --rt-width, measured by
       the panel), not the window: HA's sidebar never covers part of it */
    left: calc(var(--rt-left, 0px) + var(--rt-width, 100vw) / 2);
    top: calc(var(--top) + (100dvh - var(--top) - var(--bottom)) / 2);
    transform: translate(-50%, -50%);
    width: min(var(--dialog-w, 520px), calc(var(--rt-width, 100vw) - 24px));
    max-height: calc(100dvh - var(--top) - var(--bottom) - 24px);
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 14px 16px 16px;
    background: var(--rt-dialog);
    border: 1px solid var(--rt-tile-border);
    border-radius: 18px;
    color: var(--rt-text);
    box-sizing: border-box;
  }
  button {
    font: inherit;
    color: inherit;
    cursor: pointer;
  }
  button:disabled {
    opacity: 0.4;
    cursor: default;
  }
  input[type="text"],
  input[type="search"],
  input:not([type]),
  select {
    font: inherit;
    color: var(--rt-text);
    background: var(--rt-button);
    border: 1px solid var(--rt-tile-border);
    border-radius: 8px;
    padding: 7px 9px;
    min-width: 0;
  }
  .head {
    display: flex;
    align-items: center;
  }
  .title {
    flex: 1;
    font-weight: 700;
    font-size: 1.15rem;
  }
  .x {
    border: none;
    background: none;
    padding: 4px;
    --mdc-icon-size: 26px;
  }
  .intro,
  .hint {
    font-size: 0.88rem;
    color: var(--rt-text-secondary);
  }
  .warn {
    font-size: 0.88rem;
    color: var(--rt-light);
  }
  .list {
    overflow-y: auto;
    overscroll-behavior: contain; /* its end doesn't scroll what's behind */
    min-height: 0;
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .footer {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
    padding-top: 8px;
    border-top: 1px solid var(--rt-tile-border);
    flex: none;
  }
  .footer button {
    border-radius: 10px;
    padding: 9px 16px;
    border: 1px solid var(--rt-tile-border);
    background: var(--rt-button);
  }
  .footer .primary {
    background: var(--rt-accent);
    color: var(--rt-on-accent);
    border-color: var(--rt-accent);
  }
  .link {
    border: none;
    background: none;
    padding: 0 4px;
    color: var(--rt-accent);
    text-decoration: underline;
  }
  .check {
    display: flex;
    gap: 8px;
    align-items: center;
    cursor: pointer;
  }
`;

/** Every component: text can't be selected (a long-press on a label made iOS
 *  select it, and show its copy menu) - except where you type. Shared so each
 *  shadow root gets it: inputs need it switched back on inside their own. */
export const noSelectStyles = css`
  :host {
    -webkit-user-select: none;
    user-select: none;
    -webkit-touch-callout: none;
  }
  input,
  textarea,
  [contenteditable] {
    -webkit-user-select: text;
    user-select: text;
    -webkit-touch-callout: default;
  }
`;

/** A framed group of settings (docs/UI.md "Settings come in framed groups"):
 *  `.group` + `.group-head` (icon + title). Its own sheet so any dialog can
 *  load it without the row styles. */
export const groupStyles = css`
  /* A framed group of settings (docs/UI.md): a darker panel with a border,
     headed by its icon + title - so what belongs together is obvious. The
     appliance dialog's unit cards look the same. */
  .group {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 4px 12px 8px;
    margin-top: 8px;
    border: 1px solid var(--rt-tile-border);
    border-radius: 14px;
    background: var(--rt-panel-dark);
  }
  .group-head {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 1rem;
    font-weight: 500;
    padding: 6px 0 8px;
    margin-bottom: 2px;
    border-bottom: 1px solid var(--rt-tile-border);
    --mdc-icon-size: 22px;
  }
  .group-head ha-icon {
    color: var(--rt-accent);
  }
`;

/** Settings rows: label left, control right, one line each; rows that open a
 *  dialog end in a chevron. */
export const rowStyles = css`
  .section {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--rt-text-secondary);
    margin: 6px 0 2px;
  }

  .setting {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 40px;
  }
  .setting > .label {
    flex: 1;
    min-width: 0;
  }
  button.nav {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    min-height: 40px;
    padding: 0 4px;
    border: none;
    border-radius: 8px;
    background: none;
    text-align: left;
    --mdc-icon-size: 20px;
  }
  button.nav:hover {
    background: var(--rt-button);
  }
  button.nav .label {
    flex: 1;
  }
  button.nav .chev {
    color: var(--rt-text-secondary);
  }
  .badge {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--rt-light);
  }
  .segmented {
    display: flex;
    gap: 4px;
  }
  .segmented button {
    padding: 6px 12px;
    border-radius: 8px;
    border: 1px solid var(--rt-tile-border);
    background: var(--rt-button);
  }
  .segmented button.on {
    background: var(--rt-accent);
    color: var(--rt-on-accent);
    border-color: var(--rt-accent);
  }
  rt-switch.small {
    --u: 0.75px;
  }
`;

/** An on/off setting: the panels' switch art (blue when on). */
export function toggle(
  checked: boolean,
  onChange: (on: boolean) => void,
  label: string,
  theme: ThemeName = DEFAULT_THEME,
): TemplateResult {
  const art = (n: string) => assetUrl(STATIC_BASE, `ui/${n}.png`, theme);
  return html`<rt-switch
    class="small"
    .w=${75}
    .trackOff=${art("track_switch_off")}
    .trackOn=${art("track_switch_on_blue")}
    .knob=${art("knob_switch")}
    .checked=${checked}
    .label=${label}
    @change=${(e: CustomEvent) => onChange(e.detail.checked)}
  ></rt-switch>`;
}

/** A row that opens a dialog: icon, label, optional badge, chevron. */
/** Set up an appliance / vacuum / pool (set_appliance, set_robot,
 *  set_pool): its tile joins its area's automatic boards by itself; when the
 *  user changed that area's board, the panel asks ("tiles-ask"). */
export async function setUpDevice(
  el: HTMLElement,
  hass: { callService(d: string, s: string, data?: Record<string, unknown>, t?: Record<string, unknown>, n?: boolean, r?: boolean): Promise<unknown> },
  service: string,
  data: Record<string, unknown>,
  name: string,
): Promise<void> {
  const res = (await hass.callService("room_tiles", service, data, undefined, true, true)) as { response?: { ask?: string[] } } | undefined;
  const areas = res?.response?.ask ?? [];
  if (areas.length) el.dispatchEvent(new CustomEvent("tiles-ask", { detail: { areas, name }, bubbles: true, composed: true }));
}

export function navRow(icon: string, label: string, onClick: () => void, badge = false): TemplateResult {
  return html`<button class="nav" @click=${onClick}>
    <ha-icon icon=${icon}></ha-icon>
    <span class="label">${label}</span>
    ${badge ? html`<span class="badge" aria-label=${t("common.needs_attention")}></span>` : ""}
    <ha-icon class="chev" icon="mdi:chevron-right"></ha-icon>
  </button>`;
}

/** Map editing (the map editor, marker editing) is best on a tablet or a
 *  computer - room for the map and the tools. On a phone-sized touch screen
 *  both editors say so once, until OK (this device). */
const TOUCH_NOTE = "room-tiles:touch-note";

export function touchNoteShown(): boolean {
  const touchOnly = typeof matchMedia === "function" && !matchMedia("(any-pointer: fine)").matches;
  // a phone: the screen's short side under 600 CSS px (tablets are fine)
  const phone = typeof screen !== "undefined" && Math.min(screen.width, screen.height) < 600;
  if (!touchOnly || !phone) return false;
  try {
    return localStorage.getItem(TOUCH_NOTE) !== "1";
  } catch {
    return true;
  }
}

export function touchNote(dismiss: () => void): TemplateResult {
  const ok = () => {
    try {
      localStorage.setItem(TOUCH_NOTE, "1");
    } catch {
      /* not remembered: shown again next time */
    }
    dismiss();
  };
  return html`<div class="touch-note" role="note">
    <ha-icon icon="mdi:tablet-cellphone"></ha-icon>
    <span>${t("touch_note.text")}</span>
    <button class="pill" @click=${ok}>${t("common.ok")}</button>
  </div>`;
}

export const touchNoteStyles = css`
  .touch-note {
    flex: none;
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 4px 12px;
    padding: 6px 10px;
    border-radius: 10px;
    background: var(--rt-panel-dark);
    border: 1px solid var(--rt-tile-border);
    font-size: 0.88rem;
    --mdc-icon-size: 20px;
  }
  .touch-note ha-icon {
    color: var(--rt-accent);
    flex: none;
  }
  .touch-note span {
    flex: 1;
  }
`;

/** The Room Tiles icon (custom_components/room_tiles/themes/masters/brand/room_tiles_icon.svg - four
 *  rounded outlines in the tile colours), inline: the loading and empty
 *  screens. `size` in CSS px. */
export function brandIcon(size = 96): TemplateResult {
  return html`<svg class="brand" viewBox="0 0 256 256" width=${size} height=${size} aria-hidden="true">
    ${svg`<g fill="none" stroke-width="20">
      <rect x="30" y="30" width="80" height="80" rx="16" stroke="var(--rt-light)"></rect>
      <rect x="146" y="30" width="80" height="80" rx="16" stroke="var(--rt-accent)"></rect>
      <rect x="30" y="146" width="80" height="80" rx="16" stroke="var(--rt-cover)"></rect>
      <rect x="146" y="146" width="80" height="80" rx="16" stroke="var(--rt-lock)"></rect>
    </g>`}
  </svg>`;
}

/** Which edges of a scrolling area `shown` px tall, holding `total` px and
 *  scrolled `top` px, have more beyond them. */
export function moreBeyond(shown: number, total: number, top: number): { above: boolean; below: boolean } {
  const more = total - shown;
  if (more <= 1) return { above: false, below: false };
  return { above: top > 1, below: top < more - 1 };
}

const FADE_MIN = 24; // px
const FADE_MAX = 0.45; // (of the area's height: a short area keeps its middle clear)

/** The row at the line y (viewport px) inside a scrolling area `node`: the
 *  child the line crosses, else the nearest one on the inward side (`before`:
 *  rows ending above the line - the bottom edge). A child that's a group of
 *  rows (rows stacked inside it, taller than a row) gives its own row
 *  instead - one level down, so a group's row, a board's tile - never a
 *  piece of one, nor a whole group. */
export function rowAt(node: Element, y: number, before: boolean, inside = false): DOMRect | undefined {
  let best: Element | undefined;
  let found: DOMRect | undefined;
  for (const kid of Array.from(node.children)) {
    const r = kid.getBoundingClientRect();
    if (r.height === 0) continue;
    if (r.top < y && r.bottom > y) {
      best = kid;
      found = r;
      break;
    }
    if (before ? r.bottom <= y && (!found || r.bottom > found.bottom) : r.top >= y && (!found || r.top < found.top)) {
      best = kid;
      found = r;
    }
  }
  if (!best || !found) return undefined;
  if (!inside && found.height >= GROUP_PX && stacked(best)) {
    const inner = rowAt(best, y, before, true);
    if (inner) return inner;
    // (only the group's frame on the inward side of the line: the next row
    // past the group - the fade reaches over the frame to it)
    return rowAt(node, before ? found.top : found.bottom, before) ?? found;
  }
  return found;
}

const GROUP_PX = 120; // (taller than any one row)

/** Are (some of) its children one above another - rows, not parts side by side? */
function stacked(el: Element): boolean {
  const rs = Array.from(el.children)
    .map((k) => k.getBoundingClientRect())
    .filter((r) => r.height > 0);
  return rs.some((a) => rs.some((b) => a.bottom <= b.top + 1));
}

/** Fades at the edges of scrolling areas (docs/UI.md): a list that ends at a
 *  row's edge looks complete, and a phone shows its own scroll bar only once
 *  it's moving. So each scrolling area a component names (`selector`, in its
 *  own shadow root) fades out where there's more: at the bottom while more is
 *  below, at the top once it's scrolled down - nothing when it all fits. The
 *  browser's own scroll bar is left as the platform has it. A fade blends
 *  into what's behind the list (its own background, else the nearest one
 *  under it) and never takes a tap. (The panels draw thin scroll bars
 *  instead: there's no platform bar there - firmware style_scroll.) */
export class ScrollFades implements ReactiveController {
  private readonly areas = new Map<HTMLElement, { above: HTMLElement; below: HTMLElement; ro: ResizeObserver }>();
  private frame = 0;

  constructor(
    private readonly host: ReactiveControllerHost & HTMLElement,
    private readonly selector: string,
  ) {
    host.addController(this);
  }

  hostUpdated(): void {
    this.sync();
  }

  hostDisconnected(): void {
    for (const el of [...this.areas.keys()]) this.drop(el);
    cancelAnimationFrame(this.frame);
  }

  /** New scrolling areas get their fades; gone ones lose them. */
  private sync(): void {
    const root = this.host.shadowRoot;
    if (!root) return;
    const now = new Set(root.querySelectorAll<HTMLElement>(this.selector));
    for (const el of [...this.areas.keys()]) if (!now.has(el) || !el.isConnected) this.drop(el);
    for (const el of now) {
      let area = this.areas.get(el);
      if (!area) {
        const fade = () => {
          const d = document.createElement("div");
          d.setAttribute("aria-hidden", "true");
          Object.assign(d.style, { position: "absolute", pointerEvents: "none", display: "none" });
          return d;
        };
        const ro = new ResizeObserver(() => this.later());
        ro.observe(el);
        el.addEventListener("scroll", this.onScroll, { passive: true });
        area = { above: fade(), below: fade(), ro };
        this.areas.set(el, area);
      }
      // (its content's size changes too: what's in it now)
      for (const child of Array.from(el.children)) area.ro.observe(child);
    }
    this.later();
  }

  private drop(el: HTMLElement): void {
    const area = this.areas.get(el);
    if (!area) return;
    area.ro.disconnect();
    area.above.remove();
    area.below.remove();
    el.removeEventListener("scroll", this.onScroll);
    this.areas.delete(el);
  }

  private readonly onScroll = (): void => this.later();

  private later(): void {
    cancelAnimationFrame(this.frame);
    this.frame = requestAnimationFrame(() => {
      for (const [el, area] of this.areas) this.place(el, area.above, area.below);
    });
  }

  private place(el: HTMLElement, above: HTMLElement, below: HTMLElement): void {
    const box = el.parentNode;
    const edges = moreBeyond(el.clientHeight, el.scrollHeight, el.scrollTop);
    if (!box || el.clientHeight === 0 || (!edges.above && !edges.below)) {
      above.style.display = below.style.display = "none";
      return;
    }
    const cs = getComputedStyle(el);
    const bt = parseFloat(cs.borderTopWidth);
    const bl = parseFloat(cs.borderLeftWidth);
    const bg = behind(el);
    const z = parseInt(cs.zIndex, 10);
    const er = el.getBoundingClientRect();
    const inner = (r: string) => `${Math.max(0, parseFloat(r) - Math.max(bt, bl))}px`;
    for (const [fade, on, top] of [
      [above, edges.above, true],
      [below, edges.below, false],
    ] as const) {
      if (!on) {
        fade.style.display = "none";
        continue;
      }
      // beside it, in the same tree (its styles, its layer); where that puts
      // the fade's origin is measured - offsetParent can't say (the shadow
      // host for a container outside the shadow root; none for a fixed
      // dialog) - which also covers transforms and scrolling
      if (fade.parentNode !== box) box.appendChild(fade);
      Object.assign(fade.style, { display: "block", top: "0px", left: "0px", zIndex: Number.isNaN(z) ? "1" : String(z + 1) });
      const origin = fade.getBoundingClientRect();
      // a row tall: from the far side of the row at the edge (the last one
      // in view at the bottom, the first at the top) to the edge, so that
      // row always visibly fades
      const edge = top ? er.top + bt : er.top + bt + el.clientHeight;
      const row = rowAt(el, edge, !top);
      const reach = row ? (top ? row.bottom - edge : edge - row.top) : FADE_MIN;
      const h = Math.round(Math.min(el.clientHeight * FADE_MAX, Math.max(FADE_MIN, reach)));
      const y = top ? edge : edge - h;
      Object.assign(fade.style, {
        top: `${y - origin.top}px`,
        height: `${h}px`,
        left: `${er.left + bl - origin.left}px`,
        width: `${el.clientWidth}px`,
        // (fully the background just before the edge: the row reads as going on)
        background: `linear-gradient(${top ? "to top" : "to bottom"}, transparent, ${bg} 85%)`,
        // (inside a rounded box: its corners)
        borderRadius: top
          ? `${inner(cs.borderTopLeftRadius)} ${inner(cs.borderTopRightRadius)} 0 0`
          : `0 0 ${inner(cs.borderBottomRightRadius)} ${inner(cs.borderBottomLeftRadius)}`,
      });
    }
  }
}

/** The colour behind `el`: its own background, else the nearest one under it
 *  (across shadow roots). */
function behind(el: Element): string {
  const clear = (c: string) => c === "transparent" || /,\s*0(\.0+)?\)$/.test(c);
  for (let n: Node | null = el; n; ) {
    if (n instanceof Element) {
      const c = getComputedStyle(n).backgroundColor;
      if (c && !clear(c)) return c;
    }
    n = n.parentNode instanceof ShadowRoot ? n.parentNode.host : n.parentNode;
  }
  return "var(--rt-page)";
}

