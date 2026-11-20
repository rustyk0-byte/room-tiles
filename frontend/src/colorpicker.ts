// <rt-color-picker>: the panels' colour / white-temperature picker as a
// pop-up (esphome color_picker/ in the original firmware).
//
// Colour tab: hue ring + preview swatch in its centre, saturation and
// brightness sliders. White tab: warm-to-cool slider (the panels'
// temp_track art) and 2700 / 3000 / 4000 / 5000 / 6500 K presets inside the
// light's range. Tabs only for what the light supports. Changes are sent after
// a short pause and held on screen until HA confirms (or 3 s pass).
//
// The ring / swatch colours are the LIGHT's colours (data), not theme colours,
// so they are computed here; everything else uses the --rt-* theme variables.

import { dialogStyles, noSelectStyles, ScrollFades } from "./ui";
import { LitElement, css, html, nothing, type PropertyValues } from "lit";
import { DialogPin } from "./dialog-pin";
import type { HassEntity, HomeAssistant } from "./types";
import { pct, t } from "./i18n";

// Sending, like the panels: while the user moves, at most one call per
// THROTTLE_MS so the light follows along; a final call when they stop
// (SETTLE_MS of quiet) with the exact value; nothing if the value didn't change
// since the last call. The picker holds the user's values for HOLD_MS so HA's
// slower confirmations don't make it jump back.
// Light groups update member by member, so HA reports in-between colours for
// a while: groups get a slower throttle and a longer hold, and the hold only
// ends early once HA reports the value that was sent (within a tolerance).
const THROTTLE_MS = 500;
const THROTTLE_GROUP_MS = 1500;
const SETTLE_MS = 250;
const HOLD_MS = 4000;
const HOLD_GROUP_MS = 15000;
const PRESETS_K = [2700, 3000, 4000, 5000, 6500];
const COLOR_MODES = new Set(["hs", "xy", "rgb", "rgbw", "rgbww"]);

// MIRRORED: firmware/components/room_tiles/picker.cpp kelvin colour - a change here must be made there too.
/** A colour temperature (K) as an approximate display colour. */
export function kelvinCss(k: number): string {
  const t = k / 100;
  const r = t <= 66 ? 255 : 329.698727446 * Math.pow(t - 60, -0.1332047592);
  const g = t <= 66 ? 99.4708025861 * Math.log(t) - 161.1195681661 : 288.1221695283 * Math.pow(t - 60, -0.0755148492);
  const b = t >= 66 ? 255 : t <= 19 ? 0 : 138.5177312231 * Math.log(t - 10) - 305.0447927307;
  const c = (v: number) => Math.round(Math.min(255, Math.max(0, v)));
  return `rgb(${c(r)} ${c(g)} ${c(b)})`;
}

// MIRRORED: firmware/components/room_tiles/picker.cpp + picker.h hs colour - a change here must be made there too.
export function hsCss(h: number, s: number): string {
  return `hsl(${Math.round(h)} ${Math.round(s)}% ${Math.round(100 - s / 2)}%)`;
}

/** The colour a light tile's swatch shows (undefined = no colour info). */
export function lightSwatch(stateObj?: HassEntity): string | undefined {
  const a = stateObj?.attributes ?? {};
  if (a.color_mode === "color_temp" && typeof a.color_temp_kelvin === "number") return kelvinCss(a.color_temp_kelvin);
  if (Array.isArray(a.hs_color)) return hsCss(a.hs_color[0], a.hs_color[1]);
  return undefined;
}

export function supports(stateObj?: HassEntity): { color: boolean; temp: boolean } {
  const modes: string[] = stateObj?.attributes.supported_color_modes ?? [];
  return { color: modes.some((m) => COLOR_MODES.has(m)), temp: modes.includes("color_temp") };
}

type Tab = "color" | "temp";

// The ring's hole (.ring-hole inset 22%): inner radius as a fraction of the
// ring's width. Keep in step with the CSS.
const RING_INNER = 0.5 - 0.22;

export class RtColorPicker extends LitElement {
  /** fades where a scrolling area has more (ui.ts ScrollFades) */
  protected readonly _scrollFades = new ScrollFades(this, ".dialog");

  /** the dialog's top edge stays put while its content changes (dialog-pin.ts) */
  readonly dialogPin = new DialogPin(this);
  static properties = {
    hass: { attribute: false },
    entity: { type: String },
    name: { type: String },
    _tab: { state: true },
    _hue: { state: true },
    _sat: { state: true },
    _bri: { state: true },
    _kelvin: { state: true },
  };

