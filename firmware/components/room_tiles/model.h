// Room Tiles panel: what the payload says (panels.py payload()).
#pragma once

#include <array>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace esphome::room_tiles {

struct TileSpec {
  std::string kind;  // "" = blank
  std::string entity;
  std::string name;  // the tile's own name ("Map"), else the entity's short name
};

// ---- maps (Room Tiles' map data: plan units; drawn by map_view) ------------------

struct Pt {
  float x, y;
};

struct MapZone {
  std::string id;
  std::string name;
  std::vector<Pt> points;
  std::string area;
  Pt label{0, 0};
  bool has_label{false};
  bool outdoor{false};
  std::string vacuum;  // a vacuum zone: only on that vacuum's view
  bool vertical{false};
};

struct MapShape {
  std::string style;  // floor / water / grass / deck / paving
  std::vector<Pt> points;
};

struct MapLink {  // a tappable spot that opens another map (stairs, a yard door)
  std::string to;
  Pt at{0, 0};
  std::string label;
};

struct MapLayer {
  std::string id;
  std::string name;
  float min_zoom{1};
  float max_zoom{0};  // 0 = on and on
};

struct MapSpec {
  uint32_t sig{0};  // a hash of its JSON: the same map in a new payload keeps its tiles
  std::string id;
  std::string name;
  std::string floor;  // HA floor id
  float bounds[4]{0, 0, 1, 1};
  float wall_width{6};
  bool generated{false};
  std::vector<std::array<float, 4>> walls, windows, openings;
  std::vector<MapShape> shapes;
  std::vector<MapZone> zones;
  std::vector<MapLink> links;
  std::vector<MapLayer> layers;
};

struct MapMarker {
  std::string id;
  std::string map;
  std::string layer;
  std::string entity;
  float x{0}, y{0};
  bool show_name{false};
};

// A marker's pop-up after its own tile: the groups it's in, the scenes that
// set it (Room Tiles works these out), and how many more of each
struct PopupSpec {
  std::vector<std::string> groups, scenes;
  int more_groups{0}, more_scenes{0};
};

// A robot vacuum with a room queue (Room Tiles runs the queue; its state is
// the robot sensor's attributes: queue, current, tile)
struct RobotSpec {
  std::string robot, sensor, vacuum, name;
  std::vector<std::string> areas;  // the HA areas it cleans
};

struct AreaSpec {
  std::string id;
  std::string name;
  std::string short_name;
  std::string floor;  // HA floor id ("" = none)
  std::vector<std::string> lights;  // what the area lights button switches (none: no button)
  std::vector<TileSpec> tiles_5x2;
  std::vector<TileSpec> tiles_6x3;
  const std::vector<TileSpec> &tiles(bool big) const { return big ? this->tiles_5x2 : this->tiles_6x3; }
};

struct EntityInfo {
  std::string kind;
  std::string short_name;
  std::string icon;  // a hint Room Tiles adds: "icon_garage", "icon_matic"...
};

// A tile the picker offers (the catalog) and its HA area
struct CatalogItem {
  std::string entity;
  std::string kind;
  std::string short_name;
  std::string area;
};

struct PanelModel {
  // the panel's own settings (defaults already filled in by Room Tiles)
  std::string area;
  bool area_set{true};  // (false: none picked and its device has none - the panel asks)
  std::string layout;  // "5x2" / "6x3"
  std::string theme;
  std::string language;
  /// The room the panel is IN (its HA device's area - not the area it
  /// shows): its area lights entity (or its lights) - "Screen off when the
  /// lights are off". None: no such room.
  std::vector<std::string> room_lights;
  std::string room;  // (that room's name: "" = the panel's device has no area)
  std::vector<AreaSpec> areas;
  std::map<std::string, EntityInfo> entities;
  std::vector<CatalogItem> catalog;
  std::map<std::string, std::string> floors;  // floor id -> name
  // (shared: the map drawing task keeps the version it started with)
  std::vector<std::shared_ptr<const MapSpec>> maps;
  std::vector<MapMarker> markers;
  std::map<std::string, PopupSpec> popups;  // marker entity -> its pop-up's extras
  std::vector<RobotSpec> robots;
  // the settings menu: the languages with wording (code -> its own name),
  // the themes, and this panel's own choices ("" = the default)
  std::map<std::string, std::string> languages;
  std::vector<std::string> themes;
  std::map<std::string, std::string> theme_names;  // (its name in the panel's language; else the wording's "theme.<id>")
  std::string own_language, own_theme;
  int found{0};  // devices Room Tiles found that aren't set up (the dashboard sets them up)
  /// The robot behind a vacuum tile (its sensor or its vacuum), or none.
  const RobotSpec *robot_for(const std::string &entity) const {
    for (auto &r : this->robots)
      if (r.sensor == entity || r.vacuum == entity)
        return &r;
    return nullptr;
  }

  const AreaSpec *current() const {
    for (auto &a : this->areas)
      if (a.id == this->area)
        return &a;
    return this->areas.empty() ? nullptr : &this->areas.front();
  }
  std::string icon(const std::string &entity) const {
    auto it = this->entities.find(entity);
    return it == this->entities.end() ? std::string() : it->second.icon;
  }
  std::string short_name(const std::string &entity) const {
    auto it = this->entities.find(entity);
    return it == this->entities.end() || it->second.short_name.empty() ? entity : it->second.short_name;
  }
};

}  // namespace esphome::room_tiles
