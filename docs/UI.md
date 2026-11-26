# Room Tiles - UI rules (dashboard, and the panels where they apply)

Keep every screen consistent. New UI follows these; if a rule doesn't fit,
change the rule here first, then the code.

## Primary goals

For everyday use (tiles, the map - everything outside editing), every design
decision serves these two:

1. **Information at a glance** - state is easy and quick to read without
   studying the screen: on / off, open / closed, running / done show by colour,
   art and position, not by reading text.
2. **Action in the fewest touches** - the common action is one tap (turn a
   light on: tap it). No confirm dialogs, extra screens or menus for simple
   things; anything more (settings, details, pop-up tiles) sits behind a long
   press / right-click, never in the way of the one tap.
   **Except entry:** what lets people in - locks, garage doors, gates,
   doors - never changes on one tap of a map marker; the tap opens its tile,
   where the change is deliberate.

When a feature would cost either one - an extra tap for a common action, or a
state that has to be read rather than seen - rethink it.

**Editing and settings** have their own goal: **intuitive and fast**. Obvious
without reading docs (visible buttons, a brief ? help), few steps, direct
manipulation (drag, tap to select), and safe without slowing you down - drafts
with Save changes / Cancel and undo instead of "are you sure?" prompts.
The one prompt allowed: closing (X, backdrop, closing the map) with unsaved
changes (`rt-unsaved`: Save changes / Discard / Keep editing - one tap each),
since closing is the one loss a draft and undo can't protect. Never shown
without changes, never on Cancel.

## Building blocks (frontend/src/ui.ts)

- **Dialogs** use `dialogStyles`: backdrop, title bar with an X, content,
  footer with **Cancel** + **Save changes** (primary, right). Set the width with
  `--dialog-w`. Never copy dialog styling into a component.
- **Settings** use `rowStyles`: one row per setting - label left, control
  right, one line (`.setting`). Group rows under small uppercase section
  headings (`.section`).
- **Rows that open a dialog** are `navRow()`: icon, label, optional badge,
  chevron.
- **Anything that scrolls shows there's more**: a component names its
  scrolling areas in a `ScrollFades` controller, which fades each one out at
  the edge where more is hidden - the bottom while more is below, the top
  once scrolled down; nothing when it all fits. The browser's own scroll bar
  stays as the platform has it (a phone shows it only while moving). Lists,
  menus and dialogs only - never the board's tiles, the map, nor rollers.
  The panels, which have no platform bar, draw thin scroll bars.

## Words

- **A dialog, menu or picker open over the tiles freezes them** (the tile
  view's `locked`: no scrolling until it closes). On a phone, a drag that
  starts on a part of a dialog that can't scroll itself (its title, a list
  too short to scroll) would otherwise scroll the tiles behind it.
- **Entity** - anything from Home Assistant on a tile or marker (pickers,
  Short names, Help): HA's own word, so it matches what people see there.
