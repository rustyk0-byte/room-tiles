"""A developer build's demo home on a panel (DEV_BUILD only - for panel
screenshots: the landing page's pictures, never a real home's).

<config>/room_tiles_demo/ holds:
- panel.json   the demo home (tools/demo/make_demo.py writes it): what a
               panel is sent for it - areas, tiles, maps... - and its
               entities' states, as HA's ESPHome integration would send them
- panels.txt   the panels that show it: their names (or ESPHome node
               names), one a line

A listed panel keeps its own settings (theme, language, screen) and gets
the demo home instead of this one, its states with it (the firmware asks
HA for nothing then - a demo entity may share an id with a real one). What
it sends back (a tap, a setting) is never carried out. Unlisting it
restarts the panel back to the real home.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEMO_DIR = "room_tiles_demo"
# a payload's parts that are the home (the rest is the panel's own)
HOME_KEYS = ("areas", "entities", "catalog", "floors", "maps", "markers", "popups", "robots")


def esphome_value(value: Any) -> str:
    """A value as HA's ESPHome integration sends it to a panel (str(); a
    yes / no as on / off)."""
    if isinstance(value, bool):
        return "on" if value else "off"
    return str(value)


def states_of(states: Any) -> dict[str, dict[str, str]]:
    """HA states as the panel would get them: entity -> {"": state, attr: value}
    (an attribute that's None isn't sent)."""
    return {
        s.entity_id: {"": s.state, **{k: esphome_value(v) for k, v in s.attributes.items() if v is not None}}
        for s in states
    }


def home_of(payload: dict[str, Any], states: dict[str, dict[str, str]], area: str) -> dict[str, Any]:
    """What make_demo.py writes: the demo home's part of a panel payload,
    the area it opens in and its states."""
    return {"area": area, "home": {k: payload.get(k) for k in HOME_KEYS}, "states": states}


def read(folder: Path) -> tuple[set[str], dict[str, Any] | None]:
    """The panels listed and the demo home (None: not there, or unreadable)."""
    try:
        names = {ln.strip() for ln in (folder / "panels.txt").read_text(encoding="utf-8").splitlines() if ln.strip()}
    except OSError:
        names = set()
    try:
        home = json.loads((folder / "panel.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        home = None
    return names, home if isinstance(home, dict) and isinstance(home.get("home"), dict) else None


def fingerprint(folder: Path) -> tuple[tuple[str, int, int], ...]:
    out = []
    for name in ("panels.txt", "panel.json"):
        try:
            st = (folder / name).stat()
        except OSError:
            continue
        out.append((name, st.st_mtime_ns, st.st_size))
    return tuple(out)


def shows_demo(names: set[str], home: dict[str, Any] | None, dev: Any) -> bool:
    return home is not None and (dev.name in names or dev.node in names)


def apply(real: dict[str, Any], home: dict[str, Any]) -> dict[str, Any]:
    """The panel's payload with the demo home in it: its own settings stay
    (theme, language...); the area, the home and its states are the demo's."""
    out = {**real, **home["home"]}
    panel = dict(real.get("panel") or {})
    areas = home["home"].get("areas") or []
    area = next((a for a in areas if a.get("id") == home.get("area")), areas[0] if areas else None)
    panel.update({
        "area": area.get("id") if area else None,
        "area_set": True,
        "layout": (area or {}).get("layout") or panel.get("layout") or "5x2",
        "room_lights": [],  # (its real room's lights: nothing to do with the demo)
        "room": "",
    })
    out["panel"] = panel
    out["found"] = 0
    out.pop("firmware", None)  # (no updates offered meanwhile)
    out["demo"] = {"states": home.get("states") or {}}
    return out
