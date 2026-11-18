// Room Tiles panel: the main screen - top bar + the area's tile board, drawn
// at runtime from the payload (docs/DESIGN.md "Panel firmware"). One drawing
// function per tile kind; geometry from the original panels (1024x600: 5x2 =
// 198x254 tiles, 6x3 = 164x173, 8 px gaps, board from y 64).
#pragma once

#include <deque>
#include <initializer_list>
#include <memory>
#include <string>
#include <vector>

#include <lvgl.h>

#include "busy.h"
#include "model.h"

namespace esphome::room_tiles {

class RoomTiles;

/// Field i of a "a|b|c" tile attribute ("" past the end).
std::string field_(const std::string &s, int i);

struct Fonts {
  const lv_font_t *bar{nullptr};     // top bar (area name)
  const lv_font_t *name{nullptr};    // tile names: 5x2 / 6x3
  const lv_font_t *name_s{nullptr};
  const lv_font_t *play{nullptr};    // the play glyph: 5x2 / 6x3
  const lv_font_t *play_s{nullptr};
  // rollers: rows above / below, the selected row (big / smaller kinds), the
  // word left of it - 5x2 and 6x3 each
  const lv_font_t *roll{nullptr};
  const lv_font_t *roll_s{nullptr};
  const lv_font_t *roll_sel{nullptr};
  const lv_font_t *roll_sel_s{nullptr};
  const lv_font_t *roll_mid{nullptr};
  const lv_font_t *roll_mid_s{nullptr};
  const lv_font_t *prefix{nullptr};
  const lv_font_t *prefix_s{nullptr};
  // thermostat / pool: the current temperature, big (5x2 / 6x3)
  const lv_font_t *thermo{nullptr};
  const lv_font_t *thermo_s{nullptr};
  // small glyphs: the pool / spa heater button (flame / snowflake)
  const lv_font_t *glyph{nullptr};
  const lv_font_t *glyph_s{nullptr};
  // tiny glyphs at text size: a map link's arrow
  const lv_font_t *tiny{nullptr};
  // the drop-down triangle after a top bar name that opens a list
  const lv_font_t *menu{nullptr};
  // the idle clock's digits (big)
  const lv_font_t *clock{nullptr};
  const lv_font_t *date{nullptr};  // the idle clock's date (analog; a theme's "large")
  // the Room Tiles icon at the top bars' far left (tiles and map)
  const lv_image_dsc_t *brand{nullptr};
};

/// A top bar name that opens a list when tapped (the area's, the map's): the
/// name, then the drop-down triangle (the dashboard's mdi:menu-down) - the
/// name cut short with "..." to keep both within max_w. Returns the row, the
/// tap target (clickable; add the event).
lv_obj_t *dropdown_title(lv_obj_t *parent, const std::string &text, const Fonts &fonts, uint32_t color, int max_w);

/// A top bar button (the gear, the layout and map buttons, the map's back and
/// close): the dashboard's framed look - button colour, a 1 px tile-border
/// frame, rounded - BAR_BTN_W x BAR_BTN_H, its tap area a little bigger.
/// Put the icon in it, centered.
static constexpr int BAR_BTN_W = 48, BAR_BTN_H = 40;
lv_obj_t *bar_button(lv_obj_t *parent, uint32_t bg, uint32_t border, int ext_click);

/// The settings button's dot (something waits on the dashboard: a device
/// found to set up) - the dashboard's .gear-dot: yellow, top right.
/// `slot` (optional) holds it while it exists (nulled when it's deleted).
lv_obj_t *gear_dot(lv_obj_t *gear, uint32_t colour, lv_obj_t **slot = nullptr);

/// The Room Tiles icon at a top bar's far left (the tiles' and the map's),
/// centered on `mid_y`; not a button. `themed`: the theme's own (its pack's
/// brand_bar - bigger, the plain icon's squares in its middle), centered where
/// the plain one is. Returns the x where the bar's next item may start
/// (`fallback` when there's no icon).
static constexpr int BRAND_PX = 36;
int brand_icon(lv_obj_t *parent, const Fonts &fonts, int mid_y, int fallback, const lv_image_dsc_t *themed);

class Board {
 public:
  void attach(lv_obj_t *root, RoomTiles *rt, const Fonts &fonts) {
    this->root_ = root;
    this->rt_ = rt;
    this->fonts_ = fonts;
  }
  bool attached() const { return this->root_ != nullptr; }
  /// A panel without an area: the area picker opens by itself.
  void ask_area() { this->open_area_picker_(); }
  /// The round panel's layout (board_strip.cpp): the area's 5x2 tiles in one
  /// horizontal strip, one tile wide - set once, before the first build.
  void set_strip(bool strip) { this->strip_ = strip; }
  bool strip() const { return this->strip_; }
  /// The knob (round panel): a click = half a tile along the strip.
  void knob_turn(int clicks);
  /// The knob's press: a tap on the centered tile (nothing at a split).
  void knob_press();
  /// A tile in view is animating (an appliance running) - the idle clock
  /// keeps away then ("Animations keep tiles visible"). The round panel: the
  /// centered tile or both halves of a split; a wall panel: the board.
  bool visible_animating() const;
  const Fonts &fonts() const { return this->fonts_; }
  /// Draw everything again (new payload, new theme / wording).
  void build(const PanelModel &model);
  /// Take everything down (before a pack it draws from is rewritten; build()
  /// starts with it) - and forget every object it drew: a state change
  /// meanwhile must find nothing to paint.
  void clear();
  /// An entity's state changed: redraw the tiles showing it.
  void entity_changed(const std::string &entity);
  /// Timers: held values running out, scene / script flashes.
  void loop();
  /// Subscribe ahead to what the areas' boards show (this area first) - up
  /// to a budget, so switching areas finds the states already there.
  void preload(const PanelModel &model);
  /// What a tile of `kind` needs to know about `entity` (watched).
  void watch_(const std::string &kind, const std::string &entity);
  /// An edit is on its way for these slots: their stopwatch until it lands.
  void wait_for_(std::initializer_list<int> slots);
  // board_strip.cpp: the round panel
  bool strip_{false};
  lv_obj_t *strip_cont_{nullptr};
  std::vector<lv_obj_t *> strip_dots_;
  int strip_shown_{-1};  // (the snap point the dots show: 2 x tile, odd = a split)
  int strip_settings_y_{-1};  // (the settings page drawn again: where it was scrolled to)
  void build_strip_(const PanelModel &model, const AreaSpec *area);
  int strip_step_() const;
  int strip_points_() const;
  int strip_point_() const;
  void strip_go_(int point, bool anim);
  void paint_dots_();
  void open_strip_areas_();
  void open_strip_settings_();
  lv_obj_t *strip_page_(const std::string &title);
  static void on_strip_scroll_end_(lv_event_t *e);
  static void on_strip_scroll_(lv_event_t *e);
  /// A tile on its own (the map's pop-up row), 5x2 size, at (x, y) in
  /// `parent`; kept live like the board's own. Returns its box.
  lv_obj_t *popup_add(lv_obj_t *parent, const std::string &entity, const std::string &kind, int x, int y);
  /// Take the pop-up tiles down (before their parent is deleted).
  void popup_clear();
  static constexpr int POPUP_W = 198, POPUP_H = 254;

