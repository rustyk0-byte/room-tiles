#!/usr/bin/env python3
"""Convert LVGL 9 I8 C image arrays (256-colour palette + indices) into PNG.

One-off import of the original panel art into assets/masters/. Standard
library only. Drops the magenta cut-out key some originals still carry
(see make_appliance_sprites.py in the old panel repo).

  python3 lvgl_to_png.py SRC.c OUT.png
"""

import re
import struct
import sys
import zlib


def read_lvgl_i8(path: str) -> tuple[int, int, bytes]:
    text = open(path, encoding="utf-8").read()
    w = int(re.search(r"\.w = (\d+)", text).group(1))
    h = int(re.search(r"\.h = (\d+)", text).group(1))
    assert "LV_COLOR_FORMAT_I8" in text, path
    body = text[text.index("_map[] = {"):text.index("};")]
    data = bytes(int(b, 16) for b in re.findall(r"0x([0-9a-fA-F]{2})", body))
    assert len(data) == 1024 + w * h, (path, len(data), w, h)
    pal = []
    for i in range(256):
        b, g, r, a = data[i * 4:i * 4 + 4]
        if r > 90 and b > 90 and g < 60 and abs(r - b) < 50:  # magenta key
            r = g = b = a = 0
        pal.append(bytes((r, g, b, a)))
    rows = bytearray()
    idx = data[1024:]
    for y in range(h):
        rows.append(0)  # PNG filter: none
        for i in idx[y * w:(y + 1) * w]:
            rows += pal[i]
    return w, h, bytes(rows)


def write_png(path: str, w: int, h: int, raw: bytes) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))  # 8-bit RGBA
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    open(path, "wb").write(png)


if __name__ == "__main__":
    w, h, raw = read_lvgl_i8(sys.argv[1])
    write_png(sys.argv[2], w, h, raw)
    print(f"{sys.argv[2]}: {w}x{h}")
