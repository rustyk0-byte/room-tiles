#include "map_draw.h"

#include <algorithm>
#include <cmath>

#include "raster.h"

namespace esphome::room_tiles {

// MIRRORED: frontend/src/plan-draw.ts SHAPE_ORDER - a change here must be made there too.
// shapes are drawn by TYPE, bottom to top (plan-draw.ts SHAPE_ORDER)
static int shape_rank(const std::string &style) {
  static const char *const ORDER[] = {"grass", "paving", "deck", "water", "floor"};
  for (int i = 0; i < 5; i++)
    if (style == ORDER[i])
      return i;
  return 5;
}

static uint32_t shape_colour(const MapColors &c, const std::string &style) {
  if (style == "water")
    return c.water;
  if (style == "grass")
    return c.grass;
  if (style == "deck")
    return c.deck;
  if (style == "paving")
    return c.paving;
  return c.floor;
}

// ---- the index ------------------------------------------------------------------

static void box_of(const std::vector<Pt> &pts, float pad, float &x0, float &y0, float &x1, float &y1) {
  x0 = y0 = 1e30f;
  x1 = y1 = -1e30f;
  for (const Pt &p : pts) {
    x0 = std::min(x0, p.x);
    y0 = std::min(y0, p.y);
    x1 = std::max(x1, p.x);
    y1 = std::max(y1, p.y);
  }
  x0 -= pad;
  y0 -= pad;
  x1 += pad;
  y1 += pad;
}

MapIndex::MapIndex(const MapSpec &m) {
  auto add = [this](Kind kind, size_t i, float x0, float y0, float x1, float y1) {
    this->items_.push_back(Item{kind, (uint16_t) i, x0, y0, x1, y1});
  };
  // draw order: shapes by type, room floors, outlines (generated maps), walls,
  // windows, openings
  std::vector<size_t> shapes(m.shapes.size());
  for (size_t i = 0; i < shapes.size(); i++)
    shapes[i] = i;
  std::stable_sort(shapes.begin(), shapes.end(),
                   [&m](size_t a, size_t b) { return shape_rank(m.shapes[a].style) < shape_rank(m.shapes[b].style); });
  float x0, y0, x1, y1;
  for (size_t i : shapes) {
    box_of(m.shapes[i].points, 0, x0, y0, x1, y1);
    add(SHAPE, i, x0, y0, x1, y1);
  }
  for (size_t i = 0; i < m.zones.size(); i++)
    if (!m.zones[i].outdoor && m.zones[i].vacuum.empty()) {
      box_of(m.zones[i].points, 0, x0, y0, x1, y1);
      add(FLOOR, i, x0, y0, x1, y1);
    }
  // (every zone: a special view's room looks, drawn only when it has one)
  for (size_t i = 0; i < m.zones.size(); i++) {
    box_of(m.zones[i].points, m.wall_width, x0, y0, x1, y1);
    add(ZONE, i, x0, y0, x1, y1);
  }
  if (m.generated)
    for (size_t i = 0; i < m.zones.size(); i++)
      if (m.zones[i].vacuum.empty()) {
        box_of(m.zones[i].points, m.wall_width, x0, y0, x1, y1);  // (a 2 px outline: a generous pad)
        add(OUTLINE, i, x0, y0, x1, y1);
      }
  auto segs = [&](const std::vector<std::array<float, 4>> &v, Kind kind, float pad) {
    for (size_t i = 0; i < v.size(); i++) {
      const auto &s = v[i];
      add(kind, i, std::min(s[0], s[2]) - pad, std::min(s[1], s[3]) - pad, std::max(s[0], s[2]) + pad,
          std::max(s[1], s[3]) + pad);
    }
  };
  segs(m.walls, WALL, m.wall_width);
  segs(m.windows, WINDOW, m.wall_width);
  segs(m.openings, OPENING, m.wall_width);
  for (size_t i = 0; i < m.zones.size(); i++) {
    box_of(m.zones[i].points, m.wall_width, x0, y0, x1, y1);
    add(ZONE_TOP, i, x0, y0, x1, y1);
  }

  // the grid over everything drawn: ~8 items a cell, 4..64 cells a side
  float gx0 = 1e30f, gy0 = 1e30f, gx1 = -1e30f, gy1 = -1e30f;
  for (const Item &it : this->items_) {
    gx0 = std::min(gx0, it.x0);
    gy0 = std::min(gy0, it.y0);
    gx1 = std::max(gx1, it.x1);
    gy1 = std::max(gy1, it.y1);
  }
  if (this->items_.empty()) {
    gx0 = gy0 = 0;
    gx1 = gy1 = 1;
  }
  const int side = std::max(4, std::min(64, (int) ceilf(sqrtf(this->items_.size() / 8.0f))));
  this->cols_ = this->rows_ = side;
  this->gx0_ = gx0;
  this->gy0_ = gy0;
  this->cw_ = std::max(1e-3f, (gx1 - gx0) / side);
  this->ch_ = std::max(1e-3f, (gy1 - gy0) / side);
  this->cells_.assign(side * side, {});
  for (uint32_t n = 0; n < this->items_.size(); n++) {
    const Item &it = this->items_[n];
    for (int cy = this->cell_y_(it.y0); cy <= this->cell_y_(it.y1); cy++)
      for (int cx = this->cell_x_(it.x0); cx <= this->cell_x_(it.x1); cx++)
        this->cells_[cy * side + cx].push_back(n);
  }
}

int MapIndex::cell_x_(float x) const {
  return std::max(0, std::min(this->cols_ - 1, (int) floorf((x - this->gx0_) / this->cw_)));
}
int MapIndex::cell_y_(float y) const {
  return std::max(0, std::min(this->rows_ - 1, (int) floorf((y - this->gy0_) / this->ch_)));
}

void MapIndex::query(float x0, float y0, float x1, float y1, std::vector<uint32_t> &out) const {
  out.clear();
  if (this->items_.empty())
    return;
  for (int cy = this->cell_y_(y0); cy <= this->cell_y_(y1); cy++)
    for (int cx = this->cell_x_(x0); cx <= this->cell_x_(x1); cx++)
      for (uint32_t n : this->cells_[cy * this->cols_ + cx]) {
        const Item &it = this->items_[n];
        if (it.x1 >= x0 && it.x0 <= x1 && it.y1 >= y0 && it.y0 <= y1)
          out.push_back(n);
      }
  // (an item in several cells: once; ascending = draw order)
  std::sort(out.begin(), out.end());
  out.erase(std::unique(out.begin(), out.end()), out.end());
}

// ---- one tile ---------------------------------------------------------------------

void draw_map_tile(const MapSpec &m, const MapIndex &index, const MapColors &c, float k, int px, int py, uint16_t *buf,
                   int size, const MapStyle *style) {
  Raster r(buf, size, size, (float) px, (float) py);
  r.clear(c.bg);
  const float bx = m.bounds[0], by = m.bounds[1];
  auto P = [&](float x, float y) { return FPt{(x - bx) * k, (y - by) * k}; };
  std::vector<FPt> tmp;
  auto poly = [&](const std::vector<Pt> &pts, uint32_t rgb, uint8_t opa) {
    tmp.clear();
    for (const Pt &p : pts)
      tmp.push_back(P(p.x, p.y));
    r.polygon(tmp.data(), (int) tmp.size(), rgb, opa);
  };
  // the tile in map units (+ a pixel of slack for anti-aliased edges)
  std::vector<uint32_t> items;
  const float slack = 2.0f / k;
  index.query(bx + px / k - slack, by + py / k - slack, bx + (px + size) / k + slack, by + (py + size) / k + slack, items);
  for (uint32_t n : items) {
    const MapIndex::Item &it = index.item(n);
    switch (it.kind) {
      case MapIndex::SHAPE:
        poly(m.shapes[it.index].points, shape_colour(c, m.shapes[it.index].style), 255);
        break;
      case MapIndex::FLOOR:  // every indoor room has a floor along its outline
        poly(m.zones[it.index].points, c.floor, 255);
        break;
      case MapIndex::OUTLINE: {  // generated maps (squares per area): outlines show
        const auto &pts = m.zones[it.index].points;
        for (size_t i = 0; i < pts.size(); i++) {
          const Pt &a = pts[i], &b = pts[(i + 1) % pts.size()];
          r.line(P(a.x, a.y), P(b.x, b.y), 2.0f, c.wall, 255, true);
        }
        break;
      }
      case MapIndex::WALL: {
        const auto &w = m.walls[it.index];
        r.line(P(w[0], w[1]), P(w[2], w[3]), m.wall_width * k, c.wall, 255, true);
        break;
      }
      case MapIndex::WINDOW: {
        const auto &w = m.windows[it.index];
        r.line(P(w[0], w[1]), P(w[2], w[3]), m.wall_width * 0.6f * k, c.window, 255, false);
        break;
      }
      case MapIndex::OPENING: {  // thin dashes of a fixed screen size
        const auto &o = m.openings[it.index];
        r.dashed(P(o[0], o[1]), P(o[2], o[3]), 1.5f, 6.0f, 5.0f, c.wall, 153);
        break;
      }
      case MapIndex::ZONE:
      case MapIndex::ZONE_TOP: {
        if (style == nullptr)
          break;
        const auto &v = it.kind == MapIndex::ZONE ? style->base : style->top;
        if (it.index >= v.size())
          break;
        const ZoneStyle &z = v[it.index];
        const auto &pts = m.zones[it.index].points;
        if (z.fill_opa)
          poly(pts, z.fill, z.fill_opa);
        if (z.stroke_opa)  // a 2 px outline (dashed: 6 on, 4 off)
          for (size_t i = 0; i < pts.size(); i++) {
            const Pt &a = pts[i], &b = pts[(i + 1) % pts.size()];
            if (z.dashed)
              r.dashed(P(a.x, a.y), P(b.x, b.y), 2.0f, 6.0f, 4.0f, z.stroke, z.stroke_opa);
            else
              r.line(P(a.x, a.y), P(b.x, b.y), 2.0f, z.stroke, z.stroke_opa, true);
          }
        break;
      }
    }
  }
}

}  // namespace esphome::room_tiles
