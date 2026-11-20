#include "room_tiles.h"

#include <algorithm>
#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>

#include <esp_attr.h>
#include <esp_heap_caps.h>
#include <esp_rom_sys.h>
#include <esp_http_client.h>
#include <esp_app_desc.h>
#include <esp_ota_ops.h>
#include <mbedtls/sha256.h>
#include <nvs.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

// LVGL 9.5's lvgl.h no longer pulls in the image cache's API
#include <src/misc/cache/instance/lv_image_cache.h>

#include "esphome/components/api/api_server.h"
#ifdef USE_WIFI
#include "esphome/components/wifi/wifi_component.h"
#endif
#include "esphome/components/json/json_util.h"
#include "esphome/core/helpers.h"
#include "esphome/core/application.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"
#include "boot_words.h"
#include "psram_scope.h"
#include "signing.h"

namespace esphome::room_tiles {

static const char *const TAG = "room_tiles";

static const char *const PANEL_PATH = "/api/room_tiles/panel";
static const char *const PACK_PATH = "/api/room_tiles/panel/pack";
static const char *const FIRMWARE_PATH = "/api/room_tiles/panel/firmware";
// a firmware update that failed: tried again after this long
static const uint32_t FIRMWARE_RETRY_MS = 10 * 60 * 1000;
// an automatic update waits until nobody's using the panel: idle (asleep,
// the clock, dimmed) - or this long untouched when it never goes idle
static const uint32_t AUTO_UPDATE_UNTOUCHED_MS = 10 * 60 * 1000;
static const uint32_t PICK_RESEND_MS = 15 * 1000;
// HA gone while a panel is idle on its clock: "Connecting…" shows dimmed this
// long, then the screen goes dark (idle_loop_)
static const uint32_t OFFLINE_DARK_MS = 10 * 60 * 1000;
static const int KNOB_SCROLL_PX = 64;  // (a knob click in a list: about one row)
static const uint32_t KNOB_AGAIN_MS = 500;  // (longer than a scroll animation runs)
// a fast turn goes further a click: the time since the last click the same
// way picks how many steps this one makes (slow = 1 step, as always)
static int knob_steps(uint32_t gap_ms) {
  if (gap_ms < 50)
    return 4;
  if (gap_ms < 90)
    return 3;
  if (gap_ms < 150)
    return 2;
  return 1;
}
// back from HA's absence on a screen it darkened: this long for the tiles'
// states to show an animation (or the clock to come) before it stays dark
static const uint32_t RESUME_WINDOW_MS = 15 * 1000;
static const size_t MAX_BODY = 6 * 1024 * 1024;  // bigger than this is refused
static const uint32_t RETRY_MS = 30000;
// a theme picked on the panel: how long the boot screen waits for its download
static const uint32_t THEME_WAIT_MS = 20000;
// Home Assistant gone this long: the boot screen ("Connecting to Home
// Assistant…") instead of a board whose states may be old
static const uint32_t OFFLINE_AFTER_MS = 10000;
// on Wi-Fi without Home Assistant this long: the boot screen offers Change
// Wi-Fi (a panel set up on the wrong network never gets to its settings)
static const uint32_t WIFI_BUTTON_AFTER_MS = 90000;
static const uint32_t WIFI_ARMED_MS = 5000;  // (its "tap again")

// ESPHome's main loop naps this long after each pass (its default is 16 ms).
// A touch doesn't wake it - the touch panel's interrupt only sets a flag -
// so a tap can wait a whole nap before it's read: short while the screen is
// on, the default while it's off. (The map runs without a nap while it pans.)
static const uint32_t LOOP_AWAKE_MS = 5, LOOP_ASLEEP_MS = 16;

// An allocation that fails (internal RAM full / too broken up) aborts the
// panel; what it was is kept over the reboot (and printed on the serial port
// at once) so the next boot can say
struct OomNote {
  uint32_t magic;
  uint32_t size, caps, free_internal, largest_internal;
  char fn[32];
};
static constexpr uint32_t OOM_MAGIC = 0x4F4F4D21;  // "OOM!"
static RTC_NOINIT_ATTR OomNote oom_note;

static void on_failed_alloc(size_t size, uint32_t caps, const char *fn) {
  oom_note.magic = OOM_MAGIC;
  oom_note.size = (uint32_t) size;
  oom_note.caps = caps;
  oom_note.free_internal = (uint32_t) heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
  oom_note.largest_internal = (uint32_t) heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL);
  strncpy(oom_note.fn, fn != nullptr ? fn : "?", sizeof(oom_note.fn) - 1);
  oom_note.fn[sizeof(oom_note.fn) - 1] = 0;
  esp_rom_printf("Room Tiles: out of memory - %u bytes (caps 0x%x) in %s; internal free %u, largest %u\n",
                 (unsigned) size, (unsigned) caps, oom_note.fn, (unsigned) oom_note.free_internal,
                 (unsigned) oom_note.largest_internal);
}

void RoomTiles::setup() {
  {
    // this firmware's build: its ELF's SHA-256, first 8 bytes (Room Tiles reads
    // the same from an image file - firmware.py)
    const uint8_t *sha = esp_app_get_description()->app_elf_sha256;
    char hex[17];
    for (int i = 0; i < 8; i++)
      snprintf(hex + 2 * i, 3, "%02x", sha[i]);
    this->build_ = hex;
  }
  if (oom_note.magic == OOM_MAGIC) {
    ESP_LOGE(TAG, "The last restart: out of memory - %u bytes (caps 0x%x) in %s; internal RAM free %u, largest block %u",
             (unsigned) oom_note.size, (unsigned) oom_note.caps, oom_note.fn, (unsigned) oom_note.free_internal,
             (unsigned) oom_note.largest_internal);
    this->oom_report_ = true;
  }
  oom_note.magic = 0;
  heap_caps_register_failed_alloc_callback(on_failed_alloc);
  App.set_loop_interval(LOOP_AWAKE_MS);  // (taps read sooner: sleep_)
  // the display settings, kept on the panel (the old panels')
  this->display_pref_ = global_preferences->make_preference<Display>(0x52544450u /* "RTDP" */);
  if (!this->display_pref_.load(&this->display_))
    this->display_ = Display{};
  this->display_.brightness = std::max<uint8_t>(10, std::min<uint8_t>(100, this->display_.brightness));
  // when idle: its own record. A new (or factory reset) panel's first
  // defaults: the digital clock after 1 minute untouched (the round one: 30
  // s), at 40 % - a clock when nobody's using it, and updates come sooner.
  // A panel set up before keeps its own.
  this->idle_pref_ = global_preferences->make_preference<Idle>(0x52544932u /* "RTI2" */);
  if (!this->idle_pref_.load(&this->idle_)) {
    this->idle_ = Idle{};
    this->idle_.mode = IDLE_DIGITAL;
    if (this->display_.sleep_s == 0)
      this->display_.sleep_s = this->strip_ ? 30 : 60;
  }
  this->idle_bright_pref_ = global_preferences->make_preference<uint8_t>(0x52544942u /* "RTIB" */);
  if (!this->idle_bright_pref_.load(&this->idle_bright_))
    this->idle_bright_ = 40;
  this->idle_bright_ = std::max<uint8_t>(10, std::min<uint8_t>(100, this->idle_bright_));
  this->idle_lights_pref_ = global_preferences->make_preference<uint8_t>(0x5254494Cu /* "RTIL" */);
  if (!this->idle_lights_pref_.load(&this->idle_lights_) || this->idle_lights_ > 1)
    this->idle_lights_ = 0;
  this->wifi_chip_pref_ = global_preferences->make_preference<uint32_t>(0x52545743u /* "RTWC" */);
  if (!this->wifi_chip_pref_.load(&this->wifi_chip_tried_))
    this->wifi_chip_tried_ = 0;
  this->strip_points_pref_ = global_preferences->make_preference<StripPoints>(0x52545350u /* "RTSP" */);
  if (!this->strip_points_pref_.load(&this->strip_points_))
    this->strip_points_ = StripPoints{};
  this->clock24_pref_ = global_preferences->make_preference<uint8_t>(0x5254434Bu /* "RTCK" */);
  if (!this->clock24_pref_.load(&this->clock24_) || this->clock24_ > 2)
    this->clock24_ = 0;
  // an automatic update while the screen was dark: this start stays dark
  // (once - set_backlight)
  this->quiet_pref_ = global_preferences->make_preference<uint8_t>(0x52545142u /* "RTQB" */);
  uint8_t dark = 0;
  if (this->quiet_pref_.load(&dark) && dark == 1) {
    this->quiet_boot_ = true;
    dark = 0;
    this->quiet_pref_.save(&dark);
  }
  this->queue_pref_ = global_preferences->make_preference<uint8_t>(0x52545141u /* "RTQA" */);
  uint8_t autostart = 0;
  if (this->queue_pref_.load(&autostart))
    this->queue_autostart_ = autostart == 1;
  if (!this->assets_.begin())
    ESP_LOGE(TAG, "No asset area - this panel needs the new flash layout (one USB flash)");
  // the language picked on the first start (a new panel's boot screen)
  this->boot_lang_pref_ = global_preferences->make_preference<BootLang>(0x52544C47u /* "RTLG" */);
  if (!this->boot_lang_pref_.load(&this->boot_lang_))
    this->boot_lang_ = BootLang{};
  this->boot_lang_.code[sizeof(this->boot_lang_.code) - 1] = 0;
  if (boot_lang_index(this->boot_lang_.code) < 0)
    this->boot_lang_ = BootLang{};
  this->assets_changed_();  // what's stored from before shows right away
  this->say_("panel.connecting", "Connecting to Home Assistant…");
  this->wifi_setup_.attach(this);  // (it hears every Wi-Fi scan from now on)
  // status words (tile_words...) in the panel's own language: its string pack
  this->states_.set_words([this](const char *token) { return this->assets_.t(token); });
  this->states_.on_change([this](const std::string &entity) {
    this->board_.entity_changed(entity);
    this->picker_.entity_changed(entity);
    this->map_view_.entity_changed(entity);
  });
}

// MIRRORED: frontend/src/input.ts TAP_SLOP_PX / tapGuard - a change here must be made there too.
// Every press's start; a click whose finger travelled further than the slop
// is stopped at the touchscreen - it never reaches the object
static lv_point_t press_at{0, 0};

void RoomTiles::guard_taps() {
  static bool done = false;
  if (done)
    return;
  done = true;
  for (lv_indev_t *in = lv_indev_get_next(nullptr); in != nullptr; in = lv_indev_get_next(in)) {
    if (lv_indev_get_type(in) != LV_INDEV_TYPE_POINTER)
      continue;
    // (the indev as user data: on an indev's own events the param is the object)
    lv_indev_add_event_cb(
        in, [](lv_event_t *e) { lv_indev_get_point(static_cast<lv_indev_t *>(lv_event_get_user_data(e)), &press_at); },
        LV_EVENT_PRESSED, in);
    auto check = [](lv_event_t *e) {
      auto *in = static_cast<lv_indev_t *>(lv_event_get_user_data(e));
      lv_point_t now;
      lv_indev_get_point(in, &now);
      const int dx = now.x - press_at.x, dy = now.y - press_at.y;
      if (dx * dx + dy * dy > TAP_SLOP_PX * TAP_SLOP_PX) {
        ESP_LOGD(TAG, "Not a tap: moved %d,%d", dx, dy);
        lv_indev_stop_processing(in);
      }
    };
    lv_indev_add_event_cb(in, check, LV_EVENT_SHORT_CLICKED, in);
    lv_indev_add_event_cb(in, check, LV_EVENT_CLICKED, in);
  }
}

