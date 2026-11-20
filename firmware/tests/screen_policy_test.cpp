// The panel's screen states (components/room_tiles/screen_policy.cpp) - built
// and run on a PC, no LVGL / ESPHome:
//
//     g++ -std=gnu++20 -Wall -Werror -I../components/room_tiles -o screen_policy_test
//         screen_policy_test.cpp ../components/room_tiles/screen_policy.cpp && ./screen_policy_test
//
// Each test plays a panel's day: time passes, someone touches it, the room's
// lights switch, HA goes and comes back, an update runs - and checks what
// the screen shows.
#include "screen_policy.h"

#include <cstdio>
#include <cstdlib>
#include <functional>
#include <string>
#include <vector>

using namespace esphome::room_tiles;

static int failures = 0;
static std::string current;

static const char *name(Screen s) {
  switch (s) {
    case Screen::LIT:
      return "lit";
    case Screen::DIMMED:
      return "dimmed";
    case Screen::CLOCK:
      return "clock";
    case Screen::DARK:
      return "dark";
  }
  return "?";
}

// A panel: the policy, the facts as the panel would gather them, and the
// time. The idle time is "since the last use", like LVGL's.
struct Panel {
  ScreenPolicy p;
  ScreenFacts f;
  uint32_t used_at{0};
  uint32_t away_since{0};

  Panel() {
    f.now = 1000;
    f.sleep_ms = 60 * 1000;
    f.board = true;
    f.clock = true;
    used_at = f.now;
  }
  Screen step() {
    f.idle_ms = f.now - used_at;
    f.away_ms = f.away ? f.now - away_since : 0;
    return p.step(f);
  }
  // time passes, a step a second (as the loop would, only coarser)
  Screen wait(uint32_t ms) {
    Screen s = step();
    for (uint32_t t = 0; t < ms; t += 1000) {
      f.now += ms - t < 1000 ? ms - t : 1000;
      s = step();
    }
    return s;
  }
  // a touch: LVGL sees it (the idle time starts again), and a dark screen only wakes
  bool touch() {
    used_at = f.now;
    const bool woke = p.touched();
    step();
    return woke;
  }
  void lights(Lights l) {
    f.room = l;
    step();
  }
  void ha_gone() {
    f.away = true;
    f.board = false;
    away_since = f.now;
    step();
  }
  void ha_back() {
    f.away = false;
    f.board = true;
    step();
  }
};

static void expect(const char *what, Screen got, Screen want) {
  if (got != want) {
    std::printf("  FAIL %s: %s - %s, expected %s\n", current.c_str(), what, name(got), name(want));
    failures++;
  }
}
static void expect_true(const char *what, bool got) {
  if (!got) {
    std::printf("  FAIL %s: %s\n", current.c_str(), what);
    failures++;
  }
}

static const uint32_t SLEEP = 60 * 1000, MIN = 60 * 1000;

static void test(const char *title, const std::function<void()> &body) {
  current = title;
  const int before = failures;
  body();
  std::printf("%s %s\n", failures == before ? "ok  " : "FAIL", title);
}

