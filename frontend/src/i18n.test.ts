import { beforeAll, describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { html, render } from "lit";
import { LANGS, LANG_NAMES, baseLanguage, loadLanguage, num, pct, setLanguage, t, th, thn, tn } from "./i18n";

const DIR = join(__dirname, "..", "i18n");
const files = readdirSync(DIR).filter((f) => f.endsWith(".json"));
const load = (f: string) => JSON.parse(readFileSync(join(DIR, f), "utf8")) as { strings: Record<string, string> };
const en = load("en.json").strings;
const holes = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

beforeAll(async () => {
  for (const code of Object.keys(LANG_NAMES)) await loadLanguage(code);
});

describe("string tables (frontend/i18n)", () => {
  it("every language file is loaded by i18n.ts", () => {
    expect(files.map((f) => f.replace(".json", "")).sort()).toEqual(Object.keys(LANG_NAMES).sort());
    expect(Object.keys(LANGS).sort()).toEqual(Object.keys(LANG_NAMES).sort());
    // each one but English: its own file (src/langs/<code>.ts)
    const langs = readdirSync(join(__dirname, "langs")).map((f) => f.replace(".ts", ""));
    expect(langs.sort()).toEqual(Object.keys(LANG_NAMES).filter((c) => c !== "en").sort());
  });

  for (const f of files) {
    it(`${f}: only known keys, the same placeholders as English, plural forms`, () => {
      const s = load(f).strings;
      const code = f.replace(".json", "");
      const forms = new Intl.PluralRules(code).resolvedOptions().pluralCategories;
      for (const [k, v] of Object.entries(s)) {
        const plural = k.match(/^(.*)\.(zero|one|two|few|many|other)$/);
        const base = plural ? `${plural[1]}.other` : k;
        expect(en[k] ?? en[base], `${f}: unknown key ${k}`).toBeDefined();
        const ref = en[k] ?? en[base];
        // a plural form may leave {n} out ("one" often says it in words)
        const want = holes(ref).filter((h) => !(plural && h === "n"));
        expect(holes(v).filter((h) => !(plural && h === "n")), `${f}: ${k}`).toEqual(want);
        expect(v.trim(), `${f}: ${k} is empty`).not.toBe("");
      }
      // a counted text this language has: every form it needs
      const counted = new Set(Object.keys(s).filter((k) => k.endsWith(".other")).map((k) => k.slice(0, -6)));
      for (const key of counted) for (const form of forms) if (form !== "zero") expect(s[`${key}.${form}`] ?? s[`${key}.other`], `${f}: ${key}.${form}`).toBeDefined();
    });
  }
});

describe("t / tn", () => {
  it("English, placeholders, unknown keys, plural forms", () => {
    setLanguage("en");
    expect(t("common.discard")).toBe("Discard");
    expect(t("no.such.key")).toBe("no.such.key");
    LANGS.en["test.count.one"] = "{n} room";
    LANGS.en["test.count.other"] = "{n} rooms";
    expect(tn("test.count", 1)).toBe("1 room");
    expect(tn("test.count", 3)).toBe("3 rooms");
    delete LANGS.en["test.count.one"];
    delete LANGS.en["test.count.other"];
  });
  it("HA's language code to a file", () => {
    expect(baseLanguage("en-GB")).toBe("en");
    expect(baseLanguage(undefined)).toBe("en");
    expect(baseLanguage("xx")).toBe("en");
  });
});

describe("th / thn (sentences with markup)", () => {
  it("fills parts with templates; the counted form by the language", () => {
    setLanguage("en");
    LANGS.en["test.link"] = "See {link} now.";
    LANGS.en["test.left.one"] = "{n} is left.";
    LANGS.en["test.left.other"] = "{n} are left.";
    const d = document.createElement("div");
    render(html`<p>${th("test.link", { link: html`<a href="#">here</a>` })}</p><p>${thn("test.left", 2, { n: html`<b>2</b>` })}</p>`, d);
    expect(d.querySelector("a")?.textContent).toBe("here");
    expect(d.textContent).toContain("See here now.");
    expect(d.querySelector("b")?.textContent).toBe("2");
    expect(d.textContent).toContain("2 are left.");
    for (const k of ["test.link", "test.left.one", "test.left.other"]) delete LANGS.en[k];
  });
});

describe("num / pct (numbers the language's way)", () => {
  it("decimal comma and percent spacing follow the language", () => {
    setLanguage("en");
    expect(num(72.5)).toBe("72.5");
    expect(num(0, 1, 1)).toBe("0.0");
    expect(pct(45)).toBe("45%");
    // (a Node built with English-only locale data can't check the rest;
    //  browsers and CI have them all)
    if (Intl.NumberFormat.supportedLocalesOf(["de"]).length) {
      setLanguage("de");
      expect(num(72.5)).toBe("72,5");
      expect(pct(45)).toMatch(/^45\s%$/);
      setLanguage("en");
    }
  });
});
