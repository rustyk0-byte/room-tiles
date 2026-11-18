# Room Tiles - still to do

Open work in priority order. Decisions and rules live in DESIGN.md / UI.md;
this is only the list. Remove an item when it's built.

Order: **1. Installing and updating panels**, then **2. Before the public
release**. After those, sort what must be done before going public from what
can wait.

## 1. Installing and updating panels (current)

Goal: nobody compiles anything. A first install is a browser and a USB
cable; after that, panels update with Room Tiles itself.

**First install (what the user does):**
1. Open the Room Tiles install page in Chrome / Edge, pick the board (photos:
   7" V1.0, 7" V1.2, 10.1" ...), plug in USB-C, Install (~2 min).
2. Wi-Fi: the install page asks for the network right after flashing
   (Improv over USB); or the panel's hotspot, from a phone. (Picking it on
   the panel itself comes after the first release - section 6.)
3. HA shows "Discovered: Room Tiles Panel" - Add (one click; HA sets the
   encryption key).
4. The panel asks which area it's in; its board appears.

**Updates (what the user does):** nothing, by default. A Room Tiles update
(HACS) carries the matching firmware for every board; panels install it on
their own ("Updating firmware… 45%", restart, back to the board). Turned
off: each panel has HA's usual update entry (Settings › Updates: Install,
Skip, release notes) and Room Tiles' settings can update all of them. A
panel whose format no longer matches (PANEL_SCHEMA) updates right away even
then; its Repairs notice gets an "Update now" button.

**Built so far:** the frozen flash layout (DESIGN.md "Flash layout"); one
generic firmware per board - the panel's identity a package of its own
(`firmware/identity/`), device files per board named by what's printed on
it (`firmware/devices/`, `tools/sync-firmware.sh`), Wi-Fi through the
panel's hotspot (also when its network goes away), ⚙ › Change Wi-Fi and the
boot screen's Change Wi-Fi; updates through Room Tiles - each build's board,
build and kind reported, images read from the integration's and the config
folder, an update entity on each panel's device, the panel's own install
with progress (DESIGN.md "Firmware updates through Room Tiles"). Every
existing panel has moved over and updates this way. Also built: "Update
panels automatically" (on by default; never to an older build, a few tries
at most), a panel too old for HA updating itself from its 426 answer, the
image's panel format in its tag (another format is never offered), the
dashboard's Panels page (each panel's firmware, Install, the switch,
Upload firmware), one image per board in the folder.

**Left, by phase:**
- **A + B. CI** (`.github/workflows/firmware.yml`, written 2026-11-15; the
  one-board build runs green, the all-boards / release run not tried yet).
  Run by hand (free on the public repo; a build takes minutes): the device
  files named (or "all") for a chip kind - each fails above 80% of a slot
  (`tools/check_firmware_size.py`) - and on a pull request; "all" or a
  release, every board's update + factory image (a release: attached to it), for
  engineering-sample chips (v1.x) and production ones (v3.x) from the same
  device file (`esphome -s engineering_sample false`; a production 10.1"
  build compiles). The chip's revision is never the user's pick (it isn't
  printed anywhere): the install page reads it from the chip, updates go by
  what the panel reports. Production images take chips from v3.0 up
  (`CONFIG_ESP32P4_REV_MIN_300` in the board file - ESP-IDF's default v3.1
  would refuse a v3.0 board). Left: the production builds come with the
  HACS pre-release test (E: a release builds every board for both chip
  kinds); a production board booting one waits for a beta tester or the
  first users (the maintainer has no production board).
- **C. The install page - drafted 2026-11-15** (`install/index.html`,
  `tools/make_install_site.py`, the firmware workflow's install-page job:
  GitHub Pages for each release, once the repo is public). ESP Web Tools'
  tasmota fork (Apache-2.0) tells an ESP32-P4's chip revisions apart
  ("rev0" below v3.0, "rev300" from v3.0) and picks the matching build -
  the user only picks what's printed on the board. Improv over USB after
  flashing is on. Left: board photos, production-chip builds. NOT tried
  by the maintainer (no USB flashing on the test panels): browser flashing of the
  P4 and the install page are first tried by others - a beta tester or the
  first users (say so in the release notes).
