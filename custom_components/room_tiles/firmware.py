"""Panel firmware: images Room Tiles installs on its panels (docs/TODO.md
Step 4 "Installing and updating panels", phase E).

- **Where images come from:** `firmware_images/` beside this file (a
  release's own, built for every board) and `<config>/room_tiles_firmware/`
  (builds dropped in by hand: ESPHome's "OTA format" download). Only GENERIC
  images (identity/generic.yaml) are used - a hand-built panel's image holds
  its own name and key, so it's never sent anywhere; those are updated with
  ESPHome.
- **What an image says about itself:** its tag
  `RT-IMAGE:<board>:generic:<PANEL_SCHEMA>;` (the firmware's room_tiles
  codegen writes it) - so a panel only ever gets an image for its own board,
  and only one that speaks this Room Tiles' panel format - and the ESP app description every ESP-IDF
  image starts with: build time and the ELF's SHA-256. Its first 8 bytes,
  hex, are the build's id; a panel reports the same for itself
  (room_tiles.cpp setup).
- **Install:** the panel's update entity (update.py) asks - or Room Tiles
  itself (`auto_installs`): "Update panels automatically", and always for
  a panel too old for this Room Tiles (PANEL_SCHEMA); the panel's next
  payload (or its 426 answer) names the build, size and SHA-256
  ("firmware"); the panel downloads it (PanelFirmwareView), checks it,
  writes its other firmware slot and restarts into it.
- **Never older:** an automatic install only ever offers an image built
  after what the panel runs (it reports its build time) - a panel flashed
  by hand with something newer is left alone.
"""

from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from pathlib import Path

BUNDLED_DIR = Path(__file__).parent / "firmware_images"

# HA's time zone, for the build times shown (set at setup - set_time_zone)
_time_zone: tzinfo | None = None


def set_time_zone(tz: tzinfo | None) -> None:
    """The time zone build times are shown in (HA's; None: the system's)."""
    global _time_zone
    _time_zone = tz
UPLOAD_DIR_NAME = "room_tiles_firmware"  # (in HA's config folder)

IMAGE_TAG = re.compile(rb"RT-IMAGE:([A-Za-z0-9.\-]+):(generic|own):(\d+);")
ESP_IMAGE_MAGIC = 0xE9
# esp_app_desc_t: right after the image header (24 bytes) and the first
# segment's header (8 bytes)
APP_DESC = 0x20
APP_DESC_MAGIC = 0xABCD5432
_TIME = APP_DESC + 4 + 4 + 8 + 32 + 32  # magic, secure_version, reserv1, version, project_name
_DATE = _TIME + 16
_ELF_SHA = _DATE + 16 + 32  # (idf_ver between)
MAX_IMAGE = 8 * 1024 * 1024  # (bigger than any firmware slot: not one)
# an automatic install: at most this many downloads of one build per panel
# (one that doesn't take - it fails, or the panel falls back to its old
# firmware - isn't tried for ever; the update entity's Install still is)
AUTO_TRIES = 2
NEWER_BY_S = 60  # (a build time a minute later: really newer, not the same build's clock)


@dataclass(frozen=True)
class Image:
    path: Path
    board: str
    build: str  # the ELF's SHA-256, first 8 bytes, hex
    sha256: str  # the whole file's (the panel checks it)
    size: int
    built: datetime | None
    generic: bool
    schema: int  # the panel format it speaks (panels.py PANEL_SCHEMA)

    @property
    def built_ts(self) -> float | None:
        return self.built.timestamp() if self.built is not None else None

    @property
    def label(self) -> str:
        """What HA shows as the version: when it was built - in HA's time
        zone (a build stamped with its builder's, e.g. CI's UTC, is
        converted; one without a zone shows as it is) - and its id."""
        built = self.built
        if built is not None and built.tzinfo is not None:
            built = built.astimezone(_time_zone)
        when = built.strftime("%Y-%m-%d %H:%M") if built else "build"
        return f"{when} ({self.build[:6]})"


