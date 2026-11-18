"""Finding pool / spa systems (pool_detect.py)."""

from custom_components.room_tiles.appliance_detect import Ent
from custom_components.room_tiles.pool_detect import find_pools

S = "QYF5"
JANDY = [
    Ent("sensor.pool_temp", "iaqualink", f"{S}_pool_temp", None, "a"),
    Ent("sensor.spa_temp", "iaqualink", f"{S}_spa_temp", None, "b"),
    Ent("climate.pool", "iaqualink", f"{S}_pool_set_point", None, "c"),
    Ent("climate.spa", "iaqualink", f"{S}_spa_set_point", None, "d"),
    Ent("switch.pool_pump", "iaqualink", f"{S}_pool_pump", None, "e"),
    Ent("switch.spa_pump", "iaqualink", f"{S}_spa_pump", None, "f"),
    Ent("sensor.air_temp", "iaqualink", f"{S}_air_temp", None, "g"),
    Ent("switch.pool_heater", "iaqualink", f"{S}_pool_heater", None, "h"),
    Ent("switch.spa_heater", "iaqualink", f"{S}_spa_heater", None, "i"),
]


def test_jandy_combo_is_shared():
    [s] = find_pools(JANDY, {}, set(), set())
    assert (s["id"], s["name"], s["preset"], s["layout"]) == ("pool", "Pool & Spa", "iaqualink", "shared")
    assert (s["spa_mode"], s["pump"]) == ("switch.spa_pump", "switch.pool_pump")
    assert s["pool"] == {
        "temp": "sensor.pool_temp",
        "heater": "climate.pool",
        "pump": None,
        "pump_with_heater": True,
        "heater_switch": "switch.pool_heater",  # kept off the tiles (the thermostat does it)
    }
    assert (s["spa"]["heater"], s["spa"]["heater_switch"]) == ("climate.spa", "switch.spa_heater")
    assert not any("Beta" in n for n in s["notes"])


def test_pool_only():
    [s] = find_pools([e for e in JANDY if "spa" not in e.unique_id], {}, set(), set())
    assert (s["name"], s["layout"], s["spa"]) == ("Pool", "pool", None)
    assert s["pool"]["pump"] == "switch.pool_pump"


def test_already_set_up_or_taken_id():
    assert find_pools(JANDY, {}, {"sensor.pool_temp"}, set()) == []
    [s] = find_pools(JANDY, {}, set(), {"pool"})
    assert s["id"] == "pool_2"


MAC = "00-C0-33-AA-BB-CC"
PENTAIR = [
    Ent("climate.pool_heat", "screenlogic", f"{MAC}_0", "body_0", "d"),
    Ent("climate.spa_heat", "screenlogic", f"{MAC}_1", "body_1", "d"),
    Ent("switch.pool", "screenlogic", f"{MAC}_505", None, "d", "Pool"),
    Ent("switch.spa", "screenlogic", f"{MAC}_500", None, "d", "Spa"),
    Ent("switch.cleaner", "screenlogic", f"{MAC}_501", None, "d", "Cleaner"),
    Ent("sensor.air_temperature", "screenlogic", f"{MAC}_air_temperature", "air_temperature", "d"),
]


def test_pentair_screenlogic_combo_is_shared_and_reads_through_the_heaters():
    [s] = find_pools(PENTAIR, {}, set(), set())
    assert (s["preset"], s["layout"], s["spa_mode"], s["pump"]) == ("screenlogic", "shared", "switch.spa", "switch.pool")
    assert s["pool"] == {"temp": None, "heater": "climate.pool_heat", "pump": None, "pump_with_heater": True}
    assert s["spa"]["heater"] == "climate.spa_heat"
    assert not any("Beta" in n for n in s["notes"])
    # set up (known by its heater): not offered again
    assert find_pools(PENTAIR, {}, {"climate.pool_heat"}, set()) == []


def test_pentair_pool_only():
    [s] = find_pools([e for e in PENTAIR if "spa" not in e.entity_id], {}, set(), set())
    assert (s["layout"], s["spa"], s["pool"]["pump"]) == ("pool", None, "switch.pool")


SYS = "12345"
HAYWARD = [
    Ent("sensor.backyard_pool_water_temperature", "omnilogic", f"{SYS}_10_water_temperature", None, "h", "Backyard Pool Water Temperature"),
    Ent("sensor.backyard_spa_water_temperature", "omnilogic", f"{SYS}_20_water_temperature", None, "h", "Backyard Spa Water Temperature"),
    Ent("switch.backyard_pool_filter_pump", "omnilogic", f"{SYS}_10_11_pump", None, "h", "Backyard Pool Filter Pump"),
    Ent("switch.backyard_pool_booster", "omnilogic", f"{SYS}_10_12_pump", None, "h", "Backyard Pool Booster Pump"),
    Ent("switch.backyard_spa_filter_pump", "omnilogic", f"{SYS}_20_21_pump", None, "h", "Backyard Spa Filter Pump"),
]


def test_hayward_omnilogic_separate_bodies_without_heaters():
    [s] = find_pools(HAYWARD, {}, set(), set())
    assert (s["preset"], s["layout"], s["spa_mode"]) == ("omnilogic", "separate", None)
    assert s["pool"] == {
        "temp": "sensor.backyard_pool_water_temperature",
        "heater": None,
        "pump": "switch.backyard_pool_filter_pump",
        "pump_with_heater": True,
    }
    assert s["spa"]["pump"] == "switch.backyard_spa_filter_pump"
    assert any("Heating isn't available" in n for n in s["notes"])



def test_a_body_without_a_heater_is_noted():
    no_heater = [e for e in JANDY if "set_point" not in e.unique_id]
    [s] = find_pools(no_heater, {}, set(), set())
    assert s["pool"]["heater"] is None
    assert any("No heater found for the pool" in n for n in s["notes"])
    assert any("No heater found for the spa" in n for n in s["notes"])
    # with heaters: no such note
    [s] = find_pools(JANDY, {}, set(), set())
    assert not any("No heater" in n for n in s["notes"])
