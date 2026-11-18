// Room Tiles panel: a small software rasterizer for the map tiles - filled,
// anti-aliased polygons straight into an RGB565 buffer (thick lines and
// dashes are polygons too). It touches no LVGL state, so it runs on the map
// drawing task, off the main loop.
#pragma once

#include <cstdint>
#include <vector>

namespace esphome::room_tiles {

struct FPt {
  float x, y;
};

class Raster {
 public:
  /// Draw into `buf` (w x h RGB565, row-major) whose top-left is at (ox, oy)
  /// in the drawing's coordinates.
  Raster(uint16_t *buf, int w, int h, float ox, float oy) : buf_(buf), w_(w), h_(h), ox_(ox), oy_(oy) {}

  void clear(uint32_t rgb);
  /// A filled polygon (even-odd), `opa` 0-255, anti-aliased edges.
  void polygon(const FPt *pts, int n, uint32_t rgb, uint8_t opa = 255);
  /// A line `width` wide; `square` = its ends extended by half the width.
  void line(FPt a, FPt b, float width, uint32_t rgb, uint8_t opa = 255, bool square = false);
  /// A dashed line (`dash` on, `gap` off, in drawing units).
  void dashed(FPt a, FPt b, float width, float dash, float gap, uint32_t rgb, uint8_t opa);

 protected:
  uint16_t *buf_;
  int w_, h_;
  float ox_, oy_;
  std::vector<uint16_t> cov_;  // (scratch: one row's coverage, the crossings)
  std::vector<float> xs_;
};

/// 0xRRGGBB -> RGB565
inline uint16_t rgb565(uint32_t rgb) {
  return (uint16_t) (((rgb >> 8) & 0xF800) | ((rgb >> 5) & 0x07E0) | ((rgb >> 3) & 0x001F));
}

}  // namespace esphome::room_tiles
