import { describe, expect, it } from "vitest";
import { pinnedTop } from "./dialog-pin";

describe("dialog top edge", () => {
  it("stays where it opened while the content fits", () => {
    expect(pinnedTop(200, 300, 12, 788)).toBe(200); // shorter or taller, same top
    expect(pinnedTop(200, 588, 12, 788)).toBe(200); // exactly reaches the bottom
  });
  it("moves up only as far as needed to fit", () => {
    expect(pinnedTop(200, 700, 12, 788)).toBe(88);
  });
  it("never above the top limit", () => {
    expect(pinnedTop(200, 900, 60, 788)).toBe(60);
  });
});
