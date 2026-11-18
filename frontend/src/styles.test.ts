import { describe, expect, it } from "vitest";
import { applianceStyles } from "./appliance";
import { RoomTilesPanel } from "./room-tiles-panel";

/** class names used in a stylesheet's selectors */
const classes = (cssText: string) =>
  new Set([...cssText.replace(/\{[^}]*\}/g, "{}").matchAll(/\.([a-zA-Z][\w-]*)/g)].map((m) => m[1]));

describe("style modules sharing the panel's shadow root", () => {
  it("appliance styles use their own class names (a shared '.sheet' once broke the washer animation)", () => {
    const panel = (RoomTilesPanel.styles as unknown as { cssText: string }[])
      .filter((s) => s !== (applianceStyles as unknown))
      .map((s) => s.cssText)
      .join("\n");
    const own = classes(applianceStyles.cssText);
    // the panel's tile-cell state classes are referenced on purpose (edit mode)
    const shared = [...own].filter((c) => classes(panel).has(c) && !["cell", "editing"].includes(c));
    expect(shared).toEqual([]);
  });
});
