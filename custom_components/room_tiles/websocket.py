"""Websocket feed for the Room Tiles dashboard (and anything else that wants
live data): `room_tiles/subscribe`.

Messages on the subscription:
  {"type": "full",   "schema": N, "data": {areas, maps, markers, catalog,
                                            settings, area_lights, disabled,
                                            vacuums}}
      once, right after subscribing
  {"type": "update", "schema": N, "data": {<only the changed sections>}}
      after every change (a tile edit sends just "areas"; map geometry, the
      big part, only when a map changes)
  {"type": "reset"}
      Room Tiles was unloaded / reloaded: subscribe again
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, PAYLOAD_SCHEMA

TYPE_SUBSCRIBE = f"{DOMAIN}/subscribe"
TYPE_REPORT_PREVIEW = f"{DOMAIN}/report_preview"
TYPE_PROBLEM_CYCLES = f"{DOMAIN}/problem_cycles"
TYPE_RECORDING = f"{DOMAIN}/recording"


@callback
def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_report_preview)
    websocket_api.async_register_command(hass, ws_problem_cycles)
    websocket_api.async_register_command(hass, ws_recording)


def _store(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg_id: int) -> Any:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_error(msg_id, "not_set_up", "Room Tiles is not set up")
        return None
    return entries[0].runtime_data


_SUBJECT = {
    vol.Required("subject"): vol.In(["appliance", "pool", "robot"]),
    vol.Required("target"): str,  # (its id - "id" is the message's own)
    vol.Optional("unit"): str,
}


@websocket_api.websocket_command({vol.Required("type"): TYPE_PROBLEM_CYCLES, **_SUBJECT})
@websocket_api.async_response
async def ws_problem_cycles(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Report a problem / how it went: an appliance's / pool's / vacuum's
    recent cycles in HA's history (cycles.py) - {history, running, cycles:
    [{start, end}], windows}, times for the user's eyes - and the features a
    model report asks about (model_report.py)."""
    import time

    from .cycles import async_find_cycles, subject
    from .model_report import features

    store = _store(hass, connection, msg["id"])
    if store is None:
        return
    sub = subject(hass, store.data, msg["subject"], msg["target"], msg.get("unit", ""))
    if sub is None:
        connection.send_error(msg["id"], "not_found", "no such appliance, pool or vacuum")
        return
    found = await async_find_cycles(hass, sub, time.time())
    found["features"] = features(store.data, sub.kind, sub.id, sub.unit)
    connection.send_result(msg["id"], found)


