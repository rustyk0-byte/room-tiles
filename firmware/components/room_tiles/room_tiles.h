// Room Tiles panel: the link to the Room Tiles integration - its payload,
// theme pack and wording (docs/DESIGN.md "Panel firmware").
#pragma once

#include <atomic>
#include <map>
#include <string>
#include <vector>

#include "esphome/components/light/light_state.h"
#include "esphome/core/automation.h"
#include "esphome/core/component.h"
#include "esphome/core/preferences.h"
#ifdef USE_UPDATE
#include "esphome/components/update/update_entity.h"
#endif

#include "actions.h"
#include "assets.h"
#include "board.h"
#include "idle_clock.h"
#include "map_view.h"
#include "model.h"
#include "picker.h"
#include "screenshot.h"
#include "states.h"

namespace esphome::room_tiles {

class StatusTrigger;
class AssetsTrigger;
class ScreenTrigger;

class RoomTiles : public Component {
 public:
  void setup() override;
  void loop() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::AFTER_CONNECTION; }

  // from sensor.room_tiles_panel_link: its state / its `url` attribute
  void set_revision(const std::string &revision);
  void set_base_url(const std::string &url);

  void add_status_trigger(StatusTrigger *t) { this->status_triggers_.push_back(t); }
  void add_assets_trigger(AssetsTrigger *t) { this->assets_triggers_.push_back(t); }
  void add_screen_trigger(ScreenTrigger *t) { this->screen_triggers_.push_back(t); }

  /// The main screen's container and the fonts it uses (YAML, at boot).
  void attach_board(lv_obj_t *root, const Fonts &fonts) {
    this->board_.attach(root, this, fonts);
    this->board_.set_strip(this->strip_);
    this->map_view_.attach(lv_obj_get_parent(root), root, this, &this->board_.fonts());
    guard_taps();
  }
  /// The boot screen's language picker: an empty full-screen container on it
  /// (YAML, at boot, after attach_board) - filled here, shown while
  /// language_needed().
  void attach_language_picker(lv_obj_t *root);
  /// A new panel (no wording yet, no language picked): the boot screen asks
  /// for its language first. The pick is the boot screen's language and,
  /// once HA has added the panel, the panel's own language there.
  bool language_needed() const;
  /// "Add this panel in Home Assistant" (no API key yet): the panel's name as
  /// HA's Discovered list shows it, and where to find it there; "" otherwise.
  std::string setup_name() const;
  std::string setup_hint() const;
  /// A tap is a tap only when the finger stayed put (TAP_SLOP_PX): a press
  /// that slid further (a missed scroll, a slip) clicks nothing - every
  /// button, tile and dialog alike.
  static constexpr int TAP_SLOP_PX = 16;
  static void guard_taps();
  /// The map screen: `map_id`, else the map of this area's floor.
  void open_map(const std::string &map_id);
  /// A vacuum tile's room queue: its map in queue mode (when it has one).
  void open_queue(const std::string &entity);
  /// Back to the tiles (the map / queue closed, when open).
  void close_map();
  /// A screenshot, sent to the integration (its PNG in HA's media folder);
  /// `tell`: the panel says where it went (taken from its settings).
  void take_screenshot(bool tell = false);

