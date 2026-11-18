// Room Tiles panel: live entity states from Home Assistant. Subscriptions are
// added at runtime (the tiles decide what's needed) over the ESPHome API
// connection the panel already holds; HA pushes every change.
//
// Kept in PSRAM: each subscription's names live here once (ESPHome gets them
// by pointer, no copies) and its callback carries just an index - a few dozen
// bytes of internal RAM per subscription instead of ~450.
#pragma once

#include <cstdint>
#include <deque>
#include <functional>
#include <map>
#include <string>
#include <vector>

#include "psram.h"
#include "words.h"

namespace esphome::room_tiles {

class StateHub {
 public:
  /// Make sure `entity`'s state (attr "") or an attribute is pushed to us.
  void watch(const std::string &entity, const std::string &attr = "");
  /// The last value HA pushed ("" = none yet). A text that comes with its
  /// words (`tile` + `tile_words`, `status` + `status_word`: watching one
  /// watches both) is in the panel's own language - whatever HA's is.
  const std::string &get(const std::string &entity, const std::string &attr = "") const;
  /// How a word's token reads in the panel's language (its string pack).
  void set_words(WordLookup &&t) { this->words_ = std::move(t); }
  /// The panel's language changed: every text with words again.
  void relocalize();
  /// Asked for and not answered yet: no value, and HA hasn't got to it (its
  /// subscription not sent yet, or sent and HA's answers - in the order
  /// asked - not past it). HA never sends an attribute the entity doesn't
  /// have: each batch ends in main states, which it always has; WAIT_MS is
  /// the fallback when it doesn't answer at all.
  bool waiting(const std::string &entity, const std::string &attr = "") const;
  static constexpr uint32_t WAIT_MS = 3000;
  /// Called with the entity whenever one of its watched values changes.
  void on_change(std::function<void(const std::string &)> &&cb) { this->listener_ = std::move(cb); }
  /// How many values are subscribed.
  size_t count() const { return this->entries_.size(); }
  /// Main loop: send new subscriptions to HA (batched).
  void loop();

 protected:
  struct Entry {
    pstring entity;
    pstring attr;
    std::string value;  // (mostly short: kept inline, no allocation)
    std::string local;  // a text with words: in the panel's language
    bool localized{false};
    int32_t seq{-1};      // its place in the order sent to HA (-1: not yet)
    uint32_t sent_ms{0};  // when
  };
  void notify_unanswered_(uint32_t from, uint32_t to);
  void push_(uint32_t index, const char *value, size_t len);
  int find_(const std::string &entity, const std::string &attr) const;
  void localize_(uint32_t index);

  // a deque: entries never move, so the names ESPHome points at stay put
  std::deque<Entry, PsramAllocator<Entry>> entries_;
  std::map<pstring, uint32_t, std::less<>, PsramAllocator<std::pair<const pstring, uint32_t>>> index_;  // "entity|attr"
  std::vector<uint32_t, PsramAllocator<uint32_t>> pending_;  // to subscribe
  std::function<void(const std::string &)> listener_;
  WordLookup words_;
  // the entries in the order their subscriptions went to HA - the order it
  // answers in: the latest one answered means it has got to every one
  // before it (-1: none yet)
  std::vector<uint32_t, PsramAllocator<uint32_t>> order_;
  int32_t answered_seq_{-1};
  // the batches sent and not all answered yet: [from, to) in order_, and when
  struct Sent {
    uint32_t from, to, at;
  };
  std::vector<Sent> sent_;
};

/// Is an entity of this kind active - a map marker coloured, not grayed; a
/// tile's or marker's icon "on", not the theme's off picture (map_markers.cpp).
bool marker_active(const StateHub &st, const std::string &kind, const std::string &entity);

}  // namespace esphome::room_tiles