- **Device** - only the phone / tablet / computer showing Room Tiles ("This
  device", "on every device"), and "Supported devices" (hardware models).
  Never for an entity.
- **Appliance** - Room Tiles' own: a washer, dryer or dishwasher set up in
  Appliances.

## Which control

| Choice | Control |
|---|---|
| On / off setting | `toggle()` - the panels' switch art (blue when on) |
| 2-3 short options | segmented buttons (`.segmented`) |
| One of several / longer labels | dropdown (`<select>`) |
| Picking items from a list, list filters | checkboxes |
| Tile controls | `<rt-switch>` / `<rt-roller>` with the tile's kind colours |

## Input (frontend/src/input.ts)

Touch and mouse / keyboard each follow their own conventions. Decided **per
gesture** (the event's pointer type), not per device - an iPad with a
trackpad or a touchscreen laptop uses both. Raw events become **intents** in
`input.ts`; editors act on intents and never check pointer types or modifier
keys themselves. New differences go into this table and `input.ts`.

| Gesture | Touch | Mouse / trackpad / pen |
|---|---|---|
| Tap / click an item | add or remove it from the selection (like the panels) | select just it |
| ... with Shift / Ctrl / Cmd | - | add or remove it |
| Tap / click empty space | clear the selection | clear the selection |
| Drag a selected item | moves all selected | moves all selected |
| Drag an unselected item | moves it, adds it to the selection | moves it, selects just it |
| Drag on empty space | pans (in **Select** mode: selection box) | pans; with **Shift / Alt**: selection box (adds) |
| Long press / right-click | more (settings, pop-up tiles) | right-click: the same |
| Press, slide, let go | nothing - a tap is a tap only within 16 px (TAP_SLOP_PX; the panels: every button) | the same |

A map marker's pop-up tiles: its own tile, then the groups it's in
(closest first, tagged "group" - at most 6, then "+N more groups"), then the scenes that set it or one of
those groups (tagged "scene"): the most specific first (it directly, then
its smallest group...), then by name - at most 6, then "+N more scenes".
| Double-click | not used | not used |

Each editor has a **? help dialog** (map editing: `map-help.ts`): brief,
tables not prose - buttons, touch vs mouse, keys. When this table or
`input.ts` changes, update the help too.

**Keyboard shortcuts are accelerators only** - everything must also be
reachable with visible buttons (touch users have no keyboard). Never active
while typing in a field. Map editing: Ctrl/Cmd+Z undo, Ctrl/Cmd+Y or
Ctrl/Cmd+Shift+Z redo, Delete / Backspace delete the selection, Esc clear it,
Ctrl/Cmd+A select all on the layer, arrows nudge (Shift: 10x). Modifiers for
"add to selection" are Shift / Ctrl / Cmd (not Alt - often taken by the
system; Option on a Mac means "duplicate" elsewhere).

## Behaviour

- **Edits are drafts**: nothing changes until **Save changes** (always a
  visible button - the footer of a dialog, the bar of a full-screen editor).
  In a dialog **Cancel** discards at once. **Full-screen editing sessions**
  (map editor, marker editing) never drop a session in one tap: the map
  editor has no session Cancel (Save changes / X), marker editing's Cancel
  asks when there are changes. A **Cancel next to Done** while drawing drops
  only the unfinished piece (a Cancel at the top reads as "cancel this
  polygon"). **X and the backdrop close; with unsaved
  changes they ask first** (`rt-unsaved`: Save changes / Discard / Keep
  editing) - never lose work silently, same everywhere.
  Save is disabled until something changed. **X in an editor leaves the
  editor, not the screen it was opened from**: the map editor's and marker
  editing's X both go back to the map view; X there closes the map.
- **Style modules that share the panel's shadow root use prefixed class
  names** (`appl-...` in appliance.ts): the panel's `.sheet` (map editor's
  bottom sheet) once restyled the washer animation's `.sheet` image - dark
  square, wrong offset. styles.test.ts fails the build on a shared name.
- **Tests: happy-dom mishandles bindings at a template's top level** (a
  leading `${...}` shifts every binding by one; a trailing one doesn't
  render). Browsers are fine. Put optional overlays (the unsaved prompt...)
  at the END of the template, and check them in tests through their state.
- **Selection panels** (the map editors' bottom sheets) edit the open draft
  live; they end with **Done** (deselect), never an X - an X reads as
  "close without saving". (Exception: settings that only affect this device - layout,
  animations, full screen - apply at once.)
- **A settings dialog inside an editor** (the map editor's Map settings)
  edits that editor's draft, so it has just **Done**: its changes are undoable
  and saved / cancelled with the editor's own Save changes / Cancel.
- **The map is always one tap from the area picker** (its first button,
  "Map": the map holding the current area) - no Map tile needed.
- **Hidden areas hide their map**: the map view doesn't offer a map whose
  rooms all belong to areas hidden in Room Tiles (nothing is deleted - it's
  back once one is shown; the Map Editor lists every map), nor rooms of
  hidden areas in its room picker.
- **"+ Add layer" links** (the Layer Editor's layer list - its last entry -,
  the zoomed-in note, Help's Layer settings link) open Map settings with
  the Marker layers group framed and scrolled to, until it closes.
- **Board top bar, like the panels**: right of the area's name, More tiles
  (5x2 <-> 6x3 on this device, lit on 6x3) and Map (= a Map tile); both
  hidden while editing tiles. Default boards get no Map tile (it can still
  be placed by hand). The panels' bar also shows the time in the middle
  (the old panels'; 12-hour or 24-hour by the panel's 24-hour clock switch,
  which the digital idle clock follows too) - not while editing, nor when a
  long area name leaves no room. The dashboard's bar shows it the same way
  (centred between the left and right buttons, hidden whole - never cut -
  when it doesn't fit), in the user's HA profile time format and time zone
  (the panels' 24-hour switch is per panel). The panel's settings have no Area button:
  the area's name in the bar picks it.
- **A Map tile (and the Map button) opens its area's map**: the map used last (in this browser)
  if that area has a room on it, else the first map (in the maps' order)
  that does - zoomed so ALL of that area's rooms on it are in view together
  (an area may be drawn as several rooms, or on several maps). A Map tile
  visit never changes which map counts as used last.
- **Tool modes say which tool is active** in words, at the start of the
  hint line under the toolbar (icon + name + a few words on what to do):
  touch screens have no tooltips, so nothing may rely on them. The hint is
  a few words, never a paragraph - details go on the Help page.
- **Help pages are reference, not prose**: short tables (what - how),
  a few words per row; no narrative paragraphs.
- **Editing = pencil**, never a gear; actions people must find (New map,
  Map settings) are labelled buttons, not bare icons.
- **Every editor is in the settings menu** (Tile editor, Layer editor, Map
  editor): the tiles and the map have the same top-right buttons - Help (?)
  and Settings (the gear) - and the gear opens the same menu on both. One
  name and one icon per editor everywhere (Map editor = `mdi:pencil-ruler`).
- **Every editor behaves the same**: the same gestures and selection rules
  (the first tap after a drag starts a new selection; dragging near the
  map's edge scrolls it), Help + gear top right, Save changes / Discard /
  Keep editing, a picker in the title. **Save changes saves and keeps the
  editor open**; X leaves (asking first if anything is unsaved). Where one can't (the tile grid has no
  free dragging) it says so in its Help.
- **Leaving an editor goes back to where you came from** - the same editor,
  map, layer and view. E.g. the Layer Editor's Layer settings link (Help:
  add / rename / delete layers) opens Map settings in the Map editor;
  closing Map settings (after saving or discarding) returns to the Layer
  Editor as it was.
- **Every screen and editor has a Help page** behind its ? button; how-to
  text doesn't sit on the screen itself (a line that says what happens next,
  like "Now tap where it should go" while moving a tile, is fine).
- **Dialog backdrops ignore the tap that opened them** (touch screens deliver
  that click after the finger lifts).
- **A dialog opened from a dialog** sits on the next layer (`--z: 30`); the one
  underneath keeps its draft.
- **Show full names next to short names** wherever a short name is edited or
  reviewed (plus area / entity ID for context).
- **Room-Tiles-wide settings** (apply everywhere) and **this-device settings**
  are kept apart and labelled as such.
- **Hints only when they matter** (e.g. the reduced-motion line only when the
  device asks for reduced motion).
- **Right-click = long press** wherever a long press does something (see
  Input). Double-click is not used: its first click already acts (toggles),
  and telling the two apart would delay every single click.
  The browser's own menu never opens in Room Tiles (a touch long press
  fires it too - e.g. on the pop-up tile it just opened), except in text
  fields and links.
- **Undo / redo** in the map editor (markers now, zones / walls / shapes
  later): every change in the editing session, a whole drag = one step, ~100
  steps, Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y; Save commits and clears it, Cancel
  discards all. Not in the tile editor (one small change; Cancel covers it).
- **Controls send to HA only on direct user input** - see DESIGN.md "Sending
  changes to HA".

- **A button inside a settings dialog never closes it or turns it into
  something else**. Choices that reshape what's being
  edited (e.g. an appliance's tile: one tile / separate) are cards at the
  TOP of the dialog; picking one only changes what's shown below; the
  change happens on Save.

- **The Appliances dot** (settings menu): lit whenever ANYTHING on the
  Appliances page hasn't been set up yet - found appliances, pool / spa
  systems, vacuums, and any kind added later. A new kind
  of device on that page must be counted in the dot too.

- **The Settings dot** (the gear, on every screen incl. the Map editor):
  lit whenever any row in its menu has a dot (Appliances, Short names...).
  A new menu dot must be counted there too. The panels: the same yellow dot
  on their gear (tiles and map) when a device waits to be set up, and a
  line at the bottom of their settings saying so (set up on the dashboard,
  where nothing can be done on a panel): opening the settings clears the
  dot until another device is found; the line stays while one waits.

- **The Panels dot** (settings menu, shown once there's a panel): a panel
  update waiting for Install - only with "Update panels automatically" off
  (on, the panels take it themselves).

- **Short names to review**: new ones raise one HA notification ("Room
  Tiles: short names to review") linking to the Short names dialog; it goes
  once nothing is waiting. Same rules as found devices below.

- **New device found while running**: a compatible appliance, vacuum or
  pool appearing in HA also raises one HA notification ("Room Tiles found
  compatible appliances") linking to the Appliances page - one phrase, never
  a list of devices (or, for short names, of names). It goes once
  nothing is waiting (set up or ignored); devices already waiting at
  startup don't notify again.

- **Appliances page: Ignore, never Remove**. Every found
  card has Ignore next to Set up (the accent pill); a set-up item's settings end with Ignore
  (two taps - its tiles go empty) instead of Remove. Ignored items wait in
  the Ignored section at the bottom of the page with Set up, and the dot
  never counts them. Same for appliances, pools / spas and vacuums.

- **A dialog's top edge stays put** once it's open: content that changes
  height (a filter changing a list, options appearing) must not move the
  control being used. It only moves up when the dialog would run off the
  bottom; rotating / resizing centres it again (dialog-pin.ts, on every
  dialog).
- **Settings come in framed groups**: in every web
  settings dialog, settings that belong together sit in a framed group
  (`groupStyles` in ui.ts - `.group` + `.group-head`: a darker panel with a border, headed
  by an icon + title) - like the appliance dialog's unit cards - not a flat
  list under small section labels.

- **Before sending anything back** (reports, unknown states, recordings):
  a confirmation that shows the exact data, says what's NOT in it (no names,
  serial numbers, addresses, times of day), and says how it's sent: "As a
  public GitHub issue from your GitHub account - you need an account and to
  be signed in. Anyone can see the issue and your public GitHub profile;
  your email isn't shown unless it's public on your profile." Nothing goes
  without pressing Send (DESIGN.md "Privacy: what reports send").

- **A newer dashboard installed** (an update, a rebuild - an open page keeps
  its old code): checked on reconnect, when the page comes back on screen
  and every minute. The bar "Room Tiles was updated. [Reload]" shows; the
  page never reloads by itself (whoever has it open - a wall tablet,
  someone reading - decides; frontend/src/no-auto-reload.test.ts). A
  dialog opened from a link (appliances, short names) opens again after
  the Reload.
- **An update HA hasn't restarted for** (new integration files on disk, HA
  still running the old ones - update_watch.py): the bar says "Restart
  Home Assistant to finish updating Room Tiles." with a Restart button for
  admins (one confirm), and the page does NOT reload onto the new dashboard
  meanwhile. After that Restart (the user's own) the page reloads. HA
  also gets a repair that restarts on Fix - unless HACS raised its own restart repair for
  Room Tiles (one message, not two).

## Look

- **Colours only from `theme.ts` tokens** (`--rt-*`) - CI rejects hard-coded
  colours and HA theme variables. Dark only in v1; code stays theme-ready.
- **Art through `assetUrl()`**; on/off alpha only; 256-colour palette.
- **Touch targets** at least ~36 px; **text** never below ~0.75 rem.
- **Top bar**: menu, area name, area lights (Auto configure + Done while
  editing), settings -
  nothing else; anything occasional goes in the settings menu.
- **Top bar buttons are framed** (button colour, 1 px tile-border frame,
  rounded) - the board's and the map's, the map's back and close too; a
  dialog's own X stays plain on the dashboard. The panels frame every close,
  dialogs' too (one look for close on a panel).
- **The panels' top bars are the dashboard's**: the board's - area name
  with its triangle, More tiles, the map, then area lights (when the area
  has some), Help, settings; editing - the name, a hint, Done, Help,
  settings; the map's - back, title, its Map and Layer groups (framed, led
  by their name; collapsing to "current ▾" with a list when they don't fit,
  layers first; scrolling sideways as a last resort - nav-fit.ts), then
  Help, settings, close.
  No menu or full-screen button there. The panels' Help pages are the
  dashboard's for touch, edited to what the panel has: its own lines where
  it differs (zooming with the zoom box, its settings, adding a room by
  tapping it), and what it lacks left out (full screen, the HA Card, the
  queue's Rooms list and order arrows, Auto configure).
- **A name that opens a list shows the drop-down triangle** (mdi:menu-down)
  right after it - the area's name, the map's title - on the dashboard and
  the panels alike.
- **Phone first**: every screen must work in portrait at ~360 px wide.
- **Stay inside the safe area** (notch, status bar, home bar): full-height and
  fixed elements use `env(safe-area-inset-*)` - the shared dialog does.
