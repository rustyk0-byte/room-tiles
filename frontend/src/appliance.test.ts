import { describe, expect, it } from "vitest";
import { markerAnimation } from "./appliance";

describe("markerAnimation (an appliance's map marker)", () => {
  it("the top unit's animation wins, else the other's", () => {
    expect(markerAnimation("Dryer|drying|Drying||;Washer|washing|Washing||")).toBe("sun_dry");
    expect(markerAnimation("Upper|idle|Idle||;Lower|done|Done||")).toBe("check_done");
    expect(markerAnimation("Dishwasher|waiting|Wet||")).toBe("wet_hourglass");
  });
  it("none when nothing is running", () => {
    expect(markerAnimation("Dishwasher|idle|Idle||")).toBeUndefined();
    expect(markerAnimation(undefined)).toBeUndefined();
  });
});
