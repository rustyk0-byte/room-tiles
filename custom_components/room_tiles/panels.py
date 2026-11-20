"""Wall panels on Room Tiles firmware (docs/DESIGN.md "Panel firmware").

- **Which devices are panels:** ESPHome devices whose firmware says it is
  Room Tiles' panel (ESPHome `project: name: room-tiles.panel` -> HA's device
  registry shows manufacturer "room-tiles", model "panel"). Each gets a
  `Panel` in the stored data (its own settings, default = unset).
- **Getting the data:** the sensor `sensor.room_tiles_panel_link` changes its
  state (a revision) whenever anything a panel shows changes; its `url`
  attribute is where HA answers. The panel subscribes to it over the ESPHome
  API (which it holds open anyway), then fetches its payload over HTTP:
  GET <url>/api/room_tiles/panel?name=<node>&ts=<unix time>&schema=<n>[&...]&sig=<hex>
  where sig = HMAC-SHA256(the panel's API encryption key, the whole request:
  request_signature) - the key HA's ESPHome integration already holds for
  it, so nothing new is shared and only that panel is answered; nothing of
  a request (its path, its values) can be changed and sent again. HA's
  answer is signed back (answer_signature): the panel takes nothing that
  isn't from HA. (Plain HTTP: the payload can be read on the wire - it holds
  no secrets - but not changed.)
- **Taps:** POST <url>/api/room_tiles/panel/action (same query), JSON body;
  the signature then also covers the body, and each signature is accepted
  once (no replays). A panel may call a short list of services, only on
  entities on its own boards, and change its own settings - nothing else.
- **Older panels** (signed the old way, a lower schema): only the way out -
  every request answered "update needed" (426, with its board's image), and
  that image's download.
"""

from __future__ import annotations

import base64
import binascii
import gzip
import hashlib
import hmac
import json
import logging
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import voluptuous as vol
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, LAYOUTS, NO_ENTITY_KINDS, PANEL_SCHEMA
from .model import Panel, RoomTilesData

_LOGGER = logging.getLogger(__name__)

PANEL_MANUFACTURER = "room-tiles"
PANEL_MODEL = "panel"
LINK_ENTITY = "sensor.room_tiles_panel_link"
URL = "/api/room_tiles/panel"
FIRMWARE_URL = "/api/room_tiles/panel/firmware"
PACK_URL = "/api/room_tiles/panel/pack"
ACTION_URL = "/api/room_tiles/panel/action"
SCREENSHOT_URL = "/api/room_tiles/panel/screenshot"
PACK_DIR = Path(__file__).parent / "panel_packs"  # built by assets/build_panel.py
MAX_SKEW_S = 300  # a request's time may be this far off HA's


def _themes(folder: Path = PACK_DIR) -> dict[str, dict[str, str]]:
    """The themes Room Tiles has packs for, the default first, with their
    names per language: panel_packs/themes.json, written with the packs from
    the theme folders (assets/build_panel.py, docs/THEMES.md)."""
    try:
        found = {str(t["id"]): dict(t.get("name") or {}) for t in json.loads((folder / "themes.json").read_text(encoding="utf-8"))}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        found = {}
    return found or {"dark": {"en": "Dark"}}


_THEME_INFO = _themes()
THEMES = tuple(_THEME_INFO)  # the bundled ones; the first is the default (panels mark it "(Default)")
# themes the user installed, ready to use (user_themes.py keeps this current):
# key ("user:<id>") -> its names per language
_INSTALLED: dict[str, dict[str, str]] = {}


def set_installed(names: dict[str, dict[str, str]]) -> None:
    """The installed themes ready to use, in their order (user_themes.py)."""
    _INSTALLED.clear()
    _INSTALLED.update(names)


def all_themes() -> tuple[str, ...]:
    """Every theme a panel can pick: the bundled ones (the default first),
    then the installed ones."""
    return THEMES + tuple(k for k in _INSTALLED if k not in _THEME_INFO)


def theme_name(theme: str, language: str) -> str:
    """A theme's name in that language (its theme.json), else English, else its id."""
    names = _THEME_INFO.get(theme) or _INSTALLED.get(theme) or {}
    return names.get(language) or names.get("en") or theme
# each language's own name (frontend/src/i18n.ts LANG_NAMES - a test keeps them the same)
LANG_NAMES = {
    "en": "English",
    "de": "Deutsch",
    "es": "Español",
    "fr": "Français",
    "it": "Italiano",
    "nl": "Nederlands",
    "pt": "Português",
}


@dataclass
class PanelDevice:
    """A panel as HA knows it: its device, ESPHome node name and API key."""

    device_id: str
    node: str
    name: str
    area_id: str | None
    psk: bytes | None


@callback
def find_panels(hass: HomeAssistant) -> dict[str, PanelDevice]:
    """Room Tiles panels in HA's device registry, by device id."""
    out: dict[str, PanelDevice] = {}
    reg = dr.async_get(hass)
    for entry in hass.config_entries.async_entries("esphome"):
        node = str(entry.data.get("device_name") or "")
        if not node:
            continue
        for dev in dr.async_entries_for_config_entry(reg, entry.entry_id):
            if dev.manufacturer != PANEL_MANUFACTURER or dev.model != PANEL_MODEL:
                continue
            out[dev.id] = PanelDevice(
                device_id=dev.id,
                node=node,
                name=dev.name_by_user or dev.name or node,
                area_id=dev.area_id,
                psk=_psk(entry.data.get("noise_psk")),
            )
    return out


def _psk(value: Any) -> bytes | None:
    try:
        key = base64.b64decode(str(value or ""), validate=True)
    except (binascii.Error, ValueError):
        return None
    return key if len(key) == 32 else None


