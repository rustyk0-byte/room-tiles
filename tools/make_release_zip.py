#!/usr/bin/env python3
"""Build the HACS release zip (hacs.json `zip_release`): the integration
with its dashboard bundle and every board's panel firmware, so one HACS
install / update brings the panels' firmware with it (firmware.py reads
`firmware_images/`; "Update panels automatically" installs it).

    tools/make_release_zip.py <images dir> <frontend dir> <tag> <out.zip>

- images: CI's `room-tiles-<board>.ota.bin` (.github/workflows/firmware.yml);
  each must be a generic image for its own board, in this Room Tiles' panel
  format (PANEL_SCHEMA) - anything else stops the release.
- frontend: the built dashboard (frontend.yml: room-tiles-panel.js + the
  themes' art).
- tag: the release's tag (v1.2.3) - manifest.json's version.

HACS unpacks the zip into custom_components/room_tiles/.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "room_tiles"
SIGNING_H = ROOT / "firmware" / "components" / "room_tiles" / "signing.h"
SKIP_DIRS = {"__pycache__", "frontend", "firmware_images"}  # (the last two: added from the build)


def _firmware():
    """custom_components/room_tiles/firmware.py (standard library only)."""
    spec = importlib.util.spec_from_file_location("rt_firmware", COMPONENT / "firmware.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rt_firmware"] = mod  # (dataclasses look it up)
    spec.loader.exec_module(mod)
    return mod


def panel_schema() -> int:
    m = re.search(r"PANEL_SCHEMA\s*=\s*(\d+)", SIGNING_H.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("PANEL_SCHEMA not found in signing.h")
    return int(m.group(1))


def check_images(images: Path, schema: int) -> list[Path]:
    fw = _firmware()
    files = sorted(images.glob("room-tiles-*.ota.bin"))
    if not files:
        raise SystemExit(f"no room-tiles-*.ota.bin in {images}")
    for f in files:
        img = fw.read_image(f)
        if img is None or not img.generic:
            raise SystemExit(f"{f.name}: not a generic Room Tiles image")
        if img.schema != schema:
            raise SystemExit(f"{f.name}: panel format {img.schema}, this Room Tiles speaks {schema}")
        if f.name != fw.file_name(img.board):
            raise SystemExit(f"{f.name}: holds the image for {img.board}")
        print(f"  {f.name}  {img.label}  {f.stat().st_size // 1024} KB")
    return files


def main() -> int:
    if len(sys.argv) != 5:
        print(__doc__)
        return 2
    images, frontend, tag, out = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
    version = tag[1:] if tag.startswith("v") else tag
    if not re.fullmatch(r"\d+\.\d+\.\d+([.-]?[0-9A-Za-z.]+)?", version):
        raise SystemExit(f"tag {tag!r} isn't a version (v1.2.3)")
    if not (frontend / "room-tiles-panel.js").is_file():
        raise SystemExit(f"no dashboard bundle (room-tiles-panel.js) in {frontend}")
    print("Panel firmware:")
    files = check_images(images, panel_schema())

    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    manifest["version"] = version
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(COMPONENT.rglob("*")):
            rel = f.relative_to(COMPONENT)
            if not f.is_file() or SKIP_DIRS & set(rel.parts[:-1]) or f.suffix == ".pyc":
                continue
            if rel.as_posix() == "manifest.json":
                z.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
            else:
                z.write(f, rel.as_posix())
        for f in sorted(frontend.rglob("*")):
            if f.is_file():
                z.write(f, "frontend/" + f.relative_to(frontend).as_posix())
        for f in files:
            z.write(f, "firmware_images/" + f.name)
        # (the license travels with every copy - Apache-2.0 section 4)
        for name in ("LICENSE", "NOTICE"):
            z.write(ROOT / name, name)
    print(f"{out}: {out.stat().st_size / 1e6:.1f} MB, version {version}, {len(files)} panel images")
    return 0


if __name__ == "__main__":
    sys.exit(main())
