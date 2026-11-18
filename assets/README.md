# Room Tiles artwork

`masters/` holds the master copies of all artwork; everything the wall-panel
firmware and the dashboard show is generated from them. Edit a master, never
generated output.

- `masters/appliances/` - appliance pictures. Animated ones are sprite sheets of
  8 x 4 frames (196 px each, played row by row at 16 fps); `plate_knife_fork`
  and `shirt_socks` are single images (the still picture under an animation).
  Imported 2026-11-07 from the original panel firmware's LVGL arrays
  (`tools/lvgl_to_png.py`), which include edits made after the first exports.
- `masters/ui/icon_robot_vacuum.png` - the generic robot vacuum (non-Matic
  brands), drawn by `tools/make_robot_vacuum_icon.py` (2026-11-08) in the
  icons' style; replace with hand-made / AI art any time (same name, 60 x 60).
- `masters/ui/icon_scene.png`, `icon_script.png` - the scene (artist's
  palette, teal) and script (scroll with a play mark, orange) tile icons,
  drawn by `tools/make_run_icons.py` (2026-11-12); replace any time.
- `masters/ui/icon_pool.png`, `icon_spa.png` - the pool / spa tile icons,
  drawn by `tools/make_water_icons.py` (2026-11-12) in the icons' style;
  replace with hand-made / AI art any time (same names, 60 x 60).
- `masters/ui/` - switch tracks and knobs, slider tracks, padlocks, map icons,
  at the size the panels show them (1x). Sharper versions can replace them later
  without code changes. (2026-11-07: the two blind tracks had an opaque black
  background - made transparent with `tools/clear_border_black.py`.)

Alpha is on/off only (fully transparent or fully opaque) - by design; the
artwork is never alpha-blended. Generators must keep it that way
(`build_web.py` snaps alpha after resizing and writes lossless WebP).

`build_web.py` turns the masters into the dashboard's files, per theme
(`<out>/<theme>/...`); CI runs it. `build_panel.py` makes the panels' theme
packs from the same art.

## Themes

`themes/<theme>/{ui,appliances}/` replaces masters by name - same size and
format; anything a theme doesn't draw comes from `masters/`.
`themes/<theme>/ui/<icon>_off.png` is an icon's picture while its entity is
off (listed in `frontend/src/theme.ts` OFF_ART). The theme's colours are in
`frontend/src/theme.ts`.
**Picture formats in the panels' packs** (build_panel.py): every ui picture is
I8X - 256 palette entries with their own alpha, colour and alpha quantized
together (libimagequant), so soft edges keep their in-between alphas; the
panel expands each into RGB565A8 in PSRAM the first time it's drawn.
Exceptions stay RGB565A8 (`RGB565A8_ONLY`: gradients and shading 256 colours
would band, and the brand icon's exact colours). The appliance sheets stay I8
with on / off alpha.
`themes/<theme>/clock.json` + `ui/clock_face.png` (420 x 420), `clock_hour`,
`clock_minute`, optional `clock_second` and `clock_cap` make the theme's idle
clock: the hands drawn pointing at 12 at their own fixed sizes (optionally
also a large set, `clock_*_l.png` at 4/3 - 560 px - for the wall panels;
clock.json stays in 420-px units); clock.json
says where they turn on the face, each hand's pivot and length (a scale),
where the date goes and the pieces' order back to front (build_panel.py
theme_clock has the details and checks them). Christmas: an elf whose arms
are the hands, a candy-cane second hand, his buckle as the cap.
`themes/<theme>/ui/brand_bar.png` (48 x 48) is the panels' top-bar Room Tiles
icon: the logo must still be easy to make out - its four squares in its
middle, same size, place and color. Theme art may be drawn over them (a
wreath in front), but at most 40% of each square (`build_panel.py` checks);
the background and anything around them are the theme's.

- `light` - the dark theme's daylight twin: `tools/make_light_theme.py`
  darkens the few masters that vanish on a light tile (the grid and gear
  glyphs, the slider tracks, the off / closed / unlocked switch pills, the
  pool ladder, the spa's steam); everything else is the masters.
- `christmas` - drawn by `tools/make_christmas_theme.py` (run it again after
  changing it): a reindeer whose nose is a light bulb (lights; dark while
  off), a Christmas tree (switches; its lights go out), a snowflake (fans), a
  shade with snowflakes, a garage door with a wreath, a candy-cane
  thermometer, a roast turkey on the plate (dishwashers), an ugly sweater
  and a stocking (laundry), a bauble (scenes), Santa's list (scripts), a
  gingerbread gear, Santa hats on the vacuums and the spa, padlocks wrapped
  as presents, peppermint knobs; the animations turn into swirling
  snowflakes, a turning star, a candy-cane check and a snowy hourglass.

## Licence

All artwork here was generated with AI by the project's author and is
dedicated to the public domain under [CC0 1.0](LICENSE): use it for anything,
no conditions.

`tools/recolor.py SRC DEST "#RRGGBB"` recolours a master to a tile colour,
keeping its shading and its greys (the switch icon and its ON track are
raspberry `#E2559B` this way).

`tools/make_entry_icon.py` draws the garage-door icon (`masters/ui/icon_garage.png`,
used for every cover that lets people in: garage doors, gates, doors) in the
cover green and greys; it also draws the other options that were considered.
