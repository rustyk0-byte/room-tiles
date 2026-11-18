// Tile behaviour rules - the dashboard's port of the panel firmware's
// panel_logic.h (roller rows, what a row sends to HA, settle windows).
// Keep the two in step; shared test vectors will check them later.

import type { HassEntity, HomeAssistant, TileKind } from "./types";
import { t } from "./i18n";
import { localTile } from "./words";

export interface RollerSpec {
  options: string[];
  prefix: string;
  /** theme token name of the selected value's colour */
  color: string;
}

const range = (from: number, to: number, step: number) => {
  const out: string[] = [];
  for (let v = from; step > 0 ? v <= to : v >= to; v += step) out.push(String(v));
  return out;
};

export const CLIMATE_MIN_F = 65;
export const CLIMATE_MAX_F = 80;
export const FAN_SPEEDS = 6;
export const BRI_OFF_ROW = 20;
export const COV_OPEN_ROW = 0;
export const COV_CLOSED_ROW = 10;
export const LOCK_LOCKED_ROW = 1;
/** HA's CoverEntityFeature.SET_POSITION */
export const COVER_SET_POSITION = 4;

// MIRRORED: firmware/components/room_tiles/board.cpp (rollers) - a change here must be made there too.
/** The roller a kind shows (panel tile.yaml `options`), or undefined. */
export function rollerSpec(kind: TileKind, stateObj?: HassEntity): RollerSpec | undefined {
  switch (kind) {
    case "dimmable_light":
    case "color_light":
      return { options: [...range(100, 5, -5), t("roller.off")], prefix: t("roller.brightness"), color: "light" };
    case "fan":
      return { options: [...range(FAN_SPEEDS, 1, -1), t("roller.off")], prefix: t("roller.speed"), color: "fan" };
    case "cover":
      // only a cover that can be SET to a position (HA's set_position
      // feature, bit 4) gets the roller; one that just opens / closes (many
      // garage doors) has only its open / close switch
      if (stateObj && !((Number(stateObj.attributes.supported_features) || 0) & COVER_SET_POSITION)) return undefined;
      return { options: [t("roller.open"), ...range(10, 90, 10), t("roller.closed")], prefix: t("roller.coverage"), color: "cover" };
    case "lock":
      return { options: [t("roller.unlocked"), t("roller.locked")], prefix: t("roller.doors"), color: "lock" };
    case "climate": {
      // auto (heat / cool) holds a band (low / high): the roller is its
      // middle, moving the whole band (climateBand); its prefix line shows
      // low and high. The colour follows the mode (climateTone).
      const tone = climateTone(stateObj);
      const color = tone === "heat" ? "heatStrong" : tone === "cool" ? "coolStrong" : "text";
      if (climateRange(stateObj)) return { options: range(CLIMATE_MAX_F, CLIMATE_MIN_F, -1), prefix: t("roller.auto"), color };
      return { options: range(CLIMATE_MAX_F, CLIMATE_MIN_F, -1), prefix: tone === "cool" ? t("roller.cool") : t("roller.heat"), color };
    }
    case "water":
      // no heater set up for this body: nothing to set, no roller
      if (stateObj?.attributes.has_heater === false) return undefined;
      return { options: range(104, 80, -1), prefix: t("roller.heat"), color: "heatStrong" };
    default:
      return undefined;
  }
}

/** A thermostat holding a low / high range (auto) rather than one target. */
export function climateRange(stateObj?: HassEntity): boolean {
  const a = stateObj?.attributes;
  if (!a || typeof a.temperature === "number") return false;
  return typeof a.target_temp_low === "number" || typeof a.target_temp_high === "number";
}

// MIRRORED: firmware/components/room_tiles/board_kinds.cpp climate_tone + board.cpp - a change here must be made there too.
/** A thermostat's colour - its MODE, not the moment: heat mode red (running
 *  or not), cool mode blue; auto (heat / cool): red while heating, blue while
 *  cooling, neutral while idle; anything else (dry, fan only) neutral. */
