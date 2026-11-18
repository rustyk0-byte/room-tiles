"""A panel's screenshots: the raw RGB565 picture it sends (its "Take
Screenshot" button) saved as a PNG in HA's media folder - Media > My media >
room_tiles - the last KEEP of each panel kept."""

from __future__ import annotations

import struct
import time
import zlib
from array import array
from pathlib import Path

KEEP = 20
FOLDER = "room_tiles"

# RGB565 -> 8 bits a channel (each channel's top bits repeated into the low ones)
_R = bytes(((v >> 11) & 0x1F) * 255 // 31 for v in range(0x10000))
_G = bytes(((v >> 5) & 0x3F) * 255 // 63 for v in range(0x10000))
_B = bytes((v & 0x1F) * 255 // 31 for v in range(0x10000))


def rgb565_to_png(data: bytes, width: int, height: int) -> bytes:
    """The panel's picture (little-endian RGB565, rows packed) as a PNG."""
    if width <= 0 or height <= 0 or len(data) != width * height * 2:
        raise ValueError("size doesn't match the picture")
    px = array("H")
    px.frombytes(data)
    if px.itemsize != 2:
        raise ValueError("no 16-bit array")
    if struct.pack("=H", 1) != b"\x01\x00":
        px.byteswap()  # (a big-endian host)
    rgb = bytearray(width * height * 3)
    rgb[0::3] = bytes(_R[v] for v in px)
    rgb[1::3] = bytes(_G[v] for v in px)
    rgb[2::3] = bytes(_B[v] for v in px)
    row = width * 3
    raw = bytearray()
    for y in range(height):
        raw += b"\x00"  # (no filter)
        raw += rgb[y * row : (y + 1) * row]

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b"")


def save(media_dir: str, node: str, data: bytes, width: int, height: int, now: float | None = None) -> Path:
    """Write it as <media>/room_tiles/<node>-<date>-<time>.png; drop that
    panel's oldest past KEEP. Returns the file. (Blocking: run in the
    executor.)"""
    folder = Path(media_dir) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now if now is not None else time.time()))
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in node) or "panel"
    path = folder / f"{safe}-{stamp}.png"
    path.write_bytes(rgb565_to_png(data, width, height))
    mine = sorted(folder.glob(f"{safe}-*.png"))
    for old in mine[:-KEEP]:
        old.unlink(missing_ok=True)
    return path
