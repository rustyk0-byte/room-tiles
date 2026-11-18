// Room Tiles panel: the tiles with their own layouts - thermostat and pool /
// spa (the original panels' shared thermostat layout: the temperature + what
// it's doing left of the roller), the pool / spa heater button, appliances
// (one or two units: picture + animation, label, status) and the vacuum /
// map tiles. Rules: frontend/src/rules.ts + room-tiles-panel.ts.

#include <algorithm>
#include <cinttypes>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "board.h"
#include "text_fit.h"
#include "esphome/core/hal.h"
#include "room_tiles.h"
#include "psram_scope.h"
#include "vacuum_map.h"
#include "esphome/core/log.h"
#include <esp_heap_caps.h>
#include <src/misc/cache/instance/lv_image_cache.h>

namespace esphome::room_tiles {

// MIRRORED: frontend/src/rules.ts settleMs - a change here must be made there too.
static const uint32_t HEATER_HOLD_MS = 20000;  // (rules.ts settleMs: water)
static const uint32_t FRAME_MS = 62;           // appliance animations: 16 fps
static const int SHEET_COLS = 8, SHEET_ROWS = 4;

static bool yes(const std::string &v) { return v == "on" || v == "True" || v == "true"; }
static bool none(const std::string &v) { return v.empty() || v == "None" || v == "unknown" || v == "unavailable"; }

// ---- thermostat / pool rules -----------------------------------------------------

// MIRRORED: frontend/src/rules.ts climateTone - a change here must be made there too.
// heat 1 / cool 2 / neutral 0 - the MODE, not the moment (rules.ts climateTone)
int Board::climate_tone_(const TileView &tv) const {
  auto &st = this->rt_->states();
  const std::string &mode = st.get(tv.entity), &action = st.get(tv.entity, "hvac_action");
  if (mode == "heat")
    return 1;
  if (mode == "cool")
    return 2;
  if (mode == "heat_cool" || mode == "auto")
    return action == "heating" ? 1 : action == "cooling" ? 2 : 0;
  return 0;
}

// MIRRORED: frontend/src/rules.ts climateBand - a change here must be made there too.
// Auto's band: low / high now (mid = -1000), or with its MIDDLE at mid - the
// width kept, within the thermostat's limits, on its step (rules.ts climateBand)
bool Board::climate_band_(const TileView &tv, int mid, float &lo, float &hi) const {
  auto &st = this->rt_->states();
  const std::string &l = st.get(tv.entity, "target_temp_low"), &h = st.get(tv.entity, "target_temp_high");
  if (none(l) || none(h))
    return false;
  lo = atof(l.c_str());
  hi = atof(h.c_str());
  if (mid == -1000)
    return true;
  const float width = hi - lo;
  const std::string &step_s = st.get(tv.entity, "target_temp_step");
  const float step = !none(step_s) && atof(step_s.c_str()) > 0 ? atof(step_s.c_str()) : 1.0f;
  const std::string &mn = st.get(tv.entity, "min_temp"), &mx = st.get(tv.entity, "max_temp");
  float low = roundf((mid - width / 2) / step) * step;
  if (!none(mx))
    low = fminf(low, atof(mx.c_str()) - width);
  if (!none(mn))
    low = fmaxf(low, atof(mn.c_str()));
  lo = roundf(low * 100) / 100;
  hi = roundf((low + width) * 100) / 100;
  return true;
}

// MIRRORED: frontend/src/rules.ts waterSwitch - a change here must be made there too.
// 1 = the switch turns the body on (pump / spa mode), 2 = a spa's heater (a
// Spa tile without a pump), 0 = nothing to switch (rules.ts waterSwitch).
// A Pool tile and the combined tile never switch a heater.
int Board::water_switch_(const TileView &tv) const {
  auto &st = this->rt_->states();
  if (st.get(tv.entity, "pool").empty())
    return 0;  // a hand-made sensor (the old tile contract): read-only
  if (yes(st.get(tv.entity, "can_turn_on")))
    return 1;
  const bool spa_tile = st.get(tv.entity, "body") == "spa" && st.get(tv.entity, "mode").empty();
  return spa_tile && st.get(tv.entity, "has_heater") != "off" ? 2 : 0;
}

// MIRRORED: frontend/src/rules.ts waterOn - a change here must be made there too.
// (rules.ts waterOn)
bool Board::water_on_(const TileView &tv) const {
  auto &st = this->rt_->states();
  const std::string &state = st.get(tv.entity);
  if (this->water_switch_(tv) == 1)
    return yes(st.get(tv.entity, "active")) && state != "pump_off" && state != "offline" && state != "standby";
  return field_(st.get(tv.entity, "tile"), 5) == "on";
}

// ---- the thermostat layout -------------------------------------------------------

void Board::build_thermo_(TileView &tv) {
  const float k = tv.big ? 1.0f : 0.68f;
  auto px = [k](int v) { return (int) (v * k + 0.5f); };
  const int w = tv.big ? 92 : 94;
  tv.temp = lv_label_create(tv.box);
  lv_obj_set_width(tv.temp, w);
  lv_obj_set_style_text_align(tv.temp, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_style_text_font(tv.temp, tv.big ? this->fonts_.thermo : this->fonts_.thermo_s, 0);
  lv_obj_set_pos(tv.temp, px(12), px(98));
  tv.status = lv_label_create(tv.box);
  lv_obj_set_size(tv.status, w, px(40));
  lv_label_set_long_mode(tv.status, LV_LABEL_LONG_MODE_WRAP);
  lv_obj_set_style_text_align(tv.status, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_style_text_font(tv.status, tv.big ? this->fonts_.roll : this->fonts_.roll_s, 0);
  lv_obj_set_style_text_color(tv.status, lv_color_hex(this->color_("textSecondary", 0x9E9E9E)), 0);
  lv_obj_set_pos(tv.status, px(12), px(152));
  if (tv.kind == "climate" && tv.roller != nullptr) {
    // auto: the band's low and high, small, either side under the roller
    for (lv_obj_t **l : {&tv.band_lo, &tv.band_hi}) {
      *l = lv_label_create(tv.box);
      lv_obj_set_style_text_font(*l, tv.big ? this->fonts_.prefix : this->fonts_.prefix_s, 0);
      lv_obj_set_style_text_color(*l, lv_color_hex(this->color_("textSecondary", 0x9E9E9E)), 0);
      lv_obj_add_flag(*l, LV_OBJ_FLAG_HIDDEN);
    }
  }
}

void Board::paint_thermo_(TileView &tv) {
  auto &st = this->rt_->states();
  std::string temp, status;
  uint32_t colour = this->color_("text", 0xFFFFFF);
  if (tv.kind == "water") {
    const std::string &tile = st.get(tv.entity, "tile");  // title|temp|status|look|target|heater
    temp = field_(tile, 1);
    // switching / offline: no roller - the full status line has its room
    status = this->busy_(tv) && !none(st.get(tv.entity, "status")) ? st.get(tv.entity, "status") : field_(tile, 2);
    const std::string look = field_(tile, 3);
    if (look == "heating")
      colour = this->color_("heatStrong", 0xFF2F26);
    else if (look == "cooling")
      colour = this->color_("coolStrong", 0x2B78F1);
    // not circulating: `temperature_read` holds WHEN its last reading was
    // (a time, not yes / no) - that reading, dimmed
    if (!none(st.get(tv.entity, "temperature_read")))
      colour = this->color_("textSecondary", 0x9E9E9E);
    // the body's picture - the combined tile's follows the mode
    if (tv.icon != nullptr) {
      const std::string &mode = st.get(tv.entity, "mode");
      const bool spa = (mode.empty() ? st.get(tv.entity, "body") : mode) == "spa";
      const AssetId icon = spa ? (tv.big ? IMG_ICON_SPA : IMG_ICON_SPA_S) : (tv.big ? IMG_ICON_POOL : IMG_ICON_POOL_S);
      // (off: the theme's own picture for it, when it has one - like every icon)
      const lv_image_dsc_t *img = !this->icon_on_(tv, this->is_on_(tv)) ? this->rt_->image(off_art(icon)) : nullptr;
      if (img == nullptr)
        img = this->rt_->image(icon);
      if (img != nullptr && lv_image_get_src(tv.icon) != img)
        lv_image_set_src(tv.icon, img);
    }
  } else {
    temp = st.get(tv.entity, "current_temperature");
    const std::string &action = st.get(tv.entity, "hvac_action");
    status = none(action) ? st.get(tv.entity) : action;
    for (auto &c : status)
      if (c == '_')
        c = ' ';
    if (action == "heating")
      colour = this->color_("heatStrong", 0xFF2F26);
    else if (action == "cooling" || st.get(tv.entity) == "cool")
      colour = this->color_("coolStrong", 0x2B78F1);
  }
  char t[16];
  if (none(temp))
    snprintf(t, sizeof(t), "--\xC2\xB0");
  else
    snprintf(t, sizeof(t), "%ld\xC2\xB0", lroundf(atof(temp.c_str())));
  lv_label_set_text(tv.temp, t);
  lv_obj_set_style_text_color(tv.temp, lv_color_hex(colour), 0);
  // left of the roller - or, with no roller (switching), across the tile
  {
    const float k = tv.big ? 1.0f : 0.68f;
    auto px = [k](int v) { return (int) (v * k + 0.5f); };
    const bool wide = this->busy_(tv);
    const int w = wide ? (tv.big ? 198 : 164) - 2 * px(12) : (tv.big ? 92 : 94);
    lv_obj_set_width(tv.temp, w);
    lv_obj_set_width(tv.status, w);
    // broken to fit, never cut (text_fit.h)
    lv_label_set_text(tv.status, fit_lines(status, tv.big ? this->fonts_.roll : this->fonts_.roll_s, w).c_str());
  }

  if (tv.band_lo != nullptr) {
    // the band being rolled to while held, else HA's
    float lo, hi;
    const bool band = this->climate_band_(tv, tv.held_row >= 0 ? 80 - tv.held_row : -1000, lo, hi);
    for (lv_obj_t *l : {tv.band_lo, tv.band_hi}) {
      if (band)
        lv_obj_remove_flag(l, LV_OBJ_FLAG_HIDDEN);
      else
        lv_obj_add_flag(l, LV_OBJ_FLAG_HIDDEN);
    }
    if (band) {
      char b[24];
      snprintf(b, sizeof(b), "%g", lo);
      lv_label_set_text(tv.band_lo, b);
      snprintf(b, sizeof(b), "%g", hi);
      lv_label_set_text(tv.band_hi, b);
      lv_obj_align_to(tv.band_lo, tv.roller, LV_ALIGN_OUT_BOTTOM_LEFT, 0, 0);
      lv_obj_align_to(tv.band_hi, tv.roller, LV_ALIGN_OUT_BOTTOM_RIGHT, 0, 0);
    }
  }
}

// ---- the pool / spa heater button (bottom right; flame = heat, snowflake = chill)

void Board::build_heater_(TileView &tv) {
  const float k = tv.big ? 1.0f : 0.68f;
  auto px = [k](int v) { return (int) (v * k + 0.5f); };
  tv.heater = lv_obj_create(tv.box);
  lv_obj_remove_style_all(tv.heater);
  lv_obj_set_size(tv.heater, px(44), px(44));
  lv_obj_align(tv.heater, LV_ALIGN_BOTTOM_RIGHT, -px(14), -px(10));
  lv_obj_set_style_radius(tv.heater, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_bg_opa(tv.heater, LV_OPA_COVER, 0);
  lv_obj_set_style_bg_color(tv.heater, lv_color_hex(this->color_("button", 0x3A3A3A)), 0);
  lv_obj_set_style_border_width(tv.heater, 1, 0);
  lv_obj_set_style_border_color(tv.heater, lv_color_hex(this->color_("tileBorder", 0x4A4A4A)), 0);
  lv_obj_add_flag(tv.heater, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_set_ext_click_area(tv.heater, std::max(px(10), 14));  // (the 7")
  lv_obj_add_event_cb(tv.heater, &Board::on_heater_, LV_EVENT_CLICKED, &tv);
  tv.heater_glyph = lv_label_create(tv.heater);
  lv_obj_set_style_text_font(tv.heater_glyph, tv.big ? this->fonts_.glyph : this->fonts_.glyph_s, 0);
  lv_obj_center(tv.heater_glyph);
  // asked on / off and not there yet (controllers can take minutes): a
  // stopwatch in place of the flame (paint_heater_)
  tv.heater_busy = this->busy_icons_.make(tv.heater, px(26), this->color_("accent", 0x4B9EF3));
}

static bool heater_on_word(const std::string &h) { return h == "heat" || h == "heating" || h == "cool" || h == "cooling"; }

void Board::paint_heater_(TileView &tv) {
  auto &st = this->rt_->states();
  if (st.get(tv.entity, "has_heater") == "off" || st.get(tv.entity, "pool").empty()) {
    lv_obj_add_flag(tv.heater, LV_OBJ_FLAG_HIDDEN);
    return;
  }
  lv_obj_remove_flag(tv.heater, LV_OBJ_FLAG_HIDDEN);
  const std::string &h = st.get(tv.entity, "heater");
  // MIRRORED: frontend/src/room-tiles-panel.ts (water tile heater button: heater_pending) - a change here must be made there too.
  // what it looks like: the tap just made (held), else what was asked and
  // isn't there yet (heater_pending: up to 5 minutes), else HA's state
  const std::string &pending = st.get(tv.entity, "heater_pending");
  const bool on = tv.heater_held >= 0 ? tv.heater_held == 1 : !pending.empty() ? pending == "on" : heater_on_word(h);
  const bool waiting = !pending.empty() || (tv.heater_held >= 0 && (tv.heater_held == 1) != heater_on_word(h));
  BusyIcons::show(tv.heater_busy, waiting);
  if (waiting)
    lv_obj_add_flag(tv.heater_glyph, LV_OBJ_FLAG_HIDDEN);
  else
    lv_obj_remove_flag(tv.heater_glyph, LV_OBJ_FLAG_HIDDEN);
  // switching between pool and spa / offline: no taps (on_heater_) - and it
  // looks it: dimmed, like the dashboard's disabled button
  const std::string &state = st.get(tv.entity);
  const bool locked = state == "switching" || state == "offline" || state == "unavailable" || state.empty();
  lv_obj_set_style_opa(tv.heater, locked ? LV_OPA_40 : LV_OPA_COVER, 0);
  const bool cool = h == "cool" || h == "cooling" || (h != "heat" && h != "heating" && st.get(tv.entity, "heater_next") == "cool");
  lv_label_set_text(tv.heater_glyph, cool ? "\U000F0717" : "\U000F0238");  // mdi:snowflake / mdi:fire
  // on: the rollers' strong red / blue, its ring too (like the dashboard)
  const uint32_t c = !on   ? this->color_("textSecondary", 0x9E9E9E)
                     : cool ? this->color_("coolStrong", 0x2B78F1)
                            : this->color_("heatStrong", 0xFF2F26);
  lv_obj_set_style_text_color(tv.heater_glyph, lv_color_hex(c), 0);
  lv_obj_set_style_border_color(tv.heater, lv_color_hex(on ? c : this->color_("tileBorder", 0x4A4A4A)), 0);
  lv_obj_center(tv.heater_glyph);
}

void Board::on_heater_(lv_event_t *e) {
  auto *tv = static_cast<TileView *>(lv_event_get_user_data(e));
  if (tv == nullptr || tv->board == nullptr)
    return;
  Board *b = tv->board;
  const std::string &state = b->rt_->states().get(tv->entity);
  if (state.empty() || state == "unavailable" || state == "switching" || state == "offline")
    return;
  // (what it shows: a tap while one is on its way turns it the other way)
  const std::string &pending = b->rt_->states().get(tv->entity, "heater_pending");
  const bool on = tv->heater_held >= 0  ? tv->heater_held == 1
                  : !pending.empty() ? pending == "on"
                                     : heater_on_word(b->rt_->states().get(tv->entity, "heater"));
  // one tap, no confirm; off -> on uses its last mode (Room Tiles knows it)
  tv->heater_held = on ? 0 : 1;
  tv->heater_held_until = millis() + HEATER_HOLD_MS;
  b->paint_heater_(*tv);
  b->rt_->actions().call("room_tiles.pool_set_heater", tv->entity, on ? "{\"heater\":false}" : "{\"heater\":true}");
}

// ---- appliances ------------------------------------------------------------------

void Board::build_appliance_(TileView &tv) {
  const float k = tv.big ? 1.0f : 0.68f;
  auto px = [k](int v) { return (int) (v * k + 0.5f); };
  for (int i = 0; i < 2; i++) {
    auto &u = tv.units[i];
    u.half = lv_obj_create(tv.box);
    lv_obj_remove_style_all(u.half);
    lv_obj_set_size(u.half, px(174), px(100));
    lv_obj_remove_flag(u.half, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(u.half, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_flag(u.half, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_user_data(u.half, (void *) (intptr_t) i);
    lv_obj_add_event_cb(u.half, &Board::on_unit_, LV_EVENT_CLICKED, &tv);
    const int f = tv.big ? 96 : 65;
    u.frame_px = f;
    u.base = lv_image_create(u.half);
    lv_obj_set_pos(u.base, 0, px(2));
    lv_obj_remove_flag(u.base, LV_OBJ_FLAG_CLICKABLE);
    // the animation: one frame of its sheet through a frame-sized window
    u.clip = lv_obj_create(u.half);
    lv_obj_remove_style_all(u.clip);
    lv_obj_set_size(u.clip, f, f);
    lv_obj_set_pos(u.clip, 0, px(2));
    lv_obj_remove_flag(u.clip, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(u.clip, LV_OBJ_FLAG_CLICKABLE);
    u.sheet = lv_image_create(u.clip);
    lv_obj_remove_flag(u.sheet, LV_OBJ_FLAG_CLICKABLE);
    u.label = lv_label_create(u.half);
    lv_obj_set_width(u.label, px(74));
    lv_label_set_long_mode(u.label, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_style_text_font(u.label, tv.big ? this->fonts_.prefix : this->fonts_.prefix_s, 0);
    lv_obj_set_style_text_color(u.label, lv_color_hex(this->color_("textSecondary", 0x9E9E9E)), 0);
    lv_obj_set_pos(u.label, px(100), px(18));
    u.status = lv_label_create(u.half);
    lv_obj_set_width(u.status, px(74));
    lv_label_set_long_mode(u.status, LV_LABEL_LONG_MODE_WRAP);
    lv_obj_set_style_text_font(u.status, tv.big ? this->fonts_.roll : this->fonts_.roll_s, 0);
    lv_obj_set_style_text_color(u.status, lv_color_hex(this->color_("text", 0xFFFFFF)), 0);
    // (2 lines of the step + the time's: 3 px higher on 6x3 to fit them)
    lv_obj_set_pos(u.status, px(100), tv.big ? 40 : px(40) - 3);
    u.time = lv_label_create(u.half);
    lv_obj_set_style_text_font(u.time, tv.big ? this->fonts_.roll : this->fonts_.roll_s, 0);
    lv_obj_set_style_text_color(u.time, lv_color_hex(this->color_("text", 0xFFFFFF)), 0);
  }
  // no units reported: one line in the middle
  tv.status = lv_label_create(tv.box);
  lv_obj_set_style_text_font(tv.status, tv.big ? this->fonts_.roll : this->fonts_.roll_s, 0);
  lv_obj_set_style_text_color(tv.status, lv_color_hex(this->color_("textSecondary", 0x9E9E9E)), 0);
  lv_obj_center(tv.status);
}

static AssetId sheet_for(const std::string &state, bool big) {
  if (state == "washing")
    return big ? IMG_BUBBLE_WASH_96 : IMG_BUBBLE_WASH_65;
  if (state == "drying")
    return big ? IMG_SUN_DRY_96 : IMG_SUN_DRY_65;
  if (state == "done")
    return big ? IMG_CHECK_DONE_96 : IMG_CHECK_DONE_65;
  if (state == "waiting")
    return big ? IMG_WET_HOURGLASS_96 : IMG_WET_HOURGLASS_65;
  return IMG_COUNT;
}

void Board::paint_appliance_(TileView &tv) {
  const float k = tv.big ? 1.0f : 0.68f;
  auto px = [k](int v) { return (int) (v * k + 0.5f); };
  // units "label|state|status|base|time;..." (at most two - the panels' format)
  const std::string &tile = this->rt_->states().get(tv.entity, "tile");
  std::string parts[2];
  int n = 0;
  size_t start = 0;
  while (n < 2 && start <= tile.size() && !tile.empty()) {
    const size_t end = tile.find(';', start);
    const std::string u = tile.substr(start, end == std::string::npos ? std::string::npos : end - start);
    if (u.find('|') != std::string::npos)
      parts[n++] = u;
    if (end == std::string::npos)
      break;
    start = end + 1;
  }
  if (n == 0) {
    lv_label_set_text(tv.status, this->rt_->t("appliance.no_data").c_str());
    lv_obj_remove_flag(tv.status, LV_OBJ_FLAG_HIDDEN);
  } else {
    lv_obj_add_flag(tv.status, LV_OBJ_FLAG_HIDDEN);
  }
  for (int i = 0; i < 2; i++) {
    auto &u = tv.units[i];
    if (i >= n) {
      lv_obj_add_flag(u.half, LV_OBJ_FLAG_HIDDEN);
      u.animating = false;
      continue;
    }
    lv_obj_remove_flag(u.half, LV_OBJ_FLAG_HIDDEN);
    // one unit: exactly a half, in the middle of the tile's lower part
    // two units: stacked so the lower one's picture ends on the tile's inside
    // edge (5x2: 56 + 98 + 2 + 96 = 252; 6x3: 37 + 67 + 1 + 65 = 170 of 171)
    const int top = tv.big ? 56 : 37, step = tv.big ? 98 : 67;
    lv_obj_align(u.half, LV_ALIGN_TOP_MID, 0, n == 1 ? px(58) + px(50) : top + i * step);
    const std::string &p = parts[i];
    const std::string label = field_(p, 0), state = field_(p, 1), status = field_(p, 2), base = field_(p, 3);
    std::string time = field_(p, 4);
    if (time == "unknown" || time == "unavailable" || time == "none" || time == "None" || time == "0")
      time.clear();
    const AssetId still = base == "plate"   ? (tv.big ? IMG_PLATE_KNIFE_FORK_96 : IMG_PLATE_KNIFE_FORK_65)
                          : base == "shirt" ? (tv.big ? IMG_SHIRT_SOCKS_96 : IMG_SHIRT_SOCKS_65)
                                            : IMG_COUNT;
    const lv_image_dsc_t *still_img = still < IMG_COUNT ? this->rt_->image(still) : nullptr;
    if (still_img != nullptr) {
      lv_image_set_src(u.base, still_img);
      lv_obj_remove_flag(u.base, LV_OBJ_FLAG_HIDDEN);
    } else {
      lv_obj_add_flag(u.base, LV_OBJ_FLAG_HIDDEN);
    }
    const AssetId sheet = sheet_for(state, tv.big);
    const lv_image_dsc_t *sheet_img = sheet < IMG_COUNT ? this->rt_->image(sheet) : nullptr;
    if (sheet_img != nullptr) {
      lv_image_set_src(u.sheet, sheet_img);
      lv_obj_remove_flag(u.clip, LV_OBJ_FLAG_HIDDEN);
      u.frame_px = sheet_img->header.h / SHEET_ROWS;
      u.animating = true;
    } else {
      lv_obj_add_flag(u.clip, LV_OBJ_FLAG_HIDDEN);
      u.animating = false;
    }
    lv_label_set_text(u.label, label.c_str());
    // the step broken to its column (text_fit.h), the time left on a line of
    // its own under it - never split
    const lv_font_t *font = tv.big ? this->fonts_.roll : this->fonts_.roll_s;
    lv_label_set_text(u.status, fit_lines(status, font, px(74)).c_str());
    lv_label_set_text(u.time, time.c_str());
    if (time.empty())
      lv_obj_add_flag(u.time, LV_OBJ_FLAG_HIDDEN);
    else
      lv_obj_remove_flag(u.time, LV_OBJ_FLAG_HIDDEN);
    lv_obj_align_to(u.time, u.status, LV_ALIGN_OUT_BOTTOM_LEFT, 0, 0);
  }
}

void Board::on_unit_(lv_event_t *e) {
  auto *tv = static_cast<TileView *>(lv_event_get_user_data(e));
  auto *half = static_cast<lv_obj_t *>(lv_event_get_current_target(e));
  if (tv == nullptr || tv->board == nullptr)
    return;
  // a finished unit (done / waiting): emptied - Room Tiles checks which and if
  const int i = (int) (intptr_t) lv_obj_get_user_data(half);
  tv->board->rt_->actions().call("room_tiles.appliance_tap", tv->entity, "{\"index\":" + std::to_string(i) + "}");
}

void Board::animate_(uint32_t now) {
  if ((int32_t) (now - this->anim_at_) < (int32_t) FRAME_MS)
    return;
  this->anim_at_ = now;
  this->anim_frame_ = (this->anim_frame_ + 1) % (SHEET_COLS * SHEET_ROWS);
  const int col = this->anim_frame_ % SHEET_COLS, row = this->anim_frame_ / SHEET_COLS;
  auto step = [&](TileView &tv) {
    if (tv.kind != "appliance")
      return;
    for (auto &u : tv.units)
      if (u.animating)
        lv_obj_set_pos(u.sheet, -col * u.frame_px, -row * u.frame_px);
  };
  for (auto &tv : this->tiles_)
    step(tv);
  for (auto &tv : this->popups_)
    step(tv);
}

// ---- vacuum + map ---------------------------------------------------------------

// MIRRORED: frontend/src/room-tiles-panel.ts (the vacuum tile with a room queue) - a change here must be made there too.
// A vacuum with a room queue: its map, small (the queue's rooms in their
// colours, no names) under its name, what it's doing beside its icon; else
// what it's doing in the middle. A tap: the queue (the map in queue mode).
void Board::build_vacuum_(TileView &tv) {
  lv_obj_add_flag(tv.box, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_event_cb(tv.box, &Board::on_tap_, LV_EVENT_CLICKED, &tv);
  const float k = tv.big ? 1.0f : 0.68f;
  auto px = [k](int v) { return (int) (v * k + 0.5f); };
  tv.status = lv_label_create(tv.box);
  lv_obj_set_size(tv.status, (tv.big ? 198 : 164) - 2 * px(12), px(40));
  lv_label_set_long_mode(tv.status, LV_LABEL_LONG_MODE_WRAP);
  lv_obj_set_style_text_align(tv.status, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_style_text_font(tv.status, tv.big ? this->fonts_.roll : this->fonts_.roll_s, 0);
  lv_obj_align(tv.status, LV_ALIGN_TOP_MID, 0, px(58));
  // its robot (a queue): its sensor's queue followed too (the tile may be the vacuum's)
  const RobotSpec *r = this->model_ != nullptr ? this->model_->robot_for(tv.entity) : nullptr;
  if (r == nullptr || this->model_->maps.empty())
    return;
  tv.robot_sensor = r->sensor;
  auto &st = this->rt_->states();
  st.watch(r->sensor);
  for (const char *a : {"queue", "current", "tile"})
    st.watch(r->sensor, a);
  tv.vmap_img = lv_image_create(tv.box);
  lv_obj_add_flag(tv.vmap_img, LV_OBJ_FLAG_HIDDEN);
  lv_obj_remove_flag(tv.vmap_img, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_set_pos(tv.vmap_img, px(8), px(44));
}

Board::TileMap::~TileMap() {
  if (this->buf != nullptr) {
    lv_image_cache_drop(&this->dsc);
    heap_caps_free(this->buf);
  }
}

// The tile's map for the queue as it is now: drawn again only when the map,
// the queue or the tile's size changed. False: nothing to show (no map with
// a room it cleans).
bool Board::draw_vacuum_map_(TileView &tv) {
  if (tv.vmap_img == nullptr || this->model_ == nullptr)
    return false;
  const RobotSpec *r = this->model_->robot_for(tv.entity);
  if (r == nullptr)
    return false;
  const QueueState q = read_queue(this->rt_, *r);
  const MapSpec *m = queue_map(*this->model_, *r, q);
  if (m == nullptr)
    return false;
  const float kk = tv.big ? 1.0f : 0.68f;
  auto px = [kk](int v) { return (int) (v * kk + 0.5f); };
  lv_obj_update_layout(tv.box);
  const int bw = lv_obj_get_content_width(tv.box), bh = lv_obj_get_content_height(tv.box);
  // (the web tile's box: 8 in from the sides, under the name, over the status line)
  const int w = std::max(16, bw - 2 * px(8));
  const int h = std::max(16, std::min(px(138), bh - px(44) - px(14 + 44) - px(4)));
  const uint32_t bg = this->color_("tile", 0x1E1E1E);
  uint32_t sig = 0;
  auto style = queue_style(this->rt_, *m, *r, q, bg, &sig);
  sig = (sig * 16777619u) ^ m->sig ^ ((uint32_t) w << 20) ^ ((uint32_t) h << 8) ^ bg;
  if (tv.vmap && tv.vmap->sig == sig && tv.vmap->w == w && tv.vmap->h == h)
    return true;
  PsramScope psram;  // (the map's index: PSRAM)
  const int S = std::max(w, h);  // (draw_map_tile draws a square)
  if (!tv.vmap || tv.vmap->stride_px != S) {
    auto tm = std::make_shared<TileMap>();
    tm->buf = static_cast<uint16_t *>(heap_caps_malloc((size_t) S * S * 2, MALLOC_CAP_SPIRAM));
    if (tm->buf == nullptr)
      return false;
    tm->stride_px = S;
    if (tv.vmap)
      lv_image_set_src(tv.vmap_img, nullptr);  // (the old picture goes with it)
    tv.vmap = tm;
  }
  TileMap &t = *tv.vmap;
  t.w = w;
  t.h = h;
  t.sig = sig;
  const uint32_t started = micros();
  MapColors c;
  c.bg = bg;  // (no ground: the tile's own colour around the plan, as on the dashboard)
  c.floor = this->color_("mapFloor", c.floor);
  c.wall = this->color_("mapWall", c.wall);
  c.window = this->color_("mapWindow", c.window);
  c.water = this->color_("mapWater", c.water);
  c.grass = this->color_("mapGrass", c.grass);
  c.deck = this->color_("mapDeck", c.deck);
  c.paving = this->color_("mapPaving", c.paving);
  const float mw = std::max(1.0f, m->bounds[2] - m->bounds[0]), mh = std::max(1.0f, m->bounds[3] - m->bounds[1]);
  const float k = std::min(w / mw, h / mh);
  // centered in the box (the tile's pixel (0, 0) = the plan's corner)
  const int ox = -(int) lroundf((w - mw * k) / 2), oy = -(int) lroundf((h - mh * k) / 2);
  MapIndex index(*m);
  draw_map_tile(*m, index, c, k, ox, oy, t.buf, S, style.get());
  lv_image_cache_drop(&t.dsc);
  t.dsc = lv_image_dsc_t{};
  t.dsc.header.magic = LV_IMAGE_HEADER_MAGIC;
  t.dsc.header.cf = LV_COLOR_FORMAT_RGB565;
  t.dsc.header.w = w;
  t.dsc.header.h = h;
  t.dsc.header.stride = S * 2;
  t.dsc.data_size = (uint32_t) S * h * 2;
  t.dsc.data = reinterpret_cast<const uint8_t *>(t.buf);
  lv_image_set_src(tv.vmap_img, &t.dsc);
  lv_obj_invalidate(tv.vmap_img);
  ESP_LOGD("room_tiles.board", "Vacuum tile map %dx%d drawn in %" PRIu32 " us", w, h, micros() - started);
  return true;
}

void Board::paint_vacuum_(TileView &tv) {
  // MIRRORED: frontend/src/rules.ts vacuumStatus - a change here must be made there too.
  // "class|text" (Room Tiles' robot sensor) or the vacuum's own state (rules.ts vacuumStatus)
  auto &st = this->rt_->states();
  const std::string &tile = st.get(tv.entity, "tile");
  std::string cls = st.get(tv.entity), text = cls;
  if (tile.find('|') != std::string::npos) {
    cls = field_(tile, 0);
    text = field_(tile, 1).empty() ? cls : field_(tile, 1);
  }
  const uint32_t c = cls == "cleaning"    ? this->color_("vacCleaning", 0x4CAF50)
                     : cls == "paused"    ? this->color_("vacPaused", 0xFFB300)
                     : cls == "attention" ? this->color_("vacAttention", 0xFF6D00)
                     : cls == "error"     ? this->color_("vacError", 0xF44336)
                                          : this->color_("textSecondary", 0x9E9E9E);
  const float k = tv.big ? 1.0f : 0.68f;
  auto px = [k](int v) { return (int) (v * k + 0.5f); };
  const bool map = this->draw_vacuum_map_(tv);
  if (tv.vmap_img != nullptr) {
    if (map)
      lv_obj_remove_flag(tv.vmap_img, LV_OBJ_FLAG_HIDDEN);
    else
      lv_obj_add_flag(tv.vmap_img, LV_OBJ_FLAG_HIDDEN);
  }
  const lv_font_t *font = tv.big ? this->fonts_.roll : this->fonts_.roll_s;
  if (map) {
    // beside the icon, under the map (the web tile's .vac-line: 70 in, 14 up, 44 high)
    const int w = (tv.big ? 198 : 164) - px(70) - px(8);
    lv_obj_set_width(tv.status, w);
    lv_obj_set_height(tv.status, LV_SIZE_CONTENT);
    lv_obj_set_style_text_align(tv.status, LV_TEXT_ALIGN_LEFT, 0);
    lv_label_set_text(tv.status, fit_lines(text, font, w).c_str());
    lv_obj_update_layout(tv.status);
    const int lh = std::min(px(44), (int) lv_obj_get_height(tv.status));
    lv_obj_align(tv.status, LV_ALIGN_BOTTOM_LEFT, px(70), -px(14) - (px(44) - lh) / 2);
  } else {
    const int w = (tv.big ? 198 : 164) - 2 * px(12);
    lv_obj_set_size(tv.status, w, px(40));
    lv_obj_set_style_text_align(tv.status, LV_TEXT_ALIGN_CENTER, 0);
    lv_label_set_text(tv.status, fit_lines(text, font, w).c_str());
    lv_obj_align(tv.status, LV_ALIGN_TOP_MID, 0, px(58));
  }
  lv_obj_set_style_text_color(tv.status, lv_color_hex(c), 0);
}

void Board::build_map_(TileView &tv) {
  // the floor-plan glyph in the middle; a tap anywhere on the tile opens the map
  lv_obj_add_flag(tv.box, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_event_cb(tv.box, &Board::on_tap_, LV_EVENT_CLICKED, &tv);
  // MIRRORED: frontend/src/theme.ts BUTTON_ART (tile_map) - a change here must be made there too.
  if (const lv_image_dsc_t *art = this->rt_->image(tv.big ? IMG_TILE_MAP : IMG_TILE_MAP_S)) {  // (the theme's own)
    lv_obj_t *img = lv_image_create(tv.box);
    lv_image_set_src(img, art);
    lv_obj_align(img, LV_ALIGN_CENTER, 0, (int) (14 * (tv.big ? 1.0f : 0.68f)));
    return;
  }
  lv_obj_t *g = lv_label_create(tv.box);
  lv_label_set_text(g, "\U000F0821");  // mdi:floor-plan
  lv_obj_set_style_text_font(g, tv.big ? this->fonts_.play : this->fonts_.play_s, 0);
  lv_obj_set_style_text_color(g, lv_color_hex(this->color_("accent", 0x4B9EF3)), 0);
  lv_obj_align(g, LV_ALIGN_CENTER, 0, (int) (12 * (tv.big ? 1.0f : 0.68f)));
}

}  // namespace esphome::room_tiles
