"""The Holly & Ivy theme's art (assets/themes/holly_ivy/ui/), drawn as SVG:
candles, holly, ivy, brass bells, poinsettias - no Santa, no tree. Icons at
240 px (4x their 60), the rest at 4x too; the clock at its own sizes.

  python3 tools/themes/holly_ivy/art.py <svg dir>
  node tools/themes/holly_ivy/render.mjs <svg dir> <png dir>     (playwright-core + Chromium)
  python3 tools/themes/holly_ivy/fit.py <png dir> assets/themes/holly_ivy/ui

The lit candle's flame is the lights' orange (#FFB300); an unlit one has a
wisp of smoke instead.
"""
import base64, math, json, sys, os
from pathlib import Path

FLAME = "#FFB300"  # the lights' orange (the default theme's light colour)

DEFS = """
<linearGradient id="wax" x1="0" x2="1"><stop offset="0" stop-color="#6E0F18"/><stop offset="0.35" stop-color="#C8303A"/><stop offset="0.55" stop-color="#D9474E"/><stop offset="1" stop-color="#7A121C"/></linearGradient>
<linearGradient id="waxtop" x1="0" x2="1"><stop offset="0" stop-color="#9C1E28"/><stop offset="0.5" stop-color="#E8676B"/><stop offset="1" stop-color="#A3222C"/></linearGradient>
<radialGradient id="glow" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="#FFB300" stop-opacity="0.55"/><stop offset="0.45" stop-color="#FF9A00" stop-opacity="0.18"/><stop offset="1" stop-color="#FF8A00" stop-opacity="0"/></radialGradient>
<linearGradient id="flameO" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#FF8F00"/><stop offset="0.6" stop-color="#FFB300"/><stop offset="1" stop-color="#FFC94A"/></linearGradient>
<linearGradient id="flameI" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#FFF3C4"/><stop offset="1" stop-color="#FFD54F"/></linearGradient>
<linearGradient id="brass" x1="0" x2="1"><stop offset="0" stop-color="#7A5418"/><stop offset="0.3" stop-color="#D9AE4E"/><stop offset="0.5" stop-color="#F6DD8E"/><stop offset="0.72" stop-color="#C08F2E"/><stop offset="1" stop-color="#6E4A14"/></linearGradient>
<linearGradient id="brassV" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F3D88A"/><stop offset="0.5" stop-color="#C99A38"/><stop offset="1" stop-color="#7A5418"/></linearGradient>
<linearGradient id="leaf" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#3E8A4F"/><stop offset="1" stop-color="#1D4D2B"/></linearGradient>
<linearGradient id="ivy" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#5FA36B"/><stop offset="1" stop-color="#2A5E37"/></linearGradient>
<radialGradient id="berry" cx="0.35" cy="0.32" r="0.7"><stop offset="0" stop-color="#FF6B6B"/><stop offset="0.35" stop-color="#D11A2A"/><stop offset="1" stop-color="#7A0A14"/></radialGradient>
<linearGradient id="bract" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#8E0F1E"/><stop offset="0.5" stop-color="#D3263A"/><stop offset="1" stop-color="#A3172A"/></linearGradient>
<linearGradient id="velvet" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#B02A3A"/><stop offset="1" stop-color="#6A0F1C"/></linearGradient>
"""

def svg(body, w=240, h=240):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><defs>{DEFS}</defs>{body}</svg>'

def holly_leaf(L=70, W=30, spikes=4):
    """A holly leaf along +x from (0,0) to (L,0): spiky edge, concave between spikes."""
    pts_top, pts_bot = [], []
    ts = [0.12 + i * (0.84 / spikes) for i in range(1, spikes + 1)]
    def w(t): return W * 0.5 * math.sin(math.pi * min(1, t * 1.05)) ** 0.8
    d = "M0,0 "
    prev = (0, 0)
    for t in ts[:-1]:
        x, y = t * L, -w(t) * 1.25
        cx, cy = (prev[0] + x) / 2 + L * 0.02, -w((prev[0] / L + t) / 2) * 0.55
        d += f"Q{cx:.1f},{cy:.1f} {x:.1f},{y:.1f} "
        prev = (x, y)
    d += f"Q{(prev[0]+L)/2:.1f},{-w(0.9)*0.5:.1f} {L},0 "
    prev = (L, 0)
    for t in reversed(ts[:-1]):
        x, y = t * L, w(t) * 1.25
        cx, cy = (prev[0] + x) / 2 - L * 0.02, w(((prev[0]) / L + t) / 2) * 0.55
        d += f"Q{cx:.1f},{cy:.1f} {x:.1f},{y:.1f} "
        prev = (x, y)
    d += f"Q{prev[0]/2:.1f},{w(0.1)*0.6:.1f} 0,0 Z"
    return d

def leaf(x, y, ang, L=70, W=30, fill="url(#leaf)"):
    p = holly_leaf(L, W)
    return (f'<g transform="translate({x},{y}) rotate({ang})">'
            f'<path d="{p}" fill="{fill}" stroke="#123620" stroke-width="2" stroke-linejoin="round"/>'
            f'<path d="M2,0 L{L*0.92},0" stroke="#9BD3A6" stroke-width="2" stroke-linecap="round" opacity="0.7"/></g>')

def berry(x, y, r=9):
    return (f'<circle cx="{x}" cy="{y}" r="{r}" fill="url(#berry)" stroke="#4A0610" stroke-width="1.5"/>'
            f'<circle cx="{x-r*0.35}" cy="{y-r*0.38}" r="{r*0.28}" fill="#FFD0D0" opacity="0.85"/>')

def sprig(x, y, s=1.0, ang=0):
    return (f'<g transform="translate({x},{y}) rotate({ang}) scale({s})">'
            + leaf(0, 0, -150, 62, 28) + leaf(0, 0, -30, 62, 28)
            + berry(-6, 6, 9) + berry(8, 8, 9) + berry(1, -6, 9) + '</g>')

