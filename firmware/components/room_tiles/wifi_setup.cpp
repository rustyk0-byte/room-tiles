// Wi-Fi set up on the panel (wifi_setup.h): the screens, and trying a
// network the way ESPHome's own Improv does - tried first, saved only once
// the panel really is on it; if it isn't within the time, the network it had
// comes back (Change Wi-Fi), or the hotspot stays (a new panel). The router
// turning the password away twice ends it at once (a mesh router may turn
// the first try away); one that never answers: the whole time.

#include "wifi_setup.h"

#include <algorithm>
#include <cstring>

#ifdef USE_WIFI
#include <atomic>

#include <esp_event.h>
#include <esp_wifi.h>
#endif

#include "esphome/core/application.h"
#include "esphome/core/log.h"

#include "board.h"
#include "room_tiles.h"

namespace esphome::room_tiles {

static const char *const TAG = "room_tiles.wifi";

static constexpr int W = 1024, H = 600, PAD = 32;
static constexpr int ROW_H = 64;  // (a network: easy to hit on the 7")
static constexpr uint32_t RESCAN_MS = 20000;  // (nothing found yet: looked again by itself)
static constexpr uint8_t RESCANS = 3;
static constexpr uint32_t SCAN_GIVE_UP_MS = 15000;
static constexpr uint32_t TRY_NEW_MS = 45000;      // (a new panel: a few tries' time)
static constexpr uint32_t TRY_SWITCH_MS = 90000;   // (leaving a network first takes longer - Improv's)
static constexpr uint32_t DONE_SHOWN_MS = 2500;
static constexpr uint32_t UNTOUCHED_MS = 3 * 60 * 1000;  // (Change Wi-Fi left open: it closes)
static constexpr uint8_t REFUSED_ENOUGH = 2;  // (the router turned the password away: twice - not a mesh's first no)

#ifdef USE_WIFI
// the router's "no" to the network being tried (the Wi-Fi event task): its
// name, and how often - read in loop(). Listened to only while a network is
// tried (never at start-up: nothing else changes then)
static char s_want[33];
static esp_event_handler_instance_t s_listening = nullptr;
static std::atomic<bool> s_watching{false};
static std::atomic<uint8_t> s_refused{0};

static void on_wifi_event(void *, esp_event_base_t base, int32_t id, void *data) {
  if (base != WIFI_EVENT || id != WIFI_EVENT_STA_DISCONNECTED || !s_watching.load())
    return;
  const auto *it = static_cast<const wifi_event_sta_disconnected_t *>(data);
  switch (it->reason) {
    case WIFI_REASON_AUTH_FAIL:
    case WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT:
    case WIFI_REASON_HANDSHAKE_TIMEOUT:
    case WIFI_REASON_MIC_FAILURE:
    case WIFI_REASON_802_1X_AUTH_FAILED:
      break;
    default:
      return;  // (not found, out of range... - the whole time, as before)
  }
  if (it->ssid_len == strlen(s_want) && memcmp(it->ssid, s_want, it->ssid_len) == 0)
    s_refused.fetch_add(1);
}
#endif

// a network's signal as 0..3 bars (its row's glyph)
static int bars(int rssi) { return rssi >= -55 ? 3 : rssi >= -65 ? 2 : rssi >= -75 ? 1 : 0; }

static const char *const BKSP = "\U000F0B5C";   // mdi:backspace-outline (rt_font_keys)
static const char *const SHIFT = "\U000F0636";  // mdi:apple-keyboard-shift
static const char *const SPACE = " ";

// the keyboard: letters, then numbers and the usual symbols, then the rest
// of a password's printable characters
static const char *const MAP_LOWER[] = {"q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "\n",       //
                                        "a", "s", "d", "f", "g", "h", "j", "k", "l", "\n",            //
                                        SHIFT, "z", "x", "c", "v", "b", "n", "m", BKSP, "\n",         //
                                        "123", SPACE, ".", ""};
static const char *const MAP_UPPER[] = {"Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P", "\n",       //
                                        "A", "S", "D", "F", "G", "H", "J", "K", "L", "\n",            //
                                        SHIFT, "Z", "X", "C", "V", "B", "N", "M", BKSP, "\n",         //
                                        "123", SPACE, ".", ""};
static const char *const MAP_NUM[] = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "\n",          //
                                      "-", "/", ":", ";", "(", ")", "$", "&", "@", "\"", "\n",         //
                                      "#+=", ".", ",", "?", "!", "'", BKSP, "\n",                      //
                                      "ABC", SPACE, ".", ""};
static const char *const MAP_SYM[] = {"[", "]", "{", "}", "#", "%", "^", "*", "+", "=", "\n",          //
                                      "_", "\\", "|", "~", "<", ">", "`", "\n",                        //
                                      "123", ".", ",", "?", "!", "'", BKSP, "\n",                      //
                                      "ABC", SPACE, ".", ""};
static const char *const *const MAPS[] = {MAP_LOWER, MAP_UPPER, MAP_NUM, MAP_SYM};

static std::string fill(std::string s, const char *what, const std::string &with) {
  const std::string key = std::string("{") + what + "}";
  for (size_t at = s.find(key); at != std::string::npos; at = s.find(key, at + with.size()))
    s.replace(at, key.size(), with);
  return s;
}

void WifiSetup::attach(RoomTiles *rt) {
  this->rt_ = rt;
#if defined(USE_WIFI) && defined(ESPHOME_WIFI_SCAN_RESULTS_LISTENERS)
  if (wifi::global_wifi_component != nullptr)
    wifi::global_wifi_component->add_scan_results_listener(this);
#endif
}

std::string WifiSetup::t_(const char *key, const char *fallback) const { return this->rt_->boot_text(key, fallback); }

