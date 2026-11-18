// Room Tiles panel: a status line broken to fit its column - never scrolled,
// never cut. Breaks at spaces, after a hyphen, at a soft hyphen (U+00AD in the
// wording: invisible, drawn as "-" where it breaks), and as a last resort
// inside a word (with "-"). The wording keeps every status within its lines
// (tools/check_panel_text.py); a longer one still breaks, past the lines.
#pragma once

#include <string>

#include <lvgl.h>

namespace esphome::room_tiles {

/// `text` as lines of at most `width` px in `font`, joined with "\n";
/// soft hyphens dropped (or "-" at a break).
std::string fit_lines(const std::string &text, const lv_font_t *font, int width);

}  // namespace esphome::room_tiles
