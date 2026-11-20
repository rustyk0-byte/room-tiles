"""A panel's screenshot: RGB565 in, a PNG out, the last few kept."""

import struct
import zlib

import pytest

from custom_components.room_tiles import screenshots


def _pixels(png: bytes) -> bytes:
    """The PNG's raw rows (filter byte + RGB), from its IDAT chunks."""
    pos, data = 8, b""
    while pos < len(png):
        (n,) = struct.unpack(">I", png[pos : pos + 4])
        kind = png[pos + 4 : pos + 8]
        if kind == b"IDAT":
            data += png[pos + 8 : pos + 8 + n]
        pos += 12 + n
    return zlib.decompress(data)


def test_colors_come_out_right():
    # 2 x 1: pure red, pure blue (little-endian RGB565)
    png = screenshots.rgb565_to_png(struct.pack("<HH", 0xF800, 0x001F), 2, 1)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert _pixels(png) == b"\x00" + bytes([255, 0, 0, 0, 0, 255])


def test_a_wrong_size_is_refused():
    with pytest.raises(ValueError):
        screenshots.rgb565_to_png(b"\x00" * 6, 2, 2)


def test_the_last_few_are_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(screenshots, "KEEP", 2)
    for t in (1_700_000_000, 1_700_000_100, 1_700_000_200):
        screenshots.save(str(tmp_path), "kitchen-panel", b"\x00\x00", 1, 1, now=t)
    screenshots.save(str(tmp_path), "other", b"\x00\x00", 1, 1, now=1_700_000_000)
    names = sorted(p.name for p in (tmp_path / "room_tiles").iterdir())
    assert len([n for n in names if n.startswith("kitchen-panel-")]) == 2
    assert len([n for n in names if n.startswith("other-")]) == 1


def test_a_panel_keeps_only_its_own_screenshots_trimmed(tmp_path):
    """Another panel whose name starts the same keeps its pictures."""
    from custom_components.room_tiles.screenshots import FOLDER, KEEP, save

    w, h = 2, 2
    data = bytes(w * h * 2)
    for i in range(KEEP + 2):
        save(str(tmp_path), "kitchen-2", data, w, h, now=1_700_000_000 + i)
    for i in range(KEEP + 2):
        save(str(tmp_path), "kitchen", data, w, h, now=1_700_100_000 + i)
    names = [p.name for p in (tmp_path / FOLDER).iterdir()]
    assert sum(n.startswith("kitchen-2-") for n in names) == KEEP
    assert sum(not n.startswith("kitchen-2-") for n in names) == KEEP
