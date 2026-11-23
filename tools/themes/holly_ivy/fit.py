"""The 4x renders (render.mjs) at the sizes a built-in theme ships
(docs/THEMES.md): icons 60, the run button 60 / 41, the Map tile 76x58 /
52x40, knobs 30 / 40, padlocks 76x84; top-bar art and the clock as drawn.

  python3 tools/themes/holly_ivy/fit.py <png dir> assets/themes/holly_ivy/ui

Animation frames (anim.py: <name>__NN.png) become 8 x 4 sheets of 196 px
frames in the theme's appliances/ folder, beside ui/; so do the stills
(shirt_socks, plate_knife_fork: 196 px).
"""
import sys
from pathlib import Path

from PIL import Image

SIZES = {"run_gift": (60, 60), "run_gift_s": (41, 41), "tile_map": (76, 58), "tile_map_s": (52, 40),
         "knob_switch": (30, 30), "track_switch_open_green": (100, 32), "track_switch_closed": (100, 32),
         "track_switch_locked_purple": (120, 32), "track_switch_unlocked": (120, 32), "knob_grip_v": (40, 40), "lock_padlock_closed": (76, 84), "lock_padlock_open": (76, 84)}

STILLS = ("shirt_socks", "plate_knife_fork")

src, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
frames: dict[str, list[Path]] = {}
for f in sorted(src.glob("*.png")):
    name = f.stem
    if "__" in name:
        frames.setdefault(name.split("__")[0], []).append(f)
        continue
    size = SIZES.get(name) or ((60, 60) if name.startswith("icon_") and name != "icon_settings"
                               else (75, 32) if name.startswith("track_switch") else None)
    im = Image.open(f).convert("RGBA")
    if name in STILLS:
        (out.parent / "appliances").mkdir(exist_ok=True)
        im.resize((196, 196), Image.LANCZOS).save(out.parent / "appliances" / f.name, optimize=True)
        print(f"{name}: 196x196")
        continue
    if size and im.size != size:
        im = im.resize(size, Image.LANCZOS)
    im.save(out / f.name, optimize=True)
    print(f"{name}: {im.size[0]}x{im.size[1]}")

FR, COLS, ROWS = 196, 8, 4
for name, fs in frames.items():
    assert len(fs) == COLS * ROWS, (name, len(fs))
    sheet = Image.new("RGBA", (FR * COLS, FR * ROWS), (0, 0, 0, 0))
    for i, f in enumerate(fs):
        sheet.paste(Image.open(f).convert("RGBA").resize((FR, FR), Image.LANCZOS), ((i % COLS) * FR, (i // COLS) * FR))
    (out.parent / "appliances").mkdir(exist_ok=True)
    sheet.save(out.parent / "appliances" / f"{name}.png", optimize=True)
    print(f"{name}: {COLS * ROWS} frames")
