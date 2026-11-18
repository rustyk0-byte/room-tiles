#include "psram_scope.h"

#include <cstdlib>
#include <new>

#include <esp_heap_caps.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace esphome::room_tiles {

// the task inside a scope (one at a time: the main loop's), and how deep
static void *volatile psram_task = nullptr;
static int psram_depth = 0;

PsramScope::PsramScope() : prev_task_(psram_task) {
  psram_task = xTaskGetCurrentTaskHandle();
  ++psram_depth;
}

PsramScope::~PsramScope() {
  if (--psram_depth == 0)
    psram_task = nullptr;
  else
    psram_task = this->prev_task_;
}

static inline void *alloc(size_t n) {
  if (n == 0)
    n = 1;
  if (psram_task != nullptr && psram_task == xTaskGetCurrentTaskHandle()) {
    if (void *p = heap_caps_malloc(n, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT))
      return p;
  }
  return malloc(n);
}

}  // namespace esphome::room_tiles

// The replaceable global allocation functions (the aligned ones are left to
// the library). A failed plain new aborts - the failed-allocation hook
// (room_tiles.cpp) has recorded it first.
void *operator new(size_t n) {
  if (void *p = esphome::room_tiles::alloc(n))
    return p;
  abort();
}
void *operator new[](size_t n) {
  if (void *p = esphome::room_tiles::alloc(n))
    return p;
  abort();
}
void *operator new(size_t n, const std::nothrow_t &) noexcept { return esphome::room_tiles::alloc(n); }
void *operator new[](size_t n, const std::nothrow_t &) noexcept { return esphome::room_tiles::alloc(n); }
void operator delete(void *p) noexcept { free(p); }
void operator delete[](void *p) noexcept { free(p); }
void operator delete(void *p, size_t) noexcept { free(p); }
void operator delete[](void *p, size_t) noexcept { free(p); }
void operator delete(void *p, const std::nothrow_t &) noexcept { free(p); }
void operator delete[](void *p, const std::nothrow_t &) noexcept { free(p); }
