"""Room Tiles theme folders (docs/THEMES.md, format 1): read and checked
here, for every build step (build_panel.py, build_web.py,
tools/make_off_icons.py). The dashboard reads the same folders at build time
(frontend/theme-data.mjs) - one source.

  assets/themes/<id>/theme.json   id, names, colours (+ optional order, default)
  assets/themes/<id>/ui/*.png      pictures replacing the base art by name
  assets/themes/<id>/appliances/   the appliance animations it replaces
  assets/themes/<id>/clock.json    its own idle clock (optional)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEME_ART = ROOT / "assets" / "themes"
FORMAT = 1
HEX = re.compile(r"#[0-9A-Fa-f]{6}")
ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")


def read(folder: Path) -> dict:
    """A theme folder's theme.json, checked (SystemExit says what's wrong)."""
    return _read(folder)


def _read(folder: Path) -> dict:
    path = folder / "theme.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    where = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    if doc.get("format") != FORMAT:
        raise SystemExit(f"{where}: format {doc.get('format')!r} - this Room Tiles reads format {FORMAT}")
    if doc.get("id") != folder.name or not ID.fullmatch(folder.name):
        raise SystemExit(f"{where}: id {doc.get('id')!r} must be the folder's name (a-z, 0-9, - or _, up to 32)")
    names = doc.get("name")
    if not isinstance(names, dict) or not isinstance(names.get("en"), str) or not names["en"].strip():
        raise SystemExit(f"{where}: name needs at least an English one ({{\"en\": \"...\"}})")
    colours = doc.get("colors", {})
    bad = [k for k, v in colours.items() if not (isinstance(v, str) and HEX.fullmatch(v))]
    if bad:
        raise SystemExit(f"{where}: colors must be #rrggbb ({', '.join(bad)})")
    return doc


def themes() -> list[dict]:
    """Every theme, the default first, then by `order` (default 100), then id."""
    found = [_read(d) for d in sorted(THEME_ART.iterdir()) if (d / "theme.json").exists()]
    defaults = [t for t in found if t.get("default")]
    if len(defaults) != 1:
        raise SystemExit(f"assets/themes: exactly one theme must be the default (found {len(defaults)})")
    return sorted(found, key=lambda t: (not t.get("default"), t.get("order", 100), t["id"]))


def ids() -> list[str]:
    return [t["id"] for t in themes()]


def default_id() -> str:
    return themes()[0]["id"]


def colours(theme: str) -> dict[str, str]:
    """The theme's colours, the default theme's for any it leaves out."""
    all_ = {t["id"]: t for t in themes()}
    base = dict(all_[default_id()].get("colors", {}))
    base.update(all_[theme].get("colors", {}))
    return base


def name(theme: str, lang: str) -> str:
    """Its name in that language, else the English one."""
    names = {t["id"]: t for t in themes()}[theme]["name"]
    return names.get(lang) or names["en"]


# ---- the pictures (docs/THEMES.md "Pictures") ---------------------------------------

MASTERS = ROOT / "assets" / "masters"
# pictures only themes have (no default art): their sizes
OWN_SIZES = {
    "bar_area_lights": (44, 34),
    "bar_map": (44, 34),
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
            size = Image.open(f).size
            out[(sub, f.stem)] = size
            if sub == "ui" and f.stem.startswith("icon_"):
                out[(sub, f"{f.stem}_off")] = size  # (any icon may have an off picture)
    for name, size in OWN_SIZES.items():
        out[("ui", name)] = size
    out[("ui", "bar_area_lights_off")] = OWN_SIZES["bar_area_lights"]
    for name in CLOCK_FREE:
        out[("ui", name)] = None
        out[("ui", f"{name}_l")] = None
    return out


def check_pictures(theme_dir: Path, scaled_ok: bool = True) -> list[str]:
    """What's wrong with a theme folder's pictures ([] = nothing): only known
    names, readable PNGs, each at its size (or 2x / 4x when `scaled_ok` -
    today's build takes the size itself only), nothing else in ui/ or
    appliances/."""
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
