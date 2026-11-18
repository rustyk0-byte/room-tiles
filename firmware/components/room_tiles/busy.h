// Room Tiles panel: the "working on it" stopwatch - a ring with its crown and
// a hand sweeping once a second (vector-drawn: crisp at any size). Small over
// a tile that's waiting (a change on its way, its first state), big for
// whole-screen waits.
#pragma once

#include <deque>

#include <lvgl.h>

namespace esphome::room_tiles {

class BusyIcons {
 public:
  /// A stopwatch of `size` px centred in `parent` (hidden until shown).
  lv_obj_t *make(lv_obj_t *parent, int size, uint32_t colour);
  static void show(lv_obj_t *busy, bool on);
  /// Move every visible hand (call often; draws ~30 times a second).
  void animate(uint32_t now);
  /// Forget them all (their parents were deleted).
  void clear() { this->items_.clear(); }
  /// Forget the ones inside `parent` (about to be deleted).
  void forget_in(lv_obj_t *parent);

 protected:
  struct Item {
    lv_obj_t *root{nullptr};
    lv_obj_t *hand{nullptr};
    lv_point_precise_t pts[2];  // (lv_line keeps a pointer: they live here)
    float c{0};  // the hand's centre and length, inside the ring's border
    float r{0};
  };
  std::deque<Item> items_;
  uint32_t drawn_at_{0};
};

}  // namespace esphome::room_tiles
