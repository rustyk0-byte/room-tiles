// Build the browser demo (src/demo.ts, docs/TODO.md "Landing page + browser
// demo") into a folder that works on any static web host:
//
//   node build-demo.mjs <demo data dir> <out dir>
//
// <demo data dir>: what tools/demo/make_demo.py wrote (feed.json, ...).
// <out dir> gets index.html (the demo's bar over app.html: the dashboard), demo.js, data/ (the made-up home), static/
// (the themes' pictures, where the dashboard looks for them) and only the
// icons the dashboard and the home use (from @mdi/js).
import { build } from "esbuild";
import { createHash } from "node:crypto";
import { cpSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { themeData } from "./theme-data.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const [dataDir, out] = process.argv.slice(2);
if (!dataDir || !out) {
  console.error("usage: node build-demo.mjs <demo data dir> <out dir>");
  process.exit(2);
}

// the icons: every "mdi:name" in the dashboard's code and the home's data
// (@mdi/js, a build-only dependency; without it the demo has no icons)
const mdi = await import("@mdi/js").catch(() => {
  console.warn("@mdi/js isn't installed (npm install): the demo has no icons");
  return {};
});
const text = [
  ...readdirSync(join(here, "src"))
    .filter((f) => f.endsWith(".ts") && !f.endsWith(".test.ts"))
    .map((f) => readFileSync(join(here, "src", f), "utf8")),
  ...readdirSync(dataDir).map((f) => readFileSync(join(dataDir, f), "utf8")),
].join("\n");
const icons = {};
for (const [, name] of text.matchAll(/mdi:([a-z0-9-]+)/g)) {
  const key = "mdi" + name.replace(/(^|-)([a-z0-9])/g, (_m, _d, c) => c.toUpperCase());
  if (mdi[key]) icons[`mdi:${name}`] = mdi[key];
}

mkdirSync(out, { recursive: true });
await build({
  entryPoints: [join(here, "src/demo.ts")],
  bundle: true,
  format: "esm",
  target: "es2022",
  minify: true,
  outfile: join(out, "demo.js"),
  define: {
    BUILD_ID: JSON.stringify("demo"),
    THEME_DATA: JSON.stringify(themeData()),
    DEMO_STATIC: JSON.stringify("static"),
    DEMO_ICONS: JSON.stringify(icons),
  },
});
// the pages ask for this build's frame and code by name + version: a web
// host may tell the browser to keep files for weeks (HA's /local: 31 days)
const v = createHash("sha256").update(readFileSync(join(out, "demo.js"))).digest("hex").slice(0, 10);
for (const [page, from, to] of [["index.html", '"app.html"', `"app.html?v=${v}"`], ["app.html", '"demo.js"', `"demo.js?v=${v}"`]]) {
  const text = readFileSync(join(here, "..", "tools", "demo", page), "utf8");
  if (!text.includes(from)) throw new Error(`${page}: no ${from}`);
  writeFileSync(join(out, page), text.replace(from, to));
}
cpSync(dataDir, join(out, "data"), { recursive: true });
// the themes' pictures (the dashboard bundle's folders, as HA serves them)
const bundle = join(here, "..", "custom_components", "room_tiles", "frontend");
for (const f of readdirSync(bundle, { withFileTypes: true }))
  if (f.isDirectory()) cpSync(join(bundle, f.name), join(out, "static", f.name), { recursive: true });
writeFileSync(join(out, ".nojekyll"), "");
console.log(`demo built in ${out}: ${Object.keys(icons).length} icons`);
