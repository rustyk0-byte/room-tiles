// Build the dashboard bundle with a build id baked in (BUILD_ID) and written
// next to it (version.json): an open page compares the two and offers a
// reload when a newer build has been installed.
import { build } from "esbuild";
import { writeFileSync, mkdirSync } from "node:fs";
import { themeData } from "./theme-data.mjs";

const out = "../custom_components/room_tiles/frontend";
const id = (process.env.GITHUB_SHA || "dev").slice(0, 12) + "-" + Date.now().toString(36);
mkdirSync(out, { recursive: true });
await build({
  entryPoints: ["src/room-tiles-panel.ts"],
  bundle: true,
  format: "esm",
  target: "es2022",
  minify: true,
  sourcemap: true,
  outfile: `${out}/room-tiles-panel.js`,
  define: { BUILD_ID: JSON.stringify(id), THEME_DATA: JSON.stringify(themeData()) },
});
writeFileSync(`${out}/version.json`, JSON.stringify({ build: id }) + "\n");
console.log("built", id);
