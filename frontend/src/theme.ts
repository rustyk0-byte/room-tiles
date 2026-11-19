// Room Tiles themes. Components never hard-code colours or theme-specific
// image paths: colours are the --rt-* CSS variables set from these tokens,
// images go through assetUrl(). A theme is a folder (docs/THEMES.md):
// assets/themes/<id>/theme.json (its names, colours) + any pictures of its
// own (what it doesn't replace comes from custom_components/room_tiles/themes/masters/) - read at build
// time (frontend/theme-data.mjs, THEME_DATA), never listed here by hand. The
// panels' packs come from the same folders (assets/build_panel.py). Meanings
// keep their colours in every theme: heat / cool, the vacuum queue's states.

import { language } from "./i18n";

export type ThemeName = string;

interface ThemeInfo {
  id: string;
  name: Record<string, string>;
  order: number;
  default: boolean;
  colors: Record<string, string>;
}
declare const THEME_DATA: {
  themes: ThemeInfo[];
  offArt: Record<string, readonly string[]>;
  buttonArt: Record<string, readonly string[]>;
};
const DATA: typeof THEME_DATA =
  typeof THEME_DATA !== "undefined" ? THEME_DATA : { themes: [], offArt: {}, buttonArt: {} };

/** The bundled themes' ids, the default first (then each theme.json's order). */
export const THEME_NAMES: readonly ThemeName[] = DATA.themes.map((th) => th.id);
export const DEFAULT_THEME: ThemeName = DATA.themes.find((th) => th.default)?.id ?? THEME_NAMES[0] ?? "dark";

/** A theme the user installed (Room Tiles' feed "themes" - user_themes.py
 *  for_dashboard): described like the bundled ones, its pictures at `base`. */
export interface InstalledTheme {
  id: string; // "user:<its folder>"
  name: Record<string, string>;
  order: number;
  colors: Record<string, string>;
  offArt: string[];
  buttonArt: string[];
  base: string;
}
/** An installed theme's id: never a bundled theme's (user_themes.py). */
export const isInstalledId = (id: string): boolean => id.startsWith("user:");
const INSTALLED_BASE: Record<ThemeName, string> = {};
let installed: InstalledTheme[] = [];

/** Every theme to pick: the bundled ones, then the installed ones. */
export function themeNames(): ThemeName[] {
  return [...THEME_NAMES, ...installed.map((th) => th.id)];
}

/** The theme's name in the dashboard's language (its theme.json), else English. */
export function themeName(id: ThemeName): string {
  const th = DATA.themes.find((x) => x.id === id) ?? installed.find((x) => x.id === id);
  return th ? (th.name[language()] ?? th.name.en ?? id) : id;
}

// MIRRORED: firmware/components/room_tiles/board.cpp paint_ (off_art) - a change here must be made there too.
/** Icons with a picture of their own while their entity is off: any icon a
 *  theme has an `<icon>_off.png` for (drawn, or generated: theme.json "off") -
 *  from the theme folders. */
export const OFF_ART: Record<ThemeName, readonly string[]> = DATA.offArt;

// MIRRORED: firmware/components/room_tiles/board.cpp (lights_art_, the Map
// button, build_map_ / the play button) - a change here must be made there too.
/** Buttons a theme draws itself (a picture of that name in its ui/ folder);
 *  without one they show their icon glyphs. The panels always draw the gear
 *  as a picture.
 *    bar_area_lights (+ _off)  the top bar's Area Lights
 *    bar_map                   the top bar's Map
 *    tile_map                  the Map tile's picture
 *    run_gift                  the scene / script tiles' play button
 *    icon_settings             the gear */
export const BUTTON_ART: Record<ThemeName, readonly string[]> = DATA.buttonArt;

/** The theme draws this button itself (BUTTON_ART). */
export function hasArt(theme: ThemeName, name: string): boolean {
  return (BUTTON_ART[theme] ?? []).includes(name);
}

/** A tile / marker icon's picture for its state, in the theme. */
export function iconArt(icon: string, on: boolean, theme: ThemeName): string {
  return !on && (OFF_ART[theme] ?? []).includes(icon) ? `${icon}_off` : icon;
}

