"""The legacy panel-setup converter (tools/import_legacy.py), on a tiny
made-up house."""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("import_legacy", ROOT / "tools" / "import_legacy.py")
legacy = importlib.util.module_from_spec(spec)
sys.modules["import_legacy"] = legacy
spec.loader.exec_module(legacy)

PLAN_H = """
static const PlanSeg PLAN_WALLS[] = { {0, 0, 200, 0}, {200, 0, 200, 100} };
static const PlanSeg PLAN_WINDOWS[] = { {50, 0, 80, 0} };
static const PlanSeg PLAN_OPEN[] = { {100, 0, 100, 100} };
static const PlanRect PLAN_FLOORS[] = { {0, 0, 100, 100}, {100, 0, 200, 100}, {0, 0, 100, 100} };
static const PlanPt PLAN_POOL[] = { {-50, 10}, {-20, 10}, {-35, 40} };
static const PlanRoom PLAN_ROOMS[] = {
  {0, 0, 100, 100, 1, "Kitchen", "Kitchen"},
  {100, 0, 200, 100, 2, "Den", "Den", false, 150, 60},
  {-80, 0, 0, 100, 3, "Yard", "Yard", true, -40, 80},
};
static const int PLAN_X0 = -80, PLAN_Y0 = 0, PLAN_X1 = 200, PLAN_Y1 = 100;
static const int PLAN_WALL_W = 5;
"""

ICS = """BEGIN:VCALENDAR
BEGIN:VTODO
UID:u1
SUMMARY:1|light.counter|50|50|1
STATUS:NEEDS-ACTION
END:VTODO
BEGIN:VTODO
UID:u2
SUMMARY:0|lock.front|260|50
END:VTODO
BEGIN:VTODO
UID:u3
SUMMARY:2|fan.den|150|50|0
STATUS:COMPLETED
END:VTODO
BEGIN:VTODO
UID:u4
SUMMARY:bad
END:VTODO
END:VCALENDAR
"""

CONFIG = {
    "names": "Kitchen;Den’s Room;Spare;Outdoors;Extra",
    "lights": "light.kitchen_lights;unknown;light.spare;light.out;light.extra",
    "map_room": "0;1;-1;-1;-1",
    "room0": "light.counter|D|Counter;;map|M|Map;",
    "room0_6x3": "fan.den|F|Den Fan;",
    "room1": "unknown;unknown;",
    "room2": "light.spare|O|Spare;",
    "room3": "light.path|D|Path;light.gate|O|Gate;light.nowhere|O|Lost;light.path|D|A Very Long Tile Name;",
    "room3_6x3": "light.path|D|Path;light.path|D|Path;",
    "room4": "fan.extra|F|Extra Fan;",
    "catalog": "light.counter|D|Counter|light.kitchen_lights; fan.den|F|Den Fan; light.path|D|Garden Path Lights Left; map|M|Map; blank|B|Blank",
}

HA_AREAS = [
    {"id": "kitchen", "name": "Kitchen", "floor_id": "ground"},
    {"id": "den", "name": "Den's Room", "floor_id": "ground"},
    {"id": "spare_room", "name": "Spare room"},
    {"id": "yard", "name": "Yard", "floor_id": "out"},
    {"id": "drive", "name": "Driveway", "floor_id": "out"},
]

OPTS = dict(
    links={"Spare": "spare_room"},
    merges={"Extra": "kitchen"},
    splits=["Outdoors"],
    tile_areas={"light.path": "yard", "light.gate": "drive"},
)


def _convert(**overrides):
    plan = legacy.read_plan(_tmp("plan.h", PLAN_H))
    markers = legacy.read_markers(_tmp("map.ics", ICS))
    return legacy.convert(CONFIG, markers, plan, HA_AREAS, **{**OPTS, **overrides})


_TMP: Path | None = None


def _tmp(name, text):
    path = _TMP / name
    path.write_text(text, encoding="utf-8")
    return path


def setup_module(module):
    import tempfile

    global _TMP
    _TMP = Path(tempfile.mkdtemp())


def test_areas_are_ha_areas():
    doc, notes = _convert()
    areas = {a["id"]: a for a in doc["areas"]}
    assert list(areas) == ["kitchen", "den", "spare_room", "yard", "drive"]
    # names come from HA; a differing panel name becomes the short name
    assert areas["den"]["name"] == "Den's Room" and areas["den"]["short_name"] == "Den’s Room"
    assert areas["spare_room"]["name"] == "Spare room" and areas["spare_room"]["short_name"] == "Spare"
    assert areas["kitchen"]["floor"] == "ground"
    assert areas["den"]["lights"] is None  # "unknown" -> none


