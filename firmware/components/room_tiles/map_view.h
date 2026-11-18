// Room Tiles panel: the map screen (milestone 6) - a top bar (the map's name,
// the other maps, close) over the map drawn in 256 px tiles. A drawing task on
// the other core fills tiles (map_draw.cpp) into a pool of buffers in PSRAM;
// the main loop only shows finished ones as images, room names as labels on
// top. Tiles already drawn are kept (least recently used go first), so a tile
// is drawn once per map + zoom: panning only draws the new ones. Drag pans
// (both axes, stops with the finger), the zoom box (+, a roller of the steps, -) zooms in 0.25 steps, a tap on a room zooms to it.
#pragma once

#include <atomic>
#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <lvgl.h>

#include "esphome/core/helpers.h"

#include "busy.h"
#include "map_draw.h"
#include "model.h"
#include "perf.h"
#include "sprite.h"

namespace esphome::room_tiles {

class RoomTiles;
struct Fonts;

class MapView {
 public:
  /// The settings menu showed the found devices: the gear's dot goes.
  void found_seen();
  static constexpr int TILE = 256;
  static constexpr int BAR_H = 48;  // the top bar; the map under it
  static constexpr int AREA_W = 1024, AREA_H = 600 - BAR_H;
  static constexpr int SLOTS = 48;  // tile buffers: 48 x 128 KB = 6 MB of PSRAM

  /// `parent` = the main screen; `board` = the tile board's container
  /// (hidden while the map is up, so nothing under it redraws).
  void attach(lv_obj_t *parent, lv_obj_t *board, RoomTiles *rt, const Fonts *fonts) {
    this->parent_ = parent;
    this->board_ = board;
    this->rt_ = rt;
    this->fonts_ = fonts;
  }
  bool is_open() const { return this->open_; }
  /// Show a map: `map_id`, else the one on `floor`, else the last one shown.
  void open(const PanelModel &model, const std::string &map_id, const std::string &floor);
  void close();
  /// A robot vacuum's room queue: the map it cleans on, in queue mode (its
  /// rooms coloured by the queue; a tap on a room queues it / takes it off).
  void open_queue(const PanelModel &model, const RobotSpec &robot);
  /// A new payload: an unchanged map keeps its tiles (the same MapSpec).
  void model_changed(const PanelModel &model);
  /// New theme colours: every tile is drawn again.
  void theme_changed();
  void loop();
  /// An entity's state changed: its markers repaint.
  void entity_changed(const std::string &entity);
  /// The maps' pictures (room names, marker names, marker faces on / off)
  /// queued to be made in the background while the map is closed - a few a
  /// loop, kept in PSRAM - so a map opens without making them (model_changed).
  void queue_pictures(const PanelModel &model);
  bool pictures_pending() const { return this->picture_next_ < this->picture_jobs_.size(); }

 protected:
  struct MarkerView {
    MapView *view{nullptr};
    std::string entity, kind, hint;
    float x{0}, y{0};
    uint32_t flash_until{0};  // a scene / script just tapped: lit this long
    // its tap target (invisible: the markers layer draws its pictures)
    lv_obj_t *face{nullptr};
    const Sprite *face_sp{nullptr};  // its face now (on / off, ringed...)
    lv_opa_t opa{LV_OPA_COVER};      // (faded: no state)
    const Sprite *name_sp{nullptr};  // its name above it, if shown
    int name_x{0}, name_y{0};        // (in the layer)
    lv_obj_t *clip{nullptr};   // an appliance: its tile's animation over the icon
    lv_obj_t *sheet{nullptr};
    bool animating{false};
  };
  struct LabelView {  // a room's name (the labels layer draws them)
    const Sprite *sp;
    int x, y;  // (in the layer)
  };
  struct Key {
    uint32_t gen;  // the map (a new version of it = a new gen)
    int zoom_q;    // zoom x 100
    int tx, ty;
    bool operator<(const Key &o) const {
      if (gen != o.gen)
        return gen < o.gen;
      if (zoom_q != o.zoom_q)
        return zoom_q < o.zoom_q;
      if (tx != o.tx)
        return tx < o.tx;
      return ty < o.ty;
    }
    bool operator==(const Key &o) const { return gen == o.gen && zoom_q == o.zoom_q && tx == o.tx && ty == o.ty; }
  };
  // a tile buffer: a 4-bit sprite in PSRAM (fixed: its image descriptor's
  // address never changes)
  struct Slot {
    Sprite *sp{nullptr};
    bool blank{false};   // past the map's edges: the plain tile
    const Sprite *shown{nullptr};  // on screen: its picture / the plain one (the tiles layer draws it)
    Key key{0, 0, 0, 0};
    bool used{false};    // holds `key` (drawn, or on its way)
    bool ready{false};   // drawn
    bool queued{false};  // the task has it: hands off
    uint32_t touched{0};
  };
  struct Job {
    int slot;
    uint32_t epoch;
    std::shared_ptr<const MapSpec> map;
    std::shared_ptr<const MapIndex> index;
    MapColors colors;
    std::shared_ptr<const MapStyle> style;  // (a vacuum's queue view; else none)
    float k;
    int px, py;
    Sprite *sp;
    bool drawn{false};
    uint32_t us{0};
  };
  struct Known {  // a map seen before: its index, and its gen while it's the same
    std::shared_ptr<const MapSpec> spec;
    std::shared_ptr<const MapIndex> index;
    uint32_t gen;
  };

