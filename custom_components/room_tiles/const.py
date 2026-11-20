"""Constants for Room Tiles."""

from __future__ import annotations

from pathlib import Path

DOMAIN = "room_tiles"

# DEVELOPER BUILD: running straight from the Room Tiles source (the pack
# builder, assets/build_panel.py, beside the integration) - never a released
# install (HACS copies only custom_components/room_tiles). Decided once, at
# import. Everything that behaves differently while developing checks
# DEV_BUILD - search for it to find every such place; nothing else may.
DEV_BUILD = (Path(__file__).resolve().parents[2] / "assets" / "build_panel.py").exists()

# Storage: one JSON document in .storage/room_tiles. COMPATIBILITY RULES
# (people restore backups and downgrade at any time):
# - Every stored version ever released must keep loading: add a step in
#   migrate.py and a sample in tests/fixtures/storage/ for each version.
# - MINOR bump = additive only (new optional fields; nothing renamed,
#   removed or newly required), so OLDER Room Tiles can still read the data
#   (the model ignores unknown fields).
# - Anything else = MAJOR bump. HA won't let older code load it; the
#   pre-migration copy in room_tiles_backups/ is the way back.
# (1.1 -> 1.2 broke the minor rule before the first release; the first
# public release is the baseline.)
STORAGE_KEY = DOMAIN
FW_TRIES_KEY = f"{DOMAIN}.firmware_tries"  # (store.py: automatic installs' tries, kept across restarts)
RECORDINGS_KEY = f"{DOMAIN}.recordings"  # (cycles.py: "Report a problem" recordings of the next cycle)
STORAGE_VERSION = 1
STORAGE_MINOR_VERSION = 11  # 1.11 (2026-11-12): wall panels and their own settings - see migrate.py

# Schema version of the data sent to panels and the dashboard. A panel or
# dashboard that sees a newer major version shows "update needed" instead of
# drawing something wrong.
PAYLOAD_SCHEMA = 1

# Short names (tiles, map markers, panel headers): at most this many characters.
MAX_SHORT_NAME = 15
# Map navigation has to fit a phone and the 1024x600 panels (fixed buffers):
# at most this many maps, and marker layers per map (layers are zoom steps -
# more than a few isn't usable). Checked on edits, never on load.
MAX_MAPS = 8
MAX_LAYERS = 6

# Exports / import backups / pre-migration copies, inside the config folder.
BACKUP_DIR = "room_tiles_backups"

# Grid layouts a panel area can use (columns x rows).
LAYOUT_5X2 = "5x2"
LAYOUT_6X3 = "6x3"
LAYOUTS: dict[str, int] = {LAYOUT_5X2: 10, LAYOUT_6X3: 18}

# Tile kinds. Words, not letters: they show up in the dashboard and in
# exported data. The panel firmware maps them to its own enum.
KIND_BLANK = "blank"
KIND_ONOFF_LIGHT = "onoff_light"
KIND_DIMMABLE_LIGHT = "dimmable_light"
KIND_COLOR_LIGHT = "color_light"
KIND_SWITCH = "switch"
KIND_FAN = "fan"
KIND_COVER = "cover"
KIND_LOCK = "lock"
KIND_CLIMATE = "climate"
KIND_APPLIANCE = "appliance"
KIND_VACUUM = "vacuum"
KIND_WATER = "water"
KIND_MAP = "map"
KIND_SCENE = "scene"  # one tap: the scene turns on
KIND_SCRIPT = "script"  # one tap: the script runs (lit while it runs)

TILE_KINDS: tuple[str, ...] = (
    KIND_BLANK,
    KIND_ONOFF_LIGHT,
    KIND_DIMMABLE_LIGHT,
    KIND_COLOR_LIGHT,
    KIND_SWITCH,
    KIND_FAN,
    KIND_COVER,
    KIND_LOCK,
    KIND_CLIMATE,
    KIND_APPLIANCE,
    KIND_VACUUM,
    KIND_WATER,
    KIND_MAP,
    KIND_SCENE,
    KIND_SCRIPT,
)

# Kinds that are not tied to an entity.
NO_ENTITY_KINDS: frozenset[str] = frozenset({KIND_BLANK, KIND_MAP})

# The letters today's panel firmware (ha_dynamic) uses, for the import of an
# existing setup and for the firmware payload until the firmware port.
LEGACY_KIND_LETTERS: dict[str, str] = {
    "B": KIND_BLANK,
    "O": KIND_ONOFF_LIGHT,
    "D": KIND_DIMMABLE_LIGHT,
    "R": KIND_COLOR_LIGHT,
    "S": KIND_SWITCH,
    "F": KIND_FAN,
    "C": KIND_COVER,
    "L": KIND_LOCK,
    "A": KIND_CLIMATE,
    "P": KIND_APPLIANCE,
    "V": KIND_VACUUM,
    "W": KIND_WATER,
    "M": KIND_MAP,
}

# Map shape styles (filled polygons).
SHAPE_STYLES: tuple[str, ...] = ("floor", "water", "grass", "deck", "paving")

# MIRRORED: firmware/components/room_tiles/signing.h PANEL_SCHEMA - a change here must be made there too.
# The panels' format: payload, packs, taps, screenshots. Bump it (both sides) on
# any change the other side can't read. Every panel request says its number
# (?schema=); HA answers another number with 426 and its own in the body - the
# panel then says which side needs an update, and HA lists it in Repairs.
PANEL_SCHEMA = 4  # (4: the whole request signed - panels.py request_signature)
