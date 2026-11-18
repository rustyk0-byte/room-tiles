#!/usr/bin/env python3
"""Build the wall panels' downloadable packs from assets/masters/ and the
dashboard's string tables (needs Pillow). docs/DESIGN.md "Panel firmware".

  python3 assets/build_panel.py

Writes:
  custom_components/room_tiles/panel_packs/theme-<theme>.rtp.gz   images + colours
  custom_components/room_tiles/panel_packs/theme-<theme>-round.rtp.gz  the same,
            only what the round panel draws (ROUND_SKIP: no 6x3 sizes, map
            markers, tile picker icons or large clock - its memory is small)
  custom_components/room_tiles/panel_packs/strings-<lang>.rtp.gz  wording
  (gzip in the repo - the theme is ~2.5 MB raw, ~230 KB packed; HA unpacks
  them once and serves them raw)
  firmware/components/room_tiles/rt_assets.h                   image slot ids

Image formats:
  I8X       (the default) 256 RGBA palette entries + 1 byte per pixel: the
            colours AND the alpha quantized together (libimagequant), so soft
            edges keep their in-between alphas. The panel expands one into
            RGB565A8 in PSRAM the first time it's drawn (LVGL would convert an
            I8 picture to ARGB8888 on EVERY draw) - a third of the flash.
  I8        sprite sheets / appliance stills: 256-colour palette (BGRA) + 1
            byte per pixel, on / off alpha; drawn by LVGL as they are
  RGB565A8  the exceptions (RGB565A8_ONLY: gradients and shading that 256
            colours would band, the brand icon's exact colours): 2 bytes
            colour (little endian) per pixel, then 1 byte alpha per pixel

Pack (.rtp), little endian:
  header 64 B: "RTP1", u16 version (= PANEL_SCHEMA: a panel takes only packs
               of its own format), u16 count, u32 data size (header +
               entries + data), u8 kind (1 theme / 2 strings), 3 pad,
               char id[32] (theme / language + content hash), 16 reserved
  entries, 56 B each: char name[32], u8 kind (1 image / 2 json), u8 format
               (1 I8 / 2 RGB565A8 / 3 I8X / 0 none), u16 w, u16 h, u16 stride,
               u32 offset (from the pack start), u32 size, 8 reserved
  data:        each entry's bytes, 16-byte aligned
  trailer:     SHA-256 of everything before it (the panel checks it)
The panel stores a pack as-is in its asset area and draws from it.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MASTERS = ROOT / "assets" / "masters"
OUT = ROOT / "custom_components" / "room_tiles" / "panel_packs"
HEADER = ROOT / "firmware" / "components" / "room_tiles" / "rt_assets.h"
I18N = ROOT / "frontend" / "i18n"
WORDING = ROOT / "custom_components" / "room_tiles" / "wording"
import theme_format  # noqa: E402  (assets/: the theme folders, read and checked)

THEMES = theme_format.ids()  # the default first (assets/themes/*/theme.json)
THEME_ART = ROOT / "assets" / "themes"  # <theme>/{ui,appliances}/: replaces masters by name

I8, RGB565A8, I8X = 1, 2, 3
# pictures kept RGB565A8 (by name start): gradients and shading 256 colours
# would band, and the brand icon (its squares' exact colours - check_brand)
RGB565A8_ONLY = ("hue_ring", "swatch_ring", "temp_track", "track_", "knob_", "brand_bar")
KIND_IMAGE, KIND_JSON = 1, 2
PACK_THEME, PACK_STRINGS = 1, 2
ENTRY = 56  # bytes per entry
COLS, ROWS = 8, 4  # appliance sprite sheets: 8 x 4 frames

# Sizes the panels show (1024x600, the same on every board):
SPRITE_SIZES = {"96": 96, "65": 65, "30": 30}  # appliance frame: 5x2 tile, 6x3 tile, map marker
# icons: as drawn (5x2), 6x3 tile, the tile picker's rows, a map marker's
# (30 px in its 40 px face - the dashboard's map.ts) + its gray "off" version
ICON_SIZES = {"": None, "s": 41, "m": 40, "mk": 30}
MARKER_ICON = "mk"
SMALL = 0.68  # 6x3 tiles' tracks / knobs (51x22 from 75x32)
# other art at its own panel sizes: suffix -> px (None = as drawn)
OWN_SIZES = {
    "hue_ring": {"": 116},  # the colour picker's ring
    "swatch_ring": {"": None, "s": 41},  # a colour light tile's swatch: 5x2 / 6x3
}


def art(theme: str, sub: str, name: str) -> Path:
    """A picture's file: the theme's own, else the master."""
    own = THEME_ART / theme / sub / name
    return own if own.exists() else MASTERS / sub / name


def off_art(theme: str, stem: str) -> Image.Image | None:
    """The theme's picture for an icon whose entity is off, if it has one."""
    own = THEME_ART / theme / "ui" / f"{stem}_off.png"
    return Image.open(own).convert("RGBA") if own.exists() else None


