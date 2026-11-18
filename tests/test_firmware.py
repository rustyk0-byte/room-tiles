"""Panel firmware images: what Room Tiles reads from them, which it offers."""

import hashlib
import struct
from datetime import datetime, timedelta, timezone

from custom_components.room_tiles.firmware import (
    APP_DESC,
    APP_DESC_MAGIC,
    AUTO_TRIES,
    PanelFirmware,
    auto_installs,
    file_name,
    newer,
    offer,
    read_image,
    reported,
    scan_images,
    store_image,
    tidy_folder,
)

SCHEMA = 3

ELF = bytes(range(32))


def _image(
    board="elecrow-p4-7in-v1.2-es", kind="generic", date="Nov 14 2026", time="07:33:16", elf=ELF, schema=SCHEMA
) -> bytes:
    """An ESP-IDF app image as far as Room Tiles reads it: the image header,
    the app description (time, date, ELF SHA-256) and the board's tag."""
    data = bytearray(0x400)
    data[0] = 0xE9
    struct.pack_into("<I", data, APP_DESC, APP_DESC_MAGIC)
    t = APP_DESC + 4 + 4 + 8 + 32 + 32
    data[t : t + len(time)] = time.encode()
    data[t + 16 : t + 16 + len(date)] = date.encode()
    e = t + 16 + 16 + 32
    data[e : e + 32] = elf
    tag = f"RT-IMAGE:{board}:{kind}:{schema};".encode()
    data[0x200 : 0x200 + len(tag)] = tag
    return bytes(data)


