// MIRRORED: firmware/components/room_tiles/board_edit.cpp open_help (the panel's Help pages) - a change here must be made there too.
// <rt-map-help>: the Help pages - the tiles (mode "tiles"), the vacuum's room queue ("queue"), the tile editor
// ("tile-edit"), the map itself ("view"), marker editing ("markers") and the
// map editor ("plan") - short, scannable tables (the same rules as docs/UI.md
// "Input" / input.ts; keep them in step). Fires "close", and in marker
// mode "layer-settings" (its Layer settings link: Map settings' layers).

import { LitElement, css, html } from "lit";
import { DialogPin } from "./dialog-pin";
import { dialogStyles, noSelectStyles, ScrollFades } from "./ui";
import { t, th } from "./i18n";

// the map itself (map.ts header: what a tap / long press does per kind)
const VIEW_MARKERS: [string, string, string][] = [
  ["help.view_markers.switch_it.what", "help.view_markers.switch_it.touch", "help.common.click_it"],
  ["help.view_markers.full_controls.what", "help.view_markers.full_controls.touch", "help.view_markers.full_controls.mouse"],
  ["help.view_markers.close_the_tile.what", "help.view_markers.close_the_tile.touch", "help.view_markers.close_the_tile.mouse"],
];

const VIEW_MOVING: [string, string, string][] = [
  ["help.view_moving.into_a_room.what", "help.view_moving.into_a_room.touch", "help.view_moving.into_a_room.mouse"],
  ["help.view_moving.whole_map_again.what", "help.view_moving.whole_map_again.touch", "help.same"],
  ["help.common.zoom", "help.view_moving.zoom.touch", "help.view_moving.zoom.mouse"],
  ["help.common.pan", "help.common.drag", "help.common.drag"],
  ["help.view_moving.another_map.what", "help.view_moving.another_map.touch", "help.same"],
  ["help.view_moving.more_detail.what", "help.view_moving.more_detail.touch", "help.same"],
];

const VIEW_BUTTONS: [string, string][] = [
  ["mdi:fullscreen", "help.common.full_screen_when_it_s_on_the_m"],
  ["mdi:cog", "help.view_buttons.cog.text"],
  ["mdi:close", "help.view_buttons.close.text"],
];

// the tiles (room-tiles-panel.ts _renderTile)
const TILE_CONTROLS: [string, string, string][] = [
  ["help.tile_controls.on_off.what", "help.tile_controls.on_off.touch", "help.tile_controls.on_off.mouse"],
  ["help.tile_controls.brightness_position_speed_te.what", "help.tile_controls.brightness_position_speed_te.touch", "help.tile_controls.brightness_position_speed_te.mouse"],
  ["help.tile_controls.color.what", "help.tile_controls.color.touch", "help.common.click_it"],
  ["help.tile_controls.pool_spa_heater.what", "help.tile_controls.pool_spa_heater.touch", "help.common.click_it"],
  ["help.tile_controls.ha_card.what", "help.tile_controls.ha_card.touch", "help.common.click_it"],
  ["help.tile_controls.appliance.what", "help.tile_controls.appliance.touch", "help.common.click_it"],
  ["help.tile_controls.robot_vacuum.what", "help.tile_controls.robot_vacuum.touch", "help.common.click_it"],
  ["help.tile_controls.scene_script.what", "help.tile_controls.scene_script.touch", "help.common.click_it"],
];

const TILE_BUTTONS: [string, string][] = [
  ["mdi:fullscreen", "help.common.full_screen_when_it_s_on_the_m"],
  ["mdi:menu-down", "help.tile_buttons.menu_down.text"],
  ["mdi:grid", "help.tile_buttons.grid.text"],
  ["mdi:floor-plan", "help.tile_buttons.floor_plan.text"],
  ["mdi:lightbulb-group-outline", "help.tile_buttons.lightbulb_group_outline.text"],
  ["mdi:cog", "help.tile_buttons.cog.text"],
];

// the tile editor (room-tiles-panel.ts _editTap / long press)
const TILE_EDIT: [string, string, string][] = [
  ["help.tile_edit.change_a_tile.what", "help.tile_edit.change_a_tile.touch", "help.common.click_it"],
  ["help.tile_edit.move_a_tile.what", "help.tile_edit.move_a_tile.touch", "help.tile_edit.move_a_tile.mouse"],
  ["help.tile_edit.put_it_back.what", "help.common.tap_it_again", "help.common.click_it_again"],
  ["help.tile_edit.start_over.what", "help.tile_edit.start_over.touch", "help.same"],
  ["help.tile_edit.finish.what", "help.tile_edit.finish.touch", "help.same"],
];

