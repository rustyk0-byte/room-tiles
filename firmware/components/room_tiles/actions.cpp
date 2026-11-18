#include "actions.h"

#include <esp_http_client.h>
#include <freertos/task.h>

#include "esphome/core/log.h"
#include "signing.h"

namespace esphome::room_tiles {

static const char *const TAG = "room_tiles.actions";
static const char *const ACTION_PATH = "/api/room_tiles/panel/action";

static std::string quoted(const std::string &s) {
  std::string out = "\"";
  for (char c : s) {
    if (c == '"' || c == '\\')
      out += '\\';
    out += c;
  }
  return out + "\"";
}

void ActionSender::set_base_url(const std::string &url) {
  std::lock_guard<std::mutex> g(this->lock_);
  this->base_url_ = url;
}

void ActionSender::call(const std::string &service, const std::string &entity, const std::string &data_json) {
  this->send_("{\"service\":" + quoted(service) + ",\"entity\":" + quoted(entity) + ",\"data\":" +
              (data_json.empty() ? std::string("{}") : data_json) + "}");
}

void ActionSender::settings(const std::string &settings_json) { this->send_("{\"settings\":" + settings_json + "}"); }

void ActionSender::send_(std::string body) {
  if (this->queue_ == nullptr) {
    this->queue_ = xQueueCreate(16, sizeof(std::string *));
    xTaskCreate(&ActionSender::worker_, "rt_act", 6144, this, 6, nullptr);
  }
  auto *item = new std::string(std::move(body));
  if (xQueueSend(this->queue_, &item, 0) != pdTRUE) {
    ESP_LOGW(TAG, "Too many taps waiting - dropped one");
    delete item;
  }
}

void ActionSender::worker_(void *arg) {
  auto *self = static_cast<ActionSender *>(arg);
  esp_http_client_handle_t client = nullptr;
  std::string *item = nullptr;
  for (;;) {
    if (xQueueReceive(self->queue_, &item, portMAX_DELAY) != pdTRUE)
      continue;
    std::string base;
    {
      std::lock_guard<std::mutex> g(self->lock_);
      base = self->base_url_;
    }
    std::string query;
    SignResult signed_ok = base.empty() ? SignResult::NO_KEY : sign_query(item, query);
    if (signed_ok != SignResult::OK) {
      ESP_LOGW(TAG, "Not sent (not connected to Room Tiles yet): %s", item->c_str());
      delete item;
      continue;
    }
    const std::string url = base + ACTION_PATH + query;
    const uint32_t start = xTaskGetTickCount();
    if (client == nullptr) {
      esp_http_client_config_t cfg = {};
      cfg.url = url.c_str();
      cfg.method = HTTP_METHOD_POST;
      cfg.timeout_ms = 5000;
      cfg.keep_alive_enable = true;
      cfg.disable_auto_redirect = true;
      client = esp_http_client_init(&cfg);
    } else {
      esp_http_client_set_url(client, url.c_str());
    }
    esp_http_client_set_method(client, HTTP_METHOD_POST);
    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_post_field(client, item->data(), item->size());
    esp_err_t err = esp_http_client_perform(client);
    const int status = err == ESP_OK ? esp_http_client_get_status_code(client) : 0;
    const uint32_t ms = (xTaskGetTickCount() - start) * portTICK_PERIOD_MS;
    if (err != ESP_OK) {
      ESP_LOGW(TAG, "Couldn't send (%s): %s", esp_err_to_name(err), item->c_str());
      esp_http_client_cleanup(client);  // a fresh connection next time
      client = nullptr;
    } else if (status != 200) {
      ESP_LOGW(TAG, "Room Tiles refused (%d): %s", status, item->c_str());
    } else {
      ESP_LOGD(TAG, "Sent in %u ms: %s", (unsigned) ms, item->c_str());
    }
    delete item;
  }
}

}  // namespace esphome::room_tiles
