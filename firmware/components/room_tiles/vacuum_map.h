// Room Tiles panel: a robot vacuum's room queue as the queue view (map_queue.cpp)
// and the vacuum tile (board_kinds.cpp) both show it - which map, the
// rooms' looks. One place, so the two never disagree.
#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "map_draw.h"
#include "model.h"

namespace esphome::room_tiles {

class RoomTiles;

/// The queue right now (the robot sensor's attributes).
struct QueueState {
  std::vector<std::string> queue;  // HA areas, in order
  std::string current;             // the area being cleaned ("" = none)
  std::string cls, text;           // what the vacuum is doing: its tile class, its words
};
QueueState read_queue(RoomTiles *rt, const RobotSpec &robot);

/// Its map: the room being cleaned's, else the first queued one's, else the
/// first map with a room it cleans (vacqueue.ts tileMap). None: no map has one.
const MapSpec *queue_map(const PanelModel &model, const RobotSpec &robot, const QueueState &q);

/// The rooms' looks for this queue on map `m`: its rooms tinted (cleanable /
/// not - dimmed toward `dim` -, its own zones dashed), the queue's rooms in
/// their state's colour. `sig`: a hash of the looks (the same = nothing to redraw).
std::shared_ptr<MapStyle> queue_style(RoomTiles *rt, const MapSpec &m, const RobotSpec &robot, const QueueState &q,
                                      uint32_t dim, uint32_t *sig);

}  // namespace esphome::room_tiles
