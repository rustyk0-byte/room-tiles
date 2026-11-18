// Room Tiles panel: C++ allocations in PSRAM while a scope lives.
//
// ESPHome sets ESP-IDF's PSRAM up for explicit use only (CAPS_ALLOC): plain
// new / std::string / std::vector all come from internal RAM, ~150 KB of it
// free at best. The panel's model (a payload of tens of KB: catalog, maps,
// markers - many small objects, two models while one replaces the other), a
// map's index and its markers filled it up and the panel aborted.
//
// While a PsramScope lives, operator new on ITS task takes PSRAM (internal
// RAM if PSRAM is full); everything else - other tasks, Wi-Fi, C code's
// malloc - is untouched. operator delete frees either (ESP-IDF's free()
// knows the region). Scopes nest.
#pragma once

namespace esphome::room_tiles {

class PsramScope {
 public:
  PsramScope();
  ~PsramScope();
  PsramScope(const PsramScope &) = delete;
  PsramScope &operator=(const PsramScope &) = delete;

 private:
  void *prev_task_;
};

}  // namespace esphome::room_tiles
