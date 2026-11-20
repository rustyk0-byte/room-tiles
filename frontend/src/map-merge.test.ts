import { describe, expect, it } from "vitest";

import type { MapLayer, MapMarker } from "./map";
import { mergeLayerRanges, mergeMarkers } from "./map-merge";

const mk = (id: string, x = 0, entity = `light.${id}`): MapMarker => ({ id, map: "house", entity, x, y: 0, layer: "house", show_name: false });

describe("mergeMarkers", () => {
  it("keeps what others did meanwhile, adds this editor's own changes", () => {
    const base = [mk("a"), mk("b"), mk("c")];
    const draft = [mk("a", 5), mk("b"), mk("new-1", 9, "light.n")]; // moved a, removed c, added one
    const current = [mk("a"), mk("b", 7), mk("c"), mk("d")]; // elsewhere: moved b, added d
    expect(mergeMarkers(base, draft, current)).toEqual([mk("a", 5), mk("b", 7), mk("new-1", 9, "light.n"), mk("d")]);
  });

  it("a marker removed elsewhere and untouched here stays gone", () => {
    expect(mergeMarkers([mk("a"), mk("b")], [mk("a"), mk("b")], [mk("a")])).toEqual([mk("a")]);
  });

  it("this editor's change wins over another's on the same marker", () => {
    expect(mergeMarkers([mk("a")], [mk("a", 3)], [mk("a", 8)])).toEqual([mk("a", 3)]);
  });
});

describe("mergeLayerRanges", () => {
  const L = (id: string, name: string, min_zoom = 1, max_zoom: number | null = null): MapLayer => ({ id, name, min_zoom, max_zoom });

  it("nothing changed here: nothing to save", () => {
    expect(mergeLayerRanges([L("house", "House")], [L("house", "House")], [L("house", "Home")])).toBeUndefined();
  });

  it("a rename or a new layer elsewhere stays; only this editor's range goes in", () => {
    const base = [L("house", "House"), L("up", "Upstairs", 2)];
    const draft = [L("house", "House"), L("up", "Upstairs", 3)];
    const current = [L("house", "House"), L("up", "First floor", 2), L("attic", "Attic", 4)];
    expect(mergeLayerRanges(base, draft, current)).toEqual([L("house", "House"), L("up", "First floor", 3), L("attic", "Attic", 4)]);
  });
});
