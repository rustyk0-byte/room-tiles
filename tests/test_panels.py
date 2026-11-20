"""Wall panels: which devices are panels, their settings, signed payload requests."""

import base64
import time

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.room_tiles.const import DOMAIN
from custom_components.room_tiles.model import Area, Panel, RoomTilesData, Tile
from custom_components.room_tiles.panels import (
    ACTION_URL,
    LINK_ENTITY,
    PACK_URL,
    PANEL_SCHEMA,
    PackWatch,
    packs_fingerprint,
    URL,
    PanelDevice,
    check_action,
    popup_entities,
    popup_lists,
    robot_list,
    check_request,
    load_packs,
    pack_for,
    adopt_ha_area,
    payload,
    room_lights,
    resolve,
    schema_mismatch,
    old_signature,
    request_signature,
    answer_signature,
    sync_panels,
)

KEY = bytes(range(32))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _started_long_ago(monkeypatch):
    """(requests here are signed a few seconds back: HA counts as started before them)"""
    from custom_components.room_tiles import panels as p

    monkeypatch.setattr(p, "STARTED", 0)


def signed(method: str, path: str, ts: int | None = None, body: bytes | None = None, key: bytes = KEY,
           node: str = "panel-1", schema: str | None = None, **extra: str) -> dict[str, str]:
    """A panel's query, signed whole the way its firmware does (signing.cpp):
    name, ts, schema, its own values - then sig."""
    from urllib.parse import urlencode

    q = {"name": node, "ts": str(ts if ts is not None else int(time.time())), "schema": schema or str(PANEL_SCHEMA), **extra}
    q["sig"] = request_signature(key, method, path, urlencode(q), body)
    return q


def old_signed(ts: int | None = None, body: bytes | None = None, schema: str | None = str(PANEL_SCHEMA - 1), **extra: str) -> dict[str, str]:
    """An older panel's query (signed the old way)."""
    t = ts if ts is not None else int(time.time())
    q = {"name": "panel-1", "ts": str(t), "sig": old_signature(KEY, "panel-1", t, body)}
    if schema is not None:
        q["schema"] = schema
    return {**q, **extra}


def _raw(q: dict[str, str]) -> str:
    from urllib.parse import urlencode

    return urlencode(q)


def _dev(device_id="d1", node="panel-1", area=None, psk=KEY):
    return PanelDevice(device_id=device_id, node=node, name="Hall panel", area_id=area, psk=psk)


def test_signed_requests_only():
    found = {"d1": _dev()}
    now = 1_800_000_000
    good = signed("GET", URL, now, board="b", build="0123456789abcdef")
    ok = lambda q, path=URL, method="GET", body=None, old_ok=False: check_request(found, method, path, _raw(q), now, body, old_ok)  # noqa: E731
    assert ok(good) is found["d1"]
    assert ok({**good, "sig": good["sig"].upper()}) is found["d1"]
    # wrong key, other panel's name, stale or future time, junk
    assert ok(signed("GET", URL, now, key=b"x" * 32)) is None
    assert ok(signed("GET", URL, now, node="panel-2")) is None
    assert ok(signed("GET", URL, now - 301)) is None
    assert ok(signed("GET", URL, now + 301)) is None
    assert ok({**good, "ts": "soon"}) is None
    # a panel HA has no key for can't be read
    assert check_request({"d1": _dev(psk=None)}, "GET", URL, _raw(good), now) is None
    # the whole request is signed: no value, path or method can be changed
    assert ok({**good, "board": "other"}) is None
    assert ok({**good, "built": "99999999999"}) is None
    assert ok(good, path=PACK_URL) is None
    assert ok(good, method="POST", body=b"{}") is None
    # an older panel's old signature: only where it may use it (its way out)
    old = old_signed(now)
    assert ok(old) is None
    assert ok(old, old_ok=True) is found["d1"]
    assert ok(old_signed(now, schema=None), old_ok=True) is found["d1"]  # (one that didn't say)
    # a key twice (the check and the views must read one value): refused
    assert check_request(found, "GET", URL, _raw(good) + "&sig=" + "0" * 64, now) is None
    assert check_request(found, "GET", URL, "schema=4&" + _raw(old), now, old_ok=True) is None
    # a signature that isn't 64 hex digits: refused (never an error)
    assert ok({**good, "sig": "é"}) is None


def test_the_source_is_a_developer_build():
    from custom_components.room_tiles.const import DEV_BUILD

    assert DEV_BUILD is True  # (tests run from the source; a released install has no assets/)


def test_packs_carry_the_panel_format(tmp_path):
    import gzip as gz
    import struct as st

    packs = load_packs()
    assert packs and all(st.unpack_from("<H", p.data, 4)[0] == PANEL_SCHEMA for p in packs.values())
    # a pack made for another format (a rebuild ahead of this code) isn't served
    other = bytearray(packs["theme-dark"].data)
    st.pack_into("<H", other, 4, PANEL_SCHEMA + 1)
    (tmp_path / "theme-dark.rtp.gz").write_bytes(gz.compress(bytes(other)))
    assert load_packs(tmp_path) == {}