  void build_();
  void build_bar_();
  lv_obj_t *gear_dot_{nullptr};  // its gear's dot (while it exists)
  void build_zoom_box_();
  void paint_zoom_box_();
  void show_map_(const std::shared_ptr<const MapSpec> &m);
  /// The camera: zoom (1..max_zoom_, 0.01 steps) with map point (cx, cy) in
  /// the middle of the view (as near as the map's edges allow).
  void set_view_(float zoom, float cx, float cy);
  void zoom_by_(int dir);
  void zoom_to_(float z);
  void go_to_zone_(const MapZone *z);
  const MapZone *zone_at_(float mx, float my) const;
  void build_labels_();
  // map_markers.cpp
  std::vector<std::string> layers_shown_() const;
  void build_markers_();
  void paint_marker_(MarkerView &mv);
  void tap_marker_(MarkerView &mv);
  void open_popup_(const MarkerView &mv);
  void close_popup_();
  static void on_marker_(lv_event_t *e);
  void markers_loop_();
  /// While the map is dragged: no appliance animations (the faces, icons
  /// and names are pre-rendered sprites - cheap); back the moment it stops.
  /// The zoom box shows as a picture of itself meanwhile.
  void markers_lite_(bool on);
  bool lite_{false};
  // pre-rendered (sprite.h), kept until the theme changes: a marker's face
  // (its icon, colours, ring), a name, a room's name - every combination met
  std::map<std::string, Sprite *> sprites_;
  Sprite *face_sprite_(int icon, uint32_t fill, lv_opa_t fill_opa, uint32_t border, bool ring);
  Sprite *name_sprite_(const std::string &text);
  Sprite *label_sprite_(const std::string &text, uint32_t color, bool vertical);
  void sprites_clear_();
  void pictures_to_internal_();
  struct PictureJob {
    uint8_t what;  // 0 room name, 1 marker name, 2 marker face
    std::string text;
    uint32_t color{0}, border{0};
    int icon{0};
    lv_opa_t opa{LV_OPA_COVER};
    bool vertical{false};
  };
  std::vector<PictureJob> picture_jobs_;
  size_t picture_next_{0};
  uint32_t pictures_made_{0}, pictures_ms_{0};
  void make_pictures_();
  Sprite *zoom_sprite_{nullptr};  // the zoom box, while panning
  float zoom_sprite_at_{0};
  lv_obj_t *zoom_img_{nullptr};
  void zoom_box_as_picture_(bool on);
  void make_zoom_picture_();
  void close_overlays_later_();
  // map_queue.cpp: a vacuum's queue view
  bool queue_mode_{false};
  RobotSpec q_;
  std::vector<std::string> q_queue_;
  std::string q_current_, q_cls_, q_text_;
  std::shared_ptr<const MapStyle> style_;
  uint32_t base_gen_{0};   // the map's own gen (gen_ = it, or it mixed with the style)
  lv_obj_t *qbar_{nullptr};
  lv_obj_t *q_status_{nullptr}, *q_start_{nullptr}, *q_start_text_{nullptr};
  lv_obj_t *q_pause_{nullptr}, *q_skip_{nullptr}, *q_stop_{nullptr}, *q_clear_{nullptr};
  lv_obj_t *q_auto_{nullptr};  // "Start queue automatically"'s switch
  static constexpr int QBAR_H = 60;
  void queue_read_();
  void queue_restyle_();
  void build_badges_();
  void build_queue_bar_();
  void paint_queue_bar_();
  void queue_tap_(const MapZone &z);
  void queue_action_(const char *action, const std::string &area = "", bool start = false);
  bool zone_shown_(const MapZone &z) const;
  static void on_queue_button_(lv_event_t *e);
  void leave_queue_();
  void open_rooms_();
  void close_rooms_();
  lv_obj_t *rooms_scrim_{nullptr};
  std::vector<std::string> room_ids_;
  int picked_room_{-1};
  bool queue_map_(const MapSpec &m) const;  // the vacuum cleans a room on it
  bool opening_queue_{false};
  lv_obj_t *badges_layer_{nullptr};
  void build_links_();
  struct LinkView {
    MapView *view;
    std::string to;
  };
  std::vector<LinkView> links_;  // (event user data: reserved before use)
  std::string go_to_;            // a link tapped: the map to open
  void request_tiles_();
  int take_slot_();
  void drop_slot_(Slot &s);
  void place_(Slot &s);
  bool prev_shows_(const Key &k) const;  // the previous look's tile is on screen there
  void drop_prev_(const Key &k);         // ... and is replaced now
  bool visible_(const Key &k) const;
  bool on_screen_(const Key &k) const;
  static void worker_(void *arg);
  enum Phase : uint8_t { IDLE, PAN, ZOOM };
  void phase_(Phase p, const std::string &what);
  // one draw per layer (sprite.h): each layer draws all of its pictures in its
  // own LV_EVENT_DRAW_MAIN - no LVGL image object for each tile / marker / name
  static void on_draw_tiles_(lv_event_t *e);
  static void on_draw_markers_(lv_event_t *e);
  static void on_draw_labels_(lv_event_t *e);
  void hide_(Slot &s);
  void place_plain_(Slot &s);
  // a new zoom / look on its way: nothing of it shows until all its tiles on
  // screen are drawn, then all at once (the plain tile / the old look meanwhile)
  bool revealing_{false};
  void invalidate_in_(lv_obj_t *layer, int x, int y, const Sprite *sp);
  std::vector<LabelView> labels_;
  static void on_close_(lv_event_t *e);
  static void on_back_(lv_event_t *e);
  static void on_map_pill_(lv_event_t *e);
  static void on_layer_pill_(lv_event_t *e);
  void paint_pill_(lv_obj_t *p, bool on);
  void paint_layer_pills_();
  static void on_scroll_(lv_event_t *e);
  static void on_tap_(lv_event_t *e);
  static void on_drag_(lv_event_t *e);
  static void on_zoom_in_(lv_event_t *e);
  static void on_zoom_out_(lv_event_t *e);
  static void on_zoom_roller_(lv_event_t *e);