def test_an_image_says_its_board_and_build(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(_image())
    img = read_image(f)
    assert img.board == "elecrow-p4-7in-v1.2-es" and img.generic
    assert img.build == ELF[:8].hex()  # (what the panel reports for itself)
    assert img.built == datetime(2026, 11, 14, 7, 33, 16)
    assert img.sha256 == hashlib.sha256(f.read_bytes()).hexdigest() and img.size == 0x400
    assert img.label == "2026-11-14 07:33 (000102)"


def test_an_esphome_build_says_when_it_was_built(tmp_path):
    # (ESPHome leaves the app description's date and time empty: its own
    # "compiled on" stamp says)
    data = bytearray(_image(date="", time=""))
    stamp = b"2026-11-14 18:04:44 -0500\0"
    data[0x300 : 0x300 + len(stamp)] = stamp
    (tmp_path / "esphome.bin").write_bytes(bytes(data))
    img = read_image(tmp_path / "esphome.bin")
    assert img.built == datetime(2026, 11, 14, 18, 4, 44, tzinfo=timezone(timedelta(hours=-5)))
    # shown in HA's time zone: a CI build (UTC) at 21:50 is 16:50 in New York
    import custom_components.room_tiles.firmware as fw
    from zoneinfo import ZoneInfo

    try:
        fw.set_time_zone(ZoneInfo("America/New_York"))
        assert img.label == "2026-11-14 18:04 (000102)"
        utc = bytearray(_image(date="", time=""))
        stamp = b"2026-11-16 21:50:12 +0000\0"
        utc[0x300 : 0x300 + len(stamp)] = stamp
        (tmp_path / "ci.bin").write_bytes(bytes(utc))
        assert read_image(tmp_path / "ci.bin").label == "2026-11-16 16:50 (000102)"
    finally:
        fw.set_time_zone(None)


def test_not_an_image(tmp_path):
    (tmp_path / "junk.bin").write_bytes(b"\xe9" + b"\0" * 300)  # no app description
    assert read_image(tmp_path / "junk.bin") is None
    no_tag = bytearray(_image())
    no_tag[0x200:0x240] = b"\0" * 64
    (tmp_path / "untagged.bin").write_bytes(bytes(no_tag))
    assert read_image(tmp_path / "untagged.bin") is None  # (not a Room Tiles panel's)


def test_the_newest_generic_image_per_board(tmp_path):
    (tmp_path / "old.bin").write_bytes(_image(time="06:00:00", elf=b"\x01" * 32))
    (tmp_path / "new.bin").write_bytes(_image(time="09:00:00", elf=b"\x02" * 32))
    (tmp_path / "ten.bin").write_bytes(_image(board="elecrow-p4-10in-v1.2-es", elf=b"\x03" * 32))
    (tmp_path / "own.bin").write_bytes(_image(kind="own", time="23:00:00", elf=b"\x04" * 32))  # never sent
    (tmp_path / "other.bin").write_bytes(_image(time="23:30:00", elf=b"\x05" * 32, schema=SCHEMA + 1))  # (another format)
    got = scan_images([tmp_path, tmp_path / "missing"], SCHEMA)
    assert set(got) == {"elecrow-p4-7in-v1.2-es", "elecrow-p4-10in-v1.2-es"}
    assert got["elecrow-p4-7in-v1.2-es"].build == "02" * 8


def test_what_a_panel_reports():
    assert reported({"board": "b", "build": "00" * 8, "generic": "1"}) == PanelFirmware("b", "00" * 8, True)
    assert reported({"board": "b", "build": "00" * 8}).generic is False
    assert reported({}) is None  # (firmware too old to say)
    assert reported({"board": "b", "build": "nothex!"}) is None
    assert reported({"board": "b", "build": "00" * 8, "built": "1763251200"}).built == 1763251200
    assert reported({"board": "b", "build": "00" * 8, "built": "soon"}).built is None


def test_an_offer_only_for_its_own_board_a_generic_panel_and_another_build(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(_image())
    img = read_image(f)
    other = PanelFirmware("elecrow-p4-7in-v1.2-es", "ff" * 8, True)
    assert offer(img, other) == {"build": img.build, "size": img.size, "sha256": img.sha256}
    assert offer(img, PanelFirmware("elecrow-p4-7in-v1.2-es", img.build, True)) is None  # (runs it)
    assert offer(img, PanelFirmware("elecrow-p4-10in-v1.2-es", "ff" * 8, True)) is None  # (other board)
    assert offer(img, PanelFirmware("elecrow-p4-7in-v1.2-es", "ff" * 8, False)) is None  # (hand-built)
    assert offer(None, other) is None


def _esphome(tmp_path, name, when, elf, board="elecrow-p4-7in-v1.2-es", kind="generic"):
    """An ESPHome-built image (its "compiled on" stamp), written to tmp_path."""
    data = bytearray(_image(board=board, kind=kind, date="", time="", elf=elf))
    stamp = when.strftime("%Y-%m-%d %H:%M:%S -0500").encode() + b"\0"
    data[0x300 : 0x300 + len(stamp)] = stamp
    (tmp_path / name).write_bytes(bytes(data))
    return read_image(tmp_path / name)


EST = timezone(timedelta(hours=-5))


def test_an_automatic_install_never_goes_back(tmp_path):
    img = _esphome(tmp_path, "a.bin", datetime(2026, 11, 15, 18, 33, tzinfo=EST), b"\x07" * 32)
    t = int(img.built_ts)
    board = "elecrow-p4-7in-v1.2-es"
    assert newer(img, PanelFirmware(board, "ff" * 8, True, t - 3600))  # (an hour older)
    assert not newer(img, PanelFirmware(board, "ff" * 8, True, t + 3600))  # (flashed by hand, newer)
    assert not newer(img, PanelFirmware(board, "ff" * 8, True, t - 10))  # (the same build time, near enough)
    assert not newer(img, PanelFirmware(board, "ff" * 8, True, None))  # (doesn't say when it was built)
    assert not newer(img, PanelFirmware(board, img.build, True, t - 3600))  # (runs it)


def test_automatic_installs_stop_after_a_few_tries(tmp_path):
    img = _esphome(tmp_path, "a.bin", datetime(2026, 11, 15, 18, 33, tzinfo=EST), b"\x07" * 32)
    board = "elecrow-p4-7in-v1.2-es"
    old = PanelFirmware(board, "ff" * 8, True, int(img.built_ts) - 86400)
    images = {board: img}
    assert auto_installs(images, {"p1": old}, {}) == {"p1": img.build}
    assert auto_installs(images, {"p1": old}, {("p1", img.build): AUTO_TRIES - 1}) == {"p1": img.build}
    assert auto_installs(images, {"p1": old}, {("p1", img.build): AUTO_TRIES}) == {}
    hand = PanelFirmware(board, "ff" * 8, False, int(img.built_ts) - 86400)
    assert auto_installs(images, {"p1": hand}, {}) == {}  # (a hand-built panel: never)


def test_the_folder_keeps_the_newest_build_per_board_under_its_name(tmp_path):
    _esphome(tmp_path, "room-tiles-firmware.ota.bin", datetime(2026, 11, 15, 18, 0, tzinfo=EST), b"\x01" * 32)
    _esphome(tmp_path, "room-tiles-firmware.ota (1).bin", datetime(2026, 11, 15, 19, 0, tzinfo=EST), b"\x02" * 32)
    _esphome(tmp_path, "ten.bin", datetime(2026, 11, 15, 17, 0, tzinfo=EST), b"\x03" * 32, board="elecrow-p4-10in-v1.2-es")
    _esphome(tmp_path, "mine.bin", datetime(2026, 11, 15, 20, 0, tzinfo=EST), b"\x04" * 32, kind="own")
    (tmp_path / "notes.txt").write_text("left alone")
    tidy_folder(tmp_path)
    names = sorted(f.name for f in tmp_path.iterdir())
    assert names == sorted(
        [file_name("elecrow-p4-7in-v1.2-es"), file_name("elecrow-p4-10in-v1.2-es"), "mine.bin", "notes.txt"]
    )
    assert read_image(tmp_path / file_name("elecrow-p4-7in-v1.2-es")).build == "02" * 8


def test_an_upload_is_checked_and_kept_as_its_boards_image(tmp_path):
    folder = tmp_path / "room_tiles_firmware"
    good = _image(elf=b"\x09" * 32)
    kept = store_image(folder, good, SCHEMA)
    assert kept.build == "09" * 8 and (folder / file_name(kept.board)).exists()
    assert store_image(folder, b"not firmware", SCHEMA) == "not_firmware"
    assert store_image(folder, _image(kind="own"), SCHEMA) == "hand_built"
    assert store_image(folder, _image(schema=SCHEMA + 1), SCHEMA) == "other_version"
    assert sorted(f.name for f in folder.iterdir()) == [file_name(kept.board)]  # (nothing left behind)
