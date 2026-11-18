#!/usr/bin/env python3
"""Build the dashboard's artwork from assets/masters/ (needs Pillow).

  python3 assets/build_web.py OUT_DIR      (CI: the integration's frontend/)

Writes OUT_DIR/<theme>/...:
  appliances/<name>.webp  sprite sheets / stills, frames at 2x their CSS size
  ui/<name>.png           switch tracks, knobs, icons (copied)
A theme's own pictures (themes/<theme>/{appliances,ui}/, same names and sizes)
replace the masters; the rest come from masters/. themes/<theme>/ui/<icon>_off.png
= the icon's picture while its entity is off (frontend/src/theme.ts OFF_ART).
"""

import shutil
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
MASTERS = HERE / "masters"
THEME_ART = HERE / "themes"
sys.path.insert(0, str(Path(__file__).parent))
import theme_format  # noqa: E402  (the theme folders, read and checked)

THEMES = theme_format.ids()  # (assets/themes/*/theme.json)

COLS, ROWS = 8, 4  # sprite sheet layout (frontend/src/appliance.ts must match)
FRAME_CSS = 96  # largest size a frame is shown at in the dashboard, CSS px
FRAME_OUT = FRAME_CSS * 2  # pixels per frame: sharp on 2x screens (chosen 2026-11-07 over 1.5x)


def shrink(img: Image.Image, size: tuple[int, int]) -> tuple[Image.Image, list[bool]]:
    """Resize (premultiplied: no dark halos), then snap alpha back to fully
    transparent / fully opaque - the artwork uses on/off alpha only, never
    blending (same as the panels)."""
    small = img.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA")
    mask = [a >= 128 for _r, _g, _b, a in small.getdata()]
    # back to one 256-colour palette like the 8-bit masters: lossless WebP
    # then stores palette indices (small files). The palette is built from
    # the COLOURS only and the on/off alpha is put back from `mask`: quantizing
    # RGBA directly can merge "transparent" with a dark opaque colour, which
    # gave the washer's bubbles an opaque dark square (2026-11-08).
    rgb = small.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT).convert("RGB")
    out = Image.new("RGBA", size)
    out.putdata([(r, g, b, 255) if m else (0, 0, 0, 0) for (r, g, b), m in zip(rgb.getdata(), mask)])
    return out, mask


def art(theme: str, sub: str, name: str) -> Path:
    """A picture's file: the theme's own, else the master."""
    own = THEME_ART / theme / sub / name
    return own if own.exists() else MASTERS / sub / name


def build_appliances(theme: str, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for master in sorted((MASTERS / "appliances").glob("*.png")):
        src = art(theme, "appliances", master.name)
        img = Image.open(src).convert("RGBA")
        w, h = img.size
        sheet = (w, h) != (h, h) and w == 2 * h  # 8x4 of square frames
        size = (FRAME_OUT * COLS, FRAME_OUT * ROWS) if sheet else (FRAME_OUT, FRAME_OUT)
        dst = out / f"{src.stem}.webp"
        # lossless: compression must not soften the on/off alpha
        small, mask = shrink(img, size)
        small.save(dst, "WEBP", lossless=True, method=6)
        back = Image.open(dst).convert("RGBA")
        colours = len(back.getcolors(1 << 20) or [])
        # the written file must have exactly the master's transparency
        got = [a >= 128 for *_rgb, a in back.getdata()]
        if got != mask:
            raise SystemExit(f"{dst}: transparency changed in the build ({sum(g != m for g, m in zip(got, mask))} pixels)")
        clear = 100 * mask.count(False) // len(mask)
        print(f"{dst}: {size[0]}x{size[1]} {dst.stat().st_size // 1024} KB, {colours} colours, {clear}% transparent")


def build_ui(theme: str, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for master in sorted((MASTERS / "ui").glob("*.png")):
        shutil.copy2(art(theme, "ui", master.name), out / master.name)
    for own in sorted((THEME_ART / theme / "ui").glob("*.png")):
        shutil.copy2(own, out / own.name)  # (and what only the theme has: "off" pictures, bar_*)
    print(f"{out}: {len(list(out.glob('*.png')))} images")


def main() -> None:
    root = Path(sys.argv[1])
    for theme in THEMES:
        build_appliances(theme, root / theme / "appliances")
        build_ui(theme, root / theme / "ui")


if __name__ == "__main__":
    main()
