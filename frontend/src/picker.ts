// Shared entity-picking logic: which entities can be placed (tiles, map
// markers), their full names, short names and areas - one implementation for
// the tile editor and the map editor's "Add", so they list the same things.
// Plus <rt-entity-picker>, the stand-alone picker dialog (map "Add").

import { LitElement, css, html, type TemplateResult } from "lit";
import { DialogPin } from "./dialog-pin";
import type { HomeAssistant, RoomTilesDoc } from "./types";
import { dialogStyles, noSelectStyles, ScrollFades } from "./ui";
import { t } from "./i18n";

export const PICKABLE_DOMAINS = new Set(["light", "switch", "input_boolean", "fan", "cover", "lock", "climate", "vacuum", "scene", "script"]);

/** A script that needs inputs (a required field) can't run from one tap. */
export function needsInputs(hass: HomeAssistant | undefined, id: string): boolean {
  if (!id.startsWith("script.")) return false;
  const fields = hass?.services?.script?.[id.slice(7)]?.fields;
  return Object.values(fields ?? {}).some((f) => f?.required === true);
}

export interface Candidate {
  entity: string;
  full: string; // HA's full name
  short?: string; // Room Tiles short name, if in the catalog
  area?: string; // HA area id (own or the device's)
}

export function areaOf(hass: HomeAssistant | undefined, entity: string): string | undefined {
  const e = hass?.entities?.[entity];
  if (!e) return undefined;
  if (e.area_id) return e.area_id;
  return e.device_id ? hass?.devices?.[e.device_id]?.area_id ?? undefined : undefined;
}

/** The full name to show for an entity: HA's friendly name - but for Room
 *  Tiles' own entities the name Room Tiles gave it (its `own_name`
 *  attribute, "Dishwasher"). HA composes friendly names its own way, and
 *  each instance can change how (e.g. the device's name in front - Room
 *  Tiles' tile sensors sit on their appliance's / pool's / vacuum's device),
 *  so they're never taken apart here. */
export function fullName(hass: HomeAssistant | undefined, id: string): string {
  const st = hass?.states[id];
  const own = st?.attributes.own_name;
  if (typeof own === "string" && own && (hass?.entities?.[id] as { platform?: string } | undefined)?.platform === "room_tiles") return own;
  return (st?.attributes.friendly_name as string | undefined) ?? id;
}

export function areaName(hass: HomeAssistant | undefined, doc: RoomTilesDoc | undefined, id?: string): string {
  if (!id) return t("common.no_area");
  return doc?.areas.find((a) => a.id === id)?.name ?? hass?.areas?.[id]?.name ?? id;
}

/** The entities Room Tiles builds (or would build - found, or ignored) its
 *  own tiles from - appliance units' state / time, pool / spa temperatures, heaters, pumps and spa mode, robot
 *  vacuums and their error sensors. Their tile is Room Tiles' sensor, so they
 *  aren't offered themselves: a marker opens ITS tile, one to one. (What only
 *  empties a finished appliance - a door contact, motion in the area - isn't
 *  part of the tile and stays.) With `hass`: also every other entity on an
 *  appliance's or a robot vacuum's device - its own controls (Sabbath mode,
 *  child lock, power...) - their tile stands for them. Lights stay (placed
 *  like any light), and pools / spas keep theirs: pumps, lights and spa mode
 *  are real controls. */
