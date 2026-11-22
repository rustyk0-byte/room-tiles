// node render.mjs <svg dir> <png dir>: each SVG to a PNG of its own size, transparent
import { chromium } from "playwright-core";
import { readdirSync, readFileSync, mkdirSync } from "node:fs";
const [src, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
// (CHROMIUM: the browser to use, else Playwright's own)
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ["--no-sandbox"] });
const page = await browser.newPage();
for (const f of readdirSync(src).filter((n) => n.endsWith(".svg"))) {
  const s = readFileSync(`${src}/${f}`, "utf8");
  const w = Number(/width="([\d.]+)"/.exec(s)[1]), h = Number(/height="([\d.]+)"/.exec(s)[1]);
  await page.setViewportSize({ width: Math.max(w, 400), height: Math.max(h, 400) });
  await page.setContent(`<html><body style="margin:0;background:transparent">${s}</body></html>`, { waitUntil: "load" });
  await page.screenshot({ path: `${out}/${f.replace(".svg", ".png")}`, omitBackground: true, clip: { x: 0, y: 0, width: w, height: h } });
}
await browser.close();
