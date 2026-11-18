#include "raster.h"

#include <algorithm>
#include <cmath>
#include <vector>

namespace esphome::room_tiles {

static const int SUB = 4;  // sub-rows per pixel row (vertical anti-aliasing)

void Raster::clear(uint32_t rgb) {
  const uint16_t c = rgb565(rgb);
  std::fill(this->buf_, this->buf_ + this->w_ * this->h_, c);
}

static inline uint16_t blend565(uint16_t dst, uint16_t src, uint32_t a /* 0..256 */) {
  if (a >= 256)
    return src;
  const uint32_t ia = 256 - a;
  const uint32_t r = (((src >> 11) & 0x1F) * a + ((dst >> 11) & 0x1F) * ia) >> 8;
  const uint32_t g = (((src >> 5) & 0x3F) * a + ((dst >> 5) & 0x3F) * ia) >> 8;
  const uint32_t b = ((src & 0x1F) * a + (dst & 0x1F) * ia) >> 8;
  return (uint16_t) ((r << 11) | (g << 5) | b);
}

void Raster::polygon(const FPt *pts, int n, uint32_t rgb, uint8_t opa) {
  if (n < 3 || opa == 0)
    return;
  // its box, in this buffer's pixels: nothing to do when it misses
  float x0 = 1e9f, y0 = 1e9f, x1 = -1e9f, y1 = -1e9f;
  for (int i = 0; i < n; i++) {
    x0 = std::min(x0, pts[i].x - this->ox_);
    x1 = std::max(x1, pts[i].x - this->ox_);
    y0 = std::min(y0, pts[i].y - this->oy_);
    y1 = std::max(y1, pts[i].y - this->oy_);
  }
  if (x1 < 0 || y1 < 0 || x0 >= this->w_ || y0 >= this->h_)
    return;
  const int row0 = std::max(0, (int) floorf(y0)), row1 = std::min(this->h_ - 1, (int) ceilf(y1));
  const int col0 = std::max(0, (int) floorf(x0)), col1 = std::min(this->w_ - 1, (int) ceilf(x1));
  const uint16_t src = rgb565(rgb);
  // coverage per pixel of one row: SUB sub-rows x 64 each = 256 = full
  std::vector<uint16_t> &cov = this->cov_;
  std::vector<float> &xs = this->xs_;
  cov.assign(this->w_, 0);
  for (int row = row0; row <= row1; row++) {
    std::fill(cov.begin() + col0, cov.begin() + col1 + 1, 0);
    bool any = false;
    for (int s = 0; s < SUB; s++) {
      const float y = row + (s + 0.5f) / SUB + this->oy_;
      xs.clear();
      for (int i = 0, j = n - 1; i < n; j = i++) {
        const FPt &a = pts[j], &b = pts[i];
        if ((a.y <= y) != (b.y <= y))
          xs.push_back(a.x + (y - a.y) * (b.x - a.x) / (b.y - a.y) - this->ox_);
      }
      if (xs.size() < 2)
        continue;
      std::sort(xs.begin(), xs.end());
      for (size_t k = 0; k + 1 < xs.size(); k += 2) {
        float xa = std::max(0.0f, xs[k]), xb = std::min((float) this->w_, xs[k + 1]);
        if (xb <= xa)
          continue;
        any = true;
        const int ia = (int) xa, ib = (int) xb;
        // 64 per sub-row; the end pixels by how much of them is inside
        if (ia == ib) {
          cov[ia] += (uint16_t) ((xb - xa) * 64);
          continue;
        }
        cov[ia] += (uint16_t) ((ia + 1 - xa) * 64);
        for (int x = ia + 1; x < ib; x++)
          cov[x] += 64;
        if (ib < this->w_)
          cov[ib] += (uint16_t) ((xb - ib) * 64);
      }
    }
    if (!any)
      continue;
    uint16_t *line = this->buf_ + row * this->w_;
    for (int x = col0; x <= col1; x++) {
      const uint32_t c = cov[x];
      if (c == 0)
        continue;
      line[x] = blend565(line[x], src, (std::min<uint32_t>(c, 256) * opa) / 255);
    }
  }
}

void Raster::line(FPt a, FPt b, float width, uint32_t rgb, uint8_t opa, bool square) {
  float dx = b.x - a.x, dy = b.y - a.y;
  const float len = sqrtf(dx * dx + dy * dy);
  if (len < 1e-3f)
    return;
  dx /= len;
  dy /= len;
  const float hw = width / 2;
  if (square) {  // (walls meet without notches)
    a = {a.x - dx * hw, a.y - dy * hw};
    b = {b.x + dx * hw, b.y + dy * hw};
  }
  const float nx = -dy * hw, ny = dx * hw;
  const FPt q[4] = {{a.x + nx, a.y + ny}, {b.x + nx, b.y + ny}, {b.x - nx, b.y - ny}, {a.x - nx, a.y - ny}};
  this->polygon(q, 4, rgb, opa);
}

void Raster::dashed(FPt a, FPt b, float width, float dash, float gap, uint32_t rgb, uint8_t opa) {
  const float dx = b.x - a.x, dy = b.y - a.y;
  const float len = sqrtf(dx * dx + dy * dy);
  if (len < 1e-3f || dash <= 0)
    return;
  for (float t = 0; t < len; t += dash + gap) {
    const float e = std::min(len, t + dash);
    this->line({a.x + dx * t / len, a.y + dy * t / len}, {a.x + dx * e / len, a.y + dy * e / len}, width, rgb, opa);
  }
}

}  // namespace esphome::room_tiles
