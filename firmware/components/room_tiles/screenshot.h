// Room Tiles panel: a screenshot, sent to the integration (it saves a PNG in
// HA's media folder: Media > My media > room_tiles).
//
// The screen is redrawn once, whole, and each part is copied as LVGL hands it
// to the display (LV_EVENT_FLUSH_START) - exactly what's on the glass, the
// dialogs and the map's own drawing included. Then a task POSTs it, signed
// like the panel's other requests (raw RGB565, 1024 x 600: 1.2 MB in PSRAM
// while it's on its way).
#pragma once

#include <atomic>
#include <cstdint>
#include <string>

#include <lvgl.h>

namespace esphome::room_tiles {

class Screenshot {
 public:
  void set_base_url(const std::string &url) { this->base_url_ = url; }
  /// Take one (ignored while one is still on its way); `tell`: the panel
  /// says where it went (taken from its settings). False: couldn't start.
  bool take(bool tell = false);
  /// A told one's outcome, once: 0 nothing (yet), 1 saved (`file`: its name
  /// in the folder), 2 not saved. Main loop.
  int result(std::string &file);

 protected:
  enum State : uint8_t { IDLE, CAPTURING, SENDING };
  static void on_display_(lv_event_t *e);
  static void upload_(void *arg);

  std::atomic<uint8_t> state_{IDLE};
  bool hooked_{false};
  uint16_t *px_{nullptr};
  int w_{0}, h_{0};
  uint32_t flushed_{0};  // pixels copied this capture
  std::string base_url_;
  std::string url_;  // (the upload task's: the base URL, then the whole)
  bool tell_{false};
  std::atomic<uint8_t> result_{0};  // (set by the upload task: result())
  std::string file_;                // (the saved file's name: before result_)
};

}  // namespace esphome::room_tiles