def panel_images(theme: str) -> list[tuple[str, Image.Image, int]]:
    """(slot name, RGBA image, format) for every image the panels use."""
    out: list[tuple[str, Image.Image, int]] = []
    for master in sorted((MASTERS / "appliances").glob("*.png")):
        img = Image.open(art(theme, "appliances", master.name)).convert("RGBA")
        sheet = img.width == 2 * img.height
        for suffix, frame in SPRITE_SIZES.items():
            size = (frame * COLS, frame * ROWS) if sheet else (frame, frame)
            out.append((f"{master.stem}_{suffix}", shrink(img, size), I8))
    for master in sorted((MASTERS / "ui").glob("*.png")):
        stem = master.stem
        img = Image.open(art(theme, "ui", master.name)).convert("RGBA")
        if stem.startswith("icon_"):
            off = off_art(theme, stem)
            for suffix, px in ICON_SIZES.items():
                if suffix == MARKER_ICON and stem not in OFF_BRIGHTNESS:
                    continue  # (the top bar's grid / gear: never a marker)
                name = f"{stem}_{suffix}" if suffix else stem
                sized = img if px is None else shrink(img, (px, px), snap=False)
                out.append((name, sized, ui_format(name)))
                if off is not None and suffix in ("", "s"):  # a tile's icon while off
                    out.append((f"{name}_off", off if px is None else shrink(off, (px, px), snap=False), ui_format(name)))
                if suffix == MARKER_ICON and stem in OFF_BRIGHTNESS:  # (not the top bar's own)
                    off_mk = sized if off is None else shrink(off, (px, px), snap=False)
                    out.append((f"{name}_off", off_gray(off_mk, OFF_BRIGHTNESS.get(stem, 0.8)), ui_format(name)))
        elif stem.startswith(("track_switch", "knob_switch", "lock_padlock")):
            out.append((stem, img, ui_format(stem)))
            small = (max(1, round(img.width * SMALL)), max(1, round(img.height * SMALL)))
            out.append((f"{stem}_s", shrink(img, small, snap=False), ui_format(stem)))
        elif stem in OWN_SIZES:
            for suffix, px in OWN_SIZES[stem].items():
                name = f"{stem}_{suffix}" if suffix else stem
                out.append((name, img if px is None else shrink(img, (px, px), snap=False), ui_format(name)))
        else:
            out.append((stem, img, ui_format(stem)))
    # pictures only a theme has (the top bar's buttons: bar_* - each fitted
    # into the one box, theme_format.BAR_ART), else as drawn
    own = THEME_ART / theme / "ui"
    for src in sorted(own.glob("*.png")) if own.exists() else []:
        if (MASTERS / "ui" / src.name).exists():
            continue  # (replaces a master: above)
        if src.stem.endswith("_off") and (MASTERS / "ui" / f"{src.stem[: -len('_off')]}.png").exists():
            continue  # (an icon's "off" picture: above)
        img = Image.open(src).convert("RGBA")
        if src.stem == "brand_bar":
            check_brand(theme, img)
        if src.stem in theme_format.BAR_ART:
            pair_src = own / f"{theme_format.BAR_PAIRS.get(src.stem, '')}.png"
            pair = Image.open(pair_src) if src.stem in theme_format.BAR_PAIRS and pair_src.exists() else None
            img = theme_format.fit_bar_art(img, theme_format.BAR_BOX_PANEL, pair)
        out.append((src.stem, img, ui_format(src.stem)))
    # the top bars' gear (the theme's own, else the default) and plain grid
    # (recoloured by the firmware: lit on 6x3), in the same box
    for name, src in (("bar_gear", art(theme, "ui", "icon_settings.png")), ("bar_grid_plain", MASTERS / "ui" / "icon_grid_6x3.png")):
        out.append((name, theme_format.fit_bar_art(Image.open(src), theme_format.BAR_BOX_PANEL), ui_format(name)))
    return out


