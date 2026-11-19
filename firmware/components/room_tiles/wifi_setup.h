#pragma once
// Wi-Fi set up on the panel (docs/DESIGN.md "Wi-Fi set up on the panel"): the
// networks nearby, a tap on one, its password typed on the screen, Connect.
// A new panel shows it by itself (no network yet - its hotspot stays up, the
// phone way beside it); Change Wi-Fi (settings, the boot screen's button)
// opens it too - then the network it had stays until the new one works.
// The 7" / 10.1" panels (the round panel: the phone way only).

#include <string>
#include <vector>

#include "esphome/core/defines.h"
#ifdef USE_WIFI
#include "esphome/components/wifi/wifi_component.h"
#endif

#include "lvgl.h"

namespace esphome::room_tiles {

class RoomTiles;
struct Fonts;

struct Network {
  std::string ssid;
  int rssi;
  bool locked;
};

class WifiSetup
#if defined(USE_WIFI) && defined(ESPHOME_WIFI_SCAN_RESULTS_LISTENERS)
    : public wifi::WiFiScanResultsListener
#endif
{
 public:
  /// Once, at setup: it hears every scan from then on.
  void attach(RoomTiles *rt);
  /// Open it: `changing` - the panel has a network (Change Wi-Fi), it stays
  /// until the new one works; else a new panel (its hotspot up).
  void open(bool changing);
  void close();
  bool is_open() const { return this->root_ != nullptr; }
  bool changing() const { return this->changing_; }
  /// Trying a network, or showing "Connected to ..." - it closes by itself
  /// (never closed from outside then: the network is saved at the end).
  bool trying() const { return this->root_ != nullptr && (this->view_ == View::CONNECTING || this->view_ == View::DONE); }
  void loop();
#if defined(USE_WIFI) && defined(ESPHOME_WIFI_SCAN_RESULTS_LISTENERS)
  void on_wifi_scan_results(const wifi::wifi_scan_vector_t<wifi::WiFiScanResult> &results) override;
#endif

 protected:
  enum class View { LIST, NAME, PASSWORD, CONNECTING, DONE, PHONE };
  std::string t_(const char *key, const char *fallback) const;
  std::string t_(const char *key, const char *fallback, const std::string &name, const std::string &old = "") const;
  void scan_();
  void show_(View v);
  void build_list_();
  void build_entry_(bool name);
  void build_connecting_();
  void build_done_();
  void build_phone_();
  void paint_entry_();
  void connect_();
  void finish_(bool ok);
  void key_(uint32_t id);
  lv_obj_t *page_(const std::string &title, bool closable);
  lv_obj_t *button_(lv_obj_t *parent, int w, int h, const std::string &text, bool primary);

  RoomTiles *rt_{nullptr};
  lv_obj_t *root_{nullptr};    // (the whole screen, on the top layer)
  lv_obj_t *list_{nullptr};    // the networks
  lv_obj_t *status_{nullptr};  // "Looking for networks..." / "No networks found"
  lv_obj_t *field_{nullptr};   // what's typed
  lv_obj_t *error_{nullptr};   // under it: why the last try didn't work
  lv_obj_t *keys_{nullptr};    // the keyboard
  View view_{View::LIST};
  bool changing_{false};
  std::vector<Network> networks_;
  bool scanning_{false};
  uint32_t scan_ms_{0};
  // the entry: the network picked, what's typed, shown or hidden
  std::string ssid_, typed_, error_text_;
  bool locked_{true};
  bool other_{false};  // (a network typed in: "Other network...")
  bool show_typed_{false};
  int shift_{0};  // 0 lower, 1 upper, 2 numbers / symbols, 3 more symbols
  // trying it: since when, and the network it had (to go back to)
  uint32_t try_ms_{0};
  uint32_t try_for_ms_{0};
  bool had_old_{false};
  std::string old_ssid_;
#ifdef USE_WIFI
  wifi::WiFiAP old_;
#endif
  uint32_t done_ms_{0};
  uint32_t touched_ms_{0};
};

}  // namespace esphome::room_tiles
