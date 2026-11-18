#!/usr/bin/env python3
"""The generated "off" pictures of the themes that ask for them
(theme.json "off": "gray" - Dark and Light), made from their icons (needs
Pillow) - run by tools/build-frontend.sh, so they never fall behind.

  python3 assets/tools/make_off_icons.py

Writes assets/themes/<theme>/ui/<icon>_off.png for every entity icon: the
icon in gray - the map markers' off look exactly (build_panel.py off_gray,
map.ts OFF_BRIGHTNESS) - inside a thin outline in the tile type's full "on"
colour (the theme's token, as the markers' ring), shrunk so the outline ends
where the icon does: on and off are the same size. A tile and its marker
read alike: gray = off, the colour = what it is. Themes with off pictures
of their own (Christmas: no "off" in its theme.json) are left alone.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "assets"))
import build_panel as bp  # noqa: E402  (art(), off_gray(), OFF_BRIGHTNESS, theme_colours())

THEMES = [t["id"] for t in bp.theme_format.themes() if t.get("off") == "gray"]
# MIRRORED: frontend/src/map.ts ON_TOKEN / markerToken (a marker's colour) - a change here must be made there too.
TOKEN = {
    "icon_light": "light",
    "icon_switch": "switch",
    "icon_fan": "fan",
    "icon_blind": "cover",
    "icon_garage": "cover",
    "icon_key": "lock",
    "icon_ac": "heat",
    "icon_dishwasher": "light",
    "icon_laundry": "light",
    "icon_robot_vacuum": "accent",
    "icon_matic": "accent",
    "icon_pool": "mapWater",
    "icon_spa": "mapWater",
    "icon_scene": "scene",
    "icon_script": "script",
}
OUTLINE = 1.2  # px, at the icon's own size
K = 8  # (drawn at K x, for smooth edges)


def off_picture(img: Image.Image, brightness: float, colour: tuple[int, int, int]) -> Image.Image:
    w, h = img.size
    gray = bp.off_gray(img, brightness).resize((w * K, h * K), Image.LANCZOS)
    x0, y0, x1, y1 = img.getchannel("A").point(lambda v: 255 if v > 60 else 0).getbbox()
    s = min(((x1 - x0) - 2 * OUTLINE) / (x1 - x0), ((y1 - y0) - 2 * OUTLINE) / (y1 - y0))
    cx, cy = (x0 + x1) / 2 * K, (y0 + y1) / 2 * K
    small = gray.resize((round(w * K * s), round(h * K * s)), Image.LANCZOS)
    fitted = Image.new("RGBA", (w * K, h * K), (0, 0, 0, 0))
    fitted.alpha_composite(small, (round(cx - cx * s), round(cy - cy * s)))  # (about the icon's own middle)
    shape = fitted.getchannel("A").point(lambda v: 255 if v > 60 else 0)
    r = round(OUTLINE * K)
    edge = shape.filter(ImageFilter.MaxFilter(2 * r + 1)).filter(ImageFilter.GaussianBlur(K * 0.35))
    out = Image.new("RGBA", fitted.size, colour + (255,))
    out.putalpha(edge)
    out.alpha_composite(fitted)
    return out.resize((w, h), Image.LANCZOS)


def main() -> None:
    for theme in THEMES:
        colours = bp.theme_colours(theme)
        ui = bp.THEME_ART / theme / "ui"
        ui.mkdir(parents=True, exist_ok=True)
        for icon, token in TOKEN.items():
            hexc = colours[token]
            colour = tuple(int(hexc[i : i + 2], 16) for i in (1, 3, 5))
            img = Image.open(bp.art(theme, "ui", f"{icon}.png")).convert("RGBA")
            pic = off_picture(img, bp.OFF_BRIGHTNESS.get(icon, 0.8), colour)
            path = ui / f"{icon}_off.png"
            old = Image.open(path).convert("RGBA").tobytes() if path.exists() else None
            if old != pic.tobytes():  # (unchanged: not rewritten - no git noise)
                pic.save(path, optimize=True)
        print(f"{theme}: {len(TOKEN)} off pictures")


if __name__ == "__main__":
    main()
