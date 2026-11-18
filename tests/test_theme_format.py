"""The theme format (docs/THEMES.md): the bundled themes keep to it, and the
checker the integration will use on installed themes catches mistakes."""

import json
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "assets"))

import theme_format  # noqa: E402


def _png(path: Path, size: tuple[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, (200, 40, 40, 255)).save(path)


def _theme(tmp: Path, **extra) -> Path:
    folder = tmp / "candy"
    folder.mkdir()
    (folder / "theme.json").write_text(json.dumps({"format": 1, "id": "candy", "name": {"en": "Candy"}, **extra}))
    return folder


def test_bundled_themes_keep_to_the_format():
    ids = theme_format.ids()
    assert ids[0] == theme_format.default_id() == "dark"
    assert {"dark", "light", "christmas"} <= set(ids)
    for theme in ids:
        assert theme_format.check_pictures(theme_format.THEME_ART / theme, scaled_ok=False) == []
        assert set(theme_format.colours(theme)) == set(theme_format.colours("dark"))
        assert theme_format.name(theme, "en")


def test_bundled_clocks_are_valid():
    import build_panel  # (its clock.json check)

    for theme in theme_format.ids():
        build_panel.theme_clock(theme)  # (raises when wrong)


def test_a_good_theme_passes(tmp_path):
    folder = _theme(tmp_path, colors={"accent": "#E8508A"})
    _png(folder / "ui" / "icon_fan.png", (60, 60))
    _png(folder / "ui" / "icon_fan_off.png", (120, 120))  # (2x: the packager scales it down)
    _png(folder / "ui" / "bar_map.png", (44, 34))
    _png(folder / "ui" / "clock_hour.png", (13, 77))  # (clock hands: any size)
    assert theme_format.read(folder)["id"] == "candy"
    assert theme_format.check_pictures(folder) == []
    # today's build takes the size itself only
    assert theme_format.check_pictures(folder, scaled_ok=False) == ["candy/ui/icon_fan_off.png: 120x120 - must be 60x60"]


def test_the_checker_says_what_is_wrong(tmp_path):
    folder = _theme(tmp_path)
    _png(folder / "ui" / "icon_fan.png", (64, 64))
    _png(folder / "ui" / "icon_fann.png", (60, 60))
    (folder / "ui" / "notes.txt").write_text("hi")
    (folder / "ui" / "icon_key.png").write_bytes(b"not a png")
    problems = theme_format.check_pictures(folder)
    assert any("icon_fan.png: 64x64 - must be 60x60 or 120x120 or 240x240" in p for p in problems)
    assert any("icon_fann.png: no picture has this name" in p for p in problems)
    assert any("notes.txt: not a .png" in p for p in problems)
    assert any("icon_key.png: not a readable PNG" in p for p in problems)


@pytest.mark.parametrize(
    "doc, says",
    [
        ({"format": 2, "id": "candy", "name": {"en": "Candy"}}, "format 2"),
        ({"format": 1, "id": "other", "name": {"en": "Candy"}}, "must be the folder's name"),
        ({"format": 1, "id": "candy", "name": {"de": "Süß"}}, "English"),
        ({"format": 1, "id": "candy", "name": {"en": "Candy"}, "colors": {"accent": "pink"}}, "#rrggbb"),
    ],
)
def test_a_bad_theme_json_is_refused(tmp_path, doc, says):
    folder = tmp_path / "candy"
    folder.mkdir()
    (folder / "theme.json").write_text(json.dumps(doc))
    with pytest.raises(SystemExit, match=says):
        theme_format.read(folder)


def test_top_bar_pictures_fit_one_box():
    """docs/THEMES.md "Top bar": any size in, the box out - the drawing
    trimmed, scaled to fit, centred; an on / off pair with one scale."""
    from PIL import Image, ImageDraw

    tf = theme_format
    big = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
    ImageDraw.Draw(big).rectangle((100, 50, 199, 149), fill=(255, 0, 0, 255))  # a 100 x 100 square, off-centre
    out = tf.fit_bar_art(big, tf.BAR_BOX_PANEL)
    assert out.size == tf.BAR_BOX_PANEL
    x0, y0, x1, y1 = out.getchannel("A").getbbox()
    assert (y0, y1) == (0, tf.BAR_BOX_PANEL[1])  # (fills the box's height)
    assert abs((x0 + x1) / 2 - tf.BAR_BOX_PANEL[0] / 2) <= 0.5  # (centred)
    # the off picture drawn smaller on the same canvas: smaller after, too
    off = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
    ImageDraw.Draw(off).rectangle((125, 75, 174, 124), fill=(80, 80, 80, 255))
    fitted = tf.fit_bar_art(off, tf.BAR_BOX_PANEL, big)
    solid = fitted.getchannel("A").point(lambda a: 255 if a > 128 else 0)  # (not the resize's soft edge)
    fx0, fy0, fx1, fy1 = solid.getbbox()
    assert abs((fy1 - fy0) - (y1 - y0) / 2) <= 1  # (half the size, as drawn)