def test_rebuilt_packs_load_once_settled(tmp_path):
    (tmp_path / "theme-dark.rtp.gz").write_bytes(b"one")
    first = packs_fingerprint(tmp_path)
    watch = PackWatch(first)
    assert not watch.settled_change(first)  # nothing new
    (tmp_path / "theme-dark.rtp.gz").write_bytes(b"two, longer")
    changed = packs_fingerprint(tmp_path)
    assert changed != first
    assert not watch.settled_change(changed)  # (maybe still being written)
    assert watch.settled_change(changed)  # the same on the next check: load it
    watch.loaded = changed
    assert not watch.settled_change(changed)
    (tmp_path / "theme-new.rtp.gz").write_bytes(b"x")
    assert not watch.settled_change(packs_fingerprint(tmp_path))
    (tmp_path / "theme-new.rtp.gz").write_bytes(b"xyz")  # still changing
    assert not watch.settled_change(packs_fingerprint(tmp_path))
    assert watch.settled_change(packs_fingerprint(tmp_path))


def test_which_side_needs_an_update():
    assert schema_mismatch(str(PANEL_SCHEMA)) is None
    assert schema_mismatch(str(PANEL_SCHEMA - 1)) == "firmware"
    assert schema_mismatch("") == "firmware"  # (firmware from before the check)
    assert schema_mismatch("x") == "firmware"
    assert schema_mismatch(str(PANEL_SCHEMA + 1)) == "integration"


def test_panels_follow_their_devices():
    data = RoomTilesData(panels=[Panel(id="gone"), Panel(id="d1", theme="dark")])
    assert sync_panels(data, {"d1": _dev(), "d2": _dev("d2", "panel-2")})
    assert [p.id for p in data.panels] == ["d1", "d2"]
    assert data.panel("d1").theme == "dark"  # settings kept
    assert not sync_panels(data, {"d1": _dev(), "d2": _dev("d2", "panel-2")})


def test_settings_defaults():
    data = RoomTilesData(areas=[Area(id="kitchen", name="Kitchen"), Area(id="hall", name="Hall", layout="6x3"), Area(id="attic", name="Attic", hidden=True)])
    p = Panel(id="d1")
    # nothing set: the panel's HA area, that area's starting layout, HA's language
    r = resolve(data, p, _dev(area="hall"), "de-AT")
    assert (r["area"], r["layout"], r["theme"], r["language"]) == ("hall", "6x3", "dark", "de")
    assert r["area_set"]
    # its HA area isn't shown in Room Tiles: the first shown area - and the
    # panel asks for one
    r = resolve(data, p, _dev(area="attic"), "en")
    assert (r["area"], r["area_set"]) == ("kitchen", False)
    # no HA area either (a panel just added): the same
    r = resolve(data, p, _dev(area=None), "en")
    assert (r["area"], r["area_set"]) == ("kitchen", False)
    # set on the panel / in HA: wins
    p2 = Panel(id="d1", area="kitchen", layout="6x3", language="fr")
    r = resolve(data, p2, _dev(area="hall"), "en")
    assert (r["area"], r["layout"], r["language"], r["area_set"]) == ("kitchen", "6x3", "fr", True)


def test_ha_area_seeds_the_panel_once_at_setup():
    data = RoomTilesData(areas=[Area(id="kitchen", name="Kitchen"), Area(id="hall", name="Hall"), Area(id="attic", name="Attic", hidden=True)])
    panel = Panel(id="d1")
    # set up: no room of its own - it takes HA's area, once
    assert adopt_ha_area(data, panel, _dev(area="hall")) is True
    assert panel.area == "hall"
    # from then on it's the panel's: HA's area changing or cleared moves nothing
    assert adopt_ha_area(data, panel, _dev(area="kitchen")) is False
    assert adopt_ha_area(data, panel, _dev(area=None)) is False
    assert resolve(data, panel, _dev(area="kitchen"), "en")["area"] == "hall"
    # nothing in HA, or an area not shown: left unset - the panel asks
    for dev in (_dev(area=None), _dev(area="attic"), _dev(area="gone")):
        fresh = Panel(id="d2")
        assert adopt_ha_area(data, fresh, dev) is False and fresh.area is None
    # a factory reset clears it: set up again, HA's area seeds it again
    panel.area = None
    assert adopt_ha_area(data, panel, _dev(area="kitchen")) is True and panel.area == "kitchen"


def test_payload_has_shown_areas_and_their_entities():
    data = RoomTilesData.from_dict(
        {
            "areas": [
                {"id": "kitchen", "name": "Kitchen", "tiles": {"5x2": [{"kind": "dimmable_light", "entity": "light.counter"}]}},
                {"id": "attic", "name": "Attic", "hidden": True},
            ],
            "catalog": {
                "entries": [
                    {"entity": "light.counter", "kind": "dimmable_light", "short_name": "Counter"},
                    {"entity": "light.unused", "kind": "dimmable_light", "short_name": "Unused"},
                ]
            },
        }
    )
    out = payload(data, Panel(id="d1"), _dev(), "7", "en")
    assert out["schema"] == PANEL_SCHEMA and out["revision"] == "7"
    assert [a["id"] for a in out["areas"]] == ["kitchen"]
    assert len(out["areas"][0]["tiles"]["5x2"]) == 10
    assert out["entities"] == {"light.counter": {"kind": "dimmable_light", "short": "Counter"}}


