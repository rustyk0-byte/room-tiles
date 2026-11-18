"""Which tile kind an HA entity gets (pure: works on its domain + attributes)."""

from __future__ import annotations

from typing import Any

from .const import (
    KIND_APPLIANCE,
    KIND_CLIMATE,
    KIND_COLOR_LIGHT,
    KIND_COVER,
    KIND_DIMMABLE_LIGHT,
    KIND_FAN,
    KIND_LOCK,
    KIND_ONOFF_LIGHT,
    KIND_SCENE,
    KIND_SCRIPT,
    KIND_SWITCH,
    KIND_VACUUM,
)

COLOR_MODES = {"hs", "xy", "rgb", "rgbw", "rgbww", "color_temp"}


def infer_kind(entity_id: str, attrs: dict[str, Any] | None) -> str | None:
    """The tile kind for an entity, or None if Room Tiles has no tile for it.
    Lights: colour / dimmable / on-off from their supported colour modes.
    A sensor with a `tile` attribute is an appliance (the documented tile
    contract); other sensors have no tile."""
    attrs = attrs or {}
    domain = entity_id.split(".", 1)[0]
    if domain == "light":
        modes = set(attrs.get("supported_color_modes") or [])
        if modes & COLOR_MODES:
            return KIND_COLOR_LIGHT
        if "brightness" in modes:
            return KIND_DIMMABLE_LIGHT
        return KIND_ONOFF_LIGHT
    return {
        "switch": KIND_SWITCH,
        "input_boolean": KIND_SWITCH,
        "fan": KIND_FAN,
        "cover": KIND_COVER,
        "lock": KIND_LOCK,
        "climate": KIND_CLIMATE,
        "vacuum": KIND_VACUUM,
        "scene": KIND_SCENE,
        "script": KIND_SCRIPT,
        "sensor": KIND_APPLIANCE if "tile" in attrs else None,
    }.get(domain)