export interface ThemeTokens {
  // surfaces
  page: string; // page background (panels: black)
  tile: string; // tile face
  tileBorder: string;
  button: string; // inactive button
  dialog: string;
  panelDark: string; // marker / label backgrounds
  // text
  text: string;
  textSecondary: string;
  onAccent: string; // text / glyphs on an accent fill (a primary or selected button)
  onBright: string; // text on a bright fill (the amber Done button, a tag)
  // accents
  accent: string; // action buttons, selection
  accentSoft: string;
  // per-kind "on" colours
  light: string;
  fan: string;
  cover: string;
  lock: string;
  switch: string;
  scene: string; // teal: a scene tile's button
  script: string; // orange: a script tile's button
  heat: string;
  cool: string;
  heatStrong: string; // thermostat / pool roller values
  coolStrong: string;
  rollerText: string; // roller rows above / below the selected one
  off: string; // off icons
  // the map (panel firmware map_view.h)
  mapBg: string; // ground outside the house
  mapFloor: string;
  mapWall: string;
  mapWindow: string;
  mapLabel: string; // room labels on the floor
  mapLabelOut: string; // outdoor labels on the ground
  mapWater: string;
  mapGrass: string;
  mapDeck: string;
  mapPaving: string;
  mapMarker: string; // marker face
  mapMarkerBorder: string;
  // the vacuum room queue's rooms and status (panel firmware matic_ui.h)
  vacQueued: string;
  vacStarting: string; // sent, the vacuum isn't cleaning yet
  vacCleaning: string;
  vacPaused: string;
  vacAttention: string; // needs you: refill, empty, put back
  vacError: string;
}

/** Each theme's colours (its theme.json; any it leaves out: the default theme's). */
export const THEMES: Record<ThemeName, ThemeTokens> = Object.fromEntries(
  DATA.themes.map((th) => [th.id, th.colors as unknown as ThemeTokens]),
);

const kebab = (s: string) => s.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);

/** The theme as CSS custom properties (--rt-page, --rt-tile-border, ...). */
export function themeCss(name: ThemeName = DEFAULT_THEME): string {
  const t = THEMES[name] ?? THEMES[DEFAULT_THEME];
  return Object.entries(t)
    .map(([k, v]) => `--rt-${kebab(k)}:${v}`)
    .join(";");
}

/** URL of a theme's image (generated into frontend/<theme>/ by assets/). */
declare const BUILD_ID: string;
/** The build's id on every image address: a new build's artwork is never
 *  served from a browser's cache of the old one (the files have no cache
 *  headers, and Safari / the HA app keep images anyway). */
const VERSION = typeof BUILD_ID !== "undefined" ? `?v=${encodeURIComponent(BUILD_ID)}` : "";

export function assetUrl(base: string, name: string, theme: ThemeName = DEFAULT_THEME): string {
  // an installed theme's pictures: where Room Tiles built them (the address
  // changes with their content - no version needed)
  const own = INSTALLED_BASE[theme];
  if (own) return `${own}/${name}`;
  // a theme this dashboard doesn't know (an installed one not listed yet, or
  // gone): the default's pictures, as its colours (themeCss)
  return `${base}/${THEMES[theme] ? theme : DEFAULT_THEME}/${name}${VERSION}`;
}

/** The installed themes from Room Tiles' feed: into the lists above (their
 *  colours already over the default's - the integration fills them). */
export function setInstalledThemes(list: InstalledTheme[]): void {
  for (const th of installed) {
    delete THEMES[th.id];
    delete (OFF_ART as Record<string, readonly string[]>)[th.id];
    delete (BUTTON_ART as Record<string, readonly string[]>)[th.id];
    delete INSTALLED_BASE[th.id];
  }
  installed = [...list].sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));
  for (const th of installed) {
    THEMES[th.id] = { ...THEMES[DEFAULT_THEME], ...th.colors } as ThemeTokens;
    (OFF_ART as Record<string, readonly string[]>)[th.id] = th.offArt;
    (BUTTON_ART as Record<string, readonly string[]>)[th.id] = th.buttonArt;
    INSTALLED_BASE[th.id] = th.base;
  }
}
