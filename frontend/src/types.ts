// The Room Tiles document as sent by the integration's websocket feed
// (custom_components/room_tiles/model.py `as_dict`). Keep in step with it.

export const PAYLOAD_SCHEMA = 1;

export type Layout = "5x2" | "6x3";
export const LAYOUT_COLUMNS: Record<Layout, number> = { "5x2": 5, "6x3": 6 };

export type TileKind =
  | "blank"
  | "onoff_light"
  | "dimmable_light"
  | "color_light"
  | "switch"
  | "fan"
  | "cover"
  | "lock"
  | "climate"
  | "appliance"
  | "vacuum"
  | "water"
  | "map"
  | "scene"
  | "script";

export interface Tile {
  kind: TileKind;
  entity?: string;
  name?: string; // the tile's own short name (else the catalog's)
}

export interface Area {
  id: string;
  name: string; // HA's full name
  floor: string | null;
  short_name: string;
  review: boolean;
  hidden: boolean;
  lights: string | null; // override entity; null = all lights in the area
  lights_exclude: string[];
  tiles: Record<Layout, (Tile | null)[]>;
  /** Room Tiles may make its "<Area> Lights" light for the area (off: none) */
  light_entity?: boolean;
  /** the layout a device starts the area on until it picks one (null: 5x2) */
  layout?: Layout | null;
  /** the layouts whose board the user changed - the others get new
   *  appliance / vacuum / pool tiles by themselves */
  edited?: Layout[];
}

export interface CatalogEntry {
  entity: string;
  kind: TileKind;
  short_name: string;
  review: boolean;
  auto: boolean;
}

export interface RoomTilesDoc {
  areas: Area[];
  maps: unknown[];
  markers: unknown[];
  catalog: { entries: CatalogEntry[]; hidden: string[] };
  settings: { auto_add_areas: boolean; auto_update_panels?: boolean };
  /** the wall panels and their firmware (Panels page; integration: update.py firmware_rows) */
  panel_firmware?: { panels: PanelFirmwareRow[]; images: { board: string; label: string }[] };
  /** worked out by the integration: area id -> the lights its button switches */
  area_lights: Record<string, string[]>;
  /** entities disabled in HA: their tiles show empty, their markers are
   *  hidden - kept in the data for when they're re-enabled */
  disabled?: string[];
  /** vacuums that clean by HA area: entity -> its name and the HA areas its
   *  segments are mapped to (HA's "Map vacuum segments to areas") */
  vacuums?: Record<string, { name: string; areas: string[]; unmapped?: boolean }>;
  version?: string; // the Room Tiles version HA runs (manifest)
  dev_build?: boolean; // a developer build (a source checkout): its test-only menu items
  recordings?: Record<string, RecordingView>; // "Report a problem": appliance id -> its recording
  /** what's beta ("Report how it went"): "<kind>:<id>" -> its beta units ("" for a pool / vacuum) */
  beta?: Record<string, string[]>;
  restart_needed?: boolean; // newer Room Tiles files installed than HA runs: restart to finish  // unmapped: a room it reports isn't mapped
  /** appliance profiles (integration: model.Appliance) */
  appliances?: ApplianceProfile[];
  /** supported appliances found in HA, not set up yet - same shape + notes */
  appliance_found?: (ApplianceProfile & { notes: string[] })[];
  /** appliance id -> what setup would make of its hardware now (Set up again) */
  appliance_again?: Record<string, ApplianceProfile & { notes: string[] }>;
  /** pool / spa systems (integration: model.PoolSystem) */
  pools?: PoolProfile[];
  /** pool / spa systems found in HA, not set up yet - same shape + notes */
  pool_found?: (PoolProfile & { notes: string[] })[];
  /** robot vacuum profiles (integration: model.RobotProfile) */
  robots?: RobotProfile[];
  /** vacuums found in HA, not set up yet - same shape + notes, clean_area */
  robot_found?: (RobotProfile & { notes: string[]; clean_area: boolean })[];
  /** found but ignored by the user (Ignore) - listed at the bottom of the
   *  Appliances page, never counted by the dot */
  ignored_found?: {
    appliances: (ApplianceProfile & { notes: string[] })[];
    pools: (PoolProfile & { notes: string[] })[];
    robots: (RobotProfile & { notes: string[]; clean_area: boolean })[];
  };
  /** the brand presets setup can pick from */
  appliance_presets?: AppliancePreset[];
}

export type ApplianceType = "washer" | "dryer" | "dishwasher";

export interface ApplianceUnitProfile {
  id: string;
  label: string;
  appliance: ApplianceType;
  preset: string;
  status: string;
  time: string | null;
  door: string | null;
  /** its own door opening empties it (default on) */
  door_clears: boolean;
  finished: "done" | "waiting" | "idle";
  /** entities that turn on / open, or "unit:<id>" = that unit starting */
  clear: string[];
  drawer: boolean;
  overrides: Record<string, string>;
  /** smart-plug (power) presets: running above this many watts... */
  power_on_w?: number;
  /** ...finished after this many minutes below it */
  power_off_min?: number;
}

