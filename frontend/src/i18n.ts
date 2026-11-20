// The dashboard's wording in HA's language: one string table per language
// (frontend/i18n/<lang>.json - the same design as the integration's
// wording/<lang>.json, DESIGN.md "Wording stays in one place").
//
//   t("unsaved.title")                       -> "Save your map changes?"
//   t("queue.rooms_left", { n: 3 })          -> placeholders: {n}
//   tn("help.more_scenes", 3)                -> plurals: key.one / key.other
//                                               (Intl.PluralRules; {n} filled)
//
// English (en.json) is the full set; a key missing in another language falls
// back to English, an unknown key to itself (so a typo shows, never a blank).
// English is in the bundle; every other language is its own small file
// (src/langs/<code>.ts: these strings + the status wording), loaded when a
// device shows it - the page downloads one language, not seven. Opening the
// language setting loads the rest, so switching stays instant; until a new
// language is in, the old one stays on screen.
// ADDING A LANGUAGE = its i18n file, src/langs/<code>.ts, LOADERS and
// LANG_NAMES; CHANGING WORDING = editing a file. Use the local way of saying
// a thing, not a word-for-word translation. i18n.test.ts checks every file:
// valid, only known keys, the same placeholders as English, the plural forms
// the language needs.

import en from "../i18n/en.json";
import enWording from "../../custom_components/room_tiles/wording/en.json";

type Table = Record<string, string>;
interface LangFile {
  _about?: string;
  strings: Table;
}
interface LangModule {
  strings: LangFile;
  wording: LangFile;
}

/** language code -> its strings, once loaded (English always) */
export const LANGS: Record<string, Table> = { en: (en as LangFile).strings };
/** language code -> the integration's status wording (words.ts), once loaded */
export const WORDING: Record<string, Table> = { en: (enWording as LangFile).strings };

// one file per language (esbuild makes each its own chunk)
const LOADERS: Record<string, () => Promise<LangModule>> = {
  de: () => import("./langs/de"),
  fr: () => import("./langs/fr"),
  es: () => import("./langs/es"),
  it: () => import("./langs/it"),
  nl: () => import("./langs/nl"),
  pt: () => import("./langs/pt"),
};

/** Each language's own name (the per-device language setting). */
export const LANG_NAMES: Record<string, string> = {
  en: "English",
  de: "Deutsch",
  es: "Español",
  fr: "Français",
  it: "Italiano",
  nl: "Nederlands",
  pt: "Português",
};

let lang = "en";
let plural = new Intl.PluralRules("en");
let wanted = "en";
let ready = true;
let first = true;
const loading: Record<string, Promise<void>> = {};
const listeners = new Set<() => void>();

/** "de-AT" -> "de"; "pt-BR" stays "pt-BR" if there's a file for it. */
export function baseLanguage(code?: string | null): string {
  const c = (code || "en").replace("_", "-");
  if (c in LANG_NAMES) return c;
  const base = c.split("-")[0].toLowerCase();
  return base in LANG_NAMES ? base : "en";
}

/** Loads a language's file (once). A file that can't be had - a page left
 *  open across an update - leaves the language out: English shows. */
export function loadLanguage(code: string): Promise<void> {
  if (LANGS[code] || !LOADERS[code]) return Promise.resolve();
  return (loading[code] ??= LOADERS[code]()
    .then((m) => {
      LANGS[code] = m.strings.strings;
      WORDING[code] = m.wording.strings;
    })
    .catch(() => {
      delete loading[code];
    }));
}

/** Every language in the background (the language setting opened). */
export function loadAllLanguages(): void {
  for (const code of Object.keys(LOADERS)) void loadLanguage(code);
}

function use(code: string): void {
  lang = LANGS[code] ? code : "en";
  plural = new Intl.PluralRules(lang);
}

/** HA's language (hass.locale.language) or the device's, set by the panel.
 *  True when the wording changed now; a language still loading switches
 *  when it's in (onLanguage) - the old one stays until then. */
