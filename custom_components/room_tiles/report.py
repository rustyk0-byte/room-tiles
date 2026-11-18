"""The report scrubber (DESIGN.md "Privacy: what reports send").

Everything Room Tiles helps send back - model reports, unknown states,
recorded cycles, bug reports - goes through `scrub()` before the user sees
it. It's an ALLOW-list: a report has a fixed layout (REPORT), every value a
strict type, and anything not recognised is dropped, never "probably fine".
On top of that, every string is checked against what would tie it to the
user or their home: addresses, ids, serials, times of day, and the home's
own words (`secrets_from_hass`: names of areas, devices, entities, people,
the home; entity ids, unique ids). A dropped value is noted (path + why),
so tests can check it and the confirmation screen can say what was left out.

Pure functions (no HA) except `secrets_from_hass`.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

# ---- what each value may be --------------------------------------------------------

# the answers a user gives on the Appliances page (an unknown state): what it
# means - running (washing / drying), paused, off, error - and later report kinds'
ANSWERS = frozenset({"running", "paused", "off", "error", "not_running", "done", "waiting", "door_open", "unknown"})
# a model report's outcome
OUTCOMES = frozenset({"works", "partly", "broken"})
FEATURE_ANSWERS = frozenset({"works", "partly", "broken", "not_tried"})  # (model_report.ANSWERS)
KINDS = frozenset({"model", "unknown_state", "recording", "problem", "bug", "idea", "question"})
# (Send feedback: the user's words, and for a bug where it happened)
FEEDBACK = frozenset({"bug", "idea", "question"})
WHERE = frozenset({"dashboard", "panel", "device", "other"})
# a problem report's cycle: where it came from, how it ended, what else
# happened in it (cycles.py)
CYCLE_FROM = frozenset({"history", "window", "recorded"})
CYCLE_ENDS = frozenset({"quiet", "stopped", "limit", "no_cycle", "history"})
EVENTS = frozenset({"cycle_started", "ha_stopping", "ha_started", "ha_stopped_unclean", "room_tiles_reloaded", "stopped"})

MAX_STR = 64  # (longer: dropped - free text)
MAX_LIST = 3000  # (a recording: a cycle's state changes - cycles.MAX_ROWS)
MAX_DESCRIPTION = 2000
MAX_ATTRS = 40

_IP4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IP6 = re.compile(r"\b(?:[0-9a-f]{1,4}:){2,7}[0-9a-f]{0,4}\b", re.I)
_MAC = re.compile(r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b|\b[0-9a-f]{12}\b", re.I)
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", re.I)
_URL = re.compile(r"\b(?:https?|wss?|ftp|mqtt)://|\bwww\.", re.I)
_UUID = re.compile(r"\b[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}\b", re.I)
_LONG_HEX = re.compile(r"\b[0-9a-f]{16,}\b", re.I)
_ENTITY_ID = re.compile(r"\b[a-z_]+\.[a-z0-9_]+\b")
_ISO_TIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}|\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\b", re.I)
# 10+ letters and digits with at least 4 digits: a serial ("program2", "eco50ec" are states)
_TOKENISH = re.compile(r"\b(?=(?:[a-z]*\d){4})(?=[a-z0-9]*[a-z])[a-z0-9]{10,}\b", re.I)
_STATE = re.compile(r"^[\w .:+\-/%°()#,]{1,64}$", re.UNICODE)
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_VERSION = re.compile(r"^[0-9][0-9A-Za-z.+\-_]{0,31}$")
_DOMAIN = re.compile(r"^[a-z][a-z0-9_]{1,49}$")
_ROLE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_BOARD = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")  # (a panel board: elecrow-p4-10in)
_SIZE = re.compile(r"^\d{2,5}x\d{2,5}$")  # (a browser window: 1280x800)
_BUILD = re.compile(r"^[0-9a-f]{8}$")  # (a firmware build's hash, cut short)

# attribute keys never kept, whatever the value (names, places, people, ids)
_DENY_KEYS = re.compile(
    r"(name|friendly|entity_picture|picture|latitude|longitude|gps|location|address|zone|person|user|"
    r"owner|account|email|phone|serial|mac|ip|host|url|link|token|password|secret|key|ssid|bssid|"
    r"(^|_)id$|_ids?$|unique|device_id|config_entry|identifier|room|area|floor|home|label|title|"
    r"description|message|note|text|comment)",
    re.I,
)


@dataclass
class Scrubbed:
    """A scrubbed report: what's left, and what was dropped (path, why)."""

    doc: dict[str, Any]
    dropped: list[tuple[str, str]] = field(default_factory=list)


