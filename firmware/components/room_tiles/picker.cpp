#include "picker.h"

#include "board.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "esphome/core/hal.h"
#include "esphome/core/log.h"
#include "room_tiles.h"

namespace esphome::room_tiles {

static const char *const TAG = "room_tiles.picker";

static const uint32_t THROTTLE_MS = 500, THROTTLE_GROUP_MS = 1500;
static const uint32_t SETTLE_MS = 250;
static const uint32_t HOLD_MS = 4000, HOLD_GROUP_MS = 15000;
static const int PRESETS_K[] = {2700, 3000, 4000, 5000, 6500};
static const int DIALOG_W = 360, DIALOG_H = 440;

// ---- colours -----------------------------------------------------------------

uint32_t hs_rgb(float hue, float sat) {
  // MIRRORED: frontend/src/colorpicker.ts hsCss - a change here must be made there too.
  // hsl(h, s%, (100 - s/2)%) - the dashboard's hsCss
  const float s = sat / 100.0f, l = (100.0f - sat / 2.0f) / 100.0f;
  const float c = (1 - fabsf(2 * l - 1)) * s;
  const float hp = fmodf(hue, 360.0f) / 60.0f;
  const float x = c * (1 - fabsf(fmodf(hp, 2.0f) - 1));
  float r = 0, g = 0, b = 0;
  if (hp < 1) r = c, g = x;
  else if (hp < 2) r = x, g = c;
  else if (hp < 3) g = c, b = x;
  else if (hp < 4) g = x, b = c;
  else if (hp < 5) r = x, b = c;
  else r = c, b = x;
  const float m = l - c / 2;
  auto to = [m](float v) { return (uint32_t) lroundf(fminf(1.0f, fmaxf(0.0f, v + m)) * 255.0f); };
  return (to(r) << 16) | (to(g) << 8) | to(b);
}

uint32_t kelvin_rgb(int kelvin) {
  // MIRRORED: frontend/src/colorpicker.ts kelvinCss - a change here must be made there too.
  // the dashboard's kelvinCss
  const double t = kelvin / 100.0;
  const double r = t <= 66 ? 255 : 329.698727446 * pow(t - 60, -0.1332047592);
  const double g = t <= 66 ? 99.4708025861 * log(t) - 161.1195681661 : 288.1221695283 * pow(t - 60, -0.0755148492);
  const double b = t >= 66 ? 255 : t <= 19 ? 0 : 138.5177312231 * log(t - 10) - 305.0447927307;
  auto c = [](double v) { return (uint32_t) lround(fmin(255, fmax(0, v))); };
  return (c(r) << 16) | (c(g) << 8) | c(b);
}

// HA's attribute text: "(30.0, 50.0)" / "[30.0, 50.0]" -> two numbers
static bool two_numbers(const std::string &s, float &a, float &b) {
  const char *p = s.c_str();
  while (*p && !(isdigit((unsigned char) *p) || *p == '-' || *p == '.'))
    p++;
  return sscanf(p, "%f , %f", &a, &b) == 2;
}

bool light_swatch(RoomTiles *rt, const std::string &entity, uint32_t &rgb) {
  auto &st = rt->states();
  const std::string &mode = st.get(entity, "color_mode");
  const std::string &k = st.get(entity, "color_temp_kelvin");
  if (mode == "color_temp" && !k.empty() && k != "None") {
    rgb = kelvin_rgb(atoi(k.c_str()));
    return true;
  }
  float h, s;
  if (two_numbers(st.get(entity, "hs_color"), h, s)) {
    rgb = hs_rgb(h, s);
    return true;
  }
  return false;
}

// ---- the dialog -------------------------------------------------------------------

void ColorPicker::open(RoomTiles *rt, const Fonts &fonts, const std::string &entity, const std::string &name) {
  this->close();
  this->rt_ = rt;
  this->fonts_ = &fonts;
  this->entity_ = entity;
  this->name_ = name;
  auto &st = rt->states();
  // (a colour light's tile already watches these - the picker reads them)
  const std::string &modes = st.get(entity, "supported_color_modes");
  this->can_color_ = modes.find("hs") != std::string::npos || modes.find("xy") != std::string::npos ||
                     modes.find("rgb") != std::string::npos;
  this->can_white_ = modes.find("color_temp") != std::string::npos;
  if (!this->can_color_ && !this->can_white_)
    this->can_color_ = true;  // (not reported yet: assume colour)
  const std::string &kmin = st.get(entity, "min_color_temp_kelvin"), &kmax = st.get(entity, "max_color_temp_kelvin");
  this->k_min_ = kmin.empty() || kmin == "None" ? 2000 : atoi(kmin.c_str());
  this->k_max_ = kmax.empty() || kmax == "None" ? 6500 : atoi(kmax.c_str());
  this->group_ = st.get(entity, "entity_id").find(',') != std::string::npos;
  this->tab_ = st.get(entity, "color_mode") == "color_temp" || !this->can_color_ ? WHITE : COLOR;
  this->hold_until_ = 0;
  this->pending_ = false;
  this->from_ha_();
  this->build_();
}

void ColorPicker::close() {
  if (this->pending_)
    this->send_();  // the last value still goes
  this->teardown_();
}

void ColorPicker::teardown_() {
  if (this->scrim_ != nullptr)
    lv_obj_delete_async(this->scrim_);  // (the dialog is its child; may be inside its own event)
  this->scrim_ = this->dialog_ = this->arc_ = this->preview_ = this->sat_slider_ = nullptr;
  this->bri_slider_ = this->bri_val_ = this->temp_ = this->kelvin_val_ = nullptr;
  this->presets_.clear();
  this->tab_btn_[0] = this->tab_btn_[1] = nullptr;
}

void ColorPicker::from_ha_() {
  auto &st = this->rt_->states();
  float h, s;
  if (two_numbers(st.get(this->entity_, "hs_color"), h, s)) {
    this->hue_ = h;
    this->sat_ = s;
  }
  const std::string &b = st.get(this->entity_, "brightness");
  if (!b.empty() && b != "None")
    this->bri_ = std::max(1, (int) lroundf(atof(b.c_str()) * 100.0f / 255.0f));
  const std::string &k = st.get(this->entity_, "color_temp_kelvin");
  if (!k.empty() && k != "None")
    this->kelvin_ = atoi(k.c_str());
}

static lv_obj_t *text(lv_obj_t *parent, const std::string &s, const lv_font_t *font, uint32_t colour) {
  lv_obj_t *l = lv_label_create(parent);
  lv_label_set_text(l, s.c_str());
  lv_obj_set_style_text_font(l, font, 0);
  lv_obj_set_style_text_color(l, lv_color_hex(colour), 0);
  return l;
}

static lv_obj_t *slider(lv_obj_t *parent, int min, int max, uint32_t colour) {
  lv_obj_t *s = lv_slider_create(parent);
  lv_slider_set_range(s, min, max);
  lv_obj_set_size(s, 176, 24);
  lv_obj_set_style_radius(s, 12, 0);
  lv_obj_set_style_bg_color(s, lv_color_hex(0x444444), 0);
  lv_obj_set_style_bg_opa(s, LV_OPA_COVER, 0);
  lv_obj_set_style_radius(s, 12, LV_PART_INDICATOR);
  lv_obj_set_style_bg_color(s, lv_color_hex(colour), LV_PART_INDICATOR);
  lv_obj_set_style_bg_color(s, lv_color_hex(0xFFFFFF), LV_PART_KNOB);
  lv_obj_set_style_pad_all(s, 4, LV_PART_KNOB);
  lv_obj_set_ext_click_area(s, 12);
  return s;
}

void ColorPicker::build_() {
  RoomTiles *rt = this->rt_;
  const uint32_t text_c = rt->color("text", 0xFFFFFF), soft = rt->color("textSecondary", 0x9E9E9E);
  const uint32_t accent = rt->color("accent", 0x4B9EF3);
  // the round panel: a page of its own (a 360 x 440 card's corners would
  // fall off the circle) - the title on top, the controls in a column that
  // scrolls, close at the bottom
  const bool round = rt->round();
  // the scrim: a tap outside closes
  this->scrim_ = lv_obj_create(lv_layer_top());
  lv_obj_remove_style_all(this->scrim_);
  lv_obj_set_size(this->scrim_, round ? 480 : 1024, round ? 480 : 600);
  // MIRRORED: frontend/src/ui.ts .scrim - a change here must be made there too.
  lv_obj_set_style_bg_color(this->scrim_, lv_color_hex(rt->color("page", 0x000000)), 0);
  lv_obj_set_style_bg_opa(this->scrim_, round ? LV_OPA_COVER : LV_OPA_60, 0);
  lv_obj_add_flag(this->scrim_, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_event_cb(this->scrim_, &ColorPicker::on_close_, LV_EVENT_CLICKED, this);

  lv_obj_t *d = lv_obj_create(this->scrim_);
  this->dialog_ = d;
  lv_obj_remove_style_all(d);
  if (round) {
    lv_obj_set_size(d, DIALOG_W, 300);
    lv_obj_align(d, LV_ALIGN_CENTER, 0, 6);
    lv_obj_add_flag(d, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_scroll_dir(d, LV_DIR_VER);
    lv_obj_set_scrollbar_mode(d, LV_SCROLLBAR_MODE_OFF);
    lv_obj_t *title = text(this->scrim_, this->name_, this->fonts_->name, text_c);
    lv_label_set_long_mode(title, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_width(title, 280);
    lv_obj_set_style_text_align(title, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 46);
    lv_obj_t *x = bar_button(this->scrim_, rt->color("button", 0x333333), rt->color("tileBorder", 0x4A4A4A), 10);
    lv_obj_align(x, LV_ALIGN_BOTTOM_MID, 0, -24);
    lv_obj_add_event_cb(x, &ColorPicker::on_close_, LV_EVENT_CLICKED, this);
    lv_obj_center(text(x, "\U000F0156", this->fonts_->glyph, text_c));  // mdi:close
  } else {
    lv_obj_set_size(d, DIALOG_W, DIALOG_H);
    lv_obj_center(d);
    lv_obj_set_style_bg_color(d, lv_color_hex(rt->color("dialog", 0x2A2A2A)), 0);
    lv_obj_set_style_bg_opa(d, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(d, 1, 0);
    lv_obj_set_style_border_color(d, lv_color_hex(rt->color("tileBorder", 0x4A4A4A)), 0);
    lv_obj_set_style_radius(d, 12, 0);
    lv_obj_add_flag(d, LV_OBJ_FLAG_CLICKABLE);  // (taps inside don't reach the scrim)
    lv_obj_remove_flag(d, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *title = text(d, this->name_, this->fonts_->name, text_c);
    lv_label_set_long_mode(title, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_width(title, DIALOG_W - 72);
    lv_obj_align(title, LV_ALIGN_TOP_LEFT, 16, 14);
    // close: framed like every other close on the panel (the top bars')
    lv_obj_t *x = bar_button(d, rt->color("button", 0x333333), rt->color("tileBorder", 0x4A4A4A), 6);
    lv_obj_align(x, LV_ALIGN_TOP_RIGHT, -10, 10);
    lv_obj_add_event_cb(x, &ColorPicker::on_close_, LV_EVENT_CLICKED, this);
    lv_obj_center(text(x, "\U000F0156", this->fonts_->glyph, text_c));  // mdi:close
  }

  int y = round ? 0 : 60;
  if (this->can_color_ && this->can_white_) {
    const char *keys[2] = {"color.tab_color", "color.tab_white"};
    for (int i = 0; i < 2; i++) {
      lv_obj_t *b = lv_button_create(d);
      this->tab_btn_[i] = b;
      lv_obj_remove_style_all(b);
      lv_obj_set_size(b, 150, 36);
      lv_obj_align(b, LV_ALIGN_TOP_LEFT, 22 + i * 166, y);
      lv_obj_set_style_radius(b, 18, 0);
      lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
      lv_obj_set_user_data(b, (void *) (intptr_t) i);
      lv_obj_add_event_cb(b, &ColorPicker::on_tab_, LV_EVENT_CLICKED, this);
      lv_obj_center(text(b, rt->t(keys[i]), this->fonts_->prefix, text_c));
      lv_obj_set_style_bg_color(b, lv_color_hex((int) this->tab_ == i ? accent : rt->color("button", 0x3A3A3A)), 0);
    }
    y += 52;
  }

  if (this->tab_ == COLOR) {
    // the hue ring (an arc over the ring art) and the preview in its middle
    this->arc_ = lv_arc_create(d);
    lv_obj_set_size(this->arc_, 116, 116);
    lv_obj_align(this->arc_, LV_ALIGN_TOP_MID, 0, y);
    lv_arc_set_bg_angles(this->arc_, 0, 360);
    lv_arc_set_range(this->arc_, 0, 359);
    lv_arc_set_mode(this->arc_, LV_ARC_MODE_NORMAL);
    lv_obj_set_style_arc_opa(this->arc_, LV_OPA_TRANSP, 0);
    lv_obj_set_style_arc_opa(this->arc_, LV_OPA_TRANSP, LV_PART_INDICATOR);
    if (const lv_image_dsc_t *ring = rt->image(IMG_HUE_RING)) {
      lv_obj_set_style_bg_image_src(this->arc_, ring, 0);
      lv_obj_set_style_bg_opa(this->arc_, LV_OPA_TRANSP, 0);
    }
    lv_obj_set_style_bg_color(this->arc_, lv_color_hex(0xFFFFFF), LV_PART_KNOB);
    lv_obj_set_style_border_width(this->arc_, 2, LV_PART_KNOB);
    lv_obj_set_style_border_color(this->arc_, lv_color_hex(0x000000), LV_PART_KNOB);
    lv_obj_add_event_cb(this->arc_, &ColorPicker::on_arc_, LV_EVENT_VALUE_CHANGED, this);
    this->preview_ = lv_obj_create(d);
    lv_obj_remove_style_all(this->preview_);
    lv_obj_set_size(this->preview_, 54, 54);
    lv_obj_set_style_radius(this->preview_, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_opa(this->preview_, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(this->preview_, 2, 0);
    lv_obj_set_style_border_color(this->preview_, lv_color_hex(0xFFFFFF), 0);
    lv_obj_align_to(this->preview_, this->arc_, LV_ALIGN_CENTER, 0, 0);
    y += 136;
    lv_obj_t *l = text(d, rt->t("color.saturation"), this->fonts_->prefix, soft);
    lv_obj_align(l, LV_ALIGN_TOP_LEFT, 20, y + 2);
    this->sat_slider_ = slider(d, 0, 100, accent);
    lv_obj_align(this->sat_slider_, LV_ALIGN_TOP_RIGHT, -24, y);
    lv_obj_add_event_cb(this->sat_slider_, &ColorPicker::on_sat_, LV_EVENT_VALUE_CHANGED, this);
    y += 56;
  } else {
    // presets inside the light's range, then the warm-to-cool slider
    int n = 0;
    for (int k : PRESETS_K)
      if (k >= this->k_min_ && k <= this->k_max_)
        n++;
    const int bw = 60, gap = 6, x0 = (DIALOG_W - (n * bw + (n - 1) * gap)) / 2;
    int i = 0;
    for (int k : PRESETS_K) {
      if (k < this->k_min_ || k > this->k_max_)
        continue;
      lv_obj_t *b = lv_button_create(d);
      lv_obj_remove_style_all(b);
      lv_obj_set_size(b, bw, 52);
      lv_obj_align(b, LV_ALIGN_TOP_LEFT, x0 + i++ * (bw + gap), y);
      lv_obj_set_style_radius(b, 8, 0);
      lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
      lv_obj_set_style_bg_color(b, lv_color_hex(rt->color("button", 0x3A3A3A)), 0);
      // (a frame: the dashboard's; the one at the light's temperature in the accent - paint_)
      lv_obj_set_style_border_width(b, 2, 0);
      lv_obj_set_user_data(b, (void *) (intptr_t) k);
      lv_obj_add_event_cb(b, &ColorPicker::on_preset_, LV_EVENT_CLICKED, this);
      this->presets_.push_back(b);
      lv_obj_t *dot = lv_obj_create(b);
      lv_obj_remove_style_all(dot);
      lv_obj_set_size(dot, 16, 16);
      lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
      lv_obj_set_style_bg_opa(dot, LV_OPA_COVER, 0);
      lv_obj_set_style_bg_color(dot, lv_color_hex(kelvin_rgb(k)), 0);
      lv_obj_align(dot, LV_ALIGN_TOP_MID, 0, 6);
      char kt[8];
      snprintf(kt, sizeof(kt), "%dK", k);
      lv_obj_align(text(b, kt, this->fonts_->prefix_s, text_c), LV_ALIGN_BOTTOM_MID, 0, -6);
    }
    y += 76;
    // Warm | the bar | Cool, and the temperature now under it (the dashboard's)
    const int bar_w = 196;
    lv_obj_t *warm = text(d, rt->t("color.warm"), this->fonts_->prefix, soft);
    lv_label_set_long_mode(warm, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_width(warm, (DIALOG_W - bar_w) / 2 - 30);
    lv_obj_set_style_text_align(warm, LV_TEXT_ALIGN_RIGHT, 0);
    lv_obj_align(warm, LV_ALIGN_TOP_LEFT, 12, y - 2);
    lv_obj_t *cool = text(d, rt->t("color.cool"), this->fonts_->prefix, soft);
    lv_label_set_long_mode(cool, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_width(cool, (DIALOG_W - bar_w) / 2 - 30);
    lv_obj_align(cool, LV_ALIGN_TOP_RIGHT, -12, y - 2);
    this->temp_ = lv_slider_create(d);
    lv_slider_set_range(this->temp_, this->k_min_, this->k_max_);
    lv_obj_set_size(this->temp_, bar_w, 16);
    lv_obj_align(this->temp_, LV_ALIGN_TOP_MID, 0, y);
    this->kelvin_val_ = text(d, "", this->fonts_->prefix_s, soft);
    lv_obj_set_width(this->kelvin_val_, 80);
    lv_obj_set_style_text_align(this->kelvin_val_, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(this->kelvin_val_, LV_ALIGN_TOP_MID, 0, y + 16 + 12);
    if (const lv_image_dsc_t *track = rt->image(IMG_TEMP_TRACK)) {
      lv_obj_set_style_bg_image_src(this->temp_, track, 0);
      lv_obj_set_style_bg_opa(this->temp_, LV_OPA_TRANSP, 0);
    }
    lv_obj_set_style_bg_opa(this->temp_, LV_OPA_TRANSP, LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(this->temp_, lv_color_hex(0xFFFFFF), LV_PART_KNOB);
    lv_obj_set_style_border_width(this->temp_, 2, LV_PART_KNOB);
    lv_obj_set_style_border_color(this->temp_, lv_color_hex(0x000000), LV_PART_KNOB);
    lv_obj_set_style_pad_all(this->temp_, 6, LV_PART_KNOB);
    lv_obj_set_ext_click_area(this->temp_, 16);
    lv_obj_add_event_cb(this->temp_, &ColorPicker::on_temp_, LV_EVENT_VALUE_CHANGED, this);
    y += 60;
  }

  lv_obj_t *l = text(d, rt->t("color.brightness"), this->fonts_->prefix, soft);
  lv_obj_align(l, LV_ALIGN_TOP_LEFT, 20, y + 2);
  // (its end 40 px in, like the temperature bar's: room for the knob and,
  // centered under that end, the value)
  this->bri_slider_ = slider(d, 1, 100, rt->color("light", 0xFFB300));
  lv_obj_align(this->bri_slider_, LV_ALIGN_TOP_RIGHT, -40, y);
  lv_obj_add_event_cb(this->bri_slider_, &ColorPicker::on_bri_, LV_EVENT_VALUE_CHANGED, this);
  this->bri_val_ = text(d, "", this->fonts_->prefix_s, soft);
  const int val_w = 56;  // ("100%" and room)
  lv_obj_set_width(this->bri_val_, val_w);
  lv_obj_set_style_text_align(this->bri_val_, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_pos(this->bri_val_, DIALOG_W - 40 - val_w / 2, y + 24 + 4);
  this->paint_();
}

void ColorPicker::paint_() {
  if (this->dialog_ == nullptr)
    return;
  if (this->arc_ != nullptr && !lv_obj_has_state(this->arc_, LV_STATE_PRESSED))
    lv_arc_set_value(this->arc_, (int) lroundf(this->hue_) % 360);
  if (this->preview_ != nullptr)
    lv_obj_set_style_bg_color(this->preview_, lv_color_hex(hs_rgb(this->hue_, this->sat_)), 0);
  if (this->sat_slider_ != nullptr) {
    if (!lv_obj_has_state(this->sat_slider_, LV_STATE_PRESSED))
      lv_slider_set_value(this->sat_slider_, (int) lroundf(this->sat_), LV_ANIM_OFF);
    lv_obj_set_style_bg_color(this->sat_slider_, lv_color_hex(hs_rgb(this->hue_, 100)), LV_PART_INDICATOR);
  }
  if (this->temp_ != nullptr && !lv_obj_has_state(this->temp_, LV_STATE_PRESSED))
    lv_slider_set_value(this->temp_, this->kelvin_, LV_ANIM_OFF);
  // the light's temperature: its number, and the preset at it outlined (within 50 K)
  if (this->kelvin_val_ != nullptr)
    lv_label_set_text(this->kelvin_val_, (std::to_string(this->kelvin_) + "K").c_str());
  for (lv_obj_t *b : this->presets_) {
    const int k = (int) (intptr_t) lv_obj_get_user_data(b);
    const bool at = abs(this->kelvin_ - k) < 50;
    lv_obj_set_style_border_color(
        b, lv_color_hex(at ? this->rt_->color("accent", 0x4B9EF3) : this->rt_->color("tileBorder", 0x4A4A4A)), 0);
  }
  if (this->bri_slider_ != nullptr && !lv_obj_has_state(this->bri_slider_, LV_STATE_PRESSED))
    lv_slider_set_value(this->bri_slider_, this->bri_, LV_ANIM_OFF);
  if (this->bri_val_ != nullptr)
    lv_label_set_text(this->bri_val_, (std::to_string(this->bri_) + "%").c_str());
}

// ---- input -----------------------------------------------------------------------

void ColorPicker::on_close_(lv_event_t *e) {
  auto *self = static_cast<ColorPicker *>(lv_event_get_user_data(e));
  // (a tap inside the dialog bubbles to nothing; only the scrim itself closes)
  if (lv_event_get_target(e) != lv_event_get_current_target(e))
    return;
  self->close();
}

void ColorPicker::on_tab_(lv_event_t *e) {
  auto *self = static_cast<ColorPicker *>(lv_event_get_user_data(e));
  auto *btn = static_cast<lv_obj_t *>(lv_event_get_current_target(e));
  const Tab tab = (intptr_t) lv_obj_get_user_data(btn) == 0 ? COLOR : WHITE;
  if (tab == self->tab_)
    return;
  // (deleting the dialog from its own button's event: after this event)
  self->tab_ = tab;
  lv_async_call([](void *p) {
    auto *picker = static_cast<ColorPicker *>(p);
    picker->teardown_();
    picker->build_();
  }, self);
}

void ColorPicker::on_arc_(lv_event_t *e) {
  auto *self = static_cast<ColorPicker *>(lv_event_get_user_data(e));
  self->hue_ = (float) lv_arc_get_value(self->arc_);
  self->changed_(true);
}

void ColorPicker::on_sat_(lv_event_t *e) {
  auto *self = static_cast<ColorPicker *>(lv_event_get_user_data(e));
  self->sat_ = (float) lv_slider_get_value(self->sat_slider_);
  self->changed_(true);
}

void ColorPicker::on_bri_(lv_event_t *e) {
  auto *self = static_cast<ColorPicker *>(lv_event_get_user_data(e));
  self->bri_ = lv_slider_get_value(self->bri_slider_);
  self->changed_(self->tab_ == COLOR);
}

void ColorPicker::on_temp_(lv_event_t *e) {
  auto *self = static_cast<ColorPicker *>(lv_event_get_user_data(e));
  self->kelvin_ = lv_slider_get_value(self->temp_);
  self->changed_(false);
}

void ColorPicker::on_preset_(lv_event_t *e) {
  auto *self = static_cast<ColorPicker *>(lv_event_get_user_data(e));
  auto *btn = static_cast<lv_obj_t *>(lv_event_get_current_target(e));
  self->kelvin_ = (int) (intptr_t) lv_obj_get_user_data(btn);
  self->changed_(false);
  self->send_();  // a preset is one choice: at once
}

void ColorPicker::changed_(bool color_part) {
  this->pending_ = true;
  this->pending_color_ = color_part;
  this->last_change_ = millis();
  this->hold_until_ = millis() + (this->group_ ? HOLD_GROUP_MS : HOLD_MS);
  this->paint_();
  this->rt_->repaint(this->entity_);  // the tile's swatch follows
  // while moving: at most one call per throttle period
  if (millis() - this->last_sent_ >= (this->group_ ? THROTTLE_GROUP_MS : THROTTLE_MS))
    this->send_();
}

void ColorPicker::send_() {
  this->pending_ = false;
  std::string data;
  char buf[96];
  if (this->pending_color_ && this->can_color_ && this->tab_ == COLOR) {
    snprintf(buf, sizeof(buf), "{\"hs_color\":[%d,%d],\"brightness_pct\":%d}", (int) lroundf(this->hue_),
             (int) lroundf(this->sat_), this->bri_);
    this->sent_hue_ = this->hue_;
    this->sent_sat_ = this->sat_;
    this->sent_kelvin_ = -1;
  } else if (this->tab_ == WHITE) {
    snprintf(buf, sizeof(buf), "{\"color_temp_kelvin\":%d,\"brightness_pct\":%d}", this->kelvin_, this->bri_);
    this->sent_kelvin_ = this->kelvin_;
    this->sent_hue_ = -1;
  } else {
    snprintf(buf, sizeof(buf), "{\"brightness_pct\":%d}", this->bri_);
  }
  this->sent_bri_ = this->bri_;
  data = buf;
  if (data == this->last_body_)
    return;  // nothing new since the last call
  this->last_body_ = data;
  this->last_sent_ = millis();
  this->hold_until_ = millis() + (this->group_ ? HOLD_GROUP_MS : HOLD_MS);
  this->rt_->actions().call("light.turn_on", this->entity_, data);
}

// HA shows what was sent (within a little): the hold can end early
bool ColorPicker::confirmed_() const {
  auto &st = this->rt_->states();
  const std::string &b = st.get(this->entity_, "brightness");
  if (b.empty() || b == "None" || abs((int) lroundf(atof(b.c_str()) * 100.0f / 255.0f) - this->sent_bri_) > 2)
    return false;
  if (this->sent_kelvin_ >= 0) {
    const std::string &k = st.get(this->entity_, "color_temp_kelvin");
    return !k.empty() && abs(atoi(k.c_str()) - this->sent_kelvin_) <= 60;
  }
  if (this->sent_hue_ >= 0) {
    float h, s;
    if (!two_numbers(st.get(this->entity_, "hs_color"), h, s))
      return false;
    float dh = fabsf(h - this->sent_hue_);
    dh = fminf(dh, 360 - dh);
    return dh <= 3 && fabsf(s - this->sent_sat_) <= 3;
  }
  return true;
}

void ColorPicker::entity_changed(const std::string &entity) {
  if (entity != this->entity_ || this->dialog_ == nullptr)
    return;
  const uint32_t now = millis();
  if (this->hold_until_ != 0 && (int32_t) (now - this->hold_until_) < 0) {
    if (this->pending_ || !this->confirmed_())
      return;  // still the user's values
    this->hold_until_ = 0;
  }
  this->from_ha_();
  this->paint_();
}

void ColorPicker::loop() {
  if (this->dialog_ == nullptr)
    return;
  const uint32_t now = millis();
  // the user stopped: the exact value
  if (this->pending_ && now - this->last_change_ >= SETTLE_MS) {
    const bool pressing = (this->arc_ && lv_obj_has_state(this->arc_, LV_STATE_PRESSED)) ||
                          (this->sat_slider_ && lv_obj_has_state(this->sat_slider_, LV_STATE_PRESSED)) ||
                          (this->temp_ && lv_obj_has_state(this->temp_, LV_STATE_PRESSED)) ||
                          (this->bri_slider_ && lv_obj_has_state(this->bri_slider_, LV_STATE_PRESSED));
    if (!pressing || now - this->last_sent_ >= (this->group_ ? THROTTLE_GROUP_MS : THROTTLE_MS))
      this->send_();
  }
  if (this->hold_until_ != 0 && (int32_t) (now - this->hold_until_) >= 0) {
    this->hold_until_ = 0;  // HA's values again
    this->from_ha_();
    this->paint_();
  }
}

bool ColorPicker::held_swatch(const std::string &entity, uint32_t &rgb) const {
  if (entity != this->entity_ || this->hold_until_ == 0)
    return false;
  rgb = this->tab_ == COLOR ? hs_rgb(this->hue_, this->sat_) : kelvin_rgb(this->kelvin_);
  return true;
}

}  // namespace esphome::room_tiles