# The top bars' Room Tiles icon (the firmware's own, firmware/images/): a theme
# may draw its own as ui/brand_bar.png - 48 x 48, the icon's four squares in
# the middle exactly as they are (size, place, color); around and behind them
# is the theme's
BRAND_ICON = ROOT / "firmware" / "images" / "brand_icon_36.png"
BRAND_BAR_SIZE = 48


BRAND_VISIBLE = 0.6  # (of each square's pixels: still there, in place and color)


def check_brand(theme: str, img: Image.Image) -> None:
    """A theme's brand_bar.png keeps the icon recognizable: its four squares
    where they are, in their colors. Art may be drawn over them (a wreath in
    front), but most of each square must still show: of every square's solid
    pixels (the plain icon, centered), at least BRAND_VISIBLE unchanged (a
    little leeway for rounding)."""
    if img.size != (BRAND_BAR_SIZE, BRAND_BAR_SIZE):
        raise SystemExit(f"{theme}: brand_bar.png is {img.width}x{img.height}, not {BRAND_BAR_SIZE}x{BRAND_BAR_SIZE}")
    plain = Image.open(BRAND_ICON).convert("RGBA")
    at = (BRAND_BAR_SIZE - plain.width) // 2
    # each square: its color's solid pixels (shown / all)
    squares: dict[tuple[int, int, int], list[int]] = {}
    for y in range(plain.height):
        for x in range(plain.width):
            r, g, b, a = plain.getpixel((x, y))
            if a < 255:
                continue
            key = (r >> 5, g >> 5, b >> 5)
            tr, tg, tb, ta = img.getpixel((x + at, y + at))
            shown = ta >= 250 and max(abs(r - tr), abs(g - tg), abs(b - tb)) <= 8
            n = squares.setdefault(key, [0, 0])
            n[0] += shown
            n[1] += 1
    squares = {k: n for k, n in squares.items() if n[1] >= 8}  # (the squares, not stray edge colors)
    hidden = [f"{100 - 100 * shown // total}%" for shown, total in squares.values() if shown < BRAND_VISIBLE * total]
    if hidden:
        raise SystemExit(
            f"{theme}: brand_bar.png covers too much of the icon's squares ({', '.join(hidden)} hidden) -"
            f" at most {round(100 * (1 - BRAND_VISIBLE))}% of each may be drawn over"
        )


def _off_brightness() -> dict[str, float]:
    """Off markers' gray per icon (frontend/src/map.ts OFF_BRIGHTNESS - one
    source for both): every icon the same gray, whatever the art's own
    brightness."""
    text = (ROOT / "frontend" / "src" / "map.ts").read_text(encoding="utf-8")
    block = re.search(r"const OFF_BRIGHTNESS[^{]*\{(.*?)\};", text, re.S)
    if not block:
        raise SystemExit("map.ts: OFF_BRIGHTNESS not found")
    return {k: float(v) for k, v in re.findall(r"(icon_\w+):\s*([0-9.]+)", block.group(1))}


OFF_BRIGHTNESS = _off_brightness()


def off_gray(img: Image.Image, brightness: float) -> Image.Image:
    """An off marker's icon: the dashboard's CSS grayscale(1) brightness(b) -
    gray keeps the art's detail (a flat recolour would be a silhouette)."""
    rgba = img.convert("RGBA")
    r, g, b, a = rgba.split()
    lum = Image.eval(
        Image.merge("RGB", (r, g, b)).convert("L", (0.2126, 0.7152, 0.0722, 0)),
        lambda v: min(255, round(v * brightness)),
    )
    return Image.merge("RGBA", (lum, lum, lum, a))


def shrink(img: Image.Image, size: tuple[int, int], snap: bool = True) -> Image.Image:
    """Resize in premultiplied alpha (no dark halos). `snap`: alpha back to
    on / off (sprite art never blends - same as the dashboard's)."""
    if img.size == size:
        return img
    small = img.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA")
    if snap:
        small.putalpha(small.getchannel("A").point(lambda a: 255 if a >= 128 else 0))
    return small


