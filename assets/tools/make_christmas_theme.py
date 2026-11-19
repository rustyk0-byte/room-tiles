#!/usr/bin/env python3
"""Draw the Christmas theme's artwork (needs Pillow).

  python3 assets/tools/make_christmas_theme.py

Writes assets/themes/christmas/{ui,appliances}/*.png - the same names, sizes
and formats as custom_components/room_tiles/themes/masters/ (a theme replaces any master by name; what it
doesn't replace comes from masters/). `<icon>_off.png` is a theme's picture
for an icon when its entity is off (the reindeer's nose goes dark, the tree's
lights go out); without one an icon looks the same on and off. `bar_*.png`
are pictures for the top bar's buttons, which otherwise show icon glyphs
(Area Lights: `bar_area_lights` / `_off`, Map: `bar_map`, 44 x 34); `tile_map`
(+ `_s`, 6x3) the Map tile's picture; `run_gift` (+ `_s`) the scene / script
tiles' play button; `brand_bar` (48 x 48) the top bars' Room Tiles icon - its
four squares unchanged in the middle (here: hung in a wreath).

Everything is drawn at 8x and scaled down. Icons keep soft edges like the
masters; appliance pictures and sheets get on/off alpha (they never blend).
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
MASTERS = HERE.parents[1] / "custom_components" / "room_tiles" / "themes" / "masters"
OUT = HERE.parent / "themes" / "christmas"
SS = 8  # supersampling
# pictures only a theme has (no master): their sizes - the firmware / dashboard
# use them when the theme has them (the top bar's Area Lights button)
OWN_ART = {
    "bar_area_lights": (44, 34),
    "bar_map": (44, 34),
    "tile_map": (76, 58),
    "tile_map_s": (52, 40),
    "run_gift": (60, 60),
    "run_gift_s": (41, 41),
    "brand_bar": (48, 48),
    # the idle clock's theme face (clock.json says where the hands turn)
    "clock_face": (420, 420),
    "clock_hour": (54, 116),
    "clock_minute": (50, 156),
    "clock_second": (48, 170),
    "clock_cap": (26, 26),
    # the large clock (the wall panels): the same drawings at 4/3
    "clock_face_l": (560, 560),
    "clock_hour_l": (72, 155),
    "clock_minute_l": (67, 208),
    "clock_second_l": (64, 227),
    "clock_cap_l": (35, 35),
}
# the top bars' Room Tiles icon (the firmware's own): a theme's brand_bar keeps
# its four squares as they are, centered - only around / behind them is the theme's
BRAND_ICON = HERE.parents[1] / "firmware" / "images" / "brand_icon_36.png"

# palette
INK = (34, 20, 12, 255)  # outlines (warm near-black)
RED = (220, 38, 38, 255)
RED_DK = (150, 20, 24, 255)
GREEN = (46, 139, 71, 255)
GREEN_DK = (24, 94, 46, 255)
GOLD = (255, 200, 60, 255)
GOLD_DK = (196, 140, 30, 255)
WHITE = (250, 250, 248, 255)
SNOW = (236, 244, 250, 255)
BROWN = (138, 85, 48, 255)
TAN = (206, 160, 112, 255)
ANTLER = (222, 178, 118, 255)
ICE = (150, 220, 255, 255)
ICE_DK = (40, 110, 160, 255)


# ---- drawing helpers ------------------------------------------------------------


class Canvas:
    """An RGBA layer at SS x; coordinates are in output pixels."""

    def __init__(self, w: int, h: int, ss: int = SS) -> None:
        self.w, self.h, self.ss = w, h, ss
        self.im = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.im)

    def layer(self) -> "Canvas":
        return Canvas(self.w, self.h, self.ss)

    def p(self, pts):
        return [(x * self.ss, y * self.ss) for x, y in pts]

    def ellipse(self, cx, cy, rx, ry=None, fill=None, outline=None, width=0.0):
        ry = rx if ry is None else ry
        s = self.ss
        self.d.ellipse(
            [(cx - rx) * s, (cy - ry) * s, (cx + rx) * s, (cy + ry) * s],
            fill=fill,
            outline=outline,
            width=max(0, round(width * s)),
        )

    def rot_ellipse(self, cx, cy, rx, ry, deg, fill, n=48):
        a = math.radians(deg)
        pts = []
        for i in range(n):
            t = 2 * math.pi * i / n
            x, y = rx * math.cos(t), ry * math.sin(t)
            pts.append((cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a)))
        self.poly(pts, fill)

    def poly(self, pts, fill=None, outline=None, width=0.0):
        self.d.polygon(self.p(pts), fill=fill, outline=outline, width=max(0, round(width * self.ss)) if outline else 0)

    def line(self, pts, fill, width, caps=True):
        s = self.ss
        self.d.line(self.p(pts), fill=fill, width=max(1, round(width * s)), joint="curve")
        if caps:
            for x, y in (pts[0], pts[-1]):
                self.ellipse(x, y, width / 2, fill=fill)

    def rect(self, x0, y0, x1, y1, fill=None, radius=0.0, outline=None, width=0.0):
        s = self.ss
        self.d.rounded_rectangle(
            [x0 * s, y0 * s, x1 * s, y1 * s],
            radius=radius * s,
            fill=fill,
            outline=outline,
            width=max(0, round(width * s)),
        )

    def paste(self, other: "Canvas") -> "Canvas":
        self.im.alpha_composite(other.im)
        return self

    def under(self, other: "Canvas") -> "Canvas":
        """Put `other` beneath this layer."""
        base = other.im.copy()
        base.alpha_composite(self.im)
        self.im = base
        self.d = ImageDraw.Draw(self.im)
        return self

    def outlined(self, px: float, color=INK) -> "Canvas":
        """A dark outline px wide around everything drawn so far."""
        r = px * self.ss
        a = self.im.getchannel("A").filter(ImageFilter.GaussianBlur(r * 0.75))
        a = a.point(lambda v: 255 if v > 10 else 0)
        edge = Image.new("RGBA", self.im.size, color)
        edge.putalpha(a)
        edge.alpha_composite(self.im)
        self.im = edge
        self.d = ImageDraw.Draw(self.im)
        return self

    def clip(self, mask: Image.Image) -> "Canvas":
        """Keep only where `mask` (L, same size) is set."""
        self.im.putalpha(ImageChops.multiply(self.im.getchannel("A"), mask))
        return self

    def alpha(self) -> Image.Image:
        return self.im.getchannel("A")

    def out(self, snap: bool = False, size: tuple[int, int] | None = None) -> Image.Image:
        size = size or (self.w, self.h)
        small = self.im.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA")
        if snap:
            small.putalpha(small.getchannel("A").point(lambda a: 255 if a >= 128 else 0))
        return small


def glow(c: Canvas, cx, cy, r, color, strength=200) -> Canvas:
    """A soft round glow (its own layer)."""
    g = c.layer()
    g.ellipse(cx, cy, r * 0.62, fill=color[:3] + (strength,))
    g.im = g.im.filter(ImageFilter.GaussianBlur(r * 0.38 * c.ss))
    return g


def star_pts(cx, cy, r_out, r_in, n=5, rot=-90.0):
    pts = []
    for i in range(n * 2):
        r = r_out if i % 2 == 0 else r_in
        a = math.radians(rot + i * 180.0 / n)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def sparkle(c: Canvas, cx, cy, r, color=WHITE):
    """A 4-point twinkle."""
    c.poly(star_pts(cx, cy, r, r * 0.28, n=4, rot=-90), fill=color)


def snowflake(c: Canvas, cx, cy, r, color, edge=None, width=None, rot=0.0):
    width = width or max(0.6, r * 0.16)
    layer = c.layer()
    for i in range(6):
        a = math.radians(rot + i * 60)
        ex, ey = cx + r * math.cos(a), cy + r * math.sin(a)
        layer.line([(cx, cy), (ex, ey)], color, width)
        for f, ln in ((0.5, 0.36), (0.78, 0.24)):
            bx, by = cx + r * f * math.cos(a), cy + r * f * math.sin(a)
            for s in (-1, 1):
                b = a + s * math.radians(50)
                layer.line([(bx, by), (bx + r * ln * math.cos(b), by + r * ln * math.sin(b))], color, width * 0.85)
    layer.ellipse(cx, cy, width * 1.1, fill=color)
    if edge:
        layer.outlined(max(0.5, width * 0.45), edge)
    c.paste(layer)


def holly(c: Canvas, cx, cy, s=1.0, rot=0.0, berries=3):
    """Two holly leaves and red berries."""
    layer = c.layer()
    for side in (-1, 1):
        a = math.radians(rot + (200 if side < 0 else -20))
        pts = []
        n = 10
        L, Wd = 9 * s, 3.4 * s
        for i in range(n + 1):  # spiky leaf: one edge out, the other back
            t = i / n
            w = Wd * math.sin(math.pi * t) * (1.0 if i % 2 == 0 else 0.62)
            pts.append((t * L, -w))
        for i in range(n, -1, -1):
            t = i / n
            w = Wd * math.sin(math.pi * t) * (1.0 if i % 2 == 0 else 0.62)
            pts.append((t * L, w))
        pts = [(cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a)) for x, y in pts]
        layer.poly(pts, fill=GREEN)
        layer.line([(cx, cy), (cx + L * 0.85 * math.cos(a), cy + L * 0.85 * math.sin(a))], GREEN_DK, 0.6 * s, caps=False)
    for i in range(berries):
        a = math.radians(rot + 90 + (i - (berries - 1) / 2) * 55)
        bx, by = cx + 2.2 * s * math.cos(a), cy + 2.2 * s * math.sin(a) - 0.5 * s
        layer.ellipse(bx, by, 1.9 * s, fill=RED)
        layer.ellipse(bx - 0.6 * s, by - 0.6 * s, 0.55 * s, fill=(255, 190, 190, 255))
    layer.outlined(0.55 * s)
    c.paste(layer)


def santa_hat(c: Canvas, x, y, s=1.0, rot=0.0):
    """A Santa hat whose fur band is centred at (x, y), width ~20*s; the tip
    flops to the right."""
    layer = c.layer()

    def tf(pts):
        a = math.radians(rot)
        return [(x + px * s * math.cos(a) - py * s * math.sin(a), y + px * s * math.sin(a) + py * s * math.cos(a)) for px, py in pts]

    cone = [(-9, 0), (-7, -8), (-2, -14), (4, -16), (10, -13), (14, -8), (15, -3), (12, -6), (8, -9), (5, -7), (8, 0)]
    layer.poly(tf(cone), fill=RED)
    shade = [(2, -2), (5, -7), (8, -9), (12, -6), (15, -3), (8, 0)]
    layer.poly(tf(shade), fill=RED_DK)
    for px in range(-10, 11, 3):  # fur band: overlapping puffs
        (bx, by), = tf([(px, 0.5)])
        layer.ellipse(bx, by, 2.6 * s, fill=WHITE)
    (tx, ty), = tf([(15, -2)])
    layer.ellipse(tx, ty, 3.0 * s, fill=WHITE)
    layer.outlined(0.7 * s)
    c.paste(layer)


def ribbon_bow(c: Canvas, cx, cy, s=1.0, color=RED, dark=RED_DK):
    layer = c.layer()
    for side in (-1, 1):
        layer.poly([(cx, cy), (cx + side * 7 * s, cy - 4.5 * s), (cx + side * 7.5 * s, cy + 3.5 * s)], fill=color)
        layer.poly([(cx, cy), (cx + side * 4 * s, cy + 8 * s), (cx + side * 1.4 * s, cy + 8.5 * s)], fill=dark)
    layer.ellipse(cx, cy, 2.2 * s, fill=dark)
    layer.outlined(0.6 * s)
    c.paste(layer)


# ---- icons (60 x 60 unless noted) --------------------------------------------------


def reindeer(lit: bool) -> Image.Image:
    """The light: a reindeer whose nose is a light bulb - lit when the light is on."""
    c = Canvas(60, 60)
    head = c.layer()
    for side in (-1, 1):  # antlers
        X = lambda x: 30 + side * (30 - x)  # noqa: E731
        head.line([(X(25), 21), (X(21), 15), (X(19), 9), (X(20.5), 3)], ANTLER, 3.0)
        head.line([(X(21), 15), (X(14.5), 12.5), (X(11), 7)], ANTLER, 2.6)
        head.line([(X(19.6), 10.5), (X(15), 6.5)], ANTLER, 2.2)
        head.line([(X(15), 13.4), (X(13.5), 17.5)], ANTLER, 2.0)
    for side in (-1, 1):  # ears
        head.rot_ellipse(30 + side * 14.5, 26, 6.2, 2.9, side * -28, BROWN)
        head.rot_ellipse(30 + side * 14.8, 26, 3.6, 1.4, side * -28, (240, 160, 160, 255))
    head.ellipse(30, 30, 13, 13.5, fill=BROWN)
    head.ellipse(30, 41.5, 10.5, 8.2, fill=TAN)
    head.ellipse(30, 21, 6, 3.4, fill=(160, 104, 62, 255))  # tuft
    head.outlined(1.15)
    face = head.layer()
    for side in (-1, 1):
        ex = 30 + side * 5.4
        face.ellipse(ex, 29, 3.3, 3.9, fill=WHITE)
        face.ellipse(ex - side * 0.6, 29.9, 2.05, fill=(30, 22, 18, 255))
        face.ellipse(ex - side * 0.6 + 0.8, 28.8, 0.7, fill=WHITE)
        face.ellipse(30 + side * 9.5, 37, 2.1, 1.5, fill=(236, 120, 120, 150))
    head.paste(face)
    c.paste(head)
    if lit:
        c.paste(glow(c, 30, 46.5, 14, (255, 70, 40), 230))
        rays = c.layer()
        for i in range(8):
            a = math.radians(i * 45 + 22.5)
            if math.sin(a) < -0.6:
                continue  # (not up into the face)
            rays.line([(30 + 8.6 * math.cos(a), 46.5 + 8.6 * math.sin(a)), (30 + 11.4 * math.cos(a), 46.5 + 11.4 * math.sin(a))], (255, 220, 90, 255), 1.3)
        c.paste(rays)
    bulb = c.layer()
    bulb.rect(26.6, 38.2, 33.4, 42.2, fill=GOLD, radius=1)  # the screw base
    for y in (39.4, 40.9):
        bulb.line([(26.8, y), (33.2, y)], GOLD_DK, 0.55, caps=False)
    nose = (255, 46, 36, 255) if lit else (110, 30, 30, 255)
    bulb.poly([(27.0, 42.0), (33.0, 42.0), (35.6, 45.5), (24.4, 45.5)], fill=nose)
    bulb.ellipse(30, 47.2, 6.2, 5.6, fill=nose)
    bulb.outlined(0.9)
    shine = bulb.layer()
    shine.rot_ellipse(27.7, 45.4, 1.3, 2.3, 30, (255, 235, 225, 255) if lit else (170, 110, 110, 255))
    if lit:
        shine.line([(28.8, 44.0), (30, 47.2), (31.2, 44.0)], (255, 230, 120, 255), 0.6, caps=False)
    bulb.paste(shine)
    c.paste(bulb)
    return c.out()


def tree(lit: bool) -> Image.Image:
    """The switch: a Christmas tree - its lights on when the switch is on."""
    c = Canvas(60, 60)
    t = c.layer()
    t.rect(26.5, 46, 33.5, 55.5, fill=(122, 74, 40, 255), radius=1)
    tiers = [((30, 7.5), 18.5, 22), ((30, 15), 23, 35), ((30, 25), 28, 48.5)]
    for (ax, ay), half, by in tiers:
        pts = [(ax, ay)]
        n = 5
        for i in range(n + 1):  # a scalloped hem
            x = ax + half - 2 * half * i / n
            pts.append((x, by + (1.6 if i % 2 else 0)))
        t.poly(pts, fill=GREEN)
        t.poly([(ax, ay), (ax + half, by), (ax + half * 0.25, by)], fill=GREEN_DK)
    t.outlined(1.1, (10, 40, 20, 255))
    c.paste(t)
    g = c.layer()  # garland
    g.line([(19, 21), (25, 23.5), (34, 22.5), (40.5, 20.5)], GOLD, 1.3)
    g.line([(14.5, 33.5), (24, 36), (36, 35), (45.5, 32.5)], GOLD, 1.3)
    c.paste(g)
    bulbs = [(24, 18, RED), (35.5, 16.5, (80, 160, 255, 255)), (21, 28.5, GOLD), (31, 29.5, (255, 110, 200, 255)),
             (40, 28, RED), (17, 41.5, (80, 160, 255, 255)), (27, 43, RED), (36.5, 41, GOLD), (44, 43.5, (255, 110, 200, 255)),
             (29.5, 11.5, WHITE)]
    if lit:
        for x, y, col in bulbs:
            c.paste(glow(c, x, y, 6.5, col, 170))
    b = c.layer()
    for x, y, col in bulbs:
        if lit:
            b.ellipse(x, y, 2.1, fill=col)
            b.ellipse(x - 0.6, y - 0.6, 0.7, fill=WHITE)
        else:
            dim = tuple(int(v * 0.32 + 30) for v in col[:3]) + (255,)
            b.ellipse(x, y, 1.9, fill=dim)
    b.outlined(0.45, (10, 30, 15, 255))
    c.paste(b)
    if lit:
        c.paste(glow(c, 30, 6.5, 12, GOLD, 200))
    s = c.layer()
    s.poly(star_pts(30, 6.8, 6.6, 2.8), fill=GOLD if lit else (150, 128, 70, 255))
    s.outlined(0.8)
    c.paste(s)
    return c.out()


# ---- the fan: a snowflake, frozen while it runs -----------------------------------------

ICE_PALE = (176, 198, 214, 255)
ICE_PALE_DK = (96, 118, 138, 255)
ICICLE = (240, 251, 255, 255)  # (whiter than the flake: clear where they cross it)


FX2, FY2, FR2 = 30, 25.5, 20.5

def icicle(layer, x, y, ln, w):
    """One icicle hanging from (x, y): wide at the top, a long thin point,
    slightly crooked."""
    layer.poly([(x - w / 2, y), (x + w / 2, y), (x + w * 0.22, y + ln * 0.55), (x + w * 0.05, y + ln * 0.9), (x, y + ln),
                (x - w * 0.12, y + ln * 0.6)], fill=ICICLE)

def icy_fan(on: bool) -> Image.Image:
    """The fan: a snowflake. On (the icon): frozen - big icicles hanging off
    it (the longest from the upper-right arm), frost twinkling. Off (its off
    picture): the same flake still and pale, no ice."""
    c = Canvas(60, 60)
    if on:
        snowflake(c, FX2, FY2, FR2, ICE, edge=ICE_DK, width=3.1, rot=-90)
        c.ellipse(FX2, FY2, 4.0, fill=WHITE)
        c.ellipse(FX2, FY2, 4.0, outline=ICE_DK, width=0.9)
        # icicles: big ones hanging from the lower arms and their branches
        ic = c.layer()
        drops = []
        # (lopsided on purpose: the upper-left arm iced too, the lower-right bare)
        for ang, main in ((210, 10.5), (330, 24.0), (90, 17.0), (150, 12.5)):  # (upper right: the longest)
            a = math.radians(ang)
            tx, ty = FX2 + (FR2 - 1.5) * math.cos(a), FY2 + (FR2 - 1.5) * math.sin(a)
            drops.append((tx + (1.2 if ang == 330 else 0), ty, main, 5.4 if ang == 330 else 4.6))
            for f, ln in ((0.5, 0.36), (0.78, 0.24)):  # the branches' tips (snowflake()'s geometry)
                bx, by = FX2 + FR2 * f * math.cos(a), FY2 + FR2 * f * math.sin(a)
                for s in (-1, 1):
                    b = a + s * math.radians(50)
                    ex, ey = bx + FR2 * ln * math.cos(b), by + FR2 * ln * math.sin(b)
                    if ey > by + 0.5:  # (only the branch tips that point down)
                        drops.append((ex, ey - 0.5, main * (0.62 if f == 0.5 else 0.48), 3.4 if f == 0.5 else 2.8))
        for x, y, ln, w in drops:
            icicle(ic, x, y, min(ln, 58.5 - y), w)
        ic.outlined(0.8, ICE_DK)
        for x, y, ln, w in drops:  # a glint down each
            ic.line([(x - w * 0.22, y + 1.0), (x - w * 0.08, y + min(ln, 58.5 - y) * 0.5)], WHITE, 0.6, caps=False)
        c.paste(ic)
        for x, y, r in ((8.5, 8.5, 2.6), (51.5, 7.0, 2.1), (56.0, 42.0, 1.8)):
            sparkle(c, x, y, r)
    else:
        # off: still, the same flake in the same place, frosty and muted
        snowflake(c, FX2, FY2, FR2, ICE_PALE, edge=ICE_PALE_DK, width=3.1, rot=-90)
        c.ellipse(FX2, FY2, 4.0, fill=(222, 228, 234, 255))
        c.ellipse(FX2, FY2, 4.0, outline=ICE_PALE_DK, width=0.9)
    return c.out()


# ---- covers: a window with a shade -------------------------------------------------------

WIN_FRAME = (128, 76, 40, 255)       # the wood frame, bars and sill
WIN_FRAME_DK = (86, 48, 22, 255)
WIN_FRAME_LT = (156, 98, 56, 255)
BLIND = (52, 140, 76, 255)
BLIND_DK = (40, 116, 62, 255)
NIGHT_TOP, NIGHT_BOT = (22, 44, 92), (64, 104, 168)

WIN_X0, WIN_Y0, WIN_X1, WIN_Y1 = 12.5, 16, 47.5, 49   # the glass

def glass_mask() -> Image.Image:
    m = Canvas(60, 60); m.rect(WIN_X0, WIN_Y0, WIN_X1, WIN_Y1, fill=(255, 255, 255, 255)); return m.alpha()

def window_outside() -> Canvas:
    """Night sky, falling snow, a snowy hill and a snowman."""
    o = Canvas(60, 60)
    S = o.ss
    sky = Image.new("RGBA", o.im.size)
    d = ImageDraw.Draw(sky)
    for y in range(o.im.size[1]):
        k = min(1, max(0, (y / S - WIN_Y0) / (WIN_Y1 - WIN_Y0)))
        d.line([(0, y), (o.im.size[0], y)], fill=tuple(int(a + (b - a) * k) for a, b in zip(NIGHT_TOP, NIGHT_BOT)) + (255,))
    o.im.alpha_composite(sky)
    # a crescent moon and a few stars, upper left
    moon = o.layer()
    moon.ellipse(23.2, 25.6, 3.2, fill=(255, 244, 200, 255))
    cut = Canvas(60, 60); cut.ellipse(24.8, 24.6, 2.9, fill=(255, 255, 255, 255))
    moon.clip(ImageChops.invert(cut.alpha()))
    o.paste(moon)
    for x, y, r in ((19.4, 23.6, 0.5), (27.0, 29.9, 0.45), (20.4, 30.2, 0.4)):
        o.ellipse(x, y, r, fill=(255, 250, 220, 255))
    # the snowy ground: a soft hill
    hill = [(WIN_X0 - 1, 43)] + [(x, 41.2 + 1.6 * math.sin((x - 10) / 6.5)) for x in [WIN_X0 - 1 + i * 0.5 for i in range(80)]] + [(WIN_X1 + 1, 50), (WIN_X0 - 1, 50)]
    o.poly(hill, fill=SNOW)
    # the snowman: three balls, coal eyes, carrot nose, a red scarf, a top hat
    sx = 37.5
    o.ellipse(sx, 42.5, 5.4, 4.9, fill=WHITE, outline=(170, 190, 210, 255), width=0.5)
    o.ellipse(sx, 35.6, 3.9, 3.6, fill=WHITE, outline=(170, 190, 210, 255), width=0.5)
    o.ellipse(sx, 30.0, 3.0, fill=WHITE, outline=(170, 190, 210, 255), width=0.5)
    o.rect(sx - 3.6, 32.3, sx + 3.6, 33.6, fill=RED, radius=0.6)          # scarf
    o.rect(sx + 1.2, 33.0, sx + 2.6, 36.2, fill=RED, radius=0.5)          # its end
    o.poly([(sx + 0.3, 30.2), (sx + 4.2, 30.9), (sx + 0.3, 31.3)], fill=(255, 140, 30, 255))  # carrot
    for ex in (-1.1, 1.0):
        o.ellipse(sx + ex, 29.1, 0.55, fill=INK)
    for by in (35.0, 37.0):
        o.ellipse(sx, by, 0.5, fill=INK)
    o.rect(sx - 3.2, 26.6, sx + 3.2, 27.6, fill=INK, radius=0.3)          # hat brim
    o.rect(sx - 2.1, 22.8, sx + 2.1, 27.0, fill=INK, radius=0.4)          # hat
    o.rect(sx - 2.1, 25.6, sx + 2.1, 26.4, fill=RED)                      # its band
    # stick arms
    o.line([(sx - 3.6, 35.0), (sx - 7.4, 32.4)], BROWN, 0.6, caps=False)
    o.line([(sx + 3.6, 35.0), (sx + 7.0, 32.0)], BROWN, 0.6, caps=False)
    # falling snow
    rnd = random.Random(11)
    for _ in range(30):
        x, y = rnd.uniform(WIN_X0, WIN_X1), rnd.uniform(WIN_Y0, 41)
        if (x - 23.2) ** 2 + (y - 25.6) ** 2 < 22 or y < 22.5:
            continue
        o.ellipse(x, y, rnd.uniform(0.45, 0.8), fill=(255, 255, 255, 235))
    o.clip(glass_mask())
    return o

def window_garland(c: Canvas, x0, x1, y):
    g = c.layer()
    rnd = random.Random(5)
    n = 30
    for i in range(n + 1):  # fir: overlapping needles clumps, sagging a little in two swags
        x = x0 + (x1 - x0) * i / n
        sag = 1.4 * abs(math.sin(math.pi * 2 * (x - x0) / (x1 - x0)))
        for k in range(3):
            g.ellipse(x + rnd.uniform(-0.8, 0.8), y + sag + rnd.uniform(-1.0, 1.0), rnd.uniform(1.6, 2.2), rnd.uniform(1.1, 1.6),
                      fill=GREEN if k % 2 else GREEN_DK)
    g.outlined(0.6)
    for i, col in enumerate((RED, GOLD, RED, GOLD, RED, GOLD, RED)):  # baubles + berries along it
        x = x0 + 2.5 + (x1 - x0 - 5) * i / 6
        sag = 1.4 * abs(math.sin(math.pi * 2 * (x - x0) / (x1 - x0)))
        g.ellipse(x, y + sag + 1.4, 1.25, fill=col)
        g.ellipse(x - 0.4, y + sag + 1.0, 0.4, fill=(255, 235, 220, 255))
    c.paste(g)

def window_blind(open_: bool) -> Image.Image:
    """Covers: a wood-framed window (four panes) with garland across the
    head rail and a plain green shade with a fur hem. Open (the icon): the
    shade rolled all the way up - a snowy night, the moon, a snowman outside,
    frost in the panes' corners. Closed (its off picture): pulled down over
    the glass to the sill."""
    c = Canvas(60, 60)
    # the window: frame, sill, the outside behind the glass, one mullion
    w = c.layer()
    w.rect(9, 13, 51, 52, fill=WIN_FRAME, radius=1.2)
    w.rect(7, 50.5, 53, 54.5, fill=WIN_FRAME, radius=1.0)            # sill
    w.rect(7, 50.5, 53, 51.4, fill=WIN_FRAME_LT, radius=0.6)
    w.rect(7, 53.4, 53, 54.5, fill=WIN_FRAME_DK, radius=0.6)
    w.outlined(1.0)
    c.paste(w)
    if open_:
        c.paste(window_outside())
    else:
        dark = c.layer(); dark.rect(WIN_X0, WIN_Y0, WIN_X1, WIN_Y1, fill=(30, 50, 80, 255)); c.paste(dark)
    # the window's frame over the glass: a recess line around it, then the
    # cross bars (one vertical, one horizontal) - four panes
    if open_:  # frost in each pane's corners (soft white, fading in)
        fr = c.layer()
        BX0, BX1, BY0, BY1 = 29.25, 30.75, 31.85, 33.35
        panes = ((WIN_X0, WIN_Y0, BX0, BY0), (BX1, WIN_Y0, WIN_X1, BY0), (WIN_X0, BY1, BX0, WIN_Y1), (BX1, BY1, WIN_X1, WIN_Y1))
        for x0, y0, x1, y1 in panes:
            for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
                for r, a in ((4.2, 50), (2.8, 90), (1.6, 150)):
                    fr.ellipse(cx, cy, r, fill=(240, 248, 255, a))
        fr.clip(glass_mask())
        c.paste(fr)
    m = c.layer()
    m.rect(WIN_X0, WIN_Y0, WIN_X1, WIN_Y1, outline=WIN_FRAME_DK, width=0.9)          # (the frame's inner edge)
    m.rect(29.25, WIN_Y0, 30.75, WIN_Y1, fill=WIN_FRAME)                       # vertical bar
    m.rect(WIN_X0, 31.85, WIN_X1, 33.35, fill=WIN_FRAME)                       # horizontal bar
    c.paste(m)
    s = c.layer()
    def hem(y):  # the shade's fur hem (the old one's)
        f = c.layer()
        for x in range(12, 49, 3):
            f.ellipse(x, y, 2.6, 2.3, fill=WHITE)
        f.outlined(0.7)
        return f
    if open_:
        # rolled all the way up: a roll under the head rail, its hem under it
        s.rect(11, 14.5, 49, 18.5, fill=BLIND, radius=2.0)
        s.rect(11, 16.8, 49, 18.5, fill=BLIND_DK, radius=1.0)
        s.outlined(0.8)
        c.paste(s)
        c.paste(hem(19.6))
        pull_y = 21.5
    else:
        # pulled down over the glass, to the sill; the frame shows around it
        s.rect(11.5, 14.5, 48.5, 46.5, fill=BLIND)
        for i in range(14):  # light from the left: a soft highlight, a shadowed right edge
            x = 11.5 + i * (37 / 14)
            k = i / 13
            col = tuple(int(a + (b - a) * k) for a, b in zip((70, 162, 96), (38, 110, 58))) + (255,)
            s.rect(x, 14.5, x + 37 / 14 + 0.05, 46.5, fill=col)
        for y in (24, 34):  # soft fabric folds
            s.line([(12, y), (48, y)], (44, 126, 68, 255), 0.5, caps=False)
        s.outlined(0.9)
        c.paste(s)
        c.paste(hem(46.8))
        pull_y = 48.8
    # the head rail with garland across it
    h = c.layer()
    h.rect(7, 9.5, 53, 15, fill=(200, 205, 212, 255), radius=1.6)
    h.outlined(0.8)
    c.paste(h)
    window_garland(c, 7.5, 52.5, 11.5)
    return c.out()


def garage() -> Image.Image:
    """Entry covers, closed (the off picture): the door with a wreath and a
    string of lights."""
    c = Canvas(60, 60)
    d = c.layer()
    d.rect(5, 9, 55, 55, fill=(130, 138, 150, 255), radius=1.5)
    d.rect(9.5, 13.5, 50.5, 55, fill=(176, 56, 48, 255))
    for i, y in enumerate(range(14, 55, 6)):
        d.rect(9.5, y + 4.6, 50.5, y + 6, fill=(130, 36, 32, 255))
    d.outlined(1.0)
    c.paste(d)
    w = c.layer()
    w.ellipse(30, 31, 9.5, fill=(30, 110, 56, 255))
    w.ellipse(30, 31, 5.2, fill=(0, 0, 0, 0))
    w.im = Image.alpha_composite(w.im, Image.new("RGBA", w.im.size, (0, 0, 0, 0)))
    hole = Canvas(60, 60)
    hole.ellipse(30, 31, 5.0, fill=(255, 255, 255, 255))
    w.clip(ImageChops.invert(hole.alpha()))
    for i in range(14):  # needles
        a = math.radians(i * 360 / 14)
        w.ellipse(30 + 7.4 * math.cos(a), 31 + 7.4 * math.sin(a), 2.3, fill=(46, 139, 71, 255) if i % 2 else (24, 94, 46, 255))
    w.clip(ImageChops.invert(hole.alpha()))
    for i in range(6):
        a = math.radians(i * 60 + 15)
        w.ellipse(30 + 7.3 * math.cos(a), 31 + 7.3 * math.sin(a), 1.25, fill=RED)
    w.outlined(0.8)
    c.paste(w)
    ribbon_bow(c, 30, 39.5, 0.62)
    garage_lights(c)
    return c.out()


CAR = (52, 120, 206, 255)
CAR_DK = (30, 80, 150, 255)
CAR_LT = (110, 168, 236, 255)

def garage_lights(c):
    lights = c.layer()
    pts = [(5 + i * 2.5, 9 + 2.2 * math.sin(math.pi * ((i * 2.5) % 12.5) / 12.5)) for i in range(21)]
    lights.line(pts, (40, 60, 40, 255), 0.7, caps=False)
    cols = [RED, GOLD, (80, 160, 255, 255), (60, 200, 90, 255)]
    for i, (x, y) in enumerate(pts[1:-1:2]):
        lights.ellipse(x, y + 1.6, 1.5, 1.9, fill=cols[i % 4])
    lights.outlined(0.45)
    c.paste(lights)

def garage_open() -> Image.Image:
    """Entry covers, open (the icon): the door rolled up, a blue car inside
    with its headlights on and a bow on the grille."""
    c = Canvas(60, 60)
    S = c.ss
    d = c.layer()
    d.rect(5, 9, 55, 55, fill=(130, 138, 150, 255), radius=1.5)
    # inside: dim walls, a lighter concrete floor
    d.rect(9.5, 13.5, 50.5, 55, fill=(46, 42, 50, 255))
    d.rect(9.5, 46, 50.5, 55, fill=(92, 90, 96, 255))
    d.line([(9.5, 46), (50.5, 46)], (70, 68, 74, 255), 0.6, caps=False)
    # the door, rolled up: a red band under the header
    d.rect(9.5, 13.5, 50.5, 20, fill=(176, 56, 48, 255))
    for y in (15.6, 18.2):
        d.rect(9.5, y, 50.5, y + 1.0, fill=(130, 36, 32, 255))
    d.outlined(1.0)
    c.paste(d)
    # a warm light from the ceiling
    glow = c.layer()
    for r, a in ((16, 26), (11, 34), (6, 40)):
        glow.ellipse(30, 21, r, r * 0.8, fill=(255, 220, 150, a))
    gm = Canvas(60, 60); gm.rect(9.5, 20, 50.5, 55, fill=(255, 255, 255, 255))
    glow.clip(gm.alpha())
    c.paste(glow)
    car = c.layer()
    # wheels (behind the body)
    car.rect(16.5, 46, 21.5, 52, fill=(24, 24, 28, 255), radius=1.2)
    car.rect(38.5, 46, 43.5, 52, fill=(24, 24, 28, 255), radius=1.2)
    # the cabin and the body
    car.poly([(18.5, 37), (21.5, 29.5), (38.5, 29.5), (41.5, 37)], fill=CAR_DK)
    car.rect(14.5, 36, 45.5, 48.5, fill=CAR, radius=3.0)
    car.rect(14.5, 36, 45.5, 38.2, fill=CAR_LT, radius=1.5)
    car.outlined(0.9)
    c.paste(car)
    det = c.layer()
    # windshield: glass with a shine
    det.poly([(20.6, 36.2), (22.9, 31), (37.1, 31), (39.4, 36.2)], fill=(150, 196, 226, 255))
    det.poly([(24.5, 35.8), (27.0, 31.4), (29.2, 31.4), (26.7, 35.8)], fill=(214, 236, 250, 255))
    # headlights on, grille, bumper, plate
    for x in (19.6, 40.4):
        det.ellipse(x, 41.0, 2.5, 2.2, fill=(255, 236, 150, 255), outline=INK, width=0.5)
        det.ellipse(x - 0.6, 40.4, 0.8, fill=(255, 255, 240, 255))
    det.rect(25, 39.4, 35, 43, fill=(40, 44, 56, 255), radius=1.0)
    for x in (27.5, 30, 32.5):
        det.line([(x, 39.8), (x, 42.6)], (90, 96, 110, 255), 0.4, caps=False)
    det.rect(14, 45, 46, 47.3, fill=(196, 202, 210, 255), radius=1.1)
    det.rect(27, 45.4, 33, 46.9, fill=WHITE, radius=0.3)
    c.paste(det)
    # a red bow on the grille
    ribbon_bow(c, 30, 41.0, 0.55)
    garage_lights(c)
    return c.out()


# ---- the lock: a key behind a present ---------------------------------------------------

# a white present with a purple ribbon (the lock's purple; the scenes' gift is white too)
GIFT_BOX, GIFT_BOX_DK, GIFT_BOX_LT = (246, 242, 250, 255), (206, 198, 220, 255), (255, 255, 255, 255)
GIFT_RIB, GIFT_RIB_DK = (146, 112, 171, 255), (104, 76, 132, 255)

def key_at(c, dx):
    """The lock's purple key, moved right by dx (no bow, no holly)."""
    k = c.layer()
    purple, purple_dk = (146, 112, 171, 255), (104, 76, 132, 255)
    k.rect(27 + dx, 6, 33 + dx, 38, fill=purple, radius=1.2)
    k.rect(20.5 + dx, 8, 27.5 + dx, 12, fill=purple)
    k.rect(22.5 + dx, 15, 27.5 + dx, 19, fill=purple)
    k.ellipse(30 + dx, 45, 11, fill=purple)
    k.ellipse(33 + dx, 48, 7, fill=purple_dk)
    hole = Canvas(60, 60)
    hole.ellipse(30 + dx, 45, 4.3, fill=(255, 255, 255, 255))
    k.clip(ImageChops.invert(hole.alpha()))
    k.outlined(1.1)
    c.paste(k)

