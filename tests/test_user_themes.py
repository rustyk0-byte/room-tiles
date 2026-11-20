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


async def test_a_built_theme_is_there_right_after_a_restart(hass: HomeAssistant, entry) -> None:
    """Built before and unchanged: ready during setup - a panel asking for
    its theme straight after a restart gets it, not the default first."""
    root = Path(hass.config.path("room_tiles_themes"))
    _candy(root)
    await entry.runtime_data.user_themes.async_check()
    assert "user:candy" in panels.all_themes()
    assert await hass.config_entries.async_reload(entry.entry_id)
    # (no waiting for the background look: setup itself had it)
    assert "user:candy" in panels.all_themes()
    assert "theme-user:candy" in entry.runtime_data.all_packs()
    await hass.async_block_till_done()


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


def test_the_example_theme_builds(tmp_path):
    """examples/themes/candy (docs/THEMES.md "Start here"): a theme users copy -
    it keeps to the format and builds without a problem."""
    from custom_components.room_tiles.themes import fmt

    folder = Path(__file__).resolve().parent.parent / "examples" / "themes" / "candy"
    assert fmt.read(folder)["id"] == "candy"
    assert fmt.check_pictures(folder) == []
    found, broken = installed.scan(folder.parent)
    assert [f.id for f in found] == ["candy"] and broken == []
    base = json.loads((Path(__file__).resolve().parent.parent / "custom_components" / "room_tiles" / "panel_packs" / "themes.json").read_text())[0]
    built = installed.build(found[0], base, tmp_path / "cache")
    assert built.ok, built.problems
    assert "icon_light" in built.off_art  # (its own light icon's off picture: generated)



def _zip_bytes(files: dict) -> bytes:
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


async def test_add_a_theme_from_a_link(hass: HomeAssistant, entry, aioclient_mock, monkeypatch) -> None:
    """The dashboard's "Add from link": a zip, or a GitHub repository's latest
    release - looked at, then kept in the themes folder and built."""
    from custom_components.room_tiles import user_themes as ut

    # (the download's own public-only session: the test's mock here -
    # _PublicResolver is tested on its own)
    monkeypatch.setattr(ut, "_public_session", lambda hass: aioclient_mock.create_session(hass.loop))
    themes = entry.runtime_data.user_themes
    # an address written as numbers in the home network: refused (never looked up)
    assert await themes.async_add_from_link("https://192.168.1.50/t.zip") == {"error": "download_failed"}
    aioclient_mock.get("https://example.com/toip.zip", status=302, headers={"Location": "https://10.0.0.1:8443/x"})
    assert await themes.async_add_from_link("https://example.com/toip.zip") == {"error": "download_failed"}
    # a redirect to plain http: refused
    aioclient_mock.get("https://example.com/plain.zip", status=302, headers={"Location": "http://example.com/t.zip"})
    assert await themes.async_add_from_link("https://example.com/plain.zip") == {"error": "download_failed"}
    mint = _zip_bytes({"mint/theme.json": json.dumps({"format": 1, "id": "mint", "name": {"en": "Mint"}})})
    aioclient_mock.get("https://example.com/mint.zip", content=mint)
    assert await themes.async_add_from_link("http://example.com/mint.zip") == {"error": "not_https"}
    assert await themes.async_add_from_link("https://example.com/mint.zip") == {"id": "user:mint", "name": "Mint"}
    assert (Path(hass.config.path("room_tiles_themes")) / "mint.zip").exists()
    await hass.async_block_till_done()
    await themes.async_check()
    assert "user:mint" in panels.all_themes()
    # again: it's there already (unless replacing)
    assert (await themes.async_add_from_link("https://example.com/mint.zip"))["error"] == "exists"
    assert "error" not in await themes.async_add_from_link("https://example.com/mint.zip", replace=True)
    # a redirect to a public https address is followed
    aioclient_mock.get("https://example.com/moved.zip", status=302, headers={"Location": "https://example.com/mint.zip"})
    assert "error" not in await themes.async_add_from_link("https://example.com/moved.zip", replace=True)
    # a GitHub repository: its latest release's zip
    berry = _zip_bytes({"theme.json": json.dumps({"format": 1, "id": "berry", "name": {"en": "Berry"}})})
    aioclient_mock.get(
        "https://api.github.com/repos/someone/berry-theme/releases/latest",
        json={"assets": [{"name": "berry.zip", "browser_download_url": "https://github.com/someone/berry-theme/releases/download/v1/berry.zip"}]},
    )
    aioclient_mock.get("https://github.com/someone/berry-theme/releases/download/v1/berry.zip", content=berry)
    assert (await themes.async_add_from_link("https://github.com/someone/berry-theme"))["id"] == "user:berry"
    # a folder in a repository (/tree/<branch>/<folder>): just that folder
    repo = _zip_bytes(
        {
            "room-tiles-main/README.md": "the repository",
            "room-tiles-main/examples/themes/candy/theme.json": json.dumps({"format": 1, "id": "candy", "name": {"en": "Candy"}}),
            "room-tiles-main/examples/themes/candy/README.md": "an example",
        }
    )
    aioclient_mock.get("https://codeload.github.com/someone/room-tiles/zip/main", content=repo)
    assert await themes.async_add_from_link("https://github.com/someone/room-tiles/tree/main/examples/themes/candy") == {
        "id": "user:candy",
        "name": "Candy",
    }
    with zipfile.ZipFile(Path(hass.config.path("room_tiles_themes")) / "candy.zip") as zf:
        assert sorted(zf.namelist()) == ["candy/README.md", "candy/theme.json"]  # (nothing else of the repository)
    assert (await themes.async_add_from_link("https://github.com/someone/room-tiles/tree/main/docs"))["error"] == "not_a_theme"
    # not a theme, nothing there
    aioclient_mock.get("https://example.com/notes.zip", content=_zip_bytes({"notes.txt": "hi"}))
    assert await themes.async_add_from_link("https://example.com/notes.zip") == {"error": "not_a_theme"}
    aioclient_mock.get("https://example.com/gone.zip", status=404)
    assert await themes.async_add_from_link("https://example.com/gone.zip") == {"error": "not_found"}
    assert not (Path(hass.config.path("room_tiles_themes")) / "notes.zip").exists()
    await hass.async_block_till_done()


