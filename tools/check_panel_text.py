#!/usr/bin/env python3
"""Does every panel text fit, in every language?

Measures the panels' wording the way the firmware draws it: Roboto from
Google Fonts at the firmware's sizes (room_tiles.yaml), each glyph's hinted
advance rounded up to a whole pixel, no kerning - what ESPHome's font
converter gives LVGL. Status lines are broken as the panel breaks them
(firmware text_fit.cpp: spaces, after hyphens, soft hyphens, inside a word as
a last resort); rollers step their font down as the panel does (board.cpp).
The room each text has comes from the firmware's layout (the SLOTS below:
keep them in step with it).

  pip install freetype-py pyphen
  python tools/check_panel_text.py                    # the report
  python tools/check_panel_text.py --add-soft-hyphens # + soft hyphens where a
                                                      #   status line breaks a word

Exit status 1 when something doesn't fit.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

import freetype
import pyphen

ROOT = Path(__file__).resolve().parents[1]
FONT_CACHE = Path.home() / ".cache" / "room-tiles" / "fonts"
LANGS = ["en", "de", "es", "fr", "it", "nl", "pt"]
PYPHEN = {"en": "en_US", "de": "de_DE", "es": "es", "fr": "fr", "it": "it_IT", "nl": "nl_NL", "pt": "pt_PT"}
SHY = "­"

# ---- fonts (firmware/room_tiles.yaml: id -> weight, px) ----------------------------------
FONT = {
    "bar": (700, 24), "name": (400, 22), "name_s": (400, 16), "roll": (400, 16), "roll_s": (400, 12),
    "roll_sel": (700, 28), "roll_sel_s": (700, 21), "roll_mid": (700, 22), "roll_mid_s": (700, 16),
    "prefix": (300, 16), "prefix_s": (300, 12),
}


def font_file(weight: int) -> Path:
    """Roboto at this weight, as ESPHome's gfonts:// fetches it (cached)."""
    path = FONT_CACHE / f"roboto-{weight}.ttf"
    if not path.exists():
        FONT_CACHE.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(f"https://fonts.googleapis.com/css2?family=Roboto:wght@{weight}",
                                     headers={"User-Agent": "Mozilla/4.0"})  # (an old agent: TTF links)
        css = urllib.request.urlopen(req, timeout=30).read().decode()
        url = re.search(r"https://[^)]+\.ttf", css).group(0)
        path.write_bytes(urllib.request.urlopen(url, timeout=30).read())
    return path


_faces: dict = {}
_adv: dict = {}


def _face(fid: str):
    if fid not in _faces:
        weight, px = FONT[fid]
        f = freetype.Face(str(font_file(weight)))
        f.set_pixel_sizes(px, 0)
        _faces[fid] = f
    return _faces[fid]


def width(fid: str, text: str) -> int:
    total = 0
    for ch in text:
        key = (fid, ch)
        if key not in _adv:
            f = _face(fid)
            f.load_char(ch, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_NO_BITMAP)
            _adv[key] = (f.glyph.metrics.horiAdvance + 63) // 64
        total += _adv[key]
    return total


# ---- the panel's line breaking (firmware text_fit.cpp) ------------------------------------
def _pieces(word: str) -> list[tuple[str, bool]]:
    """(text, a soft hyphen follows) - breaks after a hyphen or at a soft hyphen."""
    out, cur = [], ""
    for i, ch in enumerate(word):
        if ch == SHY:
            out.append((cur, True))
            cur = ""
            continue
        cur += ch
        if ch == "-" and i + 1 < len(word):
            out.append((cur, False))
            cur = ""
    out.append((cur, False))
    return out


def fit_lines(text: str, fid: str, room: int) -> tuple[list[str], bool]:
    """The panel's lines, and whether a word had to break where it has no break point."""
    lines: list[str] = []
    forced = False
    for para in text.split("\n"):
        cur = ""
        for word in para.split(" "):
            p = _pieces(word)
            start = 0
            while start < len(p):
                rest = "".join(t for t, _ in p[start:])
                sep = " " if cur else ""
                if width(fid, cur + sep + rest) <= room:
                    cur += sep + rest
                    break
                best = 0
                for k in range(len(p) - 1, start, -1):
                    head = "".join(t for t, _ in p[start:k]) + ("-" if p[k - 1][1] else "")
                    if width(fid, cur + sep + head) <= room:
                        best = k
                        break
                if best:
                    lines.append(cur + sep + "".join(t for t, _ in p[start:best]) + ("-" if p[best - 1][1] else ""))
                    cur, start = "", best
                    continue
                if cur:
                    lines.append(cur)
                    cur = ""
                    continue
                forced = True
                cut = 0
                for i in range(1, len(rest) + 1):
                    if width(fid, rest[:i] + "-") > room:
                        break
                    cut = i
                cut = max(cut, 1)
                lines.append(rest[:cut] + "-")
                p, start = _pieces(rest[cut:]), 0
        lines.append(cur)
    return lines, forced


