#include "screenshot.h"

#include <algorithm>
#include <cstring>

#include <esp_err.h>
#include <esp_heap_caps.h>
#include <esp_http_client.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <src/display/lv_display_private.h>
#include <src/draw/lv_draw_private.h>

#include "esphome/core/log.h"
#include "signing.h"

namespace esphome::room_tiles {

static const char *const TAG = "room_tiles.screenshot";
static const char *const SCREENSHOT_PATH = "/api/room_tiles/panel/screenshot";

int Screenshot::result(std::string &file) {
  const int r = this->result_.exchange(0);
  if (r == 1)
    file = this->file_;
  return r;
}

bool Screenshot::take(bool tell) {
  if (this->state_ != IDLE) {
    ESP_LOGW(TAG, "One is still on its way");
    return false;
  }
  this->tell_ = tell;
  lv_display_t *disp = lv_display_get_default();
  if (disp == nullptr || this->base_url_.empty()) {
    ESP_LOGW(TAG, "Not connected to Room Tiles yet");
    return false;
  }
  this->w_ = lv_display_get_horizontal_resolution(disp);
  this->h_ = lv_display_get_vertical_resolution(disp);
  this->px_ = static_cast<uint16_t *>(
      heap_caps_calloc((size_t) this->w_ * this->h_, sizeof(uint16_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (this->px_ == nullptr) {
    ESP_LOGW(TAG, "No room for it");
    return false;
  }
  if (!this->hooked_) {
    this->hooked_ = true;
    lv_display_add_event_cb(disp, &Screenshot::on_display_, LV_EVENT_FLUSH_START, this);
    lv_display_add_event_cb(disp, &Screenshot::on_display_, LV_EVENT_REFR_READY, this);
  }
  this->flushed_ = 0;
  this->state_ = CAPTURING;
  // the whole screen drawn again (every layer: the board or map, dialogs)
  lv_obj_invalidate(lv_display_get_screen_active(disp));
  ESP_LOGI(TAG, "Taking a screenshot");
  return true;
}

void Screenshot::on_display_(lv_event_t *e) {
  auto *self = static_cast<Screenshot *>(lv_event_get_user_data(e));
  if (self->state_ != CAPTURING)
    return;
  auto *disp = static_cast<lv_display_t *>(lv_event_get_target(e));
  if (lv_event_get_code(e) == LV_EVENT_REFR_READY) {
    if (self->flushed_ == 0)
      return;  // (not drawn yet)
    ESP_LOGI(TAG, "Captured %u of %u pixels - sending", (unsigned) self->flushed_,
             (unsigned) (self->w_ * self->h_));
    self->state_ = SENDING;
    self->url_ = self->base_url_;  // (the task's own copy)
    if (xTaskCreate(&Screenshot::upload_, "rt_shot", 6144, self, 3, nullptr) != pdPASS) {
      heap_caps_free(self->px_);
      self->px_ = nullptr;
      self->state_ = IDLE;
      if (self->tell_)
        self->result_ = 2;
    }
    return;
  }
  // FLUSH_START: this part of the screen, as it goes to the display
  const auto *area = static_cast<const lv_area_t *>(lv_event_get_param(e));
  lv_layer_t *layer = disp->layer_head;
  if (area == nullptr || layer == nullptr || layer->draw_buf == nullptr)
    return;
  const lv_draw_buf_t *buf = layer->draw_buf;
  if (buf->header.cf != LV_COLOR_FORMAT_RGB565)
    return;  // (the panels draw in RGB565)
  const int x1 = std::max<int>(area->x1, 0), x2 = std::min<int>(area->x2, self->w_ - 1);
  const int y1 = std::max<int>(area->y1, 0), y2 = std::min<int>(area->y2, self->h_ - 1);
  if (x1 > x2 || y1 > y2)
    return;
  const lv_area_t &ba = layer->buf_area;  // (where the buffer's first pixel is)
  const uint32_t stride = buf->header.stride;
  const size_t row_bytes = (size_t) (x2 - x1 + 1) * 2;
  for (int y = y1; y <= y2; y++) {
    const uint8_t *src = buf->data + (size_t) (y - ba.y1) * stride + (size_t) (x1 - ba.x1) * 2;
    memcpy(self->px_ + (size_t) y * self->w_ + x1, src, row_bytes);
  }
  self->flushed_ += (uint32_t) (x2 - x1 + 1) * (uint32_t) (y2 - y1 + 1);
}

void Screenshot::upload_(void *arg) {
  auto *self = static_cast<Screenshot *>(arg);
  bool saved = false;
  const auto *data = reinterpret_cast<const uint8_t *>(self->px_);
  const size_t size = (size_t) self->w_ * self->h_ * 2;
  std::string query;
  const std::string params = "&w=" + std::to_string(self->w_) + "&h=" + std::to_string(self->h_);
  if (sign_request("POST", SCREENSHOT_PATH, params, data, size, query) != SignResult::OK) {
    ESP_LOGW(TAG, "Not sent (not connected to Room Tiles yet)");
  } else {
    self->url_ += SCREENSHOT_PATH + query;
    esp_http_client_config_t cfg = {};
    cfg.url = self->url_.c_str();
    cfg.method = HTTP_METHOD_POST;
    cfg.timeout_ms = 30000;
    cfg.disable_auto_redirect = true;
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (client != nullptr)
      esp_http_client_set_header(client, "Content-Type", "application/octet-stream");
    const uint32_t start = xTaskGetTickCount();
    esp_err_t err = client != nullptr ? esp_http_client_open(client, (int) size) : ESP_ERR_NO_MEM;
    size_t sent = 0;
    while (err == ESP_OK && sent < size) {
      const int n = esp_http_client_write(client, reinterpret_cast<const char *>(data) + sent,
                                          (int) std::min<size_t>(size - sent, 16384));
      if (n <= 0)
        err = ESP_FAIL;
      else
        sent += (size_t) n;
    }
    int status = 0;
    char answer[256] = {};
    if (err == ESP_OK && esp_http_client_fetch_headers(client) >= 0) {
      status = esp_http_client_get_status_code(client);
      esp_http_client_read_response(client, answer, sizeof(answer) - 1);
    } else if (err == ESP_OK) {
      err = ESP_FAIL;
    }
    const unsigned ms = (unsigned) ((xTaskGetTickCount() - start) * portTICK_PERIOD_MS);
    if (err != ESP_OK) {
      ESP_LOGW(TAG, "Couldn't send it (%s)", esp_err_to_name(err));
    } else if (status != 200) {
      ESP_LOGW(TAG, "Room Tiles refused it (%d)", status);
    } else {
      // {"ok": true, "file": "<name>.png"}: the name, for the panel to say
      std::string a(answer), file;
      const size_t k = a.find("\"file\"");
      const size_t q1 = k == std::string::npos ? k : a.find('"', a.find(':', k) + 1);
      const size_t q2 = q1 == std::string::npos ? q1 : a.find('"', q1 + 1);
      if (q2 != std::string::npos)
        file = a.substr(q1 + 1, q2 - q1 - 1);
      ESP_LOGI(TAG, "Sent in %u ms: %s", ms, file.c_str());
      self->file_ = file;
      saved = true;
    }
    if (client != nullptr)
      esp_http_client_cleanup(client);
  }
  heap_caps_free(self->px_);
  self->px_ = nullptr;
  if (self->tell_)
    self->result_ = saved ? 1 : 2;
  self->state_ = IDLE;
  vTaskDelete(nullptr);
}

}  // namespace esphome::room_tiles
