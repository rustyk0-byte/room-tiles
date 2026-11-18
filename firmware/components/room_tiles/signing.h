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
static constexpr int PANEL_SCHEMA = 3;  // (3: theme packs carry I8X pictures)

enum class SignResult { OK, NO_TIME, NO_KEY };

/// "?name=<node>&ts=<unix time>&sig=<hex>&schema=<PANEL_SCHEMA>" - sig = HMAC-SHA256(API key,
/// "<node>\n<ts>" [+ "\n<sha256 of body, hex>" for a POST]). Any thread.
SignResult sign_query(const std::string *body, std::string &query);
/// The same for a POST of raw bytes (a screenshot: no copy into a string).
SignResult sign_query_bytes(const uint8_t *body, size_t size, std::string &query);

/// The panel has its API key (HA sets it when it adds the panel).
bool has_api_key();

}  // namespace esphome::room_tiles
