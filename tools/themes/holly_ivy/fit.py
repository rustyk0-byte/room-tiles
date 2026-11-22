"""The 4x renders (render.mjs) at the sizes a built-in theme ships
(docs/THEMES.md): icons 60, the run button 60 / 41, the Map tile 76x58 /
52x40, knobs 30 / 40, padlocks 76x84; top-bar art and the clock as drawn.

  python3 tools/themes/holly_ivy/fit.py <png dir> assets/themes/holly_ivy/ui
"""
import sys
from pathlib import Path

from PIL import Image

SIZES = {"run_gift": (60, 60), "run_gift_s": (41, 41), "tile_map": (76, 58), "tile_map_s": (52, 40),
         "knob_switch": (30, 30), "knob_grip_v": (40, 40), "lock_padlock_closed": (76, 84), "lock_padlock_open": (76, 84)}

src, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
for f in sorted(src.glob("*.png")):
    name = f.stem
    size = SIZES.get(name) or ((60, 60) if name.startswith("icon_") and name != "icon_settings" else None)
    im = Image.open(f).convert("RGBA")
    if size and im.size != size:
        im = im.resize(size, Image.LANCZOS)
    im.save(out / f.name, optimize=True)
    print(f"{name}: {im.size[0]}x{im.size[1]}")