export function profileSources(doc: RoomTilesDoc | undefined, hass?: HomeAssistant): Set<string> {
  const out = new Set<string>();
  const add = (...ids: (string | null | undefined)[]) => ids.forEach((id) => id && out.add(id));
  // set up, waiting to be set up, and ignored: none of them is placed itself
  const ig = doc?.ignored_found;
  const appliances = [...(doc?.appliances ?? []), ...(doc?.appliance_found ?? []), ...(ig?.appliances ?? [])];
  const pools = [...(doc?.pools ?? []), ...(doc?.pool_found ?? []), ...(ig?.pools ?? [])];
  const robots = [...(doc?.robots ?? []), ...(doc?.robot_found ?? []), ...(ig?.robots ?? [])];
  for (const ap of appliances) for (const u of ap.units) add(u.status, u.time);
  for (const p of pools) {
    for (const b of [p.pool, p.spa]) if (b) add(b.temp, b.heater, b.pump, b.heater_switch);
    add(p.spa_mode, p.pump);
  }
  for (const r of robots) add(r.vacuum, r.error);
  if (hass?.entities) {
    const devices = new Set<string>();
    const ids = [...appliances.flatMap((ap) => ap.units.flatMap((u) => [u.status, u.time])), ...robots.map((r) => r.vacuum)];
    for (const id of ids) {
      const dev = id ? hass.entities[id]?.device_id : undefined;
      if (dev) devices.add(dev);
    }
    if (devices.size)
      for (const [id, e] of Object.entries(hass.entities)) {
        // Room Tiles' own appliance sensor sits on that device too: it IS the tile
        const ours = (e as { platform?: string }).platform === "room_tiles";
        if (!ours && !id.startsWith("light.") && e.device_id && devices.has(e.device_id)) out.add(id);
      }
  }
  return out;
}

/** THE rule for what can be a tile - and so a marker (a marker opens its
 *  tile): the tile domains, and sensors that are tiles (the `tile`
 *  contract, or catalogued); never hidden or settings entities, nor what
 *  Room Tiles' own tiles are made of, nor scripts that need inputs. Scenes
 *  and scripts are tiles; plain groups are not. Every list of entities to
 *  place uses it (the pickers, the map's group tiles). */
export function canBeTile(
  hass: HomeAssistant | undefined,
  doc: RoomTilesDoc | undefined,
  id: string,
  sources: Set<string> = profileSources(doc, hass),
  forMap = false,
): boolean {
  const st = hass?.states[id];
  if (!st) return false;
  const reg = hass?.entities?.[id];
  // Room Tiles' own entities are hidden in HA, not from Room Tiles
  const ours = (reg as { platform?: string } | undefined)?.platform === "room_tiles";
  if ((reg?.hidden && !ours) || reg?.entity_category || sources.has(id)) return false;
  if (needsInputs(hass, id)) return false;
  // an area's lights together: the lights button's and a map marker's -
  // never a tile on a board
  if (ours && id.startsWith("light.") && !forMap) return false;
  const domain = id.split(".")[0];
  if (PICKABLE_DOMAINS.has(domain)) return true;
  return domain === "sensor" && ("tile" in st.attributes || !!doc?.catalog.entries.some((e) => e.entity === id));
}

/** Entities that can go on a tile / the map: the usual domains, sensors that
 *  follow the appliance `tile` contract, and anything in the catalog; never
 *  hidden or settings entities, nor what Room Tiles' own tiles are made of
 *  (profileSources). Filtered to `area` unless `all`; `query`
 *  matches full name, short name or entity id. Catalogued first, then by name. */
export function entityCandidates(
  hass: HomeAssistant | undefined,
  doc: RoomTilesDoc | undefined,
  area: string | undefined,
  all: boolean,
  query: string,
  forMap = false,
): Candidate[] {
  if (!hass) return [];
  const catalog = new Map((doc?.catalog.entries ?? []).map((e) => [e.entity, e.short_name]));
  const q = query.trim().toLowerCase();
  const sources = profileSources(doc, hass);
  const out: Candidate[] = [];
  for (const id of Object.keys(hass.states)) {
    if (!canBeTile(hass, doc, id, sources, forMap)) continue;
    const c: Candidate = { entity: id, full: fullName(hass, id), short: catalog.get(id), area: areaOf(hass, id) };
    if (!all && c.area !== area) continue;
    if (q && !(c.full.toLowerCase().includes(q) || id.includes(q) || (c.short ?? "").toLowerCase().includes(q))) continue;
    out.push(c);
  }
  return out.sort((a, b) => Number(!a.short) - Number(!b.short) || a.full.localeCompare(b.full));
}

