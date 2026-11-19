"""Room Tiles panel: fetches the panel's data from the Room Tiles integration
(docs/DESIGN.md "Panel firmware"). The revision and HA's address come from
the integration's `sensor.room_tiles_panel_link` (homeassistant text sensors
in room_tiles.yaml call set_revision / set_base_url)."""

import os
from pathlib import Path
import re

from esphome import automation
import esphome.codegen as cg
from esphome.components.esp32 import request_http_client
import esphome.config_validation as cv
from esphome.const import CONF_ID, CONF_TRIGGER_ID

DEPENDENCIES = ["api", "lvgl"]
AUTO_LOAD = ["json"]

CONF_ON_STATUS = "on_status"
CONF_ON_ASSETS = "on_assets"
CONF_ON_SCREEN = "on_screen"
CONF_BOARD = "board"
CONF_GENERIC = "generic"
CONF_LAYOUT = "layout"
CONF_MAP = "map"

room_tiles_ns = cg.esphome_ns.namespace("room_tiles")
RoomTiles = room_tiles_ns.class_("RoomTiles", cg.Component)
StatusTrigger = room_tiles_ns.class_("StatusTrigger", automation.Trigger.template())
AssetsTrigger = room_tiles_ns.class_("AssetsTrigger", automation.Trigger.template())
ScreenTrigger = room_tiles_ns.class_("ScreenTrigger", automation.Trigger.template(cg.bool_))

def _release() -> str:
    """A release build's version - release.yml's firmware builds set
    ROOM_TILES_RELEASE to the release's tag ("v0.1.0" -> "0.1.0"); every
    other build (by hand, CI on its own) has none, and Room Tiles shows its
    build time and id instead (custom_components/room_tiles/firmware.py)."""
    tag = os.environ.get("ROOM_TILES_RELEASE", "").strip()
    version = tag[1:] if tag.startswith("v") else tag
    return version if re.fullmatch(r"\d+\.\d+\.\d+([.-]?[0-9A-Za-z.]+)?", version) else ""


def _panel_schema() -> int:
    """signing.h PANEL_SCHEMA (the one place it's written on this side)."""
    text = (Path(__file__).parent / "signing.h").read_text(encoding="utf-8")
    return int(re.search(r"PANEL_SCHEMA = (\d+);", text).group(1))


CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(RoomTiles),
        # which board this firmware is for (boards/*.yaml: "elecrow-p4-7in-v1.2-es"):
        # Room Tiles only ever sends a panel an image for its own board
        cv.Optional(CONF_BOARD, default=""): cv.string,
        # a generic image (identity/generic.yaml): Room Tiles may update it;
        # a hand-built one (identity/own.yaml) is updated with ESPHome
        cv.Optional(CONF_GENERIC, default=False): cv.boolean,
        # grid: the wall panels' board (5x2 / 6x3); strip: the round panel's
        # one row of the area's 5x2 tiles (board_strip.cpp)
        cv.Optional(CONF_LAYOUT, default="grid"): cv.one_of("grid", "strip", lower=True),
        # false: no map and no vacuum view (the round panel)
        cv.Optional(CONF_MAP, default=True): cv.boolean,
        cv.Optional(CONF_ON_STATUS): automation.validate_automation(
            {cv.GenerateID(CONF_TRIGGER_ID): cv.declare_id(StatusTrigger)}
        ),
        # the theme pack / wording changed (or was dropped while a new one is
        # written): redraw whatever shows images or words from them
        cv.Optional(CONF_ON_ASSETS): automation.validate_automation(
            {cv.GenerateID(CONF_TRIGGER_ID): cv.declare_id(AssetsTrigger)}
        ),
        # which page to show: x = true the main screen, false the boot screen
        cv.Optional(CONF_ON_SCREEN): automation.validate_automation(
            {cv.GenerateID(CONF_TRIGGER_ID): cv.declare_id(ScreenTrigger)}
        ),
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    request_http_client()  # ESP-IDF's HTTP client (the payload download)
    from esphome.core import CORE

    if "wifi" in CORE.config and config[CONF_LAYOUT] != "strip":
        # Wi-Fi set up on the panel (wifi_setup.cpp): every scan's networks,
        # not only the saved one's (the round panel: the phone way only -
        # nothing kept)
        from esphome.components.wifi import request_wifi_scan_results, request_wifi_scan_results_listener

        request_wifi_scan_results_listener()
        request_wifi_scan_results()  # (every network's, not only the saved one's)
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    # the image's tag: Room Tiles reads it from a firmware file to know its
    # board, panel format and release (custom_components/room_tiles/firmware.py
    # IMAGE_TAG) - an image for another format is never offered
    board, generic, release = config[CONF_BOARD], config[CONF_GENERIC], _release()
    tag = f"RT-IMAGE:{board}:{'generic' if generic else 'own'}:{_panel_schema()}:{release};"
    cg.add(var.set_image(tag, board, generic, release))
    cg.add(var.set_shape(config[CONF_LAYOUT] == "strip", config[CONF_MAP]))
    for key in (CONF_ON_STATUS, CONF_ON_ASSETS):
        for conf in config.get(key, []):
            trigger = cg.new_Pvariable(conf[CONF_TRIGGER_ID], var)
            await automation.build_automation(trigger, [], conf)
    for conf in config.get(CONF_ON_SCREEN, []):
        trigger = cg.new_Pvariable(conf[CONF_TRIGGER_ID], var)
        await automation.build_automation(trigger, [(cg.bool_, "x")], conf)