def ivy_leaf(x, y, ang, s=1.0):
    p = "M0,0 C-10,-6 -26,-4 -30,-16 C-22,-18 -14,-22 -14,-32 C-6,-28 -2,-36 0,-44 C2,-36 6,-28 14,-32 C14,-22 22,-18 30,-16 C26,-4 10,-6 0,0 Z"
    return (f'<g transform="translate({x},{y}) rotate({ang}) scale({s})"><path d="{p}" fill="url(#ivy)" stroke="#173D22" stroke-width="2" stroke-linejoin="round"/>'
            '<path d="M0,-2 L0,-38 M0,-14 L-20,-16 M0,-14 L20,-16" stroke="#B5E0BC" stroke-width="1.8" fill="none" opacity="0.7"/></g>')

# ---- the candle ----
def candle(lit=True):
    b = ""
    if lit:
        b += '<ellipse cx="120" cy="66" rx="92" ry="80" fill="url(#glow)"/>'
    # a wide pillar: it reads at 60 px
    b += ('<path d="M68,124 L68,218 Q120,232 172,218 L172,124 Z" fill="url(#wax)" stroke="#4A0610" stroke-width="4"/>'
          '<ellipse cx="120" cy="124" rx="52" ry="13" fill="url(#waxtop)" stroke="#4A0610" stroke-width="4"/>'
          '<path d="M78,127 Q80,156 86,158 Q92,155 92,130 Z M146,131 Q148,170 155,172 Q161,168 160,128 Z" fill="#E2565C" opacity="0.9"/>'
          '<path d="M90,138 L90,210" stroke="#F08A8A" stroke-width="7" stroke-linecap="round" opacity="0.35"/>')
    if lit:
        # a big flame in the lights' orange, a pale heart
        b += ('<path d="M120,118 C86,104 88,62 106,34 C110,54 120,56 118,6 C152,40 162,92 120,118 Z" fill="url(#flameO)" stroke="#E07800" stroke-width="2"/>'
              '<path d="M120,112 C104,104 105,80 113,66 C117,78 125,78 123,56 C137,76 138,102 120,112 Z" fill="url(#flameI)"/>'
              '<ellipse cx="120" cy="112" rx="7" ry="7" fill="#6C8CFF" opacity="0.5"/>')
    b += '<path d="M120,123 L120,108" stroke="#2A1A12" stroke-width="5" stroke-linecap="round"/>'
    if not lit:
        b += ('<path d="M121,106 C112,92 130,82 120,66 C111,54 128,44 120,28" fill="none" stroke="#C9C2B6" stroke-width="4" stroke-linecap="round" opacity="0.6"/>'
              '<path d="M120,108 Q127,103 123,98" stroke="#2A1A12" stroke-width="4" fill="none" stroke-linecap="round"/>')
    b += sprig(120, 214, 1.15)
    return svg(b)

# ---- the bell (switch) ----
def bell(ringing=True):
    rot = -14 if ringing else 0
    b = ""
    if ringing:
        b += ('<g fill="none" stroke="#D9454E" stroke-width="7" stroke-linecap="round" opacity="0.9">'
              '<path d="M188,92 Q202,120 188,148"/><path d="M206,78 Q228,120 206,162"/>'
              '<path d="M52,92 Q38,120 52,148"/><path d="M34,78 Q12,120 34,162"/></g>')
    b += (f'<g transform="rotate({rot} 120 60)">'
          '<path d="M120,48 C86,48 76,82 74,120 C72,150 62,166 50,178 L190,178 C178,166 168,150 166,120 C164,82 154,48 120,48 Z" fill="url(#brass)" stroke="#5A3A0C" stroke-width="3.5" stroke-linejoin="round"/>'
          '<rect x="46" y="174" width="148" height="16" rx="8" fill="url(#brassV)" stroke="#5A3A0C" stroke-width="3"/>'
          '<path d="M96,70 C90,92 88,122 86,150" stroke="#FFF2C2" stroke-width="7" stroke-linecap="round" opacity="0.55" fill="none"/>'
          '<circle cx="120" cy="198" r="13" fill="url(#brassV)" stroke="#5A3A0C" stroke-width="3"/>'
          '<path d="M120,48 L120,30" stroke="#5A3A0C" stroke-width="6"/>'
          '</g>')
    # velvet bow on top
    b += ('<g transform="translate(120,30)">'
          '<path d="M0,0 C-20,-22 -52,-20 -46,2 C-42,16 -16,10 0,0 Z" fill="url(#velvet)" stroke="#4A0610" stroke-width="2.5"/>'
          '<path d="M0,0 C20,-22 52,-20 46,2 C42,16 16,10 0,0 Z" fill="url(#velvet)" stroke="#4A0610" stroke-width="2.5"/>'
          '<path d="M-4,4 L-18,34 L-8,30 L-4,40 Z M4,4 L18,34 L8,30 L4,40 Z" fill="#8E1B2B" stroke="#4A0610" stroke-width="2"/>'
          '<circle cx="0" cy="2" r="8" fill="#B02A3A" stroke="#4A0610" stroke-width="2.5"/></g>')
    b += leaf(78, 36, 200, 44, 20) + leaf(162, 36, -20, 44, 20)
    return svg(b)

# ---- the poinsettia (scene) ----
def poinsettia():
    b = ""
    def bracts(n, r, w, rot0, fill, stroke="#4A0610"):
        s = ""
        for i in range(n):
            a = rot0 + i * 360 / n
            s += (f'<g transform="translate(120,120) rotate({a})"><path d="M0,0 C{w},-{r*0.3} {w*0.7},-{r*0.8} 0,-{r} C-{w*0.7},-{r*0.8} -{w},-{r*0.3} 0,0 Z" fill="{fill}" stroke="{stroke}" stroke-width="2.2"/>'
                  f'<path d="M0,-6 L0,-{r*0.88}" stroke="#F07A85" stroke-width="2" opacity="0.6"/></g>')
        return s
    for a in (20, 140, 260):
        b += f'<g transform="translate(120,120) rotate({a})">' + leaf(0, 0, -90, 112, 40).replace('translate(0,0)', 'translate(0,0)') + '</g>'
    b += bracts(6, 100, 30, 0, "#8E0F1E")
    b += bracts(6, 74, 26, 30, "url(#bract)")
    b += bracts(5, 46, 18, 12, "#E0394C")
    for i, (dx, dy) in enumerate([(0, 0), (-9, -5), (9, -5), (-6, 8), (7, 8), (0, -11)]):
        b += f'<circle cx="{120+dx}" cy="{120+dy}" r="5.5" fill="#D9B43A" stroke="#4D6A1E" stroke-width="2"/>'
    return svg(b)

