#include "states.h"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <string_view>

#include "esphome/components/api/api_connection.h"
#include "esphome/components/api/api_server.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"

namespace esphome::room_tiles {

static const char *const TAG = "room_tiles.states";
static const std::string EMPTY;

// "entity|attr" into a stack buffer (lookups allocate nothing)
static std::string_view key_of(char *buf, size_t size, const std::string &entity, const std::string &attr) {
  const int n = snprintf(buf, size, "%s|%s", entity.c_str(), attr.c_str());
  return std::string_view(buf, n < 0 ? 0 : std::min((size_t) n, size - 1));
}

int StateHub::find_(const std::string &entity, const std::string &attr) const {
  char buf[192];
  auto it = this->index_.find(key_of(buf, sizeof(buf), entity, attr));
  return it == this->index_.end() ? -1 : (int) it->second;
}

// MIRRORED: frontend/src/words.ts localTile / localText (the same pairs) - a change here must be made there too.
// A text and its words (the integration's wording.py): the words come first
// (HA answers in the order asked), so the text shows in the panel's language
// from the start
static const char *words_of(const std::string &attr) {
  return attr == "tile" ? "tile_words" : attr == "status" ? "status_word" : nullptr;
}
static const char *text_of(const std::string &attr) {
  return attr == "tile_words" ? "tile" : attr == "status_word" ? "status" : nullptr;
}

void StateHub::watch(const std::string &entity, const std::string &attr) {
  if (entity.empty() || this->find_(entity, attr) >= 0)
    return;
  if (const char *w = words_of(attr))
    this->watch(entity, w);
  const uint32_t i = this->entries_.size();
  this->entries_.push_back(Entry{pstring(entity.c_str()), pstring(attr.c_str()), std::string()});
  char buf[192];
  const std::string_view k = key_of(buf, sizeof(buf), entity, attr);
  this->index_.emplace(pstring(k.data(), k.size()), i);
  this->pending_.push_back(i);
}

const std::string &StateHub::get(const std::string &entity, const std::string &attr) const {
  const int i = this->find_(entity, attr);
  if (i < 0)
    return EMPTY;
  const Entry &e = this->entries_[i];
  return e.localized ? e.local : e.value;
}

// A text with words (or its words) changed: the text in the panel's language
void StateHub::localize_(uint32_t index) {
  Entry &e = this->entries_[index];
  const std::string attr(e.attr.c_str());
  const std::string entity(e.entity.c_str());
  int ti = -1, wi = -1;
  if (const char *w = words_of(attr)) {
    ti = (int) index;
    wi = this->find_(entity, w);
  } else if (const char *t = text_of(attr)) {
    wi = (int) index;
    ti = this->find_(entity, t);
  }
  if (ti < 0)
    return;
  Entry &text = this->entries_[ti];
  const std::string &words = wi < 0 ? EMPTY : this->entries_[wi].value;
  text.localized = false;
  if (text.value.empty() || words.empty() || !this->words_)
    return;  // (no words - an older Room Tiles: the text as HA gives it)
  if (attr == "tile" || attr == "tile_words")
    text.localized = local_tile(text.value, words, this->words_, text.local);
  else
    text.localized = word_text(words, this->words_, text.local);
}

void StateHub::relocalize() {
  for (uint32_t i = 0; i < this->entries_.size(); i++) {
    if (words_of(std::string(this->entries_[i].attr.c_str())) != nullptr) {
      this->localize_(i);
      if (this->listener_)
        this->listener_(std::string(this->entries_[i].entity.c_str()));
    }
  }
}

bool StateHub::waiting(const std::string &entity, const std::string &attr) const {
  const int i = this->find_(entity, attr);
  if (i < 0)
    return false;
  const Entry &e = this->entries_[i];
  if (!e.value.empty())
    return false;
  if (e.seq < 0)
    return true;  // (not asked yet)
  return e.seq > this->answered_seq_ && millis() - e.sent_ms < WAIT_MS;
}

// The entities with a value HA passed over (one the entity doesn't have)
// among sends [from, to): their tiles stop waiting
void StateHub::notify_unanswered_(uint32_t from, uint32_t to) {
  if (!this->listener_)
    return;
  const char *last = nullptr;
  for (uint32_t q = from; q < to && q < this->order_.size(); q++) {
    const Entry &e = this->entries_[this->order_[q]];
    if (e.value.empty() && (last == nullptr || strcmp(last, e.entity.c_str()) != 0)) {
      last = e.entity.c_str();
      this->listener_(std::string(last));
    }
  }
}

void StateHub::push_(uint32_t index, const char *value, size_t len) {
  if (index >= this->entries_.size())
    return;
  Entry &e = this->entries_[index];
  bool advanced = false;
  if (e.seq > this->answered_seq_) {  // HA has got this far down the list
    const uint32_t was = (uint32_t) (this->answered_seq_ + 1);
    this->answered_seq_ = e.seq;
    this->notify_unanswered_(was, (uint32_t) e.seq);
    advanced = true;
  }
  if (e.value.size() == len && e.value.compare(0, len, value, len) == 0) {
    if (advanced && len == 0 && this->listener_)  // (answered "": not waiting any more)
      this->listener_(std::string(e.entity.c_str()));
    return;
  }
  e.value.assign(value, len);
  this->localize_(index);
  if (this->listener_)
    this->listener_(std::string(e.entity.c_str()));
}

void StateHub::loop() {
  // a batch HA left unanswered (HA away or slow, or it ends in attributes
  // the entities don't have): its tiles stop waiting
  while (!this->sent_.empty()) {
    const Sent b = this->sent_.front();
    if ((int32_t) b.to - 1 <= this->answered_seq_) {
      this->sent_.erase(this->sent_.begin());  // (all answered)
    } else if (millis() - b.at >= WAIT_MS) {
      this->sent_.erase(this->sent_.begin());
      this->notify_unanswered_(std::max(b.from, (uint32_t) (this->answered_seq_ + 1)), b.to);
    } else {
      break;
    }
  }
  auto *server = api::global_api_server;
  if (this->pending_.empty() || server == nullptr)
    return;
  // the main states last: HA always has those (not every attribute), so its
  // answer to the last one says it has been through the whole batch
  std::stable_partition(this->pending_.begin(), this->pending_.end(),
                        [this](uint32_t i) { return !this->entries_[i].attr.empty(); });
  const uint32_t now = millis();
  const uint32_t from = this->order_.size();
  for (uint32_t i : this->pending_) {
    Entry &e = this->entries_[i];
    e.seq = (int32_t) this->order_.size();
    e.sent_ms = now;
    this->order_.push_back(i);
    // (by pointer: the names live in entries_ for good; the callback holds
    // only `this` + the index - small enough to need no allocation)
    server->subscribe_home_assistant_state(e.entity.c_str(), e.attr.empty() ? nullptr : e.attr.c_str(),
                                           [this, i](StringRef v) { this->push_(i, v.c_str(), v.size()); });
  }
  ESP_LOGD(TAG, "+%u subscriptions (%u in all)", (unsigned) this->pending_.size(), (unsigned) this->entries_.size());
  this->pending_.clear();
  this->sent_.push_back(Sent{from, (uint32_t) this->order_.size(), now});
  // The API sends its subscription list to HA once, when HA connects;
  // restarting that sends the new ones (and HA pushes their current values,
  // the whole list in order).
  for (auto &client : server->active_clients()) {
    if (client != nullptr && client->is_authenticated())
      client->on_subscribe_home_assistant_states_request();
  }
}

}  // namespace esphome::room_tiles