def _deny_in(text: str, secrets: Collection[str], *, version: bool = False) -> str | None:
    """Why `text` can't be sent ("" = fine). `version`: a version number (its
    dots aren't an IP address)."""
    low = text.lower()
    for word in secrets:
        if word and word in low:
            return "a name or id from this home"
    checks: tuple[tuple[re.Pattern[str], str], ...] = (
        (_URL, "an address"),
        (_EMAIL, "an email"),
        (_UUID, "an id"),
        (_MAC, "a hardware address"),
        (_IP4, "an IP address"),
        (_IP6, "an IP address"),
        (_LONG_HEX, "an id"),
        (_ISO_TIME, "a time of day"),
        (_ENTITY_ID, "an entity id"),
    )
    for pattern, why in checks:
        if version and pattern in (_IP4, _IP6):
            continue
        if pattern.search(text):
            return why
    return ""


def _string(
    value: Any,
    secrets: Collection[str],
    *,
    serials: bool = True,
    shape: re.Pattern[str] | None = None,
    names: bool = True,
    version: bool = False,
) -> tuple[Any, str]:
    if not isinstance(value, str):
        return None, "not text"
    text = value.strip()
    if not text or len(text) > MAX_STR:
        return None, "free text"
    if shape is not None and not shape.match(text):
        return None, "not the expected form"
    why = _deny_in(text, secrets if names else (), version=version)
    if why:
        return None, why
    if serials and _TOKENISH.search(text):
        return None, "a serial number"
    return text, ""


def _number(value: Any) -> tuple[Any, str]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, "not a number"
    if isinstance(value, float) and not math.isfinite(value):
        return None, "not a number"
    if 1e9 <= abs(value) < 1e14:  # (seconds or milliseconds since 1970: a time of day)
        return None, "a time of day"
    return value, ""


# ---- the leaf types ------------------------------------------------------------------

Leaf = Callable[[Any, Collection[str]], tuple[Any, str]]


def _state(value: Any, secrets: Collection[str]) -> tuple[Any, str]:
    """A raw device state / attribute value: a short word or number, a bool,
    or a short list of those."""
    if isinstance(value, bool) or value is None:
        return value, ""
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, list):
        if len(value) > 64:  # (an enum sensor's options: a few dozen)
            return None, "too long"
        out = []
        for item in value:
            kept, why = _state(item, secrets)
            if why or isinstance(item, list):
                return None, why or "nested"
            out.append(kept)
        return out, ""
    return _string(value, secrets, shape=_STATE)


# (the next three come from the device / integration, never typed by the
# user - not checked against the home's words: a device the user named
# "John's Bosch" mustn't drop the brand "Bosch"; still no addresses / ids)


def _model(value: Any, secrets: Collection[str]) -> tuple[Any, str]:
    """A brand / model name or number (model numbers look like serials: kept)."""
    return _string(value, secrets, serials=False, shape=_STATE, names=False)


def _version(value: Any, secrets: Collection[str]) -> tuple[Any, str]:
    return _string(value, secrets, serials=False, shape=_VERSION, names=False, version=True)


def _domain(value: Any, secrets: Collection[str]) -> tuple[Any, str]:
    return _string(value, secrets, serials=False, shape=_DOMAIN, names=False)


def _role(value: Any, secrets: Collection[str]) -> tuple[Any, str]:
    # (roles are Room Tiles' own words - status, door, time_left - never the
    # home's: a name there means an entity id slipped through)
    return _string(value, secrets, serials=False, shape=_ROLE)


def _board(value: Any, secrets: Collection[str]) -> tuple[Any, str]:
    return _string(value, secrets, serials=False, shape=_BOARD)


_CODE_AT = re.compile(r"^[\w.-]{1,60}\.m?js:\d{1,7}(?::\d{1,7})?$")  # (room-tiles-panel.js:3:51234)
MAX_ERROR = 300
_MASKS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_URL, "<url>"),  # (just its start: the rest goes with the word mask below)
    (_EMAIL, "<email>"),
    (_UUID, "<id>"),
    (_MAC, "<id>"),
    (_LONG_HEX, "<id>"),
    (_ISO_TIME, "<time>"),
    (_ENTITY_ID, "<entity>"),
)


def _error_text(value: Any, secrets: Collection[str]) -> tuple[Any, str]:
    """A dashboard error's message (Send feedback, a bug on this dashboard):
    kept, with what could tell about the home masked - addresses, emails,
    ids, times, entity ids, this home's own words - not dropped whole."""
    if not isinstance(value, str):
        return None, "not text"
    text = _CONTROL.sub(" ", value).strip()[:MAX_ERROR]
    text = re.sub(r"(?:https?|wss?)://\S+", "<url>", text, flags=re.I)
    for pattern, mask in _MASKS:
        text = pattern.sub(mask, text)
    for ip in (_IP4, _IP6):
        text = ip.sub("<ip>", text)
    for word in sorted((w for w in secrets if len(w) >= 3), key=len, reverse=True):
        text = re.sub(re.escape(word), "<name>", text, flags=re.I)
    return (text, "") if text else (None, "empty")