# ---- the key ----
def key(locked=False):
    b = ""
    if locked:
        b += ('<path d="M120,26 C160,26 186,54 186,96 L186,214 L54,214 L54,96 C54,54 80,26 120,26 Z" fill="url(#brassV)" stroke="#5A3A0C" stroke-width="4"/>'
              '<path d="M120,40 C152,40 172,62 172,96 L172,200 L68,200 L68,96 C68,62 88,40 120,40 Z" fill="none" stroke="#7A5418" stroke-width="3" opacity="0.7"/>'
              '<circle cx="120" cy="104" r="18" fill="#1E120A"/><path d="M110,110 L106,160 L134,160 L130,110 Z" fill="#1E120A"/>'
              '<circle cx="120" cy="200" r="0" />')
        b += sprig(120, 40, 0.75)
        return svg(b)
    b += '<g transform="rotate(-40 120 120)">'
    b += ('<rect x="112" y="96" width="16" height="122" rx="6" fill="url(#brass)" stroke="#5A3A0C" stroke-width="3"/>'
          '<path d="M128,182 L156,182 L156,194 L146,194 L146,204 L156,204 L156,216 L128,216 Z" fill="url(#brassV)" stroke="#5A3A0C" stroke-width="3" stroke-linejoin="round"/>'
          '<circle cx="120" cy="62" r="40" fill="url(#brassV)" stroke="#5A3A0C" stroke-width="3.5"/>'
          '<circle cx="120" cy="62" r="22" fill="#14231A" stroke="#5A3A0C" stroke-width="3"/>'
          '<circle cx="98" cy="62" r="7" fill="#14231A"/><circle cx="142" cy="62" r="7" fill="#14231A"/><circle cx="120" cy="40" r="7" fill="#14231A"/>'
          '<rect x="106" y="100" width="28" height="9" rx="4" fill="url(#brassV)" stroke="#5A3A0C" stroke-width="2.5"/></g>')
    # burgundy ribbon + sprig at the bow
    b += sprig(70, 92, 0.8, -20)
    return svg(b)

# ---- the candelabra (area lights, top bar) ----
def candelabra(lit=True):
    b = ""
    xs = [64, 120, 176]; tops = [92, 70, 92]
    if lit:
        for x, t in zip(xs, tops):
            b += f'<ellipse cx="{x}" cy="{t-30}" rx="40" ry="40" fill="url(#glow)"/>'
    b += ('<path d="M64,140 Q64,170 120,172 Q176,170 176,140" fill="none" stroke="url(#brassV)" stroke-width="12" stroke-linecap="round"/>'
          '<rect x="112" y="150" width="16" height="50" fill="url(#brass)" stroke="#5A3A0C" stroke-width="2.5"/>'
          '<path d="M86,214 Q120,190 154,214 Z" fill="url(#brassV)" stroke="#5A3A0C" stroke-width="3"/>')
    for x, t in zip(xs, tops):
        b += (f'<ellipse cx="{x}" cy="140" rx="20" ry="6" fill="url(#brassV)" stroke="#5A3A0C" stroke-width="2.5"/>'
              f'<rect x="{x-11}" y="{t}" width="22" height="{140-t}" fill="url(#wax)" stroke="#4A0610" stroke-width="2.5"/>'
              f'<ellipse cx="{x}" cy="{t}" rx="11" ry="3.5" fill="url(#waxtop)" stroke="#4A0610" stroke-width="2"/>'
              f'<path d="M{x},{t} L{x},{t-8}" stroke="#2A1A12" stroke-width="3" stroke-linecap="round"/>')
        if lit:
            b += (f'<path d="M{x},{t-6} C{x-12},{t-14} {x-8},{t-34} {x},{t-50} C{x+10},{t-34} {x+12},{t-14} {x},{t-6} Z" fill="url(#flameO)"/>'
                  f'<path d="M{x},{t-8} C{x-5},{t-14} {x-4},{t-24} {x},{t-32} C{x+5},{t-24} {x+5},{t-14} {x},{t-8} Z" fill="url(#flameI)"/>')
    b += leaf(96, 178, 160, 40, 18) + leaf(144, 178, 20, 40, 18) + berry(114, 180, 7) + berry(126, 180, 7)
    return svg(b)


# extra gradients for the rest
DEFS += """
<linearGradient id="ivory" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFF8EA"/><stop offset="1" stop-color="#D9CCB0"/></linearGradient>
<linearGradient id="wood" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7A4A2A"/><stop offset="1" stop-color="#4A2A16"/></linearGradient>
<linearGradient id="pane" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFD98A"/><stop offset="1" stop-color="#F09A2A"/></linearGradient>
<linearGradient id="night" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1B2E4A"/><stop offset="1" stop-color="#2E4A6E"/></linearGradient>
<linearGradient id="drape" x1="0" x2="1"><stop offset="0" stop-color="#5E0C18"/><stop offset="0.25" stop-color="#9E2232"/><stop offset="0.5" stop-color="#6E1220"/><stop offset="0.75" stop-color="#A3283A"/><stop offset="1" stop-color="#5E0C18"/></linearGradient>
<linearGradient id="water" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7FD0E8"/><stop offset="1" stop-color="#2F86B5"/></linearGradient>
<linearGradient id="copper" x1="0" x2="1"><stop offset="0" stop-color="#6E3518"/><stop offset="0.35" stop-color="#C8743E"/><stop offset="0.55" stop-color="#E8A06A"/><stop offset="1" stop-color="#6E3518"/></linearGradient>
<linearGradient id="parch" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#F6EBD0"/><stop offset="1" stop-color="#D8C49A"/></linearGradient>
<linearGradient id="steel" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F2EEE6"/><stop offset="1" stop-color="#BFB6A6"/></linearGradient>
<linearGradient id="stone" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#C9BBA2"/><stop offset="1" stop-color="#8E7E66"/></linearGradient>
<radialGradient id="flameR" cx="0.5" cy="0.6" r="0.6"><stop offset="0" stop-color="#FFF3C4"/><stop offset="0.5" stop-color="#FFB300"/><stop offset="1" stop-color="#FF8F00"/></radialGradient>
"""
OUT = 'stroke="#2A1A10" stroke-width="3.5" stroke-linejoin="round"'
BR = 'stroke="#5A3A0C" stroke-width="3.5" stroke-linejoin="round"'

