// Room Tiles panel: the map's markers (milestone 6 step 3) - the dashboard's
// map.ts markers: a 40 px face (any zoom) with the entity's icon, colour-filled
// while it's on / active, its icon gray otherwise; only the layers showing at
// this zoom. Drawn over the tiles, under the room names.
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

#include "esphome/core/hal.h"
#include "esphome/core/log.h"

#include "board.h"
#include "map_view.h"
#include "psram_scope.h"
#include "sprite.h"
#include "room_tiles.h"

namespace esphome::room_tiles {

static const char *const TAG = "room_tiles.map";

// MIRRORED: frontend/src/map.ts MARKER_PX - a change here must be made there too.
static const int MARKER_PX = 40;  // the face, on screen (map.ts MARKER_PX)
// its picture (a sprite): the face and room for the ring around it (a pop-up open)
static const int FACE_PX = 52;
static const float ZOOM_EPS = 0.005f;

// MIRRORED: frontend/src/map.ts kindFor / markerActive / markerToken - a change here must be made there too.
// ---- what a marker is (map.ts kindFor / markerActive / markerToken) -----------------

static std::string kind_of(const PanelModel &m, const std::string &entity) {
  auto it = m.entities.find(entity);
  if (it != m.entities.end() && !it->second.kind.empty())
    return it->second.kind;
  const std::string domain = entity.substr(0, entity.find('.'));
  if (domain == "light")
    return "dimmable_light";
  if (domain == "switch" || domain == "input_boolean")
    return "switch";
  for (const char *d : {"fan", "cover", "lock", "climate", "vacuum", "scene", "script"})
    if (domain == d)
      return d;
  return "appliance";
}

static bool is_light(const std::string &k) { return k == "onoff_light" || k == "dimmable_light" || k == "color_light"; }

// a vacuum's status class: Room Tiles' robot sensor ("class|text"), else its state
static std::string vac_class(const StateHub &st, const std::string &entity) {
  const std::string &tile = st.get(entity, "tile");
  if (tile.find('|') != std::string::npos)
    return field_(tile, 0);
  return st.get(entity);
}

static const char *vac_token(const std::string &cls) {
  if (cls == "cleaning")
    return "vacCleaning";
  if (cls == "returning")
    return "accent";
  if (cls == "paused")
    return "vacPaused";
  if (cls == "attention")
    return "vacAttention";
  if (cls == "error")
    return "vacError";
  return nullptr;
}

static const uint32_t FRAME_MS = 62;  // appliance animations: 16 fps (the tiles')
static const int SHEET_COLS = 8, SHEET_ROWS = 4;
static const int ANIM_PX = 30;        // the animation's window: the icon's size
static const uint32_t RUN_FLASH_MS = 1500;  // a tapped scene / script marker lights this long
static const uint32_t POPUP_IDLE_MS = 10000;  // the pop-up closes after this long untouched

// MIRRORED: frontend/src/map.ts markerActive - a change here must be made there too.
bool marker_active(const StateHub &st, const std::string &kind, const std::string &entity) {
  const std::string &s = st.get(entity);
  if (s.empty())
    return false;
  if (kind == "lock")
    return s == "unlocked";  // (highlighted = needs attention)
  if (kind == "cover")
    return s != "closed";
  if (kind == "climate")
    return s != "off";
  if (kind == "appliance" || kind == "water")
    return s != "idle" && s != "off" && s != "unavailable" && s != "unknown";
  if (kind == "vacuum")
    return vac_token(vac_class(st, entity)) != nullptr;
  if (kind == "scene")
    return false;  // (a scene has no state of its own)
  return s == "on";
}

static const char *on_token(const StateHub &st, const std::string &kind, const std::string &entity) {
  if (kind == "vacuum") {
    const char *t = vac_token(vac_class(st, entity));
    return t ? t : "accent";
  }
  if (is_light(kind) || kind == "appliance")
    return "light";
  if (kind == "climate")
    return "heat";
  if (kind == "water")
    return "mapWater";
  for (const char *k : {"switch", "fan", "cover", "lock", "scene", "script"})
    if (kind == k)
      return k;
  return "accent";
}

// fallbacks for the tokens (theme.ts dark)
static uint32_t token_fallback(const char *t) {
  static const struct {
    const char *token;
    uint32_t rgb;
  } F[] = {{"light", 0xFFB300},       {"switch", 0xE2559B},      {"fan", 0x4BC9F3},       {"cover", 0x62A363},
           {"lock", 0x9270AB},        {"heat", 0xFF5A4F},        {"mapWater", 0x29B6F6},  {"scene", 0x2EC4B6},
           {"script", 0xFF8F3F},      {"accent", 0x4B9EF3},      {"vacCleaning", 0x4CAF50}, {"vacPaused", 0xFFB300},
           {"vacAttention", 0xFF6D00}, {"vacError", 0xF44336}};
  for (auto &f : F)
    if (strcmp(f.token, t) == 0)
      return f.rgb;
  return 0x4B9EF3;
}

// MIRRORED: frontend/src/map.ts ICON + rules.ts tileIcon - a change here must be made there too.
// The marker's icon: on (colour) / off (gray) - map.ts ICON + tileIcon
static void marker_icons(const StateHub &st, const std::string &kind, const std::string &entity,
                         const std::string &hint, AssetId &on, AssetId &off) {
  on = IMG_ICON_SWITCH_MK, off = IMG_ICON_SWITCH_MK_OFF;
  auto set = [&](AssetId a, AssetId b) { on = a, off = b; };
  if (hint == "icon_garage")
    set(IMG_ICON_GARAGE_MK, IMG_ICON_GARAGE_MK_OFF);
  else if (hint == "icon_matic")
    set(IMG_ICON_MATIC_MK, IMG_ICON_MATIC_MK_OFF);
  else if (is_light(kind))
    set(IMG_ICON_LIGHT_MK, IMG_ICON_LIGHT_MK_OFF);
  else if (kind == "fan")
    set(IMG_ICON_FAN_MK, IMG_ICON_FAN_MK_OFF);
  else if (kind == "cover")
    set(IMG_ICON_BLIND_MK, IMG_ICON_BLIND_MK_OFF);
  else if (kind == "lock")
    set(IMG_ICON_KEY_MK, IMG_ICON_KEY_MK_OFF);
  else if (kind == "climate")
    set(IMG_ICON_AC_MK, IMG_ICON_AC_MK_OFF);
  else if (kind == "vacuum")
    set(IMG_ICON_ROBOT_VACUUM_MK, IMG_ICON_ROBOT_VACUUM_MK_OFF);
  else if (kind == "water") {
    // the body's picture; the combined tile's follows the mode
    std::string body = st.get(entity, "mode");
    if (body.empty())
      body = st.get(entity, "body");
    if (body == "spa")
      set(IMG_ICON_SPA_MK, IMG_ICON_SPA_MK_OFF);
    else
      set(IMG_ICON_POOL_MK, IMG_ICON_POOL_MK_OFF);
  } else if (kind == "scene")
    set(IMG_ICON_SCENE_MK, IMG_ICON_SCENE_MK_OFF);
  else if (kind == "script")
    set(IMG_ICON_SCRIPT_MK, IMG_ICON_SCRIPT_MK_OFF);
  else if (kind == "appliance" && hint == "icon_laundry")
    set(IMG_ICON_LAUNDRY_MK, IMG_ICON_LAUNDRY_MK_OFF);
  else if (kind == "appliance")
    set(IMG_ICON_DISHWASHER_MK, IMG_ICON_DISHWASHER_MK_OFF);
}

// MIRRORED: frontend/src/map.ts layersAt - a change here must be made there too.
// ---- the layers showing (map.ts layersAt) -------------------------------------------

static bool layer_shows(const MapLayer &l, float z) {
  return l.min_zoom <= z + ZOOM_EPS && (l.max_zoom <= 0 || z < l.max_zoom - ZOOM_EPS);
}

std::vector<std::string> MapView::layers_shown_() const {
  std::vector<std::string> out;
  const auto &layers = this->map_->layers;  // (sorted by their start)
  for (const MapLayer &l : layers)
    if (layer_shows(l, this->zoom_))
      out.push_back(l.id);
  // zoomed out past every start: the first layer(s), as if at their start
  if (out.empty() && !layers.empty() && this->zoom_ < layers.front().min_zoom)
    for (const MapLayer &l : layers)
      if (l.min_zoom == layers.front().min_zoom)
        out.push_back(l.id);
  if (layers.empty())
    out.push_back("house");  // (a map without layers: the default one)
  return out;
}

// ---- building / painting ------------------------------------------------------------

void MapView::build_markers_() {
  PsramScope psram;  // (on every zoom too: psram_scope.h)
  lv_obj_clean(this->markers_layer_);
  lv_obj_invalidate(this->markers_layer_);
  this->markers_.clear();
  this->links_.clear();
  if (!this->map_ || this->model_ == nullptr || this->queue_mode_)
    return;  // (queue mode: the queue's rooms only - no markers, no links)
  const MapSpec &m = *this->map_;
  const std::vector<std::string> shown = this->layers_shown_();
  auto &st = this->rt_->states();
  this->markers_.reserve(this->model_->markers.size());  // (user data: no reallocation)
  for (const MapMarker &mk : this->model_->markers) {
    if (mk.map != m.id || std::find(shown.begin(), shown.end(), mk.layer.empty() ? "house" : mk.layer) == shown.end())
      continue;
    MarkerView mv;
    mv.view = this;
    mv.entity = mk.entity;
    mv.kind = kind_of(*this->model_, mk.entity);
    mv.hint = this->model_->icon(mk.entity);
    mv.x = mk.x;
    mv.y = mk.y;
    // its states (subscribed once; the pool / spa picture and the robot's status too)
    st.watch(mv.entity);
    if (mv.kind == "vacuum" || mv.kind == "appliance")
      st.watch(mv.entity, "tile");
    if (mv.kind == "water") {
      st.watch(mv.entity, "mode");
      st.watch(mv.entity, "body");
    }
    const int cx = (int) lroundf((mk.x - m.bounds[0]) * this->k_) + this->off_x_;
    const int cy = (int) lroundf((mk.y - m.bounds[1]) * this->k_) + this->off_y_;
    // its tap target (a tap / long press; a drag from it pans the map: its
    // events go on up) - invisible: the markers layer draws its pictures
    lv_obj_t *f = lv_obj_create(this->markers_layer_);
    mv.face = f;
    lv_obj_remove_style_all(f);
    lv_obj_set_size(f, FACE_PX, FACE_PX);
    lv_obj_set_pos(f, cx - FACE_PX / 2, cy - FACE_PX / 2);
    lv_obj_add_flag(f, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_flag(f, LV_OBJ_FLAG_EVENT_BUBBLE);
    lv_obj_remove_flag(f, LV_OBJ_FLAG_SCROLLABLE);
    if (mv.kind == "appliance") {
      // its tile's animation over the icon: the sprite sheet in a 1-frame window
      mv.clip = lv_obj_create(f);
      lv_obj_remove_style_all(mv.clip);
      lv_obj_set_size(mv.clip, ANIM_PX, ANIM_PX);
      lv_obj_set_pos(mv.clip, (FACE_PX - ANIM_PX) / 2, (FACE_PX - ANIM_PX) / 2);
      lv_obj_remove_flag(mv.clip, LV_OBJ_FLAG_SCROLLABLE);
      lv_obj_remove_flag(mv.clip, LV_OBJ_FLAG_CLICKABLE);
      mv.sheet = lv_image_create(mv.clip);
      lv_obj_add_flag(mv.clip, LV_OBJ_FLAG_HIDDEN);
    }
    if (mk.show_name) {
      // its name above it, on its own backing (reads on any floor colour)
      if (Sprite *sp = this->name_sprite_(this->model_->short_name(mk.entity))) {
        mv.name_sp = sp;
        mv.name_x = cx - sp->w / 2;
        mv.name_y = cy - MARKER_PX / 2 - 4 - sp->h;
      }
    }
    this->markers_.push_back(std::move(mv));
  }
  for (auto &mv : this->markers_) {
    lv_obj_add_event_cb(mv.face, &MapView::on_marker_, LV_EVENT_SHORT_CLICKED, &mv);
    lv_obj_add_event_cb(mv.face, &MapView::on_marker_, LV_EVENT_LONG_PRESSED, &mv);
    this->paint_marker_(mv);
  }
  this->build_links_();
}

// Links to other maps (stairs, a yard door): a chip "↗ name"; a tap opens that map
void MapView::build_links_() {
  this->links_.clear();
  const MapSpec &m = *this->map_;
  this->links_.reserve(m.links.size());
  for (const MapLink &l : m.links) {
    std::string text = l.label;
    if (text.empty())
      for (auto &other : this->model_->maps)
        if (other->id == l.to)
          text = other->name;
    if (text.empty())
      text = l.to;
    this->links_.push_back(LinkView{this, l.to});
    lv_obj_t *chip = lv_obj_create(this->markers_layer_);
    lv_obj_remove_style_all(chip);
    lv_obj_set_size(chip, LV_SIZE_CONTENT, 26);
    lv_obj_set_style_pad_hor(chip, 10, 0);
    lv_obj_set_style_radius(chip, 13, 0);
    lv_obj_set_style_bg_color(chip, lv_color_hex(this->rt_->color("dialog", 0x2A2A2A)), 0);
    lv_obj_set_style_bg_opa(chip, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(chip, 2, 0);
    lv_obj_set_style_border_color(chip, lv_color_hex(this->rt_->color("accent", 0x4B9EF3)), 0);
    lv_obj_remove_flag(chip, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(chip, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_flag(chip, LV_OBJ_FLAG_EVENT_BUBBLE);  // (a drag from it pans)
    lv_obj_set_ext_click_area(chip, 11);              // (48 px to hit)
    const uint32_t tc = this->rt_->color("text", 0xFFFFFF);
    lv_obj_t *arrow = lv_label_create(chip);
    lv_label_set_text(arrow, "\U000F005C");  // mdi:arrow-top-right
    lv_obj_set_style_text_font(arrow, this->fonts_->tiny, 0);
    lv_obj_set_style_text_color(arrow, lv_color_hex(tc), 0);
    lv_obj_set_align(arrow, LV_ALIGN_LEFT_MID);
    lv_obj_t *name = lv_label_create(chip);
    lv_label_set_text(name, text.c_str());
    lv_obj_set_style_text_font(name, this->fonts_->roll_s, 0);
    lv_obj_set_style_text_color(name, lv_color_hex(tc), 0);
    lv_obj_align(name, LV_ALIGN_LEFT_MID, 18, 0);
    lv_obj_set_pos(chip, (int) lroundf((l.at.x - m.bounds[0]) * this->k_) + this->off_x_,
                   (int) lroundf((l.at.y - m.bounds[1]) * this->k_) + this->off_y_ - 13);
    lv_obj_set_style_translate_x(chip, lv_pct(-50), 0);
    lv_obj_add_event_cb(
        chip,
        [](lv_event_t *e) {
          auto *lv = static_cast<LinkView *>(lv_event_get_user_data(e));
          MapView *self = lv->view;
          if (self->panning_ || self->model_ == nullptr)
            return;
          // (opening the map deletes this chip: after its event)
          self->go_to_ = lv->to;
          lv_async_call(
              [](void *p) {
                auto *s = static_cast<MapView *>(p);
                if (s->open_ && s->model_ != nullptr)
                  s->open(*s->model_, s->go_to_, "");
              },
              self);
        },
        LV_EVENT_SHORT_CLICKED, &this->links_.back());
  }
}

void MapView::paint_marker_(MarkerView &mv) {
  auto &st = this->rt_->states();
  const bool on = (mv.flash_until != 0 && (int32_t) (millis() - mv.flash_until) < 0) ||
                  marker_active(st, mv.kind, mv.entity);
  AssetId icon_on, icon_off;
  marker_icons(st, mv.kind, mv.entity, mv.hint, icon_on, icon_off);
  // MIRRORED: frontend/src/map.ts .marker .face (the ring) - a change here must be made there too.
  // on: the type's colour, half filled; off: the plain face, its ring still
  // in the type's full colour (the tiles' off icons have it as their outline)
  const char *t = on_token(st, mv.kind, mv.entity);
  const uint32_t colour = this->rt_->color(t, token_fallback(t));
  uint32_t fill, border = colour;
  lv_opa_t fill_opa;
  if (on) {
    fill = colour;
    fill_opa = LV_OPA_50;
  } else {
    fill = this->rt_->color("mapMarker", 0x1E1E1E);
    fill_opa = LV_OPA_COVER;
  }
  // its pop-up is open: every marker of the entity ringed (placed several times)
  const bool ring = !this->popup_entity_.empty() && mv.entity == this->popup_entity_;
  const lv_opa_t opa = st.get(mv.entity).empty() ? LV_OPA_40 : LV_OPA_COVER;  // (no state: faded)
  const Sprite *sp = this->face_sprite_(on ? icon_on : icon_off, fill, fill_opa, border, ring);
  if (sp != mv.face_sp || opa != mv.opa) {
    mv.face_sp = sp;
    mv.opa = opa;
    lv_obj_invalidate(mv.face);  // (the markers layer draws it again)
  }
  if (mv.clip != nullptr) {
    // the top unit's animation (the first in `tile` with one), else the other's
    const std::string &tile = st.get(mv.entity, "tile");
    AssetId sheet = IMG_COUNT;
    size_t start = 0;
    while (sheet == IMG_COUNT && start < tile.size()) {
      size_t end = tile.find(';', start);
      if (end == std::string::npos)
        end = tile.size();
      const std::string state = field_(tile.substr(start, end - start), 1);
      sheet = state == "washing"   ? IMG_BUBBLE_WASH_30
              : state == "drying"  ? IMG_SUN_DRY_30
              : state == "done"    ? IMG_CHECK_DONE_30
              : state == "waiting" ? IMG_WET_HOURGLASS_30
                                   : IMG_COUNT;
      start = end + 1;
    }
    const lv_image_dsc_t *img = sheet < IMG_COUNT ? this->rt_->image(sheet) : nullptr;
    mv.animating = img != nullptr;
    if (img != nullptr)
      lv_image_set_src(mv.sheet, img);
    if (mv.animating && !this->lite_)
      lv_obj_remove_flag(mv.clip, LV_OBJ_FLAG_HIDDEN);
    else
      lv_obj_add_flag(mv.clip, LV_OBJ_FLAG_HIDDEN);
  }
}

// ---- taps (map.ts _tap) ------------------------------------------------------------

void MapView::on_marker_(lv_event_t *e) {
  auto *mv = static_cast<MarkerView *>(lv_event_get_user_data(e));
  MapView *self = mv->view;
  if (self->panning_ || self->press_near_zoom_box_())
    return;  // (a drag that started on it; a near miss on the zoom box)
  if (lv_event_get_code(e) == LV_EVENT_LONG_PRESSED) {
    self->open_popup_(*mv);  // a long press always opens the tile
    return;
  }
  self->tap_marker_(*mv);
}

// One tap: lights, switches, fans toggle; covers too (not a garage door, gate
// or door: safety); a scene turns on, a script runs (the marker lights a
// moment); locks, thermostats, appliances, vacuums, pools: their tile opens
void MapView::tap_marker_(MarkerView &mv) {
  const std::string domain = mv.entity.substr(0, mv.entity.find('.'));
  const std::string &k = mv.kind;
  if (is_light(k) || k == "switch" || k == "fan") {
    this->rt_->actions().call(domain + ".toggle", mv.entity);
  } else if (k == "cover" && mv.hint != "icon_garage") {
    this->rt_->actions().call("cover.toggle", mv.entity);
  } else if (k == "scene" || k == "script") {
    this->rt_->actions().call(domain + ".turn_on", mv.entity);
    mv.flash_until = millis() + RUN_FLASH_MS;
    if (mv.flash_until == 0)
      mv.flash_until = 1;
    this->paint_marker_(mv);
  } else {
    this->open_popup_(mv);
  }
}

// ---- the pop-up tile ----------------------------------------------------------------

// The marker's tile, then the groups it's in and the scenes that set it (the
// dashboard's pop-up row): three at a time, the row scrolls sideways when
// there are more (the next one peeks in)
void MapView::open_popup_(const MarkerView &mv) {
  this->close_popup_();
  const int gap = 10, tw = Board::POPUP_W, th = Board::POPUP_H;
  struct Item {
    std::string entity, kind, tag;
  };
  std::vector<Item> items{{mv.entity, mv.kind, ""}};
  int more_groups = 0, more_scenes = 0, groups = 0;
  if (this->model_ != nullptr) {
    auto it = this->model_->popups.find(mv.entity);
    if (it != this->model_->popups.end()) {
      const PopupSpec &p = it->second;
      for (const std::string &g : p.groups)
        items.push_back({g, kind_of(*this->model_, g), this->rt_->t("popup.group")});
      for (const std::string &sc : p.scenes)
        items.push_back({sc, "scene", this->rt_->t("popup.scene")});
      groups = (int) p.groups.size();
      more_groups = p.more_groups;
      more_scenes = p.more_scenes;
    }
  }
  const int n = (int) items.size();
  const int fit = std::min(n, 3);
  const bool scrolls = n > fit || more_groups > 0 || more_scenes > 0;
  const int w = fit * tw + (fit - 1) * gap + (scrolls ? (int) (tw * 0.35f) : 0) + 2 * gap;
  const int h = th + 2 * gap;
  // the marker on screen: the box above it, kept on screen
  lv_area_t a;
  lv_obj_get_coords(mv.face, &a);
  const int mx = (a.x1 + a.x2) / 2, my = (a.y1 + a.y2) / 2;
  const int left = std::max(8, std::min(1024 - w - 8, mx - (tw + 2 * gap) / 2));
  const int top = std::max(this->area_y_ + 8, std::min(600 - h - 8, my - h - 24));
  // a tap anywhere else closes it (not the release of the press that opened it)
  this->popup_scrim_ = lv_obj_create(this->root_);
  lv_obj_remove_style_all(this->popup_scrim_);
  lv_obj_set_size(this->popup_scrim_, 1024, 600);
  lv_obj_add_flag(this->popup_scrim_, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_event_cb(
      this->popup_scrim_,
      [](lv_event_t *e) {
        auto *self = static_cast<MapView *>(lv_event_get_user_data(e));
        if (millis() - self->popup_at_ > 400)
          lv_async_call([](void *p) { static_cast<MapView *>(p)->close_popup_(); }, self);
      },
      LV_EVENT_CLICKED, this);
  this->popup_box_ = lv_obj_create(this->root_);
  lv_obj_t *b = this->popup_box_;
  lv_obj_remove_style_all(b);
  lv_obj_set_pos(b, left, top);
  lv_obj_set_size(b, w, h);
  lv_obj_set_style_bg_color(b, lv_color_hex(this->rt_->color("dialog", 0x2A2A2A)), 0);
  lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
  lv_obj_set_style_border_width(b, 1, 0);
  lv_obj_set_style_border_color(b, lv_color_hex(this->rt_->color("tileBorder", 0x4A4A4A)), 0);
  lv_obj_set_style_radius(b, 14, 0);
  lv_obj_set_style_pad_right(b, gap, 0);
  lv_obj_add_flag(b, LV_OBJ_FLAG_CLICKABLE);  // (a tap on its frame isn't a tap outside)
  if (scrolls) {
    lv_obj_set_scroll_dir(b, LV_DIR_HOR);
    lv_obj_set_scrollbar_mode(b, LV_SCROLLBAR_MODE_OFF);
    lv_obj_set_scroll_snap_x(b, LV_SCROLL_SNAP_START);
  } else {
    lv_obj_remove_flag(b, LV_OBJ_FLAG_SCROLLABLE);
  }
  const uint32_t tag_bg = this->rt_->color("button", 0x333333), tag_fg = this->rt_->color("textSecondary", 0x9E9E9E);
  auto more_note = [&](int count, const char *key, int x) {
    // "+2 more groups": what was left out (any of them can still be placed)
    std::string text = this->rt_->t((std::string(key) + (count == 1 ? ".one" : ".other")).c_str());
    const size_t at = text.find("{n}");
    if (at != std::string::npos)
      text.replace(at, 3, std::to_string(count));
    lv_obj_t *l = lv_label_create(b);
    lv_label_set_text(l, text.c_str());
    lv_obj_set_style_text_font(l, this->fonts_->name_s, 0);
    lv_obj_set_style_text_color(l, lv_color_hex(tag_fg), 0);
    lv_obj_set_style_pad_hor(l, 14, 0);
    lv_obj_set_style_pad_ver(l, 10, 0);
    lv_obj_set_style_radius(l, 12, 0);
    lv_obj_set_style_border_width(l, 1, 0);
    lv_obj_set_style_border_color(l, lv_color_hex(this->rt_->color("tileBorder", 0x4A4A4A)), 0);
    lv_obj_add_flag(l, LV_OBJ_FLAG_SNAPPABLE);
    lv_obj_update_layout(l);
    lv_obj_set_pos(l, x, gap + (th - lv_obj_get_height(l)) / 2);
    return lv_obj_get_width(l);
  };
  int x = gap;
  for (int i = 0; i < n; i++) {
    lv_obj_t *box = this->rt_->board().popup_add(b, items[i].entity, items[i].kind, x, gap);
    if (box != nullptr) {
      lv_obj_add_flag(box, LV_OBJ_FLAG_SNAPPABLE);
      if (!items[i].tag.empty()) {  // "group" / "scene", top right
        lv_obj_t *tag = lv_label_create(box);
        lv_label_set_text(tag, items[i].tag.c_str());
        lv_obj_set_style_text_font(tag, this->fonts_->roll_s, 0);
        lv_obj_set_style_text_color(tag, lv_color_hex(tag_fg), 0);
        lv_obj_set_style_bg_color(tag, lv_color_hex(tag_bg), 0);
        lv_obj_set_style_bg_opa(tag, LV_OPA_COVER, 0);
        lv_obj_set_style_radius(tag, 8, 0);
        lv_obj_set_style_pad_hor(tag, 6, 0);
        lv_obj_set_style_pad_ver(tag, 1, 0);
        lv_obj_align(tag, LV_ALIGN_TOP_RIGHT, -6, 4);
      }
    }
    x += tw + gap;
    if (i == groups && more_groups > 0)  // (after the last group shown)
      x += more_note(more_groups, "popup.more_groups", x) + gap;
  }
  if (more_scenes > 0)
    more_note(more_scenes, "popup.more_scenes", x);
  this->popup_at_ = this->popup_touched_ = millis();
  this->popup_entity_ = mv.entity;
  for (auto &o : this->markers_)
    if (o.entity == mv.entity)
      this->paint_marker_(o);
}

void MapView::close_popup_() {
  if (this->popup_box_ == nullptr)
    return;
  this->rt_->board().popup_clear();
  lv_obj_delete(this->popup_box_);
  lv_obj_delete(this->popup_scrim_);
  this->popup_box_ = this->popup_scrim_ = nullptr;
  const std::string was = this->popup_entity_;
  this->popup_entity_.clear();
  for (auto &o : this->markers_)
    if (o.entity == was)
      this->paint_marker_(o);
}

// (MapView::loop) the pop-up's idle timer, the scene / script flashes
void MapView::markers_loop_() {
  const uint32_t now = millis();
  if ((int32_t) (now - this->anim_at_) >= (int32_t) FRAME_MS) {
    this->anim_at_ = now;
    this->anim_frame_ = (this->anim_frame_ + 1) % (SHEET_COLS * SHEET_ROWS);
    const int col = this->anim_frame_ % SHEET_COLS, row = this->anim_frame_ / SHEET_COLS;
    for (auto &mv : this->markers_)
      if (mv.animating)
        lv_obj_set_pos(mv.sheet, -col * ANIM_PX, -row * ANIM_PX);
  }
  for (auto &mv : this->markers_)
    if (mv.flash_until != 0 && (int32_t) (now - mv.flash_until) >= 0) {
      mv.flash_until = 0;
      this->paint_marker_(mv);
    }
  if (this->popup_box_ == nullptr)
    return;
  // touched (anything in it): it stays a while longer
  lv_indev_t *in = lv_indev_get_next(nullptr);
  if (in != nullptr && lv_indev_get_state(in) == LV_INDEV_STATE_PRESSED)
    for (lv_obj_t *o = lv_indev_get_active_obj(); o != nullptr; o = lv_obj_get_parent(o))
      if (o == this->popup_box_) {
        this->popup_touched_ = now;
        break;
      }
  if (now - this->popup_touched_ > POPUP_IDLE_MS)
    this->close_popup_();
}

void MapView::markers_lite_(bool on) {
  if (on == this->lite_)
    return;
  this->lite_ = on;
  for (auto &mv : this->markers_)
    if (mv.clip != nullptr) {
      if (on || !mv.animating)
        lv_obj_add_flag(mv.clip, LV_OBJ_FLAG_HIDDEN);
      else
        lv_obj_remove_flag(mv.clip, LV_OBJ_FLAG_HIDDEN);
    }
  this->zoom_box_as_picture_(on);
}

// ---- the pictures made ahead (queue_pictures) ----------------------------------

void MapView::queue_pictures(const PanelModel &model) {
  this->picture_jobs_.clear();
  this->picture_next_ = 0;
  const uint32_t in = this->rt_->color("mapLabel", 0x2B3240), out = this->rt_->color("mapLabelOut", 0x8A8F98);
  for (const auto &m : model.maps)
    for (const MapZone &z : m->zones) {
      if (!z.vacuum.empty() || z.name.find_first_not_of(' ') == std::string::npos)
        continue;
      PictureJob j;
      j.what = 0;
      j.text = z.name;
      j.color = z.outdoor ? out : in;
      j.vertical = z.vertical;
      this->picture_jobs_.push_back(std::move(j));
    }
  auto &st = this->rt_->states();
  const uint32_t off_fill = this->rt_->color("mapMarker", 0x1E1E1E);
  for (const MapMarker &mk : model.markers) {
    const std::string kind = kind_of(model, mk.entity), hint = model.icon(mk.entity);
    if (mk.show_name) {
      PictureJob j;
      j.what = 1;
      j.text = model.short_name(mk.entity);
      this->picture_jobs_.push_back(std::move(j));
    }
    AssetId on, off;
    marker_icons(st, kind, mk.entity, hint, on, off);
    // (both faces as paint_marker_ draws them: the ring in the type's colour)
    const char *t = on_token(st, kind, mk.entity);
    const uint32_t colour = this->rt_->color(t, token_fallback(t));
    PictureJob f;
    f.what = 2;
    f.icon = off;
    f.color = off_fill;
    f.border = colour;
    this->picture_jobs_.push_back(f);
    f.icon = on;
    f.color = f.border = colour;
    f.opa = LV_OPA_50;
    this->picture_jobs_.push_back(f);
  }
}

// (MapView::loop, the map closed) up to ~8 ms of them a pass; each kept in PSRAM
void MapView::make_pictures_() {
  if (this->picture_next_ >= this->picture_jobs_.size())
    return;
  PsramScope psram;
  const uint32_t t0 = millis();
  while (this->picture_next_ < this->picture_jobs_.size() && millis() - t0 < 8) {
    const PictureJob &j = this->picture_jobs_[this->picture_next_++];
    Sprite *sp = j.what == 0   ? this->label_sprite_(j.text, j.color, j.vertical)
                 : j.what == 1 ? this->name_sprite_(j.text)
                               : this->face_sprite_(j.icon, j.color, j.opa, j.border, false);
    sprite_to_psram(sp);  // (the map is closed: back in internal RAM when it opens)
    this->pictures_made_++;
  }
  this->pictures_ms_ += millis() - t0;
  if (this->picture_next_ >= this->picture_jobs_.size()) {
    ESP_LOGD(TAG, "Map pictures ready: %u in all, %u looked at in %u ms", (unsigned) this->sprites_.size(),
             (unsigned) this->pictures_made_, (unsigned) this->pictures_ms_);
    this->picture_jobs_.clear();
    this->picture_jobs_.shrink_to_fit();
    this->picture_next_ = 0;
    this->pictures_made_ = this->pictures_ms_ = 0;
  }
}

// ---- pre-rendered pictures (sprite.h) ---------------------------------------------

Sprite *MapView::face_sprite_(int icon, uint32_t fill, lv_opa_t fill_opa, uint32_t border, bool ring) {
  char key[64];
  snprintf(key, sizeof(key), "face|%d|%06x|%u|%06x|%d", icon, (unsigned) fill, (unsigned) fill_opa, (unsigned) border,
           ring ? 1 : 0);
  auto it = this->sprites_.find(key);
  if (it != this->sprites_.end())
    return it->second;
  SpriteCanvas cv(FACE_PX, FACE_PX);
  if (!cv.ok())
    return nullptr;
  // (as the old face: a 40 px circle, a 2 px border, the ring 2 px outside it)
  lv_draw_rect_dsc_t r;
  lv_draw_rect_dsc_init(&r);
  r.radius = LV_RADIUS_CIRCLE;
  r.bg_color = lv_color_hex(fill);
  r.bg_opa = fill_opa;
  r.border_width = 2;
  r.border_color = lv_color_hex(border);
  r.border_opa = LV_OPA_COVER;
  if (ring) {
    r.outline_width = 3;
    r.outline_pad = 2;
    r.outline_color = lv_color_hex(this->rt_->color("accent", 0x4B9EF3));
    r.outline_opa = LV_OPA_COVER;
  }
  const int m = (FACE_PX - MARKER_PX) / 2;
  const lv_area_t a{m, m, m + MARKER_PX - 1, m + MARKER_PX - 1};
  lv_draw_rect(cv.layer(), &r, &a);
  if (const lv_image_dsc_t *img = this->rt_->image((AssetId) icon)) {
    lv_draw_image_dsc_t d;
    lv_draw_image_dsc_init(&d);
    d.src = img;
    const int iw = (int) img->header.w, ih = (int) img->header.h;
    const lv_area_t ia{(FACE_PX - iw) / 2, (FACE_PX - ih) / 2, (FACE_PX - iw) / 2 + iw - 1, (FACE_PX - ih) / 2 + ih - 1};
    lv_draw_image(cv.layer(), &d, &ia);
  }
  Sprite *sp = cv.to_sprite(true);
  if (sp != nullptr)
    this->sprites_[key] = sp;
  return sp;
}

Sprite *MapView::name_sprite_(const std::string &text) {
  const std::string key = "name|" + text;
  auto it = this->sprites_.find(key);
  if (it != this->sprites_.end())
    return it->second;
  // (as the old name: a pill, padding 6 / 2, a 1 px border)
  const lv_font_t *font = this->fonts_->roll_s;
  lv_point_t ts;
  lv_text_get_size(&ts, text.c_str(), font, 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);
  const int w = ts.x + 2 * (6 + 1), h = ts.y + 2 * (2 + 1);
  SpriteCanvas cv(w, h);
  if (!cv.ok())
    return nullptr;
  lv_draw_rect_dsc_t r;
  lv_draw_rect_dsc_init(&r);
  r.radius = LV_RADIUS_CIRCLE;
  r.bg_color = lv_color_hex(this->rt_->color("dialog", 0x2A2A2A));
  r.bg_opa = LV_OPA_90;
  r.border_width = 1;
  r.border_color = lv_color_hex(this->rt_->color("tileBorder", 0x4A4A4A));
  r.border_opa = LV_OPA_COVER;
  const lv_area_t a{0, 0, w - 1, h - 1};
  lv_draw_rect(cv.layer(), &r, &a);
  lv_draw_label_dsc_t l;
  lv_draw_label_dsc_init(&l);
  l.text = text.c_str();
  l.font = font;
  l.color = lv_color_hex(this->rt_->color("text", 0xFFFFFF));
  const lv_area_t ta{7, 3, 7 + ts.x - 1, 3 + ts.y - 1};
  lv_draw_label(cv.layer(), &l, &ta);
  Sprite *sp = cv.to_sprite(true);
  if (sp != nullptr)
    this->sprites_[key] = sp;
  return sp;
}

Sprite *MapView::label_sprite_(const std::string &text, uint32_t color, bool vertical) {
  char head[32];
  snprintf(head, sizeof(head), "label|%06x|%d|", (unsigned) color, vertical ? 1 : 0);
  const std::string key = head + text;
  auto it = this->sprites_.find(key);
  if (it != this->sprites_.end())
    return it->second;
  const lv_font_t *font = this->fonts_->name_s;
  lv_point_t ts;
  lv_text_get_size(&ts, text.c_str(), font, 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);
  SpriteCanvas cv(std::max<int>(1, ts.x), std::max<int>(1, ts.y));
  if (!cv.ok())
    return nullptr;
  lv_draw_label_dsc_t l;
  lv_draw_label_dsc_init(&l);
  l.text = text.c_str();
  l.font = font;
  l.color = lv_color_hex(color);
  const lv_area_t ta{0, 0, ts.x - 1, ts.y - 1};
  lv_draw_label(cv.layer(), &l, &ta);
  // (a vertical room: its name reading upwards)
  Sprite *sp = cv.to_sprite(true, vertical);
  if (sp != nullptr)
    this->sprites_[key] = sp;
  return sp;
}

void MapView::sprites_clear_() {
  for (auto &kv : this->sprites_)
    sprite_free(kv.second);
  this->sprites_.clear();
  this->zoom_box_as_picture_(false);
  sprite_free(this->zoom_sprite_);
  this->zoom_sprite_ = nullptr;
}

// The zoom box's picture for this zoom (a no-op when it's made already)
void MapView::make_zoom_picture_() {
  if (this->zoom_box_ == nullptr || (this->zoom_sprite_ != nullptr && this->zoom_sprite_at_ == this->zoom_))
    return;
  lv_obj_update_layout(this->zoom_box_);
  lv_area_t a;
  lv_obj_get_coords(this->zoom_box_, &a);
  sprite_free(this->zoom_sprite_);
  this->zoom_sprite_ = nullptr;
  SpriteCanvas cv(lv_area_get_width(&a), lv_area_get_height(&a), a.x1, a.y1);
  if (!cv.ok())
    return;
  lv_obj_redraw(cv.layer(), this->zoom_box_);
  this->zoom_sprite_ = cv.to_sprite(true);
  this->zoom_sprite_at_ = this->zoom_;
}

// While panning the zoom box shows as a picture of itself (it sits over the
// map, so every pan frame redraws it: its roller's text, frames, buttons)
void MapView::zoom_box_as_picture_(bool on) {
  if (this->zoom_box_ == nullptr)
    return;
  if (!on) {
    if (this->zoom_img_ != nullptr) {
      lv_obj_delete(this->zoom_img_);
      this->zoom_img_ = nullptr;
      lv_obj_remove_flag(this->zoom_box_, LV_OBJ_FLAG_HIDDEN);
    }
    return;
  }
  if (this->zoom_img_ != nullptr || lv_obj_has_flag(this->zoom_box_, LV_OBJ_FLAG_HIDDEN))
    return;
  this->make_zoom_picture_();  // (made already when the map settled: map_view loop)
  if (this->zoom_sprite_ == nullptr)
    return;
  lv_area_t a;
  lv_obj_get_coords(this->zoom_box_, &a);
  this->zoom_img_ = lv_image_create(this->root_);
  lv_image_set_src(this->zoom_img_, &this->zoom_sprite_->dsc);
  lv_obj_remove_flag(this->zoom_img_, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_set_pos(this->zoom_img_, a.x1, a.y1);
  lv_obj_add_flag(this->zoom_box_, LV_OBJ_FLAG_HIDDEN);
}

void MapView::entity_changed(const std::string &entity) {
  if (!this->open_)
    return;
  if (this->queue_mode_ && (entity == this->q_.sensor || entity == this->q_.vacuum)) {
    this->queue_read_();
    this->queue_restyle_();
    this->build_badges_();
    this->paint_queue_bar_();
    this->request_tiles_();
    return;
  }
  for (auto &mv : this->markers_)
    if (mv.entity == entity)
      this->paint_marker_(mv);
}

}  // namespace esphome::room_tiles