def _code_at(value: Any, _secrets: Collection[str]) -> tuple[Any, str]:
    return (value, "") if isinstance(value, str) and _CODE_AT.match(value) else (None, "not a place in the code")


# the pools' and robots' presets (pool_detect.py, robot_detect.py); the
# appliances' are appliance_presets.PRESETS
_OTHER_PRESETS = frozenset({"iaqualink", "screenlogic", "omnilogic", "matter", "vacuum"})


def _preset(value: Any, _secrets: Collection[str]) -> tuple[Any, str]:
    """One of Room Tiles' own presets, by its id - checked against the list,
    not the home's words (an integration's title, "LG ThinQ", is in the
    home's words and in its preset's id, "lg_thinq_dryer")."""
    from .appliance_presets import PRESETS

    ok = isinstance(value, str) and (value in PRESETS or value in _OTHER_PRESETS)
    return (value, "") if ok else (None, "not a preset")


def _build(value: Any, _secrets: Collection[str]) -> tuple[Any, str]:
    return (value, "") if isinstance(value, str) and _BUILD.match(value) else (None, "not a build")


def _amount(value: Any, _secrets: Collection[str]) -> tuple[Any, str]:
    """A plain number: bytes, seconds, kilobytes (never a time of day)."""
    kept, why = _number(value)
    return (None, why) if why else (kept, "")


def _size(value: Any, _secrets: Collection[str]) -> tuple[Any, str]:
    return (value, "") if isinstance(value, str) and _SIZE.match(value) else (None, "not a size")


def _rel_time(value: Any, _secrets: Collection[str]) -> tuple[Any, str]:
    """Seconds since the report's earliest time (never a time of day)."""
    kept, why = _number(value)
    if why:
        return None, why
    if kept < 0 or kept > 400 * 86400:
        return None, "not a time since the start"
    return round(float(kept), 1), ""


def _count(value: Any, _secrets: Collection[str]) -> tuple[Any, str]:
    ok = isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10**7
    return (value, "") if ok else (None, "not a count")


_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _description(value: Any, _secrets: Collection[str]) -> tuple[Any, str]:
    """The user's own words (Report a problem). Not checked like the data -
    it's what they wrote, sent as written; the check step points out what
    looks like a name, address or time (`description_warnings`) and they
    decide."""
    if not isinstance(value, str):
        return None, "not text"
    text = _CONTROL.sub("", value).strip()[:MAX_DESCRIPTION]
    return (text, "") if text else (None, "empty")


def _bool(value: Any, _secrets: Collection[str]) -> tuple[Any, str]:
    return (value, "") if isinstance(value, bool) else (None, "not yes / no")


def _enum(options: frozenset[str]) -> Leaf:
    def check(value: Any, _secrets: Collection[str]) -> tuple[Any, str]:
        return (value, "") if isinstance(value, str) and value in options else (None, "not one of the choices")

    return check


@dataclass(frozen=True)
class AnyKey:
    """A map whose keys are checked words (attributes, a checklist)."""

    value: Any
    max_items: int = MAX_ATTRS


# ---- the report layout (the allow-list) ----------------------------------------------

_STATE_ROW = {"role": _role, "state": _state, "attributes": AnyKey(_state)}
REPORT: dict[str, Any] = {
    "kind": _enum(KINDS),
    "room_tiles": _version,
    "home_assistant": _version,
    "integration": {"domain": _domain, "version": _version},
    "device": {"manufacturer": _model, "model": _model, "model_id": _model, "hw_version": _version, "sw_version": _version},
    "kind_of_device": _enum(frozenset({"washer", "dryer", "dishwasher", "pool", "vacuum"})),  # (Room Tiles' own kind)
    "preset": _preset,
    "layout": _role,  # (a pool system's: shared / separate / pool / spa)
    "outcome": _enum(OUTCOMES),
    "checklist": AnyKey(_enum(FEATURE_ANSWERS)),  # (a model report: each feature)
    "states": [_STATE_ROW],
    "answers": [{"role": _role, "state": _state, "answer": _enum(ANSWERS)}],
    "recording": [{"t": _rel_time, **_STATE_ROW}],
    "description": _description,
    "cycle": {"from": _enum(CYCLE_FROM), "ended": _enum(CYCLE_ENDS), "trimmed": _count},
    "events": [{"t": _rel_time, "event": _enum(EVENTS)}],
    # Send feedback - a bug: where it happened, the touch panel's board and
    # firmware, the browser (name, major version, system, window size)
    "where": _enum(WHERE),
    "panel": {
        "board": _board,
        "firmware": _version,
        "build": _build,  # (a hand-built or unknown image: its build, cut short)
        "hand_built": _bool,
        "wifi_chip": _version,
        "online": _bool,
        "reset_reason": _state,  # (why it last started: ESPHome's words)
        "uptime_s": _amount,
        "restarts_24h": [{"ago_s": _amount}],  # (how long ago - never when)
        "heap_free": _amount,
        "heap_block": _amount,
        "psram_free": _amount,
        "assets_kb": _amount,
    },
    "browser": {"name": _role, "version": _version, "os": _role, "window": _size},
    # ... and Room Tiles' own recent errors there (frontend errors.ts)
    "errors": [{"ago_s": _amount, "message": _error_text, "where": _code_at}],
}