def flame(x, y, h, w):
    """A small candle flame standing at (x, y), h tall."""
    return (f'<path d="M{x},{y} C{x-w},{y-h*0.25} {x-w*0.7},{y-h*0.7} {x},{y-h} C{x+w*0.7},{y-h*0.7} {x+w},{y-h*0.25} {x},{y} Z" fill="url(#flameO)"/>'
            f'<path d="M{x},{y-h*0.1} C{x-w*0.45},{y-h*0.3} {x-w*0.35},{y-h*0.55} {x},{y-h*0.7} C{x+w*0.35},{y-h*0.55} {x+w*0.45},{y-h*0.3} {x},{y-h*0.1} Z" fill="url(#flameI)"/>')

# ---- the fan: three ivy leaves as blades on a brass hub ----
def fan(on=True):
    b = ""
    if on:
        b += '<g fill="none" stroke="#6CBB7A" stroke-width="7" stroke-linecap="round" opacity="0.85"><path d="M150,14 A108,108 0 0 1 222,96"/><path d="M200,196 A108,108 0 0 1 96,224"/><path d="M22,150 A108,108 0 0 1 40,58"/></g>'
    for a in (0, 120, 240):
        b += (f'<g transform="rotate({a + (16 if on else 0)} 120 120)">'
              '<path d="M120,120 L120,84" stroke="#2A5E37" stroke-width="7" stroke-linecap="round"/>'
              + ivy_leaf(120, 88, 0, 1.55) + '</g>')
    b += f'<circle cx="120" cy="120" r="22" fill="url(#brassV)" {BR}/><circle cx="120" cy="120" r="8" fill="#7A5418"/>'
    return svg(b)

# ---- the window (blind): an arched window with an ivy garland ----
def window(open_=True):
    b = (f'<path d="M48,214 L48,92 C48,46 82,22 120,22 C158,22 192,46 192,92 L192,214 Z" fill="url(#wood)" {OUT}/>'
         '<path d="M62,202 L62,94 C62,58 88,36 120,36 C152,36 178,58 178,94 L178,202 Z" fill="url(#night)"/>')
    if open_:
        b += ('<path d="M62,202 L62,94 C62,58 88,36 120,36 C152,36 178,58 178,94 L178,202 Z" fill="url(#pane)" opacity="0.95"/>'
              '<path d="M120,36 L120,202 M62,120 L178,120" stroke="#4A2A16" stroke-width="7"/>'
              '<rect x="102" y="150" width="14" height="40" fill="url(#wax)"/>' + flame(109, 150, 26, 8))
    else:
        b += ('<path d="M62,202 L62,94 C62,58 88,36 120,36 C152,36 178,58 178,94 L178,202 Z" fill="url(#drape)"/>'
              '<path d="M120,40 L120,202" stroke="#3E0810" stroke-width="3"/>'
              '<path d="M78,80 Q74,140 80,200 M98,60 Q94,140 98,200 M142,60 Q146,140 142,200 M162,80 Q166,140 160,200" stroke="#C8475A" stroke-width="3" fill="none" opacity="0.45"/>')
    b += f'<rect x="38" y="206" width="164" height="16" rx="5" fill="url(#stone)" {OUT}/>'
    # ivy along the arch
    for i, (x, y, a) in enumerate([(52, 104, -60), (66, 64, -30), (96, 36, -10), (144, 36, 10), (174, 64, 30), (188, 104, 60)]):
        b += ivy_leaf(x, y, a, 0.85)
    b += '<path d="M52,110 C60,60 90,30 120,28 C150,30 180,60 188,110" fill="none" stroke="#2A5E37" stroke-width="4"/>'
    return svg(b)

# ---- the garage: carriage-house doors with a wreath ----
def wreath(x, y, r):
    s = f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="#1D4D2B" stroke-width="{r*0.55}"/>'
    for k in range(10):
        a = k * 36
        s += f'<g transform="translate({x},{y}) rotate({a}) translate({r},0) rotate(90) scale({r/40})">' + ivy_leaf(0, 10, 0, 0.6) + '</g>'
    s += berry(x - r * 0.6, y - r * 0.75, r * 0.2) + berry(x + r * 0.7, y - r * 0.6, r * 0.2) + berry(x + r * 0.1, y + r * 0.95, r * 0.2)
    s += (f'<path d="M{x},{y+r*0.9} l-{r*0.4},{r*0.6} M{x},{y+r*0.9} l{r*0.4},{r*0.6}" stroke="#8E1B2B" stroke-width="{r*0.18}" stroke-linecap="round"/>'
          f'<circle cx="{x}" cy="{y+r*0.9}" r="{r*0.18}" fill="#B02A3A"/>')
    return s

