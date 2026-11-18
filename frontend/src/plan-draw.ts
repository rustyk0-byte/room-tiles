// Drawing a map's floor plan as SVG - shared by the map (<rt-map>) and the map
// editor (<rt-plan-editor>), so both look the same. Colours from --rt-map-*.

import { css, nothing, svg, type SVGTemplateResult } from "lit";
import { bbox, type Pt } from "./geom";
import type { MapData, MapShape } from "./map";

export const LABEL_PX = 15;

export interface PlanOptions {
  /** map units per screen px (labels / dashes keep a fixed screen size) */
  s: number;
  /** the zone zoomed into (map) */
  focusZone?: string;
  /** draw every zone's outline (generated maps; the editor) */
  outlineZones?: boolean;
  /** the background (default on; the editor draws its own under the trace picture) */
  ground?: boolean;
  /** a vacuum's view: its vacuum zones show, rooms it can't clean grey out */
  vacuum?: VacuumView;
}

export interface VacuumView {
  id: string; // vacuum entity
  areas: string[]; // the HA areas it cleans
}

/** Zones shown: ordinary rooms, plus - in a vacuum's view - that vacuum's
 *  zones, drawn after (on top of) the rooms. */
export function zonesShown<Z extends { vacuum?: string | null }>(zones: Z[], vacuum?: VacuumView): Z[] {
  const rooms = zones.filter((z) => !z.vacuum);
  return vacuum ? [...rooms, ...zones.filter((z) => z.vacuum === vacuum.id)] : rooms;
}

export const poly = (pts: Pt[]) => pts.map((p) => p.join(",")).join(" ");

// MIRRORED: firmware/components/room_tiles/map_draw.cpp (shape order) - a change here must be made there too.
/** Shapes are drawn by TYPE, bottom to top, never by the order they were
 *  added: the lawn, a patio on it, a deck over that, a pool set in it, the
 *  house on top (user, 2026-11-08). Same type overlapping = same colour, so
 *  their order can't be seen. */
export const SHAPE_ORDER: MapShape["style"][] = ["grass", "paving", "deck", "water", "floor"];

export function shapesInOrder<S extends { style: MapShape["style"] }>(shapes: S[]): S[] {
  const rank = (st: MapShape["style"]) => {
    const i = SHAPE_ORDER.indexOf(st);
    return i < 0 ? SHAPE_ORDER.length : i;
  };
  return [...shapes].sort((a, b) => rank(a.style) - rank(b.style)); // stable: same type keeps its order
}

/** The zone's label position: its own, else the middle of its box. */
export function labelAt(z: { points: Pt[]; label: Pt | null }): Pt {
  if (z.label) return z.label;
  const b = bbox(z.points);
  return [(b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2];
}

/** The floor is the ROOM's: every room that's inside (not "Outside (no
 *  floor)") has a floor following its outline - nothing to select or edit
 *  apart from the room. Drawn on top of the shapes, where floors go. (Floor
 *  shapes from maps drawn before this still show, under them.) */
export function roomFloors(m: MapData): MapData["zones"] {
  return m.zones.filter((z) => !z.outdoor && !z.vacuum);
}

/** Ground, filled shapes, floors, zones, walls, windows, openings (no labels -
 *  `planLabels` draws those last, above markers' faces' lines). */
export function planBase(m: MapData, o: PlanOptions, view: { x: number; y: number; w: number; h: number }): SVGTemplateResult {
  const s = o.s;
  return svg`
    ${o.ground === false ? nothing : svg`<rect class="ground" x=${view.x - view.w} y=${view.y - view.h} width=${view.w * 3} height=${view.h * 3}></rect>`}
    ${shapesInOrder(m.shapes).map((sh) => svg`<polygon class="shape ${sh.style}" points=${poly(sh.points)}></polygon>`)}
    ${roomFloors(m).map((z) => svg`<polygon class="shape floor" points=${poly(z.points)}></polygon>`)}
    ${zonesShown(m.zones, o.vacuum).map((z) => {
      const v = o.vacuum;
      const cls = !v ? "" : z.vacuum ? "vzone" : z.area && v.areas.includes(z.area) ? "clean" : "noclean";
      return svg`<polygon class="zone ${cls} ${z.id === o.focusZone ? "focus" : ""} ${o.outlineZones ? "outlined" : ""}" points=${poly(z.points)}></polygon>`;
    })}
    ${planLines(m, s)}
  `;
}

/** Walls, windows, openings. */
export function planLines(m: MapData, s: number): SVGTemplateResult {
  return svg`
    ${m.walls.map(([x1, y1, x2, y2]) => svg`<line class="wall" x1=${x1} y1=${y1} x2=${x2} y2=${y2} stroke-width=${m.wall_width}></line>`)}
    ${m.windows.map(([x1, y1, x2, y2]) => svg`<line class="window" x1=${x1} y1=${y1} x2=${x2} y2=${y2} stroke-width=${m.wall_width * 0.6}></line>`)}
    ${m.openings.map(([x1, y1, x2, y2]) => svg`<line class="opening" x1=${x1} y1=${y1} x2=${x2} y2=${y2} stroke-width=${s * 1.5} stroke-dasharray="${s * 6} ${s * 5}"></line>`)}
  `;
}

export function planLabels(m: MapData, s: number, vacuum?: VacuumView): SVGTemplateResult {
  // a room with no name (a closet given a floor): no label
  return svg`${zonesShown(m.zones, vacuum).filter((z) => z.name.trim()).map((z) => {
    const [lx, ly] = labelAt(z);
    return svg`<text class="label ${z.outdoor ? "out" : ""}" x=${lx} y=${ly} font-size=${LABEL_PX * s}
      transform=${z.label_vertical ? `rotate(-90 ${lx} ${ly})` : ""}>${z.name}</text>`;
  })}`;
}

export const planStyles = css`
  .ground {
    fill: var(--rt-map-bg);
  }
  .shape.floor {
    fill: var(--rt-map-floor);
  }
  .shape.water {
    fill: var(--rt-map-water);
  }
  .shape.grass {
    fill: var(--rt-map-grass);
  }
  .shape.deck {
    fill: var(--rt-map-deck);
  }
  .shape.paving {
    fill: var(--rt-map-paving);
  }
  .zone {
    fill: transparent;
    stroke: none;
  }
  .zone.outlined {
    stroke: var(--rt-map-wall);
    stroke-width: 2;
    vector-effect: non-scaling-stroke;
  }
  .zone.clean {
    fill: var(--rt-accent);
    fill-opacity: 0.14;
  }
  .zone.noclean {
    fill: var(--rt-map-bg);
    fill-opacity: 0.55;
  }
  .zone.vzone {
    fill: var(--rt-accent);
    fill-opacity: 0.3;
    stroke: var(--rt-accent);
    stroke-width: 2;
    stroke-dasharray: 6 4;
    vector-effect: non-scaling-stroke;
  }
  .wall {
    stroke: var(--rt-map-wall);
    stroke-linecap: square;
  }
  .window {
    stroke: var(--rt-map-window);
  }
  .opening {
    stroke: var(--rt-map-wall);
    opacity: 0.6;
  }
  .label {
    fill: var(--rt-map-label);
    text-anchor: middle;
    dominant-baseline: middle;
    pointer-events: none;
    font-family: Roboto, sans-serif;
  }
  .label.out {
    fill: var(--rt-map-label-out);
  }
`;
