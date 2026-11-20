"""The demo home on a panel (demo.py - a developer build's, for panel
screenshots)."""

from types import SimpleNamespace

from custom_components.room_tiles import demo


def _home():
    return {
        "area": "living_room",
        "home": {
            "areas": [{"id": "kitchen", "layout": "5x2"}, {"id": "living_room", "layout": "6x3"}],
            "entities": {"light.sofa": {"kind": "dimmer"}},
            "catalog": [], "floors": {}, "maps": [], "markers": [], "popups": {}, "robots": [],
        },
        "states": {"light.sofa": {"": "on", "brightness": "180"}},
    }


def test_values_as_esphome_sends_them():
    assert demo.esphome_value(True) == "on"
    assert demo.esphome_value(False) == "off"
    assert demo.esphome_value(21.5) == "21.5"
    assert demo.esphome_value(["a", "b"]) == "['a', 'b']"
    st = SimpleNamespace(entity_id="light.sofa", state="on", attributes={"brightness": 180, "effect": None, "on": True})
    assert demo.states_of([st]) == {"light.sofa": {"": "on", "brightness": "180", "on": "on"}}


def test_the_panel_keeps_its_own_settings_and_gets_the_demo_home():
    real = {
        "schema": 5, "revision": "7",
        "panel": {"id": "d1", "name": "Hall", "area": "attic", "area_set": True, "layout": "5x2", "theme": "light",
                  "language": "de", "room_lights": ["light.hall"], "room": "Hall"},
        "areas": [{"id": "attic"}], "entities": {"light.hall": {}}, "found": 2,
        "firmware": {"build": "x"}, "packs": {"theme": {"id": "t"}},
    }
    out = demo.apply(real, _home())
    assert [a["id"] for a in out["areas"]] == ["kitchen", "living_room"]
    assert out["entities"] == {"light.sofa": {"kind": "dimmer"}}
    assert out["panel"]["theme"] == "light" and out["panel"]["language"] == "de"  # (its own)
    assert out["panel"]["area"] == "living_room" and out["panel"]["layout"] == "6x3"
    assert out["panel"]["room_lights"] == [] and out["panel"]["room"] == ""
    assert out["found"] == 0 and "firmware" not in out
    assert out["packs"] == {"theme": {"id": "t"}} and out["revision"] == "7"
    assert out["demo"] == {"states": {"light.sofa": {"": "on", "brightness": "180"}}}
    assert real["panel"]["area"] == "attic"  # (the real payload untouched)


def test_which_panels_show_it(tmp_path):
    import json

    dev = SimpleNamespace(name="Hall panel", node="room-tiles-abc123")
    assert demo.read(tmp_path) == (set(), None)
    assert demo.fingerprint(tmp_path) == ()
    (tmp_path / "panels.txt").write_text("Hall panel\n\n  other  \n")
    names, home = demo.read(tmp_path)
    assert names == {"Hall panel", "other"} and home is None
    assert not demo.shows_demo(names, home, dev)  # (nothing to show yet)
    (tmp_path / "panel.json").write_text(json.dumps(_home()))
    names, home = demo.read(tmp_path)
    assert demo.shows_demo(names, home, dev)
    assert demo.shows_demo({"room-tiles-abc123"}, home, dev)  # (by its node name too)
    assert not demo.shows_demo({"Kitchen panel"}, home, dev)
    (tmp_path / "panel.json").write_text("{not json")
    assert demo.read(tmp_path)[1] is None
    assert len(demo.fingerprint(tmp_path)) == 2


def test_a_demo_panels_own_picks_hold_while_it_shows_the_demo():
    from custom_components.room_tiles.model import Panel

    shown = Panel(id="d1", area="attic", theme="dark")
    picked = demo.pick(shown, _home(), {"settings": {"area": "kitchen", "theme": "light"}}, ("dark", "light"), ("5x2", "6x3"))
    assert picked.area == "kitchen" and picked.theme == "light" and shown.theme == "dark"  # (a copy: nothing saved)
    out = demo.apply({"panel": {"layout": "5x2"}}, _home(), picked)
    assert out["panel"]["area"] == "kitchen"
    # a pick of only its theme: its real area (copied along) isn't the demo's
    theme_only = demo.pick(shown, _home(), {"settings": {"theme": "light"}}, ("dark", "light"), ("5x2",))
    assert demo.apply({"panel": {}}, _home(), theme_only)["panel"]["area"] == "living_room"
    # checked: a real home's area, an unknown theme or setting - refused
    for bad in ({"area": "attic"}, {"theme": "neon"}, {"layout": "9x9"}, {"wifi": "x"}):
        assert demo.pick(shown, _home(), {"settings": bad}, ("dark", "light"), ("5x2", "6x3")) is None
    assert demo.pick(shown, _home(), {"service": "light.toggle"}, ("dark",), ("5x2",)) is None