def garage(open_=True):
    b = (f'<path d="M24,216 L24,84 L120,26 L216,84 L216,216 Z" fill="url(#stone)" {OUT}/>'
         f'<path d="M50,216 L50,110 C50,82 82,70 120,70 C158,70 190,82 190,110 L190,216 Z" fill="#1E120A" {OUT}/>')
    if open_:
        b += ('<path d="M54,216 L54,112 C54,88 84,76 120,76 C156,76 186,88 186,112 L186,216 Z" fill="url(#pane)"/>'
              '<path d="M54,216 L54,112 C54,98 60,90 70,86 L76,216 Z M186,216 L186,112 C186,98 180,90 170,86 L164,216 Z" fill="url(#wood)" stroke="#2A1608" stroke-width="3"/>'
              '<path d="M90,214 L100,168 L140,168 L150,214 Z" fill="#E8A040" opacity="0.6"/>'
              '<rect x="104" y="118" width="32" height="6" rx="3" fill="#4A2A16" opacity="0.5"/>')
    else:
        b += ('<path d="M54,216 L54,112 C54,88 84,76 120,76 C156,76 186,88 186,112 L186,216 Z" fill="url(#wood)"/>'
              '<path d="M120,78 L120,216 M54,150 L186,150 M54,186 L186,186" stroke="#2A1608" stroke-width="4"/>'
              '<path d="M68,120 L104,150 M136,150 L172,120" stroke="#2A1608" stroke-width="3" opacity="0.6"/>')
        b += wreath(120, 118, 24)
    return svg(b)

# ---- the thermostat (ac): a brass thermometer with an ivy sprig ----
def thermometer():
    b = (f'<rect x="100" y="22" width="40" height="160" rx="20" fill="url(#ivory)" {BR}/>'
         '<rect x="112" y="60" width="16" height="122" rx="8" fill="#C8102E"/>'
         f'<circle cx="120" cy="190" r="32" fill="url(#berry)" {BR}/>'
         '<circle cx="110" cy="180" r="8" fill="#FFD0D0" opacity="0.7"/>')
    for k in range(6):
        y = 50 + k * 20
        b += f'<path d="M140,{y} L154,{y}" stroke="#5A3A0C" stroke-width="4" stroke-linecap="round"/>'
    b += ivy_leaf(78, 120, -50, 1.0) + ivy_leaf(84, 80, -80, 0.8) + '<path d="M100,150 C80,130 78,100 90,70" fill="none" stroke="#2A5E37" stroke-width="4"/>'
    return svg(b)

# ---- the dishwasher: fine china with a holly rim ----
def plate():
    b = (f'<circle cx="120" cy="120" r="98" fill="url(#ivory)" {OUT}/>'
         '<circle cx="120" cy="120" r="70" fill="#FFFDF6" stroke="#C9B98E" stroke-width="3"/>'
         '<circle cx="120" cy="120" r="86" fill="none" stroke="#B8862B" stroke-width="3"/>')
    for k in range(8):
        a = k * 45
        b += f'<g transform="rotate({a} 120 120)">' + leaf(98, 34, 160, 30, 14) + leaf(142, 34, 20, 30, 14) + berry(120, 34, 5) + '</g>'
    b += sprig(120, 120, 0.9)
    return svg(b)

# ---- the laundry: a red turtleneck, cable-knit ----
def turtleneck():
    knit = "#8A1626"
    b = ('<path d="M92,52 L60,62 Q34,72 28,100 L14,196 Q14,206 24,208 L48,210 Q58,208 58,198 L66,126 '
         'L68,214 Q120,226 172,214 L174,126 L182,198 Q182,208 192,210 L216,208 Q226,206 226,196 L212,100 '
         'Q206,72 180,62 L148,52 Z" fill="url(#velvet)" stroke="#4A0610" stroke-width="4" stroke-linejoin="round"/>'
         # the rolled turtleneck collar
         '<path d="M88,26 Q120,18 152,26 L154,56 Q120,66 86,56 Z" fill="#C0303F" stroke="#4A0610" stroke-width="4" stroke-linejoin="round"/>'
         f'<path d="M98,30 L97,56 M110,26 L110,60 M120,24 L120,62 M130,26 L130,60 M142,30 L143,56" stroke="{knit}" stroke-width="3" opacity="0.8"/>'
         # ribbed cuffs and hem
         f'<path d="M16,186 L56,190 M17,196 L56,199" stroke="{knit}" stroke-width="3.5"/>'
         f'<path d="M224,186 L184,190 M223,196 L184,199" stroke="{knit}" stroke-width="3.5"/>'
         f'<path d="M69,200 Q120,212 171,200 M69,192 Q120,204 171,192" stroke="{knit}" stroke-width="3.5" fill="none"/>')
    # a cable down the front, a plain rib either side
    for y in range(76, 186, 22):
        b += (f'<path d="M108,{y} C108,{y+8} 132,{y+12} 132,{y+22} M132,{y} C132,{y+8} 108,{y+12} 108,{y+22}" '
              f'stroke="{knit}" stroke-width="5" fill="none" stroke-linecap="round"/>')
    b += f'<path d="M94,72 L94,192 M146,72 L146,192" stroke="{knit}" stroke-width="3" opacity="0.8"/>'
    b += '<path d="M80,80 Q76,130 80,180" stroke="#E0606A" stroke-width="6" stroke-linecap="round" fill="none" opacity="0.35"/>'
    return svg(b)

# ---- the robot vacuum: ivory and brass, a sprig on top ----
def vacuum():
    b = (f'<circle cx="120" cy="128" r="94" fill="url(#ivory)" {OUT}/>'
         '<circle cx="120" cy="128" r="70" fill="none" stroke="#C9B98E" stroke-width="3"/>'
         f'<circle cx="120" cy="98" r="18" fill="url(#brassV)" {BR}/>'
         '<path d="M56,190 Q120,222 184,190" fill="none" stroke="#B8862B" stroke-width="6" stroke-linecap="round"/>')
    b += sprig(120, 50, 0.85)
    return svg(b)

# ---- the Matic: the default picture as it is (its shape is how people know
# it), two gold jingle bells on a red ribbon hung from the dock's corner ----
MASTER = Path(__file__).resolve().parents[3] / "custom_components/room_tiles/themes/masters/ui"

