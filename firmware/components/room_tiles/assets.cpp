#include "assets.h"

#include <algorithm>
#include <cstring>

#include <esp_heap_caps.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <mbedtls/sha256.h>

#include "esphome/core/log.h"
#include "signing.h"  // (PANEL_SCHEMA)

namespace esphome::room_tiles {

static const char *const TAG = "room_tiles.assets";

// The asset area: the theme pack from the start, the wording in the last
// 256 KB (assets/build_panel.py writes both formats).
// MIRRORED: assets/build_panel.py STRINGS_REGION - a change here must be made there too.
static const size_t STRINGS_REGION = 256 * 1024;
static const size_t HEADER = 64;
static const size_t ENTRY = 56;
static const size_t HASH = 32;

struct PackHeader {
  uint32_t data_size;  // header + entries + data (the hash follows)
  uint16_t count;
  uint8_t kind;
  char id[33];
};

static bool read_header(const uint8_t *p, size_t avail, PackHeader &h) {
  if (avail < HEADER + HASH || memcmp(p, "RTP1", 4) != 0)
    return false;
  uint16_t version;
  memcpy(&version, p + 4, 2);
  memcpy(&h.count, p + 6, 2);
  memcpy(&h.data_size, p + 8, 4);
  h.kind = p[12];
  memcpy(h.id, p + 16, 32);
  h.id[32] = '\0';
  // (the pack's format = the panels' one: a pack made for another firmware -
  // a new picture kind it can't read - is never taken, rather than drawn wrong)
  return version == PANEL_SCHEMA && h.data_size >= HEADER + ENTRY * h.count && h.data_size + HASH <= avail;
}

// Every entry inside the pack's data, and every picture as big as its size
// says (what's drawn or parsed is read from there - nothing past it)
static bool entries_ok(const uint8_t *p, const PackHeader &h, uint8_t kind) {
  if (kind == PACK_STRINGS && h.count < 1)
    return false;
  const uint64_t first = HEADER + (uint64_t) ENTRY * h.count;
  for (uint16_t i = 0; i < h.count; i++) {
    const uint8_t *e = p + HEADER + ENTRY * i;
    const uint8_t ekind = e[32], format = e[33];
    uint16_t w, ht, stride;
    uint32_t offset, size;
    memcpy(&w, e + 34, 2);
    memcpy(&ht, e + 36, 2);
    memcpy(&stride, e + 38, 2);
    memcpy(&offset, e + 40, 4);
    memcpy(&size, e + 44, 4);
    if (offset < first || (uint64_t) offset + size > h.data_size)
      return false;
    if (ekind != 1)
      continue;
    const uint64_t px = (uint64_t) w * ht;
    uint64_t need;
    if (format == 1)  // I8: the palette, then a row of `stride` a line
      need = 1024 + (uint64_t) stride * ht;
    else if (format == 3)  // I8X: the palette, then an index a pixel
      need = 1024 + px;
    else if (format == 2)  // RGB565A8: the colours (`stride` a line), then an alpha a pixel
      need = (uint64_t) stride * ht + px;
    else
      continue;  // (a kind this firmware doesn't draw: never used)
    if (w == 0 || ht == 0 || (format != 3 && stride < (format == 2 ? 2u * w : (uint32_t) w)) || size < need)
      return false;
  }
  return true;
}

bool AssetStore::check(PackKind kind, const uint8_t *data, size_t len, std::string &id, std::string &error) {
  PackHeader h;
  if (!read_header(data, len, h) || h.data_size + HASH != len) {
    error = "not a Room Tiles pack";
    return false;
  }
  if (h.kind != kind) {
    error = "wrong kind of pack";
    return false;
  }
  uint8_t digest[32];
  mbedtls_sha256(data, h.data_size, digest, 0);
  if (memcmp(digest, data + h.data_size, 32) != 0) {
    error = "damaged (checksum)";
    return false;
  }
  if (!entries_ok(data, h, kind)) {
    error = "damaged (its entries)";
    return false;
  }
  id = h.id;
  return true;
}

bool AssetStore::begin() {
  this->part_ = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, (esp_partition_subtype_t) 0x40, "assets");
  if (this->part_ == nullptr || this->part_->size <= STRINGS_REGION * 2) {
    this->part_ = nullptr;
    return false;
  }
  this->theme_.offset = 0;
  this->theme_.size = this->part_->size - STRINGS_REGION;
  this->strings_.offset = this->part_->size - STRINGS_REGION;
  this->strings_.size = STRINGS_REGION;
  this->load(PACK_THEME);
  this->load(PACK_STRINGS);
  return true;
}