const BUTTONS: [string, string][] = [
  ["mdi:cursor-default-outline", "help.buttons.cursor_default_outline.text"],
  ["mdi:selection-drag", "help.buttons.selection_drag.text"],
  ["mdi:map-marker-plus-outline", "help.buttons.map_marker_plus_outline.text"],
  ["mdi:magnify-plus-outline", "help.buttons.magnify_plus_outline.text"],
  ["mdi:undo", "help.buttons.undo.text"],
  ["mdi:content-save-outline", "help.buttons.content_save_outline.text"],
  ["mdi:magnify-expand", "help.buttons.magnify_expand.text"],
  ["mdi:label-outline", "help.buttons.label_outline.text"],
  ["mdi:cog", "help.buttons.cog.text"],
];

const GESTURES: [string, string, string][] = [
  ["help.gestures.select_a_marker.what", "help.common.tap_adds_to_the_selection", "help.common.click_selects_just_it"],
  ["help.common.the_one_underneath", "help.gestures.the_one_underneath.touch", "help.common.click_it_again_or_its_button"],
  ["help.common.add_remove_one", "help.common.tap_it", "help.common.shift_ctrl_cmd_click"],
  ["help.common.select_an_area", "help.common.box_select_then_drag_a_new_sel", "help.common.alt_drag_shift_ctrl_cmd_drag_a"],
  ["help.common.move", "help.gestures.move.touch", "help.same"],
  ["help.common.nudge", "help.gestures.nudge.touch", "help.common.arrow_keys_shift_bigger_steps"],
  ["help.common.line_up_space_out", "help.common.select_2_3_to_space_then_align", "help.same"],
  ["help.common.move_the_selection_box", "help.common.drag_its_title_row_double_tap", "help.common.drag_its_title_row_double_clic"],
  ["help.common.deselect_all", "help.common.tap_empty_map", "help.common.click_empty_map"],
  ["help.gestures.pan_zoom.what", "help.gestures.pan_zoom.touch", "help.gestures.pan_zoom.mouse"],
  ["help.gestures.another_room_or_map.what", "help.gestures.another_room_or_map.touch", "help.same"],
];

// the map editor (plan-editor.ts TOOLS / HINT)
const PLAN_TOOLS: [string, string, string][] = [
  // what each tool is FOR, in a few words (how: PLAN_DRAWING)
  ["mdi:image-outline", "help.plan_tools.image_outline.name", "help.plan_tools.image_outline.how"],
  ["mdi:wall", "help.plan_tools.wall.name", "help.plan_tools.wall.how"],
  ["mdi:window-closed-variant", "help.plan_tools.window_closed_variant.name", "help.plan_tools.window_closed_variant.how"],
  ["mdi:door-open", "help.plan_tools.door_open.name", "help.plan_tools.door_open.how"],
  ["mdi:vector-square", "help.plan_tools.vector_square.name", "help.plan_tools.vector_square.how"],
  ["mdi:shape-polygon-plus", "help.plan_tools.shape_polygon_plus.name", "help.plan_tools.shape_polygon_plus.how"],
  ["mdi:stairs", "help.plan_tools.stairs.name", "help.plan_tools.stairs.how"],
  ["mdi:cursor-default-outline", "help.plan_tools.cursor_default_outline.name", "help.plan_tools.cursor_default_outline.how"],
  ["mdi:selection-drag", "help.plan_tools.selection_drag.name", "help.plan_tools.selection_drag.how"],
  ["mdi:robot-vacuum", "help.plan_tools.robot_vacuum.name", "help.plan_tools.robot_vacuum.how"],
  ["mdi:eraser", "help.plan_tools.eraser.name", "help.plan_tools.eraser.how"],
];

// how to draw each thing (what the tools' one-line hints leave out)
const PLAN_DRAWING: [string, string][] = [
  ["help.plan_drawing.wall.what", "help.plan_drawing.wall.how"],
  ["help.plan_drawing.window_opening.what", "help.plan_drawing.window_opening.how"],
  ["help.plan_drawing.room_shape.what", "help.plan_drawing.room_shape.how"],
  ["help.plan_drawing.room_s_area_and_name.what", "help.plan_drawing.room_s_area_and_name.how"],
  ["help.plan_drawing.vacuum_area.what", "help.plan_drawing.vacuum_area.how"],
  ["help.plan_drawing.reshape.what", "help.plan_drawing.reshape.how"],
  ["help.plan_drawing.link.what", "help.plan_drawing.link.how"],
];

