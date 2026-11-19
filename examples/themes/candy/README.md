# Candy - an example theme

A small, complete Room Tiles theme to start your own from. The full format
is in [docs/THEMES.md](../../../docs/THEMES.md).

| File | What it does |
|---|---|
| `theme.json` | Its id (the folder's name), its name in each language, and its colors. Colors it leaves out come from the default theme. |
| `"off": "gray"` (in theme.json) | Room Tiles makes every icon's "off" picture: the icon in gray inside an outline in that kind's color. |
| `ui/icon_light.png` | Its own light icon: a wrapped candy. |
| `ui/icon_scene.png` | Its own scene icon: a lollipop. |

The two pictures are drawn at 2x (120×120 for 60×60 icons) - Room Tiles
brings them down to size. Everything else comes from the default art.

## Try it

On the Room Tiles dashboard, open the settings menu and, under Theme, **Add
a theme from a link** with:

    https://github.com/rustyk0-byte/room-tiles/releases/latest/download/candy.zip

Or copy the `candy` folder into `/config/room_tiles_themes/` in Home
Assistant (make that folder if it isn't there) and open the settings menu
(or wait a few minutes). Either way, Candy shows up in the theme lists of
your dashboards and panels.

## Make it yours

Rename the folder and the `id` to the same new name, change the names and
colors, and add or replace pictures - each one listed in docs/THEMES.md
under [Pictures](../../../docs/THEMES.md#pictures). Save, open the settings
menu again, and Room Tiles builds the new version. If something's wrong,
Home Assistant's Repairs says what.