def test_a_colour_name_is_only_a_name(tmp_path) -> None:
    """A colour's name becomes a CSS variable on the dashboard: letters and
    digits only, nothing more gets in with it."""
    from custom_components.room_tiles.themes import fmt

    folder = tmp_path / "bad"
    folder.mkdir()
    (folder / "theme.json").write_text(json.dumps({"format": 1, "id": "bad", "name": {"en": "Bad"}, "colors": {"a;background:url(x)": "#000000"}}))
    with pytest.raises(fmt.ThemeError, match="color names"):
        fmt.read(folder)


async def test_a_pasted_link_never_reaches_the_home_network() -> None:
    """The download's connections only get public addresses: a name that
    leads into the home network (now, or the second time it's looked up)
    gets none - so no connection."""
    from custom_components.room_tiles import user_themes as ut

    class Fake:
        def __init__(self, hosts):
            self.hosts = hosts

        async def resolve(self, host, port=0, family=0):
            return [{"hostname": host, "host": h, "port": port, "family": 2, "proto": 6, "flags": 0} for h in self.hosts]

        async def close(self):
            pass

    r = ut._PublicResolver()
    r._inner = Fake(["192.168.1.1", "127.0.0.1"])
    with pytest.raises(OSError):
        await r.resolve("router.example", 443)
    r._inner = Fake(["10.0.0.5", "140.82.112.3"])
    assert [h["host"] for h in await r.resolve("mixed.example", 443)] == ["140.82.112.3"]


def test_a_free_size_picture_has_a_limit(tmp_path) -> None:
    """Top-bar and clock-hand pictures may be any size - but never one that
    takes gigabytes to open."""
    from custom_components.room_tiles.themes import fmt

    folder = tmp_path / "big"
    (folder / "ui").mkdir(parents=True)
    Image.new("RGBA", (fmt.FREE_MAX_PX + 1, 4)).save(folder / "ui" / "bar_grid.png")
    Image.new("RGBA", (300, 80)).save(folder / "ui" / "bar_map.png")
    problems = fmt.check_pictures(folder)
    assert len(problems) == 1 and "bar_grid.png" in problems[0] and "at most" in problems[0]
