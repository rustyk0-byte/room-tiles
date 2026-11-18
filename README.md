# Room Tiles

Room-by-room control tiles and house maps for Home Assistant: a dashboard for
phones, tablets and computers, and firmware for ESP32 panels (on a wall or a desk).

> **Work in progress - not ready for use yet.**

Each room (a Home Assistant area) gets a board of large, touch-friendly
tiles: lights, fans, blinds, locks, thermostats, and live tiles for your
washer, dryer, dishwasher, pool / spa and robot vacuum. A map of your home
shows the same things where they are.

- Supported brands and models: [docs/SUPPORTED.md](docs/SUPPORTED.md)
- For contributors: [docs/DESIGN.md](docs/DESIGN.md) · [docs/UI.md](docs/UI.md)

## What you need

- Home Assistant **2026.11** or newer.
- Your devices in Home Assistant **areas** - Room Tiles works room by room.

## Install

1. Settings › **Marketplace** › **Add from link**, and enter
   `rustyk0-byte/room-tiles` (it's an **Integration**). Adding a repository
   by link needs the Marketplace's GitHub connection (Settings › Devices &
   services › Marketplace).
2. Install **Room Tiles**, then restart Home Assistant.

Updates show under Settings › **Updates**, like Home Assistant's own; the
ESP32 panels' firmware comes with them.

(Or download `room_tiles.zip` from a release, unzip it into
`config/custom_components/room_tiles`, and restart.)

## Set up

1. Settings › **Devices & services** › **Add integration** › **Room Tiles**.
2. Choose the areas to include, and submit.
3. Follow the **Open Room Tiles** link (it's also in the sidebar).

Every area gets a board of its tiles, and you get a starter map to draw over.

Supported appliances, pools and vacuums Room Tiles finds wait in the
settings menu (the gear) under **Appliances** - set each one up there.

## Using it

- Tap the room name to switch rooms (or open the map).
- The **lights button** at the top switches the room's lights.
- A tile's switch turns it on and off; its roller sets brightness, position,
  speed or temperature; the rest of the tile opens Home Assistant's controls.
- On the map, tap a marker to switch it; long-press it for its tile.
- The **?** button explains the screen you're on.

## Make it yours

Everything is in the settings menu (the gear):

- **Tile editor** - choose what each tile shows, and move tiles around.
- **Areas** - show, hide and order areas, and set what each lights button
  switches.
- **Short names** - the names tiles and the map show.
- **Appliances** - set up the washers, dryers, dishwashers, pools and robot
  vacuums Room Tiles found. Something wrong with one? Its **Report a
  problem** sends what went wrong with a recent cycle, pump run or clean,
  or records the next one; a beta one also has **Report how it went** -
  you check everything before it goes to GitHub.
- **Map editor** - draw your home: walls, rooms, doors, windows, a yard - or
  trace a photo of your floor plan.
- **Layer editor** - place markers on the map.
- **Panels** - your ESP32 panels and their updates (see below).
- **Send feedback** - report a bug, suggest an idea or ask a question (see
  below).

Editing is best on a tablet or computer; each editor's **Help** (?) shows how.

### Area lights

Each area's **lights button** (at the top, on the dashboard and on touch
panels) switches that area's lights together. Choose them on the
dashboard: settings menu › **Areas** › **Area lights…** beside the area:

- **All lights in this area, except the unticked ones** (the default) -
  every light Home Assistant has in that area. Room Tiles makes a light that
  switches them together, "<Area> Area Lights (Room Tiles)"; untick any to
  leave it out.
- **One entity (e.g. a light group)** - your own light or group instead.
- **None** - no lights button for this area.

Area lights are set on the dashboard only. ESP32 panels use what's set
there - for their lights button, and for **Screen off when the following
area lights are off** (see Panel settings).

### Feedback and reports

- **Send feedback** (settings menu) - report a bug, suggest an idea or ask
  a question. For a bug, say where it happened: this dashboard, a touch
  panel or somewhere else. A problem with an appliance, pool or vacuum goes
  to its own **Report a problem**, which can send what it did.