def test_payload_describes_marker_entities():
    data = RoomTilesData.from_dict(
        {
            "maps": [{"id": "house", "name": "House", "bounds": [0, 0, 100, 100]}],
            "markers": [{"id": "m1", "map": "house", "layer": "house", "entity": "fan.porch", "x": 10, "y": 20}],
            "catalog": {"entries": [{"entity": "fan.porch", "kind": "fan", "short_name": "Porch"}]},
        }
    )
    out = payload(data, Panel(id="d1"), _dev(), "7", "en")
    assert out["entities"] == {"fan.porch": {"kind": "fan", "short": "Porch"}}
    assert out["markers"][0]["entity"] == "fan.porch"


def test_a_marker_entity_may_be_acted_on():
    data = RoomTilesData.from_dict(
        {
            "maps": [{"id": "house", "name": "House", "bounds": [0, 0, 100, 100]}],
            "markers": [{"id": "m1", "map": "house", "entity": "fan.porch", "x": 10, "y": 20}],
        }
    )
    assert check_action(data, {"service": "fan.toggle", "entity": "fan.porch"}) == ("fan", "toggle", "fan.porch", {})
    assert isinstance(check_action(data, {"service": "fan.toggle", "entity": "fan.attic"}), str)


def test_a_panel_places_only_what_its_tile_picker_offers():
    """A panel's set_tile: a catalog entity (with the catalog's kind) or a
    tile without an entity - never any entity (it would then be allowed)."""
    data = RoomTilesData.from_dict(
        {
            "areas": [{"id": "kitchen", "name": "Kitchen"}],
            "catalog": {"entries": [{"entity": "light.counter", "kind": "dimmable_light", "short_name": "Counter"}]},
        }
    )
    edit = lambda **d: check_action(data, {"service": "room_tiles.set_tile", "data": {"area": "kitchen", "layout": "5x2", "slot": 0, **d}})
    ok = edit(entity="light.counter", kind="lock")
    assert ok[3]["entity"] == "light.counter" and ok[3]["kind"] == "dimmable_light"  # (the catalog's kind)
    assert "isn't in the tile list" in edit(entity="lock.front_door", kind="lock")
    assert edit(kind="map")[3]["kind"] == "map"
    assert edit()[1] == "set_tile"  # (no entity, no kind: cleared)
    assert isinstance(edit(kind="lock"), str)


async def test_room_lights_are_the_device_areas_area_lights(hass: HomeAssistant) -> None:
    """Screen off when the following area lights are off: the area lights entity of the room
    the panel is in (its HA device's area), whatever area it shows."""
    data = RoomTilesData(areas=[Area(id="kitchen", name="Kitchen"), Area(id="office", name="Office"),
                                Area(id="den", name="Den", lights="light.den_group"),
                                Area(id="attic", name="Attic", hidden=True, lights="light.attic_group"),
                                Area(id="shed", name="Shed", light_entity=False)])
    # Room Tiles' own group for the office - found by its registry id, renamed or not
    from homeassistant.helpers import entity_registry as er

    er.async_get(hass).async_get_or_create("light", DOMAIN, "area_lights_office", suggested_object_id="office_ceiling")
    hass.states.async_set("light.den_group", "on")
    hass.states.async_set("light.attic_group", "off")
    dev = _dev(area="office")
    out = payload(data, Panel(id="d1", area="kitchen"), dev, "7", "en", room=room_lights(hass, data, dev))
    assert out["panel"]["area"] == "kitchen"
    assert out["panel"]["room_lights"] == ["light.office_ceiling"]
    assert out["panel"]["room"] == "Office"
    # the override picked in area setup wins (over a group, too); a hidden area's too
    er.async_get(hass).async_get_or_create("light", DOMAIN, "area_lights_den", suggested_object_id="room_tiles_den_area_lights")
    assert room_lights(hass, data, _dev(area="den")) == ["light.den_group"]
    assert room_lights(hass, data, _dev(area="attic")) == ["light.attic_group"]
    # no area in HA, one Room Tiles doesn't have, or lights "None": none
    assert room_lights(hass, data, _dev()) == []
    assert room_lights(hass, data, _dev(area="garage")) == []
    assert room_lights(hass, data, _dev(area="shed")) == []
    assert payload(data, Panel(id="d1"), _dev(), "7", "en")["panel"]["room_lights"] == []


def test_the_area_lights_button():
    data = RoomTilesData(areas=[Area(id="kitchen", name="Kitchen"), Area(id="attic", name="Attic", hidden=True)])
    # the payload says which lights it switches
    out = payload(data, Panel(id="d1"), _dev(), "7", "en", area_lights={"kitchen": ["light.a", "light.b"]})
    assert out["areas"][0]["lights"] == ["light.a", "light.b"]
    # a panel may switch a shown area's lights, nothing else
    assert check_action(data, {"service": "room_tiles.area_lights", "data": {"area": "kitchen"}}) == (
        "room_tiles", "area_lights", "", {"area": "kitchen", "action": "toggle"})
    assert isinstance(check_action(data, {"service": "room_tiles.area_lights", "data": {"area": "attic"}}), str)
    assert isinstance(check_action(data, {"service": "room_tiles.area_lights", "data": {"area": "x"}}), str)
    assert isinstance(
        check_action(data, {"service": "room_tiles.area_lights", "data": {"area": "kitchen", "action": "dim"}}), str)