def to_i8(img: Image.Image) -> tuple[bytes, int]:
    """256-colour palette (BGRA, index 255 = transparent) + 1 byte / pixel."""
    rgba = img.convert("RGBA")
    mask = [a >= 128 for a in rgba.getchannel("A").tobytes()]
    pal_img = rgba.convert("RGB").quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    pal = pal_img.getpalette()[: 255 * 3]
    pal += [0] * (255 * 3 - len(pal))
    palette = bytearray()
    for i in range(255):
        r, g, b = pal[i * 3 : i * 3 + 3]
        palette += bytes((b, g, r, 255))
    palette += bytes((0, 0, 0, 0))
    idx = bytes(i if m else 255 for i, m in zip(pal_img.tobytes(), mask))
    return bytes(palette) + idx, img.width


def to_i8x(img: Image.Image) -> tuple[bytes, int]:
    """256 RGBA palette entries (BGRA) + 1 byte / pixel: colour and alpha
    quantized together (libimagequant - a soft edge keeps its in-between
    alphas; an on / off image just gets 0 / 255 entries)."""
    q = img.convert("RGBA").quantize(colors=256, method=Image.Quantize.LIBIMAGEQUANT, dither=Image.Dither.NONE)
    pal = q.getpalette(rawmode="RGBA")
    pal += [0] * (256 * 4 - len(pal))
    palette = bytearray()
    for i in range(256):
        r, g, b, a = pal[i * 4 : i * 4 + 4]
        palette += bytes((b, g, r, a))
    return bytes(palette) + q.tobytes(), img.width


def ui_format(name: str) -> int:
    """A ui picture's format: I8X unless it's an exception."""
    return RGB565A8 if name.startswith(RGB565A8_ONLY) else I8X


def to_rgb565a8(img: Image.Image) -> tuple[bytes, int]:
    raw = img.convert("RGBA").tobytes()
    colour = bytearray()
    for i in range(0, len(raw), 4):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        colour += struct.pack("<H", ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3))
    return bytes(colour) + raw[3::4], img.width * 2


def theme_colours(theme: str) -> dict[str, str]:
    """The theme's colour tokens (its theme.json - the dashboard reads the same)."""
    return theme_format.colours(theme)


# The idle clock's theme face (assets/themes/<theme>/clock.json + ui/clock_*.png;
# the firmware's idle_clock.cpp draws it): the face picture CLOCK_FACE x
# CLOCK_FACE, the hands' pictures pointing at 12 at their own fixed sizes.
#   center  [x, y]       where the hands turn, on the face
#   hands   hour / minute (second optional): pivot [x, y] in the hand's own
#           picture (it turns about that point), length (a scale, 0.3 - 1.5),
#           at [x, y] (optional: its own spot on the face instead of center)
#   date    (optional) at [x, y] on the face, align left | center | right,
#           font small | medium | large, color (#rrggbb or a theme colour's name)
#   cap     (optional, ui/clock_cap.png) at [x, y]: its middle there (default:
#           center) - e.g. a cap over the hands' pivot
#   order   (optional) the pieces back to front: face, date, hour, minute,
#           second, cap (default that order) - e.g. hands behind a small dial
CLOCK_FACE = 420
CLOCK_FACE_L = 560  # (optional: the same pieces at 4/3, for the wall panels)
CLOCK_HANDS = ("hour", "minute", "second")
CLOCK_PIECES = ("face", "date", "hour", "minute", "second", "cap")


