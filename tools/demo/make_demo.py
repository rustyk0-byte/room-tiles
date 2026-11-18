"""The browser demo's made-up home (docs/TODO.md "Landing page + browser
demo"): the real Room Tiles integration, run in Home Assistant's test
harness with made-up floors, areas, devices and states, and what the
dashboard is sent written out as JSON - so the demo always shows what
Room Tiles really sends.

    DEMO_OUT=<folder> python -m pytest -q tools/demo/make_demo.py

writes <folder> (default tools/demo/out/):
- feed.json      the dashboard's first message (room_tiles/subscribe "full")
- states.json    every entity's state and attributes (hass.states)
- entities.json  the entity registry's display entries (hass.entities)
- devices.json   the devices (hass.devices)
- meta.json      when it was made: the demo page moves every time in the
                 states (a finish time...) by how long ago that was

Nothing here is a real home: names, rooms and devices are made up.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import floor_registry as fr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.room_tiles.const import DOMAIN

OUT = Path(os.environ.get("DEMO_OUT") or Path(__file__).parent / "out")

COLOR = {"supported_color_modes": ["hs", "color_temp"], "color_mode": "hs"}
DIM = {"supported_color_modes": ["brightness"], "color_mode": "brightness"}
ONOFF = {"supported_color_modes": ["onoff"], "color_mode": "onoff"}

# floor -> area -> [(entity id, state, attributes)]
HOME: dict[str, dict[str, list[tuple[str, str, dict]]]] = {
    "Main Floor": {
        "Living Room": [
            ("light.living_room_lamps", "on", {**COLOR, "friendly_name": "Lamps", "brightness": 180, "hs_color": [32, 60]}),
            ("light.living_room_ceiling", "off", {**DIM, "friendly_name": "Ceiling"}),
            ("fan.living_room_fan", "on", {"friendly_name": "Ceiling Fan", "percentage": 50, "percentage_step": 25}),
            ("cover.living_room_blinds", "open", {"friendly_name": "Blinds", "current_position": 70, "device_class": "blind", "supported_features": 15}),
            ("climate.thermostat", "heat_cool", {
                "friendly_name": "Thermostat", "hvac_modes": ["off", "heat", "cool", "heat_cool"], "current_temperature": 71,
                "target_temp_low": 68, "target_temp_high": 75, "min_temp": 50, "max_temp": 90, "supported_features": 2, "hvac_action": "idle",
            }),
            ("lock.front_door", "locked", {"friendly_name": "Front Door"}),
        ],
        "Kitchen": [
            ("light.kitchen_pendants", "on", {**DIM, "friendly_name": "Pendants", "brightness": 230}),
            ("light.under_cabinet", "on", {**COLOR, "friendly_name": "Under Cabinet", "brightness": 120, "hs_color": [200, 40]}),
            ("light.kitchen_ceiling", "off", {**DIM, "friendly_name": "Ceiling"}),
            ("switch.coffee_maker", "off", {"friendly_name": "Coffee Maker"}),
        ],
        "Dining Room": [
            ("light.chandelier", "on", {**DIM, "friendly_name": "Chandelier", "brightness": 150}),
            ("cover.dining_room_shades", "closed", {"friendly_name": "Shades", "current_position": 0, "device_class": "shade", "supported_features": 15}),
        ],
        "Office": [
            ("light.desk_lamp", "on", {**COLOR, "friendly_name": "Desk Lamp", "brightness": 255, "color_mode": "color_temp", "color_temp_kelvin": 4000}),
            ("light.office_ceiling", "off", {**DIM, "friendly_name": "Ceiling"}),
            ("fan.office_fan", "off", {"friendly_name": "Fan", "percentage": 0, "percentage_step": 33.33}),
            ("switch.printer", "on", {"friendly_name": "Printer"}),
        ],
        "Laundry": [
            ("light.laundry", "off", {**ONOFF, "friendly_name": "Light"}),
        ],
        "Garage": [
            ("cover.garage_door", "closed", {"friendly_name": "Garage Door", "device_class": "garage", "supported_features": 3}),
            ("light.garage", "off", {**ONOFF, "friendly_name": "Light"}),
        ],
    },
    "Upstairs": {
        "Bedroom": [
            ("light.bedside_lamps", "on", {**COLOR, "friendly_name": "Bedside Lamps", "brightness": 90, "hs_color": [280, 50]}),
            ("light.bedroom_ceiling", "off", {**DIM, "friendly_name": "Ceiling"}),
            ("fan.bedroom_fan", "on", {"friendly_name": "Ceiling Fan", "percentage": 25, "percentage_step": 25}),
            ("cover.bedroom_blinds", "closed", {"friendly_name": "Blinds", "current_position": 0, "device_class": "blind", "supported_features": 15}),
        ],
        "Kids' Room": [
            ("light.kids_room", "on", {**COLOR, "friendly_name": "Light", "brightness": 200, "hs_color": [120, 45]}),
            ("light.night_light", "off", {**COLOR, "friendly_name": "Night Light"}),
        ],
        "Bathroom": [
            ("light.bathroom", "off", {**DIM, "friendly_name": "Light"}),
            ("fan.bathroom_fan", "off", {"friendly_name": "Exhaust Fan"}),
        ],
    },
}


# The appliances: their own devices (a brand's confirmed model: no beta
# note) and entities, (area, device, maker, model, [(entity, state, attrs)]);
# "<finish>" = a finish time FINISH_MIN from now.
FINISH_MIN = 38
APPLIANCE_DEVICES = [
    ("Laundry", "Washer", "LG", "F3P2CYUBE (DEVICE_WASHER)", [
        ("sensor.washer_current_state", "running", {"friendly_name": "Washer Current status"}),
        ("sensor.washer_finish", "<finish>", {"friendly_name": "Washer Remaining time", "device_class": "timestamp"}),
    ]),
    ("Laundry", "Dryer", "LG", "RV13D4ASJW (DEVICE_DRYER)", [
        ("sensor.dryer_current_state", "running", {"friendly_name": "Dryer Current status"}),
        ("sensor.dryer_finish", "unknown", {"friendly_name": "Dryer Remaining time", "device_class": "timestamp"}),
    ]),
    ("Kitchen", "Dishwasher", "GE Appliances", "Dishwasher", [
        ("sensor.dishwasher_cycle_state", "Main Wash", {"friendly_name": "Dishwasher Cycle state"}),
        ("sensor.dishwasher_time_remaining", "52", {"friendly_name": "Dishwasher Time remaining", "unit_of_measurement": "min",
                                                     "device_class": "duration"}),
    ]),
]
# what setup would make of them (Room Tiles' set_appliance) - and the area
# each tile goes in
APPLIANCES = [
    ("Laundry", {
        "id": "laundry", "name": "Laundry",
        "units": [
            # (the dryer on top, as setup pairs them: appliance_detect._pair_laundry)
            {"id": "dryer", "label": "Dryer", "appliance": "dryer", "preset": "lg_thinq_dryer",
             "status": "sensor.dryer_current_state", "time": "sensor.dryer_finish"},
            {"id": "washer", "label": "Washer", "appliance": "washer", "preset": "lg_thinq_washer",
             "status": "sensor.washer_current_state", "time": "sensor.washer_finish", "finished": "waiting", "clear": ["unit:dryer"]},
        ],
    }),
    ("Kitchen", {
        "id": "dishwasher", "name": "Dishwasher",
        "units": [{"id": "dishwasher", "label": "Dishwasher", "appliance": "dishwasher", "preset": "ge_home_dishwasher",
                   "status": "sensor.dishwasher_cycle_state", "time": "sensor.dishwasher_time_remaining"}],
    }),
]


# A robot vacuum for the downstairs rooms (not the garage): HA's own room
# mapping on the vacuum entity (vacuums.py reads it), cleaning the first
# room of its queue, the next one waiting.
VACUUM = "vacuum.robot_vacuum"
VACUUM_ROOMS = ("dining_room", "kitchen", "laundry", "living_room", "office")
VACUUM_QUEUE = ("kitchen", "living_room")
VACUUM_FEATURES = 29212  # (start, pause, return home, clean area...)


async def _vacuum(hass: HomeAssistant) -> None:
    ents, devs = er.async_get(hass), dr.async_get(hass)
    src = MockConfigEntry(domain="demo_vacuum", title="Demo")
    src.add_to_hass(hass)
    dev = devs.async_get_or_create(config_entry_id=src.entry_id, identifiers={("demo", "robot_vacuum")}, name="Robot Vacuum",
                                   manufacturer="Demo", model="Robot Vacuum")
    devs.async_update_device(dev.id, area_id="living_room")
    ents.async_get_or_create("vacuum", "demo", "robot_vacuum", suggested_object_id="robot_vacuum", config_entry=src, device_id=dev.id)
    ents.async_update_entity_options(VACUUM, "vacuum", {"area_mapping": {a: [str(i + 1)] for i, a in enumerate(VACUUM_ROOMS)}})
    hass.states.async_set(VACUUM, "docked", {"friendly_name": "Robot Vacuum", "supported_features": VACUUM_FEATURES, "battery_level": 86})

    async def nothing(call):  # (what a real HA and the vacuum's integration answer)
        pass

    for domain, service in (("vacuum", "clean_area"), ("vacuum", "start"), ("vacuum", "pause"), ("vacuum", "return_to_base"),
                            ("persistent_notification", "create"), ("persistent_notification", "dismiss")):
        hass.services.async_register(domain, service, nothing)
    call = lambda service, **data: hass.services.async_call(DOMAIN, service, data, blocking=True)  # noqa: E731
    await call("set_robot", robot={"id": "robot_vacuum", "name": "Robot Vacuum", "vacuum": VACUUM, "preset": "vacuum"})
    await hass.async_block_till_done()
    for area in VACUUM_QUEUE:
        await call("vacuum_queue", robot="robot_vacuum", action="add", area=area)
    await call("vacuum_queue", robot="robot_vacuum", action="start")
    hass.states.async_set(VACUUM, "cleaning", {"friendly_name": "Robot Vacuum", "supported_features": VACUUM_FEATURES, "battery_level": 74})
    await hass.async_block_till_done()


# The generated Main Floor map, changed a little: these two rooms trade
# places (the Dining Room gets the bay window), and stairs up from the
# Living Room - a link to the Upstairs map, in the room's upper part (clear
# of its name and its lights marker).
SWAP_ROOMS = ("dining_room", "garage")
STAIRS = ("main_floor", "living_room", "upstairs", 146.0)


# A second marker layer on each map: from 2x on, a marker for every tile of
# each room (in a 3 x 3 grid around the room's name, the middle free - and
# in the stairs' room its top middle too); the first layer ("Main": the
# rooms' lights) ends there. Two layers: the map gets its layer (zoom)
# buttons.
DEVICES_LAYER = ("devices", "Devices", 2.0)
GRID = 30.0  # map units between a room's markers
SLOTS = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]


def _device_layer(entry: MockConfigEntry) -> None:
    from custom_components.room_tiles.model import Layer, Marker

    data = entry.runtime_data.data
    layer_id, name, zoom = DEVICES_LAYER
    for plan in data.maps:
        for layer in plan.layers:
            layer.max_zoom = zoom
        plan.layers.append(Layer(id=layer_id, name=name, min_zoom=zoom))
        for zone in plan.zones:
            area = data.area(zone.area) if zone.area else None
            if area is None or zone.label is None:
                continue
            tiles = [t for t in area.tiles.get("5x2", []) if t is not None and t.entity and t.kind != "blank"]
            slots = [sl for sl in SLOTS if not (sl == (0, -1) and plan.id == STAIRS[0] and zone.area == STAIRS[1])]
            for t, (dx, dy) in zip(tiles, slots):
                data.markers.append(Marker(id=f"{plan.id}_{t.entity}", map=plan.id, entity=t.entity,
                                           x=zone.label[0] + dx * GRID, y=zone.label[1] + dy * GRID, layer=layer_id))


def _map_changes(entry: MockConfigEntry) -> None:
    from custom_components.room_tiles.model import Link

    data = entry.runtime_data.data
    plan = next(m for m in data.maps if m.id == STAIRS[0])
    a, b = (next(z for z in plan.zones if z.area == area) for area in SWAP_ROOMS)
    a.id, b.id, a.area, b.area, a.name, b.name = b.id, a.id, b.area, a.area, b.name, a.name
    ma, mb = (next(mk for mk in data.markers if mk.map == plan.id and mk.entity == f"light.room_tiles_{area}_area_lights")
              for area in SWAP_ROOMS)
    ma.x, ma.y, mb.x, mb.y = mb.x, mb.y, ma.x, ma.y
    room = next(z for z in plan.zones if z.area == STAIRS[1])
    plan.links.append(Link(to=STAIRS[2], at=(room.label[0], STAIRS[3])))
    _device_layer(entry)


@pytest.fixture(autouse=True)
def _custom(enable_custom_integrations):
    yield


def _build(hass: HomeAssistant) -> None:
    floors, areas, ents, devs = fr.async_get(hass), ar.async_get(hass), er.async_get(hass), dr.async_get(hass)
    src = MockConfigEntry(domain="demo", title="Demo")
    src.add_to_hass(hass)
    for level, (floor_name, rooms) in enumerate(HOME.items()):
        floor = floors.async_create(floor_name, level=level)
        for area_name, things in rooms.items():
            area = areas.async_create(area_name, floor_id=floor.floor_id)
            for entity_id, state, attrs in things:
                domain, object_id = entity_id.split(".", 1)
                dev = devs.async_get_or_create(
                    config_entry_id=src.entry_id, identifiers={("demo", object_id)}, name=attrs["friendly_name"], manufacturer="Demo"
                )
                devs.async_update_device(dev.id, area_id=area.id)
                ents.async_get_or_create(domain, "demo", object_id, suggested_object_id=object_id, config_entry=src, device_id=dev.id)
                hass.states.async_set(entity_id, state, attrs)
    finish = (dt_util.utcnow() + timedelta(minutes=FINISH_MIN)).isoformat(timespec="seconds")
    by_name = {a.name: a for a in areas.async_list_areas()}
    for area_name, name, maker, model, things in APPLIANCE_DEVICES:
        dev = devs.async_get_or_create(
            config_entry_id=src.entry_id, identifiers={("demo", name.lower())}, name=name, manufacturer=maker, model=model
        )
        devs.async_update_device(dev.id, area_id=by_name[area_name].id)
        for entity_id, state, attrs in things:
            domain, object_id = entity_id.split(".", 1)
            ents.async_get_or_create(domain, "demo", object_id, suggested_object_id=object_id, config_entry=src, device_id=dev.id)
            hass.states.async_set(entity_id, finish if state == "<finish>" else state, attrs)


async def _appliances(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set the appliances up as setup would, then finish the dryer's cycle
    (its tile: done)."""
    for _area, appliance in APPLIANCES:
        await hass.services.async_call(DOMAIN, "set_appliance", {"appliance": appliance}, blocking=True)
        await hass.async_block_till_done()  # (its tile goes in the area by itself)
    hass.states.async_set("sensor.dryer_current_state", "end", {"friendly_name": "Dryer Current status"})
    await hass.async_block_till_done()


def _write(name: str, doc) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(doc, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")


async def test_make_demo(hass: HomeAssistant, hass_ws_client) -> None:
    from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

    hass.config.units = US_CUSTOMARY_SYSTEM
    _build(hass)
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await _appliances(hass, entry)
    await _vacuum(hass)
    _map_changes(entry)

    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "room_tiles/subscribe"})
    assert (await ws.receive_json())["success"]
    full = (await ws.receive_json())["event"]
    assert full["type"] == "full"
    _write("feed.json", full)
    _write("meta.json", {"made": dt_util.utcnow().isoformat(timespec="seconds")})
    _write("states.json", {s.entity_id: {"entity_id": s.entity_id, "state": s.state, "attributes": dict(s.attributes)} for s in hass.states.async_all()})
    _write("entities.json", {
        e.entity_id: {"entity_id": e.entity_id, "area_id": e.area_id, "device_id": e.device_id, "platform": e.platform,
                      "hidden": e.hidden, "entity_category": e.entity_category}
        for e in er.async_get(hass).entities.values()
    })
    _write("devices.json", {d.id: {"id": d.id, "name": d.name_by_user or d.name, "area_id": d.area_id, "manufacturer": d.manufacturer}
                            for d in dr.async_get(hass).devices})