def test_a_markers_pop_up_lists_its_groups_then_scenes():
    from types import SimpleNamespace as NS

    def st(entity_id, members, name=None):
        return NS(entity_id=entity_id, attributes={"entity_id": members, "friendly_name": name or entity_id})

    data = RoomTilesData.from_dict(
        {
            "maps": [{"id": "house", "name": "House", "bounds": [0, 0, 100, 100]}],
            "markers": [{"id": "m1", "map": "house", "entity": "light.lamp", "x": 1, "y": 1}],
            "catalog": {
                "entries": [
                    {"entity": e, "kind": k, "short_name": e}
                    for e, k in [
                        ("light.lamp", "dimmable_light"),
                        ("light.den", "dimmable_light"),
                        ("light.house", "dimmable_light"),
                        ("scene.movie", "scene"),
                        ("scene.evening", "scene"),
                    ]
                ]
            },
        }
    )
    states = [
        st("light.house", ["light.den", "light.porch", "light.hall"]),  # a group of a group
        st("light.den", ["light.lamp", "light.desk"]),
        st("group.not_a_tile", ["light.lamp"]),  # (not in the catalog)
        st("scene.evening", ["light.house"], "Evening"),
        st("scene.movie", ["light.lamp"], "Movie"),
        st("scene.other", ["switch.x"], "Other"),
    ]
    p = popup_lists(states, data)
    assert p == {
        "light.lamp": {
            "groups": ["light.den", "light.house"],
            "more_groups": 0,
            "scenes": ["scene.movie", "scene.evening"],
            "more_scenes": 0,
        }
    }
    assert popup_entities(p) == {"light.den", "light.house", "scene.movie", "scene.evening"}
    assert check_action(data, {"service": "light.toggle", "entity": "light.den"}, popup_entities(p))[2] == "light.den"


def test_robots_with_a_room_queue_and_their_queue_actions():
    data = RoomTilesData.from_dict(
        {"robots": [{"id": "matic", "name": "Matic", "vacuum": "vacuum.matic"}, {"id": "old", "name": "Old", "vacuum": "vacuum.old"}]}
    )
    robots = robot_list(data, {"vacuum.matic": {"areas": ["kitchen", "den"]}}, {"matic": "sensor.room_tiles_matic"})
    assert robots == [
        {"robot": "matic", "sensor": "sensor.room_tiles_matic", "vacuum": "vacuum.matic", "name": "Matic", "areas": ["kitchen", "den"]}
    ]
    ok = check_action(data, {"service": "room_tiles.vacuum_queue", "data": {"robot": "matic", "action": "add", "area": "den", "x": 1}})
    assert ok == ("room_tiles", "vacuum_queue", "", {"robot": "matic", "action": "add", "area": "den"})
    assert isinstance(check_action(data, {"service": "room_tiles.vacuum_queue", "data": {"robot": "nope", "action": "start"}}), str)


def test_language_names_match_the_dashboards():
    import re
    from pathlib import Path

    from custom_components.room_tiles.panels import LANG_NAMES

    ts = (Path(__file__).resolve().parent.parent / "frontend" / "src" / "i18n.ts").read_text(encoding="utf-8")
    block = re.search(r"LANG_NAMES[^{]*\{(.*?)\};", ts, re.S).group(1)
    assert dict(re.findall(r'(\w+):\s*"([^"]+)"', block)) == LANG_NAMES


def test_payload_names_the_themes_in_the_panels_language():
    # (from panel_packs/themes.json - each theme.json's names; the panels
    # show these, so a theme the wording doesn't know still has a name)
    out = payload(RoomTilesData(), Panel(id="d1", language="de"), _dev(), "7", "en")
    assert out["themes"][0] == "dark"
    assert out["theme_names"]["dark"] == "Dunkel"
    assert out["theme_names"]["christmas"] == "Weihnachten"
    out = payload(RoomTilesData(), Panel(id="d1"), _dev(), "7", "en")
    assert out["theme_names"]["light"] == "Light"


def test_payload_offers_the_languages_with_wording():
    packs = load_packs()
    out = payload(RoomTilesData(), Panel(id="d1", language="de"), _dev(), "7", "en", packs)
    assert out["languages"]["en"] == "English" and out["languages"]["de"] == "Deutsch"
    assert out["own"] == {"language": "de", "theme": None}
    assert out["found"] == 0


def test_packs_ship_with_the_integration():
    packs = load_packs()
    assert "theme-dark" in packs and "strings-en" in packs
    for p in packs.values():
        # what the panel checks before storing one: magic + SHA-256 trailer
        import hashlib
        import struct

        size = struct.unpack_from("<I", p.data, 8)[0]
        assert p.data[:4] == b"RTP1" and hashlib.sha256(p.data[:size]).digest() == p.data[size:]
    # the wording is the table itself (key -> text), not the file's wrapper
    import json as _json

    words = packs["strings-de"].data
    off, size = struct.unpack_from("<II", words, 64 + 40)
    table = _json.loads(words[off : off + size])
    assert table["roller.speed"] == "Stufe" and "strings" not in table
    # the panel's language; English when there's no table for it
    assert pack_for(packs, "strings", {"language": "de"}).id.startswith("de-")
    assert pack_for(packs, "strings", {"language": "xx"}).id.startswith("en-")
    assert pack_for(packs, "theme", {"theme": "dark"}).id.startswith("dark-")
    # pictures for "off" (tile icons): drawn (Christmas) or generated (Dark /
    # Light: theme.json "off": "gray") - in each theme's own pack
    xmas = pack_for(packs, "theme", {"theme": "christmas"})
    assert xmas.id.startswith("christmas-") and b"icon_light_off" in xmas.data
    assert b"icon_light_off" in packs["theme-dark"].data
    light = pack_for(packs, "theme", {"theme": "light"})
    assert light.id.startswith("light-") and light.data != packs["theme-dark"].data