  lv_obj_t *parent_{nullptr};
  lv_obj_t *board_{nullptr};
  RoomTiles *rt_{nullptr};
  const Fonts *fonts_{nullptr};
  const PanelModel *model_{nullptr};
  bool open_{false};

  std::map<std::string, Known> known_;
  uint32_t next_gen_{1};
  std::string map_id_;  // shown / last shown
  std::shared_ptr<const MapSpec> map_;
  std::shared_ptr<const MapIndex> index_;
  uint32_t gen_{0};
  MapColors colors_;

  // the camera: zoom 1 = the whole map just fits the area (the dashboard's
  // zoom number); the area scrolls (by code: on_drag_), cam = the view's
  // top-left in the tiles' pixels (content: the zoomed map + any margin)
  // how far a viewer zooms in (map.ts viewMaxZoom - the same rule): 8x, more
  // for a map whose layers start deeper or whose smallest room needs it
  static constexpr float VIEW_MAX_ZOOM = 8;
  float max_zoom_{VIEW_MAX_ZOOM};
  float view_max_zoom_(const MapSpec &m) const;
  void set_zoom_steps_();
  float zoom_{1};
  float k0_{1};  // px per map unit at zoom 1
  float k_{1};
  int map_w_{0}, map_h_{0};  // the zoomed map, px
  int area_y_{BAR_H}, area_h_{AREA_H};  // the map's area on screen (queue mode: lower, shorter)
  void set_area_(int y, int h);
  int content_w_{0}, content_h_{0};  // the tiles' extent: the map, at least the area
  int off_x_{0}, off_y_{0};          // the map's top-left in it (a smaller map: centred)
  int cam_x_{0}, cam_y_{0};
  std::string zone_;  // the room zoomed into ("" = none)
  float tap_x_{0}, tap_y_{0};  // a tap, map units (for after its event)
  bool panning_{false};        // this press became a pan (its tap doesn't count)
  int drag_x_{0}, drag_y_{0};
  // The horizontal scroll stays even: a tile then starts on a 4-byte boundary
  // in the render buffer and LVGL copies its rows a word at a time (at an odd
  // x, byte by byte). A drag's odd pixel waits here for the next move.
  int drag_rest_x_{0};
  std::atomic<uint32_t> epoch_{0};  // bumped when the map / zoom changes: queued tiles are dropped

