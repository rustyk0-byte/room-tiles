// The zoom box - the same in marker editing and the map editor: zoom in /
// out by 0.25 steps (zoomStep), the zoom number (viewZoom: 1 = the whole map
// on a panel's screen) and under it the layer people see at that zoom.
// Amber (`off`) when that isn't the layer being edited. The number is a
// button (to where its layer starts), drawn as one only when that's
// somewhere else. Callers put it in a
// .zoomwrap in their map area's top-right corner (notes can go under it).

import { css, html, type TemplateResult } from "lit";
import { t } from "./i18n";

/** Layer choices compare zooms at the precision the zoom box shows (0.01):
 *  "2x" on screen is 2x for which layer people see - a hair under (the map
 *  area a pixel shorter) isn't the layer before. */
export const ZOOM_EPS = 0.005;

/** "1.75x" - the same number (and x) as the layers' zoom settings. */
export const zoomLabel = (z: number): string => `${Math.round(z * 100) / 100}x`;

export interface ZoomBox {
  z: number;
  layer?: string;
  off?: boolean;
  atIn: boolean;
  atOut: boolean;
  onIn: () => void;
  onOut: () => void;
  /** the number tapped: to where a layer starts (`start`) - the one named
   *  under it, or `startName` */
  start?: number;
  startName?: string;
  onStart?: () => void;
}

export function zoomBox(o: ZoomBox): TemplateResult {
  // the number looks like a button only when a tap goes somewhere: away
  // from where its layer starts
  const jump = !!o.onStart && o.start !== undefined && Math.abs(o.z - o.start) > ZOOM_EPS;
  return html`<div class="zoom ${o.off ? "off" : ""}" role="group" aria-label=${t("zoom.zoom")}>
    <button aria-label=${t("zoom.in")} ?disabled=${o.atIn} @click=${o.onIn}>
      <ha-icon icon="mdi:magnify-plus-outline"></ha-icon>
    </button>
    <button
      class="zlevel ${jump ? "jump" : ""}"
      title=${jump
        ? t("zoom.current_jump", { layer: o.startName ?? o.layer ?? "", zoom: zoomLabel(o.start!) })
        : t("zoom.current")}
      ?disabled=${!jump}
      @click=${() => jump && o.onStart?.()}
    >
      <span class="chip">
        <b>${zoomLabel(o.z)}</b>
        <span>${o.layer ?? ""}</span>
      </span>
    </button>
    <button aria-label=${t("zoom.out")} ?disabled=${o.atOut} @click=${o.onOut}>
      <ha-icon icon="mdi:magnify-minus-outline"></ha-icon>
    </button>
  </div>`;
}

export const zoomStyles = css`
  .zoomwrap {
    position: absolute;
    top: 10px;
    right: 10px;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 6px;
    pointer-events: none;
  }
  .zoomwrap > * {
    pointer-events: auto;
  }
  .zoom {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    width: 64px;
    border-radius: 12px;
    background: var(--rt-dialog);
    border: 1px solid var(--rt-tile-border);
    overflow: hidden;
    --mdc-icon-size: 22px;
  }
  .zoom.off {
    border-color: var(--rt-light);
  }
  .zoom.off .zlevel,
  .zoom.off .zlevel span {
    color: var(--rt-light);
  }
  .znote {
    display: flex;
    gap: 6px;
    align-items: flex-start;
    max-width: 190px;
    padding: 6px 8px;
    border-radius: 10px;
    background: var(--rt-dialog);
    border: 1px solid var(--rt-light);
    color: var(--rt-light);
    font-size: 12px;
    line-height: 1.3;
    --mdc-icon-size: 16px;
  }
  .znote a {
    color: inherit;
    font-weight: 600;
  }
  .zoom button {
    height: 40px;
    border: 0;
    background: none;
    color: var(--rt-text);
    cursor: pointer;
    padding: 0;
  }
  .zoom button:disabled {
    opacity: 0.35;
    cursor: default;
  }
  .zoom button.zlevel {
    /* the number is a button too (to where its layer starts) - its own
       height, and never dimmed when it can't */
    height: auto;
    font: inherit;
  }
  .zoom button.zlevel:disabled {
    opacity: 1;
  }
  .zlevel {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    padding: 3px 4px;
    border-block: 1px solid var(--rt-tile-border);
    color: var(--rt-text);
    font-size: 15px;
    line-height: 1.2;
  }
  .zlevel .chip {
    display: flex;
    flex-direction: column;
    align-items: center;
    min-width: 0;
    padding: 2px 2px;
    border: 1px solid transparent;
    border-radius: 8px;
    transition: background 0.12s, border-color 0.12s;
  }
  /* a tap goes to where its layer starts: it looks like the app's buttons */
  .zlevel.jump .chip {
    background: var(--rt-button);
    border-color: var(--rt-tile-border);
  }
  .zlevel.jump:hover .chip {
    border-color: var(--rt-text-secondary);
  }
  .zlevel.jump:active .chip {
    border-color: var(--rt-accent);
  }
  .zlevel span {
    font-size: 11px;
    color: var(--rt-text-secondary);
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
`;
