// Build the dashboard bundle with a build id baked in (BUILD_ID) and written
// next to it (version.json): an open page compares the two and offers a
// reload when a newer build has been installed. Every language but English
// is its own file in lang/ (i18n.ts loads it when shown; hashed names, so a
// browser never keeps an old one). Each .js gets a .gz copy beside it: HA
// sends that one to a browser that takes gzip (about a quarter of the size -
// HA doesn't compress these files itself).
import { build } from "esbuild";
import { readFileSync, readdirSync, writeFileSync, mkdirSync, rmSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { themeData } from "./theme-data.mjs";

const out = "../custom_components/room_tiles/frontend";
const id = (process.env.GITHUB_SHA || "dev").slice(0, 12) + "-" + Date.now().toString(36);
rmSync(`${out}/lang`, { recursive: true, force: true }); // (the last build's)
mkdirSync(out, { recursive: true });
await build({
  entryPoints: ["src/room-tiles-panel.ts"],
  bundle: true,
  format: "esm",
  target: "es2022",
  minify: true,
  sourcemap: true,
  splitting: true,
  outdir: out,
  entryNames: "[name]",
  chunkNames: "lang/[name]-[hash]",
  define: { BUILD_ID: JSON.stringify(id), THEME_DATA: JSON.stringify(themeData()) },
});
writeFileSync(`${out}/version.json`, JSON.stringify({ build: id }) + "\n");
for (const dir of [out, `${out}/lang`])
  for (const f of readdirSync(dir).filter((n) => n.endsWith(".js")))
    writeFileSync(`${dir}/${f}.gz`, gzipSync(readFileSync(`${dir}/${f}`), { level: 9 }));
console.log("built", id);