def jingle(x, y, r):
    return (f'<path d="M{x},{y-r} L{x},{y-r-10}" stroke="#5A3A0C" stroke-width="4"/>'
            f'<circle cx="{x}" cy="{y-r-12}" r="6" fill="none" stroke="url(#brassV)" stroke-width="4"/>'
            f'<circle cx="{x}" cy="{y}" r="{r}" fill="url(#brass)" stroke="#5A3A0C" stroke-width="3"/>'
            f'<path d="M{x-r*0.75},{y+r*0.2} L{x+r*0.75},{y+r*0.2}" stroke="#3A2408" stroke-width="4" stroke-linecap="round"/>'
            f'<circle cx="{x-r*0.75}" cy="{y+r*0.2}" r="4" fill="#3A2408"/><circle cx="{x+r*0.75}" cy="{y+r*0.2}" r="4" fill="#3A2408"/>'
            f'<path d="M{x},{y+r*0.2} L{x},{y+r}" stroke="#3A2408" stroke-width="3"/>'
            f'<circle cx="{x-r*0.38}" cy="{y-r*0.42}" r="{r*0.22}" fill="#FFF2C2" opacity="0.8"/>')

def matic():
    png = base64.b64encode((MASTER / "icon_matic.png").read_bytes()).decode()
    b = (f'<image href="data:image/png;base64,{png}" x="0" y="0" width="240" height="240" '
         'style="image-rendering:pixelated"/>')
    # a red bow beside the dock's light, the bells hung in the free space above the pad
    b += ('<path d="M206,16 Q186,40 190,74 M206,16 Q220,24 216,34" stroke="#B02A3A" stroke-width="6" fill="none" stroke-linecap="round"/>')
    b += jingle(216, 66, 22) + jingle(190, 118, 29)
    b += ('<g transform="translate(206,16)">'
          '<path d="M0,0 C-14,-16 -36,-14 -32,2 C-29,12 -11,7 0,0 Z" fill="url(#velvet)" stroke="#4A0610" stroke-width="2.5"/>'
          '<path d="M0,0 C14,-16 36,-14 32,2 C29,12 11,7 0,0 Z" fill="url(#velvet)" stroke="#4A0610" stroke-width="2.5"/>'
          '<circle cx="0" cy="1" r="6" fill="#B02A3A" stroke="#4A0610" stroke-width="2"/></g>')
    return svg(b)

# ---- the pool: a brass ladder in clear water ----
def pool():
    b = ('<path d="M20,150 Q50,136 80,150 T140,150 T200,150 T230,150 L230,224 L20,224 Z" fill="url(#water)"/>'
         '<path d="M20,176 Q50,162 80,176 T140,176 T200,176 T230,176" fill="none" stroke="#E6F6FB" stroke-width="5" opacity="0.8"/>'
         '<path d="M20,202 Q50,188 80,202 T140,202 T200,202 T230,202" fill="none" stroke="#E6F6FB" stroke-width="5" opacity="0.6"/>'
         '<path d="M78,190 L78,70 C78,40 110,40 110,64 M150,190 L150,70 C150,40 182,40 182,64" fill="none" stroke="url(#brassV)" stroke-width="12" stroke-linecap="round"/>'
         '<path d="M78,104 L150,104 M78,140 L150,140" stroke="#B8862B" stroke-width="9" stroke-linecap="round"/>')
    b += ivy_leaf(62, 88, -40, 0.75) + ivy_leaf(196, 82, 40, 0.75)
    return svg(b)

# ---- the spa: a copper tub, steam rising ----
def spa():
    b = '<g fill="none" stroke="#E8E0D0" stroke-width="8" stroke-linecap="round" opacity="0.75"><path d="M84,96 C70,76 98,62 84,40"/><path d="M120,90 C106,70 134,56 120,30"/><path d="M156,96 C142,76 170,62 156,40"/></g>'
    b += (f'<path d="M26,118 L214,118 L196,206 Q120,222 44,206 Z" fill="url(#copper)" {OUT}/>'
          '<ellipse cx="120" cy="118" rx="94" ry="16" fill="url(#water)" stroke="#2A1A10" stroke-width="3.5"/>'
          '<path d="M44,150 Q120,166 196,150" fill="none" stroke="#F2B88A" stroke-width="4" opacity="0.6"/>')
    b += leaf(40, 120, 200, 40, 18) + leaf(200, 120, -20, 40, 18) + berry(38, 112, 7) + berry(202, 112, 7)
    return svg(b)

# ---- the script: a parchment scroll with a wax seal ----
def scroll():
    b = (f'<rect x="56" y="40" width="132" height="160" fill="url(#parch)" {OUT}/>'
         f'<rect x="40" y="26" width="164" height="28" rx="14" fill="url(#parch)" {OUT}/>'
         f'<rect x="40" y="188" width="164" height="28" rx="14" fill="url(#parch)" {OUT}/>')
    for k in range(5):
        y = 76 + k * 20
        b += f'<path d="M76,{y} L{168 - (k % 2) * 30},{y}" stroke="#8A7350" stroke-width="5" stroke-linecap="round"/>'
    b += ('<circle cx="160" cy="176" r="24" fill="url(#velvet)" stroke="#4A0610" stroke-width="3"/>'
          '<circle cx="160" cy="176" r="15" fill="none" stroke="#E07A86" stroke-width="2.5" opacity="0.7"/>')
    b += leaf(150, 176, 150, 34, 16) + leaf(170, 176, 30, 34, 16)
    return svg(b)

# ---- the gear (settings): brass, with an ivy sprig ----
def gear(w=240):
    teeth = ""
    for k in range(8):
        teeth += f'<rect x="108" y="18" width="24" height="36" rx="5" fill="url(#brass)" {BR} transform="rotate({k*45} 120 120)"/>'
    b = teeth + f'<circle cx="120" cy="120" r="72" fill="url(#brassV)" {BR}/><circle cx="120" cy="120" r="30" fill="#14201A" {BR}/>'
    b += ivy_leaf(176, 182, 30, 0.95) + ivy_leaf(150, 204, -10, 0.8)
    return svg(b)

