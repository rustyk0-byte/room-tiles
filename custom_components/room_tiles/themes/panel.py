"""A theme's panel packs (docs/DESIGN.md "Panel firmware"): its pictures in
the panels' formats, its colours and clock, in one .rtp file the panel keeps
in its asset area and draws from. The same code builds the themes that come
with Room Tiles (assets/build_panel.py, at our build) and the ones a user
installs (installed.py, in Home Assistant).

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
               char id[32] (a name + content hash: the panel's "have it" check), 16 reserved
  entries, 56 B each: char name[32], u8 kind (1 image / 2 json), u8 format
               (1 I8 / 2 RGB565A8 / 3 I8X / 0 none), u16 w, u16 h, u16 stride,
               u32 offset (from the pack start), u32 size, 8 reserved
  data:        each entry's bytes, 16-byte aligned
  trailer:     SHA-256 of everything before it (the panel checks it)
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, features

from ..const import PANEL_SCHEMA
from . import fmt

MASTERS = fmt.MASTERS

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

# Off markers' gray per icon: every icon the same gray, whatever the art's
# own brightness. MIRRORED: frontend/src/map.ts OFF_BRIGHTNESS (one table -
# tests/test_theme_build.py checks they match).
OFF_BRIGHTNESS = {
    "icon_light": 0.8,
    "icon_switch": 1.2,
    "icon_fan": 0.77,
    "icon_blind": 0.92,
    "icon_key": 1.63,
    "icon_ac": 1.09,
    "icon_garage": 1.19,
    "icon_dishwasher": 0.72,
    "icon_laundry": 0.8,
    "icon_matic": 1.02,
    "icon_robot_vacuum": 0.79,
    "icon_pool": 1.01,
    "icon_spa": 0.88,
    "icon_scene": 0.95,
    "icon_script": 0.73,
}

# The top bars' Room Tiles icon (the firmware's own, firmware/images/): a theme
# may draw its own as ui/brand_bar.png - 48 x 48, the icon's four squares in
# the middle exactly as they are (size, place, color); around and behind them
# is the theme's. (A copy of firmware/images/brand_icon_36.png - the tests
# check they're the same.)
BRAND_ICON = Path(__file__).parent / "brand_icon_36.png"
BRAND_BAR_SIZE = 48
BRAND_VISIBLE = 0.6  # (of each square's pixels: still there, in place and color)

# The panels' asset area ("assets" in firmware/partitions_16mb.csv, the
# round panel's in partitions_s3_16mb.csv): the theme from its start, the
# wording in its last STRINGS_REGION.
# MIRRORED: firmware/components/room_tiles/assets.cpp STRINGS_REGION and the
# partition tables - tests/test_theme_build.py checks them.
ASSET_AREA = 0x5D0000
ASSET_AREA_ROUND = 0x7D0000
STRINGS_REGION = 256 * 1024
THEME_MAX = ASSET_AREA - STRINGS_REGION
THEME_MAX_ROUND = ASSET_AREA_ROUND - STRINGS_REGION

# The best palettes come from libimagequant (soft edges keep their
# in-between alphas); a Pillow without it quantizes with its own octree -
# a little coarser at soft edges, still correct.
HAS_LIQ = bool(features.check_feature("libimagequant"))


@dataclass
class Source:
    """A theme to build: its folder (None: only the default art) and its
    colours (the default theme's for any it leaves out)."""

    name: str  # for messages
    folder: Path | None
    colours: dict[str, str]
    clock: dict | None = None  # its clock.json, checked (fmt.clock)


def art(src: Source, sub: str, file: str) -> Path:
    """A picture's file: the theme's own, else the default art."""
    if src.folder is not None and (own := src.folder / sub / file).exists():
        return own
    return MASTERS / sub / file


def _open(path: Path, size: tuple[int, int] | None = None) -> Image.Image:
    """A picture, RGBA; one drawn at 2x / 4x brought to `size` (its master's)."""
    img = Image.open(path).convert("RGBA")
    return fmt.at_size(img, size) if size is not None else img


def _master_size(sub: str, file: str) -> tuple[int, int]:
    with Image.open(MASTERS / sub / file) as img:
        return img.size


def off_art(src: Source, stem: str, size: tuple[int, int]) -> Image.Image | None:
    """The theme's picture for an icon whose entity is off, if it has one."""
    if src.folder is None:
        return None
    own = src.folder / "ui" / f"{stem}_off.png"
    return _open(own, size) if own.exists() else None


def panel_images(src: Source) -> list[tuple[str, Image.Image, int]]:
    """(slot name, RGBA image, format) for every image the panels use."""
    out: list[tuple[str, Image.Image, int]] = []
    for master in sorted((MASTERS / "appliances").glob("*.png")):
        img = _open(art(src, "appliances", master.name), _master_size("appliances", master.name))
        sheet = img.width == 2 * img.height
        for suffix, frame in SPRITE_SIZES.items():
            size = (frame * COLS, frame * ROWS) if sheet else (frame, frame)
            out.append((f"{master.stem}_{suffix}", shrink(img, size), I8))
    for master in sorted((MASTERS / "ui").glob("*.png")):
        stem = master.stem
        msize = _master_size("ui", master.name)
        img = _open(art(src, "ui", master.name), msize)
        if stem.startswith("icon_"):
            off = off_art(src, stem, msize)
            for suffix, px in ICON_SIZES.items():
                if suffix == MARKER_ICON and stem not in OFF_BRIGHTNESS:
                    continue  # (the top bar's grid / gear: never a marker)
                pic = f"{stem}_{suffix}" if suffix else stem
                sized = img if px is None else shrink(img, (px, px), snap=False)
                out.append((pic, sized, ui_format(pic)))
                if off is not None and suffix in ("", "s"):  # a tile's icon while off
                    out.append((f"{pic}_off", off if px is None else shrink(off, (px, px), snap=False), ui_format(pic)))
                if suffix == MARKER_ICON and stem in OFF_BRIGHTNESS:  # (not the top bar's own)
                    off_mk = sized if off is None else shrink(off, (px, px), snap=False)
                    out.append((f"{pic}_off", off_gray(off_mk, OFF_BRIGHTNESS.get(stem, 0.8)), ui_format(pic)))
        elif stem.startswith(("track_switch", "knob_switch", "lock_padlock")):
            out.append((stem, img, ui_format(stem)))
            small = (max(1, round(img.width * SMALL)), max(1, round(img.height * SMALL)))
            out.append((f"{stem}_s", shrink(img, small, snap=False), ui_format(stem)))
        elif stem in OWN_SIZES:
            for suffix, px in OWN_SIZES[stem].items():
                pic = f"{stem}_{suffix}" if suffix else stem
                out.append((pic, img if px is None else shrink(img, (px, px), snap=False), ui_format(pic)))
        else:
            out.append((stem, img, ui_format(stem)))
    # pictures only a theme has (the top bar's buttons: bar_* - each fitted
    # into the one box, fmt.BAR_ART), else as drawn
    own = src.folder / "ui" if src.folder is not None else None
    for file in sorted(own.glob("*.png")) if own is not None and own.exists() else []:
        if (MASTERS / "ui" / file.name).exists():
            continue  # (replaces a master: above)
        if file.stem.endswith("_off") and (MASTERS / "ui" / f"{file.stem[: -len('_off')]}.png").exists():
            continue  # (an icon's "off" picture: above)
        size = fmt.OWN_SIZES.get(file.stem)
        img = _open(file, size)
        if file.stem == "brand_bar":
            check_brand(src.name, img)
        if file.stem in fmt.BAR_ART:
            pair_file = own / f"{fmt.BAR_PAIRS.get(file.stem, '')}.png"
            pair = Image.open(pair_file) if file.stem in fmt.BAR_PAIRS and pair_file.exists() else None
            img = fmt.fit_bar_art(img, fmt.BAR_BOX_PANEL, pair)
        out.append((file.stem, img, ui_format(file.stem)))
    # the top bars' gear (the theme's own, else the default) and plain grid
    # (recoloured by the firmware: lit on 6x3), in the same box
    for pic, file in (("bar_gear", art(src, "ui", "icon_settings.png")), ("bar_grid_plain", MASTERS / "ui" / "icon_grid_6x3.png")):
        out.append((pic, fmt.fit_bar_art(Image.open(file), fmt.BAR_BOX_PANEL), ui_format(pic)))
    return out


def check_brand(theme: str, img: Image.Image) -> None:
    """A theme's brand_bar.png keeps the icon recognizable: its four squares
    where they are, in their colors. Art may be drawn over them (a wreath in
    front), but most of each square must still show: of every square's solid
    pixels (the plain icon, centered), at least BRAND_VISIBLE unchanged (a
    little leeway for rounding)."""
    if img.size != (BRAND_BAR_SIZE, BRAND_BAR_SIZE):
        raise fmt.ThemeError(f"{theme}: brand_bar.png is {img.width}x{img.height}, not {BRAND_BAR_SIZE}x{BRAND_BAR_SIZE}")
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
        raise fmt.ThemeError(
            f"{theme}: brand_bar.png covers too much of the icon's squares ({', '.join(hidden)} hidden) -"
            f" at most {round(100 * (1 - BRAND_VISIBLE))}% of each may be drawn over"
        )


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
    quantized together (a soft edge keeps its in-between alphas; an on / off
    image just gets 0 / 255 entries)."""
    method = Image.Quantize.LIBIMAGEQUANT if HAS_LIQ else Image.Quantize.FASTOCTREE
    q = img.convert("RGBA").quantize(colors=256, method=method, dither=Image.Dither.NONE)
    pal = q.getpalette(rawmode="RGBA")
    pal += [0] * (256 * 4 - len(pal))
    palette = bytearray()
    for i in range(256):
        r, g, b, a = pal[i * 4 : i * 4 + 4]
        palette += bytes((b, g, r, a))
    return bytes(palette) + q.tobytes(), img.width


def ui_format(pic: str) -> int:
    """A ui picture's format: I8X unless it's an exception."""
    return RGB565A8 if pic.startswith(RGB565A8_ONLY) else I8X


def to_rgb565a8(img: Image.Image) -> tuple[bytes, int]:
    raw = img.convert("RGBA").tobytes()
    colour = bytearray()
    for i in range(0, len(raw), 4):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        colour += struct.pack("<H", ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3))
    return bytes(colour) + raw[3::4], img.width * 2


def pack(kind: int, ident: str, entries: list[tuple[str, int, int, int, int, int, bytes]]) -> bytes:
    """entries: (name, kind, format, w, h, stride, data)."""
    count = len(entries)
    names = [e[0] for e in entries]
    assert len(set(names)) == count, "duplicate slot names"
    assert all(len(n.encode()) < 32 for n in names), "a slot name is too long (31 bytes max)"
    assert len(ident.encode()) <= 32, "a pack id is too long (32 bytes max: it ends in the content hash)"
    offset = 64 + ENTRY * count
    table = bytearray()
    blobs = bytearray()
    for slot, ekind, form, w, h, stride, data in entries:
        pad = (-offset) % 16
        blobs += b"\0" * pad
        offset += pad
        table += struct.pack("<32sBBHHHII8x", slot.encode(), ekind, form, w, h, stride, offset, len(data))
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


def round_uses(pic: str) -> bool:
    return pic in ROUND_KEEP or not (pic.endswith(ROUND_SKIP_ENDINGS) or pic in ROUND_SKIP)


def build_theme(src: Source, ident: str, images: list | None = None, round_panel: bool = False) -> tuple[bytes, list[str]]:
    """The pack and its image slots' names. `ident` names it (the content
    hash is added: "<ident>-<hash>", 32 bytes at most). `images`: from
    panel_images(src) - pass them to build the wall and round packs from one
    pass over the pictures."""
    entries = []
    names = []
    for slot, img, form in images if images is not None else panel_images(src):
        if round_panel and not round_uses(slot):
            continue
        data, stride = to_i8(img) if form == I8 else to_i8x(img) if form == I8X else to_rgb565a8(img)
        entries.append((slot, KIND_IMAGE, form, img.width, img.height, stride, data))
        names.append(slot)
    colours = json.dumps(src.colours, separators=(",", ":"), sort_keys=True).encode()
    entries.append(("colors", KIND_JSON, 0, 0, 0, 0, colours))
    if src.clock is not None:
        entries.append(("clock", KIND_JSON, 0, 0, 0, 0, json.dumps(src.clock, separators=(",", ":")).encode()))
    digest = hashlib.sha256(b"".join(e[6] for e in entries)).hexdigest()[:12]
    return pack(PACK_THEME, f"{ident}-{digest}", entries), names