void AssetStore::release(PackKind kind) {
  Region &r = this->region_(kind);
  if (kind == PACK_THEME) {
    memset(this->have_image_, 0, sizeof(this->have_image_));
    this->free_expanded_();
    this->colors_.clear();
    this->clock_.clear();
  } else {
    this->strings_doc_.clear();
  }
  if (r.map != nullptr) {
    esp_partition_munmap(r.handle);
    r.map = nullptr;
  }
  r.id.clear();
}

void AssetStore::unmap(PackKind kind) {
  Region &r = this->region_(kind);
  if (r.map != nullptr) {
    esp_partition_munmap(r.handle);
    r.map = nullptr;
  }
}

void AssetStore::forget(PackKind kind) {
  this->release(kind);
  if (this->part_ != nullptr)
    esp_partition_erase_range(this->part_, this->region_(kind).offset, 4096);
}

bool AssetStore::write(PackKind kind, const uint8_t *data, size_t len, std::string &error,
                       std::atomic<int> *percent) {
  Region &r = this->region_(kind);
  if (this->part_ == nullptr || len > r.size) {
    error = "doesn't fit the asset area";
    return false;
  }
  // 64 KB at a time (erase, then write that piece), pausing in between so
  // the screen and the HA connection keep running. The header goes LAST: a
  // write cut short (power loss) leaves no valid magic - the region reads as
  // empty, never half-new.
  static const size_t STEP = 64 * 1024;
  const size_t total = (len + 4095) & ~size_t(4095);
  esp_err_t err = ESP_OK;
  for (size_t pos = 0; pos < total && err == ESP_OK; pos += STEP) {
    const size_t n = std::min(STEP, total - pos);
    err = esp_partition_erase_range(this->part_, r.offset + pos, n);
    const size_t from = std::max(pos, HEADER), to = std::min(pos + n, len);
    if (err == ESP_OK && to > from)
      err = esp_partition_write(this->part_, r.offset + from, data + from, to - from);
    if (percent != nullptr)
      percent->store((int) ((pos + n) * 100 / total));
    vTaskDelay(pdMS_TO_TICKS(10));
  }
  if (err == ESP_OK)
    err = esp_partition_write(this->part_, r.offset, data, HEADER);
  if (err != ESP_OK) {
    error = esp_err_to_name(err);
    return false;
  }
  return true;
}

bool AssetStore::load(PackKind kind, bool verify) {
  Region &r = this->region_(kind);
  this->release(kind);
  if (this->part_ == nullptr)
    return false;
  uint8_t head[HEADER];
  PackHeader h;
  if (esp_partition_read(this->part_, r.offset, head, HEADER) != ESP_OK || memcmp(head, "RTP1", 4) != 0)
    return false;  // nothing stored yet
  memcpy(&h.data_size, head + 8, 4);
  if (h.data_size + HASH > r.size)
    return false;
  const void *ptr = nullptr;
  if (esp_partition_mmap(this->part_, r.offset, h.data_size + HASH, ESP_PARTITION_MMAP_DATA, &ptr, &r.handle) != ESP_OK) {
    ESP_LOGE(TAG, "Couldn't map the asset area");
    return false;
  }
  r.map = static_cast<const uint8_t *>(ptr);
  std::string id, error;
  PackHeader full;
  if (!verify) {
    // (just written: checked in memory - its entries checked again here,
    // cheap, as the pictures are drawn straight from flash)
    if (!read_header(r.map, h.data_size + HASH, full) || full.kind != kind || !entries_ok(r.map, full, kind)) {
      ESP_LOGW(TAG, "Stored %s pack is damaged - it will be downloaded again", kind == PACK_THEME ? "theme" : "wording");
      esp_partition_munmap(r.handle);
      r.map = nullptr;
      return false;
    }
    char raw[33];
    memcpy(raw, r.map + 16, 32);
    raw[32] = '\0';
    id = raw;
  } else if (!check(kind, r.map, h.data_size + HASH, id, error)) {
    ESP_LOGW(TAG, "Stored %s pack is %s - it will be downloaded again", kind == PACK_THEME ? "theme" : "wording",
             error.c_str());
    esp_partition_munmap(r.handle);
    r.map = nullptr;
    return false;
  }
  r.id = id;
  if (kind == PACK_THEME)
    this->load_theme_();
  else
    this->load_strings_();
  ESP_LOGI(TAG, "%s pack %s (%u KB)", kind == PACK_THEME ? "Theme" : "Wording", r.id.c_str(),
           (unsigned) (h.data_size / 1024));
  return true;
}

