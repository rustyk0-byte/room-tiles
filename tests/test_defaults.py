"""A new home starts usable: default boards, the area's lights as a light,
the lights marker on the generated map."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.room_tiles.const import DOMAIN


async def _setup(hass, data=None):
    entry = MockConfigEntry(domain=DOMAIN, data=data or {})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _ent(hass, domain, object_id, area_id, **kw):
    src = MockConfigEntry(domain="demo")
    src.add_to_hass(hass)
    return er.async_get(hass).async_get_or_create(
        domain, "demo", object_id, suggested_object_id=object_id, config_entry=src, **kw
    ) and er.async_get(hass).async_update_entity(f"{domain}.{object_id}", area_id=area_id)


def _kitchen(hass):
    areas = ar.async_get(hass)
    kitchen = areas.async_create("Kitchen")
    areas.async_create("Cellar")  # nothing in it
    _ent(hass, "light", "ceiling", kitchen.id)
    _ent(hass, "light", "pendant", kitchen.id)
    _ent(hass, "fan", "kitchen_fan", kitchen.id)
    _ent(hass, "switch", "kettle", kitchen.id)
    _ent(hass, "switch", "kettle_child_lock", kitchen.id, entity_category=er.EntityCategory.CONFIG)
    _ent(hass, "scene", "dinner", kitchen.id)
    hass.states.async_set("light.ceiling", "on", {"supported_color_modes": ["brightness"], "brightness": 200, "friendly_name": "Ceiling"})
    hass.states.async_set("light.pendant", "off", {"supported_color_modes": ["hs"], "friendly_name": "Pendant"})
    hass.states.async_set("fan.kitchen_fan", "off", {"friendly_name": "Kitchen Fan"})
    hass.states.async_set("switch.kettle", "off", {"friendly_name": "Kettle"})
    hass.states.async_set("scene.dinner", "scening", {"entity_id": ["light.ceiling"]})
    return kitchen


async def test_area_lights_registered_under_the_old_id_move(hass: HomeAssistant) -> None:
    """light.room_tiles_<area>_lights (the earlier id) becomes ..._area_lights."""
    _kitchen(hass)
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "light", DOMAIN, "area_lights_kitchen", suggested_object_id="room_tiles_kitchen_lights", config_entry=entry
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    reg = er.async_get(hass)
    assert reg.async_get("light.room_tiles_kitchen_lights") is None
    assert reg.async_get("light.room_tiles_kitchen_area_lights").unique_id == "area_lights_kitchen"
    assert hass.states.get("light.room_tiles_kitchen_area_lights").attributes["own_name"] == "Kitchen Area Lights (Room Tiles)"


async def test_new_home_boards_and_lights(hass: HomeAssistant) -> None:
    kitchen = _kitchen(hass)
    entry = await _setup(hass)
    data = entry.runtime_data.data

    # the area's lights, together, as a light in its area
    st = hass.states.get("light.room_tiles_kitchen_area_lights")
    assert st is not None and st.state == "on"
    assert st.attributes["entity_id"] == ["light.ceiling", "light.pendant"]
    assert st.attributes["own_name"] == "Kitchen Area Lights (Room Tiles)"
    assert st.attributes["brightness"] == 200
    assert er.async_get(hass).async_get("light.room_tiles_kitchen_area_lights").area_id == kitchen.id

    # hidden in HA (Room Tiles' own), never a board tile
    assert er.async_get(hass).async_get("light.room_tiles_kitchen_area_lights").hidden_by is not None
    board = [(t.kind, t.entity) for t in data.area(kitchen.id).tiles["5x2"]]
    assert board[:4] == [
        ("color_light", "light.pendant"),
        ("dimmable_light", "light.ceiling"),
        ("fan", "fan.kitchen_fan"),
        ("switch", "switch.kettle"),  # not its child-lock setting, not the scene
    ]
    assert board[4:10] == [("blank", None)] * 6
    assert "map" not in {t.kind for lay in ("5x2", "6x3") for t in data.area(kitchen.id).tiles[lay]}  # no Map tile (placed by hand)
    assert data.area(kitchen.id).layout == "5x2"  # it all fits
    # "<Area> Area Lights" by the usual shortening (English: Kitchen -> Kit)
    assert data.catalog.get("light.room_tiles_kitchen_area_lights").short_name == "Kit Area Lights"

    # an area with nothing: shown, an empty board; no lights light
    cellar = next(a for a in data.areas if a.name == "Cellar")
    assert [t.kind for t in cellar.tiles["5x2"]] == ["blank"] * 10
    assert hass.states.get("light.room_tiles_cellar_area_lights") is None

    # the generated map: the lights marker in the kitchen's square
    assert [(m.map, m.entity) for m in data.markers] == [(data.maps[0].id, "light.room_tiles_kitchen_area_lights")]

    # filled once: a board the user empties stays empty
    for i in range(10):
        data.area(kitchen.id).tiles["5x2"][i].kind = "blank"
        data.area(kitchen.id).tiles["5x2"][i].entity = None
    ar.async_get(hass).async_update(kitchen.id, name="Kitchen")  # a registry event: refresh
    await hass.async_block_till_done()
    assert all(t.kind == "blank" for t in data.area(kitchen.id).tiles["5x2"])


async def test_area_lights_light_switches_its_lights(hass: HomeAssistant) -> None:
    _kitchen(hass)
    await _setup(hass)
    calls = []

    async def record(call):
        calls.append((call.service, sorted(call.data["entity_id"]), call.data.get("brightness")))

    # (stand-ins for the real lights' service)
    hass.services.async_register("light", "turn_on", record)
    hass.services.async_register("light", "turn_off", record)
    ours = hass.data["entity_components"]["light"].get_entity("light.room_tiles_kitchen_area_lights")
    await ours.async_turn_on(brightness=80)
    await ours.async_turn_off()
    assert calls == [
        ("turn_on", ["light.ceiling", "light.pendant"], 80),
        ("turn_off", ["light.ceiling", "light.pendant"], None),
    ]


async def test_no_lights_light_when_unwanted(hass: HomeAssistant) -> None:
    kitchen = _kitchen(hass)
    await _setup(hass)
    assert hass.states.get("light.room_tiles_kitchen_area_lights") is not None
    await hass.services.async_call(DOMAIN, "set_area_light_entity", {"area": kitchen.id, "enabled": False}, blocking=True)
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get("light.room_tiles_kitchen_area_lights") is None


async def test_existing_board_untouched(hass: HomeAssistant) -> None:
    """An upgraded home: a board with tiles is left alone (only empty ones fill)."""
    kitchen = _kitchen(hass)
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    from custom_components.room_tiles.store import RoomTilesStore  # noqa: F401 - the store loads in setup

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    data = entry.runtime_data.data
    area = data.area(kitchen.id)
    assert area.filled
    # what setup put there stays exactly as it is on later refreshes
    before = [t.as_dict() for t in area.tiles["6x3"]]
    ar.async_get(hass).async_update(kitchen.id, name="Kitchen")
    await hass.async_block_till_done()
    assert [t.as_dict() for t in area.tiles["6x3"]] == before


async def test_hidden_area_waits_until_shown(hass: HomeAssistant) -> None:
    kitchen = _kitchen(hass)
    cellar = next(a for a in ar.async_get(hass).async_list_areas() if a.name == "Cellar")
    entry = await _setup(hass, {"areas": [cellar.id], "auto_add_areas": False})  # kitchen unticked: hidden
    data = entry.runtime_data.data
    area = data.area(kitchen.id)
    assert area.hidden and not area.filled
    assert all(t.kind == "blank" for t in area.tiles["5x2"])
    await hass.services.async_call(DOMAIN, "set_area", {"area": kitchen.id, "hidden": False}, blocking=True)
    await hass.async_block_till_done()
    area = entry.runtime_data.data.area(kitchen.id)  # (actions replace the data)
    assert area.filled and area.tiles["5x2"][0].kind != "blank"


async def test_area_light_not_exposed_to_voice_assistants(hass: HomeAssistant) -> None:
    from homeassistant.components.homeassistant.exposed_entities import async_get_entity_settings
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "homeassistant", {})
    _kitchen(hass)
    await _setup(hass)
    settings = async_get_entity_settings(hass, "light.room_tiles_kitchen_area_lights")
    assert settings["cloud.alexa"]["should_expose"] is False
    assert settings["conversation"]["should_expose"] is False


def _items(spec):
    """[(kind, count, group?)] -> board-ordered items."""
    from custom_components.room_tiles.defaults import board_order

    out = []
    for kind, n, *g in spec:
        out += [(f"{kind}.{i:02}", kind, f"{kind} {i:02}", bool(g and g[0])) for i in range(n)]
    return board_order(out)


def test_small_board_deals_slots_out_over_the_kinds():
    """15 lights, 2 fans, a lock: on 9 slots (area lights + 8) every kind shows."""
    from custom_components.room_tiles.defaults import board_items

    items = _items([("dimmable_light", 15), ("fan", 2), ("lock", 1)])
    first = ("light.room_tiles_x_area_lights", "dimmable_light", "X Lights", True)
    small = board_items(first, items, 9)
    assert [k for _, k, _, _ in small] == ["dimmable_light"] + ["dimmable_light"] * 5 + ["fan"] * 2 + ["lock"]
    big = board_items(first, items, 17)  # area lights + 16 slots for 18: still every kind
    assert len(big) == 17 and [k for _, k, _, _ in big].count("dimmable_light") == 1 + 13
    assert {k for _, k, _, _ in big} == {"dimmable_light", "fan", "lock"}


def test_everything_fits_nothing_is_dealt():
    from custom_components.room_tiles.defaults import board_items

    items = _items([("color_light", 3), ("fan", 1), ("switch", 2)])
    assert board_items(None, items, 10) == items


def test_lights_one_share_groups_first_low_kinds_go_without():
    from custom_components.room_tiles.defaults import board_items

    items = _items([("dimmable_light", 4), ("onoff_light", 3, True), ("climate", 1), ("fan", 3), ("cover", 2), ("lock", 2), ("switch", 4)])
    small = board_items(None, items, 5)  # 5 slots for 6 kinds: switches go without
    # picked: one of each kind but switches; placed: lights first
    assert [k for _, k, _, _ in small] == ["onoff_light", "climate", "fan", "cover", "lock"]
    assert small[0][3] is True  # the light picked is a light group


def test_room_tiles_own_tiles_sit_last():
    from custom_components.room_tiles.defaults import board_items

    items = _items([("appliance", 1), ("water", 1), ("color_light", 2), ("fan", 1)])
    assert [k for _, k, _, _ in board_items(None, items, 10)] == ["color_light", "color_light", "fan", "appliance", "water"]


async def test_remade_area_light_is_not_exposed_despite_leftovers(hass: HomeAssistant) -> None:
    """Room Tiles removed and added again: HA hands the re-made light its old
    settings (here: exposed to Alexa) - a freshly made one is reset."""
    from homeassistant.components.homeassistant.exposed_entities import (
        async_expose_entity,
        async_get_entity_settings,
    )
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "homeassistant", {})
    _kitchen(hass)
    # the leftover: an unregistered entity's setting, from its last life
    async_expose_entity(hass, "cloud.alexa", "light.room_tiles_kitchen_area_lights", True)
    await _setup(hass)
    assert async_get_entity_settings(hass, "light.room_tiles_kitchen_area_lights")["cloud.alexa"]["should_expose"] is False


async def test_room_with_its_own_light_group(hass: HomeAssistant) -> None:
    """Room Tiles' light holds the INDIVIDUAL lights (not the home's group)
    and is the map marker; the board starts with the home's group (groups
    first among the lights)."""
    kitchen = _kitchen(hass)
    grp = MockConfigEntry(domain="group")
    grp.add_to_hass(hass)
    er.async_get(hass).async_get_or_create("light", "group", "kl", suggested_object_id="kitchen_lights", config_entry=grp)
    er.async_get(hass).async_update_entity("light.kitchen_lights", area_id=kitchen.id)
    hass.states.async_set("light.kitchen_lights", "on", {"entity_id": ["light.ceiling", "light.pendant"], "supported_color_modes": ["brightness"], "friendly_name": "Kitchen Lights"})
    entry = await _setup(hass)
    data = entry.runtime_data.data

    ours = er.async_get(hass).async_get("light.room_tiles_kitchen_area_lights")
    assert ours is not None and ours.disabled_by is None
    assert hass.states.get("light.room_tiles_kitchen_area_lights").attributes["entity_id"] == ["light.ceiling", "light.pendant"]
    board = [t.entity for t in data.area(kitchen.id).tiles["5x2"]]
    assert board[0] == "light.kitchen_lights" and "light.room_tiles_kitchen_area_lights" not in board
    assert [m.entity for m in data.markers] == ["light.room_tiles_kitchen_area_lights"]


async def test_appliance_controls_stay_off_default_boards(hass: HomeAssistant) -> None:
    """A dishwasher's sabbath-mode switch is the appliance's setting, not a
    tile of its own (its device is the appliance's)."""
    from homeassistant.helpers import device_registry as dr

    kitchen = _kitchen(hass)
    src = MockConfigEntry(domain="ge_home")
    src.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(config_entry_id=src.entry_id, identifiers={("ge_home", "dw")}, name="Dishwasher")
    dr.async_get(hass).async_update_device(dev.id, area_id=kitchen.id)
    reg = er.async_get(hass)
    reg.async_get_or_create("switch", "ge_home", "sabbath", suggested_object_id="dw_sabbath_mode", device_id=dev.id, config_entry=src)
    reg.async_get_or_create("sensor", "ge_home", "state", suggested_object_id="dw_cycle_state", device_id=dev.id, config_entry=src)
    hass.states.async_set("switch.dw_sabbath_mode", "off", {"friendly_name": "Sabbath Mode"})
    hass.states.async_set("sensor.dw_cycle_state", "off")
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    # the dishwasher as an appliance profile (found or set up: the same)
    from custom_components.room_tiles import defaults

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    data = entry.runtime_data.data
    found = {"found": [{"units": [{"status": "sensor.dw_cycle_state"}]}]}
    owned = defaults.owned_devices(hass, data, found)
    assert dev.id in owned
    _, items = defaults.area_tiles(hass, data, data.area(kitchen.id), set(), frozenset(owned))
    assert "switch.dw_sabbath_mode" not in [it[0] for it in items]
    assert "switch.kettle" in [it[0] for it in items]  # other switches stay

    # one tile from two brands: each unit's device counts (its time sensor's too)
    other = MockConfigEntry(domain="lg_thinq")
    other.add_to_hass(hass)
    lg = dr.async_get(hass).async_get_or_create(config_entry_id=other.entry_id, identifiers={("lg_thinq", "w")}, name="Washer")
    timer = dr.async_get(hass).async_get_or_create(config_entry_id=other.entry_id, identifiers={("lg_thinq", "t")}, name="Timer")
    reg.async_get_or_create("sensor", "lg_thinq", "w_state", suggested_object_id="w_state", device_id=lg.id, config_entry=other)
    reg.async_get_or_create("sensor", "lg_thinq", "w_time", suggested_object_id="w_time", device_id=timer.id, config_entry=other)
    mixed = {"found": [{"units": [{"status": "sensor.dw_cycle_state"}, {"status": "sensor.w_state", "time": "sensor.w_time"}]}]}
    assert {dev.id, lg.id, timer.id} <= defaults.owned_devices(hass, data, mixed)


async def test_garage_opener_switches_stay_off_default_boards(hass: HomeAssistant) -> None:
    """A garage door opener's switches (learn...) are its settings; its light
    and lock are tiles."""
    from homeassistant.helpers import device_registry as dr

    from custom_components.room_tiles import defaults

    areas = ar.async_get(hass)
    garage = areas.async_create("Garage")
    src = MockConfigEntry(domain="esphome")
    src.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(config_entry_id=src.entry_id, identifiers={("esphome", "gdo")}, name="Garage Door")
    dr.async_get(hass).async_update_device(dev.id, area_id=garage.id)
    reg = er.async_get(hass)
    reg.async_get_or_create("cover", "esphome", "door", suggested_object_id="gdo_door", device_id=dev.id, config_entry=src, original_device_class="garage")
    reg.async_get_or_create("switch", "esphome", "learn", suggested_object_id="gdo_learn", device_id=dev.id, config_entry=src)
    reg.async_get_or_create("light", "esphome", "light", suggested_object_id="gdo_light", device_id=dev.id, config_entry=src)
    reg.async_get_or_create("lock", "esphome", "lock", suggested_object_id="gdo_lock", device_id=dev.id, config_entry=src)
    for eid in ("cover.gdo_door", "switch.gdo_learn", "light.gdo_light", "lock.gdo_lock"):
        hass.states.async_set(eid, "off", {"friendly_name": eid})
    entry = await _setup(hass)
    data = entry.runtime_data.data
    entry_devs = frozenset(defaults.entry_devices(hass))
    assert dev.id in entry_devs
    _, items = defaults.area_tiles(hass, data, data.area(garage.id), set(), frozenset(), entry_devs)
    ids = [it[0] for it in items]
    assert "switch.gdo_learn" not in ids
    assert {"cover.gdo_door", "light.gdo_light", "lock.gdo_lock"} <= set(ids)


async def test_area_light_dims_and_colours_like_a_group(hass: HomeAssistant) -> None:
    """Room Tiles' area light can do what any of its lights can: brightness,
    colour - and its catalog kind follows (a full tile on the map)."""
    kitchen = _kitchen(hass)  # ceiling (brightness), pendant (hs)
    entry = await _setup(hass)
    st = hass.states.get("light.room_tiles_kitchen_area_lights")
    assert set(st.attributes["supported_color_modes"]) == {"hs"}
    assert entry.runtime_data.data.catalog.get("light.room_tiles_kitchen_area_lights").kind == "color_light"
    calls = []

    async def record(call):
        calls.append(dict(call.data))

    hass.services.async_register("light", "turn_on", record)
    ours = hass.data["entity_components"]["light"].get_entity("light.room_tiles_kitchen_area_lights")
    await ours.async_turn_on(brightness=120, hs_color=(30.0, 80.0))
    assert calls[-1]["hs_color"] == (30.0, 80.0) and calls[-1]["brightness"] == 120
    assert kitchen


async def test_remade_area_light_gets_room_tiles_settings_not_leftovers(hass: HomeAssistant) -> None:
    """Room Tiles removed and re-added: HA hands the re-made light its old
    registry settings (here: disabled by the integration, not hidden) -
    Room Tiles' own win: enabled, hidden."""
    kitchen = _kitchen(hass)
    reg = er.async_get(hass)
    old = MockConfigEntry(domain=DOMAIN)
    old.add_to_hass(hass)
    reg.async_get_or_create(
        "light", DOMAIN, "area_lights_" + kitchen.id, suggested_object_id=f"room_tiles_{kitchen.id}_lights",
        config_entry=old, disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    await hass.config_entries.async_remove(old.entry_id)  # (its registry entry is kept as deleted)
    await hass.async_block_till_done()
    await _setup(hass)
    e = reg.async_get("light.room_tiles_kitchen_area_lights")
    assert e is not None and e.disabled_by is None and e.hidden_by is not None


async def test_remade_area_light_is_hidden_even_with_an_old_creation_date(hass: HomeAssistant) -> None:
    """HA restores a deleted entity WITH its old creation date and its old
    "not hidden": still Room Tiles' own - hidden, not exposed."""
    from datetime import timedelta

    from homeassistant.components.homeassistant.exposed_entities import (
        async_expose_entity,
        async_get_entity_settings,
    )
    from homeassistant.setup import async_setup_component
    from homeassistant.util import dt as dt_util

    assert await async_setup_component(hass, "homeassistant", {})
    kitchen = _kitchen(hass)
    reg = er.async_get(hass)
    old = MockConfigEntry(domain=DOMAIN)
    old.add_to_hass(hass)
    e = reg.async_get_or_create("light", DOMAIN, "area_lights_" + kitchen.id, suggested_object_id=f"room_tiles_{kitchen.id}_lights", config_entry=old)
    async_expose_entity(hass, "cloud.alexa", e.entity_id, True)
    await hass.config_entries.async_remove(old.entry_id)
    await hass.async_block_till_done()
    # (as if it was made long ago)
    for d in reg.deleted_entities.values():
        object.__setattr__(d, "created_at", dt_util.utcnow() - timedelta(days=30)) if hasattr(d, "created_at") else None
    await _setup(hass)
    e = reg.async_get("light.room_tiles_kitchen_area_lights")
    assert e.hidden_by is not None and e.disabled_by is None
    assert async_get_entity_settings(hass, e.entity_id)["cloud.alexa"]["should_expose"] is False


async def test_new_vacuum_joins_automatic_boards_asks_about_changed_ones(hass: HomeAssistant) -> None:
    """A vacuum set up later: its tile joins its area's boards the user never
    changed; a changed board isn't touched - the
    answer names the area (the dashboard asks). Auto configure makes a
    board automatic again."""
    kitchen = _kitchen(hass)
    entry = await _setup(hass)
    data = lambda: entry.runtime_data.data  # noqa: E731 - replaced on each edit
    assert data().area(kitchen.id).edited == []

    def vacuum(object_id):
        _ent(hass, "vacuum", object_id, kitchen.id)
        hass.states.async_set(f"vacuum.{object_id}", "docked", {"supported_features": 29212})

    async def set_robot(rid):
        return await hass.services.async_call(
            DOMAIN, "set_robot", {"robot": {"id": rid, "name": rid.title(), "vacuum": f"vacuum.{rid}", "preset": "vacuum"}},
            blocking=True, return_response=True,
        )

    vacuum("rover")
    assert (await set_robot("rover"))["ask"] == []
    board = [(t.kind, t.entity) for t in data().area(kitchen.id).tiles["5x2"]]
    assert board[4] == ("vacuum", "sensor.room_tiles_rover")
    assert ("vacuum", "sensor.room_tiles_rover") in [(t.kind, t.entity) for t in data().area(kitchen.id).tiles["6x3"]]

    # the user moves a tile on 5x2: that board is theirs now
    await hass.services.async_call(DOMAIN, "move_tile", {"area": kitchen.id, "layout": "5x2", "from_slot": 0, "to_slot": 5}, blocking=True)
    assert data().area(kitchen.id).edited == ["5x2"]
    vacuum("mopper")
    assert (await set_robot("mopper"))["ask"] == [kitchen.id]
    assert "sensor.room_tiles_mopper" not in [t.entity for t in data().area(kitchen.id).tiles["5x2"]]
    assert "sensor.room_tiles_mopper" in [t.entity for t in data().area(kitchen.id).tiles["6x3"]]

    # Auto configure: automatic again, with both vacuums
    await hass.services.async_call(DOMAIN, "auto_board", {"area": kitchen.id, "layout": "5x2"}, blocking=True)
    a = data().area(kitchen.id)
    assert a.edited == [] and {"sensor.room_tiles_rover", "sensor.room_tiles_mopper"} <= {t.entity for t in a.tiles["5x2"]}


async def test_auto_configure_an_area_or_every_area(hass: HomeAssistant) -> None:
    """Auto configure without a layout: both of the area's boards; without
    an area: every shown area's boards. All automatic again afterwards."""
    kitchen = _kitchen(hass)
    entry = await _setup(hass)
    data = lambda: entry.runtime_data.data  # noqa: E731 - replaced on each edit
    cellar = next(a for a in data().areas if a.name == "Cellar")

    async def move(area_id, layout):
        await hass.services.async_call(DOMAIN, "move_tile", {"area": area_id, "layout": layout, "from_slot": 0, "to_slot": 5}, blocking=True)

    await move(kitchen.id, "5x2")
    await move(kitchen.id, "6x3")
    await move(cellar.id, "5x2")
    assert data().area(kitchen.id).edited == ["5x2", "6x3"] and data().area(cellar.id).edited == ["5x2"]

    await hass.services.async_call(DOMAIN, "auto_board", {"area": kitchen.id}, blocking=True)
    k = data().area(kitchen.id)
    assert k.edited == [] and k.tiles["5x2"][0].entity is not None and k.tiles["6x3"][0].entity is not None
    assert data().area(cellar.id).edited == ["5x2"]  # another area: untouched

    await move(kitchen.id, "5x2")
    await hass.services.async_call(DOMAIN, "auto_board", {}, blocking=True)
    assert data().area(kitchen.id).edited == [] and data().area(cellar.id).edited == []
