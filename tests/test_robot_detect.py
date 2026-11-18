"""Finding robot vacuums (robot_detect.py)."""

from custom_components.room_tiles.appliance_detect import Dev
from custom_components.room_tiles.robot_detect import Vac, find_robots

MATIC = Vac("vacuum.matic", "matter", "m", 29212, "Matic")
ROOMBA = Vac("vacuum.roomba", "roomba", "r", 13340, "Roomba")
DEVS = {"m": Dev("m", "Matic", "Matic Robots", "Matic"), "r": Dev("r", "Roomba", "iRobot", "i7")}


def test_every_vacuum_is_offered_with_what_it_can_do():
    found = find_robots([MATIC, ROOMBA], {"m": "sensor.matic_operational_error"}, DEVS, set(), set())
    matic, roomba = found
    assert (matic["id"], matic["preset"], matic["error"], matic["clean_area"]) == (
        "matic",
        "matter",
        "sensor.matic_operational_error",
        True,
    )
    assert (roomba["preset"], roomba["error"], roomba["clean_area"]) == ("vacuum", None, False)
    assert any("isn't supported" in n for n in roomba["notes"])
    assert not any("Beta" in n for n in roomba["notes"] + matic["notes"])  # brand status: SUPPORTED.md


def test_set_up_vacuums_are_not_offered_and_ids_stay_unique():
    assert [f["vacuum"] for f in find_robots([MATIC, ROOMBA], {}, DEVS, {"vacuum.matic"}, set())] == ["vacuum.roomba"]
    [f] = find_robots([MATIC], {}, DEVS, set(), {"matic"})
    assert f["id"] == "matic_2"