std::string WifiSetup::t_(const char *key, const char *fallback, const std::string &name, const std::string &old) const {
  return fill(fill(this->t_(key, fallback), "name", name), "old", old);
}

void WifiSetup::open(bool changing) {
  if (this->rt_ == nullptr || this->root_ != nullptr || this->rt_->board().fonts().bar == nullptr)
    return;  // (not before the board's fonts are hooked up)
  this->changing_ = changing;
  this->touched_ms_ = millis();
  this->root_ = lv_obj_create(lv_layer_top());
  lv_obj_remove_style_all(this->root_);
  lv_obj_set_size(this->root_, W, H);
  lv_obj_set_style_bg_color(this->root_, lv_color_hex(this->rt_->color("page", 0x000000)), 0);
  lv_obj_set_style_bg_opa(this->root_, LV_OPA_COVER, 0);
  lv_obj_add_flag(this->root_, LV_OBJ_FLAG_CLICKABLE);  // (nothing under it takes a tap)
  lv_obj_remove_flag(this->root_, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_add_event_cb(
      this->root_, [](lv_event_t *e) { static_cast<WifiSetup *>(lv_event_get_user_data(e))->touched_ms_ = millis(); },
      LV_EVENT_PRESSED, this);
  this->rescans_ = 0;
  this->redraw_list_ = false;
  ESP_LOGI(TAG, "Wi-Fi setup open (%s)", changing ? "change" : "new panel");
  this->show_(View::LIST);
  this->scan_();
}

void WifiSetup::close() {
  if (this->root_ == nullptr)
    return;
  if (this->view_ == View::CONNECTING) {
    // (left while trying: on it already - saved; else back to how it was)
    bool on = false;
#ifdef USE_WIFI
    char buf[wifi::SSID_BUFFER_SIZE];
    auto *w = wifi::global_wifi_component;
    on = w != nullptr && w->is_connected() && strcmp(w->wifi_ssid_to(buf), this->ssid_.c_str()) == 0;
#endif
    this->finish_(on);
  }
  lv_obj_delete(this->root_);
  this->root_ = this->list_ = this->status_ = this->field_ = this->error_ = this->keys_ = nullptr;
  this->typed_.clear();
  this->error_text_.clear();
}

// ---- scanning ---------------------------------------------------------------------------

void WifiSetup::scan_() {
#ifdef USE_WIFI
  auto *w = wifi::global_wifi_component;
  if (w == nullptr || w->is_disabled())
    return;
  // on a network: a scan of every channel, the panel staying on it (ESPHome
  // fills its results and hands them to us - its own roaming check skips
  // the scan while the signal is good); else (the hotspot up, nothing
  // saved) ESPHome's scan, as Improv does
  if (w->is_connected()) {
    wifi_scan_config_t config{};
    config.show_hidden = false;
    config.scan_type = WIFI_SCAN_TYPE_ACTIVE;
    config.scan_time.active.min = 100;
    config.scan_time.active.max = 300;
    const esp_err_t err = esp_wifi_scan_start(&config, false);
    if (err != ESP_OK) {
      ESP_LOGW(TAG, "Scan didn't start: %s", esp_err_to_name(err));
      this->scanning_ = false;
      this->scan_ms_ = millis();
      return;
    }
  } else if (!w->has_sta()) {
    w->start_scanning();
  } else {
    // (a network saved, not on it: ESPHome keeps trying it, scanning on
    // each round - those scans fill the list; one of ours would be refused
    // mid-connect. "Looking..." meanwhile, never "No networks found")
    ESP_LOGD(TAG, "Connecting: the list comes from ESPHome's scans");
  }
  this->scanning_ = true;
  this->scan_ms_ = millis();
  if (this->status_ != nullptr && this->networks_.empty())
    lv_label_set_text(this->status_, this->t_("panel.wifi_looking", "Looking for networks…").c_str());
#endif
}

#if defined(USE_WIFI) && defined(ESPHOME_WIFI_SCAN_RESULTS_LISTENERS)
void WifiSetup::on_wifi_scan_results(const wifi::wifi_scan_vector_t<wifi::WiFiScanResult> &results) {
  if (this->root_ == nullptr)
    return;
  // one row per network name (its strongest access point), hidden ones left out
  std::vector<Network> found;
  for (const auto &r : results) {
    const std::string ssid = r.get_ssid().str();
    if (ssid.empty() || r.get_is_hidden())
      continue;
    auto it = std::find_if(found.begin(), found.end(), [&](const Network &n) { return n.ssid == ssid; });
    if (it == found.end())
      found.push_back(Network{ssid, r.get_rssi(), r.get_with_auth()});
    else if (r.get_rssi() > it->rssi)
      it->rssi = r.get_rssi();
  }
  std::sort(found.begin(), found.end(), [](const Network &a, const Network &b) { return a.rssi > b.rssi; });
  this->scanning_ = false;
  if (found.empty() && !this->networks_.empty())
    return;  // (an empty scan - a roaming check that saw nothing: keep the list)
  // the same rows as shown (names, order, locks, bars): nothing to redraw
  bool same = found.size() == this->networks_.size();
  for (size_t i = 0; same && i < found.size(); i++)
    same = found[i].ssid == this->networks_[i].ssid && found[i].locked == this->networks_[i].locked &&
           bars(found[i].rssi) == bars(this->networks_[i].rssi);
  if (same)
    return;
  this->networks_ = std::move(found);
  if (this->view_ == View::LIST)
    this->redraw_list_ = true;  // (in loop(): never under a finger or mid-scroll)
}
#endif

// ---- the screens ------------------------------------------------------------------------

// a full screen: its title top left, a close (X) top right when it can be left
lv_obj_t *WifiSetup::page_(const std::string &title, bool closable) {
  lv_obj_clean(this->root_);
  this->list_ = this->status_ = this->field_ = this->error_ = this->keys_ = nullptr;
  const Fonts &f = this->rt_->board().fonts();
  lv_obj_t *t = lv_label_create(this->root_);
  lv_label_set_text(t, title.c_str());
  lv_label_set_long_mode(t, LV_LABEL_LONG_MODE_DOTS);
  lv_obj_set_width(t, W - 2 * PAD - 80);
  lv_obj_set_style_text_font(t, f.bar, 0);
  lv_obj_set_style_text_color(t, lv_color_hex(this->rt_->color("text", 0xFFFFFF)), 0);
  lv_obj_set_pos(t, PAD, 22);
  if (closable) {
    lv_obj_t *x = bar_button(this->root_, this->rt_->color("button", 0x333333), this->rt_->color("tileBorder", 0x4A4A4A), 8);
    lv_obj_align(x, LV_ALIGN_TOP_RIGHT, -12, 10);
    lv_obj_add_event_cb(
        x, [](lv_event_t *e) { lv_async_call([](void *p) { static_cast<WifiSetup *>(p)->close(); }, lv_event_get_user_data(e)); },
        LV_EVENT_CLICKED, this);
    lv_obj_t *g = lv_label_create(x);
    lv_label_set_text(g, "\U000F0156");  // mdi:close
    lv_obj_set_style_text_font(g, f.glyph, 0);
    lv_obj_set_style_text_color(g, lv_color_hex(this->rt_->color("accent", 0x4B9EF3)), 0);
    lv_obj_center(g);
  }
  return t;
}

lv_obj_t *WifiSetup::button_(lv_obj_t *parent, int w, int h, const std::string &text, bool primary) {
  const Fonts &f = this->rt_->board().fonts();
  lv_obj_t *b = lv_button_create(parent);
  lv_obj_remove_style_all(b);
  lv_obj_set_size(b, w, h);
  lv_obj_set_style_radius(b, 10, 0);
  lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
  lv_obj_set_style_bg_color(b, lv_color_hex(primary ? this->rt_->color("accent", 0x4B9EF3) : this->rt_->color("button", 0x333333)), 0);
  lv_obj_t *l = lv_label_create(b);
  lv_label_set_text(l, text.c_str());
  lv_obj_set_style_text_font(l, f.name, 0);
  lv_obj_set_style_text_color(l, lv_color_hex(primary ? this->rt_->color("onAccent", 0xFFFFFF) : this->rt_->color("text", 0xFFFFFF)), 0);
  lv_obj_center(l);
  return b;
}

void WifiSetup::show_(View v) {
  this->view_ = v;
  switch (v) {
    case View::LIST:
      this->build_list_();
      break;
    case View::NAME:
      this->build_entry_(true);
      break;
    case View::PASSWORD:
      this->build_entry_(false);
      break;
    case View::CONNECTING:
      this->build_connecting_();
      break;
    case View::DONE:
      this->build_done_();
      break;
    case View::PHONE:
      this->build_phone_();
      break;
  }
}

// the networks nearby (strongest first, a lock on secured ones), "Other
// network..."; under them the phone way - a new panel: its hotspot's name;
// Change Wi-Fi: "Set up with your phone instead"
void WifiSetup::build_list_() {
  const Fonts &f = this->rt_->board().fonts();
  const uint32_t text = this->rt_->color("text", 0xFFFFFF), dim = this->rt_->color("textSecondary", 0x9E9E9E);
  // (kept where it was when the list is drawn again after a scan)
  const int keep_y = this->list_ != nullptr ? (int) lv_obj_get_scroll_y(this->list_) : 0;
  this->redraw_list_ = false;
  this->page_(this->t_("panel.wifi_pick", "Pick your Wi-Fi network"), this->changing_);
  this->list_ = lv_obj_create(this->root_);
  lv_obj_remove_style_all(this->list_);
  lv_obj_set_pos(this->list_, PAD, 80);
  lv_obj_set_size(this->list_, W - 2 * PAD, 400);
  lv_obj_set_flex_flow(this->list_, LV_FLEX_FLOW_COLUMN);
  lv_obj_set_style_pad_row(this->list_, 8, 0);
  lv_obj_set_scroll_dir(this->list_, LV_DIR_VER);
  lv_obj_set_scrollbar_mode(this->list_, LV_SCROLLBAR_MODE_AUTO);
  auto row = [&](const std::string &name, const char *glyph) {
    lv_obj_t *r = lv_button_create(this->list_);
    lv_obj_remove_style_all(r);
    lv_obj_set_size(r, W - 2 * PAD - 16, ROW_H);
    lv_obj_set_style_radius(r, 10, 0);
    lv_obj_set_style_bg_opa(r, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(r, lv_color_hex(this->rt_->color("button", 0x333333)), 0);
    lv_obj_add_flag(r, LV_OBJ_FLAG_SCROLL_CHAIN_VER);
    if (glyph != nullptr) {
      lv_obj_t *g = lv_label_create(r);
      lv_label_set_text(g, glyph);
      lv_obj_set_style_text_font(g, f.glyph, 0);
      lv_obj_set_style_text_color(g, lv_color_hex(this->rt_->color("accent", 0x4B9EF3)), 0);
      lv_obj_align(g, LV_ALIGN_LEFT_MID, 18, 0);
    }
    lv_obj_t *l = lv_label_create(r);
    lv_label_set_text(l, name.c_str());
    lv_label_set_long_mode(l, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_width(l, W - 2 * PAD - 16 - 90);
    lv_obj_set_style_text_font(l, f.name, 0);
    lv_obj_set_style_text_color(l, lv_color_hex(text), 0);
    lv_obj_align(l, LV_ALIGN_LEFT_MID, 70, 0);
    return r;
  };
  static const char *const OPEN[] = {"\U000F091F", "\U000F0922", "\U000F0925", "\U000F0928"};    // wifi-strength-1..4
  static const char *const LOCKED[] = {"\U000F0921", "\U000F0924", "\U000F0927", "\U000F092A"};  // ... -lock
  // the network it's on (Change Wi-Fi): first, with a check mark - a tap on it does nothing
  std::string current;
#ifdef USE_WIFI
  if (wifi::global_wifi_component != nullptr && wifi::global_wifi_component->is_connected()) {
    char buf[wifi::SSID_BUFFER_SIZE];
    current = wifi::global_wifi_component->wifi_ssid_to(buf);
  }
#endif
  // (the rows as drawn: a tap picks the row's own network, whatever a scan
  // has changed in networks_ meanwhile)
  this->shown_.clear();
  for (const Network &n : this->networks_)
    if (n.ssid == current)
      this->shown_.insert(this->shown_.begin(), n);
    else
      this->shown_.push_back(n);
  for (size_t i = 0; i < this->shown_.size(); i++) {
    const Network &n = this->shown_[i];
    lv_obj_t *r = row(n.ssid, n.locked ? LOCKED[bars(n.rssi)] : OPEN[bars(n.rssi)]);
    if (!current.empty() && n.ssid == current) {
      lv_obj_t *on = lv_label_create(r);
      lv_label_set_text(on, "\U000F012C");  // mdi:check (rt_icon_menu)
      lv_obj_set_style_text_font(on, f.menu, 0);
      lv_obj_set_style_text_color(on, lv_color_hex(this->rt_->color("accent", 0x4B9EF3)), 0);
      lv_obj_align(on, LV_ALIGN_RIGHT_MID, -20, 0);
      continue;  // (on it already: nothing to pick)
    }
    lv_obj_set_user_data(r, (void *) (uintptr_t) i);
    lv_obj_add_event_cb(
        r,
        [](lv_event_t *e) {
          auto *self = static_cast<WifiSetup *>(lv_event_get_user_data(e));
          const size_t k = (size_t) (uintptr_t) lv_obj_get_user_data(lv_event_get_current_target_obj(e));
          if (k >= self->shown_.size())
            return;
          self->ssid_ = self->shown_[k].ssid;
          self->locked_ = self->shown_[k].locked;
          self->other_ = false;
          self->typed_.clear();
          self->error_text_.clear();
          lv_async_call(
              [](void *p) {
                auto *s = static_cast<WifiSetup *>(p);
                if (s->locked_)
                  s->show_(View::PASSWORD);
                else
                  s->connect_();  // (an open network: nothing to type)
              },
              self);
        },
        LV_EVENT_CLICKED, this);
  }
  // a network that doesn't show its name: typed in
  lv_obj_t *other = row(this->t_("panel.wifi_other", "Other network…"), nullptr);
  lv_obj_add_event_cb(
      other,
      [](lv_event_t *e) {
        auto *self = static_cast<WifiSetup *>(lv_event_get_user_data(e));
        self->ssid_.clear();
        self->typed_.clear();
        self->error_text_.clear();
        self->locked_ = true;
        self->other_ = true;
        lv_async_call([](void *p) { static_cast<WifiSetup *>(p)->show_(View::NAME); }, self);
      },
      LV_EVENT_CLICKED, this);
  if (!this->error_text_.empty()) {
    // (an open network that didn't connect: why, above the list)
    lv_obj_t *why = lv_label_create(this->list_);
    lv_label_set_text(why, this->error_text_.c_str());
    lv_label_set_long_mode(why, LV_LABEL_LONG_MODE_WRAP);
    lv_obj_set_width(why, W - 2 * PAD - 16);
    lv_obj_set_style_text_font(why, f.name_s, 0);
    lv_obj_set_style_text_color(why, lv_color_hex(this->rt_->color("heatStrong", 0xF44336)), 0);
    lv_obj_move_to_index(why, 0);
  }
  if (this->networks_.empty()) {
    this->status_ = lv_label_create(this->list_);
    lv_label_set_text(this->status_, (this->scanning_ ? this->t_("panel.wifi_looking", "Looking for networks…")
                                                      : this->t_("panel.wifi_none", "No networks found"))
                                         .c_str());
    lv_obj_set_style_text_font(this->status_, f.name_s, 0);
    lv_obj_set_style_text_color(this->status_, lv_color_hex(dim), 0);
    lv_obj_move_to_index(this->status_, 0);
  }
  lv_obj_update_layout(this->list_);
  lv_obj_scroll_to_y(this->list_, keep_y, LV_ANIM_OFF);
  // under the list: look again, and the phone way
  lv_obj_t *again = this->button_(this->root_, 220, 56, "", false);
  lv_obj_align(again, LV_ALIGN_BOTTOM_RIGHT, -PAD, -24);
  lv_obj_t *al = lv_obj_get_child(again, 0);
  lv_label_set_text(al, this->t_("panel.wifi_again", "Look again").c_str());
  lv_obj_add_event_cb(
      again,
      [](lv_event_t *e) {
        auto *self = static_cast<WifiSetup *>(lv_event_get_user_data(e));
        self->rescans_ = 0;
        self->scan_();
      },
      LV_EVENT_CLICKED, this);
  if (this->changing_) {
    lv_obj_t *phone = this->button_(this->root_, 420, 56, this->t_("panel.wifi_phone_instead", "Set up with your phone instead"), false);
    lv_obj_align(phone, LV_ALIGN_BOTTOM_LEFT, PAD, -24);
    lv_obj_add_event_cb(
        phone,
        [](lv_event_t *e) {
          lv_async_call([](void *p) { static_cast<WifiSetup *>(p)->show_(View::PHONE); }, lv_event_get_user_data(e));
        },
        LV_EVENT_CLICKED, this);
  } else {
    const std::string ap = this->rt_->hotspot_name();
    lv_obj_t *hint = lv_label_create(this->root_);
    lv_label_set_text(hint, this->t_("panel.wifi_phone_hint", "Or with your phone: join the network \"{name}\"", ap).c_str());
    lv_label_set_long_mode(hint, LV_LABEL_LONG_MODE_WRAP);
    lv_obj_set_width(hint, W - 2 * PAD - 220 - 24);
    lv_obj_set_style_text_font(hint, f.name_s, 0);
    lv_obj_set_style_text_color(hint, lv_color_hex(dim), 0);
    lv_obj_align(hint, LV_ALIGN_BOTTOM_LEFT, PAD, -38);
  }
}

// typing: the network's name ("Other network...") or its password - the
// field, Show / Hide, Back and Connect (or Next), the keyboard under them
void WifiSetup::build_entry_(bool name) {
  const Fonts &f = this->rt_->board().fonts();
  const uint32_t text = this->rt_->color("text", 0xFFFFFF);
  this->shift_ = 0;
  this->show_typed_ = name;  // (a name shows as typed; a password hidden)
  this->page_(name ? this->t_("panel.wifi_name_ask", "Network name")
                   : this->t_("panel.wifi_password_for", "Password for \"{name}\"", this->ssid_),
              this->changing_);
  lv_obj_t *box = lv_obj_create(this->root_);
  lv_obj_remove_style_all(box);
  lv_obj_set_pos(box, PAD, 80);
  lv_obj_set_size(box, W - 2 * PAD - 92, 60);
  lv_obj_set_style_radius(box, 10, 0);
  lv_obj_set_style_border_width(box, 2, 0);
  lv_obj_set_style_border_color(box, lv_color_hex(this->rt_->color("accent", 0x4B9EF3)), 0);
  lv_obj_set_style_bg_opa(box, LV_OPA_COVER, 0);
  lv_obj_set_style_bg_color(box, lv_color_hex(this->rt_->color("tile", 0x1E1E1E)), 0);
  lv_obj_remove_flag(box, LV_OBJ_FLAG_SCROLLABLE);
  this->field_ = lv_label_create(box);  // (as wide as what's typed: the box shows its end)
  lv_obj_set_style_text_font(this->field_, f.name, 0);
  lv_obj_set_style_text_color(this->field_, lv_color_hex(text), 0);
  lv_obj_align(this->field_, LV_ALIGN_LEFT_MID, 16, 0);
  if (!name) {
    // Show / Hide the password (its eye)
    lv_obj_t *eye = bar_button(this->root_, this->rt_->color("button", 0x333333), this->rt_->color("tileBorder", 0x4A4A4A), 8);
    lv_obj_set_size(eye, 76, 60);
    lv_obj_set_pos(eye, W - PAD - 76, 80);
    lv_obj_t *g = lv_label_create(eye);
    lv_obj_set_style_text_font(g, f.glyph, 0);
    lv_obj_set_style_text_color(g, lv_color_hex(text), 0);
    lv_obj_center(g);
    lv_label_set_text(g, "\U000F0208");  // mdi:eye
    lv_obj_add_event_cb(
        eye,
        [](lv_event_t *e) {
          auto *self = static_cast<WifiSetup *>(lv_event_get_user_data(e));
          self->show_typed_ = !self->show_typed_;
          lv_label_set_text(lv_obj_get_child(lv_event_get_current_target_obj(e), 0), self->show_typed_ ? "\U000F0209" : "\U000F0208");
          self->paint_entry_();
        },
        LV_EVENT_CLICKED, this);
  }
  this->error_ = lv_label_create(this->root_);
  lv_label_set_long_mode(this->error_, LV_LABEL_LONG_MODE_WRAP);
  lv_obj_set_width(this->error_, W - 2 * PAD - 2 * 200 - 32);
  lv_obj_set_style_text_font(this->error_, f.name_s, 0);
  lv_obj_set_style_text_color(this->error_, lv_color_hex(this->rt_->color("heatStrong", 0xF44336)), 0);
  lv_obj_set_pos(this->error_, PAD + 200 + 16, 156);
  lv_label_set_text(this->error_, this->error_text_.c_str());
  lv_obj_t *back = this->button_(this->root_, 200, 56, this->t_("common.back", "Back"), false);
  lv_obj_set_pos(back, PAD, 156);
  lv_obj_add_event_cb(
      back,
      [](lv_event_t *e) {
        auto *self = static_cast<WifiSetup *>(lv_event_get_user_data(e));
        const bool typed_name = self->view_ == View::PASSWORD && self->other_;
        lv_async_call(
            typed_name ? (lv_async_cb_t) [](void *p) {
              auto *s = static_cast<WifiSetup *>(p);
              s->typed_ = s->ssid_;  // (back to the name it typed)
              s->show_(View::NAME);
            }
                       : (lv_async_cb_t) [](void *p) { static_cast<WifiSetup *>(p)->show_(View::LIST); },
            self);
      },
      LV_EVENT_CLICKED, this);
  lv_obj_t *go = this->button_(this->root_, 200, 56, this->t_("panel.wifi_connect", "Connect"), true);
  lv_obj_set_pos(go, W - PAD - 200, 156);
  lv_obj_add_event_cb(
      go,
      [](lv_event_t *e) {
        auto *self = static_cast<WifiSetup *>(lv_event_get_user_data(e));
        if (self->typed_.empty() && self->view_ == View::NAME)
          return;  // (a name first)
        lv_async_call(
            [](void *p) {
              auto *s = static_cast<WifiSetup *>(p);
              if (s->view_ == View::NAME) {
                s->ssid_ = s->typed_;  // then its password (empty: an open network)
                s->typed_.clear();
                s->show_(View::PASSWORD);
              } else {
                s->connect_();  // (an empty password: an open network)
              }
            },
            self);
      },
      LV_EVENT_CLICKED, this);
  // the keyboard: 4 rows, keys ~93 x 83 px
  this->keys_ = lv_buttonmatrix_create(this->root_);
  lv_obj_set_size(this->keys_, W - 2 * 12, 600 - 232 - 12);
  lv_obj_set_pos(this->keys_, 12, 232);
  lv_obj_set_style_bg_opa(this->keys_, LV_OPA_TRANSP, 0);
  lv_obj_set_style_border_width(this->keys_, 0, 0);
  lv_obj_set_style_pad_all(this->keys_, 0, 0);
  lv_obj_set_style_pad_gap(this->keys_, 8, 0);
  lv_obj_set_style_radius(this->keys_, 10, LV_PART_ITEMS);
  lv_obj_set_style_bg_opa(this->keys_, LV_OPA_COVER, LV_PART_ITEMS);
  lv_obj_set_style_bg_color(this->keys_, lv_color_hex(this->rt_->color("button", 0x333333)), LV_PART_ITEMS);
  lv_obj_set_style_bg_color(this->keys_, lv_color_hex(this->rt_->color("accent", 0x4B9EF3)),
                            (lv_style_selector_t) LV_PART_ITEMS | LV_STATE_PRESSED);
  lv_obj_set_style_text_font(this->keys_, f.keys != nullptr ? f.keys : f.name, LV_PART_ITEMS);
  lv_obj_set_style_text_color(this->keys_, lv_color_hex(text), LV_PART_ITEMS);
  lv_obj_set_style_border_width(this->keys_, 0, LV_PART_ITEMS);
  lv_obj_set_style_shadow_width(this->keys_, 0, LV_PART_ITEMS);
  lv_obj_add_event_cb(
      this->keys_,
      [](lv_event_t *e) {
        auto *self = static_cast<WifiSetup *>(lv_event_get_user_data(e));
        self->key_(lv_buttonmatrix_get_selected_button(self->keys_));
      },
      LV_EVENT_VALUE_CHANGED, this);
  this->paint_entry_();
}

// the keyboard's keys for the current layer, and what's typed (or its *s)
void WifiSetup::paint_entry_() {
  if (this->field_ == nullptr)
    return;
  if (this->keys_ != nullptr) {
    lv_buttonmatrix_set_map(this->keys_, (const char **) MAPS[this->shift_]);
    // the space bar wide, the layer / shift / backspace keys a little wider
    const char *const *map = MAPS[this->shift_];
    // (set_map keeps the keys' states when their number stays: cleared first)
    lv_buttonmatrix_clear_button_ctrl_all(this->keys_, LV_BUTTONMATRIX_CTRL_CHECKED);
    uint32_t id = 0;
    for (int i = 0; map[i][0] != '\0'; i++) {
      if (strcmp(map[i], "\n") == 0)
        continue;
      const char *k = map[i];
      const int w = k == SPACE ? 6 : (k == SHIFT || k == BKSP || strlen(k) > 1) ? 2 : 1;
      lv_buttonmatrix_set_button_width(this->keys_, id, w);
      if (k == SHIFT && this->shift_ == 1)
        lv_buttonmatrix_set_button_ctrl(this->keys_, id, LV_BUTTONMATRIX_CTRL_CHECKED);
      id++;
    }
    lv_obj_set_style_bg_color(this->keys_, lv_color_hex(this->rt_->color("accent", 0x4B9EF3)),
                              (lv_style_selector_t) LV_PART_ITEMS | LV_STATE_CHECKED);
  }
  const std::string shown = this->show_typed_ ? this->typed_ : std::string(this->typed_.size(), '*');
  // (the end of a long entry stays in view: what's typed last)
  lv_label_set_text(this->field_, shown.empty() ? " " : shown.c_str());
  lv_point_t sz;
  lv_text_get_size(&sz, shown.c_str(), lv_obj_get_style_text_font(this->field_, LV_PART_MAIN), 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);
  const int room = W - 2 * PAD - 92 - 32;  // (the box's inside)
  lv_obj_set_style_translate_x(this->field_, sz.x > room ? room - sz.x : 0, 0);
}

void WifiSetup::key_(uint32_t id) {
  if (id == LV_BUTTONMATRIX_BUTTON_NONE)
    return;
  const char *k = lv_buttonmatrix_get_button_text(this->keys_, id);
  if (k == nullptr)
    return;
  this->touched_ms_ = millis();
  if (strcmp(k, BKSP) == 0) {
    if (!this->typed_.empty()) {
      // (one character back - UTF-8: its whole sequence)
      size_t n = this->typed_.size() - 1;
      while (n > 0 && (this->typed_[n] & 0xC0) == 0x80)
        n--;
      this->typed_.erase(n);
    }
  } else if (strcmp(k, SHIFT) == 0) {
    this->shift_ = this->shift_ == 1 ? 0 : 1;
  } else if (strcmp(k, "123") == 0) {
    this->shift_ = 2;
  } else if (strcmp(k, "#+=") == 0) {
    this->shift_ = 3;
  } else if (strcmp(k, "ABC") == 0) {
    this->shift_ = 0;
  } else if (this->typed_.size() < (this->view_ == View::NAME ? 32u : 63u)) {
    this->typed_ += k;
    if (this->shift_ == 1)
      this->shift_ = 0;  // (one capital, as on a phone)
  }
  this->paint_entry_();
}

void WifiSetup::build_connecting_() {
  const Fonts &f = this->rt_->board().fonts();
  this->page_("", false);
  lv_obj_t *l = lv_label_create(this->root_);
  lv_label_set_text(l, this->t_("panel.wifi_connecting_to", "Connecting to \"{name}\"…", this->ssid_).c_str());
  lv_label_set_long_mode(l, LV_LABEL_LONG_MODE_WRAP);
  lv_obj_set_width(l, W - 4 * PAD);
  lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_style_text_font(l, f.bar, 0);
  lv_obj_set_style_text_color(l, lv_color_hex(this->rt_->color("text", 0xFFFFFF)), 0);
  lv_obj_align(l, LV_ALIGN_CENTER, 0, -30);
  lv_obj_t *cancel = this->button_(this->root_, 220, 56, this->t_("common.cancel", "Cancel"), false);
  lv_obj_align(cancel, LV_ALIGN_CENTER, 0, 70);
  lv_obj_add_event_cb(
      cancel,
      [](lv_event_t *e) {
        lv_async_call(
            [](void *p) {
              auto *s = static_cast<WifiSetup *>(p);
              if (s->root_ == nullptr || s->view_ != View::CONNECTING)
                return;  // (the try ended meanwhile - saved, or already undone)
              s->finish_(false);
              s->error_text_.clear();  // (stopped on purpose: no "check the password")
              s->show_(s->locked_ ? View::PASSWORD : View::LIST);
            },
            lv_event_get_user_data(e));
      },
      LV_EVENT_CLICKED, this);
}

void WifiSetup::build_done_() {
  const Fonts &f = this->rt_->board().fonts();
  this->page_("", false);
  lv_obj_t *l = lv_label_create(this->root_);
  lv_label_set_text(l, this->t_("panel.wifi_connected", "Connected to \"{name}\"", this->ssid_).c_str());
  lv_label_set_long_mode(l, LV_LABEL_LONG_MODE_WRAP);
  lv_obj_set_width(l, W - 4 * PAD);
  lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_style_text_font(l, f.bar, 0);
  lv_obj_set_style_text_color(l, lv_color_hex(this->rt_->color("text", 0xFFFFFF)), 0);
  lv_obj_center(l);
}

// "Set up with your phone instead" (Change Wi-Fi): asked first - the panel
// forgets its network and restarts into its hotspot (as before)
// MIRRORED: board_strip.cpp confirm_strip_wifi_ (the round panel's) - a change here must be made there too.
void WifiSetup::build_phone_() {
  const Fonts &f = this->rt_->board().fonts();
  this->page_(this->t_("panel.wifi_phone_instead", "Set up with your phone instead"), true);
  lv_obj_t *ask = lv_label_create(this->root_);
  lv_label_set_text(ask, this->t_("panel.wifi_change_ask",
                                  "The panel restarts with its own Wi-Fi network. On your phone, join \"{name}\" - a page opens to "
                                  "pick your Wi-Fi. If it doesn't, open 192.168.4.1 in your phone's browser.",
                                  this->rt_->hotspot_name())
                             .c_str());
  lv_label_set_long_mode(ask, LV_LABEL_LONG_MODE_WRAP);
  lv_obj_set_width(ask, W - 4 * PAD);
  lv_obj_set_style_text_font(ask, f.name, 0);
  lv_obj_set_style_text_color(ask, lv_color_hex(this->rt_->color("text", 0xFFFFFF)), 0);
  lv_obj_set_pos(ask, PAD, 110);
  lv_obj_t *back = this->button_(this->root_, 220, 56, this->t_("common.back", "Back"), false);
  lv_obj_set_pos(back, PAD, 280);
  lv_obj_add_event_cb(
      back, [](lv_event_t *e) { lv_async_call([](void *p) { static_cast<WifiSetup *>(p)->show_(View::LIST); }, lv_event_get_user_data(e)); },
      LV_EVENT_CLICKED, this);
  lv_obj_t *go = this->button_(this->root_, 300, 56, this->t_("screen.restart", "Restart"), true);
  lv_obj_set_pos(go, W - PAD - 300, 280);
  lv_obj_add_event_cb(
      go, [](lv_event_t *e) { static_cast<WifiSetup *>(lv_event_get_user_data(e))->rt_->forget_wifi(); },
      LV_EVENT_CLICKED, this);
}

// ---- trying a network ----------------------------------------------------------------------

void WifiSetup::connect_() {
#ifdef USE_WIFI
  auto *w = wifi::global_wifi_component;
  if (w == nullptr || w->is_disabled() || this->ssid_.empty())
    return;
  this->had_old_ = this->changing_ && w->has_sta();
  if (this->had_old_) {
    this->old_ = w->get_sta();
    this->old_ssid_ = this->old_.get_ssid().str();
  }
  wifi::WiFiAP sta{};
  sta.set_ssid(this->ssid_);
  sta.set_password(this->typed_);
  const bool switching = w->is_connected();  // (sampled first: the old link drops after this)
  strncpy(s_want, this->ssid_.c_str(), sizeof(s_want) - 1);
  s_want[sizeof(s_want) - 1] = 0;
  s_refused = 0;
  s_watching = true;
  if (s_listening == nullptr &&
      esp_event_handler_instance_register(WIFI_EVENT, WIFI_EVENT_STA_DISCONNECTED, &on_wifi_event, nullptr, &s_listening) != ESP_OK) {
    s_listening = nullptr;
    ESP_LOGW(TAG, "No Wi-Fi events: a wrong password takes the whole try");
  }
  w->set_sta(sta);
  w->start_connecting(sta);
  this->try_ms_ = millis();
  this->try_for_ms_ = switching ? TRY_SWITCH_MS : TRY_NEW_MS;
  this->was_on_old_ = switching;
  ESP_LOGI(TAG, "Trying \"%s\"%s", this->ssid_.c_str(), switching ? " (leaving the network it's on)" : "");
#endif
  this->show_(View::CONNECTING);
}

// the try ended: on it - saved; not - back to the network it had (or the
// hotspot, a new panel) and why
void WifiSetup::finish_(bool ok) {
#ifdef USE_WIFI
  s_watching = false;
  if (s_listening != nullptr) {
    esp_event_handler_instance_unregister(WIFI_EVENT, WIFI_EVENT_STA_DISCONNECTED, s_listening);
    s_listening = nullptr;
  }
  auto *w = wifi::global_wifi_component;
  if (w == nullptr)
    return;
  if (ok) {
    w->save_wifi_sta(this->ssid_, this->typed_);
    ESP_LOGI(TAG, "On \"%s\": saved", this->ssid_.c_str());
    this->typed_.clear();
    return;
  }
  if (this->had_old_) {
    w->set_sta(this->old_);
    w->start_connecting(this->old_);
    // ("still on" only when it was on it: off Wi-Fi, it goes back to trying it)
    this->error_text_ = this->was_on_old_ ? this->t_("panel.wifi_kept", "Couldn't connect to \"{name}\" - still on \"{old}\".", this->ssid_, this->old_ssid_)
                                         : this->locked_ ? this->t_("panel.wifi_failed", "Couldn't connect to \"{name}\". Check the password and try again.", this->ssid_)
                                                         : this->t_("panel.wifi_failed_open", "Couldn't connect to \"{name}\".", this->ssid_);
  } else {
    w->clear_sta();  // (the hotspot stays: the phone way, or another try)
    this->error_text_ = this->t_("panel.wifi_failed", "Couldn't connect to \"{name}\". Check the password and try again.", this->ssid_);
  }
  ESP_LOGW(TAG, "\"%s\" didn't connect%s", this->ssid_.c_str(), this->had_old_ ? ": back to the network it had" : "");
#endif
  this->typed_.clear();  // (typed again from scratch: hidden, it can't be fixed in place)
}

void WifiSetup::loop() {
  if (this->root_ == nullptr)
    return;
  const uint32_t now = millis();
  // a finger on the screen (anywhere in it - its buttons and keys too):
  // touched; then never idle under it (no clock, no dimming, the screen on)
  bool pressed = false;
  for (lv_indev_t *in = lv_indev_get_next(nullptr); in != nullptr; in = lv_indev_get_next(in))
    if (lv_indev_get_state(in) == LV_INDEV_STATE_PRESSED)
      pressed = true;
  if (pressed)
    this->touched_ms_ = now;
  lv_display_trigger_activity(nullptr);
  // on top of whatever else is on the top layer (the boot screen's
  // stopwatch is made there after the screen opens)
  if (lv_obj_get_index(this->root_) != (int32_t) lv_obj_get_child_count(lv_obj_get_parent(this->root_)) - 1)
    lv_obj_move_foreground(this->root_);
#ifdef USE_WIFI
  auto *w = wifi::global_wifi_component;
  if (this->view_ == View::CONNECTING && w != nullptr) {
    char buf[wifi::SSID_BUFFER_SIZE];
    if (w->is_connected() && strcmp(w->wifi_ssid_to(buf), this->ssid_.c_str()) == 0) {
      this->finish_(true);
      this->done_ms_ = now;
      this->show_(View::DONE);
    } else if (s_refused.load() >= REFUSED_ENOUGH || now - this->try_ms_ > this->try_for_ms_) {
      if (s_refused.load() >= REFUSED_ENOUGH)
        ESP_LOGW(TAG, "\"%s\" turned the password away", this->ssid_.c_str());
      this->finish_(false);
      this->show_(this->locked_ ? View::PASSWORD : View::LIST);
    }
    return;
  }
#endif
  if (this->view_ == View::DONE) {
    if (now - this->done_ms_ > DONE_SHOWN_MS)
      this->close();
    return;
  }
  if (this->view_ == View::LIST) {
    // (off a saved network ESPHome's own rounds scan - slower: no give-up)
    const bool esphome_scans = w != nullptr && w->has_sta() && !w->is_connected();
    if (this->scanning_ && !esphome_scans && now - this->scan_ms_ > SCAN_GIVE_UP_MS) {
      this->scanning_ = false;  // (no answer: say so, try again later)
      if (this->status_ != nullptr && this->networks_.empty())
        lv_label_set_text(this->status_, this->t_("panel.wifi_none", "No networks found").c_str());
    }
    // looked again by itself only while nothing was found (a few times):
    // each scan takes the radio off its channel - a phone on the hotspot,
    // Home Assistant's link (else: "Look again")
    if (!this->scanning_ && this->networks_.empty() && this->rescans_ < RESCANS && now - this->scan_ms_ > RESCAN_MS) {
      this->rescans_++;
      this->scan_();
    }
    if (this->redraw_list_ && !pressed && (this->list_ == nullptr || !lv_obj_is_scrolling(this->list_))) {
      this->redraw_list_ = false;
      this->build_list_();
    }
  }
  if (this->changing_ && now - this->touched_ms_ > UNTOUCHED_MS && this->view_ != View::CONNECTING)
    this->close();  // (Change Wi-Fi left open: nothing changed)
}

}  // namespace esphome::room_tiles
