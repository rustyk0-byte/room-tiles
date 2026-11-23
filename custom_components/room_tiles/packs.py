"""Panel packs (.rtp - built by themes/panel.py): the themes and wording a
panel downloads. Only each pack's header is read up front - its id and size,
for the payload; the pack itself stays on disk (gzipped, for the bundled
ones) and is read when a panel asks for it, then let go once sent. Home
Assistant holds no theme in memory.

Header (themes/panel.py): "RTP1", u16 panel format, u16 count, u32 size of
everything before the SHA-256 trailer, ..., char id[32] at 16.
"""

from __future__ import annotations

import gzip
import struct
from dataclasses import dataclass
from pathlib import Path

from .const import PANEL_SCHEMA

HEADER = 48  # (as far as the id: all that's read up front)
TRAILER = 32  # SHA-256 of the pack before it


@dataclass(frozen=True)
class Pack:
    id: str  # theme / language + content hash: the panel keeps what it has
    size: int  # bytes sent: the whole pack, its trailer too
    path: Path | None = None  # .rtp.gz (bundled) / .rtp (installed themes, built uncompressed)
    raw: bytes | None = None  # (tests: a pack in memory instead)

    def read(self) -> bytes:
        """The whole pack, as sent. Blocking (reads the file) - run it in the
        executor; nothing keeps it."""
        if self.raw is not None:
            return self.raw
        assert self.path is not None
        data = self.path.read_bytes()
        return gzip.decompress(data) if self.path.suffix == ".gz" else data


def header(head: bytes) -> tuple[str, int] | None:
    """(id, size) from a pack's first bytes - None when it isn't a pack, or
    one made for another panel format than this code's (never served)."""
    if len(head) < HEADER or head[:4] != b"RTP1":
        return None
    if struct.unpack_from("<H", head, 4)[0] != PANEL_SCHEMA:
        return None
    size = struct.unpack_from("<I", head, 8)[0] + TRAILER
    ident = struct.unpack_from("<32s", head, 16)[0].rstrip(b"\0").decode()
    return ident, size


def pack_file(path: Path) -> Pack | None:
    """The pack in `path`, from its header alone. Blocking."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as f:
        found = header(f.read(HEADER))
    return Pack(found[0], found[1], path) if found else None
