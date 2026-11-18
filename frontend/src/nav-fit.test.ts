import { describe, expect, it } from "vitest";
import { navFit } from "./nav-fit";

const maps = { full: 300, menu: 150 };
const layers = { full: 200, menu: 130 };

describe("map / layer row: what fits", () => {
  it("everything fits: all pills", () => {
    expect(navFit(600, 12, maps, layers)).toEqual({ maps: false, layers: false });
  });
  it("a bit short: the layers collapse first, the maps keep their pills", () => {
    expect(navFit(450, 12, maps, layers)).toEqual({ maps: false, layers: true });
  });
  it("maps' pills don't fit beside even a collapsed layer button: maps collapse", () => {
    expect(navFit(370, 12, maps, layers)).toEqual({ maps: true, layers: false });
  });
  it("phone-narrow: both collapse", () => {
    expect(navFit(290, 12, maps, layers)).toEqual({ maps: true, layers: true });
  });
  it("one group only: its pills, or its button", () => {
    expect(navFit(310, 12, maps, undefined)).toEqual({ maps: false, layers: false });
    expect(navFit(250, 12, maps, undefined)).toEqual({ maps: true, layers: false });
    expect(navFit(150, 12, undefined, layers)).toEqual({ maps: false, layers: true });
  });
});
