"""Nothing Room Tiles creates is exposed to voice assistants (Alexa, Google,
Assist). HA exposes some new entities by default (lights, ...) and the
assistant then announces a new device; Room Tiles' entities are for its
tiles and map - the home's assistant setup stays the user's. A user who
exposes one keeps that choice: only an UNSET choice is set - except on an
entity Room Tiles has just made, whose leftover settings are always reset.
"""

from __future__ import annotations

from homeassistant.components.homeassistant.exposed_entities import (
    async_expose_entity,
    async_get_entity_settings,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

ASSISTANTS = ("cloud.alexa", "cloud.google_assistant", "conversation")


@callback
def own_defaults(hass: HomeAssistant, entity_id: str, fresh: bool) -> None:
    """Room Tiles' own entity: hidden in HA and not exposed to any voice
    assistant. `fresh` = it wasn't in HA's registry just before Room Tiles
    made it (a new install, Room Tiles added again): then these are SET,
    whatever HA restored from the entity's last life (HA keeps a deleted
    entity's settings - and its old creation date). An entity that already
    existed keeps what the user chose (only unset choices are set)."""
    reg = er.async_get(hass)
    entry = reg.async_get(entity_id)
    if entry is None:
        return
    # (voice assistants not loaded - never stops the entity being added)
    try:
        settings = async_get_entity_settings(hass, entity_id)
        for assistant in ASSISTANTS:
            if fresh or "should_expose" not in (settings.get(assistant) or {}):
                async_expose_entity(hass, assistant, entity_id, False)
    except Exception:  # noqa: BLE001
        pass
    if fresh and entry.hidden_by is None:
        reg.async_update_entity(entity_id, hidden_by=er.RegistryEntryHider.INTEGRATION)


@callback
def not_exposed(hass: HomeAssistant, entity_id: str) -> None:
    """An existing entity: unset voice choices become "not exposed"."""
    own_defaults(hass, entity_id, fresh=False)


def is_new(hass: HomeAssistant, entity_id: str) -> bool:
    """Not in HA's registry (yet): Room Tiles is making it now."""
    return er.async_get(hass).async_get(entity_id) is None
