#include "busy.h"

#include <cmath>

namespace esphome::room_tiles {

lv_obj_t *BusyIcons::make(lv_obj_t *parent, int size, uint32_t colour) {
  this->items_.emplace_back();
  Item &it = this->items_.back();
  const int stroke = size >= 48 ? size / 16 : 2;
  const int inner = size - 2 * stroke;  // (children sit inside the ring's border)
  it.c = inner / 2.0f;
  it.r = size * 0.36f;
  // the whole stopwatch (room above the ring for the crown)
  it.root = lv_obj_create(parent);
  lv_obj_remove_style_all(it.root);
  lv_obj_set_size(it.root, size, size + size / 8);
  lv_obj_center(it.root);
  lv_obj_remove_flag(it.root, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_remove_flag(it.root, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_add_flag(it.root, LV_OBJ_FLAG_HIDDEN);
  // the crown
  lv_obj_t *crown = lv_obj_create(it.root);
  lv_obj_remove_style_all(crown);
  lv_obj_set_size(crown, size / 4, size / 8);
  lv_obj_align(crown, LV_ALIGN_TOP_MID, 0, 0);
  lv_obj_set_style_radius(crown, size / 16, 0);
  lv_obj_set_style_bg_opa(crown, LV_OPA_COVER, 0);
  lv_obj_set_style_bg_color(crown, lv_color_hex(colour), 0);
  // the ring (a dark face, so it reads over a tile's art too)
  lv_obj_t *ring = lv_obj_create(it.root);
  lv_obj_remove_style_all(ring);
  lv_obj_set_size(ring, size, size);
  lv_obj_align(ring, LV_ALIGN_BOTTOM_MID, 0, 0);
  lv_obj_set_style_radius(ring, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_bg_opa(ring, LV_OPA_80, 0);
  lv_obj_set_style_bg_color(ring, lv_color_hex(0x000000), 0);
  lv_obj_set_style_border_width(ring, stroke, 0);
  lv_obj_set_style_border_color(ring, lv_color_hex(colour), 0);
  lv_obj_remove_flag(ring, LV_OBJ_FLAG_SCROLLABLE);
  // the hand, from the centre
  it.hand = lv_line_create(ring);
  lv_obj_set_size(it.hand, inner, inner);
  lv_obj_set_pos(it.hand, 0, 0);
  lv_obj_set_style_line_width(it.hand, stroke, 0);
  lv_obj_set_style_line_color(it.hand, lv_color_hex(0xFFFFFF), 0);
  lv_obj_set_style_line_rounded(it.hand, true, 0);
  it.pts[0] = {(lv_value_precise_t) it.c, (lv_value_precise_t) it.c};
  it.pts[1] = it.pts[0];
  lv_line_set_points(it.hand, it.pts, 2);
  // the centre dot
  lv_obj_t *dot = lv_obj_create(ring);
  lv_obj_remove_style_all(dot);
  const int d = stroke * 2 + 2;
  lv_obj_set_size(dot, d, d);
  lv_obj_center(dot);
  lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_bg_opa(dot, LV_OPA_COVER, 0);
  lv_obj_set_style_bg_color(dot, lv_color_hex(colour), 0);
  return it.root;
}

void BusyIcons::show(lv_obj_t *busy, bool on) {
  if (busy == nullptr)
    return;
  if (on)
    lv_obj_remove_flag(busy, LV_OBJ_FLAG_HIDDEN);
  else
    lv_obj_add_flag(busy, LV_OBJ_FLAG_HIDDEN);
}

void BusyIcons::animate(uint32_t now) {
  if (now - this->drawn_at_ < 50)
    return;
  this->drawn_at_ = now;
  // one sweep in 3 s (from 12 o'clock, clockwise): something to watch while
  // waiting, not a distraction
  const float a = (now % 3000) / 3000.0f * 2.0f * (float) M_PI;
  for (Item &it : this->items_) {
    if (it.root == nullptr || lv_obj_has_flag(it.root, LV_OBJ_FLAG_HIDDEN))
      continue;
    it.pts[1] = {(lv_value_precise_t) (it.c + it.r * sinf(a)), (lv_value_precise_t) (it.c - it.r * cosf(a))};
    lv_line_set_points(it.hand, it.pts, 2);
  }
}

}  // namespace esphome::room_tiles
