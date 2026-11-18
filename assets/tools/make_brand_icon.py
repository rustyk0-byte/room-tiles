"""Room Tiles' icon as PNGs, from the master's geometry
(assets/masters/brand/room_tiles_icon.svg - option D: four rounded outlines
in the tile colours).

Writes HA's brand images into the integration (HA 2026.3+ loads a custom
integration's own `brand/` folder): icon.png (256), icon@2x.png (512) and the
same as dark_icon*.png (the colours read on light and dark backgrounds).
`--size N --out file.png` makes any other size (e.g. the panels' boot screen).

Drawn 4x larger and scaled down for smooth edges. Needs Pillow.
    python assets/tools/make_brand_icon.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / "custom_components" / "room_tiles" / "brand"

# the master SVG's geometry (viewBox 256): rect x, y, colour; all 80 x 80, rx 16, stroke 20
TILES = (
    (30, 30, "#FFB300"),  # lights
    (146, 30, "#4B9EF3"),  # the icon's blue tile (switches were blue when it was made; it stays)
    (30, 146, "#62A363"),  # covers
    (146, 146, "#9270AB"),  # locks
)
SIDE, RX, STROKE = 80, 16, 20
SUPER = 4


def render(size: int) -> Image.Image:
    big = size * SUPER
    k = big / 256
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    half = STROKE / 2
    for x, y, colour in TILES:
        # SVG strokes are centred on the outline; Pillow draws inward from its box
        box = [(x - half) * k, (y - half) * k, (x + SIDE + half) * k, (y + SIDE + half) * k]
        d.rounded_rectangle(box, radius=(RX + half) * k, outline=colour, width=round(STROKE * k))
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.size:
        render(args.size).save(args.out or Path(f"room_tiles_icon_{args.size}.png"), optimize=True)
        return
    BRAND.mkdir(parents=True, exist_ok=True)
    for name, size in (("icon.png", 256), ("icon@2x.png", 512), ("dark_icon.png", 256), ("dark_icon@2x.png", 512)):
        render(size).save(BRAND / name, optimize=True)
        print(f"{BRAND / name} ({size} px)")


if __name__ == "__main__":
    main()
