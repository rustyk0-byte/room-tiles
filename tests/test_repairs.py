"""Repairs notices: what comes from outside (a device's state) is shown as
plain text in HA's Markdown."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.room_tiles.const import DOMAIN
from custom_components.room_tiles.repairs import MAX_LISTED, async_update_appliance_questions


async def test_a_device_state_is_never_a_link(hass: HomeAssistant) -> None:
    states = [{"label": "Washer", "state": "[Update needed](https://example.com/login)"}]
    states += [{"label": "Washer", "state": f"count {i}"} for i in range(MAX_LISTED + 5)]
    async_update_appliance_questions(hass, "washer", "Washer", states)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "appliance_question_washer")
    text = issue.translation_placeholders["states"]
    assert "`[Update needed](https://example.com/login)`" in text  # (code: not a link)
    assert text.count("\n") == MAX_LISTED  # (MAX_LISTED lines and "... more")