# ---- the map: a stone cottage, lit window, wreath on the door ----
def cottage(w, h):
    sx, sy = w / 304, h / 232
    b = (f'<g transform="scale({sx},{sy})">'
         f'<path d="M40,226 L40,110 L152,30 L264,110 L264,226 Z" fill="url(#stone)" {OUT}/>'
         f'<path d="M24,118 L152,22 L280,118" fill="none" stroke="#5E2B22" stroke-width="20" stroke-linecap="round" stroke-linejoin="round"/>'
         f'<rect x="206" y="40" width="26" height="54" fill="#7A6A5A" {OUT}/>'
         f'<rect x="64" y="132" width="56" height="48" rx="4" fill="url(#pane)" {OUT}/><path d="M92,132 L92,180 M64,156 L120,156" stroke="#4A2A16" stroke-width="5"/>'
         f'<path d="M164,226 L164,150 C164,128 216,128 216,150 L216,226 Z" fill="url(#velvet)" {OUT}/>'
         + wreath(190, 164, 14) +
         '</g>')
    return svg(b, w, h)

# ---- the run button: a brass lantern, lit ----
def lantern(w=240):
    s = w / 240
    b = (f'<g transform="scale({s})"><ellipse cx="120" cy="130" rx="80" ry="80" fill="url(#glow)"/>'
         f'<path d="M100,32 C100,14 140,14 140,32" fill="none" stroke="url(#brassV)" stroke-width="9"/>'
         f'<path d="M72,64 L120,28 L168,64 Z" fill="url(#brassV)" {BR}/>'
         f'<rect x="78" y="64" width="84" height="120" fill="url(#pane)" {BR}/>'
         '<path d="M120,64 L120,184 M78,124 L162,124" stroke="#7A5418" stroke-width="5" opacity="0.5"/>'
         '<rect x="110" y="140" width="20" height="40" fill="url(#wax)"/>' + flame(120, 140, 40, 13) +
         f'<rect x="66" y="184" width="108" height="20" rx="6" fill="url(#brassV)" {BR}/>'
         + leaf(70, 196, 170, 44, 20) + leaf(170, 196, 10, 44, 20) + berry(112, 200, 8) + berry(128, 200, 8) + '</g>')
    return svg(b, w, w)

# ---- knobs: a glossy holly berry ----
def knob(w):
    b = (f'<circle cx="{w/2}" cy="{w/2}" r="{w*0.44}" fill="url(#berry)" stroke="#4A0610" stroke-width="{w*0.03}"/>'
         f'<circle cx="{w*0.36}" cy="{w*0.34}" r="{w*0.12}" fill="#FFE0E0" opacity="0.85"/>'
         f'<circle cx="{w/2}" cy="{w*0.1}" r="{w*0.05}" fill="#3A1A10"/>')
    return svg(b, w, w)

# ---- padlocks: brass, a holly sprig engraved ----
def padlock(closed=True):
    w, h = 304, 336
    shackle = 'M92,150 L92,96 C92,40 212,40 212,96 L212,150' if closed else 'M92,150 L92,96 C92,40 212,40 212,96 L212,110'
    tr = '' if closed else ' transform="translate(0,-34)"'
    b = (f'<path d="{shackle}" fill="none" stroke="url(#steel)" stroke-width="26" stroke-linecap="round"{tr}/>'
         f'<rect x="52" y="142" width="200" height="176" rx="26" fill="url(#brassV)" {BR}/>'
         '<rect x="66" y="156" width="172" height="148" rx="18" fill="none" stroke="#7A5418" stroke-width="3" opacity="0.7"/>'
         '<circle cx="152" cy="236" r="16" fill="#1E120A"/><path d="M144,240 L140,282 L164,282 L160,240 Z" fill="#1E120A"/>')
    b += sprig(152, 186, 0.7)
    return svg(b, w, h)

# ---- the idle clock (clock.json): drawn at the 420 size, scaled for _l (560) ----
def scaled(body, w, h, k):
    return svg(f'<g transform="scale({k})">{body}</g>', round(w * k), round(h * k))

def clock_face(k=1.0):
    c = 210
    b = (f'<circle cx="{c}" cy="{c}" r="204" fill="url(#brass)" stroke="#5A3A0C" stroke-width="4"/>'
         f'<circle cx="{c}" cy="{c}" r="188" fill="#0F1D15" stroke="#5A3A0C" stroke-width="3"/>'
         f'<circle cx="{c}" cy="{c}" r="128" fill="none" stroke="#B8862B" stroke-width="2" opacity="0.6"/>')
    # Roman numerals in brass
    nums = ["XII", "I", "II", "III", "IIII", "V", "VI", "VII", "VIII", "IX", "X", "XI"]
    for i, n in enumerate(nums):
        a = math.radians(i * 30 - 90)
        x, y = c + 150 * math.cos(a), c + 150 * math.sin(a)
        size = 34 if i % 3 == 0 else 24
        b += (f'<text x="{x:.1f}" y="{y:.1f}" font-family="Georgia, \'Times New Roman\', serif" font-size="{size}" '
              f'fill="#E9C87A" text-anchor="middle" dominant-baseline="central" font-weight="700">{n}</text>')
    # minute ticks
    for i in range(60):
        if i % 5 == 0:
            continue
        b += f'<path d="M{c},{c-120} L{c},{c-128}" stroke="#B8862B" stroke-width="2" transform="rotate({i*6} {c} {c})" opacity="0.7"/>'
    # holly at XII
    b += sprig(c, 34, 0.9)
    return scaled(b, 420, 420, k)

def hand_hour(k=1.0):
    # 54 x 116, pivot (27, 104)
    b = ('<path d="M27,6 C40,22 40,34 27,46 C14,34 14,22 27,6 Z" fill="url(#brass)" stroke="#3A2408" stroke-width="2.5"/>'
         '<path d="M27,44 L33,104 L21,104 Z" fill="url(#brass)" stroke="#3A2408" stroke-width="2.5" stroke-linejoin="round"/>'
         '<circle cx="27" cy="26" r="6" fill="#0F1D15"/>'
         '<circle cx="27" cy="104" r="11" fill="url(#brassV)" stroke="#3A2408" stroke-width="2.5"/>')
    return scaled(b, 54, 116, k)

def hand_minute(k=1.0):
    # 50 x 156, pivot (25, 144)
    b = ('<path d="M25,4 L32,30 L25,40 L18,30 Z" fill="url(#brass)" stroke="#3A2408" stroke-width="2.5" stroke-linejoin="round"/>'
         '<path d="M25,38 L30,144 L20,144 Z" fill="url(#brass)" stroke="#3A2408" stroke-width="2.5" stroke-linejoin="round"/>'
         '<circle cx="25" cy="144" r="10" fill="url(#brassV)" stroke="#3A2408" stroke-width="2.5"/>')
    return scaled(b, 50, 156, k)

