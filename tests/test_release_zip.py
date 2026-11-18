"""The HACS release zip (tools/make_release_zip.py): the integration, its
dashboard and every board's panel firmware - and nothing that isn't a
generic image in this Room Tiles' panel format for its own board."""

import json
import subprocess
import sys
import zipfile
from pathlib import Path

from test_firmware import SCHEMA, _image

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "make_release_zip.py"


def _run(images, dashboard, out, tag="v1.4.0"):
    return subprocess.run([sys.executable, str(TOOL), str(images), str(dashboard), tag, str(out)], capture_output=True, text=True)


def _dashboard(tmp_path):
    d = tmp_path / "dashboard"
    (d / "dark").mkdir(parents=True)
    (d / "room-tiles-panel.js").write_text("// bundle")
    (d / "dark" / "art.png").write_bytes(b"png")
    return d


def test_the_zip_carries_the_dashboard_and_firmware(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    for board in ("elecrow-p4-7in-v1.2-es", "elecrow-p4-7in-v1.2"):
        (images / f"room-tiles-{board}.ota.bin").write_bytes(_image(board=board))
    (images / "room-tiles-elecrow-p4-7in-v1.2.factory.bin").write_bytes(b"not in the zip")
    out = tmp_path / "room_tiles.zip"
    r = _run(images, _dashboard(tmp_path), out)
    assert r.returncode == 0, r.stdout + r.stderr
    names = set(zipfile.ZipFile(out).namelist())
    assert {"__init__.py", "manifest.json", "firmware.py", "LICENSE", "NOTICE", "frontend/room-tiles-panel.js", "frontend/dark/art.png",
            "firmware_images/room-tiles-elecrow-p4-7in-v1.2-es.ota.bin",
            "firmware_images/room-tiles-elecrow-p4-7in-v1.2.ota.bin"} <= names
    assert not any("__pycache__" in n or n.endswith((".pyc", ".factory.bin")) for n in names)
    assert json.loads(zipfile.ZipFile(out).read("manifest.json"))["version"] == "1.4.0"


def test_a_wrong_image_stops_the_release(tmp_path):
    dashboard = _dashboard(tmp_path)
    for name, data in [
        ("room-tiles-elecrow-p4-7in-v1.2.ota.bin", _image(board="elecrow-p4-7in-v1.2", schema=SCHEMA - 1)),  # old format
        ("room-tiles-elecrow-p4-7in-v1.2.ota.bin", _image(board="elecrow-p4-7in-v1.0")),  # another board's
        ("room-tiles-elecrow-p4-7in-v1.2.ota.bin", _image(board="elecrow-p4-7in-v1.2", kind="own")),  # hand-built
    ]:
        images = tmp_path / "images"
        images.mkdir(exist_ok=True)
        for f in images.iterdir():
            f.unlink()
        (images / name).write_bytes(data)
        assert _run(images, dashboard, tmp_path / "x.zip").returncode != 0
    # no dashboard, no version
    images = tmp_path / "ok"
    images.mkdir()
    (images / "room-tiles-elecrow-p4-7in-v1.2.ota.bin").write_bytes(_image(board="elecrow-p4-7in-v1.2"))
    assert _run(images, tmp_path / "nothing", tmp_path / "x.zip").returncode != 0
    assert _run(images, dashboard, tmp_path / "x.zip", tag="latest").returncode != 0
