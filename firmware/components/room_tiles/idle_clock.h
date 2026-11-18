// Room Tiles panel: the idle clock (docs/DESIGN.md "When idle"). After the
// screen's idle time, instead of going dark, a clock over the board:
//   digital  the time, the weekday and date in the panel's language
//   analog   a dial, ticks and hands drawn in the theme's colours
//   theme    the theme's own face and hands (its clock.json: where the hands
//            turn, their pivots and lengths, where the date goes - the
//            pictures at their own fixed sizes, turned and scaled here)
// An optional second hand (analog / theme). A touch on it brings the board
// back (on its release: the touch never reaches a tile under it).
#pragma once

#include <string>

#include "lvgl.h"

namespace esphome::room_tiles {

class RoomTiles;
struct Fonts;

class IdleClock {
 public:
  enum Face : int { DIGITAL = 1, ANALOG = 2, THEME = 3 };
  /// Over everything (the top layer), `w` x `h` (the screen). THEME needs
  /// the theme's clock (else: show ANALOG).
  void show(RoomTiles *rt, const Fonts &fonts, int face, bool seconds, int w, int h);
  void hide();
  bool shown() const { return this->root_ != nullptr; }
  /// A finger on it right now (the board comes back on its release).
  bool pressed() const { return this->pressed_; }
  /// Each loop: redraws when the minute (with a second hand: the second)
  /// changes.
  void tick();

 protected:
  struct Hand {
    lv_obj_t *obj{nullptr};    // a line (analog) or a picture (theme)
    lv_point_precise_t pts[2]{};
    float reach{0};            // analog: its length in pixels
  };
  void build_analog_(lv_obj_t *parent, int s);
  bool build_theme_(int w, int h);
  void date_label_(lv_obj_t *parent, int x, int y, const char *align, const lv_font_t *font, uint32_t colour);
  void paint_();
  std::string short_date_() const;
  static void on_press_(lv_event_t *e);
  static void on_release_(lv_event_t *e);

  RoomTiles *rt_{nullptr};
  const Fonts *fonts_{nullptr};
  int face_{DIGITAL};
  bool seconds_{false};
  float c_{0};  // analog: the dial's center (in its own box)
  lv_obj_t *root_{nullptr};
  lv_obj_t *time_{nullptr};
  lv_obj_t *ampm_{nullptr};
  lv_obj_t *date_{nullptr};
  int date_x_{0};       // (the date's anchor and alignment: re-aligned as it changes)
  int date_align_{0};   // -1 left, 0 center, 1 right
  Hand hour_, minute_, second_;
  int shown_{-1};       // the minute (or second) drawn
  int painted_min_{-1}; // the minute the hour / minute hands and date show
  bool pressed_{false};
};

}  // namespace esphome::room_tiles
