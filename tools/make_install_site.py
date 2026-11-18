#!/usr/bin/env python3
"""Build the install page's site (docs/TODO.md phase C) from CI's panel
images: install/ (the page) + firmware/ (each board's factory image) +
manifests/<panel>.json (ESP Web Tools) + boards.json (the page's list).

    tools/make_install_site.py <images dir> <out dir>

Images are named room-tiles-<board>.factory.bin (.github/workflows/
firmware.yml). Boards are grouped by what's PRINTED on them (size + PCB
version): an engineering-sample build (`-es`, chips below v3.0) and a
production one become one panel with two builds - ESP Web Tools (the
tasmota-esp-web-tools fork) picks by the chip it finds ("rev0" / "rev300").
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "install"


def panel_of(board: str) -> tuple[str, dict] | None:
    """(panel id, what the page shows) for a board id - None if unknown."""
    m = re.fullmatch(r"elecrow-p4-(\d+)in-v([\d.]+)(-es)?", board)
    if m:
        size = "10.1" if m.group(1) == "10" else m.group(1)
        return f"{m.group(1)}in-v{m.group(2)}", {"size": size, "pcb": m.group(2), "chip": "ESP32-P4", "round": False}
    m = re.fullmatch(r"elecrow-s3-round-([\d.]+)", board)
    if m:
        return f"round-{m.group(1)}", {"size": m.group(1), "pcb": None, "chip": "ESP32-S3", "round": True}
    return None


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    images, out = Path(sys.argv[1]), Path(sys.argv[2])
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(PAGE, out)
    shutil.copy2(PAGE.parent / "custom_components" / "room_tiles" / "brand" / "icon.png", out / "icon.png")
    (out / "firmware").mkdir()
    (out / "manifests").mkdir()
    panels: dict[str, dict] = {}
    for f in sorted(images.glob("room-tiles-*.factory.bin")):
        board = f.name[len("room-tiles-") : -len(".factory.bin")]
        found = panel_of(board)
        if found is None:
            print(f"skipped (unknown board): {f.name}")
            continue
        pid, info = found
        shutil.copy2(f, out / "firmware" / f.name)
        p = panels.setdefault(pid, {"id": pid, **info, "builds": []})
        build = {"chipFamily": info["chip"], "improv": True, "parts": [{"path": f"../firmware/{f.name}", "offset": 0}]}
        if info["chip"] == "ESP32-P4":
            build["chipVariant"] = "rev0" if board.endswith("-es") else "rev300"
        p["builds"].append(build)
    for pid, p in panels.items():
        manifest = {"name": "Room Tiles", "new_install_prompt_erase": True, "builds": p.pop("builds")}
        (out / "manifests" / f"{pid}.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    order = sorted(panels.values(), key=lambda p: (p["round"], float(p["size"]), p["pcb"] or ""))
    (out / "boards.json").write_text(json.dumps(order, indent=2) + "\n", encoding="utf-8")
    print(f"{len(panels)} panels -> {out}")
    return 0 if panels else 1


if __name__ == "__main__":
    sys.exit(main())