def _cstr(data: bytes, start: int, size: int) -> str:
    return data[start : start + size].split(b"\0", 1)[0].decode("ascii", "replace")


# ESPHome's own build time ("compiled on 2026-11-14 17:49:22 -0500" in its
# log: the string App holds) - ESPHome builds leave the app description's
# date and time empty
_ESPHOME_BUILT = re.compile(rb"(20\d\d-\d\d-\d\d \d\d:\d\d:\d\d [+-]\d{4})\0")


def _built(data: bytes) -> datetime | None:
    """When the image was built: ESPHome's stamp (the builder's local time,
    with its offset), else the app description's (no time zone)."""
    stamp = _ESPHOME_BUILT.search(data)
    if stamp is not None:
        return datetime.strptime(stamp.group(1).decode(), "%Y-%m-%d %H:%M:%S %z")
    try:
        return datetime.strptime(f"{_cstr(data, _DATE, 16)} {_cstr(data, _TIME, 16)}", "%b %d %Y %H:%M:%S")
    except ValueError:
        return None


def read_image(path: Path) -> Image | None:
    """An image's board, build and checksum - None for anything that isn't a
    Room Tiles panel image. Blocking (reads the file)."""
    try:
        if path.stat().st_size > MAX_IMAGE:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    return parse_image(data, path)


def parse_image(data: bytes, path: Path) -> Image | None:
    """read_image for bytes in memory (`path`: where they are / will be)."""
    if len(data) > MAX_IMAGE or len(data) < _ELF_SHA + 32 or data[0] != ESP_IMAGE_MAGIC:
        return None
    if struct.unpack_from("<I", data, APP_DESC)[0] != APP_DESC_MAGIC:
        return None
    tag = IMAGE_TAG.search(data)
    if tag is None:
        return None
    built = _built(data)
    return Image(
        path=path,
        board=tag.group(1).decode(),
        build=data[_ELF_SHA : _ELF_SHA + 8].hex(),
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        built=built,
        generic=tag.group(2) == b"generic",
        schema=int(tag.group(3)),
    )


def scan_images(dirs: list[Path], schema: int) -> dict[str, Image]:
    """The newest generic image per board (by build time, then file time)
    that speaks panel format `schema`. Blocking."""
    best: dict[str, tuple[tuple, Image]] = {}
    for folder in dirs:
        for f in sorted(folder.glob("*.bin")) if folder.is_dir() else []:
            img = read_image(f)
            if img is None or not img.generic or img.schema != schema:
                continue
            try:
                mtime = f.stat().st_mtime
            except OSError:
                continue
            key = (img.built_ts or 0.0, mtime)
            if img.board not in best or key > best[img.board][0]:
                best[img.board] = (key, img)
    return {board: img for board, (_key, img) in best.items()}


def file_name(board: str) -> str:
    """An image's name in the upload folder: one per board."""
    return f"room-tiles-{board}.ota.bin"


def tidy_folder(folder: Path) -> list[str]:
    """The upload folder: per board, the newest generic image under its own
    name (file_name) and the older ones gone - an upload, or a build dropped
    in by hand ("room-tiles-firmware.ota.bin" from ESPHome), replaces what
    was there. Anything else (not an image, hand-built ones) is left alone.
    Blocking; says what it did."""
    if not folder.is_dir():
        return []
    best: dict[str, tuple[tuple, Path]] = {}
    others: list[tuple[str, Path]] = []
    for f in sorted(folder.glob("*.bin")):
        img = read_image(f)
        if img is None or not img.generic:
            continue
        try:
            key = (img.built_ts or 0.0, f.stat().st_mtime)
        except OSError:
            continue
        if img.board in best:
            older = min(best[img.board], (key, f))
            best[img.board] = max(best[img.board], (key, f))
            others.append((img.board, older[1]))
        else:
            best[img.board] = (key, f)
    done = []
    try:
        for board, old in others:
            old.unlink()
            done.append(f"removed {old.name} (an older {board} build)")
        for board, (_key, f) in best.items():
            name = file_name(board)
            if f.name != name:
                f.replace(folder / name)
                done.append(f"{f.name} -> {name}")
    except OSError as err:
        done.append(f"failed: {err}")
    return done


