"""Draw masters/ui/icon_robot_vacuum.png: the generic robot vacuum (any brand
that isn't Matic) - a round robot seen from above: front bumper, sensor dome,
button. 60 x 60, the same flat style and colours as the other map / tile icons
(body and outline from icon_matic, the accent blue from icon_fan).

Pure Python (no Pillow): 4 x 4 supersampling; build_web.py snaps alpha to
on/off like every master. Re-run to regenerate:
    python3 assets/tools/make_robot_vacuum_icon.py
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

SIZE = 60
SS = 4
BODY = (0xF0, 0xF2, 0xF5)
LINE = (0x26, 0x2A, 0x32)
BUMPER = (0xCD, 0xD2, 0xD8)
BLUE = (0x4B, 0xC9, 0xF3)

CX = CY = 30.0
R = 27.5  # body
W = 2.4  # outline


def color_at(x: float, y: float) -> tuple[int, int, int] | None:
    """The colour of the point (x, y), top layer first; None = transparent."""
    dx, dy = x - CX, y - CY
    d = math.hypot(dx, dy)
    if d > R:
        return None
    if d > R - W:
        return LINE
    # the button: blue with a dark ring
    bd = math.hypot(x - CX, y - 41.5)
    if bd <= 4.6:
        return BLUE if bd <= 3.2 else LINE
    # the sensor dome: dark, with a light ring
    td = math.hypot(x - CX, y - 22.5)
    if td <= 7.2:
        return LINE if td <= 5.4 or td > 6.4 else BODY
    # the front bumper: a band along the top half of the rim
    a = math.degrees(math.atan2(dy, dx))  # -90 = straight up
    if -168 <= a <= -12:
        if d > R - W - 4.6:
            return BUMPER
        if d > R - W - 6.0:
            return LINE
    # the bumper's ends
    for end in (-168, -12):
        if abs(a - end) * math.pi / 180 * d <= 0.7 and d > R - W - 6.0:
            return LINE
    return BODY


def render() -> list[list[tuple[int, int, int, int]]]:
    rows = []
    for py in range(SIZE):
        row = []
        for px in range(SIZE):
            acc = [0, 0, 0]
            n = 0
            for sy in range(SS):
                for sx in range(SS):
                    c = color_at(px + (sx + 0.5) / SS, py + (sy + 0.5) / SS)
                    if c:
                        n += 1
                        for k in range(3):
                            acc[k] += c[k]
            if n:
                row.append((round(acc[0] / n), round(acc[1] / n), round(acc[2] / n), round(255 * n / SS / SS)))
            else:
                row.append((0, 0, 0, 0))
        rows.append(row)
    return rows


def write_png(path: Path, px: list[list[tuple[int, int, int, int]]]) -> None:
    raw = b"".join(b"\x00" + bytes(v for p in row for v in p) for row in px)

    def chunk(t: bytes, c: bytes) -> bytes:
        return struct.pack(">I", len(c)) + t + c + struct.pack(">I", zlib.crc32(t + c) & 0xFFFFFFFF)

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "masters" / "ui" / "icon_robot_vacuum.png"
    write_png(out, render())
    print(out)