- **D. Setup screens on the panel - built and tried 2026-11-17** (DESIGN.md
  "Boot screen"): a Factory Reset (the panel's HA button) took a 7" V1.0
  back to new; the language picker, the hotspot's Wi-Fi page, "Add this
  panel in Home Assistant", the first downloads all worked. Left: the area
  picker on a panel HA has never seen (a re-added one gets its old HA area
  back), each line in another language, the 10.1" screen (a Factory Reset
  there - no USB needed); the round one untested (section 3). (The
  reset screen's tiles flashing for its 1.5 s: fixed, not built yet -
  hold_boot_screen_.)
- **E. Updates, the rest:**
  - The release zip carries every board's update image - written
    2026-11-16, not yet run: a published release (`release.yml`) builds
    every board and the dashboard, `tools/make_release_zip.py` packs the
    integration + dashboard + each board's `.ota.bin` into `firmware_images/`
    (only generic images in this panel format, each under its own board's
    name), manifest.json's version from the tag; HACS `zip_release`
    (`room_tiles.zip`). 17 images: ~22 MB to download, ~36 MB installed.
  - Test the whole path with a real HACS update of a pre-release (the
    restart prompt is built: UI.md "An update HA hasn't restarted for").
  - An automatic update while a panel is dark keeps it dark: the install
    runs behind the dark screen and the new firmware goes dark again as
    it starts (written 2026-11-15, not yet tried; the backlight is still
    on for the first seconds of the start - ALWAYS_ON in the board file).
