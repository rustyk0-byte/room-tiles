// Room Tiles panel: frame statistics for profiling - how long each display
// refresh takes, how many there are, how much of the screen they repaint and
// how much of that is the flush to the panel. Kept on purpose (not a temporary
// probe): the map logs one line per phase (idle / pan / zoom), so a change
// (markers...) shows its cost in the log.
#pragma once

#include <cstdint>
#include <string>

#include <lvgl.h>

namespace esphome::room_tiles {

class FrameStats {
 public:
  /// Listen to the display's refresh events (once; cheap when not running).
  void attach();
  /// Start a phase called `what` (the running one is logged first).
  void start(const std::string &what);
  /// Log the running phase and stop.
  void stop();
  bool running() const { return this->running_; }
  const std::string &phase() const { return this->what_; }
  /// ms since the phase started
  uint32_t age() const;
  /// Something to add to the phase's line ("20 tiles in 180 ms").
  void note(const std::string &text) { this->note_ = text; }

 protected:
  static void on_event_(lv_event_t *e);
  void log_();

  bool attached_{false};
  bool running_{false};
  std::string what_;
  std::string note_;
  int64_t started_us_{0};
  int64_t frame_t0_{0};
  int64_t flush_t0_{0};
  uint32_t frames_{0};
  uint64_t frame_us_{0};
  uint32_t frame_max_us_{0};
  uint64_t flush_us_{0};  // in flush_cb + waiting for the panel
  uint64_t px_{0};        // pixels repainted
  int64_t ready_t_{0};    // the last frame's end
  uint64_t gap_us_{0};    // from a frame's end to the next one's start (the rest of the main loop)
  uint32_t gaps_{0};
};


}  // namespace esphome::room_tiles
