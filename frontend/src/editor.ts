// <rt-tile-editor>: edit one slot of an area's grid (dashboard edit mode).
//
// - what the slot will show: the entity's full name, area and short name
//   (read-only; "Change short name" opens the Short names dialog on it -
//   THE place short names change)
// - the picker: Map tile, empty, and entities - full names first, the short
//   name if it has one, its area; this area's entities by default, "All
//   areas" and a search box. An entity not in the catalog yet is added
//   (room_tiles.catalog_add: kind from HA, short name suggested).
// Everything is a DRAFT until "Save changes": picking an entity / Map / Empty
// and editing names only changes the draft; Save applies it all (through the
// room_tiles actions); Cancel discards it; the X / backdrop ask first if it changed.

import "./unsaved";
import { dialogStyles, noSelectStyles, groupStyles, ScrollFades } from "./ui";
import { ALL_AREAS, areaFilter, areaName, areaOf, candidatesIn, fullName, sameNamed, telling, type Candidate } from "./picker";
import { LitElement, css, html, nothing } from "lit";
import { DialogPin } from "./dialog-pin";
import type { Area, HomeAssistant, Layout, RoomTilesDoc, Tile, TileKind } from "./types";
import { t } from "./i18n";



export class RtTileEditor extends LitElement {
  /** fades where a scrolling area has more (ui.ts ScrollFades) */
  protected readonly _scrollFades = new ScrollFades(this, ".list");

  /** the dialog's top edge stays put while its content changes (dialog-pin.ts) */
  readonly dialogPin = new DialogPin(this);
  static properties = {
    _ask: { state: true },
    hass: { attribute: false },
    doc: { attribute: false },
    area: { attribute: false },
    layout: { type: String },
    slotIndex: { type: Number },
    _query: { state: true },
    _filter: { state: true },
    _busy: { state: true },
    _error: { state: true },
    _draft: { state: true },
  };

  hass?: HomeAssistant;
  doc?: RoomTilesDoc;
  area?: Area;
  layout: Layout = "5x2";
  slotIndex = 0;
  private _query = "";
  private _filter?: string; // the area filter, once changed (starts at the tile's area)
  private _busy = false;
  private _error = "";
  /** what the slot will hold once saved (undefined = unchanged) */
  private _draft?: { kind: TileKind; entity?: string };

  private get _tile(): Tile | null {
    return this.area?.tiles[this.layout]?.[this.slotIndex] ?? null;
  }

  private _opened = Date.now();

  /** "Save your changes?" showing (X / backdrop with unsaved changes) */
  private _ask = false;

  /** X / backdrop: with unsaved changes ask (Save changes / Discard / Keep
   *  editing - docs/UI.md), else just close. Cancel discards without asking. */
  private _tryClose(): void {
    if (this._tileChanged) this._ask = true;
    else this._close();
  }

  private _close(): void {
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  }

  /** The backdrop ignores the tap that opened the editor (touch screens send
   *  its click after the finger lifts, onto whatever is there by then). */
  private _scrimClick(): void {
    if (Date.now() - this._opened > 400) this._tryClose();
  }

  private async _run(fn: () => Promise<unknown>): Promise<void> {
    this._busy = true;
    this._error = "";
    try {
      await fn();
    } catch (err) {
      this._error = (err as { message?: string })?.message ?? String(err);
    } finally {
      this._busy = false;
    }
  }

  private _call(service: string, data: Record<string, unknown>): Promise<unknown> {
    return this.hass!.callService("room_tiles", service, data);
  }

  private _where(): Record<string, unknown> {
    return { area: this.area!.id, layout: this.layout, slot: this.slotIndex };
  }

  // ---- candidates (shared with the map editor: picker.ts) ---------------------------

  private _areaOf(entity: string): string | undefined {
    return areaOf(this.hass, entity);
  }

  private _candidates(): Candidate[] {
    return candidatesIn(this.hass, this.doc, this._areaFilter, this._query);
  }

  private get _areaFilter(): string {
    return this._filter ?? (this.area?.id || ALL_AREAS);
  }

  private _areaName(id?: string): string {
    return areaName(this.hass, this.doc, id);
  }

  // ---- the draft -------------------------------------------------------------------

  /** The tile as it will be after saving. */
  private get _target(): { kind: TileKind; entity?: string } {
    if (this._draft) return this._draft;
    const t = this._tile;
    return t ? { kind: t.kind, entity: t.entity } : { kind: "blank" };
  }