# ---- times: deltas from the report's earliest -----------------------------------------
#
# A wall-clock time says when someone was home; how far apart two moments
# are doesn't. Every full timestamp in a report (a date with a time, epoch
# seconds or milliseconds) becomes its distance from the report's EARLIEST
# one - which isn't sent itself: a recording's "t" in seconds, any other
# value as "+<seconds>s". A clock time with no date ("1:05 pm") can't be
# placed and still tells the time of day: dropped.

_ISO_FULL = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$")


def _as_epoch(value: Any) -> float | None:
    """Seconds since 1970 if `value` is a full timestamp, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        if 1e9 <= value < 1e11:
            return float(value)
        if 1e12 <= value < 1e14:
            return float(value) / 1000.0
        return None
    if isinstance(value, str) and _ISO_FULL.match(value.strip()):
        try:
            when = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when.timestamp()
    return None


def _times(value: Any, out: list[float]) -> None:
    """Every full timestamp anywhere in `value`."""
    if isinstance(value, dict):
        for item in value.values():
            _times(item, out)
    elif isinstance(value, list):
        for item in value:
            _times(item, out)
    else:
        when = _as_epoch(value)
        if when is not None:
            out.append(when)


def _relative(value: Any, base: float, key: str | None = None) -> Any:
    """`value` with every full timestamp as its distance from `base`."""
    if isinstance(value, dict):
        return {k: _relative(v, base, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_relative(v, base) for v in value]
    when = _as_epoch(value)
    if when is None:
        return value
    delta = round(when - base, 1)
    if key == "t":  # (a recording row's time: seconds)
        return delta
    text = f"{delta:.1f}".rstrip("0").rstrip(".")
    return f"+{text}s"


def _walk(value: Any, spec: Any, path: str, secrets: Collection[str], dropped: list[tuple[str, str]]) -> tuple[Any, bool]:
    """(kept value, kept?) for `value` against `spec`."""
    if isinstance(spec, dict):
        if not isinstance(value, dict):
            dropped.append((path, "not the expected form"))
            return None, False
        out: dict[str, Any] = {}
        for key, item in value.items():
            where = f"{path}.{key}" if path else str(key)
            if key not in spec:
                dropped.append((where, "not something reports send"))
                continue
            kept, ok = _walk(item, spec[key], where, secrets, dropped)
            if ok and not (isinstance(spec[key], AnyKey) and kept == {}):  # (nothing left in a map: left out)
                out[key] = kept
        return out, True
    if isinstance(spec, list):
        if not isinstance(value, list):
            dropped.append((path, "not the expected form"))
            return None, False
        if len(value) > MAX_LIST:
            dropped.append((f"{path}[{MAX_LIST}:]", "too long"))
            value = value[:MAX_LIST]
        out_list = []
        for i, item in enumerate(value):
            kept, ok = _walk(item, spec[0], f"{path}[{i}]", secrets, dropped)
            if ok and kept != {}:
                out_list.append(kept)
        return out_list, True
    if isinstance(spec, AnyKey):
        if not isinstance(value, dict):
            dropped.append((path, "not the expected form"))
            return None, False
        out_map: dict[str, Any] = {}
        for key, item in value.items():
            where = f"{path}.{key}"
            if not isinstance(key, str) or not _KEY.match(key) or _DENY_KEYS.search(key) or _deny_in(key, secrets):
                dropped.append((where, "a name, place, id or time"))
                continue
            if len(out_map) >= spec.max_items:
                dropped.append((where, "too many"))
                continue
            kept, why = spec.value(item, secrets)
            if why:
                dropped.append((where, why))
                continue
            out_map[key] = kept
        return out_map, True
    kept, why = spec(value, secrets)
    if why:
        dropped.append((path, why))
        return None, False
    return kept, True


def scrub(doc: dict[str, Any], secrets: Iterable[str] = ()) -> Scrubbed:
    """`doc` as it may be sent: only the report layout's fields, every value
    checked; `secrets` (lower case, from `secrets_from_hass`) never appear;
    every timestamp as its distance from the earliest."""
    words = {s.lower() for s in secrets if isinstance(s, str) and len(s.strip()) >= 3}
    found: list[float] = []
    _times(doc, found)
    if found:  # (every time as its distance from the earliest)
        doc = _relative(doc, min(found))
    dropped: list[tuple[str, str]] = []
    kept, _ok = _walk(doc, REPORT, "", words, dropped)
    return Scrubbed(kept or {}, dropped)


# ---- what's in it (the confirmation screen) ------------------------------------------


def summary(doc: dict[str, Any]) -> list[str]:
    """What a scrubbed report holds, as wording keys (report.has.*) - the
    confirmation screen says these, and what it never holds."""
    out = []
    if doc.get("device"):
        out.append("report.has.device")
    if doc.get("integration"):
        out.append("report.has.integration")
    if doc.get("room_tiles") or doc.get("home_assistant"):
        out.append("report.has.versions")
    if doc.get("states"):
        out.append("report.has.states")
    if doc.get("answers"):
        out.append("report.has.answers")
    if doc.get("recording"):
        out.append("report.has.recording")
    if any(r.get("role") == "room_tiles" for r in doc.get("recording") or []):
        out.append("report.has.shown")
    if any(str(e.get("event", "")).startswith("ha_") for e in doc.get("events") or []):
        out.append("report.has.restarts")
    if doc.get("checklist") or doc.get("outcome"):
        out.append("report.has.checklist")
    if doc.get("description"):
        out.append("report.has.description")
    if doc.get("where"):
        out.append("report.has.where")
    if doc.get("panel"):
        out.append("report.has.panel")
    if doc.get("browser"):
        out.append("report.has.browser")
    if doc.get("errors"):
        out.append("report.has.errors")
    return out


# ---- the user's own words: what to point out ------------------------------------------

_ADDRESS = re.compile(
    r"\b\d{1,6}\s+(?:[A-Za-z]+\s+){1,3}(?:st|street|ave|avenue|rd|road|dr|drive|ln|lane|blvd|boulevard|ct|court|way|pl|place)\b\.?",
    re.I,
)
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d\b")
_WARN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_URL, "address"),
    (_EMAIL, "email"),
    (_IP4, "address"),
    (_MAC, "id"),
    (_UUID, "id"),
    (_LONG_HEX, "id"),
    (_ADDRESS, "address"),
    (_PHONE, "phone"),
    (_ISO_TIME, "time"),
    (_TOKENISH, "id"),
)


def description_warnings(text: str, secrets: Iterable[str]) -> list[dict[str, str]]:
    """What in the user's own words looks like it ties the report to them:
    [{"text": as they wrote it, "why": name / address / email / phone /
    time / id}], in the order written. Pointed out, never removed for them."""
    if not text:
        return []
    found: list[tuple[int, int, str]] = []
    low = text.lower()
    for word in sorted({s.lower() for s in secrets if isinstance(s, str) and len(s.strip()) >= 3}, key=len, reverse=True):
        for m in re.finditer(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", low):
            found.append((m.start(), m.end(), "name"))
    for pattern, why in _WARN_PATTERNS:
        for m in pattern.finditer(text):
            # (a phone number: 7+ digits, not a version number like 2026.11.2)
            if why == "phone" and (sum(ch.isdigit() for ch in m.group()) < 7 or re.fullmatch(r"[\d.]+", m.group())):
                continue
            found.append((m.start(), m.end(), why))
    found.sort(key=lambda f: (f[0], -(f[1] - f[0])))
    out: list[dict[str, str]] = []
    end = -1
    seen: set[str] = set()
    for a, b, why in found:
        if a < end:  # (inside one already pointed out)
            continue
        end = b
        piece = text[a:b].strip()
        if piece and piece.lower() not in seen:
            seen.add(piece.lower())
            out.append({"text": piece, "why": why})
    return out


# ---- the home's own words ------------------------------------------------------------


def _words(text: str | None) -> set[str]:
    """A name and its parts ("Jamie's Office" -> "jamie's office", "jamie",
    "office"): any of them in a value means it isn't sent. Parts shorter
    than 4 letters and everyday room / device words are kept out (they'd
    drop real states like "off" or "door")."""
    if not text:
        return set()
    low = text.strip().lower()
    out = {low} if len(low) >= 3 else set()
    for part in re.split(r"[\s_.\-'’()]+", low):
        if len(part) >= 4 and part not in COMMON_WORDS:
            out.add(part)
    return out


# words in many names that are also device words / states (never treated as
# the home's own)
COMMON_WORDS = frozenset(
    {
        "room", "office", "kitchen", "bedroom", "bathroom", "living", "dining", "garage", "laundry", "basement",
        "attic", "hall", "hallway", "porch", "patio", "yard", "front", "back", "upstairs", "downstairs", "main",
        "light", "lights", "lamp", "switch", "sensor", "door", "window", "lock", "fan", "pool", "spa", "washer",
        "dryer", "dishwasher", "vacuum", "status", "state", "power", "energy", "temperature", "humidity", "time",
        "remaining", "cycle", "mode", "program", "running", "done", "idle", "home", "away", "open", "closed",
        "level", "battery", "water", "heater", "pump", "filter", "clean", "cleaning", "docked", "error", "none",
        "unknown", "unavailable", "true", "false", "left", "right", "outside", "inside", "panel", "tiles",
    }
)


def secrets_from_hass(hass: Any) -> set[str]:
    """Everything that would tie a report to this home: the names the user
    gave (areas, floors, devices, entities, the home, accounts in config
    entry titles), entity ids, unique ids, device and config entry ids,
    serial numbers, hardware addresses, host names. (Not the integrations'
    own words - an entity they named "Spin speed" - which are device words.)"""
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    out: set[str] = set()
    out |= _words(hass.config.location_name)
    for area in ar.async_get(hass).async_list_areas():
        out |= _words(area.name) | {area.id.lower()}
        for alias in area.aliases or ():
            out |= _words(alias)
    try:
        from homeassistant.helpers import floor_registry as fr

        for floor in fr.async_get(hass).async_list_floors():
            out |= _words(floor.name)
    except ImportError:  # pragma: no cover - older HA
        pass
    devices = dr.async_get(hass)
    # (iterating the registry: its entries - or, before HA made that the way,
    # their ids; `.devices.values()` is deprecated)
    for item in list(devices.devices):
        dev = devices.async_get(item) if isinstance(item, str) else item
        if dev is None:
            continue
        out |= _words(dev.name) | _words(dev.name_by_user) | {dev.id.lower()}
        if dev.serial_number:
            out.add(str(dev.serial_number).lower())
        # identifiers / connections: (domain, id) - some integrations add
        # more parts; every part after the domain counts
        for ident in dev.identifiers:
            for part in tuple(ident)[1:]:
                if isinstance(part, str) and len(part) >= 4:
                    out.add(part.lower())
        for conn in dev.connections:
            for part in tuple(conn)[1:]:
                if isinstance(part, str) and part:
                    out.add(part.lower())
    for ent in er.async_get(hass).entities.values():
        out.add(ent.entity_id.lower())
        # (an object id of several parts or with digits is the home's -
        # "edith_dryer_status"; a single word - "speed" - is the
        # integration's, and would drop real states)
        obj = ent.entity_id.split(".", 1)[1].lower()
        if "_" in obj or any(ch.isdigit() for ch in obj):
            out.add(obj)
        # (only names the user typed: an integration's own entity names -
        # "Spin speed" - are device words, not the home's)
        out |= _words(ent.name)
        if ent.unique_id and len(str(ent.unique_id)) >= 4:
            out.add(str(ent.unique_id).lower())
    for state in hass.states.async_all():
        out.add(state.entity_id.lower())
    for entry in hass.config_entries.async_entries():
        out.add(entry.entry_id.lower())
        out |= _words(entry.title)
        data = entry.data if isinstance(entry.data, Mapping) else {}  # (a read-only mapping, not a dict)
        for key in ("host", "hostname", "ip_address", "address", "username", "email"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                out.add(value.strip().lower())
    return {w for w in out if len(w) >= 3 and w not in COMMON_WORDS}


# ---- the GitHub issue ------------------------------------------------------------------

# where reports go: a new issue on the Room Tiles repository (manifest.json
# "issue_tracker"), opened in the user's browser with the report filled in -
# they review it there and press Submit themselves
ISSUES_NEW = "https://github.com/rustyk0-byte/room-tiles/issues/new"
_KIND_TITLE = {
    "model": "Model report",
    "unknown_state": "Unknown state",
    "recording": "Recorded cycle",
    "problem": "Problem",
    "bug": "Bug",
    "idea": "Idea",
    "question": "Question",
    "test": "Test report",
}


def _pretty(doc: dict[str, Any]) -> str:
    """The report as JSON, a list of rows (a recording) one row per line -
    a whole cycle stays readable and fits in an issue."""
    import json

    items = list(doc.items())
    lines = ["{"]
    for i, (key, value) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            lines.append(f"  {json.dumps(key)}: [")
            for j, row in enumerate(value):
                tail = "," if j < len(value) - 1 else ""
                lines.append("    " + json.dumps(row, ensure_ascii=False) + tail)
            lines.append("  ]" + comma)
        else:
            text = json.dumps(value, indent=2, ensure_ascii=False).replace("\n", "\n  ")
            lines.append(f"  {json.dumps(key)}: {text}{comma}")
    lines.append("}")
    return "\n".join(lines)


# a kind's issue form (.github/ISSUE_TEMPLATE/<name>.yml - it applies the
# kind's label): the report goes in its "report" field
_TEMPLATE = {
    "model": "model.yml",
    "unknown_state": "unknown_state.yml",
    "problem": "problem.yml",
    "bug": "bug.yml",
    "idea": "idea.yml",
    "question": "question.yml",
}
FORM_FIELD = "report"
_OUTCOME_TITLE = {"works": "works", "partly": "partly works", "broken": "doesn't work"}
_WORDS_HEAD = {
    "model": "**Notes** (in the sender's own words):",
    "problem": "**What went wrong** (in the sender's own words):",
    "bug": "**What happened** (in the sender's own words):",
    "idea": "**The idea** (in the sender's own words):",
    "question": "**The question** (in the sender's own words):",
}
_TITLE_WORDS = 60


def _first_words(text: str) -> str:
    """A title from the user's words: their first line, cut at a word."""
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    if len(line) <= _TITLE_WORDS:
        return line
    cut = line[:_TITLE_WORDS].rsplit(" ", 1)[0] or line[:_TITLE_WORDS]
    return cut.rstrip(",.;:-") + "…"