  lv_obj_t *root_{nullptr};
  lv_obj_t *bar_{nullptr};
  lv_obj_t *area_{nullptr};
  lv_obj_t *content_{nullptr};  // moved to pan; tiles under labels
  lv_obj_t *tiles_layer_{nullptr};
  lv_obj_t *markers_layer_{nullptr};
  lv_obj_t *labels_layer_{nullptr};
  std::vector<MarkerView> markers_;  // (event user data: never resized while shown)
  // the pop-up tile (a long press on a marker): its scrim and box
  lv_obj_t *popup_scrim_{nullptr};
  lv_obj_t *popup_box_{nullptr};
  uint32_t popup_at_{0};
  uint32_t popup_touched_{0};
  std::string popup_entity_;  // its markers are all highlighted (an entity placed several times)
  uint32_t anim_at_{0};  // appliance markers' animation: the frame shown
  int anim_frame_{0};
  lv_obj_t *busy_{nullptr};
  lv_obj_t *zoom_in_{nullptr};
  lv_obj_t *zoom_out_{nullptr};
  lv_obj_t *zoom_roller_{nullptr};
  lv_obj_t *zoom_box_{nullptr};
  bool area_filled_{true};
  Sprite *blank_{nullptr};  // the plain tile (the map's background)
  uint32_t blank_rgb_{0xFFFFFFFF};
  lv_opa_t screen_opa_{LV_OPA_COVER}, bottom_opa_{LV_OPA_TRANSP};
  BusyIcons busy_icons_;
  std::vector<std::string> pill_ids_;
  std::vector<lv_obj_t *> layer_pills_;
  // the map nav (the top bar): a collapsed group's list, the Layer group's
  // current name when it's collapsed
  static constexpr int NAV_PILL_H = 32;
  lv_obj_t *layer_menu_label_{nullptr};
  bool layers_collapsed_{false};
  int nav_menu_x_{0};
  lv_obj_t *nav_pill_(lv_obj_t *parent, const std::string &text, bool on, bool menu);
  void open_nav_(bool is_maps);
  std::string map_name_(const std::string &id) const;
  static void on_maps_menu_(lv_event_t *e);
  static void on_layers_menu_(lv_event_t *e);
  float pending_zoom_{1};

  Slot slots_[SLOTS];
  std::map<Key, int> lookup_;
  uint32_t tick_{0};
  int missing_{0};             // visible tiles not drawn yet
  uint32_t missing_since_{0};
  uint32_t batch_tiles_{0}, batch_us_{0};  // tiles drawn this phase
  uint32_t loop_n_{0}, loop_us_{0}, loop_max_us_{0};  // MapView::loop this phase (profiling)
  // a press too soon after a lift is the touch panel's (a fast swipe can
  // read as lift + press): it can't close / go back - the X sits right above
  // the zoom roller
  uint32_t lift_ms_{0}, press_gap_ms_{0xFFFFFFFF};
  bool indev_hooked_{false};
  // while panning / zooming ESPHome's main loop runs without its nap (it
  // sleeps up to 16 ms after each pass otherwise - after every frame)
  HighFrequencyLoopRequester fast_loop_;
  bool deliberate_press_() const { return this->press_gap_ms_ >= 250; }
  // where the last press came down; a tap that starts this close to the zoom
  // box (about a marker's width) does nothing - a near miss on the roller
  // mustn't switch a light or zoom to a room (panning from there still works)
  lv_point_t press_at_{-1000, -1000};
  static constexpr int ZOOM_BOX_NO_TAP = 52;
  bool press_near_zoom_box_() const;
  FrameStats stats_;
  Phase phase_kind_{IDLE};
  bool opening_{false};
  QueueHandle_t jobs_{nullptr};
  QueueHandle_t done_{nullptr};
};

}  // namespace esphome::room_tiles
