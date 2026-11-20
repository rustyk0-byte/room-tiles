"""Room Tiles theme folders (docs/THEMES.md, format 1): read and checked.

One reader for every theme - the ones that come with Room Tiles (built at
our build: assets/build_panel.py, assets/build_web.py) and the ones a user
installs (built in Home Assistant: installed.py). Nothing here knows where
a theme lives: every function takes its folder.

  <theme>/theme.json   id, names, colours (+ optional order, default, off)
  <theme>/ui/*.png     pictures replacing the default art by name
  <theme>/appliances/  the appliance animations it replaces
  <theme>/clock.json   its own idle clock (optional, with ui/clock_*.png)

Pillow is imported only where pictures are read (it's slow to import).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).parent
MASTERS = HERE / "masters"  # the default art: what a theme doesn't draw
FORMAT = 1
HEX = re.compile(r"#[0-9A-Fa-f]{6}")
# a colour's name (it becomes a CSS variable on the dashboard: nothing else
# may get in with it)
COLOUR_NAME = re.compile(r"[A-Za-z][A-Za-z0-9]{0,39}")
ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")


class ThemeError(Exception):
    """What's wrong with a theme (each problem a line, for the user)."""

    def __init__(self, problems: list[str] | str) -> None:
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("\n".join(self.problems))


