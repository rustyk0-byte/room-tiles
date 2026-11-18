"""Finding supported appliances among HA's entities (appliance_detect.py)."""

from custom_components.room_tiles.appliance_detect import Dev, Ent, find_appliances, redetect

LG_DEVS = {
    "w": Dev("w", "Washer", "LGE", "F3P2CYUBE__ (DEVICE_WASHER)"),
    "d": Dev("d", "Dryer", "LGE", "RV13D4ASJW_D_US (DEVICE_DRYER)"),
}
LG = [
    Ent("sensor.washer_current_status", "lg_thinq", "x_main_current_state", "current_state", "w"),
    Ent("sensor.washer_remaining_time", "lg_thinq", "x_main_remain", "remain", "w"),
    Ent("sensor.washer_total_time", "lg_thinq", "x_main_total", "total", "w"),
    Ent("sensor.dryer_current_status", "lg_thinq", "y_current_state", "current_state", "d"),
    Ent("sensor.dryer_remaining_time", "lg_thinq", "y_remain", "remain", "d"),
]
FP_DEVS = {"f": Dev("f", "EHV416323", "Fisher & Paykel", "DDD616US")}
FP = [
    Ent("sensor.dw_lower_cycle", "ge_home", "ge_home_E1_dishwasher_cycle_state", None, "f"),
    Ent("sensor.dw_lower_time", "ge_home", "ge_home_E1_dishwasher_time_remaining", None, "f"),
    Ent("binary_sensor.dw_lower_door", "ge_home", "ge_home_E1_dishwasher_door_status", None, "f"),
    Ent("sensor.dw_upper_cycle", "ge_home", "ge_home_E1_dishwasher_upper_cycle_state", None, "f"),
    Ent("sensor.dw_upper_time", "ge_home", "ge_home_E1_dishwasher_upper_time_remaining", None, "f"),
    Ent("binary_sensor.dw_upper_door", "ge_home", "ge_home_E1_dishwasher_upper_door_status", None, "f"),
    Ent("sensor.dw_upper_mode", "ge_home", "ge_home_E1_dishwasher_upper_user_setting_cycle_mode", None, "f"),
]


def test_lg_washer_and_dryer_pair_into_laundry():
    [s] = find_appliances(LG, LG_DEVS, set())
    assert s["id"] == "laundry"
    dryer, washer = s["units"]
    assert (dryer["preset"], dryer["status"], dryer["time"]) == (
        "lg_thinq_dryer",
        "sensor.dryer_current_status",
        "sensor.dryer_remaining_time",
    )
    assert washer["preset"] == "lg_thinq_washer"
    assert washer["finished"] == "waiting"
    assert washer["clear"] == ["unit:dryer"]
    assert s["notes"] == []  # both models confirmed
    assert "_model" not in washer


def test_a_lone_washer_without_a_dryer_goes_straight_back_to_idle():
    [s] = find_appliances(LG[:3], LG_DEVS, set())
    assert s["name"] == "Washer"
    assert s["units"][0]["finished"] == "idle"
    assert s["units"][0]["clear"] == []


def test_fp_dishdrawer_two_drawers():
    [s] = find_appliances(FP, FP_DEVS, set())
    upper, lower = s["units"]
    assert (upper["id"], upper["label"], lower["id"], lower["label"]) == ("upper", "Upper", "lower", "Lower")
    assert upper["preset"] == "fp_dishdrawer"
    assert upper["drawer"] is True
    assert (upper["status"], upper["time"], upper["door"]) == (
        "sensor.dw_upper_cycle",
        "sensor.dw_upper_time",
        "binary_sensor.dw_upper_door",
    )
    assert lower["door"] == "binary_sensor.dw_lower_door"


def test_ge_single_dishwasher():
    devs = {"g": Dev("g", "Dishwasher", "GE Appliances", "GDT")}
    ents = [
        Ent("sensor.dw_cycle", "ge_home", "ge_home_Z_dishwasher_cycle_state", None, "g"),
        Ent("sensor.dw_time", "ge_home", "ge_home_Z_dishwasher_time_remaining", None, "g"),
    ]
    [s] = find_appliances(ents, devs, set())
    [u] = s["units"]
    assert s["notes"] == ["Dishwasher: beta - GDT isn't confirmed with Room Tiles yet. It should work; please report how it goes."]
    assert (u["id"], u["label"], u["preset"], u["drawer"], u["door"]) == (
        "dishwasher",
        "Dishwasher",
        "ge_home_dishwasher",
        False,
        None,
    )


def test_already_set_up_units_are_not_offered_again():
    assert find_appliances(LG, LG_DEVS, {"sensor.washer_current_status", "sensor.dryer_current_status"}) == []
    [s] = find_appliances(LG, LG_DEVS, {"sensor.dryer_current_status"}, {"dryer"}, ["dryer"])
    [u] = s["units"]
    assert u["id"] == "washer"
    # the dryer is set up on its own tile: Switch Over until it starts
    assert (u["finished"], u["clear"]) == ("waiting", ["appliance:dryer"])


