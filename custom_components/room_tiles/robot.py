"""Robot vacuum profiles: what the vacuum tile shows, for any brand.

Pure logic, no HA (tested in tests/test_robot.py); sensor.py runs it. Ported
from the author's Matic Alert / Matic Tile template sensors (2026-10/11).

Every vacuum gets its HA vacuum state; robots that report Matter's RVC
operational error (Matter vacuums - Matic...) also get ALERTS, sorted into
"attention" (something the user must refill / empty / put back - shown
amber as "needs you", not as a fault) and "error" (a real fault: stuck,
can't find the dock...).

The tile text ("class|status|current|queue") is what the panels read today;
current room + queue stay empty until the room queue add-on (clean_area).
"""

from __future__ import annotations

from dataclasses import dataclass

from .wording import Word, has, render, tile_words, w

# Matter RVC operational error ids (HA's matter integration)
NO_ALERT = frozenset({"no_error", "unknown", "unavailable", "", "none", "water_tank_lid_open"})
ATTENTION = frozenset(
    {"water_tank_empty", "water_tank_missing", "dust_bin_full", "dust_bin_missing", "mop_cleaning_pad_missing"}
)
# alert words: the wording tokens "robot.alert.<id>" (wording/<lang>.json)

# HA vacuum states the tile shows as they are
SHOWN = ("cleaning", "paused", "returning", "docked")
CLEAN_AREA = 16384  # VacuumEntityFeature.CLEAN_AREA (HA 2026.3)


@dataclass
class RobotView:
    cls: str  # attention / error / cleaning / paused / returning / docked / idle / offline
    status: str
    alert: str  # none / attention / error
    alert_text: str
    code: str
    status_word: Word = ""  # the status line as a word (each display's language)
    alert_word: Word = ""


def alert_word_of(code: str | None) -> tuple[str, Word]:
    """A Matter RVC error id -> (none / attention / error, its words)."""
    c = (code or "").strip().lower()
    if c in NO_ALERT:
        return "none", ""
    word = w(f"robot.alert.{c}") if has(f"robot.alert.{c}") else c.replace("_", " ").capitalize()
    return ("attention" if c in ATTENTION else "error"), word


def alert_of(code: str | None) -> tuple[str, str]:
    """A Matter RVC error id -> (none / attention / error, its words in HA's language)."""
    alert, word = alert_word_of(code)
    return alert, render(word)


def view(vacuum_state: str | None, error_code: str | None = None, room: str = "") -> RobotView:
    """The tile's class and status line."""
    vs = (vacuum_state or "").lower()
    alert, text = alert_word_of(error_code)
    if vs in ("unavailable", "unknown", ""):
        cls = "offline"
    elif alert == "attention":
        cls = "attention"
    elif vs == "error" or alert == "error":
        cls = "error"
    elif vs in SHOWN:
        cls = vs
    else:
        cls = "idle"
    status: Word
    if cls == "attention":
        status = text
    elif cls == "error":
        status = w("robot.error_text", text=text) if text else w("robot.error")
    elif cls == "cleaning":
        status = w("robot.cleaning_room", room=room) if room else w("robot.cleaning")
    elif cls == "paused":
        status = w("robot.paused_room", room=room) if room else w("robot.paused")
    elif cls == "returning":
        status = w("robot.returning")
    elif cls == "offline":
        status = w("robot.offline")
    else:
        status = w(f"robot.{cls}")
    return RobotView(cls, render(status), alert, render(text), (error_code or "").strip(), status, text)


# MIRRORED: read by frontend/src/rules.ts vacuumStatus and firmware/components/room_tiles/
# board_kinds.cpp + map_queue.cpp - change the format in all three
def tile_text(v: RobotView, current: str = "", queue: list[str] | None = None) -> str:
    """The panels' vacuum tile text: "class|status|current|queue"."""
    return f"{v.cls}|{v.status}|{current}|{','.join(queue or [])}"


def tile_words_of(v: RobotView) -> str:
    """Its words (the status), for each display to put in its own language."""
    return tile_words({"0.1": v.status_word})


