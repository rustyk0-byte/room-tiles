"""Load the integration's theme packager (custom_components/room_tiles/themes)
without Home Assistant: the build scripts need only Pillow. The integration
package is registered by its path without running its __init__.py (which
imports Home Assistant); themes/ itself imports only const.py from it."""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "room_tiles"
THEME_ART = ROOT / "assets" / "themes"  # the themes that come with Room Tiles

if "room_tiles" not in sys.modules:
    _pkg = types.ModuleType("room_tiles")
    _pkg.__path__ = [str(INTEGRATION)]
    sys.modules["room_tiles"] = _pkg

from room_tiles.themes import fmt, panel, web  # noqa: E402

__all__ = ["ROOT", "INTEGRATION", "THEME_ART", "fmt", "panel", "web"]
