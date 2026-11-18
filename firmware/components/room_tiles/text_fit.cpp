#include "text_fit.h"

#include <vector>

namespace esphome::room_tiles {

static const char *const SHY = "\xC2\xAD";  // U+00AD soft hyphen

static int text_w(const std::string &s, const lv_font_t *font) {
  lv_point_t p;
  lv_text_get_size(&p, s.c_str(), font, 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);
  return p.x;
}

// a word's pieces: where it may break - after a hyphen ("sèche-" + "linge")
// or at a soft hyphen ("Centri" + "fugando", a "-" drawn when it breaks there)
struct Piece {
  std::string text;
  bool soft_after;  // a soft hyphen follows it
};

static std::vector<Piece> pieces_of(const std::string &word) {
  std::vector<Piece> out;
  std::string cur;
  for (size_t i = 0; i < word.size();) {
    if (word.compare(i, 2, SHY) == 0) {
      out.push_back({cur, true});
      cur.clear();
      i += 2;
      continue;
    }
    cur += word[i];
    if (word[i] == '-' && i + 1 < word.size()) {
      out.push_back({cur, false});
      cur.clear();
    }
    ++i;
  }
  out.push_back({cur, false});
  return out;
}

static std::string joined(const std::vector<Piece> &p, size_t from, size_t to) {
  std::string s;
  for (size_t i = from; i < to; ++i)
    s += p[i].text;
  return s;
}

// (UTF-8: the next character's start)
static size_t next_char(const std::string &s, size_t i) {
  ++i;
  while (i < s.size() && (static_cast<unsigned char>(s[i]) & 0xC0) == 0x80)
    ++i;
  return i;
}

static void fit_paragraph(const std::string &para, const lv_font_t *font, int width, std::vector<std::string> &lines) {
  std::string cur;  // the line so far
  size_t start = 0;
  while (start <= para.size()) {
    size_t end = para.find(' ', start);
    if (end == std::string::npos)
      end = para.size();
    std::vector<Piece> p = pieces_of(para.substr(start, end - start));
    start = end + 1;
    size_t from = 0;  // the word's pieces left to place
    while (from < p.size()) {
      const std::string rest = joined(p, from, p.size());
      const std::string sep = cur.empty() ? "" : " ";
      if (text_w(cur + sep + rest, font) <= width) {
        cur += sep + rest;
        break;
      }
      // the most of the word that fits on this line, broken at a piece
      size_t best = 0;
      for (size_t k = p.size() - 1; k > from; --k) {
        const std::string head = joined(p, from, k) + (p[k - 1].soft_after ? "-" : "");
        if (text_w(cur + sep + head, font) <= width) {
          best = k;
          break;
        }
      }
      if (best > 0) {
        lines.push_back(cur + sep + joined(p, from, best) + (p[best - 1].soft_after ? "-" : ""));
        cur.clear();
        from = best;
        continue;
      }
      if (!cur.empty()) {  // the word on a line of its own
        lines.push_back(cur);
        cur.clear();
        continue;
      }
      // alone and still too wide, no piece fits: broken where it must be (+ "-")
      std::string word = rest;
      size_t cut = 0;
      for (size_t i = next_char(word, 0); i <= word.size(); i = next_char(word, i)) {
        if (text_w(word.substr(0, i) + "-", font) > width)
          break;
        cut = i;
        if (i == word.size())
          break;
      }
      if (cut == 0)
        cut = next_char(word, 0);  // (not even one character: one anyway)
      lines.push_back(word.substr(0, cut) + "-");
      // what's left of it: its pieces again from there
      p = pieces_of(word.substr(cut));
      from = 0;
    }
    if (end == para.size())
      break;
  }
  lines.push_back(cur);
}

std::string fit_lines(const std::string &text, const lv_font_t *font, int width) {
  std::vector<std::string> lines;
  size_t start = 0;
  for (;;) {
    const size_t nl = text.find('\n', start);
    fit_paragraph(text.substr(start, nl == std::string::npos ? std::string::npos : nl - start), font, width, lines);
    if (nl == std::string::npos)
      break;
    start = nl + 1;
  }
  std::string out;
  for (size_t i = 0; i < lines.size(); ++i)
    out += (i ? "\n" : "") + lines[i];
  return out;
}

}  // namespace esphome::room_tiles
