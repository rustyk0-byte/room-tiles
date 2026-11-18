"""Room Tiles' wording in HA's language - token substitution from one JSON
file per language (`wording/<lang>.json`; DESIGN.md "Wording stays in one
place").

    t("pool.heating_to", target="85°")  ->  "Heating to 85°" / "Heizt auf 85°"

Each file has `strings` (token -> text with {placeholders}) - display text
only. (Short-name SUGGESTION rules are separate: shortening/<lang>.json.)
English (`en.json`) is the full set; a token missing in another language falls back to English, an unknown
token to itself. ADDING A LANGUAGE = adding its file; CHANGING WORDING =
editing a file - no code. Use the local way of saying a thing, not a
word-for-word translation ("Switch Over" = "into the dryer"). Tests
(tests/test_wording.py) check every file: valid JSON, only known tokens,
the same placeholders as English.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DIR = Path(__file__).parent / "wording"


def _load() -> dict[str, dict[str, Any]]:
    # read once at import (HA imports integrations off the event loop)
    return {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(DIR.glob("*.json"))}


LANGUAGES: dict[str, dict[str, Any]] = _load()
ENGLISH: dict[str, str] = LANGUAGES["en"]["strings"]

_language = "en"


def set_language(lang: str | None) -> None:
    """HA's language ("en", "de", "pt-BR"...), set at setup."""
    global _language
    _language = base(lang)


def base(lang: str | None) -> str:
    return (lang or "en").replace("_", "-").split("-")[0].lower() or "en"


def language() -> str:
    return _language


def has(token: str, lang: str | None = None) -> bool:
    return token in ENGLISH or token in LANGUAGES.get(base(lang or _language), {}).get("strings", {})


def t(token: str, lang: str | None = None, **kw: object) -> str:
    """The token's text in the language (else English, else the token),
    with its {placeholders} filled in."""
    strings = LANGUAGES.get(base(lang or _language), {}).get("strings", {})
    text = strings.get(token) or ENGLISH.get(token) or token
    return text.format(**kw) if kw else text


# MIRRORED: render() / format_minutes() / tile_words are read by frontend/src/words.ts
# and firmware/components/room_tiles/words.cpp - a change here must be made there too.
# ---- words: text in no language yet ---------------------------------------------
#
# What a tile shows, as data each display puts into ITS language (a panel's
# own language, a dashboard device's) - never HA's (`tile_words`, next to the
# `tile` text in HA's language). A word is one of:
#   "text"                         itself (a name, a brand's own wording)
#   {"k": token, "p": {name: word}}  the token's text, its {placeholders}
#                                    filled with the words (a "p" is optional)
#   {"min": minutes}               time left: time.minutes / time.hours
#   [word, word, ...]              the words one after another ("\n": a new line)
# In attributes a word is JSON text (word_json / tile_words): HA hands
# attributes to the panels as text. The panels (firmware words.cpp) and the
# dashboard (frontend words.ts) read the same form.

Word = str | dict | list


def w(token: str, **params: Word) -> dict:
    """A token as a word: its text, its placeholders filled with words."""
    return {"k": token, "p": params} if params else {"k": token}


def minutes(m: int | None) -> Word:
    """Time left as a word ("" when there's none)."""
    return {"min": int(m)} if m is not None and m > 0 else ""


def format_minutes(m: int | None, lang: str | None = None) -> str:
    """Time left, short enough for every display: "~45m" / "~1h 05m" in
    English, the language's own way elsewhere (time.minutes / time.hours)."""
    if m is None or m <= 0:
        return ""
    return t("time.minutes", lang, m=m) if m < 60 else t("time.hours", lang, h=m // 60, mm=f"{m % 60:02d}")


def render(word: Word, lang: str | None = None) -> str:
    """A word's text in the language (HA's when None)."""
    if isinstance(word, str):
        return word
    if isinstance(word, list):
        return "".join(render(x, lang) for x in word)
    if isinstance(word, dict):
        if "min" in word:
            return format_minutes(word["min"], lang)
        params = {k: render(v, lang) for k, v in (word.get("p") or {}).items()}
        return t(word.get("k", ""), lang, **params)
    return ""


def word_json(word: Word) -> str:
    """A word as an attribute: JSON text ("" for none) - HA hands
    attributes to the panels as text, so words always go as JSON."""
    return "" if word in ("", [], None) else json.dumps(word, ensure_ascii=False, separators=(",", ":"))


def tile_words(fields: dict[str, Word]) -> str:
    """The `tile_words` attribute: which of the `tile` text's fields are
    words, "<unit>.<field>" (0-based: units split by ";", fields by "|") ->
    the word; JSON (HA hands attributes to the panels as text)."""
    return json.dumps({k: v for k, v in fields.items() if v not in ("", [], None)}, ensure_ascii=False, separators=(",", ":"))
