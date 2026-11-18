"""Restart needed after an update: the integration's files vs what HA loaded."""

import os

from custom_components.room_tiles.update_watch import fingerprint


def test_code_changes_count_dashboard_files_dont(tmp_path):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "wording").mkdir()
    (tmp_path / "sensor.py").write_text("a = 1\n")
    (tmp_path / "wording" / "en.json").write_text("{}")
    (tmp_path / "frontend" / "room-tiles.js").write_text("x")
    before = fingerprint(tmp_path)
    assert [p for p, _s, _m in before] == ["sensor.py", "wording/en.json"]

    # the dashboard rebuilt / compiled caches: no restart needed
    (tmp_path / "frontend" / "room-tiles.js").write_text("xy")
    (tmp_path / "__pycache__" / "sensor.cpython-313.pyc").write_bytes(b"0")
    assert fingerprint(tmp_path) == before

    # code updated (HACS writes new files): restart needed
    (tmp_path / "sensor.py").write_text("a = 2\n")
    os.utime(tmp_path / "sensor.py", ns=(1, 1))
    assert fingerprint(tmp_path) != before
    # a new file too
    (tmp_path / "sensor.py").write_text("a = 1\n")
    assert fingerprint(tmp_path) != before


async def test_the_installers_restart_repair_stands_in_for_ours(hass) -> None:
    """The Marketplace's (HA 2026.11) or HACS's own "restart required" repair
    for Room Tiles: Room Tiles doesn't raise a second one."""
    from homeassistant.helpers import issue_registry as ir

    from custom_components.room_tiles.const import DOMAIN
    from custom_components.room_tiles.update_watch import installer_asks_restart

    assert not installer_asks_restart(hass)
    ir.async_create_issue(hass, "marketplace", "restart_required_1462932720_v0.1.0b1", is_fixable=True,
                          issue_domain=DOMAIN, severity=ir.IssueSeverity.WARNING, translation_key="restart_required")
    assert installer_asks_restart(hass)
    ir.async_delete_issue(hass, "marketplace", "restart_required_1462932720_v0.1.0b1")
    ir.async_create_issue(hass, "hacs", "restart_required_123_v1", is_fixable=True,
                          issue_domain=DOMAIN, severity=ir.IssueSeverity.WARNING, translation_key="restart_required")
    assert installer_asks_restart(hass)
    # another integration's restart: not ours
    ir.async_delete_issue(hass, "hacs", "restart_required_123_v1")
    ir.async_create_issue(hass, "marketplace", "restart_required_9_v2", is_fixable=True,
                          issue_domain="other_thing", severity=ir.IssueSeverity.WARNING, translation_key="restart_required")
    assert not installer_asks_restart(hass)