const PLAN_PICTURE: [string, string][] = [
  ["help.plan_picture.picture_drawing.what", "help.plan_picture.picture_drawing.how"],
  ["help.common.move", "help.plan_picture.move.how"],
  ["help.plan_picture.resize_stretch.what", "help.plan_picture.resize_stretch.how"],
  ["help.plan_picture.turn.what", "help.plan_picture.turn.how"],
  ["help.plan_picture.hide_remove.what", "help.plan_picture.hide_remove.how"],
];

const PLAN_BUTTONS: [string, string][] = [
  ["mdi:magnet", "help.plan_buttons.magnet.text"],
  ["mdi:link-variant", "help.plan_buttons.link_variant.text"],
  ["mdi:pencil", "help.plan_buttons.pencil.text"],
  ["mdi:plus", "help.plan_buttons.plus.text"],
  ["mdi:content-save-outline", "help.plan_buttons.content_save_outline.text"],
  ["mdi:cog", "help.plan_buttons.cog.text"],
];

const PLAN_GESTURES: [string, string, string][] = [
  ["help.plan_gestures.select.what", "help.common.tap_adds_to_the_selection", "help.common.click_selects_just_it"],
  ["help.common.the_one_underneath", "help.plan_gestures.the_one_underneath.touch", "help.common.click_it_again_or_its_button"],
  ["help.common.add_remove_one", "help.common.tap_it", "help.common.shift_ctrl_cmd_click"],
  ["help.common.select_an_area", "help.common.box_select_then_drag_a_new_sel", "help.common.alt_drag_shift_ctrl_cmd_drag_a"],
  ["help.common.move", "help.plan_gestures.move.touch", "help.same"],
  ["help.common.nudge", "help.plan_gestures.nudge.touch", "help.common.arrow_keys_shift_bigger_steps"],
  ["help.common.line_up_space_out", "help.common.select_2_3_to_space_then_align", "help.same"],
  ["help.common.move_the_selection_box", "help.common.drag_its_title_row_double_tap", "help.common.drag_its_title_row_double_clic"],
  ["help.common.deselect_all", "help.common.tap_empty_map", "help.common.click_empty_map"],
  ["help.common.pan", "help.plan_gestures.pan.touch", "help.plan_gestures.pan.mouse"],
  ["help.common.zoom", "help.plan_gestures.zoom.touch", "help.plan_gestures.zoom.mouse"],
];

const PLAN_KEYS: [string, string][] = [
  ["help.plan_keys.v_b_w_n_d_r_s_l_p.what", "help.plan_keys.v_b_w_n_d_r_s_l_p.how"],
  ["help.plan_keys.enter.what", "help.plan_keys.enter.how"],
  ["help.common.esc", "help.plan_keys.esc.how"],
  ["help.common.ctrl_z", "help.common.undo"],
  ["help.common.ctrl_y_ctrl_shift_z", "help.common.redo"],
  ["help.common.delete_backspace", "help.common.delete_selected"],
  ["help.common.ctrl_a", "help.plan_keys.ctrl_a.how"],
  ["help.common.arrows_shift", "help.common.nudge_bigger_steps"],
];

const KEYS: [string, string][] = [
  ["help.common.ctrl_z", "help.common.undo"],
  ["help.common.ctrl_y_ctrl_shift_z", "help.common.redo"],
  ["help.common.delete_backspace", "help.common.delete_selected"],
  ["help.common.ctrl_a", "help.keys.ctrl_a.how"],
  ["help.common.arrows_shift", "help.common.nudge_bigger_steps"],
  ["help.common.esc", "help.common.deselect_all"],
];

// the vacuum's room queue (room-tiles-panel.ts _renderQueueBar)
const QUEUE_ROOMS: [string, string, string][] = [
  ["help.queue_rooms.add_a_room.what", "help.queue_rooms.add_a_room.touch", "help.common.click_it"],
  ["help.queue_rooms.take_it_off.what", "help.common.tap_it_again", "help.common.click_it_again"],
  ["help.queue_rooms.change_the_order.what", "help.queue_rooms.change_the_order.touch", "help.same"],
  ["help.queue_rooms.rooms_on_another_map.what", "help.queue_rooms.rooms_on_another_map.touch", "help.same"],
];

const QUEUE_BUTTONS: [string, string][] = [
  ["mdi:play", "help.queue_buttons.play.text"],
  ["mdi:pause", "help.queue_buttons.pause.text"],
  ["mdi:skip-next", "help.queue_buttons.skip_next.text"],
  ["mdi:stop", "help.queue_buttons.stop.text"],
  ["mdi:toggle-switch-outline", "help.queue_buttons.toggle_switch_outline.text"],
  ["mdi:close", "help.queue_buttons.close.text"],
  ["mdi:home-assistant", "help.queue_buttons.home_assistant.text"],
];

