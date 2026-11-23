"""The Holly & Ivy appliance animations (assets/themes/holly_ivy/appliances/),
and the stills they play over (the red turtleneck, the holly plate) - one
SVG per frame: 32 frames (8 x 4 sheets, 16 fps - a 2 s loop), drawn in a
196 box at 4x. Every motion repeats a whole number of times per loop, so it
loops without a seam.

  washing  bubble_wash    gentle snow falling over the clothes
  drying   sun_dry        a cozy fireplace, flickering
  waiting  wet_hourglass  a gold bell ringing (time to move the laundry)
  done     check_done     a golden check mark that glints

  python3 tools/themes/holly_ivy/anim.py <svg dir>
  node tools/themes/holly_ivy/render.mjs <svg dir> <png dir>
  python3 tools/themes/holly_ivy/fit.py <png dir> assets/themes/holly_ivy/ui
    (frames <name>__NN.png become assets/themes/holly_ivy/appliances/<name>.png)
"""
import math
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import art  # noqa: E402  (its gradients and holly)

NF = 32
TAU = 2 * math.pi
EXTRA = """
<radialGradient id="night" cx="0.45" cy="0.35" r="0.75"><stop offset="0" stop-color="#24485A"/><stop offset="1" stop-color="#0B1C24"/></radialGradient>
<radialGradient id="hearth" cx="0.5" cy="0.95" r="0.9"><stop offset="0" stop-color="#FF9A2E" stop-opacity="0.85"/><stop offset="0.45" stop-color="#7A2A0E" stop-opacity="0.6"/><stop offset="1" stop-color="#140806" stop-opacity="1"/></radialGradient>
<linearGradient id="brick" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7A3426"/><stop offset="1" stop-color="#4E1F17"/></linearGradient>
<linearGradient id="wood" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7A5432"/><stop offset="1" stop-color="#3E2614"/></linearGradient>
<linearGradient id="goldCheck" gradientUnits="userSpaceOnUse" x1="30" y1="40" x2="170" y2="160"><stop offset="0" stop-color="#FFE9A6"/><stop offset="0.35" stop-color="#E8BE55"/><stop offset="0.7" stop-color="#C08F2E"/><stop offset="1" stop-color="#8A6118"/></linearGradient>
"""


def frame(body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="784" height="784" viewBox="0 0 196 196">'
            f'<defs>{art.DEFS}{EXTRA}</defs>{body}</svg>')


def flake(x, y, r, rot, op=1.0, edge=False):
    """A snowflake; with edge, a thin blue-gray outline so it reads on light pictures too."""
    if r < 3.2:
        return f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r * 0.6:.2f}" fill="#F4FAFF" stroke="#5F7F98" stroke-width="{0.8 if edge else 0}" opacity="{op:.2f}"/>'
    w = max(1.1, r * 0.2)
    d = ""
    for k in range(6):
        a = math.radians(rot + k * 60)
        ca, sa = math.cos(a), math.sin(a)
        ex, ey = x + r * ca, y + r * sa
        d += f"M{x:.2f},{y:.2f} L{ex:.2f},{ey:.2f} "
        bx, by = x + r * 0.55 * ca, y + r * 0.55 * sa
        for s in (-1, 1):
            b = a + s * math.radians(50)
            d += f"M{bx:.2f},{by:.2f} L{bx + r * 0.32 * math.cos(b):.2f},{by + r * 0.32 * math.sin(b):.2f} "
    under = f'<path d="{d}" stroke="#5F7F98" stroke-width="{w + 1.6:.2f}" stroke-linecap="round" fill="none"/>' if edge else ""
    return f'<g opacity="{op:.2f}">{under}<path d="{d}" stroke="#F4FAFF" stroke-width="{w:.2f}" stroke-linecap="round" fill="none"/></g>'


# ---- washing: snow drifting down over the clothes (the still picture) ----
# Gentle: each flake falls a short way and fades in and out as it goes, so
# nothing has to cross the whole picture in one 2 s loop.
rng = random.Random(7)
FLAKES = [(rng.uniform(18, 178), rng.uniform(8, 120), rng.random(), r, rng.uniform(2, 5), rng.random(), rng.uniform(0, 60))
          for r in [3, 3, 3, 3, 3.5, 3.5, 4, 4, 5, 5, 6, 6, 7, 7, 8, 9, 10, 11]]


