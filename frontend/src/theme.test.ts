import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { BUTTON_ART, hasArt, iconArt, OFF_ART, THEME_NAMES, THEMES } from "./theme";

const art = (theme: string, name: string) =>
  [`../assets/themes/${theme}/ui/${name}.png`, `../custom_components/room_tiles/themes/masters/ui/${name}.png`].some((f) => existsSync(resolve(__dirname, "..", f)));

describe("themes", () => {
  it("every theme has its colours, its lists and the same tokens", () => {
    const keys = Object.keys(THEMES.dark).sort();
    for (const name of THEME_NAMES) {
      expect(Object.keys(THEMES[name]).sort()).toEqual(keys);
      expect(OFF_ART[name]).toBeDefined();
      expect(BUTTON_ART[name]).toBeDefined();
    }
  });

  it("the pictures the lists name exist (the panels use the same files)", () => {
    for (const name of THEME_NAMES) {
      for (const icon of OFF_ART[name]) expect(art(name, `${icon}_off`), `${name}: ${icon}_off`).toBe(true);
      for (const b of BUTTON_ART[name]) expect(art(name, b), `${name}: ${b}`).toBe(true);
    }
  });

  it("an icon's picture follows its state only where the theme has one", () => {
    expect(iconArt("icon_light", false, "christmas")).toBe("icon_light_off");
    expect(iconArt("icon_light", true, "christmas")).toBe("icon_light");
    // Dark / Light: every entity icon has its generated one (assets/tools/make_off_icons.py)
    expect(iconArt("icon_light", false, "dark")).toBe("icon_light_off");
    expect(iconArt("icon_script", false, "light")).toBe("icon_script_off");
    // a theme without one for an icon: the same picture on and off
    expect(iconArt("icon_ac", false, "christmas")).toBe("icon_ac");
    expect(hasArt("christmas", "bar_map")).toBe(true);
    expect(hasArt("dark", "bar_map")).toBe(false);
  });
});

describe("installed themes (Room Tiles' feed)", () => {
  it("join the list after the bundled ones, with their colours and pictures", async () => {
    const th = await import("./theme");
    th.setInstalledThemes([
      { id: "user:candy", name: { en: "Candy" }, order: 100, colors: { accent: "#E8508A" }, offArt: ["icon_fan"], buttonArt: ["bar_map"], base: "/room_tiles_themes/abc/web" },
    ]);
    expect(th.themeNames()).toEqual([...THEME_NAMES, "user:candy"]);
    expect(th.themeName("user:candy")).toBe("Candy");
    expect(THEMES["user:candy"].accent).toBe("#E8508A");
    expect(THEMES["user:candy"].page).toBe(THEMES.dark.page); // (left out: the default's)
    expect(iconArt("icon_fan", false, "user:candy")).toBe("icon_fan_off");
    expect(hasArt("user:candy", "bar_map")).toBe(true);
    expect(th.assetUrl("/x", "ui/icon_fan.png", "user:candy")).toBe("/room_tiles_themes/abc/web/ui/icon_fan.png");
    expect(th.assetUrl("/x", "ui/icon_fan.png", "dark")).toMatch(/^\/x\/dark\/ui\/icon_fan\.png/);
    // removed: gone from every list
    th.setInstalledThemes([]);
    expect(th.themeNames()).toEqual([...THEME_NAMES]);
    expect(THEMES["user:candy"]).toBeUndefined();
    expect(th.isInstalledId("user:candy") && !th.isInstalledId("christmas")).toBe(true);
  });
});