export type HelpMode = "tiles" | "tile-edit" | "view" | "markers" | "plan" | "queue";

// (keys: the dialog's title per page)
const TITLES: Record<HelpMode, string> = {
  tiles: "help.title.tiles",
  "tile-edit": "help.title.tile_edit",
  view: "help.title.view",
  markers: "help.title.markers",
  plan: "help.title.plan",
  queue: "help.title.queue",
};

export class RtMapHelp extends LitElement {
  /** fades where a scrolling area has more (ui.ts ScrollFades) */
  protected readonly _scrollFades = new ScrollFades(this, ".list");

  /** the dialog's top edge stays put while its content changes (dialog-pin.ts) */
  readonly dialogPin = new DialogPin(this);
  static properties = { mode: { type: String } };
  mode: HelpMode = "markers";
  private _opened = Date.now();

  private _close(): void {
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  }

  render() {
    return html`
      <div class="scrim" style="--z:30" @click=${() => Date.now() - this._opened > 400 && this._close()}></div>
      <div class="dialog" style="--z:30" role="dialog" aria-label=${t("help.dialog")}>
        <div class="head">
          <div class="title">${t(TITLES[this.mode])}</div>
          <button class="x" aria-label=${t("common.close")} @click=${this._close}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        ${this.mode !== "markers" && this.mode !== "plan"
          ? ""
          : html`<div class="best">
              <ha-icon icon="mdi:tablet-cellphone"></ha-icon>
              ${t("help.best")}
            </div>`}
        ${{
          plan: () => this._plan(),
          view: () => this._view(),
          markers: () => this._markers(),
          tiles: () => this._tiles(),
          "tile-edit": () => this._tileEdit(),
          queue: () => this._queue(),
        }[
          this.mode
        ]()}
      </div>
    `;
  }

  /** A plain two-column table: what, how. */
  private _pairs(rows: [string, string][]) {
    return html`<table class="pairs">
      <tbody>
        ${rows.map(([what, how]) => html`<tr><th>${t(what)}</th><td>${t(how)}</td></tr>`)}
      </tbody>
    </table>`;
  }

  private _keys(keys: [string, string][]) {
    return html`<table class="keys">
      <tbody>
        ${keys.map(([k, what]) => html`<tr><td>${t(k).split(" · ").map((x, i) => html`${i ? " " : ""}<kbd>${x}</kbd>`)}</td><td>${t(what)}</td></tr>`)}
      </tbody>
    </table>`;
  }

  private _gestures(rows: [string, string, string][]) {
    return html`<table>
      <thead>
        <tr><th></th><th><ha-icon icon="mdi:gesture-tap"></ha-icon> ${t("help.touch")}</th><th><ha-icon icon="mdi:mouse"></ha-icon> ${t("help.mouse")}</th></tr>
      </thead>
      <tbody>
        ${rows.map(([what, touch, mouse]) => html`<tr><th>${t(what)}</th><td>${t(touch)}</td><td>${t(mouse)}</td></tr>`)}
      </tbody>
    </table>`;
  }

  private _tiles() {
    return html`<div class="list">
      <div class="section">${t("help.section.tiles")}</div>
      ${this._gestures(TILE_CONTROLS)}
      <div class="hint">${t("help.tiles_hint")}</div>

      <div class="section">${t("help.section.buttons")}</div>
      <div class="buttons">
        ${TILE_BUTTONS.map(([icon, text]) => html`<ha-icon icon=${icon}></ha-icon><span>${t(text)}</span>`)}
      </div>
    </div>`;
  }

  private _tileEdit() {
    return html`<div class="list">
      <div class="section">${t("help.section.board")}</div>
      ${this._gestures(TILE_EDIT)}
      <div class="hint">${t("help.tile_edit_hint")}</div>
    </div>`;
  }

  private _queue() {
    return html`<div class="list">
      <div class="section">${t("help.section.picking_rooms")}</div>
      ${this._gestures(QUEUE_ROOMS)}
      <div class="hint">${t("help.queue_hint")}</div>

      <div class="section">${t("help.section.buttons")}</div>
      <div class="buttons">
        ${QUEUE_BUTTONS.map(([icon, text]) => html`<ha-icon icon=${icon}></ha-icon><span>${t(text)}</span>`)}
      </div>

      <div class="section">${t("help.section.moving")}</div>
      ${this._gestures(VIEW_MOVING)}
    </div>`;
  }