def store_image(folder: Path, data: bytes, schema: int) -> Image | str:
    """An uploaded image: checked, then kept as its board's image (tidy_folder)
    - or why not, as a code: not_firmware, hand_built, other_version,
    not_kept. An older build than the board's image is dropped (the newer
    one is returned). Blocking."""
    folder.mkdir(parents=True, exist_ok=True)
    part = folder / ".upload.part"
    part.write_bytes(data)
    img = read_image(part)
    why = None
    if img is None:
        why = "not_firmware"
    elif not img.generic:
        why = "hand_built"  # (its own name and key: updated with ESPHome)
    elif img.schema != schema:
        why = "other_version"
    if why is not None:
        part.unlink(missing_ok=True)
        return why
    dest = folder / f"room-tiles-upload-{img.build}.bin"
    part.replace(dest)
    tidy_folder(folder)
    return read_image(folder / file_name(img.board)) or "not_kept"


def images_fingerprint(dirs: list[Path]) -> tuple[tuple[str, int, int], ...]:
    """(path, size, modified) of every image file - cheap: no reading."""
    out = []
    for folder in dirs:
        for f in sorted(folder.glob("*.bin")) if folder.is_dir() else []:
            try:
                st = f.stat()
            except OSError:
                continue
            out.append((str(f), st.st_size, st.st_mtime_ns))
    return tuple(out)


@dataclass(frozen=True)
class PanelFirmware:
    """What a panel says it runs (each payload request: board, build,
    generic, and its build time - unix seconds; None from firmware that
    doesn't say)."""

    board: str
    build: str
    generic: bool
    built: int | None = None


def reported(query: dict[str, str]) -> PanelFirmware | None:
    """A panel's report from its payload request - None from firmware too
    old to send one."""
    board, build = query.get("board", ""), query.get("build", "")
    if not board or not re.fullmatch(r"[0-9a-f]{16}", build):
        return None
    built = query.get("built", "")
    return PanelFirmware(
        board=board,
        build=build,
        generic=query.get("generic") == "1",
        built=int(built) if built.isdigit() and int(built) > 0 else None,
    )


def offer(image: Image | None, running: PanelFirmware | None, auto: bool = False) -> dict | None:
    """The payload's "firmware" for a panel asked to update: the build, its
    size and SHA-256 (+ "auto": installed when nobody's using the panel) -
    None when there's nothing (else) to install."""
    if image is None or running is None or not running.generic or image.board != running.board:
        return None
    if image.build == running.build:
        return None
    out = {"build": image.build, "size": image.size, "sha256": image.sha256}
    if auto:
        out["auto"] = True
    return out


def newer(image: Image | None, running: PanelFirmware | None) -> bool:
    """`image` is for the panel's board, generic, and built after what it
    runs (an automatic install never goes back)."""
    if offer(image, running) is None or image is None or running is None:
        return False
    return image.built_ts is not None and running.built is not None and image.built_ts > running.built + NEWER_BY_S


def auto_installs(
    images: dict[str, Image],
    reports: dict[str, PanelFirmware],
    tries: dict[tuple[str, str], int],
) -> dict[str, str]:
    """The installs "Update panels automatically" asks for: device id ->
    build, for each panel with a newer image for its board that hasn't
    been downloaded AUTO_TRIES times already."""
    out = {}
    for device_id, running in reports.items():
        image = images.get(running.board)
        if newer(image, running) and tries.get((device_id, image.build), 0) < AUTO_TRIES:
            out[device_id] = image.build
    return out
