// Room Tiles panel: a scroll bar you can drag, for a scrolling list (LVGL's
// own only shows where you are).
#pragma once

#include <cstdint>

#include <lvgl.h>

namespace esphome::room_tiles {

/// A thin thumb in a finger-wide (44 px) strip along `list`'s right edge, made
/// in `frame` (the list's parent): drag or tap the strip to jump there; it
/// follows normal scrolling and hides while everything fits. Freed with the list.
void dragbar_attach(lv_obj_t *frame, lv_obj_t *list, uint32_t colour);

}  // namespace esphome::room_tiles
