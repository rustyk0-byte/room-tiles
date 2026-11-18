"""Draw the scene and script tile icons (masters/ui/icon_scene.png,
icon_script.png) in the tile icons' flat style: a scene = an artist's
palette in the scene teal, a script = a scroll with a play mark in the
script orange. 60 x 60, alpha on / off only. Replace with hand-made / AI
art any time (same names).

    python3 assets/tools/make_run_icons.py [out_dir]   (default masters/ui)
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

S = 8  # draw at 8x, shrink to 60 px
N = 60 * S
SCENE, SCRIPT = (46, 196, 182, 255), (255, 143, 63, 255)  # theme scene / script
LIGHT, MID = (216, 218, 220, 255), (158, 161, 165, 255)
DOTS = [(255, 179, 0, 255), (226, 85, 155, 255), (75, 201, 243, 255), LIGHT]  # light, switch, fan, white


def u(v):
    return v * S


def canvas():
    im = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def scene():
    """An artist's palette with four paint dots and a thumb hole."""
    im, d = canvas()
    d.ellipse([u(6), u(10), u(54), u(50)], fill=SCENE)
    d.ellipse([u(34), u(34), u(44), u(44)], fill=(0, 0, 0, 0))
    for (x, y), c in zip([(18, 22), (30, 17), (42, 22), (16, 34)], DOTS):
        d.ellipse([u(x - 4.2), u(y - 4.2), u(x + 4.2), u(y + 4.2)], fill=c)
    return im


def script():
    """A scroll (paper, rolled top) with a play mark."""
    im, d = canvas()
    d.rounded_rectangle([u(12), u(10), u(46), u(52)], radius=u(3), fill=LIGHT)
    d.ellipse([u(8), u(6), u(20), u(16)], fill=MID)
    d.rectangle([u(14), u(6), u(50), u(12)], fill=MID)
    d.ellipse([u(44), u(6), u(54), u(16)], fill=MID)
    d.polygon([(u(23), u(22)), (u(23), u(44)), (u(41), u(33))], fill=SCRIPT)
    return im


def save(im, path):
    small = im.resize((60, 60), Image.LANCZOS)
    small.putalpha(small.getchannel("A").point(lambda v: 255 if v >= 128 else 0))
    small.save(path)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "masters" / "ui"
    save(scene(), out / "icon_scene.png")
    save(script(), out / "icon_script.png")
