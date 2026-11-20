#include "screen_policy.h"

namespace esphome::room_tiles {

// Where the screen would be now, by the facts alone - and, for dark, why.
//   used lately (or never idle)           lit
//   the board, the room's lights off      dark (room)
//   the board, a tile animating           dimmed
//   the board, a clock set                the clock
//   the board                             dark (idle: screen off)
//   HA gone, a clock set, under 10 min    dimmed ("Connecting…")
//   HA gone                               dark (away)
//   the boot screen otherwise             lit (setting up, downloading)
Screen ScreenPolicy::target_(const ScreenFacts &f, bool idle, DarkWhy &why) const {
  why = DarkWhy::NONE;
  if (!idle)
    return Screen::LIT;
  if (f.board) {
    if (f.room == Lights::OFF) {
      why = DarkWhy::ROOM;
      return Screen::DARK;
    }
    if (f.animating)
      return Screen::DIMMED;
    if (f.clock)
      return Screen::CLOCK;
    why = DarkWhy::IDLE;
    return Screen::DARK;
  }
  if (f.away) {
    if (f.clock && f.away_ms < AWAY_DARK_MS)
      return Screen::DIMMED;
    why = DarkWhy::AWAY;
    return Screen::DARK;
  }
  return Screen::LIT;
}

Screen ScreenPolicy::step(const ScreenFacts &f) {
  // used since the last step (its idle time went back): no longer idle anyway
  if (f.idle_ms < this->last_idle_ms_)
    this->idle_anyway_ = false;
  this->last_idle_ms_ = f.idle_ms;
  // the room's lights came on: off before, on now (unknown in between
  // doesn't count as either)
  const bool lights_came_on = this->last_room_ == Lights::OFF && f.room == Lights::ON;
  if (f.room != Lights::UNKNOWN)
    this->last_room_ = f.room;
  // the board back (after HA's absence, or at all)
  if (f.board && !this->last_board_) {
    this->board_back_ = true;
    this->board_back_at_ = f.now;
  } else if (!f.board) {
    this->board_back_ = false;
  }
  this->last_board_ = f.board;

  // being written: on (or dark, for an update made while dark)
  if (this->updating_) {
    if (this->cur_ != Screen::DARK)
      this->cur_ = Screen::LIT;
    return this->cur_;
  }

  const bool idle = f.sleep_ms > 0 && (this->idle_anyway_ || f.idle_ms > f.sleep_ms);
  DarkWhy why;
  const Screen want = this->target_(f, idle, why);

  if (this->cur_ == Screen::DARK) {
    const bool resumed = this->why_ == DarkWhy::AWAY && this->board_back_ &&
                         f.now - this->board_back_at_ < RESUME_WINDOW_MS && want != Screen::DARK;
    if (!lights_came_on && !resumed)
      return this->cur_;
  }
  this->cur_ = want;
  this->why_ = why;
  return this->cur_;
}

bool ScreenPolicy::touched() {
  this->idle_anyway_ = false;
  if (this->cur_ != Screen::DARK)
    return false;
  this->cur_ = Screen::LIT;
  this->why_ = DarkWhy::NONE;
  return true;
}

void ScreenPolicy::switched(bool on) {
  if (!on && this->cur_ != Screen::DARK) {
    this->cur_ = Screen::DARK;
    this->why_ = DarkWhy::CHOICE;
  } else if (on && this->cur_ == Screen::DARK) {
    this->idle_anyway_ = false;
    this->cur_ = Screen::LIT;
    this->why_ = DarkWhy::NONE;
  }
}

void ScreenPolicy::updating(bool on, bool wake) {
  this->updating_ = on;
  if (on && wake && this->cur_ == Screen::DARK) {
    this->idle_anyway_ = false;
    this->cur_ = Screen::LIT;
    this->why_ = DarkWhy::NONE;
  }
}

void ScreenPolicy::start_dark(DarkWhy why) {
  this->cur_ = Screen::DARK;
  this->why_ = why == DarkWhy::NONE ? DarkWhy::IDLE : why;
  this->idle_anyway_ = true;
}

const char *ScreenPolicy::describe() const {
  switch (this->cur_) {
    case Screen::LIT:
      return "lit";
    case Screen::DIMMED:
      return "dimmed";
    case Screen::CLOCK:
      return "the idle clock";
    case Screen::DARK:
      break;
  }
  switch (this->why_) {
    case DarkWhy::ROOM:
      return "dark (the room's lights are off)";
    case DarkWhy::AWAY:
      return "dark (Home Assistant gone)";
    case DarkWhy::CHOICE:
      return "dark (its backlight switched off)";
    default:
      return "dark (idle)";
  }
}

}  // namespace esphome::room_tiles