/** The area filter's values besides an area id. */
export const ALL_AREAS = "*";
export const NO_AREA = "-";

/** The entities for an area filter value: one area's, every area's
 *  (ALL_AREAS) or the ones with no area (NO_AREA). */
export function candidatesIn(
  hass: HomeAssistant | undefined,
  doc: RoomTilesDoc | undefined,
  filter: string,
  query: string,
  forMap = false,
): Candidate[] {
  if (filter === ALL_AREAS) return entityCandidates(hass, doc, undefined, true, query, forMap);
  return entityCandidates(hass, doc, filter === NO_AREA ? undefined : filter, false, query, forMap);
}

/** The area filter's choices: All areas, then each area that has something
 *  to pick (plus `keep`, the current choice) by name, then No area - each
 *  with how many entities it has. */
export function areaChoices(
  hass: HomeAssistant | undefined,
  doc: RoomTilesDoc | undefined,
  keep?: string,
): { value: string; label: string }[] {
  const all = entityCandidates(hass, doc, undefined, true, "");
  const count = new Map<string, number>();
  for (const c of all) count.set(c.area ?? NO_AREA, (count.get(c.area ?? NO_AREA) ?? 0) + 1);
  if (keep && keep !== ALL_AREAS && !count.has(keep)) count.set(keep, 0);
  const areas = [...count.keys()]
    .filter((id) => id !== NO_AREA)
    .map((id) => ({ value: id, name: areaName(hass, doc, id) }))
    .sort((a, b) => a.name.localeCompare(b.name))
    .map(({ value, name }) => ({ value, label: `${name} (${count.get(value)})` }));
  const none = count.get(NO_AREA);
  return [
    { value: ALL_AREAS, label: t("picker.all_areas_n", { n: all.length }) },
    ...areas,
    ...(none !== undefined ? [{ value: NO_AREA, label: t("picker.no_area_n", { n: none }) }] : []),
  ];
}

/** The area filter: a dropdown next to the search box. */
export function areaFilter(
  hass: HomeAssistant | undefined,
  doc: RoomTilesDoc | undefined,
  value: string,
  set: (value: string) => void,
): TemplateResult {
  return html`<select class="area-filter" aria-label=${t("common.area")} @change=${(e: Event) => set((e.target as HTMLSelectElement).value)}>
    ${areaChoices(hass, doc, value).map((o) => html`<option value=${o.value} ?selected=${o.value === value}>${o.label}</option>`)}
  </select>`;
}

/** Entities in `list` whose name (full or short) another entry also shows -
 *  those get a telling-apart line (where they come from, their entity id). */
export function sameNamed(list: Candidate[]): Set<string> {
  const count = new Map<string, number>();
  const keys = (c: Candidate) => [...new Set([c.full, c.short].filter(Boolean).map((n) => n!.trim().toLowerCase()))];
  for (const c of list) for (const k of keys(c)) count.set(k, (count.get(k) ?? 0) + 1);
  return new Set(list.filter((c) => keys(c).some((k) => (count.get(k) ?? 0) > 1)).map((c) => c.entity));
}

// integration names (proper names; HA shows them the same in every language)
const PLATFORM_NAMES: Record<string, string> = { room_tiles: "Room Tiles", template: "Template", group: "Group" };

/** "Room Tiles · sensor.room_tiles_laundry" - unique for any entity. */
export function telling(hass: HomeAssistant | undefined, entity: string): string {
  const pl = hass?.entities?.[entity]?.platform;
  const from = pl ? (PLATFORM_NAMES[pl] ?? pl.replace(/_/g, " ").replace(/^\w/, (ch) => ch.toUpperCase())) : "";
  return [from, entity].filter(Boolean).join(" · ");
}

const HIDE_GROUPS_KEY = "room-tiles:add-hide-groups";
function readHideGroups(): boolean {
  try {
    return localStorage.getItem(HIDE_GROUPS_KEY) === "1";
  } catch {
    return false;
  }
}

