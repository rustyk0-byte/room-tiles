#include "words.h"

#include <cstdio>
#include <cstdlib>
#include <vector>

#include "esphome/components/json/json_util.h"

namespace esphome::room_tiles {

// MIRRORED: frontend/src/words.ts and custom_components/room_tiles/wording.py - a change here must be made there too.
static void replace_all(std::string &text, const std::string &from, const std::string &to) {
  if (from.empty())
    return;
  for (size_t at = text.find(from); at != std::string::npos; at = text.find(from, at + to.size()))
    text.replace(at, from.size(), to);
}

std::string format_minutes(int m, const WordLookup &t) {
  if (m <= 0)
    return "";
  std::string text;
  if (m < 60) {
    text = t("time.minutes");
    replace_all(text, "{m}", std::to_string(m));
  } else {
    char mm[8];
    snprintf(mm, sizeof(mm), "%02d", m % 60);
    text = t("time.hours");
    replace_all(text, "{h}", std::to_string(m / 60));
    replace_all(text, "{mm}", mm);
  }
  return text;
}

static std::string render(JsonVariantConst w, const WordLookup &t, int depth = 0) {
  if (depth > 8)
    return "";  // (no word goes this deep)
  if (w.is<const char *>())
    return w.as<const char *>();
  if (w.is<JsonArrayConst>()) {
    std::string out;
    for (JsonVariantConst x : w.as<JsonArrayConst>())
      out += render(x, t, depth + 1);
    return out;
  }
  if (w.is<JsonObjectConst>()) {
    JsonObjectConst o = w.as<JsonObjectConst>();
    if (o["min"].is<int>())
      return format_minutes(o["min"].as<int>(), t);
    std::string text = t(o["k"] | "");
    for (JsonPairConst p : o["p"].as<JsonObjectConst>())
      replace_all(text, std::string("{") + p.key().c_str() + "}", render(p.value(), t, depth + 1));
    return text;
  }
  return "";
}

bool word_text(const std::string &json, const WordLookup &t, std::string &out) {
  if (json.empty())
    return false;
  JsonDocument doc = json::parse_json(reinterpret_cast<const uint8_t *>(json.data()), json.size());
  if (doc.isNull())
    return false;
  out = render(doc.as<JsonVariantConst>(), t);
  return true;
}

bool local_tile(const std::string &tile, const std::string &words, const WordLookup &t, std::string &out) {
  if (words.empty())
    return false;
  JsonDocument doc = json::parse_json(reinterpret_cast<const uint8_t *>(words.data()), words.size());
  if (!doc.is<JsonObjectConst>())
    return false;
  // the tile text's units (";") and their fields ("|")
  std::vector<std::vector<std::string>> units(1, std::vector<std::string>(1));
  for (char c : tile) {
    if (c == ';')
      units.emplace_back(1);
    else if (c == '|')
      units.back().emplace_back();
    else
      units.back().back() += c;
  }
  for (JsonPairConst p : doc.as<JsonObjectConst>()) {
    char *end = nullptr;
    const long u = strtol(p.key().c_str(), &end, 10);
    if (end == nullptr || *end != '.' || u < 0 || u >= (long) units.size())
      continue;
    const long f = strtol(end + 1, nullptr, 10);
    if (f < 0 || f > 16)
      continue;
    auto &fields = units[u];
    while ((long) fields.size() <= f)
      fields.emplace_back();
    std::string text = render(p.value(), t);
    for (char &c : text)
      if (c == '|' || c == ';')
        c = '/';  // (the tile text's own separators can't be in a field)
    fields[f] = std::move(text);
  }
  out.clear();
  for (size_t u = 0; u < units.size(); u++) {
    if (u > 0)
      out += ';';
    for (size_t f = 0; f < units[u].size(); f++) {
      if (f > 0)
        out += '|';
      out += units[u][f];
    }
  }
  return true;
}

}  // namespace esphome::room_tiles