def snow(t):
    b = ""
    for x0, y0, ph, r, sway, sph, rot0 in FLAKES:
        q = (ph + t) % 1.0
        y = y0 + q * (40 + 3 * r)  # bigger (nearer) flakes fall a bit farther
        x = x0 + sway * math.sin(TAU * (t + sph))
        op = math.sin(math.pi * q) ** 0.7
        b += flake(x, y, r, rot0 + 60 * t, op, edge=True)
    return frame(b)


# ---- drying: a fireplace ----
def flame_path(x, base, h, w, lean):
    tx = x + lean
    return (f"M{x - w:.1f},{base:.1f} C{x - w * 1.1:.1f},{base - h * 0.45:.1f} {tx - w * 0.5:.1f},{base - h * 0.7:.1f} {tx:.1f},{base - h:.1f} "
            f"C{tx + w * 0.55:.1f},{base - h * 0.68:.1f} {x + w * 1.1:.1f},{base - h * 0.45:.1f} {x + w:.1f},{base:.1f} Z")


EMBERS = [(rng.uniform(70, 126), rng.random(), rng.uniform(1.2, 2.2), rng.random()) for _ in range(6)]


def fireplace(t):
    s = lambda k, p: math.sin(TAU * (k * t + p))  # noqa: E731
    glow = 0.55 + 0.12 * s(3, 0.1) + 0.06 * s(5, 0.4)
    b = (f'<ellipse cx="98" cy="128" rx="96" ry="72" fill="url(#glow)" opacity="{glow:.2f}"/>'
         # the brick surround
         '<rect x="18" y="40" width="160" height="136" rx="4" fill="url(#brick)" stroke="#2E100A" stroke-width="3"/>')
    for row, y in enumerate(range(52, 172, 12)):
        b += f'<path d="M20,{y} L176,{y}" stroke="#3A150E" stroke-width="1.4" opacity="0.7"/>'
        for x in range(30 + (row % 2) * 12, 176, 24):
            b += f'<path d="M{x},{y - 12} L{x},{y}" stroke="#3A150E" stroke-width="1.4" opacity="0.7"/>'
    # the firebox: an arch, dark, lit from below
    box = "M50,172 L50,104 Q50,72 98,72 Q146,72 146,104 L146,172 Z"
    b += (f'<path d="{box}" fill="#140806" stroke="#C8A15A" stroke-width="4"/>'
          f'<path d="{box}" fill="url(#hearth)" opacity="{0.55 + 0.25 * glow:.2f}"/>'
          '<clipPath id="box"><path d="M52,170 L52,104 Q52,74 98,74 Q144,74 144,104 L144,170 Z"/></clipPath><g clip-path="url(#box)">')
    # flames: outer orange, inner gold, each tongue breathing at its own pace
    tongues = [(76, 40, 13, 2, 0.0), (98, 62, 17, 3, 0.3), (120, 44, 13, 2, 0.6), (88, 32, 10, 4, 0.8), (110, 34, 10, 3, 0.15)]
    for x, h, w, k, p in tongues:
        hh = h * (1 + 0.16 * s(k, p) + 0.06 * s(k + 2, p + 0.3))
        b += f'<path d="{flame_path(x, 160, hh, w, 5 * s(k - 1 if k > 1 else 1, p + 0.5))}" fill="url(#flameO)" stroke="#E07800" stroke-width="1"/>'
    for x, h, w, k, p in tongues[:3]:
        hh = h * 0.55 * (1 + 0.2 * s(k + 1, p + 0.2))
        b += f'<path d="{flame_path(x, 160, hh, w * 0.55, 3 * s(k, p))}" fill="url(#flameI)"/>'
    for x0, ph, r, sp in EMBERS:  # sparks rising, fading near the top
        q = (ph + t) % 1.0
        y = 150 - q * 72
        x = x0 + 4 * math.sin(TAU * (t * 2 + sp))
        b += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="#FFD27A" opacity="{max(0.0, 1 - q) ** 1.2:.2f}"/>'
    b += '</g>'
    # logs across the grate, their cut ends
    b += ('<path d="M60,168 L136,152" stroke="#3E2614" stroke-width="12" stroke-linecap="round"/>'
          '<path d="M62,152 L138,168" stroke="#5A3A20" stroke-width="12" stroke-linecap="round"/>'
          '<circle cx="138" cy="168" r="6" fill="#C49A6C" stroke="#3E2614" stroke-width="1.5"/>'
          '<circle cx="60" cy="168" r="6" fill="#B08458" stroke="#3E2614" stroke-width="1.5"/>'
          f'<path d="M72,163 L126,157" stroke="#FF8F00" stroke-width="2.5" stroke-linecap="round" opacity="{0.5 + 0.3 * s(4, 0.2):.2f}"/>')
    # hearth and mantel, holly on the shelf
    b += ('<rect x="12" y="172" width="172" height="12" rx="3" fill="#8C7B6A" stroke="#3A2E24" stroke-width="2.5"/>'
          '<rect x="12" y="28" width="172" height="16" rx="4" fill="url(#wood)" stroke="#2A1608" stroke-width="2.5"/>'
          '<path d="M16,31 L180,31" stroke="#C8A15A" stroke-width="2" opacity="0.8"/>')
    b += art.leaf(40, 30, 200, 26, 12) + art.leaf(40, 30, 160, 24, 11) + art.berry(40, 30, 4.5)
    b += art.leaf(156, 30, -20, 26, 12) + art.leaf(156, 30, 20, 24, 11) + art.berry(156, 30, 4.5)
    b += art.sprig(98, 30, 0.42)
    return frame(b)


