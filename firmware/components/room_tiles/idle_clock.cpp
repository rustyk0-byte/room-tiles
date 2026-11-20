#include "idle_clock.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <vector>

#include "board.h"
#include "esphome/components/json/json_util.h"
#include "room_tiles.h"

namespace esphome::room_tiles {

// a word from the panel's wording, English until it has one
static std::string tr(RoomTiles *rt, const char *key, const char *fallback) {
  std::string s = rt->t(key);
  return s == key ? std::string(fallback) : s;
}

// "Sunday,Monday,..." -> the n-th
static std::string nth(const std::string &list, int n) {
  size_t from = 0;
  for (int i = 0; i < n; i++) {
    from = list.find(',', from);
    if (from == std::string::npos)
      return "";
    from++;
  }
  const size_t to = list.find(',', from);
  return list.substr(from, to == std::string::npos ? std::string::npos : to - from);
}

// the first n letters (UTF-8: whole letters)
static std::string letters(const std::string &s, int n) {
  size_t i = 0;
  for (int k = 0; k < n && i < s.size(); k++) {
    i++;
    while (i < s.size() && (static_cast<uint8_t>(s[i]) & 0xC0) == 0x80)
      i++;
  }
  return s.substr(0, i);
}

static const char *const WEEKDAYS_EN = "Sunday,Monday,Tuesday,Wednesday,Thursday,Friday,Saturday";

void IdleClock::show(RoomTiles *rt, const Fonts &fonts, int face, bool seconds, int w, int h) {
  this->hide();
  this->rt_ = rt;
  this->fonts_ = &fonts;
  this->face_ = face;
  this->seconds_ = seconds && face != DIGITAL;
  this->root_ = lv_obj_create(lv_layer_top());
  lv_obj_remove_style_all(this->root_);
  lv_obj_set_size(this->root_, w, h);
  lv_obj_set_style_bg_color(this->root_, lv_color_hex(rt->color("page", 0x000000)), 0);
  lv_obj_set_style_bg_opa(this->root_, LV_OPA_COVER, 0);
  lv_obj_add_flag(this->root_, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_remove_flag(this->root_, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_add_event_cb(this->root_, &IdleClock::on_press_, LV_EVENT_PRESSED, this);
  lv_obj_add_event_cb(this->root_, &IdleClock::on_release_, LV_EVENT_RELEASED, this);
  const uint32_t text = rt->color("text", 0xFFFFFF), dim = rt->color("textSecondary", 0x9E9E9E);

  if (face == THEME && !this->build_theme_(w, h)) {
    // (its clock incomplete or unreadable: the analog one - without the
    // theme's pieces made before it gave up)
    lv_obj_clean(this->root_);
    this->time_ = this->ampm_ = this->date_ = nullptr;
    this->hour_ = this->minute_ = this->second_ = Hand{};
    this->face_ = face = ANALOG;
  }
  if (face == ANALOG) {
    const int s = std::min(w, h) * 4 / 5;
    lv_obj_t *dial = lv_obj_create(this->root_);
    lv_obj_remove_style_all(dial);
    lv_obj_set_size(dial, s, s);
    lv_obj_center(dial);
    lv_obj_remove_flag(dial, LV_OBJ_FLAG_CLICKABLE);
    this->build_analog_(dial, s);
  } else if (face == DIGITAL) {
    // the time big, AM / PM beside it (12-hour languages), the date
    this->time_ = lv_label_create(this->root_);
    lv_obj_set_style_text_font(this->time_, fonts.clock != nullptr ? fonts.clock : fonts.thermo, 0);
    lv_obj_set_style_text_color(this->time_, lv_color_hex(text), 0);
    lv_obj_align(this->time_, LV_ALIGN_CENTER, 0, -20);
    this->ampm_ = lv_label_create(this->root_);
    lv_obj_set_style_text_font(this->ampm_, fonts.name, 0);
    lv_obj_set_style_text_color(this->ampm_, lv_color_hex(dim), 0);
    this->date_ = lv_label_create(this->root_);
    lv_obj_set_style_text_font(this->date_, fonts.name, 0);
    lv_obj_set_style_text_color(this->date_, lv_color_hex(dim), 0);
    lv_obj_align(this->date_, LV_ALIGN_CENTER, 0, 60);
  }
  this->shown_ = -1;
  this->painted_min_ = -1;
  this->tick();
}

// the analog dial in `parent` (s x s): a ring in the tile colours, 12 ticks
// (the quarters longer), the hands (a second hand in the accent colour), a
// dot in the middle, the date under it
void IdleClock::build_analog_(lv_obj_t *parent, int s) {
  RoomTiles *rt = this->rt_;
  const uint32_t text = rt->color("text", 0xFFFFFF), dim = rt->color("textSecondary", 0x9E9E9E);
  lv_obj_set_style_radius(parent, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_bg_color(parent, lv_color_hex(rt->color("tile", 0x1E1E1E)), 0);
  lv_obj_set_style_bg_opa(parent, LV_OPA_COVER, 0);
  lv_obj_set_style_border_width(parent, 3, 0);
  lv_obj_set_style_border_color(parent, lv_color_hex(rt->color("tileBorder", 0x4A4A4A)), 0);
  const float c = this->c_ = s / 2.0f, r = s / 2.0f;
  static std::vector<lv_point_precise_t> ticks;  // (lines keep pointers to their points)
  ticks.assign(24, {});
  for (int i = 0; i < 12; i++) {
    const float a = i * (float) M_PI / 6.0f;
    const float in = i % 3 == 0 ? 0.78f : 0.86f;
    ticks[2 * i] = {(lv_value_precise_t) (c + sinf(a) * r * in), (lv_value_precise_t) (c - cosf(a) * r * in)};
    ticks[2 * i + 1] = {(lv_value_precise_t) (c + sinf(a) * r * 0.93f), (lv_value_precise_t) (c - cosf(a) * r * 0.93f)};
    lv_obj_t *t = lv_line_create(parent);
    lv_obj_set_size(t, s, s);
    lv_obj_set_pos(t, 0, 0);
    lv_line_set_points(t, &ticks[2 * i], 2);
    lv_obj_set_style_line_width(t, i % 3 == 0 ? 6 : 3, 0);
    lv_obj_set_style_line_color(t, lv_color_hex(i % 3 == 0 ? text : dim), 0);
    lv_obj_set_style_line_rounded(t, true, 0);
  }
  // (the date under the middle, before the hands: they pass over it)
  this->date_label_(parent, (int) c, (int) (c + r * 0.36f), "center", this->fonts_->date, dim);
  auto hand = [&](Hand &h, float reach, int width, uint32_t colour) {
    h.obj = lv_line_create(parent);
    lv_obj_set_size(h.obj, s, s);
    lv_obj_set_pos(h.obj, 0, 0);
    h.pts[0] = h.pts[1] = {(lv_value_precise_t) c, (lv_value_precise_t) c};
    h.reach = r * reach;
    lv_line_set_points(h.obj, h.pts, 2);
    lv_obj_set_style_line_width(h.obj, width, 0);
    lv_obj_set_style_line_color(h.obj, lv_color_hex(colour), 0);
    lv_obj_set_style_line_rounded(h.obj, true, 0);
  };
  hand(this->hour_, 0.5f, 12, text);
  hand(this->minute_, 0.76f, 7, text);
  if (this->seconds_)
    hand(this->second_, 0.84f, 3, rt->color("accent", 0x4B9EF3));
  lv_obj_t *dot = lv_obj_create(parent);
  lv_obj_remove_style_all(dot);
  lv_obj_set_size(dot, 18, 18);
  lv_obj_center(dot);
  lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_bg_color(dot, lv_color_hex(rt->color("accent", 0x4B9EF3)), 0);
  lv_obj_set_style_bg_opa(dot, LV_OPA_COVER, 0);
}

// the theme's own: its face centered, each hand's picture placed so its pivot
// sits on its spot (the face's center unless the hand says) - turned and
// scaled about that point (paint_). False: no usable clock in the theme.
bool IdleClock::build_theme_(int w, int h) {
  RoomTiles *rt = this->rt_;
  // the large set where it fits (the wall panels), else the 420 px one;
  // clock.json is in 420-px units: everything scaled by k
  const bool large = std::min(w, h) >= 590 && rt->image(IMG_CLOCK_FACE_L) != nullptr;
  const lv_image_dsc_t *face = rt->image(large ? IMG_CLOCK_FACE_L : IMG_CLOCK_FACE);
  const std::string &text = rt->theme_clock();
  if (face == nullptr || text.empty())
    return false;
  JsonDocument doc = json::parse_json(reinterpret_cast<const uint8_t *>(text.data()), text.size());
  JsonObject c = doc.as<JsonObject>();
  if (c.isNull())
    return false;
  const int fw = face->header.w, fh = face->header.h;
  const int fx = (w - fw) / 2, fy = (h - fh) / 2;
  const float k = fw / 420.0f;
  auto sc = [k](float v) { return (int) lroundf(v * k); };
  const int cx = sc(c["center"][0] | 210.0f), cy = sc(c["center"][1] | 210.0f);
  // each piece, made in the theme's order (back to front)
  auto make_face = [&]() {
    lv_obj_t *img = lv_image_create(this->root_);
    lv_image_set_src(img, face);
    lv_obj_set_pos(img, fx, fy);
    lv_obj_remove_flag(img, LV_OBJ_FLAG_CLICKABLE);
  };
  auto make_date = [&]() {
    JsonObject d = c["date"];
    if (d.isNull())
      return;
    const char *colour = d["color"] | "text";
    const uint32_t col = colour[0] == '#' ? strtoul(colour + 1, nullptr, 16) : rt->color(colour, 0xFFFFFF);
    const char *font = d["font"] | "small";
    this->date_label_(this->root_, fx + (d["at"].isNull() ? cx : sc(d["at"][0] | 210.0f)),
                      fy + (d["at"].isNull() ? cy + 60 : sc(d["at"][1] | 270.0f)), d["align"] | "center",
                      strcmp(font, "large") == 0    ? this->fonts_->date
                      : strcmp(font, "medium") == 0 ? this->fonts_->name
                                                    : this->fonts_->prefix,
                      col);
  };
  auto make_hand = [&](const char *name, AssetId small, AssetId big, Hand &hand) {
    JsonObject hj = c["hands"][name];
    const lv_image_dsc_t *pic = rt->image(large ? big : small);
    if (hj.isNull() || pic == nullptr || (&hand == &this->second_ && !this->seconds_))
      return;
    // (the pivot is in the 420 set's picture: scaled with it)
    const int px = hj["pivot"].isNull() ? (int) pic->header.w / 2 : sc(hj["pivot"][0] | 0.0f);
    const int py = hj["pivot"].isNull() ? (int) pic->header.h : sc(hj["pivot"][1] | 0.0f);
    const int ax = hj["at"].isNull() ? cx : sc(hj["at"][0] | 210.0f);
    const int ay = hj["at"].isNull() ? cy : sc(hj["at"][1] | 210.0f);
    const float length = hj["length"] | 1.0f;
    lv_obj_t *o = lv_image_create(this->root_);
    lv_image_set_src(o, pic);
    lv_obj_set_pos(o, fx + ax - px, fy + ay - py);
    lv_image_set_pivot(o, px, py);
    lv_image_set_scale(o, (uint32_t) lroundf(length * LV_SCALE_NONE));
    lv_obj_remove_flag(o, LV_OBJ_FLAG_CLICKABLE);
    hand.obj = o;
  };
  auto make_cap = [&]() {
    const lv_image_dsc_t *pic = rt->image(large ? IMG_CLOCK_CAP_L : IMG_CLOCK_CAP);
    if (c["cap"].isNull() || pic == nullptr)
      return;
    const int ax = c["cap"]["at"].isNull() ? cx : sc(c["cap"]["at"][0] | 210.0f);
    const int ay = c["cap"]["at"].isNull() ? cy : sc(c["cap"]["at"][1] | 210.0f);
    lv_obj_t *o = lv_image_create(this->root_);
    lv_image_set_src(o, pic);
    lv_obj_set_pos(o, fx + ax - (int) pic->header.w / 2, fy + ay - (int) pic->header.h / 2);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_CLICKABLE);
  };
  auto make = [&](const char *piece) {
    if (strcmp(piece, "face") == 0)
      make_face();
    else if (strcmp(piece, "date") == 0)
      make_date();
    else if (strcmp(piece, "hour") == 0)
      make_hand("hour", IMG_CLOCK_HOUR, IMG_CLOCK_HOUR_L, this->hour_);
    else if (strcmp(piece, "minute") == 0)
      make_hand("minute", IMG_CLOCK_MINUTE, IMG_CLOCK_MINUTE_L, this->minute_);
    else if (strcmp(piece, "second") == 0)
      make_hand("second", IMG_CLOCK_SECOND, IMG_CLOCK_SECOND_L, this->second_);
    else if (strcmp(piece, "cap") == 0)
      make_cap();
  };
  JsonArray order = c["order"].as<JsonArray>();
  if (order.isNull() || order.size() == 0) {
    for (const char *p : {"face", "date", "hour", "minute", "second", "cap"})
      make(p);
  } else {
    for (JsonVariant p : order)
      make(p | "");
  }
  if (this->hour_.obj == nullptr || this->minute_.obj == nullptr)
    return false;
  // (a theme without a second hand: a thin one in its accent colour)
  if (this->seconds_ && this->second_.obj == nullptr) {
    this->second_.obj = lv_line_create(this->root_);
    lv_obj_set_size(this->second_.obj, w, h);
    lv_obj_set_pos(this->second_.obj, 0, 0);
    this->second_.pts[0] = this->second_.pts[1] = {(lv_value_precise_t) (fx + cx), (lv_value_precise_t) (fy + cy)};
    this->second_.reach = std::min(fw, fh) * 0.36f;
    lv_line_set_points(this->second_.obj, this->second_.pts, 2);
    lv_obj_set_style_line_width(this->second_.obj, 3, 0);
    lv_obj_set_style_line_color(this->second_.obj, lv_color_hex(rt->color("accent", 0x4B9EF3)), 0);
  }
  return true;
}

void IdleClock::date_label_(lv_obj_t *parent, int x, int y, const char *align, const lv_font_t *font,
                            uint32_t colour) {
  this->date_ = lv_label_create(parent);
  lv_obj_set_style_text_font(this->date_, font, 0);
  lv_obj_set_style_text_color(this->date_, lv_color_hex(colour), 0);
  lv_obj_set_y(this->date_, y - lv_font_get_line_height(font) / 2);
  this->date_x_ = x;
  this->date_align_ = strcmp(align, "left") == 0 ? -1 : strcmp(align, "right") == 0 ? 1 : 0;
}

void IdleClock::hide() {
  if (this->root_ != nullptr)
    lv_obj_delete(this->root_);
  this->root_ = this->time_ = this->ampm_ = this->date_ = nullptr;
  this->hour_ = this->minute_ = this->second_ = Hand{};
  this->pressed_ = false;
}

void IdleClock::tick() {
  if (this->root_ == nullptr)
    return;
  const time_t now = ::time(nullptr);
  struct tm t;
  localtime_r(&now, &t);
  int at = now < 1600000000 ? -2 : t.tm_hour * 60 + t.tm_min;  // (-2: no time yet)
  if (at >= 0 && this->seconds_)
    at = at * 60 + t.tm_sec;
  if (at == this->shown_)
    return;
  this->shown_ = at;
  this->paint_();
}

// "Sat 14" - the weekday's first three letters and the day (the dials')
std::string IdleClock::short_date_() const {
  const time_t now = ::time(nullptr);
  struct tm t;
  localtime_r(&now, &t);
  return letters(nth(tr(this->rt_, "clock.weekdays", WEEKDAYS_EN), t.tm_wday), 3) + " " + std::to_string(t.tm_mday);
}

void IdleClock::paint_() {
  const time_t now = ::time(nullptr);
  struct tm t;
  localtime_r(&now, &t);
  const bool known = now >= 1600000000;
  if (this->face_ != DIGITAL) {
    if (!known)
      return;
    // the hour and minute hands and the date change once a minute (each
    // change redraws what they cover); only the second hand moves each second
    const int minute = t.tm_hour * 60 + t.tm_min;
    const bool new_minute = minute != this->painted_min_;
    this->painted_min_ = minute;
    const float sa = t.tm_sec * 6.0f;
    const float ma = t.tm_min * 6.0f;
    const float ha = (t.tm_hour % 12) * 30.0f + t.tm_min * 0.5f;
    auto turn = [this](Hand &h, float deg) {
      if (h.obj == nullptr)
        return;
      if (h.reach > 0) {  // a line: its far end
        const float a = deg * (float) M_PI / 180.0f;
        h.pts[1] = {(lv_value_precise_t) (h.pts[0].x + sinf(a) * h.reach), (lv_value_precise_t) (h.pts[0].y - cosf(a) * h.reach)};
        lv_line_set_points(h.obj, h.pts, 2);
      } else {  // a picture: turned about its pivot (0.1 degree units)
        lv_image_set_rotation(h.obj, (int32_t) lroundf(deg * 10.0f));
      }
    };
    turn(this->second_, sa);
    if (!new_minute)
      return;
    turn(this->hour_, ha);
    turn(this->minute_, ma);
    if (this->date_ != nullptr) {
      lv_label_set_text(this->date_, this->short_date_().c_str());
      lv_obj_update_layout(this->date_);
      const int lw = lv_obj_get_width(this->date_);
      lv_obj_set_x(this->date_, this->date_align_ < 0 ? this->date_x_ : this->date_align_ > 0 ? this->date_x_ - lw : this->date_x_ - lw / 2);
    }
    return;
  }
  // digital: the time, 12-hour with AM / PM or 24-hour (the panel's setting)
  // MIRRORED: board.cpp paint_clock (the top bar's time) - a change here must be made there too.
  const bool h12 = this->rt_->hours12();  // (the panel's setting, else the language's way)
  char buf[16];
  if (!known)
    snprintf(buf, sizeof(buf), "--:--");
  else if (h12)
    snprintf(buf, sizeof(buf), "%d:%02d", t.tm_hour % 12 == 0 ? 12 : t.tm_hour % 12, t.tm_min);
  else
    snprintf(buf, sizeof(buf), "%02d:%02d", t.tm_hour, t.tm_min);
  lv_label_set_text(this->time_, buf);
  lv_label_set_text(this->ampm_,
                    known && h12 ? (t.tm_hour < 12 ? tr(this->rt_, "clock.am", "AM") : tr(this->rt_, "clock.pm", "PM")).c_str() : "");
  lv_obj_update_layout(this->time_);
  lv_obj_align_to(this->ampm_, this->time_, LV_ALIGN_OUT_RIGHT_BOTTOM, 8, -16);
  std::string date;
  if (known) {
    date = tr(this->rt_, "clock.date", "{weekday}, {month} {day}");
    auto put = [&date](const char *key, const std::string &v) {
      const size_t at = date.find(key);
      if (at != std::string::npos)
        date.replace(at, strlen(key), v);
    };
    put("{weekday}", nth(tr(this->rt_, "clock.weekdays", WEEKDAYS_EN), t.tm_wday));
    put("{month}", nth(tr(this->rt_, "clock.months",
                          "January,February,March,April,May,June,July,August,September,October,November,December"),
                       t.tm_mon));
    put("{day}", std::to_string(t.tm_mday));
  }
  lv_label_set_text(this->date_, date.c_str());
}

void IdleClock::on_press_(lv_event_t *e) { static_cast<IdleClock *>(lv_event_get_user_data(e))->pressed_ = true; }

// let go: the board again (after this touch is done: it never reaches a tile)
void IdleClock::on_release_(lv_event_t *e) {
  lv_async_call([](void *p) { static_cast<IdleClock *>(p)->hide(); }, lv_event_get_user_data(e));
}

}  // namespace esphome::room_tiles