  private _view() {
    return html`<div class="list">
      <div class="section">${t("help.section.markers")}</div>
      ${this._gestures(VIEW_MARKERS)}
      <div class="hint">${t("help.view_hint")}</div>

      <div class="section">${t("help.section.moving")}</div>
      ${this._gestures(VIEW_MOVING)}

      <div class="section">${t("help.section.buttons")}</div>
      <div class="buttons">
        ${VIEW_BUTTONS.map(([icon, text]) => html`<ha-icon icon=${icon}></ha-icon><span>${t(text)}</span>`)}
      </div>
    </div>`;
  }

  private _markers() {
    return html`<div class="list">
      <div class="section">${t("help.section.layers")}</div>
      <div class="about">
        ${th("help.layers_about", {
          starts: html`<b>${t("layer.starts_at")}</b>`,
          ends: html`<b>${t("layer.ends_at")}</b>`,
          link: html`<button class="link" @click=${() => this.dispatchEvent(new CustomEvent("layer-settings", { bubbles: true, composed: true }))}>
            ${t("help.layer_settings_link")}
          </button>`,
        })}
      </div>
      <div class="about">${t("help.layers_zoom")}</div>

      <div class="section">${t("help.section.buttons")}</div>
      <div class="buttons">
        ${BUTTONS.map(([icon, text]) => html`<ha-icon icon=${icon}></ha-icon><span>${t(text)}</span>`)}
      </div>

      <div class="section">${t("help.section.selecting")}</div>
      ${this._gestures(GESTURES)}
      <div class="hint">${t("help.markers_hint")}</div>

      <div class="section">${t("help.section.keyboard")} <span class="dim">${t("help.cmd_on_mac")}</span></div>
      ${this._keys(KEYS)}
    </div>`;
  }

  private _plan() {
    return html`<div class="list">
      <div class="section">${t("help.section.tools")}</div>
      <table class="tools">
        <tbody>
          ${PLAN_TOOLS.map(([icon, name, how]) => html`<tr><td class="ic"><ha-icon icon=${icon}></ha-icon></td><th>${t(name)}</th><td>${t(how)}</td></tr>`)}
        </tbody>
      </table>

      <div class="section">${t("help.section.drawing")}</div>
      ${this._pairs(PLAN_DRAWING)}

      <div class="section">${t("help.section.picture")}</div>
      ${this._pairs(PLAN_PICTURE)}

      <div class="section">${t("help.section.selecting")}</div>
      ${this._gestures(PLAN_GESTURES)}

      <div class="section">${t("help.section.buttons")}</div>
      <div class="buttons">
        ${PLAN_BUTTONS.map(([icon, text]) => html`<ha-icon icon=${icon}></ha-icon><span>${t(text)}</span>`)}
      </div>

      <div class="section">${t("help.section.keyboard")} <span class="dim">${t("help.cmd_on_mac")}</span></div>
      ${this._keys(PLAN_KEYS)}
    </div>`;
  }

  static styles = [noSelectStyles, 
    dialogStyles,
    css`
      .best {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.9rem;
        color: var(--rt-text-secondary);
        --mdc-icon-size: 18px;
      }
      :host {
        --dialog-w: 560px;
      }
      .about {
        font-size: 0.9rem;
        line-height: 1.4;
      }
      .section {
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--rt-text-secondary);
        margin: 8px 0 2px;
      }
      .section .dim {
        text-transform: none;
        letter-spacing: 0;
      }
      .buttons {
        display: grid;
        grid-template-columns: 24px 1fr;
        gap: 6px 10px;
        align-items: center;
        font-size: 0.9rem;
        --mdc-icon-size: 20px;
      }
      table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.86rem;
      }
      th,
      td {
        text-align: left;
        vertical-align: top;
        padding: 5px 6px;
        border-bottom: 1px solid var(--rt-tile-border);
      }
      thead th {
        color: var(--rt-text-secondary);
        font-weight: 600;
        white-space: nowrap;
        --mdc-icon-size: 16px;
      }
      tbody th {
        font-weight: 600;
        width: 28%;
      }
      tr:last-child > * {
        border-bottom: none;
      }
      table.pairs th {
        width: 30%;
      }
      .tools td.ic {
        width: 24px;
        --mdc-icon-size: 20px;
      }
      .tools th {
        white-space: nowrap;
        width: auto;
      }
      ha-icon.inline {
        --mdc-icon-size: 16px;
        vertical-align: -2px;
      }
      .keys td:first-child {
        width: 45%;
      }
      kbd {
        font: inherit;
        font-size: 0.8rem;
        padding: 1px 6px;
        border-radius: 5px;
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        white-space: nowrap;
      }
    `,
  ];
}

if (!customElements.get("rt-map-help")) customElements.define("rt-map-help", RtMapHelp);
