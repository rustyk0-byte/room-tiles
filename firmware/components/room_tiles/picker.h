// Room Tiles panel: the colour / white picker for a colour light - the
// dashboard's colorpicker.ts on the panel (the original panels' look: hue
// ring, preview, sliders, 360 px dialog).
//
// Colour tab: hue ring (drag) + preview in its middle, saturation slider.
// White tab: warm-to-cool slider (temp_track) + 2700 / 3000 / 4000 / 5000 /
// 6500 K presets inside the light's range. Brightness under both. Tabs only
// for what the light supports. While the user moves: at most one call per
// 0.5 s (1.5 s for a light group), the exact value once they stop, nothing
// unchanged; the user's values are held on screen until HA reports them (or
// 4 s / 15 s for groups).
#pragma once

#include <string>
#include <vector>

#include <lvgl.h>

namespace esphome::room_tiles {

class RoomTiles;
struct Fonts;

/// HSL like the dashboard's hsCss (lightness 100 - s/2) -> 0xRRGGBB
uint32_t hs_rgb(float hue, float sat);
/// A colour temperature (K) as a display colour -> 0xRRGGBB
uint32_t kelvin_rgb(int kelvin);
/// The colour a colour light's swatch shows; false = no colour info yet.
bool light_swatch(RoomTiles *rt, const std::string &entity, uint32_t &rgb);

class ColorPicker {
 public:
  void open(RoomTiles *rt, const Fonts &fonts, const std::string &entity, const std::string &name);
  void close();
  bool is_open() const { return this->dialog_ != nullptr; }
  const std::string &entity() const { return this->entity_; }
  /// HA reported something for the open light.
  void entity_changed(const std::string &entity);
  /// Throttle / settle / hold timers.
  void loop();
  /// While the user's values are held: the colour the tile's swatch shows.
  bool held_swatch(const std::string &entity, uint32_t &rgb) const;

 protected:
  enum Tab { COLOR, WHITE };
  void build_();
  void teardown_();
  void from_ha_();
  void paint_();
  void changed_(bool color_part);
  void send_();
  bool confirmed_() const;

  static void on_close_(lv_event_t *e);
  static void on_tab_(lv_event_t *e);
  static void on_arc_(lv_event_t *e);
  static void on_sat_(lv_event_t *e);
  static void on_bri_(lv_event_t *e);
  static void on_temp_(lv_event_t *e);
  static void on_preset_(lv_event_t *e);

  RoomTiles *rt_{nullptr};
  const Fonts *fonts_{nullptr};
  std::string entity_;
  std::string name_;
  bool group_{false};
  bool can_color_{false};
  bool can_white_{false};
  int k_min_{2000};
  int k_max_{6500};
  Tab tab_{COLOR};

  // what the dialog shows (the user's values while held)
  float hue_{0};
  float sat_{100};
  int bri_{100};
  int kelvin_{3000};

  // sending
  bool pending_{false};
  bool pending_color_{true};
  uint32_t last_change_{0};
  uint32_t last_sent_{0};
  uint32_t hold_until_{0};
  std::string last_body_;
  float sent_hue_{-1}, sent_sat_{-1};
  int sent_bri_{-1}, sent_kelvin_{-1};

  lv_obj_t *scrim_{nullptr};
  lv_obj_t *dialog_{nullptr};
  lv_obj_t *arc_{nullptr};
  lv_obj_t *preview_{nullptr};
  lv_obj_t *sat_slider_{nullptr};
  lv_obj_t *bri_slider_{nullptr};
  lv_obj_t *bri_val_{nullptr};
  lv_obj_t *temp_{nullptr};
  lv_obj_t *kelvin_val_{nullptr};      // the temperature now ("3000K"), under its bar
  std::vector<lv_obj_t *> presets_;    // (their kelvin in the user data: the nearest one outlined)
  lv_obj_t *tab_btn_[2]{nullptr, nullptr};
};

}  // namespace esphome::room_tiles