export function climateTone(stateObj?: HassEntity): "heat" | "cool" | "neutral" {
  const mode = stateObj?.state;
  const action = stateObj?.attributes.hvac_action;
  if (mode === "heat") return "heat";
  if (mode === "cool") return "cool";
  if (mode === "heat_cool" || mode === "auto") return action === "heating" ? "heat" : action === "cooling" ? "cool" : "neutral";
  return "neutral";
}

// MIRRORED: firmware/components/room_tiles/board_kinds.cpp + board.cpp (auto band) - a change here must be made there too.
/** Auto's band: low / high now, and the band with its MIDDLE at `mid` - the
 *  width kept, kept within the thermostat's limits, on its step. */
export function climateBand(stateObj: HassEntity | undefined, mid?: number): { low: number; high: number } | undefined {
  const a = stateObj?.attributes;
  const lo = Number(a?.target_temp_low);
  const hi = Number(a?.target_temp_high);
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return undefined;
  if (mid === undefined) return { low: lo, high: hi };
  const width = hi - lo;
  const step = Number(a?.target_temp_step) > 0 ? Number(a?.target_temp_step) : 1;
  const min = Number.isFinite(Number(a?.min_temp)) ? Number(a?.min_temp) : -Infinity;
  const max = Number.isFinite(Number(a?.max_temp)) ? Number(a?.max_temp) : Infinity;
  let low = Math.round((mid - width / 2) / step) * step;
  low = Math.min(Math.max(low, min), max - width);
  const r = (v: number) => Math.round(v * 100) / 100;
  return { low: r(low), high: r(low + width) };
}

