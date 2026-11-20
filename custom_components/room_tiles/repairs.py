"""Room Tiles' notices in HA: short names to review and new devices found
(notifications linking to the dashboard), missing entities, removed
overrides and appliance questions (Repairs).
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from . import ops
from .const import DOMAIN
from .model import RoomTilesData

ISSUE_SHORT_NAMES = "short_names"  # older versions: a repair, now a notification
ISSUE_MISSING = "missing_entities"
ISSUE_OVERRIDE_REMOVED = "area_lights_override_removed"
MAX_LISTED = 12


REVIEW_NOTIFICATION = f"{DOMAIN}_short_names"


def review_keys(data: RoomTilesData) -> set[tuple[str, str]]:
    """What has a short name waiting for review: (kind, id)."""
    return {(kind, item_id) for kind, item_id, _short in ops.needs_review(data)}


@callback
def async_report_review(hass: HomeAssistant, data: RoomTilesData, seen: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """New short names to review: one notification linking to the Short
    names dialog. It goes once nothing is waiting. Names already waiting
    (`seen`, e.g. at startup) don't notify again - the menu's dot says it.
    Returns what's waiting now (the next call's `seen`)."""
    from homeassistant.components import persistent_notification

    from .frontend import PANEL_URL_PATH
    from .wording import t as words

    waiting = review_keys(data)
    if not waiting:
        persistent_notification.async_dismiss(hass, REVIEW_NOTIFICATION)
    elif waiting - seen:
        persistent_notification.async_create(
            hass,
            words("short_names.message", url=f"/{PANEL_URL_PATH}?open=short-names"),
            title=words("short_names.title"),
            notification_id=REVIEW_NOTIFICATION,
        )
    return waiting


@callback
def async_update_missing(hass: HomeAssistant, data: RoomTilesData, disabled: set[str] | None = None) -> None:
    """Tiles / markers / catalog entries whose entity no longer exists in HA.
    Nothing is removed automatically - the user decides (they show "not
    found" meanwhile)."""
    from .arealights import entity_exists

    disabled = disabled or set()
    missing = {
        e: where
        for e, where in ops.referenced_entities(data).items()
        if e not in disabled and not entity_exists(hass, e)
    }
    if not missing:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_MISSING)
        return
    lines = [f"- {e}: {', '.join(w)}" for e, w in sorted(missing.items())]
    if len(lines) > MAX_LISTED:
        lines = lines[:MAX_LISTED] + [f"- ... and {len(lines) - MAX_LISTED} more"]
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_MISSING,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_MISSING,
        translation_placeholders={"count": str(len(missing)), "entities": "\n".join(lines)},
    )


@callback
def async_report_removed_entity(hass: HomeAssistant, entity: str, where: list[tuple[str, dict]]) -> None:
    """An entity Room Tiles used was deleted in HA and has been removed from
    Room Tiles: tell the user what went (a notification, nothing to fix) -
    in HA's language (ops.forget_entity's tokens)."""
    from homeassistant.components import persistent_notification

    from .wording import t as words

    def line(token: str, values: dict) -> str:
        if "n" in values:  # (one / other)
            token += ".one" if values["n"] == 1 else ".other"
        return words(token, **values)

    persistent_notification.async_create(
        hass,
        words("removed.message", entity=entity) + "\n" + "\n".join(f"- {line(t, v)}" for t, v in where),
        title=words("removed.title"),
        notification_id=f"{DOMAIN}_removed_{entity}",
    )


FOUND_NOTIFICATION = f"{DOMAIN}_found"


def _found_keys(found: dict[str, Any]) -> set[str]:
    """The identifying entities of every found (not set up, not ignored) device."""
    return {
        k
        for kind, key in (("appliance", "found"), ("pool", "pools"), ("robot", "robots"))
        for item in found.get(key) or []
        for k in ops.device_keys(kind, item)
    }


