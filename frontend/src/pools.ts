// <rt-pool-editor>: a pool / spa system's settings (Add and the pencil on the
// Appliances page). The EQUIPMENT LAYOUT comes first as cards - Shared (the
// spa on the pool, one pump + heater switching between them), Separate, Pool
// only, Spa only; picking a card only changes the fields below (docs/UI.md:
// buttons in a settings dialog never close or replace it). Nothing is stored
// until Add / Save changes.

import { LitElement, css, html, nothing } from "lit";
import { DialogPin } from "./dialog-pin";
import type { HassEntity, HomeAssistant, PoolBodyProfile, PoolLayout, PoolProfile, RoomTilesDoc } from "./types";
import { dialogStyles, noSelectStyles, rowStyles, toggle, groupStyles, setUpDevice, ScrollFades } from "./ui";
import "./unsaved";
import { listOf, t } from "./i18n";

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const EMPTY: PoolBodyProfile = { temp: null, heater: null, pump: null, pump_with_heater: true };

/** The layout cards (their words: pools.layout_<key> / _sub, read when drawn). */
const LAYOUTS: { key: PoolLayout; icon: string }[] = [
  { key: "shared", icon: "mdi:hot-tub" },
  { key: "separate", icon: "mdi:pool" },
  { key: "pool", icon: "mdi:pool" },
  { key: "spa", icon: "mdi:hot-tub" },
];

/** The bodies a layout has. */
export const bodiesOf = (layout: PoolLayout): ("pool" | "spa")[] =>
  layout === "shared" || layout === "separate" ? ["pool", "spa"] : [layout];

/** The tiles a layout gets (their tile-picker names). */
export const tilesOf = (layout: PoolLayout): string[] =>
  (layout === "shared" ? ["pool_spa", "spa_mode"] : layout === "separate" ? ["pool", "spa"] : [layout]).map((k) => t(`pools.tile_${k}`));

export class RtPoolEditor extends LitElement {
  /** fades where a scrolling area has more (ui.ts ScrollFades) */
  protected readonly _scrollFades = new ScrollFades(this, ".list");

  /** the dialog's top edge stays put while its content changes (dialog-pin.ts) */
  readonly dialogPin = new DialogPin(this);
  static properties = {
    hass: { attribute: false },
    doc: { attribute: false },
    profile: { attribute: false },
    adding: { type: Boolean },
    _draft: { state: true },
    _ask: { state: true },
    _confirmRemove: { state: true },
    _busy: { state: true },
    _error: { state: true },
  };

  hass?: HomeAssistant;
  doc?: RoomTilesDoc;
  profile?: PoolProfile;
  adding = false;
  private _draft?: PoolProfile;
  private _ask = false;
  private _confirmRemove = false;
  private _busy = false;
  private _error = "";
  private _opened = Date.now();

  private get _view(): PoolProfile {
    return this._draft ?? this.profile!;
  }

  private get _dirty(): boolean {
    return this.adding || (this._draft !== undefined && JSON.stringify(this._draft) !== JSON.stringify(this.profile));
  }

  private _change(fn: (p: PoolProfile) => void): void {
    const p = clone(this._view);
    fn(p);
    this._draft = p;
  }

  /** Pick a layout: keeps every entity already chosen (a body that comes
   *  back keeps its fields). */
  private _layout(layout: PoolLayout): void {
    this._change((p) => {
      p.layout = layout;
      for (const b of bodiesOf(layout)) p[b] = p[b] ?? (this.profile?.[b] ? clone(this.profile[b]!) : { ...EMPTY });
    });
  }

  /** What's missing before it can be saved ("" = ready). */
  private get _missing(): string {
    const p = this._view;
    for (const b of bodiesOf(p.layout))
      if (!p[b]?.temp && !p[b]?.heater) return t(`pools.need_temp_${b}`);
    if (p.layout === "shared" && !p.spa_mode) return t("pools.need_spa_mode");
    if (p.layout === "shared" && !p.pump) return t("pools.need_pump");
    if (p.layout === "separate" && p.pool?.heater && p.pool.heater === p.spa?.heater)
      return t("pools.one_heater");
    return "";
  }

  private _close(): void {
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  }

  private _tryClose(): void {
    if (this._dirty && !this.adding) this._ask = true;
    else this._close();
  }

  private async _run(fn: () => Promise<unknown>): Promise<void> {
    this._busy = true;
    this._error = "";
    try {
      await fn();
      this._close();
    } catch (err) {
      this._error = (err as { message?: string })?.message ?? String(err);
    } finally {
      this._busy = false;
    }
  }

  /** The stored shape: only the layout's bodies; shared-only fields cleared. */
  private _payload(): PoolProfile {
    const p = clone(this._view);
    const bodies = bodiesOf(p.layout);
    if (!bodies.includes("pool")) p.pool = null;
    if (!bodies.includes("spa")) p.spa = null;
    if (p.layout !== "shared") {
      p.spa_mode = null;
      p.pump = null;
    } else {
      for (const b of bodies) if (p[b]) p[b]!.pump = null;
    }
    p.name = p.name.trim() || this.profile!.name;
    return p;
  }

