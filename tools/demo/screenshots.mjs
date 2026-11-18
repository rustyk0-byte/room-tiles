// The landing page's pictures, taken from the browser demo (docs/TODO.md
// "Landing page + browser demo") in a headless browser - the Screenshots
// workflow runs it:
//
//   node tools/demo/screenshots.mjs <demo url, ending in /> <out dir>
//
// Needs Playwright (npm install playwright; npx playwright install chromium).
// Each picture: the dashboard's own page (app.html: no demo bar), set up
// through what it keeps in the browser (room, theme) and a few clicks.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { chromium } from "playwright";

const [base, out] = process.argv.slice(2);
if (!base || !out) {
  console.error("usage: node screenshots.mjs <demo url/> <out dir>");
  process.exit(2);
}
mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const DESKTOP = { width: 1280, height: 800 };
const PANEL = { width: 1024, height: 600 }; // (the panels' screen)

/** The dashboard on `area` in `theme`, ready. */
async function open({ area = "living_room", theme = "dark", viewport = DESKTOP, phone = false, layout = "5x2" } = {}) {
  const ctx = await browser.newContext({
    viewport,
    deviceScaleFactor: 2,
    colorScheme: "dark",
    isMobile: phone,
    hasTouch: phone,
  });
  await ctx.addInitScript(
    ([a, th, lay]) => {
      localStorage.setItem("room-tiles:area", a);
      localStorage.setItem("room-tiles:theme", th);
      localStorage.setItem("room-tiles:layouts", JSON.stringify({ [a]: lay }));
    },
    [area, theme, layout],
  );
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.warn(`page error: ${e.message}`));
  await page.goto(base + "app.html");
  await page.locator("room-tiles-panel .tile").first().waitFor();
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(1200); // (pictures, the first animation frames)
  return { page, ctx };
}

const failed = [];

/** One picture - a failure is reported, and the rest still taken. */
async function shot(name, setup, take = (page) => page.screenshot({ path: join(out, name) })) {
  const { page, ctx } = await open(setup);
  try {
    if (setup.then) await setup.then(page);
    await take(page);
    console.log(name);
  } catch (e) {
    failed.push(name);
    console.error(`${name}: ${e.message.split("\n")[0]}`);
    await page.screenshot({ path: join(out, `failed-${name}`) }).catch(() => {});
  }
  await ctx.close();
}

const openMap = async (page) => {
  await page.locator('room-tiles-panel button.head-btn[title="Map"]').click();
  await page.locator("room-tiles-panel rt-map").waitFor();
  await page.waitForTimeout(1200);
};

// a room's board, the size of a panel's screen (the opening's picture until a photo)
await shot("hero.png", { area: "living_room", viewport: PANEL });
// a room's tiles
await shot("tiles.png", { area: "living_room" });
// the map: zoomed into the Devices layer
await shot("map.png", {
  area: "living_room",
  then: async (page) => {
    await openMap(page);
    // (the visible one - the bar keeps hidden copies to measure; opened from
    // a room, the map may be zoomed into the Devices layer already)
    const devices = page.locator("room-tiles-panel button.floor:visible", { hasText: "Devices" }).first();
    if ((await devices.getAttribute("aria-pressed")) !== "true") await devices.click();
    await page.waitForTimeout(1500);
  },
});
// the laundry tile: the dryer done, the washer running
await shot("laundry.png", { area: "laundry" }, (page) =>
  page.locator("room-tiles-panel .tile.kind-appliance").first().screenshot({ path: join(out, "laundry.png") }),
);
// the robot vacuum's room queue on the map
await shot("vacuum.png", {
  area: "living_room",
  then: async (page) => {
    await page.locator("room-tiles-panel .tile.kind-vacuum").first().click();
    await page.waitForTimeout(1500);
  },
});
// a phone
await shot("phone.png", { area: "kitchen", viewport: { width: 390, height: 844 }, phone: true });
// the themes: the same room in each, side by side
const themes = ["dark", "light", "christmas"];
for (const theme of themes) await shot(`theme-${theme}.png`, { area: "kitchen", theme, viewport: PANEL });

// Pictures made of pictures (a page of them, photographed): the themes in a
// row; the link preview (1200 x 630) - the logo, the words, a board.
async function compose(name, size, html) {
  try {
    const ctx = await browser.newContext({ viewport: size, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    await page.setContent(html());
    await page.evaluate(() => Promise.all([...document.images].map((i) => i.decode())));
    await page.screenshot({ path: join(out, name) });
    await ctx.close();
    console.log(name);
  } catch (e) {
    failed.push(name);
    console.error(`${name}: ${e.message.split("\n")[0]}`);
  }
}
const data = (f) => `data:image/png;base64,${readFileSync(join(out, f)).toString("base64")}`;
await compose(
  "themes.png",
  { width: 2048 * 3 + 80, height: 1200 + 40 },
  () => `<body style="margin:0;background:#0b0c0e;display:flex;gap:20px;padding:20px">
    ${themes.map((th) => `<img src="${data(`theme-${th}.png`)}" style="width:2048px;height:1200px;border-radius:24px">`).join("")}
  </body>`,
);
const icon = readFileSync(new URL("../../custom_components/room_tiles/brand/icon@2x.png", import.meta.url)).toString("base64");
await compose(
  "og.png",
  { width: 1200, height: 630 },
  () => `<body style="margin:0;width:1200px;height:630px;background:#121417;color:#eceef1;font-family:Roboto,sans-serif;display:flex;align-items:center;gap:40px;padding:0 0 0 60px;box-sizing:border-box;overflow:hidden">
    <div style="flex:0 0 430px">
      <img src="data:image/png;base64,${icon}" style="width:110px;height:110px">
      <div style="font-size:64px;font-weight:700;margin:18px 0 10px">Room Tiles</div>
      <div style="font-size:30px;line-height:1.3;color:#9aa1ab">Every room, one tap away - for Home Assistant</div>
    </div>
    <img src="${data("hero.png")}" style="height:460px;border-radius:18px;box-shadow:0 20px 50px #000">
  </body>`,
);
await browser.close();
writeFileSync(join(out, "README.txt"), "Taken by tools/demo/screenshots.mjs from the browser demo.\n");
if (failed.length) {
  console.error(`not taken: ${failed.join(", ")}`);
  process.exit(1);
}