- **F. Safety - proven 2026-11-17 on a 7" V1.0:** an image that crashes 10 s
  after starting (a throwaway branch), installed through Room Tiles'
  automatic update, came back on the old build both times (ESP-IDF
  rollback: it crashed before safe_mode marked it good; "CRASH DETECTED ON
  PREVIOUS BOOT", the old build running), and automatic updates stopped
  after two tries (AUTO_TRIES). Also checked in the build: a failed download
  or write never touches the running slot, one job at a time. The try count
  is kept across HA restarts (.storage/room_tiles.firmware_tries, only the
  builds still offered). Left (cosmetic): the crashing build briefly checks
  in before it crashes, so its update card flips to "installed" for a few
  seconds.
- **G. The Wi-Fi chip's firmware - written 2026-11-17; built and proven
  2026-11-18 on a 7" V1.0** (2.12.12 -> 2.12.13: "Updating the Wi-Fi chip…",
  one restart, HA shows 2.12.13). Left: the other boards (a 7" V1.2 and a
  10.1" V1.2 of the maintainer's test panels) on the new build
  (DESIGN.md "The Wi-Fi chip"): every image carries ESPHome's
  `network_adapter` 2.12.13 (= the ESP-Hosted library of ESPHome 2026.10.2)
  and brings an older chip up to it once, at startup, before Wi-Fi. Left:
  - The next build: the image grows by 1.2 MB (to ~3.4 MB of a 5 MB slot -
    the size check in CI); the boards' current chips (2.12.12) are older,
    so **every panel updates its chip on its first start** - start with
    ONE panel (build one board, watch its log), then the rest.
  - A board straight from the box (2.3.0 / 2.12.3): never tried - verify
    on the next new board (or users report it). The 2.3.0 path (no
    "activate", restart after 25 s) rests on the 2026-10-12 V1.0 update.
  - Keep in step: an ESPHome upgrade that moves ESP-Hosted needs the
    matching image (firmware/wifi_chip/README.md).

## 2. Before the public release

- **Desk stand**: the 3D-printable desk frame for the Elecrow panels (print
  files + a short how-to) goes in the repo; the README already says it will
  be shared. Panels may stand on a desk or hang on a wall - docs say
  "ESP32 panels" (a tablet is a touch panel too), never assume a wall.
- **Full localization with a string table** (a release gate). No
  user-facing text hard-coded anywhere - dashboard, panel firmware,
  notifications, Repairs, config flow, help pages: every string comes from
  one string table per language (frontend/i18n/<lang>.json; English the
  full set, de / es / fr / it / nl / pt shipped as drafts - the README asks
  for native corrections). Left:
  - Later: load only the active language (all seven are in the dashboard
    bundle today - ~720 KB, ~190 KB gzip).
- **Map pictures for colorful theme packs**: markers, names and room names
  are 4-bit sprites (16 colors each) - fine for one color per marker, but a
  theme pack with multi-colored icons or gradients would band. Measure
  8-bit indexed (256 colors) for marker faces: memory (~3.5 KB a face vs
  ~1.4 KB; a map's 15-25 combinations may spill to PSRAM) and draw time.
  Likely answer: the depth per picture, with a tolerance - 4-bit when 16
  colors cover the picture closely enough (e.g. 98% of its pixels exact,
  the rest near), else 8-bit; the threshold tuned by eye on a colorful pack.
- **Report unknown states back**: the answers people give on the Appliances
  page ("Dryer reported "steam_fresh" - Not running") are exactly what the
  released presets need. Volunteer, never automatic: after answering, an
  "Also tell Room Tiles" choice (and a "Report all my answers" button on the
  Appliances page) sends brand, preset, model, the raw state and the answer
  - nothing else (DESIGN.md "Privacy") - through the feedback route
  (prefilled GitHub issue, later in-app via GitHub sign-in), labeled
  "unknown-state". Maintainers add them to the preset's state lists (with a
  test) so the next release knows them for everyone.
- **Report scrubber** (DESIGN.md "Privacy: what reports send") - **the
  scrubber is written 2026-11-17** (custom_components/room_tiles/report.py,
  tests/test_report.py): the report layout as an allow-list (REPORT - kind,
  versions, integration, device, kind / preset, states and recordings by
  role, answers from fixed choices, checklist, outcome); every value typed;
  strings checked for addresses, ids, hardware addresses, serials, entity
  ids, times of day (full timestamps become deltas from the report's
  earliest) and the home's own words (secrets_from_hass - the names
  the user gave, ids, serials; never the integrations' own words); each
  drop noted with why; summary() for the screen. **The flow is written
  too** (DESIGN.md "Privacy" - report.ts, room_tiles/report_preview, the
  wording in 7 languages; a developer build's gear > Test report). Left:
  the reports that use it, on the Appliances page - unknown states ("Also
  tell Room Tiles": **written 2026-11-17**, report.py build_unknown_state),
  model reports ("Report how it went": checklist + works / partly /
  broken - **written 2026-11-18**, model_report.py, model-report.ts),
  and problems ("Report a problem" for appliances, pools and
  robot vacuums: the user's words + a whole cycle / pump run / clean from
  HA's history or recorded live, HA restarts marked - **written
  2026-11-17**, cycles.py, DESIGN.md "Privacy"; it replaces "Record a
  cycle"), and "Send feedback" in the settings menu (bug / idea / question;
  appliance, pool and vacuum problems handed to their Report a problem;
  issue forms with labels - **written 2026-11-18**, feedback.ts, DESIGN.md
  "Privacy"). The labels the forms use exist (problem, model-report,
  unknown-state, and GitHub's bug, enhancement, question).
- **Reports: what's left** (after panel facts in panel bugs, the
  dashboard's recent errors in dashboard bugs, and HA's Download
  diagnostics - 2026-11-18):
  - **Report to test** (maintainer tool): turn a model report's or a
    problem report's issue into a CI test that replays its cycle through
    the preset (step 3 of clearing a beta flag below).
  - **Setup's beta notes** (found devices) point to Report how it went once
    the device is set up.
  - **Unknown vacuum states:** "Also tell Room Tiles" for a vacuum state
    Room Tiles doesn't know, like an appliance's.
  - Later (the repo public, or a GitHub sign-in): send reports from inside
    the app (device flow); show open issues for a model before a duplicate
    goes out; tell the reporter when their fix is released; a QR code on
    the panels that opens Send feedback with that panel filled in.
- **Formal procedure to clear a beta flag**. Beta must only go away through
  a defined, recorded path - never by hand-waving:
  1. **The user reports in the app** (done 2026-11-18 on the Appliances
     page's set-up cards; setup's own beta notes still to link): every beta
     note has "Report how it went" -> the Model report,
     prefilled: brand, model / setup, integration + version, Room Tiles + HA
     versions, preset, the features-by-model rows as a checklist (works /
     partly / broken / not tried), plus a "works" or "has problems" choice.
  2. **Evidence attached automatically** (done: a recent cycle / pump run /
     clean or a pool's last hours, picked by default; shown before
     sending): a recorded cycle (raw states over a real cycle - "record a
     cycle") or, for pools / vacuums, a few hours of the raw entities'
     states. No house details.
  3. **Maintainer checklist** (an issue template + label "model-report"):
     evidence replays through the preset as a CI test; each feature row
     checked; then the PR adds the model to the preset's
     `confirmed_models` (a robot: model_report.py CONFIRMED_ROBOTS; a pool
     setup: CONFIRMED_POOLS) + SUPPORTED.md "Confirmed
     models" + its ? marks -> ✓ / ✗, and links the report. Problems -> a
     fix PR first, then the same checklist.
  4. **Released:** the next version drops the beta note for that model;
     the reporter is told (issue closed with the release).
  Bugs on verified models go the same way (Bug report) and can put a model
  back to beta until fixed.
- **Make contributing hardware support easy**. Anyone can fork, fix and open
  a pull request; lower the bar:
  - `CONTRIBUTING.md` (the general flow is there) gets an "Add your brand /
    model" guide; the pull-request template a checklist for it (preset,
    finder, test, SUPPORTED.md row).
  - Presets as DATA files (one per brand, e.g.
    `presets/appliances/lg_thinq.yaml`) instead of Python, so a new brand is
    a file, not code; finders stay code only where matching needs it.
  - **Record a cycle:** an action / dashboard button that records an
    appliance's raw state changes during a real cycle into a JSON file. It
    doubles as the TEST for that model (CI replays it through the preset and
    checks the phases), and as evidence for "Confirmed models".
  - **No-code route:** the user's own answers for unknown states (overrides)
    plus a dashboard "Share as a preset" that turns them + the recorded
    cycle into a ready pull request / issue (through the same GitHub sign-in
    as the feedback page) - people who don't code can still add support.
  - CI on every pull request (already runs: tests, hassfest, frontend) plus
    a check that SUPPORTED.md was updated when a preset changed.
- **Feedback page** in the dashboard (settings menu "Send feedback", plus a
  "Report" button next to every beta note in setup). Three kinds:
  - **Model report:** a device works / partly works / is broken. Prefilled:
    brand, model, integration + version, Room Tiles + HA versions, the
    preset, that type's features-by-model rows as a checklist
    (works / partly / broken / not tried), unknown raw states seen.
  - **Bug report:** what happened, where, versions. (Done: Send feedback.)
  - **Feature request.** (Done: Send feedback's idea and question.)
  How - through GitHub, which delivers everything to the repo owner as
  issues (notifications, labels, one place). Nothing is sent by itself: the
  user sees exactly what goes out. No entity names / areas / house details
  unless the user types them. Needs the public repo. Steps:
  1. v1 (done): the page builds a prefilled GitHub issue (issue forms in
     `.github/ISSUE_TEMPLATE/`, labeled by kind) and opens it; the user
     presses Submit on GitHub (needs a GitHub account).
  2. Fully in-app: "Sign in with GitHub" once (GitHub's device flow - a
     Room Tiles OAuth app, the user types a code at github.com/login/device);
     the integration then files the issue through GitHub's API as that user,
     straight from the page, and can show its replies / status.
  NOT possible without the user's own GitHub account through GitHub alone:
  a project token can't ship inside open-source code (anyone could pull it
  out and spam). A no-account route would need a small relay server holding
  the token - hosting, spam and privacy to weigh first.
  GitHub Actions can then sort reports automatically (labels by brand /
  model, link to the SUPPORTED.md row).
  Reports feed docs/SUPPORTED.md: a confirmed model moves to "Confirmed
  models", its ? marks to ✓ / ✗.
- **The name:** check "Room Tiles" is free (USPTO search, app stores,
  GitHub) before going public - renaming after release breaks every install;
  file the trademark (intent to use, class 9) shortly before going public.
- **Marketplace install - tried 2026-11-18 with 0.1.0b1 (works):** "Add
  from link", Install, restart: the zip's integration + dashboard ran (not a
  developer build), and within 3 minutes of the restart all four test panels
  had installed the zip's firmware and their Wi-Fi chips were on 2.12.13.
  Found on the way: with only a pre-release out, the Marketplace installs
  the `main` branch (404: no zip there); after the release was marked
  stable, it still used `main` until "Refresh information" on the repo's
  page (a repo object made before the release keeps its old ref);
  `hide_default_branch` is read from hacs.json but not acted on (2026.11.2
  source); Room Tiles' own restart repair now steps aside for the
  Marketplace's (`restart_required_<repo>_<version>`), as it did for
  HACS's. Next: the UPDATE path (the next stable release through the
  update entity). Found with 0.1.0: the Marketplace takes the FIRST stable
  release in GitHub's release list as the newest, and GitHub listed
  v0.1.0b1 ahead of v0.1.0 - so 0.1.0 wasn't offered until b1 was marked a
  pre-release. Keep the release list to stable versions in order.
- **Before inviting anyone: the Marketplace's main Install button must
  work.** With only a pre-release out, it installed from the `main` branch,
  which has no zip (404 - 0.1.0b1 test, 2026-11-18). `hacs.json`
  `hide_default_branch` is set (HACS's option - the Marketplace doesn't act
  on it), and a stable release must be out before anyone is invited.
  **Releases are stable only - no GitHub pre-releases** (2026-11-18: the
  Marketplace only offers them behind a per-repo switch, a barrier for
  people trying it); "early" shows in the 0.x version instead. Retest: a
  fresh "Add from link" + Install with nothing chosen.
- **Going public - the repo is public since 2026-11-18** (a fresh one: one
  clean first commit; the history before it stays private). Done: the main
  branch rule (`tools/github/protect-main.sh`), the report labels, the
  Marketplace install, the install page on GitHub Pages, firmware CI per
  board. `tools/github/protect-main.sh <owner>/<repo>`: main
  changes only through pull requests the code owner approved; outside
  contributors' workflows wait for approval (both need a public repo).

## 3. Round panel

Its board can be tried again (2026-11-18). Its code first compiled in the
0.1.0b1 release run (`room-tiles-elecrow-s3-round-2.1.factory.bin`); its
first install is over USB (a new flash layout: no update from the old
firmware), then updates come like every other panel's.

**First install done 2026-11-18** through the browser install page (ESP Web
Tools, 0.1.0b1): flashed, language, Wi-Fi, added in HA. Found: the page
asks for the USB port again after flashing (the S3's own USB re-enumerates
for Improv); a board that ran ESPHome before is recognized by HA, which
offers Reconfigure on the old device - the panel then never connects (HA's
ESPHome update entity trips on the old dashboard config) until the old
device is deleted and the panel is Added fresh (both now in the README and
the install page). Tried after it (2026-11-18): a theme change ran out of
memory (the download buffer doubled to read the end - fixed for every
panel; the round panel's own theme packs added); its settings jumped back
to the top after a change and had no close (now the color picker's X,
same place); the strip forgot each room's place; the picture broke up
while a theme was saved (the wording pack was still mapped from flash, so
each erase stopped the screen's refill - now nothing of flash stays mapped
while a theme or a firmware is written) (all fixed; the X and the save fix
not yet on the panel). Next: try every screen on the hardware (strip, knob,
settings, color picker, idle clock), then an update.

A trimmed Room Tiles for the Elecrow CrowPanel 2.1" round display (ESP32-S3,
480x480, 8 MB PSRAM, 16 MB flash, CST826 touch, a rotary knob with a press).

- **The design:** the area's 10 tiles (its 5x2 layout) in one horizontal
  strip at today's 5x2 tile size (198 x 254: fits the circle - no new art,
  icon or font sizes; the same theme packs); one tile centered or two halves
  split down the middle, page dots; each room opens where it was left (kept
  on the panel, across restarts). Touch first; the knob: a turn = half a
  step, a press = tap the centered tile. Keeps themes, area switching (tap
  the area's name), settings, the color picker (round layout),
  "Connecting to Home Assistant…", When idle (starts on the digital clock
  after 30 s). Drops the map, the vacuum view and tile editing (edit on the
  dashboard).
- **Compiles (2026-11-15):** 2.0 MiB, 50.6% of its 4 MiB slot, no
  warnings.
- **Built, not flashed yet:** the board file
  (`boards/elecrow-s3-round-2.1.yaml`) and S3 flash layout;
  `room_tiles: layout: strip, map: false` (map off = a runtime switch, its
  code still built in); the strip with half-tile snapping and page dots;
  knob turn / press; the round area list and settings page; the round color
  picker; the configs validate.
- **Left:**
  - Board bring-up: screen init, touch, knob. Start with a bare test build -
    this display had a black-screen crash in an older project.
  - The firmware builds without the map / vacuum code (one switch).
  - Change Wi-Fi in its settings page.
  - The integration knows a round panel: 5x2 only, no map data, idle
    settings on the dashboard, Help text to match.
  - Installed and updated like the other panels.

## 4. Panels - smaller items

- Map Help: say that maps are edited in the dashboard (Home Assistant's
  Room Tiles page), not on the panel.
- Map top bar: picking another map changes the title's width, so the Map /
  Layer pills shift under the finger. Anchor them: a fixed start for the
  groups (room for the longest title, or the groups at a fixed position with
  the title cut to fit) so a tap never moves the next pill.
- Measure what the 8-bit (I8) animations cost to draw.
- Offer ESPHome the one-line mipi_dsi change upstream (its refresh callback
  in IRAM - CONFIG_LCD_DSI_ISR_CACHE_SAFE, no blue flash while flash is
  written), then drop the copy in firmware/components/mipi_dsi.
- Keep in mind: 16-bit sprite sheets (faster drawing, ~3x size) if the asset
  area ever has room.

## 5. Dashboard - later

- **Map backup / restore**: in Map settings, "Back up this map" saves a
  snapshot (drawing, layers, markers) to the integration's backups; a list
  of them with Restore (and delete). Nothing shows on the map meanwhile -
  the safe way to try big changes. (Duplicate map exists for variants.)
- **Pool / Spa tile: its own controls dialog** (the tile's switch = pump /
  spa mode, its heater button = heater on / off already). For the rare
  settings: heat or chill, the "pump with heater" setting, spa mode on a
  shared system; a press elsewhere on the tile keeps opening the HA Card
  (the heater's thermostat dialog) like now.
- **Portrait phones: keep or turn the grid** - one setting for all areas
  (per device, like the other display settings), used only in portrait:
  *Keep* = the panel's layout as it is (5x2 / 6x3: two columns on screen,
  scroll sideways - today's behavior); *Turn* = columns become rows (2x5 /
  3x6), scrolling down. The tiles keep their slots - only the drawing turns
  (slot at column c, row r is shown at column r, row c), so the panels and
  landscape are unaffected. Tile editing (tap / long-press to move), the
  scroll position dots and the peek of the next column / row follow the
  turned grid.
- **Compact tiles on the web** (nice to have): in the browser, text / SVG
  are always sharp and sprites scale smoothly, so it's only about
  legibility and layout. Switch on the tile's REAL rendered size, not on
  5x2 vs 6x3 (web resolution varies per device: a 6x3 tile on a big monitor
  can beat a 5x2 tile on a phone): below a threshold width the tile gets the
  panels' small-tile rules - text a step larger relative to the tile,
  roller / swatch pinned top-right with labels clear of the icon, appliance
  pictures + text fitted.
- **Webhooks and NFC tags** - run a Room Tiles action from outside the
  dashboard. Actions: vacuum (add an area to a robot's queue, start unless
  told not to), tile (toggle / on / off / open / close / stop an entity
  Room Tiles knows - scenes and scripts too) and area lights (on / off /
  toggle). Only entities Room Tiles knows (the panels' `check_action`).
  Two ways in:
  - **Webhook links - home network only, always** (no remote option): for
    anyone on the Wi-Fi, no HA app needed. URL
    `http://<HA>:8123/api/room_tiles/hook/<key>?do=...` - the key in the
    path, never the query. Keys: made by Room Tiles (random, 256-bit),
    named, revoke (kept, so the log says "revoked") / delete, last used +
    count. Remote calls (Nabu Casa included) are refused and logged. The
    reply is a short "Done" page for browsers (no Safari download prompt),
    JSON otherwise.
  - **HA tags** - the secure / remote way: Room Tiles listens to
    `tag_scanned` (HA app tags, ESPHome NFC readers, an iPhone Shortcut
    firing the event through the HA app) and runs the action bound to
    that tag. The caller is signed in to HA; nothing secret on the tag.
    Build both either way (if the iPhone route needs a tap, iPhones use
    the webhook links at home).
  - **Dashboard page** (Settings › Webhooks): keys, tags (pick an HA tag
    or type its ID -> an action), a link builder (key + action + target ->
    the local URL, copy + QR), and a log: time, key / tag + which phone or
    reader, action + target, result (done / unknown key / revoked / remote
    refused / not allowed / bad link / failed + HA's error), source IP,
    caller app; filter by key / tag, action, result, date; search; clear.
    Results stored as codes (each viewer's own language). Last 1,000
    entries or 90 days, its own store.
  - Rate limit per key / tag; a bad key counts toward HA's IP ban. Calls
    wait up to ~10 s for HA, so "done" means done.
  - Order: integration (keys, endpoint, tag listener, actions, log,
    websocket) + tests -> dashboard page + tests -> DESIGN.md / UI.md.
- **Device profiles** - only if there's demand (they make setup harder to
  follow): an on / off entity or a standard-phases sensor as hand-added
  fallbacks; a preset `door_states` for a brand that reports its door
  inside its status.
- A way to see a tile's full name (long-press / tooltip - not designed yet).
- Maybe: a new map starts with a square per HA area on its floor.
- Shared C++ / TypeScript test vectors (tile behavior).

## 6. After the first release

- **Your own themes** (docs/THEMES.md, format 1 - written 2026-11-17; the
  built-in themes are converted and build byte-identical packs from it).
  Left: the integration finds themes in `/config/room_tiles_themes/<id>/`
  (a folder or its zip), checks them (format, sizes, JSON, the pack limit -
  the checker is written: assets/theme_format.py read() / check_pictures(),
  tested in tests/test_theme_format.py, run by every pack build),
  builds their panel packs and web sets itself - one packager (DESIGN.md
  "One packager, two outputs"; the dashboard loads only its output, never a
  theme's raw files), assets/build_panel.py + build_web.py's pipeline moved
  into the integration, the default art filling gaps, cached; libimagequant
  is in this container's Pillow - check HA's), sources at 2x / 4x scaled
  down, an embedded colour profile converted to sRGB, `"off": "gray"`
  generated there; the dashboard gets the themes from the integration at
  run time (today: baked in at build); the panels already take theme names
  from the payload (theme_names, 2026-11-17). Later: "Add theme from link" (a GitHub
  release zip).

- **Wi-Fi set up on the panel** (no phone): shown while it has no saved
  network - a list of networks (strongest first, a lock on secured ones),
  tap one, type the password on an on-screen keyboard (keys sized for the
  7"; letters, numbers, symbols), Connect (ESPHome `wifi.configure`). Mesh
  routers often turn away the first try after a restart ("Authentication
  Failed", then fine), so say "wrong password" only after a few tries.
  "Set up with your phone instead" stays, the hotspot running meanwhile.