async def test_panel_fetches_its_payload(hass: HomeAssistant, hass_client_no_auth) -> None:
    hall = ar.async_get(hass).async_create("Hall")
    esp = MockConfigEntry(domain="esphome", data={"device_name": "panel-1", "noise_psk": base64.b64encode(KEY).decode()})
    esp.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(
        config_entry_id=esp.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")},
        manufacturer="room-tiles",
        model="panel",
        name="Hall panel",
    )
    dr.async_get(hass).async_update_device(dev.id, area_id=hall.id)
    e = MockConfigEntry(domain=DOMAIN)
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    store = e.runtime_data
    assert store.data.panel(dev.id) is not None  # found at setup

    link = hass.states.get(LINK_ENTITY)
    assert link is not None and link.state == str(store.panel_link.revision)

    client = await hass_client_no_auth()
    S = str(PANEL_SCHEMA)
    assert (await client.get(URL, params={"name": "panel-1", "ts": "0", "sig": "x", "schema": S})).status == 403
    ts = int(time.time())
    q = signed("GET", URL, ts)
    r = await client.get(URL, params=q)
    assert r.status == 200
    # HA's answer is signed for this panel and this request (the panel takes
    # nothing that isn't)
    raw_body = await r.read()
    assert r.headers["X-RT-Sig"] == answer_signature(KEY, q["sig"], 200, raw_body)
    assert r.headers["X-RT-Sig"] != answer_signature(KEY, q["sig"], 200, raw_body + b" ")
    body = await r.json()
    assert body["panel"]["area"] == hall.id and body["panel"]["name"] == "Hall panel"
    assert body["packs"]["theme"]["id"].startswith("dark-")

    # its packs, signed the same way
    qp = signed("GET", PACK_URL, ts, pack="theme")
    r = await client.get(PACK_URL, params=qp)
    assert r.status == 200 and r.headers["X-Pack-Id"] == body["packs"]["theme"]["id"]
    pack_bytes = await r.read()
    assert pack_bytes[:4] == b"RTP1"
    assert r.headers["X-RT-Sig"] == answer_signature(KEY, qp["sig"], 200, pack_bytes)
    assert (await client.get(PACK_URL, params={**signed("GET", PACK_URL, ts, pack="theme"), "ts": "0"})).status == 403
    # (the payload's signature isn't the pack's)
    assert (await client.get(PACK_URL, params={**signed("GET", URL, ts), "pack": "theme"})).status == 403

    # firmware that doesn't match: refused with HA's number, and a repair
    # naming the panel and which side needs the update; gone once it matches
    from homeassistant.helpers import issue_registry as ir

    issue = f"panel_needs_{dev.id}"
    for i, (theirs, needs) in enumerate(((None, "firmware"), (str(PANEL_SCHEMA - 1), "firmware"), (str(PANEL_SCHEMA + 1), "integration"))):
        # (an older panel signs the old way - each signature used once; a
        # newer one ours, its number says newer)
        q = old_signed(ts - 10 - i, schema=theirs) if needs == "firmware" else signed("GET", URL, ts - 10 - i, schema=theirs)
        r = await client.get(URL, params=q)
        assert r.status == 426 and (await r.json()) == {"schema": PANEL_SCHEMA}  # (no image for it here)
        assert r.headers["X-RT-Sig"] == answer_signature(KEY, q["sig"], 426, await r.read())
        found = ir.async_get(hass).async_get_issue(DOMAIN, issue)
        assert found is not None and found.translation_key == f"panel_needs_{needs}"
        assert found.translation_placeholders == {"name": "Hall panel"}
    assert (await client.get(URL, params=signed("GET", URL, ts))).status == 200
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue) is None
    # a stranger's request never makes one
    assert (await client.get(URL, params={"name": "panel-1", "ts": "0", "sig": "x"})).status == 403

    # a change panels show moves the revision (and the sensor)
    before = store.panel_link.revision
    store.async_changed(("areas",))
    await hass.async_block_till_done()
    assert store.panel_link.revision == before + 1
    assert hass.states.get(LINK_ENTITY).state == str(before + 1)


