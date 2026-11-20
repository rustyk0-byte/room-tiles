"""Installed themes in Home Assistant (docs/THEMES.md "Installed themes").

Themes the user puts in /config/room_tiles_themes/ (a folder or a zip) are
checked and built by themes/installed.py - in the executor, one at a time,
never holding up Home Assistant. Built themes are kept in HA's cache folder
(/config/.cache/room_tiles/themes/, not in backups: rebuilt when needed).

Room Tiles looks again (quick: file names, sizes, times) at setup, whenever
a dashboard asks for the theme list, and every few minutes - a new, changed
or removed theme needs no button and no restart. A theme that can't be used
gets a Repairs notice saying why; whatever used it shows the default theme.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from aiohttp import ThreadedResolver
from aiohttp.abc import AbstractResolver
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

THEMES_DIR = "room_tiles_themes"  # in HA's config folder
URL = "/room_tiles_themes"  # the built themes' dashboard pictures (no login: <img> can't send one)
CHECK_EVERY = timedelta(minutes=5)
ISSUE = "theme_problem"  # + "_<its file>"


class UserThemes:
    """The installed themes: built ones (by key, "user:<id>"), and the ones
    that can't be used (with why)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, base: dict, changed: Callable[[], None]) -> None:
        self.hass = hass
        self.entry = entry  # (its background looks end when Room Tiles unloads)
        self.root = Path(hass.config.path(THEMES_DIR))
        self.cache = Path(hass.config.cache_path(DOMAIN, "themes"))
        self.base = base  # the default theme (its colours fill what a theme leaves out)
        self._changed = changed
        self.themes: dict[str, Any] = {}  # key -> installed.Built (ok)
        self.broken: list[Any] = []  # installed.Built with problems
        self.building: set[str] = set()  # ids being built now
        self._stamps: dict[str, str] = {}  # id -> the stamp it was built from
        self._lock = asyncio.Lock()
        self._issues: set[str] = set()
        self._sig: tuple = ((), ())  # the folder as last looked at (none: no themes)
        self._queued = False  # a look asked for, not started yet
        self._warned_coarse = False

    # ---- looking for changes ---------------------------------------------------

    @callback
    def check_soon(self) -> None:
        """Look again, in the background (a dashboard opened its theme list...):
        after the look that's running, if one is - asked for twice, once."""
        if self._queued:
            return
        self._queued = True
        self.entry.async_create_background_task(self.hass, self.async_check(), f"{DOMAIN} themes")

    async def async_check(self) -> None:
        """Look at the folder (one look at a time) and build what changed."""
        async with self._lock:
            self._queued = False
            from .themes import installed

            if self._sig == ((), ()) and not await self.hass.async_add_executor_job(self.root.is_dir):
                return  # (no themes folder, as before: nothing to look at - one stat)
            found, scan_broken = await self.hass.async_add_executor_job(installed.scan, self.root)
            sig = (tuple(sorted((f.id, f.stamp) for f in found)), tuple(sorted(b.source for b in scan_broken)))
            if sig == self._sig:
                return  # nothing changed
            before = {b.id: b for b in [*self.themes.values(), *self.broken]}
            todo = [f for f in found if self._stamps.get(f.id) != f.stamp or f.id not in before]
            results = {f.id: before[f.id] for f in found if f not in todo}
            if todo:
                # (the list says they're getting ready; a changed theme stays
                # in use as it was until its new build is done)
                self.building = {f.id for f in todo}
                self._announce()
            for f in todo:
                built = await self.hass.async_add_executor_job(installed.build, f, self.base, self.cache)
                self.building.discard(f.id)
                self._stamps[f.id] = f.stamp
                results[f.id] = built
                if not built.ok:
                    _LOGGER.warning("Room Tiles theme %s can't be used: %s", f.path.name, "; ".join(built.problems))
                elif built.coarse and not self._warned_coarse:
                    self._warned_coarse = True
                    _LOGGER.info(
                        "This Home Assistant's Pillow has no libimagequant: installed themes' soft edges are a little coarser on the panels"
                    )
            self._stamps = {i: st for i, st in self._stamps.items() if i in results}
            self.themes = {b.key: b for b in results.values() if b.ok}
            self.broken = [b for b in results.values() if not b.ok] + scan_broken
            self._sig = sig
            keep = {b.web.parent.name for b in self.themes.values() if b.web is not None}
            await self.hass.async_add_executor_job(installed.prune, self.cache, keep)
            self._announce()

    @callback
    def _announce(self) -> None:
        self._report_issues()
        self._changed()

    @callback
    def _report_issues(self) -> None:
        now = set()
        for b in self.broken:
            issue_id = f"{ISSUE}_{b.source}"
            now.add(issue_id)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE,
                translation_placeholders={"theme": _md(b.source), "problems": "\n".join(f"- {_md(p)}" for p in b.problems)},
            )
        for gone in self._issues - now:
            ir.async_delete_issue(self.hass, DOMAIN, gone)
        self._issues = now

    async def async_load_cached(self) -> None:
        """At setup: the themes built before and unchanged since, ready at once
        - a panel asking for its theme right after a restart gets it, not the
        default first. What needs building is built in the background (start)."""
        from .themes import installed

        def load() -> list:
            if not self.root.is_dir():
                return []
            found, _ = installed.scan(self.root)
            return [(f, installed.cached(f, self.base, self.cache)) for f in found]

        for found, built in await self.hass.async_add_executor_job(load):
            if built is not None:
                self.themes[built.key] = built
                self._stamps[found.id] = found.stamp
        if self.themes:
            self._changed()

    @callback
    def start(self) -> Callable[[], None]:
        """Look now (in the background) and every few minutes; returns the stop."""
        self.check_soon()  # (most homes have no themes folder: one look, in the executor)
        return async_track_time_interval(self.hass, self._tick, CHECK_EVERY)

    @callback
    def _tick(self, _now: Any) -> None:
        self.check_soon()  # (async_check looks for the folder off the event loop)

    # ---- adding one from a link ------------------------------------------------------

    async def async_add_from_link(self, url: str, replace: bool = False) -> dict[str, Any]:
        """Download a theme into the themes folder (the dashboard's "Add from
        link"): a theme zip (https), or a GitHub repository - its latest
        release's zip, else the repository itself. Looked at before it's kept
        (theme.json; Repairs gets the rest, as for any theme). Returns
        {"id", "name"} or {"error": a code the dashboard words}."""
        import tempfile

        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        from .themes import fmt, installed

        url = url.strip()
        if not url.lower().startswith("https://"):
            return {"error": "not_https"}
        session = async_get_clientsession(self.hass)
        try:
            zip_url, folder = await self._zip_url(session, url)
        except LinkError as err:
            return {"error": err.code}
        # (the download - wherever the link or its redirects lead - on a
        # connection that only ever reaches public addresses)
        public = _public_session(self.hass)
        try:
            async with await self._get_public(public, zip_url) as resp:
                if resp.status == 404:
                    return {"error": "not_found"}
                if resp.status != 200:
                    return {"error": "download_failed"}
                if (getattr(resp, "content_length", None) or 0) > installed.ZIP_MAX_BYTES:
                    return {"error": "too_big"}
                data = bytearray()
                async for chunk in resp.content.iter_chunked(1 << 16):
                    data += chunk
                    if len(data) > installed.ZIP_MAX_BYTES:
                        return {"error": "too_big"}
        except Exception:  # noqa: BLE001 - any network failure is the same to the user
            return {"error": "download_failed"}
        finally:
            await public.close()

        def keep() -> dict[str, Any]:
            self.cache.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.cache, prefix=".link-") as tmp:
                zpath = Path(tmp) / "theme.zip"
                zpath.write_bytes(bytes(data))
                try:
                    if folder:  # (a folder of a repository: just that folder, as its own zip)
                        data[:] = installed.zip_folder(zpath, folder)
                        zpath.write_bytes(bytes(data))
                    doc = installed.check_zip(zpath, Path(tmp) / "check")
                except fmt.ThemeError:
                    return {"error": "not_a_theme"}
                theme_id = doc["id"]
                self.root.mkdir(parents=True, exist_ok=True)
                target = self.root / f"{theme_id}.zip"
                if not replace and (target.exists() or (self.root / theme_id).exists()):
                    return {"error": "exists", "id": f"{installed.PREFIX}{theme_id}", "name": fmt.name(doc, "en")}
                if (self.root / theme_id).is_dir():
                    return {"error": "exists_folder", "id": f"{installed.PREFIX}{theme_id}", "name": fmt.name(doc, "en")}
                part = self.root / f".{theme_id}.zip.part"
                part.write_bytes(bytes(data))
                part.replace(target)
                return {"id": f"{installed.PREFIX}{theme_id}", "name": fmt.name(doc, "en")}

        result = await self.hass.async_add_executor_job(keep)
        if "error" not in result:
            self.check_soon()
        return result

    async def _get_public(self, session: Any, url: str) -> Any:
        """GET `url` the safe way for a link someone pasted, on `session`
        (_public_session: public addresses only): https only, a redirect
        followed only after the same check - at most 5. Raises on anything
        else (download_failed: nothing tells what answered where)."""
        from urllib.parse import urljoin, urlsplit

        for _hop in range(6):
            parts = urlsplit(url)
            if parts.scheme != "https" or not parts.hostname:
                raise LinkError("download_failed")
            resp = await session.get(url, timeout=aiohttp_timeout(180), allow_redirects=False)
            if resp.status in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                url = urljoin(url, resp.headers["Location"])
                resp.release()
                continue
            return resp
        raise LinkError("download_failed")

    async def _zip_url(self, session: Any, url: str) -> tuple[str, str]:
        """The zip to download for a link, and the theme's folder in it ("":
        the zip is the theme): a GitHub folder (/tree/<branch>/<folder>) -
        its repository's zip at that branch; a GitHub repository - its
        latest release's zip, else its own zip; else the link itself."""
        import re

        f = re.fullmatch(r"https://github\.com/([\w.-]+)/([\w.-]+)/tree/([^/?#]+)/([^?#]+?)/?", url)
        if f is not None:
            owner, repo, ref, folder = f.groups()
            return f"https://codeload.github.com/{owner}/{repo}/zip/{ref}", folder

        m = re.fullmatch(r"https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?(?:releases(?:/latest|/tag/([^/?#]+))?/?)?", url)
        if m is None:
            return url, ""
        owner, repo, tag = m.group(1), m.group(2), m.group(3)
        api = f"https://api.github.com/repos/{owner}/{repo}/releases/" + (f"tags/{tag}" if tag else "latest")
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "room-tiles"}
        try:
            async with session.get(api, headers=headers, timeout=aiohttp_timeout(20)) as resp:
                if resp.status == 200:
                    rel = await resp.json()
                    for asset in rel.get("assets") or []:
                        if str(asset.get("name", "")).lower().endswith(".zip"):
                            return str(asset["browser_download_url"]), ""
                    if rel.get("zipball_url"):
                        return str(rel["zipball_url"]), ""
                elif resp.status != 404:
                    raise LinkError("download_failed")
            # (no release: the repository as it is)
            async with session.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers, timeout=aiohttp_timeout(20)) as resp:
                if resp.status == 404:
                    raise LinkError("not_found")
                if resp.status != 200:
                    raise LinkError("download_failed")
                info = await resp.json()
            return f"https://api.github.com/repos/{owner}/{repo}/zipball/{info.get('default_branch') or 'main'}", ""
        except LinkError:
            raise
        except Exception:  # noqa: BLE001
            raise LinkError("download_failed") from None

    # ---- what they give -----------------------------------------------------------

    def names(self) -> dict[str, dict[str, str]]:
        """Each usable theme's names per language, by key - in their order."""
        ordered = sorted(self.themes.values(), key=lambda b: (b.doc.get("order", 100), b.id))
        return {b.key: dict(b.doc["name"]) for b in ordered}

    def packs(self) -> dict[str, Any]:
        """Their panel packs, as panels.load_packs gives the bundled ones."""
        from .panels import Pack

        out: dict[str, Any] = {}
        for b in self.themes.values():
            for cut, data in b.packs.items():
                ident = struct.unpack_from("<32s", data, 16)[0].rstrip(b"\0").decode()
                out[f"theme-{b.key}{cut}"] = Pack(ident, data)
        return out

    def for_dashboard(self) -> dict[str, Any]:
        """The dashboard's list (room_tiles/themes): the usable ones as the
        bundled themes are described (frontend/src/theme.ts), where their
        pictures are, and what's getting ready or can't be used."""
        themes = []
        for key, names in self.names().items():
            b = self.themes[key]
            themes.append(
                {
                    "id": key,
                    "name": names,
                    "order": b.doc.get("order", 100),
                    "colors": b.colours,
                    "offArt": b.off_art,
                    "buttonArt": b.button_art,
                    "base": f"{URL}/{b.web.parent.name}/web",
                }
            )
        return {
            "themes": themes,
            "building": sorted(self.building),
            "problems": [{"theme": b.source, "problems": b.problems} for b in self.broken],
        }