# ---- the wording ------------------------------------------------------------------
FRONT_DIR = ROOT / "frontend" / "i18n"
WORD_DIR = ROOT / "custom_components" / "room_tiles" / "wording"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


FRONT = {lang: _load(FRONT_DIR / f"{lang}.json")["strings"] for lang in LANGS}
WORD = {lang: _load(WORD_DIR / f"{lang}.json")["strings"] for lang in LANGS}
# placeholders: long-ish real values
FILL = {"n": "2", "room": "Living Room", "h": "1", "mm": "25", "m": "45", "text": "Stuck", "target": "88°",
        "name": "Matic", "alert": "Stuck", "eta": "12:45"}


def source(key: str) -> dict:
    return WORD if key in WORD["en"] else FRONT


def text_of(lang: str, key: str) -> str | None:
    src = source(key)
    t = src[lang].get(key, src["en"].get(key))
    if t is None:
        return None

    def sub(m):
        k = m.group(1)
        if k == "now":
            return text_of(lang, "panel.move_now")
        if k == "body":
            return text_of(lang, "pool.body.pool")
        return FILL.get(k, m.group(0))

    return re.sub(r"\{(\w+)\}", sub, t)


# ---- where they're shown (keep in step with the firmware) ------------------------------
def px(v: int) -> int:  # the 6x3 tiles' scale (board.cpp)
    return int(v * 0.68 + 0.5)


B, S = "5x2", "6x3"
SLOTS: list[tuple] = []  # (what, keys, mode, {layout: spec})


def slot(what, keys, mode, big, small=None):
    SLOTS.append((what, keys, mode, {B: big, **({S: small} if small else {})}))