 protected:
  // A vacuum tile's map picture (board_kinds.cpp): RGB565 in PSRAM, drawn
  // once per look (map, queue, size)
  struct TileMap {
    uint16_t *buf{nullptr};
    int w{0}, h{0}, stride_px{0};
    lv_image_dsc_t dsc{};
    uint32_t sig{0};
    ~TileMap();
  };
  struct TileView {
    Board *board{nullptr};
    std::string kind;
    std::string entity;
    bool big{true};
    lv_obj_t *box{nullptr};
    lv_obj_t *name{nullptr};
    lv_obj_t *icon{nullptr};
    lv_obj_t *track{nullptr};
    lv_obj_t *knob{nullptr};
    lv_obj_t *play{nullptr};
    lv_obj_t *roller{nullptr};
    lv_obj_t *swatch{nullptr};  // a colour light: the ring (tap = picker)
    lv_obj_t *swatch_fill{nullptr};
    std::string name_text;
    std::string icon_hint;  // from Room Tiles (garage door, the vacuum's maker)
    // thermostat / pool: the temperature and what it's doing, left of the roller
    lv_obj_t *temp{nullptr};
    lv_obj_t *status{nullptr};
    lv_obj_t *band_lo{nullptr};  // auto: the band's low / high under the roller
    lv_obj_t *band_hi{nullptr};
    lv_obj_t *heater{nullptr};  // pool / spa: the heater button
    lv_obj_t *heater_glyph{nullptr};
    lv_obj_t *heater_busy{nullptr};  // its stopwatch: asked for, not there yet
    int heater_held{-1};
    uint32_t heater_held_until{0};
    // appliance: up to two units (picture + animation, label, status)
    struct Unit {
      lv_obj_t *half{nullptr};
      lv_obj_t *base{nullptr};
      lv_obj_t *clip{nullptr};
      lv_obj_t *sheet{nullptr};
      lv_obj_t *label{nullptr};
      lv_obj_t *status{nullptr};
      lv_obj_t *time{nullptr};  // time left: a line of its own under the step
      int frame_px{0};
      bool animating{false};
    } units[2];
    int unit_index{0};
    int slot{0};               // its place on the board
    lv_obj_t *edit{nullptr};   // edit mode: the overlay that takes the taps
    lv_obj_t *busy{nullptr};   // the small stopwatch: no state yet / a change on its way
    uint32_t waiting_until{0}; // an edit sent for this slot: until the new board
    lv_obj_t *prefix{nullptr};
    int held_row{-1};  // the user's roller pick, held like `held`
    uint32_t held_row_until{0};
    // the user's last switch value, held until HA agrees or time runs out
    int held{-1};
    uint32_t held_until{0};
    uint32_t flash_until{0};
    // vacuum: its queue's map (vacuum_map.h) and the robot sensor it follows
    std::shared_ptr<TileMap> vmap;
    lv_obj_t *vmap_img{nullptr};
    std::string robot_sensor;
  };

