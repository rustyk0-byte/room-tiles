"""Map backups (Map settings > Backups): a map's drawing, layers and
markers saved as they are - the safe way to try big changes. Restore puts
them back on the map; the map as it is then is backed up first ("before
restoring"), so a restore can be undone too. Nothing shows on the map
meanwhile; panels see a restore like any map edit.

Their own file (.storage/room_tiles.map_backups): in HA's backups with the
rest, never in exports or a panel's payload. MAX_PER_MAP per map, the
oldest going first; a map's backups go when the map does.
"""

from __future__ import annotations

import uuid
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import ops
from .const import MAP_BACKUPS_KEY
from .model import ModelError, RoomTilesData

MAX_PER_MAP = 10
# what a backup holds and a restore puts back: the drawing and its layers
# (the map's name and HA floor are its settings - they stay)
DRAWING = ("bounds", "wall_width", "walls", "windows", "openings", "shapes", "zones", "links", "layers")


def snapshot(data: RoomTilesData, map_id: str, auto: bool = False) -> dict[str, Any]:
    """A backup of the map as it is now."""
    m = data.map(map_id)
    if m is None:
        raise ModelError(f"no map '{map_id}'")
    d = m.as_dict()
    return {
        "id": uuid.uuid4().hex[:12],
        "map": map_id,
        "at": dt_util.utcnow().isoformat(timespec="seconds"),
        "auto": auto,
        "drawing": {k: d[k] for k in DRAWING if k in d},
        "markers": [
            {"entity": mk.entity, "x": mk.x, "y": mk.y, "layer": mk.layer, "show_name": mk.show_name}
            for mk in data.markers
            if mk.map == map_id
        ],
    }


def restore(data: RoomTilesData, backup: dict[str, Any]) -> tuple[str, ...]:
    """Put a backup back on its map (ops-style: changes `data`, returns the
    sections). Links to maps that are gone since are left out."""
    map_id = backup["map"]
    fields = dict(backup["drawing"])
    maps = {m.id for m in data.maps}
    fields["links"] = [lk for lk in fields.get("links") or [] if lk.get("to") in maps and lk.get("to") != map_id]
    sections = set(ops.set_map(data, map_id, fields))
    sections |= set(ops.set_markers(data, map_id, backup.get("markers") or []))
    return tuple(sorted(sections))


def summary(b: dict[str, Any]) -> dict[str, Any]:
    """A backup as the list shows it (no drawing)."""
    drawing = b.get("drawing") or {}
    return {
        "id": b["id"],
        "at": b["at"],
        "auto": bool(b.get("auto")),
        "layers": len(drawing.get("layers") or []),
        "markers": len(b.get("markers") or []),
    }


class MapBackups:
    """The backups, kept in their own file."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, 1, MAP_BACKUPS_KEY)
        self.items: list[dict[str, Any]] = []

    async def async_load(self) -> None:
        raw = await self._store.async_load() or {}
        self.items = [
            b
            for b in raw.get("backups") or []
            if isinstance(b, dict) and b.get("id") and b.get("map") and isinstance(b.get("drawing"), dict)
        ]

    def _save(self) -> None:
        self._store.async_delay_save(lambda: {"backups": self.items}, 1)

    def of_map(self, map_id: str) -> list[dict[str, Any]]:
        """A map's backups, newest first (the list is in the order they were
        made - two in the same second still keep theirs)."""
        return [b for b in reversed(self.items) if b["map"] == map_id]

    def get(self, backup_id: str) -> dict[str, Any] | None:
        return next((b for b in self.items if b["id"] == backup_id), None)

    def add(self, backup: dict[str, Any]) -> None:
        self.items.append(backup)
        keep = {b["id"] for b in self.of_map(backup["map"])[:MAX_PER_MAP]}
        self.items = [b for b in self.items if b["map"] != backup["map"] or b["id"] in keep]
        self._save()

    def remove(self, backup_id: str) -> None:
        self.items = [b for b in self.items if b["id"] != backup_id]
        self._save()

    def drop_map(self, map_id: str) -> None:
        """The map is gone: its backups too."""
        if any(b["map"] == map_id for b in self.items):
            self.items = [b for b in self.items if b["map"] != map_id]
            self._save()