def issue(doc: dict[str, Any], kind: str) -> dict[str, str]:
    """The issue for a scrubbed report: its title and body (the report as
    JSON in a code block - the exact payload the user saw; the user's own
    words above it, quoted), and the issue form it goes in (`template`, its
    `field`) - none for a test report."""
    words = str(doc.get("description") or "")
    if kind in FEEDBACK:
        title = f"{_KIND_TITLE[kind]}: {_first_words(words)}" if words else _KIND_TITLE[kind]
    else:
        device = doc.get("device") or {}
        what = " ".join(v for v in (device.get("manufacturer"), device.get("model")) if v) or doc.get("kind_of_device") or "Room Tiles"
        how = _OUTCOME_TITLE.get(str(doc.get("outcome"))) if kind == "model" else None
        title = f"{_KIND_TITLE.get(kind, 'Report')}{f' ({how})' if how else ''}: {what}"
    data = {k: v for k, v in doc.items() if k != "description"}
    said = ""
    if words:
        quoted = "\n".join("> " + line if line else ">" for line in words.splitlines())
        said = _WORDS_HEAD.get(kind, _WORDS_HEAD["problem"]) + "\n\n" + quoted + "\n\n"
    body = (
        said + "Sent from Room Tiles. Scrubbed before it was shown: no names, "
        "addresses, serial numbers or times of day - times are seconds from the start.\n\n"
        "```json\n" + _pretty(data) + "\n```\n"
    )
    out = {"title": title, "body": body, "url": ISSUES_NEW}
    if kind in _TEMPLATE:
        out.update(template=_TEMPLATE[kind], field=FORM_FIELD)
    return out


