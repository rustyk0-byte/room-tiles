# Room Tiles themes

A theme changes how Room Tiles looks on the dashboard and on the touch
panels: its colors, and any pictures it wants to draw its own way. This page
is the theme format - **format 1**.

The themes that come with Room Tiles (Dark, Light, Christmas) are made this
way, and a theme of your own is installed by putting its folder in Home
Assistant (see [Installed themes](#installed-themes)).

**Start here:** [`examples/themes/candy/`](../examples/themes/candy/) is a
small, complete theme - a few colors, two pictures of its own and generated
"off" pictures - with a guide to trying it and making it yours. The themes
that come with Room Tiles are in [`assets/themes/`](../assets/themes/) to
copy from too.

## A theme is a folder

```
my-theme/
  theme.json          its name and colors (required)
  ui/                 pictures it draws itself (optional)
  appliances/         appliance animations it draws itself (optional)
  clock.json          its own idle clock (optional, with ui/clock_*.png)
```

Everything is optional except `theme.json`. A picture the theme doesn't
have comes from the default art, and a color it doesn't set comes from the
default theme - so a theme can be just a few colors.

## theme.json

```json
{
  "format": 1,
  "id": "candy",
  "name": { "en": "Candy", "de": "Süßigkeiten" },
  "off": "gray",
  "colors": { "page": "#1A0D14", "tile": "#2A1420", "accent": "#E8508A" }
}
```

| Key | | |
|---|---|---|
| `format` | required | `1` |
| `id` | required | the folder's name: a-z, 0-9, `-` or `_`, up to 32 - it never clashes with a theme that comes with Room Tiles (see [Installed themes](#installed-themes)) |
| `name` | required | its name per language (`en`, `de`, `es`, `fr`, `it`, `nl`, `pt`); English is required, the others fall back to it |
| `colors` | optional | colors as `#rrggbb` - see below |
| `off` | optional | `"gray"`: Room Tiles makes the "off" picture of every icon (see [Off pictures](#off-pictures)) |
| `order` | optional | its place among the installed themes (lower first) |

## Colors

Set any of these; the rest come from the default theme.

| Surfaces | |
|---|---|
| `page` | the page behind everything |
| `tile`, `tileBorder` | a tile's face and edge |
| `button` | a button that isn't selected |
| `dialog` | menus and dialogs |
| `panelDark` | behind map markers and labels |

| Text | |
|---|---|
| `text`, `textSecondary` | main and quieter text |
| `onAccent` | text on an `accent` fill |
| `onBright` | text on a bright fill (the Done button) |
| `rollerText` | a roller's rows above and below the chosen one |

| Accents and meanings | |
|---|---|
| `accent`, `accentSoft` | action buttons, selection |
| `light`, `switch`, `fan`, `cover`, `lock`, `scene`, `script` | each kind of tile's "on" color - also its map marker and off-picture outline |
| `heat`, `cool`, `heatStrong`, `coolStrong` | heating and cooling |
| `off` | off icons |

| The map | |
|---|---|
| `mapBg`, `mapFloor`, `mapWall`, `mapWindow` | ground, floors, walls, windows |
| `mapLabel`, `mapLabelOut` | room names indoors and outdoors |
| `mapWater`, `mapGrass`, `mapDeck`, `mapPaving` | outdoor surfaces |
| `mapMarker`, `mapMarkerBorder` | a marker's face and edge |

| The vacuum's room queue | |
|---|---|
| `vacQueued`, `vacStarting`, `vacCleaning`, `vacPaused`, `vacAttention`, `vacError` | each room's and the vacuum's state |

Keep heating red and cooling blue - those colors mean the same in every
theme.

## Pictures

**Any normal PNG.** Truecolor with alpha (8 bits per channel) is best;
plain RGB, palette, grayscale and 16-bit PNGs work too. Use sRGB colors.
Draw with soft, smooth edges - Room Tiles decides per picture how its edges
are kept.

**The size given below, or 2× or 4× of it** (a 60×60 icon can also be
120×120 or 240×240). Larger sources give cleaner small versions.

**Your picture becomes a palette.** Each picture keeps up to 256 distinct
colors (with their transparency). Flat-color art comes through unchanged;
very smooth gradients may band slightly. Animated PNGs use their first frame
only.

### Icons - ui/

| Name | Size | |
|---|---|---|
| `icon_light`, `icon_switch`, `icon_fan`, `icon_blind`, `icon_garage`, `icon_key`, `icon_ac`, `icon_dishwasher`, `icon_laundry`, `icon_robot_vacuum`, `icon_matic`, `icon_pool`, `icon_spa`, `icon_scene`, `icon_script` | 60×60 | tiles, map markers, lists |
| `<icon>_off` | 60×60 | the same icon while its device is off (optional) |
| `icon_settings` | any (see [Top bar](#top-bar)) | the gear |
| `icon_grid_6x3` | 36×36 | the "more tiles" button |

### Buttons a theme may draw - ui/

Without one, the button shows its plain symbol.

| Name | Size | |
|---|---|---|
| `bar_grid` | any (see [Top bar](#top-bar)) | the top bar's "more tiles" button |
| `bar_map` | any | the top bar's Map button |
| `bar_area_lights` (+ `_off`) | any | the top bar's lights button |
| `bar_help` | any | the top bars' Help button |
| `tile_map`, `tile_map_s` | 76×58, 52×40 | the Map tile, on big and small tiles |
| `run_gift`, `run_gift_s` | 60×60, 41×41 | the scene / script button, on big and small tiles |
| `brand_bar` | 48×48 | the Room Tiles icon in the top bar |

### Top bar

The top bars' buttons - `bar_grid`, `bar_map`, `bar_area_lights` (and its
`_off`), `bar_help` and the gear `icon_settings` - all come out the **same
size**, on the dashboard and on the panels, and the same size as the plain
symbols beside them. Draw them at **any size**: the build trims the empty
edges around what you drew, scales it to fit one box and centers it. Draw
with a little room around the picture if you want it to look smaller.

| | The box | Its button | The plain symbols |
|---|---|---|---|
| Panels | 32×26 | 48×40 | 28 px |
| Dashboard | 24×20 (drawn at 48×40, for sharp screens) | 40×36 | 20 px |

- Keep the picture about as wide as tall, up to 4:3 - a long, flat picture
  comes out small.
- `bar_area_lights_off` is fitted together with `bar_area_lights` (the same
  trim and scale), so the button doesn't change size when the lights do -
  draw both on the same canvas.
- `bar_grid` keeps its colors: on the bigger 6x3 grid, the button's border
  lights up instead (the plain symbol itself turns the light color).

### Controls - ui/

Switch tracks, knobs, sliders and padlocks (`track_*`, `knob_*`,
`lock_padlock_*`, `temp_track`, `hue_ring`, `swatch_ring`) can be replaced
too - same names and sizes as the default art (`custom_components/room_tiles/themes/masters/ui/`).

### Appliances - appliances/

| Name | Size | |
|---|---|---|
| `plate_knife_fork`, `shirt_socks` | 196×196 | a dishwasher's, a washer's / dryer's still picture |
| `bubble_wash`, `sun_dry`, `wet_hourglass`, `check_done` | 1568×784 | animations: 8 × 4 frames of 196×196, left to right, top to bottom |

## Off pictures

An icon can look different while its device is off - a light off, a cover
closed, a lock locked, an appliance idle, a vacuum docked. The tile and its
map marker both show it.

- **Draw your own:** `ui/<icon>_off.png`, for any icon you like.
- **Or let Room Tiles make them:** `"off": "gray"` gives every icon an off
  picture - the icon in gray inside a thin outline in that kind's color.
- **Or neither:** the icon looks the same on and off.

Off map markers are always gray, with a ring in the kind's color.

## Idle clock

A theme can draw its own clock for the panels' idle screen: `clock.json`
plus `ui/clock_face.png` (420×420), `ui/clock_hour.png`,
`ui/clock_minute.png` and optionally `ui/clock_second.png` and
`ui/clock_cap.png`. A matching set at 4/3 the size (`clock_face_l.png`
560×560, and `_l` versions of the rest) makes it sharper on the bigger
screens.

```json
{
  "center": [210, 210],
  "hands": {
    "hour":   { "pivot": [27, 104], "length": 1.0 },
    "minute": { "pivot": [25, 144], "length": 1.0 },
    "second": { "pivot": [24, 160] }
  },
  "date": { "at": [210, 300], "align": "center", "font": "small", "color": "text" },
  "cap": { "at": [210, 210] },
  "order": ["face", "date", "hour", "minute", "second", "cap"]
}
```

- `center`: where the hands turn, on the face.
- `hands`: each hand's picture points at 12; `pivot` is the point it turns
  about (in its own picture), `length` scales it (0.3 - 1.5), `at` gives it
  its own spot on the face. `hour` and `minute` are required.
- `date` (optional): where the date sits; `font` small, medium or large;
  `color` a `#rrggbb` or a color name from above.
- `cap` (optional): a picture over the hands' middle.
- `order` (optional): the pieces from back to front.

## Installed themes

**To install a theme,** put its folder - or a zip of it - in
`/config/room_tiles_themes/` (make the folder the first time; the File
editor or Samba add-on, for example, can do it). A zip may have
`theme.json` at its top or inside one folder.

**Or from a link:** on the dashboard, the settings menu's Theme has **Add a
theme from a link** (for administrators). Paste a theme zip's link, a
theme folder's link on GitHub (like the example's), or a GitHub
repository's - Room Tiles takes its latest release's zip, or the
repository itself when it has no release. It's checked, then saved as
`<id>.zip` in the same folder. Sharing a theme: put it in a GitHub
repository with `theme.json` at its top, and attach a zip of it to a
release.

- **No restart:** Room Tiles looks there every few minutes, and whenever
  the dashboard's settings menu opens. The first time, it builds the
  theme's pictures for the panels and the dashboard - a few seconds, up to
  a minute on a small Home Assistant computer - then the theme shows up in
  the theme lists on panels and dashboards, like any other. Change a file
  and it's built again the same way; take the folder away and the theme
  goes.
- **Something wrong?** A theme Room Tiles can't use is listed in Home
  Assistant's Repairs, with what to fix. Everything using it shows the
  default theme until it's fixed.
- **Names never clash:** your `christmas` and the Christmas that comes
  with Room Tiles are two themes - now, and after any Room Tiles update.
  Lists show the themes that come with Room Tiles first, then yours.
- **The default stays a built-in theme.**
- **A theme with a newer format** than this Room Tiles reads waits in
  Repairs until Room Tiles is updated.

## Versions

`format` tells Room Tiles which version of this page a theme follows.
Additions that older themes simply don't use (a new icon, a new color) keep
format 1 - the default fills them in. A change that would break existing
themes raises the format number, and Room Tiles says when a theme needs
updating.
