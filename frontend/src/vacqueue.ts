// The vacuum room queue on the dashboard (DESIGN.md "The room queue's UI"):
// which maps a vacuum cleans on, which map its tile shows, which rooms an
// area is. Pure (tested in vacqueue.test.ts). The queue itself runs in the
// integration (robot.RoomQueue, service room_tiles.vacuum_queue); its state
// is the robot sensor's attributes: `queue` (area ids, in order), `current`.

import { LitElement, css, nothing, svg, type SVGTemplateResult } from "lit";
import type { MapData, MapZone } from "./map";
import { labelAt, planBase, planStyles, poly, zonesShown } from "./plan-draw";
import type { HassEntity, HomeAssistant, RoomTilesDoc } from "./types";
import type { VacuumView } from "./plan-draw";
import { t } from "./i18n";

/** A room's place in the queue - the panels' colour key: queued blue; the
 *  room being cleaned by what the vacuum is doing (starting = sent, not
 *  cleaning yet). */
export type RoomState = "queued" | "starting" | "cleaning" | "paused" | "attention" | "error";
/** The queue's colour key, in order: each state and its label. */
export const ROOM_STATES: [RoomState, string][] = [
  ["queued", "queue.state_queued"],
  ["starting", "queue.state_starting"],
  ["cleaning", "queue.state_cleaning"],
  ["paused", "queue.state_paused"],
  ["attention", "queue.state_attention"],
  ["error", "queue.state_error"],
];

/** What rt-map's queue mode and the tile's map draw. `cls`: the vacuum's
 *  tile class (cleaning, paused, attention, error, docked...). */
export interface QueueView {
  vacuum: VacuumView;
  queue: string[];
  current: string | null;
  cls?: string;
}

export function roomState(q: { queue: string[]; current: string | null; cls?: string }, area: string): RoomState | undefined {
  if (area === q.current) {
    const c = q.cls;
    return c === "cleaning" || c === "paused" || c === "attention" || c === "error" ? c : "starting";
  }
  return q.queue.includes(area) ? "queued" : undefined;
}

/** The queue's look on a map (rt-map's queue mode, the vacuum tile's map):
 *  each room in its state's colour (ROOM_STATES); number badges. */
export const queueStyles = css`
  .queued {
    --q: var(--rt-vac-queued);
  }
  .starting {
    --q: var(--rt-vac-starting);
  }
  .cleaning {
    --q: var(--rt-vac-cleaning);
  }
  .paused {
    --q: var(--rt-vac-paused);
  }
  .attention {
    --q: var(--rt-vac-attention);
  }
  .error {
    --q: var(--rt-vac-error);
  }
  .qroom {
    fill: var(--q);
    fill-opacity: 0.45;
    stroke: var(--q);
    stroke-width: 2px;
    vector-effect: non-scaling-stroke;
    pointer-events: none;
  }
  .qroom.current {
    fill-opacity: 0.7;
  }
  .qbadge circle {
    fill: var(--q);
    stroke: var(--rt-page);
    stroke-width: 2px;
    vector-effect: non-scaling-stroke;
  }
  .qbadge text {
    fill: var(--rt-on-accent);
    text-anchor: middle;
    dominant-baseline: central;
    font-family: Roboto, sans-serif;
    font-weight: 700;
    pointer-events: none;
  }
  .qbadge.starting text,
  .qbadge.paused text {
    fill: var(--rt-on-bright);
  }
  .qbadge {
    pointer-events: none;
  }
`;

/** The queue's rooms in their state's colour (rooms and the vacuum's zones). */
export function queueRooms(m: MapData, q: QueueView): SVGTemplateResult {
  return svg`${zonesShown(m.zones, q.vacuum).flatMap((z) => {
    const st = z.area ? roomState(q, z.area) : undefined;
    return st ? [svg`<polygon class="qroom ${st} ${z.area === q.current ? "current" : ""}" points=${poly(z.points)}></polygon>`] : [];
  })}`;
}

/** Number badges (the room being cleaned: a play mark), radius `r` map units,
 *  `dy` above each room's label point. */
export function queueBadges(m: MapData, q: QueueView, r: number, dy: number, font: number): SVGTemplateResult {
  return svg`${zonesShown(m.zones, q.vacuum).flatMap((z) => {
    if (!z.area) return [];
    const k = q.queue.indexOf(z.area);
    const cur = z.area === q.current;
    if (k < 0 && !cur) return [];
    const [lx, ly] = labelAt(z);
    return [
      svg`<g class="qbadge ${roomState(q, z.area) ?? ""}" transform="translate(${lx} ${ly - dy})">
        <circle r=${r}></circle>
        <text font-size=${font}>${cur ? "▶" : k + 1}</text>
      </g>`,
    ];
  })}`;
}

/** The vacuum tile's map: the whole map, small - the vacuum's view, the
 *  queue's rooms in their colours only (no labels or badges: too small to
 *  read). */
export function tileMapSvg(m: MapData, q: QueueInfo): SVGTemplateResult {
  const [x0, y0, x1, y1] = m.bounds;
  const w = x1 - x0;
  const h = y1 - y0;
  const s = Math.max(w, h) / 180; // map units per tile px (about)
  const view = queueView(q);
  return svg`<svg class="tile-map" viewBox="${x0} ${y0} ${w} ${h}" preserveAspectRatio="xMidYMid meet">
    ${planBase(m, { s, vacuum: view.vacuum, ground: false }, { x: x0, y: y0, w, h })}
    ${queueRooms(m, view)}
  </svg>`;
}

