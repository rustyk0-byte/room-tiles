// Room Tiles panel: the settings menu, the area picker and tile editing with
// its tile picker - like the original panels (and the dashboard's tile
// editor): tap a tile to change it, press and hold to pick it up, then tap
// where it goes (the two swap; the same tile again puts it back); Done ends.
// Every change goes to Room Tiles (signed actions); the new board comes back
// as a new payload. (Picking rooms on the house plan comes with the map.)

#include <algorithm>
#include <cstdio>
#include <cstring>

#include "board.h"
#include "drag_bar.h"
#include "esphome/core/application.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"
#include "room_tiles.h"

namespace esphome::room_tiles {

static const char *const TAG = "room_tiles.edit";

// the picker's categories: which kinds each shows, and its icon. The last
// one, "..." (three dots, no icon), gathers the kinds a home has only a few
// of - thermostats, appliances, pools, vacuums - and the Map tile.
struct Category {
  const char *kinds[4];
  AssetId icon;
};
static const Category CATEGORIES[] = {
    {{"onoff_light", "dimmable_light", "color_light", nullptr}, IMG_ICON_LIGHT_M},
    {{"switch", nullptr, nullptr, nullptr}, IMG_ICON_SWITCH_M},
    {{"fan", nullptr, nullptr, nullptr}, IMG_ICON_FAN_M},
    {{"cover", nullptr, nullptr, nullptr}, IMG_ICON_BLIND_M},
    {{"lock", nullptr, nullptr, nullptr}, IMG_ICON_KEY_M},
    {{"scene", nullptr, nullptr, nullptr}, IMG_ICON_SCENE_M},
    {{"script", nullptr, nullptr, nullptr}, IMG_ICON_SCRIPT_M},
    {{"climate", "appliance", "water", "vacuum"}, IMG_COUNT},
};
static const int CAT_MORE = 7;  // ("...": also the Map tile)
// a row's icon by its kind (a light's, a lock's... its category's)
static AssetId kind_icon(const std::string &kind) {
  if (kind == "climate")
    return IMG_ICON_AC_M;
  if (kind == "appliance")
    return IMG_ICON_DISHWASHER_M;
  if (kind == "water")
    return IMG_ICON_POOL_M;
  if (kind == "vacuum")
    return IMG_ICON_ROBOT_VACUUM_M;
  return IMG_COUNT;
}
static const int N_CATEGORIES = sizeof(CATEGORIES) / sizeof(CATEGORIES[0]);
static_assert(CAT_MORE == N_CATEGORIES - 1, "\"...\" is the last category");

static std::string json_str(const std::string &s) {
  std::string out = "\"";
  for (char c : s) {
    if (c == '"' || c == '\\')
      out += '\\';
    out += c;
  }
  return out + "\"";
}

static lv_obj_t *label(lv_obj_t *parent, const std::string &text, const lv_font_t *font, uint32_t colour) {
  lv_obj_t *l = lv_label_create(parent);
  lv_label_set_text(l, text.c_str());
  lv_obj_set_style_text_font(l, font, 0);
  lv_obj_set_style_text_color(l, lv_color_hex(colour), 0);
  return l;
}

// A scrolling list: a thin visible scroll bar (stripped styles hide LVGL's)
static void style_scroll(lv_obj_t *o, uint32_t bar) {
  lv_obj_set_scroll_dir(o, LV_DIR_VER);
  lv_obj_set_scrollbar_mode(o, LV_SCROLLBAR_MODE_AUTO);
  lv_obj_set_style_width(o, 6, LV_PART_SCROLLBAR);
  lv_obj_set_style_radius(o, 3, LV_PART_SCROLLBAR);
  lv_obj_set_style_bg_opa(o, LV_OPA_COVER, LV_PART_SCROLLBAR);
  lv_obj_set_style_bg_color(o, lv_color_hex(bar), LV_PART_SCROLLBAR);
  lv_obj_set_style_pad_right(o, 3, LV_PART_SCROLLBAR);
  lv_obj_set_style_pad_ver(o, 6, LV_PART_SCROLLBAR);
}


// A settings slider (brightness, sleep): a rounded track, the accent's
// indicator, a 28 px white knob - easy to grab on the 7"
static lv_obj_t *slider(lv_obj_t *parent, int w, int lo, int hi, int value, uint32_t track, uint32_t accent) {
  lv_obj_t *sl = lv_slider_create(parent);
  lv_obj_remove_style_all(sl);
  lv_obj_set_size(sl, w, 10);
  lv_slider_set_range(sl, lo, hi);
  lv_slider_set_value(sl, value, LV_ANIM_OFF);
  lv_obj_set_style_radius(sl, 5, 0);
  lv_obj_set_style_bg_opa(sl, LV_OPA_COVER, 0);
  lv_obj_set_style_bg_color(sl, lv_color_hex(track), 0);
  lv_obj_set_style_radius(sl, 5, LV_PART_INDICATOR);
  lv_obj_set_style_bg_opa(sl, LV_OPA_COVER, LV_PART_INDICATOR);
  lv_obj_set_style_bg_color(sl, lv_color_hex(accent), LV_PART_INDICATOR);
  lv_obj_set_style_radius(sl, LV_RADIUS_CIRCLE, LV_PART_KNOB);
  lv_obj_set_style_bg_opa(sl, LV_OPA_COVER, LV_PART_KNOB);
  lv_obj_set_style_bg_color(sl, lv_color_hex(0xFFFFFF), LV_PART_KNOB);
  lv_obj_set_style_pad_all(sl, 9, LV_PART_KNOB);  // (a 28 px knob)
  lv_obj_set_ext_click_area(sl, 20);              // (the 7")
  return sl;
}

static lv_obj_t *button(lv_obj_t *parent, int w, int h, uint32_t bg) {
  lv_obj_t *b = lv_button_create(parent);
  lv_obj_remove_style_all(b);
  lv_obj_set_size(b, w, h);
  lv_obj_set_style_radius(b, 10, 0);
  lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
  lv_obj_set_style_bg_color(b, lv_color_hex(bg), 0);
  return b;
}

// ---- edit mode ----------------------------------------------------------------------

void Board::set_editing(bool on) {
  this->editing_ = on;
  this->picked_ = -1;
  this->close_dialog_();
  if (this->model_ != nullptr)
    this->build(*this->model_);
}

void Board::build_edit_(TileView &tv) {
  // over the whole tile, so its own controls rest while editing
  tv.edit = lv_obj_create(tv.box);
  lv_obj_remove_style_all(tv.edit);
  lv_obj_set_size(tv.edit, lv_pct(100), lv_pct(100));
  lv_obj_add_flag(tv.edit, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_event_cb(tv.edit, &Board::on_edit_tap_, LV_EVENT_SHORT_CLICKED, &tv);
  lv_obj_add_event_cb(tv.edit, &Board::on_edit_hold_, LV_EVENT_LONG_PRESSED, &tv);
  this->paint_edit_(tv);
}

void Board::paint_edit_(TileView &tv) {
  // the dashboard's look: amber while editing, the picked-up tile accent blue
  const bool picked = this->picked_ == tv.slot;
  lv_obj_set_style_border_width(tv.box, picked ? 3 : 2, 0);
  lv_obj_set_style_border_opa(tv.box, LV_OPA_COVER, 0);
  lv_obj_set_style_border_color(tv.box, lv_color_hex(picked ? this->color_("accent", 0x4B9EF3) : this->color_("light", 0xFFB300)), 0);
  if (this->hint_ != nullptr) {
    std::string h = this->rt_->t("panel.edit_hint");
    if (this->picked_ >= 0) {
      h = this->rt_->t("panel.move_hint");
      const size_t at = h.find("{now}");
      if (at != std::string::npos)
        h.replace(at, 5, this->rt_->t("panel.move_now"));
    }
    lv_label_set_text(this->hint_, h.c_str());
  }
}

void Board::edit_tap_(TileView &tv) {
  if (this->picked_ >= 0) {
    // the drop: the same tile = put it back; another = the two swap
    const int from = this->picked_;
    this->picked_ = -1;
    if (from != tv.slot) {
      char data[160];
      snprintf(data, sizeof(data), "{\"area\":%s,\"layout\":%s,\"from_slot\":%d,\"to_slot\":%d}",
               json_str(this->area_).c_str(), json_str(this->layout_).c_str(), from, tv.slot);
      this->rt_->actions().call("room_tiles.move_tile", "", data);
      this->wait_for_({from, tv.slot});
    }
    for (auto &t : this->tiles_)
      this->paint_edit_(t);
    return;
  }
  this->open_picker_(tv.slot);
}

void Board::edit_hold_(TileView &tv) {
  this->picked_ = tv.slot;
  for (auto &t : this->tiles_)
    this->paint_edit_(t);
}

void Board::on_edit_tap_(lv_event_t *e) {
  auto *tv = static_cast<TileView *>(lv_event_get_user_data(e));
  if (tv != nullptr && tv->board != nullptr)
    tv->board->edit_tap_(*tv);
}

void Board::on_edit_hold_(lv_event_t *e) {
  auto *tv = static_cast<TileView *>(lv_event_get_user_data(e));
  if (tv != nullptr && tv->board != nullptr)
    tv->board->edit_hold_(*tv);
}

void Board::on_done_(lv_event_t *e) {
  auto *self = static_cast<Board *>(lv_event_get_user_data(e));
  // (rebuilding deletes this button: after its event)
  lv_async_call([](void *p) { static_cast<Board *>(p)->set_editing(false); }, self);
}

// ---- dialogs ---------------------------------------------------------------------

void Board::close_dialog_() {
  if (this->scrim_ != nullptr)
    lv_obj_delete_async(this->scrim_);
  this->scrim_ = nullptr;
  this->pick_list_ = this->pick_areas_ = this->pick_assign_ = nullptr;
  this->pick_cat_btns_.clear();
  this->pick_slot_ = -1;
}

lv_obj_t *Board::dialog_(int w, int h, const std::string &title) {
  this->close_dialog_();
  this->scrim_ = lv_obj_create(lv_layer_top());
  lv_obj_remove_style_all(this->scrim_);
  lv_obj_set_size(this->scrim_, 1024, 600);
  // MIRRORED: frontend/src/ui.ts .scrim - a change here must be made there too.
  // (the page's colour, 60%: dark themes darken, Light lightens - a dark scrim
  // over white tiles made a mid gray that shimmered on the 10.1" screen)
  lv_obj_set_style_bg_color(this->scrim_, lv_color_hex(this->color_("page", 0x000000)), 0);
  lv_obj_set_style_bg_opa(this->scrim_, LV_OPA_60, 0);
  lv_obj_add_flag(this->scrim_, LV_OBJ_FLAG_CLICKABLE);
  // a tap on the scrim itself (not the dialog) closes
  lv_obj_add_event_cb(
      this->scrim_,
      [](lv_event_t *e) {
        if (lv_event_get_target(e) == lv_event_get_current_target(e))
          static_cast<Board *>(lv_event_get_user_data(e))->close_dialog_();
      },
      LV_EVENT_CLICKED, this);
  lv_obj_t *d = lv_obj_create(this->scrim_);
  lv_obj_remove_style_all(d);
  lv_obj_set_size(d, w, h);
  lv_obj_center(d);
  lv_obj_set_style_bg_color(d, lv_color_hex(this->color_("dialog", 0x2A2A2A)), 0);
  lv_obj_set_style_bg_opa(d, LV_OPA_COVER, 0);
  lv_obj_set_style_border_width(d, 1, 0);
  lv_obj_set_style_border_color(d, lv_color_hex(this->color_("tileBorder", 0x4A4A4A)), 0);
  lv_obj_set_style_radius(d, 12, 0);
  lv_obj_add_flag(d, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_remove_flag(d, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_t *t = label(d, title, this->fonts_.bar, this->color_("text", 0xFFFFFF));
  lv_obj_align(t, LV_ALIGN_TOP_LEFT, 18, 14);
  // close: framed like every other close on the panel (the top bars')
  lv_obj_t *x = bar_button(d, this->color_("button", 0x333333), this->color_("tileBorder", 0x4A4A4A), 6);
  lv_obj_align(x, LV_ALIGN_TOP_RIGHT, -10, 10);
  lv_obj_add_event_cb(
      x, [](lv_event_t *e) { static_cast<Board *>(lv_event_get_user_data(e))->close_dialog_(); }, LV_EVENT_CLICKED,
      this);
  lv_obj_center(label(x, "\U000F0156", this->fonts_.glyph, this->color_("text", 0xFFFFFF)));  // mdi:close
  return d;
}

// MIRRORED: frontend/src/map-help.ts (the pages' rows; the panel's own lines where it differs) - a change here must be made there too.
// ---- the Help page (the dashboard's, map-help.ts "tiles") ---------------------------------

// "Buttons" -> "BUTTONS" (the section headings; Latin-1 letters too: "ä" -> "Ä")
static std::string upper(const std::string &s) {
  std::string out = s;
  for (size_t i = 0; i < out.size(); i++) {
    const unsigned char c = out[i];
    if (c >= 'a' && c <= 'z') {
      out[i] = (char) (c - 32);
    } else if (c == 0xC3 && i + 1 < out.size()) {
      const unsigned char n = out[i + 1];
      if (n >= 0xA0 && n <= 0xBE && n != 0xB7)  // (U+00E0-U+00FE, not "÷")
        out[i + 1] = (char) (n - 0x20);
      i++;
    }
  }
  return out;
}

// The pages: the dashboard's (map-help.ts), for touch, as the panel has them:
// its own lines where it differs (zooming with the zoom box, its settings,
// adding a room by tapping it); what it doesn't have left out (full screen,
// the HA Card, the queue's Rooms list and order arrows, Auto configure)
struct HelpRow {
  const char *what, *how;
};
struct HelpBtn {
  const char *glyph, *key;  // (glyph "": a word button - its text says it)
};
struct HelpSection {
  const char *title;
  const HelpRow *rows;
  int n_rows;
  const char *hint;
  const HelpBtn *btns;
  int n_btns;
};
#define HELP_N(a) ((int) (sizeof(a) / sizeof((a)[0])))

static const HelpRow TILE_ROWS[] = {
    {"help.tile_controls.on_off.what", "help.tile_controls.on_off.touch"},
    {"help.tile_controls.brightness_position_speed_te.what", "help.tile_controls.brightness_position_speed_te.touch"},
    {"help.tile_controls.color.what", "help.tile_controls.color.touch"},
    {"help.tile_controls.pool_spa_heater.what", "help.tile_controls.pool_spa_heater.touch"},
    {"help.tile_controls.appliance.what", "help.tile_controls.appliance.touch"},
    {"help.tile_controls.robot_vacuum.what", "help.tile_controls.robot_vacuum.touch"},
    {"help.tile_controls.scene_script.what", "help.tile_controls.scene_script.touch"},
};
static const HelpBtn TILE_BTNS[] = {
    {"\U000F035D", "help.tile_buttons.menu_down.text"},                // mdi:menu-down
    {"\U000F02C1", "help.tile_buttons.grid.text"},                     // mdi:grid
    {"\U000F0821", "help.tile_buttons.floor_plan.text"},               // mdi:floor-plan
    {"\U000F1254", "help.tile_buttons.lightbulb_group_outline.text"},  // mdi:lightbulb-group-outline
    {"\U000F0493", "help.tile_buttons.cog.panel"},                     // mdi:cog (the panel's settings)
};
static const HelpRow EDIT_ROWS[] = {
    {"help.tile_edit.change_a_tile.what", "help.tile_edit.change_a_tile.touch"},
    {"help.tile_edit.move_a_tile.what", "help.tile_edit.move_a_tile.touch"},
    {"help.tile_edit.put_it_back.what", "help.common.tap_it_again"},
    {"help.tile_edit.finish.what", "help.tile_edit.finish.touch"},
};
static const HelpRow MARKER_ROWS[] = {
    {"help.view_markers.switch_it.what", "help.view_markers.switch_it.touch"},
    {"help.view_markers.full_controls.what", "help.view_markers.full_controls.touch"},
    {"help.view_markers.close_the_tile.what", "help.view_markers.close_the_tile.touch"},
};
static const HelpRow MOVING_ROWS[] = {
    {"help.view_moving.into_a_room.what", "help.view_moving.into_a_room.touch"},
    {"help.view_moving.whole_map_again.what", "help.view_moving.whole_map_again.touch"},
    {"help.common.zoom", "help.view_moving.zoom.panel"},
    {"help.common.pan", "help.common.drag"},
    {"help.view_moving.another_map.what", "help.view_moving.another_map.touch"},
    {"help.view_moving.more_detail.what", "help.view_moving.more_detail.touch"},
};
static const HelpBtn VIEW_BTNS[] = {
    {"\U000F0493", "help.tile_buttons.cog.panel"},  // mdi:cog
    {"\U000F0156", "help.view_buttons.close.text"},  // mdi:close
};
static const HelpRow QUEUE_ROWS[] = {
    {"help.queue_rooms.add_a_room.what", "help.queue_rooms.add_a_room.panel"},
    {"help.queue_rooms.take_it_off.what", "help.common.tap_it_again"},
    {"help.queue_rooms.rooms_on_another_map.what", "help.queue_rooms.rooms_on_another_map.touch"},
};
static const HelpBtn QUEUE_BTNS[] = {
    {"\U000F040A", "help.queue_buttons.play.text"},                   // mdi:play
    {"\U000F03E4", "help.queue_buttons.pause.text"},                  // mdi:pause
    {"\U000F04AD", "help.queue_buttons.skip_next.text"},              // mdi:skip-next
    {"\U000F04DB", "help.queue_buttons.stop.text"},                   // mdi:stop
    {"\U000F0A1A", "help.queue_buttons.toggle_switch_outline.text"},  // mdi:toggle-switch-outline
    {"", "help.queue_buttons.close.text"},                            // (Clear: a word button)
};

void Board::open_help(const std::string &mode) {
  std::vector<HelpSection> page;
  const char *title = "help.title.tiles";
  if (mode == "tile-edit") {
    title = "help.title.tile_edit";
    page = {{"help.section.board", EDIT_ROWS, HELP_N(EDIT_ROWS), nullptr, nullptr, 0}};
  } else if (mode == "view") {
    title = "help.title.view";
    page = {{"help.section.markers", MARKER_ROWS, HELP_N(MARKER_ROWS), "help.view_hint", nullptr, 0},
            {"help.section.moving", MOVING_ROWS, HELP_N(MOVING_ROWS), nullptr, nullptr, 0},
            {"help.section.buttons", nullptr, 0, nullptr, VIEW_BTNS, HELP_N(VIEW_BTNS)},
            // (maps are changed on the dashboard - the panel only shows them)
            {"help.section.changing_map", nullptr, 0, "help.view_edit_panel", nullptr, 0}};
  } else if (mode == "queue") {
    title = "help.title.queue";
    page = {{"help.section.picking_rooms", QUEUE_ROWS, HELP_N(QUEUE_ROWS), "help.queue_hint", nullptr, 0},
            {"help.section.buttons", nullptr, 0, nullptr, QUEUE_BTNS, HELP_N(QUEUE_BTNS)},
            {"help.section.moving", MOVING_ROWS, HELP_N(MOVING_ROWS), nullptr, nullptr, 0}};
  } else {
    page = {{"help.section.tiles", TILE_ROWS, HELP_N(TILE_ROWS), "help.tiles_hint", nullptr, 0},
            {"help.section.buttons", nullptr, 0, nullptr, TILE_BTNS, HELP_N(TILE_BTNS)}};
  }

  // (the text clear of the scroll bar's strip on the right: 44 px)
  const int W = 760, H = 540, pad = 24, inner = W - pad - 44 - 8;
  lv_obj_t *d = this->dialog_(W, H, this->rt_->t(title));
  const uint32_t text = this->color_("text", 0xFFFFFF), dim = this->color_("textSecondary", 0x9E9E9E),
                 line = this->color_("tileBorder", 0x4A4A4A);
  // the page scrolls under the title
  lv_obj_t *list = lv_obj_create(d);
  lv_obj_remove_style_all(list);
  lv_obj_set_pos(list, pad, 60);
  lv_obj_set_size(list, W - pad - 8, H - 60 - 12);  // (up to the scroll bar's strip's right edge)
  lv_obj_set_flex_flow(list, LV_FLEX_FLOW_COLUMN);
  lv_obj_set_style_pad_bottom(list, 12, 0);
  lv_obj_set_scroll_dir(list, LV_DIR_VER);
  auto wrapped = [&](lv_obj_t *parent, const std::string &s, uint32_t colour, int w) {
    lv_obj_t *l = label(parent, s, this->fonts_.name_s, colour);
    lv_label_set_long_mode(l, LV_LABEL_LONG_MODE_WRAP);
    lv_obj_set_width(l, w);
    return l;
  };
  auto row = [&](bool rule) {
    lv_obj_t *r = lv_obj_create(list);
    lv_obj_remove_style_all(r);
    lv_obj_set_size(r, inner, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(r, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_column(r, 12, 0);
    lv_obj_remove_flag(r, LV_OBJ_FLAG_SCROLLABLE);
    if (rule) {  // (a line under it: the table's rows)
      lv_obj_set_style_border_side(r, LV_BORDER_SIDE_BOTTOM, 0);
      lv_obj_set_style_border_width(r, 1, 0);
      lv_obj_set_style_border_color(r, lv_color_hex(line), 0);
    }
    return r;
  };
  const int what_w = inner * 30 / 100;
  for (const HelpSection &sec : page) {
    lv_obj_t *h = label(list, upper(this->rt_->t(sec.title)), this->fonts_.prefix, dim);
    lv_obj_set_style_pad_top(h, 14, 0);
    lv_obj_set_style_pad_bottom(h, 4, 0);
    // what, and how
    for (int i = 0; i < sec.n_rows; i++) {
      lv_obj_t *r = row(i + 1 < sec.n_rows);
      lv_obj_set_style_pad_ver(r, 7, 0);
      wrapped(r, this->rt_->t(sec.rows[i].what), text, what_w);
      wrapped(r, this->rt_->t(sec.rows[i].how), text, inner - what_w - 12);
    }
    if (sec.hint != nullptr) {
      lv_obj_t *hint = wrapped(list, this->rt_->t(sec.hint), dim, inner);
      lv_obj_set_style_pad_top(hint, 8, 0);
    }
    // the buttons: icon, what it does
    for (int i = 0; i < sec.n_btns; i++) {
      lv_obj_t *r = row(false);
      lv_obj_set_flex_align(r, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
      lv_obj_set_style_pad_ver(r, 4, 0);
      lv_obj_t *g = label(r, sec.btns[i].glyph, this->fonts_.menu, text);
      lv_obj_set_width(g, 24);
      wrapped(r, this->rt_->t(sec.btns[i].key), text, inner - 24 - 12);
    }
  }
  // a scroll bar you can drag (more below: it shows)
  dragbar_attach(d, list, this->color_("textSecondary", 0x9E9E9E));
}

// ---- a screenshot's notice ---------------------------------------------------------

void Board::screenshot_notice(bool saved, const std::string &file) {
  lv_obj_t *d = this->dialog_(600, 210, this->rt_->t("panel.screenshot"));
  std::string s = this->rt_->t(saved ? "panel.screenshot_saved" : "panel.screenshot_failed");
  if (saved) {
    // where: HA's media folder, the panels' folder, the file
    s += "\n" + this->rt_->t("panel.screenshot_where");
    if (!file.empty())
      s += " \xE2\x80\xBA " + file;  // ›
  }
  lv_obj_t *l = label(d, s, this->fonts_.name_s, this->color_("text", 0xFFFFFF));
  lv_label_set_long_mode(l, LV_LABEL_LONG_MODE_WRAP);
  lv_obj_set_width(l, 600 - 48);
  lv_obj_set_pos(l, 24, 70);
}

// ---- the settings menu (the gear) ------------------------------------------------------

void Board::on_settings_(lv_event_t *e) { static_cast<Board *>(lv_event_get_user_data(e))->open_settings_(); }

// The settings menu (the old panels'): the screen's brightness and sleep
// time (kept on the panel), then tile editing, the 24-hour clock (a switch;
// the area is picked from its name in the top bar), the language, a
// screenshot, restart (at the bottom right, away from the others)
void Board::open_settings_() {
  const bool langs = this->model_ != nullptr && this->model_->languages.size() > 1;
  const bool themes = this->model_ != nullptr && this->model_->themes.size() > 1;
  // (Change Wi-Fi: the installer's panels - a hand-built one's networks are
  // in its firmware)
  const bool wifi = this->rt_->generic();
  // (taller with a third row of buttons: language or Change Wi-Fi shown);
  // the theme's and "When idle" share a row
  const int grid_y = 240 + 68;  // the buttons, under that row
  lv_obj_t *d = this->dialog_(580, (langs || wifi ? 468 : 400) + 68, this->rt_->t("common.settings"));
  this->theme_row_ = nullptr;
  this->idle_row_ = nullptr;
  const uint32_t text = this->color_("text", 0xFFFFFF), dim = this->color_("textSecondary", 0x9E9E9E);
  const uint32_t accent = this->color_("accent", 0x4B9EF3);

  // a slider row: its name, its value on the right, the slider under them
  auto slider_row = [&](int y, const std::string &name, int lo, int hi, int value, lv_event_cb_t cb) {
    lv_obj_t *n = label(d, name, this->fonts_.name, text);
    lv_obj_set_pos(n, 24, y);
    lv_obj_t *v = label(d, "", this->fonts_.name, dim);
    lv_obj_align(v, LV_ALIGN_TOP_RIGHT, -24, y);
    lv_obj_t *sl = slider(d, 520, lo, hi, value, this->color_("button", 0x3A3A3A), accent);
    lv_obj_set_pos(sl, 30, y + 44);
    lv_obj_set_user_data(sl, v);
    lv_obj_add_event_cb(sl, cb, LV_EVENT_VALUE_CHANGED, this);
    lv_obj_add_event_cb(sl, cb, LV_EVENT_RELEASED, this);
    lv_obj_send_event(sl, LV_EVENT_VALUE_CHANGED, nullptr);  // (its value shown)
    return sl;
  };
  // MIRRORED: board_strip.cpp open_strip_settings_ (the round panel's sliders) - a change here must be made there too.
  // brightness 10-100 % in 5s; live, kept when let go
  slider_row(66, this->rt_->t("panel.brightness"), 2, 20, this->rt_->brightness() / 5, [](lv_event_t *e) {
    auto *self = static_cast<Board *>(lv_event_get_user_data(e));
    lv_obj_t *sl = lv_event_get_current_target_obj(e);
    const int pct = lv_slider_get_value(sl) * 5;
    lv_label_set_text(static_cast<lv_obj_t *>(lv_obj_get_user_data(sl)), (std::to_string(pct) + " %").c_str());
    self->rt_->set_brightness(pct, lv_event_get_code(e) == LV_EVENT_RELEASED);
  });
  // the screen off after 5-90 s untouched, in 5s; 0 = never
  slider_row(150, this->rt_->t("panel.sleep"), 0, 18, this->rt_->sleep_seconds() / 5, [](lv_event_t *e) {
    auto *self = static_cast<Board *>(lv_event_get_user_data(e));
    lv_obj_t *sl = lv_event_get_current_target_obj(e);
    const int secs = lv_slider_get_value(sl) * 5;
    std::string v = self->rt_->t("panel.sleep_never");
    if (secs > 0) {
      v = self->rt_->t("panel.seconds");
      const size_t at = v.find("{n}");
      if (at != std::string::npos)
        v.replace(at, 3, std::to_string(secs));
    }
    lv_label_set_text(static_cast<lv_obj_t *>(lv_obj_get_user_data(sl)), v.c_str());
    self->rt_->set_sleep(secs, lv_event_get_code(e) == LV_EVENT_RELEASED);
  });

  // MIRRORED: frontend/src/room-tiles-panel.ts _renderMenu (⚙ → Theme) - a change here must be made there too.
  // the theme: a drop-down row like the dashboard's (its name, the theme in
  // use on the right); a tap opens the list over it
  // a drop-down row: its name, what's chosen (cut short to fit), the triangle
  auto dropdown_row = [&](int x, int w, const std::string &name, const std::string &value, lv_event_cb_t cb) {
    lv_obj_t *row = button(d, w, 56, this->color_("button", 0x3A3A3A));
    lv_obj_set_pos(row, x, 240);
    lv_obj_add_event_cb(row, cb, LV_EVENT_CLICKED, this);
    lv_obj_t *n = label(row, name, this->fonts_.name, text);
    lv_obj_align(n, LV_ALIGN_LEFT_MID, 16, 0);
    lv_obj_t *g = label(row, "\U000F035D", this->fonts_.glyph, text);  // mdi:menu-down
    lv_obj_align(g, LV_ALIGN_RIGHT_MID, -8, 0);
    lv_obj_update_layout(n);
    lv_obj_t *v = label(row, value, this->fonts_.prefix, dim);
    lv_label_set_long_mode(v, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_width(v, std::max(40, w - 16 - (int) lv_obj_get_width(n) - 10 - 40));
    lv_obj_set_style_text_align(v, LV_TEXT_ALIGN_RIGHT, 0);
    lv_obj_align_to(v, g, LV_ALIGN_OUT_LEFT_MID, -4, 0);
    return row;
  };
  // the theme (left half) and when idle (the right half - the whole row
  // without a theme to pick)
  if (themes) {
    const PanelModel &m = *this->model_;
    const std::string &now = m.own_theme.empty() ? m.theme : m.own_theme;
    this->theme_row_ = dropdown_row(24, 262, this->rt_->t("menu.theme"), this->theme_name_(now),
                                    [](lv_event_t *e) { static_cast<Board *>(lv_event_get_user_data(e))->open_theme_list_(); });
  }
  // MIRRORED: board_strip.cpp open_strip_settings_ (the round panel's "When idle") - a change here must be made there too.
  static const char *const IDLE_KEYS[] = {"panel.idle_off", "panel.idle_digital", "panel.idle_analog", "panel.idle_theme"};
  this->idle_row_ = dropdown_row(themes ? 294 : 24, themes ? 262 : 532, this->rt_->t("panel.idle"),
                                 this->rt_->t(IDLE_KEYS[std::max(0, std::min(3, this->rt_->idle_mode()))]),
                                 [](lv_event_t *e) { static_cast<Board *>(lv_event_get_user_data(e))->open_idle_list_(); });

  struct Row {
    const char *key;
    void (*run)(Board *);
  };
  static const Row ROWS[] = {
      {"menu.tile_editor", [](Board *b) {
         b->rt_->close_map();  // (opened from the map: the tiles it edits)
         b->set_editing(true);
       }},
      {"panel.clock_24h", nullptr},  // (a switch: On / Off in place)
      {"menu.language", [](Board *b) { b->open_languages_(); }},
      {"panel.screenshot", [](Board *b) {
         b->close_dialog_();  // (the screen under the menu)
         b->rt_->take_screenshot(true);
       }},
      {"panel.wifi_change", [](Board *b) { b->confirm_wifi_change_(); }},
      {"panel.restart_panel", [](Board *b) { b->confirm_restart_(); }},
  };
  int i = 0;
  for (const Row &r : ROWS) {
    if (strcmp(r.key, "menu.language") == 0 && !langs)
      continue;
    if (strcmp(r.key, "panel.wifi_change") == 0 && !wifi)
      continue;
    if (strcmp(r.key, "panel.restart_panel") == 0 && i % 2 == 0)
      i++;  // (on the right: not under Language, the left column)
    lv_obj_t *b = button(d, 256, 56, this->color_("button", 0x3A3A3A));
    lv_obj_set_pos(b, 24 + (i % 2) * 276, grid_y + (i / 2) * 68);
    if (r.run == nullptr) {
      // MIRRORED: board_strip.cpp open_strip_settings_ (the round panel's 24-hour clock) - a change here must be made there too.
      // the 24-hour clock: its word, On / Off at the right (the idle list's switches)
      lv_obj_t *state = label(b, this->rt_->t(this->rt_->hours12() ? "common.off" : "common.on"), this->fonts_.name, accent);
      lv_obj_align(state, LV_ALIGN_RIGHT_MID, -16, 0);
      lv_obj_update_layout(state);
      lv_obj_t *word = label(b, this->rt_->t(r.key), this->fonts_.name, text);
      lv_label_set_long_mode(word, LV_LABEL_LONG_MODE_DOTS);
      lv_obj_set_width(word, 256 - 18 - 16 - 10 - std::max<int>(40, lv_obj_get_width(state)));
      lv_obj_align(word, LV_ALIGN_LEFT_MID, 18, 0);
      lv_obj_set_user_data(b, state);
      lv_obj_add_event_cb(
          b,
          [](lv_event_t *e) {
            auto *r = static_cast<Board *>(lv_event_get_user_data(e))->rt_;
            r->set_hours24(r->hours12());
            lv_label_set_text(static_cast<lv_obj_t *>(lv_obj_get_user_data(lv_event_get_current_target_obj(e))),
                              r->t(r->hours12() ? "common.off" : "common.on").c_str());
          },
          LV_EVENT_CLICKED, this);
      i++;
      continue;
    }
    lv_obj_set_user_data(b, (void *) &r);
    lv_obj_add_event_cb(
        b,
        [](lv_event_t *e) {
          auto *self = static_cast<Board *>(lv_event_get_user_data(e));
          auto *row = static_cast<const Row *>(lv_obj_get_user_data(static_cast<lv_obj_t *>(lv_event_get_current_target(e))));
          // (the next step deletes this dialog: after this event)
          static const Row *pending = nullptr;
          pending = row;
          lv_async_call([](void *p) { pending->run(static_cast<Board *>(p)); }, self);
        },
        LV_EVENT_CLICKED, this);
    lv_obj_t *l = label(b, this->rt_->t(r.key), this->fonts_.name, text);
    lv_label_set_long_mode(l, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_width(l, 256 - 36);
    lv_obj_align(l, LV_ALIGN_LEFT_MID, 18, 0);
    i++;
  }
  // something found to set up (an appliance, a pool, a vacuum): said here,
  // as the gear's dot says - it's set up on the dashboard
  if (this->model_ != nullptr && this->model_->found > 0) {
    // seen: the gears' dots go (until the count changes)
    if (this->found_seen_ != this->model_->found) {
      this->found_seen_ = this->model_->found;
      if (this->gear_dot_ != nullptr)
        lv_obj_add_flag(this->gear_dot_, LV_OBJ_FLAG_HIDDEN);
      this->rt_->map_view().found_seen();
    }
    // two lines: what (set it up in Home Assistant), then where - the
    // dashboard's own words for its way there, so they always match it
    const int y = grid_y + ((i + 1) / 2) * 68 + 6;
    lv_obj_set_height(d, std::max<int>(lv_obj_get_height(d), y + 26 + 24 + 18));
    const uint32_t light = this->color_("light", 0xFFB300);
    lv_obj_t *dot = lv_obj_create(d);
    lv_obj_remove_style_all(dot);
    lv_obj_set_size(dot, 10, 10);
    lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_opa(dot, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(dot, lv_color_hex(light), 0);
    lv_obj_set_pos(dot, 26, y + 8);
    std::string s = this->rt_->t(this->model_->found == 1 ? "panel.new_found.one" : "panel.new_found.other");
    const size_t at = s.find("{n}");
    if (at != std::string::npos)
      s.replace(at, 3, std::to_string(this->model_->found));
    lv_obj_t *n = label(d, s, this->fonts_.prefix, text);
    lv_label_set_long_mode(n, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_width(n, 580 - 48 - 22);
    lv_obj_set_pos(n, 24 + 22, y);
    const std::string where = "Room Tiles \xE2\x80\xBA " + this->rt_->t("common.settings") + " \xE2\x80\xBA " +
                              this->rt_->t("appliances.title");  // (" > ": U+203A)
    lv_obj_t *w = label(d, where, this->fonts_.prefix, dim);
    lv_label_set_long_mode(w, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_width(w, 580 - 48 - 22);
    lv_obj_set_pos(w, 24 + 22, y + 26);
  }
}

// Restart: asked first (it's next to the other settings)
void Board::confirm_restart_() {
  lv_obj_t *d = this->dialog_(480, 180, this->rt_->t("panel.restart_panel"));
  lv_obj_t *cancel = button(d, 180, 56, this->color_("button", 0x3A3A3A));
  lv_obj_align(cancel, LV_ALIGN_BOTTOM_LEFT, 18, -18);
  lv_obj_center(label(cancel, this->rt_->t("common.cancel"), this->fonts_.name, this->color_("text", 0xFFFFFF)));
  lv_obj_add_event_cb(
      cancel, [](lv_event_t *e) { static_cast<Board *>(lv_event_get_user_data(e))->close_dialog_(); },
      LV_EVENT_CLICKED, this);
  lv_obj_t *go = button(d, 180, 56, this->color_("accent", 0x4B9EF3));
  lv_obj_align(go, LV_ALIGN_BOTTOM_RIGHT, -18, -18);
  lv_obj_center(label(go, this->rt_->t("screen.restart"), this->fonts_.name, this->color_("onAccent", 0xFFFFFF)));
  lv_obj_add_event_cb(go, [](lv_event_t *) { App.safe_reboot(); }, LV_EVENT_CLICKED, nullptr);
}

// Change Wi-Fi: asked first (the panel goes offline until it's set up again)
void Board::confirm_wifi_change_() {
  lv_obj_t *d = this->dialog_(520, 260, this->rt_->t("panel.wifi_change"));
  lv_obj_t *ask = label(d, this->rt_->t("panel.wifi_change_ask"), this->fonts_.name_s, this->color_("text", 0xFFFFFF));
  lv_label_set_long_mode(ask, LV_LABEL_LONG_MODE_WRAP);
  lv_obj_set_width(ask, 520 - 48);
  lv_obj_set_pos(ask, 24, 66);
  lv_obj_t *cancel = button(d, 200, 56, this->color_("button", 0x3A3A3A));
  lv_obj_align(cancel, LV_ALIGN_BOTTOM_LEFT, 18, -18);
  lv_obj_center(label(cancel, this->rt_->t("common.cancel"), this->fonts_.name, this->color_("text", 0xFFFFFF)));
  lv_obj_add_event_cb(
      cancel, [](lv_event_t *e) { static_cast<Board *>(lv_event_get_user_data(e))->close_dialog_(); },
      LV_EVENT_CLICKED, this);
  lv_obj_t *go = button(d, 200, 56, this->color_("accent", 0x4B9EF3));
  lv_obj_align(go, LV_ALIGN_BOTTOM_RIGHT, -18, -18);
  lv_obj_center(label(go, this->rt_->t("panel.wifi_change"), this->fonts_.name, this->color_("onAccent", 0xFFFFFF)));
  lv_obj_add_event_cb(
      go, [](lv_event_t *e) { static_cast<Board *>(lv_event_get_user_data(e))->rt_->forget_wifi(); },
      LV_EVENT_CLICKED, this);
}

// The panel's language: Home Assistant's, or one with wording (its setting in HA)
void Board::open_languages_() {
  if (this->model_ == nullptr)
    return;
  const PanelModel &m = *this->model_;
  const int n = (int) m.languages.size() + 1;
  const int H = std::min(560, 80 + n * 62);
  const bool scrolls = n * 62 > H - 76;  // (then wider: the scroll bar's strip beside the buttons)
  const int W = 420 + (scrolls ? 36 : 0);
  lv_obj_t *d = this->dialog_(W, H, this->rt_->t("menu.language"));
  static std::vector<std::string> codes;  // (the buttons' choices: this dialog's)
  codes.clear();
  codes.push_back("");
  for (auto &kv : m.languages)
    codes.push_back(kv.first);
  lv_obj_t *list = lv_obj_create(d);
  lv_obj_remove_style_all(list);
  lv_obj_set_size(list, W - 20, H - 76);
  lv_obj_align(list, LV_ALIGN_TOP_LEFT, 10, 66);
  lv_obj_set_scroll_dir(list, LV_DIR_VER);
  for (int i = 0; i < n; i++) {
    const bool on = codes[i] == m.own_language;
    lv_obj_t *b = button(list, 372, 52, on ? this->color_("accent", 0x4B9EF3) : this->color_("button", 0x3A3A3A));
    lv_obj_set_pos(b, 14, i * 62);
    lv_obj_add_flag(b, LV_OBJ_FLAG_SCROLL_CHAIN_VER);
    lv_obj_set_user_data(b, (void *) (uintptr_t) i);
    lv_obj_add_event_cb(
        b,
        [](lv_event_t *e) {
          auto *self = static_cast<Board *>(lv_event_get_user_data(e));
          const size_t k = (size_t) (uintptr_t) lv_obj_get_user_data(lv_event_get_current_target_obj(e));
          if (k < codes.size())
            self->rt_->choose_language(codes[k]);
          lv_async_call([](void *p) { static_cast<Board *>(p)->close_dialog_(); }, self);
        },
        LV_EVENT_CLICKED, this);
    const std::string name = i == 0 ? this->rt_->t("menu.language_ha") : m.languages.at(codes[i]);
    lv_obj_t *l = label(b, name, this->fonts_.name, on ? this->color_("onAccent", 0xFFFFFF) : this->color_("text", 0xFFFFFF));
    lv_obj_align(l, LV_ALIGN_LEFT_MID, 18, 0);
  }
  if (scrolls)
    dragbar_attach(d, list, this->color_("textSecondary", 0x9E9E9E));
}

// MIRRORED: board_strip.cpp open_strip_settings_ (the round panel's "When idle") - a change here must be made there too.
// "When idle": the screen off / a digital / an analog / the theme's clock
// (two by two), the second hand's and the animations' switches, the idle
// brightness, and "Screen off when the following area lights are off". It stays open for more
// than one change: a choice is shown in place (the list drawn again); its X
// or a tap beside it closes it.
void Board::open_idle_list_() {
  if (this->idle_row_ == nullptr || !lv_obj_is_valid(this->idle_row_))
    return;
  lv_obj_t *row = this->idle_row_;
  lv_obj_t *d = lv_obj_get_parent(row);
  lv_obj_update_layout(d);
  lv_obj_t *catcher = lv_obj_create(d);
  lv_obj_remove_style_all(catcher);
  lv_obj_set_size(catcher, lv_obj_get_width(d), lv_obj_get_height(d));
  lv_obj_set_pos(catcher, 0, 0);
  lv_obj_add_flag(catcher, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_event_cb(
      catcher,
      [](lv_event_t *e) {
        if (lv_event_get_target(e) == lv_event_get_current_target(e))
          lv_obj_delete_async(lv_event_get_current_target_obj(e));
      },
      LV_EVENT_CLICKED, nullptr);
  // (Theme clock stays in the list in every theme: a theme without one shows
  // the analog clock - the setting doesn't change with the theme)
  static const char *const KEYS[] = {"panel.idle_off", "panel.idle_digital", "panel.idle_analog", "panel.idle_theme"};
  const int now = this->rt_->idle_mode();
  const int row_h = 52, gap = 6, step = row_h + gap, w = 540, head_h = 48, bright_h = 76;
  const int bw = (w - 12 - gap) / 2;                // (a choice: half the list)
  const int y_modes = 6 + head_h + 10;              // (clear of the X)
  const int y_switches = y_modes + 2 * step;        // the second hand, the animations
  const int y_bright = y_switches + 2 * step;       // the idle brightness
  const int y_lights = y_bright + bright_h + gap;   // Screen off when the following area lights are off
  const int room_h = 64;                            // (its word + the room it follows)
  const int h = y_lights + room_h + 6;
  lv_obj_t *list = lv_obj_create(catcher);
  lv_obj_remove_style_all(list);
  lv_obj_set_size(list, w, h);
  lv_obj_set_style_bg_color(list, lv_color_hex(this->color_("dialog", 0x2A2A2A)), 0);
  lv_obj_set_style_bg_opa(list, LV_OPA_COVER, 0);
  lv_obj_set_style_border_width(list, 1, 0);
  lv_obj_set_style_border_color(list, lv_color_hex(this->color_("tileBorder", 0x4A4A4A)), 0);
  lv_obj_set_style_radius(list, 12, 0);
  lv_obj_add_flag(list, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_remove_flag(list, LV_OBJ_FLAG_SCROLLABLE);
  const int x = std::max(10, std::min((int) lv_obj_get_width(d) - 10 - w, (int) (lv_obj_get_x(row) + lv_obj_get_width(row) - w)));
  int y = lv_obj_get_y(row) + lv_obj_get_height(row) + 4;
  if (y + h > lv_obj_get_height(d) - 10)
    y = std::max(10, (int) lv_obj_get_height(d) - 10 - h);
  lv_obj_set_pos(list, x, y);
  const uint32_t text = this->color_("text", 0xFFFFFF), on_accent = this->color_("onAccent", 0xFFFFFF);
  const uint32_t accent = this->color_("accent", 0x4B9EF3);
  // its name and X (framed like every close on the panel): closes the list
  lv_obj_align(label(list, this->rt_->t("panel.idle"), this->fonts_.name, text), LV_ALIGN_TOP_LEFT, 18, 6 + 12);
  lv_obj_t *close = bar_button(list, this->color_("button", 0x333333), this->color_("tileBorder", 0x4A4A4A), 6);
  lv_obj_align(close, LV_ALIGN_TOP_RIGHT, -8, 8);
  lv_obj_add_event_cb(
      close, [](lv_event_t *e) { lv_obj_delete_async(lv_obj_get_parent(lv_obj_get_parent(lv_event_get_current_target_obj(e)))); },
      LV_EVENT_CLICKED, nullptr);
  lv_obj_center(label(close, "\U000F0156", this->fonts_.glyph, text));  // mdi:close
  // the four choices, two by two: a tap picks one and the list stays (drawn
  // again, the menu's row saying the new one)
  for (int i = 0; i < 4; i++) {
    const bool on = i == now;
    lv_obj_t *b = button(list, bw, row_h, on ? accent : this->color_("button", 0x3A3A3A));
    lv_obj_set_pos(b, 6 + (i % 2) * (bw + gap), y_modes + (i / 2) * step);
    lv_obj_set_user_data(b, (void *) (intptr_t) i);
    lv_obj_add_event_cb(
        b,
        [](lv_event_t *e) {
          auto *self = static_cast<Board *>(lv_event_get_user_data(e));
          lv_obj_t *b = lv_event_get_current_target_obj(e);
          const int k = (int) (intptr_t) lv_obj_get_user_data(b);
          self->rt_->set_idle(k, self->rt_->idle_anim_keep(), self->rt_->idle_seconds(), true);
          if (self->idle_row_ != nullptr && lv_obj_is_valid(self->idle_row_))
            lv_label_set_text(lv_obj_get_child(self->idle_row_, 2), self->rt_->t(KEYS[k]).c_str());  // (its value)
          lv_obj_delete_async(lv_obj_get_parent(lv_obj_get_parent(b)));                            // (the catcher)
          lv_async_call([](void *p) { static_cast<Board *>(p)->open_idle_list_(); }, self);          // (then again)
        },
        LV_EVENT_CLICKED, this);
    lv_obj_t *l = label(b, this->rt_->t(KEYS[i]), this->fonts_.name, on ? on_accent : text);
    lv_label_set_long_mode(l, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_width(l, bw - 28);
    lv_obj_align(l, LV_ALIGN_LEFT_MID, 14, 0);
  }
  // a switch: its word, On / Off at the right (switched in place)
  // (`bh` taller: a second line under the word - the room it follows)
  auto toggle = [&](int ty, const char *key, bool v, lv_event_cb_t cb, int bh = 0) {
    lv_obj_t *b = button(list, w - 12, bh ? bh : row_h, this->color_("button", 0x3A3A3A));
    lv_obj_set_pos(b, 6, ty);
    lv_obj_t *word = label(b, this->rt_->t(key), this->fonts_.prefix, text);
    lv_label_set_long_mode(word, LV_LABEL_LONG_MODE_WRAP);  // (two lines when long; clear of On / Off)
    lv_obj_set_width(word, w - 12 - 18 - 80);
    lv_obj_align(word, LV_ALIGN_LEFT_MID, 18, 0);
    if (bh) {
      lv_obj_t *sub = label(b, this->room_line_(), this->fonts_.prefix, this->color_("textSecondary", 0x9E9E9E));
      lv_label_set_long_mode(sub, LV_LABEL_LONG_MODE_DOTS);
      lv_obj_set_width(sub, w - 12 - 18 - 80);
      lv_obj_align(word, LV_ALIGN_TOP_LEFT, 18, 10);
      lv_obj_align(sub, LV_ALIGN_BOTTOM_LEFT, 18, -10);
    }
    lv_obj_t *state = label(b, this->rt_->t(v ? "common.on" : "common.off"), this->fonts_.name, accent);
    lv_obj_align(state, LV_ALIGN_RIGHT_MID, -16, 0);
    lv_obj_set_user_data(b, state);
    lv_obj_add_event_cb(b, cb, LV_EVENT_CLICKED, this);
  };
  toggle(y_switches, "panel.idle_seconds", this->rt_->idle_seconds(), [](lv_event_t *e) {
    auto *r = static_cast<Board *>(lv_event_get_user_data(e))->rt_;
    r->set_idle(r->idle_mode(), r->idle_anim_keep(), !r->idle_seconds(), true);
    lv_label_set_text(static_cast<lv_obj_t *>(lv_obj_get_user_data(lv_event_get_current_target_obj(e))),
                      r->t(r->idle_seconds() ? "common.on" : "common.off").c_str());
  });
  toggle(y_switches + step, "panel.idle_anim", this->rt_->idle_anim_keep(), [](lv_event_t *e) {
    auto *r = static_cast<Board *>(lv_event_get_user_data(e))->rt_;
    r->set_idle(r->idle_mode(), !r->idle_anim_keep(), r->idle_seconds(), true);
    lv_label_set_text(static_cast<lv_obj_t *>(lv_obj_get_user_data(lv_event_get_current_target_obj(e))),
                      r->t(r->idle_anim_keep() ? "common.on" : "common.off").c_str());
  });
  // MIRRORED: board_strip.cpp open_strip_settings_ (the idle brightness) - a change here must be made there too.
  // the idle brightness (the clock's, or a board an animation keeps): the
  // brightness slider's scale (10-100 % in 5s), its knob never past the
  // screen's brightness; shown live while it moves
  {
    lv_obj_t *name = label(list, this->rt_->t("panel.idle_brightness"), this->fonts_.prefix, text);
    lv_obj_set_pos(name, 18, y_bright + 8);
    lv_obj_t *v = label(list, "", this->fonts_.name, accent);
    lv_obj_align(v, LV_ALIGN_TOP_RIGHT, -22, y_bright + 4);
    lv_obj_t *sl = slider(list, w - 60, 2, 20, this->rt_->idle_brightness() / 5, this->color_("button", 0x3A3A3A), accent);
    lv_obj_set_pos(sl, 30, y_bright + 50);
    lv_obj_set_user_data(sl, v);
    lv_event_cb_t cb = [](lv_event_t *e) {
      auto *self = static_cast<Board *>(lv_event_get_user_data(e));
      lv_obj_t *sl = lv_event_get_current_target_obj(e);
      const int most = std::max(2, self->rt_->brightness() / 5);
      if (lv_slider_get_value(sl) > most)
        lv_slider_set_value(sl, most, LV_ANIM_OFF);  // (no brighter than the screen)
      const int pct = lv_slider_get_value(sl) * 5;
      lv_label_set_text(static_cast<lv_obj_t *>(lv_obj_get_user_data(sl)), (std::to_string(pct) + " %").c_str());
      self->rt_->set_idle_brightness(pct, lv_event_get_code(e) == LV_EVENT_RELEASED);
    };
    lv_obj_add_event_cb(sl, cb, LV_EVENT_VALUE_CHANGED, this);
    lv_obj_add_event_cb(sl, cb, LV_EVENT_RELEASED, this);
    lv_label_set_text(v, (std::to_string(this->rt_->idle_brightness()) + " %").c_str());
  }
  // the room's lights all off (where the panel is): the screen off when idle,
  // not dimmed - its word, and under it the room it follows
  toggle(y_lights, "panel.idle_room_dark", this->rt_->idle_lights_off(), [](lv_event_t *e) {
    auto *r = static_cast<Board *>(lv_event_get_user_data(e))->rt_;
    r->set_idle_lights_off(!r->idle_lights_off());
    lv_label_set_text(static_cast<lv_obj_t *>(lv_obj_get_user_data(lv_event_get_current_target_obj(e))),
                      r->t(r->idle_lights_off() ? "common.on" : "common.off").c_str());
  }, room_h);
}

// MIRRORED: board_strip.cpp open_strip_settings_ (the same line) - a change here must be made there too.
std::string Board::room_line_() const {
  const std::string room = this->model_ != nullptr ? this->model_->room : "";
  if (room.empty())
    return this->rt_->t("panel.idle_room_none");
  std::string s = this->rt_->t(this->model_->room_lights.empty() ? "panel.idle_room_no_lights" : "panel.idle_room_where");
  const size_t at = s.find("{room}");
  if (at != std::string::npos)
    s.replace(at, 6, room);
  return s;
}

// The theme's drop-down list, over its row in the settings menu (its setting
// in HA; the house theme until one is picked). A tap beside it closes it.
void Board::open_theme_list_() {
  if (this->model_ == nullptr || this->theme_row_ == nullptr || !lv_obj_is_valid(this->theme_row_))
    return;
  const PanelModel &m = *this->model_;
  lv_obj_t *row = this->theme_row_;
  lv_obj_t *d = lv_obj_get_parent(row);
  lv_obj_update_layout(d);
  static std::vector<std::string> names;  // (the list's choices)
  names = m.themes;
  const std::string &now = m.own_theme.empty() ? m.theme : m.own_theme;
  lv_obj_t *catcher = lv_obj_create(d);
  lv_obj_remove_style_all(catcher);
  lv_obj_set_size(catcher, lv_obj_get_width(d), lv_obj_get_height(d));
  lv_obj_set_pos(catcher, 0, 0);
  lv_obj_add_flag(catcher, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_event_cb(
      catcher,
      [](lv_event_t *e) {
        if (lv_event_get_target(e) == lv_event_get_current_target(e))
          lv_obj_delete_async(lv_event_get_current_target_obj(e));
      },
      LV_EVENT_CLICKED, nullptr);
  const int n = (int) names.size(), row_h = 56, gap = 6, w = 320;
  // as tall as its rows - or the menu's height, and it scrolls (installed
  // themes: any number)
  const int full = n * row_h + (n - 1) * gap + 12;
  const int h = std::min(full, (int) lv_obj_get_height(d) - 20);
  lv_obj_t *list = lv_obj_create(catcher);
  lv_obj_remove_style_all(list);
  lv_obj_set_size(list, w, h);
  lv_obj_set_style_bg_color(list, lv_color_hex(this->color_("dialog", 0x2A2A2A)), 0);
  lv_obj_set_style_bg_opa(list, LV_OPA_COVER, 0);
  lv_obj_set_style_border_width(list, 1, 0);
  lv_obj_set_style_border_color(list, lv_color_hex(this->color_("tileBorder", 0x4A4A4A)), 0);
  lv_obj_set_style_radius(list, 12, 0);
  lv_obj_add_flag(list, LV_OBJ_FLAG_CLICKABLE);  // (a tap on its edge stays in the list)
  if (full > h) {
    lv_obj_set_scroll_dir(list, LV_DIR_VER);
    lv_obj_set_style_pad_bottom(list, 6, 0);  // (the last row's gap, scrolled to the end)
  } else {
    lv_obj_remove_flag(list, LV_OBJ_FLAG_SCROLLABLE);
  }
  // under the row's right end (where the theme's name is), kept in the menu
  // (the theme row is narrower than the list: never past the menu's left edge)
  const int x = std::max(10, std::min((int) lv_obj_get_width(d) - 10 - w, (int) (lv_obj_get_x(row) + lv_obj_get_width(row) - w)));
  int y = lv_obj_get_y(row) + lv_obj_get_height(row) + 4;
  if (y + h > lv_obj_get_height(d) - 10)
    y = std::max(10, (int) lv_obj_get_height(d) - 10 - h);
  lv_obj_set_pos(list, x, y);
  for (int i = 0; i < n; i++) {
    const bool on = names[i] == now;
    lv_obj_t *b = button(list, w - 12, row_h, on ? this->color_("accent", 0x4B9EF3) : this->color_("button", 0x3A3A3A));
    lv_obj_set_pos(b, 6, 6 + i * (row_h + gap));
    lv_obj_set_user_data(b, (void *) (uintptr_t) i);
    lv_obj_add_event_cb(
        b,
        [](lv_event_t *e) {
          auto *self = static_cast<Board *>(lv_event_get_user_data(e));
          const size_t k = (size_t) (uintptr_t) lv_obj_get_user_data(lv_event_get_current_target_obj(e));
          if (k < names.size())
            self->rt_->choose_theme(names[k]);
          lv_async_call([](void *p) { static_cast<Board *>(p)->close_dialog_(); }, self);
        },
        LV_EVENT_CLICKED, this);
    // the default (HA's list starts with it) says so: "Dark (Default)"
    // MIRRORED: frontend/src/room-tiles-panel.ts theme <select> - a change here must be made there too.
    // MIRRORED: board_strip.cpp open_strip_settings_ (the round panel's theme buttons) - a change here must be made there too.
    std::string name = this->theme_name_(names[i]);
    if (i == 0) {
      std::string d = this->rt_->t("theme.default");
      const size_t at = d.find("{name}");
      if (at != std::string::npos)
        name = d.replace(at, 6, name);
    }
    lv_obj_t *l = label(b, name, this->fonts_.name, on ? this->color_("onAccent", 0xFFFFFF) : this->color_("text", 0xFFFFFF));
    lv_label_set_long_mode(l, LV_LABEL_LONG_MODE_DOTS);  // (an installed theme's long name: cut with "…")
    lv_obj_set_width(l, w - 12 - 36);
    lv_obj_align(l, LV_ALIGN_LEFT_MID, 18, 0);
    if (on && full > h)
      lv_obj_scroll_to_view(b, LV_ANIM_OFF);  // (the theme it has, in view)
  }
}

// ---- the area picker (the area's name) ------------------------------------------------

void Board::on_area_name_(lv_event_t *e) { static_cast<Board *>(lv_event_get_user_data(e))->open_area_picker_(); }

void Board::open_area_picker_() {
  if (this->model_ == nullptr)
    return;
  const PanelModel &m = *this->model_;
  lv_obj_t *d = this->dialog_(760, 500, this->rt_->t("areas.title"));
  lv_obj_t *list = lv_obj_create(d);
  lv_obj_remove_style_all(list);
  lv_obj_set_size(list, 740, 420);
  lv_obj_align(list, LV_ALIGN_TOP_MID, 0, 70);
  style_scroll(list, this->color_("textSecondary", 0x9E9E9E));
  // by floor (in Room Tiles' order), areas without a floor last
  std::vector<std::string> floors;
  for (auto &a : m.areas)
    if (std::find(floors.begin(), floors.end(), a.floor) == floors.end())
      floors.push_back(a.floor);
  std::stable_partition(floors.begin(), floors.end(), [](const std::string &f) { return !f.empty(); });
  const int bw = 216, bh = 56, gap = 10;  // (the drag bar has the right edge)
  int y = 0;
  // the map is always one tap from here: its first button (docs/UI.md)
  if (!m.maps.empty()) {
    lv_obj_t *b = button(list, bw, bh, this->color_("button", 0x3A3A3A));
    lv_obj_set_pos(b, 6, y);
    lv_obj_set_style_border_width(b, 2, 0);
    lv_obj_set_style_border_color(b, lv_color_hex(this->color_("accent", 0x4B9EF3)), 0);
    lv_obj_add_event_cb(
        b,
        [](lv_event_t *e) {
          auto *self = static_cast<Board *>(lv_event_get_user_data(e));
          self->close_dialog_();
          lv_async_call([](void *p) { static_cast<Board *>(p)->rt_->open_map(""); }, self);
        },
        LV_EVENT_CLICKED, this);
    lv_obj_t *g = label(b, "\U000F0821", this->fonts_.glyph, this->color_("accent", 0x4B9EF3));  // mdi:floor-plan
    lv_obj_align(g, LV_ALIGN_LEFT_MID, 18, 0);
    lv_obj_t *l = label(b, this->rt_->t("help.title.view"), this->fonts_.name, this->color_("text", 0xFFFFFF));
    lv_obj_align(l, LV_ALIGN_LEFT_MID, 58, 0);
    y += bh + gap + 6;
  }
  for (const std::string &floor : floors) {
    if (floors.size() > 1) {
      auto it = m.floors.find(floor);
      const std::string head = floor.empty() ? "" : (it != m.floors.end() ? it->second : floor);
      if (!head.empty()) {
        lv_obj_t *h = label(list, head, this->fonts_.prefix, this->color_("textSecondary", 0x9E9E9E));
        lv_obj_set_pos(h, 6, y);
        y += 26;
      }
    }
    int col = 0;
    for (auto &a : m.areas) {
      if (a.floor != floor)
        continue;
      const bool current = a.id == this->area_;
      lv_obj_t *b = button(list, bw, bh, current ? this->color_("accent", 0x4B9EF3) : this->color_("button", 0x3A3A3A));
      lv_obj_set_pos(b, 6 + col * (bw + gap), y);
      lv_obj_set_user_data(b, (void *) &a);
      lv_obj_add_event_cb(
          b,
          [](lv_event_t *e) {
            auto *self = static_cast<Board *>(lv_event_get_user_data(e));
            auto *area = static_cast<const AreaSpec *>(lv_obj_get_user_data(static_cast<lv_obj_t *>(lv_event_get_current_target(e))));
            // drawn at once from what the panel has (its states preloaded);
            // the panel's own setting goes to HA meanwhile
            static std::string chosen;
            chosen = area->id;
            self->close_dialog_();
            lv_async_call([](void *p) { static_cast<Board *>(p)->rt_->choose_area(chosen); }, self);
          },
          LV_EVENT_CLICKED, this);
      lv_obj_t *l = label(b, a.short_name.empty() ? a.name : a.short_name, this->fonts_.name, current ? this->color_("onAccent", 0xFFFFFF) : this->color_("text", 0xFFFFFF));
      lv_label_set_long_mode(l, LV_LABEL_LONG_MODE_DOTS);
      lv_obj_set_width(l, bw - 20);
      lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
      lv_obj_center(l);
      if (++col == 3) {
        col = 0;
        y += bh + gap;
      }
    }
    if (col != 0)
      y += bh + gap;
    y += 6;
  }
  dragbar_attach(d, list, this->color_("textSecondary", 0x9E9E9E));
}

// ---- the tile picker ------------------------------------------------------------------

void Board::open_picker_(int slot) {
  if (this->model_ == nullptr)
    return;
  const TileView *tv = nullptr;
  for (auto &t : this->tiles_)
    if (t.slot == slot)
      tv = &t;
  lv_obj_t *d = this->dialog_(900, 540, this->rt_->t("panel.pick_title"));
  this->pick_slot_ = slot;  // (dialog_ cleared it)
  // first: everything in this area (All), like the dashboard's picker
  this->pick_cat_ = -1;
  this->pick_area_ = this->area_;
  this->pick_entity_ = tv ? tv->entity : "";
  this->pick_map_ = tv != nullptr && tv->kind == "map";

  // the types across the top: All, then one icon each (one at a time)
  this->pick_cat_btns_.clear();
  for (int c = -1; c < N_CATEGORIES; c++) {
    lv_obj_t *b = button(d, 64, 56, this->color_("button", 0x3A3A3A));
    lv_obj_set_pos(b, 18 + (c + 1) * 72, 64);
    lv_obj_set_user_data(b, (void *) (intptr_t) c);
    if (c < 0) {
      lv_obj_center(label(b, this->rt_->t("panel.all"), this->fonts_.name_s, this->color_("text", 0xFFFFFF)));
    } else if (c == CAT_MORE) {
      // three dots (the font's "..." sits on the baseline)
      for (int k = -1; k <= 1; k++) {
        lv_obj_t *dot = lv_obj_create(b);
        lv_obj_remove_style_all(dot);
        lv_obj_set_size(dot, 8, 8);
        lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_bg_opa(dot, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(dot, lv_color_hex(this->color_("text", 0xFFFFFF)), 0);
        lv_obj_remove_flag(dot, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_align(dot, LV_ALIGN_CENTER, k * 14, 0);
      }
    } else if (const lv_image_dsc_t *img = this->rt_->image(CATEGORIES[c].icon)) {
      lv_obj_t *i = lv_image_create(b);
      lv_image_set_src(i, img);
      lv_obj_center(i);
    }
    lv_obj_add_event_cb(
        b,
        [](lv_event_t *e) {
          auto *self = static_cast<Board *>(lv_event_get_user_data(e));
          self->pick_cat_ = (int) (intptr_t) lv_obj_get_user_data(static_cast<lv_obj_t *>(lv_event_get_current_target(e)));
          self->picker_fill_();
        },
        LV_EVENT_CLICKED, this);
    this->pick_cat_btns_.push_back(b);
  }
  // areas (left), what they hold (right)
  const uint32_t bar = this->color_("textSecondary", 0x9E9E9E);
  // both columns: a frame of their own, the list scrolling inside it (so rows
  // never slide over the frame's lines)
  auto framed = [this, d, bar](int x, int w) {
    lv_obj_t *frame = lv_obj_create(d);
    lv_obj_remove_style_all(frame);
    lv_obj_set_size(frame, w, 330);
    lv_obj_set_pos(frame, x, 132);
    lv_obj_set_style_border_width(frame, 1, 0);
    lv_obj_set_style_border_color(frame, lv_color_hex(this->color_("tileBorder", 0x4A4A4A)), 0);
    lv_obj_set_style_radius(frame, 8, 0);
    lv_obj_remove_flag(frame, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_t *list = lv_obj_create(frame);
    lv_obj_remove_style_all(list);
    lv_obj_set_size(list, w - 4, 320);
    lv_obj_align(list, LV_ALIGN_CENTER, 0, 0);
    style_scroll(list, bar);
    return list;  // (its drag bar: picker_fill_, once it has rows)
  };
  this->pick_areas_ = framed(18, 254);
  this->pick_list_ = framed(282, 600);

  // bottom: Remove (a tile there), Cancel, Assign
  if (tv && !tv->kind.empty()) {
    lv_obj_t *rm = button(d, 200, 48, this->color_("button", 0x3A3A3A));
    lv_obj_align(rm, LV_ALIGN_BOTTOM_LEFT, 18, -14);
    lv_obj_center(label(rm, this->rt_->t("common.remove"), this->fonts_.name, this->color_("text", 0xFFFFFF)));
    lv_obj_add_event_cb(
        rm,
        [](lv_event_t *e) {
          auto *self = static_cast<Board *>(lv_event_get_user_data(e));
          char data[128];
          snprintf(data, sizeof(data), "{\"area\":%s,\"layout\":%s,\"slot\":%d}", json_str(self->area_).c_str(),
                   json_str(self->layout_).c_str(), self->pick_slot_);
          self->rt_->actions().call("room_tiles.clear_tile", "", data);
          self->wait_for_({self->pick_slot_});
          self->close_dialog_();
        },
        LV_EVENT_CLICKED, this);
  }
  lv_obj_t *cancel = button(d, 160, 48, this->color_("button", 0x3A3A3A));
  lv_obj_align(cancel, LV_ALIGN_BOTTOM_RIGHT, -196, -14);
  lv_obj_center(label(cancel, this->rt_->t("common.cancel"), this->fonts_.name, this->color_("text", 0xFFFFFF)));
  lv_obj_add_event_cb(
      cancel, [](lv_event_t *e) { static_cast<Board *>(lv_event_get_user_data(e))->close_dialog_(); },
      LV_EVENT_CLICKED, this);
  this->pick_assign_ = button(d, 160, 48, this->color_("accent", 0x4B9EF3));
  lv_obj_align(this->pick_assign_, LV_ALIGN_BOTTOM_RIGHT, -18, -14);
  lv_obj_center(label(this->pick_assign_, this->rt_->t("panel.assign"), this->fonts_.name, this->color_("onAccent", 0xFFFFFF)));
  lv_obj_add_event_cb(
      this->pick_assign_,
      [](lv_event_t *e) {
        auto *self = static_cast<Board *>(lv_event_get_user_data(e));
        if (self->model_ == nullptr)
          return;
        if (self->pick_map_) {  // the Map tile: no entity
          const std::string data = "{\"area\":" + json_str(self->area_) + ",\"layout\":" + json_str(self->layout_) +
                                   ",\"slot\":" + std::to_string(self->pick_slot_) + ",\"kind\":\"map\"}";
          self->rt_->actions().call("room_tiles.set_tile", "", data);
          self->wait_for_({self->pick_slot_});
          self->close_dialog_();
          return;
        }
        if (self->pick_entity_.empty())
          return;
        std::string kind;
        for (auto &c : self->model_->catalog)
          if (c.entity == self->pick_entity_)
            kind = c.kind;
        const std::string data = "{\"area\":" + json_str(self->area_) + ",\"layout\":" + json_str(self->layout_) +
                                 ",\"slot\":" + std::to_string(self->pick_slot_) + ",\"entity\":" +
                                 json_str(self->pick_entity_) + ",\"kind\":" + json_str(kind) + "}";
        self->rt_->actions().call("room_tiles.set_tile", "", data);
        self->wait_for_({self->pick_slot_});
        self->close_dialog_();
      },
      LV_EVENT_CLICKED, this);
  this->picker_fill_();
}

// (re)fill the picker's area column and list for the current filters
void Board::picker_fill_() {
  if (this->pick_list_ == nullptr || this->model_ == nullptr)
    return;
  const PanelModel &m = *this->model_;
  const uint32_t text_c = this->color_("text", 0xFFFFFF), button_c = this->color_("button", 0x3A3A3A);
  const uint32_t accent = this->color_("accent", 0x4B9EF3);
  const uint32_t on_accent = this->color_("onAccent", 0xFFFFFF);
  for (int i = 0; i < (int) this->pick_cat_btns_.size(); i++) {  // (button i = category i - 1; 0 = All)
    const bool on = i - 1 == this->pick_cat_;
    lv_obj_set_style_bg_color(this->pick_cat_btns_[i], lv_color_hex(on ? accent : button_c), 0);
    for (uint32_t k = 0; k < lv_obj_get_child_count(this->pick_cat_btns_[i]); k++) {
      lv_obj_t *c = lv_obj_get_child(this->pick_cat_btns_[i], k);
      if (lv_obj_check_type(c, &lv_label_class))  // ("All": its word)
        lv_obj_set_style_text_color(c, lv_color_hex(on ? on_accent : text_c), 0);
      else if (!lv_obj_check_type(c, &lv_image_class))  // ("...": its dots)
        lv_obj_set_style_bg_color(c, lv_color_hex(on ? on_accent : text_c), 0);
    }
  }

  // the areas: All, each area (with something of this category), No area
  lv_obj_clean(this->pick_areas_);
  auto cat_of = [](const CatalogItem &c) {  // -1 = none of the picker's types
    for (int i = 0; i < N_CATEGORIES; i++)
      for (const char *k : CATEGORIES[i].kinds)
        if (k != nullptr && c.kind == k)
          return i;
    return -1;
  };
  auto in_cat = [this, cat_of](const CatalogItem &c) {
    const int i = cat_of(c);
    return i >= 0 && (this->pick_cat_ < 0 || i == this->pick_cat_);
  };
  auto known_area = [&m](const std::string &id) {
    for (auto &a : m.areas)
      if (a.id == id)
        return true;
    return false;
  };
  struct Choice {
    std::string id, name;
  };
  std::vector<Choice> choices{{"", this->rt_->t("panel.all_areas")}};
  for (auto &a : m.areas)
    for (auto &c : m.catalog)
      if (c.area == a.id && in_cat(c)) {
        choices.push_back({a.id, a.short_name.empty() ? a.name : a.short_name});
        break;
      }
  for (auto &c : m.catalog)
    if (in_cat(c) && !known_area(c.area)) {
      choices.push_back({"-", this->rt_->t("panel.no_area")});
      break;
    }
  // (the area picked isn't there for this category: all areas)
  if (std::none_of(choices.begin(), choices.end(), [this](const Choice &c) { return c.id == this->pick_area_; }))
    this->pick_area_ = "";
  static std::vector<std::string> area_ids;  // (button user data: index into this)
  area_ids.clear();
  int y = 2;
  for (auto &ch : choices) {
    area_ids.push_back(ch.id);
    lv_obj_t *b = button(this->pick_areas_, 196, 48, ch.id == this->pick_area_ ? accent : button_c);  // (room right for the bar)
    lv_obj_set_pos(b, 6, y);
    lv_obj_set_user_data(b, (void *) (intptr_t) (area_ids.size() - 1));
    lv_obj_add_event_cb(
        b,
        [](lv_event_t *e) {
          auto *self = static_cast<Board *>(lv_event_get_user_data(e));
          const int i = (int) (intptr_t) lv_obj_get_user_data(static_cast<lv_obj_t *>(lv_event_get_current_target(e)));
          self->pick_area_ = area_ids[i];
          lv_async_call([](void *p) { static_cast<Board *>(p)->picker_fill_(); }, self);
        },
        LV_EVENT_CLICKED, this);
    lv_obj_t *l = label(b, ch.name, this->fonts_.name_s, text_c);
    lv_label_set_long_mode(l, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_width(l, 174);
    lv_obj_align(l, LV_ALIGN_LEFT_MID, 12, 0);
    y += 54;
  }

  // what's in it, by name
  lv_obj_clean(this->pick_list_);
  std::vector<const CatalogItem *> items;
  for (auto &c : m.catalog) {
    if (!in_cat(c))
      continue;
    if (this->pick_area_ == "-" ? known_area(c.area) : !this->pick_area_.empty() && c.area != this->pick_area_)
      continue;
    items.push_back(&c);
  }
  // by type (the type row's order; inside "...", its kinds' order), then name
  auto rank = [cat_of](const CatalogItem &c) {
    const int i = cat_of(c);
    int k = 0;
    while (k < 4 && CATEGORIES[i].kinds[k] != nullptr && c.kind != CATEGORIES[i].kinds[k])
      k++;
    return i * 4 + k;
  };
  std::sort(items.begin(), items.end(), [rank](const CatalogItem *a, const CatalogItem *b) {
    const int ra = rank(*a), rb = rank(*b);
    return ra != rb ? ra < rb : a->short_name < b->short_name;
  });
  y = 2;
  // the Map tile (in "..." and All, whatever the area): first of "..."
  auto map_row = [&]() {
    lv_obj_t *row = button(this->pick_list_, 540, 48, this->pick_map_ ? accent : this->color_("dialog", 0x2A2A2A));
    lv_obj_set_pos(row, 6, y);
    lv_obj_add_event_cb(
        row,
        [](lv_event_t *e) {
          auto *self = static_cast<Board *>(lv_event_get_user_data(e));
          self->pick_map_ = true;
          self->pick_entity_.clear();
          lv_async_call([](void *p) { static_cast<Board *>(p)->picker_fill_(); }, self);
        },
        LV_EVENT_CLICKED, this);
    // the bar's Map button picture (the theme's own, else mdi:floor-plan)
    if (const lv_image_dsc_t *img = this->rt_->image(IMG_BAR_MAP)) {
      lv_obj_t *icon = lv_image_create(row);
      lv_image_set_src(icon, img);
      lv_obj_align(icon, LV_ALIGN_LEFT_MID, 6, 0);
    } else {
      lv_obj_t *g = label(row, "\U000F0821", this->fonts_.glyph, text_c);
      lv_obj_align(g, LV_ALIGN_LEFT_MID, 10, 0);
    }
    lv_obj_t *l = label(row, this->rt_->t("tile_editor.map_tile"), this->fonts_.name, text_c);
    lv_obj_align(l, LV_ALIGN_LEFT_MID, 56, 0);
    y += 52;
  };
  const bool show_map = this->pick_cat_ < 0 || this->pick_cat_ == CAT_MORE;
  bool map_done = !show_map;
  int shown = 0;
  for (const CatalogItem *c : items) {
    if (!map_done && cat_of(*c) == CAT_MORE) {
      map_row();
      map_done = true;
    }
    shown++;
    const bool sel = !this->pick_map_ && c->entity == this->pick_entity_;
    lv_obj_t *row = button(this->pick_list_, 540, 48, sel ? accent : this->color_("dialog", 0x2A2A2A));
    lv_obj_set_pos(row, 6, y);
    lv_obj_set_user_data(row, (void *) c);
    lv_obj_add_event_cb(
        row,
        [](lv_event_t *e) {
          auto *self = static_cast<Board *>(lv_event_get_user_data(e));
          auto *item = static_cast<const CatalogItem *>(lv_obj_get_user_data(static_cast<lv_obj_t *>(lv_event_get_current_target(e))));
          self->pick_entity_ = item->entity;
          self->pick_map_ = false;
          lv_async_call([](void *p) { static_cast<Board *>(p)->picker_fill_(); }, self);
        },
        LV_EVENT_CLICKED, this);
    // its type's icon (Room Tiles' hint for it first: an entry cover's garage
    // door, a vacuum's maker, a laundry appliance), then its name
    const int cat = cat_of(*c);
    const std::string hint = this->model_ != nullptr ? this->model_->icon(c->entity) : "";
    const AssetId row_icon = hint == "icon_garage"    ? IMG_ICON_GARAGE_M
                             : hint == "icon_matic"   ? IMG_ICON_MATIC_M
                             : hint == "icon_laundry" ? IMG_ICON_LAUNDRY_M
                             : kind_icon(c->kind) < IMG_COUNT ? kind_icon(c->kind)
                             : cat >= 0               ? CATEGORIES[cat].icon
                                                      : IMG_COUNT;
    if (const lv_image_dsc_t *img = row_icon < IMG_COUNT ? this->rt_->image(row_icon) : nullptr) {
      lv_obj_t *icon = lv_image_create(row);
      lv_image_set_src(icon, img);
      lv_obj_align(icon, LV_ALIGN_LEFT_MID, 6, 0);
    }
    lv_obj_t *l = label(row, c->short_name.empty() ? c->entity : c->short_name, this->fonts_.name, text_c);
    lv_obj_align(l, LV_ALIGN_LEFT_MID, 56, 0);
    lv_obj_t *id = label(row, c->entity, this->fonts_.prefix_s, sel ? text_c : this->color_("textSecondary", 0x9E9E9E));
    lv_obj_align(id, LV_ALIGN_RIGHT_MID, -12, 0);
    y += 52;
  }
  if (!map_done)  // (nothing else of "..." here: the Map tile last)
    map_row();
  ESP_LOGD(TAG, "Picker: %d items%s", shown, show_map ? " + Map" : "");
  // drag bars (made once per list; they follow the content)
  for (lv_obj_t *l : {this->pick_areas_, this->pick_list_}) {
    if (lv_obj_get_user_data(l) == nullptr) {
      dragbar_attach(lv_obj_get_parent(l), l, this->color_("textSecondary", 0x9E9E9E));
      lv_obj_set_user_data(l, (void *) 1);
    } else {
      lv_obj_update_layout(l);
      lv_obj_scroll_to_y(l, 0, LV_ANIM_OFF);
      lv_obj_send_event(l, LV_EVENT_SCROLL, nullptr);
    }
  }
  // Assign only with a pick
  lv_obj_set_style_bg_opa(this->pick_assign_, this->pick_entity_.empty() && !this->pick_map_ ? LV_OPA_40 : LV_OPA_COVER, 0);
}

}  // namespace esphome::room_tiles
