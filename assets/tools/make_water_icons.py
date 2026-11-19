"""Draw the pool and spa tile icons (masters/ui/icon_pool.png, icon_spa.png)
in the tile icons' flat style: water blue, light / mid greys. 60 x 60,
alpha on / off only. Replace with hand-made / AI art any time (same names).

    python3 assets/tools/make_water_icons.py [out_dir]   (default masters/ui)
"""

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

S = 8  # draw at 8x, shrink to 60 px
N = 60 * S
BLUE, DEEP = (52, 125, 230, 255), (36, 96, 190, 255)
LIGHT, MID = (216, 218, 220, 255), (158, 161, 165, 255)
STEAM = (200, 204, 208, 255)


def u(v):
    return v * S


def canvas():
    im = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def wave(d, x0, x1, y, amp, period, width, fill):
    """A thick sine line from x0 to x1 (60-px units)."""
    pts = []
    steps = 80
    for i in range(steps + 1):
        x = x0 + (x1 - x0) * i / steps
        pts.append((u(x), u(y + amp * math.sin((x - x0) / period * 2 * math.pi))))
    d.line(pts, fill=fill, width=round(u(width)), joint="curve")
    for p in (pts[0], pts[-1]):
        r = u(width) / 2
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=fill)


def stroke(d, pts, width, fill):
    """A thick line through `pts` (60-px units) with round ends and joints."""
    px = [(u(x), u(y)) for x, y in pts]
    d.line(px, fill=fill, width=round(u(width)), joint="curve")
    r = u(width) / 2
    for p in px:
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=fill)


def pool():
    """Pool: a ladder's two rails and rungs going down into waves."""
    im, d = canvas()
    for x in (21, 37):  # rails: down into the water, bent over the edge at the top
        bend = [(x + 7 - 7 * math.cos(a), 14 - 7 * math.sin(a)) for a in [math.pi * i / 24 for i in range(13)]]
        stroke(d, [(x + 7 + 3, 7), (x + 7, 7)] + bend[::-1][:-1] + [(x, 14), (x, 40)], 4, LIGHT)
    for y in (22, 31):
        d.rectangle([u(21), u(y - 1.5), u(37), u(y + 1.5)], fill=MID)
    wave(d, 6, 54, 43, 2.2, 16, 5, BLUE)
    wave(d, 6, 54, 52, 2.2, 16, 5, DEEP)
    return im


def spa():
    """Spa: a tub of water with three wisps of steam."""
    im, d = canvas()
    d.rounded_rectangle([u(6), u(32), u(54), u(54)], radius=u(6), fill=MID)  # tub
    d.rounded_rectangle([u(10), u(34), u(50), u(42)], radius=u(3), fill=BLUE)  # water
    d.rectangle([u(6), u(31), u(54), u(34)], fill=LIGHT)  # rim
    for x in (18, 30, 42):  # steam
        pts = [(u(x + 2.6 * math.sin(t / 14 * 2 * math.pi)), u(26 - t)) for t in [i * 0.25 for i in range(0, 81)]]
        d.line(pts, fill=STEAM, width=round(u(3.6)), joint="curve")
        for p in (pts[0], pts[-1]):
            r = u(3.6) / 2
            d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=STEAM)
    return im


def save(im, path):
    small = im.resize((60, 60), Image.LANCZOS)
    a = small.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    small.putalpha(a)
    small.save(path)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "custom_components" / "room_tiles" / "themes" / "masters" / "ui"
    save(pool(), out / "icon_pool.png")
    save(spa(), out / "icon_spa.png")
