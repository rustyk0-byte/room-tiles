// <rt-area-settings>: Room Tiles' areas - which HA areas show and their
// order (short names: the Short names dialog) - and "include new areas
// automatically"; each area's
// "Area lights..." opens <rt-area-lights>. Drafts: nothing changes until
// "Save changes"; Cancel discards; X / the backdrop ask first if anything changed.

import { fullName } from "./picker";
import { LitElement, css, html, nothing } from "lit";
import { DialogPin } from "./dialog-pin";
import type { Area, HomeAssistant, RoomTilesDoc } from "./types";
import { dialogStyles, rowStyles, toggle, noSelectStyles, groupStyles, ScrollFades } from "./ui";
import "./unsaved";
import { t } from "./i18n";


interface Row {
  id: string;
  name: string;
  short: string;
  hidden: boolean;
}

export class RtAreaSettings extends LitElement {
  /** fades where a scrolling area has more (ui.ts ScrollFades) */
  protected readonly _scrollFades = new ScrollFades(this, ".list");

  /** the dialog's top edge stays put while its content changes (dialog-pin.ts) */
  readonly dialogPin = new DialogPin(this);
  static properties = {
    _ask: { state: true },
    hass: { attribute: false },
    doc: { attribute: false },
    _rows: { state: true },
    _auto: { state: true },
    _busy: { state: true },
    _error: { state: true },
  };

  hass?: HomeAssistant;
  doc?: RoomTilesDoc;
  private _rows?: Row[]; // the draft (undefined = not touched)
  private _auto?: boolean;
  private _busy = false;
  private _error = "";
  private _opened = Date.now();

  private get _current(): Row[] {
    return (this.doc?.areas ?? []).map((a: Area) => ({ id: a.id, name: a.name, short: a.short_name, hidden: a.hidden }));
  }

  private get _view(): Row[] {
    return this._rows ?? this._current;
  }

  private _edit(fn: (rows: Row[]) => void): void {
    const rows = this._view.map((r) => ({ ...r }));
    fn(rows);
    this._rows = rows;
  }

  /** Sort A-Z: every area by name (the user's language) - a draft change
   *  like the arrows (Save changes keeps it, Cancel drops it). */
  private _sortByName(): void {
    const lang = this._lang;
    this._edit((rows) => rows.sort((a, b) => a.name.localeCompare(b.name, lang, { sensitivity: "base" })));
  }

  private get _sorted(): boolean {
    const lang = this._lang;
    const rows = this._view;
    return rows.every((r, i) => i === 0 || rows[i - 1].name.localeCompare(r.name, lang, { sensitivity: "base" }) <= 0);
  }

  private get _lang(): string | undefined {
    return (this.hass as { locale?: { language?: string } } | undefined)?.locale?.language;
  }

  /** Turned back on here, and no map has a room for it: what that means. */
  private _noRoomNote(r: Row) {
    const was = this._current.find((o) => o.id === r.id);
    if (r.hidden || !was?.hidden) return nothing;
    const onMap = ((this.doc?.maps ?? []) as { zones: { area: string | null; vacuum?: string | null }[] }[]).some((m) =>
      m.zones.some((z) => z.area === r.id && !z.vacuum),
    );
    if (onMap) return nothing;
    return html`<div class="note">${t("areas.not_on_map")}</div>`;
  }

  private _move(i: number, by: number): void {
    this._edit((rows) => {
      const j = i + by;
      if (j < 0 || j >= rows.length) return;
      [rows[i], rows[j]] = [rows[j], rows[i]];
    });
  }

  /** "Save your changes?" showing (X / backdrop with unsaved changes) */
  private _ask = false;

  /** X / backdrop: with unsaved changes ask (Save changes / Discard / Keep
   *  editing - docs/UI.md), else just close. Cancel discards without asking. */
  private _tryClose(): void {
    if (this._dirty) this._ask = true;
    else this._close();
  }

  private _close(): void {
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  }

  private _scrimClick(): void {
    if (Date.now() - this._opened > 400) this._tryClose();
  }

  private get _dirty(): boolean {
    const auto = this._auto !== undefined && this._auto !== this.doc?.settings.auto_add_areas;
    return auto || (this._rows !== undefined && JSON.stringify(this._rows) !== JSON.stringify(this._current));
  }

