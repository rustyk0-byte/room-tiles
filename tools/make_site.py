#!/usr/bin/env python3
"""Build the GitHub Pages site:

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
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def version_files(page: Path) -> None:
    """Each file the page names (pictures - also in their fallbacks - and the
    stylesheet) asked for by name + version (its contents' hash): a changed
    file is a new address. A web host may tell browsers to keep files - and
    "not found" - for weeks (Home Assistant's /local: 31 days)."""
    folder = page.parent

    def stamp(m: re.Match) -> str:
        f = (folder / m.group(1)).resolve()
        if not f.is_file():
            return m.group(0)  # (not there: the page's fallback takes over)
        return f"{m.group(1)}?v={hashlib.sha256(f.read_bytes()).hexdigest()[:10]}"

    text = page.read_text(encoding="utf-8")
    ref = r"((?:\.\./)?(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_.-]+\.(?:png|jpg|webp|css))(?=[\"'])"
    page.write_text(re.sub(ref, stamp, text), encoding="utf-8")


def _photo(p: dict, prefix: str) -> str:
    """One gallery photo: the picture, its caption and who sent it (a link
    to their post, when there is one)."""
    cap, by = html.escape(p["caption"]), html.escape(p["by"])
    size = f' width="{p["width"]}" height="{p["height"]}"' if p.get("width") else ""
    body = (
        f'<img src="{prefix}{html.escape(p["file"])}" alt="{cap}" loading="lazy"{size} />'
        f"<figcaption><b>{cap}</b><span>{by}</span></figcaption>"
    )
    if p.get("link"):
        body = f'<a href="{html.escape(p["link"])}">{body}</a>'
    return f'<figure class="photo">{body}</figure>'


def fill_gallery(out: Path) -> None:
    """The gallery's photos (gallery/photos.json) on its page - and the first
    few on the landing page ("Room Tiles in the wild"; none: no section)."""
    photos = json.loads((out / "gallery" / "photos.json").read_text(encoding="utf-8"))
    page = out / "gallery" / "index.html"
    grid = (
        '<div class="photos">' + "".join(_photo(p, "") for p in photos) + "</div>"
        if photos
        else '<p class="sub">No photos yet - be the first to show off yours.</p>'
    )
    page.write_text(page.read_text(encoding="utf-8").replace("<!-- PHOTOS -->", grid), encoding="utf-8")
    landing = out / "index.html"
    teaser = ""
    if photos:
        teaser = f"""<section id="wild">
        <div class="wrap">
          <h2>Room Tiles in the wild</h2>
          <p class="sub">Panels, tablets and phones in real homes.</p>
          <div class="photos">{"".join(_photo(p, "gallery/") for p in photos[:TEASER])}</div>
          <div class="buttons" style="margin-top: 28px">
            <a class="button primary" href="gallery/index.html">See more</a>
            <a class="button" href="https://github.com/rustyk0-byte/room-tiles/discussions/new?category=show-and-tell">Show off yours</a>
          </div>
        </div>
      </section>"""
    landing.write_text(landing.read_text(encoding="utf-8").replace("<!-- WILD -->", teaser), encoding="utf-8")


TEASER = 3  # photos on the landing page


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
    fill_gallery(out)
    for page in (out / "index.html", out / "gallery" / "index.html"):
        version_files(page)
    subprocess.run(["node", "build-demo.mjs", str(a.demo_data.resolve()), str((out / "demo").resolve())], cwd=ROOT / "frontend", check=True)
    if a.images:
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_install_site.py"), str(a.images), str(out / "install")], check=True)
    print(f"site -> {out}" + ("" if a.images else " (no install page: no --images)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
