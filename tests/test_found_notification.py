"""A compatible device appearing while Room Tiles runs: one notification
with a link to the Appliances page; gone once nothing is waiting."""

from unittest.mock import patch

from homeassistant.core import HomeAssistant

from custom_components.room_tiles.repairs import FOUND_NOTIFICATION, async_report_found

NONE = {"found": [], "pools": [], "robots": []}
DRYER = {"id": "laundry", "name": "Laundry", "units": [{"status": "sensor.dryer_status"}]}
MATIC = {"id": "matic", "name": "Matic", "vacuum": "vacuum.matic"}


async def test_new_device_notifies_once_and_clears(hass: HomeAssistant) -> None:
    pn = "homeassistant.components.persistent_notification"
    with patch(f"{pn}.async_create") as create, patch(f"{pn}.async_dismiss") as dismiss:
        one = {**NONE, "found": [DRYER]}
        async_report_found(hass, NONE, one)
        assert create.call_count == 1
        message = create.call_args.args[1]
        assert "/room-tiles?open=appliances" in message and "Laundry" not in message  # one phrase, no list
        assert create.call_args.kwargs["notification_id"] == FOUND_NOTIFICATION
        assert create.call_args.kwargs["title"] == "Room Tiles found compatible appliances"

        # nothing new (e.g. its settings changed): no second notification
        async_report_found(hass, one, {**one})
        assert create.call_count == 1

        # another one: notified again (the same notification)
        two = {**one, "robots": [MATIC]}
        async_report_found(hass, one, two)
        assert create.call_count == 2

        # one set up, one still waiting: stays; both done: dismissed
        async_report_found(hass, two, {**NONE, "robots": [MATIC]})
        assert create.call_count == 2 and not dismiss.called
        async_report_found(hass, {**NONE, "robots": [MATIC]}, NONE)
        dismiss.assert_called_once_with(hass, FOUND_NOTIFICATION)
