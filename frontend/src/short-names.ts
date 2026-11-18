// <rt-short-names>: THE place short names are checked and changed - every
// area's and every entity's, with its full name; the ones waiting for review
// first ("check"). Tap a name to change it in place; Accept all confirms
// every waiting one as it is. Opened from the settings menu, and from the
// tile editor's "Change short name" (`focusEntity`, open to edit).

import { fullName } from "./picker";
import { dialogStyles, noSelectStyles, groupStyles, rowStyles, toggle, ScrollFades } from "./ui";
import { DEFAULT_THEME, type ThemeName } from "./theme";
import { LitElement, css, html, nothing, type PropertyValues, type TemplateResult } from "lit";
import { DialogPin } from "./dialog-pin";
import type { HomeAssistant, RoomTilesDoc } from "./types";
import { t, thn } from "./i18n";

const MAX_SHORT = 15;

interface Row {
  kind: "area" | "entity";
  id: string;
  short: string;
  full: string;
  where: string;
  review: boolean;
}

export class RtShortNames extends LitElement {
  /** fades where a scrolling area has more (ui.ts ScrollFades) */
  protected readonly _scrollFades = new ScrollFades(this, ".list");

  /** the dialog's top edge stays put while its content changes (dialog-pin.ts) */
  readonly dialogPin = new DialogPin(this);
  static properties = {
    hass: { attribute: false },
    doc: { attribute: false },
    focusEntity: { type: String },
    theme: { type: String },
    _query: { state: true },
    _reviewOnly: { state: true },
    _sortShort: { state: true },
    _busy: { state: true },
    _left: { state: true },
    _editing: { state: true },
    _value: { state: true },
    _error: { state: true },
  };

  hass?: HomeAssistant;
  doc?: RoomTilesDoc;
  /** an entity to open on, ready to edit (from the tile editor) */
  focusEntity?: string;
  theme: ThemeName = DEFAULT_THEME;
  private _query = "";
  private _reviewOnly = false;
  private _sortShort = false; // (A-Z by short name instead of full name)
  private _busy = false;
  private _left?: string[]; // after Accept all: the ones too wide to keep
  private _editing?: string; // "<kind>:<id>" being changed
  private _value = "";
  private _error = "";
  private _opened = Date.now();

  protected willUpdate(changed: PropertyValues): void {
    if (changed.has("focusEntity") && this.focusEntity) {
      const entry = this.doc?.catalog.entries.find((e) => e.entity === this.focusEntity);
      if (entry) this._startEdit({ kind: "entity", id: entry.entity, short: entry.short_name } as Row);
    }
  }

  protected updated(changed: PropertyValues): void {
    if (changed.has("_editing") && this._editing) {
      const input = this.renderRoot.querySelector<HTMLInputElement>(".row.editing input");
      input?.scrollIntoView({ block: "nearest" });
      input?.focus();
    }
  }

  private _close(): void {
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  }

  private _scrimClick(): void {
    if (Date.now() - this._opened > 400) this._close();
  }

  private _areaOf(entity: string): string {
    const e = this.hass?.entities?.[entity];
    const id = e?.area_id ?? (e?.device_id ? this.hass?.devices?.[e.device_id]?.area_id : undefined);
    if (!id) return t("common.no_area");
    return this.doc?.areas.find((a) => a.id === id)?.name ?? this.hass?.areas?.[id]?.name ?? id;
  }

  private _rows(): { areas: Row[]; entities: Row[] } {
    const q = this._query.trim().toLowerCase();
    const keep = (r: Row) =>
      (!this._reviewOnly || r.review) && (!q || r.full.toLowerCase().includes(q) || r.short.toLowerCase().includes(q) || r.id.includes(q));
    // waiting for review first, then A-Z by full name - or by short name
    // (ties: by full name)
    const order = (a: Row, b: Row) =>
      Number(b.review) - Number(a.review) ||
      (this._sortShort ? a.short.localeCompare(b.short) : 0) ||
      a.full.localeCompare(b.full);
    const areas: Row[] = (this.doc?.areas ?? [])
      .filter((a) => !a.hidden)
      .map((a) => ({ kind: "area" as const, id: a.id, short: a.short_name, full: a.name, where: t("short.area"), review: a.review }));
    const entities: Row[] = (this.doc?.catalog.entries ?? []).map((e) => ({
      kind: "entity" as const,
      id: e.entity,
      short: e.short_name,
      full: fullName(this.hass, e.entity),
      where: this._areaOf(e.entity),
      review: e.review,
    }));
    return { areas: areas.filter(keep).sort(order), entities: entities.filter(keep).sort(order) };
  }

