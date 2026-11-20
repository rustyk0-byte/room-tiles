import { describe, expect, it, vi } from "vitest";
import { LANGS, WORDING, language, languageReady, loadLanguage, onLanguage, setLanguage, t } from "./i18n";

// (its own file: a page's FIRST language is the case under test)
describe("languages load when shown", () => {
  it("only English at the start", () => {
    expect(Object.keys(LANGS)).toEqual(["en"]);
    expect(Object.keys(WORDING)).toEqual(["en"]);
  });

  it("a page's first language: nothing drawn until it's in, then it shows", async () => {
    const seen = vi.fn();
    const off = onLanguage(seen);
    expect(setLanguage("de-AT")).toBe(false);
    expect(languageReady()).toBe(false);
    expect(language()).toBe("en");
    await loadLanguage("de");
    await Promise.resolve();
    expect(languageReady()).toBe(true);
    expect(language()).toBe("de");
    expect(seen).toHaveBeenCalled();
    expect(WORDING.de).toBeDefined();
    expect(t("menu.language")).toBe(LANGS.de["menu.language"] ?? LANGS.en["menu.language"]);
    off();
  });

  it("switching later: the old language stays until the new one is in", async () => {
    expect(setLanguage("fr")).toBe(false);
    expect(languageReady()).toBe(true); // (no blank page after the first)
    expect(language()).toBe("de");
    await loadLanguage("fr");
    await Promise.resolve();
    expect(language()).toBe("fr");
    // loaded once: instant from now on
    expect(setLanguage("de")).toBe(true);
    expect(setLanguage("fr")).toBe(true);
  });

  it("a quick second pick wins over one still loading", async () => {
    setLanguage("en");
    setLanguage("es");
    setLanguage("en"); // (changed their mind before Spanish was in)
    await loadLanguage("es");
    await Promise.resolve();
    expect(language()).toBe("en");
  });
});
