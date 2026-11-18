import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { firstPick } from "./model-report";

describe("firstPick", () => {
  it("adds the most recent cycle, else a pool's longest window, else nothing", () => {
    const c = { start: 1, end: 2 };
    expect(firstPick({ history: true, cycles: [c, c], windows: [] })).toBe(0);
    expect(firstPick({ history: true, cycles: [], windows: [{ ...c, hours: 6 }, { ...c, hours: 24 }] })).toBe("w1");
    expect(firstPick({ history: true, cycles: [], windows: [] })).toBe("none");
    expect(firstPick({ history: false, cycles: [c], windows: [] })).toBe("none");
  });
});

describe("model report wording", () => {
  it("every feature the integration asks about has its words in every language", () => {
    const py = readFileSync(join(__dirname, "..", "..", "custom_components", "room_tiles", "model_report.py"), "utf8");
    const block = py.slice(py.indexOf("_APPLIANCE = ("), py.indexOf("# confirmed on real hardware"));
    const keys = new Set([...block.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]).filter((k) => !["washer", "dryer", "dishwasher", "pool", "vacuum"].includes(k)));
    keys.add("laundry_pair");
    expect(keys.size).toBeGreaterThan(15);
    for (const lang of ["en", "de", "es", "fr", "it", "nl", "pt"]) {
      const strings = JSON.parse(readFileSync(join(__dirname, "..", "i18n", `${lang}.json`), "utf8")).strings;
      for (const k of keys) expect(strings[`model.feature.${k}`], `${lang} ${k}`).toBeTruthy();
    }
  });
});
