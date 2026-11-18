// Room Tiles panel: drawing one map tile - the dashboard's plan-draw.ts in
// pixels (ground, shapes by type, room floors, generated maps' outlines,
// walls, windows, openings; room names are LVGL labels on top). Pure C++: no
// LVGL, so it runs on the drawing task (and builds on a PC for checking).
#pragma once

#include <cstdint>
#include <vector>

#include "model.h"

namespace esphome::room_tiles {

struct MapColors {
  uint32_t bg{0x121212}, floor{0xF4F1EA}, wall{0x3A4250}, window{0x7FB8E0};
  uint32_t water{0x29B6F6}, grass{0x1D2B1D}, deck{0x3B3027}, paving{0x2A2A2A};
};

/// A room's look in a special view (a vacuum's queue): a fill and an
/// outline, each off when its opacity is 0.
struct ZoneStyle {
  uint32_t fill{0};
  uint8_t fill_opa{0};
  uint32_t stroke{0};
  uint8_t stroke_opa{0};
  bool dashed{false};
};
/// Per zone (the map's zones' order): `base` drawn over the floors, under
/// the walls (the dashboard's zone classes); `top` over everything (the
/// queue's room colours). Empty = none.
struct MapStyle {
  std::vector<ZoneStyle> base, top;
};

/// What a map draws, in draw order, binned into a grid of cells over the map
/// (a flat quadtree): a tile only looks at the items in the cells it covers,
/// never at every item. Built once per map (when the payload arrives).
class MapIndex {
 public:
  enum Kind : uint8_t { SHAPE, FLOOR, ZONE, OUTLINE, WALL, WINDOW, OPENING, ZONE_TOP };
  struct Item {
    Kind kind;
    uint16_t index;          // into the map's shapes / zones / walls...
    float x0, y0, x1, y1;    // its box, map units (lines: padded by their width)
  };
  explicit MapIndex(const MapSpec &m);
  /// The items whose box meets the map-unit rect, in draw order.
  void query(float x0, float y0, float x1, float y1, std::vector<uint32_t> &out) const;
  const Item &item(uint32_t i) const { return this->items_[i]; }
  size_t size() const { return this->items_.size(); }

 protected:
  std::vector<Item> items_;
  std::vector<std::vector<uint32_t>> cells_;  // item numbers, ascending = draw order
  int cols_{1}, rows_{1};
  float gx0_{0}, gy0_{0}, cw_{1}, ch_{1};
  int cell_x_(float x) const;
  int cell_y_(float y) const;
};

/// One `size` x `size` RGB565 tile of map `m` drawn `k` pixels per map unit:
/// the tile's top-left is at pixel (px, py), pixel (0, 0) = the map's
/// bounds' top-left corner. `style`: a special view's room looks (or none).
void draw_map_tile(const MapSpec &m, const MapIndex &index, const MapColors &c, float k, int px, int py, uint16_t *buf,
                   int size, const MapStyle *style = nullptr);

}  // namespace esphome::room_tiles
