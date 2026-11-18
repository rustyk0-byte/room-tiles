"""Brand presets for appliance profiles (see appliance.py for the fields).

State lists come from each integration's SOURCE (HA core enum options, the
brand SDK), so they're complete; what a state MEANS is the uncertain part:
anything unlisted counts as running, and `verified` marks presets someone
with the hardware has confirmed. Adding a brand = a preset here + its finder
in appliance_detect.py + its row in docs/SUPPORTED.md (keep that page in step:
status, tested models, its column in the features-by-model table).
"""

from __future__ import annotations

from .appliance import Preset

# HA core `lg_thinq`: sensor `current_state` (enum). Running states not listed
# are washing / drying by type. `initial` / `detecting`: load not sized yet -
# the finish time is a placeholder; `reserved` = waiting for a delayed start.
_LG_OFF = frozenset({"power_off", "end", "reserved"})
_LG_NO_TIME = frozenset({"initial", "detecting", "pause", "frozen_prevent_pause"})

LG_THINQ_WASHER = Preset(
    running=frozenset({"running", "detecting", "spinning", "initial", "rinse_hold", "prewash", "rinsing", "add_drain", "frozen_prevent_initial", "drying", "refreshing", "frozen_prevent_running", "detergent_amount"}),
    id="lg_thinq_washer",
    name="LG ThinQ washer",
    appliance="washer",
    off=_LG_OFF,
    phases={"drying": "drying"},  # washer-dryer combos
    paused=frozenset({"pause", "frozen_prevent_pause"}),
    no_time=_LG_NO_TIME,
    labels={"detergent_amount": "detergent", "add_drain": "draining", "rinse_hold": "rinse_hold"},
    time="finish",
    verified=True,
    confirmed_models=("F3P2CYUBE",),
)

LG_THINQ_DRYER = Preset(
    running=frozenset({"wrinkle_care", "initial", "running", "cooling"}),
    id="lg_thinq_dryer",
    name="LG ThinQ dryer",
    appliance="dryer",
    off=_LG_OFF,
    no_time=_LG_NO_TIME,
    labels={"wrinkle_care": "wrinkle_care"},
    time="finish",
    verified=True,
    confirmed_models=("RV13D4ASJW",),
)

# GE Home (SmartHQ, ha_gehome): `cycle_state` reads N/A, Pre Wash, Sensing,
# Main Wash, Drying, Sanitizing, Rinsing, Pause (gehomesdk ErdCycleState).
# `time_remaining`: a duration (its unit_of_measurement).
GE_HOME_DISHWASHER = Preset(
    running=frozenset({"pre wash", "sensing", "main wash", "drying", "sanitizing", "rinsing"}),
    id="ge_home_dishwasher",
    name="GE Home dishwasher",
    appliance="dishwasher",
    phases={"drying": "drying"},
    time="duration",
    verified=False,
)

# Fisher & Paykel DishDrawers through GE Home. Measured on a DDD616 (2026-10):
# on non-timed programmes (Auto, Rinse) the countdown holds a 1 min
# placeholder for the whole cycle - only a moving countdown counts; Rinsing
# then takes ~66 min and Drying ~32 min from when that phase starts (Main
# Wash varies too much to estimate). No pause state.
FP_DISHDRAWER = Preset(
    running=frozenset({"pre wash", "sensing", "main wash", "drying", "sanitizing", "rinsing"}),
    id="fp_dishdrawer",
    name="Fisher & Paykel DishDrawer",
    appliance="dishwasher",
    phases={"drying": "drying"},
    time="duration",
    duration_unit="h",
    countdown_must_move=True,
    phase_estimates={"rinsing": 66, "drying": 32},
    verified=True,
    confirmed_models=("DDD616",),
)

# ---- beta presets, built from each integration's source (2026-11-09) ----------
# Not yet confirmed on real machines: unknown states still count as running,
# and setup says the model is beta.

# Samsung - HA core `smartthings`: the JOB state (wash / rinse / spin /
# drying...) gives the phase; it doesn't show a pause (the machine state
# does - not read yet). `completion_time` = finish timestamp.
_ST_OFF = frozenset({"none", "finish", "delay_wash"})
_ST_LABELS = {"ai_wash": "ai_wash", "ai_rinse": "ai_rinse", "ai_spin": "ai_spin", "ai_drying": "ai_drying"}
SMARTTHINGS_WASHER = Preset(
    running=frozenset({"air_wash", "ai_rinse", "ai_spin", "ai_wash", "cooling", "drying", "pre_wash", "rinse", "spin", "wash", "weight_sensing", "wrinkle_prevent", "freeze_protection"}),
    id="smartthings_washer",
    name="Samsung (SmartThings) washer",
    appliance="washer",
    off=_ST_OFF,
    phases={"drying": "drying"},
    no_time=frozenset({"weight_sensing"}),
    labels=_ST_LABELS,
    time="finish",
)
SMARTTHINGS_DRYER = Preset(
    running=frozenset({"cooling", "drying", "wrinkle_prevent", "weight_sensing", "dehumidifying", "ai_drying", "sanitizing", "internal_care", "freeze_protection", "refreshing"}),
    id="smartthings_dryer",
    name="Samsung (SmartThings) dryer",
    appliance="dryer",
    off=_ST_OFF | frozenset({"finished"}),
    no_time=frozenset({"weight_sensing"}),
    labels=_ST_LABELS,
    time="finish",
)
SMARTTHINGS_DISHWASHER = Preset(
    running=frozenset({"air_wash", "cooling", "drying", "pre_drain", "pre_wash", "rinse", "spin", "wash", "wrinkle_prevent"}),
    id="smartthings_dishwasher",
    name="Samsung (SmartThings) dishwasher",
    appliance="dishwasher",
    off=_ST_OFF,
    phases={"drying": "drying"},
    time="finish",
)

