# Contributing to Room Tiles

Bug fixes, features, translations and support for more devices are welcome.
Every change goes through a pull request, and the maintainer reviews and
approves it before it's merged.

Room Tiles is under the Apache License 2.0 ([LICENSE](LICENSE)); what you
contribute is under the same license.

## How

1. **Fork** this repository and create a branch for your change.
2. Make the change, with tests where it changes behavior.
3. Open a **pull request** against `main`. The checks run automatically
   (for a first-time contributor, once the maintainer lets them start).
4. The maintainer reviews it. Changes may be asked for; push them to the same
   branch. Once it's approved, the maintainer merges it, and it goes out with
   the next release.

For something big, open an issue first so we can agree on the approach
before you put the work in.

## Running the checks yourself

- **Integration (Python):** `pip install -r requirements_test.txt`, then
  `pytest`.
- **Dashboard:** in `frontend/`: `npm install`, `npm run typecheck`,
  `npm test`.
- **Panel firmware:** `tools/sync-firmware.sh build`, then in `build/`:
  `esphome compile room-tiles-<board>.yaml` (ESPHome version: see
  `.github/workflows/firmware.yml`).

## Another touch panel

Room Tiles' firmware is one ESPHome configuration for every panel; a new
panel is mostly a board file. Ports to more ESP32 touch panels are very
welcome.

What a panel needs: an ESP32-P4 or ESP32-S3 with PSRAM, 16 MB of flash, and
a screen and touch that ESPHome's LVGL can drive. A 1024x600 screen gets
the full layout; a smaller or round one can show a room's tiles in one strip
(`layout: strip` and `map: false` in its board file, like the 2.1" round
panel).

1. Open an issue first with the panel's name and a link, so we can agree on
   the approach.
2. Add the hardware in `firmware/boards/` (display, touch, backlight and
   the rest - start from the closest existing board) and a device file in
   `firmware/devices/`, named by what's printed on the board.
3. Build it and try it on your panel (see "Running the checks yourself"):
   install, Wi-Fi setup, the tiles, an update.
4. Open the pull request with what you tried, and add the panel to
   [docs/SUPPORTED.md](docs/SUPPORTED.md) as "Beta".

[firmware/README.md](firmware/README.md) explains the firmware's folders.

## Reports as tests

A model report or problem report on GitHub carries a recorded cycle. To keep
it as evidence (and to make sure a fix stays fixed):
`python3 tools/report_to_test.py <issue number>` replays it through today's
logic, prints what the tile shows step by step, and saves it in
`tests/reports/`. Check the steps, then commit the case with the change -
`tests/test_reports.py` replays every case from then on. Washers, dryers,
dishwashers and vacuums so far.

## Guidelines

- **Text:** everything the user reads comes from the wording files
  (`frontend/i18n/<language>.json`, English the full set). Short and
  friendly, in US English. If you can, add your text in the other languages
  too - or leave English there and say so in the pull request.
- **Panels and dashboard behave alike:** logic that exists on both sides is
  marked `MIRRORED` in both places; change both.
- **Privacy:** no personal details in code, tests, screenshots or commit
  messages - no names, addresses, serial numbers or entity ids from your
  home.
- **Docs:** keep the README and docs/ describing how things work now.

## Home Assistant's rules

The integration follows what Home Assistant's reviewers check for:

- **No file access on the event loop.** Code that runs on the loop (`async
  def`, `@callback`) never opens, reads, writes or checks files itself -
  not even `exists()` or `is_dir()`. Do it in a plain function through
  `hass.async_add_executor_job(...)`, or use HA's `Store`. Large files
  (theme packs) are read when needed and not kept in memory.
  `tests/test_event_loop_io.py` checks every change.
- **Only Room Tiles' own secrets.** Never read another integration's keys,
  tokens or config entry data; Room Tiles makes and stores its own
  (each panel's key).
- **Services that touch files are admin-only** (`async_register_admin_service`)
  and stay inside `room_tiles_backups/` - never a path the caller picks.