def test_what_a_panel_may_do():
    data = RoomTilesData.from_dict(
        {
            "areas": [
                {"id": "kitchen", "name": "Kitchen", "tiles": {"5x2": [{"kind": "onoff_light", "entity": "light.counter"}]}},
                {"id": "attic", "name": "Attic", "hidden": True, "tiles": {"5x2": [{"kind": "switch", "entity": "switch.fan"}]}},
            ]
        }
    )
    ok = check_action(data, {"service": "light.toggle", "entity": "light.counter", "data": {"entity_id": "light.other"}})
    assert ok == ("light", "toggle", "light.counter", {})  # a panel can't retarget the call
    assert isinstance(check_action(data, {"service": "light.toggle", "entity": "light.elsewhere"}), str)
    assert isinstance(check_action(data, {"service": "switch.toggle", "entity": "switch.fan"}), str)  # hidden area
    assert isinstance(check_action(data, {"service": "homeassistant.restart", "entity": "light.counter"}), str)
    assert isinstance(check_action(data, {"service": "switch.toggle", "entity": "light.counter"}), str)

    # Room Tiles' own services: only the listed ones, only their own data
    data.areas[0].tiles["5x2"][1] = Tile(kind="water", entity="sensor.room_tiles_pool")
    ok = check_action(data, {"service": "room_tiles.pool_set_target", "entity": "sensor.room_tiles_pool", "data": {"temperature": 90, "entity": "x"}})
    assert ok == ("room_tiles", "pool_set_target", "sensor.room_tiles_pool", {"temperature": 90})
    assert isinstance(check_action(data, {"service": "room_tiles.remove_area", "entity": "sensor.room_tiles_pool"}), str)
    assert isinstance(check_action(data, {"service": "room_tiles.pool_set_on", "entity": "sensor.elsewhere"}), str)

    # tile editing: its shown areas only, only the edit's own fields
    ok = check_action(data, {"service": "room_tiles.move_tile", "data": {"area": "kitchen", "layout": "5x2", "from_slot": 0, "to_slot": 3, "x": 1}})
    assert ok == ("room_tiles", "move_tile", "", {"area": "kitchen", "layout": "5x2", "from_slot": 0, "to_slot": 3})
    assert isinstance(check_action(data, {"service": "room_tiles.clear_tile", "data": {"area": "attic", "layout": "5x2", "slot": 0}}), str)
    assert isinstance(check_action(data, {"service": "room_tiles.remove_area", "data": {"area": "kitchen"}}), str)


async def test_panel_taps_reach_ha(hass: HomeAssistant, hass_client_no_auth) -> None:
    import json

    from pytest_homeassistant_custom_component.common import async_mock_service

    esp = MockConfigEntry(domain="esphome", data={"device_name": "panel-1", "noise_psk": base64.b64encode(KEY).decode()})
    esp.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(
        config_entry_id=esp.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:01")},
        manufacturer="room-tiles",
        model="panel",
        name="Hall panel",
    )
    ar.async_get(hass).async_create("Kitchen")
    e = MockConfigEntry(domain=DOMAIN)
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    store = e.runtime_data
    kitchen = store.data.areas[0]
    from custom_components.room_tiles.model import Tile

    kitchen.tiles["5x2"][0] = Tile(kind="onoff_light", entity="light.counter")
    calls = async_mock_service(hass, "light", "toggle")
    client = await hass_client_no_auth()

    def post(body: dict, ts: int | None = None):
        raw = json.dumps(body).encode()
        ts = ts or int(time.time())
        return raw, signed("POST", ACTION_URL, ts, raw)

    raw, q = post({"service": "light.toggle", "entity": "light.counter"})
    assert (await client.post(ACTION_URL, params=q, data=raw)).status == 200
    await hass.async_block_till_done()
    assert len(calls) == 1 and calls[0].data["entity_id"] == "light.counter"
    # the same request again (a replay) is refused
    assert (await client.post(ACTION_URL, params=q, data=raw)).status == 409
    # ... its signature in other letter cases too (the same signature)
    assert (await client.post(ACTION_URL, params={**q, "sig": q["sig"].upper()}, data=raw)).status == 409
    mixed = "".join(c.upper() if i % 2 else c for i, c in enumerate(q["sig"]))
    assert (await client.post(ACTION_URL, params={**q, "sig": mixed}, data=raw)).status == 409
    # ... or with another sig= in front of it (HA would read that one first)
    from urllib.parse import urlencode

    url = ACTION_URL + "?" + urlencode({"sig": "1" * 64}) + "&" + urlencode(q)
    assert (await client.post(url, data=raw)).status == 403
    assert len(calls) == 1
    # a body that isn't the one signed is refused
    _raw, q2 = post({"service": "light.toggle", "entity": "light.counter"}, int(time.time()) - 1)
    tampered = json.dumps({"service": "light.toggle", "entity": "light.other"}).encode()
    assert (await client.post(ACTION_URL, params=q2, data=tampered)).status == 403
    # not on its boards
    raw, q = post({"service": "light.toggle", "entity": "light.other"}, int(time.time()) - 2)
    assert (await client.post(ACTION_URL, params=q, data=raw)).status == 403
    # its own settings
    raw, q = post({"settings": {"layout": "6x3"}}, int(time.time()) - 3)
    assert (await client.post(ACTION_URL, params=q, data=raw)).status == 200
    assert store.data.panel(dev.id).layout == "6x3"
    raw, q = post({"settings": {"layout": "9x9"}}, int(time.time()) - 4)
    assert (await client.post(ACTION_URL, params=q, data=raw)).status == 400
    # signed before this HA run started (the replay guard was empty then): refused
    from custom_components.room_tiles import panels as panels_mod

    panels_mod.STARTED = time.time() + 100
    raw, q = post({"service": "light.toggle", "entity": "light.counter"}, int(time.time()) - 5)
    assert (await client.post(ACTION_URL, params=q, data=raw)).status == 409
    panels_mod.STARTED = 0
    # a body bigger than any tap is never read (413)
    raw, q = post({"service": "light.toggle", "entity": "light.counter", "pad": "x" * 70000}, int(time.time()) - 6)
    assert (await client.post(ACTION_URL, params=q, data=raw)).status == 413