# GE Appliances / GE Profile laundry - `ge_home` (gehomesdk MachineState):
# Off, Standby, Run, Finished, Paused, Delay Run, Delay Paused, Drain
# Timeout, Commissioning, Bulk Flush, Clean Speak, ---.
_GE_LAUNDRY_OFF = frozenset({"standby", "---", "finished", "delay run", "delay paused", "commissioning"})
GE_HOME_WASHER = Preset(
    running=frozenset({"run", "bulk flush", "clean speak"}),
    id="ge_home_washer",
    name="GE Home washer",
    appliance="washer",
    off=_GE_LAUNDRY_OFF,
    error=frozenset({"drain timeout"}),
    labels={"run": "running"},
    time="duration",
)
GE_HOME_DRYER = Preset(
    running=frozenset({"run", "bulk flush", "clean speak"}),
    id="ge_home_dryer",
    name="GE Home dryer",
    appliance="dryer",
    off=_GE_LAUNDRY_OFF,
    error=frozenset({"drain timeout"}),
    labels={"run": "running"},
    time="duration",
)

# Whirlpool (also Maytag, KitchenAid, Amana) - HA core `whirlpool`: washer /
# dryer state, including cycle steps; `end_time` = finish timestamp.
_WP_OFF = frozenset(
    {
        "standby",
        "setting",
        "delay_countdown",
        "delay_paused",
        "smart_delay",
        "complete",
        "cancelled",
        "system_initialize",
        "demo_mode",
        "life_test",
        "customer_focus_mode",
        "service_diagnostic_mode",
        "factory_diagnostic_mode",
    }
)
_WP_LABELS = {
    "running_maincycle": "running",
    "running_postcycle": "finishing",
    "cycle_filling": "filling",
    "cycle_washing": "washing",
    "cycle_rinsing": "rinsing",
    "cycle_spinning": "spinning",
    "cycle_sensing": "sensing",
    "cycle_soaking": "soaking",
}
WHIRLPOOL_WASHER = Preset(
    running=frozenset({"running_maincycle", "running_postcycle", "cycle_filling", "cycle_washing", "cycle_rinsing", "cycle_spinning", "cycle_sensing", "cycle_soaking"}),
    id="whirlpool_washer",
    name="Whirlpool washer",
    appliance="washer",
    off=_WP_OFF,
    paused=frozenset({"pause", "smart_grid_pause"}),
    error=frozenset({"exception", "hard_stop_or_error", "power_failure"}),
    no_time=frozenset({"cycle_sensing"}),
    labels=_WP_LABELS,
    time="finish",
)
WHIRLPOOL_DRYER = Preset(
    running=frozenset({"running_maincycle", "running_postcycle", "cycle_sensing"}),
    id="whirlpool_dryer",
    name="Whirlpool dryer",
    appliance="dryer",
    off=_WP_OFF,
    paused=frozenset({"pause", "smart_grid_pause"}),
    error=frozenset({"exception", "hard_stop_or_error", "power_failure"}),
    no_time=frozenset({"cycle_sensing"}),
    labels=_WP_LABELS,
    time="finish",
)

# Bosch, Siemens, Neff, Gaggenau - HA core `home_connect`: operation state
# (inactive / ready / delayedstart / run / pause / actionrequired / finished /
# error / aborting), a door sensor (closed / locked / open), finish time.
_HC_OFF = frozenset({"inactive", "ready", "delayedstart", "finished", "aborting"})
_HC_LABELS = {"run": "running", "actionrequired": "needs_you"}
HOME_CONNECT_WASHER = Preset(
    running=frozenset({"run"}),
    id="home_connect_washer",
    name="Home Connect (Bosch / Siemens) washer",
    appliance="washer",
    off=_HC_OFF,
    paused=frozenset({"pause", "actionrequired"}),
    labels=_HC_LABELS,
    time="finish",
)
HOME_CONNECT_DRYER = Preset(
    running=frozenset({"run"}),
    id="home_connect_dryer",
    name="Home Connect (Bosch / Siemens) dryer",
    appliance="dryer",
    off=_HC_OFF,
    paused=frozenset({"pause", "actionrequired"}),
    labels=_HC_LABELS,
    time="finish",
)
HOME_CONNECT_DISHWASHER = Preset(
    running=frozenset({"run"}),
    id="home_connect_dishwasher",
    name="Home Connect (Bosch / Siemens) dishwasher",
    appliance="dishwasher",
    off=_HC_OFF,
    paused=frozenset({"pause", "actionrequired"}),
    labels=_HC_LABELS,
    time="finish",
)

