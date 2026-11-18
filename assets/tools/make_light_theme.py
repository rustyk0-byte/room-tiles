#!/usr/bin/env python3
"""The Light theme's artwork (needs Pillow).

  python3 assets/tools/make_light_theme.py

The masters are drawn for a dark background; on a light tile a few of them
vanish (white glyphs, white tracks and pills, a pale ladder / steam). This
writes darker versions of just those into assets/themes/light/ui/ - same
names, sizes and formats; every other picture comes from masters/. Only
the gray / white parts change (low saturation); coloured parts stay.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
MASTERS = HERE.parent / "masters" / "ui"
OUT = HERE.parent / "themes" / "light" / "ui"

INK = (58, 58, 58)  # the glyph-like icons: the theme's text, a little softer


def neutral(r: int, g: int, b: int) -> bool:
    return max(r, g, b) - min(r, g, b) < 28


def to_ink(img: Image.Image) -> Image.Image:
    """A white glyph-like icon (the grid, the gear) in dark gray."""
    out = img.copy()
    px = out.load()
    for y in range(out.height):
        for x in range(out.width):
            r, g, b, a = px[x, y]
            if a and neutral(r, g, b):
                k = (r + g + b) / 765  # (its shading kept: lighter parts stay a bit lighter)
                v = [round(c + (255 - c) * (1 - k) * 0.5) for c in INK]
                px[x, y] = (*v, a)
    return out


def darker(img: Image.Image, scale: float, floor: int = 0) -> Image.Image:
    """Grays / whites scaled darker (pale parts read on white)."""
    out = img.copy()
    px = out.load()
    for y in range(out.height):
        for x in range(out.width):
            r, g, b, a = px[x, y]
            if a and neutral(r, g, b) and max(r, g, b) > floor:
                px[x, y] = (round(r * scale), round(g * scale), round(b * scale), a)
    return out


ART = {
    "icon_grid_6x3": to_ink,
    "icon_settings": to_ink,
    "track_slider_h": lambda im: darker(im, 0.72),
    "track_slider_v": lambda im: darker(im, 0.72),
    "track_switch_off": lambda im: darker(im, 0.86),
    "track_switch_closed": lambda im: darker(im, 0.86),
    "track_switch_unlocked": lambda im: darker(im, 0.86),
    "icon_pool": lambda im: darker(im, 0.6, floor=150),
    "icon_spa": lambda im: darker(im, 0.62, floor=150),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, make in ART.items():
        src = Image.open(MASTERS / f"{name}.png").convert("RGBA")
        img = make(src)
        assert img.size == src.size
        img.save(OUT / f"{name}.png", optimize=True)
        print(f"{name}.png: {img.width}x{img.height}")


if __name__ == "__main__":
    main()
