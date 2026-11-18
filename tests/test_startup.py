"""Every Room Tiles entity comes up cleanly when HA starts with stored data
(user, 2026-11-10: a pool sensor once failed only at start-up - the entry
isn't "loaded" yet while its entities are added). A NEW entity kind must be
added to the fixture (tests/fixtures/storage/, the latest version) and to
EXPECTED here."""

import json
import logging
from pathlib import Path

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.room_tiles.const import DOMAIN, STORAGE_MINOR_VERSION

FIXTURE = Path(__file__).parent / "fixtures" / "storage" / f"v1.{STORAGE_MINOR_VERSION}.json"


def _expected(data: dict) -> set[str]:
    """Every sensor the stored data should produce."""
    out = {f"sensor.room_tiles_{a['id']}" for a in data.get("appliances", [])}
    for p in data.get("pools", []):
        if p["layout"] == "shared":  # one combined sensor (+ the Spa Mode switch)
            out.add(f"sensor.room_tiles_{p['id']}")
        else:
            out |= {f"sensor.room_tiles_{p['id']}_{b}" for b in ("pool", "spa") if p.get(b)}
    out |= {f"sensor.room_tiles_{r['id']}" for r in data.get("robots", [])}
    out.add("sensor.room_tiles_panel_link")  # the wall panels' revision (always)
    return out


async def test_every_entity_kind_starts_cleanly(hass: HomeAssistant, hass_storage, caplog) -> None:
    stored = json.loads(FIXTURE.read_text())
    data = stored["data"]
    # the fixture must hold one of every entity kind
    assert data.get("appliances") and data.get("pools") and data.get("robots"), "fixture lacks an entity kind"
    hass_storage[DOMAIN] = stored
    caplog.set_level(logging.ERROR)
    e = MockConfigEntry(domain=DOMAIN)
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    for entity in sorted(_expected(data)):
        assert hass.states.get(entity) is not None, f"{entity} didn't come up"
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not errors, [r.getMessage() for r in errors]
