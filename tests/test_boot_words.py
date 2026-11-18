"""The firmware's built-in boot screen wording (boot_words.h) is made from
the dashboard's wording: it must be current, and every line it needs must be
in English."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_boot_words_header_is_current():
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "make_boot_words.py"), "--check"], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_firmware_says_only_boot_words():
    """Every key the firmware's boot screen says (say_ / boot_text_) is in
    the built-in table - else a new panel would show English for it."""
    import re

    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import make_boot_words
    finally:
        sys.path.pop(0)
    src = (ROOT / "firmware" / "components" / "room_tiles" / "room_tiles.cpp").read_text(encoding="utf-8")
    said = set(re.findall(r'(?:say_|boot_text_)\("([a-z_.]+)"', src))
    assert said, "no boot lines found"
    assert said <= set(make_boot_words.KEYS), sorted(said - set(make_boot_words.KEYS))