  hass?: HomeAssistant;
  entity = "";
  name = "";
  private _tab: Tab = "color";
  private _hue = 0;
  private _sat = 100;
  private _bri = 100;
  private _kelvin = 3000;
  private _holdUntil = 0;
  private _sendTimer?: number;
  private _dragging = false;
  private _lastSentAt = 0;
  private _lastSent = "";
  private _sentData?: Record<string, unknown>; // the last call, until HA reports it
  private _queued?: Record<string, unknown>;

  private get _group(): boolean {
    return Array.isArray(this._state?.attributes.entity_id);
  }

  /** Does HA's state show what was last sent? (tolerances: hue 4, sat 4,
   *  brightness 3 %, 100 K) */
  private _confirmed(): boolean {
    const sent = this._sentData;
    if (!sent) return true;
    const a = this._state?.attributes ?? {};
    const near = (x: unknown, y: unknown, tol: number) => typeof x === "number" && typeof y === "number" && Math.abs(x - y) <= tol;
    if (Array.isArray(sent.hs_color)) {
      if (!Array.isArray(a.hs_color)) return false;
      const dh = Math.abs(a.hs_color[0] - (sent.hs_color[0] as number));
      if (Math.min(dh, 360 - dh) > 4 || !near(a.hs_color[1], sent.hs_color[1], 4)) return false;
    }
    if (sent.color_temp_kelvin !== undefined && !near(a.color_temp_kelvin, sent.color_temp_kelvin, 100)) return false;
    if (sent.brightness_pct !== undefined) {
      const pct = typeof a.brightness === "number" ? (a.brightness / 255) * 100 : undefined;
      if (!near(pct, sent.brightness_pct, 3)) return false;
    }
    return true;
  }

  private get _state(): HassEntity | undefined {
    return this.hass?.states[this.entity];
  }

  protected willUpdate(changed: PropertyValues): void {
    if (changed.has("entity")) {
      const sup = supports(this._state);
      this._tab = this._state?.attributes.color_mode === "color_temp" || !sup.color ? "temp" : "color";
      this._holdUntil = 0;
      this._lastSent = ""; // (another light: nothing sent to it yet)
    }
    // follow HA unless the user just changed something - and keep holding
    // through in-between reports (groups) until HA shows what was sent
    if (changed.has("hass") && this._sentData && Date.now() <= this._holdUntil && this._confirmed()) {
      this._sentData = undefined;
      this._holdUntil = 0;
      this._lastSent = ""; // (HA has it: the same value again is a new call)
      this._emitHold(undefined); // tile: follow HA again
    }
    if ((changed.has("hass") || changed.has("entity")) && Date.now() > this._holdUntil && !this._dragging) {
      this._sentData = undefined;
      this._lastSent = ""; // (following HA: the light may have changed elsewhere)
      const a = this._state?.attributes ?? {};
      if (Array.isArray(a.hs_color)) [this._hue, this._sat] = a.hs_color;
      if (typeof a.brightness === "number") this._bri = Math.max(1, Math.round((a.brightness / 255) * 100));
      if (typeof a.color_temp_kelvin === "number") this._kelvin = a.color_temp_kelvin;
    }
  }

  private get _holdMs(): number {
    return this._group ? HOLD_GROUP_MS : HOLD_MS;
  }

  /** Tell the tile what colour to show while HA catches up (undefined = follow HA). */
  private _emitHold(colour: string | undefined): void {
    this.dispatchEvent(
      new CustomEvent("hold", { detail: { entity: this.entity, colour, until: this._holdUntil }, bubbles: true, composed: true }),
    );
  }

  private _send(data: Record<string, unknown>): void {
    this._holdUntil = Date.now() + this._holdMs;
    this._queued = data;
    this._emitHold(data.color_temp_kelvin !== undefined ? kelvinCss(this._kelvin) : hsCss(this._hue, this._sat));
    window.clearTimeout(this._sendTimer);
    if (Date.now() - this._lastSentAt >= (this._group ? THROTTLE_GROUP_MS : THROTTLE_MS)) {
      this._flush(); // moving: a call now (at most one per THROTTLE_MS)...
    }
    // ...and the exact value once the user stops
    this._sendTimer = window.setTimeout(() => this._flush(), SETTLE_MS);
  }