  void build_bar_(const PanelModel &model, const AreaSpec *area);
  void build_tile_(TileView &tv, int x, int y, int w, int h, lv_obj_t *parent = nullptr);
  void tick_(TileView &tv, uint32_t now);
  std::deque<TileView> popups_;  // (a deque: they never move - event user data)
  void paint_(TileView &tv);
  bool is_on_(const TileView &tv) const;
  bool icon_on_(const TileView &tv, bool on) const;  // (the icon's on / off picture: the markers' rule)
  void toggle_(TileView &tv);
  void run_(TileView &tv);
  void build_roller_(TileView &tv);
  void paint_roller_(TileView &tv);
  int ha_row_(const TileView &tv) const;
  void roller_picked_(TileView &tv, int row);
  static void on_roller_(lv_event_t *e);
  static void on_swatch_(lv_event_t *e);
  void build_swatch_(TileView &tv);
  void paint_swatch_(TileView &tv);
  bool ha_on_(const TileView &tv) const;
  bool busy_(const TileView &tv) const;
  bool waiting_(const TileView &tv) const;  // values asked of HA, not answered yet  // a pool / spa switching or offline: locked
  void switch_call_(TileView &tv, bool on);
  // board_kinds.cpp: thermostat, pool / spa, appliance, vacuum, map
  void build_thermo_(TileView &tv);
  void paint_thermo_(TileView &tv);
  void build_heater_(TileView &tv);
  void paint_heater_(TileView &tv);
  void build_appliance_(TileView &tv);
  void paint_appliance_(TileView &tv);
  void build_vacuum_(TileView &tv);
  void paint_vacuum_(TileView &tv);
  bool draw_vacuum_map_(TileView &tv);
  void build_map_(TileView &tv);
  void animate_(uint32_t now);
  bool water_on_(const TileView &tv) const;
  int water_switch_(const TileView &tv) const;  // 0 none, 1 the body, 2 the heater
  int climate_tone_(const TileView &tv) const;  // 0 neutral, 1 heat, 2 cool
  bool climate_band_(const TileView &tv, int mid, float &lo, float &hi) const;
  static void on_heater_(lv_event_t *e);
  static void on_unit_(lv_event_t *e);