  private _startEdit(r: Row): void {
    this._editing = `${r.kind}:${r.id}`;
    this._value = r.short;
    this._error = "";
  }

  /** Suggest: Room Tiles' shortening run on the full name now (its
   *  language's rules + English's) - into the field, not saved. */
  private async _suggest(r: Row): Promise<void> {
    if (!this.hass) return;
    this._busy = true;
    try {
      const res = await this.hass.connection.sendMessagePromise?.<{ response?: { short_name?: string } }>({
        type: "call_service",
        domain: "room_tiles",
        service: "suggest_short_name",
        service_data: { [r.kind === "area" ? "area" : "entity"]: r.id },
        return_response: true,
      });
      const short = res?.response?.short_name;
      if (short) {
        this._value = short;
        this._error = "";
      }
    } catch (err) {
      this._error = (err as { message?: string })?.message ?? String(err);
    } finally {
      this._busy = false;
    }
  }

  private async _saveEdit(r: Row): Promise<void> {
    const v = this._value.trim();
    if (!v || v.length > MAX_SHORT) {
      this._error = t("short.length", { max: MAX_SHORT });
      return;
    }
    this._busy = true;
    try {
      await this.hass!.callService("room_tiles", "set_short_name", { [r.kind === "area" ? "area" : "entity"]: r.id, short_name: v });
      this._editing = undefined;
    } catch (err) {
      // e.g. too wide for a tile - the integration's own message
      this._error = (err as { message?: string })?.message ?? String(err);
    } finally {
      this._busy = false;
    }
  }

  /** Accept all: every short name still waiting is confirmed as it is - one
   *  press, after changing any you don't like. Too-wide ones stay waiting. */
  private async _acceptAll(): Promise<void> {
    if (!this.hass) return;
    this._busy = true;
    try {
      const res = await this.hass.connection.sendMessagePromise?.<{ response?: { left?: string[] } }>({
        type: "call_service",
        domain: "room_tiles",
        service: "accept_short_names",
        service_data: {},
        return_response: true,
      });
      this._left = res?.response?.left ?? [];
    } finally {
      this._busy = false;
    }
  }

  private _row(r: Row): TemplateResult {
    const key = `${r.kind}:${r.id}`;
    if (this._editing === key)
      return html`<div class="row editing">
        <input
          .value=${this._value}
          maxlength=${MAX_SHORT}
          aria-label=${t("short.field", { name: r.full })}
          @input=${(e: Event) => (this._value = (e.target as HTMLInputElement).value)}
          @keydown=${(e: KeyboardEvent) => {
            if (e.key === "Enter") void this._saveEdit(r);
            if (e.key === "Escape") this._editing = undefined;
          }}
        />
        <span class="full">${r.full}<span class="area"> · ${r.where}</span></span>
        <span class="actions">
          <span class="count">${this._value.length}/${MAX_SHORT}</span>
          <button title=${t("short.suggest_tip")} ?disabled=${this._busy} @click=${() => this._suggest(r)}>
            <ha-icon icon="mdi:auto-fix"></ha-icon> ${t("short.suggest")}
          </button>
          <button @click=${() => (this._editing = undefined)}>${t("common.cancel")}</button>
          <button class="primary" ?disabled=${this._busy} @click=${() => this._saveEdit(r)}>${t("common.save")}</button>
        </span>
        ${this._error ? html`<div class="warn">${this._error}</div>` : nothing}
      </div>`;
    return html`<button class="row ${r.review ? "review" : ""}" @click=${() => this._startEdit(r)}>
      <span class="short">${r.short}${r.review ? html` <span class="tag">${t("short.check")}</span>` : ""}</span>
      <span class="full">${r.full}<span class="area"> · ${r.where}</span></span>
      <ha-icon class="pen" icon="mdi:pencil"></ha-icon>
    </button>`;
  }

