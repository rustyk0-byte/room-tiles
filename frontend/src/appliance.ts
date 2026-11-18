// Appliance tiles: one or two units (dual-drawer dishwasher, washer + dryer)
// with the panels' animations.
//
// Reads the appliance sensor's `tile` attribute - the format the wall panels
// read: units separated by ";", each "label|state|status|base|time".
//   state  washing -> bubbles, drying -> sun, done -> check,
//          waiting -> hourglass, anything else -> no animation
//   base   plate | shirt: the still picture under the animation
// (Brand presets in the integration will produce this later; for now it is
// whatever HA template sensor the user points the tile at.)
// Animations pause when the panel's host has data-motion="off".

import { css, html, nothing, type TemplateResult } from "lit";
import { assetUrl, type ThemeName } from "./theme";
import { t } from "./i18n";

// assets/build_web.py: sheets of 8 x 4 frames, 16 fps
export const SHEET_COLS = 8;
export const SHEET_ROWS = 4;
const FPS = 16;
const LOOP_S = (SHEET_COLS * SHEET_ROWS) / FPS;

const ANIMATION: Record<string, string> = {
  washing: "bubble_wash",
  drying: "sun_dry",
  done: "check_done",
  waiting: "wet_hourglass",
};
// MIRRORED: firmware/components/room_tiles/map_markers.cpp (marker animations) - a change here must be made there too.
/** The animation an appliance's map marker plays: the top unit's (the first
 *  in `tile` - upper drawer, dryer) when it has one, else the other's. */
export function markerAnimation(tile: unknown): string | undefined {
  for (const u of parseUnits(tile)) if (ANIMATION[u.state]) return ANIMATION[u.state];
  return undefined;
}

const BASE: Record<string, string> = { plate: "plate_knife_fork", shirt: "shirt_socks" };

export interface ApplianceUnit {
  label: string;
  state: string;
  status: string;
  base: string;
  time: string;
}

// MIRRORED: firmware/components/room_tiles/board_kinds.cpp + map_markers.cpp (appliance tile text) - a change here must be made there too.
export function parseUnits(tile: unknown): ApplianceUnit[] {
  if (typeof tile !== "string" || !tile.trim()) return [];
  return tile
    .split(";")
    .map((u) => u.split("|").map((f) => f.trim()))
    .filter((f) => f.length >= 2)
    .map(([label = "", state = "", status = "", base = "", time = ""]) => ({ label, state, status, base, time }))
    .slice(0, 2);
}

/** Static URL base of the integration's frontend files (frontend.py STATIC_URL) -
 *  the browser demo's build sets its own (build-demo.mjs DEMO_STATIC). */
declare const DEMO_STATIC: string | undefined;
export const STATIC_BASE = typeof DEMO_STATIC !== "undefined" ? DEMO_STATIC : "/room_tiles_frontend";

/** `onTap(i, event)`: a tap on unit i (the panel empties a finished one). */
export function renderAppliance(
  units: ApplianceUnit[],
  theme: ThemeName,
  onTap?: (index: number, e: Event) => void,
): TemplateResult {
  if (!units.length) return html`<div class="appliance appl-empty">${t("appliance.no_data")}</div>`;
  return html`
    <div class="appliance units-${units.length}">
      ${units.map((u, i) => {
        const anim = ANIMATION[u.state];
        const base = BASE[u.base];
        const time = u.time && !["unknown", "unavailable", "none", "0", ""].includes(u.time.toLowerCase()) ? u.time : "";
        return html`
          <div class="appl-unit" @click=${(e: Event) => onTap?.(i, e)}>
            <div class="appl-pic">
              ${base ? html`<img class="appl-base" alt="" src=${assetUrl(STATIC_BASE, `appliances/${base}.webp`, theme)} />` : nothing}
              ${anim
                ? html`<div class="appl-anim">
                    <div class="appl-rows">
                      <img class="appl-sheet" alt="" src=${assetUrl(STATIC_BASE, `appliances/${anim}.webp`, theme)} />
                    </div>
                  </div>`
                : nothing}
            </div>
            <div class="appl-label">${u.label}</div>
            <div class="appl-status">${u.status}${time ? html` <span class="appl-time">${time}</span>` : nothing}</div>
          </div>
        `;
      })}
    </div>
  `;
}

// The sheet is moved with CSS transforms in steps(): the compositor shifts an
// already-decoded GPU texture - no repaint per frame (a background-position
// animation would repaint 16 times a second). Two nested elements because
// one transform can't step x and y on different timings: .appl-rows steps
// through the 4 rows per loop, .appl-sheet through the 8 columns per row.
// Class names are prefixed (appl-): these styles share the panel's shadow
// root, and a plain ".sheet" once picked up the map editor's bottom sheet
// styles (2026-11-08: the washer's dark square).
export const applianceStyles = css`
  /* EDIT MODE ONLY: nothing inside takes touches, so they reach the edit
     overlay - Safari on iPad / iPhone hit-tests the animation's own GPU
     layers ahead of what sits above them. Outside edit mode the animation must
     stay tappable (a tap will reset an appliance's "done" state when no door
     sensor clears it). */
  .cell.editing .appliance,
  .cell.editing .appliance * {
    pointer-events: none;
  }
  /* one unit: exactly a half's layout, centred vertically in the tile */
  .appliance {
    display: flex;
    flex-direction: column;
    gap: 6px;
    width: 100%;
    height: 100%;
    justify-content: space-around;
  }
  .appliance.appl-empty {
    color: var(--rt-text-secondary);
    align-items: center;
    justify-content: center;
  }
  .appl-unit {
    display: grid;
    grid-template-columns: auto 1fr;
    grid-template-rows: auto auto;
    column-gap: 8px;
    align-items: center;
    min-width: 0;
  }
  .appl-pic {
    grid-row: span 2;
    position: relative;
    width: var(--rt-appliance-size, 56px);
    height: var(--rt-appliance-size, 56px);
  }
  .appl-base,
  .appl-anim {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
  }
  .appl-anim {
    overflow: hidden;
    contain: strict;
  }
  .appl-rows {
    width: ${SHEET_COLS * 100}%;
    height: ${SHEET_ROWS * 100}%;
    will-change: transform;
    animation: rt-sheet-y ${LOOP_S}s steps(${SHEET_ROWS}) infinite;
  }
  .appl-sheet {
    display: block;
    width: 100%;
    height: 100%;
    will-change: transform;
    animation: rt-sheet-x ${LOOP_S / SHEET_ROWS}s steps(${SHEET_COLS}) infinite;
  }
  @keyframes rt-sheet-x {
    to {
      transform: translateX(-100%);
    }
  }
  @keyframes rt-sheet-y {
    to {
      transform: translateY(-100%);
    }
  }
  /* paused by the panel's animations setting (follow device / always /
     never), not by the media query directly */
  :host([data-motion="off"]) .appl-rows,
  :host([data-motion="off"]) .appl-sheet {
    animation: none;
  }
  .appl-label {
    font-size: 0.95rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .appl-status {
    font-size: 0.8rem;
    color: var(--rt-text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .appl-time {
    color: var(--rt-light);
  }
`;