# ---- waiting: the gold bell ringing ----
def ringing(t):
    a = 18 * math.sin(TAU * 2 * t)  # two swings a loop
    clap = 26 * math.sin(TAU * (2 * t - 0.1))  # the clapper lags behind
    right, left = max(0.0, math.sin(TAU * 2 * t)), max(0.0, -math.sin(TAU * 2 * t))
    b = '<g transform="translate(26,-2) scale(0.6)">'  # (above the clothes: they show below it)
    for side, op in ((1, right), (-1, left)):  # sound arcs on the side its mouth swings to
        if op > 0.05:
            arcs = ""
            for dx, dy in ((80, 30), (100, 46)):
                dx += 4 * op
                arcs += f'<path d="M{120 + side * dx:.1f},{128 - dy} Q{120 + side * (dx + 12):.1f},128 {120 + side * dx:.1f},{128 + dy}"/>'
            # gold with a dark edge: they show on the red sweater, the plate and the tile alike
            b += (f'<g fill="none" stroke-linecap="round" opacity="{op ** 0.7:.2f}">'
                  f'<g stroke="#3A2408" stroke-width="15">{arcs}</g><g stroke="#F2C14E" stroke-width="9">{arcs}</g></g>')
    b += (f'<g transform="rotate({clap:.2f} 120 60)">'
          '<path d="M120,60 L120,192" stroke="#5A3A0C" stroke-width="5"/>'
          '<circle cx="120" cy="200" r="13" fill="url(#brassV)" stroke="#5A3A0C" stroke-width="3"/></g>'
          f'<g transform="rotate({a:.2f} 120 30)">'
          '<path d="M120,48 C86,48 76,82 74,120 C72,150 62,166 50,178 L190,178 C178,166 168,150 166,120 C164,82 154,48 120,48 Z" fill="url(#brass)" stroke="#5A3A0C" stroke-width="3.5" stroke-linejoin="round"/>'
          '<rect x="46" y="174" width="148" height="16" rx="8" fill="url(#brassV)" stroke="#5A3A0C" stroke-width="3"/>'
          '<path d="M96,70 C90,92 88,122 86,150" stroke="#FFF2C2" stroke-width="7" stroke-linecap="round" opacity="0.55" fill="none"/>'
          '<path d="M120,48 L120,30" stroke="#5A3A0C" stroke-width="6"/></g>'
          '<g transform="translate(120,30)">'
          '<path d="M0,0 C-20,-22 -52,-20 -46,2 C-42,16 -16,10 0,0 Z" fill="url(#velvet)" stroke="#4A0610" stroke-width="2.5"/>'
          '<path d="M0,0 C20,-22 52,-20 46,2 C42,16 16,10 0,0 Z" fill="url(#velvet)" stroke="#4A0610" stroke-width="2.5"/>'
          '<path d="M-4,4 L-18,34 L-8,30 L-4,40 Z M4,4 L18,34 L8,30 L4,40 Z" fill="#8E1B2B" stroke="#4A0610" stroke-width="2"/>'
          '<circle cx="0" cy="2" r="8" fill="#B02A3A" stroke="#4A0610" stroke-width="2.5"/></g>')
    b += art.leaf(78, 36, 200, 44, 20) + art.leaf(162, 36, -20, 44, 20) + '</g>'
    return frame(b)


