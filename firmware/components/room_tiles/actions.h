// Room Tiles panel: what the user does goes to the Room Tiles integration
// (signed POSTs, docs/DESIGN.md "Panel firmware"), which calls HA. In order,
// on one worker task with one kept-alive connection (a tap is quick).
#pragma once

#include <mutex>
#include <string>

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

namespace esphome::room_tiles {

class ActionSender {
 public:
  void set_base_url(const std::string &url);
  /// A service call on an entity ({"service","entity","data"}).
  void call(const std::string &service, const std::string &entity, const std::string &data_json = "{}");
  /// This panel's own settings ({"settings": {...}}), JSON object text.
  void settings(const std::string &settings_json);

 protected:
  void send_(std::string body);
  static void worker_(void *arg);

  std::mutex lock_;
  std::string base_url_;
  QueueHandle_t queue_{nullptr};
};

}  // namespace esphome::room_tiles