  private async _save(): Promise<void> {
    const hass = this.hass!;
    const now = this._current;
    const rows = this._view;
    this._busy = true;
    this._error = "";
    try {
      // any reorder: every area's final position, in order (exact result)
      const reordered = rows.map((r) => r.id).join() !== now.map((o) => o.id).join();
      for (const [i, r] of rows.entries()) {
        const old = now.find((o) => o.id === r.id);
        if (!old) continue;
        if (reordered || r.hidden !== old.hidden) {
          await hass.callService("room_tiles", "set_area", {
            area: r.id,
            hidden: r.hidden,
            ...(reordered ? { position: i } : {}),
          });
        }
      }
      if (this._auto !== undefined && this._auto !== this.doc?.settings.auto_add_areas) {
        await hass.callService("room_tiles", "set_settings", { auto_add_areas: this._auto });
      }
      this._close();
    } catch (err) {
      this._error = (err as { message?: string })?.message ?? String(err);
    } finally {
      this._busy = false;
    }
  }

  private _lights(id: string): void {
    this.dispatchEvent(new CustomEvent("area-lights", { detail: { area: id }, bubbles: true, composed: true }));
  }

  render() {
    const rows = this._view;
    const auto = this._auto ?? this.doc?.settings.auto_add_areas ?? false;
    return html`
      <div class="scrim" @click=${this._scrimClick}></div>
      <div class="dialog" role="dialog" aria-label=${t("areas.title")}>
        <div class="head">
          <div class="title">${t("areas.title")}</div>
          <button class="x" aria-label=${t("common.close")} title=${t("common.close")} @click=${this._tryClose}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        <div class="intro">${t("areas.intro")}</div>
        <div class="list">
          <div class="group">
            <div class="group-head"><ha-icon icon="mdi:plus-circle-outline"></ha-icon>${t("areas.new_areas")}</div>
            <div class="setting">
              <span class="label">${t("areas.auto_add")}</span>
              ${toggle(auto, (on) => (this._auto = on), t("areas.auto_add"))}
            </div>
          </div>
          <div class="group areas">
          <div class="group-head">
            <ha-icon icon="mdi:floor-plan"></ha-icon>${t("areas.title")}
            <button class="sort" title=${t("areas.sort_tip")} ?disabled=${this._sorted} @click=${() => this._sortByName()}>
              <ha-icon icon="mdi:sort-alphabetical-ascending"></ha-icon>${t("areas.sort")}
            </button>
          </div>
          ${rows.map(
            (r, i) => html`<div class="area ${r.hidden ? "hidden" : ""}">
              <span class="show" title=${r.hidden ? t("areas.hidden") : t("areas.shown")}>
                ${toggle(!r.hidden, (on) => this._edit((rs) => (rs[i].hidden = !on)), t("areas.show_name", { name: r.name }))}
              </span>
              <div class="names">
                <div class="full">${r.name}</div>
              </div>
              ${this._noRoomNote(r)}
              <div class="side">
                <button class="mini" ?disabled=${i === 0} aria-label=${t("common.move_up")} @click=${() => this._move(i, -1)}><ha-icon icon="mdi:chevron-up"></ha-icon></button>
                <button class="mini" ?disabled=${i === rows.length - 1} aria-label=${t("common.move_down")} @click=${() => this._move(i, 1)}><ha-icon icon="mdi:chevron-down"></ha-icon></button>
                <button class="lights" ?disabled=${r.hidden} @click=${() => this._lights(r.id)}>${t("areas.area_lights_btn")}</button>
              </div>
            </div>`,
          )}
          </div>
        </div>
        ${this._error ? html`<div class="warn">${this._error}</div>` : nothing}
        <div class="footer">
          <button ?disabled=${this._busy} @click=${this._close}>${t("common.cancel")}</button>
          <button class="primary" ?disabled=${this._busy || !this._dirty} @click=${() => this._save()}>${t("common.save_changes")}</button>
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

  static styles = [noSelectStyles, groupStyles, 
    dialogStyles,
    rowStyles,
    css`
      :host {
        --dialog-w: 560px;
      }
      .group-head .sort {
        margin-left: auto;
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 4px 10px;
        border-radius: 8px;
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        color: var(--rt-text);
        font-size: 0.85rem;
        font-weight: 400;
        text-transform: none;
        letter-spacing: 0;
        --mdc-icon-size: 18px;
      }
      .group-head .sort:disabled {
        opacity: 0.45;
      }
      .area {
        display: grid;
        grid-template-columns: auto 1fr auto;
        gap: 10px;
        align-items: center;
        padding: 8px 10px;
        border-radius: 12px;
        background: var(--rt-panel-dark);
      }
      .group.areas {
        gap: 6px;
      }
      .group .area {
        background: var(--rt-dialog);
      }
      .area .note {
        grid-column: 1 / -1;
        font-size: 0.8rem;
        color: var(--rt-text-secondary);
        padding: 2px 4px 0;
      }
      .area.hidden .names {
        opacity: 0.5;
      }
      .full {
        font-size: 0.85rem;
        color: var(--rt-text-secondary);
      }
      .shortrow {
        display: flex;
        gap: 6px;
        align-items: center;
      }
      .shortrow input {
        width: 11em;
      }
      .count {
        font-size: 0.75rem;
        color: var(--rt-text-secondary);
      }
      .side {
        display: flex;
        gap: 4px;
        align-items: center;
        flex-wrap: wrap;
        justify-content: flex-end;
      }
      .mini {
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        border-radius: 8px;
        padding: 2px;
        --mdc-icon-size: 22px;
      }
      .lights {
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        border-radius: 8px;
        padding: 5px 9px;
        font-size: 0.85rem;
      }
    `,
  ];
}

/** One area's lights button: every light in the HA area except the unticked
 *  ones, or one chosen entity. */
export class RtAreaLights extends LitElement {
  /** fades where a scrolling area has more (ui.ts ScrollFades) */
  protected readonly _scrollFades = new ScrollFades(this, ".list");

  /** the dialog's top edge stays put while its content changes (dialog-pin.ts) */
  readonly dialogPin = new DialogPin(this);
  static properties = {
    _ask: { state: true },
    hass: { attribute: false },
    doc: { attribute: false },
    area: { type: String },
    _mode: { state: true },
    _entity: { state: true },
    _exclude: { state: true },
    _busy: { state: true },
    _error: { state: true },
  };

  hass?: HomeAssistant;
  doc?: RoomTilesDoc;
  area = "";
  private _mode?: "area" | "entity" | "none";
  private _entity?: string;
  private _exclude?: string[];
  private _busy = false;
  private _error = "";
  private _opened = Date.now();

  private get _a(): Area | undefined {
    return this.doc?.areas.find((x) => x.id === this.area);
  }

  /** The INDIVIDUAL lights in the HA area, by HA's area-targeting rules
   *  (own area or the device's; not hidden / settings entities) - no light
   *  groups (they only repeat lights already here) - like arealights.py. */
  private _lightsHere(): string[] {
    const hass = this.hass;
    if (!hass?.entities) return [];
    return Object.values(hass.entities)
      .filter((e) => e.entity_id.startsWith("light.") && !e.hidden && !e.entity_category)
      // not Room Tiles' own "<Area> Lights" light - it IS these lights
      .filter((e) => (e as { platform?: string }).platform !== "room_tiles")
      // nor light groups
      .filter((e) => (e as { platform?: string }).platform !== "group" && !Array.isArray(hass.states[e.entity_id]?.attributes.entity_id))
      .filter((e) => (e.area_id ?? (e.device_id ? hass.devices?.[e.device_id]?.area_id : undefined)) === this.area)
      .map((e) => e.entity_id)
      .sort((a, b) => this._name(a).localeCompare(this._name(b)));
  }

  /** The area's lights mode as stored. */
  private _current(a: Area): "area" | "entity" | "none" {
    return a.lights ? "entity" : a.light_entity === false ? "none" : "area";
  }

  private _name(e: string): string {
    return fullName(this.hass, e);
  }

  /** "Save your changes?" showing (X / backdrop with unsaved changes) */
  private _ask = false;

  /** X / backdrop: with unsaved changes ask (Save changes / Discard / Keep
   *  editing - docs/UI.md), else just close. Cancel discards without asking. */
  private _tryClose(): void {
    if (this._mode !== undefined || this._entity !== undefined || this._exclude !== undefined) this._ask = true;
    else this._close();
  }

  private _close(): void {
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  }

  private _scrimClick(): void {
    if (Date.now() - this._opened > 400) this._tryClose();
  }

  private async _save(): Promise<void> {
    const a = this._a;
    if (!a) return;
    const mode = this._mode ?? this._current(a);
    this._busy = true;
    this._error = "";
    try {
      await this.hass!.callService("room_tiles", "set_area_lights", {
        area: a.id,
        entity: mode === "entity" ? this._entity ?? a.lights ?? "" : "",
        exclude: this._exclude ?? a.lights_exclude,
      });
      // "None": no lights button (and no Room Tiles light) for the area
      if ((mode === "none") !== (a.light_entity === false))
        await this.hass!.callService("room_tiles", "set_area_light_entity", { area: a.id, enabled: mode !== "none" });
      this._close();
    } catch (err) {
      this._error = (err as { message?: string })?.message ?? String(err);
    } finally {
      this._busy = false;
    }
  }

  render() {
    const a = this._a;
    if (!a) return nothing;
    const mode = this._mode ?? this._current(a);
    const exclude = new Set(this._exclude ?? a.lights_exclude);
    const lights = this._lightsHere();
    const entity = this._entity ?? a.lights ?? "";
    const allLights = Object.keys(this.hass?.states ?? {})
      .filter((e) => e.startsWith("light.") || e.startsWith("switch.") || e.startsWith("group."))
      .sort((x, y) => this._name(x).localeCompare(this._name(y)));
    const dirty = this._mode !== undefined || this._entity !== undefined || this._exclude !== undefined;
    return html`
      <div class="scrim" style="--z:30" @click=${this._scrimClick}></div>
      <div class="dialog" style="--z:30" role="dialog" aria-label=${t("area_lights.dialog")}>
        <div class="head">
          <div class="title">${t("area_lights.title", { area: a.short_name })}</div>
          <button class="x" aria-label=${t("common.close")} title=${t("common.close")} @click=${this._tryClose}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        <div class="intro">${t("area_lights.intro")}</div>
        <div class="list">
        <div class="group">
        <label class="check group-head">
          <input type="radio" name="mode" .checked=${mode === "area"} @change=${() => (this._mode = "area")} />
          ${t("area_lights.all")}
        </label>
        <div class="intro">${t("area_lights.all_info")}</div>
        ${mode === "area"
          ? html`<div class="lights-list">
              ${lights.length
                ? lights.map(
                    (e) => html`<label class="check light">
                      <input
                        type="checkbox"
                        .checked=${!exclude.has(e)}
                        @change=${(ev: Event) => {
                          const next = new Set(exclude);
                          if ((ev.target as HTMLInputElement).checked) next.delete(e);
                          else next.add(e);
                          this._exclude = [...next].sort();
                        }}
                      />
                      <span>${this._name(e)} <small>${e}</small></span>
                    </label>`,
                  )
                : html`<div class="intro">${t("area_lights.none_in_area")}</div>`}
            </div>`
          : nothing}
        </div>
        <div class="group">
        <label class="check group-head">
          <input type="radio" name="mode" .checked=${mode === "entity"} @change=${() => (this._mode = "entity")} />
          ${t("area_lights.one")}
        </label>
        ${mode === "entity"
          ? html`<select
              .value=${entity}
              @change=${(e: Event) => (this._entity = (e.target as HTMLSelectElement).value)}
            >
              <option value="">${t("common.choose")}</option>
              ${allLights.map((e) => html`<option value=${e} ?selected=${e === entity}>${this._name(e)} (${e})</option>`)}
            </select>`
          : nothing}
        </div>
        <div class="group">
        <label class="check group-head">
          <input type="radio" name="mode" .checked=${mode === "none"} @change=${() => (this._mode = "none")} />
          ${t("area_lights.no_button")}
        </label>
        ${mode === "none" ? html`<div class="intro">${t("area_lights.no_button_info")}</div>` : nothing}
        </div>
        </div>
        ${this._error ? html`<div class="warn">${this._error}</div>` : nothing}
        <div class="footer">
          <button ?disabled=${this._busy} @click=${this._close}>${t("common.cancel")}</button>
          <button class="primary" ?disabled=${this._busy || !dirty || (mode === "entity" && !entity)} @click=${() => this._save()}>${t("common.save_changes")}</button>
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

  static styles = [noSelectStyles, groupStyles, 
    dialogStyles,
    css`
      .lights-list {
        display: flex;
        flex-direction: column;
        gap: 4px;
        padding: 4px 0;
      }
      .light {
        padding: 6px 8px;
        border-radius: 8px;
        background: var(--rt-panel-dark);
      }
      .light small {
        color: var(--rt-text-secondary);
        margin-left: 6px;
      }
      select {
        font: inherit;
        color: var(--rt-text);
        background: var(--rt-button);
        border: 1px solid var(--rt-tile-border);
        border-radius: 8px;
        padding: 7px;
      }
    `,
  ];
}

if (!customElements.get("rt-area-settings")) customElements.define("rt-area-settings", RtAreaSettings);
if (!customElements.get("rt-area-lights")) customElements.define("rt-area-lights", RtAreaLights);
