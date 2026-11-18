// The themes, read from their folders (docs/THEMES.md) - assets/themes/<id>/:
// theme.json (id, names, colours, order, default), and which pictures it
// draws itself (ui/<icon>_off.png, the buttons). Baked into the bundle
// (build.mjs) and the tests (vitest.config.ts) as THEME_DATA; read by
// src/theme.ts. The Python builds read the same folders (assets/theme_format.py).
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const THEMES = join(dirname(fileURLToPath(import.meta.url)), "..", "assets", "themes");
// buttons a theme may draw itself (its picture, else the button's glyph)
const BUTTONS = ["bar_grid", "bar_area_lights", "bar_map", "bar_help", "tile_map", "run_gift", "icon_settings"];

export function themeData() {
  const themes = [];
  const offArt = {};
  const buttonArt = {};
  for (const id of existsSync(THEMES) ? readdirSync(THEMES).sort() : []) {
    const file = join(THEMES, id, "theme.json");
    if (!existsSync(file)) continue;
    const doc = JSON.parse(readFileSync(file, "utf8"));
    themes.push({ id, name: doc.name, order: doc.order ?? 100, default: doc.default === true, colors: doc.colors ?? {} });
    const ui = join(THEMES, id, "ui");
    const files = existsSync(ui) ? readdirSync(ui) : [];
    offArt[id] = files.filter((f) => f.endsWith("_off.png")).map((f) => f.slice(0, -"_off.png".length)).sort();
    buttonArt[id] = BUTTONS.filter((b) => files.includes(`${b}.png`));
  }
  themes.sort((a, b) => Number(b.default) - Number(a.default) || a.order - b.order || a.id.localeCompare(b.id));
  // colours a theme leaves out: the default theme's
  const base = themes[0]?.colors ?? {};
  for (const t of themes) t.colors = { ...base, ...t.colors };
  return { themes, offArt, buttonArt };
}