def _rot_rect(x0, y0, x1, y1, deg, px, py):
    a = math.radians(deg)
    out = []
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        x, y = x - px, y - py
        out.append((px + x * math.cos(a) - y * math.sin(a), py + x * math.sin(a) + y * math.cos(a)))
    return out

GBX0, GBX1, GBY0, GBY1 = 14.0, 41.0, 31.5, 56.0   # the box
GRIB = 27.5                                   # its ribbon's centre line

def gift_key(locked: bool) -> Image.Image:
    """The lock: the purple key behind a white present (a purple ribbon and
    bow). Unlocked (the icon): the box open, its lid with the bow leaning on
    its side - the closed lid, only moved and turned. Locked (its off
    picture): the lid on."""
    c = Canvas(60, 60)
    key_at(c, 12)
    b = c.layer()
    # the box: purple, a shaded right side, a gold ribbon down the front
    b.rect(GBX0, GBY0, GBX1, GBY1, fill=GIFT_BOX, radius=1.2)
    b.rect(GBX1 - 6, GBY0, GBX1, GBY1, fill=GIFT_BOX_DK, radius=1.0)
    b.rect(GRIB - 2.4, GBY0, GRIB + 2.4, GBY1, fill=GIFT_RIB)
    b.line([(GRIB - 1.2, GBY0 + 0.5), (GRIB - 1.2, GBY1 - 0.5)], GIFT_RIB_DK, 0.6, caps=False)
    if not locked:  # open: the top's rim, a thicker dark line
        b.rect(GBX0, GBY0, GBX1, GBY0 + 1.9, fill=INK, radius=0.6)
    b.outlined(1.0)
    c.paste(b)
    # the lid with its bow - drawn once, as it sits on the closed box
    lid = c.layer()
    lid.rect(GBX0 - 1.5, GBY0 - 5.5, GBX1 + 1.5, GBY0 + 0.8, fill=GIFT_BOX_LT, radius=1.4)
    lid.rect(GBX1 - 5, GBY0 - 5.5, GBX1 + 1.5, GBY0 + 0.8, fill=GIFT_BOX, radius=1.2)
    lid.rect(GRIB - 2.4, GBY0 - 5.5, GRIB + 2.4, GBY0 + 0.8, fill=GIFT_RIB)
    lid.outlined(1.0)
    ribbon_bow(lid, GRIB, GBY0 - 6.0, 1.0, color=GIFT_RIB, dark=GIFT_RIB_DK)
    if not locked:
        # off: the same lid and bow, only moved and turned (rigidly) - stood up
        # on its end at the box's left, leaning on it, the bow facing out
        S = lid.ss
        pivot = ((GBX0 - 1.5) * S, (GBY0 + 0.8) * S)   # its inner edge's left end...
        target = ((GBX0 - 0.3) * S, (GBY1) * S)          # ...on the floor, against the box
        turned = lid.im.rotate(80, resample=Image.BICUBIC, center=pivot)
        bottom = turned.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()[3]  # (its lowest point)
        lid.im = lid.im.rotate(80, resample=Image.BICUBIC, center=pivot,
                               translate=(target[0] - pivot[0], target[1] - bottom))
    c.paste(lid)
    return c.out()