  // ---- the display (the old panels' settings): brightness, sleep -------------------
  /// The backlight (YAML, at boot): this panel's brightness is applied to it.
  void set_backlight(light::LightState *light);
  /// The backlight went on / off (YAML: whoever switched it - HA too): asleep
  /// with it, so the dark screen's next touch only wakes it.
  void backlight_switched(bool on);
  /// Brightness 10-100 % (live while the slider moves; `save` when it's let go).
  void set_brightness(int percent, bool save);
  int brightness() const { return this->display_.brightness; }
  /// A vacuum's room queue starts by itself when a room is added (the
  /// dashboard's "Start queue automatically"; kept on the panel, like the
  /// display settings - off until it's turned on)
  bool queue_autostart() const { return this->queue_autostart_; }
  void set_queue_autostart(bool on);
  /// The screen goes off after this many seconds untouched (0 = never).
  void set_sleep(int seconds, bool save);
  int sleep_seconds() const { return this->display_.sleep_s; }
  /// The backlight while the idle clock is up: 10 % up to the brightness
  /// (at it: follows it). Shown live while its slider moves; kept on `save`.
  void set_idle_brightness(int percent, bool save);
  int idle_brightness() const { return std::min(this->idle_bright_, this->display_.brightness); }
  /// When idle (after the sleep time): 0 the screen off, 1 a digital clock,
  /// 2 an analog one (idle_clock.h); `anim_keep`: a tile in view animating
  /// keeps the clock away. Kept on the panel.
  enum IdleMode : int { IDLE_OFF = 0, IDLE_DIGITAL = 1, IDLE_ANALOG = 2, IDLE_THEME = 3 };
  /// `seconds`: a second hand on the analog / theme clock. The theme clock
  /// in a theme without one: the analog one (the setting stays).
  void set_idle(int mode, bool anim_keep, bool seconds, bool save);
  int idle_mode() const { return this->idle_.mode; }
  bool idle_anim_keep() const { return this->idle_.anim_keep != 0; }
  bool idle_seconds() const { return this->idle_.seconds != 0; }
  /// "Screen off when the room is dark": idle while the lights of the room
  /// the panel is in (its HA device's area's lights button - not the area it
  /// shows) are all off, the screen goes off instead of the clock or a
  /// dimmed board; the lights coming on while it's off bring the idle clock
  /// back. Kept on the panel.
  bool idle_lights_off() const { return this->idle_lights_ != 0; }
  void set_idle_lights_off(bool on);
  /// The clocks (the top bar's, the digital idle clock): 12-hour with AM / PM
  /// or 24-hour. Until it's switched: the language's way (clock.hours12).
  /// Kept on the panel.
  bool hours12() const;
  void set_hours24(bool on);
  /// The round panel's strip: where it was in each room (its snap point),
  /// kept on the panel - a room opens where it was left (after a restart, a
  /// room switch, a new payload). 0 for a room it hasn't been in.
  int strip_point(const std::string &area) const;
  void set_strip_point(const std::string &area, int point);
  /// An update is being written (a pack, the firmware): the screen stays on
  /// (no sleep) until it's done.
  /// `wake`: the screen comes on for it (an automatic update while it's
  /// dark stays dark).
  void set_updating(bool on, bool wake = true);
  /// This panel's language ("" = Home Assistant's): its setting in HA.
  void choose_language(const std::string &code);
  /// The panel's shape (codegen: room_tiles' layout / map): the round panel's
  /// strip, and no map / vacuum view.
  void set_shape(bool strip, bool map) {
    this->strip_ = strip;
    this->map_ = map;
  }
  /// The knob (round panel): turned (clicks, + = clockwise) / pressed. Either
  /// wakes a sleeping screen first.
  void knob_turn(int clicks);
  void knob_press();
  /// The round panel (480x480, the strip layout): dialogs lay out for a circle.
  bool round() const { return this->strip_; }
  /// Built from the installer's generic image (its Wi-Fi set on its hotspot).
  bool generic() const { return this->generic_; }
  /// Forget the Wi-Fi network set on the hotspot and restart: the hotspot
  /// opens again to pick a new one (generic panels only).
  void forget_wifi();
  /// Back to new (the panel's Factory Reset button in HA): Room Tiles forgets
  /// this panel's settings, then its theme, wording and everything kept on it.
  void factory_reset();
#ifdef USE_UPDATE
  /// The board's Wi-Fi chip runs other firmware than the image this build
  /// carries (its update entity's on_update_available): an older chip is
  /// brought up to it, once (DESIGN.md "The Wi-Fi chip").
  void wifi_chip_update_available(update::UpdateEntity *chip);
#endif
  /// The boot screen's Change Wi-Fi button (on Wi-Fi, no Home Assistant for
  /// a while - maybe the wrong network): 0 hidden, 1 shown, 2 asking "tap
  /// again" - and its words.
  int wifi_button() const { return this->wifi_button_; }
  std::string wifi_button_text() const;
  void wifi_button_tap();
  /// This image's tag, board, kind and release (codegen: room_tiles' board /
  /// generic; the release's version - "" for any other build).
  void set_image(const char *tag, const char *board, bool generic, const char *release) {
    this->image_tag_ = tag;
    this->board_id_ = board;
    this->generic_ = generic;
    this->release_ = release;
  }
  void choose_theme(const std::string &name);
  /// The top bars' gear: the picture fitted to the bar's box (bar_gear), or -
  /// a pack from before it - the settings icon's small size.
  const lv_image_dsc_t *bar_gear() const {
    const lv_image_dsc_t *g = this->image(IMG_BAR_GEAR);
    return g != nullptr ? g : this->image(IMG_ICON_SETTINGS_S);
  }
  const PanelModel &model() const { return this->model_; }
  StateHub &states() { return this->states_; }
  ActionSender &actions() { return this->actions_; }
  ColorPicker &picker() { return this->picker_; }
  Board &board() { return this->board_; }
  MapView &map_view() { return this->map_view_; }
  /// Show another area / layout now (drawn from what the panel has) and set
  /// the panel's own setting in HA meanwhile.
  void choose_area(const std::string &area);
  void choose_layout(const std::string &layout);
  /// Redraw the tiles showing `entity` (e.g. while the picker holds a colour).
  void repaint(const std::string &entity) { this->board_.entity_changed(entity); }