export interface ApplianceProfile {
  id: string;
  name: string;
  units: ApplianceUnitProfile[];
}

export interface RobotProfile {
  id: string;
  name: string;
  vacuum: string;
  /** Matter's RVC operational error sensor (alerts), if it reports one */
  error: string | null;
  preset: string;
}

export type PoolLayout = "shared" | "separate" | "pool" | "spa";

export interface PoolBodyProfile {
  temp: string | null;
  heater: string | null;
  pump: string | null;
  /** turning its heater on (from Room Tiles) also turns the pump on */
  pump_with_heater?: boolean;
  /** a brand's own heater on / off switch (Jandy): never a tile itself */
  heater_switch?: string | null;
}

export interface PoolProfile {
  id: string;
  name: string;
  preset: string;
  layout: PoolLayout;
  pool: PoolBodyProfile | null;
  spa: PoolBodyProfile | null;
  /** shared: the switch that puts the system in spa mode, and the pump */
  spa_mode: string | null;
  pump: string | null;
  /** turning the spa on (its tile's switch) turns its heater on too */
  spa_heater_follows: boolean;
}

export interface AppliancePreset {
  id: string;
  name: string;
  appliance: ApplianceType;
  verified: boolean;
  /** reads a smart plug's power, not a state */
  power?: boolean;
}

export type FeedMessage =
  | { type: "full"; schema: number; data: RoomTilesDoc }
  | { type: "update"; schema: number; data: Partial<RoomTilesDoc> }
  | { type: "reset" };

// The small part of Home Assistant's frontend `hass` object this panel uses.
export interface HassEntity {
  entity_id: string;
  state: string;
  attributes: Record<string, any>;
}

export interface HassEntityEntry {
  entity_id: string;
  area_id?: string | null;
  device_id?: string | null;
  hidden?: boolean;
  entity_category?: string | null;
  /** the integration it comes from (HA's entity registry display entry) */
  platform?: string;
}

/** A wall panel on the Panels page: what it runs and where its firmware stands. */
export interface PanelFirmwareRow {
  device_id: string;
  name: string;
  area: string | null;
  board: string | null;
  running: string | null;
  latest: string | null;
  entity_id: string | null;
  status: "current" | "available" | "waiting" | "updating" | "hand_built" | "unknown";
  auto: boolean;
}

export interface HomeAssistant {
  states: Record<string, HassEntity>;
  /** HA's registries as the frontend sees them (entity -> area / device) */
  entities?: Record<string, HassEntityEntry>;
  devices?: Record<string, { area_id?: string | null; manufacturer?: string | null }>;
  areas?: Record<string, { area_id: string; name: string }>;
  /** HA's actions by domain (a script's `fields`: what it asks for) */
  services?: Record<string, Record<string, { fields?: Record<string, { required?: boolean }> }>>;
  callService(
    domain: string,
    service: string,
    data?: Record<string, unknown>,
    target?: Record<string, unknown>,
    notifyOnError?: boolean,
    returnResponse?: boolean,
  ): Promise<unknown>;
  connection: {
    subscribeMessage<T>(callback: (msg: T) => void, msg: Record<string, unknown>): Promise<() => Promise<void>>;
    sendMessagePromise?<T>(msg: Record<string, unknown>): Promise<T>;
  };
  /** a fetch with the user's sign-in (HA's frontend gives every panel one) */
  fetchWithAuth?(path: string, init?: RequestInit): Promise<Response>;
  language?: string;
  locale?: {
    language?: string;
    /** the user's profile: "language" | "system" | "12" | "24" */
    time_format?: string;
    /** "local" (the browser's) | "server" (HA's) */
    time_zone?: string;
  };
  config?: { time_zone?: string };
  user?: { is_admin?: boolean };
  /** HA's own wording for a state ("On", "Ein", "Unavailable"...) */
  formatEntityState?: (stateObj: HassEntity, state?: string) => string;
}

/** A report as it would be sent (room_tiles/report_preview, report.py). */
export interface ReportPreview {
  report: Record<string, unknown>; // the exact payload: scrubbed
  summary: string[]; // what it holds: wording keys (report.has.*)
  dropped: { path: string; why: string }[]; // what was left out
  // the GitHub issue it becomes: in its kind's issue form (template), the report in its field
  issue: { title: string; body: string; url: string; template?: string; field?: string };
  warnings?: { text: string; why: string }[]; // the user's own words: what looks like a name, address, time...
}

/** "Report a problem": an appliance's next cycle being recorded (cycles.py).
 *  Times: seconds since 1970, shown to the user only. */
export interface RecordingView {
  unit: string;
  status: "waiting" | "recording" | "ready" | "no_cycle";
  armed: number;
  started: number | null;
  ended: number | null;
  description: string;
  opened: boolean; // Open GitHub was pressed: "Did the report go through?"
}