int main() {
  // ---- the usual cycle ----------------------------------------------------
  test("used: lit until the sleep time, then the clock", [] {
    Panel t;
    expect("just used", t.step(), Screen::LIT);
    expect("under the sleep time", t.wait(SLEEP - 2000), Screen::LIT);
    expect("past it", t.wait(3000), Screen::CLOCK);
  });
  test("a touch on the clock: lit (the clock's own release takes it down)", [] {
    Panel t;
    t.wait(SLEEP + 2000);
    expect_true("not a wake", !t.touch());
    expect("touched", t.step(), Screen::LIT);
  });
  test("screen off mode: dark when idle, a touch only wakes", [] {
    Panel t;
    t.f.clock = false;
    expect("idle", t.wait(SLEEP + 2000), Screen::DARK);
    expect_true("the reason", t.p.why() == DarkWhy::IDLE);
    expect("stays", t.wait(30 * MIN), Screen::DARK);
    expect_true("the touch only wakes", t.touch());
    expect("woken", t.step(), Screen::LIT);
    expect("idle again", t.wait(SLEEP + 2000), Screen::DARK);
  });
  test("sleep time never: always lit", [] {
    Panel t;
    t.f.sleep_ms = 0;
    expect("hours later", t.wait(120 * MIN), Screen::LIT);
  });
  test("sleep time never: dark by choice still stays dark until touched", [] {
    Panel t;
    t.f.sleep_ms = 0;
    t.p.switched(false);
    expect("switched off", t.wait(5 * MIN), Screen::DARK);
    t.touch();
    expect("touched", t.step(), Screen::LIT);
  });

  // ---- animations ---------------------------------------------------------
  test("an animation keeps the board up, dimmed - its end brings the clock", [] {
    Panel t;
    t.f.animating = true;
    expect("idle, animating", t.wait(SLEEP + 2000), Screen::DIMMED);
    t.f.animating = false;
    expect("it stopped", t.wait(1000), Screen::CLOCK);
  });
  test("an animation starting on the clock: the board, dimmed", [] {
    Panel t;
    t.wait(SLEEP + 2000);
    t.f.animating = true;
    expect("animating", t.wait(1000), Screen::DIMMED);
  });
  test("an animation starting while dark doesn't wake it", [] {
    Panel t;
    t.f.clock = false;
    t.wait(SLEEP + 2000);
    t.f.animating = true;
    expect("animating", t.wait(5000), Screen::DARK);
  });
  test("screen off mode with an animation: kept up dimmed while it runs", [] {
    Panel t;
    t.f.clock = false;
    t.f.animating = true;
    expect("animating", t.wait(SLEEP + 2000), Screen::DIMMED);
    t.f.animating = false;
    expect("stopped", t.wait(1000), Screen::DARK);
  });

  // ---- the room's lights ----------------------------------------------------
  test("room lights off while idle: dark; on: the clock", [] {
    Panel t;
    t.lights(Lights::ON);
    expect("idle, lights on", t.wait(SLEEP + 2000), Screen::CLOCK);
    t.lights(Lights::OFF);
    expect("lights off", t.wait(1000), Screen::DARK);
    expect_true("the reason", t.p.why() == DarkWhy::ROOM);
    t.lights(Lights::ON);
    expect("lights on", t.wait(1000), Screen::CLOCK);
  });
  test("room lights off while in use: lit until idle, then dark", [] {
    Panel t;
    t.lights(Lights::OFF);
    expect("in use", t.wait(5000), Screen::LIT);
    expect("idle", t.wait(SLEEP), Screen::DARK);
  });
  test("room lights on, screen off mode: stays dark", [] {
    Panel t;
    t.f.clock = false;
    t.lights(Lights::OFF);
    t.wait(SLEEP + 2000);
    t.lights(Lights::ON);
    expect("lights on", t.wait(1000), Screen::DARK);
  });
  test("room lights on with an animation: the board, dimmed", [] {
    Panel t;
    t.lights(Lights::OFF);
    t.wait(SLEEP + 2000);
    t.f.animating = true;
    t.lights(Lights::ON);
    expect("lights on", t.wait(1000), Screen::DIMMED);
  });
  test("after an update made while dark: lights on bring the clock (the 0.1.6 bug)", [] {
    Panel t;
    t.f.board = false;  // (starting: the boot screen)
    t.p.start_dark(DarkWhy::ROOM);
    t.used_at = t.f.now;  // (LVGL's idle time starts at the boot)
    expect("starting", t.step(), Screen::DARK);
    t.f.board = true;
    expect("the board up", t.wait(3000), Screen::DARK);
    t.lights(Lights::OFF);  // (the states come in)
    expect("lights known off", t.wait(20 * MIN), Screen::DARK);
    t.lights(Lights::ON);
    expect("lights on - before the sleep time would be up, too", t.step(), Screen::CLOCK);
  });
  test("after an update made while dark, lights on within the first seconds: still the clock", [] {
    Panel t;
    t.p.start_dark(DarkWhy::IDLE);
    t.lights(Lights::OFF);
    t.wait(5000);
    t.lights(Lights::ON);
    expect("lights on", t.step(), Screen::CLOCK);
  });
  test("after an update made while dark, the lights already on: stays dark", [] {
    Panel t;
    t.f.clock = false;
    t.p.start_dark(DarkWhy::IDLE);
    t.lights(Lights::ON);
    expect("lights on all along", t.wait(30 * MIN), Screen::DARK);
  });
  test("after an update made while dark: a touch, then the usual sleep time", [] {
    Panel t;
    t.p.start_dark(DarkWhy::IDLE);
    t.wait(10 * MIN);
    t.touch();
    expect("touched", t.step(), Screen::LIT);
    expect("a moment later", t.wait(10 * 1000), Screen::LIT);
    expect("after the sleep time", t.wait(SLEEP), Screen::CLOCK);
  });
  test("lights not known yet (a restart): not counted as off", [] {
    Panel t;
    expect("idle", t.wait(SLEEP + 2000), Screen::CLOCK);
  });
  test("lights unknown between off and on (unavailable): still came on", [] {
    Panel t;
    t.lights(Lights::OFF);
    t.wait(SLEEP + 2000);
    t.lights(Lights::UNKNOWN);
    expect("unknown", t.wait(1000), Screen::DARK);
    t.lights(Lights::ON);
    expect("on", t.wait(1000), Screen::CLOCK);
  });
  test("lights on wake a screen dark for any reason (switched off in HA)", [] {
    Panel t;
    t.lights(Lights::OFF);
    t.wait(SLEEP + 2000);
    t.p.switched(false);
    t.lights(Lights::ON);
    expect("lights on", t.wait(1000), Screen::CLOCK);
  });
  test("lights on wake a screen dark because HA was gone", [] {
    Panel t;
    t.lights(Lights::OFF);
    t.wait(SLEEP + 2000);
    t.ha_gone();
    t.wait(20 * MIN);
    t.ha_back();
    expect("back, lights still off", t.wait(30 * 1000), Screen::DARK);
    t.lights(Lights::ON);
    expect("lights on", t.wait(1000), Screen::CLOCK);
  });

  // ---- Home Assistant gone ------------------------------------------------
  test("HA gone while on the clock: Connecting dimmed, then dark after 10 min", [] {
    Panel t;
    t.wait(SLEEP + 2000);
    t.ha_gone();
    expect("gone", t.step(), Screen::DIMMED);
    expect("9 min", t.wait(9 * MIN), Screen::DIMMED);
    expect("11 min", t.wait(2 * MIN), Screen::DARK);
    expect_true("the reason", t.p.why() == DarkWhy::AWAY);
  });
  test("an HA restart while on the clock: never dark", [] {
    Panel t;
    t.wait(SLEEP + 2000);
    t.ha_gone();
    expect("restarting", t.wait(90 * 1000), Screen::DIMMED);
    t.ha_back();
    expect("back", t.wait(1000), Screen::CLOCK);
  });
  test("HA back after it made the screen dark: the clock again", [] {
    Panel t;
    t.wait(SLEEP + 2000);
    t.ha_gone();
    t.wait(30 * MIN);
    t.ha_back();
    expect("back", t.step(), Screen::CLOCK);
  });
  test("HA back after it made the screen dark: an animation arriving within 15 s", [] {
    Panel t;
    t.f.clock = false;
    t.f.animating = true;
    t.wait(SLEEP + 2000);  // (the board kept up, dimmed)
    t.ha_gone();
    t.f.animating = false;
    t.wait(30 * MIN);
    t.ha_back();
    expect("back, no states yet", t.wait(5000), Screen::DARK);
    t.f.animating = true;
    expect("the states in", t.wait(1000), Screen::DIMMED);
  });
  test("HA back after it made the screen dark, nothing to show: stays dark", [] {
    Panel t;
    t.f.animating = true;
    t.f.clock = false;
    t.wait(SLEEP + 2000);
    t.ha_gone();
    t.f.animating = false;
    t.wait(30 * MIN);
    t.ha_back();
    expect("back", t.wait(20 * 1000), Screen::DARK);
    t.f.animating = true;
    expect("an animation after the window", t.wait(1000), Screen::DARK);
  });
  test("HA gone while dark by choice (screen off): stays dark, back too", [] {
    Panel t;
    t.f.clock = false;
    t.wait(SLEEP + 2000);
    t.ha_gone();
    expect("gone", t.wait(1000), Screen::DARK);
    t.ha_back();
    expect("back", t.wait(1000), Screen::DARK);
  });
  test("HA gone while the room is dark: stays dark (not Connecting)", [] {
    Panel t;
    t.lights(Lights::OFF);
    t.wait(SLEEP + 2000);
    t.ha_gone();
    expect("gone", t.wait(1000), Screen::DARK);
  });
  test("HA gone while in use: lit, then Connecting dimmed once idle", [] {
    Panel t;
    t.ha_gone();
    expect("gone", t.wait(5000), Screen::LIT);
    expect("idle", t.wait(SLEEP), Screen::DIMMED);
  });
  test("a touch while HA is gone (dark): lit for the sleep time, not 10 min", [] {
    Panel t;
    t.wait(SLEEP + 2000);
    t.ha_gone();
    t.wait(20 * MIN);
    t.touch();
    expect("touched", t.step(), Screen::LIT);
    expect("after the sleep time", t.wait(SLEEP + 2000), Screen::DARK);
  });
  test("HA back while in use: lit (its return isn't a touch, nor a reason to dim)", [] {
    Panel t;
    t.ha_gone();
    t.wait(5000);
    t.ha_back();
    expect("back", t.step(), Screen::LIT);
  });
  test("the boot screen while setting up / downloading: lit", [] {
    Panel t;
    t.f.board = false;
    expect("long untouched", t.wait(30 * MIN), Screen::LIT);
  });

  // ---- updates ------------------------------------------------------------
  test("an update while lit: lit until it's done", [] {
    Panel t;
    t.p.updating(true, true);
    expect("writing", t.wait(10 * MIN), Screen::LIT);
    t.p.updating(false, false);
    expect("done (failed)", t.wait(1000), Screen::CLOCK);
  });
  test("an update while on the clock: lit for its progress", [] {
    Panel t;
    t.wait(SLEEP + 2000);
    t.p.updating(true, true);
    expect("writing", t.step(), Screen::LIT);
  });
  test("an update made while dark (automatic): stays dark", [] {
    Panel t;
    t.f.clock = false;
    t.wait(SLEEP + 2000);
    t.p.updating(true, false);
    expect("writing", t.wait(2 * MIN), Screen::DARK);
    expect_true("its reason kept", t.p.why() == DarkWhy::IDLE);
  });
  test("an update that wakes a dark screen: lit, then idle as usual after a failure", [] {
    Panel t;
    t.f.clock = false;
    t.wait(SLEEP + 2000);
    t.p.updating(true, true);
    expect("writing", t.step(), Screen::LIT);
    t.p.updating(false, false);
    expect("done, still idle", t.wait(1000), Screen::DARK);
  });
  test("the room's lights during a quiet update: it stays dark until done", [] {
    Panel t;
    t.lights(Lights::OFF);
    t.wait(SLEEP + 2000);
    t.p.updating(true, false);
    t.lights(Lights::ON);
    expect("writing", t.wait(1000), Screen::DARK);
  });

  // ---- the backlight switched in HA -----------------------------------------
  test("switched off in HA: dark until touched", [] {
    Panel t;
    t.p.switched(false);
    expect("off", t.wait(5 * MIN), Screen::DARK);
    expect_true("the reason", t.p.why() == DarkWhy::CHOICE);
    expect_true("a touch only wakes", t.touch());
    expect("touched", t.step(), Screen::LIT);
  });
  test("switched off, then on in HA: lit", [] {
    Panel t;
    t.f.clock = false;
    t.wait(SLEEP + 2000);  // (dark: screen off mode)
    t.p.switched(true);
    t.used_at = t.f.now;  // (the panel counts it as use)
    expect("on", t.step(), Screen::LIT);
    expect("a moment later - not dark again at once", t.wait(5000), Screen::LIT);
  });
  test("the panel's own switching is never a choice", [] {
    Panel t;
    t.f.clock = false;
    t.wait(SLEEP + 2000);  // (dark: idle)
    t.p.switched(false);   // (its own light turned off: the callback)
    expect_true("still idle's", t.p.why() == DarkWhy::IDLE);
    t.touch();
    t.p.switched(true);  // (its own light turned on)
    expect("lit", t.step(), Screen::LIT);
  });

  // ---- the knob (the round panel) -------------------------------------------
  test("the knob: wakes a dark screen, turns nothing", [] {
    Panel t;
    t.f.clock = false;
    t.wait(SLEEP + 2000);
    expect_true("only wakes", t.touch());
    expect_true("then turns", !t.touch());
    expect("lit", t.step(), Screen::LIT);
  });

  std::printf("%s\n", failures == 0 ? "All screen policy tests passed" : "Screen policy tests FAILED");
  return failures == 0 ? 0 : 1;
}
