#!/usr/bin/env python3
"""Fail when a panel firmware image takes more than 80% of its firmware slot
(docs/TODO.md phase A): the flash layout is frozen, so the room left in a
slot is all future firmware gets - this says so long before it's gone.

    tools/check_firmware_size.py <firmware.ota.bin> <partitions.csv> [--max 80]

The slot is the partition table's first `app` partition (both slots are the
same size). Prints the use either way; exit 1 above the limit.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def slot_size(partitions: Path) -> int:
    for line in partitions.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        cols = [c.strip() for c in line.split(",")]
        if len(cols) >= 5 and cols[1] == "app":
            return int(cols[4], 0)
    raise SystemExit(f"{partitions}: no app partition")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("image", type=Path)
    ap.add_argument("partitions", type=Path)
    ap.add_argument("--max", type=float, default=80.0, help="the most a slot may hold, in percent")
    args = ap.parse_args()
    size = args.image.stat().st_size
    slot = slot_size(args.partitions)
    pct = 100.0 * size / slot
    print(f"{args.image.name}: {size / 1048576:.2f} MiB of a {slot / 1048576:.2f} MiB slot ({pct:.1f}%, limit {args.max:.0f}%)")
    if pct > args.max:
        print(f"Too big: the firmware may use at most {args.max:.0f}% of its slot", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
