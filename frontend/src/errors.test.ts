import { beforeEach, describe, expect, it } from "vitest";
import { clearErrors, noteError, recentErrors, whereIn } from "./errors";

describe("recent errors", () => {
  beforeEach(() => clearErrors());

  it("keeps only Room Tiles' own, as a file and line - no folders, no query", () => {
    const ours = "TypeError: x\n    at f (https://ha.local:8123/room_tiles_frontend/room-tiles-panel.js?v=dev-abc:3:51234)";
    expect(whereIn(ours)).toBe("room-tiles-panel.js:3:51234");
    expect(whereIn("at g (https://ha.local/frontend_latest/app.js:1:2)")).toBeUndefined();
    expect(whereIn(undefined, "https://ha.local/room_tiles_frontend/room-tiles-panel.js?v=1", 7, 9)).toBe("room-tiles-panel.js:7:9");
    noteError("theirs", "at g (https://ha.local/frontend_latest/app.js:1:2)");
    noteError("ours", ours, undefined, undefined, undefined, 1000);
    expect(recentErrors(31000)).toEqual([{ ago_s: 30, message: "ours", where: "room-tiles-panel.js:3:51234" }]);
  });

  it("keeps the last 10", () => {
    for (let i = 0; i < 15; i++) noteError(`e${i}`, "at (room-tiles-panel.js:1:1)", undefined, undefined, undefined, i * 1000);
    const got = recentErrors(20000);
    expect(got).toHaveLength(10);
    expect(got[0].message).toBe("e5");
    expect(got[9]).toEqual({ ago_s: 6, message: "e14", where: "room-tiles-panel.js:1:1" });
  });
});
