"""Restart needed? After an update (HACS or by hand) the new files are on
disk, but HA keeps running the code it loaded at startup until it restarts.
The dashboard's own files are served straight from disk, so they don't
count - only the integration's code and data files do.

The fingerprint of those files is taken once, when HA first imports this
module (an integration reload doesn't re-import it, so it can't hide an
update). Every few minutes it's compared with the files on disk; a change
sets `restart_needed` in the dashboard feed (its Restart bar) and raises a
fixable repair whose fix restarts HA - unless HACS already raised its own
restart repair for Room Tiles (one message, not two).
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN

DIR = Path(__file__).parent
SKIP_DIRS = {"frontend", "__pycache__", "brand", "panel_packs", "firmware_images"}  # served from disk / not code (packs: reloaded live, __init__.py)
CHECK_EVERY = timedelta(minutes=2)
ISSUE_RESTART = "restart_required"
HACS = "hacs"


def fingerprint(root: Path = DIR) -> tuple[tuple[str, int, int], ...]:
    """(path, size, modified) of every code / data file - cheap: no reading."""
    out: list[tuple[str, int, int]] = []
    for here, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for name in files:
            if name.endswith((".pyc", ".pyo")) or name.startswith("."):
                continue
            p = Path(here, name)
            try:
                st = p.stat()
            except OSError:
                continue  # mid-update
            out.append((str(p.relative_to(root)), st.st_size, st.st_mtime_ns))
    return tuple(sorted(out))


LOADED = fingerprint()  # at import = what this HA run is running


def hacs_asks_restart(hass: HomeAssistant) -> bool:
    """HACS's own "restart required" repair for Room Tiles is up."""
    for (domain, issue_id), issue in ir.async_get(hass).issues.items():
        if domain == HACS and issue_id.startswith("restart_required") and issue.issue_domain == DOMAIN and issue.active:
            return True
    return False


@callback
def async_start(hass: HomeAssistant, store: Any) -> Any:
    """Watch for an update until HA restarts (checked now, then every few
    minutes); returns the unsubscribe."""

    async def check(_now: Any = None) -> None:
        if not store.restart_needed:
            if await hass.async_add_executor_job(fingerprint) == LOADED:
                ir.async_delete_issue(hass, DOMAIN, ISSUE_RESTART)  # (one left from before)
                return
            store.restart_needed = True
            store.async_notify(("restart_needed",))
        # (again each time: HACS's own repair may come or go)
        if hacs_asks_restart(hass):
            ir.async_delete_issue(hass, DOMAIN, ISSUE_RESTART)
        else:
            ir.async_create_issue(
                hass,
                DOMAIN,
                ISSUE_RESTART,
                is_fixable=True,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_RESTART,
            )

    hass.async_create_background_task(check(), f"{DOMAIN} update check")
    return async_track_time_interval(hass, check, CHECK_EVERY)