  private _save(): Promise<void> {
    const pool = this._payload();
    return this._run(() => setUpDevice(this, this.hass!, "set_pool", { pool }, pool.name));
  }

  private _remove(): void {
    if (!this._confirmRemove) {
      this._confirmRemove = true;
      return;
    }
    void this._run(() =>
      this.hass!.callService("room_tiles", "ignore_device", { kind: "pool", device: this.profile!, set_up_id: this.profile!.id }),
    );
  }

  /** Entities of a domain (and device class), the controller's own first. */
  private _options(domain: string, deviceClass?: string): HassEntity[] {
    const platform = this.profile?.preset;
    const mine = (s: HassEntity) => (this.hass?.entities?.[s.entity_id]?.platform === platform ? 0 : 1);
    const name = (s: HassEntity) => String(s.attributes.friendly_name ?? s.entity_id);
    return Object.values(this.hass?.states ?? {})
      .filter(
        (s) =>
          s.entity_id.startsWith(`${domain}.`) &&
          (!deviceClass || s.attributes.device_class === deviceClass) &&
          !this.hass?.entities?.[s.entity_id]?.entity_category,
      )
      .sort((a, b) => mine(a) - mine(b) || name(a).localeCompare(name(b)));
  }

  private _pick(
    label: string,
    value: string | null,
    options: HassEntity[],
    onPick: (v: string | null) => void,
    optional = false,
    tip = "",
  ) {
    const known = options.some((o) => o.entity_id === value);
    return html`<div class="setting" title=${tip}>
      <span class="label">${label}</span>
      <select aria-label=${label} @change=${(e: Event) => onPick((e.target as HTMLSelectElement).value || null)}>
        <option value="" ?selected=${!value}>${optional ? t("common.none") : t("common.choose_ellipsis")}</option>
        ${value && !known ? html`<option value=${value} selected>${value}</option>` : nothing}
        ${options.map(
          (o) => html`<option value=${o.entity_id} ?selected=${o.entity_id === value}>${o.attributes.friendly_name ?? o.entity_id}</option>`,
        )}
      </select>
    </div>`;
  }

  private _body(b: "pool" | "spa") {
    const p = this._view;
    const body = p[b] ?? EMPTY;
    const set = (fn: (x: PoolBodyProfile) => void) =>
      this._change((d) => {
        d[b] = d[b] ?? { ...EMPTY };
        fn(d[b]!);
      });
    return html`<div class="group">
      <div class="group-head"><ha-icon icon=${b === "spa" ? "mdi:hot-tub" : "mdi:pool"}></ha-icon>${t(`pools.tile_${b}`)}</div>
      ${this._pick(
        t("pools.water_temp"),
        body.temp,
        this._options("sensor", "temperature"),
        (v) => set((x) => (x.temp = v)),
        !!body.heater, // optional when its heater reads it (Pentair)
        t(`pools.water_temp_tip_${b}`),
      )}
      ${!body.temp && body.heater ? html`<div class="info">${t("pools.read_from_heater")}</div>` : nothing}
      ${this._pick(
        t("pools.heater"),
        body.heater,
        this._options("climate"),
        (v) => set((x) => (x.heater = v)),
        true,
        t(`pools.heater_tip_${b}`),
      )}
      ${p.layout !== "shared"
        ? this._pick(
            t("pools.pump"),
            body.pump,
            [...this._options("switch"), ...this._options("input_boolean")],
            (v) => set((x) => (x.pump = v)),
            true,
            t(`pools.pump_tip_${b}`),
          )
        : nothing}
      ${body.heater && (p.layout === "shared" ? p.pump : body.pump)
        ? html`<div
            class="setting"
            title=${t("pools.pump_with_heater_tip")}
          >
            <span class="label">${t("pools.pump_with_heater")}</span>
            ${toggle(body.pump_with_heater !== false, (on) => set((x) => (x.pump_with_heater = on)), t("pools.pump_with_heater"))}
          </div>`
        : nothing}
      ${b === "spa" && body.heater
        ? html`<div
            class="setting"
            title=${t("pools.heater_follows_tip")}
          >
            <span class="label">${t("pools.heater_follows")}</span>
            ${toggle(p.spa_heater_follows !== false, (on) => this._change((d) => (d.spa_heater_follows = on)), t("pools.heater_follows"))}
          </div>`
        : nothing}
    </div>`;
  }

