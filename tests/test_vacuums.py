"""Which areas each vacuum cleans: read from HA's segment-to-area mapping."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.room_tiles.vacuums import vacuum_areas


async def test_vacuum_areas_from_the_segment_mapping(hass: HomeAssistant) -> None:
    reg = er.async_get(hass)
    matic = reg.async_get_or_create("vacuum", "test", "matic", suggested_object_id="matic")
    reg.async_get_or_create("vacuum", "test", "plain", suggested_object_id="plain")  # no mapping
    reg.async_update_entity_options(
        matic.entity_id, "vacuum", {"area_mapping": {"kitchen": ["1"], "bar_area": ["2", "3"], "attic": []}}
    )
    hass.states.async_set(matic.entity_id, "docked", {"friendly_name": "Matic"})
    assert vacuum_areas(hass) == {matic.entity_id: {"name": "Matic", "areas": ["bar_area", "kitchen"], "unmapped": False}}
    # a room the vacuum reports that isn't mapped
    reg.async_update_entity_options(
        matic.entity_id,
        "vacuum",
        {
            "area_mapping": {"kitchen": ["1"], "bar_area": ["2", "3"]},
            "last_seen_segments": [{"id": "1", "name": "Kitchen"}, {"id": "2", "name": "Bar"}, {"id": "9", "name": "Hallway"}],
        },
    )
    assert vacuum_areas(hass)[matic.entity_id]["unmapped"] is True