/** A picker dialog: choose one entity (search, this area / all areas).
 *  Fires "pick" {entity} or "close". With `multiple`: select up to `max`
 *  (kept across areas and searches - pinned on top), then Insert fires "pick-many"
 *  {entities} - by area, then name. */
export class RtEntityPicker extends LitElement {
  /** fades where a scrolling area has more (ui.ts ScrollFades) */
  protected readonly _scrollFades = new ScrollFades(this, ".list");

  /** the dialog's top edge stays put while its content changes (dialog-pin.ts) */
  readonly dialogPin = new DialogPin(this);
  static properties = {
    hass: { attribute: false },
    doc: { attribute: false },
    area: { type: String },
    heading: { type: String },
    forMap: { type: Boolean },
    multiple: { type: Boolean },
    max: { type: Number },
    placed: { attribute: false },
    _ticked: { state: true },
    _hideGroups: { state: true },
    _query: { state: true },
    _filter: { state: true },
  };

  hass?: HomeAssistant;
  doc?: RoomTilesDoc;
  /** the area shown first (the filter starts there; All areas if none) */
  area?: string;
  /** choosing a map marker (an area's lights can be one; not a tile) */
  forMap = false;
  /** the title; default "Choose an entity" (in the language) */
  heading = "";
  /** tick several, then Insert */
  multiple = false;
  /** most that can be ticked */
  max = 37;
  /** already on the layer being edited (shown as such; may go on again) */
  placed?: Set<string>;
  private _ticked: string[] = [];
  /** groups left out of the list (remembered in this browser) */
  private _hideGroups = readHideGroups();
  private _query = "";
  private _filter?: string; // the area filter, once changed
  private _opened = Date.now();

  private _close(): void {
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  }

  private _tick(entity: string): void {
    if (this._ticked.includes(entity)) this._ticked = this._ticked.filter((e) => e !== entity);
    else if (this._ticked.length < this.max) this._ticked = [...this._ticked, entity];
  }

  /** A group of entities (a light group, an HA group, an area's lights):
   *  it lists its members. (A scene lists what it sets too - not a group.) */
  private _isGroup(entity: string): boolean {
    if (entity.startsWith("scene.")) return false;
    const members = this.hass?.states[entity]?.attributes.entity_id;
    return Array.isArray(members) && members.length > 0;
  }

  /** Select every shown one not on the layer yet (as many as the limit allows). */
  private _tickNew(list: Candidate[]): void {
    const add = list
      .map((c) => c.entity)
      .filter((e) => !this._ticked.includes(e) && !this.placed?.has(e))
      .slice(0, Math.max(0, this.max - this._ticked.length));
    this._ticked = [...this._ticked, ...add];
  }

  /** Select all shown (as many as the limit allows), or deselect them if all are. */
  private _tickShown(list: Candidate[]): void {
    const shown = list.map((c) => c.entity);
    if (shown.every((e) => this._ticked.includes(e))) {
      this._ticked = this._ticked.filter((e) => !shown.includes(e));
      return;
    }
    const add = shown.filter((e) => !this._ticked.includes(e)).slice(0, Math.max(0, this.max - this._ticked.length));
    this._ticked = [...this._ticked, ...add];
  }

  private _insert(): void {
    const all = new Map(candidatesIn(this.hass, this.doc, ALL_AREAS, "", this.forMap).map((c) => [c.entity, c]));
    const key = (e: string) => {
      const c = all.get(e);
      return [c?.area ? areaName(this.hass, this.doc, c.area) : "\uffff", c?.full ?? e];
    };
    const entities = [...this._ticked].sort((a, b) => {
      const [ka, kb] = [key(a), key(b)];
      return ka[0].localeCompare(kb[0]) || ka[1].localeCompare(kb[1]);
    });
    this.dispatchEvent(new CustomEvent("pick-many", { detail: { entities }, bubbles: true, composed: true }));
  }

