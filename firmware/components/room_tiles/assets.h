// Room Tiles panel: the asset area - the downloaded theme pack (images +
// colours) and wording (assets/build_panel.py has the pack format). Packs are
// kept exactly as downloaded and drawn straight from flash (mapped).
#pragma once

#include <atomic>
#include <cstdint>
#include <map>
#include <string>

#include <esp_partition.h>
#include <lvgl.h>

#include "esphome/components/json/json_util.h"
#include "rt_assets.h"

namespace esphome::room_tiles {

enum PackKind : uint8_t { PACK_THEME = 1, PACK_STRINGS = 2 };

class AssetStore {
 public:
  /// Find the asset area and load whatever valid packs it holds.
  bool begin();
  bool has_area() const { return this->part_ != nullptr; }
  uint32_t area_size() const { return this->part_ ? this->part_->size : 0; }

  /// The id of the pack stored for that kind ("" = none / broken).
  const std::string &pack_id(PackKind kind) const { return this->region_(kind).id; }

  /// An image from the theme pack, or nullptr (no theme stored yet).
  const lv_image_dsc_t *image(AssetId id) const;
  /// A theme colour token ("accent", "light"...), or `fallback`.
  /// The theme's idle clock (its clock.json as text; "" = it draws none).
  const std::string &clock() const { return this->clock_; }
  uint32_t color(const std::string &token, uint32_t fallback) const;
  /// A string from the wording pack, or the key itself.
  std::string t(const char *key) const;

  /// Check a downloaded pack (magic, kind, size, SHA-256). Any thread.
  static bool check(PackKind kind, const uint8_t *data, size_t len, std::string &id, std::string &error);
  /// Main loop: stop drawing from that pack (before it's rewritten).
  void release(PackKind kind);
  /// Main loop: only the pack's flash mapping let go (the wording's parsed
  /// copy kept: still usable while its pack is rewritten).
  void unmap(PackKind kind);
  /// Download task: erase + write the pack into its region, in 64 KB steps
  /// with short pauses (each erase stops everything running from flash for a
  /// moment); `percent` follows along. Blocking.
  bool write(PackKind kind, const uint8_t *data, size_t len, std::string &error, std::atomic<int> *percent);
  /// Main loop: drop the stored pack (its header sector) - it downloads again.
  void forget(PackKind kind);
  /// Main loop: map and load what's stored now. `verify` = check its SHA-256
  /// (skipped right after a write: it was checked in memory before).
  bool load(PackKind kind, bool verify = true);

 protected:
  struct Region {
    size_t offset{0};
    size_t size{0};
    const uint8_t *map{nullptr};
    esp_partition_mmap_handle_t handle{0};
    std::string id;
  };
  Region &region_(PackKind kind) { return kind == PACK_THEME ? this->theme_ : this->strings_; }
  const Region &region_(PackKind kind) const { return kind == PACK_THEME ? this->theme_ : this->strings_; }
  void load_theme_();
  void load_strings_();

  const esp_partition_t *part_{nullptr};
  Region theme_;
  Region strings_;
  // (mutable: an I8X picture becomes its RGB565A8 copy the first time asked for)
  mutable lv_image_dsc_t images_[IMG_COUNT]{};
  bool have_image_[IMG_COUNT]{};
  // I8X (build_panel.py): expanded into RGB565A8 in PSRAM on first use - LVGL
  // would convert an I8 picture to ARGB8888 on every draw. The copies go when
  // the theme does.
  bool is_i8x_[IMG_COUNT]{};
  mutable uint8_t *expanded_[IMG_COUNT]{};
  void expand_(AssetId id) const;
  void free_expanded_();
  std::map<std::string, uint32_t> colors_;
  std::string clock_;  // the theme's clock.json ("": it draws no clock)
  JsonDocument strings_doc_;
};

}  // namespace esphome::room_tiles