export function setLanguage(code?: string | null): boolean {
  const next = baseLanguage(code);
  const firstCall = first;
  first = false;
  wanted = next;
  if (next === lang) return false;
  if (LANGS[next] || !LOADERS[next]) {
    use(next);
    return true;
  }
  if (firstCall) ready = false; // (a page's first language: nothing drawn in English meanwhile)
  void loadLanguage(next).then(() => {
    ready = true;
    if (wanted === next && lang !== next) use(next);
    for (const f of listeners) f();
  });
  return false;
}

/** False only while the first language a page asked for is loading. */
export const languageReady = (): boolean => ready;

/** Called when a language that was loading is in (redraw). */
export function onLanguage(f: () => void): () => void {
  listeners.add(f);
  return () => listeners.delete(f);
}

export const language = (): string => lang;

function fill(text: string, vars?: Record<string, string | number>): string {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (all, name: string) => (name in vars ? String(vars[name]) : all));
}

/** The text for `key` in the current language (English, else the key). */
export function t(key: string, vars?: Record<string, string | number>): string {
  return fill(LANGS[lang]?.[key] ?? LANGS.en[key] ?? key, vars);
}

/** A counted text: `key.one` / `key.few` / `key.other`... as the language
 *  needs (Intl.PluralRules), with {n} = the count. */
export function tn(key: string, n: number, vars?: Record<string, string | number>): string {
  const form = plural.select(n);
  const table = LANGS[lang] ?? {};
  const text = table[`${key}.${form}`] ?? table[`${key}.other`] ?? LANGS.en[`${key}.${n === 1 ? "one" : "other"}`] ?? LANGS.en[`${key}.other`] ?? key;
  return fill(text, { n, ...vars });
}

/** A sentence with parts that are markup (a link, a bold name): the
 *  translation keeps the WHOLE sentence - words around a part can move -
 *  and each {name} is filled with `parts[name]` (text or a template).
 *    th("map.switch_to", { layer: html`<b>${name}</b>` }) */
export function th(key: string, parts: Record<string, unknown>): unknown[] {
  const text = LANGS[lang]?.[key] ?? LANGS.en[key] ?? key;
  const out: unknown[] = [];
  let last = 0;
  for (const m of text.matchAll(/\{(\w+)\}/g)) {
    out.push(text.slice(last, m.index));
    out.push(m[1] in parts ? parts[m[1]] : m[0]);
    last = (m.index ?? 0) + m[0].length;
  }
  out.push(text.slice(last));
  return out; // (Lit renders a list of parts in place)
}

/** th() for a counted sentence: the form for `n` in this language (key.one /
 *  key.few / key.other...), {n} = parts.n if given (e.g. bold), else n. */
export function thn(key: string, n: number, parts: Record<string, unknown> = {}): unknown[] {
  const form = plural.select(n);
  const table = LANGS[lang] ?? {};
  const k = `${key}.${form}` in table ? `${key}.${form}` : `${key}.other` in table ? `${key}.other` : `${key}.${n === 1 ? "one" : "other"}`;
  return th(k, { n, ...parts });
}

/** A number the language's way: "72.5" / "72,5" (at most `digits`
 *  decimals, at least `min`). */
export function num(x: number, digits = 1, min = 0): string {
  if (!Number.isFinite(x)) return "--";
  try {
    return new Intl.NumberFormat(lang, { minimumFractionDigits: min, maximumFractionDigits: digits }).format(x);
  } catch {
    return x.toFixed(digits);
  }
}

/** A whole percent the language's way: "45%" / "45 %". */
export function pct(n: number): string {
  try {
    return new Intl.NumberFormat(lang, { style: "percent", maximumFractionDigits: 0 }).format(n / 100);
  } catch {
    return `${Math.round(n)}%`;
  }
}

/** "a, b, c" in the language's way of listing (Intl.ListFormat). */
export function listOf(items: string[]): string {
  try {
    return new Intl.ListFormat(lang, { style: "short", type: "unit" }).format(items);
  } catch {
    return items.join(", ");
  }
}
