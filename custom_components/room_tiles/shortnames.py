"""Short names: what tiles and map markers show (at most 15 characters).

Every area and catalog entity has its full HA name (pickers, dialogs) and a
short name for the small places. suggest() makes a first one; anything it
had to shorten is flagged for the user to review. Pure Python.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from dataclasses import dataclass

from .const import MAX_SHORT_NAME
from .fontwidths import DEFAULT_WIDTH, ROBOTO_400

# A 5x2 panel tile: 198 px wide, 12 px padding each side, name in Roboto 22 px.
TILE_NAME_PX = 174
TILE_NAME_FONT_PX = 22

# ---- per-language rules ----------------------------------------------------------
# Only for SUGGESTING a short name (once, from the HA name, which is written
# in the owner's language); the short names themselves live in Room Tiles'
# data per installation and never change with the language. Each language's
# rules (abbreviations, whether dropping vowels stays readable) are one file:
# shortening/<lang>.json. No file -> GENERIC: no abbreviations, no vowel
# dropping - whole words dropped from the end, then trimming. Adding a
# language = adding its file, no code.


@dataclass(frozen=True)
class Rules:
    # word swaps tried in order until the name fits (whole words, case kept
    # from the table) - only ones a reader recognises at a glance
    abbreviations: tuple[tuple[str, str], ...] = ()
    # drop a long word's vowels (after its first letter) before dropping
    # whole words - readable in English ("Garage" -> "Grg"), not everywhere
    drop_vowels: bool = False
    vowels: str = "aeiou"
    # how a suggestion is capitalised, so short names look alike whatever
    # the entity names were: "words" = every word starts with a capital
    # (English: "back patio" -> "Back Patio"), "first" = just the first
    # letter (where capitalising every word reads wrong: "Luz de cocina").
    # Words already capitalised or in capitals (TV, LED, iPad) stay as typed.
    case: str = "words"
    # with "words": small words that stay lower case unless first ("Back of
    # House") - the language's own list
    lower: frozenset[str] = frozenset()


def capitalise(text: str, case: str = "words", lower: frozenset[str] = frozenset()) -> str:
    """The suggestion's capitals (Rules.case / Rules.lower)."""
    words = text.split(" ")

    def up(w: str) -> str:
        # a word with a capital already (TV, iPad, McDonald) stays as typed
        return w if not w or any(c.isupper() for c in w) else w[0].upper() + w[1:]

    if case == "first":
        return " ".join([up(words[0]), *words[1:]]) if words else text
    return " ".join(w if i and w in lower else up(w) for i, w in enumerate(words))


def _rules(doc: dict | None) -> Rules:
    """A language's rules file (shortening/<lang>.json) as Rules."""
    if not doc:
        return GENERIC
    return Rules(
        abbreviations=tuple((str(a), str(b)) for a, b in doc.get("abbreviations") or []),
        drop_vowels=bool(doc.get("drop_vowels", False)),
        vowels=str(doc.get("vowels") or "aeiou"),
        case=str(doc.get("case") or "words"),
        lower=frozenset(str(w) for w in doc.get("lower") or []),
    )


GENERIC = Rules()
# every language with a rules file (read once at import)
RULES: dict[str, Rules] = {
    f.stem: _rules(json.loads(f.read_text(encoding="utf-8")))
    for f in sorted((Path(__file__).parent / "shortening").glob("*.json"))
}
ENGLISH = RULES["en"]

# kept for anything that imported the old name
ABBREVIATIONS = ENGLISH.abbreviations

_language = "en"


def set_language(lang: str | None) -> None:
    """The language names are shortened for (HA's language: "en", "en-GB",
    "de"...); set at setup."""
    global _language
    _language = (lang or "en").replace("_", "-").split("-")[0].lower() or "en"


def rules_for(lang: str | None = None) -> Rules:
    return RULES.get((lang or _language).split("-")[0].lower(), GENERIC)


def _char_width(c: str) -> float:
    """A letter's width in the panel font; an accented letter (é, Ü, ñ...)
    as its base letter - the accent barely changes the width."""
    if c in ROBOTO_400:
        return ROBOTO_400[c]
    plain = unicodedata.normalize("NFD", c)[0]
    return ROBOTO_400.get(plain, DEFAULT_WIDTH)


def width_px(text: str, font_px: float = TILE_NAME_FONT_PX) -> float:
    return sum(_char_width(c) for c in text) * font_px / 1000


def fits(text: str) -> bool:
    """Short enough to be a short name: the character limit, and wide letters
    (capitals, W, M) don't push it past a 5x2 tile."""
    return len(text) <= MAX_SHORT_NAME and width_px(text) <= TILE_NAME_PX


def _no_vowels(word: str, vowels: str) -> str:
    """'Garage' -> 'Grg': a long word without its vowels after the first
    letter; short words (4 letters or fewer) and results under 3 letters stay."""
    if len(word) <= 4:
        return word
    out = word[0] + "".join(c for c in word[1:] if c.lower() not in vowels)
    return out if len(out) >= 3 else word


def abbreviations(rules: Rules) -> tuple[tuple[str, str], ...]:
    """The language's own abbreviations, then English's: names are often
    English in any home (manufacturers' defaults - "Living Room Lamp" in a
    German one). Whole-word swaps, so a word of the language itself never
    matches an English one; its own entry wins when both have the word."""
    if rules is ENGLISH:
        return rules.abbreviations
    own = {long.lower() for long, _ in rules.abbreviations}
    return rules.abbreviations + tuple(a for a in ENGLISH.abbreviations if a[0].lower() not in own)


def suggest(name: str, lang: str | None = None) -> tuple[str, bool]:
    """(short name, needs review). A name that fits is used as is (no review).
    Otherwise, by the language's rules (rules_for): its abbreviations (then
    English's - abbreviations()) until it
    fits; then (English) the longest words lose their vowels one by one; then
    whole words dropped from the end. Never cuts inside a word unless a single
    word is itself too long. Anything changed is flagged for review."""
    rules = rules_for(lang)
    # capitals first (a case change alone needs no review), then shortening
    name = capitalise(" ".join(name.split()), rules.case, rules.lower)
    if fits(name):
        return name, False
    s = name
    for long, short in abbreviations(rules):
        if fits(s):
            break
        s = re.sub(rf"\b{re.escape(long)}\b", short, s, flags=re.IGNORECASE)

    def drop_words(text: str) -> list[str]:
        words = text.split(" ")
        while len(words) > 1 and not fits(" ".join(words)):
            words.pop()
        return words

    # without vowel dropping: whole words go from the end
    plain = drop_words(s)
    best = plain
    if rules.drop_vowels and not fits(s):
        words = s.split(" ")
        for i in sorted(range(len(words)), key=lambda k: -len(words[k])):
            if fits(" ".join(words)):
                break
            words[i] = _no_vowels(words[i], rules.vowels)
        vowelled = drop_words(" ".join(words))
        # vowels dropped only pay off when they keep more words; on a tie the
        # words stay whole ("Kit Island", not "Kit Islnd")
        if len(vowelled) > len(plain):
            best = vowelled
    s = " ".join(best)
    while s and not fits(s):  # one very long word
        s = s[:-1]
    return s.rstrip() or name[:MAX_SHORT_NAME], True
