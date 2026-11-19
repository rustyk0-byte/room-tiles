"""Installed themes (docs/THEMES.md "Installed themes", user_themes.py):
found in /config/room_tiles_themes/, built, offered to panels and
dashboards; a broken one is reported in Repairs and never offered."""

import json
import shutil
import zipfile
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from PIL import Image, ImageDraw
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.room_tiles import panels
from custom_components.room_tiles.const import DOMAIN
from custom_components.room_tiles.themes import installed


def _candy(root: Path, **extra) -> Path:
    folder = root / "candy"
    (folder / "ui").mkdir(parents=True)
    doc = {"format": 1, "id": "candy", "name": {"en": "Candy", "de": "Bonbon"}, "colors": {"accent": "#E8508A"}, **extra}
    (folder / "theme.json").write_text(json.dumps(doc))
    img = Image.new("RGBA", (120, 120), (0, 0, 0, 0))  # (2x: brought down to 60 x 60)
    ImageDraw.Draw(img).ellipse((10, 10, 110, 110), fill=(232, 80, 138, 255))
    img.save(folder / "ui" / "icon_fan.png")
    img.save(folder / "ui" / "bar_map.png")  # (any size: fitted into the top bar's box)
    return folder


@pytest.fixture
async def entry(hass: HomeAssistant):
    e = MockConfigEntry(domain=DOMAIN)
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    yield e
    shutil.rmtree(hass.config.path("room_tiles_themes"), ignore_errors=True)
    shutil.rmtree(hass.config.cache_path(DOMAIN), ignore_errors=True)


async def test_an_installed_theme_reaches_panels_and_dashboards(hass: HomeAssistant, entry) -> None:
    store = entry.runtime_data
    root = Path(hass.config.path("room_tiles_themes"))
    _candy(root)
    await store.user_themes.async_check()
    assert "user:candy" in panels.all_themes() and panels.all_themes()[0] == "dark"
    assert panels.theme_name("user:candy", "de") == "Bonbon"
    # the panels: its packs (and the round panel's), its colours over the default's
    packs = store.all_packs()
    assert {"theme-user:candy", "theme-user:candy-round"} <= set(packs)
    theme = panels.pack_for(packs, "theme", {"theme": "user:candy"})
    assert theme is packs["theme-user:candy"] and theme.id.startswith("user-")
    # the dashboard: its description and its built pictures
    listed = store.payload()["themes"]
    (candy,) = listed["themes"]
    assert candy["id"] == "user:candy" and candy["colors"]["accent"] == "#E8508A"
    assert candy["colors"]["page"]  # (the default theme's, where it sets none)
    assert candy["buttonArt"] == ["bar_map"] and listed["problems"] == []
    web = Path(hass.config.cache_path(DOMAIN, "themes")) / candy["base"].split("/")[2] / "web"
    with Image.open(web / "ui" / "icon_fan.png") as img:
        assert img.size == (60, 60)
    assert (web / "appliances").is_dir()
    # unchanged: never built again
    before = store.user_themes.themes["user:candy"].version
    await store.user_themes.async_check()
    assert store.user_themes.themes["user:candy"].version == before


async def test_a_broken_theme_is_reported_and_left_out(hass: HomeAssistant, entry) -> None:
    store = entry.runtime_data
    root = Path(hass.config.path("room_tiles_themes"))
    folder = _candy(root)
    Image.new("RGBA", (64, 64)).save(folder / "ui" / "icon_key.png")  # (wrong size)
    await store.user_themes.async_check()
    assert "user:candy" not in panels.all_themes()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "theme_problem_candy")
    assert issue is not None and "icon_key.png: 64x64" in issue.translation_placeholders["problems"]
    assert store.payload()["themes"]["problems"][0]["theme"] == "candy"
    # fixed: offered, the notice gone
    (folder / "ui" / "icon_key.png").unlink()
    await store.user_themes.async_check()
    assert "user:candy" in panels.all_themes()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "theme_problem_candy") is None
    # removed: gone again (and a panel on it falls back to the default)
    shutil.rmtree(folder)
    await store.user_themes.async_check()
    assert "user:candy" not in panels.all_themes()
    assert panels.pack_for(store.all_packs(), "theme", {"theme": "user:candy"}).id.startswith("dark-")


def test_a_theme_zip_unpacks_safely(tmp_path):
    root = tmp_path / "themes"
    root.mkdir()
    with zipfile.ZipFile(root / "mint.zip", "w") as zf:
        zf.writestr("mint/theme.json", json.dumps({"format": 1, "id": "mint", "name": {"en": "Mint"}}))
    with zipfile.ZipFile(root / "evil.zip", "w") as zf:
        zf.writestr("theme.json", json.dumps({"format": 1, "id": "evil", "name": {"en": "Evil"}}))
        zf.writestr("../../outside.txt", "no")
    found, broken = installed.scan(root)
    assert sorted(f.id for f in found) == ["evil", "mint"] and broken == []
    base = {"colors": {"page": "#000000", "accent": "#111111"}}
    by_id = {f.id: f for f in found}
    assert installed.build(by_id["mint"], base, tmp_path / "cache").ok
    evil = installed.build(by_id["evil"], base, tmp_path / "cache")
    assert not evil.ok and "outside the theme" in evil.problems[0]
    assert not (tmp_path / "outside.txt").exists()


def test_the_folder_says_what_it_cant_use(tmp_path):
    root = tmp_path / "themes"
    (root / "loose").mkdir(parents=True)  # (no theme.json)
    (root / "candy").mkdir()
    (root / "candy" / "theme.json").write_text("{}")
    with zipfile.ZipFile(root / "candy.zip", "w") as zf:
        zf.writestr("theme.json", "{}")
    found, broken = installed.scan(root)
    assert [f.path.name for f in found] == ["candy"]
    assert {b.source for b in broken} == {"loose", "candy.zip"}