@websocket_api.websocket_command(
    {
        vol.Required("type"): TYPE_RECORDING,
        vol.Required("action"): vol.In(["start", "stop", "delete", "update"]),
        **_SUBJECT,
        vol.Optional("description"): vol.All(str, vol.Length(max=4000)),
        vol.Optional("opened"): bool,
    }
)
@callback
def ws_recording(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Report a problem: record the next cycle of an appliance / pool /
    vacuum (start), end it now (stop), throw it away (delete), or keep the
    user's words / that GitHub was opened (update). The recordings are in
    the feed ("recordings", keyed "<subject>:<id>")."""
    import time

    store = _store(hass, connection, msg["id"])
    if store is None:
        return
    rec = store.recordings
    action, key = msg["action"], f"{msg['subject']}:{msg['target']}"
    if action == "start":
        ok = rec.start(store.data, msg["subject"], msg["target"], msg.get("unit", ""), msg.get("description", ""), time.time()) is not None
    elif action == "stop":
        ok = rec.stop(key, time.time())
    elif action == "delete":
        ok = rec.delete(key)
    else:
        ok = rec.update(key, description=msg.get("description"), opened=msg.get("opened"))
    if not ok:
        connection.send_error(msg["id"], "not_found", "no such appliance, pool, vacuum or recording")
        return
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): TYPE_REPORT_PREVIEW,
        vol.Required("kind"): vol.In(["test", "model", "unknown_state", "recording", "problem", "bug", "idea", "question"]),
        vol.Optional("draft"): dict,
    }
)
@websocket_api.async_response
async def ws_report_preview(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """A report as it would be sent (report.py): the draft scrubbed with this
    home's own words, Room Tiles' and HA's versions added - the exact
    payload, what it holds (summary: wording keys), what was left out, and
    the GitHub issue (title, body, where). Nothing is sent from here: the
    user opens GitHub and submits it there."""
    from homeassistant.const import __version__ as HA_VERSION

    from .const import DEV_BUILD
    from .report import build_unknown_state, description_warnings, device_facts, issue, sample_report, scrub, secrets_from_hass, summary
    from .store import VERSION

    kind = msg["kind"]
    if kind in ("problem", "model"):
        # (the dashboard names the appliance / pool / vacuum and the cycle - a
        # past one or the last hours by their times, or the recorded one; HA
        # builds the report from the cycle itself. A model report: how it
        # went and each feature's answer, a cycle only if the user added one)
        import time

        from homeassistant.helpers import area_registry as ar

        from .cycles import async_history_cycle, problem_draft, subject
        from .model_report import features, model_draft
        from .report import OUTCOMES

        store = _store(hass, connection, msg["id"])
        if store is None:
            return
        d = msg.get("draft") or {}
        words = str(d.get("description") or "")
        if kind == "model" and d.get("outcome") not in OUTCOMES:
            connection.send_error(msg["id"], "invalid_format", "a model report needs how it went")
            return
        sub = subject(hass, store.data, str(d.get("subject")), str(d.get("target")), str(d.get("unit") or ""))
        if sub is None:
            connection.send_error(msg["id"], "not_found", "no such appliance, pool or vacuum")
            return
        cycle = None
        if d.get("recorded") and kind == "problem":
            cycle = store.recordings.cycle(store.data, sub.key)
        elif "start" in d or kind == "problem":
            try:
                start, end = float(d["start"]), float(d["end"])
            except (KeyError, TypeError, ValueError):
                connection.send_error(msg["id"], "invalid_format", "a cycle needs its start and end")
                return
            cycle = await async_history_cycle(hass, sub, start, end, time.time(), window=bool(d.get("window")))
        if cycle is None and kind == "problem":
            connection.send_error(msg["id"], "not_found", "no such cycle")
            return
        if cycle is not None:
            areas = {a.id for a in ar.async_get(hass).async_list_areas()}
            draft = problem_draft(cycle, words, areas)
        else:
            draft = {"kind_of_device": sub.kind_of_device, "preset": sub.preset, **({"layout": sub.layout} if sub.layout else {})}
        if kind == "model":
            draft.pop("description", None)
            draft.update(model_draft(features(store.data, sub.kind, sub.id, sub.unit), str(d["outcome"]), dict(d.get("checklist") or {}), words))
        draft.update(await device_facts(hass, sub.main))
        draft["kind"] = kind
    elif kind == "test":
        if not DEV_BUILD:  # (a developer build's test report only)
            connection.send_error(msg["id"], "not_available", "only in a developer build")
            return
        draft = sample_report()
    elif kind == "unknown_state" and "appliance" in (msg.get("draft") or {}):
        # (the dashboard names the appliance, unit, state and answer; HA builds
        # the report from the device itself)
        d = msg["draft"]
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        if not entries:
            connection.send_error(msg["id"], "not_set_up", "Room Tiles is not set up")
            return
        built = await build_unknown_state(
            hass, entries[0].runtime_data.data, str(d.get("appliance")), str(d.get("unit")), str(d.get("state")), str(d.get("answer"))
        )
        if built is None:
            connection.send_error(msg["id"], "not_found", "no such appliance")
            return
        draft = built
        draft["kind"] = kind
    else:
        draft = dict(msg.get("draft") or {})
        draft["kind"] = kind
        # a bug on a touch panel: the dashboard names the panel (its device);
        # HA adds what it knows of it - board, firmware, memory, restarts
        panel_device = draft.pop("panel_device", None)
        if kind == "bug" and draft.get("where") == "panel" and panel_device:
            from .report import panel_facts

            store = _store(hass, connection, msg["id"])
            if store is None:
                return
            draft["panel"] = await panel_facts(hass, store, str(panel_device))
    draft["room_tiles"] = VERSION
    draft["home_assistant"] = HA_VERSION
    secrets = secrets_from_hass(hass)
    done = scrub(draft, secrets)
    connection.send_result(
        msg["id"],
        {
            "report": done.doc,
            "summary": summary(done.doc),
            "dropped": [{"path": path, "why": why} for path, why in done.dropped],
            "issue": issue(done.doc, kind),
            # the user's own words: what looks like a name, address or time
            "warnings": description_warnings(str(done.doc.get("description") or ""), secrets),
        },
    )


@websocket_api.websocket_command({vol.Required("type"): TYPE_SUBSCRIBE})
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "not_set_up", "Room Tiles is not set up")
        return
    store = entries[0].runtime_data
    msg_id = msg["id"]

    @callback
    def forward(sections: tuple[str, ...]) -> None:
        doc = store.payload()
        if {"appliances", "pools", "robots"} & set(sections):
            sections = (*sections, "beta")  # (what's beta follows them)
        connection.send_message(
            websocket_api.event_message(
                msg_id,
                {"type": "update", "schema": PAYLOAD_SCHEMA, "data": {s: doc[s] for s in sections}},
            )
        )

    remove_listener = store.async_add_listener(forward)

    @callback
    def reset() -> None:
        connection.send_message(websocket_api.event_message(msg_id, {"type": "reset"}))

    remove_reset = store.async_add_unload_listener(reset)

    @callback
    def unsubscribe() -> None:
        remove_listener()
        remove_reset()

    connection.subscriptions[msg_id] = unsubscribe
    connection.send_result(msg_id)
    connection.send_message(
        websocket_api.event_message(
            msg_id, {"type": "full", "schema": PAYLOAD_SCHEMA, "data": store.payload()}
        )
    )