def read(folder: Path, where: str | None = None) -> dict:
    """A theme folder's theme.json, checked (ThemeError says what's wrong).
    `where`: how to name the file in messages (default: its path)."""
    path = folder / "theme.json"
    where = where or str(path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ThemeError(f"{where}: missing") from None
    except (ValueError, UnicodeDecodeError) as err:
        raise ThemeError(f"{where}: not valid JSON ({err})") from None
    if not isinstance(doc, dict):
        raise ThemeError(f"{where}: not a JSON object")
    if doc.get("format") != FORMAT:
        fmt = doc.get("format")
        newer = isinstance(fmt, int) and fmt > FORMAT
        raise ThemeError(
            f"{where}: format {fmt!r} - this Room Tiles reads format {FORMAT}"
            + (" (update Room Tiles to use it)" if newer else "")
        )
    if doc.get("id") != folder.name or not ID.fullmatch(folder.name):
        raise ThemeError(f"{where}: id {doc.get('id')!r} must be the folder's name (a-z, 0-9, - or _, up to 32)")
    names = doc.get("name")
    if not isinstance(names, dict) or not isinstance(names.get("en"), str) or not names["en"].strip():
        raise ThemeError(f'{where}: name needs at least an English one ({{"en": "..."}})')
    if any(not isinstance(v, str) for v in names.values()):
        raise ThemeError(f"{where}: every name must be text")
    colours = doc.get("colors", {})
    if not isinstance(colours, dict):
        raise ThemeError(f"{where}: colors must be an object")
    bad_names = [k for k in colours if not COLOUR_NAME.fullmatch(k)]
    if bad_names:
        raise ThemeError(f"{where}: color names are letters and digits, starting with a letter ({', '.join(map(repr, bad_names))})")
    bad = [k for k, v in colours.items() if not (isinstance(v, str) and HEX.fullmatch(v))]
    if bad:
        raise ThemeError(f"{where}: colors must be #rrggbb ({', '.join(bad)})")
    if "order" in doc and not isinstance(doc["order"], (int, float)):
        raise ThemeError(f"{where}: order must be a number")
    if doc.get("off") not in (None, "gray"):
        raise ThemeError(f'{where}: off must be "gray"')
    return doc


def name(doc: dict, lang: str) -> str:
    """Its name in that language, else the English one."""
    return doc["name"].get(lang) or doc["name"]["en"]


def colours(doc: dict, base: dict) -> dict[str, str]:
    """The theme's colours over `base` (the default theme's, for any it leaves out)."""
    out = dict(base.get("colors", {}))
    out.update(doc.get("colors", {}))
    return out


# ---- the top bars' buttons (docs/THEMES.md "Top bar") -------------------------------
# A theme may draw any of these buttons itself (ui/<name>.png, any size):
# the builders fit each into ONE box - its drawn part (alpha) trimmed,
# scaled to fit, centred - so every top-bar picture is the same size as the
# others and as the buttons' icon symbols (panels: 28 px, ~23 seen, in 48 x
# 40 buttons; the dashboard: 20 px, ~17 seen, in 40 x 36). A little roomier
# than a symbol: a drawing reads smaller than a clean glyph.
# MIRRORED: frontend/src/room-tiles-panel.ts .bar-art (BAR_BOX_WEB / 2 in CSS px) and
# firmware/components/room_tiles/board.cpp (the bar buttons) - a change here must be made there too.
BAR_ART = ("bar_grid", "bar_map", "bar_area_lights", "bar_area_lights_off", "bar_help", "icon_settings")
BAR_BOX_PANEL = (32, 26)  # panel px
BAR_BOX_WEB = (48, 40)  # px - shown at 24 x 20 CSS px (sharp on 2x screens)
# a picture fitted with another's scale and trim: its on / off pair never jumps
BAR_PAIRS = {"bar_area_lights_off": "bar_area_lights"}


def fit_bar_art(img, box: tuple[int, int], pair=None):
    """`img` fitted into `box` (docs/THEMES.md "Top bar"): its drawn part -
    with `pair`'s, when given (the same trim and scale for both) - scaled to
    fit, centred on a clear box. Premultiplied resizing (no dark fringes)."""
    from PIL import Image

    img = img.convert("RGBA")
    bbox = img.getchannel("A").getbbox()
    if pair is not None:
        pb = pair.convert("RGBA").getchannel("A").getbbox()
        if bbox and pb and pair.size == img.size:
            bbox = (min(bbox[0], pb[0]), min(bbox[1], pb[1]), max(bbox[2], pb[2]), max(bbox[3], pb[3]))
    if bbox:
        img = img.crop(bbox)
    k = min(box[0] / img.width, box[1] / img.height)
    size = (max(1, round(img.width * k)), max(1, round(img.height * k)))
    small = img.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA")
    out = Image.new("RGBA", box, (0, 0, 0, 0))
    out.paste(small, ((box[0] - size[0]) // 2, (box[1] - size[1]) // 2))
    return out


# pictures only themes have (no default art): their sizes
OWN_SIZES = {
    "tile_map": (76, 58),
    "tile_map_s": (52, 40),
    "run_gift": (60, 60),
    "run_gift_s": (41, 41),
    "brand_bar": (48, 48),
    "clock_face": (420, 420),
    "clock_face_l": (560, 560),
}
# the idle clock's other pieces: any size (clock.json says how they sit)
CLOCK_FREE = ("clock_hour", "clock_minute", "clock_second", "clock_cap")
SCALES = (1, 2, 4)  # a source may be the size, or 2x / 4x of it (docs/THEMES.md)


def expected_sizes() -> dict[tuple[str, str], tuple[int, int] | None]:
    """(folder, name) -> its size (None: any) - every picture a theme may have."""
    from PIL import Image  # (only the picture checks need Pillow)

    out: dict[tuple[str, str], tuple[int, int] | None] = {}
    for sub in ("ui", "appliances"):
        for f in sorted((MASTERS / sub).glob("*.png")):
            with Image.open(f) as img:
                size = img.size
            out[(sub, f.stem)] = size
            if sub == "ui" and f.stem.startswith("icon_"):
                out[(sub, f"{f.stem}_off")] = size  # (any icon may have an off picture)
    for pic, size in OWN_SIZES.items():
        out[("ui", pic)] = size
    for pic in BAR_ART:  # (any size: fitted into the top bar's box)
        out[("ui", pic)] = None
    for pic in CLOCK_FREE:
        out[("ui", pic)] = None
        out[("ui", f"{pic}_l")] = None
    return out


ALLOWED_FILES = {"theme.json", "clock.json"}  # (beside ui/ and appliances/; README / LICENSE files are fine too)


def check_pictures(theme_dir: Path, scaled_ok: bool = True) -> list[str]:
    """What's wrong with a theme folder's pictures ([] = nothing): only known
    names, readable PNGs, each at its size (or 2x / 4x when `scaled_ok`),
    nothing else in ui/ or appliances/."""
    from PIL import Image

    want = expected_sizes()
    problems: list[str] = []
    for sub in ("ui", "appliances"):
        folder = theme_dir / sub
        if not folder.exists():
            continue
        for f in sorted(folder.iterdir()):
            where = f"{theme_dir.name}/{sub}/{f.name}"
            if f.suffix.lower() != ".png":
                problems.append(f"{where}: not a .png")
                continue
            if (sub, f.stem) not in want:
                problems.append(f"{where}: no picture has this name (docs/THEMES.md lists them)")
                continue
            try:
                with Image.open(f) as img:
                    img.verify()
                with Image.open(f) as img:
                    size = img.size
            except Exception as err:  # noqa: BLE001 - any unreadable file is the same problem
                problems.append(f"{where}: not a readable PNG ({err})")
                continue
            need = want[(sub, f.stem)]
            if need is None:
                continue
            ok = [(need[0] * k, need[1] * k) for k in (SCALES if scaled_ok else (1,))]
            if size not in ok:
                problems.append(f"{where}: {size[0]}x{size[1]} - must be {' or '.join(f'{w}x{h}' for w, h in ok)}")
    return problems


def at_size(img, size: tuple[int, int]):
    """A picture drawn at 2x / 4x brought down to its size (premultiplied: no
    dark fringes); one already at its size as it is."""
    from PIL import Image

    if img.size == size:
        return img
    return img.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA")


# ---- the idle clock (docs/THEMES.md "Idle clock") -----------------------------------
# The idle clock's theme face (<theme>/clock.json + ui/clock_*.png;
# the firmware's idle_clock.cpp draws it): the face picture CLOCK_FACE x
# CLOCK_FACE, the hands' pictures pointing at 12 at their own fixed sizes.
#   center  [x, y]       where the hands turn, on the face
#   hands   hour / minute (second optional): pivot [x, y] in the hand's own
#           picture (it turns about that point), length (a scale, 0.3 - 1.5),
#           at [x, y] (optional: its own spot on the face instead of center)
#   date    (optional) at [x, y] on the face, align left | center | right,
#           font small | medium | large, color (#rrggbb or a theme colour's name)
#   cap     (optional, ui/clock_cap.png) at [x, y]: its middle there (default:
#           center) - e.g. a cap over the hands' pivot
#   order   (optional) the pieces back to front: face, date, hour, minute,
#           second, cap (default that order) - e.g. hands behind a small dial
CLOCK_FACE = 420
CLOCK_FACE_L = 560  # (optional: the same pieces at 4/3, for the wall panels)
CLOCK_HANDS = ("hour", "minute", "second")
CLOCK_PIECES = ("face", "date", "hour", "minute", "second", "cap")


def clock(theme_dir: Path, theme_colours: dict[str, str]) -> dict | None:
    """The theme's clock.json, checked (ThemeError) - None when it draws no clock."""
    from PIL import Image

    path = theme_dir / "clock.json"
    if not path.exists():
        return None
    theme = theme_dir.name

    def bad(why: str) -> ThemeError:
        return ThemeError(f"{theme}/clock.json: {why}")

    try:
        c = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as err:
        raise bad(f"not valid JSON ({err})") from None
    if not isinstance(c, dict):
        raise bad("not a JSON object")
    ui = theme_dir / "ui"

    def size_of(p: Path) -> tuple[int, int]:
        with Image.open(p) as img:
            return img.size

    def point(v, w, h, what):
        if not (isinstance(v, list) and len(v) == 2 and all(isinstance(n, (int, float)) for n in v)):
            raise bad(f"{what} isn't [x, y]")
        if not (0 <= v[0] <= w and 0 <= v[1] <= h):
            raise bad(f"{what} {v} is outside its {w} x {h} picture")

    face = ui / "clock_face.png"
    if not face.exists():
        raise bad("no ui/clock_face.png")
    if size_of(face) != (CLOCK_FACE, CLOCK_FACE):
        raise bad(f"clock_face.png must be {CLOCK_FACE} x {CLOCK_FACE}")
    # the large set (optional, the wall panels): every piece at CLOCK_FACE_L /
    # CLOCK_FACE - the same geometry scaled (clock.json stays in 420 units)
    if (ui / "clock_face_l.png").exists():
        k = CLOCK_FACE_L / CLOCK_FACE
        for small in sorted(ui.glob("clock_*.png")):
            if small.stem.endswith("_l"):
                continue
            large = ui / f"{small.stem}_l.png"
            w, h = size_of(small)
            want = (round(w * k), round(h * k))
            if not large.exists() or size_of(large) != want:
                raise bad(f"the large set needs {large.name} at {want[0]} x {want[1]}")
    point(c.get("center"), CLOCK_FACE, CLOCK_FACE, "center")
    hands = c.get("hands") or {}
    if not isinstance(hands, dict):
        raise bad("hands must be an object")
    for hand_name in ("hour", "minute"):
        if hand_name not in hands:
            raise bad(f"no {hand_name} hand")
    for hand_name, hand in hands.items():
        if hand_name not in CLOCK_HANDS:
            raise bad(f"unknown hand {hand_name!r}")
        if not isinstance(hand, dict):
            raise bad(f"the {hand_name} hand must be an object")
        pic = ui / f"clock_{hand_name}.png"
        if not pic.exists():
            raise bad(f"no ui/clock_{hand_name}.png")
        w, h = size_of(pic)
        point(hand.get("pivot"), w, h, f"{hand_name} pivot")
        try:
            length = float(hand.get("length", 1.0))
        except (TypeError, ValueError):
            raise bad(f"{hand_name} length must be a number") from None
        if not 0.3 <= length <= 1.5:
            raise bad(f"{hand_name} length must be 0.3 - 1.5")
        if "at" in hand:
            point(hand["at"], CLOCK_FACE, CLOCK_FACE, f"{hand_name} at")
    cap = c.get("cap")
    if cap is not None:
        if not isinstance(cap, dict):
            raise bad("cap must be an object")
        if not (ui / "clock_cap.png").exists():
            raise bad("a cap but no ui/clock_cap.png")
        if "at" in cap:
            point(cap["at"], CLOCK_FACE, CLOCK_FACE, "cap at")
    order = c.get("order")
    if order is not None:
        if not isinstance(order, list) or any(p not in CLOCK_PIECES for p in order) or len(set(order)) != len(order):
            raise bad(f"order lists pieces from {', '.join(CLOCK_PIECES)}, each once")
        for need in ("face", "hour", "minute"):
            if need not in order:
                raise bad(f"order leaves out {need}")
    date = c.get("date")
    if date is not None:
        if not isinstance(date, dict):
            raise bad("date must be an object")
        point(date.get("at"), CLOCK_FACE, CLOCK_FACE, "date at")
        if date.get("align", "center") not in ("left", "center", "right"):
            raise bad("date align must be left, center or right")
        if date.get("font", "small") not in ("small", "medium", "large"):
            raise bad("date font must be small, medium or large")
        colour = date.get("color", "text")
        if not (isinstance(colour, str) and (re.fullmatch(r"#[0-9A-Fa-f]{6}", colour) or colour in theme_colours)):
            raise bad(f"date color {colour!r} isn't #rrggbb or a theme colour")
    return c