void RoomTiles::choose_area(const std::string &area) {
  this->model_.area = area;
  this->board_.build(this->model_);
  this->pick_("area", area);
}

void RoomTiles::choose_layout(const std::string &layout) {
  this->model_.layout = layout;
  this->board_.build(this->model_);
  this->pick_("layout", layout);
}

void RoomTiles::pick_(const char *key, const std::string &value) {
  this->picked_[key] = value;
  this->send_picked_();
}

void RoomTiles::send_picked_() {
  if (this->picked_.empty())
    return;
  std::string json = "{";
  for (auto &kv : this->picked_) {
    if (json.size() > 1)
      json += ",";
    json += "\"" + kv.first + "\":" + (kv.second.empty() ? std::string("null") : "\"" + kv.second + "\"");
  }
  this->actions_.settings(json + "}");
  this->picked_sent_ms_ = millis();
}

// ---- the display ----------------------------------------------------------------------

void RoomTiles::set_backlight(light::LightState *light) {
  this->backlight_ = light;
  this->apply_backlight_();
  if (this->quiet_boot_) {
    this->quiet_boot_ = false;
    ESP_LOGI(TAG, "Updated while the screen was dark: back to dark");
    this->sleep_();
  }
}

void RoomTiles::backlight_switched(bool on) {
  // (the panel's own switching finds it already asleep / awake: nothing to do)
  if (!on && !this->asleep_)
    this->sleep_();
  else if (on && this->asleep_)
    this->wake_();
}

void RoomTiles::apply_backlight_() {
  if (this->backlight_ == nullptr)
    return;
  // asleep: off; else the setting (also while flash is written: the display
  // keeps its picture then - CONFIG_LCD_DSI_ISR_CACHE_SAFE) - the idle
  // brightness while the clock is up, a slider's value while it moves
  int pct = this->display_.brightness;
  if (this->preview_pct_ > 0)
    pct = this->preview_pct_;
  else if (this->dimmed_)
    pct = std::min<int>(pct, this->idle_bright_);
  const float level = this->asleep_ ? 0.0f : pct / 100.0f;
  auto call = level > 0 ? this->backlight_->turn_on() : this->backlight_->turn_off();
  if (level > 0)
    call.set_brightness(level);
  call.set_transition_length(0);
  call.perform();
}

void RoomTiles::set_brightness(int percent, bool save) {
  this->display_.brightness = (uint8_t) std::max(10, std::min(100, percent));  // (never fully dark from here)
  this->apply_backlight_();
  if (save)
    this->display_pref_.save(&this->display_);
}

void RoomTiles::set_idle_brightness(int percent, bool save) {
  const int pct = std::max(10, std::min<int>(this->display_.brightness, percent));
  if (!save && this->preview_pct_ == 0 && pct == this->idle_brightness())
    return;  // (its slider showing what's set, not moved)
  this->idle_bright_ = pct >= this->display_.brightness ? 100 : (uint8_t) pct;  // (at the brightness: follows it)
  this->preview_pct_ = save ? 0 : (uint8_t) pct;
  this->apply_backlight_();
  if (save)
    this->idle_bright_pref_.save(&this->idle_bright_);
}

void RoomTiles::set_sleep(int seconds, bool save) {
  this->display_.sleep_s = (uint8_t) std::max(0, std::min(255, seconds));
  if (save)
    this->display_pref_.save(&this->display_);
}

void RoomTiles::set_queue_autostart(bool on) {
  this->queue_autostart_ = on;
  const uint8_t v = on ? 1 : 0;
  this->queue_pref_.save(&v);
}

void RoomTiles::set_updating(bool on, bool wake) {
  this->updating_ = on;
  if (on && wake)
    this->wake_();
  this->apply_backlight_();
}

