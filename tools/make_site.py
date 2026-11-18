#!/usr/bin/env python3
"""Build the GitHub Pages site (docs/TODO.md "Landing page + browser demo"):

    <out>/            the landing page (tools/site/)
    <out>/demo/       the browser demo (frontend/build-demo.mjs)
    <out>/install/    the firmware install page (tools/make_install_site.py)

    tools/make_site.py <out> --demo-data <dir> [--images <dir>]

--demo-data: what tools/demo/make_demo.py wrote. --images: CI's panel
images (room-tiles-<board>.factory.bin); without them there's no install
page (a local preview). The dashboard's theme pictures must be built
first (assets/build_web.py: tools/build-frontend.sh does it).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def version_pictures(page: Path) -> None:
    """Each picture the page names (img/x.png - also in its fallbacks) asked
    for by name + version (its contents' hash): a changed picture is a new
    address. A web host may tell browsers to keep files - and "not found" -
    for weeks (Home Assistant's /local: 31 days)."""
    folder = page.parent

    def stamp(m: re.Match) -> str:
        f = folder / m.group(1)
        if not f.is_file():
            return m.group(0)  # (not there: the page's fallback takes over)
        return f"{m.group(1)}?v={hashlib.sha256(f.read_bytes()).hexdigest()[:10]}"

    text = page.read_text(encoding="utf-8")
    page.write_text(re.sub(r"(img/[A-Za-z0-9_.-]+\.(?:png|jpg|webp))(?=[\"'])", stamp, text), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--demo-data", type=Path, required=True)
    ap.add_argument("--images", type=Path)
    a = ap.parse_args()
    out: Path = a.out
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "tools" / "site", out)
    shutil.copy2(ROOT / "custom_components" / "room_tiles" / "brand" / "icon.png", out / "icon.png")
    (out / ".nojekyll").write_text("")
    version_pictures(out / "index.html")
    subprocess.run(["node", "build-demo.mjs", str(a.demo_data.resolve()), str((out / "demo").resolve())], cwd=ROOT / "frontend", check=True)
    if a.images:
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_install_site.py"), str(a.images), str(out / "install")], check=True)
    print(f"site -> {out}" + ("" if a.images else " (no install page: no --images)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