  render() {
    const { areas, entities } = this._rows();
    const waiting = (this.doc?.catalog.entries ?? []).filter((e) => e.review).length + (this.doc?.areas ?? []).filter((a) => a.review && !a.hidden).length;
    return html`
      <div class="scrim" @click=${this._scrimClick}></div>
      <div class="dialog" role="dialog" aria-label=${t("short.title")}>
        <div class="head">
          <div class="title">${t("short.title")}</div>
          <button class="x" aria-label=${t("common.close")} @click=${this._close}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        <div class="intro">
          ${t("short.intro", { max: MAX_SHORT })} ${waiting ? thn("short.waiting", waiting, { n: html`<b>${waiting}</b>` }) : nothing}
        </div>
        <div class="search">
          <input type="search" placeholder=${t("common.search")} .value=${this._query} @input=${(e: Event) => (this._query = (e.target as HTMLInputElement).value)} />
        </div>
        <div class="setting">
          <span class="label">${t("short.review_only")}</span>
          ${toggle(this._reviewOnly, (on) => (this._reviewOnly = on), t("short.review_only"), this.theme)}
        </div>
        <div class="setting">
          <span class="label">${t("short.sort_short")}</span>
          ${toggle(this._sortShort, (on) => (this._sortShort = on), t("short.sort_short"), this.theme)}
        </div>
        <div class="list">
          ${areas.length
            ? html`<div class="group names">
                <div class="group-head"><ha-icon icon="mdi:floor-plan"></ha-icon>${t("short.areas")}</div>
                ${areas.map((r) => this._row(r))}
              </div>`
            : nothing}
          ${entities.length
            ? html`<div class="group names">
                <div class="group-head"><ha-icon icon="mdi:form-textbox"></ha-icon>${t("short.entities")}</div>
                ${entities.map((r) => this._row(r))}
              </div>`
            : nothing}
        </div>
        ${waiting || this._left?.length
          ? html`<div class="footer">
              <span class="hint"
                >${this._left?.length
                  ? thn("short.too_wide", this._left.length, { n: html`<b>${this._left.length}</b>` })
                  : nothing}</span
              >
              <button class="primary" ?disabled=${this._busy || !waiting} @click=${() => this._acceptAll()}>
                ${waiting ? t("short.accept_all_n", { n: waiting }) : t("short.accept_all")}
              </button>
            </div>`
          : nothing}
      </div>
    `;
  }

  static styles = [
    noSelectStyles,
    groupStyles,
    rowStyles,
    dialogStyles,
    css`
      :host {
        --dialog-w: 600px;
      }
      .footer .hint {
        flex: 1;
        align-self: center;
      }
      .search {
        display: flex;
        gap: 10px;
        align-items: center;
      }
      .names {
        gap: 6px;
      }
      .row {
        display: grid;
        grid-template-columns: 10.5em 1fr auto;
        gap: 10px;
        align-items: center;
        text-align: left;
        padding: 8px 10px;
        border-radius: 10px;
        border: 1px solid transparent;
        background: var(--rt-button);
        width: 100%;
        box-sizing: border-box;
      }
      .row.review {
        border-color: var(--rt-light);
      }
      .row.editing {
        border-color: var(--rt-accent);
        grid-template-columns: 10.5em 1fr;
      }
      .row.editing input {
        min-width: 0;
      }
      .row.editing .actions {
        grid-column: 1 / -1;
        display: flex;
        justify-content: flex-end;
        align-items: center;
        gap: 8px;
      }
      .row.editing .warn {
        grid-column: 1 / -1;
      }
      .row.editing .actions button {
        border-radius: 10px;
        padding: 7px 14px;
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        color: var(--rt-text);
      }
      .row.editing .actions .primary {
        background: var(--rt-accent);
        color: var(--rt-on-accent);
        border-color: var(--rt-accent);
      }
      .count {
        font-size: 0.8rem;
        color: var(--rt-text-secondary);
        margin-right: auto;
      }
      .short {
        font-weight: 700;
        white-space: nowrap;
      }
      .full {
        overflow-wrap: anywhere;
        font-size: 0.9rem;
      }
      .area {
        font-size: 0.8rem;
        color: var(--rt-text-secondary);
      }
      .pen {
        --mdc-icon-size: 18px;
        color: var(--rt-text-secondary);
      }
      .tag {
        font-size: 0.7rem;
        font-weight: 400;
        padding: 1px 6px;
        border-radius: 8px;
        background: var(--rt-light);
        color: var(--rt-on-bright);
      }
      @media (max-width: 520px) {
        .row {
          grid-template-columns: 1fr auto;
        }
        .full {
          grid-column: 1 / -1;
          grid-row: 2;
        }
      }
    `,
  ];
}

if (!customElements.get("rt-short-names")) customElements.define("rt-short-names", RtShortNames);