def test_unmatched_area_is_an_error():
    import pytest

    with pytest.raises(SystemExit, match="Spare"):
        _convert(links={})


def test_drop():
    doc, notes = _convert(links={}, drops=["Spare"])
    assert "spare_room" not in {a["id"] for a in doc["areas"]}
    assert any("dropped" in n for n in notes)


def test_merge_fills_free_slots():
    doc, notes = _convert()
    kitchen = doc["areas"][0]["tiles"]["5x2"]
    assert kitchen[1]["entity"] == "fan.extra"  # first blank slot
    assert any("merged into 'Kitchen' (1 tiles moved)" in n for n in notes)


def test_split_spreads_tiles_and_dedupes():
    doc, notes = _convert()
    areas = {a["id"]: a for a in doc["areas"]}
    assert [t["entity"] for t in areas["yard"]["tiles"]["5x2"] if t] == ["light.path"]
    assert [t["entity"] for t in areas["yard"]["tiles"]["6x3"] if t] == ["light.path"]
    assert [t["entity"] for t in areas["drive"]["tiles"]["5x2"] if t] == ["light.gate"]
    assert any("light.nowhere has no --tile-area" in n for n in notes)


def test_zones_link_by_name_when_unmapped():
    doc, _ = _convert()
    zones = {z["name"]: z["area"] for z in doc["maps"][0]["zones"]}
    assert zones == {"Kitchen": "kitchen", "Den": "den", "Yard": "yard"}


def test_tiles_positional():
    doc, _ = _convert(merges={}, drops=["Extra"])
    kitchen = doc["areas"][0]["tiles"]
    assert kitchen["5x2"][0] == {"kind": "dimmable_light", "entity": "light.counter"}  # name = catalog's
    assert kitchen["5x2"][1] is None  # cleared slot
    assert kitchen["5x2"][2] == {"kind": "map"}
    assert len(kitchen["5x2"]) == 10 and len(kitchen["6x3"]) == 18
    assert all(t is None for t in doc["areas"][1]["tiles"]["5x2"])  # "unknown" slots


def test_catalog_skips_builtin_kinds():
    doc, _ = _convert()
    entries = {e["entity"]: e for e in doc["catalog"]["entries"]}
    assert set(entries) == {"light.counter", "fan.den", "light.path"}
    assert "group" not in entries["light.counter"]  # no tap-group logic since storage 1.5


def test_map_zones_shapes_and_markers():
    doc, notes = _convert()
    (m,) = doc["maps"]
    assert m["wall_width"] == 5
    assert [z["area"] for z in m["zones"]] == ["kitchen", "den", "yard"]
    assert m["zones"][1]["label"] == [150, 60]
    assert m["zones"][2]["outdoor"] is True
    styles = [s["style"] for s in m["shapes"]]
    assert styles.count("floor") == 2  # duplicate floor rect dropped
    assert styles.count("water") == 1
    markers = {mk["id"]: mk for mk in doc["markers"]}
    assert set(markers) == {"u1", "u2"}  # completed + malformed skipped
    assert markers["u1"]["layer"] == "rooms" and markers["u1"]["show_name"] is True
    assert markers["u2"]["layer"] == "house"
    # u2 sits outside the plan: bounds widened to include it
    assert m["bounds"][2] >= 260
    assert any("bounds widened" in n for n in notes)


def test_output_is_valid_room_tiles_data():
    doc, _ = _convert()
    data = legacy.model.RoomTilesData.from_dict(json.loads(json.dumps(doc)))
    assert data.as_dict() == doc


def test_short_names():
    doc, notes = _convert()
    entries = {e["entity"]: e for e in doc["catalog"]["entries"]}
    assert (entries["light.counter"]["short_name"], entries["light.counter"]["review"]) == ("Counter", False)
    long = entries["light.path"]
    assert len(long["short_name"]) <= 15 and long["review"] is True
    yard = next(a for a in doc["areas"] if a["id"] == "yard")
    # the panel showed "Path" (differs from the catalog name): kept as the tile's own name
    assert yard["tiles"]["5x2"][0] == {"kind": "dimmable_light", "entity": "light.path", "name": "Path"}
