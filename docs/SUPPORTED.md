# Supported devices

What works with Room Tiles, brand by brand and model by model. Search this
page for your brand, model number or Home Assistant integration.

**Status of a brand / model:**
- **Verified:** confirmed on real hardware by someone using Room Tiles. The
  models listed under "Confirmed models" are the ones confirmed.
- **Beta:** supported, but not confirmed yet. It was built from what can be
  read about the device: the Home Assistant integration's source code and
  documentation, the brand's published state lists, and other owners'
  reports. Until someone with that model confirms it, we can't be sure every
  feature works. Setup and the Appliances page mark beta support "(beta)".
- **Planned:** being designed.
- **Not supported:** setup tells you so, and the features it can't do are
  turned off.

A brand can be verified for one model and beta for others. Only the models
under "Confirmed models" are verified; any other model of that brand is beta
until someone confirms it.

**In the feature tables:**

| Mark | Meaning |
|---|---|
| ✓ | works |
| ~ | works partly (see the note) |
| ✗ | not possible: the device or its integration doesn't provide it |
| ? | should work, not confirmed yet |

Room Tiles setup lists the supported devices it finds in your Home Assistant.
It also tells you what isn't supported, and which features are missing for
your model.

**Keeping this page current:** every change to a brand preset, a finder or
a feature updates this page in the same commit. When someone confirms a
model, it's added under "Confirmed models", and its ? marks become ✓ or ✗.

## Help confirm a beta model

Something wrong with an appliance, pool or vacuum - beta or not? Use
**Report a problem** on its card (Appliances, in Room Tiles' settings
menu): it sends what went wrong with a whole cycle, pump run or clean.

Have a beta model? Its card on the Appliances page says "Beta" and has
**Report how it went**: say how it went, mark each feature of this page's
"Features by model" table as works, partly, doesn't work or not tried, and
add a recent cycle's data (a pool: a pump run or the last hours; a vacuum:
a clean). The brand, model, integration and versions are filled in for you,
and you check everything before it goes to GitHub.

One confirmed cycle is enough to move a model from beta to verified, or to
fix what's wrong. A beta flag only goes away through that report: the
recorded cycle becomes an automatic test, every feature row is checked, and
the model is added to "Confirmed models" in a release.

## ESP32 panels (Room Tiles firmware)

Room Tiles' own firmware runs on the Elecrow CrowPanel Advanced ESP32-P4
(all 1024x600) and on Elecrow's 2.1" round ESP32-S3 panel. Pick the
firmware by the size and the version printed on the board ("V1.2" etc.).

| Panel | Board version | Status |
|---|---|---|
| CrowPanel Advanced 7" | V1.0 | Verified |
| CrowPanel Advanced 7" | V1.1 | Beta: built like V1.2, not tried yet |
| CrowPanel Advanced 7" | V1.2 | Verified |
| CrowPanel Advanced 9" | V1.0, V1.1, V1.2 | Beta: built like the 10.1", not tried yet |
| CrowPanel Advanced 10.1" | V1.1 | Beta: built like V1.2, not tried yet |
| CrowPanel Advanced 10.1" | V1.2 | Verified |
| CrowPanel 2.1" round (ESP32-S3, 480x480, rotary knob) | - | Beta: installed and tried; a room's tiles in one strip, no map or vacuum view |