# Miele - HA core `miele`: status (off / on / programmed / waiting_to_start /
# in_use / pause / program_ended / failure / program_interrupted / idle /
# rinse_hold / service / not_connected...), a door sensor, finish time.
_MIELE_OFF = frozenset({"off", "on", "programmed", "waiting_to_start", "program_ended", "idle", "service", "reserved"})
_MIELE_LABELS = {"in_use": "running", "rinse_hold": "rinse_hold", "program_interrupted": "interrupted"}
MIELE_WASHER = Preset(
    running=frozenset({"in_use"}),
    id="miele_washer",
    name="Miele washer",
    appliance="washer",
    off=_MIELE_OFF,
    paused=frozenset({"pause", "rinse_hold", "program_interrupted"}),
    error=frozenset({"failure"}),
    hold=frozenset({"not_connected"}),
    labels=_MIELE_LABELS,
    time="finish",
)
MIELE_DRYER = Preset(
    running=frozenset({"in_use"}),
    id="miele_dryer",
    name="Miele dryer",
    appliance="dryer",
    off=_MIELE_OFF,
    paused=frozenset({"pause", "program_interrupted"}),
    error=frozenset({"failure"}),
    hold=frozenset({"not_connected"}),
    labels=_MIELE_LABELS,
    time="finish",
)
MIELE_DISHWASHER = Preset(
    running=frozenset({"in_use"}),
    id="miele_dishwasher",
    name="Miele dishwasher",
    appliance="dishwasher",
    off=_MIELE_OFF,
    paused=frozenset({"pause", "program_interrupted"}),
    error=frozenset({"failure"}),
    hold=frozenset({"not_connected"}),
    labels=_MIELE_LABELS,
    time="finish",
)

# Matter (any brand) - HA core `matter`, Operational State cluster: the
# `operational_state` sensor (stopped / running / paused / error, plus
# vendor-specific states - those count as running), `estimated_end_time`
# (finish timestamp). Matter 1.2 washers + dishwashers, 1.3 dryers.
_MATTER = {
    "off": frozenset({"stopped"}),
    "paused": frozenset({"paused"}),
    "error": frozenset({"error"}),
    "running": frozenset({"running"}),
}
MATTER_WASHER = Preset(id="matter_washer", name="Matter washer", appliance="washer", time="finish", **_MATTER)
MATTER_DRYER = Preset(id="matter_dryer", name="Matter dryer", appliance="dryer", time="finish", **_MATTER)
MATTER_DISHWASHER = Preset(id="matter_dishwasher", name="Matter dishwasher", appliance="dishwasher", time="finish", **_MATTER)

# Any appliance on a smart plug with power monitoring (generic): the unit's
# status entity is the plug's POWER sensor (W); running above its threshold,
# finished once it has stayed below for its off-after minutes.
POWER_WASHER = Preset(id="power_washer", name="Smart plug (power)", appliance="washer", time="none", power=True, labels={"running": "running"})
POWER_DRYER = Preset(id="power_dryer", name="Smart plug (power)", appliance="dryer", time="none", power=True, labels={"running": "running"})
POWER_DISHWASHER = Preset(id="power_dishwasher", name="Smart plug (power)", appliance="dishwasher", time="none", power=True, labels={"running": "running"})

PRESETS: dict[str, Preset] = {
    p.id: p
    for p in (
        LG_THINQ_WASHER,
        LG_THINQ_DRYER,
        GE_HOME_DISHWASHER,
        FP_DISHDRAWER,
        SMARTTHINGS_WASHER,
        SMARTTHINGS_DRYER,
        SMARTTHINGS_DISHWASHER,
        GE_HOME_WASHER,
        GE_HOME_DRYER,
        WHIRLPOOL_WASHER,
        WHIRLPOOL_DRYER,
        HOME_CONNECT_WASHER,
        HOME_CONNECT_DRYER,
        HOME_CONNECT_DISHWASHER,
        MIELE_WASHER,
        MIELE_DRYER,
        MIELE_DISHWASHER,
        MATTER_WASHER,
        MATTER_DRYER,
        MATTER_DISHWASHER,
        POWER_WASHER,
        POWER_DRYER,
        POWER_DISHWASHER,
    )
}
