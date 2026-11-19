"""A theme's pictures for the dashboard (docs/DESIGN.md "One packager, two
outputs"): <out>/appliances/<name>.webp (the animations as sprite sheets,
frames at 2x their CSS size) and <out>/ui/<name>.png. The same code builds
the themes that come with Room Tiles (assets/build_web.py, at our build)
and the ones a user installs (installed.py, in Home Assistant). The
dashboard only ever loads this output, never a theme folder's raw files.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from . import fmt
from .panel import Source, _master_size, art

MASTERS = fmt.MASTERS
COLS, ROWS = 8, 4  # sprite sheet layout (frontend/src/appliance.ts must match)
FRAME_CSS = 96  # largest size a frame is shown at in the dashboard, CSS px
FRAME_OUT = FRAME_CSS * 2  # pixels per frame: sharp on 2x screens


def _pixels(img: Image.Image):
    return img.get_flattened_data() if hasattr(img, "get_flattened_data") else img.getdata()


def shrink(img: Image.Image, size: tuple[int, int]) -> tuple[Image.Image, list[bool]]:
    """Resize (premultiplied: no dark halos), then snap alpha back to fully
    transparent / fully opaque - the artwork uses on/off alpha only, never
    blending (same as the panels)."""
    small = img.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA")
    mask = [a >= 128 for a in small.getchannel("A").tobytes()]
    # back to one 256-colour palette like the 8-bit masters: lossless WebP
    # then stores palette indices (small files). The palette is built from
    # the COLOURS only and the on/off alpha is put back from `mask`:
    # quantizing RGBA directly can merge "transparent" with a dark opaque
    # colour (an opaque dark square under the washer's bubbles).
    rgb = small.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT).convert("RGB")
    out = Image.new("RGBA", size)
    out.putdata([(r, g, b, 255) if m else (0, 0, 0, 0) for (r, g, b), m in zip(_pixels(rgb), mask)])
    return out, mask


def build_appliances(src: Source, out: Path) -> list[str]:
    """The animations; returns a line per file (for the build's log)."""
    out.mkdir(parents=True, exist_ok=True)
    log = []
    for master in sorted((MASTERS / "appliances").glob("*.png")):
        file = art(src, "appliances", master.name)
        img = fmt.at_size(Image.open(file).convert("RGBA"), _master_size("appliances", master.name))
        w, h = img.size
        sheet = (w, h) != (h, h) and w == 2 * h  # 8x4 of square frames
        size = (FRAME_OUT * COLS, FRAME_OUT * ROWS) if sheet else (FRAME_OUT, FRAME_OUT)
        dst = out / f"{master.stem}.webp"
        # lossless: compression must not soften the on/off alpha
        small, mask = shrink(img, size)
        small.save(dst, "WEBP", lossless=True, method=6)
        back = Image.open(dst).convert("RGBA")
        # the written file must have exactly the master's transparency
        got = [a >= 128 for a in back.getchannel("A").tobytes()]
        if got != mask:
            raise fmt.ThemeError(f"{dst}: transparency changed in the build ({sum(g != m for g, m in zip(got, mask))} pixels)")
        colours = len(back.getcolors(1 << 20) or [])
        clear = 100 * mask.count(False) // len(mask)
        log.append(f"{dst}: {size[0]}x{size[1]} {dst.stat().st_size // 1024} KB, {colours} colours, {clear}% transparent")
    return log


def build_ui(src: Source, out: Path) -> list[str]:
    """The ui pictures: the default art with the theme's own over it, and
    what only the theme has ("off" pictures, bar_*). Pictures drawn at 2x /
    4x come down to their size; the top bar's are each fitted into one box
    (fmt.BAR_ART)."""
    out.mkdir(parents=True, exist_ok=True)
    for master in sorted((MASTERS / "ui").glob("*.png")):
        _copy(art(src, "ui", master.name), out / master.name, _master_size("ui", master.name))
    own = src.folder / "ui" if src.folder is not None else None
    for file in sorted(own.glob("*.png")) if own is not None and own.exists() else []:
        if (MASTERS / "ui" / file.name).exists():
            continue  # (above)
        size = fmt.OWN_SIZES.get(file.stem)
        if file.stem.endswith("_off") and (MASTERS / "ui" / f"{file.stem[: -len('_off')]}.png").exists():
            size = _master_size("ui", f"{file.stem[: -len('_off')]}.png")
        _copy(file, out / file.name, size)
    # the top bar's pictures: each fitted into the one box
    originals = {pic: Image.open(out / f"{pic}.png").copy() for pic in fmt.BAR_ART if (out / f"{pic}.png").exists()}
    for pic, img in originals.items():
        pair = originals.get(fmt.BAR_PAIRS.get(pic, ""))
        fmt.fit_bar_art(img, fmt.BAR_BOX_WEB, pair).save(out / f"{pic}.png", optimize=True)
    return [f"{out}: {len(list(out.glob('*.png')))} images"]


def _copy(file: Path, dst: Path, size: tuple[int, int] | None) -> None:
    """A picture as it is - or, drawn larger (2x / 4x), brought to its size."""
    if size is not None:
        with Image.open(file) as img:
            if img.size != size:
                fmt.at_size(img.convert("RGBA"), size).save(dst, optimize=True)
                return
    dst.write_bytes(file.read_bytes())
