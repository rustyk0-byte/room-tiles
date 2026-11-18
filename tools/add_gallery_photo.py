#!/usr/bin/env python3
"""Add a photo to the gallery, "Room Tiles in the wild" (tools/site/gallery/):

    tools/add_gallery_photo.py <photo> --caption "..." --by "..." [--link <url>] [--turn 90|180|270]

The photo is turned upright, made web-sized (1800 px on its long side at
most) and saved as a JPEG with NOTHING else from the original - no camera
details and no location (phones put where a photo was taken in it). It goes
first in photos.json: --caption (a few words), --by (who sent it, as they'd
like to be named), --link (their Show and tell post, optional). --turn: degrees clockwise, for
a photo that comes in sideways without saying so.
Needs Pillow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageOps

GALLERY = Path(__file__).resolve().parent / "site" / "gallery"
LONG_SIDE = 1800


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("photo", type=Path)
    ap.add_argument("--caption", required=True)
    ap.add_argument("--by", required=True)
    ap.add_argument("--link")
    ap.add_argument("--turn", type=int, choices=(90, 180, 270))
    a = ap.parse_args()
    with Image.open(a.photo) as im:
        im = ImageOps.exif_transpose(im)  # (upright, as the camera held it)
        im = im.convert("RGB")
        if a.turn:
            im = im.rotate(-a.turn, expand=True)  # (PIL turns counter-clockwise)
        im.thumbnail((LONG_SIDE, LONG_SIDE), Image.Resampling.LANCZOS)
        # a fresh image: only the pixels - no EXIF, GPS or other metadata
        clean = Image.new("RGB", im.size)
        clean.paste(im)
    slug = re.sub(r"[^a-z0-9]+", "-", a.caption.lower()).strip("-")[:40] or "photo"
    digest = hashlib.sha256(clean.tobytes()).hexdigest()[:8]
    (GALLERY / "photos").mkdir(parents=True, exist_ok=True)
    name = f"photos/{slug}-{digest}.jpg"
    clean.save(GALLERY / name, "JPEG", quality=85, optimize=True, progressive=True)
    listed = json.loads((GALLERY / "photos.json").read_text(encoding="utf-8"))
    entry = {"file": name, "caption": a.caption, "by": a.by, "width": clean.width, "height": clean.height}
    if a.link:
        entry["link"] = a.link
    listed.insert(0, entry)
    (GALLERY / "photos.json").write_text(json.dumps(listed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"added {name} ({clean.width} x {clean.height}, {(GALLERY / name).stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
