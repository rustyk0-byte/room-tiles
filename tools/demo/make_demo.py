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
            {"id": "washer", "label": "Washer", "appliance": "washer", "preset": "lg_thinq_washer",
             "status": "sensor.washer_current_state", "time": "sensor.washer_finish", "finished": "waiting", "clear": ["unit:dryer"]},
            {"id": "dryer", "label": "Dryer", "appliance": "dryer", "preset": "lg_thinq_dryer",
             "status": "sensor.dryer_current_state", "time": "sensor.dryer_finish", "finished": "waiting"},
        ],
    }),
    ("Kitchen", {
        "id": "dishwasher", "name": "Dishwasher",
        "units": [{"id": "dishwasher", "label": "Dishwasher", "appliance": "dishwasher", "preset": "ge_home_dishwasher",
                   "status": "sensor.dishwasher_cycle_state", "time": "sensor.dishwasher_time_remaining"}],
    }),
]


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
    (its tile: switch over)."""
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