def theme_clock(theme: str) -> dict | None:
    """The theme's clock.json, checked - None when the theme draws no clock."""
    path = THEME_ART / theme / "clock.json"
    if not path.exists():
        return None
    c = json.loads(path.read_text(encoding="utf-8"))
    ui = THEME_ART / theme / "ui"

    def bad(why: str) -> SystemExit:
        return SystemExit(f"{theme}/clock.json: {why}")

    def point(v, w, h, what):
        if not (isinstance(v, list) and len(v) == 2 and all(isinstance(n, (int, float)) for n in v)):
            raise bad(f"{what} isn't [x, y]")
        if not (0 <= v[0] <= w and 0 <= v[1] <= h):
            raise bad(f"{what} {v} is outside its {w} x {h} picture")

    face = ui / "clock_face.png"
    if not face.exists():
        raise bad("no ui/clock_face.png")
    if Image.open(face).size != (CLOCK_FACE, CLOCK_FACE):
        raise bad(f"clock_face.png must be {CLOCK_FACE} x {CLOCK_FACE}")
    # the large set (optional, the wall panels): every piece at CLOCK_FACE_L /
    # CLOCK_FACE - the same geometry scaled (clock.json stays in 420 units)
    if (ui / "clock_face_l.png").exists():
        k = CLOCK_FACE_L / CLOCK_FACE
        for small in sorted(ui.glob("clock_*.png")):
            if small.stem.endswith("_l"):
                continue
            large = ui / f"{small.stem}_l.png"
            w, h = Image.open(small).size
            want = (round(w * k), round(h * k))
            if not large.exists() or Image.open(large).size != want:
                raise bad(f"the large set needs {large.name} at {want[0]} x {want[1]}")
    point(c.get("center"), CLOCK_FACE, CLOCK_FACE, "center")
    hands = c.get("hands") or {}
    for name in ("hour", "minute"):
        if name not in hands:
            raise bad(f"no {name} hand")
    for name, hand in hands.items():
        if name not in CLOCK_HANDS:
            raise bad(f"unknown hand {name!r}")
        pic = ui / f"clock_{name}.png"
        if not pic.exists():
            raise bad(f"no ui/clock_{name}.png")
        w, h = Image.open(pic).size
        point(hand.get("pivot"), w, h, f"{name} pivot")
        if not 0.3 <= float(hand.get("length", 1.0)) <= 1.5:
            raise bad(f"{name} length must be 0.3 - 1.5")
        if "at" in hand:
            point(hand["at"], CLOCK_FACE, CLOCK_FACE, f"{name} at")
    cap = c.get("cap")
    if cap is not None:
        if not (ui / "clock_cap.png").exists():
            raise bad("a cap but no ui/clock_cap.png")
        if "at" in cap:
            point(cap["at"], CLOCK_FACE, CLOCK_FACE, "cap at")
    order = c.get("order")
    if order is not None:
        if not isinstance(order, list) or any(p not in CLOCK_PIECES for p in order) or len(set(order)) != len(order):
            raise bad(f"order lists pieces from {', '.join(CLOCK_PIECES)}, each once")
        for need in ("face", "hour", "minute"):
            if need not in order:
                raise bad(f"order leaves out {need}")
    date = c.get("date")
    if date is not None:
        point(date.get("at"), CLOCK_FACE, CLOCK_FACE, "date at")
        if date.get("align", "center") not in ("left", "center", "right"):
            raise bad("date align must be left, center or right")
        if date.get("font", "small") not in ("small", "medium", "large"):
            raise bad("date font must be small, medium or large")
        colour = date.get("color", "text")
        if not (re.fullmatch(r"#[0-9A-Fa-f]{6}", colour) or colour in theme_colours(theme)):
            raise bad(f"date color {colour!r} isn't #rrggbb or a theme colour")
    return c


def _panel_schema() -> int:
    """The panels' format number (custom_components/room_tiles/panels.py
    PANEL_SCHEMA - one source): every pack carries it, so a panel never takes
    a pack made for another format (the firmware's read_header), and HA never
    serves one its own code isn't for (panels.load_packs)."""
    text = (ROOT / "custom_components" / "room_tiles" / "panels.py").read_text(encoding="utf-8")
    m = re.search(r"^PANEL_SCHEMA = (\d+)", text, re.M)
    if not m:
        raise SystemExit("panels.py: PANEL_SCHEMA not found")
    return int(m.group(1))


PANEL_SCHEMA = _panel_schema()


def pack(kind: int, ident: str, entries: list[tuple[str, int, int, int, int, int, bytes]]) -> bytes:
    """entries: (name, kind, format, w, h, stride, data)."""
    count = len(entries)
    names = [e[0] for e in entries]
    assert len(set(names)) == count, "duplicate slot names"
    assert all(len(n.encode()) < 32 for n in names), "a slot name is too long (31 bytes max)"
    offset = 64 + ENTRY * count
    table = bytearray()
    blobs = bytearray()
    for name, ekind, fmt, w, h, stride, data in entries:
        pad = (-offset) % 16
        blobs += b"\0" * pad
        offset += pad
        table += struct.pack("<32sBBHHHII8x", name.encode(), ekind, fmt, w, h, stride, offset, len(data))
        blobs += data
        offset += len(data)
    head = struct.pack("<4sHHIB3x32s16x", b"RTP1", PANEL_SCHEMA, count, offset, kind, ident.encode()[:32])
    body = head + bytes(table) + bytes(blobs)
    assert len(body) == offset
    return body + hashlib.sha256(body).digest()