def sync_panels(data: RoomTilesData, found: dict[str, PanelDevice]) -> bool:
    """A Panel for every panel device; forget panels whose device is gone.
    True if anything changed."""
    before = [p.id for p in data.panels]
    data.panels = [p for p in data.panels if p.id in found]
    have = {p.id for p in data.panels}
    data.panels += [Panel(id=dev_id) for dev_id in found if dev_id not in have]
    return [p.id for p in data.panels] != before


class PanelLink:
    """The revision panels watch: changes whenever their payload may have. It
    starts from the clock, so after an HA restart every panel fetches again."""

    # what panels show
    # (what a panel's payload holds: its boards, maps, the robots' queues,
    # the found-devices notice)
    SECTIONS = (
        "areas", "catalog", "settings", "panels", "maps", "markers",
        "robots", "vacuums", "appliance_found", "pool_found", "robot_found",
        "area_lights",  # (the area lights button: which lights it switches)
    )

    def __init__(self) -> None:
        self.revision = int(time.time())
        self._listeners: list[Any] = []
        self._devices: dict[str, tuple[str, str, str | None]] = {}

    @callback
    def bump(self) -> None:
        self.revision += 1
        for listener in list(self._listeners):
            listener()

    @callback
    def sections_changed(self, sections: tuple[str, ...]) -> None:
        if any(s in self.SECTIONS for s in sections):
            self.bump()

    @callback
    def devices_seen(self, found: dict[str, PanelDevice]) -> None:
        """A panel's name, node or area in HA changed: its payload did."""
        now = {d.device_id: (d.node, d.name, d.area_id) for d in found.values()}
        if now != self._devices:
            first = not self._devices
            self._devices = now
            if not first:
                self.bump()

    @callback
    def add_listener(self, listener: Any) -> Any:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None


# ---- packs: theme (images + colours) and wording ---------------------------------


@dataclass
class Pack:
    id: str  # theme / language + content hash: the panel keeps what it has
    data: bytes


def load_packs(folder: Path = PACK_DIR) -> dict[str, Pack]:
    """Every pack, unpacked, by file stem ("theme-dark", "strings-de"). Blocking
    (reads files) - run it in the executor."""
    out: dict[str, Pack] = {}
    for f in sorted(folder.glob("*.rtp.gz")):
        data = gzip.decompress(f.read_bytes())
        if data[:4] != b"RTP1":
            continue
        if struct.unpack_from("<H", data, 4)[0] != PANEL_SCHEMA:
            continue  # (made for another panel format than this code's: never served)
        ident = struct.unpack_from("<32s", data, 16)[0].rstrip(b"\0").decode()
        out[f.name[: -len(".rtp.gz")]] = Pack(ident, data)
    return out


def packs_fingerprint(folder: Path = PACK_DIR) -> tuple[tuple[str, int, int], ...]:
    """(name, size, modified) of every pack file - cheap: no reading."""
    out = []
    for f in sorted(folder.glob("*.rtp.gz")):
        try:
            st = f.stat()
        except OSError:
            continue  # (mid-write)
        out.append((f.name, st.st_size, st.st_mtime_ns))
    return tuple(out)


class PackWatch:
    """Packs rebuilt on disk (assets/build_panel.py) are served without a
    restart: a new set is loaded once its files have stopped changing (one
    check with the same files as the last - never a half-written build), and
    panels are told only when a pack's id (its content hash) changed."""

    def __init__(self, loaded: tuple[tuple[str, int, int], ...]) -> None:
        self.loaded = loaded
        self._last = loaded

    def settled_change(self, now: tuple[tuple[str, int, int], ...]) -> bool:
        """True when `now` differs from what's loaded and matches the last check."""
        ready = now != self.loaded and now == self._last
        self._last = now
        return ready


def pack_ids(packs: dict[str, Pack]) -> dict[str, str]:
    return {name: p.id for name, p in packs.items()}


def is_round(store: Any, device_id: str) -> bool:
    """The panel is a round one (its firmware's board, as it last reported):
    it gets the round theme packs - only what it draws."""
    running = store.fw_reports.get(device_id)
    return running is not None and running.board.startswith("elecrow-s3-round")


def pack_for(packs: dict[str, Pack], kind: str, settings: dict[str, Any]) -> Pack | None:
    """The panel's theme pack ("theme"; a round panel's own cut of it,
    `settings["round"]` - assets/build_panel.py ROUND_SKIP) or its language's
    wording ("strings"; English when there's no table for its language)."""
    if kind == "theme":
        # its theme (its round cut first, on a round panel), else the default's
        cuts = ("-round", "") if settings.get("round") else ("",)
        for theme in (settings["theme"], THEMES[0]):
            for cut in cuts:
                if (p := packs.get(f"theme-{theme}{cut}")) is not None:
                    return p
        return None
    if kind == "strings":
        return packs.get(f"strings-{settings['language']}") or packs.get("strings-en")
    return None


# ---- requests -------------------------------------------------------------------


# MIRRORED: firmware/components/room_tiles/signing.cpp sign_request - a change here must be made there too.
def request_signature(psk: bytes, method: str, path: str, query: str, body: bytes | None = None) -> str:
    """A panel's request, signed whole: its method, path, query (as sent,
    without ?, and without its own sig) and its body's hash ("" for a GET)."""
    msg = f"RT2\n{method.upper()}\n{path}\n{query}\n" + (hashlib.sha256(body).hexdigest() if body is not None else "")
    return hmac.new(psk, msg.encode(), hashlib.sha256).hexdigest()


# MIRRORED: firmware/components/room_tiles/signing.cpp answer_ok - a change here must be made there too.
def answer_signature(psk: bytes, request_sig: str, status: int, body: bytes) -> str:
    """HA's answer to a panel, signed with that panel's key: tied to the
    request it answers (its sig), the status and the body - the panel takes
    nothing (data, an update offer, a pack, an image) that isn't."""
    msg = f"RT2-ANSWER\n{request_sig.lower()}\n{status}\n{hashlib.sha256(body).hexdigest()}"
    return hmac.new(psk, msg.encode(), hashlib.sha256).hexdigest()


