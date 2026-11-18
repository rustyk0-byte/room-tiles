#include "map_view.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstdio>
#include <functional>
#include <vector>

#include <esp_heap_caps.h>
#include <esp_timer.h>
#include <freertos/task.h>
#include <src/misc/cache/instance/lv_image_cache.h>

#include "esphome/core/hal.h"
#include "esphome/core/log.h"

#include "board.h"
#include "drag_bar.h"
#include "psram_scope.h"
#include "raster.h"
#include "room_tiles.h"

namespace esphome::room_tiles {

static const char *const TAG = "room_tiles.map";
static const int DRAG_PX = 6;  // a press that moves further is a pan, not a tap (the old panels)
static const float ZONE_MARGIN = 0.18f;    // a room zoomed into: this much around it (the dashboard)
static const uint32_t BUSY_AFTER_MS = 250; // tiles still missing this long: the stopwatch

// ---- opening / closing ------------------------------------------------------------

// A pop-up / the room list open over the map closes when the view changes -
// after this event: the tap that changes it may be on a tile in the pop-up
void MapView::close_overlays_later_() {
  if (this->popup_box_ == nullptr && this->rooms_scrim_ == nullptr)
    return;
  lv_async_call(
      [](void *p) {
        auto *self = static_cast<MapView *>(p);
        self->close_popup_();
        self->close_rooms_();
      },
      this);
}

void MapView::open(const PanelModel &model, const std::string &map_id, const std::string &floor) {
  if (this->parent_ == nullptr || model.maps.empty())
    return;
  PsramScope psram;  // (its index, markers, names: PSRAM - psram_scope.h)
  this->pictures_to_internal_();
  this->close_overlays_later_();
  this->model_ = &model;
  std::shared_ptr<const MapSpec> pick;
  auto find = [&](auto pred) {
    for (auto &m : model.maps)
      if (pred(*m))
        return m;
    return std::shared_ptr<const MapSpec>();
  };
  if (!map_id.empty())
    pick = find([&](const MapSpec &m) { return m.id == map_id; });
  if (!pick && !floor.empty())
    pick = find([&](const MapSpec &m) { return m.floor == floor; });
  if (!pick && !this->map_id_.empty())
    pick = find([&](const MapSpec &m) { return m.id == this->map_id_; });
  if (!pick)
    pick = model.maps.front();
  if (this->jobs_ == nullptr) {
    this->jobs_ = xQueueCreate(SLOTS, sizeof(Job *));
    this->done_ = xQueueCreate(SLOTS, sizeof(Job *));
    // core 0, low priority: drawing never holds up the main loop (LVGL)
    xTaskCreatePinnedToCore(&MapView::worker_, "rt_map", 6144, this, 1, nullptr, 0);
  }
  if (this->root_ == nullptr)
    this->build_();
  if (!this->opening_queue_)
    this->leave_queue_();  // (a plain map: out of any vacuum's queue view)
  this->open_ = true;
  this->missing_since_ = millis();
  lv_obj_remove_flag(this->root_, LV_OBJ_FLAG_HIDDEN);
  lv_obj_add_flag(this->board_, LV_OBJ_FLAG_HIDDEN);  // (nothing under the map redraws)
  // the screen and the display's bottom layer aren't painted under the map
  // (their opacity only: never HIDDEN on a screen - an LVGL 9.5 crash)
  this->screen_opa_ = lv_obj_get_style_bg_opa(this->parent_, LV_PART_MAIN);
  this->bottom_opa_ = lv_obj_get_style_bg_opa(lv_layer_bottom(), LV_PART_MAIN);
  lv_obj_set_style_bg_opa(this->parent_, LV_OPA_TRANSP, 0);
  lv_obj_set_style_bg_opa(lv_layer_bottom(), LV_OPA_TRANSP, 0);
  this->phase_(ZOOM, "Map open " + pick->id);
  this->opening_ = true;
  const uint32_t t_open = millis();
  this->show_map_(pick);
  this->opening_ = false;
  ESP_LOGI(TAG,
           "Map %s open in %u ms (PSRAM free %u KB, internal free %u KB, largest block %u KB; %u pictures, %u KB of "
           "them in internal RAM)",
           pick->id.c_str(), (unsigned) (millis() - t_open), (unsigned) (heap_caps_get_free_size(MALLOC_CAP_SPIRAM) / 1024),
           (unsigned) (heap_caps_get_free_size(MALLOC_CAP_INTERNAL) / 1024),
           (unsigned) (heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL) / 1024), (unsigned) this->sprites_.size(),
           (unsigned) (sprite_internal_bytes() / 1024));
}

// Profiling: one log line per phase - how many frames, how long each took
// (perf.h). ZOOM lasts until the screen's tiles are all drawn, PAN from the
// drag starting to the finger lifting, IDLE is logged every 10 s.
void MapView::phase_(Phase p, const std::string &what) {
  std::string note;
  if (this->batch_tiles_ > 0) {
    char b[64];
    snprintf(b, sizeof(b), "%u tiles drawn, %.1f ms each", (unsigned) this->batch_tiles_,
             this->batch_us_ / 1000.0f / this->batch_tiles_);
    note = b;
  }
  if (this->loop_n_ > 0) {
    char b[64];
    snprintf(b, sizeof(b), "%smap loop avg %.2f / max %.1f ms", note.empty() ? "" : ", ",
             this->loop_us_ / 1000.0f / this->loop_n_, this->loop_max_us_ / 1000.0f);
    note += b;
  }
  if (!note.empty())
    this->stats_.note(note);
  this->batch_tiles_ = this->batch_us_ = 0;
  this->loop_n_ = this->loop_us_ = this->loop_max_us_ = 0;
  this->phase_kind_ = p;
  if (p == PAN || p == ZOOM)
    this->fast_loop_.start();
  else
    this->fast_loop_.stop();
  this->stats_.start(what);
}

void MapView::close() {
  if (!this->open_)
    return;
  this->open_ = false;
  this->close_popup_();
  this->close_rooms_();
  this->markers_lite_(false);  // (closed mid-drag: the zoom box itself again)
  this->epoch_++;  // (tiles still queued: not needed now)
  // its markers and room names go (made again when it opens - quick: their
  // pictures are kept), the pictures' pixels move to PSRAM (internal RAM back
  // for the rest of the panel; back again when it opens - copies, ~1 ms)
  lv_obj_clean(this->markers_layer_);
  this->markers_.clear();
  this->markers_.shrink_to_fit();
  this->links_.clear();
  this->labels_.clear();
  this->labels_.shrink_to_fit();
  this->zoom_box_as_picture_(false);
  for (auto &kv : this->sprites_)
    sprite_to_psram(kv.second);
  sprite_to_psram(this->zoom_sprite_);
  lv_obj_add_flag(this->root_, LV_OBJ_FLAG_HIDDEN);
  lv_obj_set_style_bg_opa(this->parent_, this->screen_opa_, 0);
  lv_obj_set_style_bg_opa(lv_layer_bottom(), this->bottom_opa_, 0);
  lv_obj_remove_flag(this->board_, LV_OBJ_FLAG_HIDDEN);
  BusyIcons::show(this->busy_, false);
  this->phase_(IDLE, "Map closing");  // (logs the running phase)
  this->stats_.stop();
}

void MapView::model_changed(const PanelModel &model) {
  this->model_ = &model;
  this->queue_pictures(model);  // (made in the background while the map is closed)
  // forget maps that are gone (their tiles age out of the pool)
  for (auto it = this->known_.begin(); it != this->known_.end();) {
    bool still = false;
    for (auto &m : model.maps)
      still |= m == it->second.spec;
    it = still ? std::next(it) : this->known_.erase(it);
  }
  if (!this->open_)
    return;
  std::shared_ptr<const MapSpec> now;
  for (auto &m : model.maps)
    if (m->id == this->map_id_)
      now = m;
  if (!now) {
    this->close();
    return;
  }
  this->build_bar_();  // (the maps' names / the list may have changed)
  if (now != this->map_)
    this->show_map_(now);
  else
    this->build_markers_();  // (markers placed / moved on the dashboard)
}

void MapView::theme_changed() {
  this->known_.clear();  // new gens: every tile again, in the new colours
  this->epoch_++;
  this->sprites_clear_();  // (the pre-rendered markers, names, zoom box: their colours)
  if (this->root_ != nullptr) {
    // the screen itself is built again on the next open (its colours)
    this->close();
    for (auto &s : this->slots_)
      s.shown = nullptr;
    this->labels_.clear();
    lv_obj_delete(this->root_);
    this->root_ = nullptr;
    this->qbar_ = nullptr;  // (it was in the root)
    this->q_auto_ = nullptr;
    this->rooms_scrim_ = nullptr;
    this->queue_mode_ = false;
    this->style_.reset();
    this->area_y_ = BAR_H;
    this->area_h_ = AREA_H;
    this->markers_.clear();
    this->busy_icons_.clear();
  }
}

// ---- the screen ---------------------------------------------------------------------