# rollers (board.cpp build_roller_): the selected row's font steps down until the
# longest option fits inside the border (1 px each side; the row may use the padding);
# the other rows' font (roll / roll_s) a size down on 5x2 if needed
ROLLERS = {  # kind: (x offset, width, mid font, option keys, word key)
    "light": (44, 74, False, ["roller.off"], "roller.brightness"),
    "fan": (16, 72, False, ["roller.off"], "roller.speed"),
    "cover": (30, 84, True, ["roller.open", "roller.closed"], "roller.coverage"),
    "lock": (34, 96, True, ["roller.unlocked", "roller.locked"], "roller.doors"),
}
ROLLER_STEPS = {B: ["roll_mid", "roll_mid_s", "roll"], S: ["roll_mid_s", "roll_s"]}
for kind, (gx, w, mid, keys, word) in ROLLERS.items():
    first_b, first_s = ("roll_mid", "roll_mid_s") if mid else ("roll_sel", "roll_sel_s")
    slot(f"roller ({kind})", keys, "roller",
         ([first_b] + [f for f in ROLLER_STEPS[B] if f != first_b], w - 2),
         ([first_s] + [f for f in ROLLER_STEPS[S] if f != first_s], px(w) - 2))
    # its word, left of it to the tile's edge
    slot(f"roller word ({kind})", [word], "line", ("prefix", (196 - w) // 2 + gx - 6 - 2),
         ("prefix_s", 162 - 2 - px(w) - px(6) - 2))
slot("colour light word", ["roller.color_brightness"], "line", ("prefix", (196 - 60) // 2 + 44 - 6 - 2),
     ("prefix_s", 162 - 12 - 41 - px(6) - 2))
# tile status lines (board_kinds.cpp): broken to fit, at most this many lines
STEP_KEYS = [k for k in WORD["en"] if k.startswith(("step.", "appliance."))]
slot("appliance step", STEP_KEYS, "fit", ("roll", 74, 2), ("roll_s", px(74), 2))
slot("appliance time left", ["time.hours", "time.minutes"], "line", ("roll", 74), ("roll_s", px(74)))
slot("appliance: no data", ["appliance.no_data"], "line", ("roll", 196 - 24), ("roll_s", 162 - 16))
slot("vacuum status", [k for k in WORD["en"] if k.startswith("robot.") and not k.startswith("robot.queue.")],
     "fit", ("roll", 198 - 24, 2), ("roll_s", 164 - 2 * px(12), 2))
slot("pool status", [k for k in WORD["en"] if k.startswith("pool.short.")], "fit", ("roll", 92, 2),
     ("roll_s", 94, 2))
# the board's bar, edit mode, settings (board.cpp, board_edit.cpp)
slot("new device found (settings)", ["panel.new_found.one", "panel.new_found.other"], "line", ("prefix", 580 - 48 - 22))
slot("edit hint (top bar)", ["panel.edit_hint", "panel.move_hint"], "line", ("prefix", 560 - 42))  # (- the Room Tiles icon)
slot("Done editing button", ["panel.done_editing"], "line", ("name", 200 - 24))
slot("settings: slider name + value", ["panel.brightness", "panel.sleep"], "pair", ("name", 580 - 48 - 16))
slot("color picker: warm / cool", ["color.warm", "color.cool"], "line", ("prefix", 52))
slot("settings buttons", ["menu.tile_editor", "menu.language", "panel.screenshot", "panel.wifi_change", "panel.restart_panel"],
     "line", ("name", 256 - 36))
# the 24-hour clock switch: its word left of On / Off (board_edit.cpp open_settings_)
slot("settings: 24-hour clock switch", ["panel.clock_24h"], "line", ("name", 256 - 18 - 16 - 10 - 56))
slot("settings: On / Off", ["common.on", "common.off"], "line", ("name", 56))
# When idle (board_edit.cpp open_idle_list_: 540 wide, its choices two by two;
# the round panel's switches board_strip.cpp: 210 wide)
slot("When idle: choices", ["panel.idle_off", "panel.idle_digital", "panel.idle_analog", "panel.idle_theme"], "line",
     ("name", (540 - 12 - 6) // 2 - 28))
slot("When idle: switches", ["panel.idle_seconds", "panel.idle_anim"], "fit", ("prefix", 540 - 12 - 18 - 80, 2))
slot("When idle: switches (round)", ["panel.idle_seconds", "panel.idle_anim"], "fit", ("prefix", 210, 2))
# Screen off when the following area lights are off: its word over the room it follows
# (one line each; on the round panel three / two - its row grows)
ROOM_KEYS = ["panel.idle_room_where", "panel.idle_room_none", "panel.idle_room_no_lights"]
slot("When idle: room switch", ["panel.idle_room_dark"] + ROOM_KEYS, "line", ("prefix", 540 - 12 - 18 - 80))
slot("When idle: room switch (round)", ["panel.idle_room_dark"], "fit", ("prefix", 210, 3))  # (its row grows)
slot("When idle: room line (round)", ROOM_KEYS, "fit", ("prefix", 210, 2))
slot("restart confirm: buttons", ["common.cancel", "screen.restart"], "line", ("name", 180 - 20))
slot("area picker: Map button", ["help.title.view"], "line", ("name", 216 - 18 - 28 - 10 - 12))
slot("tile picker: All", ["panel.all"], "line", ("name_s", 64 - 8))
slot("tile picker: Remove", ["common.remove"], "line", ("name", 200 - 24))
slot("tile picker: Cancel / Assign", ["common.cancel", "panel.assign"], "line", ("name", 160 - 24))
slot("colour picker tabs", ["color.tab_color", "color.tab_white"], "line", ("prefix", 150 - 12))
slot("colour picker slider names", ["color.saturation", "color.brightness"], "line",
     ("prefix", 360 - 20 - 24 - 176 - 8))
# the map (map_queue.cpp, map_markers.cpp)
slot("queue: Start / Resume", ["queue.start", "queue.resume"], "line", ("name", 160 - 50 - 12))
slot("queue: status", ["robot.idle", "robot.docked", "robot.returning", "robot.paused"], "line", ("name", 240))
slot("queue: Clear", ["queue.clear"], "line", ("name", 140 - 24))
slot("queue: Start automatically", ["queue.auto_start"], "fit", ("roll_s", 80, 3))  # (48 px tall)
slot("pop-up tag (group / scene)", ["popup.group", "popup.scene"], "line", ("roll_s", 90 - 12))


# ---- the check ------------------------------------------------------------------------
def check() -> tuple[list, list, list]:
    misfits, smaller, forced = [], [], []
    for what, keys, mode, layouts in SLOTS:
        for layout, spec in layouts.items():
            for lang in LANGS:
                if mode == "roller":
                    steps, room = spec
                    words = [text_of(lang, k) for k in keys]
                    chosen = next((f for f in steps if max(width(f, w) for w in words) <= room), None)
                    # the other rows: the roller font (5x2: a size down if needed)
                    rows = "roll" if layout == B else "roll_s"
                    if layout == B and max(width(rows, w) for w in words) > room:
                        rows = "roll_s"
                    if max(width(rows, w) for w in words) > room:
                        widest = max(words, key=lambda w: width(rows, w))
                        misfits.append((what, layout, lang, keys, widest, width(rows, widest), room,
                                        "too wide in the other rows"))
                    if chosen is None:
                        widest = max(words, key=lambda w: width(steps[-1], w))
                        misfits.append((what, layout, lang, keys, widest, width(steps[-1], widest), room,
                                        "too wide even at the smallest size"))
                    elif chosen != steps[0]:
                        smaller.append((what, layout, lang, chosen, words))
                    continue
                fid, room = spec[0], spec[1]
                for key in keys:
                    t = text_of(lang, key)
                    if t is None:
                        continue
                    if mode == "pair":
                        v = max(text_of(lang, "panel.sleep_never"), text_of(lang, "panel.seconds"), "100 %",
                                key=lambda s: width(fid, s))
                        used = width(fid, t) + width(fid, v)
                        if used > room:
                            misfits.append((what, layout, lang, key, f"{t} | {v}", used, room, ""))
                    elif mode == "line":
                        used = max(width(fid, ln) for ln in t.split("\n"))
                        if used > room:
                            misfits.append((what, layout, lang, key, t, used, room, ""))
                    else:  # "fit": broken as the panel breaks it
                        lines, hard = fit_lines(t, fid, room)
                        if len(lines) > spec[2]:
                            misfits.append((what, layout, lang, key, t.replace(SHY, ""), len(lines), spec[2],
                                            " / ".join(lines)))
                        elif hard:
                            forced.append((what, layout, lang, key, t, " / ".join(lines)))
    return misfits, smaller, forced


def add_soft_hyphens(forced: list) -> int:
    """Soft hyphens (every syllable) in the words a status line had to break."""
    changed = 0
    for what, layout, lang, key, t, lines in forced:
        src_dir = WORD_DIR if key in WORD["en"] else FRONT_DIR
        path = src_dir / f"{lang}.json"
        data = _load(path)
        table = data["strings"]
        if key not in table:
            continue  # (the English fallback: give the language its own text first)
        dic = pyphen.Pyphen(lang=PYPHEN[lang])
        fid, room = next(spec for w, ks, m, ls in SLOTS for l, spec in ls.items() if w == what and l == layout)[:2]
        words = table[key].split(" ")
        for i, word in enumerate(words):
            if SHY not in word and width(fid, word) > room:
                words[i] = dic.inserted(word, hyphen=SHY)
        new = " ".join(words)
        if new != table[key]:
            table[key] = new
            text = json.dumps(data, ensure_ascii=False, indent=2).replace(SHY, "\\u00ad") + "\n"
            path.write_text(text, encoding="utf-8")
            (WORD if src_dir == WORD_DIR else FRONT)[lang][key] = new
            changed += 1
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--add-soft-hyphens", action="store_true", help="soft hyphens where a status line breaks a word")
    args = ap.parse_args()
    misfits, smaller, forced = check()
    if args.add_soft_hyphens and forced:
        print(f"soft hyphens added to {add_soft_hyphens(forced)} texts")
        misfits, smaller, forced = check()
    if smaller:
        print("Rollers at a smaller size (fine):")
        for what, layout, lang, font, words in smaller:
            print(f"  {what} {layout} {lang}: {font} - {', '.join(words)}")
    if forced:
        print("\nStatus lines that break a word with no break point (add soft hyphens: --add-soft-hyphens):")
        for what, layout, lang, key, t, lines in forced:
            print(f"  {what} {layout} {lang} {key}: {lines}")
    if misfits:
        print("\nDOESN'T FIT:")
        for what, layout, lang, key, t, used, room, note in sorted(misfits):
            unit = "lines" if isinstance(used, int) and used < 10 and note and "/" in note else "px"
            print(f"  {what} {layout} {lang} {key}: {t!r} {used}/{room} {unit} {note}")
    else:
        print("\nEverything fits.")
    return 1 if misfits else 0


if __name__ == "__main__":
    sys.exit(main())
