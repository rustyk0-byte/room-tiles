"""Wording: token substitution from one JSON file per language
(custom_components/room_tiles/wording/<lang>.json)."""

import json
import re
from pathlib import Path

from custom_components.room_tiles import wording
from custom_components.room_tiles.appliance import status_text
from custom_components.room_tiles.appliance_presets import FP_DISHDRAWER, HOME_CONNECT_DISHWASHER, LG_THINQ_WASHER
from custom_components.room_tiles.pool import BodyResult
from custom_components.room_tiles.pool import status_text as pool_status
from custom_components.room_tiles.robot import view
from custom_components.room_tiles.shortnames import rules_for

DIR = Path(wording.__file__).parent / "wording"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def test_every_language_file_is_valid_and_consistent():
    english = json.loads((DIR / "en.json").read_text(encoding="utf-8"))["strings"]
    assert PLACEHOLDER.findall("Heating to {target}") == ["target"]  # the check itself works
    for f in sorted(DIR.glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        assert "strings" in doc and "short_names" not in doc, f.name  # display text only
        for token, text in doc["strings"].items():
            assert token in english, f"{f.name}: unknown token {token}"
            assert set(PLACEHOLDER.findall(text)) == set(PLACEHOLDER.findall(english[token])), (f.name, token)

    # short-name suggestion rules: their own files
    for f in sorted((DIR.parent / "shortening").glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        for pair in doc.get("abbreviations", []):
            assert len(pair) == 2 and all(isinstance(x, str) and x for x in pair), (f.name, pair)


def test_tokens_in_english_and_unknown_languages_fall_back():
    assert wording.t("appliance.clean", "en") == "Clean"
    assert wording.t("appliance.clean", "ja") == "Clean"  # no file: English
    assert wording.t("no.such.token") == "no.such.token"
    assert wording.t("pool.heating_to", "en", target="85°") == "Heating to 85°"


def test_lines_follow_the_language():
    wording.set_language("de")
    try:
        assert status_text(FP_DISHDRAWER, "done", "N/A") == "Sauber"
        assert status_text(LG_THINQ_WASHER, "waiting", "end") == "In den Trockner"
        assert status_text(LG_THINQ_WASHER, "washing", "rinsing") == "Spülen"  # a raw state that's a step
        assert status_text(HOME_CONNECT_DISHWASHER, "paused", "actionrequired") == "Pausiert"
        assert status_text(FP_DISHDRAWER, "washing", "Main Wash") == "Main Wash"  # the brand's own wording
        heating = BodyResult("heating", 80, None, "heating", 85, True)
        assert pool_status("pool", heating, "~55 min") == "Heizt auf 85°, noch ~55 min"
        assert view("docked", "water_tank_empty").status == "Wassertank füllen"
        assert view("returning").status == "Fährt zur Station"
    finally:
        wording.set_language("en")


def test_short_name_rules_come_from_their_own_files():
    assert rules_for("en").drop_vowels is True
    assert ("Badezimmer", "Bad") in rules_for("de").abbreviations
    assert rules_for("ja").abbreviations == ()  # no file: generic rules


def test_accents_and_special_characters_survive_the_pipeline():
    """UTF-8 files -> the status lines: accents, ß, ç, ñ, the French
    no-break space before ':'."""
    from custom_components.room_tiles.robot import view

    for lang, expected in (
        ("de", "Fährt zur Station"),
        ("fr", "Retour à la base"),
        ("es", "Volviendo a la base"),
        ("pt", "Voltando à base"),
    ):
        wording.set_language(lang)
        try:
            assert view("returning").status == expected
        finally:
            wording.set_language("en")
    assert wording.t("robot.error_text", "fr", text="x") == "Erreur : x"
    assert wording.t("pool.offline", "es") == "Sin conexión"
    assert wording.t("robot.alert.dust_bin_full", "de") == "Staubbehälter leeren"
    assert wording.t("step.rinsing", "fr") == "Rinçage"
    # the files hold the real letters, not \\u escapes (only the invisible
    # soft hyphen is written as one)
    raw = (DIR / "de.json").read_text(encoding="utf-8")
    assert "ä" in raw and "\\u00" not in raw.replace("\\u00ad", "")


def test_words_render_in_any_language():
    """Words (tile_words) carry no language: each display renders them in its
    own - whatever HA's language is."""
    import json as _json

    from custom_components.room_tiles.wording import format_minutes, minutes, render, tile_words, w

    word = [w("pool.short.heating"), "\n", minutes(65)]
    assert render(word, "en") == "Heating\n~1h 05m"
    assert render(word, "de") == wording.t("pool.short.heating", "de") + "\n~1:05 h"
    # placeholders filled with words, themselves rendered in the language
    nested = w("pool.off_other_running", body=w("pool.body.spa"))
    assert render(nested, "fr") == wording.t("pool.off_other_running", "fr", body=wording.t("pool.body.spa", "fr"))
    assert render("Main Wash", "de") == "Main Wash"  # a brand's own wording stays
    assert minutes(None) == "" and minutes(0) == "" and minutes(5) == {"min": 5}
    assert format_minutes(45, "en") == "~45m"
    # HA's language changes the `tile` text, never the words
    wording.set_language("de")
    try:
        words = tile_words({"0.2": word, "0.4": ""})
    finally:
        wording.set_language("en")
    assert words == tile_words({"0.2": word, "0.4": ""})
    assert _json.loads(words) == {"0.2": [{"k": "pool.short.heating"}, "\n", {"min": 65}]}


def test_panel_pack_tables_never_share_a_key():
    """The panels' string packs hold the dashboard's strings AND this wording
    (assets/build_panel.py): one key, one meaning."""
    root = Path(wording.__file__).parents[2]
    for code in ("en", "de", "fr", "es", "it", "nl", "pt"):
        ui = json.loads((root / "frontend" / "i18n" / f"{code}.json").read_text(encoding="utf-8"))["strings"]
        words = json.loads((DIR / f"{code}.json").read_text(encoding="utf-8"))["strings"]
        assert not set(ui) & set(words), code


def test_panel_string_packs_are_up_to_date():
    """Each language's string pack (panel_packs/strings-<lang>.rtp.gz, built by
    assets/build_panel.py) holds exactly its tables' texts: a word added
    without rebuilding the packs would show as its key on the panels."""
    import gzip
    import struct

    root = Path(wording.__file__).parents[2]
    packs = root / "custom_components" / "room_tiles" / "panel_packs"
    for code in ("en", "de", "fr", "es", "it", "nl", "pt"):
        want: dict = {}
        for folder in (root / "frontend" / "i18n", DIR):
            want.update(json.loads((folder / "en.json").read_text(encoding="utf-8"))["strings"])
            if code != "en":
                want.update(json.loads((folder / f"{code}.json").read_text(encoding="utf-8"))["strings"])
        data = gzip.decompress((packs / f"strings-{code}.rtp.gz").read_bytes())
        count = struct.unpack_from("<H", data, 6)[0]
        assert count == 1
        _name, _kind, _fmt, _w, _h, _stride, offset, size = struct.unpack_from("<32sBBHHHII8x", data, 64)
        have = json.loads(data[offset : offset + size])
        missing = sorted(set(want) - set(have))
        changed = sorted(k for k in want if k in have and have[k] != want[k])
        assert not missing and not changed, f"strings-{code}: rebuild the packs (python3 assets/build_panel.py) - {missing[:5]} {changed[:5]}"


def test_names_room_tiles_makes_follow_has_language():
    """Its own entities' names, the tile picker's names for them and new
    maps' defaults: in HA's language (stored so)."""
    from types import SimpleNamespace

    from custom_components.room_tiles.light import light_name
    from custom_components.room_tiles.mapgen import generate_maps
    from custom_components.room_tiles.model import default_layers
    from custom_components.room_tiles.pool import switch_name, tile_name

    area = SimpleNamespace(name="Küche")
    try:
        wording.set_language("de")
        assert (tile_name(None), tile_name("spa"), switch_name("spa_mode")) == ("Pool / Whirlpool", "Whirlpool", "Whirlpool-Modus")
        assert light_name(area) == "Küche Raumlicht (Room Tiles)"
        assert default_layers()[0].name == "Hauptebene"
        assert generate_maps([], [])[0].name == "Zuhause"
        from custom_components.room_tiles.appliance_detect import _kind_name

        assert (_kind_name("washer"), _kind_name("dryer"), wording.t("names.laundry")) == ("Waschmaschine", "Trockner", "Wäsche")
        wording.set_language("en")
        assert (tile_name(None), tile_name("pool"), switch_name("spa_mode")) == ("Pool / Spa", "Pool", "Spa Mode")
        assert light_name(SimpleNamespace(name="Kitchen")) == "Kitchen Area Lights (Room Tiles)"
        assert default_layers()[0].name == "Main" and generate_maps([], [])[0].name == "Home"
    finally:
        wording.set_language("en")