def thermometer() -> Image.Image:
    """The thermostat: a candy-cane thermometer with holly."""
    c = Canvas(60, 60)
    t = c.layer()
    t.rect(24.5, 6, 35.5, 44, fill=WHITE, radius=5.5)
    t.ellipse(30, 47, 9, fill=WHITE)
    mask = t.alpha()
    stripes = c.layer()
    for i in range(-4, 12):
        y = i * 6.0
        stripes.poly([(20, y), (40, y - 7), (40, y - 4), (20, y + 3)], fill=RED)
    stripes.clip(mask)
    t.paste(stripes)
    t.ellipse(30, 47, 6.6, fill=RED)
    t.outlined(1.1)
    t.ellipse(27.3, 44.5, 1.6, fill=(255, 200, 200, 255))
    c.paste(t)
    holly(c, 30, 8.5, 0.8, rot=0)
    return c.out()


def turkey(c: Canvas, cx, cy, s):
    """A roast turkey seen from above-front (drawn on c, centre cx, cy)."""
    t = c.layer()
    for side in (-1, 1):  # drumsticks
        t.rot_ellipse(cx + side * 8.5 * s, cy - 4.5 * s, 4.2 * s, 6.5 * s, side * 35, (176, 98, 40, 255))
        t.line([(cx + side * 11 * s, cy - 8.5 * s), (cx + side * 14 * s, cy - 13 * s)], (240, 230, 215, 255), 2.2 * s)
        t.ellipse(cx + side * 14.6 * s, cy - 13.6 * s, 1.5 * s, fill=(240, 230, 215, 255))
        t.ellipse(cx + side * 13.6 * s, cy - 14.4 * s, 1.5 * s, fill=(240, 230, 215, 255))
    t.ellipse(cx, cy + 1 * s, 12.5 * s, 9.5 * s, fill=(190, 108, 42, 255))
    t.ellipse(cx - 1 * s, cy - 1 * s, 9.5 * s, 6.5 * s, fill=(214, 134, 58, 255))
    t.outlined(0.9 * s)
    sh = t.layer()
    sh.rot_ellipse(cx - 4 * s, cy - 3 * s, 3.4 * s, 1.6 * s, -20, (240, 176, 100, 255))
    for side in (-1, 1):  # paper frills on the bones
        sh.ellipse(cx + side * 12.3 * s, cy - 10.2 * s, 1.3 * s, fill=WHITE)
    t.paste(sh)
    c.paste(t)


