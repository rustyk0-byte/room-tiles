// Saving an editor's draft over what others saved meanwhile (another
// dashboard, a panel): only this editor's own changes go in - the rest stays
// as it is now, not as it was when editing began.

import type { MapLayer, MapMarker } from "./map";

const same = (a: MapMarker, b: MapMarker): boolean =>
  a.entity === b.entity && a.x === b.x && a.y === b.y && a.layer === b.layer && !!a.show_name === !!b.show_name;

/** A map's markers to save: `base` = when editing began, `draft` = the
 *  editor's now, `current` = what HA has now. A marker changed here: this
 *  editor's; untouched here: HA's now (gone there: gone); removed here:
 *  gone; added here (no id in base): added; added elsewhere: kept. */
export function mergeMarkers(base: MapMarker[], draft: MapMarker[], current: MapMarker[]): MapMarker[] {
  const before = new Map(base.map((m) => [m.id, m]));
  const now = new Map(current.map((m) => [m.id, m]));
  const mine = new Set(draft.map((m) => m.id));
  const out: MapMarker[] = [];
  for (const m of draft) {
    const was = before.get(m.id);
    if (!was) out.push(m); // added here
    else if (!same(was, m)) out.push(m); // changed here: this editor's
    else if (now.has(m.id)) out.push(now.get(m.id)!); // untouched here: as HA has it now
  }
  for (const m of current) if (!before.has(m.id) && !mine.has(m.id)) out.push(m); // added elsewhere
  return out;
}

/** The layers to save: HA's now (names, order, layers added or removed
 *  elsewhere), with only the zoom ranges this editor changed. Undefined:
 *  nothing changed here. */
export function mergeLayerRanges(base: MapLayer[], draft: MapLayer[], current: MapLayer[]): MapLayer[] | undefined {
  const range = (l: MapLayer | undefined) => (l ? `${l.min_zoom}|${l.max_zoom ?? ""}` : "");
  const before = new Map(base.map((l) => [l.id, l]));
  const changed = new Map(draft.filter((l) => range(l) !== range(before.get(l.id))).map((l) => [l.id, l]));
  if (!changed.size) return undefined;
  return current.map((l) => {
    const c = changed.get(l.id);
    return c ? { ...l, min_zoom: c.min_zoom, max_zoom: c.max_zoom ?? null } : l;
  });
}