# MIRRORED: firmware/components/room_tiles/board_strip.cpp (the round panel's
# pictures) - a picture it starts drawing must not be skipped here.
# The round panel (one 5x2 strip, no map, no tile editing, 480 px) never
# draws the 6x3 sizes (_s, _65), the map's markers (_mk, _30, the Map
# button), the tile picker's icons (_m) or the wall panels' large clock (_l)
ROUND_SKIP_ENDINGS = ("_s", "_s_off", "_m", "_mk", "_mk_off", "_30", "_65", "_l")
ROUND_SKIP = {"bar_map", "bar_grid", "bar_grid_plain", "bar_help"}
ROUND_KEEP = {"icon_settings_s"}  # (its settings button: board_strip.cpp)


def round_uses(name: str) -> bool:
    return name in ROUND_KEEP or not (name.endswith(ROUND_SKIP_ENDINGS) or name in ROUND_SKIP)


def build_theme(theme: str, round_panel: bool = False) -> tuple[bytes, list[str]]:
    entries = []
    names = []
    for name, img, fmt in panel_images(theme):
        if round_panel and not round_uses(name):
            continue
        data, stride = to_i8(img) if fmt == I8 else to_i8x(img) if fmt == I8X else to_rgb565a8(img)
        entries.append((name, KIND_IMAGE, fmt, img.width, img.height, stride, data))
        names.append(name)
    colours = json.dumps(theme_colours(theme), separators=(",", ":"), sort_keys=True).encode()
    entries.append(("colors", KIND_JSON, 0, 0, 0, 0, colours))
    clock = theme_clock(theme)
    if clock is not None:
        entries.append(("clock", KIND_JSON, 0, 0, 0, 0, json.dumps(clock, separators=(",", ":")).encode()))
    digest = hashlib.sha256(b"".join(e[6] for e in entries)).hexdigest()[:12]
    ident = f"{theme}-round-{digest}" if round_panel else f"{theme}-{digest}"
    return pack(PACK_THEME, ident, entries), names