- **Report a problem** (Appliances, on each appliance's, pool's and
  vacuum's card) - say what went wrong and when: a recent cycle, pump run
  or clean, or for a pool the last 6 or 24 hours. Or choose **Record the
  next cycle**: Home Assistant records it, and lets you know when it's
  ready to send.
- **Report how it went** (Appliances, on a card marked "Beta") - for a
  model, or a pool setup, not confirmed yet: how it went, which features
  work, and a recent cycle's data. That's how a beta model gets confirmed.
- **Unknown states** - when an appliance shows a state Room Tiles doesn't
  know, its card asks what it means; **Also tell Room Tiles** sends your
  answer so the next release knows it.

A bug report adds what helps find it: on this dashboard, your browser and
Room Tiles' recent errors on the page; on an ESP32 panel, its model,
firmware, memory and recent restarts.

Everything goes to Room Tiles as a public GitHub issue, posted from your
own GitHub account, and you see exactly what it holds first. Reports never
hold names, addresses, serial numbers or times of day - only the words you
write, as you wrote them (anything in them that looks personal is pointed
out, so you can remove it).

Writing an issue on GitHub yourself? Home Assistant's **Download
diagnostics** (Settings › Devices & services › Room Tiles › ⋮) gives a file
to attach: how Room Tiles is set up - versions, tile kinds, panels,
appliance presets - with no names or entity ids.

### Panel or dashboard?

Everyday use works on both: switching rooms, tiles, the lights button, the
map. Some things live in only one place:

**Only on the dashboard** (phone, tablet or computer):
- Map editor and Layer editor
- Areas (with each area's **Area lights**) and Short names
- Appliances - setting up washers, dryers, dishwashers, pools and vacuums,
  and **Report a problem** with one
- Panels - your panels' updates, and **Update panels automatically**
- Send feedback
- Animations and full screen (each browser's own)

**Only on a panel** (each panel's own):
- Screen brightness, Go idle after, When idle and the 24-hour clock
- Change Wi-Fi and Restart panel

**On both:** the Tile editor (on a panel: the room it shows), Theme
and Language - each device keeps its own choice.

**In Home Assistant**, on a panel's device page: its update (Settings ›
Updates), its Wi-Fi chip's version, and **Factory Reset**.

Nothing Room Tiles creates is shown to Alexa, Google Assistant or Assist
unless you expose it yourself.

### Undo a removal

Removing Room Tiles keeps a copy of your setup in the `room_tiles_backups`
folder (in Home Assistant's config folder). To bring it back, add Room
Tiles again, then run the **Room Tiles: Import data** action (Developer
tools › Actions) with the copy's name, like
`room_tiles_backups/removed-20261115-201337.json`.

## Languages

Room Tiles follows Home Assistant's language: English, Deutsch, Español,
Français, Italiano, Nederlands and Português. A panel can have its own
(its settings › **Language**). The translations are drafts - corrections are
very welcome: see [CONTRIBUTING.md](CONTRIBUTING.md).

## ESP32 panels

ESP32 touch panels running Room Tiles' own firmware, showing the same
boards and maps, are part of this project (boards: [docs/SUPPORTED.md](docs/SUPPORTED.md)). Mount one on a
wall or stand it on a desk: 3D-printable desk stands for the 7" and 10.1"
are in [hardware/desk-stand](hardware/desk-stand/README.md).
A tablet or any other screen with a web browser doesn't need this: it runs
the dashboard.
### Install the firmware

1. Plug the panel into your computer with a USB-C cable (a data cable,
   not a charge-only one).
2. In **Chrome or Edge** on that computer, open the
   [install page](https://rustyk0-byte.github.io/room-tiles/).
3. Pick your panel - its size, and the board version printed on its back
   ("V1.2") - and press **Install**. Choose the panel's port when the browser
   asks, and let it finish (a few minutes). It erases what the panel ran
   before.
4. If the page then offers to connect the panel to Wi-Fi, you can do it
   right there (else the panel helps you - see below). On the round panel
   the page first says the USB port has changed: select the port again to
   continue, or just close the page.

Then unplug it, and power it where it will live.

> **The panel's Wi-Fi chip gets updated too.** The CrowPanel Advanced
> boards (not the round one) have a separate Wi-Fi chip (an ESP32-C6) with its own firmware, and it has to
> match the panel's firmware. Room Tiles' panel firmware carries the
> matching Wi-Fi chip firmware and installs it when the chip has an older
> version: on a new panel's first start, and after a panel update that
> brings a newer one. This replaces the Wi-Fi chip firmware the board came
> with, and it can't be skipped - the panel's Wi-Fi needs the matching
> version. It never installs an older version, and tries each version only
> once. The chip's version is on the panel's device page in Home Assistant.
> If you later put other firmware on the panel, that firmware may need its
> own Wi-Fi chip version.

### Pick its language

The first time a panel starts, it asks for its language. Tap yours. It's
the panel's language from then on; you can change it later in its settings.

Right after, a new panel may update its own Wi-Fi chip (see the note
above) - "Updating the Wi-Fi chip…" for about a minute, then it restarts by
itself. Leave it plugged in.

### Connect a panel to Wi-Fi

Then, with no Wi-Fi yet, its screen shows the name of the panel's own Wi-Fi
network, such as `room-tiles-a1b2c3`.

1. On your phone, open the Wi-Fi settings and join that network.
2. Stay on the Wi-Fi settings screen for a little while - your phone opens
   the panel's Wi-Fi page by itself. (If it doesn't, open your browser and go
   to `http://192.168.4.1`.) Pick your home Wi-Fi and enter its password.
3. The panel joins your Wi-Fi, and your phone goes back to its usual network.

### Add the panel to Home Assistant

Once it's on your Wi-Fi, the panel says **Add this panel in Home
Assistant**, with its name, such as **Room Tiles Panel a1b2c3**:

> **Did this board run ESPHome before (your own firmware, or Elecrow's)?**
> Delete its old device in Home Assistant first: Settings › Devices &
> services › **ESPHome** › the old device › ⋮ › **Delete**. Then unplug the
> panel and plug it back in. Otherwise Home Assistant recognizes the board
> and offers **Reconfigure** for the old device instead of **Add** - and
> Room Tiles can't finish setting it up (the panel stays on "Connecting to
> Home Assistant…"). If that already happened: delete the device, unplug
> the panel, plug it back in, and choose **Add**.

1. Make sure the Room Tiles integration is installed and set up (above).
2. In Home Assistant, go to Settings › **Devices & services**. The panel
   shows up under **Discovered** with that name.
3. Select **Add** (never Reconfigure) and confirm.

A minute later the panel has its look and wording. If its device has no
area in Home Assistant, the panel asks which area to show.

### Panel settings

Tap the gear on the panel:

- **Screen brightness**, and **Go idle after** - how long untouched before
  it goes idle (1 minute on a new panel; **Never** keeps it bright - an
  automatic update then waits for 10 minutes untouched, see Updates).
- **When idle** - the screen goes off, or shows a clock (digital, analog or
  the theme's), at its own **Brightness** (a new panel: the digital clock,
  dimmed). **Animations keep tiles visible**
  keeps the tiles up, dimmed, while something on them is moving - a running
  washer, say. **Screen off when the following area lights are off**
  turns the screen off instead while the room the panel is in is dark -
  the area of the panel's device in Home Assistant (set on its device
  page), whichever area it's showing - by that area's lights as set on the
  dashboard (see Area lights). The clock comes back when they're turned
  on. Under the switch, the panel names that area.
- **24-hour clock** - for the clock in the top bar and the digital idle
  clock.
- **Theme**, **Language**, **Tile editor** (this room's tiles, right on the
  panel), **Change Wi-Fi** and **Restart panel**.

To show another room, tap the room's name at the top left.

To start a panel over as new (to give it away, or set it up again): on its
device page in Home Assistant, turn on **Factory Reset** and press it. It
forgets its Wi-Fi, its settings and its place in Home Assistant, then starts
like a new panel - remove the device from Home Assistant before adding it
again.

### Updates

Panels update themselves when you update Room Tiles - this is the
dashboard's **Update panels automatically** (gear › **Panels**), on unless
you turn it off. Each panel waits until nobody's using it:
- it goes idle (its screen off, or its clock or dimmed tiles showing) - the
  update starts then;
- set to never go idle (**Go idle after: Never**), it waits for 10 minutes
  with no touch (and, on the round panel, no turn of the knob) - each use
  starts the 10 minutes over.

Until then, the Panels page shows **Updates when nobody's using it** beside
the panel.

Then it shows "Downloading the update…" and "Installing the update…",
restarts (a minute or two) and comes back to its board. Once it has
started, a touch doesn't stop it. A panel that's dark when its update
starts stays dark.

To update a panel now, while it's in use, press **Install** - on the
Panels page, or on its card under Settings › **Updates** - it starts right
away. With automatic updates turned off, a panel waits for that
**Install**. The card is **Room Tiles firmware**, with the Room Tiles
version it brings, like 0.1.1. (A panel too old to work with your Room
Tiles at all updates right away.)

An update can bring a newer Wi-Fi chip firmware too (see the note under
ESP32 panels): after restarting, the panel shows "Updating the Wi-Fi chip…"
for about a minute and restarts once more. Leave it plugged in.

### Changing Wi-Fi

- **Wi-Fi down for a while** (a router restarting, an outage): the panel
  shows its own network again - just wait; it goes back to normal once your
  Wi-Fi is back.
- **New router or password:** join the panel's network and pick the new one,
  as above.
- **Another network:** on the panel, gear › **Change Wi-Fi**. It forgets its
  network and restarts - set it up as above.
- **Stuck on "Connecting to Home Assistant…"** (the wrong network, like a
  guest one): after a minute and a half a **Change Wi-Fi** button appears.
  Tap it twice to start over. (Not added to Home Assistant yet? Do that
  first.)

## Support

Room Tiles is free. If you'd like to help cover its development costs:
[GitHub Sponsors](https://github.com/sponsors/rustyk0-byte) or
[Ko-fi](https://ko-fi.com/roomtiles). GitHub sponsors at $5
a month get their bug reports and ideas looked at first; fixes and features
still go to everyone in the next release.

## License

Apache License 2.0 ([LICENSE](LICENSE)). The panel firmware images are
built with ESPHome and are GPLv3 as a whole; see [NOTICE](NOTICE). The
Room Tiles name and logo aren't covered by the license.
