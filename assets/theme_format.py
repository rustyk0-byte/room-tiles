"""The theme folders that come with Room Tiles (assets/themes/<id>/,
docs/THEMES.md format 1), read and checked for the build steps
(build_panel.py, build_web.py, tools/make_off_icons.py). The reading and
checking itself is the integration's (custom_components/room_tiles/themes/
fmt.py) - the same code checks the themes users install. A problem stops
the build (SystemExit). The dashboard reads the same folders at build time
(frontend/theme-data.mjs).
"""
from __future__ import annotations

from pathlib import Path

from _themekit import ROOT, THEME_ART, fmt  # noqa: F401  (ROOT: for callers)

FORMAT = fmt.FORMAT
ID = fmt.ID
MASTERS = fmt.MASTERS
BAR_ART, BAR_BOX_PANEL, BAR_BOX_WEB, BAR_PAIRS = fmt.BAR_ART, fmt.BAR_BOX_PANEL, fmt.BAR_BOX_WEB, fmt.BAR_PAIRS
OWN_SIZES, CLOCK_FREE, SCALES = fmt.OWN_SIZES, fmt.CLOCK_FREE, fmt.SCALES
fit_bar_art = fmt.fit_bar_art
expected_sizes = fmt.expected_sizes
check_pictures = fmt.check_pictures


def read(folder: Path) -> dict:
    """A theme folder's theme.json, checked (SystemExit says what's wrong)."""
    path = folder / "theme.json"
    where = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    try:
        return fmt.read(folder, where)
    except fmt.ThemeError as err:
        raise SystemExit(str(err)) from None


def themes() -> list[dict]:
    """Every theme, the default first, then by `order` (default 100), then id."""
    found = [read(d) for d in sorted(THEME_ART.iterdir()) if (d / "theme.json").exists()]
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
    return fmt.colours(all_[theme], all_[default_id()])


def name(theme: str, lang: str) -> str:
    """Its name in that language, else the English one."""
    return fmt.name({t["id"]: t for t in themes()}[theme], lang)


def source(theme: str):
    """The theme as the packager's Source (its folder, colours and clock)."""
    folder = THEME_ART / theme
    c = colours(theme)
    try:
        clock = fmt.clock(folder, c)
    except fmt.ThemeError as err:
        raise SystemExit(str(err)) from None
    return _panel().Source(theme, folder, c, clock)


def _panel():
    from _themekit import panel

    return panel
