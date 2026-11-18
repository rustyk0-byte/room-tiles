#include "board.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <ctime>

#include "esphome/core/hal.h"
#include "picker.h"
#include "esphome/core/log.h"
#include "room_tiles.h"

namespace esphome::room_tiles {

static const char *const TAG = "room_tiles.board";

static const int SCREEN_W = 1024;
static const int BOARD_Y = 64;  // the top bar above
static const int GAP = 8;
// MIRRORED: frontend/src/rules.ts settleMs - a change here must be made there too.
// how long a control shows the user's value before HA's wins (rules.ts settleMs)
static uint32_t hold_ms(const std::string &kind, bool roller, int row) {
  if (kind == "fan" || kind == "climate")
    return 5000;
  if (kind == "water")
    return 20000;
  if (kind == "lock" || kind == "switch")  // (a TV: seconds before HA hears it's on)
    return 10000;
  if (kind == "cover")
    return roller && row != 0 && row != 10 ? 30000 : 8000;
  return 3000;
}
static const uint32_t FLASH_MS = 1500;  // a scene's / script's tap lights its tile this long

static std::string domain_of(const std::string &entity) { return entity.substr(0, entity.find('.')); }

static AssetId icon_for(const std::string &kind, bool big, const std::string &hint) {
  AssetId id = IMG_COUNT;
  // Room Tiles' hint first (an entry cover's garage door, the vacuum's maker)
  if (hint == "icon_garage")
    return big ? IMG_ICON_GARAGE : IMG_ICON_GARAGE_S;
  if (hint == "icon_matic")
    return big ? IMG_ICON_MATIC : IMG_ICON_MATIC_S;
  if (kind == "onoff_light" || kind == "dimmable_light" || kind == "color_light")
    id = big ? IMG_ICON_LIGHT : IMG_ICON_LIGHT_S;
  else if (kind == "switch")
    id = big ? IMG_ICON_SWITCH : IMG_ICON_SWITCH_S;
  else if (kind == "fan")
    id = big ? IMG_ICON_FAN : IMG_ICON_FAN_S;
  else if (kind == "cover")
    id = big ? IMG_ICON_BLIND : IMG_ICON_BLIND_S;
  else if (kind == "lock")
    id = big ? IMG_ICON_KEY : IMG_ICON_KEY_S;
  else if (kind == "climate")
    id = big ? IMG_ICON_AC : IMG_ICON_AC_S;
  else if (kind == "vacuum")
    id = big ? IMG_ICON_ROBOT_VACUUM : IMG_ICON_ROBOT_VACUUM_S;
  else if (kind == "water")
    id = big ? IMG_ICON_POOL : IMG_ICON_POOL_S;
  else if (kind == "scene")
    id = big ? IMG_ICON_SCENE : IMG_ICON_SCENE_S;
  else if (kind == "script")
    id = big ? IMG_ICON_SCRIPT : IMG_ICON_SCRIPT_S;
  return id;  // (appliance / map tiles: no corner icon)
}

// MIRRORED: frontend/src/rules.ts switchTrack - a change here must be made there too.
// The switch per kind (rules.ts switchTrack): its off / on track, big + small.
struct Track {
  AssetId off, on, off_s, on_s;
};
static bool track_for(const std::string &kind, Track &t) {
  if (kind == "onoff_light" || kind == "dimmable_light" || kind == "color_light")
    t = {IMG_TRACK_SWITCH_OFF, IMG_TRACK_SWITCH_ON, IMG_TRACK_SWITCH_OFF_S, IMG_TRACK_SWITCH_ON_S};
  else if (kind == "switch")
    t = {IMG_TRACK_SWITCH_OFF, IMG_TRACK_SWITCH_ON_RASPBERRY, IMG_TRACK_SWITCH_OFF_S, IMG_TRACK_SWITCH_ON_RASPBERRY_S};
  else if (kind == "fan")
    t = {IMG_TRACK_SWITCH_OFF, IMG_TRACK_SWITCH_ON_CYAN, IMG_TRACK_SWITCH_OFF_S, IMG_TRACK_SWITCH_ON_CYAN_S};
  else if (kind == "cover")
    t = {IMG_TRACK_SWITCH_CLOSED, IMG_TRACK_SWITCH_OPEN_GREEN, IMG_TRACK_SWITCH_CLOSED_S, IMG_TRACK_SWITCH_OPEN_GREEN_S};
  else if (kind == "lock")
    t = {IMG_TRACK_SWITCH_UNLOCKED, IMG_TRACK_SWITCH_LOCKED_PURPLE, IMG_TRACK_SWITCH_UNLOCKED_S,
         IMG_TRACK_SWITCH_LOCKED_PURPLE_S};
  else if (kind == "climate" || kind == "water")
    // (a thermostat's ON track follows its mode - paint_ picks it)
    t = {IMG_TRACK_SWITCH_OFF, IMG_TRACK_SWITCH_ON_RED, IMG_TRACK_SWITCH_OFF_S, IMG_TRACK_SWITCH_ON_RED_S};
  else
    return false;
  return true;
}
static bool has_switch(const std::string &kind) {
  Track t;
  return track_for(kind, t);
}
// What "on" (the switch to the right) means per kind
static bool state_on(const std::string &kind, const std::string &state) {
  if (kind == "cover")
    return !state.empty() && state != "closed" && state != "unavailable" && state != "unknown";
  if (kind == "lock")
    return state == "locked" || state == "locking";
  return state == "on";
}
// ...and the service that switches it
static std::string switch_service(const std::string &kind, const std::string &domain, bool on) {
  if (kind == "cover")
    return on ? "cover.open_cover" : "cover.close_cover";
  if (kind == "lock")
    return on ? "lock.lock" : "lock.unlock";
  if (kind == "climate")
    return on ? "climate.turn_on" : "climate.turn_off";
  return domain + (on ? ".turn_on" : ".turn_off");
}
static bool is_run(const std::string &kind) { return kind == "scene" || kind == "script"; }

// MIRRORED: frontend/src/theme.ts themeName - a change here must be made there too.
std::string Board::theme_name_(const std::string &id) const {
  if (this->model_ != nullptr) {
    auto it = this->model_->theme_names.find(id);
    if (it != this->model_->theme_names.end() && !it->second.empty())
      return it->second;
  }
  return this->rt_->t(("theme." + id).c_str());
}

uint32_t Board::color_(const char *token, uint32_t fallback) const { return this->rt_->color(token, fallback); }

// MIRRORED: frontend/src/rules.ts rollerSpec / rollerRow / rollerCall - a change here must be made there too.
// ---- rollers (rules.ts rollerSpec / rollerRow / rollerCall) --------------------------

static const int FAN_SPEEDS = 6;
static const int BRI_OFF_ROW = 20;
static const int COV_OPEN_ROW = 0, COV_CLOSED_ROW = 10;
static const int LOCK_LOCKED_ROW = 1;
static const int COVER_SET_POSITION = 4;
static const int CLIMATE_MAX_F = 80, CLIMATE_MIN_F = 65;
static const int WATER_MAX_F = 104, WATER_MIN_F = 80;

struct RollerGeo {
  int x, w;
  bool mid_font;  // the selected row in the smaller font (longer words)
  const char *color;
  uint32_t fallback;
};
static bool roller_geo(const std::string &kind, RollerGeo &g) {
  if (kind == "dimmable_light")
    g = {44, 74, false, "light", 0xFFB300};
  else if (kind == "fan")
    g = {16, 72, false, "fan", 0x4BC9F3};
  else if (kind == "cover")
    g = {30, 84, true, "cover", 0x62A363};
  else if (kind == "lock")
    g = {34, 96, true, "lock", 0x9270AB};
  else if (kind == "climate" || kind == "water")
    g = {40, 70, false, "heatStrong", 0xFF2F26};  // (a thermostat's colour follows its mode)
  else
    return false;
  return true;
}

static int as_int(const std::string &s, int fallback) {
  if (s.empty())
    return fallback;
  char *end = nullptr;
  const double v = strtod(s.c_str(), &end);
  return end == s.c_str() ? fallback : (int) v;
}
static int clampi(int v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : v; }
// field i of a "a|b|c" tile attribute ("" past the end)
std::string field_(const std::string &s, int i) {
  size_t start = 0;
  for (int k = 0; k < i; k++) {
    start = s.find('|', start);
    if (start == std::string::npos)
      return "";
    start++;
  }
  const size_t end = s.find('|', start);
  return s.substr(start, end == std::string::npos ? std::string::npos : end - start);
}

void Board::clear() {
  if (this->scrim_ != nullptr)
    lv_obj_add_flag(this->scrim_, LV_OBJ_FLAG_HIDDEN);  // (gone now; deleted next)
  this->close_dialog_();
  if (this->root_ != nullptr)
    lv_obj_clean(this->root_);
  this->tiles_.clear();
  this->busy_icons_.clear();
  // pointers into what was just deleted: the top bar's area lights button
  // (repainted on any of its lights' changes), the edit hint, the settings'
  // theme row
  this->hint_ = nullptr;
  this->clock_ = nullptr;
  this->clock_shown_ = -1;
  this->lights_glyph_ = nullptr;
  this->lights_art_ = nullptr;
  this->lights_.clear();
  this->theme_row_ = nullptr;
  this->idle_row_ = nullptr;
  this->strip_cont_ = nullptr;
  this->strip_dots_.clear();
  this->strip_shown_ = -1;
}

void Board::build(const PanelModel &model) {
  if (this->root_ == nullptr)
    return;
  const uint32_t started = millis();
  this->clear();  // (a menu / picker drawn from the old payload too)
  this->model_ = &model;
  this->layout_ = model.layout;
  lv_obj_set_style_bg_color(this->root_, lv_color_hex(this->color_("page", 0x000000)), 0);
  lv_obj_set_style_bg_opa(this->root_, LV_OPA_COVER, 0);
  const AreaSpec *area = model.current();
  this->area_ = area ? area->id : "";
  if (this->strip_) {
    this->build_strip_(model, area);  // (the round panel: board_strip.cpp)
    ESP_LOGI(TAG, "Board (strip): %s, %u tiles, built in %u ms", area ? area->name.c_str() : "-",
             (unsigned) this->tiles_.size(), (unsigned) (millis() - started));
    return;
  }
  this->build_bar_(model, area);
  if (area == nullptr)
    return;
  const bool big = model.layout != "6x3";
  const int cols = big ? 5 : 6, rows = big ? 2 : 3;
  const int w = big ? 198 : 164, h = big ? 254 : 173;
  const int x0 = (SCREEN_W - (cols * w + (cols - 1) * GAP)) / 2;
  const auto &specs = area->tiles(big);
  this->tiles_.reserve(specs.size());  // (tiles are event user data: no reallocation after this)
  for (size_t i = 0; i < specs.size() && (int) i < cols * rows; i++) {
    this->tiles_.emplace_back();
    TileView &tv = this->tiles_.back();
    tv.board = this;
    tv.kind = specs[i].kind;
    tv.entity = specs[i].entity;
    tv.big = big;
    tv.slot = (int) i;
    tv.icon_hint = model.icon(tv.entity);
    const int col = (int) i % cols, row = (int) i / cols;
    this->build_tile_(tv, x0 + col * (w + GAP), BOARD_Y + row * (h + GAP), w, h);
    // the tile's own name (a Map tile has no entity), else the entity's
    tv.name_text = specs[i].name.empty() ? model.short_name(tv.entity) : specs[i].name;
    if (tv.name != nullptr)
      lv_label_set_text(tv.name, tv.name_text.c_str());
    this->paint_(tv);
    if (this->editing_)
      this->build_edit_(tv);
  }
  ESP_LOGI(TAG, "Board: %s, %s, %u tiles, built in %u ms", area->name.c_str(), model.layout.c_str(),
           (unsigned) this->tiles_.size(), (unsigned) (millis() - started));
}

lv_obj_t *dropdown_title(lv_obj_t *parent, const std::string &text, const Fonts &fonts, uint32_t color, int max_w) {
  const int gap = 2;  // (the dashboard's .area-name gap)
  lv_obj_t *row = lv_obj_create(parent);
  lv_obj_remove_style_all(row);
  lv_obj_set_size(row, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
  lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
  lv_obj_set_flex_align(row, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
  lv_obj_set_style_pad_column(row, gap, 0);
  lv_obj_remove_flag(row, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_add_flag(row, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_t *name = lv_label_create(row);
  lv_obj_set_style_text_font(name, fonts.bar, 0);
  lv_obj_set_style_text_color(name, lv_color_hex(color), 0);
  lv_obj_t *tri = nullptr;
  int tri_w = 0;
  if (fonts.menu != nullptr) {
    tri = lv_label_create(row);
    lv_label_set_text(tri, "\U000F035D");  // mdi:menu-down
    lv_obj_set_style_text_font(tri, fonts.menu, 0);
    lv_obj_set_style_text_color(tri, lv_color_hex(color), 0);
    tri_w = lv_font_get_glyph_width(fonts.menu, 0xF035D, 0) + gap;
  }
  // the name as wide as it is, cut short past the room left for it
  lv_point_t size;
  lv_text_get_size(&size, text.c_str(), fonts.bar, 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);
  const int text_w = size.x;
  lv_label_set_text(name, text.c_str());
  if (text_w > max_w - tri_w) {
    lv_label_set_long_mode(name, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_width(name, std::max(0, max_w - tri_w));
  }
  return row;
}

void bar_art(lv_obj_t *glyph, const lv_image_dsc_t *art) {
  if (glyph == nullptr || art == nullptr)
    return;
  lv_obj_add_flag(glyph, LV_OBJ_FLAG_HIDDEN);
  lv_obj_t *img = lv_image_create(lv_obj_get_parent(glyph));
  lv_image_set_src(img, art);
  lv_obj_center(img);
  lv_obj_remove_flag(img, LV_OBJ_FLAG_CLICKABLE);
}

lv_obj_t *bar_button(lv_obj_t *parent, uint32_t bg, uint32_t border, int ext_click) {
  lv_obj_t *b = lv_obj_create(parent);
  lv_obj_remove_style_all(b);
  lv_obj_set_size(b, BAR_BTN_W, BAR_BTN_H);
  lv_obj_set_style_bg_color(b, lv_color_hex(bg), 0);
  lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
  lv_obj_set_style_border_width(b, 1, 0);
  lv_obj_set_style_border_color(b, lv_color_hex(border), 0);
  lv_obj_set_style_radius(b, 8, 0);
  lv_obj_remove_flag(b, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_add_flag(b, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_set_ext_click_area(b, ext_click);
  return b;
}

// The dashboard's top bar: the area's name (its short name) with the
// drop-down triangle - it opens the area picker - then More tiles (5x2 <->
// 6x3, lit on 6x3) and the map; on the right the area lights (when it has
// some), Help, settings. Editing: the name, a hint, then Done, Help, settings.
// Framed buttons 8 px apart, level with the name.
// MIRRORED: frontend/src/room-tiles-panel.ts _settingsButton / .gear-dot (the
// panel's dot: devices found to set up) - a change here must be made there too.
lv_obj_t *gear_dot(lv_obj_t *gear, uint32_t colour, lv_obj_t **slot) {
  lv_obj_t *d = lv_obj_create(gear);
  lv_obj_remove_style_all(d);
  lv_obj_set_size(d, 10, 10);
  lv_obj_set_style_radius(d, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_bg_opa(d, LV_OPA_COVER, 0);
  lv_obj_set_style_bg_color(d, lv_color_hex(colour), 0);
  lv_obj_remove_flag(d, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_align(d, LV_ALIGN_TOP_RIGHT, -4, 4);
  if (slot != nullptr) {
    *slot = d;
    lv_obj_add_event_cb(
        d, [](lv_event_t *e) { *static_cast<lv_obj_t **>(lv_event_get_user_data(e)) = nullptr; }, LV_EVENT_DELETE,
        slot);
  }
  return d;
}

bool Board::found_dot() const {
  return this->model_ != nullptr && this->model_->found > 0 && this->model_->found != this->found_seen_;
}

int brand_icon(lv_obj_t *parent, const Fonts &fonts, int mid_y, int fallback, const lv_image_dsc_t *themed) {
  const lv_image_dsc_t *src = themed != nullptr ? themed : fonts.brand;
  if (src == nullptr)
    return fallback;
  const int mid_x = 14 + BRAND_PX / 2;  // (a theme's, bigger, around the same middle)
  const int w = src->header.w, h = src->header.h;
  lv_obj_t *img = lv_image_create(parent);
  lv_image_set_src(img, src);
  lv_obj_remove_flag(img, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_set_pos(img, mid_x - w / 2, mid_y - h / 2);
  return std::max(14 + BRAND_PX, mid_x + (w + 1) / 2) + 12;
}

void Board::build_bar_(const PanelModel &model, const AreaSpec *area) {
  const uint32_t btn_bg = this->color_("button", 0x333333), btn_border = this->color_("tileBorder", 0x4A4A4A);
  const uint32_t text = this->color_("text", 0xFFFFFF);
  const int btn_y = 10;
  const int gear_x = 1024 - 12 - BAR_BTN_W;
  const int help_x = gear_x - 8 - BAR_BTN_W;
  const bool lights = !this->editing_ && area != nullptr && !area->lights.empty();

  // Done (editing): the dashboard's - check mark and "Done", light on page colour
  lv_obj_t *done = nullptr;
  if (this->editing_) {
    done = lv_obj_create(this->root_);
    lv_obj_remove_style_all(done);
    lv_obj_set_size(done, LV_SIZE_CONTENT, BAR_BTN_H);
    lv_obj_set_flex_flow(done, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(done, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_hor(done, 14, 0);
    lv_obj_set_style_pad_column(done, 6, 0);
    lv_obj_set_style_radius(done, 8, 0);
    lv_obj_set_style_bg_opa(done, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(done, lv_color_hex(this->color_("light", 0xFFB300)), 0);
    lv_obj_remove_flag(done, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(done, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_ext_click_area(done, 4);
    lv_obj_add_event_cb(done, &Board::on_done_, LV_EVENT_CLICKED, this);
    const uint32_t ink = this->color_("onBright", 0x000000);
    if (this->fonts_.menu != nullptr) {
      lv_obj_t *c = lv_label_create(done);
      lv_label_set_text(c, "\U000F012C");  // mdi:check
      lv_obj_set_style_text_font(c, this->fonts_.menu, 0);
      lv_obj_set_style_text_color(c, lv_color_hex(ink), 0);
    }
    lv_obj_t *l = lv_label_create(done);
    lv_label_set_text(l, this->rt_->t("common.done").c_str());
    lv_obj_set_style_text_font(l, this->fonts_.bar, 0);
    lv_obj_set_style_text_color(l, lv_color_hex(ink), 0);
    lv_obj_update_layout(done);
    lv_obj_set_pos(done, help_x - 8 - lv_obj_get_width(done), btn_y);
  }
  // the leftmost button on the right
  const int right_x = done != nullptr ? lv_obj_get_x(done) : lights ? help_x - 8 - BAR_BTN_W : help_x;
  const int left_btns = this->editing_ ? 0 : 12 + BAR_BTN_W + (model.maps.empty() ? 0 : 8 + BAR_BTN_W);
  // the Room Tiles icon, far left; the name after it
  const int lead = brand_icon(this->root_, this->fonts_, btn_y + BAR_BTN_H / 2, 20, this->rt_->image(IMG_BRAND_BAR));
  // (room left for the edit hint while editing)
  const int name_max = (this->editing_ ? 420 : right_x - 16) - lead - left_btns;
  lv_obj_t *name = dropdown_title(this->root_, area ? (area->short_name.empty() ? area->name : area->short_name) : "",
                                  this->fonts_, text, name_max);
  lv_obj_set_style_pad_ver(name, 6, 0);  // (a taller tap target, the text where it was)
  lv_obj_set_pos(name, lead, 10);
  lv_obj_set_ext_click_area(name, 8);  // (up to the next button's tap area)
  lv_obj_add_event_cb(name, &Board::on_area_name_, LV_EVENT_CLICKED, this);
  lv_obj_update_layout(name);
  int x = lead + lv_obj_get_width(name) + 12;

  // a note in the room between the left and the right: centered, one line
  auto note = [&](const std::string &s) {
    const int nx = x + 8, nw = right_x - 16 - nx;
    lv_obj_t *n = lv_label_create(this->root_);
    lv_label_set_text(n, s.c_str());
    lv_label_set_long_mode(n, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_width(n, std::max(0, nw));
    lv_obj_set_style_text_align(n, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_font(n, this->fonts_.prefix, 0);
    lv_obj_set_style_text_color(n, lv_color_hex(this->color_("light", 0xFFB300)), 0);
    lv_obj_set_pos(n, nx, 22);
    return n;
  };

  if (this->editing_) {
    this->hint_ = note("");  // (what to do: board_edit.cpp)
  } else {
    // More tiles: 5x2 <-> 6x3, lit on 6x3 (the dashboard's colours)
    // MIRRORED: frontend/src/room-tiles-panel.ts (the grid button: bar_grid, lit) - a change here must be made there too.
    const lv_image_dsc_t *own = this->rt_->image(IMG_BAR_GRID);  // (the theme's own picture)
    const lv_image_dsc_t *grid = own != nullptr ? own : this->rt_->image(IMG_BAR_GRID_PLAIN);
    if (grid == nullptr)
      grid = this->rt_->image(IMG_ICON_GRID_6X3_S);  // (a pack from before the top bar's box)
    lv_obj_t *btn = bar_button(this->root_, btn_bg, btn_border, 4);
    lv_obj_set_pos(btn, x, btn_y);
    lv_obj_add_event_cb(btn, &Board::on_layout_, LV_EVENT_CLICKED, this);
    if (grid != nullptr) {
      lv_obj_t *img = lv_image_create(btn);
      lv_image_set_src(img, grid);
      lv_obj_center(img);
      if (own == nullptr) {
        // (white art: lit in the light colour on 6x3, the text colour otherwise)
        lv_obj_set_style_image_recolor(img, lv_color_hex(model.layout == "6x3" ? this->color_("light", 0xFFB300) : text), 0);
        lv_obj_set_style_image_recolor_opa(img, LV_OPA_COVER, 0);
      } else if (model.layout == "6x3") {
        // (the theme's colours: its border lit instead)
        lv_obj_set_style_border_color(btn, lv_color_hex(this->color_("light", 0xFFB300)), 0);
      }
    }
    x += BAR_BTN_W + 8;

    // the map (when there is one)
    if (!model.maps.empty()) {
      lv_obj_t *mb = bar_button(this->root_, btn_bg, btn_border, 4);
      lv_obj_set_pos(mb, x, btn_y);
      lv_obj_add_event_cb(mb, [](lv_event_t *e) {
        static_cast<Board *>(lv_event_get_user_data(e))->rt_->open_map("");
      }, LV_EVENT_CLICKED, this);
      // MIRRORED: frontend/src/theme.ts BUTTON_ART (bar_map) - a change here must be made there too.
      if (const lv_image_dsc_t *art = this->rt_->image(IMG_BAR_MAP)) {  // (the theme's own: a gingerbread house)
        lv_obj_t *img = lv_image_create(mb);
        lv_image_set_src(img, art);
        lv_obj_center(img);
      } else {
        lv_obj_t *g = lv_label_create(mb);
        lv_label_set_text(g, "\U000F0821");  // mdi:floor-plan
        lv_obj_set_style_text_font(g, this->fonts_.glyph, 0);
        lv_obj_set_style_text_color(g, lv_color_hex(text), 0);
        lv_obj_center(g);
      }
      x += BAR_BTN_W + 8;
    }

    // the time, in the middle of the bar (the old panels'): centered on the
    // screen when the room between the buttons allows, else in that room;
    // not shown when a long name leaves too little
    this->clock_ = lv_label_create(this->root_);
    lv_obj_set_style_text_font(this->clock_, this->fonts_.name, 0);
    lv_obj_set_style_text_color(this->clock_, lv_color_hex(text), 0);
    lv_obj_remove_flag(this->clock_, LV_OBJ_FLAG_CLICKABLE);
    this->clock_lo_ = x + 8;
    this->clock_hi_ = right_x - 16;
    this->paint_clock();
  }

  auto glyph_btn = [&](int bx, const char *glyph, lv_event_cb_t cb) {
    lv_obj_t *b = bar_button(this->root_, btn_bg, btn_border, 4);
    lv_obj_set_pos(b, bx, btn_y);
    lv_obj_add_event_cb(b, cb, LV_EVENT_CLICKED, this);
    lv_obj_t *g = lv_label_create(b);
    lv_label_set_text(g, glyph);
    lv_obj_set_style_text_font(g, this->fonts_.glyph, 0);
    lv_obj_set_style_text_color(g, lv_color_hex(text), 0);
    lv_obj_center(g);
    return g;
  };
  // the area's lights, all on / off (lit while any is on)
  if (lights) {
    this->lights_ = area->lights;
    for (const std::string &l : this->lights_)
      this->rt_->states().watch(l);
    this->lights_glyph_ = glyph_btn(right_x, "\U000F1254", [](lv_event_t *e) {
      auto *self = static_cast<Board *>(lv_event_get_user_data(e));
      // (the integration decides on / off for the whole set: any on -> all off)
      self->rt_->actions().call("room_tiles.area_lights", "", "{\"area\":\"" + self->area_ + "\",\"action\":\"toggle\"}");
    });
    // MIRRORED: frontend/src/theme.ts BUTTON_ART - a change here must be made there too.
    // the theme's own picture for the button (Christmas: a string of bulbs)
    if (const lv_image_dsc_t *art = this->rt_->image(IMG_BAR_AREA_LIGHTS)) {
      lv_obj_add_flag(this->lights_glyph_, LV_OBJ_FLAG_HIDDEN);
      this->lights_art_ = lv_image_create(lv_obj_get_parent(this->lights_glyph_));
      lv_image_set_src(this->lights_art_, art);
      lv_obj_center(this->lights_art_);
      lv_obj_remove_flag(this->lights_art_, LV_OBJ_FLAG_CLICKABLE);
    }
    this->paint_lights_();
  }
  // Help: the dashboard's page for the tiles (or for editing them)
  lv_obj_t *help = glyph_btn(help_x, "\U000F0625", [](lv_event_t *e) {  // mdi:help-circle-outline
    auto *self = static_cast<Board *>(lv_event_get_user_data(e));
    lv_async_call(
        [](void *p) {
          auto *b = static_cast<Board *>(p);
          b->open_help(b->editing_ ? "tile-edit" : "tiles");
        },
        self);
  });
  bar_art(help, this->rt_->image(IMG_BAR_HELP));  // (the theme's own picture, if it has one)

  // settings, far right
  if (const lv_image_dsc_t *gear = this->rt_->bar_gear()) {
    lv_obj_t *g = bar_button(this->root_, btn_bg, btn_border, 4);
    lv_obj_set_pos(g, gear_x, btn_y);
    lv_obj_add_event_cb(g, &Board::on_settings_, LV_EVENT_CLICKED, this);
    lv_obj_t *img = lv_image_create(g);
    lv_image_set_src(img, gear);
    if (this->found_dot())  // (a device found to set up: its line in the menu)
      gear_dot(g, this->color_("light", 0xFFB300), &this->gear_dot_);
    lv_obj_center(img);
  }
}

void Board::build_tile_(TileView &tv, int x, int y, int w, int h, lv_obj_t *parent) {
  const float k = tv.big ? 1.0f : 0.68f;
  auto px = [k](int v) { return (int) (v * k + 0.5f); };
  lv_obj_t *box = lv_obj_create(parent != nullptr ? parent : this->root_);
  tv.box = box;
  lv_obj_remove_style_all(box);
  lv_obj_set_pos(box, x, y);
  lv_obj_set_size(box, w, h);
  lv_obj_remove_flag(box, LV_OBJ_FLAG_SCROLLABLE);
  if (tv.kind.empty()) {
    // a Blank: an empty card with a faint outline (the old panels)
    lv_obj_set_style_border_width(box, 1, 0);
    lv_obj_set_style_border_color(box, lv_color_hex(this->color_("tileBorder", 0x4A4A4A)), 0);
    lv_obj_set_style_border_opa(box, LV_OPA_40, 0);
    lv_obj_set_style_radius(box, px(8), 0);
    return;
  }
  lv_obj_set_style_bg_color(box, lv_color_hex(this->color_("tile", 0x1E1E1E)), 0);
  lv_obj_set_style_bg_opa(box, LV_OPA_COVER, 0);
  lv_obj_set_style_border_width(box, 1, 0);
  lv_obj_set_style_border_color(box, lv_color_hex(this->color_("tileBorder", 0x4A4A4A)), 0);
  lv_obj_set_style_radius(box, px(8), 0);

  tv.name = lv_label_create(box);
  lv_obj_set_width(tv.name, w - 2 * px(12));
  lv_label_set_long_mode(tv.name, LV_LABEL_LONG_MODE_DOTS);
  lv_obj_set_style_text_align(tv.name, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_style_text_font(tv.name, tv.big ? this->fonts_.name : this->fonts_.name_s, 0);
  lv_obj_set_style_text_color(tv.name, lv_color_hex(this->color_("text", 0xFFFFFF)), 0);
  lv_obj_align(tv.name, LV_ALIGN_TOP_MID, 0, px(12));

  const AssetId icon = icon_for(tv.kind, tv.big, tv.icon_hint);
  if (const lv_image_dsc_t *img = icon < IMG_COUNT ? this->rt_->image(icon) : nullptr) {
    tv.icon = lv_image_create(box);
    lv_image_set_src(tv.icon, img);
    // (the thermometer art reaches the bottom of its image: 4 px higher)
    lv_obj_align(tv.icon, LV_ALIGN_BOTTOM_LEFT, px(5), -px(tv.kind == "climate" ? 14 : 10));
  }

  if (has_switch(tv.kind)) {
    // the switch: its track image (on / off) and the knob over it
    Track tr;
    track_for(tv.kind, tr);
    const lv_image_dsc_t *off = this->rt_->image(tv.big ? tr.off : tr.off_s);
    if (off != nullptr) {
      tv.track = lv_image_create(box);
      lv_image_set_src(tv.track, off);
      lv_obj_align(tv.track, LV_ALIGN_TOP_MID, 0, px(58));
      // (sized for the 7": the same pixels are ~30% smaller there)
      lv_obj_set_ext_click_area(tv.track, std::max(px(15), 16));
      lv_obj_add_flag(tv.track, LV_OBJ_FLAG_CLICKABLE);
      lv_obj_add_event_cb(tv.track, &Board::on_tap_, LV_EVENT_CLICKED, &tv);
      tv.knob = lv_image_create(tv.track);
      if (const lv_image_dsc_t *knob = this->rt_->image(tv.big ? IMG_KNOB_SWITCH : IMG_KNOB_SWITCH_S))
        lv_image_set_src(tv.knob, knob);
    }
    if (tv.kind == "color_light")
      this->build_swatch_(tv);
    else
      this->build_roller_(tv);
    if (tv.kind == "climate" || tv.kind == "water")
      this->build_thermo_(tv);
    if (tv.kind == "water")
      this->build_heater_(tv);
  } else if (tv.kind == "appliance") {
    this->build_appliance_(tv);
  } else if (tv.kind == "vacuum") {
    this->build_vacuum_(tv);
  } else if (tv.kind == "map") {
    this->build_map_(tv);
  } else if (is_run(tv.kind)) {
    // one big play button in the middle
    const int d = px(96);
    tv.play = lv_obj_create(box);
    lv_obj_remove_style_all(tv.play);
    lv_obj_set_size(tv.play, d, d);
    lv_obj_set_style_radius(tv.play, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_opa(tv.play, LV_OPA_COVER, 0);
    lv_obj_align(tv.play, LV_ALIGN_CENTER, 0, px(8));
    lv_obj_add_flag(tv.play, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(tv.play, &Board::on_tap_, LV_EVENT_CLICKED, &tv);
    // MIRRORED: frontend/src/theme.ts BUTTON_ART (run_gift) - a change here must be made there too.
    if (const lv_image_dsc_t *art = this->rt_->image(tv.big ? IMG_RUN_GIFT : IMG_RUN_GIFT_S)) {  // (a present)
      lv_obj_t *img = lv_image_create(tv.play);
      lv_image_set_src(img, art);
      lv_obj_center(img);
    } else {
      lv_obj_t *glyph = lv_label_create(tv.play);
      lv_label_set_text(glyph, "\U000F040A");  // mdi:play
      lv_obj_set_style_text_font(glyph, tv.big ? this->fonts_.play : this->fonts_.play_s, 0);
      lv_obj_set_style_text_color(glyph, lv_color_hex(this->color_("onAccent", 0xFFFFFF)), 0);
      lv_obj_align(glyph, LV_ALIGN_CENTER, px(3), 0);
    }
  }
  this->watch_(tv.kind, tv.entity);
  // the small stopwatch, over the middle (shown while it waits)
  if (!tv.entity.empty())
    tv.busy = this->busy_icons_.make(box, px(40), this->color_("accent", 0x4B9EF3));
}

// What each kind of tile needs to know (the state + these attributes). HA
// answers in the order asked and skips attributes an entity doesn't have:
// each list ends in one it always has, so the answer to that one says the
// tile has everything (Board::waiting_)
static std::vector<const char *> attrs_for(const std::string &kind) {
  if (kind == "dimmable_light")
    return {"brightness"};
  if (kind == "color_light")
    return {"entity_id", "brightness", "hs_color", "color_temp_kelvin", "color_mode", "min_color_temp_kelvin",
            "max_color_temp_kelvin", "supported_color_modes"};
  if (kind == "fan")
    return {"percentage"};
  if (kind == "cover")
    return {"current_position", "supported_features"};
  if (kind == "climate")
    return {"current_temperature", "temperature", "target_temp_low", "target_temp_high", "hvac_action",
            "target_temp_step", "min_temp", "max_temp"};
  if (kind == "water")
    return {"pool", "body", "mode", "can_turn_on", "has_heater", "active", "heater", "heater_next",
            "heater_pending", "temperature_read", "status", "tile"};
  if (kind == "appliance" || kind == "vacuum")
    return {"tile"};
  return {};
}

// Asked HA for and still waiting on any of it: every tile's stopwatch shows
bool Board::waiting_(const TileView &tv) const {
  if (tv.entity.empty())
    return false;
  StateHub &st = this->rt_->states();
  if (st.waiting(tv.entity))
    return true;
  for (const char *a : attrs_for(tv.kind))
    if (st.waiting(tv.entity, a))
      return true;
  return false;
}

void Board::watch_(const std::string &kind, const std::string &entity) {
  if (entity.empty())
    return;
  this->rt_->states().watch(entity);
  for (const char *a : attrs_for(kind))
    this->rt_->states().watch(entity, a);
}

// Up to this many subscribed values ahead (~200 B of internal RAM each); past
// it the remaining areas subscribe when they're shown (their tiles' stopwatch
// shows meanwhile). This house: ~420.
static const size_t PRELOAD_BUDGET = 600;

void Board::preload(const PanelModel &model) {
  auto &st = this->rt_->states();
  auto area_tiles = [&](const AreaSpec &a) {
    for (bool big : {true, false})
      for (const TileSpec &t : a.tiles(big)) {
        if (st.count() >= PRELOAD_BUDGET)
          return false;
        this->watch_(t.kind, t.entity);
      }
    return true;
  };
  const AreaSpec *cur = model.current();
  if (cur != nullptr && !area_tiles(*cur))
    return;
  for (const AreaSpec &a : model.areas)
    if (&a != cur && !area_tiles(a))
      break;
}

void Board::wait_for_(std::initializer_list<int> slots) {
  const uint32_t until = millis() + 10000;  // (the new board replaces it sooner)
  for (auto &tv : this->tiles_)
    for (int s : slots)
      if (tv.slot == s) {
        tv.waiting_until = until;
        BusyIcons::show(tv.busy, true);
      }
}

// A colour light: the swatch ring (the light's colour inside) where the
// roller would be; a tap opens the colour picker (dashboard _renderSwatch).
void Board::build_swatch_(TileView &tv) {
  const lv_image_dsc_t *ring = this->rt_->image(tv.big ? IMG_SWATCH_RING : IMG_SWATCH_RING_S);
  if (ring == nullptr)
    return;
  const int d = ring->header.w;
  tv.swatch = lv_obj_create(tv.box);
  lv_obj_remove_style_all(tv.swatch);
  lv_obj_set_size(tv.swatch, d, d);
  if (tv.big)
    lv_obj_align(tv.swatch, LV_ALIGN_TOP_MID, 44, 110);
  else
    lv_obj_align(tv.swatch, LV_ALIGN_TOP_RIGHT, -12, 76);
  lv_obj_add_flag(tv.swatch, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_set_ext_click_area(tv.swatch, 12);
  lv_obj_add_event_cb(tv.swatch, &Board::on_swatch_, LV_EVENT_CLICKED, &tv);
  tv.swatch_fill = lv_obj_create(tv.swatch);
  lv_obj_remove_style_all(tv.swatch_fill);
  lv_obj_set_size(tv.swatch_fill, d * 7 / 10, d * 7 / 10);
  lv_obj_center(tv.swatch_fill);
  lv_obj_set_style_radius(tv.swatch_fill, LV_RADIUS_CIRCLE, 0);
  lv_obj_remove_flag(tv.swatch_fill, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_t *img = lv_image_create(tv.swatch);
  lv_image_set_src(img, ring);
  lv_obj_center(img);
  lv_obj_remove_flag(img, LV_OBJ_FLAG_CLICKABLE);
  // "Color & Brightness" left of it, like a roller's word (the old panels)
  const float k = tv.big ? 1.0f : 0.68f;
  tv.prefix = lv_label_create(tv.box);
  lv_label_set_text(tv.prefix, this->rt_->t("roller.color_brightness").c_str());
  lv_obj_set_style_text_align(tv.prefix, LV_TEXT_ALIGN_RIGHT, 0);
  lv_obj_set_style_text_font(tv.prefix, tv.big ? this->fonts_.prefix : this->fonts_.prefix_s, 0);
  lv_obj_set_style_text_color(tv.prefix, lv_color_hex(this->color_("light", 0xFFB300)), 0);
  lv_obj_align_to(tv.prefix, tv.swatch, tv.big ? LV_ALIGN_OUT_LEFT_MID : LV_ALIGN_OUT_LEFT_TOP, -(int) (6 * k + 0.5f), 0);
}

void Board::paint_swatch_(TileView &tv) {
  if (tv.swatch_fill == nullptr)
    return;
  uint32_t rgb = 0;
  bool have = this->rt_->picker().held_swatch(tv.entity, rgb) || light_swatch(this->rt_, tv.entity, rgb);
  const bool on = this->is_on_(tv);
  lv_obj_set_style_bg_color(tv.swatch_fill, lv_color_hex(rgb), 0);
  lv_obj_set_style_bg_opa(tv.swatch_fill, !have ? LV_OPA_TRANSP : on ? LV_OPA_COVER : LV_OPA_30, 0);
}

void Board::on_swatch_(lv_event_t *e) {
  auto *tv = static_cast<TileView *>(lv_event_get_user_data(e));
  if (tv == nullptr || tv->board == nullptr)
    return;
  const std::string &state = tv->board->rt_->states().get(tv->entity);
  if (state.empty() || state == "unavailable")
    return;
  tv->board->rt_->picker().open(tv->board->rt_, tv->board->fonts_, tv->entity, tv->name_text);
}

void Board::build_roller_(TileView &tv) {
  RollerGeo g;
  if (!roller_geo(tv.kind, g))
    return;
  std::string opts;
  std::string prefix;
  auto add = [&opts](const std::string &o) { opts += (opts.empty() ? "" : "\n") + o; };
  if (tv.kind == "dimmable_light") {
    for (int v = 100; v >= 5; v -= 5)
      add(std::to_string(v));
    add(this->rt_->t("roller.off"));
    prefix = this->rt_->t("roller.brightness");
  } else if (tv.kind == "fan") {
    for (int v = FAN_SPEEDS; v >= 1; v--)
      add(std::to_string(v));
    add(this->rt_->t("roller.off"));
    prefix = this->rt_->t("roller.speed");
  } else if (tv.kind == "cover") {
    add(this->rt_->t("roller.open"));
    for (int v = 10; v <= 90; v += 10)
      add(std::to_string(v));
    add(this->rt_->t("roller.closed"));
    prefix = this->rt_->t("roller.coverage");
  } else if (tv.kind == "lock") {
    add(this->rt_->t("roller.unlocked"));
    add(this->rt_->t("roller.locked"));
    prefix = this->rt_->t("roller.doors");
  } else if (tv.kind == "climate") {
    // (no word beside it: the temperature and status take that place)
    for (int v = CLIMATE_MAX_F; v >= CLIMATE_MIN_F; v--)
      add(std::to_string(v));
  } else {
    for (int v = WATER_MAX_F; v >= WATER_MIN_F; v--)
      add(std::to_string(v));
  }
  const float k = tv.big ? 1.0f : 0.68f;
  auto px = [k](int v) { return (int) (v * k + 0.5f); };
  const uint32_t colour = this->color_(g.color, g.fallback);
  lv_obj_t *r = lv_roller_create(tv.box);
  tv.roller = r;
  lv_roller_set_options(r, opts.c_str(), LV_ROLLER_MODE_NORMAL);
  lv_obj_set_width(r, px(g.w));
  // a subtle frame (the tiles' own border grey - the original panels' theme
  // frame was too bright) and the rows above / below dimmed: the dashboard's
  // fade, as text opacity (one row each side - no gradient mask to draw)
  lv_obj_set_style_bg_opa(r, LV_OPA_TRANSP, 0);
  lv_obj_set_style_border_width(r, 1, 0);
  lv_obj_set_style_border_color(r, lv_color_hex(this->color_("tileBorder", 0x4A4A4A)), 0);
  lv_obj_set_style_radius(r, px(8), 0);
  lv_obj_set_style_pad_hor(r, px(2), 0);
  lv_obj_set_style_pad_ver(r, px(4), 0);
  if (!tv.big)
    lv_obj_set_style_text_line_space(r, (lv_obj_get_style_text_line_space(r, LV_PART_MAIN) * 68 + 50) / 100, 0);
  lv_obj_set_style_text_opa(r, LV_OPA_50, 0);
  lv_obj_set_style_text_opa(r, LV_OPA_COVER, LV_PART_SELECTED);
  lv_obj_set_style_text_align(r, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_style_text_font(r, tv.big ? this->fonts_.roll : this->fonts_.roll_s, 0);
  lv_obj_set_style_text_color(r, lv_color_hex(this->color_("rollerText", 0x808080)), 0);
  lv_obj_set_style_bg_opa(r, LV_OPA_TRANSP, LV_PART_SELECTED);
  lv_obj_set_style_text_color(r, lv_color_hex(colour), LV_PART_SELECTED);
  // the selected row's font: the kind's own, a size down at a time until its
  // longest word fits (a language's long "Off" / "Unlocked"; the numbers with it)
  {
    const lv_font_t *steps_big[] = {g.mid_font ? this->fonts_.roll_mid : this->fonts_.roll_sel, this->fonts_.roll_mid,
                                    this->fonts_.roll_mid_s, this->fonts_.roll};
    const lv_font_t *steps_small[] = {g.mid_font ? this->fonts_.roll_mid_s : this->fonts_.roll_sel_s,
                                      this->fonts_.roll_mid_s, this->fonts_.roll_s};
    const lv_font_t *const *steps = tv.big ? steps_big : steps_small;
    const int n_steps = tv.big ? 4 : 3;
    const int room = px(g.w) - 2;  // (inside its border: the row may use the padding)
    const lv_font_t *font = steps[n_steps - 1];
    for (int i = 0; i < n_steps; ++i) {
      int widest = 0;
      size_t start = 0;
      while (start <= opts.size()) {
        size_t end = opts.find('\n', start);
        if (end == std::string::npos)
          end = opts.size();
        lv_point_t sz;
        lv_text_get_size(&sz, opts.substr(start, end - start).c_str(), steps[i], 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);
        widest = std::max<int>(widest, sz.x);
        start = end + 1;
      }
      if (widest <= room) {
        font = steps[i];
        break;
      }
    }
    lv_obj_set_style_text_font(r, font, LV_PART_SELECTED);
    // the other rows (smaller, dimmed): a size down too if a word needs it
    if (tv.big) {
      int widest = 0;
      size_t start = 0;
      while (start <= opts.size()) {
        size_t end = opts.find('\n', start);
        if (end == std::string::npos)
          end = opts.size();
        lv_point_t sz;
        lv_text_get_size(&sz, opts.substr(start, end - start).c_str(), this->fonts_.roll, 0, 0, LV_COORD_MAX,
                         LV_TEXT_FLAG_NONE);
        widest = std::max<int>(widest, sz.x);
        start = end + 1;
      }
      if (widest > room)
        lv_obj_set_style_text_font(r, this->fonts_.roll_s, 0);
    }
  }
  lv_roller_set_visible_row_count(r, 3);  // (after the fonts and spacing: its height follows them)
  if (tv.big)
    lv_obj_align(r, LV_ALIGN_TOP_MID, g.x, 114);
  else
    lv_obj_align(r, LV_ALIGN_TOP_RIGHT, -2, 78);
  lv_obj_add_event_cb(r, &Board::on_roller_, LV_EVENT_VALUE_CHANGED, &tv);
  if (prefix.empty())
    return;
  tv.prefix = lv_label_create(tv.box);
  lv_label_set_text(tv.prefix, prefix.c_str());
  lv_obj_set_style_text_font(tv.prefix, tv.big ? this->fonts_.prefix : this->fonts_.prefix_s, 0);
  lv_obj_set_style_text_color(tv.prefix, lv_color_hex(colour), 0);
  lv_obj_align_to(tv.prefix, r, tv.big ? LV_ALIGN_OUT_LEFT_MID : LV_ALIGN_OUT_LEFT_TOP, -px(6), 0);
}

// MIRRORED: frontend/src/rules.ts rollerRow - a change here must be made there too.
// The row for HA's state (rules.ts rollerRow); -1 = no roller shown
int Board::ha_row_(const TileView &tv) const {
  auto &st = this->rt_->states();
  const std::string &state = st.get(tv.entity);
  if (tv.kind == "dimmable_light") {
    if (state != "on")
      return BRI_OFF_ROW;
    const int pct = as_int(st.get(tv.entity, "brightness"), 255) * 100 / 255;
    return clampi(BRI_OFF_ROW - (pct + 4) / 5, 0, BRI_OFF_ROW - 1);
  }
  if (tv.kind == "fan") {
    if (state != "on")
      return FAN_SPEEDS;
    const int pct = as_int(st.get(tv.entity, "percentage"), 100);
    return FAN_SPEEDS - clampi((pct * FAN_SPEEDS + 50) / 100, 1, FAN_SPEEDS);
  }
  if (tv.kind == "cover") {
    if (!(as_int(st.get(tv.entity, "supported_features"), 0) & COVER_SET_POSITION))
      return -1;  // opens / closes only: the switch is all
    const bool open = state_on("cover", state);
    const int pos = as_int(st.get(tv.entity, "current_position"), open ? 100 : 0);
    if (pos <= 0)
      return COV_CLOSED_ROW;
    if (pos >= 100)
      return COV_OPEN_ROW;
    return clampi((100 - pos + 9) / 10, COV_OPEN_ROW + 1, COV_CLOSED_ROW - 1);
  }
  if (tv.kind == "lock")
    return state == "locked" ? LOCK_LOCKED_ROW : 0;
  if (tv.kind == "climate") {
    float lo, hi;
    int t = -1000;
    if (this->climate_band_(tv, -1000, lo, hi))
      t = (int) lroundf((lo + hi) / 2);
    else if (!st.get(tv.entity, "temperature").empty() && st.get(tv.entity, "temperature") != "None")
      t = (int) lroundf(atof(st.get(tv.entity, "temperature").c_str()));
    return t == -1000 ? 7 : clampi(CLIMATE_MAX_F - t, 0, CLIMATE_MAX_F - CLIMATE_MIN_F);
  }
  if (tv.kind == "water") {
    if (st.get(tv.entity, "has_heater") == "off" || this->busy_(tv))
      return -1;  // no heater for this body / switching: nothing to set now
    const int target = as_int(field_(st.get(tv.entity, "tile"), 4), 0);
    return target > 0 ? clampi(WATER_MAX_F - target, 0, WATER_MAX_F - WATER_MIN_F) : 6;
  }
  return -1;
}

void Board::paint_roller_(TileView &tv) {
  if (tv.roller == nullptr)
    return;
  const int ha = this->ha_row_(tv);
  const bool show = ha >= 0;
  if (show) {
    lv_obj_remove_flag(tv.roller, LV_OBJ_FLAG_HIDDEN);
    if (tv.prefix)
      lv_obj_remove_flag(tv.prefix, LV_OBJ_FLAG_HIDDEN);
  } else {
    lv_obj_add_flag(tv.roller, LV_OBJ_FLAG_HIDDEN);
    if (tv.prefix)
      lv_obj_add_flag(tv.prefix, LV_OBJ_FLAG_HIDDEN);
    return;
  }
  if (tv.kind == "climate") {
    // the mode's colour (rules.ts climateTone): heat red, cool blue, else white
    const int tone = this->climate_tone_(tv);
    const uint32_t c = tone == 1 ? this->color_("heatStrong", 0xFF2F26)
                       : tone == 2 ? this->color_("coolStrong", 0x2B78F1)
                                   : this->color_("text", 0xFFFFFF);
    lv_obj_set_style_text_color(tv.roller, lv_color_hex(c), LV_PART_SELECTED);
  }
  // never move it under the user's finger
  if (lv_obj_has_state(tv.roller, LV_STATE_PRESSED) || lv_obj_is_scrolling(tv.roller))
    return;
  const int row = tv.held_row >= 0 ? tv.held_row : ha;
  if ((int) lv_roller_get_selected(tv.roller) != row)
    lv_roller_set_selected(tv.roller, row, LV_ANIM_ON);
}

// MIRRORED: frontend/src/rules.ts rollerCall (+ climateBand) - a change here must be made there too.
// The user stopped the roller on a row (rules.ts rollerCall)
void Board::roller_picked_(TileView &tv, int row) {
  const std::string &state = this->rt_->states().get(tv.entity);
  if (state.empty() || state == "unavailable" || this->busy_(tv)) {
    this->paint_roller_(tv);  // (back to HA's row)
    return;
  }
  if (row == this->ha_row_(tv) && tv.held_row < 0)
    return;  // nothing changed
  tv.held_row = row;
  tv.held_row_until = millis() + hold_ms(tv.kind, true, row);
  auto &act = this->rt_->actions();
  const std::string &e = tv.entity;
  if (tv.kind == "dimmable_light") {
    if (row == BRI_OFF_ROW)
      act.call("light.turn_off", e);
    else
      act.call("light.turn_on", e, "{\"brightness_pct\":" + std::to_string((BRI_OFF_ROW - row) * 5) + "}");
  } else if (tv.kind == "fan") {
    if (row == FAN_SPEEDS)
      act.call("fan.turn_off", e);
    else
      act.call("fan.set_percentage", e, "{\"percentage\":" + std::to_string((FAN_SPEEDS - row) * 100 / FAN_SPEEDS) + "}");
  } else if (tv.kind == "cover") {
    if (row == COV_OPEN_ROW)
      act.call("cover.open_cover", e);
    else if (row == COV_CLOSED_ROW)
      act.call("cover.close_cover", e);
    else
      act.call("cover.set_cover_position", e, "{\"position\":" + std::to_string(100 - row * 10) + "}");
  } else if (tv.kind == "lock") {
    act.call(row == LOCK_LOCKED_ROW ? "lock.lock" : "lock.unlock", e);
  } else if (tv.kind == "climate") {
    // auto: the whole band moves, its width kept (rules.ts climateBand)
    float lo, hi;
    char buf[80];
    if (this->climate_band_(tv, CLIMATE_MAX_F - row, lo, hi))
      snprintf(buf, sizeof(buf), "{\"target_temp_low\":%.2f,\"target_temp_high\":%.2f}", lo, hi);
    else
      snprintf(buf, sizeof(buf), "{\"temperature\":%d}", CLIMATE_MAX_F - row);
    act.call("climate.set_temperature", e, buf);
    this->paint_(tv);
    return;  // (a temperature: the switch stays as it is)
  } else if (tv.kind == "water") {
    act.call("room_tiles.pool_set_target", e, "{\"temperature\":" + std::to_string(WATER_MAX_F - row) + "}");
    this->paint_(tv);
    return;
  }
  // the switch follows the pick at once (off row = off)
  const bool on = tv.kind == "dimmable_light" ? row != BRI_OFF_ROW
                  : tv.kind == "fan"          ? row != FAN_SPEEDS
                  : tv.kind == "cover"        ? row != COV_CLOSED_ROW
                                              : row == LOCK_LOCKED_ROW;
  tv.held = on ? 1 : 0;
  tv.held_until = tv.held_row_until;
  this->paint_(tv);
}

void Board::on_roller_(lv_event_t *e) {
  auto *tv = static_cast<TileView *>(lv_event_get_user_data(e));
  if (tv == nullptr || tv->board == nullptr)
    return;
  tv->board->roller_picked_(*tv, (int) lv_roller_get_selected(tv->roller));
}

// MIRRORED: frontend/src/map.ts iconOn - a change here must be made there too.
// A tile's icon "on" (else the theme's off picture, when it has one): the
// map markers' rule, so tile and marker agree - the switch's own value where
// there is one (a tap shows at once), a lock's inverted (unlocked = active,
// as on the map); a scene / script lit while its tap flashes.
bool Board::icon_on_(const TileView &tv, bool on) const {
  if (is_run(tv.kind) && tv.flash_until != 0)
    return true;
  if (tv.kind == "lock")
    return !on;
  if (tv.kind == "appliance" || tv.kind == "water" || tv.kind == "vacuum" || tv.kind == "scene" || tv.kind == "script")
    return marker_active(this->rt_->states(), tv.kind, tv.entity);
  return on;
}

bool Board::is_on_(const TileView &tv) const {
  if (tv.held >= 0)
    return tv.held == 1;
  return this->ha_on_(tv);
}

// A pool / spa switching between pool and spa (minutes) or offline: its
// controls are dimmed and locked - a change made then could settle long after
// the user has gone (user, 2026-11-12); the temperature + status stay
bool Board::busy_(const TileView &tv) const {
  if (tv.kind != "water")
    return false;
  const std::string &state = this->rt_->states().get(tv.entity);
  return state == "switching" || state == "offline";
}

// MIRRORED: frontend/src/rules.ts switchOn / switchCall - a change here must be made there too.
// What HA says about the switch (rules.ts switchOn)
bool Board::ha_on_(const TileView &tv) const {
  const std::string &state = this->rt_->states().get(tv.entity);
  if (tv.kind == "climate")
    return !state.empty() && state != "off" && state != "unavailable" && state != "unknown";
  if (tv.kind == "water")
    return this->water_on_(tv);
  return state_on(tv.kind, state);
}

void Board::switch_call_(TileView &tv, bool on) {
  if (tv.kind == "water") {
    // the body (pump / spa mode), or a spa's heater (rules.ts switchCall)
    const int what = this->water_switch_(tv);
    if (what == 1)
      this->rt_->actions().call("room_tiles.pool_set_on", tv.entity, on ? "{\"on\":true}" : "{\"on\":false}");
    else if (what == 2)
      this->rt_->actions().call("room_tiles.pool_set_heater", tv.entity, on ? "{\"heater\":true}" : "{\"heater\":false}");
    return;
  }
  this->rt_->actions().call(switch_service(tv.kind, domain_of(tv.entity), on), tv.entity);
}

void Board::paint_(TileView &tv) {
  if (tv.kind.empty() || tv.box == nullptr)
    return;
  const std::string &state = this->rt_->states().get(tv.entity);
  // (a Map tile has no entity: never "unavailable")
  const bool unavailable = !tv.entity.empty() && (state.empty() || state == "unavailable");
  const bool busy = this->busy_(tv);
  // (the roller itself is hidden then - ha_row_ - and the full status shows)
  for (lv_obj_t *o : {tv.track, tv.icon})
    if (o != nullptr)
      lv_obj_set_style_opa(o, busy ? LV_OPA_40 : LV_OPA_COVER, 0);
  // (dimmed by colour, never by object opacity: that renders each tile
  // through its own off-screen layer - far too slow for a whole board)
  if (tv.name != nullptr)
    lv_obj_set_style_text_color(tv.name,
                                lv_color_hex(unavailable || busy ? this->color_("textSecondary", 0x9E9E9E)
                                                                 : this->color_("text", 0xFFFFFF)),
                                0);
  // no state yet, or HA still to answer for some of it (just drawn, a
  // pop-up, a far area past the preload), or a change on its way: the stopwatch
  BusyIcons::show(tv.busy, (!tv.entity.empty() && state.empty()) || this->waiting_(tv) || tv.waiting_until != 0);
  bool on = !unavailable && is_on_(tv);
  if (tv.kind == "scene")
    on = tv.flash_until != 0;  // a scene is only "on" for its tap's flash
  else if (tv.kind == "script")
    on = on || tv.flash_until != 0;
  // (the icon stays in its colours in every state, like the dashboard: the
  // switch / roller say what state it's in) - unless the theme has a picture
  // of its own for "off" (any icon: the Christmas reindeer's nose goes dark)
  // MIRRORED: frontend/src/theme.ts iconArt (OFF_ART) - a change here must be made there too.
  if (tv.icon != nullptr && tv.kind != "water") {  // (water: paint_thermo_ picks pool / spa)
    const AssetId icon = icon_for(tv.kind, tv.big, tv.icon_hint);
    const AssetId off = icon < IMG_COUNT ? off_art(icon) : IMG_COUNT;
    const lv_image_dsc_t *img = !this->icon_on_(tv, on) && off < IMG_COUNT ? this->rt_->image(off) : nullptr;
    if (img == nullptr && icon < IMG_COUNT)
      img = this->rt_->image(icon);
    if (img != nullptr && lv_image_get_src(tv.icon) != img)
      lv_image_set_src(tv.icon, img);
  }
  if (tv.track != nullptr && tv.kind == "water") {
    // nothing to switch on this body: no switch
    if (this->water_switch_(tv) == 0)
      lv_obj_add_flag(tv.track, LV_OBJ_FLAG_HIDDEN);
    else
      lv_obj_remove_flag(tv.track, LV_OBJ_FLAG_HIDDEN);
  }
  if (tv.track != nullptr) {
    Track tr;
    track_for(tv.kind, tr);
    if (tv.kind == "climate") {
      const int tone = this->climate_tone_(tv);
      tr.on = tone == 1 ? IMG_TRACK_SWITCH_ON_RED : tone == 2 ? IMG_TRACK_SWITCH_ON_BLUE : IMG_TRACK_SWITCH_ON_SLATE;
      tr.on_s = tone == 1 ? IMG_TRACK_SWITCH_ON_RED_S : tone == 2 ? IMG_TRACK_SWITCH_ON_BLUE_S : IMG_TRACK_SWITCH_ON_SLATE_S;
    }
    const lv_image_dsc_t *track = this->rt_->image(on ? (tv.big ? tr.on : tr.on_s) : (tv.big ? tr.off : tr.off_s));
    if (track != nullptr) {
      lv_image_set_src(tv.track, track);
      const int tw = track->header.w, th = track->header.h;
      int kw = 0, kh = 0;
      if (const lv_image_dsc_t *knob = this->rt_->image(tv.big ? IMG_KNOB_SWITCH : IMG_KNOB_SWITCH_S)) {
        kw = knob->header.w;
        kh = knob->header.h;
      }
      lv_obj_set_pos(tv.knob, on ? tw - kw - 1 : 1, (th - kh) / 2);
    }
  }
  this->paint_roller_(tv);
  this->paint_swatch_(tv);
  if (tv.temp != nullptr)
    this->paint_thermo_(tv);
  if (tv.heater != nullptr)
    this->paint_heater_(tv);
  if (tv.kind == "appliance")
    this->paint_appliance_(tv);
  else if (tv.kind == "vacuum")
    this->paint_vacuum_(tv);
  if (tv.play != nullptr) {
    const uint32_t c = this->color_(tv.kind == "scene" ? "scene" : "script", tv.kind == "scene" ? 0x2EC4B6 : 0xFF8F3F);
    lv_obj_set_style_bg_color(tv.play, lv_color_hex(c), 0);
    if (!this->editing_) {  // (editing: the edit outline stays)
      lv_obj_set_style_border_width(tv.box, on ? 2 : 1, 0);
      lv_obj_set_style_border_color(tv.box, lv_color_hex(on ? c : this->color_("tileBorder", 0x4A4A4A)), 0);
    }
  }
}

void Board::toggle_(TileView &tv) {
  const std::string &state = this->rt_->states().get(tv.entity);
  if (state.empty() || state == "unavailable" || this->busy_(tv))
    return;
  const bool want = !is_on_(tv);
  tv.held = want ? 1 : 0;
  tv.held_until = millis() + hold_ms(tv.kind, false, -1);
  this->paint_(tv);
  this->switch_call_(tv, want);
}

void Board::run_(TileView &tv) {
  const std::string &state = this->rt_->states().get(tv.entity);
  if (state.empty() || state == "unavailable")
    return;
  tv.flash_until = millis() + FLASH_MS;
  this->paint_(tv);
  this->rt_->actions().call(domain_of(tv.entity) + ".turn_on", tv.entity);
}

void Board::on_tap_(lv_event_t *e) {
  auto *tv = static_cast<TileView *>(lv_event_get_user_data(e));
  if (tv == nullptr || tv->board == nullptr)
    return;
  if (tv->kind == "map")
    tv->board->rt_->open_map("");
  else if (tv->kind == "vacuum")
    tv->board->rt_->open_queue(tv->entity);
  else if (is_run(tv->kind))
    tv->board->run_(*tv);
  else
    tv->board->toggle_(*tv);
}

void Board::on_layout_(lv_event_t *e) {
  auto *self = static_cast<Board *>(lv_event_get_user_data(e));
  // drawn at once from what the panel has; the panel's own setting goes to HA
  // (rebuilding deletes this button: after its event)
  lv_async_call([](void *p) {
    auto *b = static_cast<Board *>(p);
    b->rt_->choose_layout(b->layout_ == "6x3" ? "5x2" : "6x3");
  }, self);
}

lv_obj_t *Board::popup_add(lv_obj_t *parent, const std::string &entity, const std::string &kind, int x, int y) {
  if (this->model_ == nullptr)
    return nullptr;
  this->popups_.emplace_back();
  TileView &tv = this->popups_.back();
  tv.board = this;
  tv.kind = kind;
  tv.entity = entity;
  tv.big = true;
  tv.slot = -1;
  tv.icon_hint = this->model_->icon(entity);
  this->build_tile_(tv, x, y, POPUP_W, POPUP_H, parent);
  tv.name_text = this->model_->short_name(entity);
  if (tv.name != nullptr)
    lv_label_set_text(tv.name, tv.name_text.c_str());
  this->paint_(tv);
  return tv.box;
}

void Board::popup_clear() {
  for (auto &tv : this->popups_) {
    this->busy_icons_.forget_in(tv.box);
    lv_obj_delete(tv.box);
  }
  this->popups_.clear();
}

void Board::paint_lights_() {
  if (this->lights_glyph_ == nullptr)
    return;
  const bool on = std::any_of(this->lights_.begin(), this->lights_.end(),
                              [this](const std::string &l) { return this->rt_->states().get(l) == "on"; });
  if (this->lights_art_ != nullptr) {
    const lv_image_dsc_t *img = on ? nullptr : this->rt_->image(IMG_BAR_AREA_LIGHTS_OFF);
    if (img == nullptr)
      img = this->rt_->image(IMG_BAR_AREA_LIGHTS);
    if (img != nullptr && lv_image_get_src(this->lights_art_) != img)
      lv_image_set_src(this->lights_art_, img);
    return;
  }
  lv_label_set_text(this->lights_glyph_, on ? "\U000F1253" : "\U000F1254");  // mdi:lightbulb-group(-outline)
  lv_obj_set_style_text_color(this->lights_glyph_,
                              lv_color_hex(on ? this->color_("light", 0xFFB300) : this->color_("text", 0xFFFFFF)), 0);
}

void Board::entity_changed(const std::string &entity) {
  if (std::find(this->lights_.begin(), this->lights_.end(), entity) != this->lights_.end())
    this->paint_lights_();
  std::vector<TileView *> views;
  for (auto &tv : this->tiles_)
    views.push_back(&tv);
  for (auto &tv : this->popups_)
    views.push_back(&tv);
  for (TileView *p : views) {
    TileView &tv = *p;
    if (tv.entity != entity) {
      if (!tv.robot_sensor.empty() && tv.robot_sensor == entity)
        this->paint_(tv);  // (a vacuum tile: its queue changed)
      continue;
    }
    // HA agrees with the held value: stop holding
    if (tv.held >= 0 && this->ha_on_(tv) == (tv.held == 1) && tv.held_row < 0)
      tv.held = -1;
    if (tv.held_row >= 0 && this->ha_row_(tv) == tv.held_row) {
      tv.held_row = -1;
      tv.held = -1;
    }
    this->paint_(tv);
  }
}

void Board::paint_clock() {
  if (this->clock_ == nullptr || this->rt_ == nullptr)
    return;
  const time_t t_now = ::time(nullptr);
  struct tm t;
  localtime_r(&t_now, &t);
  const bool known = t_now >= 1600000000;
  const bool h12 = this->rt_->hours12();
  this->clock_shown_ = known ? t.tm_hour * 60 + t.tm_min : -2;
  // MIRRORED: idle_clock.cpp paint_ (the digital clock's time) - a change here must be made there too.
  char buf[40];
  if (!known) {
    snprintf(buf, sizeof(buf), "--:--");
  } else if (h12) {
    std::string ampm = this->rt_->t(t.tm_hour < 12 ? "clock.am" : "clock.pm");
    if (ampm == "clock.am" || ampm == "clock.pm")
      ampm = t.tm_hour < 12 ? "AM" : "PM";
    snprintf(buf, sizeof(buf), "%d:%02d %s", t.tm_hour % 12 == 0 ? 12 : t.tm_hour % 12, t.tm_min, ampm.c_str());
  } else {
    snprintf(buf, sizeof(buf), "%02d:%02d", t.tm_hour, t.tm_min);
  }
  lv_label_set_text(this->clock_, buf);
  lv_obj_update_layout(this->clock_);
  const int w = lv_obj_get_width(this->clock_), h = lv_obj_get_height(this->clock_);
  if (this->clock_hi_ - this->clock_lo_ < w) {
    lv_obj_add_flag(this->clock_, LV_OBJ_FLAG_HIDDEN);
    return;
  }
  lv_obj_remove_flag(this->clock_, LV_OBJ_FLAG_HIDDEN);
  const int cx = std::max(this->clock_lo_ + w / 2, std::min(this->clock_hi_ - (w + 1) / 2, 512));
  lv_obj_set_pos(this->clock_, cx - w / 2, 10 + BAR_BTN_H / 2 - h / 2);
}

void Board::loop() {
  const uint32_t now = millis();
  if (this->clock_ != nullptr) {  // (a new minute: the top bar's time)
    static uint32_t checked = 0;
    if (now - checked >= 1000) {
      checked = now;
      const time_t t_now = ::time(nullptr);
      struct tm t;
      localtime_r(&t_now, &t);
      if ((t_now >= 1600000000 ? t.tm_hour * 60 + t.tm_min : -2) != this->clock_shown_)
        this->paint_clock();
    }
  }
  for (auto &tv : this->tiles_)
    this->tick_(tv, now);
  for (auto &tv : this->popups_)
    this->tick_(tv, now);
  this->animate_(now);
  this->busy_icons_.animate(now);
}

// A tile's timers: held values running out, flashes, waits
void Board::tick_(TileView &tv, uint32_t now) {
  {
    bool repaint = false;
    if (tv.held >= 0 && (int32_t) (now - tv.held_until) >= 0) {
      tv.held = -1;  // HA never agreed: show what it says
      repaint = true;
    }
    if (tv.held_row >= 0 && (int32_t) (now - tv.held_row_until) >= 0) {
      tv.held_row = -1;
      repaint = true;
    }
    if (tv.flash_until != 0 && (int32_t) (now - tv.flash_until) >= 0) {
      tv.flash_until = 0;
      repaint = true;
    }
    if (tv.heater_held >= 0 && (int32_t) (now - tv.heater_held_until) >= 0) {
      tv.heater_held = -1;
      repaint = true;
    }
    if (tv.waiting_until != 0 && (int32_t) (now - tv.waiting_until) >= 0) {
      tv.waiting_until = 0;
      repaint = true;
    }
    if (repaint)
      this->paint_(tv);
  }
}

}  // namespace esphome::room_tiles
