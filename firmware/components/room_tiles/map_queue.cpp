// Room Tiles panel: a robot vacuum's room queue on the map (the dashboard's
// queue mode, vacqueue.ts): the map it cleans on with its rooms tinted
// (cleanable / not, its own zones) and the queue's rooms in their state's
// colour with their number; a tap on a room queues it / takes it off; a bar
// under the top bar: what it's doing, Start / Pause / Skip / Stop, Clear.
// Room Tiles runs the queue (room_tiles.vacuum_queue); its state is the
// robot sensor's attributes.
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

#include "esphome/core/hal.h"
#include "esphome/core/log.h"

#include "board.h"
#include "map_view.h"
#include "psram_scope.h"
#include "text_fit.h"
#include "room_tiles.h"
#include "vacuum_map.h"

namespace esphome::room_tiles {

static const char *const TAG = "room_tiles.queue";
static const int BADGE_R = 13;   // a room's number badge (px)
static const int BADGE_DY = 20;  // above its name

// "['kitchen', 'den']" (HA hands a list attribute over as its text) -> the ids
static std::vector<std::string> parse_list(const std::string &s) {
  std::vector<std::string> out;
  size_t i = 0;
  while ((i = s.find_first_of("'\"", i)) != std::string::npos) {
    const char q = s[i];
    const size_t j = s.find(q, i + 1);
    if (j == std::string::npos)
      break;
    out.push_back(s.substr(i + 1, j - i - 1));
    i = j + 1;
  }
  return out;
}

static bool has(const std::vector<std::string> &v, const std::string &x) {
  return std::find(v.begin(), v.end(), x) != v.end();
}

// a room's place in the queue -> its colour token ("" = not in it): the
// room being cleaned by what the vacuum is doing (starting = sent, not yet)
static const char *room_token(const std::vector<std::string> &queue, const std::string &current,
                              const std::string &cls, const std::string &area) {
  if (!current.empty() && area == current) {
    if (cls == "cleaning")
      return "vacCleaning";
    if (cls == "paused")
      return "vacPaused";
    if (cls == "attention")
      return "vacAttention";
    if (cls == "error")
      return "vacError";
    return "vacStarting";
  }
  return has(queue, area) ? "vacQueued" : "";
}

static uint32_t token_rgb(RoomTiles *rt, const char *t) {
  static const struct {
    const char *token;
    uint32_t rgb;
  } F[] = {{"vacQueued", 0x4B9EF3},   {"vacStarting", 0xA5D6A7}, {"vacCleaning", 0x4CAF50},
           {"vacPaused", 0xFFB300},   {"vacAttention", 0xFF6D00}, {"vacError", 0xF44336}};
  for (auto &f : F)
    if (strcmp(f.token, t) == 0)
      return rt->color(t, f.rgb);
  return rt->color(t, 0x4B9EF3);
}

// ---- shared with the vacuum tile (vacuum_map.h) ----------------------------------------

QueueState read_queue(RoomTiles *rt, const RobotSpec &robot) {
  auto &st = rt->states();
  QueueState q;
  q.queue = parse_list(st.get(robot.sensor, "queue"));
  q.current = st.get(robot.sensor, "current");
  if (q.current == "None" || q.current == "unknown" || q.current == "unavailable")
    q.current.clear();
  // what it's doing: Room Tiles' "class|text", else the sensor's state
  const std::string &tile = st.get(robot.sensor, "tile");
  q.cls = tile.find('|') != std::string::npos ? field_(tile, 0) : st.get(robot.sensor);
  q.text = tile.find('|') != std::string::npos ? field_(tile, 1) : q.cls;
  if (q.text.empty())
    q.text = q.cls;
  return q;
}

static bool cleans_on(const MapSpec &m, const RobotSpec &robot) {
  for (const MapZone &z : m.zones)
    if (!z.area.empty() && (z.vacuum.empty() || z.vacuum == robot.vacuum) && has(robot.areas, z.area))
      return true;
  return false;
}

// MIRRORED: frontend/src/vacqueue.ts tileMap - a change here must be made there too.
const MapSpec *queue_map(const PanelModel &model, const RobotSpec &robot, const QueueState &q) {
  std::vector<std::string> wanted{q.current};
  wanted.insert(wanted.end(), q.queue.begin(), q.queue.end());
  for (const std::string &area : wanted) {
    if (area.empty())
      continue;
    for (auto &m : model.maps)
      for (const MapZone &z : m->zones)
        if (z.area == area && (z.vacuum.empty() || z.vacuum == robot.vacuum))
          return m.get();
  }
  for (auto &m : model.maps)
    if (cleans_on(*m, robot))
      return m.get();
  return nullptr;
}

std::shared_ptr<MapStyle> queue_style(RoomTiles *rt, const MapSpec &m, const RobotSpec &robot, const QueueState &q,
                                      uint32_t dim, uint32_t *sig_out) {
  auto style = std::make_shared<MapStyle>();
  style->base.resize(m.zones.size());
  style->top.resize(m.zones.size());
  const uint32_t accent = rt->color("accent", 0x4B9EF3);
  uint32_t sig = 2166136261u;  // FNV-1a over the looks
  auto mix = [&sig](uint32_t v) {
    for (int b = 0; b < 4; b++)
      sig = (sig ^ ((v >> (8 * b)) & 0xFF)) * 16777619u;
  };
  for (size_t i = 0; i < m.zones.size(); i++) {
    const MapZone &z = m.zones[i];
    if (!z.vacuum.empty() && z.vacuum != robot.vacuum)
      continue;  // (another vacuum's own zone)
    ZoneStyle &b = style->base[i];
    if (!z.vacuum.empty())
      b = ZoneStyle{accent, 77, accent, 255, true};  // its own zone: dashed outline
    else if (!z.area.empty() && has(robot.areas, z.area))
      b = ZoneStyle{accent, 36, 0, 0, false};  // it cleans this room
    else
      b = ZoneStyle{dim, 140, 0, 0, false};  // it doesn't: dimmed
    const char *t = z.area.empty() ? "" : room_token(q.queue, q.current, q.cls, z.area);
    if (*t) {
      const uint32_t c = token_rgb(rt, t);
      style->top[i] = ZoneStyle{c, (uint8_t) (z.area == q.current ? 178 : 115), c, 255, false};
    }
    for (const ZoneStyle *zs : {&style->base[i], &style->top[i]}) {
      mix(zs->fill);
      mix(zs->fill_opa | (zs->stroke_opa << 8) | (zs->dashed << 16));
      mix(zs->stroke);
    }
  }
  if (sig_out != nullptr)
    *sig_out = sig;
  return style;
}

// ---- the queue view ---------------------------------------------------------------------

bool MapView::zone_shown_(const MapZone &z) const {
  // rooms; a vacuum's own zones only in its queue view
  return z.vacuum.empty() || (this->queue_mode_ && z.vacuum == this->q_.vacuum);
}

bool MapView::queue_map_(const MapSpec &m) const { return cleans_on(m, this->q_); }

// ---- opening / leaving ----------------------------------------------------------------

void MapView::open_queue(const PanelModel &model, const RobotSpec &robot) {
  if (this->parent_ == nullptr || model.maps.empty())
    return;
  PsramScope psram;  // (psram_scope.h)
  this->pictures_to_internal_();
  this->close_overlays_later_();  // (the tap may be the pop-up's vacuum tile)
  this->model_ = &model;
  this->q_ = robot;
  this->queue_mode_ = true;
  auto &st = this->rt_->states();
  st.watch(robot.sensor);
  for (const char *a : {"queue", "current", "tile", "alert"})
    st.watch(robot.sensor, a);
  st.watch(robot.vacuum);
  this->queue_read_();
  // its map: the one the vacuum tile shows (vacuum_map.h queue_map)
  QueueState qs;
  qs.queue = this->q_queue_;
  qs.current = this->q_current_;
  qs.cls = this->q_cls_;
  const MapSpec *mp = queue_map(model, robot, qs);
  const std::string pick = mp != nullptr ? mp->id : std::string();
  if (this->root_ == nullptr)
    this->build_();
  if (this->qbar_ == nullptr)
    this->build_queue_bar_();
  this->set_area_(BAR_H + QBAR_H, AREA_H - QBAR_H);
  this->map_.reset();  // (a full show: the queue's look)
  this->opening_queue_ = true;
  this->open(model, pick, "");
  this->opening_queue_ = false;
  this->paint_queue_bar_();
  ESP_LOGD(TAG, "Queue of %s: %u waiting, current '%s'", robot.robot.c_str(), (unsigned) this->q_queue_.size(),
           this->q_current_.c_str());
}

void MapView::leave_queue_() {
  if (!this->queue_mode_)
    return;
  this->queue_mode_ = false;
  this->style_.reset();
  if (this->qbar_ != nullptr) {
    lv_obj_delete(this->qbar_);
    this->qbar_ = nullptr;
    this->q_auto_ = nullptr;
  }
  lv_obj_clean(this->badges_layer_);
  this->set_area_(BAR_H, AREA_H);
  this->map_.reset();  // (a full show: the plain look)
}

// ---- the queue's state ----------------------------------------------------------------

void MapView::queue_read_() {
  QueueState q = read_queue(this->rt_, this->q_);
  this->q_queue_ = std::move(q.queue);
  this->q_current_ = std::move(q.current);
  this->q_cls_ = std::move(q.cls);
  this->q_text_ = std::move(q.text);
}

// The rooms' looks for this queue state (tinted / dimmed, the queue's
// colours): a new look = new tiles, drawn while the old ones stay on screen
void MapView::queue_restyle_() {
  if (!this->map_ || !this->queue_mode_)
    return;
  QueueState q;
  q.queue = this->q_queue_;
  q.current = this->q_current_;
  q.cls = this->q_cls_;
  uint32_t sig = 0;
  auto style = queue_style(this->rt_, *this->map_, this->q_, q, this->rt_->color("mapBg", 0x121212), &sig);
  const uint32_t gen = (this->base_gen_ * 2654435761u) ^ (sig | 1u);
  if (gen == this->gen_)
    return;
  // (what's on screen stays until the new look's tiles are all drawn, then
  // they all show at once: prev_shows_, revealing_)
  this->gen_ = gen;
  this->revealing_ = true;
  this->style_ = style;
}

// The queue's rooms' numbers (the room being cleaned: a play mark), above their names
void MapView::build_badges_() {
  lv_obj_clean(this->badges_layer_);
  if (!this->queue_mode_ || !this->map_)
    return;
  const MapSpec &m = *this->map_;
  for (const MapZone &z : m.zones) {
    if (z.area.empty() || !this->zone_shown_(z))
      continue;
    const auto it = std::find(this->q_queue_.begin(), this->q_queue_.end(), z.area);
    const bool cur = z.area == this->q_current_;
    if (it == this->q_queue_.end() && !cur)
      continue;
    Pt at = z.label;
    if (!z.has_label) {
      float x0 = 1e30f, y0 = 1e30f, x1 = -1e30f, y1 = -1e30f;
      for (const Pt &p : z.points) {
        x0 = std::min(x0, p.x);
        y0 = std::min(y0, p.y);
        x1 = std::max(x1, p.x);
        y1 = std::max(y1, p.y);
      }
      at = Pt{(x0 + x1) / 2, (y0 + y1) / 2};
    }
    const char *t = room_token(this->q_queue_, this->q_current_, this->q_cls_, z.area);
    lv_obj_t *b = lv_obj_create(this->badges_layer_);
    lv_obj_remove_style_all(b);
    lv_obj_set_size(b, 2 * BADGE_R, 2 * BADGE_R);
    lv_obj_set_pos(b, (int) lroundf((at.x - m.bounds[0]) * this->k_) + this->off_x_ - BADGE_R,
                   (int) lroundf((at.y - m.bounds[1]) * this->k_) + this->off_y_ - BADGE_DY - BADGE_R);
    lv_obj_set_style_radius(b, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(b, lv_color_hex(token_rgb(this->rt_, t)), 0);
    lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(b, 2, 0);
    lv_obj_set_style_border_color(b, lv_color_hex(this->rt_->color("page", 0x000000)), 0);
    lv_obj_remove_flag(b, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_remove_flag(b, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_t *l = lv_label_create(b);
    if (cur) {
      lv_label_set_text(l, "\U000F040A");  // mdi:play
      lv_obj_set_style_text_font(l, this->fonts_->tiny, 0);
    } else {
      lv_label_set_text(l, std::to_string(it - this->q_queue_.begin() + 1).c_str());
      lv_obj_set_style_text_font(l, this->fonts_->name_s, 0);
    }
    // (dark on the light colours: starting, paused)
    // MIRRORED: frontend/src/vacqueue.ts .qbadge text - a change here must be made there too.
    const bool dark = strcmp(t, "vacStarting") == 0 || strcmp(t, "vacPaused") == 0;
    lv_obj_set_style_text_color(l, lv_color_hex(dark ? this->rt_->color("onBright", 0x000000) : this->rt_->color("onAccent", 0xFFFFFF)), 0);
    lv_obj_center(l);
  }
}

// ---- taps -----------------------------------------------------------------------------

void MapView::queue_action_(const char *action, const std::string &area, bool start) {
  std::string data = std::string("{\"robot\":\"") + this->q_.robot + "\",\"action\":\"" + action + "\"";
  if (!area.empty())
    data += ",\"area\":\"" + area + "\"";
  if (start)
    data += ",\"start\":true";
  data += "}";
  this->rt_->actions().call("room_tiles.vacuum_queue", "", data);
}

// A room: queued, or taken off (the room being cleaned stays - Skip moves on)
void MapView::queue_tap_(const MapZone &z) {
  if (z.area.empty() || !has(this->q_.areas, z.area) || z.area == this->q_current_)
    return;
  // added: started at once with "Start queue automatically" on (no Start press)
  if (has(this->q_queue_, z.area))
    this->queue_action_("remove", z.area);
  else
    this->queue_action_("add", z.area, this->rt_->queue_autostart());
}

// ---- the bar --------------------------------------------------------------------------

void MapView::build_queue_bar_() {
  this->qbar_ = lv_obj_create(this->root_);
  lv_obj_t *bar = this->qbar_;
  lv_obj_remove_style_all(bar);
  lv_obj_set_pos(bar, 0, BAR_H);
  lv_obj_set_size(bar, 1024, QBAR_H);
  lv_obj_set_style_bg_color(bar, lv_color_hex(this->rt_->color("dialog", 0x2A2A2A)), 0);
  lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);
  lv_obj_remove_flag(bar, LV_OBJ_FLAG_SCROLLABLE);

  this->q_status_ = lv_label_create(bar);
  lv_label_set_long_mode(this->q_status_, LV_LABEL_LONG_MODE_CLIP);  // (paint_queue_bar_ fits it)
  lv_obj_set_width(this->q_status_, Q_STATUS_W);
  lv_obj_set_style_text_font(this->q_status_, this->fonts_->name, 0);
  lv_obj_align(this->q_status_, LV_ALIGN_LEFT_MID, 20, 0);

  const uint32_t text = this->rt_->color("text", 0xFFFFFF);
  auto button = [&](int x, int w, const char *action, bool primary) {
    lv_obj_t *b = lv_obj_create(bar);
    lv_obj_remove_style_all(b);
    lv_obj_set_size(b, w, 48);
    lv_obj_align(b, LV_ALIGN_LEFT_MID, x, 0);
    lv_obj_set_style_radius(b, 24, 0);
    lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(b, lv_color_hex(primary ? this->rt_->color("accent", 0x4B9EF3) : this->rt_->color("button", 0x333333)), 0);
    lv_obj_remove_flag(b, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(b, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_user_data(b, (void *) action);
    lv_obj_add_event_cb(b, &MapView::on_queue_button_, LV_EVENT_CLICKED, this);
    return b;
  };
  auto glyph = [&](lv_obj_t *b, const char *g, int dx) {
    lv_obj_t *l = lv_label_create(b);
    lv_label_set_text(l, g);
    lv_obj_set_style_text_font(l, this->fonts_->glyph, 0);
    lv_obj_set_style_text_color(l, lv_color_hex(text), 0);
    lv_obj_align(l, dx ? LV_ALIGN_LEFT_MID : LV_ALIGN_CENTER, dx, 0);
    return l;
  };
  // Start / Resume (play mark + its word), Pause, Skip, Stop, Clear, the
  // auto start switch; the bar's right end stays empty - the map's X is above it
  this->q_start_ = button(270, 160, "start", true);
  const uint32_t on_accent = this->rt_->color("onAccent", 0xFFFFFF);
  lv_obj_set_style_text_color(glyph(this->q_start_, "\U000F040A", 14), lv_color_hex(on_accent), 0);  // mdi:play
  this->q_start_text_ = lv_label_create(this->q_start_);
  lv_obj_set_style_text_font(this->q_start_text_, this->fonts_->name, 0);
  lv_obj_set_style_text_color(this->q_start_text_, lv_color_hex(on_accent), 0);
  lv_obj_align(this->q_start_text_, LV_ALIGN_LEFT_MID, 50, 0);
  this->q_pause_ = button(442, 64, "pause", false);
  glyph(this->q_pause_, "\U000F03E4", 0);  // mdi:pause
  this->q_skip_ = button(516, 64, "skip", false);
  glyph(this->q_skip_, "\U000F04AD", 0);  // mdi:skip-next
  this->q_stop_ = button(590, 64, "stop", false);
  glyph(this->q_stop_, "\U000F04DB", 0);  // mdi:stop
  this->q_clear_ = button(664, 140, "clear", false);  // (next to Stop)
  lv_obj_t *cl = lv_label_create(this->q_clear_);
  lv_label_set_text(cl, this->rt_->t("queue.clear").c_str());
  lv_obj_set_style_text_font(cl, this->fonts_->name, 0);
  lv_obj_set_style_text_color(cl, lv_color_hex(text), 0);
  lv_obj_center(cl);

  // "Start queue automatically" (the dashboard's; kept on this panel): its
  // words, then a switch - the whole 136 x 48 a tap target
  lv_obj_t *a = lv_obj_create(bar);
  lv_obj_remove_style_all(a);
  lv_obj_set_size(a, 136, 48);
  lv_obj_align(a, LV_ALIGN_LEFT_MID, 816, 0);  // (ends at 952: nothing under the map's X)
  lv_obj_remove_flag(a, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_add_flag(a, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_event_cb(
      a,
      [](lv_event_t *e) {
        auto *self = static_cast<MapView *>(lv_event_get_user_data(e));
        self->rt_->set_queue_autostart(!self->rt_->queue_autostart());
        self->paint_queue_bar_();
      },
      LV_EVENT_CLICKED, this);
  lv_obj_t *words = lv_label_create(a);
  lv_label_set_text(words, fit_lines(this->rt_->t("queue.auto_start"), this->fonts_->roll_s, 80).c_str());
  lv_obj_set_width(words, 80);
  lv_obj_set_style_text_font(words, this->fonts_->roll_s, 0);
  lv_obj_set_style_text_color(words, lv_color_hex(text), 0);
  lv_obj_align(words, LV_ALIGN_LEFT_MID, 0, 0);
  // (LVGL's switch: compiled in by room_tiles.yaml's feature_switch)
  this->q_auto_ = lv_switch_create(a);
  lv_obj_set_size(this->q_auto_, 46, 26);
  lv_obj_align(this->q_auto_, LV_ALIGN_RIGHT_MID, 0, 0);
  lv_obj_remove_flag(this->q_auto_, LV_OBJ_FLAG_CLICKABLE);  // (its area takes the tap)
  lv_obj_set_style_bg_color(this->q_auto_, lv_color_hex(this->rt_->color("button", 0x3A3A3A)), 0);
  lv_obj_set_style_bg_opa(this->q_auto_, LV_OPA_COVER, 0);
  lv_obj_set_style_bg_color(this->q_auto_, lv_color_hex(this->rt_->color("accent", 0x4B9EF3)),
                            (lv_style_selector_t) LV_PART_INDICATOR | LV_STATE_CHECKED);
  lv_obj_set_style_bg_color(this->q_auto_, lv_color_hex(0xFFFFFF), LV_PART_KNOB);
}

void MapView::paint_queue_bar_() {
  if (this->qbar_ == nullptr)
    return;
  if (this->q_auto_ != nullptr) {
    if (this->rt_->queue_autostart())
      lv_obj_add_state(this->q_auto_, LV_STATE_CHECKED);
    else
      lv_obj_remove_state(this->q_auto_, LV_STATE_CHECKED);
  }
  auto &st = this->rt_->states();
  const std::string vac = st.get(this->q_.vacuum);
  const bool running = vac == "cleaning", paused = vac == "paused";
  const size_t n = this->q_queue_.size();
  const std::string &alert = st.get(this->q_.sensor, "alert");
  const bool alerting = !alert.empty() && alert != "none" && !this->q_current_.empty();
  // what it's doing, in the tile's colours
  const std::string &c = this->q_cls_;
  const uint32_t colour = c == "cleaning"    ? this->rt_->color("vacCleaning", 0x4CAF50)
                          : c == "paused"    ? this->rt_->color("vacPaused", 0xFFB300)
                          : c == "attention" ? this->rt_->color("vacAttention", 0xFF6D00)
                          : c == "error"     ? this->rt_->color("vacError", 0xF44336)
                                             : this->rt_->color("textSecondary", 0x9E9E9E);
  // one line - or, when it's longer (the queue cleared because something
  // else took the vacuum over...), two in the smaller font
  const std::string one = fit_lines(this->q_text_, this->fonts_->name, Q_STATUS_W);
  const bool two = one.find('\n') != std::string::npos;
  lv_obj_set_style_text_font(this->q_status_, two ? this->fonts_->name_s : this->fonts_->name, 0);
  lv_label_set_text(this->q_status_, two ? fit_lines(this->q_text_, this->fonts_->name_s, Q_STATUS_W).c_str() : one.c_str());
  lv_obj_align(this->q_status_, LV_ALIGN_LEFT_MID, 20, 0);
  lv_obj_set_style_text_color(this->q_status_, lv_color_hex(colour), 0);
  lv_label_set_text(this->q_start_text_, this->rt_->t(paused ? "queue.resume" : "queue.start").c_str());
  auto enable = [](lv_obj_t *b, bool on) {
    lv_obj_set_style_opa(b, on ? LV_OPA_COVER : LV_OPA_40, 0);
    if (on)
      lv_obj_add_flag(b, LV_OBJ_FLAG_CLICKABLE);
    else
      lv_obj_remove_flag(b, LV_OBJ_FLAG_CLICKABLE);
  };
  enable(this->q_start_, n > 0 || paused || alerting);
  enable(this->q_pause_, running);
  enable(this->q_skip_, !this->q_current_.empty());
  enable(this->q_stop_, !this->q_current_.empty() || n > 0 || running || paused);
  enable(this->q_clear_, n > 0);
}

void MapView::on_queue_button_(lv_event_t *e) {
  auto *self = static_cast<MapView *>(lv_event_get_user_data(e));
  const char *action = static_cast<const char *>(lv_obj_get_user_data(lv_event_get_current_target_obj(e)));
  if (self->queue_mode_ && action != nullptr)
    self->queue_action_(action);
}

}  // namespace esphome::room_tiles