  private get _tileChanged(): boolean {
    const t = this._tile;
    const d = this._draft;
    if (!d) return false;
    return (t?.kind ?? "blank") !== d.kind || (t?.entity ?? undefined) !== d.entity;
  }

  /** Entity-wide settings (short name...) live in their own editor. */
  /** The Short names dialog, on this entity, ready to edit (THE place
   *  short names change). */
  private _editShortName(entity: string): void {
    this.dispatchEvent(new CustomEvent("edit-short-name", { detail: { entity }, bubbles: true, composed: true }));
  }


  private _choose(kind: TileKind, entity?: string): void {
    this._draft = { kind, entity };
    this._error = "";
  }

  private _save(): void {
    const target = this._target;
    const changed = this._tileChanged;
    void this._run(async () => {
      if (target.kind === "blank" || target.kind === "map") {
        if (changed) {
          if (target.kind === "blank") await this._call("clear_tile", this._where());
          else await this._call("set_tile", { ...this._where(), kind: "map" });
        }
      } else if (target.entity) {
        const inCatalog = this.doc?.catalog.entries.some((e) => e.entity === target.entity);
        // a new entity: kind worked out by HA, short name suggested
        if (!inCatalog) await this._call("catalog_add", { entity: target.entity });
        if (changed) await this._call("set_tile", { ...this._where(), entity: target.entity });
      }
      this._close(); // saved
    });
  }

  // ---- rendering -------------------------------------------------------------------