def test_nothing_found_without_supported_integrations():
    ents = [Ent("sensor.x", "other", "u", "current_state", None)]
    assert find_appliances(ents, {}, set()) == []


def test_an_unconfirmed_model_of_a_verified_brand_is_beta():
    devs = {**LG_DEVS, "w": Dev("w", "Washer", "LGE", "WM4000HWA (DEVICE_WASHER)")}
    [s] = find_appliances(LG, devs, set())
    assert s["notes"] == [
        "Washer: beta - WM4000HWA isn't confirmed with Room Tiles yet. It should work; please report how it goes."
    ]


def test_found_ids_avoid_appliances_already_set_up():
    [s] = find_appliances(LG, LG_DEVS, set(), {"laundry"})
    assert s["id"] == "laundry_2"


def test_set_up_again_matches_by_hardware_and_keeps_id_and_name():
    mine = {"id": "wash", "name": "Utility", "units": [{"status": "sensor.washer_current_status"}]}
    gone = {"id": "old", "name": "Old", "units": [{"status": "sensor.nothing"}]}
    again = redetect(LG, LG_DEVS, [mine, gone])
    assert list(again) == ["wash"]
    assert (again["wash"]["id"], again["wash"]["name"]) == ("wash", "Utility")
    assert [u["id"] for u in again["wash"]["units"]] == ["dryer", "washer"]


def test_several_of_a_kind_each_get_their_own_tile_and_name():
    devs = {
        "a": Dev("a", "Kitchen Dishwasher", "GE Appliances", "GDT"),
        "b": Dev("b", "Bar Dishwasher", "GE Appliances", "GDT"),
    }
    ents = [
        Ent("sensor.a_cycle", "ge_home", "ge_home_A_dishwasher_cycle_state", None, "a"),
        Ent("sensor.b_cycle", "ge_home", "ge_home_B_dishwasher_cycle_state", None, "b"),
    ]
    found = find_appliances(ents, devs, set())
    assert [(s["id"], s["name"]) for s in found] == [
        ("dishwasher", "Kitchen Dishwasher"),
        ("dishwasher_2", "Bar Dishwasher"),
    ]
    # two washers + two dryers: four tiles, none paired automatically
    devs2 = {
        **LG_DEVS,
        "w2": Dev("w2", "Washer 2", "LGE", "F3P2CYUBE (DEVICE_WASHER)"),
        "d2": Dev("d2", "Dryer 2", "LGE", "RV13D4ASJW (DEVICE_DRYER)"),
    }
    ents2 = LG + [
        Ent("sensor.w2", "lg_thinq", "w2_current_state", "current_state", "w2"),
        Ent("sensor.d2", "lg_thinq", "d2_current_state", "current_state", "d2"),
    ]
    found2 = find_appliances(ents2, devs2, set())
    assert sorted(s["name"] for s in found2) == ["Dryer", "Dryer 2", "Washer", "Washer 2"]
    assert len({s["id"] for s in found2}) == 4


# ---- beta brands (2026-11-09), from each integration's source ----------------


def test_samsung_smartthings_washer_and_dryer_pair_up():
    devs = {"w": Dev("w", "Washer", "Samsung", "WF45"), "d": Dev("d", "Dryer", "Samsung", "DVE45")}
    ents = [
        Ent("sensor.washer_job_state", "smartthings", "w_main_job", "washer_job_state", "w"),
        Ent("sensor.washer_completion_time", "smartthings", "w_main_done", "completion_time", "w"),
        Ent("sensor.washer_sub_job_state", "smartthings", "w_sub_job", "washer_sub_job_state", "w"),
        Ent("sensor.dryer_job_state", "smartthings", "d_main_job", "dryer_job_state", "d"),
        Ent("sensor.dryer_completion_time", "smartthings", "d_main_done", "completion_time", "d"),
    ]
    [s] = find_appliances(ents, devs, set())
    dryer, washer = s["units"]
    assert (s["name"], dryer["preset"], washer["preset"]) == ("Laundry", "smartthings_dryer", "smartthings_washer")
    assert (washer["status"], washer["time"]) == ("sensor.washer_job_state", "sensor.washer_completion_time")
    assert (washer["finished"], washer["clear"]) == ("waiting", ["unit:dryer"])


def test_whirlpool_washer():
    devs = {"w": Dev("w", "Washer", "Whirlpool", "WTW8127LW")}
    ents = [
        Ent("sensor.washer_state", "whirlpool", "said1", "washer_state", "w"),
        Ent("sensor.washer_end_time", "whirlpool", "said1-timeremaining", "end_time", "w"),
    ]
    [s] = find_appliances(ents, devs, set())
    [u] = s["units"]
    assert (u["preset"], u["time"]) == ("whirlpool_washer", "sensor.washer_end_time")


