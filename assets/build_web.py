#!/usr/bin/env python3
"""Build the dashboard's pictures for the themes that come with Room Tiles
(assets/themes/) - needs Pillow. The builder itself is the integration's
(custom_components/room_tiles/themes/web.py - the same code builds the
themes users install, in Home Assistant).

  python3 assets/build_web.py OUT_DIR      (CI: the integration's frontend/)

Writes OUT_DIR/<theme>/appliances/<name>.webp and OUT_DIR/<theme>/ui/<name>.png.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import theme_format  # noqa: E402  (the theme folders, read and checked)
from _themekit import web  # noqa: E402

THEMES = theme_format.ids()  # (assets/themes/*/theme.json)


def main() -> None:
    root = Path(sys.argv[1])
    for theme in THEMES:
        src = theme_format.source(theme)
        try:
            for line in web.build_appliances(src, root / theme / "appliances") + web.build_ui(src, root / theme / "ui"):
                print(line)
        except web.fmt.ThemeError as err:
            raise SystemExit(str(err)) from None


if __name__ == "__main__":
    main()
