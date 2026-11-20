import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { LANG_NAMES, loadLanguage, setLanguage } from "./i18n";
import { formatMinutes, localText, localTile, wordText } from "./words";

beforeAll(async () => {
  for (const code of Object.keys(LANG_NAMES)) await loadLanguage(code);
});
afterEach(() => setLanguage("en"));

describe("status words in this device's language", () => {
  it("renders tokens, placeholders, minutes and plain text", () => {
    expect(wordText({ k: "pool.short.heating" }, "en")).toBe("Heating");
    expect(wordText([{ k: "pool.short.heating" }, "\n", { min: 65 }], "en")).toBe("Heating\n~1h 05m");
    expect(wordText({ k: "pool.off_other_running", p: { body: { k: "pool.body.spa" } } }, "en")).toBe("Off - Spa running");
    expect(wordText("Main Wash", "de")).toBe("Main Wash");
    expect(formatMinutes(45, "en")).toBe("~45m");
    expect(formatMinutes(65, "de")).toBe("~1:05 h");
    expect(formatMinutes(0, "en")).toBe("");
    // a language without a table: English
    expect(wordText({ k: "pool.short.heating" }, "ja")).toBe("Heating");
  });

  it("fills a tile's words in, whatever language HA wrote the text in", () => {
    const attributes = {
      // HA in German: its text - the words decide what this device shows
      tile: "Spa|82|Heizt\n~0:49 h|heating|97|on",
      tile_words: JSON.stringify({ "0.0": { k: "pool.body.spa" }, "0.2": [{ k: "pool.short.heating" }, "\n", { min: 49 }] }),
    };
    setLanguage("en");
    expect(localTile(attributes)).toBe("Spa|82|Heating\n~49m|heating|97|on");
    setLanguage("fr");
    expect(localTile(attributes).split("|")[2]).toContain("49");
    expect(localTile(attributes).split("|")[3]).toBe("heating");
  });

  it("keeps units apart and falls back to the text", () => {
    const attributes = {
      tile: "Upper|done|Sauber|plate|;Lower|washing|Spült|plate|~1:05 h",
      tile_words: JSON.stringify({ "0.2": { k: "appliance.clean" }, "1.2": { k: "step.rinsing" }, "1.4": { min: 65 } }),
    };
    expect(localTile(attributes)).toBe("Upper|done|Clean|plate|;Lower|washing|Rinsing|plate|~1h 05m");
    expect(localTile({ tile: "docked|Docked||" })).toBe("docked|Docked||"); // no words: as it is
    expect(localTile({ tile: "a|b", tile_words: "not json" })).toBe("a|b");
    expect(localText(undefined, "Docked")).toBe("Docked");
    expect(localText('{"k":"robot.docked"}', "Angedockt")).toBe("Docked");
    expect(localText("", "Angedockt")).toBe("Angedockt");
  });
});