export interface QueueInfo {
  robot: string; // Room Tiles robot id
  sensor: string; // its sensor (sensor.room_tiles_<id>)
  vacuum: string; // the HA vacuum entity
  name: string;
  queue: string[];
  current: string | null;
  cleanable: string[]; // HA areas it cleans (its segment mapping)
  cls: string; // what the vacuum is doing (its tile class: cleaning, paused, attention, error...)
}

/** The queue behind a vacuum tile / marker: the Room Tiles robot sensor (or
 *  the one for a vacuum entity). None: not a queue-capable vacuum (no
 *  clean_area, or no areas mapped). */
export function queueInfo(hass: HomeAssistant | undefined, doc: RoomTilesDoc | undefined, entity: string | null | undefined): QueueInfo | undefined {
  if (!hass || !entity) return undefined;
  let st: HassEntity | undefined = hass.states[entity];
  if (entity.startsWith("vacuum.")) st = Object.values(hass.states).find((s) => s.attributes.robot && s.attributes.vacuum === entity);
  const a = st?.attributes;
  if (!st || !a?.robot || !a.clean_area) return undefined;
  const vacuum = String(a.vacuum ?? "");
  const cleanable = doc?.vacuums?.[vacuum]?.areas ?? [];
  if (!cleanable.length) return undefined;
  return {
    robot: String(a.robot),
    sensor: st.entity_id,
    vacuum,
    name: String(a.own_name ?? a.friendly_name ?? a.robot),
    queue: Array.isArray(a.queue) ? a.queue.filter((x: unknown): x is string => typeof x === "string") : [],
    current: typeof a.current === "string" && a.current ? a.current : null,
    cleanable,
    cls: String(a.tile ?? "").split("|")[0],
  };
}

export const vacuumView = (q: QueueInfo): VacuumView => ({ id: q.vacuum, areas: q.cleanable });
export const queueView = (q: QueueInfo): QueueView => ({ vacuum: vacuumView(q), queue: q.queue, current: q.current, cls: q.cls });

/** Why a vacuum has no room queue (shown on its tile and in its settings):
 *  its integration can't clean chosen rooms; its rooms aren't linked to HA
 *  areas; or none of those areas has a room on a map yet. None: it's fine. */
export function queueProblem(hass: HomeAssistant | undefined, doc: RoomTilesDoc | undefined, maps: MapData[], entity: string | null | undefined): string | undefined {
  if (!hass || !entity) return undefined;
  let st: HassEntity | undefined = hass.states[entity];
  if (entity.startsWith("vacuum.")) st = Object.values(hass.states).find((s) => s.attributes.robot && s.attributes.vacuum === entity);
  const a = st?.attributes;
  if (!st || !a?.robot || st.state === "unavailable") return undefined;
  if (!a.clean_area) return t("queue.problem_not_supported");
  const vacuum = String(a.vacuum ?? "");
  const areas = doc?.vacuums?.[vacuum]?.areas ?? [];
  if (!areas.length) return t("queue.problem_not_set_up");
  if (!maps.some((m) => areas.some((x) => roomsOf(m, x, vacuum).length))) return t("queue.problem_not_on_map");
  return undefined;
}

/** A map's rooms that stand for `area` for this vacuum: its rooms, and the
 *  vacuum's own zones for it. */
export function roomsOf(m: MapData, area: string, vacuum: string): MapZone[] {
  return m.zones.filter((z) => z.area === area && (!z.vacuum || z.vacuum === vacuum));
}

/** The maps with a room the vacuum cleans - the queue mode's map toggle. */
export function queueMaps(maps: MapData[], q: QueueInfo): MapData[] {
  return maps.filter((m) => q.cleanable.some((a) => roomsOf(m, a, q.vacuum).length));
}

// MIRRORED: firmware/components/room_tiles/map_queue.cpp (first map) - a change here must be made there too.
/** The map the vacuum tile draws: the area being cleaned's; else the first
 *  queued area's; else the first map with a room it cleans. */
export function tileMap(maps: MapData[], q: QueueInfo): MapData | undefined {
  const own = queueMaps(maps, q);
  for (const area of [q.current, ...q.queue]) {
    if (!area) continue;
    const m = own.find((x) => roomsOf(x, area, q.vacuum).length);
    if (m) return m;
  }
  return own[0];
}

/** <rt-tile-map>: the vacuum tile's map in its own element - the map
 *  drawing's styles (.label, .zone...) stay inside it, off the panel. */
export class RtTileMap extends LitElement {
  static properties = { map: { attribute: false }, q: { attribute: false } };
  map?: MapData;
  q?: QueueInfo;

  render() {
    return this.map && this.q ? tileMapSvg(this.map, this.q) : nothing;
  }

  static styles = [
    planStyles,
    queueStyles,
    css`
      :host {
        display: block;
      }
      .tile-map {
        width: 100%;
        height: 100%;
        display: block;
      }
    `,
  ];
}

if (!customElements.get("rt-tile-map")) customElements.define("rt-tile-map", RtTileMap);

