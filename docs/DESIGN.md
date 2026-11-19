# Room Tiles - design decisions and rules

UI rules (controls, dialogs, look): [UI.md](UI.md).

The decisions behind Room Tiles and the rules contributors must keep. Change
this file when a decision changes.

## What Room Tiles is

Room-by-room control tiles and house maps for Home Assistant, in two clients
of one data model:

- the **Room Tiles dashboard** (sidebar panel + card, shipped inside the
  integration) for phones, tablets, computers and existing HA touchscreens;
- **touch-panel firmware** (wall or desk) (ESPHome, Elecrow CrowPanel Advanced ESP32-P4 boards,
  all 1024x600: 7" V1.0/V1.1/V1.2, 9", 10.1").

The integration (`custom_components/room_tiles`) owns all data; both clients
read it live and change it through the same actions.

## Data

- **Areas are Home Assistant areas.** A Room Tiles area's id is the HA area id;
  its name and floor follow HA (renames, moves, deletions). There are no
  Room-Tiles-only areas. Setup ticks which HA areas appear; unticked areas stay
  hidden with their tiles kept. New HA areas arrive hidden unless "include new
  areas automatically" is on.
- **Two grids per area:** 5x2 (10 tiles) and 6x3 (18 tiles). A simpler view
  for guests is simply a well-chosen 5x2.
- **A map always exists.** Without a drawn plan the integration generates one
  map per HA floor with a square per area. Maps are data (walls, windows,
  openings, filled shapes, zones linked to areas, links between maps), never
  compiled into firmware. Several maps: floors, a yard, anything.
- **Markers belong to a map and one of its LAYERS.** A layer is a group of
  markers with a zoom range: it shows from its start (`min_zoom`) to its end
  (`max_zoom`; none = on and on). Every layer whose range holds the zoom
  shows, so several show at once - e.g. "Main" always, "Rooms" adding detail
  from 3x, "Overview" (group markers) only up to 3x. A marker lives on ONE
  layer, so editing it never needs reconciling across layers. A new map has
  one layer; the map editor (Map settings) adds (up to 6) / renames /
  deletes them, the Layer Editor sets each one's range (Starts at / Ends at
  - part of its draft, saved with the markers). The Layer Editor changes
  only the edited layer; the other layers showing at that zoom are drawn
  faded and can't be touched. The map / layer row lights every layer
  showing; a layer button goes to where it starts.
