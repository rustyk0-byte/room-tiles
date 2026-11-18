#include "perf.h"

#include <algorithm>

#include <esp_timer.h>

#include "esphome/core/log.h"

namespace esphome::room_tiles {

static const char *const TAG = "room_tiles.perf";

void FrameStats::attach() {
  if (this->attached_)
    return;
  lv_display_t *d = lv_display_get_default();
  if (d == nullptr)
    return;
  this->attached_ = true;
  for (lv_event_code_t code : {LV_EVENT_REFR_START, LV_EVENT_REFR_READY, LV_EVENT_FLUSH_START, LV_EVENT_FLUSH_FINISH,
                               LV_EVENT_FLUSH_WAIT_START, LV_EVENT_FLUSH_WAIT_FINISH})
    lv_display_add_event_cb(d, &FrameStats::on_event_, code, this);
}

void FrameStats::on_event_(lv_event_t *e) {
  auto *self = static_cast<FrameStats *>(lv_event_get_user_data(e));
  if (!self->running_)
    return;
  const int64_t now = esp_timer_get_time();
  switch (lv_event_get_code(e)) {
    case LV_EVENT_REFR_START:
      self->frame_t0_ = now;
      // (a gap only between frames close together: panning, not idle)
      if (self->ready_t_ != 0 && now - self->ready_t_ < 200000) {
        self->gap_us_ += (uint64_t) (now - self->ready_t_);
        self->gaps_++;
      }
      break;
    case LV_EVENT_REFR_READY: {
      if (self->frame_t0_ == 0)
        break;
      const uint32_t us = (uint32_t) (now - self->frame_t0_);
      self->frame_t0_ = 0;
      if (us < 200)
        break;  // (nothing to redraw: not a frame)
      self->frames_++;
      self->ready_t_ = now;
      self->frame_us_ += us;
      self->frame_max_us_ = std::max(self->frame_max_us_, us);
      break;
    }
    case LV_EVENT_FLUSH_START: {
      auto *a = static_cast<const lv_area_t *>(lv_event_get_param(e));
      if (a != nullptr)
        self->px_ += (uint64_t) lv_area_get_width(a) * lv_area_get_height(a);
      self->flush_t0_ = now;
      break;
    }
    case LV_EVENT_FLUSH_WAIT_START:
      self->flush_t0_ = now;
      break;
    case LV_EVENT_FLUSH_FINISH:
    case LV_EVENT_FLUSH_WAIT_FINISH:
      if (self->flush_t0_ != 0)
        self->flush_us_ += (uint64_t) (now - self->flush_t0_);
      self->flush_t0_ = 0;
      break;
    default:
      break;
  }
}

void FrameStats::start(const std::string &what) {
  this->attach();
  if (this->running_)
    this->log_();
  this->running_ = true;
  this->what_ = what;
  this->note_.clear();
  this->started_us_ = esp_timer_get_time();
  this->frame_t0_ = this->flush_t0_ = 0;
  this->frames_ = this->frame_max_us_ = 0;
  this->frame_us_ = this->flush_us_ = this->px_ = 0;
  this->ready_t_ = 0;
  this->gap_us_ = this->gaps_ = 0;
}

void FrameStats::stop() {
  if (!this->running_)
    return;
  this->log_();
  this->running_ = false;
}

uint32_t FrameStats::age() const {
  return this->running_ ? (uint32_t) ((esp_timer_get_time() - this->started_us_) / 1000) : 0;
}

// "Map pan: 2.4 s, 31 frames 12.9 fps, frame avg 61.0 / max 84.2 ms (flush 9.1), repaint 92% of the screen"
void FrameStats::log_() {
  const float secs = (esp_timer_get_time() - this->started_us_) / 1e6f;
  if (this->frames_ == 0) {
    ESP_LOGI(TAG, "%s: %.1f s, no frames%s%s", this->what_.c_str(), secs, this->note_.empty() ? "" : ", ",
             this->note_.c_str());
    return;
  }
  lv_display_t *d = lv_display_get_default();
  const float screen = d ? (float) lv_display_get_horizontal_resolution(d) * lv_display_get_vertical_resolution(d) : 1;
  ESP_LOGI(TAG,
           "%s: %.1f s, %u frames %.1f fps, frame avg %.1f / max %.1f ms (flush %.1f), between frames %.1f ms, "
           "repaint %.0f%% of the screen%s%s",
           this->what_.c_str(), secs, (unsigned) this->frames_, secs > 0 ? this->frames_ / secs : 0.0f,
           this->frame_us_ / 1000.0f / this->frames_, this->frame_max_us_ / 1000.0f,
           this->flush_us_ / 1000.0f / this->frames_, this->gaps_ ? this->gap_us_ / 1000.0f / this->gaps_ : 0.0f,
           100.0f * this->px_ / this->frames_ / screen, this->note_.empty() ? "" : ", ", this->note_.c_str());
}

}  // namespace esphome::room_tiles
