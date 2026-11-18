#include "drag_bar.h"

#include <algorithm>

namespace esphome::room_tiles {

// A scroll bar you can DRAG (LVGL's own only shows where you are): a thin
// thumb in a wider touch strip along the list's right edge; drag or tap the
// strip to jump there. The thumb follows normal scrolling too.
struct DragBar {
  lv_obj_t *list{nullptr};
  lv_obj_t *strip{nullptr};
  lv_obj_t *thumb{nullptr};
};

static void dragbar_update(DragBar *bar) {
  const int h = lv_obj_get_height(bar->list);
  const int y = lv_obj_get_scroll_y(bar->list);
  const int total = y + lv_obj_get_scroll_bottom(bar->list);  // how far it scrolls
  if (total <= 0) {
    lv_obj_add_flag(bar->strip, LV_OBJ_FLAG_HIDDEN);  // (it all fits)
    return;
  }
  lv_obj_remove_flag(bar->strip, LV_OBJ_FLAG_HIDDEN);
  const int th = std::max(36, h * h / (h + total));
  lv_obj_set_height(bar->thumb, th);
  lv_obj_set_y(bar->thumb, (h - th) * std::min(y, total) / total);
}

void dragbar_attach(lv_obj_t *frame, lv_obj_t *list, uint32_t colour) {
  auto *bar = new DragBar;
  bar->list = list;
  lv_obj_set_scrollbar_mode(list, LV_SCROLLBAR_MODE_OFF);  // (this one instead)
  lv_obj_update_layout(list);
  const int h = lv_obj_get_height(list);
  bar->strip = lv_obj_create(frame);
  lv_obj_remove_style_all(bar->strip);
  lv_obj_set_size(bar->strip, 44, h);  // (a finger's width on the 7")
  lv_obj_align_to(bar->strip, list, LV_ALIGN_TOP_RIGHT, 0, 0);
  lv_obj_add_flag(bar->strip, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_remove_flag(bar->strip, LV_OBJ_FLAG_SCROLLABLE);
  bar->thumb = lv_obj_create(bar->strip);
  lv_obj_remove_style_all(bar->thumb);
  lv_obj_set_width(bar->thumb, 8);
  lv_obj_set_x(bar->thumb, 44 - 8 - 4);
  lv_obj_set_style_radius(bar->thumb, 4, 0);
  lv_obj_set_style_bg_opa(bar->thumb, LV_OPA_COVER, 0);
  lv_obj_set_style_bg_color(bar->thumb, lv_color_hex(colour), 0);
  lv_obj_remove_flag(bar->thumb, LV_OBJ_FLAG_CLICKABLE);
  // a press / drag on the strip: the list jumps so the thumb is under the finger
  lv_obj_add_event_cb(
      bar->strip,
      [](lv_event_t *e) {
        auto *bar = static_cast<DragBar *>(lv_event_get_user_data(e));
        lv_point_t p;
        lv_indev_get_point(lv_indev_active(), &p);
        lv_area_t a;
        lv_obj_get_coords(bar->strip, &a);
        const int h = lv_area_get_height(&a);
        const int y = lv_obj_get_scroll_y(bar->list);
        const int total = y + lv_obj_get_scroll_bottom(bar->list);
        if (total <= 0 || h <= 0)
          return;
        const int th = lv_obj_get_height(bar->thumb);
        int pos = p.y - a.y1 - th / 2;
        pos = std::max(0, std::min(pos, h - th));
        lv_obj_scroll_to_y(bar->list, h - th > 0 ? total * pos / (h - th) : 0, LV_ANIM_OFF);
        dragbar_update(bar);
      },
      LV_EVENT_PRESSING, bar);
  lv_obj_add_event_cb(
      list, [](lv_event_t *e) { dragbar_update(static_cast<DragBar *>(lv_event_get_user_data(e))); }, LV_EVENT_SCROLL, bar);
  lv_obj_add_event_cb(
      list, [](lv_event_t *e) { delete static_cast<DragBar *>(lv_event_get_user_data(e)); }, LV_EVENT_DELETE, bar);
  dragbar_update(bar);
}

}  // namespace esphome::room_tiles
