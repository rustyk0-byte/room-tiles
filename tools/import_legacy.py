#!/usr/bin/env python3
"""Convert a pre-Room-Tiles panel setup into a Room Tiles data file.

For the original room-control panels (ESPHome ha_dynamic firmware), whose
data lived in HA template sensors, input_text helpers and a to-do list. The
output is loaded into Room Tiles with the `room_tiles.import_data` action.

Inputs (all read-only):
  --panel-config  JSON of sensor.panel_config's attributes (names, lights,
                  map_room, roomN / roomN_6x3 tile specs, catalog)
  --markers       the "Panel Map" local to-do .ics file (items
                  "view|entity|x|y|show_name")
  --plan          the firmware's generated floor plan header (house_plan_vec.h)
  --areas         HA's .storage/core.area_registry (to link areas by name)
  --out           where to write the Room Tiles JSON

Standard library only; validates the result with Room Tiles' own model.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "custom_components" / "room_tiles"


def _load_model():
    """const + model without the HA-dependent package __init__."""
    pkg = types.ModuleType("rt")
    pkg.__path__ = [str(PKG)]
    sys.modules["rt"] = pkg
    mods = {}
    for name in ("const", "fontwidths", "shortnames", "model"):
        spec = importlib.util.spec_from_file_location(f"rt.{name}", PKG / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"rt.{name}"] = mod
        spec.loader.exec_module(mod)
        mods[name] = mod
    return mods["const"], mods["model"], mods["shortnames"]


const, model, shortnames = _load_model()

EMPTY = {"", "unknown", "unavailable", "none"}


def norm(text: str) -> str:
    """Name comparison: case and apostrophe style (' vs \u2019) don't matter."""
    return text.replace("\u2019", "'").replace("\u2018", "'").strip().lower()


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower().replace("'", "")).strip("_")
    return s or "x"


# ---- floor plan header ----------------------------------------------------------


def _array(src: str, name: str) -> str:
    m = re.search(rf"{name}\[\]\s*=\s*\{{(.*?)\}};", src, re.S)
    if not m:
        raise SystemExit(f"plan: {name} not found")
    return m.group(1)


def _int_groups(body: str, size: int) -> list[tuple[float, ...]]:
    out = []
    for g in re.findall(r"\{([^{}]*)\}", body):
        nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", g)]
        if len(nums) != size:
            raise SystemExit(f"plan: expected {size} numbers in '{{{g}}}'")
        out.append(tuple(nums))
    return out


def read_plan(path: Path) -> dict:
    src = path.read_text(encoding="utf-8")
    rooms = []
    for g in re.findall(r"\{([^{}]*)\}", _array(src, "PLAN_ROOMS")):
        m = re.match(
            r'\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(\d+),\s*"([^"]*)",\s*"([^"]*)"'
            r"(?:,\s*(true|false)(?:,\s*(-?\d+),\s*(-?\d+))?)?",
            g,
        )
        if not m:
            raise SystemExit(f"plan: can't read room '{{{g}}}'")
        x0, y0, x1, y1, view = (int(m.group(i)) for i in range(1, 6))
        rooms.append(
            {
                "rect": (x0, y0, x1, y1),
                "view": view,
                "label": m.group(6),
                "name": m.group(7),
                "outdoor": m.group(8) == "true",
                "label_at": (int(m.group(9)), int(m.group(10))) if m.group(9) else None,
            }
        )
    bounds = {
        k: int(v) for k, v in re.findall(r"PLAN_(X0|Y0|X1|Y1)\s*=\s*(-?\d+)", src)
    }
    wall_w = re.search(r"PLAN_WALL_W\s*=\s*(\d+)", src)
    return {
        "walls": _int_groups(_array(src, "PLAN_WALLS"), 4),
        "windows": _int_groups(_array(src, "PLAN_WINDOWS"), 4),
        "openings": _int_groups(_array(src, "PLAN_OPEN"), 4),
        "floors": _int_groups(_array(src, "PLAN_FLOORS"), 4),
        "pool": _int_groups(_array(src, "PLAN_POOL"), 2),
        "rooms": rooms,
        "bounds": (bounds["X0"], bounds["Y0"], bounds["X1"], bounds["Y1"]),
        "wall_width": float(wall_w.group(1)) if wall_w else 6.0,
    }


# ---- markers ---------------------------------------------------------------------


def read_markers(path: Path) -> list[dict]:
    """VTODO items: UID + SUMMARY "view|entity|x|y[|show_name]". Completed
    items are skipped (the old sensor ignored them too)."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    text = re.sub(r"\n[ \t]", "", text)  # unfold continuation lines
    out = []
    for block in re.findall(r"BEGIN:VTODO\n(.*?)END:VTODO", text, re.S):
        fields = dict(
            line.split(":", 1) for line in block.split("\n") if ":" in line
        )
        fields = {k.split(";", 1)[0]: v for k, v in fields.items()}
        if fields.get("STATUS", "").upper() == "COMPLETED":
            continue
        parts = [p.strip() for p in fields.get("SUMMARY", "").split("|")]
        if len(parts) < 4:
            print(f"  skipped marker '{fields.get('SUMMARY')}' (not view|entity|x|y)")
            continue
        out.append(
            {
                "uid": fields.get("UID") or f"m{len(out)}",
                "view": int(parts[0]),
                "entity": parts[1],
                "x": float(parts[2]),
                "y": float(parts[3]),
                "show_name": len(parts) > 4 and parts[4] == "1",
            }
        )
    return out


# ---- tiles and catalog ------------------------------------------------------------


def parse_spec(item: str):
    """One "entity|K|name" tile spec -> Tile (blank for empty / unknown)."""
    item = item.strip()
    if item.lower() in EMPTY:
        return model.Tile()
    f = [p.strip() for p in item.split("|")]
    kind = const.LEGACY_KIND_LETTERS.get(f[1][:1] if len(f) > 1 and f[1] else "")
    if kind is None:
        print(f"  tile '{item}': unknown kind, left blank")
        return model.Tile()
    if kind == const.KIND_BLANK:
        return model.Tile()
    entity = None if kind in const.NO_ENTITY_KINDS else f[0]
    return model.Tile(kind=kind, entity=entity, name=f[2] if len(f) > 2 else "")


def parse_grid(spec: str | None) -> list:
    """Positional: segment N is slot N (an empty segment is a cleared slot);
    the specs end with ";", which is not an extra slot."""
    if not spec:
        return []
    items = spec.split(";")
    if spec.endswith(";"):
        items = items[:-1]
    return [parse_spec(i) for i in items]


def parse_catalog(spec: str) -> list:
    """Catalog entries with short names suggested from the panel's names
    (chosen by the user, so better starting points than HA's entity names);
    each keeps the panel name in `_panel_name` for the tile-name check."""
    out = []
    for raw in spec.split(";"):
        f = [p.strip() for p in raw.split("|")]
        if len(f) < 3 or not f[0]:
            continue
        kind = const.LEGACY_KIND_LETTERS.get(f[1][:1])
        if kind is None or kind in const.NO_ENTITY_KINDS:
            continue  # blank / map are built-in picker options, not catalog entries
        short, review = shortnames.suggest(f[2] or f[0])
        entry = model.CatalogEntry(
            entity=f[0],
            kind=kind,
            short_name=short,
            review=review,
            auto=False,
        )
        entry._panel_name = f[2]
        out.append(entry)
    return out


def settle_tile_names(areas: list, catalog: list, notes: list[str]) -> None:
    """A tile keeps its own name only where the panel showed something other
    than the catalog's name; that name must fit as is (a tile override has no
    review step), otherwise the catalog's short name is used."""
    panel_names = {e.entity: getattr(e, "_panel_name", "") for e in catalog}
    for a in areas:
        for layout, grid in a.tiles.items():
            for t in grid:
                if t.kind == const.KIND_BLANK:
                    continue
                raw = (t.name or "").strip()
                if t.kind == const.KIND_MAP or not raw or raw == panel_names.get(t.entity, raw):
                    t.name = None
                elif shortnames.fits(raw):
                    t.name = raw
                else:
                    notes.append(
                        f"area '{a.name}' {layout}: tile name '{raw}' too long - uses the entity's short name"
                    )
                    t.name = None


# ---- assemble ----------------------------------------------------------------------


def _place(area, layout: str, tile) -> bool:
    """Put `tile` in the first blank slot of `area`'s grid (skipped if that
    entity is already in the grid). False if the grid is full."""
    grid = area.tiles[layout]
    if tile.entity and any(t.entity == tile.entity for t in grid):
        return True
    for i, t in enumerate(grid):
        if t.kind == const.KIND_BLANK:
            grid[i] = tile
            return True
    return False


def convert(
    cfg: dict,
    markers: list[dict],
    plan: dict,
    ha_areas: list[dict],
    links: dict[str, str] | None = None,
    merges: dict[str, str] | None = None,
    drops: list[str] | None = None,
    splits: list[str] | None = None,
    tile_areas: dict[str, str] | None = None,
) -> tuple[dict, list[str]]:
    """Every Room Tiles area must be an HA area. Panel areas are matched by
    name (case / apostrophe style ignored) or:
      links      panel area name -> HA area id (names differ)
      merges     panel area name -> HA area id: its tiles fill that area's
                 free slots
      drops      panel area names to leave out
      splits     panel area names whose tiles are spread over HA areas by
                 `tile_areas` (entity -> HA area id)
    A panel name that differs from HA's becomes the area's short name."""
    notes: list[str] = []
    names = [n.strip() for n in cfg["names"].split(";")]
    lights = [x.strip() for x in cfg.get("lights", "").split(";")]
    map_room = [int(x) for x in cfg.get("map_room", "").split(";") if x.strip()]

    ha = {a["id"]: a for a in ha_areas}
    by_name = {norm(a["name"]): a["id"] for a in ha_areas}
    links = {norm(k): v for k, v in (links or {}).items()}
    merges = {norm(k): v for k, v in (merges or {}).items()}
    drops_n = {norm(d) for d in drops or []}
    splits_n = {norm(x) for x in splits or []}
    tile_areas = dict(tile_areas or {})
    for opt, ids in (("--link", links.values()), ("--merge", merges.values()), ("--tile-area", tile_areas.values())):
        for v in ids:
            if v not in ha:
                raise SystemExit(f"{opt}: HA area '{v}' doesn't exist")

    def new_area(ha_id: str, panel_name: str | None = None, light: str | None = None):
        """Short name from the panel's name for the area (else HA's)."""
        h = ha[ha_id]
        short, review = shortnames.suggest(panel_name or h["name"])
        return model.Area(
            id=ha_id, name=h["name"], floor=h.get("floor_id"),
            short_name=short, review=review, lights=light,
        )

    areas: list = []
    by_id: dict[str, object] = {}
    panel_to_area: dict[int, str] = {}  # panel area index -> Room Tiles area id
    pending_merges: list[tuple[int, str]] = []
    pending_splits: list[int] = []
    unresolved: list[str] = []
    for i, name in enumerate(names):
        n = norm(name)
        if n in drops_n:
            notes.append(f"area '{name}': dropped")
            continue
        if n in merges:
            pending_merges.append((i, merges[n]))
            continue
        if n in splits_n:
            pending_splits.append(i)
            areas.append(("split", i))  # placeholder keeps the panel order
            continue
        ha_id = links.get(n) or by_name.get(n)
        if ha_id is None:
            unresolved.append(name)
            continue
        if ha_id in by_id:
            raise SystemExit(f"area '{name}': HA area '{ha_id}' is already used by another panel area - use --merge")
        light = lights[i] if i < len(lights) and lights[i].lower() not in EMPTY else None
        a = new_area(ha_id, name, light)
        a.tiles = {
            const.LAYOUT_5X2: parse_grid(cfg.get(f"room{i}")),
            const.LAYOUT_6X3: parse_grid(cfg.get(f"room{i}_6x3")),
        }
        a.__post_init__()
        areas.append(a)
        by_id[ha_id] = a
        panel_to_area[i] = ha_id
    if unresolved:
        raise SystemExit(
            "these panel areas match no HA area - use --link, --merge, --drop or --split: "
            + ", ".join(unresolved)
        )

    # splits: each tile goes to the HA area named by --tile-area, in order;
    # new areas take the split area's place in the area order
    ordered: list = []
    for item in areas:
        if not (isinstance(item, tuple) and item[0] == "split"):
            ordered.append(item)
            continue
        i = item[1]
        for layout, key in ((const.LAYOUT_5X2, f"room{i}"), (const.LAYOUT_6X3, f"room{i}_6x3")):
            for t in parse_grid(cfg.get(key)):
                if t.kind == const.KIND_BLANK:
                    continue
                target = tile_areas.get(t.entity or "")
                if target is None:
                    notes.append(f"area '{names[i]}': tile {t.entity or t.kind} has no --tile-area - dropped")
                    continue
                if target not in by_id:
                    a = new_area(target)
                    by_id[target] = a
                    ordered.append(a)
                    notes.append(f"area '{names[i]}': new area '{a.name}' for its tiles")
                if not _place(by_id[target], layout, t):
                    notes.append(f"area '{by_id[target].name}' {layout}: full, {t.entity} dropped")
    areas = ordered

    for i, target in pending_merges:
        if target not in by_id:
            a = new_area(target)
            by_id[target] = a
            areas.append(a)
        moved = 0
        for layout, key in ((const.LAYOUT_5X2, f"room{i}"), (const.LAYOUT_6X3, f"room{i}_6x3")):
            for t in parse_grid(cfg.get(key)):
                if t.kind == const.KIND_BLANK:
                    continue
                if _place(by_id[target], layout, t):
                    moved += 1
                else:
                    notes.append(f"area '{by_id[target].name}' {layout}: full, {t.entity} dropped")
        notes.append(f"area '{names[i]}': merged into '{by_id[target].name}' ({moved} tiles moved)")

    # zones from the plan's rooms; map_room[i] = index into PLAN_ROOMS for area i
    zone_area: dict[int, str] = {}
    for i, idx in enumerate(map_room):
        if idx >= 0 and i in panel_to_area:
            zone_area[idx] = panel_to_area[i]
    # zones still unlinked: an area with the zone's name
    linked = set(zone_area.values())
    for idx, r in enumerate(plan["rooms"]):
        if idx not in zone_area:
            a_id = by_name.get(norm(r["name"]))
            if a_id in by_id and a_id not in linked:
                zone_area[idx] = a_id
                linked.add(a_id)
    zones = []
    zone_ids: set[str] = set()
    view_zone: dict[int, str] = {}
    for idx, r in enumerate(plan["rooms"]):
        x0, y0, x1, y1 = r["rect"]
        zid = slug(r["name"])
        while zid in zone_ids:
            zid += "_"
        zone_ids.add(zid)
        view_zone[r["view"]] = zid
        label = r["label_at"] or ((x0 + x1) / 2, (y0 + y1) / 2)
        zones.append(
            model.Zone(
                id=zid,
                name=r["name"],
                points=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                area=zone_area.get(idx),
                label=label,
                outdoor=r["outdoor"],
            )
        )
        if idx not in zone_area:
            notes.append(f"zone '{r['name']}' has no panel area linked (link it in the map editor)")

    floors = sorted({tuple(f) for f in plan["floors"]})
    shapes = [
        model.Shape(style="floor", points=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
        for (x0, y0, x1, y1) in floors
    ]
    if plan["pool"]:
        shapes.append(model.Shape(style="water", points=[tuple(p) for p in plan["pool"]]))

    # markers: view 0 = the whole-house overview -> layer "house"; room views -> "rooms"
    bx0, by0, bx1, by1 = plan["bounds"]
    margin = 60
    out_markers = []
    mids: set[str] = set()
    for m in markers:
        mid = m["uid"]
        while mid in mids:
            mid += "_"
        mids.add(mid)
        if m["view"] != 0 and m["view"] not in view_zone:
            notes.append(f"marker {m['entity']}: view {m['view']} has no room in the plan - kept on the rooms layer")
        bx0, by0 = min(bx0, m["x"] - margin), min(by0, m["y"] - margin)
        bx1, by1 = max(bx1, m["x"] + margin), max(by1, m["y"] + margin)
        out_markers.append(
            model.Marker(
                id=mid,
                map="house",
                entity=m["entity"],
                x=m["x"],
                y=m["y"],
                layer="rooms" if m["view"] != 0 else "house",
                show_name=m["show_name"],
            )
        )
    if (bx0, by0, bx1, by1) != tuple(plan["bounds"]):
        notes.append(
            f"map bounds widened from {tuple(plan['bounds'])} to {(bx0, by0, bx1, by1)} "
            "to fit markers placed outside the plan"
        )

    house = model.Map(
        id="house",
        name="House",
        bounds=(bx0, by0, bx1, by1),
        wall_width=plan["wall_width"],
        walls=[tuple(s) for s in plan["walls"]],
        windows=[tuple(s) for s in plan["windows"]],
        openings=[tuple(s) for s in plan["openings"]],
        shapes=shapes,
        zones=zones,
        # the panels' two kinds of view: the whole house, and a room
        layers=[model.Layer(model.LAYER_HOUSE, "House", 1.0), model.Layer(model.LAYER_ROOMS, "Rooms", 1.7)],
    )

    catalog = model.Catalog(entries=parse_catalog(cfg.get("catalog", "")))
    settle_tile_names(areas, catalog.entries, notes)
    data = model.RoomTilesData(areas=areas, maps=[house], markers=out_markers, catalog=catalog)
    data.validate()

    known = {e.entity for e in catalog.entries}
    for a in areas:
        for layout, grid in a.tiles.items():
            for t in grid:
                if t.entity and t.entity not in known:
                    notes.append(f"area '{a.name}' {layout}: tile {t.entity} is not in the catalog")
    return data.as_dict(), notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--panel-config", type=Path, required=True)
    ap.add_argument("--markers", type=Path, required=True)
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--areas", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument(
        "--link",
        action="append",
        default=[],
        metavar="'PANEL AREA=ha_area_id'",
        help="link a panel area to an HA area whose name differs (repeatable)",
    )
    ap.add_argument("--merge", action="append", default=[], metavar="'PANEL AREA=ha_area_id'",
                    help="move a panel area's tiles into another area (repeatable)")
    ap.add_argument("--drop", action="append", default=[], metavar="'PANEL AREA'",
                    help="leave a panel area out (repeatable)")
    ap.add_argument("--split", action="append", default=[], metavar="'PANEL AREA'",
                    help="spread a panel area's tiles over HA areas, see --tile-area (repeatable)")
    ap.add_argument("--tile-area", action="append", default=[], metavar="'entity_id=ha_area_id'",
                    help="where a split area's tile goes (repeatable)")
    args = ap.parse_args()

    def pairs(items, opt):
        out = {}
        for item in items:
            k, _, v = item.partition("=")
            if not v:
                ap.error(f"{opt} '{item}': expected 'name=ha_area_id'")
            out[k.strip()] = v.strip()
        return out

    links = pairs(args.link, "--link")
    merges = pairs(args.merge, "--merge")
    tile_areas = pairs(args.tile_area, "--tile-area")

    cfg = json.loads(args.panel_config.read_text(encoding="utf-8"))
    ha_areas = json.loads(args.areas.read_text(encoding="utf-8"))["data"]["areas"]
    doc, notes = convert(
        cfg, read_markers(args.markers), read_plan(args.plan), ha_areas,
        links, merges, args.drop, args.split, tile_areas,
    )
    args.out.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")

    tiles = sum(1 for a in doc["areas"] for g in a["tiles"].values() for t in g if t)
    review = [a["short_name"] for a in doc["areas"] if a["review"]] + [
        e["short_name"] for e in doc["catalog"]["entries"] if e["review"]
    ]
    print(
        f"wrote {args.out}: {len(doc['areas'])} areas ({tiles} tiles), "
        f"{len(doc['catalog']['entries'])} catalog entries, {len(doc['maps'])} map "
        f"({len(doc['maps'][0]['zones'])} zones), {len(doc['markers'])} markers"
    )
    for n in notes:
        print("  note:", n)
    if review:
        print(f"  {len(review)} short names were shortened and will be listed for review in HA (Repairs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
