# Room Tiles - still to do

Open work in priority order. Decisions and rules live in DESIGN.md / UI.md;
this is only the list. Remove an item when it's built.

Public since 2026-11-18. Section 1's rest waits on beta testers or the
first users.

## 1. Installing and updating panels

Goal: nobody compiles anything. A first install is a browser and a USB
cable; after that, panels update with Room Tiles itself.

**First install (what the user does):**
1. Open the Room Tiles install page in Chrome / Edge, pick the board (photos:
   7" V1.0, 7" V1.2, 10.1" ...), plug in USB-C, Install (~2 min).
2. Wi-Fi: the install page asks for the network right after flashing
   (Improv over USB); on the 7" / 10.1", right on the panel's screen; or
   the panel's hotspot, from a phone.
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
  there - no USB needed); the round one untested (section 3).
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
- **G. The Wi-Fi chip's firmware** (DESIGN.md "The Wi-Fi chip"): every
  image carries ESPHome's `network_adapter` 2.12.13 and brings an older
  chip up to it once, at startup - all the maintainer's panels are on
  2.12.13 (2026-11-18). Left:
  - A board straight from the box (2.3.0 / 2.12.3): never tried - verify
    on the next new board (or users report it). The 2.3.0 path (no
    "activate", restart after 25 s) rests on the 2026-10-12 V1.0 update.
  - Keep in step: an ESPHome upgrade that moves ESP-Hosted needs the
    matching image (firmware/wifi_chip/README.md).

## 2. Early users

- **Map pictures for colorful theme packs**: markers, names and room names
  are 4-bit sprites (16 colors each) - fine for one color per marker, but a
  theme pack with multi-colored icons or gradients would band. Measure
  8-bit indexed (256 colors) for marker faces: memory (~3.5 KB a face vs
  ~1.4 KB; a map's 15-25 combinations may spill to PSRAM) and draw time.
  Likely answer: the depth per picture, with a tolerance - 4-bit when 16
  colors cover the picture closely enough (e.g. 98% of its pixels exact,
  the rest near), else 8-bit; the threshold tuned by eye on a colorful pack.
- **Animations per appliance type** (next theme format): a theme has one
  set of appliance animations, so a dishwasher drying plays the dryer's
  (Holly & Ivy: the fireplace hides the plate). Let a theme add its own
  for a type (e.g. `dishwasher/sun_dry.png`), falling back to the shared
  one - dashboard and panel packs alike.
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
- **Marketplace:** releases are stable only - no GitHub pre-releases (the
  Marketplace offers them only behind a per-repo switch, and takes the
  FIRST stable release in GitHub's list as the newest - keep the list in
  order). Retest once: a fresh "Add from link" + Install with nothing
  chosen picks the latest stable. Later: ask to be listed in the
  Marketplace's main catalog (found without a link).
- **Panel screenshots for the landing page:** the 7" ones are up ("On the
  touch panels", from the demo home on a panel - DESIGN.md "The demo home
  on a panel"); maybe later: the round panel's.
## 3. Round panel

Built and tried on the hardware (every screen: the strip, the knob,
settings, the color picker, the idle clock; the dashboard's round-panel
settings). Nothing left.

- **Not planned:** a firmware build without the map code - it would save
  ~74 KB of the round image's 2.0 MB (its slot 51% full) and no RAM (the
  map is off at run time); revisit only if the image nears its slot.

## 4. Panels - smaller items

- Measure what the 8-bit (I8) animations cost to draw.
- Offer ESPHome the one-line mipi_dsi change upstream (its refresh callback
  in IRAM - CONFIG_LCD_DSI_ISR_CACHE_SAFE, no blue flash while flash is
  written), then drop the copy in firmware/components/mipi_dsi.
- Keep in mind: 16-bit sprite sheets (faster drawing, ~3x size) if the asset
  area ever has room.

## 5. Dashboard - later

- **Pool / Spa tile: its own controls dialog** (the tile's switch = pump /
  spa mode, its heater button = heater on / off already). For the rare
  settings: heat or chill, the "pump with heater" setting, spa mode on a
  shared system; a press elsewhere on the tile keeps opening the HA Card
  (the heater's thermostat dialog) like now.
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

- **Wi-Fi set up on the panel, the round panel:** a knob letter wheel for
  the password (the 7" / 10.1" have the on-screen keyboard) - only if people
  ask; the phone way works there.

- **Maybe: an "add this panel" step.** Today any ESPHome device that
  reports itself as a Room Tiles panel is taken as one. A one-time
  confirmation in Room Tiles would close that, at the cost of an extra
  setup step - left out for now to keep setup simple.