void MapView::build_() {
  const uint32_t bg = this->rt_->color("mapBg", 0x121212);
  this->root_ = lv_obj_create(this->parent_);
  lv_obj_remove_style_all(this->root_);
  lv_obj_set_size(this->root_, 1024, 600);
  // nothing under the map is painted while it's up (a full-screen fill into
  // the render buffer is ~25 ms a frame): the map area is always covered by
  // tiles - drawn ones, plain background ones while they're drawn, and around
  // a map smaller than the area - so the root, the area and the screen behind
  // them are see-through; the bar has its own fill
  lv_obj_set_style_bg_opa(this->root_, LV_OPA_TRANSP, 0);
  lv_obj_remove_flag(this->root_, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_add_flag(this->root_, LV_OBJ_FLAG_HIDDEN);

  this->bar_ = lv_obj_create(this->root_);
  lv_obj_remove_style_all(this->bar_);
  lv_obj_set_size(this->bar_, 1024, BAR_H);
  lv_obj_set_style_bg_color(this->bar_, lv_color_hex(this->rt_->color("page", 0x000000)), 0);
  lv_obj_set_style_bg_opa(this->bar_, LV_OPA_COVER, 0);
  lv_obj_remove_flag(this->bar_, LV_OBJ_FLAG_SCROLLABLE);

  this->area_ = lv_obj_create(this->root_);
  lv_obj_remove_style_all(this->area_);
  lv_obj_set_pos(this->area_, 0, this->area_y_);
  lv_obj_set_size(this->area_, AREA_W, this->area_h_);
  lv_obj_set_style_bg_color(this->area_, lv_color_hex(bg), 0);
  lv_obj_set_style_bg_opa(this->area_, LV_OPA_COVER, 0);
  // panning: LVGL's own drag-scrolling locks each drag to one axis, so it's
  // off (scroll_dir NONE) and on_drag_ follows the finger on both, stopping
  // with it (the old panels' map); the area still scrolls by code
  lv_obj_set_scrollbar_mode(this->area_, LV_SCROLLBAR_MODE_OFF);
  lv_obj_set_scroll_dir(this->area_, LV_DIR_NONE);
  lv_obj_add_event_cb(this->area_, &MapView::on_scroll_, LV_EVENT_SCROLL, this);
  if (!this->indev_hooked_) {
    // every press / lift on the touch panel: how long after a lift a press came
    if (lv_indev_t *in = lv_indev_get_next(nullptr)) {
      this->indev_hooked_ = true;
      lv_indev_add_event_cb(
          in,
          [](lv_event_t *e) {
            auto *self = static_cast<MapView *>(lv_event_get_user_data(e));
            const uint32_t now = millis();
            const lv_event_code_t code = lv_event_get_code(e);
            if (code == LV_EVENT_PRESSED) {
              self->press_gap_ms_ = self->lift_ms_ == 0 ? 0xFFFFFFFF : now - self->lift_ms_;
              lv_indev_get_point(static_cast<lv_indev_t *>(lv_event_get_target(e)), &self->press_at_);  // (the target: the indev)
            }
            else if (code == LV_EVENT_RELEASED)
              self->lift_ms_ = now;
          },
          LV_EVENT_ALL, this);
    }
  }
  lv_obj_add_event_cb(this->area_, &MapView::on_drag_, LV_EVENT_ALL, this);
  lv_obj_add_event_cb(this->area_, &MapView::on_tap_, LV_EVENT_CLICKED, this);

  this->content_ = lv_obj_create(this->area_);
  lv_obj_remove_style_all(this->content_);
  lv_obj_remove_flag(this->content_, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_remove_flag(this->content_, LV_OBJ_FLAG_CLICKABLE);
  // tiles, then the markers, the room names on top (the dashboard's order)
  this->tiles_layer_ = lv_obj_create(this->content_);
  this->markers_layer_ = lv_obj_create(this->content_);
  this->labels_layer_ = lv_obj_create(this->content_);
  this->badges_layer_ = lv_obj_create(this->content_);  // (queue mode: the rooms' numbers)
  for (lv_obj_t *o : {this->tiles_layer_, this->markers_layer_, this->labels_layer_, this->badges_layer_}) {
    lv_obj_remove_style_all(o);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_CLICKABLE);
  }
  // a marker's / link's events go on up to the area (its drag: panning_ and
  // the pan from a marker) - every level between must pass them on
  lv_obj_add_flag(this->markers_layer_, LV_OBJ_FLAG_EVENT_BUBBLE);
  lv_obj_add_flag(this->content_, LV_OBJ_FLAG_EVENT_BUBBLE);
  lv_obj_add_event_cb(this->tiles_layer_, &MapView::on_draw_tiles_, LV_EVENT_DRAW_MAIN, this);
  lv_obj_add_event_cb(this->markers_layer_, &MapView::on_draw_markers_, LV_EVENT_DRAW_MAIN, this);
  lv_obj_add_event_cb(this->labels_layer_, &MapView::on_draw_labels_, LV_EVENT_DRAW_MAIN, this);

  this->area_filled_ = true;  // (only if a tile on screen has no buffer: see request_tiles_)

  // the plain tile: a tile not drawn yet, a tile past the map's edges
  sprite_init();
  if (this->blank_ == nullptr) {
    this->blank_ = sprite_new(TILE, TILE, false);  // (one colour: every pixel entry 0)
    if (this->blank_ != nullptr)
      memset(this->blank_->px, 0, (size_t) this->blank_->stride * TILE);
  }
  this->blank_rgb_ = 0xFFFFFFFF;  // (its colour set when a map shows)

  // (on the root: it mustn't scroll with the map)
  this->busy_ = this->busy_icons_.make(this->root_, 72, this->rt_->color("accent", 0x4B9EF3));
  lv_obj_align(this->busy_, LV_ALIGN_CENTER, 0, this->area_y_ + this->area_h_ / 2 - 300);
  this->build_zoom_box_();
}

// how far below the top bar the zoom box sits: clear of the bar's buttons
// (a finger going for + mustn't land on settings or close)
static const int ZOOM_BOX_GAP = 60;

// The map's area: under the top bar (and the queue's bar in queue mode)
void MapView::set_area_(int y, int h) {
  this->area_y_ = y;
  this->area_h_ = h;
  if (this->area_ == nullptr)
    return;
  lv_obj_set_pos(this->area_, 0, y);
  lv_obj_set_size(this->area_, AREA_W, h);
  lv_obj_align(this->busy_, LV_ALIGN_CENTER, 0, y + h / 2 - 300);
  lv_obj_set_y(this->zoom_box_, y + ZOOM_BOX_GAP);
}

// The zoom box, the map's top-right corner: in, a roller of the zoom steps
// (like the tiles' rollers: the steps either side small and gray - roll it,
// let go, and the map jumps to that zoom), out.
static std::string zoom_text(float zoom) {
  // "1x", "1.5x", "2.25x"
  char buf[16];
  const int z = (int) lroundf(zoom * 100);
  if (z % 100 == 0)
    snprintf(buf, sizeof(buf), "%dx", z / 100);
  else if (z % 10 == 0)
    snprintf(buf, sizeof(buf), "%d.%dx", z / 100, (z % 100) / 10);
  else
    snprintf(buf, sizeof(buf), "%d.%02dx", z / 100, z % 100);
  return buf;
}

static const float ZOOM_STEP = 0.5f;  // (the panel's steps: each zoom a whole new set of tiles)

void MapView::build_zoom_box_() {
  const int W = 88;  // (sized for the 7": every part at least ~48 px)
  lv_obj_t *box = lv_obj_create(this->root_);
  this->zoom_box_ = box;
  lv_obj_remove_style_all(box);
  lv_obj_set_width(box, W);
  lv_obj_set_pos(box, 1024 - W - 12, this->area_y_ + ZOOM_BOX_GAP);
  lv_obj_set_style_bg_color(box, lv_color_hex(this->rt_->color("tile", 0x1E1E1E)), 0);
  lv_obj_set_style_bg_opa(box, LV_OPA_COVER, 0);
  lv_obj_set_style_border_width(box, 1, 0);
  lv_obj_set_style_border_color(box, lv_color_hex(this->rt_->color("tileBorder", 0x4A4A4A)), 0);
  lv_obj_set_style_radius(box, 12, 0);
  lv_obj_remove_flag(box, LV_OBJ_FLAG_SCROLLABLE);
  auto button = [&](const char *glyph, lv_event_cb_t cb) {
    lv_obj_t *b = lv_obj_create(box);
    lv_obj_remove_style_all(b);
    lv_obj_set_size(b, W, 52);
    lv_obj_add_flag(b, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(b, cb, LV_EVENT_CLICKED, this);
    lv_obj_t *g = lv_label_create(b);
    lv_label_set_text(g, glyph);
    lv_obj_set_style_text_font(g, this->fonts_->glyph, 0);
    lv_obj_center(g);
    return b;
  };
  this->zoom_in_ = button("\U000F0415", &MapView::on_zoom_in_);  // mdi:plus

  // the steps, the biggest zoom on top (like + above it): set_zoom_steps_
  lv_obj_t *r = lv_roller_create(box);
  this->zoom_roller_ = r;
  this->set_zoom_steps_();
  lv_obj_set_width(r, W - 12);
  // the tiles' roller look: subtle frame, side rows dimmed (board.cpp build_roller_)
  lv_obj_set_style_bg_opa(r, LV_OPA_TRANSP, 0);
  lv_obj_set_style_border_width(r, 1, 0);
  lv_obj_set_style_border_color(r, lv_color_hex(this->rt_->color("tileBorder", 0x4A4A4A)), 0);
  lv_obj_set_style_radius(r, 8, 0);
  lv_obj_set_style_pad_hor(r, 2, 0);
  lv_obj_set_style_pad_ver(r, 4, 0);
  lv_obj_set_style_text_opa(r, LV_OPA_50, 0);
  lv_obj_set_style_text_opa(r, LV_OPA_COVER, LV_PART_SELECTED);
  lv_obj_set_style_text_align(r, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_style_text_font(r, this->fonts_->roll, 0);
  lv_obj_set_style_text_color(r, lv_color_hex(this->rt_->color("rollerText", 0x808080)), 0);
  lv_obj_set_style_bg_opa(r, LV_OPA_TRANSP, LV_PART_SELECTED);
  lv_obj_set_style_text_color(r, lv_color_hex(this->rt_->color("text", 0xFFFFFF)), LV_PART_SELECTED);
  lv_obj_set_style_text_font(r, this->fonts_->roll_mid, LV_PART_SELECTED);
  lv_roller_set_visible_row_count(r, 3);  // (after the fonts and spacing: its height follows them)
  lv_obj_add_event_cb(r, &MapView::on_zoom_roller_, LV_EVENT_VALUE_CHANGED, this);

  this->zoom_out_ = button("\U000F0374", &MapView::on_zoom_out_);  // mdi:minus
  lv_obj_update_layout(box);
  const int rh = lv_obj_get_height(r);
  lv_obj_set_pos(this->zoom_in_, 0, 0);
  lv_obj_set_pos(r, 6, 52);
  lv_obj_set_pos(this->zoom_out_, 0, 52 + rh);
  lv_obj_set_height(box, 52 + rh + 52);
}

// The roller's steps: the map's zoom limit down to 1x, in 0.25s
void MapView::set_zoom_steps_() {
  if (this->zoom_roller_ == nullptr)
    return;
  std::string opts;
  const int steps = (int) lroundf((this->max_zoom_ - 1) / ZOOM_STEP);
  for (int i = 0; i <= steps; i++)
    opts += (i ? "\n" : "") + zoom_text(this->max_zoom_ - i * ZOOM_STEP);
  lv_roller_set_options(this->zoom_roller_, opts.c_str(), LV_ROLLER_MODE_NORMAL);
}

// MIRRORED: frontend/src/map.ts viewMaxZoom - a change here must be made there too.
// How far a viewer zooms in (map.ts viewMaxZoom, the same rule): 8x, or 1.25x
// the deepest layer's start, or what its smallest room needs to fill the view
// (as a tap on it zooms: ZONE_MARGIN round it) - in 0.25 steps
float MapView::view_max_zoom_(const MapSpec &m) const {
  float z = VIEW_MAX_ZOOM;
  for (const MapLayer &l : m.layers)
    z = std::max(z, l.min_zoom * 1.25f);
  const float bw = std::max(1.0f, m.bounds[2] - m.bounds[0]), bh = std::max(1.0f, m.bounds[3] - m.bounds[1]);
  const float ref = std::max(bw / AREA_W, bh / AREA_H);  // (map units a pixel at 1x)
  for (const MapZone &zn : m.zones) {
    if (!zn.vacuum.empty() || zn.points.empty())
      continue;  // (a vacuum's own zone: only its queue view)
    float x0 = 1e30f, y0 = 1e30f, x1 = -1e30f, y1 = -1e30f;
    for (const Pt &p : zn.points) {
      x0 = std::min(x0, p.x), y0 = std::min(y0, p.y), x1 = std::max(x1, p.x), y1 = std::max(y1, p.y);
    }
    const float w = (x1 - x0) * (1 + 2 * ZONE_MARGIN), h = (y1 - y0) * (1 + 2 * ZONE_MARGIN);
    if (w > 0 && h > 0)
      z = std::max(z, ref / std::max(w / AREA_W, h / AREA_H));
  }
  return ceilf(z / ZOOM_STEP - 1e-3f) * ZOOM_STEP;  // (on the panel's steps)
}

void MapView::paint_zoom_box_() {
  this->paint_layer_pills_();
  // the nearest step (a room's zoom falls between them)
  const int steps = (int) lroundf((this->max_zoom_ - 1) / ZOOM_STEP);
  const int i = std::max(0, std::min(steps, (int) lroundf((this->max_zoom_ - this->zoom_) / ZOOM_STEP)));
  lv_roller_set_selected(this->zoom_roller_, i, LV_ANIM_OFF);
  const uint32_t on = this->rt_->color("text", 0xFFFFFF), off = this->rt_->color("tileBorder", 0x4A4A4A);
  lv_obj_set_style_text_color(lv_obj_get_child(this->zoom_in_, 0), lv_color_hex(this->zoom_ < this->max_zoom_ - 0.005f ? on : off), 0);
  lv_obj_set_style_text_color(lv_obj_get_child(this->zoom_out_, 0), lv_color_hex(this->zoom_ > 1.005f ? on : off), 0);
}

void MapView::on_zoom_roller_(lv_event_t *e) {
  auto *self = static_cast<MapView *>(lv_event_get_user_data(e));
  self->zoom_to_(self->max_zoom_ - lv_roller_get_selected(self->zoom_roller_) * ZOOM_STEP);
}

void MapView::build_bar_() {
  lv_obj_clean(this->bar_);
  this->pill_ids_.clear();
  const uint32_t text = this->rt_->color("text", 0xFFFFFF);
  const uint32_t accent = this->rt_->color("accent", 0x4B9EF3);

  // in a room: Back (to the whole map) and the room's name; else the map's
  const MapZone *zone = nullptr;
  if (this->map_ && !this->zone_.empty())
    for (const MapZone &z : this->map_->zones)
      if (z.id == this->zone_)
        zone = &z;
  // (the back and close buttons framed like the dashboard's, 12 px in, their
  // tap areas 6 px wider all round)
  const uint32_t btn_bg = this->rt_->color("button", 0x333333), btn_border = this->rt_->color("tileBorder", 0x4A4A4A);
  const int btn_y = (BAR_H - BAR_BTN_H) / 2;
  // the Room Tiles icon, far left (as on the tiles' bar)
  const int lead = brand_icon(this->bar_, *this->fonts_, BAR_H / 2, 20, this->rt_->image(IMG_BRAND_BAR));
  int title_x = lead;
  if (zone != nullptr) {
    const int back_x = lead - 8;  // (the button's frame where the title would start)
    lv_obj_t *back = bar_button(this->bar_, btn_bg, btn_border, 6);
    lv_obj_set_pos(back, back_x, btn_y);
    lv_obj_add_event_cb(back, &MapView::on_back_, LV_EVENT_CLICKED, this);
    lv_obj_t *g = lv_label_create(back);
    lv_label_set_text(g, "\U000F004D");  // mdi:arrow-left
    lv_obj_set_style_text_font(g, this->fonts_->glyph, 0);
    lv_obj_set_style_text_color(g, lv_color_hex(text), 0);
    lv_obj_center(g);
    title_x = back_x + BAR_BTN_W + 18;  // (clear of its tap area and the title's)
  }
  std::string name = this->map_ ? this->map_->name : "";
  if (this->queue_mode_)  // "Matic · Queue"
    name = this->q_.name + " \xC2\xB7 " + this->rt_->t("help.title.queue");
  if (zone != nullptr) {
    name = zone->name;
    if (name.find_first_not_of(' ') == std::string::npos && this->model_ != nullptr)
      for (const AreaSpec &a : this->model_->areas)
        if (a.id == zone->area)
          name = a.name;
  }
  const int title_cap = 320 + (lead - 20);  // (the title's room: as before the icon)
  int title_end = title_x;  // (where the nav may start)
  if (this->queue_mode_) {
    lv_obj_t *title = lv_label_create(this->bar_);
    lv_label_set_text(title, name.c_str());
    lv_label_set_long_mode(title, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_width(title, title_cap - title_x);
    lv_obj_set_style_text_font(title, this->fonts_->bar, 0);
    lv_obj_set_style_text_color(title, lv_color_hex(text), 0);
    lv_obj_set_pos(title, title_x, 11);
    lv_point_t sz;  // (the label is a fixed width: its text's own)
    lv_text_get_size(&sz, name.c_str(), this->fonts_->bar, 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);
    title_end = title_x + std::min<int>(title_cap - title_x, sz.x);
  } else {
    // like the tiles' area name: a tap opens the room list (go to a room),
    // its triangle says so
    lv_obj_t *title = dropdown_title(this->bar_, name, *this->fonts_, text, title_cap - title_x);
    lv_obj_set_pos(title, title_x, 11);
    lv_obj_set_ext_click_area(title, 12);
    lv_obj_update_layout(title);
    title_end = title_x + lv_obj_get_width(title);
    lv_obj_add_event_cb(
        title,
        [](lv_event_t *e) {
          // (the bar is rebuilt by what's picked: the list opens after this event)
          lv_async_call([](void *p) { static_cast<MapView *>(p)->open_rooms_(); }, lv_event_get_user_data(e));
        },
        LV_EVENT_CLICKED, this);
  }

  // close, top right (blue, like the old panels' map)
  // Help and settings beside it (the dashboard's map bar): Help's map page
  // (or the queue's), the settings menu
  auto tool = [&](int from_right, const char *glyph, lv_event_cb_t cb) {
    lv_obj_t *b = bar_button(this->bar_, btn_bg, btn_border, 4);
    lv_obj_align(b, LV_ALIGN_TOP_RIGHT, -12 - from_right * (BAR_BTN_W + 8), btn_y);
    lv_obj_add_event_cb(b, cb, LV_EVENT_CLICKED, this);
    lv_obj_t *g = lv_label_create(b);
    lv_label_set_text(g, glyph);
    lv_obj_set_style_text_font(g, this->fonts_->glyph, 0);
    lv_obj_set_style_text_color(g, lv_color_hex(text), 0);
    lv_obj_center(g);
  };
  tool(2, "\U000F0625", [](lv_event_t *e) {  // mdi:help-circle-outline
    auto *self = static_cast<MapView *>(lv_event_get_user_data(e));
    self->rt_->board().open_help(self->queue_mode_ ? "queue" : "view");
  });
  if (const lv_image_dsc_t *gear = this->rt_->image(IMG_ICON_SETTINGS_S)) {
    lv_obj_t *b = bar_button(this->bar_, btn_bg, btn_border, 4);
    lv_obj_align(b, LV_ALIGN_TOP_RIGHT, -12 - (BAR_BTN_W + 8), btn_y);
    lv_obj_add_event_cb(
        b, [](lv_event_t *e) { static_cast<MapView *>(lv_event_get_user_data(e))->rt_->board().open_settings(); },
        LV_EVENT_CLICKED, this);
    lv_obj_t *img = lv_image_create(b);
    lv_image_set_src(img, gear);
    lv_obj_center(img);
    if (this->rt_->board().found_dot())  // (as on the tiles' bar)
      gear_dot(b, this->rt_->color("light", 0xFFB300), &this->gear_dot_);
  }

  lv_obj_t *x = bar_button(this->bar_, btn_bg, btn_border, 4);
  lv_obj_align(x, LV_ALIGN_TOP_RIGHT, -12, btn_y);
  lv_obj_add_event_cb(x, &MapView::on_close_, LV_EVENT_CLICKED, this);
  lv_obj_t *xg = lv_label_create(x);
  lv_label_set_text(xg, "\U000F0156");  // mdi:close
  lv_obj_set_style_text_font(xg, this->fonts_->glyph, 0);
  lv_obj_set_style_text_color(xg, lv_color_hex(accent), 0);
  lv_obj_center(xg);

  // Where you are (the dashboard's map nav, nav-fit.ts): a framed group for
  // the maps (floors, the yard...) and one for this map's marker layers -
  // each only when there's a choice - led by its name (Map / Layer). A group
  // that doesn't fit collapses to its current one ("Ground ▾", a tap lists
  // them all): the layers first, then the maps; one still too wide scrolls
  // sideways in its frame. Between the title and Help.
  this->layer_pills_.clear();
  this->layer_menu_label_ = nullptr;
  std::vector<std::shared_ptr<const MapSpec>> pill_maps;
  if (this->model_ != nullptr)
    for (auto &m : this->model_->maps)
      if (!this->queue_mode_ || this->queue_map_(*m))
        pill_maps.push_back(m);
  this->pill_ids_.clear();
  for (auto &m : pill_maps)
    this->pill_ids_.push_back(m->id);
  const bool show_maps = pill_maps.size() > 1;
  const bool show_layers = this->map_ && this->map_->layers.size() > 1 && !this->queue_mode_;  // (queue: no markers)
  const int left = title_end + 16, right = 1024 - 12 - 3 * BAR_BTN_W - 2 * 8 - 16;  // (clear of Help, settings, close)
  const int group_gap = 12;
  auto make_group = [&](bool is_maps, bool collapsed) {
    lv_obj_t *g = lv_obj_create(this->bar_);
    lv_obj_remove_style_all(g);
    lv_obj_set_size(g, LV_SIZE_CONTENT, NAV_PILL_H + 8);
    lv_obj_set_flex_flow(g, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(g, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(g, 6, 0);
    lv_obj_set_style_pad_left(g, 10, 0);
    lv_obj_set_style_pad_right(g, 6, 0);
    lv_obj_set_style_radius(g, 14, 0);
    lv_obj_set_style_bg_opa(g, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(g, lv_color_hex(this->rt_->color("panelDark", 0x1E1E1E)), 0);
    lv_obj_set_style_border_width(g, 1, 0);
    lv_obj_set_style_border_color(g, lv_color_hex(this->rt_->color("tileBorder", 0x4A4A4A)), 0);
    lv_obj_set_scroll_dir(g, LV_DIR_HOR);
    lv_obj_set_scrollbar_mode(g, LV_SCROLLBAR_MODE_OFF);
    // its name: the icon (accent), the word, a line after them
    lv_obj_t *name_row = lv_obj_create(g);
    lv_obj_remove_style_all(name_row);
    lv_obj_set_size(name_row, LV_SIZE_CONTENT, NAV_PILL_H);
    lv_obj_set_flex_flow(name_row, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(name_row, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(name_row, 6, 0);
    lv_obj_set_style_pad_right(name_row, 8, 0);
    lv_obj_set_style_border_side(name_row, LV_BORDER_SIDE_RIGHT, 0);
    lv_obj_set_style_border_width(name_row, 1, 0);
    lv_obj_set_style_border_color(name_row, lv_color_hex(this->rt_->color("tileBorder", 0x4A4A4A)), 0);
    lv_obj_remove_flag(name_row, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_flag(name_row, LV_OBJ_FLAG_SCROLL_CHAIN_HOR);
    lv_obj_t *icon = lv_label_create(name_row);
    lv_label_set_text(icon, is_maps ? "\U000F0821" : "\U000F09FE");  // mdi:floor-plan / mdi:layers-outline
    lv_obj_set_style_text_font(icon, this->fonts_->menu, 0);
    lv_obj_set_style_text_color(icon, lv_color_hex(this->rt_->color("accent", 0x4B9EF3)), 0);
    lv_obj_t *word = lv_label_create(name_row);
    lv_label_set_text(word, this->rt_->t(is_maps ? "help.title.view" : "layers.layer").c_str());
    lv_obj_set_style_text_font(word, this->fonts_->name_s, 0);
    lv_obj_set_style_text_color(word, lv_color_hex(this->rt_->color("text", 0xFFFFFF)), 0);
    if (collapsed) {
      // the current one, "▾": a tap anywhere on the group lists them all
      lv_obj_add_flag(g, LV_OBJ_FLAG_CLICKABLE);
      lv_obj_add_event_cb(g, is_maps ? &MapView::on_maps_menu_ : &MapView::on_layers_menu_, LV_EVENT_CLICKED, this);
      std::string cur = this->map_ ? this->map_->name : "";
      lv_obj_t *p = this->nav_pill_(g, cur, true, true);
      lv_obj_remove_flag(p, LV_OBJ_FLAG_CLICKABLE);  // (the group's tap)
      if (!is_maps)
        this->layer_menu_label_ = lv_obj_get_child(p, 0);
      return g;
    }
    if (is_maps) {
      for (size_t i = 0; i < pill_maps.size(); i++) {
        lv_obj_t *p = this->nav_pill_(g, pill_maps[i]->name, this->map_ && pill_maps[i]->id == this->map_->id, false);
        lv_obj_set_user_data(p, (void *) (uintptr_t) i);
        lv_obj_add_event_cb(p, &MapView::on_map_pill_, LV_EVENT_CLICKED, this);
      }
    } else {
      for (size_t i = 0; i < this->map_->layers.size(); i++) {
        lv_obj_t *p = this->nav_pill_(g, this->map_->layers[i].name, false, false);  // (lit: paint_layer_pills_)
        lv_obj_set_user_data(p, (void *) (uintptr_t) i);
        lv_obj_add_event_cb(p, &MapView::on_layer_pill_, LV_EVENT_CLICKED, this);
        this->layer_pills_.push_back(p);
      }
    }
    return g;
  };
  // each group's width, full and collapsed (made, measured, gone)
  auto width_of = [&](bool is_maps, bool collapsed) {
    lv_obj_t *g = make_group(is_maps, collapsed);
    lv_obj_update_layout(g);
    const int w = lv_obj_get_width(g);
    lv_obj_delete(g);
    return w;
  };
  int maps_full = 0, maps_menu = 0, layers_full = 0, layers_menu = 0;
  if (show_maps)
    maps_full = width_of(true, false), maps_menu = width_of(true, true);
  if (show_layers)
    layers_full = width_of(false, false), layers_menu = width_of(false, true);
  this->layer_pills_.clear();
  this->layer_menu_label_ = nullptr;
  // MIRRORED: frontend/src/nav-fit.ts navFit - a change here must be made there too.
  // what collapses (nav-fit.ts navFit): as many pills as fit, the maps kept longest
  const int avail = right - left, gap = show_maps && show_layers ? group_gap : 0;
  bool maps_c = false, layers_c = false;
  auto fits = [&](bool mc, bool lc) {
    return (show_maps ? (mc ? maps_menu : maps_full) : 0) + (show_layers ? (lc ? layers_menu : layers_full) : 0) + gap <= avail;
  };
  if (!fits(false, false)) {
    if (show_layers && fits(false, true))
      layers_c = true;
    else if (show_maps && fits(true, false))
      maps_c = true;
    else
      maps_c = show_maps, layers_c = show_layers;
  }
  this->layers_collapsed_ = layers_c;
  std::vector<lv_obj_t *> groups;
  if (show_maps)
    groups.push_back(make_group(true, maps_c));
  if (show_layers)
    groups.push_back(make_group(false, layers_c));
  if (!groups.empty()) {
    lv_obj_update_layout(this->bar_);
    int total = gap;
    for (lv_obj_t *g : groups)
      total += lv_obj_get_width(g);
    if (total > avail) {
      // still too wide: each gets its share, its pills scrolling in its frame
      const int share = (avail - gap) / (int) groups.size();
      for (lv_obj_t *g : groups)
        if (lv_obj_get_width(g) > share)
          lv_obj_set_width(g, share);
      lv_obj_update_layout(this->bar_);
      total = gap;
      for (lv_obj_t *g : groups)
        total += lv_obj_get_width(g);
    }
    int x = std::max(left, std::min((1024 - total) / 2, right - total));  // (centered when it can be)
    for (lv_obj_t *g : groups) {
      lv_obj_set_pos(g, x, (BAR_H - (NAV_PILL_H + 8)) / 2);
      x += lv_obj_get_width(g) + group_gap;
    }
  }
  this->paint_layer_pills_();
}

// A pill of the map nav: lit = the accent (the dashboard's .floor / .floor.on);
// `menu`: the current one of a collapsed group, its "▾" after it
lv_obj_t *MapView::nav_pill_(lv_obj_t *parent, const std::string &text, bool on, bool menu) {
  lv_obj_t *p = lv_button_create(parent);
  lv_obj_remove_style_all(p);
  lv_obj_set_size(p, LV_SIZE_CONTENT, NAV_PILL_H);
  lv_obj_set_flex_flow(p, LV_FLEX_FLOW_ROW);
  lv_obj_set_flex_align(p, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
  lv_obj_set_style_pad_column(p, 2, 0);
  lv_obj_set_style_pad_left(p, 12, 0);
  lv_obj_set_style_pad_right(p, menu ? 6 : 12, 0);
  lv_obj_set_style_radius(p, NAV_PILL_H / 2, 0);
  lv_obj_set_style_bg_opa(p, LV_OPA_COVER, 0);
  lv_obj_set_style_border_width(p, 1, 0);
  lv_obj_set_ext_click_area(p, 4);
  lv_obj_add_flag(p, LV_OBJ_FLAG_SCROLL_CHAIN_HOR);  // (a swipe on it scrolls its group)
  lv_obj_t *l = lv_label_create(p);
  lv_label_set_text(l, text.c_str());
  lv_obj_set_style_text_font(l, this->fonts_->name_s, 0);
  if (menu) {
    lv_obj_t *v = lv_label_create(p);
    lv_label_set_text(v, "\U000F0140");  // mdi:chevron-down
    lv_obj_set_style_text_font(v, this->fonts_->menu, 0);
  }
  this->paint_pill_(p, on);
  return p;
}

// A collapsed group's tap: its list, under it (the dashboard's nav menu)
void MapView::on_maps_menu_(lv_event_t *e) {
  lv_obj_t *g = lv_event_get_current_target_obj(e);
  auto *self = static_cast<MapView *>(lv_event_get_user_data(e));
  self->nav_menu_x_ = lv_obj_get_x(g);
  lv_async_call([](void *p) { static_cast<MapView *>(p)->open_nav_(true); }, self);
}
void MapView::on_layers_menu_(lv_event_t *e) {
  lv_obj_t *g = lv_event_get_current_target_obj(e);
  auto *self = static_cast<MapView *>(lv_event_get_user_data(e));
  self->nav_menu_x_ = lv_obj_get_x(g);
  lv_async_call([](void *p) { static_cast<MapView *>(p)->open_nav_(false); }, self);
}

void MapView::open_nav_(bool is_maps) {
  if (!this->map_ || this->model_ == nullptr || this->rooms_scrim_ != nullptr)
    return;
  // (the room list's place: one list at a time, closed the same ways)
  this->rooms_scrim_ = lv_obj_create(this->root_);
  lv_obj_remove_style_all(this->rooms_scrim_);
  lv_obj_set_size(this->rooms_scrim_, 1024, 600);
  lv_obj_add_flag(this->rooms_scrim_, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_event_cb(
      this->rooms_scrim_,
      [](lv_event_t *e) {
        lv_async_call([](void *p) { static_cast<MapView *>(p)->close_rooms_(); }, lv_event_get_user_data(e));
      },
      LV_EVENT_CLICKED, this);
  const int n = is_maps ? (int) this->pill_ids_.size() : (int) this->map_->layers.size();
  const int full = n * (NAV_PILL_H + 6) - 6 + 16;
  const int h = std::min((600 - BAR_H) * 60 / 100, full);
  const bool scrolls = full > h;
  const int w = 220 + (scrolls ? 32 : 0);
  lv_obj_t *list = lv_obj_create(this->rooms_scrim_);
  lv_obj_remove_style_all(list);
  lv_obj_set_pos(list, std::max(8, std::min(this->nav_menu_x_, 1024 - w - 8)), BAR_H + 6);
  lv_obj_set_size(list, w, h);
  lv_obj_set_style_bg_color(list, lv_color_hex(this->rt_->color("panelDark", 0x1E1E1E)), 0);
  lv_obj_set_style_bg_opa(list, LV_OPA_COVER, 0);
  lv_obj_set_style_border_width(list, 1, 0);
  lv_obj_set_style_border_color(list, lv_color_hex(this->rt_->color("tileBorder", 0x4A4A4A)), 0);
  lv_obj_set_style_radius(list, 14, 0);
  lv_obj_set_style_pad_all(list, 8, 0);
  lv_obj_set_scroll_dir(list, LV_DIR_VER);
  lv_obj_add_flag(list, LV_OBJ_FLAG_CLICKABLE);  // (a tap in it isn't a tap outside)
  const std::vector<std::string> shown = this->layers_shown_();
  for (int i = 0; i < n; i++) {
    const std::string name = is_maps ? this->map_name_(this->pill_ids_[i]) : this->map_->layers[i].name;
    const bool on = is_maps ? this->pill_ids_[i] == this->map_->id
                            : std::find(shown.begin(), shown.end(), this->map_->layers[i].id) != shown.end();
    lv_obj_t *p = this->nav_pill_(list, name, on, false);
    lv_obj_set_width(p, 220 - 16);
    lv_obj_set_pos(p, 0, i * (NAV_PILL_H + 6));
    lv_obj_add_flag(p, LV_OBJ_FLAG_SCROLL_CHAIN_VER);
    lv_obj_set_user_data(p, (void *) (uintptr_t) i);
    lv_obj_add_event_cb(p, is_maps ? &MapView::on_map_pill_ : &MapView::on_layer_pill_, LV_EVENT_CLICKED, this);
    // (then the list closes - after the pill's own handler, which may rebuild the bar)
    lv_obj_add_event_cb(
        p,
        [](lv_event_t *e) {
          lv_async_call([](void *q) { static_cast<MapView *>(q)->close_rooms_(); }, lv_event_get_user_data(e));
        },
        LV_EVENT_CLICKED, this);
  }
  if (scrolls)
    dragbar_attach(this->rooms_scrim_, list, this->rt_->color("textSecondary", 0x9E9E9E));
}

std::string MapView::map_name_(const std::string &id) const {
  if (this->model_ != nullptr)
    for (auto &m : this->model_->maps)
      if (m->id == id)
        return m->name;
  return id;
}

void MapView::paint_pill_(lv_obj_t *p, bool on) {
  const uint32_t accent = this->rt_->color("accent", 0x4B9EF3);
  lv_obj_set_style_bg_color(p, lv_color_hex(on ? accent : this->rt_->color("button", 0x333333)), 0);
  lv_obj_set_style_border_color(p, lv_color_hex(on ? accent : this->rt_->color("tileBorder", 0x4A4A4A)), 0);
  const uint32_t ink = on ? this->rt_->color("onAccent", 0xFFFFFF) : this->rt_->color("text", 0xFFFFFF);
  for (uint32_t i = 0; i < lv_obj_get_child_count(p); i++)
    lv_obj_set_style_text_color(lv_obj_get_child(p, (int32_t) i), lv_color_hex(ink), 0);
}

// The layer pills: lit while their layer shows (several at once)
void MapView::paint_layer_pills_() {
  if (!this->map_)
    return;
  const std::vector<std::string> shown = this->layers_shown_();
  if (this->layer_menu_label_ != nullptr) {
    // collapsed: the deepest layer showing now (the zoom's)
    std::string cur = this->map_->layers.empty() ? "" : this->map_->layers.front().name;
    for (const auto &l : this->map_->layers)
      if (std::find(shown.begin(), shown.end(), l.id) != shown.end())
        cur = l.name;
    lv_label_set_text(this->layer_menu_label_, cur.c_str());
  }
  for (size_t i = 0; i < this->layer_pills_.size() && i < this->map_->layers.size(); i++)
    this->paint_pill_(this->layer_pills_[i],
                      std::find(shown.begin(), shown.end(), this->map_->layers[i].id) != shown.end());
}

// A layer's pill: to where it starts
void MapView::on_layer_pill_(lv_event_t *e) {
  auto *self = static_cast<MapView *>(lv_event_get_user_data(e));
  const size_t i = (size_t) (uintptr_t) lv_obj_get_user_data(lv_event_get_target_obj(e));
  if (!self->map_ || i >= self->map_->layers.size())
    return;
  // (leaving a room's view rebuilds the bar - this pill: after its event)
  self->pending_zoom_ = std::max(1.0f, self->map_->layers[i].min_zoom);
  lv_async_call([](void *p) {
    auto *v = static_cast<MapView *>(p);
    if (v->open_)
      v->zoom_to_(v->pending_zoom_);
  }, self);
}

void MapView::on_close_(lv_event_t *e) {
  auto *self = static_cast<MapView *>(lv_event_get_user_data(e));
  if (self->deliberate_press_())
    self->close();
}

void MapView::on_back_(lv_event_t *e) {
  if (!static_cast<MapView *>(lv_event_get_user_data(e))->deliberate_press_())
    return;
  // (rebuilding the bar deletes this button: after its event)
  lv_async_call([](void *p) { static_cast<MapView *>(p)->go_to_zone_(nullptr); }, lv_event_get_user_data(e));
}

void MapView::on_zoom_in_(lv_event_t *e) { static_cast<MapView *>(lv_event_get_user_data(e))->zoom_by_(1); }
void MapView::on_zoom_out_(lv_event_t *e) { static_cast<MapView *>(lv_event_get_user_data(e))->zoom_by_(-1); }

void MapView::on_scroll_(lv_event_t *e) {
  auto *self = static_cast<MapView *>(lv_event_get_user_data(e));
  self->cam_x_ = lv_obj_get_scroll_x(self->area_);
  self->cam_y_ = lv_obj_get_scroll_y(self->area_);
  self->request_tiles_();
}

void MapView::on_drag_(lv_event_t *e) {
  auto *self = static_cast<MapView *>(lv_event_get_user_data(e));
  const lv_event_code_t code = lv_event_get_code(e);
  if (code == LV_EVENT_PRESSED) {
    self->panning_ = false;
    self->drag_x_ = self->drag_y_ = 0;
    self->drag_rest_x_ = 0;
  } else if (code == LV_EVENT_PRESSING) {
    lv_indev_t *in = lv_indev_active();
    if (in == nullptr)
      return;
    lv_point_t v;
    lv_indev_get_vect(in, &v);
    self->drag_x_ += v.x;
    self->drag_y_ += v.y;
    if (!self->panning_) {
      if (abs(self->drag_x_) < DRAG_PX && abs(self->drag_y_) < DRAG_PX)
        return;
      self->panning_ = true;
      self->markers_lite_(true);
      self->phase_(PAN, "Map pan");
      v.x = self->drag_x_;  // (catch up with the movement so far)
      v.y = self->drag_y_;
    }
    // sideways in 2 px steps (the scroll stays even - map_view.h)
    self->drag_rest_x_ += v.x;
    const int dx = self->drag_rest_x_ - self->drag_rest_x_ % 2;
    self->drag_rest_x_ -= dx;
    if (dx != 0 || v.y != 0)
      lv_obj_scroll_by_bounded(self->area_, dx, v.y, LV_ANIM_OFF);
  } else if ((code == LV_EVENT_RELEASED || code == LV_EVENT_PRESS_LOST) && self->phase_kind_ == PAN) {
    self->markers_lite_(false);
    self->phase_(IDLE, "Map idle");
  }
}

// A tap (not a drag): the room under it, zoomed to
bool MapView::press_near_zoom_box_() const {
  if (this->zoom_box_ == nullptr)
    return false;
  lv_area_t a;
  lv_obj_get_coords(this->zoom_box_, &a);  // (also while it shows as a picture)
  const lv_point_t &p = this->press_at_;
  const int m = ZOOM_BOX_NO_TAP;
  return p.x >= a.x1 - m && p.x <= a.x2 + m && p.y >= a.y1 - m && p.y <= a.y2 + m;
}

void MapView::on_tap_(lv_event_t *e) {
  auto *self = static_cast<MapView *>(lv_event_get_user_data(e));
  if (!self->map_ || self->panning_ || lv_event_get_target_obj(e) != self->area_)
    return;  // (a drag; a marker's tap, come up from it)
  if (self->press_near_zoom_box_())
    return;
  lv_point_t p;
  lv_indev_get_point(lv_indev_active(), &p);
  const MapSpec &m = *self->map_;
  const float mx = m.bounds[0] + (p.x + self->cam_x_ - self->off_x_) / self->k_;
  const float my = m.bounds[1] + (p.y - self->area_y_ + self->cam_y_ - self->off_y_) / self->k_;
  const MapZone *z = self->zone_at_(mx, my);
  if (self->queue_mode_) {  // queue mode: queue the room / take it off (no zooming)
    if (z != nullptr)
      self->queue_tap_(*z);
    return;
  }
  if (z != nullptr && z->id != self->zone_)
    lv_async_call(
        [](void *arg) {
          auto *s = static_cast<MapView *>(arg);
          // (looked up again: the payload may have changed meanwhile)
          const MapZone *zz = s->zone_at_(s->tap_x_, s->tap_y_);
          if (zz != nullptr)
            s->go_to_zone_(zz);
        },
        self);
  self->tap_x_ = mx;
  self->tap_y_ = my;
}

// The smallest room (not a vacuum's zone) containing the point (a closet in a bedroom: the closet)
const MapZone *MapView::zone_at_(float mx, float my) const {
  const MapZone *best = nullptr;
  float best_area = 0;
  for (const MapZone &z : this->map_->zones) {
    if (!this->zone_shown_(z) || z.points.size() < 3)
      continue;
    if (z.area.empty() && z.name.find_first_not_of(' ') == std::string::npos)
      continue;
    bool in = false;
    float area = 0;
    for (size_t i = 0, j = z.points.size() - 1; i < z.points.size(); j = i++) {
      const Pt &a = z.points[j], &b = z.points[i];
      if ((a.y > my) != (b.y > my) && mx < a.x + (my - a.y) * (b.x - a.x) / (b.y - a.y))
        in = !in;
      area += a.x * b.y - b.x * a.y;
    }
    area = fabsf(area) / 2;
    if (in && (best == nullptr || area < best_area)) {
      best = &z;
      best_area = area;
    }
  }
  return best;
}

void MapView::go_to_zone_(const MapZone *z) {
  if (!this->map_)
    return;
  const MapSpec &m = *this->map_;
  this->zone_ = z ? z->id : "";
  this->build_bar_();
  if (z == nullptr) {
    this->set_view_(1, (m.bounds[0] + m.bounds[2]) / 2, (m.bounds[1] + m.bounds[3]) / 2);
    return;
  }
  float x0 = 1e30f, y0 = 1e30f, x1 = -1e30f, y1 = -1e30f;
  for (const Pt &p : z->points) {
    x0 = std::min(x0, p.x);
    y0 = std::min(y0, p.y);
    x1 = std::max(x1, p.x);
    y1 = std::max(y1, p.y);
  }
  const float w = (x1 - x0) * (1 + 2 * ZONE_MARGIN), h = (y1 - y0) * (1 + 2 * ZONE_MARGIN);
  const float k = std::min(AREA_W / std::max(w, 1e-3f), this->area_h_ / std::max(h, 1e-3f));
  this->set_view_(k / this->k0_, (x0 + x1) / 2, (y0 + y1) / 2);
}

// The zoom buttons: to the next 0.25 step, about the middle of the view
void MapView::zoom_by_(int dir) {
  if (!this->map_)
    return;
  const float n = dir > 0 ? floorf(this->zoom_ / ZOOM_STEP + 1e-3f) + 1 : ceilf(this->zoom_ / ZOOM_STEP - 1e-3f) - 1;
  this->zoom_to_(n * ZOOM_STEP);
}

// To zoom `z` about the middle of the view (out of a room's view)
void MapView::zoom_to_(float z) {
  if (!this->map_)
    return;
  z = std::max(1.0f, std::min(this->max_zoom_, z));
  if (fabsf(z - this->zoom_) < 0.005f) {
    this->paint_zoom_box_();  // (the roller back on the step it shows)
    return;
  }
  const MapSpec &m = *this->map_;
  const float cx = m.bounds[0] + (this->cam_x_ - this->off_x_ + AREA_W / 2.0f) / this->k_;
  const float cy = m.bounds[1] + (this->cam_y_ - this->off_y_ + this->area_h_ / 2.0f) / this->k_;
  if (!this->zone_.empty()) {
    this->zone_.clear();
    this->build_bar_();
  }
  this->set_view_(z, cx, cy);
}

void MapView::on_map_pill_(lv_event_t *e) {
  auto *self = static_cast<MapView *>(lv_event_get_user_data(e));
  const size_t i = (size_t) (uintptr_t) lv_obj_get_user_data(lv_event_get_target_obj(e));
  if (i >= self->pill_ids_.size() || self->model_ == nullptr)
    return;
  const std::string id = self->pill_ids_[i];
  // (rebuilding the bar deletes this pill: after its event)
  lv_async_call(
      [](void *p) {
        auto *s = static_cast<MapView *>(p);
        if (s->open_ && s->model_ != nullptr) {
          s->opening_queue_ = s->queue_mode_;  // (queue mode stays: another of its maps)
          s->open(*s->model_, s->map_id_, "");
          s->opening_queue_ = false;
        }
      },
      self);
  self->map_id_ = id;
}

// ---- go to a room (the title's list) ---------------------------------------------------

// The whole map, then this map's rooms A-Z (not a hidden area's); a tap goes there
void MapView::open_rooms_() {
  if (!this->map_ || this->model_ == nullptr || this->rooms_scrim_ != nullptr)
    return;
  const MapSpec &m = *this->map_;
  auto title_of = [&](const MapZone &z) {
    std::string t = z.name;
    if (t.find_first_not_of(' ') == std::string::npos)
      for (const AreaSpec &a : this->model_->areas)
        if (a.id == z.area)
          t = a.name;
    return t.find_first_not_of(' ') == std::string::npos ? std::string() : t;
  };
  struct Room {
    std::string title, id;
  };
  std::vector<Room> rooms;
  for (const MapZone &z : m.zones) {
    if (!z.vacuum.empty())
      continue;
    bool shown_area = z.area.empty();
    for (const AreaSpec &a : this->model_->areas)
      shown_area |= a.id == z.area;
    const std::string t = title_of(z);
    if (shown_area && !t.empty())
      rooms.push_back({t, z.id});
  }
  std::sort(rooms.begin(), rooms.end(), [](const Room &a, const Room &b) { return a.title < b.title; });
  this->room_ids_.clear();
  this->room_ids_.push_back("");  // (the whole map)
  for (auto &r : rooms)
    this->room_ids_.push_back(r.id);

  // a scrim (a tap outside closes) and the list under the title
  this->rooms_scrim_ = lv_obj_create(this->root_);
  lv_obj_remove_style_all(this->rooms_scrim_);
  lv_obj_set_size(this->rooms_scrim_, 1024, 600);
  lv_obj_add_flag(this->rooms_scrim_, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_event_cb(
      this->rooms_scrim_,
      [](lv_event_t *e) {
        lv_async_call([](void *p) { static_cast<MapView *>(p)->close_rooms_(); }, lv_event_get_user_data(e));
      },
      LV_EVENT_CLICKED, this);
  const int bw = 300, bh = 52, gap = 6;
  const int n = (int) this->room_ids_.size();
  const int full = n * (bh + gap) + gap + 12;
  const int h = std::min(600 - BAR_H - 16, full);
  const bool scrolls = full > h;  // (then wider: the scroll bar's strip beside the rooms)
  lv_obj_t *list = lv_obj_create(this->rooms_scrim_);
  lv_obj_remove_style_all(list);
  lv_obj_set_pos(list, 12, BAR_H + 4);
  lv_obj_set_size(list, bw + 24 + (scrolls ? 32 : 0), h);
  lv_obj_set_style_bg_color(list, lv_color_hex(this->rt_->color("dialog", 0x2A2A2A)), 0);
  lv_obj_set_style_bg_opa(list, LV_OPA_COVER, 0);
  lv_obj_set_style_border_width(list, 1, 0);
  lv_obj_set_style_border_color(list, lv_color_hex(this->rt_->color("tileBorder", 0x4A4A4A)), 0);
  lv_obj_set_style_radius(list, 14, 0);
  lv_obj_set_style_pad_all(list, 12, 0);
  lv_obj_set_scroll_dir(list, LV_DIR_VER);
  lv_obj_add_flag(list, LV_OBJ_FLAG_CLICKABLE);  // (a tap in it isn't a tap outside)
  const uint32_t accent = this->rt_->color("accent", 0x4B9EF3), text = this->rt_->color("text", 0xFFFFFF);
  for (int i = 0; i < n; i++) {
    const bool on = this->room_ids_[i] == this->zone_;
    lv_obj_t *b = lv_obj_create(list);
    lv_obj_remove_style_all(b);
    lv_obj_set_size(b, bw, bh);
    lv_obj_set_pos(b, 0, i * (bh + gap));
    lv_obj_set_style_radius(b, 10, 0);
    lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(b, lv_color_hex(on ? accent : this->rt_->color("button", 0x333333)), 0);
    lv_obj_remove_flag(b, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(b, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_flag(b, LV_OBJ_FLAG_SCROLL_CHAIN_VER);
    lv_obj_set_user_data(b, (void *) (uintptr_t) i);
    lv_obj_add_event_cb(
        b,
        [](lv_event_t *e) {
          auto *self = static_cast<MapView *>(lv_event_get_user_data(e));
          self->picked_room_ = (int) (uintptr_t) lv_obj_get_user_data(lv_event_get_current_target_obj(e));
          lv_async_call(
              [](void *p) {
                auto *s = static_cast<MapView *>(p);
                const int k = s->picked_room_;
                const std::string id = k >= 0 && k < (int) s->room_ids_.size() ? s->room_ids_[k] : "";
                s->close_rooms_();
                const MapZone *z = nullptr;
                if (s->map_)
                  for (const MapZone &zz : s->map_->zones)
                    if (!id.empty() && zz.id == id)
                      z = &zz;
                s->go_to_zone_(z);
              },
              self);
        },
        LV_EVENT_CLICKED, this);
    int tx = 14;
    if (i == 0) {  // the whole map: the floor-plan mark before it
      lv_obj_t *g = lv_label_create(b);
      lv_label_set_text(g, "\U000F0821");
      lv_obj_set_style_text_font(g, this->fonts_->glyph, 0);
      lv_obj_set_style_text_color(g, lv_color_hex(on ? this->rt_->color("onAccent", 0xFFFFFF) : accent), 0);
      lv_obj_align(g, LV_ALIGN_LEFT_MID, 12, 0);
      tx = 52;
    }
    lv_obj_t *l = lv_label_create(b);
    lv_label_set_text(l, i == 0 ? this->rt_->t("panel.whole_map").c_str() : rooms[i - 1].title.c_str());
    lv_label_set_long_mode(l, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_width(l, bw - tx - 14);
    lv_obj_set_style_text_font(l, this->fonts_->name, 0);
    lv_obj_set_style_text_color(l, lv_color_hex(on ? this->rt_->color("onAccent", 0xFFFFFF) : text), 0);
    lv_obj_align(l, LV_ALIGN_LEFT_MID, tx, 0);
  }
  // a scroll bar you can drag, when there are more rooms than fit (the area picker's)
  if (scrolls)
    dragbar_attach(this->rooms_scrim_, list, this->rt_->color("textSecondary", 0x9E9E9E));
}

void MapView::close_rooms_() {
  if (this->rooms_scrim_ == nullptr)
    return;
  lv_obj_delete(this->rooms_scrim_);
  this->rooms_scrim_ = nullptr;
}

// ---- one map ------------------------------------------------------------------------

void MapView::show_map_(const std::shared_ptr<const MapSpec> &m) {
  // its index + gen: kept while the payload brings the same MapSpec
  Known &kn = this->known_[m->id];
  if (kn.spec != m) {
    const uint32_t t0 = millis();
    kn.spec = m;
    kn.index = std::make_shared<const MapIndex>(*m);
    kn.gen = this->next_gen_++;
    ESP_LOGD(TAG, "Map %s: %u items indexed in %u ms", m->id.c_str(), (unsigned) kn.index->size(),
             (unsigned) (millis() - t0));
  }
  const bool same = this->map_ == m && this->base_gen_ == kn.gen && !this->queue_mode_ && !this->style_;
  this->map_ = m;
  this->map_id_ = m->id;
  this->index_ = kn.index;
  this->base_gen_ = this->gen_ = kn.gen;
  if (this->queue_mode_)
    this->queue_restyle_();  // (the queue's look: its own gen)
  else
    this->style_.reset();
  if (same) {  // (reopened: where it was left - its markers and names made again)
    this->build_bar_();
    this->build_labels_();
    this->build_markers_();
    return;
  }
  this->zone_.clear();
  this->build_bar_();

  MapColors c;
  c.bg = this->rt_->color("mapBg", c.bg);
  c.floor = this->rt_->color("mapFloor", c.floor);
  c.wall = this->rt_->color("mapWall", c.wall);
  c.window = this->rt_->color("mapWindow", c.window);
  c.water = this->rt_->color("mapWater", c.water);
  c.grass = this->rt_->color("mapGrass", c.grass);
  c.deck = this->rt_->color("mapDeck", c.deck);
  c.paving = this->rt_->color("mapPaving", c.paving);
  this->colors_ = c;
  if (this->blank_ != nullptr && this->blank_rgb_ != c.bg) {
    this->blank_rgb_ = c.bg;
    for (uint16_t &e : this->blank_->c565)
      e = rgb565(c.bg);
    lv_image_cache_drop(&this->blank_->dsc);
  }

  // MIRRORED: frontend/src/map.ts REF_VIEW / zoom number - a change here must be made there too.
  // zoom 1: the whole map just fits the area (the dashboard's zoom number)
  const float bw = std::max(1.0f, m->bounds[2] - m->bounds[0]);
  const float bh = std::max(1.0f, m->bounds[3] - m->bounds[1]);
  // (the panels' whole map area, even with the queue's bar: zoom numbers
  // mean the same everywhere - the dashboard's REF_VIEW)
  this->k0_ = std::min(AREA_W / bw, AREA_H / bh);
  const float max_zoom = this->view_max_zoom_(*m);
  if (max_zoom != this->max_zoom_) {
    this->max_zoom_ = max_zoom;
    this->set_zoom_steps_();
  }
  this->zoom_ = 0;  // (forces the new map's tiles + labels)
  this->set_view_(1, m->bounds[0] + bw / 2, m->bounds[1] + bh / 2);
}

void MapView::set_view_(float zoom, float cx, float cy) {
  const MapSpec &m = *this->map_;
  zoom = roundf(std::max(1.0f, std::min(this->max_zoom_, zoom)) * 100) / 100;  // (tiles are keyed by it)
  if (zoom != this->zoom_) {
    this->zoom_ = zoom;
    this->k_ = this->k0_ * zoom;
    this->map_w_ = std::max(1, (int) ceilf((m.bounds[2] - m.bounds[0]) * this->k_));
    this->map_h_ = std::max(1, (int) ceilf((m.bounds[3] - m.bounds[1]) * this->k_));
    // the tiles cover the area at least (a smaller map: centred in them)
    this->content_w_ = (std::max(this->map_w_, AREA_W) + 1) & ~1;  // (even: its far edge at an even scroll)
    this->content_h_ = std::max(this->map_h_, this->area_h_);
    this->off_x_ = (this->content_w_ - this->map_w_) / 2;
    this->off_y_ = (this->content_h_ - this->map_h_) / 2;
    this->epoch_++;  // (tiles queued for the old zoom: dropped)
    // the old zoom's tiles leave the screen (they stay in the pool); the new
    // ones show all at once when they're all drawn - the plain tile meanwhile
    for (auto &s : this->slots_)
      s.shown = nullptr;
    this->revealing_ = true;
    lv_obj_invalidate(this->tiles_layer_);
    lv_obj_set_size(this->content_, this->content_w_, this->content_h_);
    lv_obj_set_size(this->tiles_layer_, this->content_w_, this->content_h_);
    lv_obj_set_size(this->markers_layer_, this->content_w_, this->content_h_);
    lv_obj_set_size(this->labels_layer_, this->content_w_, this->content_h_);
    lv_obj_set_size(this->badges_layer_, this->content_w_, this->content_h_);
    this->build_labels_();
    this->build_badges_();
    this->build_markers_();  // (their places follow the zoom; so do the layers shown)
    this->missing_since_ = millis();
    if (!this->opening_) {  // (opening: its own phase, "Map open")
      char b[32];
      snprintf(b, sizeof(b), "Map zoom %.2fx", zoom);
      this->phase_(ZOOM, b);
    }
  }
  // (cx, cy) in the middle, inside the map's edges
  lv_obj_update_layout(this->area_);
  const int sx = std::max(0, std::min(this->content_w_ - AREA_W,
                                      (int) lroundf((cx - m.bounds[0]) * this->k_ + this->off_x_ - AREA_W / 2.0f))) &
                 ~1;  // (even - map_view.h)
  const int sy = std::max(0, std::min(this->content_h_ - this->area_h_,
                                      (int) lroundf((cy - m.bounds[1]) * this->k_ + this->off_y_ - this->area_h_ / 2.0f)));
  lv_obj_scroll_to(this->area_, sx, sy, LV_ANIM_OFF);
  this->cam_x_ = lv_obj_get_scroll_x(this->area_);
  this->cam_y_ = lv_obj_get_scroll_y(this->area_);
  this->paint_zoom_box_();
  this->request_tiles_();
}

void MapView::build_labels_() {
  PsramScope psram;  // (psram_scope.h)
  this->labels_.clear();
  lv_obj_invalidate(this->labels_layer_);
  const MapSpec &m = *this->map_;
  const uint32_t in = this->rt_->color("mapLabel", 0x2B3240), out = this->rt_->color("mapLabelOut", 0x8A8F98);
  for (const MapZone &z : m.zones) {
    if (!this->zone_shown_(z) || z.name.find_first_not_of(' ') == std::string::npos)
      continue;  // (vacuum zones: the vacuum's view; a room with no name: no label)
    Pt at = z.label;
    if (!z.has_label) {  // the middle of its box
      float x0 = 1e30f, y0 = 1e30f, x1 = -1e30f, y1 = -1e30f;
      for (const Pt &p : z.points) {
        x0 = std::min(x0, p.x);
        y0 = std::min(y0, p.y);
        x1 = std::max(x1, p.x);
        y1 = std::max(y1, p.y);
      }
      at = Pt{(x0 + x1) / 2, (y0 + y1) / 2};
    }
    // a pre-rendered picture of its name (sprite.h), centred on the point;
    // a vertical room's reads upwards
    Sprite *sp = this->label_sprite_(z.name, z.outdoor ? out : in, z.vertical);
    if (sp == nullptr)
      continue;
    this->labels_.push_back(LabelView{sp, (int) lroundf((at.x - m.bounds[0]) * this->k_) + this->off_x_ - sp->w / 2,
                                      (int) lroundf((at.y - m.bounds[1]) * this->k_) + this->off_y_ - sp->h / 2});
  }
}

// ---- tiles --------------------------------------------------------------------------

// Its place is on screen at this zoom (whatever its look)
bool MapView::on_screen_(const Key &k) const {
  if (k.zoom_q != (int) lroundf(this->zoom_ * 100))
    return false;
  const int x = k.tx * TILE - this->cam_x_, y = k.ty * TILE - this->cam_y_;
  return x < AREA_W && y < this->area_h_ && x + TILE > 0 && y + TILE > 0;
}

// A tile of the current look, on screen
bool MapView::visible_(const Key &k) const { return k.gen == this->gen_ && this->on_screen_(k); }

// A free buffer, else the least recently used one not on screen / being drawn.
int MapView::take_slot_() {
  int best = -1;
  for (int i = 0; i < SLOTS; i++) {
    Slot &s = this->slots_[i];
    if (!s.used) {
      if (s.sp == nullptr) {
        s.sp = sprite_new(TILE, TILE, false);
        if (s.sp == nullptr) {
          ESP_LOGW(TAG, "No PSRAM for map tile %d", i);
          continue;
        }
      }
      return i;
    }
    // (on screen: the current look's, or an older look's still shown there)
    if (s.queued || (this->on_screen_(s.key) && (s.key.gen == this->gen_ || s.shown != nullptr)))
      continue;
    if (best < 0 || (int32_t) (s.touched - this->slots_[best].touched) < 0)
      best = i;
  }
  if (best >= 0)
    this->drop_slot_(this->slots_[best]);
  return best;
}

void MapView::drop_slot_(Slot &s) {
  this->hide_(s);
  if (s.ready && s.sp != nullptr)
    lv_image_cache_drop(&s.sp->dsc);  // (its pixels are about to change)
  this->lookup_.erase(s.key);
  s.used = s.ready = false;
}

// A tile on screen: its picture, or the plain one until it's drawn
void MapView::place_(Slot &s) {
  const Sprite *src = s.ready && !s.blank ? s.sp : this->blank_;
  if (s.shown == src)
    return;
  s.shown = src;
  this->invalidate_in_(this->tiles_layer_, s.key.tx * TILE, s.key.ty * TILE, src);
  if (s.ready && s.key.gen == this->gen_)
    this->drop_prev_(s.key);  // (drawn: the previous look's tile under it goes)
}

// A new look of the same map (the queue changed - often several times in a
// moment: the queue, the room being cleaned, the vacuum's state): its tiles
// are drawn while whatever is on screen at each place stays - an older
// look's tile - until the newest look's is ready. No blank tiles in between.
bool MapView::prev_shows_(const Key &k) const {
  for (const Slot &s : this->slots_)
    if (s.shown != nullptr && s.key.gen != this->gen_ && s.key.zoom_q == k.zoom_q && s.key.tx == k.tx && s.key.ty == k.ty)
      return true;
  return false;
}

void MapView::drop_prev_(const Key &k) {
  for (Slot &s : this->slots_)
    if (s.shown != nullptr && s.key.gen != this->gen_ && s.key.zoom_q == k.zoom_q && s.key.tx == k.tx && s.key.ty == k.ty)
      this->hide_(s);
}

// The plain tile in a slot's place (a reveal: what's drawn shows at the end)
void MapView::place_plain_(Slot &s) {
  if (s.shown == this->blank_)
    return;
  s.shown = this->blank_;
  this->invalidate_in_(this->tiles_layer_, s.key.tx * TILE, s.key.ty * TILE, this->blank_);
}

void MapView::hide_(Slot &s) {
  if (s.shown == nullptr)
    return;
  this->invalidate_in_(this->tiles_layer_, s.key.tx * TILE, s.key.ty * TILE, s.shown);
  s.shown = nullptr;
}

// (x, y) in the layer: that sprite's area to be drawn again
void MapView::invalidate_in_(lv_obj_t *layer, int x, int y, const Sprite *sp) {
  if (layer == nullptr || sp == nullptr)
    return;
  lv_area_t c;
  lv_obj_get_coords(layer, &c);
  const lv_area_t a{c.x1 + x, c.y1 + y, c.x1 + x + sp->w - 1, c.y1 + y + sp->h - 1};
  lv_obj_invalidate_area(layer, &a);
}

// The map's pictures back in internal RAM while it's open (moved out when it
// closes): the zoom box's first, then the rest while there's room
void MapView::pictures_to_internal_() {
  sprite_to_internal(this->zoom_sprite_);
  for (auto &kv : this->sprites_)
    sprite_to_internal(kv.second);
}

// ---- one draw per layer -------------------------------------------------------------

// the tiles on screen: the previous look's first (a new look's tile covers it)
void MapView::on_draw_tiles_(lv_event_t *e) {
  auto *self = static_cast<MapView *>(lv_event_get_user_data(e));
  lv_layer_t *layer = lv_event_get_layer(e);
  lv_area_t c;
  lv_obj_get_coords(self->tiles_layer_, &c);
  const lv_area_t &clip = layer->_clip_area;
  SpriteBlit items[SLOTS];
  int n = 0;
  for (int pass = 0; pass < 2; ++pass)
    for (const Slot &s : self->slots_)
      if (s.shown != nullptr && (s.key.gen == self->gen_) == (pass == 1)) {
        const int x = c.x1 + s.key.tx * TILE, y = c.y1 + s.key.ty * TILE;
        if (x > clip.x2 || y > clip.y2 || x + TILE <= clip.x1 || y + TILE <= clip.y1)
          continue;  // (not in this strip)
        items[n++] = SpriteBlit{s.shown, x, y};
      }
  // (both cores: sprite.h)
  sprite_draw_tiles(layer, items, n);
}

// each marker's face (a later one over an earlier); their names: the labels
// layer, over them all
void MapView::on_draw_markers_(lv_event_t *e) {
  auto *self = static_cast<MapView *>(lv_event_get_user_data(e));
  lv_layer_t *layer = lv_event_get_layer(e);
  for (const MarkerView &mv : self->markers_) {
    if (mv.face_sp != nullptr) {
      lv_area_t f;
      lv_obj_get_coords(mv.face, &f);
      sprite_draw(layer, mv.face_sp, f.x1, f.y1, mv.opa);
    }
  }
}

void MapView::on_draw_labels_(lv_event_t *e) {
  auto *self = static_cast<MapView *>(lv_event_get_user_data(e));
  lv_layer_t *layer = lv_event_get_layer(e);
  lv_area_t c;
  lv_obj_get_coords(self->labels_layer_, &c);
  // the markers' names: over every marker - the animated ones too (objects in
  // the markers layer, drawn after its own pictures)
  lv_area_t m;
  lv_obj_get_coords(self->markers_layer_, &m);
  for (const MarkerView &mv : self->markers_)
    if (mv.name_sp != nullptr)
      sprite_draw(layer, mv.name_sp, m.x1 + mv.name_x, m.y1 + mv.name_y);
  // the rooms' names
  for (const LabelView &l : self->labels_)
    sprite_draw(layer, l.sp, c.x1 + l.x, c.y1 + l.y);
}

// The tiles on screen: drawn ones shown, missing ones queued (nearest the
// middle first).
void MapView::request_tiles_() {
  const int zq = (int) lroundf(this->zoom_ * 100);
  const int nx = (this->content_w_ + TILE - 1) / TILE, ny = (this->content_h_ + TILE - 1) / TILE;
  // on screen, then a ring of one tile around it (panning finds them drawn)
  const int vx0 = (int) floorf((float) this->cam_x_ / TILE), vy0 = (int) floorf((float) this->cam_y_ / TILE);
  const int vx1 = (int) floorf((float) (this->cam_x_ + AREA_W - 1) / TILE);
  const int vy1 = (int) floorf((float) (this->cam_y_ + this->area_h_ - 1) / TILE);
  const int tx0 = std::max(0, vx0 - 1), ty0 = std::max(0, vy0 - 1);
  const int tx1 = std::min(nx - 1, vx1 + 1), ty1 = std::min(ny - 1, vy1 + 1);
  struct Want {
    int tx, ty;
    bool ring;
    float d;
  };
  std::vector<Want> want;
  const float mx = this->cam_x_ + AREA_W / 2.0f, my = this->cam_y_ + this->area_h_ / 2.0f;
  for (int ty = ty0; ty <= ty1; ty++)
    for (int tx = tx0; tx <= tx1; tx++) {
      const float dx = tx * TILE + TILE / 2 - mx, dy = ty * TILE + TILE / 2 - my;
      want.push_back(Want{tx, ty, tx < vx0 || tx > vx1 || ty < vy0 || ty > vy1, dx * dx + dy * dy});
    }
  std::sort(want.begin(), want.end(), [](const Want &a, const Want &b) { return a.ring != b.ring ? !a.ring : a.d < b.d; });
  this->tick_++;
  int missing = 0;    // on screen, not drawn yet
  int uncovered = 0;  // on screen with no buffer at all (every one busy)
  for (const Want &w : want) {
    const Key key{this->gen_, zq, w.tx, w.ty};
    auto it = this->lookup_.find(key);
    if (it != this->lookup_.end()) {
      Slot &s = this->slots_[it->second];
      s.touched = this->tick_;
      if (!w.ring) {
        if (this->revealing_) {
          if (!this->prev_shows_(key))
            this->place_plain_(s);  // (drawn or not: all at once at the end)
        } else if (s.ready || !this->prev_shows_(key)) {
          this->place_(s);
        }
      }
      if (s.ready)
        continue;
      missing += !w.ring;
      if (s.queued)
        continue;
      // (dropped by the task: an old epoch) - queue it again below
      this->drop_slot_(s);
    } else {
      missing += !w.ring;
    }
    const int i = this->take_slot_();
    if (i < 0) {
      uncovered += !w.ring;  // every buffer busy: again on the next loop
      continue;
    }
    Slot &s = this->slots_[i];
    s.key = key;
    s.used = true;
    s.touched = this->tick_;
    this->lookup_[key] = i;
    // the tile in the map's pixels: wholly past its edges = the plain tile
    const int px = w.tx * TILE - this->off_x_, py = w.ty * TILE - this->off_y_;
    if (px >= this->map_w_ || py >= this->map_h_ || px + TILE <= 0 || py + TILE <= 0) {
      s.ready = true;
      s.queued = false;
      s.blank = true;
      missing -= !w.ring;
      if (!w.ring)
        this->place_(s);
      continue;
    }
    s.ready = false;
    s.queued = true;
    s.blank = false;
    Job *j = new Job{i, this->epoch_.load(), this->map_, this->index_, this->colors_, this->style_, this->k_, px, py, s.sp};
    if (xQueueSend(this->jobs_, &j, 0) != pdTRUE) {
      delete j;
      s.queued = false;
      this->lookup_.erase(key);
      s.used = false;
      uncovered += !w.ring;
      continue;
    }
    if (!w.ring && !this->prev_shows_(key))
      this->place_(s);  // (plain until it's drawn - or the previous look meanwhile)
  }
  if (missing > 0 && this->missing_ == 0)
    this->missing_since_ = millis();
  this->missing_ = missing;
  if (this->revealing_ && missing == 0 && uncovered == 0) {
    // every tile on screen drawn: they all show at once
    this->revealing_ = false;
    for (const Want &w : want) {
      if (w.ring)
        continue;
      auto it = this->lookup_.find(Key{this->gen_, zq, w.tx, w.ty});
      if (it != this->lookup_.end() && this->slots_[it->second].ready)
        this->place_(this->slots_[it->second]);
    }
  }
  // the area's own fill: only if a tile on screen has nothing to show (else they cover it)
  if ((uncovered > 0) != this->area_filled_) {
    this->area_filled_ = uncovered > 0;
    lv_obj_set_style_bg_opa(this->area_, this->area_filled_ ? LV_OPA_COVER : LV_OPA_TRANSP, 0);
  }
}

void MapView::worker_(void *arg) {
  auto *self = static_cast<MapView *>(arg);
  // a tile is drawn in RGB565 here, then made a 4-bit sprite (its 16 most
  // used colours; the anti-aliased edges round to the nearest)
  auto *rgb = static_cast<uint16_t *>(heap_caps_aligned_alloc(64, TILE * TILE * 2, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  auto *counts = static_cast<uint32_t *>(heap_caps_calloc(65536, sizeof(uint32_t), MALLOC_CAP_SPIRAM));
  auto *cmap = static_cast<uint8_t *>(heap_caps_malloc(65536, MALLOC_CAP_SPIRAM));
  if (rgb == nullptr || counts == nullptr || cmap == nullptr)
    ESP_LOGE(TAG, "No PSRAM for the map's drawing task");
  for (;;) {
    Job *j = nullptr;
    if (xQueueReceive(self->jobs_, &j, portMAX_DELAY) != pdTRUE)
      continue;
    if (j->epoch == self->epoch_.load() && rgb != nullptr && counts != nullptr && cmap != nullptr) {
      const int64_t t0 = esp_timer_get_time();
      draw_map_tile(*j->map, *j->index, j->colors, j->k, j->px, j->py, rgb, TILE, j->style.get());
      sprite_quantize_565(j->sp, rgb, TILE, counts, cmap);
      j->us = (uint32_t) (esp_timer_get_time() - t0);
      j->drawn = true;
    }
    xQueueSend(self->done_, &j, portMAX_DELAY);
    vTaskDelay(1);  // (core 0's idle task: the watchdog)
  }
}

void MapView::loop() {
  if (this->done_ == nullptr) {  // (never opened yet: its pictures made ahead all the same)
    this->make_pictures_();
    return;
  }
  struct LoopTime {  // (profiling: counted however it returns)
    MapView *v;
    int64_t t0;
    ~LoopTime() {
      if (!v->open_)
        return;
      const uint32_t us = (uint32_t) (esp_timer_get_time() - t0);
      v->loop_n_++;
      v->loop_us_ += us;
      v->loop_max_us_ = std::max(v->loop_max_us_, us);
    }
  } loop_time{this, esp_timer_get_time()};
  Job *j = nullptr;
  bool got = false;
  while (xQueueReceive(this->done_, &j, 0) == pdTRUE) {
    Slot &s = this->slots_[j->slot];
    s.queued = false;
    if (j->drawn) {
      s.ready = true;
      this->batch_tiles_++;
      this->batch_us_ += j->us;
      if (this->open_ && this->visible_(s.key) && s.key.gen == this->gen_ && !this->revealing_)
        this->place_(s);  // (its picture instead of the plain one / the previous look)
    }
    delete j;
    got = true;
  }
  if (!this->open_) {
    this->make_pictures_();  // (the map closed: its pictures made ahead, a few a pass)
    return;
  }
  if (got || this->missing_ > 0)
    this->request_tiles_();
  // a zoom ends when the screen is drawn; idle is logged every 10 s
  if ((this->phase_kind_ == ZOOM && this->missing_ == 0) || (this->phase_kind_ == IDLE && this->stats_.age() > 10000))
    this->phase_(IDLE, "Map idle");
  this->markers_loop_();
  // settled: the zoom box's picture for dragging made now, not when a drag starts
  if (this->phase_kind_ == IDLE && this->missing_ == 0 && this->zoom_img_ == nullptr)
    this->make_zoom_picture_();
  BusyIcons::show(this->busy_, this->revealing_ || (this->missing_ > 0 && millis() - this->missing_since_ > BUSY_AFTER_MS));
  this->busy_icons_.animate(millis());
}

void MapView::found_seen() {
  if (this->gear_dot_ != nullptr)
    lv_obj_add_flag(this->gear_dot_, LV_OBJ_FLAG_HIDDEN);
}

}  // namespace esphome::room_tiles