def _fw_image(board="elecrow-p4-7in-v1.2-es", built="2026-11-15 18:33:30 -0500", elf=b"\x07" * 32, schema=PANEL_SCHEMA) -> bytes:
    """An ESPHome-built generic panel image as Room Tiles reads it (firmware.py)."""
    import struct

    from custom_components.room_tiles.firmware import APP_DESC, APP_DESC_MAGIC, _ELF_SHA

    data = bytearray(0x400)
    data[0] = 0xE9
    struct.pack_into("<I", data, APP_DESC, APP_DESC_MAGIC)
    data[_ELF_SHA : _ELF_SHA + 32] = elf
    tag = f"RT-IMAGE:{board}:generic:{schema};".encode()
    data[0x200 : 0x200 + len(tag)] = tag
    stamp = built.encode() + b"\0"
    data[0x300 : 0x300 + len(stamp)] = stamp
    return bytes(data)


async def test_firmware_tries_survive_a_restart(hass: HomeAssistant, hass_storage) -> None:
    """The automatic installs' tries per (panel, build) are kept: a build that
    won't take isn't tried again after every HA restart (AUTO_TRIES)."""
    from types import SimpleNamespace

    from pytest_homeassistant_custom_component.common import flush_store

    from custom_components.room_tiles.const import FW_TRIES_KEY
    from custom_components.room_tiles.store import RoomTilesStore

    hass_storage[FW_TRIES_KEY] = {"version": 1, "key": FW_TRIES_KEY, "data": {"tries": [["dev1", "abc", 2], ["broken"]]}}
    store = RoomTilesStore(hass)
    await store.async_load()
    assert store.fw_tries == {("dev1", "abc"): 2}
    # another download counted and saved; a build no longer offered dropped
    store.fw_images = {"elecrow-p4-7in-v1.0-es": SimpleNamespace(build="abc")}
    store.firmware_downloaded("dev1", "abc")
    store.firmware_downloaded("dev2", "gone")
    await flush_store(store._fw_tries_store)  # (the delayed save, written now)
    assert hass_storage[FW_TRIES_KEY]["data"]["tries"] == [["dev1", "abc", 3]]
    # loaded again (an HA restart): the count is there
    again = RoomTilesStore(hass)
    await again.async_load()
    assert again.fw_tries == {("dev1", "abc"): 3}


async def test_an_automatic_update_waits_until_the_panel_fetches_it(hass: HomeAssistant) -> None:
    """The Panels page and HA's update card: an automatic install is
    "waiting" until the panel fetches the image (nobody's using it then);
    one asked for by hand is under way at once."""
    from types import SimpleNamespace

    from custom_components.room_tiles.store import RoomTilesStore

    store = RoomTilesStore(hass)
    await store.async_load()
    store.fw_images = {"b": SimpleNamespace(build="new")}
    store.fw_install["dev1"] = "new"
    store.fw_auto.add("dev1")
    assert not store.firmware_installing("dev1")  # (waiting)
    store.firmware_downloaded("dev1", "old")  # (another build: still waiting)
    assert not store.firmware_installing("dev1")
    store.firmware_downloaded("dev1", "new")
    assert store.firmware_installing("dev1")
    store.firmware_install("dev2", "new")  # (by hand)
    assert store.firmware_installing("dev2")
    assert not store.firmware_installing("dev3")