  /// One line for the boot screen: what the panel is doing / what it got.
  const std::string &status() const { return this->status_; }
  /// Drop the stored theme + wording so both download again (HA's button).
  void download_again();
  /// 0-100 while a pack downloads, then again while it's saved; -1 otherwise.
  /// (on_status fires when it moves.)
  int progress() const { return this->shown_progress_; }
  /// The asset area's size in bytes (0 = this panel has the old flash layout).
  uint32_t assets_size() const { return this->assets_.area_size(); }
  /// An image from the theme pack (nullptr until one is stored).
  const lv_image_dsc_t *image(AssetId id) const { return this->assets_.image(id); }
  /// The theme's idle clock (clock.json text; "" = it draws none).
  const std::string &theme_clock() const { return this->assets_.clock(); }
  /// A theme colour token, or `fallback`.
  uint32_t color(const std::string &token, uint32_t fallback) const { return this->assets_.color(token, fallback); }
  /// Wording in the panel's language (the key itself until it's stored).
  std::string t(const char *key) const { return this->assets_.t(key); }

 protected:
  enum Job : int { JOB_NONE = 0, JOB_PAYLOAD, JOB_THEME, JOB_STRINGS, JOB_FIRMWARE };
  // a job: the task downloads (+ checks a pack) -> READY; the loop stops
  // drawing from the old pack -> WRITE; the task writes it -> WRITTEN
  enum Step : int { IDLE = 0, BUSY, READY, WRITE, WRITTEN, FAILED };

  static void job_task_(void *arg);
  bool sign_(std::string &query);
  void start_job_(Job job);
  void finish_payload_();
  void finish_pack_();
  void set_status_(const std::string &status);
  /// A firmware update installed (WRITTEN: restart) or not (FAILED).
  void finish_firmware_();
  /// Write a downloaded, checked image into the other firmware slot (the job
  /// task); percent 0-100.
  static bool write_firmware_(const uint8_t *data, size_t len, std::string &error, std::atomic<int> *percent);
  /// The boot screen up, the board's map / picker / dialog closed (a theme
  /// is coming: nothing may draw from the old pack).
  void take_board_down_();
  /// HA connected or not (each loop): the boot screen after a while without.
  void watch_connection_();
  /// No Wi-Fi network yet (its hotspot up): the boot screen says which to join.
  void watch_wifi_setup_();
  void watch_wifi_button_();
  /// No API key yet (HA hasn't added this panel): the boot screen says to
  /// add it (checked once a second).
  void watch_adding_();
  void set_adding_(bool on);
  /// HA's Room Tiles uses format `theirs`, not this firmware's: the boot
  /// screen, saying which side needs an update (tried again meanwhile).
  void mismatch_(int theirs);
  /// A boot screen line in the panel's language (`fallback` until its wording
  /// is stored).
  std::string boot_text_(const char *key, const char *fallback) const;
  /// The boot screen's language before the wording is stored (boot_words.h).
  const char *boot_language_() const;
  /// The status line from its key (+ `{name}`) - said again when a
  /// language is picked.
  void say_(const char *key, const char *fallback, const std::string &name = "");
  void show_language_picker_();
  void pick_language_(int index);
  void show_summary_();
  void assets_changed_();
  void maybe_show_board_();
  void show_screen_(bool main);

  AssetStore assets_;
  std::string revision_;
  std::string base_url_;
  std::string fetched_revision_;  // the revision of the payload we have
  std::string want_theme_;        // pack ids the last payload asked for
  std::string want_strings_;
  uint32_t retry_at_{0};

