"""Room Tiles panel: fetches the panel's data from the Room Tiles integration
(docs/DESIGN.md "Panel firmware"). The revision and HA's address come from
the integration's `sensor.room_tiles_panel_link` (homeassistant text sensors
in room_tiles.yaml call set_revision / set_base_url)."""

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
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    # the image's tag: Room Tiles reads it from a firmware file to know its
    # board and panel format (custom_components/room_tiles/firmware.py
    # IMAGE_TAG) - an image for another format is never offered
    board, generic = config[CONF_BOARD], config[CONF_GENERIC]
    tag = f"RT-IMAGE:{board}:{'generic' if generic else 'own'}:{_panel_schema()};"
    cg.add(var.set_image(tag, board, generic))
    cg.add(var.set_shape(config[CONF_LAYOUT] == "strip", config[CONF_MAP]))
    for key in (CONF_ON_STATUS, CONF_ON_ASSETS):
        for conf in config.get(key, []):
            trigger = cg.new_Pvariable(conf[CONF_TRIGGER_ID], var)
            await automation.build_automation(trigger, [], conf)
    for conf in config.get(CONF_ON_SCREEN, []):
        trigger = cg.new_Pvariable(conf[CONF_TRIGGER_ID], var)
        await automation.build_automation(trigger, [(cg.bool_, "x")], conf)