  render() {
    const target = this._target;
    const entry = target.entity ? this.doc?.catalog.entries.find((e) => e.entity === target.entity) : undefined;
    const dirty = this._tileChanged;
    const list = this._candidates();
    const dupes = sameNamed(list);
    const label =
      target.kind === "blank" ? t("tile_editor.empty_tile") : target.kind === "map" ? t("tile_editor.map_tile") : (target.entity ? fullName(this.hass, target.entity) : "");
    return html`
      <div class="scrim" @click=${this._scrimClick}></div>
      <div class="dialog" role="dialog" aria-label=${t("tile_editor.dialog")}>
        <div class="head">
          <div class="title">${t("tile_editor.title", { area: this.area?.short_name ?? "", n: this.slotIndex + 1 })}</div>
          <button class="x" aria-label=${t("common.close")} title=${t("common.close")} @click=${this._tryClose}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>

        <section class="group current ${this._tileChanged ? "changed" : ""}">
          <div class="group-head"><ha-icon icon="mdi:view-grid-outline"></ha-icon>${t("tile_editor.this_tile")}</div>
          <div class="row">
            <span class="k">${t("tile_editor.shows")}</span>
            <span class="full big">${label}</span>
            ${this._tileChanged ? html`<span class="tag">${t("tile_editor.changed")}</span>` : html`<span></span>`}
          </div>
          ${target.entity
            ? html`
                <div class="row">
                  <span class="k">${t("common.area")}</span><span class="full">${this._areaName(this._areaOf(target.entity))}</span><span></span>
                </div>
                <div class="row">
                  <span class="k">${t("tile_editor.short_name")}</span>
                  <span class="full">${entry?.short_name ?? html`<i>${t("tile_editor.suggested")}</i>`}</span>
                  ${entry
                    ? html`<button class="link" @click=${() => this._editShortName(target.entity!)}>${t("tile_editor.change_short")}</button>`
                    : html`<span></span>`}
                </div>
              `
            : nothing}
        </section>

        <section class="group picker">
          <div class="group-head"><ha-icon icon="mdi:magnify"></ha-icon>${t("tile_editor.change_entity")}</div>
          <div class="search">
            <input
              type="search"
              placeholder=${t("common.search_entities")}
              .value=${this._query}
              @input=${(e: Event) => (this._query = (e.target as HTMLInputElement).value)}
            />
            ${areaFilter(this.hass, this.doc, this._areaFilter, (v) => (this._filter = v))}
          </div>
          <div class="specials">
            <button class=${target.kind === "map" ? "on" : ""} ?disabled=${this._busy} @click=${() => this._choose("map")}>
              <ha-icon icon="mdi:floor-plan"></ha-icon> ${t("tile_editor.map")}
            </button>
            <button class=${target.kind === "blank" ? "on" : ""} ?disabled=${this._busy} @click=${() => this._choose("blank")}>
              <ha-icon icon="mdi:checkbox-blank-outline"></ha-icon> ${t("tile_editor.empty")}
            </button>
          </div>
          <div class="list">
            ${list.length
              ? list.map(
                  (c) => html`<button
                    class="cand ${target.entity === c.entity ? "on" : ""}"
                    ?disabled=${this._busy}
                    @click=${() => this._choose(this._kindFor(c.entity), c.entity)}
                  >
                    <span class="full">${c.full}</span>
                    <span class="meta">${c.short ? html`<b>${c.short}</b> · ` : ""}${this._areaName(c.area)}</span>
                    ${dupes.has(c.entity) ? html`<span class="meta id">${telling(this.hass, c.entity)}</span>` : nothing}
                  </button>`,
                )
              : this._areaFilter === ALL_AREAS
              ? html`<div class="hint">${t("common.no_matching_entities")}</div>`
              : html`<div class="hint">
                  ${this._query.trim() ? t("common.nothing_in_area") : t("common.no_entities_in_area")}
                  <button class="link" @click=${() => (this._filter = ALL_AREAS)}>${t("common.search_all_areas")}</button>
                </div>`}
          </div>
        </section>

        ${this._error ? html`<div class="hint warn">${this._error}</div>` : nothing}
        <div class="footer">
          <button class="secondary" ?disabled=${this._busy} @click=${this._close}>${t("common.cancel")}</button>
          <button class="primary" ?disabled=${this._busy || !dirty} @click=${() => this._save()}>${t("common.save_changes")}</button>
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

  /** The kind a picked entity's tile gets: the catalog's, else worked out from
   *  HA when saved (shown as the entity's domain kind meanwhile). */
  private _kindFor(entity: string): TileKind {
    const entry = this.doc?.catalog.entries.find((e) => e.entity === entity);
    if (entry) return entry.kind;
    const domain = entity.split(".")[0];
    return ({ light: "dimmable_light", fan: "fan", cover: "cover", lock: "lock", climate: "climate", vacuum: "vacuum", sensor: "appliance", scene: "scene", script: "script" } as Record<string, TileKind>)[domain] ?? "switch";
  }

  static styles = [noSelectStyles, groupStyles, 
    dialogStyles,
    css`
      :host {
        --dialog-w: 520px;
      }
    section {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .group.picker {
      gap: 8px;
    }
    .row {
      display: grid;
      grid-template-columns: 7.5em 1fr auto;
      gap: 8px;
      align-items: center;
    }
    .k {
      color: var(--rt-text-secondary);
      font-size: 0.9rem;
    }
    .full {
      overflow-wrap: anywhere;
    }
    .count {
      font-size: 0.8rem;
      color: var(--rt-text-secondary);
    }
    .hint.warn {
      color: var(--rt-light);
    }
    .current.changed {
      outline: 2px solid var(--rt-accent);
    }
    .big {
      font-weight: 700;
    }
    .tag {
      font-size: 0.75rem;
      padding: 2px 8px;
      border-radius: 8px;
      background: var(--rt-accent);
      color: var(--rt-on-accent);
    }
    .pick-title {
      font-weight: 700;
    }
    .specials button.on {
      border-color: var(--rt-accent);
      background: var(--rt-accent);
      color: var(--rt-on-accent);
    }
    .actions button,
    .specials button {
      border-radius: 10px;
      padding: 7px 12px;
      border: 1px solid var(--rt-tile-border);
      background: var(--rt-button);
    }
    .actions .primary {
      background: var(--rt-accent);
      color: var(--rt-on-accent);
      border-color: var(--rt-accent);
    }
    .picker {
      min-height: 0;
      flex: 1;
    }
    .search {
      display: flex;
      gap: 10px;
      align-items: center;
    }
    .search input[type="search"] {
      flex: 1;
    }
    .area-filter {
      max-width: 45%;
    }
    .specials {
      display: flex;
      gap: 8px;
    }
    .specials button {
      display: flex;
      align-items: center;
      gap: 6px;
      --mdc-icon-size: 18px;
    }
    .cand {
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 2px;
      text-align: left;
      padding: 8px 10px;
      border-radius: 10px;
      border: 1px solid transparent;
      background: var(--rt-button);
    }
    .cand.on {
      border-color: var(--rt-accent);
    }
    .cand .meta {
      font-size: 0.8rem;
      color: var(--rt-text-secondary);
    }
    .meta.id {
      overflow-wrap: anywhere;
      opacity: 0.85;
    }
    `,
  ];
}

if (!customElements.get("rt-tile-editor")) customElements.define("rt-tile-editor", RtTileEditor);
