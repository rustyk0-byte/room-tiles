"""Generated "off" pictures (theme.json "off": "gray", docs/THEMES.md "Off
pictures"): an entity icon in gray - the map markers' off look exactly
(panel.off_gray, map.ts OFF_BRIGHTNESS) - inside a thin outline in the tile
type's full "on" colour (the theme's token, as the markers' ring), shrunk so
the outline ends where the icon does: on and off are the same size. A tile
and its marker read alike: gray = off, the colour = what it is. Made for
the themes that come with Room Tiles at our build
(assets/tools/make_off_icons.py) and for installed ones in Home Assistant.
"""

from __future__ import annotations

from PIL import Image, ImageFilter

from .panel import off_gray

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
    gray = off_gray(img, brightness).resize((w * K, h * K), Image.LANCZOS)
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




def colour_of(colours: dict[str, str], icon: str) -> tuple[int, int, int]:
    hexc = colours[TOKEN[icon]]
    return tuple(int(hexc[i : i + 2], 16) for i in (1, 3, 5))