  // the running job (its task fills these; loop() reads them per step)
  Job job_{JOB_NONE};
  std::atomic<int> step_{IDLE};
  std::string job_url_;
  std::string job_revision_;
  uint8_t *body_{nullptr};
  size_t body_len_{0};
  int http_status_{0};
  std::string job_error_;
  std::string pack_id_;
  uint32_t job_started_ms_{0};
  uint32_t write_started_ms_{0};
  std::atomic<int> percent_{-1};  // the task's progress (download, then save)
  int shown_progress_{-1};

  std::string status_;
  const char *status_key_{nullptr};  // (the status line's key: nullptr = not a boot line)
  const char *status_fallback_{""};
  std::string status_name_;
  // the language picked on a new panel's first start: a record of its own;
  // `sent` once it's the panel's language in HA (or HA's was the same)
  struct BootLang {
    char code[4];
    uint8_t sent;
  } boot_lang_{};
  ESPPreferenceObject boot_lang_pref_;
  bool boot_lang_pending_{false};  // (sent: HA's payloads still in its own language)
  lv_obj_t *lang_root_{nullptr};
  bool adding_{false};  // (no API key yet: "Add this panel in Home Assistant")
  uint32_t adding_checked_ms_{0};
  bool area_asked_{false};  // (a panel without an area: the area picker opened once)
  std::string area_name_;
  int area_count_{0};
  std::vector<StatusTrigger *> status_triggers_;
  std::vector<AssetsTrigger *> assets_triggers_;
  std::vector<ScreenTrigger *> screen_triggers_;

