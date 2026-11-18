// MIRRORED: frontend/src/words.ts (the dashboard) and
// custom_components/room_tiles/wording.py render() - a change here must be made there too.
// Room Tiles panel: status words in the panel's own language. Room Tiles'
// sensors give their text in HA's language (`tile`, `status`) and the same as
// words in no language yet (`tile_words`, `status_word`: JSON text); the
// panel fills them in from its string pack, whatever HA's language is. The
// word form (the integration's wording.py "words"):
//   "text"                          itself (a name, a brand's own wording)
//   {"k": token, "p": {name: word}}   the token's text, its {placeholders}
//                                     filled with the words
//   {"min": minutes}                time left: time.minutes / time.hours
//   [word, word, ...]               one after another ("\n": a new line)
#pragma once

#include <functional>
#include <string>

namespace esphome::room_tiles {

/// A token's text in the panel's language (the token itself when unknown).
using WordLookup = std::function<std::string(const char *token)>;

/// One word (`status_word`: JSON text) as text; "" when it isn't one.
bool word_text(const std::string &json, const WordLookup &t, std::string &out);
/// A `tile` text with its `tile_words` ("<unit>.<field>" -> word) filled in.
/// False (out untouched) when there are no words to fill in.
bool local_tile(const std::string &tile, const std::string &words, const WordLookup &t, std::string &out);
/// Time left the language's way ("~45m" / "~1h 05m"; "" for none).
std::string format_minutes(int minutes, const WordLookup &t);

}  // namespace esphome::room_tiles
