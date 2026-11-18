"""Find pool / spa systems among HA's entities - what setup offers to add.

Pure (tested in tests/test_pool_detect.py). Matching uses unique-id endings,
never entity ids or names. The LAYOUT is a guess setup always shows for the
user to confirm (the cards in the pool dialog).
"""

from __future__ import annotations

from typing import Any

from . import wording
from .appliance_detect import Dev, Ent


def _iaqualink(ents: list[Ent], devs: dict[str, Dev]) -> list[dict[str, Any]]:
    """Jandy iAquaLink (HA core `iaqualink`): `<serial>_pool_temp`,
    `_spa_temp`, `_pool_set_point` / `_spa_set_point` (climate), `_pool_pump`,
    `_spa_pump`, `_pool_heater` / `_spa_heater` (heater switches - the
    thermostat's own on / off). With both bodies and both pump switches it's the usual
    combo system - the spa on the pool, `spa_pump` = spa mode (shared)."""
    systems: dict[str, dict[str, str]] = {}
    for e in ents:
        if e.platform != "iaqualink":
            continue
        for key in ("pool_temp", "spa_temp", "pool_set_point", "spa_set_point", "pool_pump", "spa_pump", "pool_heater", "spa_heater"):
            if e.unique_id.endswith(f"_{key}"):
                serial = e.unique_id[: -len(key) - 1]
                systems.setdefault(serial, {})[key] = e.entity_id
    out = []
    for f in systems.values():
        has = {b for b in ("pool", "spa") if f"{b}_temp" in f}
        if not has:
            continue
        body = lambda b: {  # noqa: E731
            "temp": f[f"{b}_temp"],
            "heater": f.get(f"{b}_set_point"),
            "pump": None,
            "pump_with_heater": True,
            # its heater on / off switch: the thermostat does the same
            **({"heater_switch": f[f"{b}_heater"]} if f"{b}_heater" in f else {}),
        }
        if has == {"pool", "spa"} and "spa_pump" in f and "pool_pump" in f:
            layout = "shared"
            sys_ = {"spa_mode": f["spa_pump"], "pump": f["pool_pump"], "pool": body("pool"), "spa": body("spa")}
        elif has == {"pool", "spa"}:
            layout = "separate"
            sys_ = {"spa_mode": None, "pump": None, "pool": body("pool"), "spa": body("spa")}
            sys_["pool"]["pump"] = f.get("pool_pump")
            sys_["spa"]["pump"] = f.get("spa_pump")
        else:
            (only,) = has
            layout = only
            sys_ = {"spa_mode": None, "pump": None, "pool": None, "spa": None, only: body(only)}
            sys_[only]["pump"] = f.get(f"{only}_pump")
        name = "Pool & Spa" if len(has) == 2 else ("Pool" if "pool" in has else "Spa")
        out.append({"id": "pool", "name": name, "preset": "iaqualink", "layout": layout, "spa_heater_follows": True, **sys_})
    return out


def _body(temp: str | None, heater: str | None, pump: str | None = None) -> dict[str, Any]:
    return {"temp": temp, "heater": heater, "pump": pump, "pump_with_heater": True}


def _screenlogic(ents: list[Ent], devs: dict[str, Dev]) -> list[dict[str, Any]]:
    """Pentair ScreenLogic (HA core `screenlogic` - EasyTouch / IntelliTouch /
    SunTouch): a thermostat per body (`climate`, translation key `body_0` =
    pool, `body_1` = spa) that also carries the water temperature, and the
    "Pool" / "Spa" circuits as switches. With both bodies it's taken to be the
    usual combo - the spa on the pool, the Spa circuit = spa mode, the Pool
    circuit = the pump (shared); setup asks to confirm."""
    systems: dict[str, dict[str, str]] = {}
    for e in ents:
        if e.platform != "screenlogic":
            continue
        mac = e.unique_id.rsplit("_", 1)[0]
        domain = e.entity_id.split(".", 1)[0]
        if domain == "climate" and e.translation_key in ("body_0", "body_1"):
            systems.setdefault(mac, {})["pool" if e.translation_key == "body_0" else "spa"] = e.entity_id
        elif domain == "switch" and (e.name or "").strip().lower() in ("pool", "spa"):
            systems.setdefault(mac, {})[f"{(e.name or '').strip().lower()}_circuit"] = e.entity_id
    out = []
    for f in systems.values():
        has = [b for b in ("pool", "spa") if b in f]
        if not has:
            continue
        if len(has) == 2:
            shared = "spa_circuit" in f and "pool_circuit" in f
            sys_ = {
                "layout": "shared" if shared else "separate",
                "spa_mode": f.get("spa_circuit") if shared else None,
                "pump": f.get("pool_circuit") if shared else None,
                "pool": _body(None, f["pool"], None if shared else f.get("pool_circuit")),
                "spa": _body(None, f["spa"], None if shared else f.get("spa_circuit")),
            }
            name = "Pool & Spa"
        else:
            (only,) = has
            sys_ = {"layout": only, "spa_mode": None, "pump": None, "pool": None, "spa": None}
            sys_[only] = _body(None, f[only], f.get(f"{only}_circuit"))
            name = only.capitalize()
        out.append(
            {
                "id": "pool",
                "name": name,
                "preset": "screenlogic",
                "spa_heater_follows": True,
                **sys_,
            }
        )
    return out