def plate_icon() -> Image.Image:
    """The dishwasher: a plate with the roast turkey."""
    c = Canvas(60, 60)
    p = c.layer()
    p.ellipse(30, 30, 26.5, fill=WHITE)
    p.ellipse(30, 30, 19.5, fill=(226, 228, 232, 255))
    p.outlined(1.0, (40, 40, 40, 255))
    p.ellipse(30, 30, 19.5, outline=(170, 172, 178, 255), width=0.8)
    for i in range(16):  # a red / green rim pattern
        a = math.radians(i * 22.5)
        p.ellipse(30 + 23 * math.cos(a), 30 + 23 * math.sin(a), 1.2, fill=RED if i % 2 else GREEN)
    c.paste(p)
    turkey(c, 30, 32, 1.0)
    holly(c, 43, 42, 0.55, rot=-30, berries=2)
    return c.out()


def sweater(c: Canvas, s=1.0, ox=0.0, oy=0.0):
    """An ugly Christmas sweater on c (60-unit design scaled by s)."""
    def P(pts):
        return [(ox + x * s, oy + y * s) for x, y in pts]

    w = c.layer()
    body = [(17, 8), (24, 6), (30, 9), (36, 6), (43, 8), (55, 20), (49, 27), (45, 23), (45, 54), (15, 54), (15, 23), (11, 27), (5, 20)]
    w.poly(P(body), fill=(196, 40, 40, 255))
    mask = w.alpha()
    band = w.layer()
    band.rect(ox, oy + 23 * s, ox + 60 * s, oy + 30 * s, fill=WHITE)
    zz = [(x, 26.5 + (2.2 if (x // 3) % 2 else -2.2)) for x in range(0, 61, 3)]
    band.line(P(zz), GREEN, 1.4 * s, caps=False)
    band.rect(ox, oy + 49 * s, ox + 60 * s, oy + 54 * s, fill=(30, 110, 56, 255))
    for x in range(1, 60, 3):
        band.line(P([(x, 49), (x, 54)]), (24, 90, 46, 255), 0.7 * s, caps=False)
    band.poly(P([(0, 20), (11, 27), (5, 20)]), fill=(30, 110, 56, 255))
    band.clip(mask)
    w.paste(band)
    w.poly(P([(30, 32), (24.5, 44), (35.5, 44)]), fill=(46, 139, 71, 255))  # a small tree
    w.rect(ox + 28.8 * s, oy + 44 * s, ox + 31.2 * s, oy + 46.5 * s, fill=(122, 74, 40, 255))
    w.poly(P(star_pts(30, 31.6, 2.4, 1.0)), fill=GOLD)
    for x, y in ((20, 36), (40, 37), (21, 45), (39, 45.5), (24, 13), (36, 13)):
        w.ellipse(ox + x * s, oy + y * s, 1.1 * s, fill=WHITE)
    w.poly(P([(24, 6), (30, 9), (36, 6), (33, 11), (27, 11)]), fill=(30, 110, 56, 255))  # collar
    w.outlined(1.0 * s)
    c.paste(w)


def stocking(c: Canvas, cx, cy, s=1.0):
    st = c.layer()
    leg = [(-4.5, -9), (4.5, -9), (4.5, 4), (9, 6.5), (9.5, 10.5), (6, 12.5), (-1, 11.5), (-4.5, 8)]
    st.poly([(cx + x * s, cy + y * s) for x, y in leg], fill=RED)
    st.ellipse(cx + 6.4 * s, cy + 9.6 * s, 3.3 * s, 2.9 * s, fill=(30, 110, 56, 255))  # toe
    st.rect(cx - 6 * s, cy - 12.5 * s, cx + 6 * s, cy - 7.5 * s, fill=WHITE, radius=2 * s)
    st.outlined(0.8 * s)
    c.paste(st)


def laundry_icon() -> Image.Image:
    """The washer / dryer: an ugly sweater and a stocking."""
    c = Canvas(60, 60)
    sweater(c)
    stocking(c, 44, 44, 0.95)
    return c.out()


def ornament() -> Image.Image:
    """The scene: a teal bauble."""
    c = Canvas(60, 60)
    o = c.layer()
    o.ellipse(30, 36, 19.5, fill=(46, 196, 182, 255))
    mask = o.alpha()
    band = o.layer()
    band.rect(0, 32, 60, 39, fill=WHITE)
    zz = [(x, 35.5 + (1.8 if (x // 4) % 2 else -1.8)) for x in range(0, 61, 4)]
    band.line(zz, RED, 1.3, caps=False)
    band.rot_ellipse(36, 46, 9, 5, -30, (24, 150, 140, 255))
    band.clip(mask)
    o.paste(band)
    o.rect(25, 13, 35, 18.5, fill=GOLD, radius=1)
    o.ellipse(30, 10.8, 3.2, outline=GOLD_DK, width=1.1)
    o.outlined(1.0)
    o.rot_ellipse(22.5, 27.5, 3.0, 5.6, 35, (220, 255, 250, 255))
    c.paste(o)
    sparkle(c, 47, 20, 4.2, WHITE)
    return c.out()


def nice_list() -> Image.Image:
    """The script: Santa's list with the scripts' orange play mark."""
    c = Canvas(60, 60)
    s = c.layer()
    s.rect(14, 8, 46, 50, fill=(246, 232, 200, 255))
    s.rect(11, 5, 49, 11, fill=(228, 206, 160, 255), radius=3)
    s.rect(11, 47, 49, 53, fill=(228, 206, 160, 255), radius=3)
    s.outlined(1.0)
    for i, y in enumerate((17, 23, 29, 35)):
        s.line([(18.5, y - 0.6), (20, y + 0.8), (22.5, y - 2)], (40, 150, 70, 255), 0.9, caps=False)
        s.line([(25, y), (42 - (i % 2) * 6, y)], (120, 100, 80, 255), 0.9)
    c.paste(s)
    p = c.layer()
    p.poly([(31, 36), (31, 50), (43, 43)], fill=(255, 143, 63, 255))
    p.outlined(0.9)
    c.paste(p)
    holly(c, 13, 9, 0.55, rot=200, berries=2)
    return c.out()


def santa_gear() -> Image.Image:
    """Settings (72 x 72): a plain silver gear (low left) wearing a Santa hat,
    tipped to the right - a gear at a glance."""
    n, ss = 72, SS
    S = n * ss
    cx, cy = (36 - 3) * ss, (36 + 7) * ss
    ro, rr, hole, teeth = 26 * ss, 19 * ss, 7 * ss, 8
    pts = []
    step = 2 * math.pi / teeth
    for i in range(teeth):  # each tooth: up its flank, across its top, down; then the root
        a = -math.pi / 2 + i * step
        for ang, r in ((a - step * 0.31, rr), (a - step * 0.21, ro), (a + step * 0.21, ro), (a + step * 0.31, rr)):
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        for k in range(1, 6):
            ang = a + step * 0.31 + (step * 0.38) * k / 6
            pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    shape = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(shape)
    d.polygon(pts, fill=255)
    d.ellipse((cx - hole, cy - hole, cx + hole, cy + hole), fill=0)
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    edge = Image.new("RGBA", (S, S), (70, 74, 82, 255))
    edge.putalpha(shape.filter(ImageFilter.MaxFilter(2 * int(1.4 * ss) + 1)))
    im.alpha_composite(edge)
    silver = Image.new("RGBA", (S, S))
    sd = ImageDraw.Draw(silver)
    top, bot = (246, 247, 250), (176, 182, 194)
    for y in range(S):  # (light to darker, top to bottom)
        sd.line([(0, y), (S, y)], fill=tuple(int(a + (b - a) * y / S) for a, b in zip(top, bot)) + (255,))
    silver.putalpha(shape)
    im.alpha_composite(silver)
    # the hat: a red cone leaning right, its shaded fold, the fur band, the pom-pom
    hat = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hat)
    hx, hy = (36 - 4) * ss, (36 - 10) * ss
    u = ss
    hd.polygon([(hx - 18 * u, hy + 5 * u), (hx + 15 * u, hy + 4 * u), (hx + 19 * u, hy - 11 * u), (hx + 25 * u, hy - 17 * u),
                (hx + 6 * u, hy - 22 * u), (hx - 9 * u, hy - 12 * u)], fill=RED)
    hd.polygon([(hx + 6 * u, hy - 22 * u), (hx + 25 * u, hy - 17 * u), (hx + 19 * u, hy - 11 * u), (hx + 5 * u, hy - 15 * u)], fill=RED_DK)
    hd.rounded_rectangle((hx - 21 * u, hy, hx + 18 * u, hy + 9 * u), radius=4.5 * u, fill=WHITE)
    hd.ellipse((hx + 21 * u, hy - 21 * u, hx + 30 * u, hy - 12 * u), fill=WHITE)
    hat = hat.rotate(-10, center=(hx, hy), resample=Image.BICUBIC)
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 255))
    shadow.putalpha(hat.getchannel("A").filter(ImageFilter.GaussianBlur(2 * ss)).point(lambda v: int(v * 0.35)))
    im.alpha_composite(shadow)
    im.alpha_composite(hat)
    return im.convert("RGBa").resize((n, n), Image.LANCZOS).convert("RGBA")


def with_hat(src: str, x, y, s, rot=0.0) -> Image.Image:
    """A master icon wearing a Santa hat."""
    base = Image.open(MASTERS / "ui" / src).convert("RGBA")
    c = Canvas(base.width, base.height)
    c.im = base.resize((base.width * SS, base.height * SS), Image.LANCZOS)
    c.d = ImageDraw.Draw(c.im)
    santa_hat(c, x, y, s, rot)
    return c.out()


def pool_icon() -> Image.Image:
    """The pool: the ladder in icy water, snow falling."""
    base = Image.open(MASTERS / "ui" / "icon_pool.png").convert("RGBA")
    px = base.load()
    for y in range(base.height):
        for x in range(base.width):
            r, g, b, a = px[x, y]
            if a and b > r + 40:  # the water: icy
                px[x, y] = (min(255, r + 60), min(255, g + 70), min(255, b + 20), a)
    c = Canvas(60, 60)
    c.im = base.resize((60 * SS, 60 * SS), Image.LANCZOS)
    c.d = ImageDraw.Draw(c.im)
    for x, y, r in ((40, 10, 4.5), (51, 22, 3.4), (33, 25, 2.8)):
        snowflake(c, x, y, r, WHITE, edge=ICE_DK, width=0.9)
    santa_hat(c, 12.5, 8.5, 0.5, rot=-12)
    return c.out()


def peppermint(size: int, r: float) -> Image.Image:
    """Switch / slider knobs: a peppermint candy."""
    c = Canvas(size, size)
    cx = cy = size / 2
    p = c.layer()
    p.ellipse(cx, cy, r, fill=WHITE)
    mask = p.alpha()
    sw = p.layer()
    for i in range(6):
        pts = [(cx, cy)]
        a0 = i * 60
        for k in range(13):  # a curved wedge (pinwheel)
            t = k / 12
            a = math.radians(a0 + 26 * t + 40 * t * t)
            pts.append((cx + r * 1.05 * t * math.cos(a) * 1.0, cy + r * 1.05 * t * math.sin(a)))
        for k in range(12, -1, -1):
            t = k / 12
            a = math.radians(a0 + 26 * t + 40 * t * t + 28)
            pts.append((cx + r * 1.05 * t * math.cos(a), cy + r * 1.05 * t * math.sin(a)))
        sw.poly(pts, fill=RED)
    sw.clip(mask)
    p.paste(sw)
    p.ellipse(cx, cy, r, outline=(150, 150, 150, 255), width=max(0.8, r * 0.07))
    hl = p.layer()
    hl.rot_ellipse(cx - r * 0.38, cy - r * 0.42, r * 0.34, r * 0.18, -40, (255, 255, 255, 200))
    p.paste(hl)
    c.paste(p)
    return c.out()


def padlock(open_: bool) -> Image.Image:
    """The lock switch's padlocks, wrapped as presents."""
    name = "lock_padlock_open.png" if open_ else "lock_padlock_closed.png"
    base = Image.open(MASTERS / "ui" / name).convert("RGBA")
    W, H = base.size
    c = Canvas(W, H)
    c.im = base.resize((W * SS, H * SS), Image.LANCZOS)
    c.d = ImageDraw.Draw(c.im)
    body = Image.new("L", (W * SS, H * SS), 0)
    ImageDraw.Draw(body).rectangle([0, 44 * SS, W * SS, H * SS], fill=255)
    body = ImageChops.multiply(body, c.alpha())
    rib = c.layer()
    cx = 44
    rib.rect(cx - 3.2, 40, cx + 3.2, 84, fill=GOLD)
    rib.rect(0, 59, 76, 65.4, fill=GOLD)
    rib.line([(cx - 2.2, 44), (cx - 2.2, 84)], GOLD_DK, 0.7, caps=False)
    rib.line([(0, 60.2), (76, 60.2)], GOLD_DK, 0.7, caps=False)
    rib.clip(body)
    c.paste(rib)
    ribbon_bow(c, cx, 46, 0.9, color=GOLD, dark=GOLD_DK)
    holly(c, 27, 74, 0.6, rot=-15, berries=2)
    return c.out()


def c8_string(lit: bool) -> Image.Image:
    """The top bar's Area Lights button (44 x 34): three old C8 bulbs on a
    wire - green, red, blue - lit while any of the area's lights is on."""
    c = Canvas(44, 34)
    wire = c.layer()
    wire.line([(0.5, 5.5), (8, 7.8), (16, 6.2), (22, 7.2), (28, 6.2), (36, 7.8), (43.5, 5.5)], (40, 90, 50, 255), 1.2, caps=False)
    c.paste(wire)
    bulbs = [(9.5, 7.6, -16, (60, 200, 90)), (22, 7.1, 0, (240, 50, 50)), (34.5, 7.6, 16, (70, 140, 255))]
    if lit:
        for x, y, rot, col in bulbs:
            a = math.radians(rot)
            gx, gy = x - 13 * math.sin(a), y + 13 * math.cos(a)
            c.paste(glow(c, gx, gy, 15, col, 200))
    for x, y, rot, col in bulbs:
        b = c.layer()
        a = math.radians(rot)

        def at(u, v):  # u across, v down the bulb (from the top of its base)
            return (x + u * math.cos(a) - v * math.sin(a), y + u * math.sin(a) + v * math.cos(a))

        b.poly([at(-2.4, 0), at(2.4, 0), at(2.4, 4.6), at(-2.4, 4.6)], fill=(205, 205, 200, 255))  # the screw base
        for v in (1.4, 2.9):
            b.line([at(-2.4, v), at(2.4, v)], (130, 130, 125, 255), 0.55, caps=False)
        L, W = 17.5, 9.4
        right, left = [], []
        for k in range(25):  # the C8's pointed teardrop
            t = k / 24
            hw = W / 2 * (0.55 + 0.45 * math.sin(math.pi / 2 * min(t / 0.35, 1.0))) * (1 - t) ** 0.7
            right.append(at(hw, 4.4 + t * L))
            left.append(at(-hw, 4.4 + t * L))
        body = right + left[::-1]
        if lit:
            fill = col + (255,)
            facet = tuple(min(255, v + 90) for v in col) + (255,)
        else:
            fill = tuple(int(v * 0.32 + 25) for v in col) + (255,)
            facet = tuple(int(v * 0.45 + 35) for v in col) + (255,)
        b.poly(body, fill=fill)
        b.outlined(0.75)
        f = b.layer()  # the glass's ridges
        for u in (-1.9, 0.0, 1.9):
            f.line([at(u * 0.9, 6.5), at(u * 0.55, 4.4 + L * 0.72)], facet, 0.65, caps=False)
        if lit:
            f.rot_ellipse(*at(-1.6, 8.5), 0.9, 2.2, rot, (255, 255, 255, 230))
        mask = Canvas(44, 34)
        mask.poly(body, fill=(255, 255, 255, 255))
        f.clip(mask.alpha())
        b.paste(f)
        c.paste(b)
    return c.out()


def gingerbread_house(size: tuple[int, int] = (44, 34)) -> Image.Image:
    """The Map: a gingerbread house (drawn in 44 x 34 units) - the top bar's
    button, and bigger on the Map tile."""
    c = Canvas(44, 34, ss=max(SS, round(SS * size[0] / 44)))
    h = c.layer()
    h.rect(9, 15, 35, 32.5, fill=(178, 106, 52, 255))  # the walls
    h.poly([(5.5, 17.5), (22, 3.0), (38.5, 17.5)], fill=(150, 84, 38, 255))  # the roof
    h.rect(29, 4.5, 33, 11, fill=(150, 84, 38, 255))  # the chimney
    h.outlined(0.9)
    d = h.layer()
    for i in range(9):  # icing along the roof: scallops
        t = i / 8
        for side in (-1, 1):
            x = 22 + side * 16.5 * t
            y = 3.0 + 14.5 * t
            d.ellipse(x, y, 1.6, fill=WHITE)
    d.rect(28.5, 3.6, 33.5, 5.4, fill=WHITE, radius=0.8)  # snow on the chimney
    d.rect(18.8, 22.5, 25.2, 32.5, fill=(110, 60, 28, 255), radius=3)  # the door
    d.ellipse(23.6, 27.8, 0.7, fill=GOLD)
    for wx in (11.5, 27.5):  # warm windows with icing frames
        d.rect(wx, 19, wx + 5, 24, fill=(255, 211, 107, 255))
        d.rect(wx, 19, wx + 5, 24, outline=WHITE, width=0.8)
        d.line([(wx + 2.5, 19), (wx + 2.5, 24)], WHITE, 0.6, caps=False)
    for x, col in ((12, RED), (17, GREEN), (27, RED), (32, GREEN)):  # gumdrops on the wall's top
        d.ellipse(x, 16.4, 1.5, 1.2, fill=col)
    for k in range(4):  # a candy-cane stripe up the corners
        d.line([(9.4, 18 + k * 4), (10.8, 20 + k * 4)], RED, 0.8, caps=False)
        d.line([(34.6, 18 + k * 4), (33.2, 20 + k * 4)], RED, 0.8, caps=False)
    h.paste(d)
    c.paste(h)
    return c.out(size=size)


def gift(size: int) -> Image.Image:
    """Scene / script tiles' play button: a present to open (white box, red
    ribbon - it reads on the teal, the orange and the gray)."""
    s = size / 60
    c = Canvas(size, size)
    g = c.layer()
    g.rect(10 * s, 27 * s, 50 * s, 56 * s, fill=WHITE, radius=1.5 * s)  # the box
    g.rect(6.5 * s, 19 * s, 53.5 * s, 28.5 * s, fill=(236, 236, 232, 255), radius=1.5 * s)  # the lid
    g.rect(26.5 * s, 19 * s, 33.5 * s, 56 * s, fill=RED)
    g.rect(10 * s, 38 * s, 50 * s, 44 * s, fill=RED)
    g.outlined(1.2 * s)
    c.paste(g)
    ribbon_bow(c, 30 * s, 17 * s, 1.6 * s)
    return c.out()


# ---- the idle clock: a character clock - an elf (clock.json says where the hands turn) ----

SKIN = (248, 210, 176, 255)
SKIN_DK = (222, 170, 132, 255)
CREAM = (240, 230, 208, 255)
DIAL_INK = (34, 30, 30, 255)
FONT_CACHE = Path.home() / ".cache" / "room-tiles-fonts"


def font_file(family: str, weight: int) -> Path:
    """A Google font as TTF (cached) - the dial's numerals."""
    import re as _re
    import urllib.request

    path = FONT_CACHE / f"{family.replace(' ', '_')}-{weight}.ttf"
    if not path.exists():
        FONT_CACHE.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(
            f"https://fonts.googleapis.com/css2?family={family.replace(' ', '+')}:wght@{weight}",
            headers={"User-Agent": "Mozilla/4.0"},  # (an old agent: TTF links)
        )
        css = urllib.request.urlopen(req, timeout=30).read().decode()
        url = _re.search(r"https://[^)]+\.ttf", css).group(0)
        path.write_bytes(urllib.request.urlopen(url, timeout=30).read())
    return path


def elf_clock_face(scale: float = 1.0) -> Image.Image:
    """The idle clock's face, a character clock in a giant wreath: a snowy
    dial (a few ice-blue snowflakes) ringed by a fir wreath whose decorations
    mark the hours - a gold star at 12, red baubles at 3 and 9, a bow at 6,
    little lights at the rest - and an elf standing in it (one boot kicked
    forward). His arms are the hands (clock_hour / clock_minute), turning at
    his chest: the dial's center (210, 210). The date goes inside the wreath
    by the 3 (clock.json)."""
    W, cx, cy = 420, 210, 210
    c = Canvas(W, W, 4)
    rnd = random.Random(11)
    c.ellipse(cx, cy, 196, fill=(232, 241, 248, 255))  # the snowy dial
    for _ in range(14):  # snowflakes inside the wreath: a clear ice blue (seen on the panels' screens)
        a, r = rnd.uniform(0, 2 * math.pi), rnd.uniform(40, 150)
        fr, rot = rnd.uniform(5, 9), rnd.uniform(0, 60)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        if abs(x - 322) < 62 and abs(y - 210) < 24:
            continue  # (clear of the date: clock.json "date")
        snowflake(c, x, y, fr, (96, 150, 212, 255), width=fr * 0.2, rot=rot)
    # the wreath: two rings of needles (dark under light), jittered
    ring = c.layer()
    for layer, (count, col, r_mid) in enumerate(((150, GREEN_DK, 190), (170, GREEN, 186))):
        for i in range(count):
            a = 2 * math.pi * i / count + rnd.uniform(-0.03, 0.03)
            r = r_mid + rnd.uniform(-13, 13)
            x, y = cx + r * math.cos(a), cy + r * math.sin(a)
            ring.rot_ellipse(x, y, 13, 4.2, math.degrees(a) + 90 + rnd.uniform(-40, 40), col)
    ring.outlined(1.6)
    c.paste(ring)
    # berry clusters and pine cones between the hours
    for k in range(12):
        a = math.radians(k * 30 + 15)
        x, y = cx + 188 * math.sin(a), cy - 188 * math.cos(a)
        if k % 2 == 0:
            for j in range(3):
                c.ellipse(x + 5 * math.cos(j * 2.1), y + 5 * math.sin(j * 2.1), 4.2, fill=RED, outline=INK, width=1)
        else:
            c.rot_ellipse(x, y, 5, 8.5, math.degrees(a), BROWN)
    # the hours: decorations on the wreath
    lights = (RED, ICE, GOLD, GREEN, (230, 90, 200, 255))
    for h in range(12):
        a = math.radians(h * 30)
        x, y = cx + 186 * math.sin(a), cy - 186 * math.cos(a)
        if h == 0:  # 12: a gold star
            star = c.layer()
            star.poly(star_pts(x, y, 26, 10.5), fill=GOLD)
            star.outlined(1.6)
            c.paste(star)
            c.paste(glow(c, x, y, 34, GOLD, 90))
        elif h in (3, 9):  # baubles
            c.ellipse(x, y, 15, fill=RED, outline=INK, width=1.6)
            c.ellipse(x - 5, y - 5, 4, fill=(255, 190, 190, 255))
            c.rect(x - 5, y - 21, x + 5, y - 14, fill=GOLD, outline=INK, width=1)
        elif h == 6:  # a red bow
            ribbon_bow(c, x, y - 2, 2.6)
        else:  # a little light, pointing in
            col = lights[h % len(lights)]
            ix, iy = cx + 164 * math.sin(a), cy - 164 * math.cos(a)
            c.paste(glow(c, ix, iy, 30, col, 120))
            bulb = c.layer()
            bulb.rot_ellipse(ix, iy, 9, 15, h * 30, col)
            sx, sy = cx + 178 * math.sin(a), cy - 178 * math.cos(a)
            bulb.rot_ellipse(sx, sy, 6, 6, h * 30, (70, 70, 70, 255))  # (its socket)
            bulb.outlined(1.4)
            c.paste(bulb)
            c.rot_ellipse(ix - 3 * math.cos(a), iy - 3 * math.sin(a) - 2, 2.2, 4, h * 30, (255, 255, 255, 170))
    S = round(W * scale)  # (drawn in 420-units; out at the size asked: 420 / the large 560)
    img = c.out(size=(S, S))
    # the elf on top
    e = Canvas(W, W, 4)
    elf = e.layer()
    # legs: striped stockings; the left kicked out forward, the right planted
    def leg(x0, y0, x1, y1):
        elf.line([(x0, y0), (x1, y1)], WHITE, 15)
        stripes = elf.layer()
        n = 6
        for k in range(n):
            t0, t1 = k / n, (k + 0.5) / n
            stripes.line([(x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0), (x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1)], RED, 15, caps=False)
        elf.paste(stripes)
    leg(cx - 18, 262, cx - 48, 290)
    leg(cx + 18, 262, cx + 22, 300)
    # boots: curled toes with bells (inside the numerals' ring)
    elf.rot_ellipse(cx - 64, 298, 25, 12, -28, GREEN_DK)
    # (its tip: the ellipse's left end, turned -28 degrees - down and left)
    tx, ty = cx - 64 - 25 * math.cos(math.radians(28)), 298 + 25 * math.sin(math.radians(28))
    elf.ellipse(tx - 2, ty - 5, 6, fill=GREEN_DK)  # the toe, curled up
    elf.ellipse(tx - 4, ty - 12, 5, fill=GOLD)
    elf.rot_ellipse(cx + 38, 310, 25, 11, 6, GREEN_DK)
    elf.ellipse(cx + 62, 302, 6, fill=GREEN_DK)
    elf.ellipse(cx + 67, 296, 5, fill=GOLD)
    # the tunic: shoulders to a zigzag hem, a belt with a gold buckle
    hem = []
    for k in range(9):
        x = cx - 52 + k * 13
        hem.append((x, 270 if k % 2 == 0 else 256))
    elf.poly([(cx - 34, 178), (cx + 34, 178), (cx + 52, 256)] + hem[::-1] + [(cx - 52, 256)], fill=GREEN)
    elf.rect(cx - 46, 234, cx + 46, 246, fill=DIAL_INK)
    elf.rect(cx - 10, 231, cx + 10, 249, fill=GOLD, radius=2)
    elf.rect(cx - 5, 236, cx + 5, 244, fill=DIAL_INK)
    # the head: pointy ears, face, rosy cheeks, a big smile; the hat flops right
    hx, hy = cx, 132
    for side in (-1, 1):
        elf.poly([(hx + side * 30, hy - 2), (hx + side * 64, hy - 20), (hx + side * 34, hy + 16)], fill=SKIN)
        elf.poly([(hx + side * 34, hy), (hx + side * 54, hy - 12), (hx + side * 36, hy + 9)], fill=SKIN_DK)
    elf.ellipse(hx, hy, 36, 35, fill=SKIN)
    elf.outlined(2.6)
    e.paste(elf)
    face = e.layer()
    for side in (-1, 1):
        face.ellipse(hx + side * 13, hy - 2, 5, 7, fill=INK)
        face.ellipse(hx + side * 12, hy - 4, 1.8, fill=WHITE)
        face.ellipse(hx + side * 22, hy + 12, 8, 5, fill=(240, 130, 130, 150))
    face.ellipse(hx, hy + 8, 5.5, 5, fill=(232, 120, 104, 255))
    face.poly([(hx - 15, hy + 17), (hx + 15, hy + 17), (hx + 9, hy + 27), (hx, hy + 30), (hx - 9, hy + 27)], fill=(150, 40, 40, 255))
    face.line([(hx - 16, hy + 17), (hx + 16, hy + 17)], INK, 2.2)
    e.paste(face)
    hat = e.layer()
    hat.poly([(hx - 38, hy - 16), (hx - 18, hy - 50), (hx + 14, hy - 66), (hx + 54, hy - 70),
              (hx + 70, hy - 52), (hx + 38, hy - 44), (hx + 38, hy - 16)], fill=RED)
    hat.poly([(hx + 14, hy - 66), (hx + 54, hy - 70), (hx + 70, hy - 52), (hx + 30, hy - 40)], fill=RED_DK)
    for px in range(-38, 42, 9):
        hat.ellipse(hx + px, hy - 18, 8.5, fill=WHITE)
    hat.ellipse(hx + 74, hy - 48, 10, fill=WHITE)
    hat.outlined(2.2)
    e.paste(hat)
    collar = e.layer()
    pts = []
    for k in range(9):
        x = hx - 36 + k * 9
        pts.append((x, hy + 40 if k % 2 == 0 else hy + 52))
    collar.poly([(hx - 38, hy + 36), (hx + 38, hy + 36)] + pts[::-1], fill=GREEN_DK)
    collar.outlined(1.6)
    e.paste(collar)
    img.alpha_composite(e.out(size=(S, S)))
    return img


def elf_arm(w: int, h: int, pivot_y: int, scale: float = 1.0) -> Image.Image:
    """A clock hand: the elf's arm pointing up (12 o'clock) - a green sleeve,
    a white fur cuff, a white cartoon glove: a fist with the INDEX finger up
    off its thumb side (left), the thumb along it, the curled fingers' bumps
    to the right, three stitches on its back. Its pivot: (w / 2, pivot_y)."""
    c = Canvas(w, h, 8)
    u, x = w, w / 2
    arm = c.layer()
    arm.line([(x, pivot_y), (x, 0.92 * u)], GREEN, 0.34 * u)  # the sleeve
    arm.rect(x - 0.36 * u, 0.80 * u, x + 0.36 * u, 1.00 * u, fill=WHITE, radius=0.09 * u)  # the cuff
    glove = arm.layer()
    glove.rect(x - 0.30 * u, 0.36 * u, x + 0.32 * u, 0.82 * u, fill=WHITE, radius=0.17 * u)  # the fist
    glove.rect(x - 0.30 * u, 0.02 * u, x - 0.06 * u, 0.50 * u, fill=WHITE, radius=0.12 * u)  # the index finger
    for k, bx in enumerate((-0.02, 0.12, 0.25)):  # the curled fingers' tops
        glove.ellipse(x + bx * u, 0.38 * u + k * 0.02 * u, 0.085 * u, fill=WHITE)
    glove.rot_ellipse(x - 0.34 * u, 0.56 * u, 0.09 * u, 0.20 * u, 14, WHITE)  # the thumb
    glove.outlined(1.4)
    arm.paste(glove)
    arm.outlined(1.2)
    c.paste(arm)
    seam = (120, 110, 105, 255)
    c.line([(x - 0.06 * u, 0.36 * u), (x - 0.06 * u, 0.50 * u)], seam, 0.03 * u)  # the finger's edge
    for bx in (-0.02, 0.10, 0.22):  # stitches
        c.line([(x + bx * u, 0.54 * u), (x + bx * u, 0.72 * u)], seam, 0.03 * u)
    c.line([(x - 0.36 * u, 0.80 * u), (x + 0.36 * u, 0.80 * u)], seam, 0.03 * u)
    return c.out(size=(round(w * scale), round(h * scale)))


def cane_second(scale: float = 1.0) -> Image.Image:
    """The second hand: a candy cane hung on the clock's center peg - its
    crook loops around the center (the pivot: the loop's middle, (24, 150) -
    clock.json), its straight stem points at the seconds out to the wreath.
    The red cap sits over the loop (drawn after it). Exaggerated, bold: easy
    to see across the room."""
    W, H, x = 48, 170, 9  # (x: the stem; the loop's middle 15 to its right)
    px, py, r = x + 15, 150, 15
    path = [(x, 10)] + [(x, y) for y in range(14, py, 4)]
    path += [(px - r * math.cos(t), py + r * math.sin(t)) for t in [k * math.pi / 18 for k in range(19)]]
    path += [(px + r, py - 8)]  # (the crook's end, turned back up)
    c = Canvas(W, H, 8)
    cane = c.layer()
    cane.line(path, WHITE, 9)
    mask = cane.alpha()
    stripes = c.layer()
    for y in range(-W, H + W, 14):
        stripes.poly([(0, y), (W, y - 18), (W, y - 10), (0, y + 8)], fill=RED)
    stripes.clip(mask)
    cane.paste(stripes)
    cane.outlined(1.2)
    c.paste(cane)
    return c.out(size=(round(W * scale), round(H * scale)))


def elf_cap(scale: float = 1.0) -> Image.Image:
    """The cap over the arms' pivot: a red dome with a dark ring."""
    c = Canvas(26, 26, 8)
    c.ellipse(13, 13, 11, fill=DIAL_INK)
    c.ellipse(13, 13, 8, fill=RED)
    c.ellipse(11, 11, 2.5, fill=(255, 190, 190, 255))
    return c.out(size=(round(26 * scale),) * 2)


# ---- appliance pictures (196 x 196, on/off alpha) -----------------------------------------


def plate_big() -> Image.Image:
    c = Canvas(196, 196, 4)
    p = c.layer()
    p.ellipse(98, 98, 86, fill=WHITE)
    p.ellipse(98, 98, 64, fill=(226, 228, 232, 255))
    p.outlined(3.0, (20, 20, 20, 255))
    p.ellipse(98, 98, 64, outline=(160, 162, 168, 255), width=2.4)
    for i in range(28):
        a = math.radians(i * 360 / 28)
        p.ellipse(98 + 75 * math.cos(a), 98 + 75 * math.sin(a), 3.6, fill=RED if i % 2 else GREEN)
    c.paste(p)
    turkey(c, 98, 104, 3.4)
    holly(c, 142, 140, 1.7, rot=-30, berries=3)
    holly(c, 56, 62, 1.3, rot=150, berries=2)
    return c.out(snap=True)


def shirt_big() -> Image.Image:
    c = Canvas(196, 196, 4)
    sweater(c, 3.0, 8, 8)
    stocking(c, 140, 140, 3.0)
    return c.out(snap=True)


# ---- animations: 8 x 4 frames of 196 px, played row by row -------------------------------

def wreath_icon(r_mid: float = 20.5, leaf: float = 4.0, bow: float = 1.1) -> Image.Image:
    """The top bars' Room Tiles icon hung in a thick fir wreath IN FRONT of it
    (berries, a few lights, a big red bow below): the wreath covers the
    squares' outer edges, the logo still easy to make out (build_panel.py
    check_brand: at most 40% of each square drawn over)."""
    W = 48
    c = Canvas(W, W)
    cx = cy = W / 2
    rnd = random.Random(7)
    ring = c.layer()
    # needles: two rings of leaves (dark under light), jittered
    for layer, (count, col, rr) in enumerate(((64, GREEN_DK, r_mid + 0.6), (72, GREEN, r_mid - 0.4))):
        for i in range(count):
            a = 2 * math.pi * (i + 0.5 * layer) / count + rnd.uniform(-0.05, 0.05)
            r = rr + rnd.uniform(-1.8, 1.8)
            x, y = cx + r * math.cos(a), cy + r * math.sin(a)
            ring.rot_ellipse(x, y, leaf, leaf * 0.38, math.degrees(a) + 90 + rnd.uniform(-40, 40), col)
    ring.outlined(0.7)
    c.paste(ring)
    # lights on the ring (gold, blue, red alternating) and holly berries
    for k, deg in enumerate((-150, -105, -60, -15, 30, 150)):
        a = math.radians(deg)
        x, y = cx + r_mid * math.cos(a), cy + r_mid * math.sin(a)
        col = (GOLD, ICE, RED)[k % 3]
        c.paste(glow(c, x, y, 4.2, col, 150))
        c.ellipse(x, y, 1.6, fill=col, outline=INK, width=0.45)
        c.ellipse(x - 0.5, y - 0.5, 0.5, fill=WHITE)
    for deg in (-128, -38, 170, 10):
        a = math.radians(deg)
        x, y = cx + (r_mid - 1.4) * math.cos(a), cy + (r_mid - 1.4) * math.sin(a)
        c.ellipse(x, y, 1.35, fill=RED, outline=INK, width=0.4)
    ribbon_bow(c, cx, cy + r_mid, bow)
    # the icon as it is (its own pixels: never resampled), the wreath over it
    icon = Image.open(BRAND_ICON).convert("RGBA")
    out = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    out.alpha_composite(icon, ((W - icon.width) // 2, (W - icon.width) // 2))
    out.alpha_composite(c.out())
    return out


FR = 196
COLS, ROWS = 8, 4
NF = COLS * ROWS


def sheet(frames: list[Image.Image]) -> Image.Image:
    out = Image.new("RGBA", (FR * COLS, FR * ROWS), (0, 0, 0, 0))
    for i, f in enumerate(frames):
        out.paste(f, ((i % COLS) * FR, (i // COLS) * FR))
    return out


def snow_wash() -> Image.Image:
    """Washing: one big snowflake tossed round the drum - riding the circle,
    lifted and dropped back (its distance from the middle rises and falls
    twice a turn) and spinning. Loops seamlessly: one turn, and 120 degrees
    of spin (a snowflake repeats every 60)."""
    frames = []
    for f in range(NF):
        c = Canvas(FR, FR, 4)
        t = 2 * math.pi * f / NF
        a = math.radians(200) + t
        R = 34 + 9 * math.sin(2 * t)  # (the gentle toss)
        x, y = 98 + R * math.cos(a), 98 + R * math.sin(a)
        snowflake(c, x, y, 44, (190, 232, 255, 255), edge=(30, 90, 150, 255), width=7.0, rot=f * 120 / NF)
        c.ellipse(x, y, 7.5, fill=WHITE)
        c.ellipse(x, y, 7.5, outline=(30, 90, 150, 255), width=2.0)
        frames.append(c.out(snap=True))
    return sheet(frames)


def star_dry() -> Image.Image:
    """Drying: a warm star turning and twinkling over gold tinsel waves."""
    frames = []
    for f in range(NF):
        c = Canvas(FR, FR, 4)
        t = f / NF
        rays = c.layer()
        for i in range(10):
            a = math.radians(i * 36 + t * 72)
            L = 46 + (5 if i % 2 else 0) * math.sin(2 * math.pi * (t * 2 + i / 10))
            rays.line([(98 + 30 * math.cos(a), 66 + 30 * math.sin(a)), (98 + L * math.cos(a), 66 + L * math.sin(a))], (255, 214, 90, 255), 3.0)
        c.paste(rays)
        s = c.layer()
        s.poly(star_pts(98, 66, 30, 13, rot=-90 + 8 * math.sin(2 * math.pi * t)), fill=GOLD)
        s.outlined(2.0, (150, 90, 10, 255))
        s.ellipse(91, 58, 3.6, fill=(255, 245, 200, 255))
        c.paste(s)
        w = c.layer()
        for k, (y, col) in enumerate(((128, RED), (146, GOLD), (164, GREEN))):
            pts = [(x, y + 5 * math.sin(2 * math.pi * (x / 46 + t * 2 + k * 0.33))) for x in range(34, 163, 3)]
            w.line(pts, col, 4.0)
        w.outlined(1.2, (60, 30, 10, 255))
        c.paste(w)
        frames.append(c.out(snap=True))
    return sheet(frames)


def candy_done() -> Image.Image:
    """Done: the check mark as a candy cane, with the masters' sparkles - in
    a green outline (stands out on the red sweater)."""
    src = Image.open(MASTERS / "appliances" / "check_done.png").convert("RGBA")
    frames = []
    for f in range(NF):
        fr = src.crop(((f % COLS) * FR, (f // COLS) * FR, (f % COLS + 1) * FR, (f // COLS + 1) * FR))
        px = fr.load()
        out = fr.copy()
        po = out.load()
        check = Image.new("L", (FR, FR), 0)
        cp = check.load()
        for y in range(FR):
            for x in range(FR):
                r, g, b, a = px[x, y]
                if a and g > 120 and g > r + 60:  # the green check: stripes
                    band = int((x + y + f * 2) / 11) % 2
                    po[x, y] = (226, 40, 44, 255) if band else (252, 250, 246, 255)
                    cp[x, y] = 255
        # the outline: the check grown past its dark edge, soft-edged, under it
        ring = check.filter(ImageFilter.GaussianBlur(5)).point(lambda v: 255 if v > 14 else 0)  # (on/off alpha)
        green = Image.new("RGBA", (FR, FR), (22, 128, 52, 255))
        green.putalpha(ring)
        frames.append(Image.alpha_composite(green, out))
    return sheet(frames)


def snow_glass() -> Image.Image:
    """Waiting (still wet): the hourglass in red, snowflakes for the drops."""
    src = Image.open(MASTERS / "appliances" / "wet_hourglass.png").convert("RGBA")
    frames = []
    for f in range(NF):
        fr = src.crop(((f % COLS) * FR, (f // COLS) * FR, (f % COLS + 1) * FR, (f // COLS + 1) * FR))
        px = fr.load()
        blue = Image.new("L", (FR, FR), 0)
        bp = blue.load()
        out = fr.copy()
        po = out.load()
        for y in range(FR):
            for x in range(FR):
                r, g, b, a = px[x, y]
                if not a:
                    continue
                if b > r + 40 and b > 120:  # drops and puddles
                    bp[x, y] = 255
                    po[x, y] = (0, 0, 0, 0)
                elif r > 150 and g > 100 and b < 80:  # the gold frame: candy red
                    po[x, y] = (210, 36, 40, 255) if r > 200 else (150, 20, 24, 255)
        # each blob of drop pixels -> a snowflake at its centre
        c = Canvas(FR, FR, 4)
        c.im = out.resize((FR * 4, FR * 4), Image.NEAREST)
        c.d = ImageDraw.Draw(c.im)
        seen = set()
        bl = blue.load()
        for y in range(FR):
            for x in range(FR):
                if bl[x, y] and (x, y) not in seen:
                    stack, pts = [(x, y)], []
                    seen.add((x, y))
                    while stack:
                        qx, qy = stack.pop()
                        pts.append((qx, qy))
                        for nx, ny in ((qx + 1, qy), (qx - 1, qy), (qx, qy + 1), (qx, qy - 1), (qx + 2, qy), (qx - 2, qy)):
                            if 0 <= nx < FR and 0 <= ny < FR and bl[nx, ny] and (nx, ny) not in seen:
                                seen.add((nx, ny))
                                stack.append((nx, ny))
                    if len(pts) < 6:
                        continue
                    mx = sum(p[0] for p in pts) / len(pts)
                    my = sum(p[1] for p in pts) / len(pts)
                    w = max(p[0] for p in pts) - min(p[0] for p in pts)
                    h = max(p[1] for p in pts) - min(p[1] for p in pts)
                    r = max(10.0, min(17.0, max(w, h) * 1.1))  # (big enough to read as snowflakes)
                    if w > 2.2 * h:  # a puddle: a little snow drift
                        c.ellipse(mx, my, w * 0.5, max(3.0, h * 0.8), fill=SNOW)
                        c.ellipse(mx, my, w * 0.5, max(3.0, h * 0.8), outline=(90, 140, 190, 255), width=1.2)
                    else:
                        snowflake(c, mx, my, r, (200, 236, 255, 255), edge=(30, 90, 150, 255), width=2.6, rot=f * 9)
        frames.append(c.out(snap=True))
    return sheet(frames)


# ---- main ---------------------------------------------------------------------------------


def main() -> None:
    ui = OUT / "ui"
    appl = OUT / "appliances"
    ui.mkdir(parents=True, exist_ok=True)
    appl.mkdir(parents=True, exist_ok=True)
    art = {
        ui / "icon_light.png": lambda: reindeer(True),
        ui / "icon_light_off.png": lambda: reindeer(False),
        ui / "icon_switch.png": lambda: tree(True),
        ui / "icon_switch_off.png": lambda: tree(False),
        ui / "icon_fan.png": lambda: icy_fan(True),
        ui / "icon_fan_off.png": lambda: icy_fan(False),
        ui / "icon_blind.png": lambda: window_blind(True),
        ui / "icon_blind_off.png": lambda: window_blind(False),
        ui / "icon_garage.png": garage_open,
        ui / "icon_garage_off.png": garage,
        ui / "icon_key.png": lambda: gift_key(False),
        ui / "icon_key_off.png": lambda: gift_key(True),
        ui / "icon_ac.png": thermometer,
        ui / "icon_dishwasher.png": plate_icon,
        ui / "icon_laundry.png": laundry_icon,
        ui / "icon_scene.png": ornament,
        ui / "icon_script.png": nice_list,
        ui / "icon_settings.png": santa_gear,
        ui / "icon_matic.png": lambda: with_hat("icon_matic.png", 21, 7.5, 0.75, rot=-8),
        ui / "icon_robot_vacuum.png": lambda: with_hat("icon_robot_vacuum.png", 27, 9.5, 0.8, rot=-10),
        ui / "icon_pool.png": pool_icon,
        ui / "icon_spa.png": lambda: with_hat("icon_spa.png", 15, 31, 0.62, rot=-14),
        ui / "bar_area_lights.png": lambda: c8_string(True),
        ui / "bar_area_lights_off.png": lambda: c8_string(False),
        ui / "bar_map.png": gingerbread_house,
        ui / "tile_map.png": lambda: gingerbread_house((76, 58)),
        ui / "tile_map_s.png": lambda: gingerbread_house((52, 40)),
        ui / "run_gift.png": lambda: gift(60),
        ui / "run_gift_s.png": lambda: gift(41),
        ui / "brand_bar.png": wreath_icon,
        ui / "clock_face.png": elf_clock_face,
        ui / "clock_hour.png": lambda: elf_arm(54, 116, 104),  # (the short arm: the hours)
        ui / "clock_minute.png": lambda: elf_arm(50, 156, 144),
        ui / "clock_second.png": cane_second,
        ui / "clock_cap.png": elf_cap,
        ui / "clock_face_l.png": lambda: elf_clock_face(4 / 3),
        ui / "clock_hour_l.png": lambda: elf_arm(54, 116, 104, 4 / 3),
        ui / "clock_minute_l.png": lambda: elf_arm(50, 156, 144, 4 / 3),
        ui / "clock_second_l.png": lambda: cane_second(4 / 3),
        ui / "clock_cap_l.png": lambda: elf_cap(4 / 3),
        ui / "knob_switch.png": lambda: peppermint(30, 14.2),
        ui / "knob_grip_v.png": lambda: peppermint(40, 18.5),
        ui / "lock_padlock_closed.png": lambda: padlock(False),
        ui / "lock_padlock_open.png": lambda: padlock(True),
        appl / "plate_knife_fork.png": plate_big,
        appl / "shirt_socks.png": shirt_big,
        appl / "bubble_wash.png": snow_wash,
        appl / "sun_dry.png": star_dry,
        appl / "check_done.png": candy_done,
        appl / "wet_hourglass.png": snow_glass,
    }
    for path, make in art.items():
        img = make()
        master = MASTERS / path.parent.name / path.name.replace("_off.png", ".png")
        # (art only themes have - the top bar's buttons: their own sizes)
        want = Image.open(master).size if master.exists() else OWN_ART[path.stem.replace("_off", "")]
        if img.size != want:
            raise SystemExit(f"{path.name}: {img.size}, the master is {want}")
        img.save(path, optimize=True)
        print(f"{path.relative_to(OUT)}: {img.size[0]}x{img.size[1]}")


if __name__ == "__main__":
    main()
