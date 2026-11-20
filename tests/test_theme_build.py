"""The theme packager (custom_components/room_tiles/themes/): its copies of
other parts' facts stay the same as theirs."""

import re
from pathlib import Path

from custom_components.room_tiles.themes import panel

ROOT = Path(__file__).resolve().parent.parent


def test_off_brightness_matches_the_dashboards():
    text = (ROOT / "frontend" / "src" / "map.ts").read_text(encoding="utf-8")
    block = re.search(r"const OFF_BRIGHTNESS[^{]*\{(.*?)\};", text, re.S).group(1)
    web = {k: float(v) for k, v in re.findall(r"(icon_\w+):\s*([0-9.]+)", block)}
    assert list(web.items()) == list(panel.OFF_BRIGHTNESS.items())  # (and in the same order: the reserved slots)


def test_brand_icon_is_the_firmwares():
    assert panel.BRAND_ICON.read_bytes() == (ROOT / "firmware" / "images" / "brand_icon_36.png").read_bytes()


def test_theme_room_matches_the_partition_table():
    for table, size in (("partitions_16mb.csv", panel.ASSET_AREA), ("partitions_s3_16mb.csv", panel.ASSET_AREA_ROUND)):
        for line in (ROOT / "firmware" / table).read_text(encoding="utf-8").splitlines():
            cols = [c.strip() for c in line.split(",")]
            if cols[0] == "assets":
                assert int(cols[4], 0) == size, table
                break
        else:
            raise AssertionError(f"{table}: no assets partition")
    cpp = (ROOT / "firmware" / "components" / "room_tiles" / "assets.cpp").read_text(encoding="utf-8")
    m = re.search(r"STRINGS_REGION\s*=\s*(\d+)\s*\*\s*1024", cpp)
    assert m and int(m.group(1)) * 1024 == panel.STRINGS_REGION


def test_prune_leaves_work_in_progress_alone(tmp_path):
    """A build's .tmp folder or an "Add from link" download (dot-named) may be
    in use beside a prune: only unused finished builds go."""
    from custom_components.room_tiles.themes.installed import prune

    for name in ("kept-1", "old-2", ".link-abc", ".kept-3.tmp"):
        (tmp_path / name).mkdir()
    import os

    old = tmp_path / ".gone-4.tmp"
    old.mkdir()
    os.utime(old, (0, 0))  # (left behind by a restart, long ago)
    prune(tmp_path, {"kept-1"})
    assert sorted(p.name for p in tmp_path.iterdir()) == [".kept-3.tmp", ".link-abc", "kept-1"]