void AssetStore::load_theme_() {
  this->free_expanded_();  // (a theme loaded again: none of the old copies)
  const uint8_t *p = this->theme_.map;
  uint16_t count;
  memcpy(&count, p + 6, 2);
  int images = 0;
  for (uint16_t i = 0; i < count; i++) {
    const uint8_t *e = p + HEADER + ENTRY * i;
    char name[33];
    memcpy(name, e, 32);
    name[32] = '\0';
    const uint8_t kind = e[32], format = e[33];
    uint16_t w, h, stride;
    uint32_t offset, size;
    memcpy(&w, e + 34, 2);
    memcpy(&h, e + 36, 2);
    memcpy(&stride, e + 38, 2);
    memcpy(&offset, e + 40, 4);
    memcpy(&size, e + 44, 4);
    if (kind == 2 && strcmp(name, "colors") == 0) {
      JsonDocument doc = json::parse_json(p + offset, size);
      for (JsonPair kv : doc.as<JsonObject>()) {
        const char *hex = kv.value() | "";
        if (hex[0] == '#')
          this->colors_[kv.key().c_str()] = strtoul(hex + 1, nullptr, 16);
      }
      continue;
    }
    if (kind == 2 && strcmp(name, "clock") == 0) {
      // the idle clock's theme face (build_panel.py theme_clock): kept as
      // text, read when the clock shows
      this->clock_.assign(reinterpret_cast<const char *>(p + offset), size);
      continue;
    }
    if (kind != 1)
      continue;
    int slot = -1;
    for (int s = 0; s < IMG_COUNT; s++) {
      if (strcmp(ASSET_NAMES[s], name) == 0) {
        slot = s;
        break;
      }
    }
    if (slot < 0)
      continue;  // a newer pack's image this firmware doesn't use
    lv_image_dsc_t &d = this->images_[slot];
    d = {};
    d.header.magic = LV_IMAGE_HEADER_MAGIC;
    // (I8X: kept as the pack's I8 until first asked for - then expanded)
    d.header.cf = format == 1 || format == 3 ? LV_COLOR_FORMAT_I8 : LV_COLOR_FORMAT_RGB565A8;
    this->is_i8x_[slot] = format == 3;
    d.header.w = w;
    d.header.h = h;
    d.header.stride = stride;
    d.data_size = size;
    d.data = p + offset;
    this->have_image_[slot] = true;
    images++;
  }
  ESP_LOGD(TAG, "Theme: %d images, %u colours", images, (unsigned) this->colors_.size());
}

void AssetStore::load_strings_() {
  const uint8_t *p = this->strings_.map;
  uint32_t offset, size;
  memcpy(&offset, p + HEADER + 40, 4);
  memcpy(&size, p + HEADER + 44, 4);
  this->strings_doc_ = json::parse_json(p + offset, size);
}

const lv_image_dsc_t *AssetStore::image(AssetId id) const {
  if (id < 0 || id >= IMG_COUNT || !this->have_image_[id])
    return nullptr;
  if (this->is_i8x_[id] && this->expanded_[id] == nullptr)
    this->expand_(id);
  return &this->images_[id];
}

// An I8X picture (256 BGRA palette entries, then one index a pixel) into
// RGB565A8 in PSRAM, once: the colours, then the alphas - drawn (and turned)
// straight from there. No PSRAM: left as I8 (LVGL converts it each draw).
void AssetStore::expand_(AssetId id) const {
  lv_image_dsc_t &d = this->images_[id];
  const int w = d.header.w, h = d.header.h, n = w * h;
  const uint8_t *pal = static_cast<const uint8_t *>(d.data), *idx = pal + 1024;
  auto *out = static_cast<uint8_t *>(heap_caps_malloc((size_t) n * 3, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (out == nullptr)
    return;
  uint16_t rgb[256];
  for (int i = 0; i < 256; i++) {
    const uint8_t b = pal[i * 4], g = pal[i * 4 + 1], r = pal[i * 4 + 2];
    rgb[i] = (uint16_t) (((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3));
  }
  auto *colour = reinterpret_cast<uint16_t *>(out);
  uint8_t *alpha = out + (size_t) n * 2;
  for (int i = 0; i < n; i++) {
    colour[i] = rgb[idx[i]];
    alpha[i] = pal[idx[i] * 4 + 3];
  }
  this->expanded_[id] = out;
  d.header.cf = LV_COLOR_FORMAT_RGB565A8;
  d.header.stride = (uint32_t) w * 2;
  d.data_size = (uint32_t) n * 3;
  d.data = out;
}

void AssetStore::free_expanded_() {
  for (int i = 0; i < IMG_COUNT; i++) {
    if (this->expanded_[i] != nullptr)
      heap_caps_free(this->expanded_[i]);
    this->expanded_[i] = nullptr;
    this->is_i8x_[i] = false;
  }
}

uint32_t AssetStore::color(const std::string &token, uint32_t fallback) const {
  auto it = this->colors_.find(token);
  return it == this->colors_.end() ? fallback : it->second;
}

std::string AssetStore::t(const char *key) const {
  const char *s = this->strings_doc_[key] | (const char *) nullptr;
  return s != nullptr ? std::string(s) : std::string(key);
}

}  // namespace esphome::room_tiles