def sample_report() -> dict[str, Any]:
    """A developer build's test report (settings menu > Test report): a
    recorded cycle full of what must NOT go out - names, an entity id, a
    serial, a MAC, an IP, an email, wall-clock times - to see the scrubber
    and the confirmation screen at work."""
    return {
        "kind": "recording",
        "device": {"manufacturer": "GE Appliances", "model": "PTD9000SN", "serial_number": "DRY0099887766", "name": "Grandma's Dryer"},
        "integration": {"domain": "ge_home", "version": "2026.10.1"},
        "kind_of_device": "dryer",
        "entity_id": "sensor.grandmas_dryer_status",
        "recording": [
            {"t": "2026-11-17T13:00:00+00:00", "role": "status", "state": "idle", "attributes": {"friendly_name": "Grandma's Dryer"}},
            {"t": "2026-11-17T13:01:30+00:00", "role": "status", "state": "drying",
             "attributes": {"cycle": "cotton", "wifi_mac": "aa:bb:cc:dd:ee:ff", "host": "192.168.1.40"}},
            {"t": "2026-11-17T14:02:05+00:00", "role": "status", "state": "done",
             "attributes": {"finished_at": "2026-11-17T14:02:00+00:00", "owner": "grandma@example.com"}},
        ],
        "answers": [{"role": "status", "state": "steam_fresh", "answer": "not_running"}],
        "notes": "This is Grandma's dryer in the basement at 12 Main St.",
    }