ANSWER_HEADER = "X-RT-Sig"
ACTION_MAX_BYTES = 64 * 1024
SCREENSHOT_MAX_BYTES = 1280 * 800 * 2  # (the biggest panel screen, RGB565)


def old_signature(psk: bytes, node: str, ts: int, body: bytes | None = None) -> str:
    """How panels before PANEL_SCHEMA 4 sign (only their name and time, and
    a POST's body): taken only on the way out of an old panel - its update."""
    msg = f"{node}\n{ts}"
    if body is not None:
        msg += "\n" + hashlib.sha256(body).hexdigest()
    return hmac.new(psk, msg.encode(), hashlib.sha256).hexdigest()


SIGNED_WHOLE_FROM = 4  # (the panel format that signs whole requests - for good, whatever PANEL_SCHEMA becomes)


def signs_old(schema: str) -> bool:
    """A panel that signs the old way (its format before SIGNED_WHOLE_FROM,
    or one that doesn't say) - by its own number, not ours: a later bump of
    PANEL_SCHEMA must still let today's panels get their update."""
    try:
        return int(schema) < SIGNED_WHOLE_FROM
    except ValueError:
        return True


def unsigned_query(raw: str) -> str:
    """A raw query string as it was signed: without its sig= (the rest
    exactly as sent, in its order)."""
    return "&".join(part for part in raw.split("&") if part and not part.startswith("sig="))


def schema_mismatch(theirs: str) -> str | None:
    """Which side needs an update when a panel's ?schema= isn't ours:
    "firmware" (the panel's is older, or it doesn't say), "integration"
    (newer), None when they match."""
    try:
        n = int(theirs)
    except ValueError:
        return "firmware"
    if n == PANEL_SCHEMA:
        return None
    return "firmware" if n < PANEL_SCHEMA else "integration"


