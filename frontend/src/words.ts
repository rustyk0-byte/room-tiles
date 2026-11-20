// MIRRORED: firmware/components/room_tiles/words.cpp (the panels) and
// custom_components/room_tiles/wording.py render() - a change here must be made there too.
// Status words in THIS device's language. Room Tiles' sensors give the text
// in HA's language (`tile`, `status`...) and, next to it, the same as words
// in no language yet (`tile_words`, `status_word`... as JSON text): each display - this
// dashboard, every wall panel - puts them in its own language, whatever HA's
// is. The word form (custom_components/room_tiles/wording.py "words"):
//   "text"                            itself (a name, a brand's own wording)
//   {k: token, p?: {name: word}}      the token's text, its {placeholders}
//                                     filled with the words
//   {min: minutes}                    time left: time.minutes / time.hours
//   [word, word, ...]                 one after another ("\n": a new line)
// The wording itself is the integration's (wording/<lang>.json): one place;
// i18n.ts loads a language's wording with its strings.

import { WORDING, language } from "./i18n";

function token(key: string, lang: string): string {
  const base = lang.split("-")[0].toLowerCase();
  return WORDING[lang]?.[key] || WORDING[base]?.[key] || WORDING.en[key] || key;
}

function fill(text: string, vars: Record<string, string>): string {
  return text.replace(/\{(\w+)\}/g, (all, name: string) => (name in vars ? vars[name] : all));
}

/** Time left the language's way: "~45m" / "~1h 05m" ("" for none). */
export function formatMinutes(m: number, lang: string = language()): string {
  if (!(m > 0)) return "";
  if (m < 60) return fill(token("time.minutes", lang), { m: String(m) });
  return fill(token("time.hours", lang), { h: String(Math.floor(m / 60)), mm: String(m % 60).padStart(2, "0") });
}

/** A word's text in the language (this device's by default). */
export function wordText(word: unknown, lang: string = language()): string {
  if (typeof word === "string") return word;
  if (Array.isArray(word)) return word.map((x) => wordText(x, lang)).join("");
  if (word && typeof word === "object") {
    const o = word as { k?: unknown; p?: Record<string, unknown>; min?: unknown };
    if (typeof o.min === "number") return formatMinutes(o.min, lang);
    const vars: Record<string, string> = {};
    for (const [name, v] of Object.entries(o.p ?? {})) vars[name] = wordText(v, lang);
    return fill(token(String(o.k ?? ""), lang), vars);
  }
  return "";
}

/** A text attribute in this device's language: its word when the sensor
 *  gives one (`status_word` next to `status`: JSON text - HA hands attributes
 *  to the panels as text, so words always go as JSON), else the text as it is. */
export function localText(word: unknown, text: unknown): string {
  if (typeof word === "string" && word) {
    try {
      return wordText(JSON.parse(word));
    } catch {
      /* not a word: the text */
    }
  }
  return String(text ?? "");
}

// MIRRORED: firmware/components/room_tiles/words.cpp local_tile + states.cpp (the pairs) - a change here must be made there too.
/** A sensor's `tile` text with its words (`tile_words`: "<unit>.<field>" ->
 *  word) in this device's language - else the text as HA gave it. */
export function localTile(attributes?: Record<string, unknown>): string {
  const tile = String(attributes?.tile ?? "");
  let words: Record<string, unknown>;
  try {
    words = JSON.parse(String(attributes?.tile_words ?? "")) as Record<string, unknown>;
  } catch {
    return tile;
  }
  if (!words || typeof words !== "object") return tile;
  const units = tile.split(";").map((u) => u.split("|"));
  for (const [at, word] of Object.entries(words)) {
    const [u, f] = at.split(".").map(Number);
    if (units[u] === undefined || !(f >= 0)) continue;
    while (units[u].length <= f) units[u].push("");
    // (the tile text's own separators can't appear inside a field)
    units[u][f] = wordText(word).replace(/[|;]/g, "/");
  }
  return units.map((u) => u.join("|")).join(";");
}
