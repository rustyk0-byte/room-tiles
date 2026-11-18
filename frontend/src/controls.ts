// The panel's tile controls as web components: <rt-switch> (track image +
// knob) and <rt-roller> (3-row vertical picker). Sizes are panel design
// pixels times --u (set by the tile: 198 design px = the tile's width), so a
// tile keeps the panel's proportions at any size. Colours only from --rt-*.

import { LitElement, css, html, type PropertyValues } from "lit";

const ROW_U = 32; // roller row height, design px (3 rows visible)
const SETTLE_SCROLL_MS = 140; // scroll considered finished after this quiet time

export class RtSwitch extends LitElement {
  static properties = {
    checked: { type: Boolean, reflect: true },
    disabled: { type: Boolean, reflect: true },
    trackOff: { attribute: false },
    trackOn: { attribute: false },
    knob: { attribute: false },
    w: { type: Number },
    label: { type: String },
  };

  checked = false;
  disabled = false;
  trackOff = "";
  trackOn = "";
  knob = "";
  w = 75;
  label = "";

  private _toggle(e: Event): void {
    e.stopPropagation();
    if (this.disabled) return;
    this.checked = !this.checked;
    this.dispatchEvent(new CustomEvent("change", { detail: { checked: this.checked }, bubbles: true, composed: true }));
  }

  render() {
    return html`<button
      role="switch"
      aria-checked=${this.checked}
      aria-label=${this.label}
      ?disabled=${this.disabled}
      style="--w:${this.w}"
      @click=${this._toggle}
    >
      <img class="track off" alt="" src=${this.trackOff} />
      <img class="track on" alt="" src=${this.trackOn} />
      <img class="knob" alt="" src=${this.knob} />
    </button>`;
  }

  static styles = css`
    :host {
      display: inline-block;
    }
    button {
      position: relative;
      display: block;
      width: calc(var(--w) * var(--u, 1px));
      height: calc(32 * var(--u, 1px));
      padding: 0;
      border: none;
      background: none;
      cursor: pointer;
      /* the panels' ext_click_area: easier to hit */
      margin: calc(-8 * var(--u, 1px));
      border: calc(8 * var(--u, 1px)) solid transparent;
      box-sizing: content-box;
    }
    button:disabled {
      cursor: default;
      opacity: 0.5;
    }
    .track {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      transition: opacity 0.15s;
    }
    .track.on,
    :host([checked]) .track.off {
      opacity: 0;
    }
    :host([checked]) .track.on {
      opacity: 1;
    }
    .knob {
      position: absolute;
      top: calc(1 * var(--u, 1px));
      left: calc(1 * var(--u, 1px));
      width: calc(30 * var(--u, 1px));
      height: calc(30 * var(--u, 1px));
      transition: transform 0.18s ease-out;
    }
    :host([checked]) .knob {
      transform: translateX(calc((var(--w) - 32) * var(--u, 1px)));
    }
    @media (prefers-reduced-motion: reduce) {
      .knob,
      .track {
        transition: none;
      }
    }
  `;
}

export class RtRoller extends LitElement {
  static properties = {
    options: { attribute: false },
    selected: { type: Number },
    disabled: { type: Boolean, reflect: true },
    label: { type: String },
    _center: { state: true },
  };

  options: string[] = [];
  /** the row the roller should show (from HA / pending); the user's scroll wins while active */
  selected = 0;
  disabled = false;
  label = "";
  private _center = 0;
  // Only the USER's scrolling may send: programmatic scrolls (following HA)
  // and layout changes (resize, rotation - when the list can briefly have no
  // height, making the row maths land on the first / last row) never do.
  private _userScrolling = false;
  private _userUntil = 0; // the user flag expires 1.5 s after their last touch / scroll
  // a finger / button still down: a pause (changing direction) isn't the end
  // of the roll - it settles once they let go (and the momentum stops)
  private _touching = false;
  private _settleTimer?: number;

  private get _list(): HTMLElement | null {
    return this.renderRoot.querySelector(".list");
  }

  private _rowPx(): number {
    const list = this._list;
    return list && list.clientHeight > 0 ? list.clientHeight / 3 : 0;
  }

  protected updated(changed: PropertyValues): void {
    if ((changed.has("selected") || changed.has("options")) && !this._userScrolling) {
      this._scrollTo(this.selected, false);
    }
  }

  protected firstUpdated(): void {
    // after layout: the list's height is known
    requestAnimationFrame(() => this._scrollTo(this.selected, false));
  }

  private _scrollTo(row: number, smooth: boolean): void {
    const list = this._list;
    const rowPx = this._rowPx();
    if (!list || !rowPx) return; // not laid out yet: updated() / resize retries
    this._center = row;
    list.scrollTo({ top: row * rowPx, behavior: smooth ? "smooth" : "instant" });
  }

  private _onScroll(): void {
    const list = this._list;
    const rowPx = this._rowPx();
    if (!list || !rowPx) return;
    const before = this._center;
    this._center = Math.max(0, Math.min(this.options.length - 1, Math.round(list.scrollTop / rowPx)));
    if (this._userScrolling && !this._touching && Date.now() > this._userUntil) this._userScrolling = false; // a stale touch
    if (!this._userScrolling) return; // our own scroll / a layout change: never sends
    // while rolling: the row it's on now (a tile can show what it would set);
    // "change" still comes once, when it settles
    if (this._center !== before)
      this.dispatchEvent(new CustomEvent("rolling", { detail: { row: this._center }, bubbles: true, composed: true }));
    this._userUntil = Date.now() + 1500; // still moving (incl. momentum)
    window.clearTimeout(this._settleTimer);
    this._settleTimer = window.setTimeout(() => this._settled(), SETTLE_SCROLL_MS);
  }