# ---- done: a golden check mark, a glint across it, sparkles ----
CHECK = "M40,102 L76,140 L160,46"


def sparkle(x, y, r, op):
    if r <= 0.3:
        return ""
    q = r * 0.22
    return (f'<path d="M{x},{y - r} Q{x + q},{y - q} {x + r},{y} Q{x + q},{y + q} {x},{y + r} Q{x - q},{y + q} {x - r},{y} Q{x - q},{y - q} {x},{y - r} Z" '
            f'fill="#FFF6D6" opacity="{op:.2f}"/>')


def check(t):
    b = (f'<path d="{CHECK}" stroke="#000" stroke-width="34" stroke-linecap="round" stroke-linejoin="round" fill="none" opacity="0.25" transform="translate(0,4)"/>'
         f'<path d="{CHECK}" stroke="#5A3A0C" stroke-width="34" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
         f'<path d="{CHECK}" stroke="url(#goldCheck)" stroke-width="27" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
         '<path d="M50,100 L76,128 L150,46" stroke="#FFF2C2" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" fill="none" opacity="0.55"/>')
    # the glint: a bright band crossing the check in the first half of the loop
    gx = -40 + t * 2 * 300
    if gx < 240:
        b += (f'<mask id="m"><path d="{CHECK}" stroke="#fff" stroke-width="27" stroke-linecap="round" stroke-linejoin="round" fill="none"/></mask>'
              f'<g mask="url(#m)"><path d="M{gx - 14},196 L{gx + 34},0 L{gx + 52},0 L{gx + 4},196 Z" fill="#FFFBEA" opacity="0.75"/></g>')
    for x, y, r, p in ((160, 22, 13, 0.0), (178, 66, 8, 0.35), (112, 54, 7, 0.6), (26, 128, 6, 0.8)):
        v = max(0.0, math.sin(TAU * (t + p)))
        b += sparkle(x, y, r * v, 0.5 + 0.5 * v)
    b += art.sprig(66, 166, 0.5, 8)
    return frame(b)


# ---- the stills under the animations: the laundry icon's turtleneck, the
# dishwasher icon's holly plate - kept inside the fireplace's bricks ----
def still(svg240):
    body = svg240.split("</defs>", 1)[1].rsplit("</svg>", 1)[0]
    return frame(f'<g transform="translate(14,20) scale(0.7)">{body}</g>')


STILLS = {"shirt_socks": lambda: still(art.turtleneck()), "plate_knife_fork": lambda: still(art.plate())}

ANIMS = {"bubble_wash": snow, "sun_dry": fireplace, "wet_hourglass": ringing, "check_done": check}

if __name__ == "__main__":
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    only = sys.argv[2:] or list(ANIMS) + list(STILLS)
    for name in only:
        if name in STILLS:
            open(f"{out}/{name}.svg", "w").write(STILLS[name]())
            continue
        for f in range(NF):
            open(f"{out}/{name}__{f:02d}.svg", "w").write(ANIMS[name](f / NF))
    print(len(only), "pictures")