# ---- the room queue (generic: HA's vacuum.clean_area) -------------------------
#
# Ported from this project's YAML Matic queue (scripts matic_add_room_to_queue
# / matic_start_queue / matic_pause_queue / matic_skip_to_next_room /
# matic_stop_and_clear_queue, automations "advance to next room" and "error
# handling"), with what running it taught:
# - a room is done when the vacuum turns to RETURNING with no alert - the
#   next room goes out at once (it never docks in between; a return trip
#   that fails can't stop the queue). A vacuum that skips "returning" and
#   goes straight from cleaning to docked / idle counts too.
# - clean_area is sent BEFORE a room is taken off the queue: a refused
#   command (stale segments...) leaves the queue as it was.
# - Start: paused -> resume; an alert with a room in progress -> send that
#   room again; else the next room - but only redirecting a vacuum that's
#   already on a room when a PERSON pressed it (`manual`): an add that
#   starts the queue must not redirect a clean that hasn't reported
#   "cleaning" yet (the two-NFC-tags race, 2026-09-03).
# - adding a room never resumes a paused vacuum; a room already being
#   cleaned isn't queued again; one already queued moves to the end.
# - an alert (attention / error) while a room is in progress pauses the
#   queue on that room - no advancing; 12 h unresolved: cancel and clear.

QUEUE_GIVE_UP_S = 12 * 3600

# How a queued room is cleaned: vacuum / mop / both. For now every room is
# cleaned with both (per-room choices come later).
CLEAN_MODES = ("vacuum", "mop", "both")
DEFAULT_CLEAN_MODE = "both"


def mode_option(options: list[str], mode: str) -> str | None:
    """The vacuum's clean-mode option for vacuum / mop / both (Matter's RVC
    clean mode select: "Quick Vacuum", "Vacuum", "Deep Vacuum+Mop"...): by
    the words in it - the plain one first (no Quick / Deep: the shortest)."""
    def kind(o: str) -> str | None:
        low = o.lower()
        v, m = "vacuum" in low or "vac" in low or "sweep" in low, "mop" in low
        return "both" if v and m else "vacuum" if v else "mop" if m else None

    found = [o for o in options if kind(o) == mode]
    return min(found, key=len) if found else None


@dataclass
class QueueStep:
    """What the queue asks of the vacuum: clean `area` / resume / pause /
    go home (`dock`)."""

    action: str  # clean / resume / pause / dock
    area: str | None = None
    mode: str = DEFAULT_CLEAN_MODE  # clean: vacuum / mop / both


@dataclass
class RoomQueue:
    queue: list[str]
    current: str | None = None
    error_since: float | None = None

    def add(self, area: str) -> None:
        if area == self.current:
            return
        self.queue = [a for a in self.queue if a != area] + [area]

    def remove(self, area: str) -> None:
        self.queue = [a for a in self.queue if a != area]

    def move(self, area: str, index: int) -> None:
        if area not in self.queue:
            return
        rest = [a for a in self.queue if a != area]
        k = max(0, min(len(rest), index))
        self.queue = rest[:k] + [area] + rest[k:]

    def start(self, vacuum_state: str | None, alert: str, manual: bool = True) -> QueueStep | None:
        vs = (vacuum_state or "").lower()
        if vs == "paused":
            return QueueStep("resume")
        if alert != "none" and self.current:
            return QueueStep("clean", self.current)  # try that room again
        if vs == "cleaning":
            return None
        if (manual or not self.current) and self.queue:
            return QueueStep("clean", self.queue[0])
        return None

    def sent(self, area: str) -> None:
        """clean_area for `area` went out: it's the room in progress now."""
        self.current = area
        self.queue = [a for a in self.queue if a != area]

    def skip(self) -> QueueStep:
        return QueueStep("dock")  # back to base: "returning" moves on to the next room

    def stop_and_clear(self) -> QueueStep:
        self.queue = []
        self.current = None
        self.error_since = None
        return QueueStep("dock")

    def on_state(self, before: str | None, after: str | None, alert: str) -> QueueStep | None:
        """The vacuum's state changed: a room finished cleanly -> the next one
        (or the queue is done)."""
        b = (before or "").lower()
        a = (after or "").lower()
        done = alert == "none" and (
            (a == "returning" and b != "returning") or (b in ("cleaning",) and a in ("docked", "idle"))
        )
        if not done:
            return None
        if self.queue:
            return QueueStep("clean", self.queue[0])  # (current stays until it's sent)
        self.current = None
        return None

    def on_alert(self, alert: str, now: float) -> bool:
        """Track how long an alert has lasted with a room in progress; True =
        12 h unresolved: give up (the queue is cleared here)."""
        if alert == "none" or not self.current:
            self.error_since = None
            return False
        if self.error_since is None:
            self.error_since = now
        if now - self.error_since >= QUEUE_GIVE_UP_S:
            self.queue = []
            self.current = None
            self.error_since = None
            return True
        return False