# ---- building a report from Room Tiles' own data -------------------------------------
#
# The dashboard never hands over entity ids or names: it says which appliance
# (and unit), the state and the answer; HA builds the report from the device
# itself - its brand and model, the integration and its version - and the
# scrubber still checks all of it.

# an answer on the Appliances page (the phase it saved) -> what the report says
_PHASE_ANSWER = {"washing": "running", "drying": "running", "running": "running", "paused": "paused", "off": "off", "error": "error"}


async def device_facts(hass: Any, entity_id: str) -> dict[str, Any]:
    """The device behind an entity: brand, model, versions; its integration
    and that integration's version (a custom one's manifest; a built-in one:
    HA's own)."""
    from homeassistant.const import __version__ as HA_VERSION
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from homeassistant.loader import async_get_integration

    out: dict[str, Any] = {}
    ent = er.async_get(hass).async_get(entity_id)
    if ent is None:
        return out
    try:
        integration = await async_get_integration(hass, ent.platform)
        version = str(integration.version) if integration.version else HA_VERSION
    except Exception:  # noqa: BLE001 - an integration that can't be looked up: its name only
        version = None
    out["integration"] = {"domain": ent.platform, **({"version": version} if version else {})}
    dev = dr.async_get(hass).async_get(ent.device_id) if ent.device_id else None
    if dev is not None:
        device = {
            "manufacturer": dev.manufacturer,
            "model": dev.model,
            "model_id": getattr(dev, "model_id", None),
            "hw_version": dev.hw_version,
            "sw_version": dev.sw_version,
        }
        out["device"] = {k: v for k, v in device.items() if v}
    return out


