#!/usr/bin/env python3
"""Make the black background around a picture transparent (on/off alpha).

Flood-fills from the image border through near-black pixels (all channels
<= THRESHOLD) and sets them fully transparent; black inside the picture (not
connected to the border) is kept. Standard library only.

  python3 clear_border_black.py IMAGE.png [THRESHOLD]
"""

import struct
import sys
import zlib
from collections import deque


def read_rgba(path):
    b = open(path, "rb").read()
    w, h, depth, ctype = struct.unpack(">IIBB", b[16:26])
    assert depth == 8 and ctype == 6, "needs 8-bit RGBA"
    idat = b""
    i = 8
    while i < len(b):
        n = struct.unpack(">I", b[i:i + 4])[0]
        if b[i + 4:i + 8] == b"IDAT":
            idat += b[i + 8:i + 8 + n]
        i += 12 + n
    raw = zlib.decompress(idat)
    stride = w * 4
    rows, prev, pos = [], bytearray(stride), 0
    for _ in range(h):
        ft = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        for x in range(stride):
            a = line[x - 4] if x >= 4 else 0
            up = prev[x]
            c = prev[x - 4] if x >= 4 else 0
            if ft == 1:
                line[x] = (line[x] + a) & 255
            elif ft == 2:
                line[x] = (line[x] + up) & 255
            elif ft == 3:
                line[x] = (line[x] + (a + up) // 2) & 255
            elif ft == 4:
                p = a + up - c
                pa, pb, pc = abs(p - a), abs(p - up), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else up if pb <= pc else c)) & 255
        rows.append(line)
        prev = line
    return w, h, rows


def write_rgba(path, w, h, rows):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    open(path, "wb").write(png)


def main():
    path = sys.argv[1]
    thr = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    w, h, rows = read_rgba(path)
    dark = lambda x, y: max(rows[y][x * 4:x * 4 + 3]) <= thr and rows[y][x * 4 + 3] > 0
    seen = set()
    q = deque((x, y) for x in range(w) for y in (0, h - 1)) + deque((x, y) for y in range(h) for x in (0, w - 1))
    cleared = 0
    while q:
        x, y = q.popleft()
        if (x, y) in seen or not (0 <= x < w and 0 <= y < h) or not dark(x, y):
            continue
        seen.add((x, y))
        rows[y][x * 4:x * 4 + 4] = b"\x00\x00\x00\x00"
        cleared += 1
        q.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    write_rgba(path, w, h, rows)
    print(f"{path}: {cleared} of {w * h} pixels made transparent")


if __name__ == "__main__":
    main()
