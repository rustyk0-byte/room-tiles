"""HA's translations of Room Tiles (translations/<lang>.json) match its
English (strings.json): only keys English has, with the same {placeholders}.
A key a language leaves out falls back to English."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent / "custom_components" / "room_tiles"
FILES = sorted((ROOT / "translations").glob("*.json"))


def _flat(o, p=""):
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            out.update(_flat(v, f"{p}.{k}" if p else k))
        return out
    return {p: o}


ENGLISH = _flat(json.loads((ROOT / "strings.json").read_text(encoding="utf-8")))


def test_english_is_strings_json():
    assert _flat(json.loads((ROOT / "translations" / "en.json").read_text(encoding="utf-8"))) == ENGLISH


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_a_translation_matches_english(path):
    words = _flat(json.loads(path.read_text(encoding="utf-8")))
    assert set(words) <= set(ENGLISH), set(words) - set(ENGLISH)
    for key, text in words.items():
        assert sorted(re.findall(r"\{\w+\}", text)) == sorted(re.findall(r"\{\w+\}", ENGLISH[key])), key
    # what people see in HA's own screens: set up, Repairs, the entity names,
    # the actions (Developer tools, the automation editor)
    seen = {k for k in ENGLISH if k.split(".")[0] in ("config", "issues", "entity", "services")}
    assert seen <= set(words), seen - set(words)
