"""Recolour a master image to a tile colour, keeping its shading and greys.

    python assets/tools/recolor.py SRC DEST "#E2559B"

Every coloured pixel (not grey) gets the target's hue; its saturation and
brightness keep their place relative to the image's MAIN colour (its most
common coloured pixel), which lands exactly on the target. Grey pixels -
the icons' other half - and transparency stay as they are.
"""

from __future__ import annotations

import colorsys
import sys
from collections import Counter

from PIL import Image


def _hsv(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    return colorsys.rgb_to_hsv(*(c / 255 for c in rgb))


def recolor(src: str, dest: str, target: str, grey: float = 0.15) -> None:
    im = Image.open(src).convert("RGBA")
    px = list(im.getdata())
    coloured = [p[:3] for p in px if p[3] > 128 and _hsv(p[:3])[1] > grey]
    main = Counter(coloured).most_common(1)[0][0]
    _, ms, mv = _hsv(main)
    th, ts, tv = _hsv(tuple(int(target[i : i + 2], 16) for i in (1, 3, 5)))
    out = []
    for r, g, b, a in px:
        _, s, v = _hsv((r, g, b))
        if s <= grey or a == 0:
            out.append((r, g, b, a))
            continue
        ns = min(1.0, s * ts / ms) if ms else ts
        nv = min(1.0, v * tv / mv) if mv else tv
        nr, ng, nb = colorsys.hsv_to_rgb(th, ns, nv)
        out.append((round(nr * 255), round(ng * 255), round(nb * 255), a))
    im.putdata(out)
    im.save(dest)


if __name__ == "__main__":
    recolor(sys.argv[1], sys.argv[2], sys.argv[3])