  // board_edit.cpp: the settings menu, the area picker, tile editing + the tile picker
 public:
  /// The gears' dot: a device found to set up that this panel hasn't shown
  /// in its settings yet (opening them clears it; a new count lights it again)
  bool found_dot() const;
 public:
  bool editing() const { return this->editing_; }
  void set_editing(bool on);
 protected:
  void build_edit_(TileView &tv);
  void paint_edit_(TileView &tv);
  void edit_tap_(TileView &tv);
  void edit_hold_(TileView &tv);
  void open_settings_();
  void open_area_picker_();
  void open_languages_();
  void open_theme_list_();
  void open_idle_list_();
  /// The line under "Screen off when the following area lights are off": the room it
  /// follows (where the panel is - its HA device's area), or what's missing.
  std::string room_line_() const;
  lv_obj_t *idle_row_{nullptr};  // the settings menu's "When idle" row (its list opens over it)
  void confirm_restart_();
  void confirm_wifi_change_();
  void open_picker_(int slot);
  void close_dialog_();
  lv_obj_t *dialog_(int w, int h, const std::string &title);
  void picker_fill_();
  static void on_edit_tap_(lv_event_t *e);
  static void on_edit_hold_(lv_event_t *e);
  static void on_settings_(lv_event_t *e);
  static void on_area_name_(lv_event_t *e);
  static void on_done_(lv_event_t *e);
  const PanelModel *model_{nullptr};
  std::string area_;
  bool editing_{false};
  int found_seen_{0};            // the found count the settings menu last showed
  lv_obj_t *gear_dot_{nullptr};  // the tiles' bar's (while it exists)
  int picked_{-1};              // the slot picked up to move (-1 = none)
  bool hold_click_{false};      // swallow the click that ends a long press
  lv_obj_t *hint_{nullptr};     // top bar, edit mode: what to do
  lv_obj_t *clock_{nullptr};    // top bar: the time, between the left and right buttons (not while editing)
  int clock_lo_{0}, clock_hi_{0};  // (the room it has there)
  int clock_shown_{-1};         // (the minute shown: loop repaints on the next)
  lv_obj_t *lights_glyph_{nullptr};  // top bar: the area lights button's bulbs (lit: any on)
  lv_obj_t *lights_art_{nullptr};
  lv_obj_t *theme_row_{nullptr};  // the settings menu's Theme row (its list opens over it)    // ... or the theme's own picture (bar_area_lights)
  std::vector<std::string> lights_;  // what it switches
  void paint_lights_();
 public:
  /// The Help page (the dashboard's): "tiles", "tile-edit", "view" (the map), "queue"
  void open_help(const std::string &mode);
  /// The settings menu (the gear), from the board or the map
  void open_settings() { this->open_settings_(); }
  /// The top bar's time, now (a minute on, or the 12 / 24-hour setting changed).
  void paint_clock();
  /// Where a screenshot taken from the settings went (or that it didn't)
  void screenshot_notice(bool saved, const std::string &file);
 protected:
  lv_obj_t *scrim_{nullptr};    // an open dialog (settings / area / picker)
  // the tile picker
  int pick_slot_{-1};
  std::string pick_area_;       // "" = all areas, "-" = no area
  int pick_cat_{0};
  std::string pick_entity_;
  bool pick_map_{false};  // the Map tile picked (no entity)
  lv_obj_t *pick_list_{nullptr};
  lv_obj_t *pick_areas_{nullptr};
  lv_obj_t *pick_assign_{nullptr};
  std::vector<lv_obj_t *> pick_cat_btns_;
  uint32_t anim_at_{0};
  int anim_frame_{0};
  uint32_t color_(const char *token, uint32_t fallback) const;
  /// A theme's name in the panel's language: Room Tiles' (the payload), else the wording's "theme.<id>".
  std::string theme_name_(const std::string &id) const;

  static void on_tap_(lv_event_t *e);
  static void on_layout_(lv_event_t *e);

  lv_obj_t *root_{nullptr};
  RoomTiles *rt_{nullptr};
  Fonts fonts_;
  std::string layout_;
  std::vector<TileView> tiles_;
  BusyIcons busy_icons_;
};

}  // namespace esphome::room_tiles