@callback
def async_report_found(hass: HomeAssistant, old: dict[str, Any], new: dict[str, Any]) -> None:
    """A compatible appliance / vacuum / pool appeared in HA while Room Tiles
    runs: one notification, linking to the Appliances page. It goes once
    nothing is waiting (set up or ignored). Devices already waiting at
    startup don't notify again (the setup message / the menu's dot say it)."""
    from homeassistant.components import persistent_notification

    from .frontend import PANEL_URL_PATH
    from .wording import t as words

    waiting = _found_keys(new)
    if not waiting:
        persistent_notification.async_dismiss(hass, FOUND_NOTIFICATION)
        return
    if not waiting - _found_keys(old):
        return
    persistent_notification.async_create(
        hass,
        words("found.message", url=f"/{PANEL_URL_PATH}?open=appliances"),
        title=words("found.title"),
        notification_id=FOUND_NOTIFICATION,
    )


@callback
def async_report_dropped_overrides(hass: HomeAssistant, dropped: list[str]) -> None:
    """An Area Lights override entity was deleted: the area now switches all
    its lights. Told once; the user dismisses it."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_OVERRIDE_REMOVED,
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_OVERRIDE_REMOVED,
        translation_placeholders={"areas": ", ".join(dropped)},
    )


def _name(text: str) -> str:
    """A name the device chose (its friendly name), in a notice's title and
    text: never a link or formatting - Markdown's characters and web
    addresses taken out, one line."""
    import re

    text = re.sub(r"[\[\]()<>`*_#!|~:\\]", " ", text)
    text = re.sub(r"(?i)www\.", "www\u200b.", text)
    return " ".join(text.split())[:80]


def _code(text: str) -> str:
    """Text from outside (a device's state...) as Markdown code: shown as it
    is, never as a link or formatting."""
    return "`" + " ".join(text.replace("`", "'").split())[:120] + "`"


ISSUE_APPLIANCE_QUESTION = "appliance_question"


@callback
def async_update_appliance_questions(hass: HomeAssistant, appliance_id: str, name: str, questions: list[dict]) -> None:
    """An appliance reported states its preset doesn't know: a notice pointing
    to the Appliances page (where the user answers); gone once answered."""
    issue_id = f"{ISSUE_APPLIANCE_QUESTION}_{appliance_id}"
    if not questions:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    # (what devices report, shown as code: never links or formatting in HA's
    # Markdown; at most MAX_LISTED - a counter in a state can't grow it)
    lines = [f'- {_code(str(q["label"]))}: {_code(str(q["state"]))}' for q in questions]
    if len(lines) > MAX_LISTED:
        lines = lines[:MAX_LISTED] + [f"- ... and {len(lines) - MAX_LISTED} more"]
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_APPLIANCE_QUESTION,
        translation_placeholders={"name": name, "states": "\n".join(lines)},
    )


ISSUE_PANEL_SCHEMA = "panel_needs"


@callback
def async_report_panel_schema(hass: HomeAssistant, device_id: str, name: str, needs: str | None) -> None:
    """A panel whose firmware doesn't match this Room Tiles (panels.py
    PANEL_SCHEMA): which side needs an update ("firmware" / "integration");
    gone with its next matching request (None)."""
    issue_id = f"{ISSUE_PANEL_SCHEMA}_{device_id}"
    if needs is None:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=f"{ISSUE_PANEL_SCHEMA}_{needs}",
        translation_placeholders={"name": _name(name)},
    )


# ---- fix flows (HA's repairs platform) -------------------------------------------


async def async_create_fix_flow(hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None) -> Any:
    """The fix for "restart to finish updating": a confirm that restarts HA
    (like HACS's own)."""
    from homeassistant import data_entry_flow
    from homeassistant.components.repairs import RepairsFlow

    class RestartFlow(RepairsFlow):
        async def async_step_init(self, user_input: dict[str, str] | None = None) -> data_entry_flow.FlowResult:
            return await self.async_step_confirm()

        async def async_step_confirm(self, user_input: dict[str, str] | None = None) -> data_entry_flow.FlowResult:
            if user_input is not None:
                await self.hass.services.async_call("homeassistant", "restart")
                return self.async_create_entry(data={})
            return self.async_show_form(step_id="confirm")

    return RestartFlow()