  private _flush(): void {
    const data = this._queued;
    if (!data) return;
    this._queued = undefined;
    const key = JSON.stringify(data);
    if (key === this._lastSent) return; // unchanged since the last call
    this._lastSent = key;
    this._lastSentAt = Date.now();
    this._sentData = data;
    this._holdUntil = Date.now() + this._holdMs;
    this.hass?.callService("light", "turn_on", { entity_id: this.entity, ...data });
  }

  private _sendColor(): void {
    this._send({ hs_color: [Math.round(this._hue), Math.round(this._sat)], brightness_pct: this._bri });
  }

  private _close(): void {
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  }

  // hue ring: angle from the centre, 0 deg = top, clockwise (like the panels)
  private _ringPointer(e: PointerEvent): void {
    const el = e.currentTarget as HTMLElement;
    const r = el.getBoundingClientRect();
    const x = e.clientX - (r.left + r.width / 2);
    const y = e.clientY - (r.top + r.height / 2);
    if (e.type === "pointerdown") {
      // only the coloured band starts a drag: not the centre / preview, not
      // outside the ring (band = between the hole and the edge, RING_INNER..0.5)
      const d = Math.hypot(x, y) / r.width;
      if (d < RING_INNER || d > 0.5) return;
      this._dragging = true;
      el.setPointerCapture(e.pointerId);
    } else if (!this._dragging) return;
    this._hue = (Math.atan2(x, -y) * 180) / Math.PI + (x < 0 ? 360 : 0);
    if (this._sat < 10) this._sat = 100; // picking a hue on white means "make it colourful"
    this._sendColor();
  }

  private _ringUp(): void {
    this._dragging = false;
  }

  render() {
    const sup = supports(this._state);
    const a = this._state?.attributes ?? {};
    const kMin = a.min_color_temp_kelvin ?? 2000;
    const kMax = a.max_color_temp_kelvin ?? 6500;
    return html`
      <div class="scrim" @click=${this._close}></div>
      <div class="dialog" role="dialog" aria-label=${t("color.dialog", { name: this.name })}>
        <div class="head">
          <div class="title">${this.name}</div>
          <button class="x" aria-label=${t("common.close")} @click=${this._close}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        ${sup.color && sup.temp
          ? html`<div class="tabs" role="tablist">
              <button role="tab" aria-selected=${this._tab === "color"} class=${this._tab === "color" ? "on" : ""} @click=${() => (this._tab = "color")}>${t("color.tab_color")}</button>
              <button role="tab" aria-selected=${this._tab === "temp"} class=${this._tab === "temp" ? "on" : ""} @click=${() => (this._tab = "temp")}>${t("color.tab_white")}</button>
            </div>`
          : nothing}
        ${this._tab === "color" && sup.color ? this._renderColor() : this._renderTemp(kMin, kMax)}
        <label class="slider">
          <span>${t("color.brightness")}</span>
          <input
            type="range"
            min="1"
            max="100"
            .value=${String(this._bri)}
            @input=${(e: Event) => {
              this._bri = Number((e.target as HTMLInputElement).value);
              this._send({ brightness_pct: this._bri });
            }}
          />
          <span class="val">${pct(this._bri)}</span>
        </label>
      </div>
    `;
  }

  private _renderColor() {
    const swatch = hsCss(this._hue, this._sat);
    return html`
      <div
        class="ring"
        @pointerdown=${this._ringPointer}
        @pointermove=${this._ringPointer}
        @pointerup=${this._ringUp}
        @pointercancel=${this._ringUp}
      >
        <div class="ring-hole"><div class="preview" style="background:${swatch}"></div></div>
        <div class="marker" style="transform: rotate(${this._hue}deg)"><span></span></div>
      </div>
      <label class="slider">
        <span>${t("color.saturation")}</span>
        <input
          type="range"
          min="0"
          max="100"
          .value=${String(Math.round(this._sat))}
          style="--from:${hsCss(this._hue, 0)};--to:${hsCss(this._hue, 100)}"
          class="sat"
          @input=${(e: Event) => {
            this._sat = Number((e.target as HTMLInputElement).value);
            this._sendColor();
          }}
        />
        <span class="val">${pct(Math.round(this._sat))}</span>
      </label>
    `;
  }