  render() {
    const p = this._view;
    const switches = [...this._options("switch"), ...this._options("input_boolean")];
    const missing = this._missing;
    return html`
      <div class="scrim" style="--z:30" @click=${() => Date.now() - this._opened > 400 && this._tryClose()}></div>
      <div class="dialog" style="--z:30" role="dialog" aria-label=${t("common.settings_of", { name: p.name })}>
        <div class="head">
          <div class="title">${this.adding ? t("common.add_name", { name: this.profile!.name }) : this.profile!.name}</div>
          <button class="x" aria-label=${t("common.close")} title=${t("common.close")} @click=${this._tryClose}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        <div class="list">
          <div class="group">
          <div class="group-head"><ha-icon icon="mdi:pipe"></ha-icon>${t("pools.equipment")}</div>
          ${this.adding && p.layout === this.profile?.layout
            ? // set up from a scan: the layout picked here is a guess (gone once they pick one)
              html`<div class="guess">${t("pools.detected")}</div>`
            : nothing}
          <div class="cards" role="radiogroup" aria-label=${t("pools.layout")}>
            ${LAYOUTS.map(
              (l) => html`<button
                class="card ${l.key === p.layout ? "on" : ""}"
                role="radio"
                aria-checked=${l.key === p.layout ? "true" : "false"}
                @click=${() => this._layout(l.key)}
              >
                <ha-icon icon=${l.icon}></ha-icon>
                <span>${t(`pools.layout_${l.key}`)}</span><small>${t(`pools.layout_${l.key}_sub`)}</small>
              </button>`,
            )}
          </div>
          <div class="info">${t("pools.tiles", { list: listOf(tilesOf(p.layout)) })}</div>
          <div class="setting">
            <span class="label">${t("common.name")}</span>
            <input .value=${p.name} aria-label=${t("common.name")} @input=${(e: Event) => this._change((d) => (d.name = (e.target as HTMLInputElement).value))} />
          </div>
          </div>
          ${p.layout === "shared"
            ? html`<div class="group">
                <div class="group-head"><ha-icon icon="mdi:pump"></ha-icon>${t("pools.shared_equipment")}</div>
                ${this._pick(
                  t("pools.spa_mode_switch"),
                  p.spa_mode,
                  switches,
                  (v) => this._change((d) => (d.spa_mode = v)),
                  false,
                  t("pools.spa_mode_switch_tip"),
                )}
                ${this._pick(
                  t("pools.pump"),
                  p.pump,
                  switches,
                  (v) => this._change((d) => (d.pump = v)),
                  false,
                  t("pools.shared_pump_tip"),
                )}
              </div>`
            : nothing}
          ${bodiesOf(p.layout).map((b) => this._body(b))}
          ${!this.adding
            ? html`<div class="group">
                  <div class="group-head"><ha-icon icon="mdi:eye-off-outline"></ha-icon>${t("common.ignore")}</div>
                  <div class="setting">
                  <span class="label">${t("common.ignore_info")}</span>
                  <button class="danger" ?disabled=${this._busy} @click=${this._remove}>
                    ${this._confirmRemove ? t("common.ignore_again") : t("common.ignore")}
                  </button>
                </div>
                </div>`
            : nothing}
        </div>
        ${this._error ? html`<div class="warn">${this._error}</div>` : missing && this._draft ? html`<div class="warn">${missing}</div>` : nothing}
        <div class="footer">
          <button ?disabled=${this._busy} @click=${this._close}>${t("common.cancel")}</button>
          <button class="primary" ?disabled=${this._busy || !this._dirty || !!missing} @click=${() => this._save()}>
            ${this.adding ? t("common.add") : t("common.save_changes")}
          </button>
        </div>
      </div>
      ${this._ask
        ? html`<rt-unsaved
            @keep=${() => (this._ask = false)}
            @discard=${() => this._close()}
            @save=${() => {
              this._ask = false;
              void this._save();
            }}
          ></rt-unsaved>`
        : nothing}
    `;
  }

  static styles = [
    noSelectStyles,
    groupStyles,
    dialogStyles,
    rowStyles,
    css`
      :host {
        --dialog-w: 520px;
      }
      .info {
        font-size: 0.85rem;
        color: var(--rt-text-secondary);
        padding: 2px 4px 6px;
      }
      .guess {
        font-size: 0.85rem;
        color: var(--rt-light);
        padding: 0 4px 8px;
      }
      input:not([type]) {
        width: 11em;
      }
      select {
        max-width: 60%;
      }
      .cards {
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding: 2px 0 6px;
      }
      .cards .card {
        display: grid;
        grid-template-columns: auto 1fr;
        grid-template-rows: auto auto;
        column-gap: 12px;
        align-items: center;
        text-align: left;
        padding: 12px 14px;
        border-radius: 14px;
        border: 2px solid var(--rt-tile-border);
        background: var(--rt-button);
        font-size: 1rem;
        --mdc-icon-size: 28px;
      }
      .cards .card.on {
        border-color: var(--rt-accent);
      }
      .cards ha-icon {
        grid-row: span 2;
      }
      .cards small {
        font-size: 0.8rem;
        color: var(--rt-text-secondary);
      }
      .danger {
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        border-radius: 10px;
        padding: 8px 12px;
        color: var(--rt-light);
      }
    `,
  ];
}

if (!customElements.get("rt-pool-editor")) customElements.define("rt-pool-editor", RtPoolEditor);