  /** A selected entity's row in the pinned "Selected" group. */
  private _row(c: Candidate, dupes: Set<string>, full: boolean) {
    const ticked = this._ticked.includes(c.entity);
    return html`<button
      class="cand ${ticked ? "ticked" : ""}"
      role="checkbox"
      aria-checked=${ticked ? "true" : "false"}
      ?disabled=${full && !ticked}
      @click=${() => this._tick(c.entity)}
    >
      <ha-icon class="box" icon=${ticked ? "mdi:checkbox-marked" : "mdi:checkbox-blank-outline"}></ha-icon>
      <span class="text">
        <span class="full">${c.full}</span>
        <span class="meta"
          >${c.short ? html`<b>${c.short}</b> · ` : ""}${areaName(this.hass, this.doc, c.area)}${this.placed?.has(c.entity) ? " · already on this layer" : ""}</span
        >
        ${dupes.has(c.entity) ? html`<span class="meta id">${telling(this.hass, c.entity)}</span>` : ""}
      </span>
    </button>`;
  }

  render() {
    const filter = this._filter ?? (this.area || ALL_AREAS);
    // "Hide groups": light groups, HA groups, area lights left out of the list
    const found = candidatesIn(this.hass, this.doc, filter, this._query, this.forMap).filter((c) => !this._hideGroups || !this._isGroup(c.entity));
    // selected ones stay in view whatever the filter / search: pinned on top
    const all = this._ticked.length ? new Map(candidatesIn(this.hass, this.doc, ALL_AREAS, "", this.forMap).map((c) => [c.entity, c])) : undefined;
    const picked = this._ticked.map((e) => all?.get(e)).filter((c): c is Candidate => !!c);
    const list = found.filter((c) => !this._ticked.includes(c.entity));
    const dupes = sameNamed([...picked, ...list]);
    const n = this._ticked.length;
    const full = n >= this.max;
    const allShown = found.length > 0 && found.every((c) => this._ticked.includes(c.entity));
    return html`
      <div class="scrim" style="--z:30" @click=${() => Date.now() - this._opened > 400 && this._close()}></div>
      <div class="dialog" style="--z:30" role="dialog" aria-label=${this.heading || t("picker.choose")}>
        <div class="head">
          <div class="title">${this.heading || t("picker.choose")}</div>
          <button class="x" aria-label=${t("common.cancel")} @click=${this._close}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        <div class="search">
          <input type="search" placeholder=${t("common.search_entities")} .value=${this._query} @input=${(e: Event) => (this._query = (e.target as HTMLInputElement).value)} />
          ${areaFilter(this.hass, this.doc, filter, (v) => (this._filter = v))}
        </div>
        ${this.multiple
          ? html`<label class="check hide-groups">
              <input
                type="checkbox"
                .checked=${this._hideGroups}
                @change=${(e: Event) => {
                  this._hideGroups = (e.target as HTMLInputElement).checked;
                  try {
                    localStorage.setItem(HIDE_GROUPS_KEY, this._hideGroups ? "1" : "0");
                  } catch {
                    /* private mode: just this time */
                  }
                }}
              />
              ${t("picker.hide_groups")}
            </label>`
          : ""}
        ${this.multiple && found.length
          ? html`<div class="tick-bar">
              <button class="link" ?disabled=${full && !allShown} @click=${() => this._tickShown(found)}>
                ${allShown ? t("picker.deselect_shown") : t("picker.select_shown")}
              </button>
              ${this.placed?.size && found.some((c) => this.placed!.has(c.entity))
                ? html`<button
                    class="link"
                    ?disabled=${full || !found.some((c) => !this.placed!.has(c.entity) && !this._ticked.includes(c.entity))}
                    @click=${() => this._tickNew(found)}
                  >
                    ${t("picker.select_not_on_layer")}
                  </button>`
                : ""}
              ${n ? html`<button class="link" @click=${() => (this._ticked = [])}>${t("picker.deselect_all")}</button>` : ""}
            </div>`
          : ""}
        <div class="list">
          ${this.multiple && picked.length
            ? html`<div class="list-head">${t("picker.selected_n", { n: picked.length })}</div>
                ${picked.map((c) => this._row(c, dupes, full))}
                <div class="list-head">${list.length ? t("picker.more") : ""}</div>`
            : ""}
          ${list.length
            ? list.map((c) => {
                const ticked = this._ticked.includes(c.entity);
                const text = html`<span class="text">
                  <span class="full">${c.full}</span>
                  <span class="meta"
                    >${c.short ? html`<b>${c.short}</b> · ` : ""}${areaName(this.hass, this.doc, c.area)}${this.placed?.has(c.entity)
                      ? ` · ${t("picker.on_layer")}`
                      : ""}</span
                  >
                  ${dupes.has(c.entity) ? html`<span class="meta id">${telling(this.hass, c.entity)}</span>` : ""}
                </span>`;
                return this.multiple
                  ? html`<button
                      class="cand ${ticked ? "ticked" : ""}"
                      role="checkbox"
                      aria-checked=${ticked ? "true" : "false"}
                      ?disabled=${full && !ticked}
                      @click=${() => this._tick(c.entity)}
                    >
                      <ha-icon class="box" icon=${ticked ? "mdi:checkbox-marked" : "mdi:checkbox-blank-outline"}></ha-icon>${text}
                    </button>`
                  : html`<button
                      class="cand"
                      @click=${() => this.dispatchEvent(new CustomEvent("pick", { detail: { entity: c.entity }, bubbles: true, composed: true }))}
                    >
                      ${text}
                    </button>`;
              })
            : picked.length && found.length
              ? ""
              : html`<div class="hint">
                ${this._query.trim() ? t("picker.nothing_matches") : t("picker.no_entities")}
                ${filter !== ALL_AREAS ? html`<button class="link" @click=${() => (this._filter = ALL_AREAS)}>${t("common.search_all_areas")}</button>` : ""}
              </div>`}
        </div>
        ${this.multiple
          ? html`<div class="footer">
              <span class="hint">${full ? t("picker.max", { n: this.max }) : n ? t("picker.n_selected", { n }) : t("picker.select_what")}</span>
              <button class="primary" ?disabled=${!n} @click=${() => this._insert()}>
                ${n ? (full ? t("picker.insert_n_max", { n }) : t("picker.insert_n", { n })) : t("picker.insert")}
              </button>
            </div>`
          : ""}
      </div>
    `;
  }