  private _renderTemp(kMin: number, kMax: number) {
    const presets = PRESETS_K.filter((k) => k >= kMin && k <= kMax);
    const setK = (k: number) => {
      this._kelvin = k;
      this._send({ color_temp_kelvin: k, brightness_pct: this._bri });
    };
    return html`
      <div class="presets">
        ${presets.map(
          (k) => html`<button class=${Math.abs(this._kelvin - k) < 50 ? "on" : ""} @click=${() => setK(k)}>
            <span class="dot" style="background:${kelvinCss(k)}"></span>${k}K
          </button>`,
        )}
      </div>
      <label class="slider">
        <span>${t("color.warm")}</span>
        <input
          type="range"
          class="temp"
          min=${kMin}
          max=${kMax}
          step="50"
          .value=${String(this._kelvin)}
          @input=${(e: Event) => setK(Number((e.target as HTMLInputElement).value))}
        />
        <span>${t("color.cool")}</span>
      </label>
      <div class="kelvin">${this._kelvin}K</div>
    `;
  }

  static styles = [noSelectStyles, 
    dialogStyles,
    css`
      :host {
        --dialog-w: 380px;
      }
      .dialog {
        overflow: auto; /* short screens (phone in landscape) */
        gap: 14px;
      }
    .tabs {
      display: flex;
      gap: 6px;
    }
    .tabs button {
      flex: 1;
      padding: 8px;
      border-radius: 10px;
      border: 1px solid var(--rt-tile-border);
      background: var(--rt-button);
    }
    .tabs button.on {
      background: var(--rt-accent);
      color: var(--rt-on-accent);
      border-color: var(--rt-accent);
    }
    .ring {
      position: relative;
      width: min(240px, 70vw);
      aspect-ratio: 1;
      margin: 0 auto;
      border-radius: 50%;
      /* the light's hues, 0 deg at the top, clockwise */
      background: conic-gradient(
        hsl(0 100% 50%),
        hsl(60 100% 50%),
        hsl(120 100% 50%),
        hsl(180 100% 50%),
        hsl(240 100% 50%),
        hsl(300 100% 50%),
        hsl(360 100% 50%)
      );
      touch-action: none;
      cursor: crosshair;
    }
    .ring-hole {
      position: absolute;
      inset: 22%;
      border-radius: 50%;
      background: var(--rt-dialog);
      display: flex;
      align-items: center;
      justify-content: center;
      pointer-events: none;
    }
    .preview {
      width: 62%;
      aspect-ratio: 1;
      border-radius: 50%;
      border: 2px solid var(--rt-tile-border);
    }
    .marker {
      position: absolute;
      inset: 0;
      pointer-events: none;
    }
    .marker span {
      position: absolute;
      left: 50%;
      top: 2%;
      width: 18%;
      aspect-ratio: 1;
      transform: translateX(-50%);
      border-radius: 50%;
      border: 3px solid var(--rt-text);
      box-sizing: border-box;
    }
    .slider {
      display: grid;
      grid-template-columns: 5.5em 1fr auto;
      align-items: center;
      gap: 10px;
      font-size: 0.95rem;
    }
    .slider .val {
      min-width: 3em;
      text-align: right;
      color: var(--rt-text-secondary);
    }
    input[type="range"] {
      width: 100%;
      height: 36px; /* a big touch area */
      accent-color: var(--rt-accent);
    }
    input.sat {
      appearance: none;
      background: linear-gradient(to right, var(--from), var(--to)) center / 100% 10px no-repeat;
    }
    input.temp {
      appearance: none;
      background: var(--rt-temp-track) center / 100% 12px no-repeat;
    }
    input.sat::-webkit-slider-thumb,
    input.temp::-webkit-slider-thumb {
      appearance: none;
      width: 26px;
      height: 26px;
      border-radius: 50%;
      background: var(--rt-text);
      border: 2px solid var(--rt-tile-border);
    }
    input.sat::-moz-range-thumb,
    input.temp::-moz-range-thumb {
      width: 24px;
      height: 24px;
      border-radius: 50%;
      background: var(--rt-text);
      border: 2px solid var(--rt-tile-border);
    }
    .presets {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      justify-content: center;
    }
    .presets button {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 8px 10px;
      border-radius: 10px;
      border: 1px solid var(--rt-tile-border);
      background: var(--rt-button);
    }
    .presets button.on {
      border-color: var(--rt-accent);
    }
    .dot {
      width: 14px;
      height: 14px;
      border-radius: 50%;
    }
    .kelvin {
      text-align: center;
      color: var(--rt-text-secondary);
    }
    `,
  ];
}

if (!customElements.get("rt-color-picker")) customElements.define("rt-color-picker", RtColorPicker);
