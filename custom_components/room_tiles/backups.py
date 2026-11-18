"""Room Tiles' copies in `<config>/room_tiles_backups/`: one before every
storage upgrade (`before-migration-*`), import (`before-import-*`) and
removal (`removed-*`, so removing Room Tiles by mistake can be undone).

- **Kept:** the newest KEEP of each kind; older ones go whenever a new one
  is written (`prune`).
- **Importable:** every copy goes back in with the import action. A removal
  or upgrade copy is HA's storage file - the setup inside a version wrapper,
  maybe from an older Room Tiles: `unwrap` takes the setup out and brings it
  up to this version (the storage migrations); an export is the setup
  itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .const import STORAGE_MINOR_VERSION, STORAGE_VERSION
from .migrate import migrate

KINDS = ("removed-", "before-migration-", "before-import-")
KEEP = 5


def prune(folder: Path, keep: int = KEEP) -> list[str]:
    """Delete all but the newest `keep` copies of each kind. Blocking; the
    names it deleted."""
    gone = []
    if not folder.is_dir():
        return gone
    for kind in KINDS:
        files = sorted(
            (f for f in folder.glob(f"{kind}*.json") if f.is_file()),
            key=lambda f: (f.stat().st_mtime, f.name),
            reverse=True,
        )
        for old in files[keep:]:
            try:
                old.unlink()
                gone.append(old.name)
            except OSError:
                pass
    return gone


def wrap(major: int, minor: int, doc: dict[str, Any]) -> dict[str, Any]:
    """A setup as HA's storage keeps it (with its version)."""
    return {"version": major, "minor_version": minor, "key": "room_tiles", "data": doc}


def unwrap(raw: Any) -> Any:
    """An importable setup from a file's contents: an export as it is; a
    storage file (removal / upgrade copy) unwrapped and brought up to this
    version. ValueError for one from a newer major version (another Room
    Tiles' format)."""
    if not (isinstance(raw, dict) and "data" in raw and "version" in raw):
        return raw
    major, minor = int(raw["version"]), int(raw.get("minor_version") or 1)
    if major != STORAGE_VERSION:
        raise ValueError(f"it's from another Room Tiles (storage version {major})")
    doc = raw["data"]
    if minor < STORAGE_MINOR_VERSION:
        doc = migrate(major, minor, doc, STORAGE_MINOR_VERSION)
    return doc
