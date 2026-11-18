"""Find supported appliances among HA's entities - what setup offers to add.

Pure (tested in tests/test_appliance_detect.py): it works on plain
descriptions of registry entries, built by `describe()` in appliances_ha.py.
Matching uses what integrations keep stable - platform, translation key,
unique-id endings, device manufacturer / model - never entity ids or names.

Each suggestion is an Appliance as a dict (model.Appliance), ready to store,
plus `notes`: what won't work for it (setup shows them).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .appliance import confirmed
from .appliance_presets import PRESETS
from . import wording


@dataclass(frozen=True)
class Ent:
    entity_id: str
    platform: str
    unique_id: str
    translation_key: str | None
    device_id: str | None
    name: str | None = None  # the integration's own name for it (original_name)


@dataclass(frozen=True)
class Dev:
    id: str
    name: str
    manufacturer: str
    model: str


def _unit(uid: str, label: str, appliance: str, preset: str, status: str, **kw: Any) -> dict[str, Any]:
    return {
        "id": uid,
        "label": label,
        "appliance": appliance,
        "preset": preset,
        "status": status,
        "time": kw.get("time"),
        "door": kw.get("door"),
        "door_clears": True,
        "finished": kw.get("finished", "done"),
        "clear": kw.get("clear", []),
        "drawer": kw.get("drawer", False),
        "overrides": {},
    }


def _kind_name(kind: str) -> str:
    """A machine's name by its kind (Washer...), in HA's language."""
    return wording.t(f"names.{kind}") if wording.has(f"names.{kind}") else kind.capitalize()


def _single(kind: str, preset: str, status: str, dev: Dev | None, **kw: Any) -> dict[str, Any]:
    """One machine as its own suggestion. Washers and dryers are marked
    `_laundry` so find_appliances can pair one of each into a Laundry tile."""
    unit = _unit(kind, _kind_name(kind), kind, preset, status, **kw)
    unit["_model"] = dev.model if dev else ""
    return {
        "id": kind,
        "name": _kind_name(kind),
        "units": [unit],
        "_devname": (dev.name if dev and dev.name else _kind_name(kind)),
        **({"_laundry": kind} if kind in ("washer", "dryer") else {}),
    }


def _same_device(ents: list[Ent], device_id: str | None, test) -> str | None:
    return next((x.entity_id for x in ents if x.device_id == device_id and test(x)), None)


def _lg_thinq(ents: list[Ent], devs: dict[str, Dev]) -> list[dict[str, Any]]:
    """LG ThinQ (HA core): `current_state` + `remain` per device; the device
    model says DEVICE_WASHER / DEVICE_DRYER."""
    out = []
    for e in ents:
        if e.platform != "lg_thinq" or e.translation_key != "current_state" or not e.device_id:
            continue
        dev = devs.get(e.device_id)
        model = (dev.model if dev else "").upper()
        kind = "washer" if "DEVICE_WASHER" in model else "dryer" if "DEVICE_DRYER" in model else None
        if kind is None:
            continue
        remain = _same_device(ents, e.device_id, lambda x: x.translation_key == "remain")
        out.append(_single(kind, f"lg_thinq_{kind}", e.entity_id, dev, time=remain))
    return out


def _smartthings(ents: list[Ent], devs: dict[str, Dev]) -> list[dict[str, Any]]:
    """Samsung - HA core `smartthings`: `washer_job_state` / `dryer_job_state`
    / `dishwasher_job_state` (the main unit; a twin washer's "sub" unit has
    its own keys) and `completion_time` on the same device."""
    out = []
    for e in ents:
        if e.platform != "smartthings" or not e.device_id:
            continue
        kind = {"washer_job_state": "washer", "dryer_job_state": "dryer", "dishwasher_job_state": "dishwasher"}.get(
            e.translation_key or ""
        )
        if kind is None:
            continue
        done = _same_device(ents, e.device_id, lambda x: x.translation_key == "completion_time")
        out.append(_single(kind, f"smartthings_{kind}", e.entity_id, devs.get(e.device_id), time=done))
    return out


def _whirlpool(ents: list[Ent], devs: dict[str, Dev]) -> list[dict[str, Any]]:
    """Whirlpool / Maytag / KitchenAid - HA core `whirlpool`: `washer_state` /
    `dryer_state` and `end_time` on the same device."""
    out = []
    for e in ents:
        if e.platform != "whirlpool" or e.translation_key not in ("washer_state", "dryer_state") or not e.device_id:
            continue
        kind = e.translation_key.split("_")[0]
        end = _same_device(ents, e.device_id, lambda x: x.translation_key == "end_time")
        out.append(_single(kind, f"whirlpool_{kind}", e.entity_id, devs.get(e.device_id), time=end))
    return out


def _home_connect_kind(ents: list[Ent], device_id: str | None, dev: Dev | None) -> str | None:
    """Which machine a Home Connect appliance is: its option keys name it
    (`LaundryCare.Washer...`, `LaundryCare.Dryer...`, `Dishcare.Dishwasher...`),
    else its name."""
    uids = " ".join(x.unique_id for x in ents if x.device_id == device_id)
    if "LaundryCare.WasherDryer" in uids or "LaundryCare.Washer." in uids:
        return "washer"
    if "LaundryCare.Dryer." in uids:
        return "dryer"
    if "Dishcare.Dishwasher" in uids:
        return "dishwasher"
    name = (dev.name if dev else "").lower()
    for word, kind in (("dish", "dishwasher"), ("dry", "dryer"), ("wash", "washer")):
        if word in name:
            return kind
    return None


def _home_connect(ents: list[Ent], devs: dict[str, Dev]) -> list[dict[str, Any]]:
    """Bosch / Siemens / Neff / Gaggenau - HA core `home_connect`: operation
    state `<haId>-BSH.Common.Status.OperationState`, door
    `...-BSH.Common.Status.DoorState`, finish time
    `...-BSH.Common.Option.RemainingProgramTime`."""
    out = []
    for e in ents:
        if e.platform != "home_connect" or not e.unique_id.endswith("-BSH.Common.Status.OperationState"):
            continue
        dev = devs.get(e.device_id or "")
        kind = _home_connect_kind(ents, e.device_id, dev)
        if kind is None:
            continue
        base = e.unique_id[: -len("BSH.Common.Status.OperationState")]
        door = next((x.entity_id for x in ents if x.unique_id == f"{base}BSH.Common.Status.DoorState"), None)
        finish = next((x.entity_id for x in ents if x.unique_id == f"{base}BSH.Common.Option.RemainingProgramTime"), None)
        out.append(_single(kind, f"home_connect_{kind}", e.entity_id, dev, time=finish, door=door))
    return out


def _miele(ents: list[Ent], devs: dict[str, Dev]) -> list[dict[str, Any]]:
    """Miele - HA core `miele`: status `<serial>-state_status`, finish time
    `...-state_finish_timestamp`, door `...-state_signal_door`; the device
    model says Washing machine / Tumble dryer / Dishwasher / Washer dryer."""
    out = []
    for e in ents:
        if e.platform != "miele" or not e.unique_id.endswith("-state_status"):
            continue
        dev = devs.get(e.device_id or "")
        model = (dev.model if dev else "").lower()
        kind = (
            "dishwasher"
            if "dishwasher" in model
            else "dryer"
            if "dryer" in model and "washer" not in model
            else "washer"
            if "wash" in model
            else None
        )
        if kind is None:
            continue
        base = e.unique_id[: -len("state_status")]
        finish = next((x.entity_id for x in ents if x.unique_id == f"{base}state_finish_timestamp"), None)
        door = next((x.entity_id for x in ents if x.unique_id == f"{base}state_signal_door"), None)
        out.append(_single(kind, f"miele_{kind}", e.entity_id, dev, time=finish, door=door))
    return out


def _ge_laundry(ents: list[Ent], devs: dict[str, Dev]) -> list[dict[str, Any]]:
    """GE Appliances / GE Profile laundry - `ge_home`: `..._laundry_machine_state`,
    `..._laundry_time_remaining`, `..._laundry_door`; a washer has
    `_laundry_washer_...` entities, a dryer `_laundry_dryer_...`."""
    out = []
    for e in ents:
        if e.platform != "ge_home" or not e.unique_id.endswith("_laundry_machine_state"):
            continue
        base = e.unique_id[: -len("laundry_machine_state")]
        uids = [x.unique_id for x in ents if x.device_id == e.device_id]
        kind = "washer" if any("_laundry_washer_" in u for u in uids) else "dryer" if any("_laundry_dryer_" in u for u in uids) else None
        if kind is None:
            continue
        time = next((x.entity_id for x in ents if x.unique_id == f"{base}laundry_time_remaining"), None)
        door = next((x.entity_id for x in ents if x.unique_id == f"{base}laundry_door"), None)
        out.append(_single(kind, f"ge_home_{kind}", e.entity_id, devs.get(e.device_id or ""), time=time, door=door))
    return out


def _matter_kind(ents: list[Ent], device_id: str | None, dev: Dev | None) -> str | None:
    """A Matter appliance's type: dishwashers have a dishwasher mode / alarms,
    washers spin-speed / rinse settings; dryers have nothing of their own in
    HA (they share the laundry mode), so their NAME is checked first."""
    name = f"{dev.name if dev else ''} {dev.model if dev else ''}".lower()
    if "dryer" in name and "washer" not in name:
        return "dryer"
    if "dish" in name:
        return "dishwasher"
    mine = [x for x in ents if x.device_id == device_id]
    uids = " ".join(x.unique_id for x in mine)
    keys = {x.translation_key for x in mine}
    if "-MatterDishwasherMode-" in uids or "dishwasher_alarm_inflow" in keys:
        return "dishwasher"
    if keys & {"laundry_washer_spin_speed", "laundry_washer_number_of_rinses"} or "wash" in name:
        return "washer"
    if "-MatterLaundryWasherMode-" in uids:
        return "dryer"  # the laundry mode without a washer's settings
    return None


def _matter(ents: list[Ent], devs: dict[str, Dev]) -> list[dict[str, Any]]:
    """Matter appliances (any brand) - HA core `matter`: the Operational State
    sensor `<device>-<endpoint>-OperationalState-...` (robot vacuums use
    RvcOperationalState - never matched) and `...-OperationalStateCountdownTime-...`
    (estimated end time) on the same device."""
    out = []
    for e in ents:
        if e.platform != "matter" or "-OperationalState-" not in e.unique_id or not e.entity_id.startswith("sensor."):
            continue
        if any(x.device_id == e.device_id and x.entity_id.startswith("vacuum.") for x in ents):
            continue
        dev = devs.get(e.device_id or "")
        kind = _matter_kind(ents, e.device_id, dev)
        if kind is None:
            continue
        end = _same_device(ents, e.device_id, lambda x: "-OperationalStateCountdownTime-" in x.unique_id)
        out.append(_single(kind, f"matter_{kind}", e.entity_id, dev, time=end))
    return out


_FP = re.compile(r"fisher\s*&?\s*paykel", re.I)


def _ge_home(ents: list[Ent], devs: dict[str, Dev]) -> list[dict[str, Any]]:
    """GE Home / SmartHQ (ha_gehome): dishwasher `..._dishwasher_cycle_state`
    (a drawer model's lower drawer too) and `..._dishwasher_upper_cycle_state`
    (upper drawer), with matching time_remaining / door_status. Fisher & Paykel
    DishDrawers use their own preset."""
    out = []
    by_dev: dict[str, dict[str, str]] = {}
    for e in ents:
        if e.platform != "ge_home" or not e.device_id:
            continue
        for part in ("upper_", ""):
            for key in ("cycle_state", "time_remaining", "door_status"):
                if e.unique_id.endswith(f"_dishwasher_{part}{key}"):
                    by_dev.setdefault(e.device_id, {})[f"{part}{key}"] = e.entity_id
    for dev_id, f in by_dev.items():
        dev = devs.get(dev_id)
        fp = bool(dev and _FP.search(dev.manufacturer or ""))
        preset = "fp_dishdrawer" if fp else "ge_home_dishwasher"
        units = []
        dual = "upper_cycle_state" in f
        for part, label in (("upper_", wording.t("names.upper")), ("", wording.t("names.lower") if dual else _kind_name("dishwasher"))):
            if f"{part}cycle_state" not in f:
                continue
            units.append(
                _unit(
                    (part.rstrip("_") or ("lower" if dual else "dishwasher")),
                    label,
                    "dishwasher",
                    preset,
                    f[f"{part}cycle_state"],
                    time=f.get(f"{part}time_remaining"),
                    door=f.get(f"{part}door_status"),
                    drawer=fp,
                )
            )
            units[-1]["_model"] = dev.model if dev else ""
        if units:
            out.append(
                {"id": "dishwasher", "name": _kind_name("dishwasher"), "units": units, "_devname": dev.name if dev and dev.name else _kind_name("dishwasher")}
            )
    return out


FINDERS = (_lg_thinq, _ge_home, _ge_laundry, _smartthings, _whirlpool, _home_connect, _miele, _matter)


def _pair_laundry(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Exactly one washer and one dryer (any brands): one Laundry tile, the
    dryer on top, the washer showing "Switch Over" until the dryer starts.
    Otherwise every machine keeps its own tile (paired by hand)."""
    washers = [f for f in found if f.get("_laundry") == "washer"]
    dryers = [f for f in found if f.get("_laundry") == "dryer"]
    if len(washers) != 1 or len(dryers) != 1:
        return found
    dryer, washer = dryers[0]["units"][0], washers[0]["units"][0]
    washer["finished"] = "waiting"
    washer["clear"] = ["unit:dryer"]
    laundry = {"id": "laundry", "name": wording.t("names.laundry"), "units": [dryer, washer], "_devname": wording.t("names.laundry")}
    return [f for f in found if f not in (washers[0], dryers[0])] + [laundry]


def find_appliances(
    ents: list[Ent],
    devs: dict[str, Dev],
    known: set[str],
    taken_ids: set[str] | frozenset[str] = frozenset(),
    dryers: list[str] | tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Suggestions for every supported appliance not set up yet (`known` =
    status entities already used by an appliance). Ids are made unique, also
    against `taken_ids` (appliances already set up). `dryers`: the set-up
    dryers on their own tile (a washer on its own waits for one)."""
    out: list[dict[str, Any]] = []
    found = _pair_laundry([sug for finder in FINDERS for sug in finder(ents, devs)])
    # several of a kind (same name): each named after its device
    names = [f["name"] for f in found]
    for f in found:
        devname = f.pop("_devname", None)
        f.pop("_laundry", None)
        if names.count(f["name"]) > 1 and devname:
            f["name"] = devname
    for sug in found:
        sug["units"] = [u for u in sug["units"] if u["status"] not in known]
        if not sug["units"]:
            continue
        ids = {u["id"] for u in sug["units"]}
        for u in sug["units"]:
            u["clear"] = [c for c in u["clear"] if not c.startswith("unit:") or c[5:] in ids]
            if not u["clear"] and u["finished"] == "waiting":
                u["finished"] = "done"
        sug["notes"] = []
        for u in sug["units"]:
            model = u.pop("_model", "")
            if not confirmed(PRESETS[u["preset"]], model):
                sug["notes"].append(
                    f"{u['label']}: beta - {model.split(' (')[0].strip() or 'this model'} isn't confirmed "
                    "with Room Tiles yet. It should work; please report how it goes."
                )
        out.append(sug)
    taken: set[str] = set(taken_ids)
    for sug in out:
        base, n = sug["id"], 1
        while sug["id"] in taken:
            n += 1
            sug["id"] = f"{base}_{n}"
        taken.add(sug["id"])
    washer_default(out, [*dryers, *(f["id"] for f in out if _only(f, "dryer"))])
    return out


def _only(sug: dict[str, Any], kind: str) -> bool:
    return len(sug["units"]) == 1 and sug["units"][0]["appliance"] == kind


def washer_default(found: list[dict[str, Any]], dryer_tiles: list[str]) -> None:
    """A washer on its own tile: with a dryer around, "Switch Over" until
    that dryer (its own tile) starts; with none, straight back to idle. (On a
    tile with a dryer: _pair_laundry.) Several dryers: Switch Over, emptied
    by a tap / its door."""
    for sug in found:
        if not _only(sug, "washer"):
            continue
        u = sug["units"][0]
        u["clear"] = [c for c in u["clear"] if not c.startswith(("unit:", "appliance:"))]
        if not dryer_tiles:
            u["finished"] = "idle"
            continue
        u["finished"] = "waiting"
        if len(dryer_tiles) == 1:
            u["clear"].append(f"appliance:{dryer_tiles[0]}")


def redetect(ents: list[Ent], devs: dict[str, Dev], appliances: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """For each appliance already set up: what setup would make of its
    hardware NOW (Set up again - e.g. after replacing a machine, or to start
    over). Matched by shared status entities; keeps the appliance's id and
    name. Appliances whose hardware isn't found get no entry."""
    fresh = find_appliances(ents, devs, set())
    out: dict[str, dict[str, Any]] = {}
    for ap in appliances:
        mine = {u["status"] for u in ap["units"]}
        best = max(fresh, key=lambda f: len(mine & {u["status"] for u in f["units"]}), default=None)
        if best is not None and mine & {u["status"] for u in best["units"]}:
            out[ap["id"]] = {**best, "id": ap["id"], "name": ap["name"]}
    return out
