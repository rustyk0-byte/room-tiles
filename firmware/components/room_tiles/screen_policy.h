// Room Tiles panel: what the screen shows when nobody's using it (docs/DESIGN.md
// "Screen states"). One place decides - lit, dimmed, the idle clock or dark -
// from the facts each loop and a few events (a touch, the backlight switched
// in HA, an update). Plain C++: no LVGL, no ESPHome (firmware/tests).
//
// Where the screen would be comes from the facts alone (target). Dark is
// sticky: once dark, the screen leaves it only for a touch, the backlight
// switched on in HA, an update that shows its progress, the room's lights
// coming on (whatever made it dark), or the board's return after HA's
// absence (when that's what made it dark and there's something to show).
#pragma once

#include <cstdint>

namespace esphome::room_tiles {

enum class Screen : uint8_t { LIT, DIMMED, CLOCK, DARK };
// why it's dark - kept over a restart after an update made while dark
// (the numbers are stored: never renumber; 1 = what older firmware wrote)
enum class DarkWhy : uint8_t { NONE = 0, IDLE = 1, ROOM = 2, AWAY = 3, CHOICE = 4 };
// the lights of the room the panel is in, for "Screen off when the
// following area lights are off": UNKNOWN when that's off, the room has
// none, or none reported yet
enum class Lights : uint8_t { UNKNOWN, ON, OFF };

struct ScreenFacts {
  uint32_t now{0};       // millis
  uint32_t idle_ms{0};   // since the last use (a touch, the knob)
  uint32_t sleep_ms{0};  // the sleep time (0 = never idle)
  bool board{false};     // the board is up (not the boot screen)
  bool away{false};      // Home Assistant gone (the boot screen says so)
  uint32_t away_ms{0};   // since when
  Lights room{Lights::UNKNOWN};
  bool clock{false};      // idle brings a clock (else: the screen off)
  bool animating{false};  // "Animations keep tiles visible" and a tile in view animates
};

class ScreenPolicy {
 public:
  // HA gone while idle on the clock: "Connecting…" dimmed this long, then dark
  static constexpr uint32_t AWAY_DARK_MS = 10 * 60 * 1000;
  // the board back after HA's absence made it dark: this long for the
  // tiles' states to bring an animation (or the clock) before it stays dark
  static constexpr uint32_t RESUME_WINDOW_MS = 15 * 1000;

  /// Each loop: the screen now.
  Screen step(const ScreenFacts &f);

  /// A touch or the knob. Dark: it only wakes (true - the touch goes no
  /// further).
  bool touched();
  /// The backlight switched in HA (off: dark by choice; on: lit). The
  /// panel's own switching finds it already so: nothing changes.
  void switched(bool on);
  /// A pack or the firmware being written (the screen stays on meanwhile);
  /// `wake`: it comes on for it (else an update while dark stays dark).
  void updating(bool on, bool wake);
  /// The first start after an update made while dark: dark again, for the
  /// same reason, and idle until used.
  void start_dark(DarkWhy why);

  Screen now() const { return this->cur_; }
  bool dark() const { return this->cur_ == Screen::DARK; }
  DarkWhy why() const { return this->why_; }
  bool is_updating() const { return this->updating_; }
  /// For the log: what it shows and why.
  const char *describe() const;

 protected:
  Screen target_(const ScreenFacts &f, bool idle, DarkWhy &why) const;

  Screen cur_{Screen::LIT};
  DarkWhy why_{DarkWhy::NONE};
  Lights last_room_{Lights::UNKNOWN};  // (the last known: OFF then ON = they came on)
  bool last_board_{false};
  bool board_back_{false};     // (the board came back - at board_back_at_)
  uint32_t board_back_at_{0};
  bool updating_{false};
  bool idle_anyway_{false};  // (start_dark: idle until used)
  uint32_t last_idle_ms_{0};
};

}  // namespace esphome::room_tiles