// Asleep: the backlight off and an opaque layer over everything - the next
// touch only wakes it (it never reaches a tile under it)
void RoomTiles::sleep_() {
  if (this->asleep_)
    return;
  this->asleep_ = true;
  App.set_loop_interval(LOOP_ASLEEP_MS);
  if (this->sleep_overlay_ == nullptr) {
    this->sleep_overlay_ = lv_obj_create(lv_layer_top());
    lv_obj_remove_style_all(this->sleep_overlay_);
    lv_obj_set_size(this->sleep_overlay_, LV_PCT(100), LV_PCT(100));
    lv_obj_set_style_bg_color(this->sleep_overlay_, lv_color_hex(0x000000), 0);
    lv_obj_set_style_bg_opa(this->sleep_overlay_, LV_OPA_COVER, 0);
    lv_obj_add_flag(this->sleep_overlay_, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(
        this->sleep_overlay_, [](lv_event_t *e) { static_cast<RoomTiles *>(lv_event_get_user_data(e))->wake_(); },
        LV_EVENT_PRESSED, this);
  }
  lv_obj_remove_flag(this->sleep_overlay_, LV_OBJ_FLAG_HIDDEN);
  lv_obj_move_foreground(this->sleep_overlay_);
  this->apply_backlight_();
}

void RoomTiles::wake_() {
  if (!this->asleep_)
    return;
  this->asleep_ = false;
  this->offline_slept_ = false;
  this->lights_slept_ = false;
  this->resume_at_ = 0;
  App.set_loop_interval(LOOP_AWAKE_MS);
  // (hidden after this touch is done with it: the release mustn't reach what's under it)
  lv_async_call([](void *p) {
    auto *self = static_cast<RoomTiles *>(p);
    if (!self->asleep_ && self->sleep_overlay_ != nullptr)
      lv_obj_add_flag(self->sleep_overlay_, LV_OBJ_FLAG_HIDDEN);
  }, this);
  this->apply_backlight_();
}

void RoomTiles::choose_language(const std::string &code) { this->pick_("language", code); }

void RoomTiles::choose_theme(const std::string &name) {
  this->pick_("theme", name);
  if (name == this->model_.theme)
    return;  // (this one already: nothing comes)
  // straight to the boot screen (loop() takes the board down - this runs in
  // the settings' own tap)
  this->theme_asked_ms_ = millis() | 1;
  this->say_("panel.theme_requesting", "Requesting the theme…");
}

void RoomTiles::take_screenshot(bool tell) {
  if (!this->screenshot_.take(tell) && tell)
    this->board_.screenshot_notice(false, "");
}

void RoomTiles::close_map() {
  if (this->map_view_.is_open())
    this->map_view_.close();
}

bool RoomTiles::hours12() const {
  if (this->clock24_ != 0)
    return this->clock24_ == 1;
  return this->t("clock.hours12") != "0";  // (the language's way; English's until there's wording)
}

int RoomTiles::strip_point(const std::string &area) const {
  const uint32_t h = fnv1_hash(area);
  for (int i = 0; i < STRIP_ROOMS; i++)
    if (this->strip_points_.room[i] == h && h != 0)
      return this->strip_points_.point[i];
  return 0;
}

void RoomTiles::set_strip_point(const std::string &area, int point) {
  if (area.empty())
    return;
  const uint32_t h = fnv1_hash(area);
  const uint8_t p = (uint8_t) std::clamp(point, 0, 255);
  int at = STRIP_ROOMS - 1;  // (not there: the oldest makes room)
  for (int i = 0; i < STRIP_ROOMS; i++) {
    if (this->strip_points_.room[i] == h) {
      if (i == 0 && this->strip_points_.point[0] == p)
        return;  // (no change: nothing written)
      at = i;
      break;
    }
  }
  // this room first (the most recent), the others moved down
  for (int i = at; i > 0; i--) {
    this->strip_points_.room[i] = this->strip_points_.room[i - 1];
    this->strip_points_.point[i] = this->strip_points_.point[i - 1];
  }
  this->strip_points_.room[0] = h;
  this->strip_points_.point[0] = p;
  this->strip_points_pref_.save(&this->strip_points_);  // (written to flash with the next batch)
}

void RoomTiles::set_hours24(bool on) {
  this->clock24_ = on ? 2 : 1;
  this->clock24_pref_.save(&this->clock24_);
  this->clock_.hide();         // (shown again the new way when idle)
  this->board_.paint_clock();  // (the top bar's, now)
}

void RoomTiles::set_idle(int mode, bool anim_keep, bool seconds, bool save) {
  this->idle_.mode = (uint8_t) std::max(0, std::min(3, mode));
  this->idle_.anim_keep = anim_keep ? 1 : 0;
  this->idle_.seconds = seconds ? 1 : 0;
  this->clock_.hide();  // (shown again in the new way when idle)
  if (this->idle_.mode == IDLE_OFF)
    this->clock_.hide();
  if (save)
    this->idle_pref_.save(&this->idle_);
}

void RoomTiles::set_idle_lights_off(bool on) {
  this->idle_lights_ = on ? 1 : 0;
  this->idle_lights_pref_.save(&this->idle_lights_);
}

bool RoomTiles::room_dark_() {
  // the room the panel is in (its HA device's area), whatever area it shows
  const std::vector<std::string> &lights = this->model_.room_lights;
  if (lights.empty())
    return false;  // (no room in HA, or no lights button there: the clock as usual)
  std::string key;
  for (const std::string &l : lights)
    key += l + ",";
  if (this->lights_watched_ != key) {
    for (const std::string &l : lights)
      this->states_.watch(l);
    this->lights_watched_ = key;
  }
  bool off = false;
  for (const std::string &l : lights) {
    const std::string &s = this->states_.get(l);
    if (s == "on")
      return false;
    off = off || s == "off";
  }
  return off;  // (none known yet, or all unavailable: not "off")
}

// After the sleep time untouched: the screen off, or the clock (the
// setting) at the idle brightness. A tile in view animating ("Animations
// keep tiles visible") keeps the board up instead - dimmed to the idle
// brightness. "Screen off when the following area lights are off": while the lights of the
// room the panel is in (its HA device's area, not the area shown) are all
// off, the screen off instead of either; they come on while it's off (still
// untouched): the clock (or the kept board) again. The clock goes when the
// panel is used again (its own touch: on its release - idle_clock.cpp).
void RoomTiles::idle_loop_() {
  const uint32_t inactive = lv_display_get_inactive_time(nullptr);
  // back from HA's absence (offline_slept_): idle as before it, until touched
  bool resumed = false;
  if (this->resume_at_ != 0) {
    const uint32_t since = millis() - this->resume_at_;
    if (inactive + 1000 < since || inactive > this->display_.sleep_s * 1000u)
      this->resume_at_ = 0;  // (touched since, or idle anyway now)
    else if (this->asleep_ && since > RESUME_WINDOW_MS)
      this->resume_at_ = 0;  // (nothing to show: it stays dark)
    else
      resumed = true;
  }
  const bool idle = this->display_.sleep_s > 0 && !this->updating_ && (resumed || inactive > this->display_.sleep_s * 1000u);
  const bool dark = this->idle_lights_ && this->main_shown_ && idle && this->room_dark_();
  const bool keep = !dark && this->idle_.anim_keep && this->main_shown_ && this->board_.visible_animating();
  if (this->lights_slept_ && this->asleep_ && !dark && idle && (keep || this->idle_.mode != IDLE_OFF)) {
    ESP_LOGI(TAG, "The room's lights came on: %s", keep ? "an animation keeps the board up" : "the idle clock");
    this->dim_(true);  // (straight to the idle brightness)
    this->wake_();
  }
  if (resumed && this->asleep_ && this->main_shown_ && idle && !dark && (keep || this->idle_.mode != IDLE_OFF)) {
    ESP_LOGI(TAG, "Home Assistant back: %s", keep ? "an animation keeps the board up" : "the idle clock");
    const uint32_t at = this->resume_at_;
    this->dim_(true);  // (straight to the idle brightness: never the full one)
    this->wake_();
    this->resume_at_ = at;  // (wake_ ends it for a touch: not this one)
  }
  if (this->idle_.mode == IDLE_OFF || dark || !this->main_shown_) {
    this->clock_.hide();
    // HA gone while idle on the clock (not dark by choice): "Connecting to
    // Home Assistant…" at the idle brightness for OFFLINE_DARK_MS - an HA
    // restart passes lit - then dark: if HA stays away, say overnight, a
    // dark screen keeps nobody awake
    const bool waiting = !this->main_shown_ && this->offline_ && this->idle_.mode != IDLE_OFF && !this->asleep_ &&
                         this->offline_since_ != 0 && millis() - this->offline_since_ < OFFLINE_DARK_MS;
    // an animation keeps the board up, dimmed; else the screen goes dark
    // (also on the boot screen while HA is gone, once that's past)
    this->dim_(idle && (keep || waiting));
    if (idle && !keep && !waiting && (this->main_shown_ || this->offline_) && !this->asleep_) {
      this->sleep_();
      this->offline_slept_ = !this->main_shown_;  // (HA's absence did it: undone when it's back)
      this->lights_slept_ = dark;                 // (the lights did it: undone when they come on)
    }
    return;
  }
  if (idle && !keep && !this->clock_.shown() && !this->asleep_) {
    // (never while dark: the first touch must reach the sleep overlay - wake)
    const bool round = this->strip_;
    // the theme's clock: the analog one in a theme without (the setting stays)
    int face = this->idle_.mode;
    if (face == IDLE_THEME && this->theme_clock().empty())
      face = IDLE_ANALOG;
    this->clock_.show(this, this->board_.fonts(), face, this->idle_.seconds != 0, round ? 480 : 1024, round ? 480 : 600);
  } else if (this->clock_.shown() && !this->clock_.pressed() && (keep || !idle)) {
    this->clock_.hide();  // (an animation in view, or the knob turned)
  }
  this->clock_.tick();
  // the idle brightness: the clock up (until its own touch takes it down), or
  // the board an animation keeps, past the sleep time
  this->dim_(this->clock_.shown() || (idle && keep));
}

void RoomTiles::dim_(bool on) {
  if (on == this->dimmed_)
    return;
  this->dimmed_ = on;
  this->preview_pct_ = 0;  // (a slider left mid-move)
  this->apply_backlight_();
}

// The topmost thing that scrolls up and down under `obj` (a page's list, a
// dialog's column, the language list) - nullptr when nothing does.
static lv_obj_t *vertical_scroller(lv_obj_t *obj) {
  if (obj == nullptr || lv_obj_has_flag(obj, LV_OBJ_FLAG_HIDDEN))
    return nullptr;
  for (int i = (int) lv_obj_get_child_count(obj) - 1; i >= 0; i--)  // (the last child is on top)
    if (lv_obj_t *s = vertical_scroller(lv_obj_get_child(obj, i)))
      return s;
  if (lv_obj_has_flag(obj, LV_OBJ_FLAG_SCROLLABLE) && (lv_obj_get_scroll_dir(obj) & LV_DIR_VER) &&
      lv_obj_get_scroll_top(obj) + lv_obj_get_scroll_bottom(obj) > 0)
    return obj;
  return nullptr;
}

void RoomTiles::knob_turn(int clicks) {
  lv_display_trigger_activity(nullptr);  // (the screen's idle time)
  if (this->asleep_) {
    this->wake_();
    return;
  }
  const uint32_t now = millis();
  const int dir = clicks > 0 ? 1 : -1;
  const bool again = now - this->knob_ms_ < KNOB_AGAIN_MS;  // (its scroll may still run)
  if (dir == this->knob_dir_)
    clicks *= knob_steps(now - this->knob_ms_);
  this->knob_dir_ = dir;
  this->knob_ms_ = now;
  // wherever touch can scroll, the knob scrolls too: a page or dialog on
  // top (its list), else the strip, else a list on the screen (the
  // language picker); clockwise = down the list
  lv_obj_t *list = vertical_scroller(lv_layer_top());
  if (list == nullptr && this->board_.knob_turn(clicks, again))
    return;
  if (list == nullptr)
    list = vertical_scroller(lv_screen_active());
  if (list == nullptr)
    return;
  // (a click while the last one still scrolls: on from where that one goes)
  const int32_t y = lv_obj_get_scroll_y(list);
  const int32_t from = again && list == this->knob_list_ && lv_anim_get(list, nullptr) != nullptr ? this->knob_y_ : y;
  this->knob_y_ = std::clamp<int32_t>(from + clicks * KNOB_SCROLL_PX, y - lv_obj_get_scroll_top(list),
                                      y + lv_obj_get_scroll_bottom(list));
  this->knob_list_ = list;
  lv_obj_scroll_to_y(list, this->knob_y_, LV_ANIM_ON);
}

void RoomTiles::knob_press() {
  lv_display_trigger_activity(nullptr);
  if (this->asleep_) {
    this->wake_();
    return;
  }
  this->board_.knob_press();
}

void RoomTiles::open_queue(const std::string &entity) {
  if (!this->map_)
    return;  // (no vacuum view on this panel)
  if (const RobotSpec *r = this->model_.robot_for(entity))
    this->map_view_.open_queue(this->model_, *r);
}

void RoomTiles::open_map(const std::string &map_id) {
  if (!this->map_)
    return;
  const AreaSpec *area = this->model_.current();
  this->map_view_.open(this->model_, map_id, area ? area->floor : "");
}

void RoomTiles::show_screen_(bool main) {
  if (main == this->main_shown_)
    return;
  this->main_shown_ = main;
  // the board appearing counts as use: the idle time (the screen off / the
  // clock) starts now, not at the last touch - after a boot there's none
  if (main)
    lv_display_trigger_activity(nullptr);
  // dark only because HA was gone: idle again as before (idle_loop_)
  if (main && this->offline_slept_ && this->asleep_) {
    this->offline_slept_ = false;
    this->resume_at_ = millis() | 1;
  }
  for (auto *t : this->screen_triggers_)
    t->trigger(main);
}

// The board shows once there is a payload and the packs it asked for are
// stored (or a pack can't be had: then plain, without art).
void RoomTiles::maybe_show_board_() {
  if (!this->have_model_ || !this->board_.attached())
    return;
  const bool packs_pending = (!this->want_strings_.empty() && this->want_strings_ != this->assets_.pack_id(PACK_STRINGS)) ||
                             (!this->want_theme_.empty() && this->want_theme_ != this->assets_.pack_id(PACK_THEME));
  if (packs_pending && !this->main_shown_ && this->retry_at_ == 0)
    return;  // it's coming: keep the boot screen up meanwhile
  if (this->theme_asked_ms_ != 0 || this->mismatched_ || this->offline_)
    return;  // (one picked here: its payload is on the way / an update needed first / HA gone)
  // a firmware update or a theme pack on its way: its boot screen and progress
  // bar stay up until it's done - nothing may draw from the old pack while
  // it's rewritten (loop's "the maps' pictures made" check would otherwise
  // put the board straight back, and the idle clock come and go over it)
  if (this->job_ == JOB_FIRMWARE || this->job_ == JOB_THEME || this->hold_boot_screen_)
    return;  // (and a factory reset / the Wi-Fi chip's update the same way)
  if (!this->main_shown_) {
    // the maps' pictures made while the boot screen is up (a few a loop: its
    // stopwatch keeps going), so a map opens without making them - at most 5 s
    if (this->boot_pictures_at_ == 0) {
      this->boot_pictures_at_ = millis();
      this->map_view_.queue_pictures(this->model_);
    }
    if (this->map_view_.pictures_pending() && millis() - this->boot_pictures_at_ < 5000)
      return;  // (loop shows the board once they're made)
  }
  this->board_.build(this->model_);
  this->map_view_.model_changed(this->model_);
  this->board_.preload(this->model_);  // (the other areas' states, ahead - within a budget)
  ESP_LOGD(TAG, "Subscribed: %u values", (unsigned) this->states_.count());
  this->show_screen_(true);
  // no area for this panel yet (none picked, its device has none): it asks,
  // once a start
  if (!this->model_.area_set && !this->area_asked_ && !this->model_.areas.empty()) {
    this->area_asked_ = true;
    this->board_.ask_area();
  }
}

void RoomTiles::dump_config() {
  ESP_LOGCONFIG(TAG, "Room Tiles panel:");
  ESP_LOGCONFIG(TAG, "  Asset area: %" PRIu32 " KB", this->assets_.area_size() / 1024);
  ESP_LOGCONFIG(TAG, "  Theme pack: %s", this->assets_.pack_id(PACK_THEME).empty() ? "(none)" : this->assets_.pack_id(PACK_THEME).c_str());
  ESP_LOGCONFIG(TAG, "  Wording: %s", this->assets_.pack_id(PACK_STRINGS).empty() ? "(none)" : this->assets_.pack_id(PACK_STRINGS).c_str());
  const esp_partition_t *app = esp_ota_get_running_partition();
  if (app != nullptr)
    ESP_LOGCONFIG(TAG, "  Running from: %s (%" PRIu32 " KB slot)", app->label, (uint32_t) (app->size / 1024));
  ESP_LOGCONFIG(TAG, "  Image: %s build %s", this->image_tag_, this->build_.c_str());
}

void RoomTiles::set_revision(const std::string &revision) {
  if (revision.empty() || revision == "unknown" || revision == "unavailable")
    return;
  this->revision_ = revision;
  this->retry_at_ = 0;  // something changed: try now
}

void RoomTiles::set_base_url(const std::string &url) {
  std::string u = url;
  while (!u.empty() && u.back() == '/')
    u.pop_back();
  if (u.empty() || u == "None" || u == "unknown" || u == "unavailable")
    return;
  if (u != this->base_url_) {
    this->base_url_ = u;
    this->retry_at_ = 0;
  }
  this->actions_.set_base_url(this->base_url_);
  this->screenshot_.set_base_url(this->base_url_);
}

void RoomTiles::mismatch_(int theirs) {
  this->mismatched_ = true;
  this->take_board_down_();
  if (theirs > PANEL_SCHEMA)
    this->say_("panel.needs_firmware", "Update this panel's firmware – Room Tiles in Home Assistant is newer");
  else
    this->say_("panel.needs_integration", "Update Room Tiles in Home Assistant – this panel's firmware is newer");
}

// HA gone a while: the boot screen says so (an old "on" on the board is worse
// than none); back on the board once it's connected again. Only once the
// panel has had its data (before that the boot screen's own status says
// more - "add this panel", downloads), never mid-download / save.
void RoomTiles::watch_connection_() {
  auto *api = api::global_api_server;
  const bool up = api != nullptr && api->is_connected_with_state_subscription();  // (HA; not a log viewer)
  if (up) {
    this->offline_since_ = 0;
    if (this->offline_) {
      this->offline_ = false;
      ESP_LOGI(TAG, "Home Assistant is back");
      this->show_summary_();
      this->maybe_show_board_();
    }
    return;
  }
  const uint32_t now = millis();
  if (this->offline_since_ == 0) {
    this->offline_since_ = now | 1;
    return;
  }
  if (this->offline_ || !this->have_model_ || this->job_ != JOB_NONE || now - this->offline_since_ < OFFLINE_AFTER_MS)
    return;
  this->offline_ = true;
  ESP_LOGW(TAG, "No Home Assistant for %" PRIu32 " s: the boot screen until it's back", (now - this->offline_since_) / 1000);
  this->take_board_down_();
  this->say_("panel.connecting", "Connecting to Home Assistant…");
}

// No Wi-Fi network yet (a generic image, fresh): the panel's own hotspot is
// up - the boot screen says which network to join (its page takes the
// network and password; Improv over USB does too).
void RoomTiles::watch_wifi_setup_() {
#ifdef USE_WIFI
  auto *w = wifi::global_wifi_component;
  // (never set up, or its network gone - a new router, a new password: after
  // a while without it the hotspot opens again, and the panel says so)
  const bool setup = w != nullptr && w->is_ap_active() && !w->is_connected();
  // a new panel (the 7" / 10.1"): its networks to pick, on the screen,
  // once its language is picked; gone again once it's on one (or the phone did it)
  // (the board's fonts hooked up - its loop runs before the boot's last
  // steps do - and the language picked)
  // A panel that has a network saved isn't new - it's reconnecting (after
  // a restart, an update) or its network is gone: its hotspot and the
  // phone line as before, never this screen opening by itself
  const bool picker_up = setup && !w->has_sta() && !this->strip_ && this->generic_ && this->board_.fonts().bar != nullptr &&
                         this->lang_root_ != nullptr && !this->language_needed();
  if (picker_up && !this->wifi_setup_.is_open())
    this->wifi_setup_.open(false);
  else if (!setup && this->wifi_setup_.is_open() && !this->wifi_setup_.changing() && !this->wifi_setup_.trying())
    this->wifi_setup_.close();
  if (setup == this->wifi_setup_mode_)
    return;
  this->wifi_setup_mode_ = setup;
  if (!setup) {
    this->say_("panel.connecting", "Connecting to Home Assistant…");
    return;
  }
  const std::string ssid = this->hotspot_name();
  ESP_LOGI(TAG, "No Wi-Fi network: hotspot %s", ssid.c_str());
  this->say_("panel.wifi_setup", "Set up Wi-Fi: with your phone, join the network \"{name}\"", ssid);
#endif
}

// No API key yet (a generic panel HA hasn't added): the boot screen says to
// add it - its name as HA's Discovered list shows it, and where. HA sets the
// key when it adds the panel; then on as usual. (Only on Wi-Fi: without it
// the Wi-Fi setup line comes first.)
void RoomTiles::watch_adding_() {
  const uint32_t now = millis();
  if (now - this->adding_checked_ms_ < 1000)
    return;
  this->adding_checked_ms_ = now;
#ifdef USE_WIFI
  auto *w = wifi::global_wifi_component;
  const bool online = w != nullptr && w->is_connected();
#else
  const bool online = true;
#endif
  this->set_adding_(this->generic_ && online && !has_api_key());
}

void RoomTiles::set_adding_(bool on) {
  if (on == this->adding_)
    return;
  this->adding_ = on;
  if (on) {
    ESP_LOGI(TAG, "No API key yet: waiting to be added in Home Assistant (%s)", App.get_friendly_name().str().c_str());
    this->say_("panel.add_title", "Add this panel in Home Assistant");
  } else {
    this->say_("panel.connecting", "Connecting to Home Assistant…");
  }
}

std::string RoomTiles::setup_name() const {
  return this->adding_ ? App.get_friendly_name().str() : std::string();
}

std::string RoomTiles::setup_hint() const {
  return this->adding_ ? this->boot_text_("panel.add_where", "Settings › Devices & services › Discovered") : std::string();
}

// A new panel's first start: its language before anything else, each
// language in its own name. The wall panels: under the boot screen's logo and
// name (the picker covers the lower part - the status lines), 4 + 3 across.
// The round panel: the languages alone, two by two inside the circle.
bool RoomTiles::language_needed() const {
  return this->generic_ && this->boot_lang_.code[0] == 0 && this->assets_.pack_id(PACK_STRINGS).empty();
}

void RoomTiles::attach_language_picker(lv_obj_t *root) {
  this->lang_root_ = root;
  const Fonts &f = this->board_.fonts();
  const bool round = this->strip_;
  const int cols = round ? 2 : 4;
  const int bw = round ? 170 : 220, bh = round ? 52 : 60, gap = round ? 10 : 12;
  const int rows = (BOOT_LANG_COUNT + cols - 1) / cols;
  const int grid_h = rows * bh + (rows - 1) * gap;
  // (the screen's height: at boot the page's own isn't laid out yet)
  const int screen_h = lv_display_get_vertical_resolution(lv_display_get_default());
  int top;  // (the first row's top, in the container)
  if (round) {
    top = (screen_h - grid_h) / 2;  // (the whole screen, centered)
  } else {
    // the lower part, from just under the name ("Room Tiles", y 50 from the center)
    const int h = screen_h / 2 - 80;
    lv_obj_set_size(root, LV_PCT(100), h);
    lv_obj_align(root, LV_ALIGN_BOTTOM_MID, 0, 0);
    top = 20;
  }
  for (int i = 0; i < BOOT_LANG_COUNT; i++) {
    lv_obj_t *b = lv_button_create(root);
    lv_obj_remove_style_all(b);
    lv_obj_set_size(b, bw, bh);
    lv_obj_set_style_radius(b, 12, 0);
    lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(b, lv_color_hex(0x333333), 0);
    lv_obj_set_style_bg_color(b, lv_color_hex(0x4B9EF3), LV_STATE_PRESSED);
    // each row centered (a shorter last row too)
    const int row = i / cols, col = i % cols;
    const int in_row = std::min(cols, BOOT_LANG_COUNT - row * cols);
    const int x = col * (bw + gap) - (in_row * bw + (in_row - 1) * gap) / 2 + bw / 2;
    lv_obj_align(b, LV_ALIGN_TOP_MID, x, top + row * (bh + gap));
    lv_obj_set_user_data(b, (void *) (intptr_t) i);
    lv_obj_add_event_cb(
        b,
        [](lv_event_t *e) {
          auto *self = static_cast<RoomTiles *>(lv_event_get_user_data(e));
          auto *btn = static_cast<lv_obj_t *>(lv_event_get_current_target(e));
          self->pick_language_((int) (intptr_t) lv_obj_get_user_data(btn));
        },
        LV_EVENT_CLICKED, this);
    lv_obj_t *l = lv_label_create(b);
    lv_label_set_text(l, BOOT_LANG_NAMES[i]);
    lv_obj_set_style_text_font(l, f.bar, 0);
    lv_obj_set_style_text_color(l, lv_color_hex(0xFFFFFF), 0);
    lv_obj_center(l);
  }
  this->show_language_picker_();
}

void RoomTiles::show_language_picker_() {
  if (this->lang_root_ == nullptr)
    return;
  if (this->language_needed())
    lv_obj_remove_flag(this->lang_root_, LV_OBJ_FLAG_HIDDEN);
  else
    lv_obj_add_flag(this->lang_root_, LV_OBJ_FLAG_HIDDEN);
}

void RoomTiles::pick_language_(int index) {
  if (index < 0 || index >= BOOT_LANG_COUNT)
    return;
  std::snprintf(this->boot_lang_.code, sizeof(this->boot_lang_.code), "%s", BOOT_LANGS[index]);
  this->boot_lang_.sent = 0;
  this->boot_lang_pref_.save(&this->boot_lang_);
  ESP_LOGI(TAG, "Language picked: %s", this->boot_lang_.code);
  this->show_language_picker_();
  // the boot screen in it now
  if (this->status_key_ != nullptr) {
    const std::string name = this->status_name_;
    this->say_(this->status_key_, this->status_fallback_, name);
  }
  for (auto *t : this->status_triggers_)
    t->trigger();  // (the add screen's lines, Change Wi-Fi)
}

// The network set on the hotspot is ESPHome's own record (wifi_component.cpp
// start()): NVS namespace "esphome", key 88491487 when the firmware names no
// network (a generic panel), its fast-connect record the next key. Erased, the
// panel restarts with no network: the hotspot opens at once. (HA's key and the
// panel's other settings are other records: kept.) Check on ESPHome updates.
void RoomTiles::forget_wifi() {
  if (!this->generic_)
    return;  // (a hand-built panel's networks are in its firmware)
  global_preferences->sync();  // (anything pending written first: not after)
  nvs_handle_t h;
  if (nvs_open("esphome", NVS_READWRITE, &h) == ESP_OK) {
    for (const char *key : {"88491487", "88491488"})
      nvs_erase_key(h, key);
    nvs_commit(h);
    nvs_close(h);
  }
  ESP_LOGI(TAG, "Wi-Fi network forgotten: restarting into the hotspot");
  App.safe_reboot();
}

#ifdef USE_UPDATE
#if __has_include(<esp_hosted_host_fw_ver.h>)
#include <esp_hosted_host_fw_ver.h>  // (the ESP-Hosted library this firmware is built with)
#endif
// "2.12.13" -> {2, 12, 13}; false when it isn't a version
static bool chip_version(const std::string &s, int (&v)[3]) {
  v[0] = v[1] = v[2] = 0;
  const char *p = s.c_str();
  for (int i = 0; i < 3; i++) {
    if (*p < '0' || *p > '9')
      return i >= 2;  // (major.minor at least)
    char *end = nullptr;
    v[i] = (int) strtol(p, &end, 10);
    p = end;
    if (*p == '.')
      p++;
  }
  return true;
}

static int chip_compare(const int (&a)[3], const int (&b)[3]) {
  for (int i = 0; i < 3; i++)
    if (a[i] != b[i])
      return a[i] < b[i] ? -1 : 1;
  return 0;
}

// The Wi-Fi chip (an ESP32-C6 with ESP-Hosted) runs other firmware than the
// image this build carries: an OLDER chip is brought up to it, once per
// carried version - before Wi-Fi, so a board straight from the box gets there
// too. Never a newer chip (no downgrade), never twice for the same image (a
// failed try isn't repeated in a loop). The boot screen says so meanwhile;
// ESPHome restarts the panel when it's done. A chip older than 2.6 (the
// maker's first firmware, 2.3.0) takes the image but doesn't know the last
// step, "activate" (ESPHome then reports a failure): it switches over by
// itself ~20 s later, and the panel restarts after that - Espressif's own
// example does the same for old chips (seen on a V1.0, 2026-10-12).
void RoomTiles::wifi_chip_update_available(update::UpdateEntity *chip) {
  const std::string have = chip->update_info.current_version, carried = chip->update_info.latest_version;
  int h[3], c[3];
  if (!chip_version(have, h) || !chip_version(carried, c)) {
    ESP_LOGW(TAG, "Wi-Fi chip: version '%s' not known - left alone", have.c_str());
    return;
  }
  if (chip_compare(h, c) >= 0) {
    ESP_LOGI(TAG, "Wi-Fi chip %s: not older than this image's %s - left alone", have.c_str(), carried.c_str());
    return;
  }
#ifdef ESP_HOSTED_VERSION_MAJOR_1
  // only the image that matches the ESP-Hosted library this firmware was
  // built with (a panel built by hand with another ESPHome: its chip is left
  // alone - firmware/wifi_chip/README.md)
  static const int LIBRARY[3] = {ESP_HOSTED_VERSION_MAJOR_1, ESP_HOSTED_VERSION_MINOR_1, ESP_HOSTED_VERSION_PATCH_1};
  if (chip_compare(c, LIBRARY) != 0) {
    ESP_LOGW(TAG, "Wi-Fi chip: the carried image %s doesn't match this firmware's ESP-Hosted %d.%d.%d - left alone",
             carried.c_str(), LIBRARY[0], LIBRARY[1], LIBRARY[2]);
    return;
  }
#endif
  const uint32_t tag = fnv1_hash(carried);
  if (this->wifi_chip_tried_ == tag) {
    ESP_LOGW(TAG, "Wi-Fi chip %s: updating it to %s was tried before - not again", have.c_str(), carried.c_str());
    return;
  }
  // after the language is picked (a new panel asks for it first: the message
  // in its words, and before Wi-Fi is set up - loop starts it); at once on a
  // panel that has its language
  this->wifi_chip_waiting_ = chip;
  ESP_LOGI(TAG, "Wi-Fi chip %s -> %s: due%s", have.c_str(), carried.c_str(),
           this->language_needed() ? " once the language is picked" : "");
}

void RoomTiles::wifi_chip_update_() {
  update::UpdateEntity *chip = this->wifi_chip_waiting_;
  this->wifi_chip_waiting_ = nullptr;
  const std::string have = chip->update_info.current_version, carried = chip->update_info.latest_version;
  int h[3];
  static const int ACTIVATES[3] = {2, 6, 0};  // (the "activate" step: from 2.6)
  chip_version(have, h);
  this->wifi_chip_tried_ = fnv1_hash(carried);
  this->wifi_chip_pref_.save(&this->wifi_chip_tried_);
  global_preferences->sync();  // (written before the update: never a second try)
  const bool old_chip = chip_compare(h, ACTIVATES) < 0;
  ESP_LOGW(TAG, "Wi-Fi chip %s -> %s: updating", have.c_str(), carried.c_str());
  this->hold_boot_screen_ = true;
  this->take_board_down_();
  this->say_("panel.wifi_chip_updating", "Updating the Wi-Fi chip…");
  this->set_updating(true);  // (the screen on meanwhile)
  // (a moment for the boot screen to show it; then the write - it blocks,
  // about a minute)
  this->set_timeout("wifi_chip", 800, [this, chip, old_chip]() {
    chip->perform(false);
    if (chip->state == update::UPDATE_STATE_NO_UPDATE)
      return;  // (done: ESPHome restarts the panel in a moment)
    if (old_chip) {
      // (written; it switches over by itself - then a fresh start links to it)
      ESP_LOGW(TAG, "Wi-Fi chip older than 2.6: no \"activate\" - it switches over by itself; restarting in 25 s");
      this->set_timeout("wifi_chip_restart", 25000, []() { App.safe_reboot(); });
      return;
    }
    ESP_LOGE(TAG, "Wi-Fi chip update failed - the panel goes on with the chip as it was");
    this->hold_boot_screen_ = false;
    this->set_updating(false);
    this->show_summary_();
    this->maybe_show_board_();
  });
}
#endif

// Factory reset (its HA button, disabled until enabled there): back to new.
// Room Tiles forgets this panel's settings first (area, layout, theme,
// language: the defaults again - while it can still be told), then the
// downloaded theme and wording go, then everything kept on the panel (all of
// NVS: the Wi-Fi network, the encryption key HA set, its language,
// brightness, idle settings...). It starts like a new one: the hotspot, the
// language, "Add this panel in Home Assistant", the area.
void RoomTiles::factory_reset() {
  ESP_LOGW(TAG, "Factory reset: back to new");
  this->picked_.clear();
  this->actions_.settings("{\"area\":null,\"layout\":null,\"theme\":null,\"language\":null}");
  this->hold_boot_screen_ = true;  // (no tiles back meanwhile - Room Tiles answers)
  this->take_board_down_();       // (nothing may draw from the packs being erased)
  this->say_("panel.factory_reset", "Resetting to new…");
  // (a moment for Room Tiles to hear it, then the rest - in one go, no
  // drawing in between)
  this->set_timeout("factory_reset", 1500, [this]() {
    this->assets_.forget(PACK_THEME);
    this->assets_.forget(PACK_STRINGS);
    global_preferences->reset();  // (and nothing is saved after this, before the restart)
    App.safe_reboot();
  });
}

// The boot screen's Change Wi-Fi: a generic panel on Wi-Fi that hasn't
// reached Home Assistant for a while (a hand-built one's networks are in its
// firmware; no Wi-Fi at all: the hotspot asks by itself)
void RoomTiles::watch_wifi_button_() {
#ifdef USE_WIFI
  auto *w = wifi::global_wifi_component;
  auto *api = api::global_api_server;
  const uint32_t now = millis();
  // (the round panel: no room under the add screen's lines - not then)
  const bool lost = this->generic_ && !this->main_shown_ && !(this->strip_ && this->adding_) && w != nullptr && w->is_connected() &&
                    !(api != nullptr && api->is_connected_with_state_subscription()) && this->offline_since_ != 0 &&
                    now - this->offline_since_ >= WIFI_BUTTON_AFTER_MS;
  if (this->wifi_armed_ms_ != 0 && now - this->wifi_armed_ms_ > WIFI_ARMED_MS)
    this->wifi_armed_ms_ = 0;
  const int b = !lost ? 0 : this->wifi_armed_ms_ != 0 ? 2 : 1;
  if (b == this->wifi_button_)
    return;
  this->wifi_button_ = b;
  if (b == 0)
    this->wifi_armed_ms_ = 0;
  for (auto *t : this->status_triggers_)
    t->trigger();
#endif
}

std::string RoomTiles::wifi_button_text() const {
  return this->wifi_button_ == 2 ? this->boot_text_("panel.wifi_change_again", "Tap again to confirm")
                                 : this->boot_text_("panel.wifi_change", "Change Wi-Fi");
}

void RoomTiles::wifi_button_tap() {
  if (this->wifi_button_ == 0)
    return;
  if (!this->strip_) {  // (the networks, picked here - the round panel: tapped twice, then its hotspot)
    this->open_wifi_setup();
    return;
  }
  if (this->wifi_button_ == 2) {
    this->forget_wifi();
    return;
  }
  this->wifi_armed_ms_ = millis() | 1;
  this->watch_wifi_button_();
}

std::string RoomTiles::hotspot_name() const {
  std::string ssid;
#ifdef USE_WIFI
  if (wifi::global_wifi_component != nullptr)
    ssid = wifi::global_wifi_component->get_ap().get_ssid().str();  // (empty: .str(), never c_str())
#endif
  return ssid.empty() ? App.get_name().str() : ssid;  // (the hotspot is named like the panel)
}

void RoomTiles::open_wifi_setup() {
  if (this->strip_ || !this->generic_) {
    this->forget_wifi();  // (the round panel - asked on its page first; a hand-built one: nothing)
    return;
  }
  if (!this->wifi_setup_.is_open())
    this->wifi_setup_.open(true);
}

void RoomTiles::take_board_down_() {
  this->show_screen_(false);
  this->picker_.close();
  this->map_view_.close();
  this->board_.clear();
}

std::string RoomTiles::boot_text_(const char *key, const char *fallback) const {
  std::string s = this->assets_.t(key);
  if (s != key)
    return s;
  const char *built_in = boot_word(this->boot_language_(), key);
  return built_in != nullptr ? std::string(built_in) : std::string(fallback);
}

// The boot screen's language before the panel has its wording: HA's choice
// once a payload came, else the one picked on its first start, else English.
const char *RoomTiles::boot_language_() const {
  if (this->have_model_ && !this->model_.language.empty() && !this->boot_lang_pending_)
    return this->model_.language.c_str();
  return this->boot_lang_.code[0] != 0 ? this->boot_lang_.code : "en";
}

void RoomTiles::say_(const char *key, const char *fallback, const std::string &name) {
  this->status_key_ = key;
  this->status_fallback_ = fallback;
  this->status_name_ = name;
  std::string s = this->boot_text_(key, fallback);
  const size_t at = s.find("{name}");
  if (at != std::string::npos)
    s.replace(at, 6, name);
  this->set_status_(s);
}

void RoomTiles::set_status_(const std::string &status) {
  if (status == this->status_)
    return;
  this->status_ = status;
  ESP_LOGI(TAG, "%s", status.c_str());
  for (auto *t : this->status_triggers_)
    t->trigger();
}

// "Living Room · 18 rooms" - in the panel's language once its wording is stored
void RoomTiles::show_summary_() {
  std::string rooms = this->assets_.t("editor.count_zone.other");
  if (rooms == "editor.count_zone.other")
    rooms = "{n} rooms";
  const size_t at = rooms.find("{n}");
  if (at != std::string::npos)
    rooms.replace(at, 3, std::to_string(this->area_count_));
  this->status_key_ = nullptr;
  this->set_status_((this->area_name_.empty() ? std::string("-") : this->area_name_) + " · " + rooms);
}

void RoomTiles::assets_changed_() {
  // a re-saved pack reuses the same image descriptors: forget anything LVGL
  // cached from the old one
  lv_image_cache_drop(nullptr);
  this->states_.relocalize();  // (new wording: the status words again)
  this->map_view_.theme_changed();
  this->show_language_picker_();  // (wording stored: no picker)
  for (auto *t : this->assets_triggers_)
    t->trigger();
}

void RoomTiles::loop() {
  if (!this->picked_.empty() && millis() - this->picked_sent_ms_ > PICK_RESEND_MS)
    this->send_picked_();  // (HA hasn't got them yet: picked_)
#ifdef USE_UPDATE
  if (this->wifi_chip_waiting_ != nullptr && !this->language_needed() && this->job_ == JOB_NONE)
    this->wifi_chip_update_();  // (the Wi-Fi chip, once the language is picked)
#endif
  this->watch_wifi_setup_();
  this->watch_adding_();
  this->watch_connection_();
  this->watch_wifi_button_();
  if (this->theme_asked_ms_ != 0) {
    // a theme picked here: the boot screen now; if no download starts
    // (HA didn't take it), the board again after a while
    if (this->main_shown_)
      this->take_board_down_();
    else if (millis() - this->theme_asked_ms_ > THEME_WAIT_MS) {
      this->theme_asked_ms_ = 0;
      this->show_summary_();
    }
  }
  if (!this->main_shown_ && this->boot_pictures_at_ != 0 &&
      (!this->map_view_.pictures_pending() || millis() - this->boot_pictures_at_ >= 5000))
    this->maybe_show_board_();  // (the maps' pictures made: the board)
  if (this->oom_report_ && millis() > 30000) {  // (again, for the network log)
    this->oom_report_ = false;
    ESP_LOGE(TAG, "The last restart: out of memory - %u bytes (caps 0x%x) in %s; internal RAM free %u, largest block %u",
             (unsigned) oom_note.size, (unsigned) oom_note.caps, oom_note.fn, (unsigned) oom_note.free_internal,
             (unsigned) oom_note.largest_internal);
  }
  this->states_.loop();
  {
    std::string file;
    if (const int r = this->screenshot_.result(file))  // (one taken from the settings)
      this->board_.screenshot_notice(r == 1, file);
  }
  // the screen goes off after the panel's sleep time untouched (the main screen only)
  this->idle_loop_();
  this->board_.loop();
  this->map_view_.loop();
  this->picker_.loop();
  this->wifi_setup_.loop();
  // dark: the sleep overlay over everything on the top layer (the Wi-Fi
  // setup keeps itself on top of the rest) - a first touch only wakes
  if (this->asleep_ && this->sleep_overlay_ != nullptr &&
      lv_obj_get_index(this->sleep_overlay_) != (int32_t) lv_obj_get_child_count(lv_layer_top()) - 1)
    lv_obj_move_foreground(this->sleep_overlay_);
  // the boot screen's big stopwatch: while it waits (no progress bar then)
  if (this->boot_busy_obj_ == nullptr) {
    this->boot_busy_obj_ = this->boot_busy_.make(lv_layer_top(), 72, this->assets_.color("accent", 0x4B9EF3));
    lv_obj_align(this->boot_busy_obj_, LV_ALIGN_CENTER, 0, 190);
  }
  BusyIcons::show(this->boot_busy_obj_, !this->main_shown_ && this->shown_progress_ < 0 && !this->language_needed() && !this->adding_);
  this->boot_busy_.animate(millis());
  // the progress bar follows the task (in 2% steps: fewer redraws)
  const int step_now = this->step_.load();
  int p = (this->job_ == JOB_THEME || this->job_ == JOB_STRINGS || this->job_ == JOB_FIRMWARE) && step_now != IDLE
              ? this->percent_.load()
              : -1;
  if (p >= 0)
    p -= p % 2;
  if (p != this->shown_progress_) {
    this->shown_progress_ = p;
    for (auto *t : this->status_triggers_)
      t->trigger();
  }
  switch (step_now) {
    case BUSY:
    case WRITE:
      return;  // the task is working
    case READY:
      if (this->job_ == JOB_PAYLOAD) {
        this->finish_payload_();
      } else if (this->job_ == JOB_FIRMWARE) {
        // a checked image: into the other slot (the board is down already)
        this->say_("panel.update_installing", "Installing the update…");
        // nothing of flash mapped while it's written (see the theme's save
        // below): the pictures go (back after a failed write:
        // finish_firmware_), the wording's parsed copy stays
        this->assets_.release(PACK_THEME);
        this->assets_.unmap(PACK_STRINGS);
        this->assets_changed_();
        this->write_started_ms_ = millis();
        // (an automatic one while the screen was dark: it stays dark - and
        // comes back dark: quiet_pref_)
        this->set_updating(true, !(this->want_auto_ && this->update_dark_));
        this->percent_.store(0);
        this->step_.store(WRITE);
      } else {
        // a checked pack: stop drawing from the old one, then let the task write
        const PackKind kind = this->job_ == JOB_THEME ? PACK_THEME : PACK_STRINGS;
        if (kind == PACK_THEME) {
          // the pictures are drawn straight from the pack: nothing may draw
          // while it's rewritten - back to the boot screen (its progress
          // bar) with the board taken down
          this->take_board_down_();
          this->assets_.release(kind);
          // (the wording's mapping too - its parsed copy stays: with nothing
          // of flash mapped, a firmware run from PSRAM keeps its cache, and
          // so the round panel's screen keeps its picture, while flash is
          // erased; any mapping left and each erase stops the screen's refill)
          this->assets_.unmap(PACK_STRINGS);
          this->assets_changed_();
          this->say_("panel.theme_saving", "Saving the theme…");
        } else {
          // the wording is a copy in RAM: the board stays up meanwhile (then
          // rebuilt in the new wording)
          this->assets_.unmap(kind);
        }
        this->write_started_ms_ = millis();
        this->set_updating(true);  // (the screen stays on while it's written)
        this->percent_.store(0);
        this->step_.store(WRITE);
      }
      return;
    case WRITTEN:
    case FAILED:
      if (this->job_ == JOB_PAYLOAD)
        this->finish_payload_();
      else if (this->job_ == JOB_FIRMWARE)
        this->finish_firmware_();
      else
        this->finish_pack_();
      return;
    default:
      break;
  }
  // idle: what's next?
  if (this->base_url_.empty() || this->revision_.empty())
    return;
  const bool firmware = this->generic_ && !this->want_build_.empty() && this->want_build_ != this->build_ &&
                        (this->want_build_ != this->failed_build_ || millis() - this->failed_at_ > FIRMWARE_RETRY_MS);
  if (firmware && this->mismatched_) {
    this->start_job_(JOB_FIRMWARE);  // too old for HA's Room Tiles (its 426 offer): nothing else works
    return;
  }
  if (this->retry_at_ != 0 && (int32_t) (millis() - this->retry_at_) < 0)
    return;
  if (this->revision_ != this->fetched_revision_) {
    this->start_job_(JOB_PAYLOAD);
  } else if (firmware && (!this->want_auto_ || this->unused_())) {
    this->start_job_(JOB_FIRMWARE);  // an update HA offers: before packs (it may want new ones)
  } else if (!this->want_strings_.empty() && this->want_strings_ != this->assets_.pack_id(PACK_STRINGS)) {
    this->start_job_(JOB_STRINGS);  // small and changes the words: first
  } else if (!this->want_theme_.empty() && this->want_theme_ != this->assets_.pack_id(PACK_THEME)) {
    this->start_job_(JOB_THEME);
  }
}

// Nobody's using the panel (an automatic update may restart it now): by
// idle time only, whatever is on screen - idle (dark, the clock, or dimmed:
// also a board an animation keeps up), or untouched a good while
bool RoomTiles::unused_() const {
  return this->asleep_ || this->dimmed_ || lv_display_get_inactive_time(nullptr) > AUTO_UPDATE_UNTOUCHED_MS;
}

void RoomTiles::download_again() {
  if (this->step_.load() != IDLE)
    return;  // one is downloading already
  // the pictures go from under the screen: nothing may draw from them -
  // the board and the idle clock down first (the boot screen until the new
  // theme is in)
  this->clock_.hide();
  this->take_board_down_();
  this->assets_.forget(PACK_THEME);
  this->assets_.forget(PACK_STRINGS);
  this->assets_changed_();
  this->retry_at_ = 0;
}

bool RoomTiles::sign_(std::string &query) {
  switch (sign_query(nullptr, query)) {
    case SignResult::OK:
      return true;
    case SignResult::NO_TIME:
      this->say_("panel.wait_time", "Waiting for the time from Home Assistant…");
      this->retry_at_ = millis() + 2000;
      return false;
    default:
      this->set_adding_(true);  // (no key yet: HA hasn't added this panel)
      this->retry_at_ = millis() + RETRY_MS;
      return false;
  }
}

void RoomTiles::start_job_(Job job) {
  std::string query;
  if (!this->sign_(query))
    return;
  this->job_ = job;
  this->job_url_ = this->base_url_ + (job == JOB_PAYLOAD ? PANEL_PATH : job == JOB_FIRMWARE ? FIRMWARE_PATH : PACK_PATH) + query;
  if (job == JOB_THEME)
    this->job_url_ += "&pack=theme";
  else if (job == JOB_STRINGS)
    this->job_url_ += "&pack=strings";
  else if (job == JOB_PAYLOAD)  // (what it runs: for updates)
    this->job_url_ += std::string("&board=") + this->board_id_ + "&build=" + this->build_ + "&generic=" + (this->generic_ ? "1" : "0") +
                      "&built=" + std::to_string((long long) App.get_build_time()) +
                      (*this->release_ ? std::string("&release=") + this->release_ : std::string());
  else if (job == JOB_FIRMWARE)
    this->job_url_ += "&build=" + this->want_build_;
  this->job_revision_ = this->revision_;
  this->job_error_.clear();
  this->pack_id_.clear();
  this->http_status_ = 0;
  this->body_len_ = 0;
  this->job_started_ms_ = millis();
  this->percent_.store(job == JOB_PAYLOAD ? -1 : 0);
  if (job == JOB_PAYLOAD && this->fetched_revision_.empty())
    this->say_("panel.getting_data", "Getting Room Tiles data…");
  else if (job == JOB_THEME)
    this->say_("panel.theme_downloading", "Downloading the theme…");
  else if (job == JOB_STRINGS)
    this->say_("panel.getting_wording", "Getting the wording…");
  else if (job == JOB_FIRMWARE)
    this->say_("panel.update_downloading", "Downloading the update…");
  if (job == JOB_FIRMWARE) {
    // dark by choice (idle: the screen off; the room's lights off): the
    // update stays dark and the panel comes back dark - not dark only
    // because HA was gone (offline_slept_: HA restarting for this very
    // update): that one shows its progress and comes back lit
    this->update_dark_ = this->asleep_ && !this->offline_slept_;
    ESP_LOGI(TAG, "Firmware update: build %s (%u KB) - this one is %s", this->want_build_.c_str(),
             (unsigned) (this->want_size_ / 1024), this->build_.c_str());
    this->take_board_down_();  // (the boot screen and its progress bar)
  }
  if (job == JOB_THEME) {
    // the boot screen while it downloads (its progress bar), not just once
    // it's saved
    this->theme_asked_ms_ = 0;
    this->take_board_down_();
  }
  this->step_.store(BUSY);
  // downloads block (DNS, connect, read) and so do flash writes: own task
  if (xTaskCreate(&RoomTiles::job_task_, "rt_job", 6144, this, 5, nullptr) != pdPASS) {
    ESP_LOGE(TAG, "Couldn't start the download task");
    this->step_.store(IDLE);
    this->job_ = JOB_NONE;
    this->retry_at_ = millis() + RETRY_MS;
  }
}

void RoomTiles::job_task_(void *arg) {
  auto *self = static_cast<RoomTiles *>(arg);
  // 1. download (into PSRAM - packs are megabytes; internal RAM is precious)
  esp_http_client_config_t cfg = {};
  cfg.url = self->job_url_.c_str();
  cfg.timeout_ms = 20000;
  cfg.buffer_size = 4096;
  cfg.disable_auto_redirect = true;
  esp_http_client_handle_t client = esp_http_client_init(&cfg);
  uint8_t *buf = nullptr;
  size_t len = 0;
  if (client == nullptr) {
    self->job_error_ = "client init failed";
  } else if (esp_err_t err = esp_http_client_open(client, 0); err != ESP_OK) {
    self->job_error_ = esp_err_to_name(err);
  } else {
    int64_t length = esp_http_client_fetch_headers(client);
    self->http_status_ = esp_http_client_get_status_code(client);
    size_t cap = (length > 0 && (size_t) length < MAX_BODY) ? (size_t) length + 1 : 64 * 1024;
    buf = static_cast<uint8_t *>(heap_caps_malloc(cap, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    while (buf != nullptr) {
      // (the whole body, as its length said: done - never grow the buffer
      // just to read the end; doubling a 3 MB pack's buffer to 6 MB is more
      // than the round panel's 8 MB of PSRAM can give)
      if (length > 0 && len >= (size_t) length)
        break;
      if (len + 1 >= cap) {
        if (cap >= MAX_BODY) {
          self->job_error_ = "too big";
          break;
        }
        size_t bigger = std::min(cap * 2, MAX_BODY);
        auto *grown = static_cast<uint8_t *>(heap_caps_realloc(buf, bigger, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
        if (grown == nullptr) {
          self->job_error_ = "out of memory";
          break;
        }
        buf = grown;
        cap = bigger;
      }
      int n = esp_http_client_read(client, reinterpret_cast<char *>(buf) + len, cap - len - 1);
      if (n < 0) {
        self->job_error_ = "read failed";
        break;
      }
      if (n == 0)
        break;
      len += n;
      if (length > 0 && self->job_ != JOB_PAYLOAD)
        self->percent_.store((int) (len * 100 / (size_t) length));
    }
    if (buf == nullptr && self->job_error_.empty())
      self->job_error_ = "out of memory";
    if (buf != nullptr)
      buf[len] = '\0';
  }
  if (client != nullptr) {
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
  }
  self->body_ = buf;
  self->body_len_ = len;
  if (self->job_ == JOB_PAYLOAD || !self->job_error_.empty() || self->http_status_ != 200) {
    self->step_.store(self->job_ == JOB_PAYLOAD && self->job_error_.empty() ? READY : FAILED);
    vTaskDelete(nullptr);
    return;
  }
  if (self->job_ == JOB_FIRMWARE) {
    // 2. an image: the size and SHA-256 HA said, before touching the flash
    uint8_t digest[32];
    char hex[65];
    mbedtls_sha256(buf, len, digest, 0);
    for (int i = 0; i < 32; i++)
      snprintf(hex + 2 * i, 3, "%02x", digest[i]);
    if (len != self->want_size_ || self->want_sha256_ != hex) {
      self->job_error_ = "not the image offered (size / checksum)";
      self->step_.store(FAILED);
      vTaskDelete(nullptr);
      return;
    }
    self->step_.store(READY);
    while (self->step_.load() == READY)  // (the loop says when: WRITE)
      vTaskDelay(pdMS_TO_TICKS(20));
    self->step_.store(write_firmware_(buf, len, self->job_error_, &self->percent_) ? WRITTEN : FAILED);
    vTaskDelete(nullptr);
    return;
  }
  // 2. a pack: check it completely before touching the flash
  const PackKind kind = self->job_ == JOB_THEME ? PACK_THEME : PACK_STRINGS;
  if (!AssetStore::check(kind, buf, len, self->pack_id_, self->job_error_)) {
    self->step_.store(FAILED);
    vTaskDelete(nullptr);
    return;
  }
  self->step_.store(READY);
  // 3. wait for the loop to stop drawing from the old pack, then write
  while (self->step_.load() == READY)
    vTaskDelay(pdMS_TO_TICKS(20));
  self->step_.store(self->assets_.write(kind, buf, len, self->job_error_, &self->percent_) ? WRITTEN : FAILED);
  vTaskDelete(nullptr);
}

void RoomTiles::finish_payload_() {
  PsramScope psram;  // (the new model - two while one replaces the other - its board: PSRAM)
  const uint32_t took = millis() - this->job_started_ms_;
  uint8_t *body = this->body_;
  const size_t len = this->body_len_;
  this->body_ = nullptr;
  this->step_.store(IDLE);
  this->job_ = JOB_NONE;

  bool ok = false;
  if (!this->job_error_.empty()) {
    ESP_LOGW(TAG, "Download failed: %s", this->job_error_.c_str());
    this->say_("panel.cant_reach", "Can't reach Home Assistant – trying again");
  } else if (this->http_status_ == 403) {
    ESP_LOGW(TAG, "Home Assistant refused the request (403) - is this panel added there, with this key?");
    this->say_("panel.not_accepted", "Home Assistant didn't accept this panel – trying again");
  } else if (this->http_status_ == 426) {
    // HA's Room Tiles and this firmware don't match: its number - and, when
    // this firmware is the older one, the image to install (right away)
    JsonDocument doc = json::parse_json(body, len);
    const int theirs = doc["schema"] | 0;
    ESP_LOGW(TAG, "Room Tiles in Home Assistant uses format %d, this firmware %d", theirs, PANEL_SCHEMA);
    this->want_build_ = doc["firmware"]["build"] | "";
    this->want_sha256_ = doc["firmware"]["sha256"] | "";
    this->want_size_ = doc["firmware"]["size"] | 0;
    this->want_auto_ = false;
    if (!this->want_build_.empty())
      ESP_LOGI(TAG, "Home Assistant offers build %s for it", this->want_build_.c_str());
    this->mismatch_(theirs);
  } else if (this->http_status_ == 404) {
    ESP_LOGW(TAG, "Room Tiles doesn't know this panel yet (404)");
    this->say_("panel.wait_added", "Waiting for Room Tiles to add this panel…");
  } else if (this->http_status_ != 200) {
    ESP_LOGW(TAG, "Unexpected answer: HTTP %d", this->http_status_);
    this->say_("panel.not_answering", "Room Tiles isn't answering – trying again");
  } else {
    JsonDocument doc = json::parse_json(body, len);
    JsonObject root = doc.as<JsonObject>();
    if (root.isNull()) {
      ESP_LOGW(TAG, "The payload isn't valid JSON (%u bytes)", (unsigned) len);
      this->say_("panel.unreadable", "Room Tiles sent something unreadable – trying again");
    } else if ((root["schema"] | 0) != PANEL_SCHEMA) {
      ESP_LOGW(TAG, "Payload schema %d, this firmware %d", (int) (root["schema"] | 0), PANEL_SCHEMA);
      this->mismatch_(root["schema"] | 0);
    } else {
      this->mismatched_ = false;
      const char *area_id = root["panel"]["area"] | "";
      JsonArray areas = root["areas"].as<JsonArray>();
      this->area_count_ = areas.size();
      this->area_name_.clear();
      for (JsonObject a : areas) {
        if (strcmp(a["id"] | "", area_id) == 0) {
          this->area_name_ = a["name"] | "";
          break;
        }
      }
      this->want_theme_ = root["packs"]["theme"]["id"] | "";
      // an update HA offers this panel (asked for on its update entity)
      this->want_build_ = root["firmware"]["build"] | "";
      this->want_sha256_ = root["firmware"]["sha256"] | "";
      this->want_size_ = root["firmware"]["size"] | 0;
      this->want_auto_ = root["firmware"]["auto"] | false;  // (installed once nobody's using the panel)
      this->want_strings_ = root["packs"]["strings"]["id"] | "";
      // the model the board is drawn from
      PanelModel m;
      m.area = root["panel"]["area"] | "";
      m.area_set = root["panel"]["area_set"] | true;
      m.layout = root["panel"]["layout"] | "5x2";
      m.theme = root["panel"]["theme"] | "";
      m.language = root["panel"]["language"] | "";
      m.room = root["panel"]["room"] | "";
      for (JsonVariant l : root["panel"]["room_lights"].as<JsonArray>()) {
        const char *id = l | "";
        if (*id != '\0')
          m.room_lights.emplace_back(id);
      }
      for (JsonObject a : areas) {
        AreaSpec s;
        s.id = a["id"] | "";
        s.name = a["name"] | "";
        s.short_name = a["short"] | "";
        s.floor = a["floor"] | "";
        JsonArray lights = a["lights"].as<JsonArray>();
        for (JsonVariant l : lights) {
          const char *id = l | "";
          if (*id != '\0')
            s.lights.emplace_back(id);
        }
        for (const char *layout : {"5x2", "6x3"}) {
          auto &out = strcmp(layout, "5x2") == 0 ? s.tiles_5x2 : s.tiles_6x3;
          JsonArray tiles = a["tiles"][layout].as<JsonArray>();  // (a local: GCC 14 warns on the temporary)
          for (JsonVariant t : tiles) {
            TileSpec ts;
            if (!t.isNull()) {
              ts.kind = t["kind"] | "";
              ts.entity = t["entity"] | "";
              ts.name = t["name"] | "";
            }
            out.push_back(ts);
          }
        }
        m.areas.push_back(std::move(s));
      }
      JsonArray catalog = root["catalog"].as<JsonArray>();
      for (JsonObject c : catalog)
        m.catalog.push_back(CatalogItem{c["entity"] | "", c["kind"] | "", c["short"] | "", c["area"] | ""});
      JsonObject floors = root["floors"].as<JsonObject>();
      for (JsonPair kv : floors)
        m.floors[kv.key().c_str()] = kv.value() | "";
      auto pts = [](JsonArray a) {
        std::vector<Pt> out;
        for (JsonArray p : a)
          out.push_back(Pt{p[0] | 0.0f, p[1] | 0.0f});
        return out;
      };
      auto segs = [](JsonArray a) {
        std::vector<std::array<float, 4>> out;
        for (JsonArray s : a)
          out.push_back({s[0] | 0.0f, s[1] | 0.0f, s[2] | 0.0f, s[3] | 0.0f});
        return out;
      };
      JsonArray maps = root["maps"].as<JsonArray>();
      for (JsonObject mj : maps) {
        // unchanged since the last payload: the same MapSpec (its tiles stay drawn)
        std::string json;
        serializeJson(mj, json);
        uint32_t sig = 2166136261u;  // FNV-1a
        for (unsigned char ch : json)
          sig = (sig ^ ch) * 16777619u;
        std::shared_ptr<const MapSpec> same;
        for (auto &old : this->model_.maps)
          if (old->sig == sig && old->id == (mj["id"] | ""))
            same = old;
        if (same) {
          m.maps.push_back(same);
          continue;
        }
        auto ms = std::make_shared<MapSpec>();
        ms->sig = sig;
        ms->id = mj["id"] | "";
        ms->name = mj["name"] | "";
        ms->floor = mj["ha_floor"] | "";
        JsonArray b = mj["bounds"].as<JsonArray>();
        for (int i = 0; i < 4; i++)
          ms->bounds[i] = b[i] | (i < 2 ? 0.0f : 1.0f);
        ms->wall_width = mj["wall_width"] | 6.0f;
        ms->generated = mj["generated"] | false;
        ms->walls = segs(mj["walls"].as<JsonArray>());
        ms->windows = segs(mj["windows"].as<JsonArray>());
        ms->openings = segs(mj["openings"].as<JsonArray>());
        JsonArray shapes_a = mj["shapes"].as<JsonArray>();  // (a local: GCC 14 dangling-reference warning)
        for (JsonObject sj : shapes_a)
          ms->shapes.push_back(MapShape{sj["style"] | "floor", pts(sj["points"].as<JsonArray>())});
        JsonArray zones_a = mj["zones"].as<JsonArray>();  // (a local: GCC 14 dangling-reference warning)
        for (JsonObject zj : zones_a) {
          MapZone z;
          z.id = zj["id"] | "";
          z.name = zj["name"] | "";
          z.points = pts(zj["points"].as<JsonArray>());
          z.area = zj["area"] | "";
          JsonArray l = zj["label"].as<JsonArray>();
          z.has_label = !l.isNull();
          if (z.has_label)
            z.label = Pt{l[0] | 0.0f, l[1] | 0.0f};
          z.outdoor = zj["outdoor"] | false;
          z.vacuum = zj["vacuum"] | "";
          z.vertical = zj["label_vertical"] | false;
          ms->zones.push_back(std::move(z));
        }
        JsonArray links_a = mj["links"].as<JsonArray>();  // (a local: GCC 14 dangling-reference warning)
        for (JsonObject lj : links_a) {
          JsonArray at = lj["at"].as<JsonArray>();
          ms->links.push_back(MapLink{lj["to"] | "", Pt{at[0] | 0.0f, at[1] | 0.0f}, lj["label"] | ""});
        }
        JsonArray layers_a = mj["layers"].as<JsonArray>();  // (a local: GCC 14 dangling-reference warning)
        for (JsonObject yj : layers_a)
          ms->layers.push_back(MapLayer{yj["id"] | "", yj["name"] | "", yj["min_zoom"] | 1.0f, yj["max_zoom"] | 0.0f});
        m.maps.push_back(std::move(ms));
      }
      JsonArray markers = root["markers"].as<JsonArray>();
      for (JsonObject kj : markers)
        m.markers.push_back(MapMarker{kj["id"] | "", kj["map"] | "", kj["layer"] | "", kj["entity"] | "",
                                      kj["x"] | 0.0f, kj["y"] | 0.0f, kj["show_name"] | false});
      JsonObject popups = root["popups"].as<JsonObject>();
      for (JsonPair kv : popups) {
        PopupSpec p;
        JsonArray groups_a = kv.value()["groups"].as<JsonArray>();
        for (JsonVariant g : groups_a)
          p.groups.push_back(g | "");
        JsonArray scenes_a = kv.value()["scenes"].as<JsonArray>();
        for (JsonVariant sc : scenes_a)
          p.scenes.push_back(sc | "");
        p.more_groups = kv.value()["more_groups"] | 0;
        p.more_scenes = kv.value()["more_scenes"] | 0;
        m.popups[kv.key().c_str()] = std::move(p);
      }
      JsonObject langs = root["languages"].as<JsonObject>();
      for (JsonPair kv : langs)
        m.languages[kv.key().c_str()] = kv.value() | "";
      JsonArray themes_a = root["themes"].as<JsonArray>();
      for (JsonVariant t : themes_a)
        m.themes.push_back(t | "");
      JsonObject theme_names = root["theme_names"].as<JsonObject>();
      for (JsonPair kv : theme_names)
        m.theme_names[kv.key().c_str()] = kv.value() | "";
      m.own_language = root["own"]["language"] | "";
      m.own_theme = root["own"]["theme"] | "";
      m.found = root["found"] | 0;
      JsonArray robots_a = root["robots"].as<JsonArray>();
      for (JsonObject rj : robots_a) {
        RobotSpec r{rj["robot"] | "", rj["sensor"] | "", rj["vacuum"] | "", rj["name"] | "", {}};
        JsonArray ra = rj["areas"].as<JsonArray>();
        for (JsonVariant a : ra)
          r.areas.push_back(a | "");
        m.robots.push_back(std::move(r));
      }
      JsonObject entities = root["entities"].as<JsonObject>();
      for (JsonPair kv : entities)
        m.entities[kv.key().c_str()] = EntityInfo{kv.value()["kind"] | "", kv.value()["short"] | "", kv.value()["icon"] | ""};
      // the user's own picks win until HA's payload has them too - and go
      // again while it doesn't (picked_)
      if (!this->picked_.empty()) {
        for (auto it = this->picked_.begin(); it != this->picked_.end();) {
          const std::string &key = it->first, &want = it->second;
          const std::string &has = key == "area" ? m.area : key == "layout" ? m.layout : key == "theme" ? m.theme : m.language;
          // (an area, theme or language gone meanwhile - an installed theme
          // removed, say: HA can never take it, so HA's stands)
          bool gone = false;
          if (key == "area") {
            gone = true;
            for (auto &a : m.areas)
              gone = gone && a.id != want;
          } else if (key == "theme" && !want.empty()) {
            gone = std::find(m.themes.begin(), m.themes.end(), want) == m.themes.end();
          } else if (key == "language" && !want.empty()) {
            gone = m.languages.count(want) == 0;
          }
          if (has == want || gone) {
            it = this->picked_.erase(it);
            continue;
          }
          if (key == "area")
            m.area = want;
          else if (key == "layout")
            m.layout = want;
          ++it;
        }
        this->send_picked_();
      }
      if (!this->map_) {
        // (no map on this panel: nothing of it - no Map button, no map
        // pictures made at startup)
        m.maps.clear();
        m.markers.clear();
      }
      this->model_ = std::move(m);
      this->have_model_ = true;
      // the language picked on the first start: the panel's own in HA, once
      // (HA's own already: it stays "Same as Home Assistant")
      if (this->boot_lang_.code[0] != 0 && this->boot_lang_.sent == 0) {
        if (this->model_.own_language.empty() && this->model_.language != this->boot_lang_.code) {
          ESP_LOGI(TAG, "Language picked on the panel: %s - set in Home Assistant", this->boot_lang_.code);
          this->choose_language(this->boot_lang_.code);
          this->boot_lang_pending_ = true;
        }
        this->boot_lang_.sent = 1;
        this->boot_lang_pref_.save(&this->boot_lang_);
      } else if (this->boot_lang_pending_ && (this->model_.language == this->boot_lang_.code || !this->model_.own_language.empty())) {
        this->boot_lang_pending_ = false;
      }
      ESP_LOGI(TAG, "Payload revision %s: %u bytes in %" PRIu32 " ms, %d areas, panel area '%s', layout %s, language %s",
               this->job_revision_.c_str(), (unsigned) len, took, this->area_count_, area_id,
               (const char *) (root["panel"]["layout"] | "?"), (const char *) (root["panel"]["language"] | "?"));
      this->fetched_revision_ = this->job_revision_;
      ok = true;
    }
  }
  if (body != nullptr)
    heap_caps_free(body);
  if (ok) {
    this->show_summary_();
    this->maybe_show_board_();
  } else {
    this->retry_at_ = millis() + RETRY_MS;
  }
}

// The image is in the other slot: restart into it (the bootloader goes back
// to this one if it doesn't start - ESPHome's safe mode confirms a good boot).
// Not written: the board again, tried later.
void RoomTiles::finish_firmware_() {
  this->set_updating(false);
  const bool written = this->step_.load() == WRITTEN;
  if (this->body_ != nullptr)
    heap_caps_free(this->body_);
  this->body_ = nullptr;
  this->step_.store(IDLE);
  this->job_ = JOB_NONE;
  this->percent_.store(-1);
  if (written) {
    ESP_LOGI(TAG, "Firmware build %s installed (%u KB, downloaded in %" PRIu32 " ms, written in %" PRIu32 " ms) - restarting",
             this->want_build_.c_str(), (unsigned) (this->body_len_ / 1024), this->write_started_ms_ - this->job_started_ms_,
             millis() - this->write_started_ms_);
    this->say_("panel.update_restarting", "Restarting…");
    if (this->want_auto_ && this->update_dark_) {
      const uint8_t dark = 1;  // (back dark after the restart: set_backlight)
      this->quiet_pref_.save(&dark);
      global_preferences->sync();
    }
    App.safe_reboot();
    return;
  }
  ESP_LOGW(TAG, "Firmware update failed: %s (HTTP %d) - this one keeps running",
           this->job_error_.empty() ? "-" : this->job_error_.c_str(), this->http_status_);
  this->failed_build_ = this->want_build_;
  this->failed_at_ = millis();
  if (this->assets_.pack_id(PACK_THEME).empty()) {  // (let go for the write: back)
    this->assets_.load(PACK_THEME, false);
    this->assets_changed_();
  }
  this->show_summary_();
  this->maybe_show_board_();
}

bool RoomTiles::write_firmware_(const uint8_t *data, size_t len, std::string &error, std::atomic<int> *percent) {
  const esp_partition_t *part = esp_ota_get_next_update_partition(nullptr);
  if (part == nullptr) {
    error = "no other firmware slot";
    return false;
  }
  if (len > part->size) {
    error = "bigger than the firmware slot";
    return false;
  }
  esp_ota_handle_t h;
  // erased as it's written (a sector at a time): the screen and the HA
  // connection keep running, as for a theme pack
  esp_err_t err = esp_ota_begin(part, OTA_WITH_SEQUENTIAL_WRITES, &h);
  static const size_t STEP = 64 * 1024;
  for (size_t pos = 0; err == ESP_OK && pos < len; pos += STEP) {
    const size_t n = std::min(STEP, len - pos);
    err = esp_ota_write(h, data + pos, n);
    percent->store((int) ((pos + n) * 100 / len));
    vTaskDelay(pdMS_TO_TICKS(10));
  }
  if (err == ESP_OK)
    err = esp_ota_end(h);  // (checks the image)
  else
    esp_ota_abort(h);
  if (err == ESP_OK)
    err = esp_ota_set_boot_partition(part);
  if (err != ESP_OK) {
    error = esp_err_to_name(err);
    return false;
  }
  return true;
}

void RoomTiles::finish_pack_() {
  this->set_updating(false);
  const PackKind kind = this->job_ == JOB_THEME ? PACK_THEME : PACK_STRINGS;
  const char *what = kind == PACK_THEME ? "Theme" : "Wording";
  const bool written = this->step_.load() == WRITTEN;
  if (this->body_ != nullptr)
    heap_caps_free(this->body_);
  this->body_ = nullptr;
  this->step_.store(IDLE);
  this->job_ = JOB_NONE;
  this->percent_.store(-1);
  if (written) {
    ESP_LOGI(TAG, "%s pack %s: %u KB, downloaded in %" PRIu32 " ms, saved in %" PRIu32 " ms", what,
             this->pack_id_.c_str(), (unsigned) (this->body_len_ / 1024), this->write_started_ms_ - this->job_started_ms_,
             millis() - this->write_started_ms_);
  } else if (!this->job_error_.empty()) {
    ESP_LOGW(TAG, "%s pack failed: %s", what, this->job_error_.c_str());
  } else {
    ESP_LOGW(TAG, "%s pack: HTTP %d", what, this->http_status_);
  }
  // load whatever is stored now (the new pack - or, after a failed write,
  // nothing: plain colours until the retry)
  this->assets_.load(kind, !written);  // (just written: it was checked in memory)
  this->assets_changed_();
  if (written)
    this->show_summary_();
  else
    this->retry_at_ = millis() + RETRY_MS;
  this->maybe_show_board_();
}

}  // namespace esphome::room_tiles
