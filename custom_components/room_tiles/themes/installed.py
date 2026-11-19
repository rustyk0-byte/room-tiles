"""Themes a user installs (docs/THEMES.md "Installed themes"): folders or
zips in /config/room_tiles_themes/, found, checked and built here - the
panel packs and the dashboard's pictures, with the same packager as the
themes that come with Room Tiles. Blocking (files, Pillow): Home
Assistant runs it in the executor (user_themes.py). Nothing here imports
Home Assistant.

A built theme is kept in the cache folder under a key made from its files'
fingerprint and the packager's (the default art, the panels' format, the
quantizer): unchanged, it's never built again - not even after a restart.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import fmt

# an installed theme's id everywhere Room Tiles keeps one (panels'
# settings, the dashboard, packs): its folder's id after this - never the
# same as a theme that comes with Room Tiles (none starts with it)
PREFIX = "user:"
# MIRRORED: frontend/theme-data.mjs BUTTONS (the buttons a theme may draw) - a change here must be made there too.
BUTTONS = ("bar_grid", "bar_area_lights", "bar_map", "bar_help", "tile_map", "run_gift", "icon_settings")
BUILDER = 1  # (bump when the build's output changes: every installed theme builds again)
ZIP_MAX_BYTES = 64 * 1024 * 1024  # a theme zip, unpacked
ZIP_MAX_FILES = 2000


@dataclass
class Found:
    """A theme in the themes folder: a folder or a zip, and its fingerprint."""

    id: str  # its folder's name (the zip's: its name without .zip)
    path: Path
    zipped: bool
    stamp: str  # changes whenever any of its files does


@dataclass
class Built:
    """A theme ready to use (or why it isn't: `problems`)."""

    id: str
    source: str  # its file in the themes folder (for messages)
    doc: dict = field(default_factory=dict)  # theme.json
    colours: dict = field(default_factory=dict)
    off_art: list[str] = field(default_factory=list)  # icons with an "off" picture
    button_art: list[str] = field(default_factory=list)  # buttons it draws (BUTTONS)
    version: str = ""  # changes with its content (the dashboard's image addresses)
    packs: dict[str, bytes] = field(default_factory=dict)  # "" (wall panels) / "-round"
    web: Path | None = None  # its dashboard pictures: web/ui, web/appliances
    problems: list[str] = field(default_factory=list)
    coarse: bool = False  # built without libimagequant (soft edges a little coarser on panels)

    @property
    def key(self) -> str:
        return PREFIX + self.id

    @property
    def ok(self) -> bool:
        return not self.problems


def _stamp(path: Path) -> str:
    h = hashlib.sha256()
    if path.is_file():
        st = path.stat()
        h.update(f"{st.st_size}:{st.st_mtime_ns}".encode())
    else:
        for f in sorted(p for p in path.rglob("*") if p.is_file()):
            st = f.stat()
            h.update(f"{f.relative_to(path).as_posix()}:{st.st_size}:{st.st_mtime_ns}\n".encode())
    return h.hexdigest()[:20]


def scan(root: Path) -> tuple[list[Found], list[Built]]:
    """The themes folder's themes (a folder with a theme.json, or a .zip),
    and what can't even be looked at (a folder without theme.json, two of
    one id). Quick: only file names, sizes and times."""
    found: dict[str, Found] = {}
    broken: list[Built] = []
    if not root.is_dir():
        return [], []
    for entry in sorted(root.iterdir()):
        if entry.name.startswith(".") or entry.name.startswith("__"):
            continue
        if entry.is_dir():
            if not (entry / "theme.json").exists():
                broken.append(Built(entry.name, entry.name, problems=[f"{entry.name}: no theme.json in this folder"]))
                continue
            theme_id, zipped = entry.name, False
        elif entry.suffix.lower() == ".zip":
            theme_id, zipped = entry.stem, True
        else:
            continue  # (a README or such beside the themes)
        if theme_id in found:
            other = found[theme_id].path.name
            broken.append(Built(theme_id, entry.name, problems=[f"{entry.name}: {other} has the same id - this one is left out"]))
            continue
        found[theme_id] = Found(theme_id, entry, zipped, _stamp(entry))
    return list(found.values()), broken


def packager_stamp() -> str:
    """What else a build depends on: the default art (a theme's gaps), the
    panels' format, the quantizer and the builder itself."""
    from ..const import PANEL_SCHEMA
    from .panel import HAS_LIQ

    h = hashlib.sha256(f"{BUILDER}:{PANEL_SCHEMA}:{HAS_LIQ}\n".encode())
    h.update(_stamp(fmt.MASTERS).encode())
    return h.hexdigest()[:12]


def _unzip(zpath: Path, dest: Path) -> Path:
    """A theme zip unpacked into `dest`: its theme folder (theme.json at the
    zip's top, or in its one top folder). Nothing outside `dest`, size and
    file count limited."""
    try:
        zf = zipfile.ZipFile(zpath)
    except (OSError, zipfile.BadZipFile) as err:
        raise fmt.ThemeError(f"{zpath.name}: not a readable zip ({err})") from None
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX/")]
        if len(infos) > ZIP_MAX_FILES or sum(i.file_size for i in infos) > ZIP_MAX_BYTES:
            raise fmt.ThemeError(f"{zpath.name}: too big for a theme")
        names = [i.filename for i in infos]
        if "theme.json" in names:
            top = ""
        else:
            tops = {n.split("/", 1)[0] for n in names}
            if len(tops) != 1 or f"{next(iter(tops))}/theme.json" not in names:
                raise fmt.ThemeError(f"{zpath.name}: no theme.json at its top or in its one folder")
            top = next(iter(tops)) + "/"
        folder = dest / zpath.stem
        root = folder.resolve()
        for info in infos:
            if not info.filename.startswith(top):
                continue
            rel = info.filename[len(top) :]
            out = (folder / rel).resolve()
            if root not in out.parents:
                raise fmt.ThemeError(f"{zpath.name}: {info.filename} points outside the theme")
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return folder


def _art_lists(ui: Path) -> tuple[list[str], list[str]]:
    files = {f.name for f in ui.glob("*.png")} if ui.is_dir() else set()
    off_art = sorted(f[: -len("_off.png")] for f in files if f.endswith("_off.png"))
    return off_art, [b for b in BUTTONS if f"{b}.png" in files]


def build(found: Found, base: dict, cache: Path) -> Built:
    """`found` checked and built (or its problems): its packs and pictures in
    `cache`/<key>/, reused when nothing changed. `base`: the default theme's
    theme.json (the colours a theme leaves out)."""
    from . import off, panel, web

    key = hashlib.sha256(f"{found.id}:{found.stamp}:{packager_stamp()}:{json.dumps(base.get('colors', {}), sort_keys=True)}".encode()).hexdigest()[:24]
    done = cache / key
    meta_file = done / "meta.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            return Built(
                found.id,
                found.path.name,
                doc=meta["doc"],
                colours=meta["colours"],
                off_art=meta["off_art"],
                button_art=meta["button_art"],
                version=meta["version"],
                packs={"": (done / "theme.rtp").read_bytes(), "-round": (done / "theme-round.rtp").read_bytes()},
                web=done / "web",
                coarse=meta.get("coarse", False),
            )
        except (OSError, ValueError, KeyError):
            shutil.rmtree(done, ignore_errors=True)  # (a broken cache entry: build again)
    work = cache / f".{key}.tmp"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        # a copy to work on: a zip unpacked, or the folder copied (generated
        # "off" pictures go into it, never into the user's folder)
        if found.zipped:
            folder = _unzip(found.path, work / "src")
        else:
            folder = work / "src" / found.id
            shutil.copytree(found.path, folder)
        doc = fmt.read(folder, f"{found.path.name}/theme.json")
        problems = fmt.check_pictures(folder)
        for extra in sorted(p.name for p in folder.iterdir() if p.is_file()):
            if extra.lower().endswith((".json",)) and extra not in fmt.ALLOWED_FILES:
                problems.append(f"{found.id}/{extra}: not a theme file (theme.json, clock.json)")
        if problems:
            raise fmt.ThemeError(problems)
        colours = fmt.colours(doc, base)
        missing = sorted(set(base.get("colors", {})) - set(colours))
        if missing:
            raise fmt.ThemeError(f"{found.id}: colors missing {', '.join(missing)}")
        if doc.get("off") == "gray":
            ui = folder / "ui"
            ui.mkdir(exist_ok=True)
            src0 = panel.Source(found.id, folder, colours)
            for icon in off.TOKEN:
                if not (ui / f"{icon}_off.png").exists():
                    img = fmt.at_size(
                        panel._open(panel.art(src0, "ui", f"{icon}.png")),
                        panel._master_size("ui", f"{icon}.png"),
                    )
                    off.off_picture(img, panel.OFF_BRIGHTNESS.get(icon, 0.8), off.colour_of(colours, icon)).save(ui / f"{icon}_off.png")
        src = panel.Source(found.id, folder, colours, fmt.clock(folder, colours))
        images = panel.panel_images(src)
        ident = f"user-{hashlib.sha1(found.id.encode()).hexdigest()[:6]}"
        wall, _ = panel.build_theme(src, ident, images)
        rnd, _ = panel.build_theme(src, f"{ident}-round", images, round_panel=True)
        if len(wall) > panel.THEME_MAX:
            raise fmt.ThemeError(f"{found.id}: {len(wall) / 1048576:.1f} MB for the panels - they hold {panel.THEME_MAX / 1048576:.1f} MB")
        if len(rnd) > panel.THEME_MAX_ROUND:
            raise fmt.ThemeError(f"{found.id}: {len(rnd) / 1048576:.1f} MB for the round panel - it holds {panel.THEME_MAX_ROUND / 1048576:.1f} MB")
        web.build_appliances(src, work / "web" / "appliances")
        web.build_ui(src, work / "web" / "ui")
        off_art, button_art = _art_lists(folder / "ui")
        version = hashlib.sha256(wall).hexdigest()[:12]
        (work / "theme.rtp").write_bytes(wall)
        (work / "theme-round.rtp").write_bytes(rnd)
        meta = {
            "doc": doc,
            "colours": colours,
            "off_art": off_art,
            "button_art": button_art,
            "version": version,
            "coarse": not panel.HAS_LIQ,
        }
        (work / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        shutil.rmtree(work / "src", ignore_errors=True)
        shutil.rmtree(done, ignore_errors=True)
        work.rename(done)
    except fmt.ThemeError as err:
        shutil.rmtree(work, ignore_errors=True)
        return Built(found.id, found.path.name, problems=err.problems)
    except Exception as err:  # noqa: BLE001 - a theme's file can break the build any way; say so, never crash
        shutil.rmtree(work, ignore_errors=True)
        return Built(found.id, found.path.name, problems=[f"{found.path.name}: couldn't be built ({type(err).__name__}: {err})"])
    return build(found, base, cache)  # (read back from the cache: one way in)


def prune(cache: Path, keep: set[str]) -> None:
    """Drop cached builds no theme uses any more (`keep`: their folders' names)."""
    if not cache.is_dir():
        return
    for entry in cache.iterdir():
        if entry.is_dir() and entry.name not in keep:
            shutil.rmtree(entry, ignore_errors=True)