def test_bosch_home_connect_dishwasher_and_washer():
    devs = {"a": Dev("a", "Dishwasher", "BOSCH", "SHX88PZ65N"), "b": Dev("b", "Washer", "BOSCH", "WAW285H2UC")}
    ents = [
        Ent("sensor.dishwasher_operation_state", "home_connect", "BOSCH-SHX-1-BSH.Common.Status.OperationState", "operation_state", "a"),
        Ent("sensor.dishwasher_door", "home_connect", "BOSCH-SHX-1-BSH.Common.Status.DoorState", "door", "a"),
        Ent("sensor.dishwasher_finish", "home_connect", "BOSCH-SHX-1-BSH.Common.Option.RemainingProgramTime", "program_finish_time", "a"),
        Ent("switch.dishwasher_extra_dry", "home_connect", "BOSCH-SHX-1-Dishcare.Dishwasher.Option.ExtraDry", None, "a"),
        Ent("sensor.washer_operation_state", "home_connect", "BOSCH-WAW-2-BSH.Common.Status.OperationState", "operation_state", "b"),
        Ent("select.washer_temperature", "home_connect", "BOSCH-WAW-2-LaundryCare.Washer.Option.Temperature", None, "b"),
    ]
    found = {s["units"][0]["preset"]: s["units"][0] for s in find_appliances(ents, devs, set())}
    assert set(found) == {"home_connect_dishwasher", "home_connect_washer"}
    dw = found["home_connect_dishwasher"]
    assert (dw["door"], dw["time"]) == ("sensor.dishwasher_door", "sensor.dishwasher_finish")


def test_miele_dryer_by_its_model():
    devs = {"m": Dev("m", "Dryer", "Miele", "Tumble dryer")}
    ents = [
        Ent("sensor.dryer_status", "miele", "0001-state_status", "status", "m"),
        Ent("sensor.dryer_finish", "miele", "0001-state_finish_timestamp", "finish", "m"),
        Ent("binary_sensor.dryer_door", "miele", "0001-state_signal_door", None, "m"),
    ]
    [s] = find_appliances(ents, devs, set())
    [u] = s["units"]
    assert (u["preset"], u["time"], u["door"]) == ("miele_dryer", "sensor.dryer_finish", "binary_sensor.dryer_door")


def test_ge_profile_laundry():
    devs = {"g": Dev("g", "Washer", "GE Appliances", "PFW870")}
    ents = [
        Ent("sensor.w_machine_state", "ge_home", "ge_home_X1_laundry_machine_state", None, "g"),
        Ent("sensor.w_time", "ge_home", "ge_home_X1_laundry_time_remaining", None, "g"),
        Ent("binary_sensor.w_door", "ge_home", "ge_home_X1_laundry_door", None, "g"),
        Ent("sensor.w_soil", "ge_home", "ge_home_X1_laundry_washer_soil_level", None, "g"),
    ]
    [s] = find_appliances(ents, devs, set())
    [u] = s["units"]
    assert (u["preset"], u["time"], u["door"]) == ("ge_home_washer", "sensor.w_time", "binary_sensor.w_door")


def test_mixed_brands_pair_too():
    devs = {"w": Dev("w", "Washer", "Samsung", "WF45"), **{"d": LG_DEVS["d"]}}
    ents = [Ent("sensor.washer_job_state", "smartthings", "w_main_job", "washer_job_state", "w"), *LG[3:]]
    [s] = find_appliances(ents, devs, set())
    assert [u["preset"] for u in s["units"]] == ["lg_thinq_dryer", "smartthings_washer"]


def test_matter_washer_dryer_dishwasher_never_the_robot():
    devs = {
        "w": Dev("w", "Laundry", "Acme", "WM-1"),
        "d": Dev("d", "Utility Dryer", "Acme", "DR-1"),
        "k": Dev("k", "Kitchen", "Acme", "DW-1"),
        "r": Dev("r", "Matic", "Matic Robots", "Matic"),
    }
    ents = [
        Ent("sensor.w_state", "matter", "S-W-1-OperationalState-96-4", "operational_state", "w"),
        Ent("sensor.w_end", "matter", "S-W-1-OperationalStateCountdownTime-96-2", "estimated_end_time", "w"),
        Ent("select.w_spin", "matter", "S-W-1-MatterLaundryWasherSpinSpeed-83-1", "laundry_washer_spin_speed", "w"),
        Ent("sensor.d_state", "matter", "S-D-1-OperationalState-96-4", "operational_state", "d"),
        Ent("sensor.k_state", "matter", "S-K-1-OperationalState-96-4", "operational_state", "k"),
        Ent("select.k_mode", "matter", "S-K-1-MatterDishwasherMode-89-1", "mode", "k"),
        Ent("sensor.r_state", "matter", "S-R-1-RvcOperationalState-97-4", "operational_state", "r"),
        Ent("vacuum.matic", "matter", "S-R-1-MatterVacuumCleaner-84-1", None, "r"),
    ]
    found = find_appliances(ents, devs, set())
    presets = sorted(u["preset"] for s in found for u in s["units"])
    assert presets == ["matter_dishwasher", "matter_dryer", "matter_washer"]
    laundry = next(s for s in found if s["id"] == "laundry")
    assert laundry["units"][1]["time"] == "sensor.w_end"
