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

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "assets"))
import build_panel as bp  # noqa: E402  (art(), OFF_BRIGHTNESS, theme_colours())
from _themekit import off  # noqa: E402  (the pictures themselves: themes/off.py)

THEMES = [t["id"] for t in bp.theme_format.themes() if t.get("off") == "gray"]
def main() -> None:
    for theme in THEMES:
        colours = bp.theme_colours(theme)
        ui = bp.THEME_ART / theme / "ui"
        ui.mkdir(parents=True, exist_ok=True)
        for icon in off.TOKEN:
            colour = off.colour_of(colours, icon)
            img = Image.open(bp.art(theme, "ui", f"{icon}.png")).convert("RGBA")
            pic = off.off_picture(img, bp.OFF_BRIGHTNESS.get(icon, 0.8), colour)
            path = ui / f"{icon}_off.png"
            old = Image.open(path).convert("RGBA").tobytes() if path.exists() else None
            if old != pic.tobytes():  # (unchanged: not rewritten - no git noise)
                pic.save(path, optimize=True)
        print(f"{theme}: {len(off.TOKEN)} off pictures")


if __name__ == "__main__":
    main()