- **The zoom number is marker spacing, not map-in-view.** Markers have a
  fixed on-screen size, so the zoom compares how big the map is drawn with
  how big it is when it just fits a panel's map area (1024 x 552 CSS px):
  1 = the whole map on a panel; a phone showing the whole map is well
  below 1, a big monitor above. The same zoom - and so the same layer -
  means the same spacing between markers on every screen. Sizes are CSS px
  (the browser's scaled pixels), never device pixels. On the panels it is
  simply "whole map = 1".
- **A marker is one placement** of an entity. An entity may have any number of
  markers - on several layers (each with its own position) and several times
  in one layer. **A marker always controls its own entity**: no tap groups or
  connector lines; a light group is simply placed as its own entity (e.g. a
  "Groups" layer for groups, another for the single fixtures).
- **Long press on a marker** = its tile plus a tile for every HA group it is
  in (directly or through another group), closest group first, in a row that
  scrolls sideways - pick what to set right there.
- **Short names.** Tiles and map markers show a short name of at most
  15 characters (and narrow enough for a 5x2 panel tile in Roboto 22 px);
  pickers and dialogs show the full HA name - for Room Tiles' own entities
  the name Room Tiles gave them (their `own_name` attribute). HA composes
  friendly names its own, instance-configurable way (e.g. the device's name
  in front; Room Tiles' tile sensors sit on their appliance's device), so
  they're never taken apart. Short names are suggested
  automatically (abbreviations, whole words, never cut mid-word) and anything
  shortened is flagged for review (an HA notification links to the Short
  names dialog when new ones come up; the Settings dot shows while any
  wait). Nothing breaks unreviewed - the suggestion is used. They can be changed at any
  time. Two entities may share a short name - the area or map position tells
  them apart. A tile may override its entity's short name.
- **Short-name editing UI (dashboard):** every row shows the full HA name
  (read-only) and the entity's area next to the editable short name, so the
  user always knows what a short name stands for. Reviewing happens only
  there (no HA Repairs form).
- **Area Lights** (the lights button of an area): by default every light in
  the HA area (its own area or its device's), minus what HA itself leaves out
  of area targeting (hidden, disabled, settings entities) and minus the area's
  exclude list - worked out live from HA's registries, so new / moved /
  deleted / renamed lights need no upkeep (exclusions of lights that left the
  area are dropped; renames are followed). Optional override: one entity
  (e.g. a light group); if it's deleted the area falls back and the user is
  told. Toggle = any on -> all off, else all on. Devices with a screen should
  mark their backlight as a settings entity so it's never included.
- **Entities deleted in HA** (the registry's explicit "removed" event) are
  removed everywhere in Room Tiles - tiles become empty, markers go from every
  layer, the catalog entry and area-lights references go - and a notification
  lists what was removed where.
- **Entities disabled in HA** keep all their Room Tiles data (tiles, markers,
  catalog entry, names): their tiles show empty and their markers are hidden
  while disabled; re-enabling brings everything back.
- **Entities merely missing** (no registry entry, integration not loaded yet...)
  are never removed: their tiles show "not found" and a Repairs notice lists
  them.
- **Brand-specific devices** (appliances, pool/spa): the tile reads a generic
  contract; per-brand presets map states to it. Unknown states fall back safely
  and the user is asked once.

## Derived sensors are Room Tiles' job (no template YAML)

The original panels depend on ~30 hand-written HA template sensors: per-unit
state / status / time left for dishwashers and laundry, combined
`*_tile` sensors, the pool / spa set (mode, active body's temperature,
heater, target, state, status, time to target) and the robot vacuum's alert
and tile. Room Tiles must do all of this itself, behind the scenes:

- **The rule: where HA has a good generic interface, use
  it; where it doesn't, Room Tiles makes its own.** Lights, locks, covers,
  fans, switches, thermostats... use HA's own entities and services directly
  (any brand already works). Brand-specific tiles read only Room Tiles' own
  sensors: laundry, dishwasher, vacuum, pool and spa tiles never read a
  brand's raw entities or call its services directly; each device type has
  one Room Tiles sensor set + action set (its contract), and a **device
  profile** per brand / setup maps the real hardware onto it. A setup process
  gets each user's actual hardware connected to those sensors. Supporting new
  hardware - e.g. a vacuum without the HA interface used today - means a new
  profile; tiles, maps and the queue stay unchanged.
- **Device profiles, not templates.** Room Tiles recognises supported devices
  (washer, dryer, dishwasher - including dual-drawer -, robot vacuum,
  pool / spa controller) through the brand presets and creates what the tiles
  need as its own entities / derived data, from the device's raw entities.
- **At install:** setup lists the recognised devices ("Found: GE dishwasher
  (2 drawers), washer + dryer, Matic vacuum, iAquaLink pool / spa - add
  them?"); a tick creates their tiles' data. Unrecognised devices can be set up
  by hand from their entities (the generic "standard phases" / power-plug
  fallbacks).
- **Any number of each device type**: two pools, three
  dishwashers, several washers / dryers / vacuums - nothing assumes one.
  Every profile has its own id, sensor and tiles; setup names several
  of a kind after their HA devices ("Kitchen Dishwasher", "Bar
  Dishwasher"). A washer + dryer pair up automatically only when there's
  exactly one of each; otherwise each is its own tile and the user pairs
  them in the Appliances page.
- **A tile shows one or two appliances**: two = top /
  bottom halves (a double DishDrawer, washer + dryer); one = exactly a
  half's layout (same size), centred vertically.
- **Names may repeat**: tiles / appliances aren't forced
  to unique names (HA itself allows duplicates, and most tiles are HA
  entities). The appliance dialog notes a duplicate ("This is not a
  problem, but letting you know"); the tile / entity pickers show
  same-named entries with "<integration> · <entity id>" so they can always
  be told apart. Renaming an appliance renames its tile-picker entry.
- **An appliance's tile stands for the appliance.** Once Room Tiles finds an
  appliance or a robot vacuum (set up, waiting, or ignored), the tile and
  marker pickers offer neither the entities its tile is made of nor the
  other entities on its device - its own controls (Sabbath mode, child
  lock, power...). Lights are the exception: placed like any light. Pools
  and spas aren't covered: their pumps, lights and spa mode are real
  controls. Full control of an appliance, if added, belongs in an
  appliance dialog.
- **The appliance dialog** (Add and the pencil both open it): ONE dialog,
  the TILE CHOICE FIRST as cards - two on a tile: "One tile" / "Separate
  tiles"; one alone: "Its own tile" / "Share with <each other single one>".
  Picking a card never closes or replaces the dialog: it only changes what
  is shown below (one settings block, or one per resulting tile). Nothing
  happens until Save / Add, which does the split / combine and then stores
  every tile's settings; Cancel drops it all. Washer + dryer get "switch
  over until the dryer starts" either way: on one tile the rule is
  `unit:<dryer unit>`, on separate tiles `appliance:<dryer's appliance>`
  (the dryer's own sensor starting empties the washer's). A washer's
  default comes from whether there's a dryer: one around -> Switch Over
  until it starts; none -> Idle (straight back). Setup, Add by hand and
  Separate tiles all follow it (appliance_detect.washer_default). UI rule:
  buttons inside a settings dialog never close it or turn it into
  something else.
- **Setup always says what won't work**: hardware that
  isn't supported, and supported hardware with features missing (e.g. a
  vacuum without room cleaning), get a plain note at setup - never a silent
  gap. Unsupported features are disabled / hidden, not left as dead
  controls. Wording and detail to be tuned when setup is built.
- **Afterwards, automatically:** device-registry events drive it - a newly
  added supported device is offered (notification / dashboard prompt, not
  silently added); once set up, its tile joins its area's boards the user
  never changed (worked out again, so it sits where its kind goes) - a
  board the user changed is theirs: the dashboard asks and opens the tile
  editor there. Auto configure (tile editor) makes boards automatic again: this board
  only, both boards for the area, or all boards (a second confirm).
  A removed device's derived entities are removed and its
  tiles / markers listed in the "missing entities" Repairs notice; a
  replaced device can be re-linked to the existing tiles.
- **Settings:** a dashboard "Devices" page per profile: which raw entities
  feed it, unit names (Upper / Lower, Washer / Dryer), pairing two appliances
  into one tile, the brand state mapping (with the one-tap answers for unknown
  states), status wording language.
- **Clearing "done" (unload me):** a finished appliance stays "done" (the
  check animation - e.g. "clothes ready, take them out") until it is emptied.
  What clears it, in order of preference, set per appliance in its profile:
  1. the appliance's own door sensor, if its integration exposes one;
  2. a sensor the user picks (e.g. a separate contact sensor on the dryer
     door);
  3. last resort: tapping the animation on the tile resets it.
  The tap works in every case, as a manual override.
  **Only KNOWN signals empty a finished unit**: never "any
  status change" and never unavailable / unknown (dropouts). Checked on real
  data: LG washers / dryers go `end` -> `power_off` 30-55 s after EVERY cycle
  (auto power-off), and F&P drawers' cycle state never changes when a drawer
  opens - a status change says nothing reliable about unloading. A brand
  that reports its door INSIDE its status gets `door_states` in its preset
  (the exact raw states meaning "door opened"), treated like a door sensor:
  "Its door opening", ticked by default, can be unticked. Not needed by any
  current brand - add it with the first brand that does.
- **Pool / spa profile** (brands: Jandy iAquaLink, Pentair,
  Hayward; others by hand from their entities). Setup has to know the
  **equipment layout**, detected where the integration shows it and always
  confirmed by the user:
  - **Shared**: the spa sits on the pool, one pump and one
    heater switch between them - the system is in pool mode OR spa mode, and
    only the active body's temperature reads.
  - **Separate**: each body has its own pump / heater and both can run at
    once.
  - Pool only / spa only (one body).

  Room Tiles creates **per-body derived sensors** (pool, spa): water
  temperature (with "last read" while that body isn't circulating), heater
  state, target, state + status text, time to target - plus, for a shared
  system, the mode (pool / spa / switching / offline). The tiles read only
  these, never the brand's raw entities, so the same tiles work for every
  brand and layout:
  - **Pool tile** and **Spa tile** - one body each: separate and
    one-body systems.
  - **Pool / Spa tile** (the panels' combined one) - a shared system's only
    water tile: it follows whichever body is active (one pump and heater,
    so separate Pool and Spa tiles would only repeat it).
  - Room Tiles' own switch and button - the tiles never use a brand's raw
    switches, these route to them:
    - **Spa Mode** (shared only, `switch.room_tiles_<id>_spa_mode`): on =
      spa mode; it reads the system's spa-mode switch and acts like the
      spa going on / off below (its heater follows when the setting says so).
    - **Heater button** (every water tile with a heater = with the roller):
      bottom right under the roller, a flame (heat) or snowflake (chill),
      lit while on, gray while off; one tap on / off, no confirm (a heater
      is like a light; the controller keeps its limits). Off -> on picks the
      mode it was last in (`heater_next`; heat at first, cool for a
      chiller that can't heat); heat vs chill itself is changed on the HA
      Card. The combined tile's acts on the active body. Turning it on
      starts the body's pump first per "pump with the heater". No Heater
      switch tiles (they made a shared system three tiles).
    - A brand's own heater on / off switches (Jandy `_pool_heater` /
      `_spa_heater`) are recorded as the body's `heater_switch` and kept off
      the tiles, like the other equipment entities.
  - Icons (bottom left, like every tile): `icon_pool` / `icon_spa`; the
    combined tile's follows the mode.
  - Controls (set target, heater on / off, spa on / off) go through the
    profile's actions, which per brand / layout call the right raw entities.
  - A heater only runs with water flowing through it, so it's tied to ONE
    pump; some controllers (Jandy...) start the pump themselves when the
    heater goes on, some don't. Each body's heater has a
    setting "turning its heater on also turns the pump on" (default on):
    when Room Tiles turns a heater on (its action, the Spa tile's switch) it
    turns that body's pump on first - only if it was off; turning a heater
    off never stops the pump, EXCEPT the spa going off stops a pump that the
    spa going on started (remembered while HA runs). HA's own thermostat dialog bypasses it (Room Tiles never starts
    pumps on seeing a heater go on - that would catch controller schedules).
    While the pump is off with the heater on it says "Heater on - waiting
    for the pump". One heater can't serve two separate bodies.
  - Spa tile switch / Spa Mode = spa on / off (shared: spa mode); its
    heater follows when the setting "turning the spa on also turns its
    heater on" is on (default); a spa without a pump switches its heater.
    Pool tile and the combined tile: switch = the pool / active body on /
    off (pump, pool mode) - NEVER a heater (turning the pump on must not
    start heating the pool by surprise; heated pools run the heater on a
    schedule); no pump to switch = no switch. Roller = target only (never
    turns a heater on). The tile's details open the body's heater (HA's
    thermostat dialog). A body not circulating shows its last reading,
    dimmed.
- **docs/SUPPORTED.md is the public list** of supported brands / models
  (status verified / beta / planned / not supported, tested models, quirks)
  with a FEATURES-BY-MODEL table per device type (works / partly / not
  possible / unconfirmed). BETA = supported from what can be read online
  (integration source, docs, owner reports) but no Room Tiles user with that
  model has confirmed it; presets carry `confirmed_models` and setup notes
  "beta" for any other model. A model leaves beta ONLY through the formal
  report procedure (TODO.md "Formal procedure to clear a beta flag"): an
  in-app report with evidence -> a replay test in CI + feature rows checked
  -> confirmed_models / SUPPORTED.md updated in a release.
  Every preset, finder or capability change updates it in the same commit.
- **Unknown raw states are asked once**: every preset lists the
  states it knows (from the integration's source); anything else counts as
  running and is asked on the Appliances page (Running / Paused / Not
  running / Error; a Repairs notice; the Appliances dot). The answer is the
  unit's override. Users can volunteer their answers back (TODO "Report
  unknown states back") so released presets learn them.
- **Wording stays in one place** (the integration, translated), never in a
  display - same rule as the original template sensors. Token substitution
  from ONE JSON FILE PER LANGUAGE (`custom_components/room_tiles/wording/
  <lang>.json`): `strings` (token -> text with {placeholders}, e.g.
  `pool.heating_to`) - display text only.
  Code only uses tokens (`wording.t()`); English (`en.json`) is the full
  set, a missing token falls back to it. Adding a language = adding a file;
  changing wording = editing it - no code. The local way of saying a thing,
  not word for word ("Switch Over" = "into the dryer"). The brands' own
  wording ("Main Wash") is shown as it comes. Tests check every file (valid,
  known tokens, the same placeholders as English).
  The SAME goes for the dashboard: every piece of UI text - labels, tooltips,
  hints, help, aria-labels - is translated through a token table, nothing
  shown to a person is left in code (docs/TODO.md "Localize the whole
  dashboard").
- **Every display shows its own language**, whatever HA's language is. A
  panel and a dashboard device each pick a language; the sensors' text
  (`tile`, `status`...) is in HA's language, so each sensor also gives the
  same as WORDS in no language (`tile_words`, `status_word`, a unit's
  `status_word` / `time_word`: JSON text, since HA hands attributes to the
  panels as text) - tokens with their values ("pool.short.heating" + 49
  minutes). The dashboard (frontend/src/words.ts) and the panels
  (firmware words.cpp, filled in by the state hub) render them from the same
  wording files; the panels' string packs carry the wording too. The text
  stays for older panels and other cards.
- **Logic mirrored between the dashboard and the panels is marked** on both
  sides with a `MIRRORED:` comment naming the other side - a change to one
  must be made to the other (and `grep -rn MIRRORED` lists them all).
- Existing hand-made sensors keep working: a tile can still point at any sensor
  whose `tile` attribute follows the documented contract (the escape hatch).

## Short names are shortened per language

The short names THEMSELVES are per installation (Room Tiles' data, one per
entity / area, editable) and never change with the language. Only the rules
for SUGGESTING one - once, from the HA name, written in the owner's
language - are per language: `shortening/<lang>.json` (separate from the
display wording; abbreviations, whether dropping vowels stays readable),
chosen by HA's language; a language without a file gets the generic rules
(whole words dropped from the end, then trimming). English: its
abbreviations, then the longest words lose their vowels ("Garage" -> "Grg") -
kept only if that saves a word, otherwise words stay whole - then words
dropped from the end. Anything shortened is flagged for review.

## Privacy: what reports send

Anything Room Tiles helps send back (model reports, bug reports, unknown
states, recorded cycles, logs) follows one rule: **no personal data, and
nothing that ties it back to the user or their home.**

- **Allowed:** brand, model number, integration + version, Room Tiles + HA
  versions, the preset, raw device states, the user's own answers, feature
  checklists, durations *relative* to the start of a recording.
- **Never:** names (people, the home, areas, entities - user-typed names can
  hold anything), entity ids (they're often named after people / rooms - they
  become role placeholders: `status`, `door`, `time_left`, `pool_temp`...),
  serial numbers and MAC addresses (they hide in unique ids and entity ids,
  e.g. a dishwasher's serial), IP addresses, host names, URLs, emails,
  account ids, tokens, locations / coordinates, wall-clock timestamps (they
  reveal routines - only relative times), free text from HA.
- **Logs and recordings are scrubbed** before they're shown to the user:
  an ALLOW-list (only the fields above survive; anything unrecognised is
  dropped, never "probably fine") with its own tests, run on everything sent
  (`report.py` scrub(): the report layout REPORT, each value typed, every
  string checked against addresses / ids / serials / times / the home's own
  words from `secrets_from_hass`; brand, model and version fields come from
  the device, so the home's words don't touch them - a device the user
  named "John's Bosch" still reports "Bosch"). **Times become deltas:**
  every full timestamp in a report (a date with a time, epoch seconds or
  milliseconds) becomes its distance from the report's earliest - a
  recording's `t` in seconds, any other value as `+<seconds>s`; the earliest
  shows as 0, its date and time are never sent. A clock time with no date
  ("1:05 pm") can't be placed: dropped. Logs aren't in the layout
  yet: free text, so they need their own form (codes, not messages) first.
- **The user sees it all first:** before anything is sent, the exact payload
  is shown with a plain statement of what's in it and what isn't ("No names,
  serial numbers, addresses or times of day - only these model details and
  states"). Nothing is sent without the user submitting it.
- **One report = one device** (an appliance, for now), started from that
  device; never other devices, the rooms, the map or settings. The flow
  (`<rt-report>`, frontend/src/report.ts), nothing collected before step 3:
  1. **"Send a report?"** - what it is, a public GitHub issue from the
     user's own account. Yes / Not now.
  2. **"Do you have a GitHub account?"** - asked BEFORE any work, so nobody
     reaches the end without one. Yes, continue (remembered in this browser)
     / No, how do I get one? (free: github.com/signup) / Not now.
  3. **"Check before sending"** - `room_tiles/report_preview` (websocket.py)
     scrubs the draft with this home's own words and adds the versions: the
     device it's about (its name here - shown, never sent), what the report
     holds (summary), "The report never holds names, addresses, serial
     numbers or times of day", the exact payload on request; **Open GitHub**
     (not "Send": nothing is sent yet) opens a new issue with the report
     filled in - the user reviews, edits and submits it there. A report too
     long for an address is copied instead, GitHub opened with a note to
     paste it.
  A developer build has gear > Test report: a sample full of what must not
  go out (DEV_BUILD).
- **Unknown states** (the first report): after the user answers a state an
  appliance's preset didn't know (Appliances page), its card offers "Also
  tell Room Tiles about "<state>"?" - Tell Room Tiles / No thanks. The
  dashboard names only the appliance, unit, state and answer; HA builds the
  report from the device (report.py build_unknown_state: brand, model,
  versions, the integration and its version, the kind and preset, the
  status sensor's own list of states, the answer as running / paused / off
  / error), then scrubs it.
- **Report a problem** (cycles.py, frontend/src/problem.ts): every set-up
  appliance's, pool's and robot vacuum's card has "Report a problem", for
  wrong behavior even when every state is known. A "cycle" is a wash / dry
  / dishwasher cycle, a pool's pump run (its pump on, or the tile heating,
  cooling or switching) or a vacuum's clean (leaving the dock to docked).
  Its own first step, then the three above:
  - **"What went wrong?"** in the user's own words (up to 2000 characters),
    and with two units on one tile, which one.
  - **"When did it happen?"**: recent cycles from HA's history (the last 7
    days, `room_tiles/problem_cycles`: running by the device or by what
    Room Tiles showed, gaps under an hour merged; times shown to the user
    only); for a pool also "The last 6 / 24 hours" (a pool's problem isn't
    always one run); or **"Record the next cycle"** (pump run, clean; "...
    from now on" when one is running; the only choice when HA keeps no
    history for it).
  - **What it holds:** every entity of the devices behind what Room Tiles
    reads, not only those entities, by role - Room Tiles' own (`status`,
    `time_left`, `door`; `pump`, `spa_mode`, `pool_temp`, `spa_heater`...;
    `vacuum`, `error`), else the integration's own word for the entity (its
    translation key, else the name it gave it; never a name the user typed)
    - and what the tile showed (`room_tiles`, a pool's `room_tiles_pool` /
    `_spa`: an appliance unit's phase, status, minutes left, running; a
    pool's or vacuum's sensor less its names, ids and panel text), from 5
    minutes before the cycle to up to an hour after. A vacuum's room queue
    (HA area ids) goes as `area_1`, `area_2`... in the order they first
    show: the queue's moves stay readable, the rooms don't go out.
    Only changes are kept (an attribute row holds what changed); a number
    that keeps changing (a power reading) is thinned to one row per 30 s
    with its last value kept; at most 3000 rows (more: counted as
    `trimmed`). **HA stopping and starting** inside the cycle is in it
    (`events`): for a past cycle from the recorder's own log of its runs
    (a crash shows as a stop that wasn't clean); for a recording from its
    own marks (below).
  - **The user's words are theirs:** sent as written, outside the checked
    data (`description`; the issue quotes them above the JSON). The check
    step shows them with what looks like a name from the home, an address,
    an email, a phone number, a time of day or an id pointed out
    (`description_warnings`), each with Remove it - pointed out, never
    removed for them. "Apart from your words, the report never holds..."
  - **Recording the next cycle** is done by the integration, not the
    browser (`Recordings`, .storage/room_tiles.recordings): it waits for the
    cycle to start (keeping only the last 5 minutes before it; a week with
    no cycle: given up, "No cycle started"), then records until the cycle
    is over - an hour after both the device and Room Tiles say it stopped
    with nothing happening (a word changing, or a number moving a real
    step - a power reading jittering doesn't count), Stop on the card, or 12
    hours (a pool: 24 - its pump can run all day). HA stopping is marked when it stops; starting again is marked,
    with a stop that never got marked (a crash) placed at the last save;
    every entity is read again at the start, so changes made while HA was
    down show. The file is written at most once a minute (and when HA
    stops). When it's over, an HA notification links to the Appliances
    page, where the card says "The cycle is recorded" - Review and send /
    Delete. After Open GitHub it asks "Did the report go through?" - Yes,
    delete it / Keep it (Room Tiles can't tell whether the issue was
    submitted). One recording per appliance / pool / vacuum; one nobody
    sent is deleted after 30 days.
  - **Too long to paste** (GitHub takes about 65,000 characters in an
    issue): the report is saved as a file to attach to the issue instead.
- **Model reports** ("Report how it went"; model_report.py,
  frontend/src/model-report.ts): a set-up appliance, pool or robot vacuum
  that's beta - an appliance unit whose device model isn't in its preset's
  `confirmed_models`, a robot whose preset + model isn't in
  CONFIRMED_ROBOTS, a pool system whose preset + layout isn't in
  CONFIRMED_POOLS (its devices have no model) - says "Beta" on its card
  (the feed's `beta`: "<kind>:<id>" -> its beta units), with Report how it
  went. One step of its own, then the three above: which unit (the beta
  ones), **how it went** (works / partly / doesn't work - needed), **each
  feature** of its kind (SUPPORTED.md's "Features by model" rows:
  `model_report.FEATURES`, a laundry pair's washer + dryer on one tile, no
  spa row without a spa) as works / partly / doesn't work / not tried
  (not tried until answered), anything to add (the user's words, checked
  as above), and **a recent cycle's data** (pump run, clean, a pool's last
  hours - the most recent picked, or "Don't add any": the same rows as
  Report a problem). HA adds the brand, model, integration and versions.
  The issue: "Model report (partly works): <brand> <model>", label
  model-report.
- **Send feedback** (settings menu, frontend/src/feedback.ts): "What would
  you like to send?"
  - **Something's wrong with an appliance, pool or vacuum** (only when one
    is set up): which one, then its card's Report a problem - the cycle data
    is what finds those problems, so they're sent there.
  - **Report a bug:** "What happened?" and **"Where did it happen?"** - this
    dashboard (the browser goes with it: its name, major version, system and
    window size - never the whole user agent; and Room Tiles' own last 10
    uncaught errors and rejected promises on the page - frontend errors.ts,
    kept in memory only: each its message, how many seconds ago, where in
    Room Tiles' code (file:line:column); HA masks the message's URLs,
    emails, ids, times, entity ids and the home's own words -
    `_error_text` - rather than dropping it), an ESP32 panel (which one, if
    there are several - never its name; HA adds what it knows of it,
    report.py `panel_facts`: board, firmware label or build, hand-built,
    the Wi-Fi chip's version, online, ESPHome's reset reason, uptime, free
    heap / largest block / PSRAM, the asset area's size, and its restarts
    over the last 24 hours from the uptime's history - how long ago each,
    never when), an
    appliance, pool or vacuum (the same hand-over as above, the words kept,
    with why: its cycle data makes the problem much easier to find;
    "Send without the data" goes on as a bug), or somewhere else.
  - **Suggest an idea / Ask a question:** the user's words.
  Then the three steps above (kinds `bug` / `idea` / `question`): the words
  checked the same way, the versions added. No text guessing: the user
  picks where a problem belongs.
- **Download diagnostics** (HA's own, diagnostics.py): the setup's shape
  for an issue written by hand - versions and schemas, each area's settings
  and its boards' tile kinds, the maps' counts (walls, rooms, zones...),
  markers by domain, the catalog by kind, the appliances' / pools' /
  robots' presets and options, how many units are beta, the recordings'
  status, the panels (board, firmware, status, layout, theme, language).
  Never a name, an entity id or a device id: areas area_1..., floors
  floor_1..., appliance_1 / pool_1 / robot_1.
- **Issue forms** (`.github/ISSUE_TEMPLATE/`): each kind opens its own form
  (bug, idea, question, problem, model report, unknown state), which applies
  its label (bug, enhancement, question, problem, model-report,
  unknown-state); the report fills the form's `report` field. A feedback
  issue's title is the start of the user's words; a device report's is its
  brand and model.
- **The channel is said too, before sending:** reports go as a GitHub issue
  posted from the user's OWN GitHub account - so they need one and must be
  signed in (the prefilled issue: GitHub asks them to sign in; the in-app
  route: they sign in once, approving Room Tiles on GitHub). The issue is
  PUBLIC: anyone can see it together with their public GitHub profile
  (username, avatar, whatever they've made public). Their email isn't shown
  unless it's public on their profile, and the in-app sign-in asks only for
  permission to post issues - never email or private data. They can edit or
  delete the issue later (copies such as notification emails may remain).
  An anonymous route (a relay) is a later option.

## Nothing of Room Tiles' is exposed to voice assistants

Entities Room Tiles creates (tile sensors, the "<Area> Lights" lights) are
never exposed to Alexa, Google Assistant or Assist by Room Tiles: HA would
expose some new entities by default and the assistant announces a new
device. Room Tiles sets "not exposed" when it makes an entity, and only
where nothing was chosen - a user who exposes one keeps that (voice.py).

## Every entity starts cleanly

Every entity Room Tiles creates must come up without errors when HA starts
or restarts with stored data - not only when it's first added at runtime
(a pool sensor once failed only at start-up: the config entry isn't
"loaded" yet while its entities are added, so entities get what they need
at creation, never by looking the entry up). `tests/test_startup.py` loads
the latest storage fixture and checks every expected entity exists and
nothing logged an error. A NEW entity kind is added to that fixture and to
the test in the same change.

## Graphics and animations

- **One source of art for both clients.** The master artwork (196 px
  appliance sprite sheets, full-size PNGs) and the generator scripts live in
  `assets/`; they produce the panel firmware's LVGL arrays AND the dashboard's
  web files (WebP sprite sheets animated with CSS `steps()` at 16 fps, 2x/3x
  images, SVG where simpler). CI checks generated files are current.
- **The Room Tiles icon**: the dashboard's grid
  icon with each rounded outline in a tile colour (lights amber, blue,
  covers green, locks purple - the blue tile stays blue though switches are
  raspberry now). Master: `custom_components/room_tiles/themes/masters/brand/
  room_tiles_icon.svg`; `assets/tools/make_brand_icon.py` draws the same
  geometry into `custom_components/room_tiles/brand/` (HA 2026.3+ shows a
  custom integration's own icon.png / icon@2x.png / dark_ variants) and any
  size on demand (the panels' boot screen). The HA sidebar keeps an mdi icon
  (panels must use one).
- **Colours** come from one tokens file that generates both the firmware's
  `ui_theme.h` and the dashboard's CSS variables.
- **Art formats:** 256-colour palette, alpha on/off only (never blended),
  lossless WebP. Browsers decode every image to 32-bit RGBA anyway (no
  palettised or 16-bit textures on the web/GPU), so 8-bit sources only cut file
  size. Sprite animations move the sheet with CSS transform `steps()` on its
  own layer - compositor-only, no repaint per frame; only animations on screen
  are loaded.
- **Animations setting, per device** (dashboard ⚙): follow the device's
  reduced-motion setting (default) / always / never. When following a device
  that asks for reduced motion, a one-time notice says the animations are
  paused, where to change the device setting, and offers "Always animate";
  choosing "Follow device setting" again re-arms the notice.
- Panel controls (roller, switch + knob, colour picker) are rebuilt as web
  components with the same artwork. Animations honour "reduce motion".
- **Themes: Dark, Light, Christmas.** Dark and Christmas are drawn for a dark
  background, so the Room Tiles page stays dark even under a light HA theme. Each device
  picks its own (dashboard ⚙ → Theme, per browser; a panel's settings →
  Theme, its setting in HA). Components use only Room Tiles' own `--rt-*`
  CSS variables (from `frontend/src/theme.ts`; never hard-coded colours,
  never HA's theme variables - CI fails otherwise); images go through
  `assetUrl()`, which picks the theme's folder. **A theme is a folder in the
  public theme format** (docs/THEMES.md, format 1): `assets/themes/<id>/
  theme.json` (names per language, colours, `off`, `order`, `default`) + any
  pictures of its own - same names and sizes as the masters, which fill in
  the rest; colours it leaves out come from the default theme. Nothing lists
  the themes by hand: the builds read the folders (`assets/theme_format.py`,
  `frontend/theme-data.mjs`), the panel packs carry each theme's name
  ("theme.<id>" in the wording) and the integration reads
  `panel_packs/themes.json` (written with the packs).
- **Bundled and installed themes, one list** (docs/THEMES.md "Installed themes").
  Bundled themes ship in the release zip **prebuilt** (their panel packs,
  their web pictures, `themes.json`) - built by us, nothing to do on the HA
  box. Installed themes (`/config/room_tiles_themes/<id>/`, a folder or its
  zip) are **built by the integration** with the same pipeline
  (`custom_components/room_tiles/themes/`: fmt / panel / web, run in the
  executor, one theme at a time), once, and cached in HA's cache folder
  (`/config/.cache/room_tiles/themes/`, not in backups) by their files'
  fingerprint and the packager's (default art, panel format, quantizer).
  Looked for at setup, when a dashboard's settings menu opens
  (`room_tiles/themes_check`) and every 5 minutes - no folder, nothing
  runs. A changed theme stays in use as it was until its new build is
  ready; the default art (`custom_components/room_tiles/themes/masters`,
  shipped in the zip for this) fills their gaps, the default theme their
  colours. Rules:
  - **Ids never clash:** an installed theme is `user:<id>` everywhere it's
    stored or sent (panel / browser settings, pack names `theme-user:<id>`,
    its web pictures under `/room_tiles_themes/<build>/web/` - a new
    address with every build); a bundled one is its plain id. A user's `christmas` is a second theme, and a Room Tiles update
    adding a bundled theme never takes an installed one's place.
  - **The default is always bundled** (`default` in an installed
    theme.json is ignored): a missing or broken installed theme falls back
    to it, with a Repairs notice naming the theme.
  - **Lists:** bundled first (their `order`), then installed (their
    `order`, then name); names come from each theme.json in the device's
    language - for installed themes the panels get them in the payload.
  - **Format:** one format for both. A newer `format` than this release
    reads is skipped with a notice; older formats are read or converted.
  - **One packager, two outputs:** from a theme folder it makes, in one
    pass, the panel pack and the web set (pictures resized from 2x / 4x,
    sRGB, gaps filled from the default art, checked; the animations as the
    dashboard's WebP sheets - full colour: the palette is the panels' memory
    limit). **The dashboard only ever loads the packager's output** (its
    own served folder), never a theme folder's raw files. The bundled
    themes go through the same packager (at our build), so both reach the
    browser the same way. Colours with a meaning (heat / cool, the vacuum
  queue's states) are the same in every theme. Text on a coloured fill
  uses `onAccent` (a primary or selected button, a lit play button) or
  `onBright` (the amber Done button, tags) - never `text` / `page`, which
  swap places in the Light theme. Themes: Dark (the default), Light,
  Christmas.
- **A picture for "off" - any icon, any theme, optional.** A theme may draw
  an `<icon>_off.png` for any entity icon (and `bar_area_lights_off` for the
  Area Lights button); nothing lists them - the dashboard's build reads the
  theme folders (`frontend/off-art.mjs`) and the panels' firmware has a slot
  for every icon's off picture, so a theme pack adds one without a firmware
  update. Shown on the tile and the map marker (grayed there, like every off
  marker) whenever the entity isn't active by the markers' rule
  (`map.ts` markerActive / iconOn): a light, switch or fan off, a cover
  closed, a lock locked, a thermostat off, an appliance or pool idle, a
  vacuum docked, a scene not just tapped. Without one an icon looks the same
  in every state. Christmas draws its own (the reindeer's nose goes dark,
  the blind comes down, the garage shuts, the present closes). **Dark and
  Light generate theirs** (`assets/tools/make_off_icons.py`, run by the
  dashboard build): the icon in the markers' gray, inside a thin outline in
  the type's full colour, shrunk so on and off are the same size.
- **Off markers** keep their ring in the type's full colour (the face plain,
  the icon gray) - with the tiles' outline, gray = off and the colour = what
  it is, alike on the map and the board.
- **Buttons a theme draws itself** (`theme.ts` BUTTON_ART): the Area Lights
  and Map buttons, the Map tile's picture, the scene / script play button,
  the gear - pictures in `assets/themes/<theme>/ui/` (`bar_*`, `tile_map`,
  `run_gift`, `icon_settings`); the panels and the dashboard both use them
  when the theme has them, else the icon glyphs (the panels' gear is always
  a picture). Controls (close, back, zoom, the queue's play / pause) and
  glyphs with a meaning (the heater's flame / snowflake) stay glyphs.
- **The Room Tiles icon** (the panels' top bars, far left): a theme may draw
  its own as `ui/brand_bar.png`, 48 x 48 - the logo still easy to make
  out: the icon's four squares in the middle (same size, place and colors);
  the theme's art goes around, behind and may go over them (the Christmas
  one hangs in a wreath), covering at most 40% of each square.
  `build_panel.py` refuses one that hides more. Panels
  only for now; without one, the icon built into the firmware.
- **Licence of the artwork:** all of it is AI-generated; it is published as
  CC0 (free to use, no conditions).

## Panel firmware

The ESP32 panels (on a wall or a desk) run Room Tiles firmware (ESPHome + LVGL, `firmware/`). They
show and use what the integration holds; nothing about a house is compiled in.

- **Flash layout (16 MB, frozen 2026-11-14):** two firmware slots (5 MiB
  each, so an over-the-air update can always fall back), one **asset area**
  (5.8 MiB: the theme up to 5.56 MiB - `build_panel.py` refuses a bigger
  one - and the wording in its last 256 KiB; that split is the firmware's,
  so an update may move it), 64 KiB of settings (NVS) and 64 KiB for a crash
  report. Changing the layout needs one USB flash per panel; updates are
  over the air after that. Firmware room was put first: a firmware that
  outgrows its slot can't be updated at all, a theme that outgrows its
  space only has to draw less. Measured 2026-11-14: firmware 2.0 MiB
  (3.2 MiB with the Wi-Fi chip's image), biggest theme 2.6 MiB.
- **Art is downloaded, not compiled.** The firmware has a fixed slot per
  image; the integration serves a **theme pack** (every image already in
  the display's own format, plus the theme's colours) and the panel stores
  ONE theme in its asset area, drawn straight from flash (no decoding, no
  working memory). A theme change or new art in an update = a download,
  never a reflash. While a pack downloads, or if one is broken, tiles draw
  in plain colours without art and the panel retries. The **round panel** gets
  each theme's round cut (`theme-<theme>-round`, assets/build_panel.py
  ROUND_SKIP: no 6x3 sizes, map markers, tile picker icons or large clock -
  about 60% of the full pack); the integration knows a round panel by the
  board it reports. A download is held in PSRAM at exactly its length (the
  round panel's 8 MB has no room for a doubled buffer).
- **Image formats:** sprite sheets 8-bit palette (I8; never scaled or
  rotated on the panel - one image per size), icons 16-bit with alpha
  (RGB565A8). 16-bit sprite sheets render faster but are about three times
  the size - possible later if the firmware slots can shrink.
- **Wording is downloaded too:** the panel's string table for its language
  (the same tables and keys as the dashboard, plus panel-only keys) is stored
  in the asset area. A wording fix or a new language = a download.
- **Fonts are compiled in** (Roboto at the panel's sizes) with Latin-1
  Supplement + Latin Extended-A and the usual punctuation - every language
  Room Tiles has, and accented names in any language. Other scripts (Greek,
  Cyrillic, CJK) would need runtime fonts (LVGL's TrueType renderer) - later.
- **Theme and language are per panel**, defaulting to the house theme and
  HA's language. They can be changed on the panel (its settings) or in the
  dashboard; both write the same setting in HA, so they always agree.
- **Getting the data:** the integration publishes a small revision per
  panel (pushed over the ESPHome API, which the panel already holds open);
  when it changes, the panel fetches its payload (JSON, schema-versioned)
  over HTTP from the integration and swaps it in. Theme packs and string
  tables come the same way. A released install gets its packs with the
  integration (an update restarts HA anyway; HA's Reload of the integration
  also reloads them). In a developer build, packs rebuilt in the source
  are served live: their files are checked every
  10 s, a new set loads once they've stopped changing, and the revision
  moves only when a pack's content hash changed (the update watch skips
  `panel_packs/`). Entity states stay on the ESPHome API's state
  subscriptions, as today.
- **Developer build** (`DEV_BUILD`, const.py): the integration running
  straight from the Room Tiles source (`assets/build_panel.py` beside it),
  never a released install (HACS copies only the integration). Decided once
  at startup and logged as a warning. Every development-only behavior
  checks it - search for `DEV_BUILD` to find them all. Today: packs rebuilt
  on disk are served live.
- **When idle** (every panel; idle_clock.cpp): after the sleep time
  untouched (a new or reset panel: 1 minute - the round one 30 s - then the
  digital clock at 40 %; one set up keeps its own), the screen goes dark or a clock comes up (digital - the time,
  the weekday and date in the panel's language, 12-hour with AM / PM in
  English - or analog: a dial drawn in the theme's colours - or the theme's
  own face: Theme clock, the analog one in a theme without a clock; the
  setting stays as chosen whatever the theme). A second hand (on by default; switched off
  in the list; analog / theme); the analog and theme faces show a short date ("Sat 14"). With "Animations
  keep tiles visible" (off by default) a tile in view that animates keeps the
  clock away: the round panel's centered tile or both halves of a split, a
  panel's whole board - the board stays up dimmed instead (with Screen
  off too: the screen stays on while it animates). Idle has its own
  brightness (in the list, under the switches; 10 % up to the screen's
  brightness - at it, it follows it; shown live while the slider moves): a
  dim clock at night. **Screen off when the following area lights are off** (off by
  default; under the brightness): the lights of the room the panel is IN -
  its HA device's area, NOT the area it shows (people switch that) - by
  that room's area lights entity, the one its lights button uses (the
  override, else Room Tiles' "<Area> Area Lights"; a hidden area has none
  made: its lights; the payload's `panel.room_lights`, `panel.room`). Idle while they're all off (none on, one at least
  reported off), the screen goes off instead of the clock or a board an
  animation keeps; they come on while it's off and still untouched: the
  clock (or the kept board) again. Under its word, the room it follows
  ("Office (HA device area)"), or what's missing (no area in HA; an
  area without lights): then as usual. Its own record ("RTIL": the idle
  record keeps its size). A
  touch on the clock brings the board back, at full brightness, on its
  release. Kept on the panel (its own record); a round panel starts on
  the digital clock after 30 s.
  The list (a panel's settings menu) stays open for more than one change:
  the four faces two by two, a pick shown in place; its own X, or a tap
  beside it, closes it.
- **The Wi-Fi chip** (an ESP32-C6 with Espressif's ESP-Hosted
  `network_adapter`; firmware/wifi_chip/): its firmware must match the
  ESP-Hosted library in the panel firmware, and boards ship with older
  ones (2.3.0, 2.12.3 seen). Every image carries the matching one (1.2 MB;
  ESPHome's `esp32_hosted` update, embedded) and, at startup - before
  Wi-Fi, so a board straight from the box gets there too - brings an
  **older** chip up to it **once per carried version** (RoomTiles::
  wifi_chip_update_available; the tried version kept in NVS "RTWC") - on a
  new panel **after its language is picked and before Wi-Fi is set up**
  (the message in its words; its hotspot only gone before anyone uses it),
  on one set up before at startup: "Updating the Wi-Fi chip…" on the boot
  screen, about a minute, then a restart. Never a newer chip (no downgrade), never a second try of the
  same image, never in a loop, and only when the carried image is exactly
  the ESP-Hosted library the firmware was built with (a panel someone builds
  by hand with another ESPHome: its chip left alone). Users never build:
  every image comes from our CI with one pinned ESPHome (`ESPHOME_VERSION`
  in firmware.yml), so the image and the library always ship together - the
  user's own ESPHome (or none) doesn't matter. A chip below 2.6 can't "activate" (ESPHome
  reports it as a failure): it switches over by itself ~20 s later, and
  the panel restarts after 25 s (Espressif's example for old chips does the
  same; seen on a V1.0 with 2.3.0, 2026-10-12). V1.0 boards need the 1-bit
  SDIO bus for the stock firmware (the board file does it). Risk accepted:
  a chip that won't boot can't be fixed over USB (its own pads only). The
  chip's version shows on the panel's HA device (Wi-Fi Chip Firmware). When
  ESPHome moves ESP-Hosted, the image moves with it (firmware/wifi_chip/
  README.md).
- **Firmware updates through Room Tiles** (firmware.py, update.py; the
  panel's room_tiles.cpp JOB_FIRMWARE): each build names its board
  (`elecrow-p4-<size>-v<PCB>[-es]`, from the board file), whether it's
  generic (`identity/generic.yaml`) and the panel format it speaks
  (`PANEL_SCHEMA`) in a tag Room Tiles reads from the image file
  (`RT-IMAGE:<board>:generic:<n>:<release>;` - <release> only in a
  release's builds: release.yml's firmware builds set ROOM_TILES_RELEASE to
  the tag), with ESPHome's build time and the ELF SHA-256 (its first 8 bytes
  = the build's id). Each payload request reports the panel's board, build,
  kind, build time and release. HA shows a release's build by its version
  ("0.1.0"), any other build by its build time and id
  ("2026-11-18 09:54 (88d578)"); an update is there when the builds differ. Images:
  `firmware_images/` (a release's) and `<config>/room_tiles_firmware/`
  (uploads from the dashboard's Panels page; in a developer build also
  ESPHome "OTA format" files dropped in). The folder keeps one image per
  board, named for it (`room-tiles-<board>.ota.bin`): a newer build
  replaces the older. An image for another panel format is never offered.
  One update entity per panel, on its own device: Install puts the build,
  size and SHA-256 in its payload; the panel downloads it (signed, only its
  own board's, only that build), checks size and checksum, writes its other
  slot sector by sector (progress on the boot screen) and restarts into
  it; the bootloader returns to the old one if it doesn't start. Only
  generic panels: a hand-built image holds its panel's name and key (those
  keep ESPHome's own updates).
- **Update panels automatically** (Room Tiles' setting, on by default; the
  Panels page and `room_tiles.set_settings`): Room Tiles offers each panel
  a newer image for its board by itself, marked `"auto"`; the panel installs
  it once nobody's using it - by idle time only, whatever is on screen:
  idle (dark, the clock, or dimmed - also a board an animation keeps up),
  or 10 minutes untouched when it never goes idle; one that starts while the screen is
  dark by choice (idle: the screen off; the room's lights off) stays dark
  (and the new firmware goes dark again as it starts) - dark only because
  HA was gone (restarting for this very update) doesn't count: the update
  shows its progress and the panel comes back lit.
  Never older: only an image built more
  than a minute after what the panel runs (a panel flashed by hand with a
  newer build is left alone; firmware that doesn't report its build time
  isn't updated by itself). A build that doesn't take (the download fails,
  or the panel comes back on its old build) is offered by itself twice, then
  left for Install. The update entities say whether it's on (HA's "auto
  update").
- **A panel too old for this Room Tiles updates right away:** its 426
  answer carries its board's image (whatever the setting says); its
  firmware download stays open to it, so it gets out of the mismatch on its
  own.
- **Panels page** (dashboard settings menu, shown once there's a panel):
  each panel's name, area, board and firmware state (up to date, an update
  with Install, updating, built by hand, not connected), the auto-update
  switch, the images Room Tiles has, and Upload firmware (admins; a file
  for one panel, another format or something else is refused with a
  reason). Live from the feed's `panel_firmware`.
- **Firmware and integration must match:** one format number
  (`PANEL_SCHEMA`, panels.py and the firmware's signing.h) covers
  everything between them - payload, packs, taps, screenshots - and is
  bumped on both sides with any change the other side can't read. An
  additive change needs no bump: a new field the old side never sends gets
  a default on the reading side that means the old behavior (e.g. the
  payload's `area_set` - missing: "has an area", no picker), and either
  side ignores fields it doesn't know - so firmware and HA can update in
  either order. Every
  panel request carries it; HA answers another number with 426 (JSON: its
  own number, and for an older panel its board's image) and lists the
  panel in Repairs, saying which side needs the update. The panel stays on its boot screen saying the same
  ("Update this panel's firmware – Room Tiles in Home Assistant is newer" /
  "Update Room Tiles in Home Assistant – this panel's firmware is newer") and tries again every 30 s. No compatibility with
  other numbers before the first release.
- **A tile waits for its data:** any tile (on the board or in a pop-up)
  shows its stopwatch until HA has answered for its state and every
  attribute its kind uses. HA answers subscriptions in the order asked and
  skips attributes an entity doesn't have, so each batch is sent attributes
  first, main states last, and each kind's attribute list ends in one HA
  always sets: its last answer means the batch is done. A batch HA doesn't
  answer at all stops waiting after 3 s.
- **Editing on the panels = tile editing only** (assign, remove, reorder,
  layout, with the picker). Map, layer and board editors, settings dialogs,
  device setup and short names are dashboard-only; the panel says when there
  is something to set up there.
- **Wi-Fi set up on the panel** (firmware wifi_setup.cpp; the 7" / 10.1" -
  the round panel: the phone way only): a panel with NO network saved shows
  the networks nearby by itself once its language is picked (strongest
  first, a lock on secured ones, "Other network..." to type one in), the
  phone way on the same screen (its hotspot stays up). A panel that has a
  network saved but isn't on it yet (restarting, an update, its network
  gone) never gets it by itself - it reconnects in the background. Change
  Wi-Fi (settings, and the boot screen's button) opens it too: the network
  it's on is first with a check mark, and **it stays until the new one
  works** - tried the way ESPHome's Improv does (set, not saved; saved only
  once the panel is on THAT network; 45 s for a new panel, 90 s when leaving
  one - a mesh router's first refusal is retried meanwhile), else the old
  network again ("still on ..."). The screen is never closed from outside
  while it tries. Scans: on a network, the panel's own (ESP-IDF, every
  channel, staying connected - ESPHome's roaming check skips the scan on a
  good signal); without one, ESPHome's; never while ESPHome is connecting
  (it would interrupt it). The keyboard is LVGL's button grid with our
  layers (letters, numbers, symbols; backspace / shift from MDI in
  rt_font_keys), keys ~90 x 62 px. Open, the panel never goes idle; Change
  Wi-Fi left untouched closes after 3 minutes. Its words are built into the
  firmware (boot_words.h): a new panel has no pack yet.
- **Boot screen:** the Room Tiles icon on black (built into the firmware,
  so it shows before any download), the name, and - small and dim at the
  name's bottom right - the firmware's release ("v0.1.4"; none on a build
  that isn't a release, nor on the round panel).
  - **Factory reset** (the panel's HA button "Factory Reset", disabled by
    default - never pressed or voice-exposed by accident): Room Tiles is told
    to forget the panel's settings (area, layout, theme, language), the
    board comes down ("Resetting to new…"), the theme and wording packs and
    all of NVS (Wi-Fi, the API key HA set, every panel setting) are erased,
    and it restarts as a new panel - the hotspot, the language, "Add this
    panel", the downloads, the area. HA's old device entry is removed by
    hand before adding it again.
  - **A new panel** (no wording stored, none picked) asks for its language
    first, each language in its own name, before anything else shows: under
    the logo and name on the 1024x600 panels, the languages alone on the round
    one. Its
    boot lines are built into the firmware in every language
    (`boot_words.h`, made by `tools/make_boot_words.py` from the dashboard's
    wording; a test keeps it current): the stored wording first, then these
    in HA's language for the panel (once a payload came), else the picked
    one. Once HA has added the panel, the pick becomes the panel's own
    language there - unless it's HA's language already ("Same as Home
    Assistant" stays).
  - **No API key yet** (HA hasn't added it): "Add this panel in Home
    Assistant", the panel's name as HA's Discovered list shows it (the
    friendly name with the chip's suffix) and where that is.
  - **No area:** none picked and its device has no shown area - the payload
    says so (`area_set: false`; the first area meanwhile) and the panel opens
    its area picker by itself, once a start.
  - **HA's area seeds the room once, at setup** (`adopt_ha_area`): a panel
    with no room of its own takes its HA device's area the first time Room
    Tiles serves it, and keeps it as its own. After that the room is the
    panel's - changing or clearing the device's area in HA does nothing to
    it; the panel's area picker changes it. A factory reset clears it, so
    setting up again takes HA's area again (HA restores a re-added device's
    old area and name - no picker then).
  - **A pick on the panel is kept until HA has it** (`picked_`): the area,
    layout, theme or language picked on the panel goes to Room Tiles; a
    send HA can't take (restarting, Wi-Fi) would be lost, so the panel keeps
    each pick, sends it again with every payload that doesn't have it yet
    and every 15 s, and shows the picked area and layout meanwhile - until
    a payload has it (or the area is gone). Not kept across the panel's
    own restart.
 Home Assistant gone for 10 s (a restart, the
  router, an outage - HA's own connection, not a log viewer) takes the
  board down to it: "Connecting to Home Assistant…" (old states shown as
  current would be worse); the board comes back once HA is. A panel idle
  when HA goes (its clock, or a board an animation keeps up - not one dark
  by choice) shows "Connecting…" at the idle brightness for 10 minutes
  (OFFLINE_DARK_MS: an HA restart passes lit), then goes dark - if HA stays
  away, say overnight, a dark screen keeps nobody awake. A touch then wakes
  it for the usual sleep time, not another 10 minutes. When that darkness was only
  HA's doing (the screen was up, dimmed or the clock before), the board's
  return wakes it into what the idle rules want then, as if untouched all
  along - an animation keeps it up dimmed, the clock comes back - never full
  brightness; nothing to show within 15 s: it stays dark. (A Wi-Fi roam is
  enough to drop HA for longer than 10 s.) A theme picked on the panel goes straight
  to it ("Requesting the theme…", then downloading and saving with the
  progress bar) - nothing may draw from the old pack while it's rewritten;
  if no download starts within 20 s, the board comes back.
- **The map** (map_view, map_draw, raster): drawn in 256 px tiles by the
  panel's own anti-aliased rasterizer on a background task, into a pool of
  tile buffers in PSRAM (least recently used go first); LVGL only shows
  finished tiles as images. Every item of a map is binned into a grid of
  cells once, so a tile only looks at what's near it. The map area is always
  covered by tiles (a plain background tile until one is drawn, plain tiles
  around a map smaller than the screen), so nothing under them is painted.
  Panning follows the finger on both axes; a tile is drawn once per map and
  zoom. A new zoom (or the map opening, or a vacuum's queue changing its
  look) shows nothing of its tiles until all of them on screen are drawn -
  the plain background (or the old look) and the busy stopwatch meanwhile,
  markers and names already in place - then all at once. Zoom: the zoom box (+, a roller of 0.5 steps up to the map's limit, -: every zoom is a new set of tiles, so fewer, bigger steps than the dashboard's 0.25); viewers - the panels and the dashboard's map, not its editors - zoom to 8x, more for a map whose layers start deeper or whose smallest room needs it (viewMaxZoom / view_max_zoom_: one rule), a
  tap on a room, the map's name (its room list); the same zoom numbers as
  the dashboard. Markers: the layers showing at the zoom, coloured while on
  (gray with detail when off - theme pack versions), a tap = the direct
  action, a long press = the pop-up row (the tile, its groups, the scenes
  that set it; Room Tiles works the lists out). A vacuum tile opens its room queue: its
  map with the rooms tinted, the queue's rooms coloured and numbered, a tap
  queues a room, a bar with Start / Pause / Skip / Stop / Clear.
- **Map drawing** (sprite.h): what a pan redraws every frame is kept
  cheap. Tiles are stored at 4 bits a pixel - each tile's 16 most used
  colours, the anti-aliased edges rounded to the nearest of them - which
  quarters what each frame reads from PSRAM (the slow part: the screen's
  map is re-read for every frame). Markers (face, icon, ring), their names,
  room names and, while panning, the zoom box are pre-rendered once by LVGL
  itself (so they look the same) into 4-bit pictures with alpha, kept in
  internal RAM while there's room, one for every combination met (on, off,
  ringed...) until the theme changes. Each map layer (tiles, markers, room
  names) draws all of its pictures in one go straight into LVGL's render
  buffer - no LVGL object per tile or picture (a marker keeps an invisible
  one: what a tap hits); the zoom box's picture goes through Room Tiles' own
  image decoder.
- **No taps right beside the zoom box**: a tap that starts within a
  marker's width of it does nothing (a marker, a room), so a near miss on
  the roller can't switch a light; a pan can still start there.
- **Display settings stay on the panel** (brightness, screen-off time - the
  next touch only wakes it); language and theme are the panel's settings in
  HA. The screen dims while a theme or the firmware is written.
- **Screenshots** (screenshot.h): the panel's settings (Screenshot - the
  menu closes first, then the panel says where it went) or its "Take
  Screenshot" button in HA (diagnostic, silent) redraw the screen once and copies each part as it goes to
  the display - exactly what's shown - then POSTs it (raw RGB565, signed
  like the panel's other requests) to the integration, which saves a PNG in
  HA's media folder (Media > My media > room_tiles), the last 20 per panel.
- **Frame statistics** (perf.h): the map logs one line per phase (open,
  zoom, pan, idle) - frames, fps, frame / flush time, how much of the screen
  each frame repaints - so a change's cost shows in the log.

## Dashboard layout

- **The panel formation is kept everywhere** (the area's 5x2 / 6x3 grid):
  a tile is in the same place on a panel, the phone and the computer.
- **Portrait:** the grid TURNED by default (per device: menu "Turn the tiles
  in portrait"): columns become rows (5x2 -> 2x5, 6x3 -> 3x6), all of them
  across the screen, scrolling down - the tiles keep their slots, only the
  drawing turns (slot at column c, row r drawn at column r, row c), so the
  panels and landscape are unaffected. Switched off: tiles at the "2 wide"
  size, the panel's formation kept, panning both ways with snap to whole
  tiles, the next column peeking in. Either way a small indicator shows
  which tiles are on screen (of the grid as drawn).
- **A narrow screen held upright** (under 560 px wide): the top bar in two
  rows - the room's name across the first (after the menu button), the
  buttons under it - a one-row bar left the name no room.
- **Landscape:** the whole grid fitted to the screen. On touch devices Room
  Tiles covers HA's sidebar and header (full screen; a button shows HA's menu
  again); per-device setting, default on for touch, off for mouse devices.
- Orientation comes from the window's shape, not HA's "narrow" flag.
- **Tile layout (5x2 / 6x3) is per area and per device**, like the panels;
  the grid button next to the area name switches it (no settings-menu entry).
- Top bar: menu, area name (opens the area picker), area lights (Done while
  editing), Help, settings. The editors (Tile, Layer, Map), Areas,
  Appliances, Short names and the device options live in the settings menu.
- **Language**: the dashboard follows Home Assistant's (the user's profile);
  Settings › This device › Language overrides it on this device (stored in
  the browser). All languages are in the bundle (i18n.ts), so switching is
  instant. The integration's own texts (status lines, notifications) stay
  in HA's language.
- **Scene and script tiles** (kinds `scene` / `script`): the middle is one
  big play button - scene teal, script orange; a tap turns the scene on /
  runs the script (one tap, no confirm, like a light). A scene has no state
  of its own, so its button lights ~1 s to say it went; a script's stays lit
  while it runs. A script that asks for inputs (a required field in HA's
  `services`) is left out of the pickers. Never placed by Auto configure
  (not in defaults.TILE_DOMAINS) - people add them by hand.

## Editing

- On the **panels**: tile editing (assign, remove, reorder, layout),
  area picker, area lights, colour picker, settings. The panel's tile picker
  filters by type: All, lights, switches, fans, covers, locks, scenes,
  scripts, then **"..."** for what a home has only a few of - thermostats,
  appliances, pools, vacuums - and the Map tile (the dashboard's tile editor
  has Map as a button beside Empty).
- **Dashboard only** (rare / fiddly): the map editor (zones, walls, shapes,
  floors, links), map markers, area and catalog setup, short-name review,
  and **device setup** - appliances (and later pool / spa, vacuums): adding
  what was found, editing, combining / splitting, what empties a unit.
- The **panels only say** when something new was found ("New appliance
  found - set it up in Home Assistant: Room Tiles") and point to the
  dashboard; they never run device setup themselves.

### The map editor (plan-editor.ts)

- One **draft** per session over a copy of the map; Save changes writes it in
  one step (`room_tiles.set_map`), Cancel drops it. Undo / redo (100 steps)
  covers every change incl. the map settings dialog.
- Tools: Select, Wall, Window, Opening, Room, Shape, Link, Picture. Drag draws
  (end to end, or a rectangle); taps draw corner by corner. A window /
  opening drawn along a wall **replaces that piece of the wall**.
- **Snapping** (on by default): existing corners, walls, 0/45/90 degree
  directions, lining up with corners. **Joined corners move together**
  (dragged or nudged): within the house drawing (walls, windows, openings,
  rooms, shapes), and within one vacuum's areas - a vacuum area snaps to the
  house but is never welded to it, nor to another vacuum's. The toolbar's
  "Shared corners move together" (on by default) off: a corner moves only
  for its own item.
- An edited map stops being `generated`: new HA areas no longer get a square
  on it - you draw their room and pick the HA area.
- Bounds are fitted on Save - the Map Editor's and the Layer Editor's - to everything drawn plus the map's markers: they grow when a marker goes outside and shrink again when it comes back. Markers may sit anywhere; the bounds only frame the whole-map view (panning is free). Saving only the bounds and the layers' starts (the Layer Editor) keeps a starter map `generated`.
- **Shapes are drawn by type**, bottom to top: grass, paving, deck, water,
  floor - never by the order they were added (plan-draw.ts SHAPE_ORDER; the
  panels must match). A tap still picks the smallest shape.
- A room's name can read **vertically** (bottom to top) for narrow rooms
  (`label_vertical`); the panels' map must draw it the same way.
- Markers are NOT shown in the map editor (clutter, no use there) - they're
  placed with the marker editor (pencil).
- The editor's top row names its map dialogs in words (a bare gear doesn't
  read as "edit"): **Map settings** (pencil) and **New map**.
- Maps are added (New map) / ordered / deleted (Map settings) (add_map,
  order_maps, remove_map act at once, outside the draft; deleting needs a
  second tap). Removing a layer moves its markers to the first layer.
- **Trace picture**: a floor-plan image under the drawing - usually a phone
  photo of a paper plan, so never straight or to scale: move, resize
  (corners), stretch one way (side dots), fine turn (a knob above it, 0.1
  degree steps, tap = level), turn 90 (button), fade, hide. Stored in the browser only (IndexedDB per map) - a
  drawing aid, never sent to HA; Cancel doesn't touch it.
- Full SVG import is not planned for now: tracing over a picture covers it.

### Vacuums on the maps (no second set of maps)

- `vacuum.clean_area` takes **HA area ids**; HA maps each vacuum segment (a
  room in the vacuum's app) to an HA area ("Map vacuum segments to areas").
  So every piece a vacuum cleans on its own needs an HA area - also pieces
  that aren't real rooms (e.g. `bar_area`, only for the vacuum).
- Room Tiles **reads that mapping** (entity registry options
  `vacuum.area_mapping`; vacuums.py, live feed section `vacuums`) - never
  entered twice. A map room whose area is mapped = cleanable by that vacuum.
- **Vacuum areas** (vacuum zones in the code: `Zone.vacuum` = the vacuum entity, storage 1.6; "Vacuum area" in the UI) add the
  pieces people split their floor into for vacuuming: drawn on the same map,
  linked to the segment's HA area, shown only in that vacuum's view, may
  overlap rooms (the smaller zone wins a tap, drawn on top).
- The map editor's vacuum view (robot button): cleanable rooms highlighted,
  others greyed, vacuum zones on top, "not on a map yet" list of mapped
  areas; the Room tool adds vacuum zones there.
- Several vacuums each get their own zones; floors work as for everything
  else (a vacuum's view of each map).
- The vacuum tile / queue map (Matic add-on) will use this view: tap a room
  or zone = queue its area.
- **The room queue's UI** (decided 2026-11-11, building in step 2):
  - The queue is ONE list of HA areas (`clean_area` takes areas) - not tied
    to a map. An area with rooms on several maps / several rooms: any of
    them queues the same area once; every one of its rooms shows it queued
    (its position number).
  - **The vacuum tile shows a map** (as the panels' Matic tile does): the
    map holding the area being cleaned (else the first queued area's; else
    the vacuum's first map with a cleanable room), drawn small - colours
    only, no numbers (too small to read).
  - **Colours = the panels' key** (vacqueue.ts ROOM_STATES, theme `vac*`):
    queued blue; the room being cleaned green, amber paused, orange needs
    you, red error, pale green starting (sent, not cleaning yet). Rooms,
    room buttons, queue chips and the status line use them; the queue map
    shows the key.
  - **Adding / removing rooms is the map** in queue mode (the vacuum view):
    cleanable rooms lit, the rest grey; tap a room / vacuum zone = add or
    remove its area; queued ones show their number. It opens showing the
    whole map (every room in reach, no scrolling). A quick toggle switches
    between the maps that have rooms the vacuum cleans (only those).
  - **Start queue automatically** (per device): adding a room starts an
    idle queue - no Start press (never resumes a paused vacuum).
  - Queue controls (order, remove, Start / Pause / Stop / Clear) next to it.
  - Behaviour from the YAML Matic queue: the next room starts only after the
    last finished cleanly; an error pauses on that room; adding rooms never
    resumes a paused vacuum; a long error (12 h) cancels and clears.
  - **Taken over = let go:** while a room of the queue is in progress,
    something else controlling the vacuum (its own app, HA's vacuum card, a
    voice assistant, another automation) stops and clears the queue - its
    command stands, nothing more is sent. The status line says "Queue
    cleared - used elsewhere" (tile and queue bar) until the vacuum docks or
    the queue is used again. Seen as: a vacuum command through HA that isn't
    Room Tiles' own (its commands carry their own HA context) - any vacuum;
    and, for makers tested to work this way (robot.py IDLE_IS_A_STOP: Matic),
    the vacuum turning idle when Room Tiles didn't ask (a stop or a "go
    home" from its app goes idle first; a finished room goes straight from
    cleaning to returning). Pause never counts (the queue waits). Other
    makers: idle still counts as a finished room until someone checks theirs.
    The queue only moves on from a room of its own: a job something else
    started never starts or advances it.
- **No vacuum is assumed**: no vacuum, any brand, any number. Vacuums come
  only from HA (those with a segment-to-area mapping, plus any that already
  have vacuum zones); no vacuum = no vacuum button, nothing vacuum-related
  shown. Brand-specific things (Matic's queue add-on, its icon) are keyed on
  the device's manufacturer, never on an entity id.
- **The room queue is a generic VACUUM queue**, not tied to a brand. Rooms go out with HA's own
  `vacuum.clean_area` (HA 2026.3+: Matter, Ecovacs, Roborock so far), one area
  at a time. Requirement = the vacuum supports `clean_area` + has a segment
  mapping, never a brand. **Matter vacuums are supported** (the current
  Matic queue is the reference: room done = returning, or docked, with no
  error - idle too for makers not known to turn idle when stopped); Matter-only extras (the RVC operational state / error sensors for
  "interrupted vs finished", "needs you") are used when present, else plain
  vacuum states. Other integrations (e.g. iRobot / Roomba without
  `clean_area`): unknown - check what they offer when we get there. Cleaning
  a room is a vacuum-profile action: `clean_area` is the first (and Matter's)
  implementation; a brand without it can be added later by a profile with
  its own way (its own service), queue unchanged. Until then such a vacuum
  gets the vacuum tile but no queue.
  **Roomba:** HA's iRobot integration gives a normal
  vacuum entity (tile fine) but no `clean_area` / segments yet. Room
  cleaning today is only `vacuum.send_command` `start` with `pmap_id` +
  `regions` ids the user digs out of debug logs (fragile, model-dependent),
  or custom integrations (roomba_rest980, Roomba+ - has a clean_area
  feature request). No send_command workaround: Roomba
  gets everything it supports, the rest is disabled.
  **Setup says what's unavailable:** a vacuum without `clean_area` (checked by
  the feature flag, not the brand) is set up with a plain note, e.g. "This
  Roomba doesn't support cleaning chosen rooms yet - room cleaning is off for
  it." Its tile works; queue / tap-a-room-to-clean are hidden for it (no
  dead buttons). If its integration adds `clean_area` later, the feature
  turns on by itself (re-checked on integration reload).
- Icons: `icon_matic` for Matic robots (device manufacturer "Matic..."),
  `icon_robot_vacuum` (generic round robot, assets/tools/
  make_robot_vacuum_icon.py) for every other brand - tiles and map markers.
  The panel firmware port needs the same rule.
  A vacuum tile on a SENSOR (e.g. a queue status sensor) names its vacuum
  in a `vacuum` attribute; the icon follows that vacuum's device.

## Storage compatibility (people restore backups and downgrade at any time)

1. **Every stored version ever released must keep loading.** Each version has
   a step in `migrate.py` and a sample in `tests/fixtures/storage/`
   (`v<major>.<minor>.json`); CI loads every sample.
2. **A minor version bump is additive only:** new optional fields; nothing
   renamed, removed or newly required. Older Room Tiles can then still read
   newer data (the model ignores fields it doesn't know); CI checks this.
3. **Anything else is a major version bump.** Home Assistant won't let older
   code load it, so before every migration the old-format data is saved to
   `room_tiles_backups/before-migration-v<old>-<time>.json` (as HA stores
   it, with its version), which can be loaded again with
   `room_tiles.import_data` - so can a removal copy (`removed-*`): import
   unwraps a storage file and migrates it (backups.py). The folder keeps
   the newest 5 copies of each kind.
4. Storage 1.1 -> 1.2 broke rule 2 before the first release; the first public
   release is the baseline.

## Sending changes to HA (dashboard and panels)

- **A control sends ONLY in direct response to the user's input** (touch,
  drag, wheel, click, keys). Programmatic updates (showing HA's value), layout
  changes (resize, rotation, full screen) and re-renders must never send
  (e.g. a roller must not take its own scroll during a layout change as
  input and set a thermostat by itself).
- Never flood HA: rollers send once they come to rest; continuous controls
  (colour ring, sliders) send at most once per 0.5 s while moving (1.5 s for
  light groups) plus the exact value when the user stops, and nothing when the
  value didn't change since the last call.
- Hold the user's value on screen until HA reports it (within a tolerance) or a
  settle window runs out (per kind, like the panels; 15 s for light groups,
  whose members report in-between colours as they change one by one).

## Edits

- Every edit runs on a copy of the data that must validate before it replaces
  the live data: a refused edit changes nothing.
- Changes are announced per document section (`areas`, `maps`, `markers`,
  `catalog`, `settings`) so a tile edit never resends map geometry.