def check_request(
    panels: dict[str, PanelDevice],
    method: str,
    path: str,
    raw_query: str,
    now: float,
    body: bytes | None = None,
    old_ok: bool = False,
) -> PanelDevice | None:
    """The panel this request is from, if all of it is signed by that panel's
    key and its time is close to HA's; else None. `old_ok`: an older panel's
    old signature counts too (only for its way out: the 426 answer, its
    update's download)."""
    import re
    from urllib.parse import parse_qsl

    pairs = parse_qsl(raw_query, keep_blank_values=True)
    q = dict(pairs)
    if len(q) != len(pairs):
        return None  # (a key twice: what's checked here and what's used later must be one value)
    node, sig = q.get("name", ""), q.get("sig", "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sig):
        return None
    dev = next((p for p in panels.values() if p.node == node), None)
    if dev is None or dev.psk is None:
        return None
    try:
        t = int(q.get("ts", ""))
    except ValueError:
        return None
    if abs(now - t) > MAX_SKEW_S:
        return None
    if signs_old(q.get("schema", "")):
        # a panel from before whole-request signing: its old signature, and
        # only where it may use it
        good = old_signature(dev.psk, node, t, body) if old_ok else ""
    else:
        good = request_signature(dev.psk, method, path, unsigned_query(raw_query), body)
    return dev if good and hmac.compare_digest(good, sig) else None


# ---- what a panel may do -------------------------------------------------------------

# per entity domain: the services a panel may call on it
SERVICES: dict[str, set[str]] = {
    "light": {"turn_on", "turn_off", "toggle"},
    "switch": {"turn_on", "turn_off", "toggle"},
    "input_boolean": {"turn_on", "turn_off", "toggle"},
    "fan": {"turn_on", "turn_off", "toggle", "set_percentage"},
    "cover": {"open_cover", "close_cover", "stop_cover", "set_cover_position", "toggle"},
    "lock": {"lock", "unlock"},
    "climate": {"set_temperature", "set_hvac_mode", "turn_on", "turn_off"},
    "scene": {"turn_on"},
    "script": {"turn_on"},
}
TARGET_KEYS = {"entity_id", "device_id", "area_id", "floor_id", "label_id"}  # never from a panel
# Room Tiles' own services a panel may call on a tile's entity (its pool /
# spa sensor), and the data each may carry ("entity" is always the tile's)
ROOM_TILES_SERVICES: dict[str, set[str]] = {
    "vacuum_queue": {"robot", "action", "area", "index", "start"},  # (checked by its robot, not its entity)
    "pool_set_on": {"on"},
    "pool_set_heater": {"heater"},
    "pool_set_target": {"temperature"},
    "appliance_tap": {"index"},  # a tap on an appliance unit (done / waiting: emptied)
}
ENTRY_COVERS = ("garage", "gate", "door")  # (rules.ts isEntryCover)
# tile editing on the panel (its boards only): Room Tiles' own board actions
EDIT_SERVICES: dict[str, set[str]] = {
    "set_tile": {"area", "layout", "slot", "entity", "kind"},
    "clear_tile": {"area", "layout", "slot"},
    "move_tile": {"area", "layout", "from_slot", "to_slot"},
}
PANEL_SETTINGS = ("area", "layout", "theme", "language")


def board_entities(data: RoomTilesData) -> set[str]:
    """Entities on the boards of the shown areas and on the maps (markers):
    all a panel may act on."""
    out: set[str] = set()
    for a in data.areas:
        if a.hidden:
            continue
        for grid in a.tiles.values():
            out |= {t.entity for t in grid if t.entity}
    out |= {mk.entity for mk in data.markers if mk.entity}
    return out


def check_action(
    data: RoomTilesData, body: Any, also: set[str] | None = None
) -> tuple[str, str, str, dict[str, Any]] | str:
    """A service call a panel asked for -> (domain, service, entity, data),
    or why it's refused. `also`: more entities it may act on (its markers'
    pop-up tiles: their groups and scenes)."""
    allowed = board_entities(data) | (also or set())
    if not isinstance(body, dict):
        return "not an object"
    service = str(body.get("service") or "")
    entity = str(body.get("entity") or "")
    domain, _, name = service.partition(".")
    extra = body.get("data") or {}
    if not isinstance(extra, dict):
        return "data isn't an object"
    if domain == "room_tiles" and name in EDIT_SERVICES:
        area = data.area(str(extra.get("area") or ""))
        if area is None or area.hidden:
            return f"no area {extra.get('area')}"
        edit = {k: v for k, v in extra.items() if k in EDIT_SERVICES[name]}
        if name == "set_tile":
            # only what the panel's tile picker offers: a catalog entry (its
            # kind the catalog's), or a tile without an entity (Map, blank) -
            # else a placed tile would open any entity to the panel's actions
            if edit.get("entity"):
                entry = data.catalog.get(str(edit["entity"]))
                if entry is None:
                    return f"{edit['entity']} isn't in the tile list"
                edit["kind"] = entry.kind
            elif edit.get("kind") not in (None, *NO_ENTITY_KINDS):
                return f"a '{edit.get('kind')}' tile needs an entity"
        return domain, name, entity, edit
    if domain == "room_tiles" and name == "area_lights":
        # the top bar's area lights button: a shown area's lights
        area = data.area(str(extra.get("area") or ""))
        if area is None or area.hidden:
            return f"no area {extra.get('area')}"
        action = str(extra.get("action") or "toggle")
        if action not in ("turn_on", "turn_off", "toggle"):
            return f"no action {action}"
        return domain, name, "", {"area": area.id, "action": action}
    if domain == "room_tiles" and name == "vacuum_queue":
        # a robot's room queue (its map's queue mode): any robot Room Tiles has
        if str(extra.get("robot") or "") not in {r.id for r in data.robots}:
            return f"no robot {extra.get('robot')}"
        return domain, name, "", {k: v for k, v in extra.items() if k in ROOM_TILES_SERVICES[name]}
    if domain == "room_tiles":
        if name not in ROOM_TILES_SERVICES:
            return f"{service} isn't allowed"
        if entity not in allowed:
            return f"{entity} isn't on a board"
        return domain, name, entity, {k: v for k, v in extra.items() if k in ROOM_TILES_SERVICES[name]}
    if entity.split(".", 1)[0] != domain or name not in SERVICES.get(domain, set()):
        return f"{service} on {entity} isn't allowed"
    if entity not in allowed:
        return f"{entity} isn't on a board"
    return domain, name, entity, {k: v for k, v in extra.items() if k not in TARGET_KEYS}


def picker_extras(hass: HomeAssistant, data: RoomTilesData) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """The panel's tile picker: every catalog entry with its HA area (entity's,
    else its device's), and the floors' names."""
    from homeassistant.helpers import entity_registry as er
    from homeassistant.helpers import floor_registry as fr

    ents, devs = er.async_get(hass), dr.async_get(hass)
    catalog = []
    for c in data.catalog.entries:
        reg = ents.async_get(c.entity)
        area = reg.area_id if reg else None
        if area is None and reg and reg.device_id:
            dev = devs.async_get(reg.device_id)
            area = dev.area_id if dev else None
        catalog.append({"entity": c.entity, "kind": c.kind, "short": c.short_name, "area": area})
    floors = {f.floor_id: f.name for f in fr.async_get(hass).async_list_floors()}
    return catalog, floors


POPUP_MAX = 6  # a marker's pop-up shows at most this many groups, and as many scenes


def popup_lists(states: list[Any], data: RoomTilesData) -> dict[str, dict[str, Any]]:
    """What a marker's pop-up shows after its own tile (the dashboard's
    _groupsOf / _scenesOf): the groups it's in (closest - fewest members -
    first, groups of its groups too), then the scenes that set it or one of
    those groups (it directly first, then by its closest group, then by
    name); only what can be a tile (in the catalog); at most POPUP_MAX of
    each, with how many more. `states`: HA's states. Pure (testable)."""
    catalog = {c.entity for c in data.catalog.entries}
    members: dict[str, list[str]] = {}
    scenes: list[tuple[str, list[str], str]] = []
    for st in states:
        ids = st.attributes.get("entity_id")
        if not isinstance(ids, (list, tuple)) or not ids:
            continue
        if st.entity_id.startswith("scene."):
            scenes.append((st.entity_id, list(ids), str(st.attributes.get("friendly_name") or st.entity_id)))
        else:
            members[st.entity_id] = list(ids)
    out: dict[str, dict[str, Any]] = {}
    for entity in sorted({mk.entity for mk in data.markers if mk.entity}):
        found: list[str] = []
        queue = [entity]
        while queue:
            e = queue.pop(0)
            for g, m in members.items():
                if g != entity and g not in found and e in m:
                    found.append(g)
                    queue.append(g)
        groups = sorted((g for g in found if g in catalog), key=lambda g: len(members[g]))

        def rank(m: list[str]) -> int:
            if entity in m:
                return 0
            return next((i + 1 for i, g in enumerate(groups) if g in m), -1)

        ranked = sorted(
            ((rank(m), name, sid) for sid, m, name in scenes if sid in catalog and rank(m) >= 0),
        )
        sc = [sid for _r, _n, sid in ranked]
        if groups or sc:
            out[entity] = {
                "groups": groups[:POPUP_MAX],
                "more_groups": max(0, len(groups) - POPUP_MAX),
                "scenes": sc[:POPUP_MAX],
                "more_scenes": max(0, len(sc) - POPUP_MAX),
            }
    return out


def robot_list(data: RoomTilesData, vacuums: dict[str, dict[str, Any]], sensors: dict[str, str]) -> list[dict[str, Any]]:
    """The robots whose rooms can be queued (their vacuum's segments mapped to
    HA areas): `vacuums` = store.vacuums, `sensors` = robot id -> its sensor."""
    out = []
    for r in data.robots:
        areas = (vacuums.get(r.vacuum) or {}).get("areas") or []
        if not areas:
            continue
        out.append(
            {
                "robot": r.id,
                "sensor": sensors.get(r.id, f"sensor.room_tiles_{r.id}"),
                "vacuum": r.vacuum,
                "name": r.name,
                "areas": list(areas),
            }
        )
    return out


def popup_entities(popups: dict[str, dict[str, Any]]) -> set[str]:
    """Every entity the pop-ups show (a panel may act on them)."""
    return {e for p in popups.values() for e in (*p["groups"], *p["scenes"])}


def tile_icons(hass: HomeAssistant, data: RoomTilesData) -> dict[str, str]:
    """Icons a panel can't tell by itself (rules.ts tileIcon / applianceIcon):
    an entry cover (garage, gate, door: its device class) shows the garage
    door; a vacuum its maker's robot (Matic's own, else the generic one); an
    appliance the laundry when it has a washer or dryer, else the dishwasher.
    For the tiles, the maps' markers and the catalog (the tile picker)."""
    from homeassistant.helpers import entity_registry as er

    kinds: dict[str, str] = {}
    for a in data.areas:
        if a.hidden:
            continue
        for grid in a.tiles.values():
            for t in grid:
                if t.entity and t.kind in ("cover", "vacuum", "appliance"):
                    kinds[t.entity] = t.kind
    # the catalog (the tile picker's rows; the maps' markers are from it)
    for c in data.catalog.entries:
        if c.entity and c.kind in ("cover", "vacuum", "appliance"):
            kinds.setdefault(c.entity, c.kind)
    out: dict[str, str] = {}
    ents, devs = er.async_get(hass), dr.async_get(hass)
    for entity, kind in kinds.items():
        st = hass.states.get(entity)
        if kind == "cover":
            if st is not None and st.attributes.get("device_class") in ENTRY_COVERS:
                out[entity] = "icon_garage"
            continue
        if kind == "appliance":
            units = st.attributes.get("units") if st is not None else None
            laundry = isinstance(units, list) and any(
                isinstance(u, dict) and u.get("appliance") in ("washer", "dryer") for u in units
            )
            out[entity] = "icon_laundry" if laundry else "icon_dishwasher"
            continue
        # a vacuum tile may sit on Room Tiles' robot sensor, which names its vacuum
        target = entity
        if st is not None and not entity.startswith("vacuum.") and isinstance(st.attributes.get("vacuum"), str):
            target = st.attributes["vacuum"]
        reg = ents.async_get(target)
        dev = devs.async_get(reg.device_id) if reg and reg.device_id else None
        maker = (dev.manufacturer or "") if dev else ""
        out[entity] = "icon_matic" if maker.lower().startswith("matic") else "icon_robot_vacuum"
    return out


def apply_settings(data: RoomTilesData, panel: Panel, body: Any) -> str | None:
    """A panel changing its own settings (None = done, else why not)."""
    if not isinstance(body, dict) or not isinstance(body.get("settings"), dict):
        return "no settings"
    want = body["settings"]
    # every key checked first: a refused change changes nothing
    for key, value in want.items():
        if key not in PANEL_SETTINGS:
            return f"unknown setting {key}"
        if value is None:
            continue  # (back to the default)
        if key == "area" and (data.area(str(value)) is None):
            return f"no area {value}"
        if key == "layout" and value not in LAYOUTS:
            return f"no layout {value}"
        if key == "theme" and value not in all_themes():
            return f"no theme {value}"
    for key, value in want.items():
        setattr(panel, key, None if value is None else str(value))
    return None


class _Replays:
    """Signatures of POSTs already done (each is good once)."""

    def __init__(self) -> None:
        self._seen: dict[str, float] = {}

    def first_time(self, sig: str, now: float) -> bool:
        # (as checked: hex in any case is the same signature - one use)
        sig = sig.lower()
        self._seen = {s: t for s, t in self._seen.items() if now - t < 2 * MAX_SKEW_S}
        if sig in self._seen:
            return False
        self._seen[sig] = now
        return True


REPLAYS = _Replays()
# (this HA run's start: REPLAYS is empty after a restart - a POST signed
# before it is refused, never done twice)
STARTED = time.time()


# ---- what a panel gets ---------------------------------------------------------------


def adopt_ha_area(data: RoomTilesData, panel: Panel, dev: PanelDevice) -> bool:
    """Setup: a panel with no room of its own takes its HA device's area, once
    (True = changed - save). From then on the room is the panel's: changing
    or clearing the device's area in HA doesn't move it (the panel's own area
    picker does). A factory reset clears it - set up again, it takes HA's
    again. No area in HA (or one not shown): it stays unset, and the panel
    asks (its area picker opens by itself)."""
    if panel.area is not None or not dev.area_id:
        return False
    area = data.area(dev.area_id)
    if area is None or area.hidden:
        return False
    panel.area = dev.area_id
    return True


def room_lights(hass: HomeAssistant, data: RoomTilesData, dev: PanelDevice) -> list[str]:
    """The signal for the panel's "Screen off when the following area lights are off": the
    area lights entity of the room the panel is IN - its HA device's area,
    not the area it shows - the same one its lights button uses: the area's
    override, else Room Tiles' "<Area> Area Lights". A room without one (a
    hidden area: none is made) - its lights as the button would switch
    them. No area in HA, none in Room Tiles, or lights "None": none."""
    from homeassistant.helpers import entity_registry as er

    from .arealights import entity_exists, lights_by_area, resolve as resolve_lights

    area = data.area(dev.area_id) if dev.area_id else None
    if area is None or not (area.light_entity or area.lights):
        return []
    if area.lights and entity_exists(hass, area.lights):
        return [area.lights]  # (the override the user picked in area setup)
    # (Room Tiles' own group: by its registry id - it may have been renamed)
    own = er.async_get(hass).async_get_entity_id("light", DOMAIN, f"area_lights_{area.id}")
    if own is not None:
        return [own]
    return resolve_lights(hass, area, lights_by_area(hass))


def resolve(data: RoomTilesData, panel: Panel, dev: PanelDevice, ha_language: str) -> dict[str, Any]:
    """The panel's settings with the defaults filled in."""
    shown = [a for a in data.areas if not a.hidden]
    area = data.area(panel.area) if panel.area else None
    if area is None or area.hidden:
        area = next((a for a in shown if a.id == dev.area_id), None)
    # none picked, and its device's isn't shown: the first area for now - the
    # panel asks (its area picker opens by itself)
    area_set = area is not None
    if area is None:
        area = shown[0] if shown else None
    layout = panel.layout or (area.layout if area and area.layout else None) or "5x2"
    return {
        "id": panel.id,
        "name": dev.name,
        "area": area.id if area else None,
        "area_set": area_set,
        "layout": layout if layout in LAYOUTS else "5x2",
        "theme": panel.theme if panel.theme in all_themes() else THEMES[0],
        "language": (panel.language or ha_language or "en").replace("_", "-").split("-")[0].lower(),
    }


def payload(
    data: RoomTilesData,
    panel: Panel,
    dev: PanelDevice,
    revision: str,
    ha_language: str,
    packs: dict[str, Pack] | None = None,
    icons: dict[str, str] | None = None,
    picker: tuple[list[dict[str, Any]], dict[str, str]] | None = None,
    popups: dict[str, dict[str, Any]] | None = None,
    robots: list[dict[str, Any]] | None = None,
    found: int = 0,
    area_lights: dict[str, list[str]] | None = None,
    firmware: dict[str, Any] | None = None,
    room: list[str] | None = None,
    round_panel: bool = False,
) -> dict[str, Any]:
    """Everything the panel shows (milestone 2: its settings, the shown areas
    with their boards, and the names / kinds of the entities on them)."""
    shown = [a for a in data.areas if not a.hidden]
    used: set[str] = set()
    areas = []
    for a in shown:
        tiles = {layout: [t.as_dict() for t in grid] for layout, grid in a.tiles.items()}
        for grid in tiles.values():
            used |= {t["entity"] for t in grid if t and t.get("entity")}
        areas.append({
            "id": a.id, "name": a.name, "short": a.short_name, "floor": a.floor, "layout": a.layout, "tiles": tiles,
            "lights": list((area_lights or {}).get(a.id) or []),  # (the area lights button; [] = none)
        })
    used |= {mk.entity for mk in data.markers if mk.entity}  # (the maps' markers: their kind + name too)
    used |= popup_entities(popups or {})  # (and what their pop-ups show)
    entities = {
        c.entity: {"kind": c.kind, "short": c.short_name} for c in data.catalog.entries if c.entity in used
    }
    for entity, icon in (icons or {}).items():
        if entity in entities:
            entities[entity]["icon"] = icon
    settings = resolve(data, panel, dev, ha_language)
    settings["round"] = round_panel  # (its theme pack: the round one)
    # the room it's in (its HA device's area): its area lights entity, for
    # "Screen off when the following area lights are off" - whatever area it shows
    settings["room_lights"] = list(room or [])
    home = data.area(dev.area_id) if dev.area_id else None
    settings["room"] = home.name if home else ""  # (its name, shown with the setting)
    # which packs the panel should have (it downloads one only when its id changes)
    pack_ids = {}
    for kind in ("theme", "strings"):
        p = pack_for(packs or {}, kind, settings)
        if p is not None:
            pack_ids[kind] = {"id": p.id, "size": len(p.data)}
    return {
        "schema": PANEL_SCHEMA,
        "revision": revision,
        "panel": settings,
        "packs": pack_ids,
        "areas": areas,
        "entities": entities,
        # the tile picker (tile editing on the panel)
        "catalog": picker[0] if picker else [],
        "floors": picker[1] if picker else {},
        # the maps (drawn by the panel; markers come with them)
        "maps": [m.as_dict() for m in data.maps],
        "markers": [mk.as_dict() for mk in data.markers],
        # a marker's pop-up: its groups and scenes, after its own tile
        "popups": popups or {},
        # the robot vacuums with a room queue: their sensor, vacuum, the HA
        # areas they clean (the queue's state: the sensor's attributes)
        "robots": robots or [],
        # the panel's settings menu: what it can pick (its own choice; None =
        # the default - HA's language, the house theme)
        "languages": {
            code: LANG_NAMES.get(code, code)
            for code in sorted(k.split("-", 1)[1] for k in (packs or {}) if k.startswith("strings-"))
        },
        "themes": list(all_themes()),
        # each theme's name in the panel's language (its theme.json - a theme
        # the wording doesn't know, e.g. one installed later, still has one)
        "theme_names": {t: theme_name(t, settings["language"]) for t in all_themes()},
        # (its own theme while it's there: one gone - an installed theme
        # removed or broken - shows as the default it falls back to; the
        # choice itself is kept and used again when the theme comes back)
        "own": {"language": panel.language, "theme": panel.theme if panel.theme in all_themes() else None},
        # devices Room Tiles found that aren't set up yet: the panel says so
        # (setting them up is on the dashboard)
        "found": found,
        # an update asked for on its update entity (firmware.offer)
        **({"firmware": firmware} if firmware else {}),
    }


class _PanelRequest(HomeAssistantView):
    """A request signed by a panel (see the module doc)."""

    requires_auth = False  # the panel signs with its own key instead

    def __init__(self, store_of: Any) -> None:
        self._store_of = store_of  # () -> the running RoomTilesStore (or None)

    # (the firmware download: open to a panel too old for this Room Tiles -
    # that's how it gets out of it)
    any_schema = False

    def _panel(self, request: web.Request, body: bytes | None = None) -> tuple[Any, Panel, PanelDevice] | web.Response:
        hass: HomeAssistant = request.app["hass"]
        store = self._store_of()
        if store is None:
            return web.Response(status=503)
        q = request.query
        # an older panel (signed the old way): only the way out - a 426 from
        # any request (below), and its update's download (any_schema)
        dev = check_request(
            find_panels(hass), request.method, request.path, request.rel_url.raw_query_string, time.time(), body, old_ok=True
        )
        if dev is None:
            return web.Response(status=403)
        # an older panel's signature covers only its name and time: each used
        # once at each address; so is any POST's, and the firmware download's
        # (each counts as a try)
        old = signs_old(q.get("schema", ""))
        # (by address too: an old panel asks for its image right after its
        # 426 - the same second, the same old signature - and must get it)
        if (old or body is not None or self.any_schema) and not REPLAYS.first_time(f"{request.path}|{q.get('sig', '')}", time.time()):
            return self._signed(request, dev, web.Response(status=409, text="already done"))
        if (old or body is not None or self.any_schema) and int(q.get("ts", "0")) < STARTED:
            # (what's used once: never signed before this run started either -
            # the guard above starts empty)
            return self._signed(request, dev, web.Response(status=409, text="signed before Home Assistant started"))
        from .repairs import async_report_panel_schema

        needs = None if self.any_schema else schema_mismatch(q.get("schema", ""))
        if not self.any_schema:
            async_report_panel_schema(hass, dev.device_id, dev.name, needs)
        if needs is not None:
            # 426 Upgrade Required: our number, so the panel can say which side
            # - and to a panel that's too old, its board's image: it installs
            # that right away, whatever "Update panels automatically" says
            answer: dict[str, Any] = {"schema": PANEL_SCHEMA}
            if needs == "firmware":
                from . import firmware as fw

                # (an older panel's report isn't covered by its signature:
                # it picks the image offered in this answer, nothing is kept -
                # what HA shows and installs comes from signed reports only)
                running = fw.reported(dict(q))
                if running is not None:
                    offer = fw.offer(store.fw_images.get(running.board), running)
                    if offer is not None:
                        answer["firmware"] = offer
            return self._signed(request, dev, web.json_response(answer, status=426))
        panel = store.data.panel(dev.device_id)
        if panel is None:
            return self._signed(request, dev, web.Response(status=404))
        return store, panel, dev

    @staticmethod
    def _signed(request: web.Request, dev: PanelDevice, resp: web.Response) -> web.Response:
        """The answer signed for the panel that asked (answer_signature)."""
        body = resp.body if isinstance(resp.body, (bytes, bytearray)) else b""
        resp.headers[ANSWER_HEADER] = answer_signature(dev.psk or b"", request.query.get("sig", ""), resp.status, bytes(body))
        return resp

    async def _signed_big(self, request: web.Request, dev: PanelDevice, resp: web.Response) -> web.Response:
        """The same for a big body (an image, a pack): hashed off the event loop."""
        hass: HomeAssistant = request.app["hass"]
        return await hass.async_add_executor_job(self._signed, request, dev, resp)


class PanelView(_PanelRequest):
    """GET a panel's payload."""

    url = URL
    name = "api:room_tiles:panel"

    async def get(self, request: web.Request) -> web.Response:
        found = self._panel(request)
        if isinstance(found, web.Response):
            return found
        store, panel, dev = found
        hass: HomeAssistant = request.app["hass"]
        if adopt_ha_area(store.data, panel, dev):  # (setup: HA's area, once - then it's the panel's)
            store.async_changed(("panels",))
        # what it runs (for updates), and an update asked for on its entity
        from . import firmware as fw

        running = fw.reported(dict(request.query))
        if running is not None:
            store.firmware_seen(dev.device_id, running)
        image = store.fw_images.get(running.board) if running else None
        wanted = store.fw_install.get(dev.device_id)
        auto = dev.device_id in store.fw_auto
        body = payload(
            store.data,
            panel,
            dev,
            str(store.panel_link.revision),
            hass.config.language,
            store.all_packs(),
            tile_icons(hass, store.data),
            picker_extras(hass, store.data),
            popup_lists(hass.states.async_all(), store.data),
            robot_list(store.data, store.vacuums, {rid: e.entity_id for rid, e in store.robot_entities.items()}),
            sum(len(store.appliance_found.get(k) or []) for k in ("found", "pools", "robots")),
            store.area_lights,
            fw.offer(image, running, auto) if image is not None and wanted == image.build else None,
            room_lights(hass, store.data, dev),
            is_round(store, dev.device_id),
        )
        return self._signed(request, dev, web.json_response(body, headers={"Cache-Control": "no-store"}))


class PanelFirmwareView(_PanelRequest):
    """GET the firmware image offered to a panel (?build=): only for its own
    board, only a generic one, only the build offered."""

    url = FIRMWARE_URL
    name = "api:room_tiles:panel:firmware"
    any_schema = True

    async def get(self, request: web.Request) -> web.Response:
        found = self._panel(request)
        if isinstance(found, web.Response):
            return found
        store, _panel, dev = found
        hass: HomeAssistant = request.app["hass"]
        # the image asked for (?build=) - a generic one; for a panel whose
        # signed report says its board, only that board's
        running = store.fw_reports.get(dev.device_id)
        build = request.query.get("build")
        image = next((img for img in store.fw_images.values() if img.build == build), None)
        if image is None or not image.generic or (running is not None and (image.board != running.board or not running.generic)):
            return self._signed(request, dev, web.Response(status=404))
        data = await hass.async_add_executor_job(image.path.read_bytes)
        if hashlib.sha256(data).hexdigest() != image.sha256:
            return self._signed(request, dev, web.Response(status=409, text="the image changed"))  # (rescanned soon)
        store.firmware_downloaded(dev.device_id, image.build)
        resp = web.Response(body=data, content_type="application/octet-stream", headers={"Cache-Control": "no-store"})
        return await self._signed_big(request, dev, resp)


class PanelPackView(_PanelRequest):
    """GET a panel's theme pack or wording (?pack=theme|strings), raw."""

    url = PACK_URL
    name = "api:room_tiles:panel:pack"

    async def get(self, request: web.Request) -> web.Response:
        found = self._panel(request)
        if isinstance(found, web.Response):
            return found
        store, panel, dev = found
        hass: HomeAssistant = request.app["hass"]
        settings = resolve(store.data, panel, dev, hass.config.language)
        settings["round"] = is_round(store, dev.device_id)
        pack = pack_for(store.all_packs(), request.query.get("pack", ""), settings)
        if pack is None:
            return self._signed(request, dev, web.Response(status=404))
        resp = web.Response(
            body=pack.data,
            content_type="application/octet-stream",
            headers={"Cache-Control": "no-store", "X-Pack-Id": pack.id},
        )
        return await self._signed_big(request, dev, resp)


class PanelScreenshotView(_PanelRequest):
    """POST a panel's screenshot (its "Take Screenshot" button): raw RGB565,
    ?w=&h= its size - saved as a PNG in HA's media folder (screenshots.py)."""

    url = SCREENSHOT_URL
    name = "api:room_tiles:panel:screenshot"

    async def post(self, request: web.Request) -> web.Response:
        from . import screenshots

        # (read only up to what a panel's screen can be: a stranger's 16 MB
        # never gets read and hashed)
        if request.content_length is None or request.content_length > SCREENSHOT_MAX_BYTES:
            return web.Response(status=413)
        raw = await request.read()
        found = self._panel(request, raw)
        if isinstance(found, web.Response):
            return found
        _store, _panel, dev = found
        try:
            w, h = int(request.query.get("w", "0")), int(request.query.get("h", "0"))
        except ValueError:
            return self._signed(request, dev, web.Response(status=400, text="no size"))
        if not (0 < w <= 4096 and 0 < h <= 4096) or len(raw) != w * h * 2:
            return self._signed(request, dev, web.Response(status=400, text="size doesn't match the picture"))
        hass: HomeAssistant = request.app["hass"]
        media = (getattr(hass.config, "media_dirs", None) or {}).get("local") or hass.config.path("media")
        path = await hass.async_add_executor_job(screenshots.save, media, dev.node, raw, w, h)
        return self._signed(request, dev, web.json_response({"ok": True, "file": path.name}))


async def _call_for_panel(hass: HomeAssistant, panel: Panel, domain: str, service: str, data: dict[str, Any]) -> None:
    """A panel's action, not waited for: a refusal (no such action, data HA
    won't take) is logged - never an unhandled task error."""
    from homeassistant.exceptions import HomeAssistantError

    try:
        await hass.services.async_call(domain, service, data, blocking=False)
    except (HomeAssistantError, vol.Invalid) as err:
        _LOGGER.warning("A panel's %s.%s wasn't done (panel %s): %s", domain, service, panel.id, err)


class PanelActionView(_PanelRequest):
    """POST what a panel's user did: a service call on one of its board's
    entities ({"service", "entity", "data"}) or its own settings
    ({"settings": {...}})."""

    url = ACTION_URL
    name = "api:room_tiles:panel:action"

    async def post(self, request: web.Request) -> web.Response:
        import json

        if request.content_length is None or request.content_length > ACTION_MAX_BYTES:
            return web.Response(status=413)  # (a tap is a few hundred bytes)
        raw = await request.read()
        found = self._panel(request, raw)
        if isinstance(found, web.Response):
            return found
        store, panel, dev = found
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return self._signed(request, dev, web.Response(status=400, text="not JSON"))
        hass: HomeAssistant = request.app["hass"]
        if isinstance(body, dict) and "settings" in body:
            why = apply_settings(store.data, panel, body)
            if why:
                return self._signed(request, dev, web.Response(status=400, text=why))
            store.async_changed(("panels",))
            return self._signed(request, dev, web.json_response({"ok": True}))
        checked = check_action(store.data, body)
        if isinstance(checked, str) and checked.endswith("isn't on a board"):
            # (a marker's pop-up: its groups and scenes)
            checked = check_action(store.data, body, popup_entities(popup_lists(hass.states.async_all(), store.data)))
        if isinstance(checked, str):
            return self._signed(request, dev, web.Response(status=403, text=checked))
        domain, service, entity, data = checked
        if domain == "room_tiles" and service in EDIT_SERVICES:
            # a board edit: done now, so a refusal (not in the catalog...) can
            # be answered; the new board reaches the panel as a new revision
            from homeassistant.exceptions import HomeAssistantError

            try:
                await hass.services.async_call(domain, service, data, blocking=True)
            except (HomeAssistantError, ValueError, vol.Invalid) as err:
                return self._signed(request, dev, web.Response(status=400, text=str(err)))
            return self._signed(request, dev, web.json_response({"ok": True}))
        if domain == "room_tiles" and service == "appliance_tap":
            # which unit, and is it finished? (the sensor knows; the panel only
            # knows where it was tapped)
            st = hass.states.get(entity)
            units = st.attributes.get("units") if st else None
            index = data.get("index")
            if not isinstance(units, list) or not isinstance(index, int) or not 0 <= index < len(units):
                return self._signed(request, dev, web.json_response({"ok": False}))
            unit = units[index]
            if unit.get("phase") not in ("done", "waiting"):
                return self._signed(request, dev, web.json_response({"ok": False}))  # nothing to empty
            service, data = "clear_appliance", {"appliance": st.attributes.get("appliance"), "unit": unit.get("id")}
        elif domain == "room_tiles" and service in ("vacuum_queue", "area_lights"):
            pass  # (its robot / area says which: no entity)
        elif domain == "room_tiles":
            data = {"entity": entity, **data}
        else:
            data = {"entity_id": entity, **data}
        # (not blocking: the panel shows the result when HA reports it)
        hass.async_create_task(_call_for_panel(hass, panel, domain, service, data))
        return self._signed(request, dev, web.json_response({"ok": True}))