def build_strings(lang: str) -> bytes:
    """The language's table over English (a missing key = the English text):
    the dashboard's strings and the integration's wording (the status words
    the panel puts in its own language - tile_words)."""
    def read(folder: Path, code: str) -> dict:
        # (the tables keep their texts under "strings", next to "_about")
        f = folder / f"{code}.json"
        return json.loads(f.read_text(encoding="utf-8"))["strings"] if f.exists() else {}

    table: dict = {}
    for folder in (I18N, WORDING):
        table.update(read(folder, "en"))
        if lang != "en":
            table.update(read(folder, lang))
    for theme in THEMES:  # (each theme's name: its theme.json - the panels say "theme.<id>")
        table[f"theme.{theme}"] = theme_format.name(theme, lang)
    data = json.dumps(table, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    digest = hashlib.sha256(data).hexdigest()[:12]
    return pack(PACK_STRINGS, f"{lang}-{digest}", [("strings", KIND_JSON, 0, 0, 0, 0, data)])


def write_header(names: list[str]) -> None:
    lines = [
        "// GENERATED by assets/build_panel.py - don't edit. The theme pack's image",
        "// slots, in pack order: a pack lists the same names; the firmware looks",
        "// each one up by name when a pack is loaded.",
        "#pragma once",
        "",
        "namespace esphome::room_tiles {",
        "",
        "enum AssetId : int {",
    ]
    lines += [f"  IMG_{n.upper()}," for n in names]
    lines += ["  IMG_COUNT,", "};", "", "static const char *const ASSET_NAMES[IMG_COUNT] = {"]
    lines += [f'    "{n}",' for n in names]
    lines += ["};", ""]
    # a tile icon's "off" picture (a theme's: the image is missing from packs
    # that don't have one - then the icon looks the same on and off)
    pairs = [(n[: -len("_off")], n) for n in names if n.endswith("_off") and not n.endswith("_mk_off")]
    lines += [
        "// a tile icon's picture while its entity is off (IMG_COUNT: none)",
        "inline AssetId off_art(AssetId id) {",
        "  switch (id) {",
    ]
    lines += [f"    case IMG_{on.upper()}:\n      return IMG_{off.upper()};" for on, off in pairs if on in names]
    lines += ["    default:", "      return IMG_COUNT;", "  }", "}", "", "}  // namespace esphome::room_tiles", ""]
    HEADER.write_text("\n".join(lines), encoding="utf-8")


def _write(path: Path, data: bytes) -> None:
    # mtime=0: the same content gives the same file (no git noise); and an
    # unchanged pack isn't rewritten - the integration's update check
    # (update_watch.py) would take the new file time for an update
    packed = gzip.compress(data, 9, mtime=0)
    if path.exists() and path.read_bytes() == packed:
        return
    path.write_bytes(packed)


# The panels' asset area (firmware/partitions_16mb.csv "assets"): the theme
# from its start, the wording in its last STRINGS_REGION.
# MIRRORED: firmware/components/room_tiles/assets.cpp STRINGS_REGION - a change here must be made there too.
STRINGS_REGION = 256 * 1024


def _asset_area() -> int:
    for line in (ROOT / "firmware" / "partitions_16mb.csv").read_text(encoding="utf-8").splitlines():
        cols = [c.strip() for c in line.split(",")]
        if cols[0] == "assets":
            return int(cols[4], 0)
    raise SystemExit("partitions_16mb.csv: no assets partition")


THEME_MAX = _asset_area() - STRINGS_REGION


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    keep: set[Path] = set()
    names: list[str] = []
    for theme in THEMES:
        # (the format's checks first - the same the integration will run on
        # installed themes; this build takes each picture at its size only)
        problems = theme_format.check_pictures(THEME_ART / theme, scaled_ok=False)
        if problems:
            raise SystemExit("\n".join(problems))
        data, own = build_theme(theme)
        if len(data) > THEME_MAX:
            raise SystemExit(f"theme-{theme}: {len(data) / 1048576:.2f} MiB - more than the panels hold ({THEME_MAX / 1048576:.2f} MiB)")
        _write(OUT / f"theme-{theme}.rtp.gz", data)
        keep.add(OUT / f"theme-{theme}.rtp.gz")
        names += [n for n in own if n not in names]  # (every theme's slots)
        print(f"theme-{theme}: {len(data) / 1024:.0f} KB of {THEME_MAX // 1024} KB, {len(own)} images")
        # the round panel's: the same theme, only what it draws
        data, own = build_theme(theme, round_panel=True)
        _write(OUT / f"theme-{theme}-round.rtp.gz", data)
        keep.add(OUT / f"theme-{theme}-round.rtp.gz")
        print(f"theme-{theme}-round: {len(data) / 1024:.0f} KB, {len(own)} images")
    # every entity icon may have an "off" picture (a theme's <icon>_off.png,
    # any icon, any theme): its slots are always there, so a theme pack can
    # add one without a firmware update - a pack without it leaves it empty
    # (always last, in a fixed order: a theme gaining one never moves a slot)
    reserved = [f"{name}_off" for stem in OFF_BRIGHTNESS for name in (stem, f"{stem}_s") if name in names]
    # and every top-bar picture a theme may draw (theme_format.BAR_ART): the
    # same - a theme drawing its own grid or Help button needs no new firmware
    bar = [n for n in theme_format.BAR_ART if n != "icon_settings"]
    names = [n for n in names if n not in reserved and n not in bar] + bar + reserved
    langs = sorted(p.stem for p in I18N.glob("*.json"))
    for lang in langs:
        data = build_strings(lang)
        if len(data) > STRINGS_REGION:
            raise SystemExit(f"strings-{lang}: {len(data) // 1024} KB - more than the panels hold ({STRINGS_REGION // 1024} KB)")
        _write(OUT / f"strings-{lang}.rtp.gz", data)
        keep.add(OUT / f"strings-{lang}.rtp.gz")
    print(f"strings: {', '.join(langs)} ({len(build_strings('en')) / 1024:.0f} KB each, about)")
    for old in OUT.glob("*.rtp*"):
        if old not in keep:
            old.unlink()  # (a theme / language that's gone)
    write_header(names)
    # the themes the integration offers (its order: the default first)
    themes_json = json.dumps(
        [{"id": t, "name": {"en": theme_format.name(t, "en"), **{
            lang: theme_format.name(t, lang) for lang in sorted(p.stem for p in I18N.glob("*.json"))}}} for t in THEMES],
        ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
    if not (OUT / "themes.json").exists() or (OUT / "themes.json").read_bytes() != themes_json:
        (OUT / "themes.json").write_bytes(themes_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
