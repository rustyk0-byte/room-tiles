import { describe, expect, it } from "vitest";
import { MIN_SHOWN, picBox, picHandleAt, resizePic, tiltFrom, toLocal, toWorld, traceBlend, turn90 } from "./trace-geom";
import type { TracePicture } from "./trace-store";

const pic = (more: Partial<TracePicture> = {}): TracePicture => ({ blob: new Blob(), x: 0, y: 0, w: 100, rot: 0, opacity: 0.5, ...more });
const close = (a: number[], b: number[]) => a.forEach((v, i) => expect(v).toBeCloseTo(b[i], 6));

describe("trace picture", () => {
  it("box: height from the image unless stretched; old pictures have no tilt", () => {
    expect(picBox(pic(), 0.5)).toEqual({ cx: 50, cy: 25, w: 100, h: 50, tilt: 0 });
    expect(picBox(pic({ rot: 1 }), 0.5).h).toBe(200);
    expect(picBox(pic({ h: 80 }), 0.5).h).toBe(80);
  });

  it("local / world round trip with a tilt", () => {
    const b = picBox(pic({ tilt: 30 }), 0.5);
    close(toWorld(b, toLocal(b, [7, -3])), [7, -3]);
    close(toLocal(b, toWorld(b, [50, 0])), [50, 0]);
  });

  it("handles: knob, corners, side dots, the picture", () => {
    const b = picBox(pic(), 0.5); // 100 x 50 at 0,0
    expect(picHandleAt(b, [50, -20], 4, 20)).toEqual({ kind: "turn" });
    expect(picHandleAt(b, [101, 51], 4, 20)).toEqual({ kind: "corner", sx: 1, sy: 1 });
    expect(picHandleAt(b, [0, 25], 4, 20)).toEqual({ kind: "side", sx: -1, sy: 0 });
    expect(picHandleAt(b, [30, 30], 4, 20)).toEqual({ kind: "move" });
    expect(picHandleAt(b, [300, 30], 4, 20)).toBeUndefined();
  });

  it("corner resizes keeping the shape; side stretches one way; the far side stays", () => {
    const b = picBox(pic(), 0.5);
    expect(resizePic(b, { kind: "corner", sx: 1, sy: 1 }, [200, 60], 5)).toEqual({ x: 0, y: 0, w: 200, h: 100 });
    expect(resizePic(b, { kind: "side", sx: 1, sy: 0 }, [150, 10], 5)).toEqual({ x: 0, y: 0, w: 150, h: 50 });
    const r = resizePic(b, { kind: "side", sx: 0, sy: -1 }, [40, -30], 5);
    close([r.x, r.y, r.w, r.h!], [0, -30, 100, 80]);
  });

  it("tilt from the knob: fine steps, straight near 0", () => {
    const b = picBox(pic(), 0.5);
    expect(tiltFrom(b, [50.2, -100])).toBe(0);
    expect(tiltFrom(b, [50 + 100 * Math.tan((3 * Math.PI) / 180), -75])).toBe(3);
  });

  it("a 90 degree turn swaps the sides around the centre", () => {
    expect(turn90(pic(), 0.5)).toEqual({ rot: 1, w: 50, h: 100, x: 25, y: -25 });
  });
});

describe("traceBlend (the Picture slider)", () => {
  it("middle: both in full; an end: the other faded, never gone", () => {
    expect(traceBlend(0.5)).toEqual({ picture: 1, drawing: 1 });
    expect(traceBlend(undefined)).toEqual({ picture: 1, drawing: 1 });
    expect(traceBlend(0)).toEqual({ picture: 1, drawing: MIN_SHOWN });
    expect(traceBlend(1)).toEqual({ picture: MIN_SHOWN, drawing: 1 });
    expect(traceBlend(0.25)).toEqual({ picture: 1, drawing: 0.5 });
  });
});