# a touch panel's own diagnostics (firmware room_tiles.yaml: ESPHome's debug
# and uptime sensors), by the name the firmware gave them
_PANEL_SENSORS = {
    "Reset Reason": "reset_reason",
    "Uptime": "uptime_s",
    "Heap Free": "heap_free",
    "Heap Max Block": "heap_block",
    "PSRAM Free": "psram_free",
    "Asset Area": "assets_kb",
}
_SECONDS = {"s": 1, "min": 60, "h": 3600, "d": 86400}


async def panel_facts(hass: Any, store: Any, device_id: str) -> dict[str, Any]:
    """A bug on a touch panel: its board and firmware, its Wi-Fi chip's
    version, whether it's online, why it last started, its uptime and memory
    headroom, and its restarts over the last 24 hours (how long ago each was
    - never a time of day). Empty: no such panel."""
    import time
    from datetime import timedelta

    from homeassistant.helpers import entity_registry as er
    from homeassistant.util import dt as dt_util

    from .panels import find_panels

    if device_id not in find_panels(hass):
        return {}
    out: dict[str, Any] = {}
    running = store.fw_reports.get(device_id)
    if running is not None:
        out["board"] = running.board
        image = store.fw_images.get(running.board)
        if image is not None and image.build == running.build:
            out["firmware"] = image.label
        else:
            out["build"] = running.build[:8]
        if not running.generic:
            out["hand_built"] = True
    uptime_entity = None
    states = []
    for ent in er.async_entries_for_device(er.async_get(hass), device_id):
        state = hass.states.get(ent.entity_id)
        if state is None:
            continue
        states.append(state.state)
        name = ent.original_name or ""
        if ent.domain == "update" and name == "Wi-Fi Chip Firmware":
            if state.attributes.get("installed_version"):
                out["wifi_chip"] = str(state.attributes["installed_version"])
            continue
        key = _PANEL_SENSORS.get(name)
        if key is None or state.state in ("unknown", "unavailable"):
            continue
        if key == "reset_reason":
            out[key] = state.state
            continue
        try:
            value = float(state.state)
        except ValueError:
            continue
        if key == "uptime_s":
            value *= _SECONDS.get(str(state.attributes.get("unit_of_measurement") or "s"), 1)
            uptime_entity = ent.entity_id
        out[key] = round(value)
    out["online"] = any(s not in ("unknown", "unavailable") for s in states)
    if uptime_entity is not None:
        # the restarts: the uptime going down (the recorder's history)
        try:
            from homeassistant.components.recorder import get_instance, history

            now = dt_util.utcnow()
            found = await get_instance(hass).async_add_executor_job(
                lambda: history.state_changes_during_period(
                    hass, now - timedelta(hours=24), now, uptime_entity, no_attributes=True
                )
            )
            last = None
            ago = []
            for st in found.get(uptime_entity, []):
                try:
                    v = float(st.state)
                except ValueError:
                    continue
                if last is not None and v < last:
                    ago.append({"ago_s": round(time.time() - st.last_changed.timestamp())})
                last = v
            out["restarts_24h"] = ago[-20:]
        except Exception:  # noqa: BLE001 - no recorder / its history: no restarts list
            pass
    return out


async def build_unknown_state(hass: Any, data: Any, appliance_id: str, unit_id: str, state: str, phase: str) -> dict[str, Any] | None:
    """"Also tell Room Tiles": a state an appliance reported that its preset
    didn't know, and what the user said it means. None: no such appliance."""
    appliance = next((a for a in data.appliances if a.id == appliance_id), None)
    unit = next((u for u in appliance.units if u.id == unit_id), None) if appliance else None
    if unit is None:
        return None
    draft: dict[str, Any] = {
        "kind_of_device": unit.appliance,
        "preset": unit.preset,
        "answers": [{"role": "status", "state": state, "answer": _PHASE_ANSWER.get(phase, "unknown")}],
    }
    draft.update(await device_facts(hass, unit.status))
    # the status sensor's own list of states, when it has one (an enum
    # sensor): the preset can learn them all at once
    st = hass.states.get(unit.status)
    options = st.attributes.get("options") if st is not None else None
    if isinstance(options, list) and options:
        draft["states"] = [{"role": "status", "state": state, "attributes": {"options": options}}]
    return draft