def _omnilogic(ents: list[Ent], devs: dict[str, Dev]) -> list[dict[str, Any]]:
    """Hayward OmniLogic (HA core `omnilogic`): per body of water a water
    temperature sensor (`<system>_<body>_water_temperature`) and its filter
    pump switch (`<system>_<body>_<filter>_pump`). The integration has NO
    heater control, so bodies come without a heater. Pool or spa from the
    body's name; each body has its own filter pump (separate)."""
    bodies: dict[str, dict[str, Any]] = {}
    for e in ents:
        if e.platform != "omnilogic":
            continue
        uid = e.unique_id
        if uid.endswith("_water_temperature"):
            key = uid[: -len("_water_temperature")]
            bodies.setdefault(key, {})["temp"] = e.entity_id
            bodies[key]["name"] = e.name or ""
    for e in ents:
        if e.platform != "omnilogic" or not e.unique_id.endswith("_pump") or not e.entity_id.startswith("switch."):
            continue
        for key, b in bodies.items():
            if e.unique_id.startswith(f"{key}_"):
                # prefer the filter pump when a body has several pumps
                if "pump" not in b or "filter" in (e.name or "").lower():
                    b["pump"] = e.entity_id
    systems: dict[str, dict[str, Any]] = {}
    for key, b in bodies.items():
        kind = "spa" if "spa" in (b.get("name") or "").lower() else "pool"
        systems.setdefault(key.split("_", 1)[0], {})[kind] = b
    out = []
    for found in systems.values():
        has = [k for k in ("pool", "spa") if k in found]
        sys_: dict[str, Any] = {"spa_mode": None, "pump": None, "pool": None, "spa": None}
        for k in has:
            sys_[k] = _body(found[k]["temp"], None, found[k].get("pump"))
        out.append(
            {
                "id": "pool",
                "name": wording.t("names.pool_and_spa") if len(has) == 2 else wording.t(f"pool.body.{has[0]}"),
                "preset": "omnilogic",
                "layout": "separate" if len(has) == 2 else has[0],
                "spa_heater_follows": True,
                **sys_,
                "_notes": [
                    "Heating isn't available for Hayward: the tiles show the temperature and run the pumps.",
                ],
            }
        )
    return out


FINDERS = (_iaqualink, _screenlogic, _omnilogic)


def find_pools(ents: list[Ent], devs: dict[str, Dev], known: set[str], taken_ids: set[str]) -> list[dict[str, Any]]:
    """Systems not set up yet (`known` = water temperature sensors - or, for
    bodies read through their heater, heaters - already used). Each gets `notes` (what setup should say) and a unique id."""
    out = []
    for finder in FINDERS:
        for sug in finder(ents, devs):
            temps = {sug[b]["temp"] or sug[b]["heater"] for b in ("pool", "spa") if sug.get(b)}
            if temps & known:
                continue
            sug["notes"] = list(sug.pop("_notes", None) or [])
            # no heater found for a body (common) - unless the brand's own
            # note already says heating isn't available
            if not any("Heating isn't available" in n for n in sug["notes"]):
                for b in ("pool", "spa"):
                    if sug.get(b) and not sug[b].get("heater"):
                        sug["notes"].append(
                            f"No heater found for the {b}. Pick one below if it has one."
                        )
            out.append(sug)
    taken = set(taken_ids)
    for sug in out:
        base, n = sug["id"], 1
        while sug["id"] in taken:
            n += 1
            sug["id"] = f"{base}_{n}"
        taken.add(sug["id"])
    return out