export function climateCooling(stateObj?: HassEntity): boolean {
  const mode = stateObj?.state;
  const action = stateObj?.attributes.hvac_action;
  return mode === "cool" || action === "cooling";
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

// MIRRORED: firmware/components/room_tiles/board.cpp (roller row) - a change here must be made there too.
/** The row a tile's roller should show for an entity's HA state (roller_row). */
export function rollerRow(kind: TileKind, stateObj?: HassEntity): number {
  const a = stateObj?.attributes ?? {};
  const on = stateObj ? !["off", "closed", "unavailable", "unknown", "locked"].includes(stateObj.state) : false;
  switch (kind) {
    case "dimmable_light":
    case "color_light": {
      if (stateObj?.state !== "on") return BRI_OFF_ROW;
      const raw = typeof a.brightness === "number" ? a.brightness : 255;
      const pct = Math.floor((raw / 255) * 100);
      return clamp(BRI_OFF_ROW - Math.floor((pct + 4) / 5), 0, BRI_OFF_ROW - 1);
    }
    case "fan": {
      if (stateObj?.state !== "on") return FAN_SPEEDS;
      const pct = typeof a.percentage === "number" ? a.percentage : 100;
      const speed = Math.floor((pct * FAN_SPEEDS) / 100 + 0.5);
      return FAN_SPEEDS - clamp(speed, 1, FAN_SPEEDS);
    }
    case "cover": {
      let pos = typeof a.current_position === "number" ? a.current_position : on ? 100 : 0;
      if (pos <= 0) return COV_CLOSED_ROW;
      if (pos >= 100) return COV_OPEN_ROW;
      return clamp(Math.floor((100 - pos + 9) / 10), COV_OPEN_ROW + 1, COV_CLOSED_ROW - 1);
    }
    case "lock":
      return stateObj?.state === "locked" ? LOCK_LOCKED_ROW : 0;
    case "climate": {
      const band = climateRange(stateObj) ? climateBand(stateObj) : undefined;
      const t = band ? Math.round((band.low + band.high) / 2) : typeof a.temperature === "number" ? Math.round(a.temperature) : NaN;
      return Number.isNaN(t) ? 7 : clamp(CLIMATE_MAX_F - t, 0, CLIMATE_MAX_F - CLIMATE_MIN_F);
    }
    default:
      return 0;
  }
}

export interface Call {
  domain: string;
  service: string;
  data: Record<string, unknown>;
}

// MIRRORED: firmware/components/room_tiles/board.cpp (roller call) - a change here must be made there too.
/** What a roller row sends to HA (roller_action + row_* in panel_logic.h). */
export function rollerCall(kind: TileKind, entity: string, row: number, stateObj?: HassEntity): Call | undefined {
  const t = { entity_id: entity };
  switch (kind) {
    case "dimmable_light":
    case "color_light":
      return row === BRI_OFF_ROW
        ? { domain: "light", service: "turn_off", data: t }
        : { domain: "light", service: "turn_on", data: { ...t, brightness_pct: (BRI_OFF_ROW - row) * 5 } };
    case "fan":
      return row === FAN_SPEEDS
        ? { domain: "fan", service: "turn_off", data: t }
        : // integer-floor bucket bound, like the panels (HA's ordered-list mapping)
          { domain: "fan", service: "set_percentage", data: { ...t, percentage: Math.floor(((FAN_SPEEDS - row) * 100) / FAN_SPEEDS) } };
    case "cover":
      if (row === COV_OPEN_ROW) return { domain: "cover", service: "open_cover", data: t };
      if (row === COV_CLOSED_ROW) return { domain: "cover", service: "close_cover", data: t };
      return { domain: "cover", service: "set_cover_position", data: { ...t, position: 100 - row * 10 } };
    case "lock":
      return { domain: "lock", service: row === LOCK_LOCKED_ROW ? "lock" : "unlock", data: t };
    case "climate": {
      // auto: the band moves, its width kept
      const band = climateRange(stateObj) ? climateBand(stateObj, CLIMATE_MAX_F - row) : undefined;
      if (band) return { domain: "climate", service: "set_temperature", data: { ...t, target_temp_low: band.low, target_temp_high: band.high } };
      return { domain: "climate", service: "set_temperature", data: { ...t, temperature: CLIMATE_MAX_F - row } };
    }
    case "water":
      return { domain: "room_tiles", service: "pool_set_target", data: { entity, temperature: 104 - row } };
    default:
      return undefined;
  }
}

// MIRRORED: firmware/components/room_tiles/board.cpp (switch state) - a change here must be made there too.
/** Whether the tile's switch shows "on" (panel slot_on). */
export function switchOn(kind: TileKind, stateObj?: HassEntity): boolean {
  if (!stateObj) return false;
  switch (kind) {
    case "cover":
      return stateObj.state !== "closed";
    case "lock":
      return stateObj.state === "locked";
    case "climate":
      return stateObj.state !== "off";
    case "water":
      return waterOn(stateObj);
    default:
      return stateObj.state === "on";
  }
}

/** A Room Tiles pool / spa sensor (it can be controlled; a hand-made tile
 *  sensor following the old contract stays read-only). */
export const isPoolSensor = (stateObj?: HassEntity): boolean => typeof stateObj?.attributes.pool === "string";

/** The entity a tile's details (tap / long-press) open: a pool / spa tile
 *  opens its body's heater (HA's thermostat dialog - on / off, set point),
 *  not Room Tiles' own sensor, which has no controls. */
export function detailsEntity(kind: TileKind, entity: string | null | undefined, stateObj?: HassEntity): string | undefined {
  // pool / spa: the body's heater; a vacuum tile on a sensor: the vacuum
  const target =
    kind === "water" ? stateObj?.attributes.heater_entity : kind === "vacuum" && !entity?.startsWith("vacuum.") ? stateObj?.attributes.vacuum : undefined;
  return typeof target === "string" && target ? target : (entity ?? undefined);
}

// MIRRORED: firmware/components/room_tiles/board_kinds.cpp (vacuum tile) - a change here must be made there too.
/** A vacuum tile's status line and its colour class, from a sensor following
 *  the vacuum tile text ("class|status|current|queue") - Room Tiles' own or a
 *  hand-made one - else the vacuum's plain state. */
export function vacuumStatus(stateObj?: HassEntity): { text: string; cls: string } {
  const tile = localTile(stateObj?.attributes); // (in this device's language)
  if (tile.includes("|")) {
    const [cls, text] = tile.split("|");
    return { text: text || cls, cls };
  }
  return { text: stateObj?.state ?? "", cls: stateObj?.state ?? "" };
}

// MIRRORED: firmware/components/room_tiles/board_kinds.cpp (water switch) - a change here must be made there too.
/** What a pool / spa tile's switch does: "body" (turn the body on - the
 *  pool: its pump / pool mode; the spa: spa mode / its pump), "heater", or
 *  undefined (nothing to switch). A Pool tile and the combined tile NEVER
 *  switch a heater (user, 2026-11-09: turning the pump on must not start
 *  heating the pool by surprise - heated pools run the heater on a schedule);
 *  only a Spa tile without a pump falls back to its heater. */
export function waterSwitch(stateObj: HassEntity): "body" | "heater" | undefined {
  const a = stateObj.attributes;
  const spaTile = a.body === "spa" && !("mode" in a);
  if (a.can_turn_on === true) return "body";
  return spaTile && a.has_heater !== false ? "heater" : undefined;
}

// MIRRORED: firmware/components/room_tiles/board_kinds.cpp (water on) - a change here must be made there too.
/** The water tile's switch: on when its body is on (or, a Spa tile switching
 *  its heater, when the heater is on). */
export function waterOn(stateObj?: HassEntity): boolean {
  if (!stateObj) return false;
  const a = stateObj.attributes;
  // the body is on: the active one (shared) / its pump running - not while
  // its pump is off or the system is offline
  if (isPoolSensor(stateObj) && waterSwitch(stateObj) === "body")
    return a.active === true && !["pump_off", "offline", "standby"].includes(stateObj.state);
  return String(a.tile ?? "").split("|")[5] === "on";
}

// MIRRORED: firmware/components/room_tiles/board.cpp (switch call) - a change here must be made there too.
/** What the tile's switch sends for a new on/off value (switch_action). */
export function switchCall(kind: TileKind, entity: string, on: boolean, stateObj?: HassEntity): Call | undefined {
  const t = { entity_id: entity };
  switch (kind) {
    case "onoff_light":
    case "dimmable_light":
    case "color_light":
      return { domain: "light", service: on ? "turn_on" : "turn_off", data: t };
    case "switch":
      // a switch tile is a switch or a helper (input_boolean): its own domain's action
      return { domain: entity.startsWith("input_boolean.") ? "input_boolean" : "switch", service: on ? "turn_on" : "turn_off", data: t };
    case "fan":
      return { domain: "fan", service: on ? "turn_on" : "turn_off", data: t };
    case "cover":
      return { domain: "cover", service: on ? "open_cover" : "close_cover", data: t };
    case "lock":
      return { domain: "lock", service: on ? "lock" : "unlock", data: t };
    case "climate":
      return { domain: "climate", service: on ? "turn_on" : "turn_off", data: t };
    case "water":
      if (!isPoolSensor(stateObj)) return undefined;
      // turn the body on / off (the Spa tile's heater follows per its
      // setting); only a Spa tile without a pump switches its heater
      switch (waterSwitch(stateObj!)) {
        case "body":
          return { domain: "room_tiles", service: "pool_set_on", data: { entity, on } };
        case "heater":
          return { domain: "room_tiles", service: "pool_set_heater", data: { entity, heater: on } };
        default:
          return undefined;
      }
    default:
      return undefined;
  }
}

// MIRRORED: firmware/components/room_tiles/board.cpp + board_kinds.cpp (hold times) - a change here must be made there too.
/** How long a tile holds the user's change before trusting HA again
 *  (settle_timeout_ms): lights 3 s, fans / climate 5 s, locks 10 s, covers 8 s
 *  to an end stop or 30 s to a mid position. */
export function settleMs(kind: TileKind, roller: boolean, row: number): number {
  switch (kind) {
    case "fan":
    case "climate":
      return 5000;
    case "water":
      return 20000;
    case "lock":
    case "switch": // a TV, a plug's appliance: often seconds before HA hears it's on
      return 10000;
    case "cover":
      return roller && row !== COV_OPEN_ROW && row !== COV_CLOSED_ROW ? 30000 : 8000;
    default:
      return 3000;
  }
}

// MIRRORED: firmware/components/room_tiles/board.cpp (switch tracks) - a change here must be made there too.
/** Panel switch geometry: track width (design px) and its images. */
export function switchTrack(kind: TileKind, stateObj?: HassEntity): { w: number; off: string; on: string } | undefined {
  switch (kind) {
    case "onoff_light":
    case "dimmable_light":
    case "color_light":
    case "switch":
      return { w: 75, off: "track_switch_off", on: kind === "switch" ? "track_switch_on_raspberry" : "track_switch_on" };
    case "fan":
      return { w: 75, off: "track_switch_off", on: "track_switch_on_cyan" };
    case "cover":
      return { w: 100, off: "track_switch_closed", on: "track_switch_open_green" };
    case "lock":
      return { w: 120, off: "track_switch_unlocked", on: "track_switch_locked_purple" };
    case "climate":
      return {
        w: 75,
        off: "track_switch_off",
        on: { heat: "track_switch_on_red", cool: "track_switch_on_blue", neutral: "track_switch_on_slate" }[climateTone(stateObj)],
      };
    case "water":
      // a pool / spa sensor whose body has nothing to switch: no switch
      if (isPoolSensor(stateObj) && !waterSwitch(stateObj!)) return undefined;
      return { w: 75, off: "track_switch_off", on: "track_switch_on_red" };
    default:
      return undefined;
  }
}

/** A robot vacuum's icon: Matic's own for Matic robots (by the device's
 *  manufacturer), the generic round robot for every other brand. A tile on a
 *  sensor (not the vacuum itself) names its vacuum in a `vacuum` attribute. */
export function vacuumIcon(hass: HomeAssistant | undefined, entity: string | undefined): string {
  const named = entity && !entity.startsWith("vacuum.") ? hass?.states[entity]?.attributes.vacuum : undefined;
  const target = typeof named === "string" ? named : entity;
  const dev = target ? hass?.entities?.[target]?.device_id : undefined;
  const maker = dev ? hass?.devices?.[dev]?.manufacturer ?? "" : "";
  return /^matic\b/i.test(maker) ? "icon_matic" : "icon_robot_vacuum";
}

/** Covers that let people in (HA device class): one icon for all of them -
 *  a garage door, the common case - and never changed by one map tap. */
export const ENTRY_COVERS = ["garage", "gate", "door"];

export function isEntryCover(hass: HomeAssistant | undefined, entity: string | undefined): boolean {
  const cls = entity ? hass?.states[entity]?.attributes.device_class : undefined;
  return typeof cls === "string" && ENTRY_COVERS.includes(cls);
}

/** An appliance's icon (the tile picker, map markers - its tile has none):
 *  the laundry when it has a washer or dryer, else the dishwasher. */
export function applianceIcon(hass?: HomeAssistant, entity?: string): string {
  const units = entity ? hass?.states[entity]?.attributes?.units : undefined;
  const laundry =
    Array.isArray(units) && units.some((u) => u && typeof u === "object" && ["washer", "dryer"].includes(u.appliance));
  return laundry ? "icon_laundry" : "icon_dishwasher";
}

// MIRRORED: firmware/components/room_tiles/map_markers.cpp (marker icons) - a change here must be made there too.
/** The tile's type icon (bottom left), from the panel art. */
export function tileIcon(kind: TileKind, entity?: string, hass?: HomeAssistant): string | undefined {
  switch (kind) {
    case "onoff_light":
    case "dimmable_light":
    case "color_light":
      return "icon_light";
    case "fan":
      return "icon_fan";
    case "cover":
      return isEntryCover(hass, entity) ? "icon_garage" : "icon_blind";
    case "lock":
      return "icon_key";
    case "climate":
      return "icon_ac";
    case "water": {
      // the body's picture; the combined tile's follows the mode
      const a = entity ? hass?.states[entity]?.attributes : undefined;
      return (a?.mode ?? a?.body) === "spa" ? "icon_spa" : "icon_pool";
    }
    case "vacuum":
      return vacuumIcon(hass, entity);
    case "switch":
      return "icon_switch";
    case "scene":
      return "icon_scene";
    case "script":
      return "icon_script";
    default:
      return undefined;
  }
}