def hand_second(k=1.0):
    # 48 x 170, pivot (24, 150): a burgundy needle, a berry at its tail
    b = ('<path d="M24,6 L24,150" stroke="#B02A3A" stroke-width="3.5" stroke-linecap="round"/>'
         '<path d="M24,150 L24,166" stroke="#B02A3A" stroke-width="6" stroke-linecap="round"/>'
         + berry(24, 160, 8))
    return scaled(b, 48, 170, k)

def clock_cap(k=1.0):
    b = '<circle cx="13" cy="13" r="11" fill="url(#brassV)" stroke="#3A2408" stroke-width="2"/><circle cx="13" cy="13" r="5" fill="url(#berry)"/>'
    return scaled(b, 26, 26, k)

# ---- switch tracks: brass-rimmed, red / green / gold when on, dark velvet off ----
TRACK_FILL = {
    "gold": ("#F6D778", "#D4A23A", "#8F6418", "#4A1A0C"),
    "red": ("#E2565E", "#A9222C", "#6A0E18", "#FFF3E0"),
    "green": ("#6CBB7A", "#2F7A45", "#1A4A2A", "#FFF3E0"),
    "blue": ("#6FA6F0", "#2B62BE", "#183E80", "#FFF3E0"),
    "dark": ("#2C3A31", "#1A2720", "#101A14", "#B8B29C"),
}

def track(w, word, fill, text_left):
    """A switch track, w x 32 (drawn 4x): the word on the side the knob leaves free."""
    W, H = w * 4, 128
    top, mid, bot, ink = TRACK_FILL[fill]
    gid = f"t{fill}"
    defs = (f'<linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/>'
            f'<stop offset="0.55" stop-color="{mid}"/><stop offset="1" stop-color="{bot}"/></linearGradient>')
    knob_room = 128  # the knob (30 px) sits at one end
    x0, x1 = (16, W - knob_room) if text_left else (knob_room, W - 16)
    size = min(64, (x1 - x0) / (0.66 * len(word)))
    b = (f'<defs>{defs}</defs>'
         f'<rect x="6" y="6" width="{W-12}" height="{H-12}" rx="{(H-12)/2}" fill="url(#{gid})" stroke="url(#brassV)" stroke-width="10"/>'
         f'<rect x="20" y="16" width="{W-40}" height="30" rx="15" fill="#FFFFFF" opacity="0.16"/>'
         f'<text x="{(x0+x1)/2}" y="{H/2+2}" font-family="DejaVu Sans, Verdana, sans-serif" font-weight="700" font-size="{size:.0f}" '
         f'letter-spacing="2" fill="{ink}" text-anchor="middle" dominant-baseline="central">{word}</text>')
    return svg(b, W, H)

ART = {
    "icon_light": lambda: candle(True), "icon_light_off": lambda: candle(False),
    "icon_switch": lambda: bell(True), "icon_switch_off": lambda: bell(False),
    "icon_scene": poinsettia,
    "icon_key": lambda: key(False), "icon_key_off": lambda: key(True),
    "bar_area_lights": lambda: candelabra(True), "bar_area_lights_off": lambda: candelabra(False),
    "icon_fan": lambda: fan(True), "icon_fan_off": lambda: fan(False),
    "icon_blind": lambda: window(True), "icon_blind_off": lambda: window(False),
    "icon_garage": lambda: garage(True), "icon_garage_off": lambda: garage(False),
    "icon_ac": thermometer, "icon_dishwasher": plate, "icon_laundry": turtleneck,
    "icon_robot_vacuum": vacuum, "icon_matic": matic,
    "icon_pool": pool, "icon_spa": spa, "icon_script": scroll, "icon_settings": gear,
    "bar_map": lambda: cottage(304, 232), "tile_map": lambda: cottage(304, 232), "tile_map_s": lambda: cottage(208, 160),
    "run_gift": lambda: lantern(240), "run_gift_s": lambda: lantern(164),
    "knob_switch": lambda: knob(120), "knob_grip_v": lambda: knob(160),
    "lock_padlock_closed": lambda: padlock(True), "lock_padlock_open": lambda: padlock(False),
    "clock_face": lambda: clock_face(1), "clock_face_l": lambda: clock_face(4 / 3),
    "clock_hour": lambda: hand_hour(1), "clock_hour_l": lambda: hand_hour(4 / 3),
    "clock_minute": lambda: hand_minute(1), "clock_minute_l": lambda: hand_minute(4 / 3),
    "clock_second": lambda: hand_second(1), "clock_second_l": lambda: hand_second(4 / 3),
    "clock_cap": lambda: clock_cap(1), "clock_cap_l": lambda: clock_cap(4 / 3),
    # the tracks (rules.ts switchTrack): lights gold, switches red, fans green,
    # covers green, locks gold; heat red and cool blue as in every theme
    "track_switch_off": lambda: track(75, "OFF", "dark", False),
    "track_switch_on": lambda: track(75, "ON", "gold", True),
    "track_switch_on_raspberry": lambda: track(75, "ON", "red", True),
    "track_switch_on_cyan": lambda: track(75, "ON", "green", True),
    "track_switch_on_red": lambda: track(75, "ON", "red", True),
    "track_switch_on_blue": lambda: track(75, "ON", "blue", True),
    "track_switch_on_slate": lambda: track(75, "ON", "green", True),
    "track_switch_open_green": lambda: track(100, "OPEN", "green", True),
    "track_switch_closed": lambda: track(100, "CLOSED", "dark", False),
    "track_switch_locked_purple": lambda: track(120, "LOCKED", "gold", True),
    "track_switch_unlocked": lambda: track(120, "UNLOCKED", "dark", False),
}

if __name__ == "__main__":
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    for name, f in ART.items():
        open(f"{out}/{name}.svg", "w").write(f())
    print(len(ART), "svg")