  private _settled(): void {
    if (!this._userScrolling || this._touching) return; // still held: wait for the release
    this._userScrolling = false;
    const row = this._center;
    this._scrollTo(row, true); // snap exactly
    if (row !== this.selected) {
      this.dispatchEvent(new CustomEvent("change", { detail: { row }, bubbles: true, composed: true }));
    }
  }

  private _resizeObs?: ResizeObserver;

  connectedCallback(): void {
    super.connectedCallback();
    // a size change (rotation, full screen) re-shows HA's row - never sends
    this._resizeObs = new ResizeObserver(() => {
      if (!this._userScrolling) this._scrollTo(this.selected, false);
    });
    this._resizeObs.observe(this);
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    this._resizeObs?.disconnect();
    window.clearTimeout(this._settleTimer);
    this._userScrolling = false;
    this._touching = false;
  }

  private _onUser(): void {
    if (this.disabled) return;
    this._userScrolling = true;
    this._userUntil = Date.now() + 1500;
  }

  private _onDown(): void {
    this._onUser();
    if (!this.disabled) this._touching = true;
  }

  /** Let go: it settles once the scrolling (momentum) goes quiet. */
  private _onUp(): void {
    if (!this._touching) return;
    this._touching = false;
    this._userUntil = Date.now() + 1500;
    window.clearTimeout(this._settleTimer);
    this._settleTimer = window.setTimeout(() => this._settled(), SETTLE_SCROLL_MS);
  }

  private _pick(row: number, e: Event): void {
    e.stopPropagation();
    if (this.disabled) return;
    this._userScrolling = true;
    this._userUntil = Date.now() + 1500;
    this._scrollTo(row, true);
    window.clearTimeout(this._settleTimer);
    this._settleTimer = window.setTimeout(() => this._settled(), 350);
  }

  private _key(e: KeyboardEvent): void {
    if (this.disabled) return;
    const step = e.key === "ArrowDown" ? 1 : e.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const row = Math.max(0, Math.min(this.options.length - 1, this._center + step));
    this._pick(row, e);
  }

  render() {
    return html`<div
      class="list"
      role="listbox"
      tabindex=${this.disabled ? -1 : 0}
      aria-label=${this.label}
      aria-activedescendant="o${this._center}"
      @scroll=${this._onScroll}
      @pointerdown=${this._onDown}
      @pointerup=${this._onUp}
      @pointercancel=${(e: PointerEvent) => {
        // a touch that turned into the list's own scrolling is cancelled as a
        // pointer - the finger is still down: its touchend ends it
        if (e.pointerType !== "touch") this._onUp();
      }}
      @wheel=${this._onUser}
      @touchstart=${this._onDown}
      @touchend=${this._onUp}
      @touchcancel=${this._onUp}
      @keydown=${this._key}
      @click=${(e: Event) => e.stopPropagation()}
    >
      <div class="pad"></div>
      ${this.options.map(
        (o, i) => html`<div
          id="o${i}"
          role="option"
          aria-selected=${i === this._center}
          class="opt ${i === this._center ? "sel" : ""}"
          @click=${(e: Event) => this._pick(i, e)}
        >
          ${o}
        </div>`,
      )}
      <div class="pad"></div>
    </div>`;
  }

  static styles = css`
    :host {
      display: block;
      --row: calc(${ROW_U} * var(--u, 1px));
      /* a subtle frame (the tiles' border grey; the panels draw the same) -
         on the host, so the list's fade mask doesn't fade it, and inset, so
         nothing moves */
      border-radius: calc(8 * var(--u, 1px));
      box-shadow: inset 0 0 0 1px var(--rt-tile-border);
    }
    .list {
      height: calc(var(--row) * 3);
      overflow-y: auto;
      scroll-snap-type: y mandatory;
      scrollbar-width: none;
      overscroll-behavior: contain;
      outline: none;
      /* fade the rows above / below the selected one */
      mask-image: linear-gradient(transparent, black 30%, black 70%, transparent);
    }
    .list::-webkit-scrollbar {
      display: none;
    }
    :host([disabled]) .list {
      overflow-y: hidden;
      opacity: 0.6;
    }
    .pad {
      height: var(--row);
    }
    .opt {
      height: var(--row);
      line-height: var(--row);
      text-align: center;
      scroll-snap-align: center;
      font-size: calc(16 * var(--u, 1px));
      color: var(--rt-roller-text);
      cursor: pointer;
      white-space: nowrap;
      user-select: none;
    }
    .opt.sel {
      font-size: var(--rt-roller-selected-size, calc(28 * var(--u, 1px)));
      font-weight: 700;
      color: var(--rt-roller-color, var(--rt-text));
    }
    .list:focus-visible .opt.sel {
      text-decoration: underline;
    }
  `;
}

if (!customElements.get("rt-switch")) customElements.define("rt-switch", RtSwitch);
if (!customElements.get("rt-roller")) customElements.define("rt-roller", RtRoller);
