// Room Tiles panel: the round panel's board (480x480; docs/TODO.md "Round
// panel"). The area's tiles - its 5x2 layout, in order, empty slots left out -
// in one horizontal strip at the 5x2 tile size (198 x 254: it fits the
// circle). The strip snaps every half tile: one tile centered, or two halves
// split down the middle. The area's name on top (a tap: the area list), page
// dots under the strip. The knob: a click = a snap step; its press = a tap on
// the centered tile.
#include "board.h"

#include <algorithm>

#include "esphome/core/log.h"
#include "room_tiles.h"

namespace esphome::room_tiles {

static const char *const TAG = "room_tiles.strip";

static constexpr int ROUND = 480;               // the screen (a circle)
static constexpr int TILE_W = 198, TILE_H = 254;  // (the 5x2 tile)
static constexpr int STRIP_GAP = 16;
static constexpr int STRIP_Y = 108;              // the strip's top: centered, a little up
static constexpr int STRIP_PAD = (ROUND - TILE_W) / 2;  // (the first / last tile can center)
static constexpr int DOTS_Y = STRIP_Y + TILE_H + 22;
static constexpr int DOT = 8, DOT_GAP = 8;

int Board::strip_step_() const { return (TILE_W + STRIP_GAP) / 2; }

// snap points: 0 = tile 0 centered, 1 = tiles 0|1 split, 2 = tile 1 centered...
int Board::strip_points_() const { return this->tiles_.empty() ? 0 : 2 * (int) this->tiles_.size() - 1; }

int Board::strip_point_() const {
  if (this->strip_cont_ == nullptr)
    return 0;
  const int x = lv_obj_get_scroll_x(this->strip_cont_);
  const int step = this->strip_step_();
  return std::clamp((x + step / 2) / step, 0, std::max(0, this->strip_points_() - 1));
}

void Board::strip_go_(int point, bool anim) {
  if (this->strip_cont_ == nullptr)
    return;
  point = std::clamp(point, 0, std::max(0, this->strip_points_() - 1));
  // (an odd point lands between two tiles: half a step past the tile)
  const int x = (point / 2) * (TILE_W + STRIP_GAP) + (point % 2) * this->strip_step_();
  lv_obj_scroll_to_x(this->strip_cont_, x, anim ? LV_ANIM_ON : LV_ANIM_OFF);
  this->strip_shown_ = point;
  this->paint_dots_();
}

// the dots: one per tile, lit for the centered one (both halves at a split)
void Board::paint_dots_() {
  const int p = this->strip_shown_ < 0 ? 0 : this->strip_shown_;
  const uint32_t on = this->color_("accent", 0x4B9EF3), off = this->color_("textSecondary", 0x9E9E9E);
  for (int i = 0; i < (int) this->strip_dots_.size(); i++) {
    const bool lit = i == p / 2 || (p % 2 == 1 && i == p / 2 + 1);
    lv_obj_set_style_bg_color(this->strip_dots_[i], lv_color_hex(lit ? on : off), 0);
    lv_obj_set_style_bg_opa(this->strip_dots_[i], lit ? LV_OPA_COVER : LV_OPA_50, 0);
  }
}

// while it moves: the dots follow
void Board::on_strip_scroll_(lv_event_t *e) {
  auto *self = static_cast<Board *>(lv_event_get_user_data(e));
  const int p = self->strip_point_();
  if (p != self->strip_shown_) {
    self->strip_shown_ = p;
    self->paint_dots_();
  }
}

// let go (or a throw ran out): to the nearest snap point
void Board::on_strip_scroll_end_(lv_event_t *e) {
  auto *self = static_cast<Board *>(lv_event_get_user_data(e));
  if (self->strip_cont_ == nullptr)
    return;
  const int p = self->strip_point_();
  const int want = (p / 2) * (TILE_W + STRIP_GAP) + (p % 2) * self->strip_step_();
  if (std::abs(lv_obj_get_scroll_x(self->strip_cont_) - want) > 1)
    self->strip_go_(p, true);  // (its own scroll end then finds it there)
  else
    self->rt_->set_strip_point(self->area_, p);  // (settled: this room opens here next time)
}

void Board::build_strip_(const PanelModel &model, const AreaSpec *area) {
  const uint32_t text = this->color_("text", 0xFFFFFF);
  // the area's name, top center: a tap opens the area list
  lv_obj_t *name = dropdown_title(this->root_, area ? (area->short_name.empty() ? area->name : area->short_name) : "",
                                  this->fonts_, text, 300);
  lv_obj_set_style_pad_ver(name, 6, 0);
  lv_obj_update_layout(name);
  lv_obj_set_pos(name, (ROUND - lv_obj_get_width(name)) / 2, 34);
  lv_obj_set_ext_click_area(name, 12);
  lv_obj_add_event_cb(
      name, [](lv_event_t *e) { static_cast<Board *>(lv_event_get_user_data(e))->open_strip_areas_(); },
      LV_EVENT_CLICKED, this);
  if (area == nullptr)
    return;

  // the strip: scrolls sideways only (a tile's own up / down drags stay its own)
  lv_obj_t *cont = lv_obj_create(this->root_);
  lv_obj_remove_style_all(cont);
  lv_obj_set_size(cont, ROUND, TILE_H);
  lv_obj_set_pos(cont, 0, STRIP_Y);
  lv_obj_set_scroll_dir(cont, LV_DIR_HOR);
  lv_obj_set_scrollbar_mode(cont, LV_SCROLLBAR_MODE_OFF);
  lv_obj_set_style_pad_right(cont, STRIP_PAD, 0);  // (the last tile can center)
  lv_obj_add_event_cb(cont, &Board::on_strip_scroll_, LV_EVENT_SCROLL, this);
  lv_obj_add_event_cb(cont, &Board::on_strip_scroll_end_, LV_EVENT_SCROLL_END, this);
  this->strip_cont_ = cont;

  // the area's 5x2 tiles in order, its empty slots left out
  const auto &specs = area->tiles(true);
  this->tiles_.reserve(specs.size());  // (event user data: no reallocation after this)
  for (size_t i = 0; i < specs.size(); i++) {
    if (specs[i].kind.empty() || specs[i].kind == "blank")
      continue;
    this->tiles_.emplace_back();
    TileView &tv = this->tiles_.back();
    tv.board = this;
    tv.kind = specs[i].kind;
    tv.entity = specs[i].entity;
    tv.big = true;
    tv.slot = (int) i;
    tv.icon_hint = model.icon(tv.entity);
    const int n = (int) this->tiles_.size() - 1;
    this->build_tile_(tv, STRIP_PAD + n * (TILE_W + STRIP_GAP), 0, TILE_W, TILE_H, cont);
    tv.name_text = specs[i].name.empty() ? model.short_name(tv.entity) : specs[i].name;
    if (tv.name != nullptr)
      lv_label_set_text(tv.name, tv.name_text.c_str());
    this->paint_(tv);
  }

  // the dots
  const int n = (int) this->tiles_.size();
  const int dots_w = n * DOT + std::max(0, n - 1) * DOT_GAP;
  for (int i = 0; i < n; i++) {
    lv_obj_t *d = lv_obj_create(this->root_);
    lv_obj_remove_style_all(d);
    lv_obj_set_size(d, DOT, DOT);
    lv_obj_set_style_radius(d, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_pos(d, (ROUND - dots_w) / 2 + i * (DOT + DOT_GAP), DOTS_Y);
    lv_obj_remove_flag(d, LV_OBJ_FLAG_CLICKABLE);
    this->strip_dots_.push_back(d);
  }
  // settings: the gear, bottom center (the theme's gear picture)
  if (const lv_image_dsc_t *gear = this->rt_->bar_gear()) {
    lv_obj_t *g = bar_button(this->root_, this->color_("button", 0x333333), this->color_("tileBorder", 0x4A4A4A), 10);
    lv_obj_set_pos(g, (ROUND - BAR_BTN_W) / 2, DOTS_Y + 22);
    lv_obj_add_event_cb(
        g, [](lv_event_t *e) { static_cast<Board *>(lv_event_get_user_data(e))->open_strip_settings_(); },
        LV_EVENT_CLICKED, this);
    lv_obj_t *img = lv_image_create(g);
    lv_image_set_src(img, gear);
    lv_obj_center(img);
  }
  lv_obj_update_layout(cont);
  this->strip_go_(this->rt_->strip_point(area->id), false);  // (where this room was left)
  ESP_LOGD(TAG, "Strip: %d tiles", n);
}

bool Board::visible_animating() const {
  auto anim = [](const TileView &tv) { return tv.units[0].animating || tv.units[1].animating; };
  if (!this->strip_)
    return std::any_of(this->tiles_.begin(), this->tiles_.end(), anim);
  const int p = this->strip_point_();
  const int i = p / 2;
  return (i < (int) this->tiles_.size() && anim(this->tiles_[i])) ||
         (p % 2 == 1 && i + 1 < (int) this->tiles_.size() && anim(this->tiles_[i + 1]));
}

bool Board::knob_turn(int clicks) {
  if (!this->strip_ || this->strip_cont_ == nullptr || this->scrim_ != nullptr)
    return false;
  this->strip_go_(this->strip_point_() + clicks, true);
  return true;
}

void Board::knob_press() {
  if (!this->strip_ || this->strip_cont_ == nullptr || this->scrim_ != nullptr)
    return;
  const int p = this->strip_point_();
  if (p % 2 == 1 || p / 2 >= (int) this->tiles_.size())
    return;  // (a split: no tile in the middle)
  TileView &tv = this->tiles_[p / 2];
  if (tv.kind == "scene" || tv.kind == "script")  // (board.cpp is_run)
    this->run_(tv);
  else
    this->toggle_(tv);
}

// A round page over everything (the area list, settings): the page's
// colour, a title on top, a column that scrolls in the middle; a tap beside
// the column closes it. Returns the column.
lv_obj_t *Board::strip_page_(const std::string &title) {
  this->close_dialog_();
  this->scrim_ = lv_obj_create(lv_layer_top());
  lv_obj_remove_style_all(this->scrim_);
  lv_obj_set_size(this->scrim_, ROUND, ROUND);
  lv_obj_set_style_bg_color(this->scrim_, lv_color_hex(this->color_("page", 0x000000)), 0);
  lv_obj_set_style_bg_opa(this->scrim_, LV_OPA_COVER, 0);
  lv_obj_add_flag(this->scrim_, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_event_cb(
      this->scrim_,
      [](lv_event_t *e) {
        if (lv_event_get_target(e) == lv_event_get_current_target(e))
          static_cast<Board *>(lv_event_get_user_data(e))->close_dialog_();
      },
      LV_EVENT_CLICKED, this);
  if (!title.empty()) {
    lv_obj_t *t = lv_label_create(this->scrim_);
    lv_label_set_text(t, title.c_str());
    lv_obj_set_style_text_font(t, this->fonts_.bar, 0);
    lv_obj_set_style_text_color(t, lv_color_hex(this->color_("text", 0xFFFFFF)), 0);
    lv_obj_align(t, LV_ALIGN_TOP_MID, 0, 40);
  }
  lv_obj_t *list = lv_obj_create(this->scrim_);
  lv_obj_remove_style_all(list);
  lv_obj_set_size(list, 300, 330);
  lv_obj_align(list, LV_ALIGN_CENTER, 0, 20);
  lv_obj_set_scroll_dir(list, LV_DIR_VER);
  lv_obj_set_scrollbar_mode(list, LV_SCROLLBAR_MODE_OFF);
  return list;
}

// the area list: one column (a circle has no room for a grid); a tap picks
void Board::open_strip_areas_() {
  if (this->model_ == nullptr)
    return;
  const PanelModel &m = *this->model_;
  lv_obj_t *list = this->strip_page_(this->rt_->t("areas.title"));
  const uint32_t text = this->color_("text", 0xFFFFFF), on_accent = this->color_("onAccent", 0xFFFFFF);
  int y = 0;
  for (auto &a : m.areas) {
    const bool current = a.id == this->area_;
    lv_obj_t *b = lv_obj_create(list);
    lv_obj_remove_style_all(b);
    lv_obj_set_size(b, 300, 56);
    lv_obj_set_pos(b, 0, y);
    lv_obj_set_style_radius(b, 10, 0);
    lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(b, lv_color_hex(current ? this->color_("accent", 0x4B9EF3) : this->color_("button", 0x333333)), 0);
    lv_obj_add_flag(b, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_flag(b, LV_OBJ_FLAG_SCROLL_CHAIN_VER);
    lv_obj_set_user_data(b, (void *) &a);
    lv_obj_add_event_cb(
        b,
        [](lv_event_t *e) {
          auto *self = static_cast<Board *>(lv_event_get_user_data(e));
          auto *area = static_cast<const AreaSpec *>(lv_obj_get_user_data(lv_event_get_current_target_obj(e)));
          static std::string chosen;
          chosen = area->id;
          self->close_dialog_();
          lv_async_call([](void *p) { static_cast<Board *>(p)->rt_->choose_area(chosen); }, self);
        },
        LV_EVENT_CLICKED, this);
    lv_obj_t *l = lv_label_create(b);
    lv_label_set_text(l, (a.short_name.empty() ? a.name : a.short_name).c_str());
    lv_label_set_long_mode(l, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_width(l, 270);
    lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_font(l, this->fonts_.name, 0);
    lv_obj_set_style_text_color(l, lv_color_hex(current ? on_accent : text), 0);
    lv_obj_center(l);
    y += 64;
  }
}

// Settings (round): brightness, the screen's sleep, the theme - as on the
// wall panels' menu, one column. (Language, restart: the dashboard.)
void Board::open_strip_settings_() {
  if (this->model_ == nullptr)
    return;
  const PanelModel &m = *this->model_;
  lv_obj_t *list = this->strip_page_(this->rt_->t("common.settings"));
  const uint32_t text = this->color_("text", 0xFFFFFF), dim = this->color_("textSecondary", 0x9E9E9E);
  const uint32_t accent = this->color_("accent", 0x4B9EF3), on_accent = this->color_("onAccent", 0xFFFFFF);
  int y = 0;
  auto slider = [&](const std::string &name, int lo, int hi, int value, lv_event_cb_t cb) {
    lv_obj_t *n = lv_label_create(list);
    lv_label_set_text(n, name.c_str());
    lv_obj_set_style_text_font(n, this->fonts_.name, 0);
    lv_obj_set_style_text_color(n, lv_color_hex(text), 0);
    lv_obj_set_pos(n, 6, y);
    lv_obj_t *v = lv_label_create(list);
    lv_label_set_text(v, "");
    lv_obj_set_style_text_font(v, this->fonts_.name, 0);
    lv_obj_set_style_text_color(v, lv_color_hex(dim), 0);
    lv_obj_align(v, LV_ALIGN_TOP_RIGHT, -6, y);
    lv_obj_t *sl = lv_slider_create(list);
    lv_obj_remove_style_all(sl);
    lv_obj_set_size(sl, 260, 10);
    lv_obj_set_pos(sl, 20, y + 42);
    lv_slider_set_range(sl, lo, hi);
    lv_slider_set_value(sl, value, LV_ANIM_OFF);
    lv_obj_set_style_radius(sl, 5, 0);
    lv_obj_set_style_bg_opa(sl, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(sl, lv_color_hex(this->color_("button", 0x3A3A3A)), 0);
    lv_obj_set_style_radius(sl, 5, LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(sl, LV_OPA_COVER, LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(sl, lv_color_hex(accent), LV_PART_INDICATOR);
    lv_obj_set_style_radius(sl, LV_RADIUS_CIRCLE, LV_PART_KNOB);
    lv_obj_set_style_bg_opa(sl, LV_OPA_COVER, LV_PART_KNOB);
    lv_obj_set_style_bg_color(sl, lv_color_hex(0xFFFFFF), LV_PART_KNOB);
    lv_obj_set_style_pad_all(sl, 9, LV_PART_KNOB);
    lv_obj_set_ext_click_area(sl, 20);
    lv_obj_set_user_data(sl, v);
    lv_obj_add_event_cb(sl, cb, LV_EVENT_VALUE_CHANGED, this);
    lv_obj_add_event_cb(sl, cb, LV_EVENT_RELEASED, this);
    lv_obj_send_event(sl, LV_EVENT_VALUE_CHANGED, nullptr);
    y += 84;
  };
  // MIRRORED: board_edit.cpp open_settings_ (the sliders: brightness 10-100 % in 5s, sleep 0-90 s in 5s) - a change here must be made there too.
  slider(this->rt_->t("panel.brightness"), 2, 20, this->rt_->brightness() / 5, [](lv_event_t *e) {
    auto *self = static_cast<Board *>(lv_event_get_user_data(e));
    lv_obj_t *sl = lv_event_get_current_target_obj(e);
    const int pct = lv_slider_get_value(sl) * 5;
    lv_label_set_text(static_cast<lv_obj_t *>(lv_obj_get_user_data(sl)), (std::to_string(pct) + " %").c_str());
    self->rt_->set_brightness(pct, lv_event_get_code(e) == LV_EVENT_RELEASED);
  });
  slider(this->rt_->t("panel.sleep"), 0, 18, this->rt_->sleep_seconds() / 5, [](lv_event_t *e) {
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
  // when idle: the screen off / a clock, and the animations' switch
  // MIRRORED: board_edit.cpp open_settings_ / open_idle_list_ - a change here must be made there too.
  {
    lv_obj_t *h = lv_label_create(list);
    lv_label_set_text(h, this->rt_->t("panel.idle").c_str());
    lv_obj_set_style_text_font(h, this->fonts_.name, 0);
    lv_obj_set_style_text_color(h, lv_color_hex(text), 0);
    lv_obj_set_pos(h, 6, y);
    y += 36;
    static const char *const KEYS[] = {"panel.idle_off", "panel.idle_digital", "panel.idle_analog", "panel.idle_theme"};
    for (int i = 0; i < 4; i++) {
      const bool on = i == this->rt_->idle_mode();
      lv_obj_t *b = lv_obj_create(list);
      lv_obj_remove_style_all(b);
      lv_obj_set_size(b, 300, 52);
      lv_obj_set_pos(b, 0, y);
      lv_obj_set_style_radius(b, 10, 0);
      lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
      lv_obj_set_style_bg_color(b, lv_color_hex(on ? accent : this->color_("button", 0x333333)), 0);
      lv_obj_add_flag(b, LV_OBJ_FLAG_CLICKABLE);
      lv_obj_add_flag(b, LV_OBJ_FLAG_SCROLL_CHAIN_VER);
      lv_obj_set_user_data(b, (void *) (intptr_t) i);
      lv_obj_add_event_cb(
          b,
          [](lv_event_t *e) {
            auto *self = static_cast<Board *>(lv_event_get_user_data(e));
            const int k = (int) (intptr_t) lv_obj_get_user_data(lv_event_get_current_target_obj(e));
            self->rt_->set_idle(k, self->rt_->idle_anim_keep(), self->rt_->idle_seconds(), true);
            // (drawn again - at the same place: never back to the top)
            self->strip_settings_y_ = lv_obj_get_scroll_y(lv_obj_get_parent(lv_event_get_current_target_obj(e)));
            lv_async_call([](void *p) { static_cast<Board *>(p)->open_strip_settings_(); }, self);
          },
          LV_EVENT_CLICKED, this);
      lv_obj_t *l = lv_label_create(b);
      lv_label_set_text(l, this->rt_->t(KEYS[i]).c_str());
      lv_obj_set_style_text_font(l, this->fonts_.name, 0);
      lv_obj_set_style_text_color(l, lv_color_hex(on ? on_accent : text), 0);
      lv_obj_center(l);
      y += 60;
    }
    // the switches: second hand, animations, 24-hour clock
    // MIRRORED: board_edit.cpp open_settings_ (the 24-hour clock) - a change here must be made there too.
    static const char *const SWITCHES[] = {"panel.idle_seconds", "panel.idle_anim", "panel.clock_24h"};
    for (int t = 0; t < 3; t++) {
      lv_obj_t *b = lv_obj_create(list);
      lv_obj_remove_style_all(b);
      lv_obj_set_size(b, 300, 52);
      lv_obj_set_pos(b, 0, y);
      lv_obj_set_style_radius(b, 10, 0);
      lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
      lv_obj_set_style_bg_color(b, lv_color_hex(this->color_("button", 0x333333)), 0);
      lv_obj_add_flag(b, LV_OBJ_FLAG_CLICKABLE);
      lv_obj_add_flag(b, LV_OBJ_FLAG_SCROLL_CHAIN_VER);
      lv_obj_t *w = lv_label_create(b);
      lv_label_set_text(w, this->rt_->t(SWITCHES[t]).c_str());
      lv_label_set_long_mode(w, LV_LABEL_LONG_MODE_WRAP);
      lv_obj_set_width(w, 210);
      lv_obj_set_style_text_font(w, this->fonts_.prefix, 0);
      lv_obj_set_style_text_color(w, lv_color_hex(text), 0);
      lv_obj_align(w, LV_ALIGN_LEFT_MID, 14, 0);
      const bool v = t == 0 ? this->rt_->idle_seconds() : t == 1 ? this->rt_->idle_anim_keep() : !this->rt_->hours12();
      lv_obj_t *st = lv_label_create(b);
      lv_label_set_text(st, this->rt_->t(v ? "common.on" : "common.off").c_str());
      lv_obj_set_style_text_font(st, this->fonts_.name, 0);
      lv_obj_set_style_text_color(st, lv_color_hex(accent), 0);
      lv_obj_align(st, LV_ALIGN_RIGHT_MID, -14, 0);
      lv_obj_set_user_data(b, st);
      lv_obj_add_event_cb(
          b,
          t == 0 ? (lv_event_cb_t) [](lv_event_t *e) {
            auto *r = static_cast<Board *>(lv_event_get_user_data(e))->rt_;
            r->set_idle(r->idle_mode(), r->idle_anim_keep(), !r->idle_seconds(), true);
            lv_label_set_text(static_cast<lv_obj_t *>(lv_obj_get_user_data(lv_event_get_current_target_obj(e))),
                              r->t(r->idle_seconds() ? "common.on" : "common.off").c_str());
          }
          : t == 2 ? (lv_event_cb_t) [](lv_event_t *e) {
            auto *r = static_cast<Board *>(lv_event_get_user_data(e))->rt_;
            r->set_hours24(r->hours12());
            lv_label_set_text(static_cast<lv_obj_t *>(lv_obj_get_user_data(lv_event_get_current_target_obj(e))),
                              r->t(r->hours12() ? "common.off" : "common.on").c_str());
          }
                 : (lv_event_cb_t) [](lv_event_t *e) {
            auto *r = static_cast<Board *>(lv_event_get_user_data(e))->rt_;
            r->set_idle(r->idle_mode(), !r->idle_anim_keep(), r->idle_seconds(), true);
            lv_label_set_text(static_cast<lv_obj_t *>(lv_obj_get_user_data(lv_event_get_current_target_obj(e))),
                              r->t(r->idle_anim_keep() ? "common.on" : "common.off").c_str());
          },
          LV_EVENT_CLICKED, this);
      y += 60;
    }
    y += 8;
    // MIRRORED: board_edit.cpp open_idle_list_ (the idle brightness) - a change here must be made there too.
    // the idle brightness: never past the screen's; live while it moves
    slider(this->rt_->t("panel.idle_brightness"), 2, 20, this->rt_->idle_brightness() / 5, [](lv_event_t *e) {
      auto *self = static_cast<Board *>(lv_event_get_user_data(e));
      lv_obj_t *sl = lv_event_get_current_target_obj(e);
      const int most = std::max(2, self->rt_->brightness() / 5);
      if (lv_slider_get_value(sl) > most)
        lv_slider_set_value(sl, most, LV_ANIM_OFF);  // (no brighter than the screen)
      const int pct = lv_slider_get_value(sl) * 5;
      lv_label_set_text(static_cast<lv_obj_t *>(lv_obj_get_user_data(sl)), (std::to_string(pct) + " %").c_str());
      self->rt_->set_idle_brightness(pct, lv_event_get_code(e) == LV_EVENT_RELEASED);
    });
    // MIRRORED: board_edit.cpp open_idle_list_ (Screen off when the following area lights are off) - a change here must be made there too.
    // the room's lights all off (where the panel is): the screen off when
    // idle, not dimmed - its word, and under it the room it follows
    {
      lv_obj_t *b = lv_obj_create(list);
      lv_obj_remove_style_all(b);
      lv_obj_set_size(b, 300, LV_SIZE_CONTENT);  // (its word and the room line: as tall as they are)
      lv_obj_set_style_pad_ver(b, 10, 0);
      lv_obj_set_pos(b, 0, y);
      lv_obj_set_style_radius(b, 10, 0);
      lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
      lv_obj_set_style_bg_color(b, lv_color_hex(this->color_("button", 0x333333)), 0);
      lv_obj_add_flag(b, LV_OBJ_FLAG_CLICKABLE);
      lv_obj_add_flag(b, LV_OBJ_FLAG_SCROLL_CHAIN_VER);
      lv_obj_t *w = lv_label_create(b);
      lv_label_set_text(w, this->rt_->t("panel.idle_room_dark").c_str());
      lv_label_set_long_mode(w, LV_LABEL_LONG_MODE_WRAP);
      lv_obj_set_width(w, 210);
      lv_obj_set_style_text_font(w, this->fonts_.prefix, 0);
      lv_obj_set_style_text_color(w, lv_color_hex(text), 0);
      lv_obj_set_pos(w, 14, 0);
      lv_obj_t *sub = lv_label_create(b);
      lv_label_set_text(sub, this->room_line_().c_str());
      lv_label_set_long_mode(sub, LV_LABEL_LONG_MODE_WRAP);
      lv_obj_set_width(sub, 210);
      lv_obj_set_style_text_font(sub, this->fonts_.prefix, 0);
      lv_obj_set_style_text_color(sub, lv_color_hex(dim), 0);
      lv_obj_update_layout(w);  // (its height: one to three lines)
      lv_obj_align_to(sub, w, LV_ALIGN_OUT_BOTTOM_LEFT, 0, 4);
      lv_obj_t *st = lv_label_create(b);
      lv_label_set_text(st, this->rt_->t(this->rt_->idle_lights_off() ? "common.on" : "common.off").c_str());
      lv_obj_set_style_text_font(st, this->fonts_.name, 0);
      lv_obj_set_style_text_color(st, lv_color_hex(accent), 0);
      lv_obj_align(st, LV_ALIGN_RIGHT_MID, -14, 0);
      lv_obj_set_user_data(b, st);
      lv_obj_add_event_cb(
          b,
          [](lv_event_t *e) {
            auto *r = static_cast<Board *>(lv_event_get_user_data(e))->rt_;
            r->set_idle_lights_off(!r->idle_lights_off());
            lv_label_set_text(static_cast<lv_obj_t *>(lv_obj_get_user_data(lv_event_get_current_target_obj(e))),
                              r->t(r->idle_lights_off() ? "common.on" : "common.off").c_str());
          },
          LV_EVENT_CLICKED, this);
      lv_obj_update_layout(b);
      y += lv_obj_get_height(b) + 8;
    }
  }
  // the theme: one button each (the first is the default)
  if (m.themes.size() > 1) {
    lv_obj_t *h = lv_label_create(list);
    lv_label_set_text(h, this->rt_->t("menu.theme").c_str());
    lv_obj_set_style_text_font(h, this->fonts_.name, 0);
    lv_obj_set_style_text_color(h, lv_color_hex(text), 0);
    lv_obj_set_pos(h, 6, y);
    y += 36;
    static std::vector<std::string> names;
    names = m.themes;
    const std::string &now = m.own_theme.empty() ? m.theme : m.own_theme;
    for (size_t i = 0; i < names.size(); i++) {
      const bool on = names[i] == now;
      lv_obj_t *b = lv_obj_create(list);
      lv_obj_remove_style_all(b);
      lv_obj_set_size(b, 300, 52);
      lv_obj_set_pos(b, 0, y);
      lv_obj_set_style_radius(b, 10, 0);
      lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
      lv_obj_set_style_bg_color(b, lv_color_hex(on ? accent : this->color_("button", 0x333333)), 0);
      lv_obj_add_flag(b, LV_OBJ_FLAG_CLICKABLE);
      lv_obj_add_flag(b, LV_OBJ_FLAG_SCROLL_CHAIN_VER);
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
      // MIRRORED: board_edit.cpp open_theme_list_ ("(Default)" on the first) - a change here must be made there too.
      std::string label = this->theme_name_(names[i]);
      if (i == 0) {
        std::string d = this->rt_->t("theme.default");
        const size_t at = d.find("{name}");
        if (at != std::string::npos)
          label = d.replace(at, 6, label);
      }
      lv_obj_t *l = lv_label_create(b);
      lv_label_set_text(l, label.c_str());
      lv_obj_set_style_text_font(l, this->fonts_.name, 0);
      lv_obj_set_style_text_color(l, lv_color_hex(on ? on_accent : text), 0);
      lv_obj_center(l);
      y += 60;
    }
  }
  // done: the X at the bottom, where the color picker has its own
  // (MIRRORED: picker.cpp build_ round - a change here must be made there
  // too); the list ends above it, as the picker's column does
  lv_obj_set_height(list, 300);
  lv_obj_align(list, LV_ALIGN_CENTER, 0, 6);
  {
    lv_obj_t *x = bar_button(this->scrim_, this->color_("button", 0x333333), this->color_("tileBorder", 0x4A4A4A), 10);
    lv_obj_align(x, LV_ALIGN_BOTTOM_MID, 0, -24);
    lv_obj_add_event_cb(
        x,
        [](lv_event_t *e) {
          lv_async_call([](void *p) { static_cast<Board *>(p)->close_dialog_(); }, lv_event_get_user_data(e));
        },
        LV_EVENT_CLICKED, this);
    lv_obj_t *g = lv_label_create(x);
    lv_label_set_text(g, "\U000F0156");  // mdi:close
    lv_obj_set_style_text_font(g, this->fonts_.glyph, 0);
    lv_obj_set_style_text_color(g, lv_color_hex(text), 0);
    lv_obj_center(g);
  }
  // drawn again after a change: back where it was
  if (this->strip_settings_y_ > 0) {
    lv_obj_update_layout(list);
    lv_obj_scroll_to_y(list, this->strip_settings_y_, LV_ANIM_OFF);
  }
  this->strip_settings_y_ = -1;
}

}  // namespace esphome::room_tiles