async def test_panel_updates(hass: HomeAssistant, hass_client_no_auth, tmp_path) -> None:
    """Room Tiles updates its panels: by itself when they run something
    older ("Update panels automatically", the offer marked auto), never with
    something older than what they run, not for ever when it doesn't take,
    and always - from the 426 answer - a panel too old for this Room Tiles."""
    from custom_components.room_tiles.firmware import AUTO_TRIES
    from custom_components.room_tiles.panels import FIRMWARE_URL

    hass.config.config_dir = str(tmp_path)
    folder = tmp_path / "room_tiles_firmware"
    folder.mkdir()
    board = "elecrow-p4-7in-v1.2-es"
    (folder / "new.bin").write_bytes(_fw_image(board))
    esp = MockConfigEntry(domain="esphome", data={"device_name": "panel-1", "noise_psk": base64.b64encode(KEY).decode()})
    esp.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(
        config_entry_id=esp.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")},
        manufacturer="room-tiles",
        model="panel",
        name="Hall panel",
    )
    e = MockConfigEntry(domain=DOMAIN)
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    store = e.runtime_data
    image = store.fw_images[board]
    client = await hass_client_no_auth()

    import itertools

    back = itertools.count(1)

    def q(build="ff" * 8, built=None, schema=str(PANEL_SCHEMA), path=URL, **more):
        more.setdefault("ts", int(time.time()) - next(back))  # (each request its own signature)
        extra = {"board": board, "build": build, "generic": "1"}
        if built is not None:
            extra["built"] = str(built)
        if schema != str(PANEL_SCHEMA):  # (an older panel: the old way)
            return old_signed(schema=schema, **extra, **more)
        return signed("GET", path, **extra, **more)

    when = int(image.built_ts)
    # running something newer (flashed by hand): left alone
    body = await (await client.get(URL, params=q(built=when + 3600))).json()
    assert "firmware" not in body and dev.id not in store.fw_install
    # running something older: offered, marked automatic
    body = await (await client.get(URL, params=q(built=when - 86400))).json()
    assert body["firmware"] == {"build": image.build, "size": image.size, "sha256": image.sha256, "auto": True}
    # downloads that don't take: tried AUTO_TRIES times, then left for the user
    for _ in range(AUTO_TRIES):
        fq = q(build=image.build, built=when - 86400, path=FIRMWARE_URL)
        r = await client.get(FIRMWARE_URL, params=fq)
        assert r.status == 200 and len(await r.read()) == image.size
        # (the same request again - caught and resent - doesn't count as a try)
        assert (await client.get(FIRMWARE_URL, params=fq)).status == 409
        await client.get(URL, params=q(built=when - 86400))  # (back on its old build)
    body = await (await client.get(URL, params=q(built=when - 86400))).json()
    assert "firmware" not in body
    # the setting off: nothing offered by itself
    store.fw_tries.clear()
    store.data.settings.auto_update_panels = False
    store.async_changed(("settings",))
    body = await (await client.get(URL, params=q(built=when - 86400))).json()
    assert "firmware" not in body
    # too old for this Room Tiles: the 426 answer carries the image, its
    # download stays open, whatever the setting says
    r = await client.get(URL, params=q(built=when + 3600, schema=str(PANEL_SCHEMA - 1)))
    assert r.status == 426
    answer = await r.json()
    assert answer["schema"] == PANEL_SCHEMA and answer["firmware"]["build"] == image.build
    # (an old panel's report isn't signed: nothing of it is kept)
    assert store.fw_reports[dev.id].built != when + 3600
    assert "auto" not in answer["firmware"]
    r = await client.get(FIRMWARE_URL, params=q(schema=str(PANEL_SCHEMA - 1), build=image.build))
    assert r.status == 200
    # ... but nothing else: its tap is answered "update needed", not done
    import json as _json

    tap = _json.dumps({"service": "light.toggle", "entity": "light.x"}).encode()
    r = await client.post(ACTION_URL, params=old_signed(body=tap), data=tap)
    assert r.status == 426
    # installed: done
    await client.get(URL, params=q(build=image.build, built=when))
    assert dev.id not in store.fw_install


async def test_a_left_over_room_tiles_device_goes(hass: HomeAssistant) -> None:
    """Room Tiles makes no devices of its own: one left on its entry (an
    older version's) is removed at setup."""
    e = MockConfigEntry(domain=DOMAIN)
    e.add_to_hass(hass)
    stale = dr.async_get(hass).async_get_or_create(
        config_entry_id=e.entry_id, connections={(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:00:00:01")}, name="Room Tiles"
    )
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    assert dr.async_get(hass).async_get(stale.id) is None


def test_a_round_panel_gets_the_round_theme_pack():
    """The round panel's theme pack: the theme's round cut (only what it
    draws); a theme without one, or any other panel: the full pack."""
    from custom_components.room_tiles.panels import Pack

    packs = {
        "theme-dark": Pack("dark-1", b"x"),
        "theme-dark-round": Pack("dark-round-1", b"x"),
        "theme-light": Pack("light-1", b"x"),
    }
    assert pack_for(packs, "theme", {"theme": "dark", "round": True}).id == "dark-round-1"
    assert pack_for(packs, "theme", {"theme": "dark"}).id == "dark-1"
    assert pack_for(packs, "theme", {"theme": "light", "round": True}).id == "light-1"  # (no round cut yet)
    out = payload(RoomTilesData(), Panel(id="d1", theme="dark"), _dev(), "7", "en", packs, round_panel=True)
    assert out["packs"]["theme"]["id"] == "dark-round-1" and out["panel"]["round"] is True


def test_a_refused_settings_change_changes_nothing():
    from custom_components.room_tiles.panels import apply_settings

    data = RoomTilesData.from_dict({"areas": [{"id": "kitchen", "name": "Kitchen"}]})
    p = Panel(id="d1")
    assert apply_settings(data, p, {"settings": {"theme": "light", "area": "gone_area"}}) == "no area gone_area"
    assert (p.theme, p.area) == (None, None)
    assert apply_settings(data, p, {"settings": {"theme": "light", "area": "kitchen"}}) is None
    assert (p.theme, p.area) == ("light", "kitchen")
    assert apply_settings(data, p, {"settings": {"theme": None}}) is None and p.theme is None


async def test_a_panel_action_ha_refuses_is_logged(hass: HomeAssistant, caplog) -> None:
    """Not waited for: a refusal is a log line, never an unhandled task error."""
    from custom_components.room_tiles.panels import _call_for_panel

    await _call_for_panel(hass, Panel(id="d1"), "light", "no_such_action", {"entity_id": "light.x"})
    assert "wasn't done" in caplog.text
