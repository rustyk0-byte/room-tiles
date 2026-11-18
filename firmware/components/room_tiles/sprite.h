// Room Tiles panel: sprites - pictures in 4 bits a pixel (16 palette colours,
// each RGB565 + alpha), drawn by LVGL through Room Tiles' own image decoder
// straight into the render buffer (no decoding step, no intermediate copy).
//
// The map uses them for everything a pan redraws every frame: its tiles
// (opaque, a palette per tile, in PSRAM - a quarter of RGB565's bytes to
// read) and its markers, their names, the room names and the zoom box
// (pre-rendered once by LVGL itself, so they look the same; in internal RAM
// when there's room). See docs/DESIGN.md "Map drawing".
#pragma once

#include <cstdint>
#include <string>

#include <lvgl.h>

namespace esphome::room_tiles {

struct Sprite {
  static constexpr uint32_t MAGIC = 0x34535452;  // "RTS4"
  uint32_t magic{MAGIC};
  uint16_t w{0}, h{0};
  uint16_t stride{0};   // bytes a row: (w + 1) / 2
  bool opaque{true};    // every pixel's alpha 255: plain copies
  bool internal{false};  // (where its pixels are)
  uint16_t c565[16]{};
  uint8_t alpha[16]{};
  uint8_t *px{nullptr};  // 2 pixels a byte, the left one in the high nibble
  lv_image_dsc_t dsc{};  // an lv_image shows it: lv_image_set_src(img, &s->dsc)
};

/// Register the decoder (once LVGL runs; again is a no-op).
void sprite_init();

/// Draw `s` with its top-left at (x, y) (screen coordinates) into `layer`,
/// inside its clip area - from an object's LV_EVENT_DRAW_MAIN: one object
/// drawing many sprites (the map's tiles / markers / labels layers).
void sprite_draw(lv_layer_t *layer, const Sprite *s, int x, int y, lv_opa_t opa = LV_OPA_COVER);

/// Opaque sprites (the map's tiles) with their top-left corners, in order.
struct SpriteBlit {
  const Sprite *s;
  int x, y;
};
/// Draw them as sprite_draw would, the strip's rows split between this core
/// and the other one (a helper task, started on first use).
void sprite_draw_tiles(lv_layer_t *layer, const SpriteBlit *items, int n);

/// A sprite w x h (pixels unset). Internal RAM when asked and that leaves
/// enough free there, else PSRAM. nullptr: no memory.
Sprite *sprite_new(int w, int h, bool prefer_internal);
void sprite_free(Sprite *s);
/// Its pixels moved to PSRAM / to internal RAM (only while that leaves the
/// reserve free) - a copy, nothing drawn again; the sprite itself (what LVGL
/// holds) stays put. False when it stayed where it was.
bool sprite_to_psram(Sprite *s);
bool sprite_to_internal(Sprite *s);

/// RGB565 pixels -> its 16 most used colours (each other colour becomes the
/// nearest of them: the anti-aliased edges). Opaque. `map` is scratch: 65536
/// bytes, and `counts` 65536 x uint32 all zero (left zero again).
void sprite_quantize_565(Sprite *s, const uint16_t *src, int src_stride_px, uint32_t *counts, uint8_t *map);

/// ARGB8888 pixels (as LVGL draws them: straight alpha, `src_w` wide) -> 16
/// colours with alpha, chosen to fit (pictures: icons, text on a backing);
/// `rotate_ccw`: the source turned a quarter anticlockwise. No allocations.
void sprite_quantize_argb(Sprite *s, const uint32_t *src, int src_w, bool rotate_ccw = false);

/// Pre-rendering: an ARGB8888 canvas w x h, cleared; LVGL draws into
/// `layer()` (lv_draw_rect / lv_draw_image / lv_draw_label / lv_obj_redraw),
/// `finish()` waits for it, `to_sprite()` makes the sprite (optionally
/// turned 90 degrees anticlockwise: text reading upwards).
class SpriteCanvas {
 public:
  /// (x0, y0): the canvas's top-left in the screen's coordinates (what an
  /// object redrawn into it is placed at; plain draws use 0, 0).
  SpriteCanvas(int w, int h, int x0 = 0, int y0 = 0);
  ~SpriteCanvas();
  bool ok() const { return this->buf_ != nullptr; }
  lv_layer_t *layer() { return &this->layer_; }
  void finish();
  Sprite *to_sprite(bool prefer_internal, bool rotate_ccw = false);

 protected:
  int w_, h_;
  uint32_t *buf_{nullptr};
  lv_draw_buf_t draw_buf_{};
  lv_layer_t layer_{};
  bool finished_{false};
};

/// Every sprite allocation in internal RAM, bytes (logged by the map).
size_t sprite_internal_bytes();


}  // namespace esphome::room_tiles