def _md(text: str) -> str:
    """A theme's own text (its file names...) in a Repairs notice: shown as
    it is, never as links or formatting (HA reads the notice as Markdown) -
    as code (no Markdown and no web addresses there)."""
    return "`" + text.replace("`", "'").replace("\n", " ") + "`"


class _PublicResolver(AbstractResolver):
    """Names to addresses - public ones only (none: an error): what "Add
    from link" connects to is exactly what was checked - a name that leads
    into the home network, now or the second time it's looked up, never
    gets a connection."""

    def __init__(self) -> None:
        self._inner = ThreadedResolver()

    async def resolve(self, host: str, port: int = 0, family: int = 0) -> list[dict[str, Any]]:
        import ipaddress

        found = await self._inner.resolve(host, port, family)
        public = [h for h in found if ipaddress.ip_address(h["host"]).is_global]
        if not public:
            raise OSError(f"{host}: no public address")
        return public

    async def close(self) -> None:
        await self._inner.close()


def _public_session(hass: HomeAssistant) -> Any:
    """A session of its own for a pasted link's download: its connections
    reach public addresses only (_PublicResolver). Closed after use."""
    import aiohttp
    from homeassistant.util.ssl import get_default_context

    return aiohttp.ClientSession(connector=aiohttp.TCPConnector(resolver=_PublicResolver(), ssl=get_default_context()))


class LinkError(Exception):
    """A link that leads to no theme zip (`code`: the dashboard's words)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def aiohttp_timeout(seconds: float) -> Any:
    import aiohttp

    return aiohttp.ClientTimeout(total=seconds)


def default_theme(pack_dir: Path) -> dict:
    """The default theme as its theme.json (id, names, colours): the first
    in panel_packs/themes.json (assets/build_panel.py)."""
    try:
        first = json.loads((pack_dir / "themes.json").read_text(encoding="utf-8"))[0]
        return {"id": first["id"], "name": first["name"], "colors": dict(first.get("colors") or {})}
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return {"id": "dark", "name": {"en": "Dark"}, "colors": {}}
