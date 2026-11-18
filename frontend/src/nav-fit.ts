// The map screen's "where you are" row: Map pills and Layer pills. Each group
// shows all its pills while they fit, else collapses to one framed button
// ("Map: Ground ▾") that opens the list. Wide screens (the 1024x600 panels,
// tablets, desktop) put the groups in the top bar instead of a row of their
// own. Pure: widths in, what's collapsed out (tested in nav-fit.test.ts).

export interface GroupWidths {
  full: number; // every pill
  menu: number; // collapsed to one button
}

export interface NavFit {
  maps: boolean; // true = collapsed
  layers: boolean;
}

/** Top-bar placement from this width up (narrower: a row of its own). */
export const NAV_IN_TOOLBAR_FROM = 720;

// MIRRORED: firmware/components/room_tiles/map_view.cpp (map nav) - a change here must be made there too.
/** What collapses so the groups fit `avail` px (a missing group: not shown).
 *  Keeps as many pills as it can; when only one group can stay open, the
 *  maps stay (they change more of the screen). */
export function navFit(avail: number, gap: number, maps?: GroupWidths, layers?: GroupWidths): NavFit {
  const w = (g: GroupWidths | undefined, collapsed: boolean) => (g ? (collapsed ? g.menu : g.full) : 0);
  const gapOf = maps && layers ? gap : 0;
  const options: NavFit[] = [
    { maps: false, layers: false },
    { maps: false, layers: true },
    { maps: true, layers: false },
  ];
  for (const o of options) {
    if ((o.maps && !maps) || (o.layers && !layers)) continue; // collapsing a missing group changes nothing
    if (w(maps, o.maps) + w(layers, o.layers) + gapOf <= avail) return o;
  }
  return { maps: !!maps, layers: !!layers };
}
