// Room Tiles panel: signing requests to the integration with the panel's own
// API key (panels.py has the other side).
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

namespace esphome::room_tiles {

// MIRRORED: custom_components/room_tiles/panels.py PANEL_SCHEMA - a change here must be made there too.
// The panels' format (payload, packs, taps, screenshots): bump both on any
// change the other side can't read. Every request says it (&schema=); HA
// answers another number with 426 and its own number as the body.
static constexpr int PANEL_SCHEMA = 4;  // (4: the whole request signed - sign_request)

enum class SignResult { OK, NO_TIME, NO_KEY };

// MIRRORED: custom_components/room_tiles/panels.py request_signature - a change here must be made there too.
/// A request's query, signed whole: "?name=<node>&ts=<unix time>&schema=<PANEL_SCHEMA><params>&sig=<hex>"
/// - `params`: its own values, each "&key=value" (URL-safe), or "". sig = HMAC-SHA256(API key,
/// "RT2\n<method>\n<path>\n<the query without '?' and &sig>\n<sha256 of the body, hex - "" for a GET>"):
/// nothing of it can be changed and sent again. `body` nullptr: a GET. Any thread.
SignResult sign_request(const char *method, const char *path, const std::string &params, const uint8_t *body,
                        size_t size, std::string &query);
inline SignResult sign_request(const char *method, const char *path, const std::string &params,
                               const std::string *body, std::string &query) {
  return sign_request(method, path, params, body != nullptr ? reinterpret_cast<const uint8_t *>(body->data()) : nullptr,
                      body != nullptr ? body->size() : 0, query);
}

// MIRRORED: custom_components/room_tiles/panels.py answer_signature - a change here must be made there too.
/// HA's answer is from HA: `answer_sig` (its X-RT-Sig header, hex) = HMAC-SHA256(API key,
/// "RT2-ANSWER\n<the request's sig>\n<status>\n<sha256 of the body, hex>"). Nothing HA
/// answers (data, an update offer, a pack, an image) is taken without it.
bool answer_ok(const std::string &request_sig, int status, const uint8_t *body, size_t size, const char *answer_sig);

/// The panel has its API key (HA sets it when it adds the panel).
bool has_api_key();

}  // namespace esphome::room_tiles
