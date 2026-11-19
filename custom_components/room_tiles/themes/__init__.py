"""Room Tiles themes: one packager for every theme (docs/THEMES.md).

  fmt.py        a theme folder read and checked (theme.json, pictures, clock)
  panel.py      its panel packs (.rtp)
  web.py        its dashboard pictures
  masters/      the default art: what a theme doesn't draw

The themes that come with Room Tiles are built at our build
(assets/build_panel.py, assets/build_web.py); a user's are built in Home
Assistant from /config/room_tiles_themes/. Nothing here imports Home
Assistant: the build scripts load this package on their own.
"""