  static styles = [noSelectStyles, 
    dialogStyles,
    css`
      :host {
        --dialog-w: 480px;
      }
      .search {
        display: flex;
        gap: 10px;
        align-items: center;
      }
      .search input {
        flex: 1;
        min-width: 0;
      }
      .area-filter {
        max-width: 45%;
      }
      .cand {
        display: flex;
        align-items: center;
        gap: 10px;
        text-align: left;
        padding: 8px 10px;
        border-radius: 10px;
        border: 1px solid transparent;
        background: var(--rt-button);
      }
      .cand .text {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 2px;
        min-width: 0;
      }
      .cand.ticked {
        border-color: var(--rt-accent);
      }
      .cand:disabled {
        opacity: 0.45;
      }
      .box {
        --mdc-icon-size: 22px;
        flex: none;
        color: var(--rt-text-secondary);
      }
      .ticked .box {
        color: var(--rt-accent);
      }
      .list-head {
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--rt-text-secondary);
        padding: 4px 2px 0;
      }
      .list-head:empty {
        display: none;
      }
      .hide-groups {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 0.9rem;
      }
      .tick-bar {
        display: flex;
        gap: 6px 16px;
        flex-wrap: wrap;
      }
      .footer .hint {
        flex: 1;
        align-self: center;
      }
      .meta {
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

if (!customElements.get("rt-entity-picker")) customElements.define("rt-entity-picker", RtEntityPicker);
