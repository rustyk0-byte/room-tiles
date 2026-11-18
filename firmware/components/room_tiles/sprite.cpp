#include "sprite.h"

#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <vector>

#include <esp_heap_caps.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include <src/draw/lv_draw_private.h>
#include <src/draw/lv_image_decoder_private.h>
#include <src/misc/lv_area_private.h>
#include <src/misc/cache/instance/lv_image_cache.h>

#include "esphome/core/log.h"

namespace esphome::room_tiles {

static const char *const TAG = "room_tiles.sprite";

// a sprite in internal RAM only while this much stays free there (Wi-Fi,
// the network, LVGL's own allocations, the model's lists - each one block:
// a new payload's rebuild needs its room)
static constexpr size_t INTERNAL_RESERVE = 150 * 1024;
static size_t internal_bytes = 0;

size_t sprite_internal_bytes() { return internal_bytes; }

// ---- memory -----------------------------------------------------------------------

Sprite *sprite_new(int w, int h, bool prefer_internal) {
  const uint16_t stride = (uint16_t) ((w + 1) / 2);
  const size_t bytes = (size_t) stride * h;
  uint8_t *px = nullptr;
  bool internal = false;
  if (prefer_internal && heap_caps_get_free_size(MALLOC_CAP_INTERNAL) > bytes + INTERNAL_RESERVE) {
    px = static_cast<uint8_t *>(heap_caps_malloc(bytes, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    internal = px != nullptr;
  }
  if (px == nullptr)
    px = static_cast<uint8_t *>(heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (px == nullptr)
    return nullptr;
  auto *s = new Sprite();
  s->w = (uint16_t) w;
  s->h = (uint16_t) h;
  s->stride = stride;
  s->px = px;
  s->internal = internal;
  if (internal)
    internal_bytes += bytes;
  // what LVGL is handed: our decoder knows it by the sprite behind it
  s->dsc.header.magic = LV_IMAGE_HEADER_MAGIC;
  s->dsc.header.cf = LV_COLOR_FORMAT_RAW_ALPHA;
  s->dsc.header.w = (uint32_t) w;
  s->dsc.header.h = (uint32_t) h;
  s->dsc.header.stride = stride;
  s->dsc.data = reinterpret_cast<const uint8_t *>(s);
  s->dsc.data_size = sizeof(Sprite);
  return s;
}

bool sprite_to_psram(Sprite *s) {
  if (s == nullptr || !s->internal)
    return false;
  const size_t bytes = (size_t) s->stride * s->h;
  auto *px = static_cast<uint8_t *>(heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (px == nullptr)
    return false;
  memcpy(px, s->px, bytes);
  heap_caps_free(s->px);
  s->px = px;
  s->internal = false;
  internal_bytes -= bytes;
  return true;
}

bool sprite_to_internal(Sprite *s) {
  if (s == nullptr || s->internal)
    return false;
  const size_t bytes = (size_t) s->stride * s->h;
  if (heap_caps_get_free_size(MALLOC_CAP_INTERNAL) <= bytes + INTERNAL_RESERVE)
    return false;
  auto *px = static_cast<uint8_t *>(heap_caps_malloc(bytes, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
  if (px == nullptr)
    return false;
  memcpy(px, s->px, bytes);
  heap_caps_free(s->px);
  s->px = px;
  s->internal = true;
  internal_bytes += bytes;
  return true;
}

void sprite_free(Sprite *s) {
  if (s == nullptr)
    return;
  lv_image_cache_drop(&s->dsc);
  if (s->internal)
    internal_bytes -= (size_t) s->stride * s->h;
  heap_caps_free(s->px);
  delete s;
}

// ---- quantizing -------------------------------------------------------------------

static inline void put4(Sprite *s, int x, int y, uint8_t i) {
  uint8_t &b = s->px[y * s->stride + x / 2];
  b = (x & 1) ? (uint8_t) ((b & 0xF0) | i) : (uint8_t) ((b & 0x0F) | (i << 4));
}

static inline int dist565(uint16_t a, uint16_t b) {
  // (in 8-bit units per channel; green weighs most, like the eye)
  const int dr = (int) ((a >> 11) & 31) * 8 - (int) ((b >> 11) & 31) * 8;
  const int dg = (int) ((a >> 5) & 63) * 4 - (int) ((b >> 5) & 63) * 4;
  const int db = (int) (a & 31) * 8 - (int) (b & 31) * 8;
  return 3 * dr * dr + 4 * dg * dg + 2 * db * db;
}

__attribute__((optimize("O2"))) void sprite_quantize_565(Sprite *s, const uint16_t *src, int src_stride_px,
                                                        uint32_t *counts, uint8_t *map) {
  const int w = s->w, h = s->h;
  // the colours, by use
  std::vector<uint16_t> seen;
  seen.reserve(256);
  for (int y = 0; y < h; y++) {
    const uint16_t *row = src + y * src_stride_px;
    for (int x = 0; x < w; x++)
      if (counts[row[x]]++ == 0)
        seen.push_back(row[x]);
  }
  std::sort(seen.begin(), seen.end(), [&](uint16_t a, uint16_t b) { return counts[a] > counts[b]; });
  const int n = std::min<int>(16, (int) seen.size());
  for (int i = 0; i < 16; i++) {
    s->c565[i] = i < n ? seen[i] : 0;
    s->alpha[i] = 255;
  }
  s->opaque = true;
  // each colour -> its palette entry (the 16 themselves, the rest the nearest)
  for (size_t k = 0; k < seen.size(); k++) {
    const uint16_t c = seen[k];
    uint8_t best = 0;
    if ((int) k < n) {
      best = (uint8_t) k;
    } else {
      int bd = 1 << 30;
      for (int i = 0; i < n; i++) {
        const int d = dist565(c, s->c565[i]);
        if (d < bd) {
          bd = d;
          best = (uint8_t) i;
        }
      }
    }
    map[c] = best;
    counts[c] = 0;  // (left zero for the next one)
  }
  for (int y = 0; y < h; y++) {
    const uint16_t *row = src + y * src_stride_px;
    uint8_t *out = s->px + y * s->stride;
    int x = 0;
    for (; x + 1 < w; x += 2)
      *out++ = (uint8_t) ((map[row[x]] << 4) | map[row[x + 1]]);
    if (x < w)
      *out = (uint8_t) (map[row[x]] << 4);
  }
}

// ARGB in premultiplied terms (what blending sees): a colour at low alpha
// is near transparent whatever its hue
struct PColor {
  float a, r, g, b;
};

static inline PColor premul(uint32_t argb) {
  const float a = (float) (argb >> 24);
  return {a, ((argb >> 16) & 255) * a / 255.0f, ((argb >> 8) & 255) * a / 255.0f, (argb & 255) * a / 255.0f};
}

static inline float pdist(const PColor &x, const PColor &y) {
  const float da = x.a - y.a, dr = x.r - y.r, dg = x.g - y.g, db = x.b - y.b;
  return 2 * da * da + 3 * dr * dr + 4 * dg * dg + 2 * db * db;
}

__attribute__((optimize("O2"))) void sprite_quantize_argb(Sprite *s, const uint32_t *src, int src_w, bool rotate_ccw) {
  const int w = s->w, h = s->h;
  // the sprite's (x, y) in the source: as it is, or the source turned a
  // quarter anticlockwise (the source is h wide then: (x, y) <- (w-1-y, x))
  auto px_at = [&](int x, int y) -> uint32_t {
    const uint32_t c = rotate_ccw ? src[x * src_w + (src_w - 1 - y)] : src[y * src_w + x];
    return (c >> 24) == 0 ? 0 : c;  // (fully transparent: one colour)
  };

  // 1. the most used colours, in a fixed table (Misra-Gries: any colour
  // covering more than 1/64 of the pixels is sure to be in it)
  constexpr int K = 64;
  uint32_t cand[K];
  uint32_t cnt[K];
  int nc = 0;
  int last = -1;  // (runs of one colour: its entry again)
  for (int y = 0; y < h; y++)
    for (int x = 0; x < w; x++) {
      const uint32_t c = px_at(x, y);
      if (last >= 0 && cand[last] == c) {
        cnt[last]++;
        continue;
      }
      int i = 0;
      while (i < nc && cand[i] != c)
        i++;
      if (i < nc) {
        cnt[i]++;
        last = i;
      } else if (nc < K) {
        cand[nc] = c;
        cnt[nc] = 1;
        last = nc++;
      } else {
        last = -1;
        // full: every count down one, the ones at zero leave
        int j = 0;
        for (int k = 0; k < nc; k++)
          if (--cnt[k] > 0) {
            cand[j] = cand[k];
            cnt[j++] = cnt[k];
          }
        nc = j;
      }
    }
  // the 16 most counted start the palette
  int order[K];
  for (int i = 0; i < nc; i++)
    order[i] = i;
  std::sort(order, order + nc, [&](int a, int b) { return cnt[a] > cnt[b]; });
  const int n = std::max(1, std::min(16, nc));
  PColor centre[16];
  for (int i = 0; i < n; i++)
    centre[i] = nc > 0 ? premul(cand[order[i]]) : PColor{0, 0, 0, 0};

  // (runs of one colour: its answer again - reset when the entries move)
  uint32_t near_c = 0;
  int near_i = -1;
  auto nearest_of = [&](uint32_t c, const PColor &p, auto &&nearest) -> int {
    if (near_i >= 0 && c == near_c)
      return near_i;
    near_c = c;
    near_i = nearest(p);
    return near_i;
  };
  auto nearest = [&](const PColor &p) -> int {
    int best = 0;
    float bd = 1e30f;
    for (int i = 0; i < n; i++) {
      const float d = pdist(p, centre[i]);
      if (d < bd) {
        bd = d;
        best = i;
      }
    }
    return best;
  };

  // 2. a few rounds over the pixels: each to its nearest, each entry to the
  // middle of its pixels (the shades share what's left; the big areas stay)
  for (int round = 0; round < 4; round++) {
    PColor sum[16] = {};
    uint32_t num[16] = {};
    near_i = -1;
    for (int y = 0; y < h; y++)
      for (int x = 0; x < w; x++) {
        const uint32_t c = px_at(x, y);
        const PColor p = premul(c);
        const int i = nearest_of(c, p, nearest);
        sum[i].a += p.a, sum[i].r += p.r, sum[i].g += p.g, sum[i].b += p.b;
        num[i]++;
      }
    bool moved = false;
    for (int i = 0; i < n; i++)
      if (num[i] > 0) {
        const PColor c{sum[i].a / num[i], sum[i].r / num[i], sum[i].g / num[i], sum[i].b / num[i]};
        moved |= pdist(c, centre[i]) > 0.25f;
        centre[i] = c;
      }
    if (!moved)
      break;
  }

  // 3. the palette (straight alpha, as drawn), then each pixel's nearest entry
  s->opaque = true;
  for (int i = 0; i < 16; i++) {
    if (i >= n) {
      s->c565[i] = 0;
      s->alpha[i] = 0;
      continue;
    }
    const PColor &c = centre[i];
    const float a = std::max(0.0f, std::min(255.0f, c.a));
    const auto chan = [&](float v) {
      return a < 0.5f ? 0 : (int) std::max(0.0f, std::min(255.0f, v * 255.0f / a + 0.5f));
    };
    const int r = chan(c.r), g = chan(c.g), b = chan(c.b);
    s->c565[i] = (uint16_t) (((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
    s->alpha[i] = (uint8_t) (a + 0.5f);
    if (s->alpha[i] != 255)
      s->opaque = false;
  }
  std::memset(s->px, 0, (size_t) s->stride * h);
  near_i = -1;
  for (int y = 0; y < h; y++)
    for (int x = 0; x < w; x++) {
      const uint32_t c = px_at(x, y);
      put4(s, x, y, (uint8_t) nearest_of(c, premul(c), nearest));
    }
}

// ---- drawing (the decoder) ----------------------------------------------------------

static inline uint16_t blend565(uint16_t fg, uint16_t bg, uint32_t a /* 0..255 */) {
  const uint32_t a5 = (a + 4) >> 3;  // 0..32
  uint32_t f = (fg | ((uint32_t) fg << 16)) & 0x07E0F81F;
  uint32_t b = (bg | ((uint32_t) bg << 16)) & 0x07E0F81F;
  const uint32_t r = ((((f - b) * a5) >> 5) + b) & 0x07E0F81F;
  return (uint16_t) ((r >> 16) | r);
}

static const Sprite *sprite_of(const void *src) {
  if (src == nullptr || lv_image_src_get_type(src) != LV_IMAGE_SRC_VARIABLE)
    return nullptr;
  const auto *d = static_cast<const lv_image_dsc_t *>(src);
  if (d->data == nullptr || d->data_size != sizeof(Sprite))
    return nullptr;
  const auto *s = reinterpret_cast<const Sprite *>(d->data);
  return s->magic == Sprite::MAGIC ? s : nullptr;
}

static lv_result_t dec_info(lv_image_decoder_t *, lv_image_decoder_dsc_t *dsc, lv_image_header_t *header) {
  const Sprite *s = sprite_of(dsc->src);
  if (s == nullptr)
    return LV_RESULT_INVALID;
  header->magic = LV_IMAGE_HEADER_MAGIC;
  header->w = s->w;
  header->h = s->h;
  // (what it covers: an opaque one hides what's under it)
  header->cf = s->opaque ? LV_COLOR_FORMAT_RGB565 : LV_COLOR_FORMAT_ARGB8888;
  header->stride = s->stride;
  header->flags = LV_IMAGE_FLAGS_CUSTOM_DRAW;
  return LV_RESULT_OK;
}

static lv_result_t dec_open(lv_image_decoder_t *, lv_image_decoder_dsc_t *dsc) {
  dsc->decoded = nullptr;  // (drawn by dec_draw)
  return sprite_of(dsc->src) ? LV_RESULT_OK : LV_RESULT_INVALID;
}

static void dec_close(lv_image_decoder_t *, lv_image_decoder_dsc_t *) {}

// What LVGL queued before this image (the tiles under a marker...) must be
// in the buffer before we write over it. Without an OS LVGL draws each task
// as it's added; this only finishes any left over.
static void finish_queued(lv_layer_t *layer) {
  for (int guard = 0; guard < 64; guard++) {
    bool pending = false;
    for (lv_draw_task_t *t = layer->draw_task_head; t != nullptr; t = t->next)
      if (t->state != LV_DRAW_TASK_STATE_FINISHED) {
        pending = true;
        break;
      }
    if (!pending || !lv_draw_dispatch_layer(lv_display_get_default(), layer))
      return;
  }
}

static void dec_draw(lv_layer_t *layer, const lv_image_decoder_dsc_t *dsc, const lv_area_t *coords,
                     const lv_draw_image_dsc_t *draw_dsc, const lv_area_t *clip_area);

// An opaque sprite's part `clip` (inside `coords` and inside the buffer
// `buf`) into an RGB565 buffer. Touches no LVGL state: either core runs it
// (sprite_draw_tiles splits a strip's rows between them).
__attribute__((optimize("O2"))) static void blit_opaque_565(const Sprite *s, uint8_t *data, uint32_t stride,
                                                             const lv_area_t &buf, const lv_area_t &coords,
                                                             const lv_area_t &clip) {
  const int sx0 = clip.x1 - coords.x1, sy0 = clip.y1 - coords.y1;
  const int w = clip.x2 - clip.x1 + 1, h = clip.y2 - clip.y1 + 1;
  const int dx0 = clip.x1 - buf.x1, dy0 = clip.y1 - buf.y1;
  if (w <= 0 || h <= 0)
    return;
  // the source and destination rows: one add each a row (in locals, so the
  // stores through `out` don't make the compiler re-read the sprite)
  const uint32_t in_stride = s->stride;
  const uint8_t *in_row = s->px + (uint32_t) sy0 * in_stride + ((uint32_t) sx0 >> 1);
  uint8_t *out_row = data + (uint32_t) dy0 * stride + (uint32_t) dx0 * 2;
  const bool odd = sx0 & 1;  // (starts on a byte's right pixel)
  uint16_t pal[16];
  for (int i = 0; i < 16; ++i)
    pal[i] = s->c565[i];
  if (((reinterpret_cast<uintptr_t>(out_row) + (odd ? 2 : 0)) & 3) != 0 || (stride & 3) != 0) {
    // (not 4-byte aligned: a pixel at a time)
    for (int y = 0; y < h; ++y, in_row += in_stride, out_row += stride) {
      auto *out = reinterpret_cast<uint16_t *>(out_row);
      for (int x = 0, sx = odd; x < w; ++x, ++sx) {
        const uint8_t v = in_row[sx >> 1];
        out[x] = pal[(sx & 1) ? (v & 15) : (v >> 4)];
      }
    }
    return;
  }
  // two pixels a byte through a 256-entry pair table, eight pixels (one
  // 32-bit read) a step; the destination 4-byte aligned (the even scroll)
  uint32_t pair[256];
  for (int i = 0; i < 256; ++i)
    pair[i] = (uint32_t) pal[i >> 4] | ((uint32_t) pal[i & 15] << 16);
  const uint32_t rest = (uint32_t) (w - (odd ? 1 : 0));
  const uint32_t pairs_all = rest >> 1;
  const bool last = rest & 1;
  for (int y = 0; y < h; ++y, in_row += in_stride, out_row += stride) {
    const uint8_t *__restrict b = in_row;
    uint16_t *__restrict out = reinterpret_cast<uint16_t *>(out_row);
    if (odd)
      *out++ = pal[*b++ & 15];
    uint32_t *__restrict o32 = reinterpret_cast<uint32_t *>(out);
    uint32_t pairs = pairs_all;
    while (pairs != 0 && (reinterpret_cast<uintptr_t>(b) & 3) != 0) {  // (to a word in the source)
      *o32++ = pair[*b++];
      --pairs;
    }
    const uint32_t *__restrict b32 = reinterpret_cast<const uint32_t *>(b);
    for (uint32_t n = pairs >> 2; n != 0; --n) {
      const uint32_t v = *b32++;  // (little-endian: the first byte lowest)
      o32[0] = pair[v & 255];
      o32[1] = pair[(v >> 8) & 255];
      o32[2] = pair[(v >> 16) & 255];
      o32[3] = pair[v >> 24];
      o32 += 4;
    }
    b = reinterpret_cast<const uint8_t *>(b32);
    for (uint32_t n = pairs & 3; n != 0; --n)
      *o32++ = pair[*b++];
    if (last)
      *reinterpret_cast<uint16_t *>(o32) = pal[*b >> 4];
  }
}

__attribute__((optimize("O2"))) static void draw_sprite(lv_layer_t *layer, const Sprite *s, const lv_area_t *coords,
                                                         lv_opa_t opa, const lv_area_t *clip_area) {
  lv_draw_buf_t *db = layer->draw_buf;
  if (db == nullptr || db->data == nullptr)
    return;
  lv_area_t clip;
  if (!lv_area_intersect(&clip, clip_area, &layer->_clip_area) || !lv_area_intersect(&clip, &clip, coords) ||
      !lv_area_intersect(&clip, &clip, &layer->buf_area))
    return;
  finish_queued(layer);
  const lv_color_format_t cf = (lv_color_format_t) db->header.cf;
  const uint32_t stride = db->header.stride;
  const int sx0 = clip.x1 - coords->x1, sy0 = clip.y1 - coords->y1;
  const int w = lv_area_get_width(&clip), h = lv_area_get_height(&clip);
  const int dx0 = clip.x1 - layer->buf_area.x1, dy0 = clip.y1 - layer->buf_area.y1;

  if (cf == LV_COLOR_FORMAT_RGB565) {
    // the source and destination rows: one add each a row (in locals, so the
    // stores through `out` don't make the compiler re-read the sprite)
    const uint32_t in_stride = s->stride;
    const uint8_t *in_row = s->px + (uint32_t) sy0 * in_stride + ((uint32_t) sx0 >> 1);
    uint8_t *out_row = db->data + (uint32_t) dy0 * stride + (uint32_t) dx0 * 2;
    const bool odd = sx0 & 1;  // (starts on a byte's right pixel)
    uint16_t pal[16];
    for (int i = 0; i < 16; ++i)
      pal[i] = s->c565[i];
    if (s->opaque && opa >= LV_OPA_MAX) {
      blit_opaque_565(s, db->data, stride, layer->buf_area, *coords, clip);
      return;
    }
    // with alpha: per entry - skip (clear), copy (solid) or blend, the blend's
    // colour spread out once (565 -> 0x07E0F81F form)
    uint8_t kind[16], a5[16];
    uint32_t fx[16];
    for (int i = 0; i < 16; ++i) {
      const uint32_t al = (s->alpha[i] * (uint32_t) opa + 127) / 255;
      kind[i] = al < 4 ? 0 : al >= 252 ? 1 : 2;
      a5[i] = (uint8_t) ((al + 4) >> 3);
      fx[i] = (pal[i] | ((uint32_t) pal[i] << 16)) & 0x07E0F81F;
    }
    auto put = [&](uint16_t *o, uint8_t i) {
      if (kind[i] == 1) {
        *o = pal[i];
      } else if (kind[i] == 2) {
        const uint32_t bx = (*o | ((uint32_t) *o << 16)) & 0x07E0F81F;
        const uint32_t r = ((((fx[i] - bx) * a5[i]) >> 5) + bx) & 0x07E0F81F;
        *o = (uint16_t) ((r >> 16) | r);
      }
    };
    // (a byte whose two pixels are both clear: skipped whole)
    const bool clear0 = kind[0] == 0;
    const uint32_t rest = (uint32_t) (w - (odd ? 1 : 0));
    const uint32_t pairs_all = rest >> 1;
    const bool last = rest & 1;
    for (int y = 0; y < h; ++y, in_row += in_stride, out_row += stride) {
      const uint8_t *__restrict b = in_row;
      uint16_t *__restrict out = reinterpret_cast<uint16_t *>(out_row);
      if (odd)
        put(out++, *b++ & 15);
      for (uint32_t n = pairs_all; n != 0; --n, ++b, out += 2) {
        const uint8_t v = *b;
        if (v == 0 && clear0)
          continue;
        put(out, v >> 4);
        put(out + 1, v & 15);
      }
      if (last)
        put(out, *b >> 4);
    }
    return;
  }

  if (cf == LV_COLOR_FORMAT_ARGB8888 || cf == LV_COLOR_FORMAT_XRGB8888) {
    // (a layer of its own: an object with opacity / a transform; rare here)
    for (int y = 0; y < h; y++) {
      const uint8_t *in = s->px + (sy0 + y) * s->stride;
      auto *out = reinterpret_cast<uint32_t *>(db->data + (dy0 + y) * stride) + dx0;
      for (int x = 0, sx = sx0; x < w; x++, sx++) {
        const uint8_t b = in[sx >> 1];
        const uint8_t i = (sx & 1) ? (b & 15) : (b >> 4);
        const uint32_t al = (s->alpha[i] * (uint32_t) opa + 127) / 255;
        if (al == 0)
          continue;
        const uint16_t c = s->c565[i];
        const uint32_t r = ((c >> 11) & 31) * 255 / 31, g = ((c >> 5) & 63) * 255 / 63, bl = (c & 31) * 255 / 31;
        const uint32_t d = out[x];
        const uint32_t da = d >> 24;
        if (al >= 255 || da == 0) {
          out[x] = (al << 24) | (r << 16) | (g << 8) | bl;
          continue;
        }
        // straight alpha "over"
        const uint32_t oa = al + da * (255 - al) / 255;
        auto mix = [&](uint32_t sc, uint32_t dc) { return (sc * al + dc * da * (255 - al) / 255) / oa; };
        out[x] = (oa << 24) | (mix(r, (d >> 16) & 255) << 16) | (mix(g, (d >> 8) & 255) << 8) | mix(bl, d & 255);
      }
    }
    return;
  }
  static bool warned = false;
  if (!warned) {
    warned = true;
    ESP_LOGW(TAG, "Can't draw into colour format %d", (int) cf);
  }
}

static void dec_draw(lv_layer_t *layer, const lv_image_decoder_dsc_t *dsc, const lv_area_t *coords,
                     const lv_draw_image_dsc_t *draw_dsc, const lv_area_t *clip_area) {
  const Sprite *s = sprite_of(dsc->src);
  if (s != nullptr)
    draw_sprite(layer, s, coords, draw_dsc->opa, clip_area);
}

void sprite_draw(lv_layer_t *layer, const Sprite *s, int x, int y, lv_opa_t opa);

// ---- tiles on both cores -------------------------------------------------------------

// A strip's tiles: this core copies the top half of its rows, a helper task on
// the other core the bottom half (the copy is CPU-bound: ~2x)
struct TilesJob {
  const SpriteBlit *items;
  int n;
  uint8_t *data;
  uint32_t stride;
  lv_area_t buf, clip;
};
static TilesJob helper_job;
static SemaphoreHandle_t helper_go = nullptr, helper_done = nullptr;
static bool helper_ok = false;

static void run_tiles(const TilesJob &j) {
  for (int i = 0; i < j.n; ++i) {
    const Sprite *sp = j.items[i].s;
    const lv_area_t coords{j.items[i].x, j.items[i].y, j.items[i].x + sp->w - 1, j.items[i].y + sp->h - 1};
    lv_area_t c;
    c.x1 = std::max(coords.x1, j.clip.x1);
    c.y1 = std::max(coords.y1, j.clip.y1);
    c.x2 = std::min(coords.x2, j.clip.x2);
    c.y2 = std::min(coords.y2, j.clip.y2);
    if (c.x1 <= c.x2 && c.y1 <= c.y2)
      blit_opaque_565(sp, j.data, j.stride, j.buf, coords, c);
  }
}

static void helper_main(void *) {
  for (;;) {
    if (xSemaphoreTake(helper_go, portMAX_DELAY) != pdTRUE)
      continue;
    run_tiles(helper_job);
    xSemaphoreGive(helper_done);
  }
}

static void helper_start() {
  static bool tried = false;
  if (tried)
    return;
  tried = true;
  helper_go = xSemaphoreCreateBinary();
  helper_done = xSemaphoreCreateBinary();
  // the other core than LVGL's; above the map's tile worker (priority 1)
  // sharing it, which waits a few ms a frame
  helper_ok = helper_go != nullptr && helper_done != nullptr &&
              xTaskCreatePinnedToCore(helper_main, "rt_blit", 3072, nullptr, 5, nullptr, 1 - xPortGetCoreID()) ==
                  pdPASS;
  if (!helper_ok)
    ESP_LOGW(TAG, "No second core for the map's tiles: one core draws them");
}

void sprite_draw_tiles(lv_layer_t *layer, const SpriteBlit *items, int n) {
  if (layer == nullptr || n <= 0)
    return;
  lv_draw_buf_t *db = layer->draw_buf;
  if (db == nullptr || db->data == nullptr)
    return;
  if (db->header.cf != LV_COLOR_FORMAT_RGB565) {
    // (a layer of its own: one at a time, the general way)
    for (int i = 0; i < n; ++i)
      sprite_draw(layer, items[i].s, items[i].x, items[i].y);
    return;
  }
  lv_area_t clip;
  if (!lv_area_intersect(&clip, &layer->_clip_area, &layer->buf_area))
    return;
  finish_queued(layer);  // (what's under the tiles is in the buffer first)
  helper_start();
  TilesJob job{items, n, db->data, db->header.stride, layer->buf_area, clip};
  const int rows = clip.y2 - clip.y1 + 1;
  if (helper_ok && rows >= 8) {
    // the bottom half to the other core, the top half here
    helper_job = job;
    helper_job.clip.y1 = clip.y1 + rows / 2;
    job.clip.y2 = helper_job.clip.y1 - 1;
    xSemaphoreGive(helper_go);
    run_tiles(job);
    xSemaphoreTake(helper_done, portMAX_DELAY);  // (the buffer is LVGL's again)
  } else {
    run_tiles(job);
  }
}

void sprite_draw(lv_layer_t *layer, const Sprite *s, int x, int y, lv_opa_t opa) {
  if (layer == nullptr || s == nullptr || opa <= LV_OPA_MIN)
    return;
  const lv_area_t coords{x, y, x + s->w - 1, y + s->h - 1};
  draw_sprite(layer, s, &coords, opa, &layer->_clip_area);
}

void sprite_init() {
  static bool done = false;
  if (done)
    return;
  done = true;
  lv_image_decoder_t *d = lv_image_decoder_create();
  lv_image_decoder_set_info_cb(d, dec_info);
  lv_image_decoder_set_open_cb(d, dec_open);
  lv_image_decoder_set_close_cb(d, dec_close);
  d->custom_draw_cb = dec_draw;
  d->name = "room_tiles_sprite";
}

// ---- pre-rendering -------------------------------------------------------------------

SpriteCanvas::SpriteCanvas(int w, int h, int x0, int y0) : w_(w), h_(h) {
  this->buf_ = static_cast<uint32_t *>(heap_caps_aligned_calloc(64, (size_t) w * h, 4, MALLOC_CAP_SPIRAM));
  if (this->buf_ == nullptr)
    return;
  if (lv_draw_buf_init(&this->draw_buf_, w, h, LV_COLOR_FORMAT_ARGB8888, w * 4, this->buf_, w * h * 4) !=
      LV_RESULT_OK) {
    heap_caps_free(this->buf_);
    this->buf_ = nullptr;
    return;
  }
  lv_layer_init(&this->layer_);
  const lv_area_t area{x0, y0, x0 + w - 1, y0 + h - 1};
  this->layer_.draw_buf = &this->draw_buf_;
  this->layer_.color_format = LV_COLOR_FORMAT_ARGB8888;
  this->layer_.buf_area = area;
  this->layer_._clip_area = area;
  this->layer_.phy_clip_area = area;
  lv_draw_unit_send_event(nullptr, LV_EVENT_CHILD_CREATED, &this->layer_);
}

void SpriteCanvas::finish() {
  if (this->finished_ || this->buf_ == nullptr)
    return;
  this->finished_ = true;
  // (as lv_canvas_finish_layer)
  this->layer_.all_tasks_added = true;
  while (this->layer_.draw_task_head != nullptr) {
    lv_draw_dispatch_wait_for_request();
    if (!lv_draw_dispatch_layer(lv_display_get_default(), &this->layer_)) {
      lv_draw_wait_for_finish();
      lv_draw_dispatch_request();
    }
  }
  lv_draw_unit_send_event(nullptr, LV_EVENT_SCREEN_LOAD_START, &this->layer_);
  lv_draw_unit_send_event(nullptr, LV_EVENT_CHILD_DELETED, &this->layer_);
}

SpriteCanvas::~SpriteCanvas() {
  this->finish();
  heap_caps_free(this->buf_);
}

Sprite *SpriteCanvas::to_sprite(bool prefer_internal, bool rotate_ccw) {
  this->finish();
  if (this->buf_ == nullptr)
    return nullptr;
  // (turned: the sprite is the canvas's height wide)
  Sprite *s = rotate_ccw ? sprite_new(this->h_, this->w_, prefer_internal) : sprite_new(this->w_, this->h_, prefer_internal);
  if (s != nullptr)
    sprite_quantize_argb(s, this->buf_, this->w_, rotate_ccw);
  return s;
}

}  // namespace esphome::room_tiles