  StateHub states_;
  ActionSender actions_;
  Screenshot screenshot_;
  PanelModel model_;
  Board board_;
  MapView map_view_;
  ColorPicker picker_;
  // this firmware: its board, generic or hand-built, and its build (the
  // first 8 bytes of its ELF's SHA-256, hex) - sent with each payload request
  const char *image_tag_{""};
  const char *release_{""};  // (a release's build: its version, "0.1.0")
  const char *board_id_{""};
  bool generic_{false};
  std::string build_;
  // an update HA offers (its payload's "firmware"): the build, its size and
  // SHA-256; tried again only after FIRMWARE_RETRY_MS if it failed
  std::string want_build_, want_sha256_;
  size_t want_size_{0};
  bool want_auto_{false};
  bool update_dark_{false};  // (the screen was dark when the update started)
  ESPPreferenceObject quiet_pref_;  // (set: the next start goes dark at once)
  bool quiet_boot_{false};  // ("Update panels automatically": when nobody's using it - unused_)
  bool unused_() const;
  std::string failed_build_;
  uint32_t failed_at_{0};
  bool strip_{false};
  bool map_{true};
  bool have_model_{false};
  bool main_shown_{false};
  // HA's Room Tiles and this firmware don't match (signing.h PANEL_SCHEMA):
  // the boot screen says which needs an update until a payload is accepted
  bool mismatched_{false};
  // a theme picked on this panel: the boot screen ("Requesting the theme…")
  // until its download starts - or, if none comes, a while (millis; 0 = none)
  uint32_t theme_asked_ms_{0};
  // Home Assistant gone (a restart, the router, an outage): since when
  // (millis; 0 = connected), and whether the boot screen says so - after
  // OFFLINE_AFTER_MS, so a short blip doesn't flip the screen
  uint32_t offline_since_{0};
  bool offline_{false};
  bool wifi_setup_{false};  // (no Wi-Fi network yet: watch_wifi_setup_)
  int wifi_button_{0};        // (watch_wifi_button_)
  uint32_t wifi_armed_ms_{0};  // (its first tap: a second within a few seconds forgets)
  // settings picked on the panel (area, layout, theme, language -> its
  // value, "" = the default), kept until HA's payload has them: a send while
  // HA can't be reached (restarting, Wi-Fi) is lost - they go again with
  // each payload that doesn't have them yet and every PICK_RESEND_MS; the
  // area and layout shown meanwhile are the picked ones (and an older
  // payload in flight doesn't flip the board back for a moment)
  std::map<std::string, std::string> picked_;
  uint32_t picked_sent_ms_{0};
  void pick_(const char *key, const std::string &value);
  void send_picked_();
  struct Display {
    uint8_t brightness{100};
    uint8_t sleep_s{0};  // (0 = never)
  } display_;
  ESPPreferenceObject display_pref_;
  // the idle settings: a record of their own (the display one keeps its size)
  struct Idle {
    uint8_t mode{IDLE_OFF};
    uint8_t anim_keep{0};  // (off by default: the clock comes whatever animates)
    uint8_t seconds{1};    // a second hand (on by default: switched off by choice)
  } idle_;
  ESPPreferenceObject idle_pref_;
  // the idle clock's brightness: its own record (100 = the brightness)
  uint8_t idle_bright_{100};
  ESPPreferenceObject idle_bright_pref_;
  // "Screen off when the room is dark": its own record (the idle one keeps its size)
  uint8_t idle_lights_{0};
  ESPPreferenceObject idle_lights_pref_;
  std::string lights_watched_;  // (the room's lights watched for it)
  bool lights_slept_{false};    // (asleep because the room's lights went off)
  /// The room the panel is in has lights (its lights button) and all are off.
  bool room_dark_();
#ifdef USE_UPDATE
  update::UpdateEntity *wifi_chip_waiting_{nullptr};  // (an update due: once the language is picked)
  void wifi_chip_update_();
#endif
  bool hold_boot_screen_{false};  // (a factory reset / the Wi-Fi chip's update: the boot screen stays up)
  uint32_t wifi_chip_tried_{0};  // (the carried Wi-Fi chip version last tried: its hash - never again)
  ESPPreferenceObject wifi_chip_pref_;
  uint8_t clock24_{0};  // 0 = the language's way, 1 = 12-hour, 2 = 24-hour
  // the round panel's strip, per room: its own record, the rooms last used
  // first (a room id's hash -> its snap point; the oldest goes when full)
  static constexpr int STRIP_ROOMS = 24;
  struct StripPoints {
    uint32_t room[STRIP_ROOMS];
    uint8_t point[STRIP_ROOMS];
  } strip_points_{};
  ESPPreferenceObject strip_points_pref_;
  ESPPreferenceObject clock24_pref_;
  uint8_t preview_pct_{0};  // (a brightness slider moving: shown as it goes; 0 = none)
  bool dimmed_{false};      // (idle: the backlight at the idle brightness - idle_loop_)
  void dim_(bool on);
  IdleClock clock_;
  /// Each loop: the screen off or the clock when idle (the setting).
  void idle_loop_();
  ESPPreferenceObject queue_pref_;  // (its own: the display record keeps its size)
  bool queue_autostart_{false};
  bool oom_report_{false};
  uint32_t boot_pictures_at_{0};  // (the boot screen waits for the maps' pictures: maybe_show_board_)  // (the last restart was out of memory: logged again once connected)
  light::LightState *backlight_{nullptr};
  bool asleep_{false};
  // the knob: its last click (when, which way) and where its list scroll goes
  uint32_t knob_ms_{0};
  int knob_dir_{0};
  lv_obj_t *knob_list_{nullptr};  // (only compared: never used)
  int32_t knob_y_{0};
  // the screen went dark only because HA was gone (the Connecting screen):
  // when the board is back, the idle rules decide again, as if untouched all
  // along - an animation keeps it up dimmed, a clock comes - for a while
  // (resume_at_: then the tiles' states are in), else it stays dark
  bool offline_slept_{false};
  uint32_t resume_at_{0};
  bool updating_{false};
  lv_obj_t *sleep_overlay_{nullptr};
  void apply_backlight_();
  void sleep_();
  void wake_();
  BusyIcons boot_busy_;
  lv_obj_t *boot_busy_obj_{nullptr};
};

/// `on_status:` - the status line changed.
class StatusTrigger : public Trigger<> {
 public:
  explicit StatusTrigger(RoomTiles *parent) { parent->add_status_trigger(this); }
};

/// `on_screen:` (x = true: the main screen, false: the boot screen) - which
/// page the panel should show.
class ScreenTrigger : public Trigger<bool> {
 public:
  explicit ScreenTrigger(RoomTiles *parent) { parent->add_screen_trigger(this); }
};

/// `on_assets:` - the theme / wording changed: redraw what uses them.
class AssetsTrigger : public Trigger<> {
 public:
  explicit AssetsTrigger(RoomTiles *parent) { parent->add_assets_trigger(this); }
};

}  // namespace esphome::room_tiles