The 5" ESP32-P4 board isn't supported: its screen is 800x480 on another kind
of display connection (the 7", 9" and 10.1" share 1024x600 and the board).

What changes between board versions: from V1.1 on, the board's Wi-Fi chip
is wired differently (the firmware handles both). V1.1 and V1.2 differ
only in parts Room Tiles doesn't use, so they run the same firmware - V1.1
with the Wi-Fi chip's link at half speed until one is confirmed.

## Everyday devices: any brand

Lights, switches, fans, covers (blinds, shades, garage doors), locks,
thermostats, scenes and scripts use Home Assistant's own standard entities. **Any brand works**
as long as its integration creates these entities.

| Device | Home Assistant entity | Notes |
|---|---|---|
| Lights | `light` | Colour, dimmable or on/off tile, from the light's colour modes. Light groups work. |
| Switches | `switch`, `input_boolean` | |
| Fans | `fan` | |
| Covers | `cover` | Blinds, shades, garage doors. |
| Locks | `lock` | |
| Thermostats | `climate` | |
| Scenes | `scene` | One tap turns the scene on. |
| Scripts | `script` | One tap runs it; lit while it runs. Scripts that ask for inputs can't be tiles. |

## Washers, dryers and dishwashers

Room Tiles works out what the appliance is doing (washing, drying, done, door
open...), its status text and the time left. A finished appliance stays
"done" until it's emptied. Three things can clear it:
- its own door opening, where the model reports its door
- a sensor you pick, e.g. a contact sensor on the laundry door
- a tap on the tile, which always works

### Brands and models

| Brand | Integration | Appliance | Status | Confirmed models | Based on |
|---|---|---|---|---|---|
| LG | LG ThinQ (`lg_thinq`, built into HA) | Washer | Verified for F3P2CYUBE; beta for other models | F3P2CYUBE | Owner testing; the integration's state list |
| LG | LG ThinQ (`lg_thinq`, built into HA) | Dryer | Verified for RV13D4ASJW; beta for other models | RV13D4ASJW | Owner testing; the integration's state list |
| Fisher & Paykel | GE Home / SmartHQ (`ge_home`, custom integration from HACS) | DishDrawer (single or double) | Verified for DDD616; beta for other models | DDD616 (double) | Owner testing, 22 recorded cycles |
| GE Appliances | GE Home / SmartHQ (`ge_home`, custom) | Dishwasher | Beta | none yet | The GE Home SDK's cycle states (gehomesdk) |
| GE Appliances / GE Profile | GE Home / SmartHQ (`ge_home`, custom) | Washer, dryer | Beta | none yet | gehomesdk laundry machine states; ha_gehome's entities |
| Samsung | SmartThings (`smartthings`, built into HA) | Washer, dryer, dishwasher | Beta | none yet | HA's SmartThings integration source (job states) |
| Whirlpool (also Maytag, KitchenAid, Amana) | Whirlpool (`whirlpool`, built into HA) | Washer, dryer | Beta | none yet | HA's Whirlpool integration source |
| Bosch, Siemens, Neff, Gaggenau | Home Connect (`home_connect`, built into HA) | Washer, dryer, washer-dryer, dishwasher | Beta | none yet | HA's Home Connect integration source |
| Miele | Miele (`miele`, built into HA) | Washer, dryer, washer-dryer, dishwasher | Beta | none yet | HA's Miele integration source |
| Any brand with Matter (1.2+ washers / dishwashers, 1.3+ dryers) | Matter (`matter`, built into HA) | Washer, dryer, dishwasher | Beta | none yet | HA's Matter integration source (Operational State) |
| Any appliance on a smart plug that measures power | any (the plug's power sensor) | Washer, dryer, dishwasher - added by hand | Beta | none yet | Generic: running while it draws power, finished after it stays low for a few minutes |

### Features by model

| Feature | LG washer / dryer | F&P DishDrawer | GE dishwasher | GE laundry | Samsung | Whirlpool | Bosch (Home Connect) | Miele |
|---|---|---|---|---|---|---|---|---|
| Running / finished | ✓ | ✓ | ? | ? | ? | ? | ? | ? |
| Cycle step as status text | ✓ | ✓ | ? | ~ ⁴ | ? | ? | ~ ⁴ | ~ ⁴ |
| Time left | ~ ¹ | ~ ² | ? | ? | ? | ? | ? | ? |
| Paused | ✓ | ✗ | ? | ? | ✗ ⁵ | ? | ? | ? |
| Error | ✓ | ✗ | ✗ | ? | ✗ | ? | ? | ? |
| Door open shown, empties it | ✗ ³ | ✓ (per drawer) | ? | ? | ✗ ³ | ✗ ³ | ? | ? |
| Washer + dryer on one tile | ✓ | n/a | n/a | ? | ? | ? | ? | ? |

1. **LG time left:** hidden while the load is being sized and while paused.
   It's a placeholder then.
2. **F&P time left:**
   - Fixed programmes (e.g. Intense) count down for real.
   - Auto and Rinse hold a 1-minute placeholder for the whole cycle. Room
     Tiles ignores it and estimates instead: Rinsing about 66 minutes, Drying
     about 32 minutes. These were measured on a DDD616.
   - Main Wash varies too much to estimate, so no time is shown then.
3. **No door sensor in the integration:** pick a sensor, or tap the tile.
4. **Status text:** these integrations report the machine's state (Running,
   Paused...), not the wash step, so the status says "Running" rather than
   "Rinse". Whirlpool and Samsung do report steps.
5. **Samsung pause:** Room Tiles reads the job state (wash, rinse, spin...),
   which doesn't change when paused.

Any washer and dryer pair into one Laundry tile when there's exactly one of
each, whatever the brands.

**Matter:** the machine type comes from its Matter features (a washer's spin
and rinse settings, a dishwasher's mode) or its name - Matter dryers have
nothing of their own in Home Assistant, so name yours with "dryer" if setup
calls it something else. Status reads Running / Paused / Error (no wash steps).

**Smart plug (generic):** for any appliance Home Assistant can't read. Add it
by hand on the Appliances page and pick the plug's power sensor. It's
running above a threshold (5 W by default) and finished once the power has
stayed below it for a few minutes (3 by default, 20 for a dishwasher, which
dries on almost no power). No time left, no cycle steps.

**On a Laundry tile** the washer shows "Switch over" when it finishes, until
the dryer starts.

### Not supported yet

Other brands and integrations, e.g. Electrolux / Frigidaire, Haier, Beko, and
anything without a Home Assistant integration.

Planned:
- **More brand presets:** wanted, especially from people who own the
  hardware.
- **A generic fallback:** a smart plug's power reading, or any on/off
  entity, for appliances without an integration.

## Robot vacuums

The vacuum tile uses Home Assistant's standard `vacuum` entity, so **any
brand gets the tile**. Setup offers every vacuum on the Appliances page and
says what each can do (alerts, room cleaning).

**Cleaning chosen rooms** works through Home Assistant's `vacuum.clean_area`
action. Each robot room (segment) must be linked to an HA area, under
"Map vacuum segments to areas" in the vacuum's settings. Room Tiles checks
whether a vacuum supports `clean_area`, not its brand. A vacuum without it
gets the tile, but room cleaning is turned off for it.

Several vacuums, on one floor or several, are supported. Each vacuum can have
its own cleaning zones drawn on the house map.

### Brands and models

| Brand | Integration | Status | Confirmed models | Based on |
|---|---|---|---|---|
| Matic | Matter (`matter`) | Verified (tile, alerts, room queue) | Matic robot | Owner testing |
| Other Matter vacuums | Matter (`matter`) | Beta | none yet | The Matter standard; HA's Matter integration |
| Roborock | Roborock (`roborock`, built into HA) | Beta | none yet | HA 2026.3 release notes (`clean_area` support) |
| Ecovacs | Ecovacs (`ecovacs`, built into HA) | Beta | none yet | HA 2026.3 release notes (`clean_area` support) |
| iRobot Roomba | iRobot (`roomba`, built into HA) | Beta, tile only | none yet | HA's iRobot integration (no `clean_area`, checked 2026-11) |

### Features by model

| Feature | Matic | Other Matter | Roborock | Ecovacs | Roomba |
|---|---|---|---|---|---|
| Vacuum tile (state, start / dock) | ✓ | ? | ? | ? | ? |
| Clean chosen rooms (`clean_area`) | ✓ | ~ ¹ | ? | ? | ✗ ² |
| Room queue | ✓ | ~ ¹ | ? | ? | ✗ ² |
| Queue lets go when HA controls the vacuum | ✓ | ~ ¹ | ? | ? | ✗ ² |
| Queue lets go when the vacuum's own app controls it | ✓ | ? ⁴ | ? ⁴ | ? ⁴ | ✗ ² |
| Cleaning zones on the map | ✓ | ~ ¹ | ? | ? | ✗ ² |
| "Needs you" alerts | ✓ | ~ ³ | ✗ | ✗ | ✗ |
| Interrupted vs finished | ✓ | ~ ³ | ✗ | ✗ | ✗ |
| Brand icon | ✓ | generic robot | generic robot | generic robot | generic robot |

1. **Other Matter vacuums:** only robots that report their rooms (the Matter
   Service Area feature).
2. **Roomba:** HA's iRobot integration has no `clean_area` (checked
   2026-11). Room cleaning turns on by itself if it adds it.
3. **Matter extras:** used when the robot reports Matter's operational state
   and error details.
4. **The vacuum's own app:** Room Tiles has to tell "stopped from the app"
   from "finished the room" by the vacuum's states alone. Matic turns idle
   first when stopped or sent home from its app; other brands are untested,
   so their queue still treats idle as a finished room. A report with a
   recent clean helps add a brand.

## Pools and spas

Setup asks how the equipment is laid out:
- **Shared:** the spa sits on the pool, and one pump and one heater switch
  between them.
- **Separate:** each body has its own equipment.
- **Only one:** just a pool, or just a spa.

Separate: a Pool tile and a Spa tile. Only one: that body's tile. Shared:
one Pool / Spa tile that follows whichever is running, plus a Spa Mode
switch. A tile with a heater has a heater button (flame = heat, snowflake
= chill).

### Brands and setups

| Brand | Integration | Status | Confirmed setups | Based on |
|---|---|---|---|---|
| Jandy | iAquaLink (`iaqualink`, built into HA) | Beta (being tested on a shared pool + spa) | none yet | Owner testing under way |
| Pentair | ScreenLogic (`screenlogic`, built into HA): EasyTouch, IntelliTouch, SunTouch | Beta | none yet | HA's ScreenLogic integration source (2026-11) |
| Hayward | OmniLogic (`omnilogic`, built into HA) | Beta, no heating | none yet | HA's OmniLogic integration source (2026-11) |
| Pentair IntelliCenter, Hayward OmniLogic Local | custom integrations | Not supported yet | | |

Setup guesses the equipment layout and always asks you to confirm it:
- **Jandy:** shared when both bodies and both pump switches are there; the
  spa pump switch is spa mode.
- **Pentair:** shared when both bodies and the "Pool" and "Spa" circuits are
  there; the Spa circuit is spa mode, the Pool circuit the pump.
- **Hayward:** separate, each body with its own filter pump.

### Features by setup

| Feature | Jandy iAquaLink | Pentair ScreenLogic | Hayward OmniLogic |
|---|---|---|---|
| Water temperature | ~ ¹ | ? ² | ? |
| Set target temperature | ✓ | ? | ✗ ³ |
| Heater on / off | ✓ | ? | ✗ ³ |
| Chill (heat pump cooling) | ✓ | ✗ | ✗ |
| Spa on / off (spa mode) | ✓ ⁴ | ? ⁵ | ? (its pump) |
| Pool pump on / off | ✓ | ? (Pool circuit) | ? (filter pump) |
| Time to target | ✓ ⁶ | ? | ✗ |
| "Switching" detection | ✓ | ✗ ⁷ | ✗ |
| Pool / spa lights | ✗ ⁸ | ? (light circuits, as light tiles) | ? |

1. **Jandy water temperature:** only the active body's temperature reads;
   the other shows its last reading, dimmed.
2. **Pentair:** the temperature comes from each body's thermostat (its last
   reading, also while that body isn't running).
3. **Hayward heating:** HA's OmniLogic integration has no heater control.
   Setup says so; the tiles show temperature and pumps only.
4. **Jandy spa mode:** the integration's spa pump switch.
5. **Pentair spa mode:** the "Spa" circuit (usual combo plumbing).
6. **Time to target:** worked out by Room Tiles from the temperature changes,
   heating or chilling. It appears once the temperature is clearly moving
   (a slow pool can take a few hours) and counts in hours, also past a day.
   None is shown while the temperature is holding steady.
7. **Switching:** Pentair keeps reporting the last temperature, so a
   pool <-> spa change isn't shown as "switching".
8. **Jandy lights:** pool and spa lights on newer Jandy hardware aren't in
   the integration. Older light circuits may be.
