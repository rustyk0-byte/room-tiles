// Room Tiles panel: containers kept in PSRAM (32 MB) instead of the internal
// RAM (~500 KB) every small malloc() lands in otherwise.
#pragma once

#include <cstddef>
#include <cstdlib>
#include <string>

#include <esp_heap_caps.h>

namespace esphome::room_tiles {

template<class T> struct PsramAllocator {
  using value_type = T;
  PsramAllocator() = default;
  template<class U> PsramAllocator(const PsramAllocator<U> &) {}
  T *allocate(std::size_t n) {
    void *p = heap_caps_malloc(n * sizeof(T), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (p == nullptr)
      p = heap_caps_malloc(n * sizeof(T), MALLOC_CAP_8BIT);  // (no PSRAM left: internal)
    if (p == nullptr)
      abort();  // (out of memory everywhere; no exceptions in this build)
    return static_cast<T *>(p);
  }
  void deallocate(T *p, std::size_t) { heap_caps_free(p); }
  template<class U> bool operator==(const PsramAllocator<U> &) const { return true; }
  template<class U> bool operator!=(const PsramAllocator<U> &) const { return false; }
};

using pstring = std::basic_string<char, std::char_traits<char>, PsramAllocator<char>>;

}  // namespace esphome::room_tiles
