// The browser demo (docs/TODO.md "Landing page + browser demo"): the real
// dashboard on a made-up home, in a plain web page - no Home Assistant.
// tools/demo/make_demo.py writes what Room Tiles sends the dashboard for
// that home (data/*.json); this page plays the part of HA: the states, the
// feed, and what a tap does (a light on, a blind down...). Room Tiles' own
// edits (tiles, maps, settings) aren't saved anywhere - the page says so.
// Built by build-demo.mjs.

import "./room-tiles-panel";
import type { FeedMessage, HassEntity, HomeAssistant } from "./types";

declare const DEMO_ICONS: Record<string, string>; // "mdi:close" -> its SVG path

// ---- <ha-icon>: HA's icon element, as far as the dashboard uses it -------------

class DemoIcon extends HTMLElement {
  static observedAttributes = ["icon"];
  private _icon = "";

  get icon(): string {
    return this._icon;
  }
  set icon(v: string) {
    this._icon = v ?? "";
    this._draw();
  }
  attributeChangedCallback(_n: string, _o: string | null, v: string | null): void {
    this.icon = v ?? "";
  }
  connectedCallback(): void {
    this._draw();
  }
  private _draw(): void {
    const root = this.shadowRoot ?? this.attachShadow({ mode: "open" });
    const path = DEMO_ICONS[this._icon] ?? "";
    root.innerHTML =
      `<style>:host{display:inline-flex;align-items:center;justify-content:center;vertical-align:middle;` +
      `width:var(--mdc-icon-size,24px);height:var(--mdc-icon-size,24px)}svg{width:100%;height:100%;fill:currentColor}</style>` +
      `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"></path></svg>`;
  }
}
if (!customElements.get("ha-icon")) customElements.define("ha-icon", DemoIcon);

// ---- the made-up home ------------------------------------------------------------

interface DemoData {
  feed: FeedMessage;
  states: Record<string, HassEntity>;
  entities: HomeAssistant["entities"];
  devices: HomeAssistant["devices"];
  meta: { made: string };
}

async function load(): Promise<DemoData> {
  // (asked fresh each time: a web host may tell the browser to keep files for weeks)
  const get = async (name: string) => (await fetch(`data/${name}.json`, { cache: "no-cache" })).json();
  const [feed, states, entities, devices, meta] = await Promise.all(
    ["feed", "states", "entities", "devices", "meta"].map(get),
  );
  return { feed, states, entities, devices, meta };
}

/** The home as if it was made a moment ago: every time in it (a finish time)
 *  moved by how long ago the demo was built. */
function moveTimes(states: Record<string, HassEntity>, made: string): void {
  const shift = Date.now() - Date.parse(made);
  if (!Number.isFinite(shift)) return;
  for (const s of Object.values(states)) {
    if (s.attributes?.device_class === "timestamp" && !Number.isNaN(Date.parse(s.state)))
      s.state = new Date(Date.parse(s.state) + shift).toISOString();
  }
}

// ---- what a tap does -------------------------------------------------------------

type Attrs = Record<string, any>;

/** The entities a call is for (data.entity_id or target.entity_id). */
function targets(data?: Attrs, target?: Attrs): string[] {
  const ids = target?.entity_id ?? data?.entity_id;
  return Array.isArray(ids) ? ids : ids ? [ids] : [];
}

/** An entity's new state after `domain.service` - null: nothing to change. */
function apply(s: HassEntity, domain: string, service: string, data: Attrs): HassEntity | null {
  const a = { ...s.attributes };
  let state = s.state;
  const on = state !== "off" && state !== "closed" && state !== "locked";
  const want = service === "toggle" ? !on : service === "turn_on" || service === "open_cover" || service === "unlock";
  const kind = s.entity_id.split(".", 1)[0];
  switch (kind) {
    case "light":
      if (service === "turn_on" || (service === "toggle" && want)) {
        state = "on";
        if (data.brightness_pct !== undefined) a.brightness = Math.round((Number(data.brightness_pct) * 255) / 100);
        if (data.brightness !== undefined) a.brightness = Number(data.brightness);
        if (a.brightness === undefined || a.brightness === null) a.brightness = 255;
        if (data.hs_color) {
          a.hs_color = data.hs_color;
          a.color_mode = "hs";
        }
        if (data.color_temp_kelvin) {
          a.color_temp_kelvin = data.color_temp_kelvin;
          a.color_mode = "color_temp";
        }
      } else if (service === "turn_off" || service === "toggle") {
        state = "off";
        a.brightness = null;
      } else return null;
      break;
    case "switch":
      if (["turn_on", "turn_off", "toggle"].includes(service)) state = want ? "on" : "off";
      else return null;
      break;
    case "fan":
      if (service === "set_percentage") {
        a.percentage = Number(data.percentage) || 0;
        state = a.percentage > 0 ? "on" : "off";
      } else if (["turn_on", "turn_off", "toggle"].includes(service)) {
        state = want ? "on" : "off";
        a.percentage = want ? a.percentage || 50 : 0;
      } else return null;
      break;
    case "cover":
      if (service === "set_cover_position") a.current_position = Number(data.position) || 0;
      else if (service === "open_cover" || (service === "toggle" && want)) a.current_position = 100;
      else if (service === "close_cover" || service === "toggle") a.current_position = 0;
      else if (service === "stop_cover") return null;
      else return null;
      state = a.current_position > 0 ? "open" : "closed";
      break;
    case "lock":
      if (service === "lock" || service === "unlock") state = service === "lock" ? "locked" : "unlocked";
      else if (service === "toggle") state = on ? "locked" : "unlocked";
      else return null;
      break;
    case "climate":
      if (service === "set_temperature") {
        for (const k of ["temperature", "target_temp_low", "target_temp_high"]) if (data[k] !== undefined) a[k] = data[k];
        if (data.hvac_mode) state = data.hvac_mode;
      } else if (service === "set_hvac_mode") state = data.hvac_mode;
      else return null;
      break;
    default:
      return null;
  }
  return { ...s, state, attributes: a };
}

// ---- the page ----------------------------------------------------------------------

async function main(): Promise<void> {
  const data = await load();
  moveTimes(data.states, data.meta.made);
  let states = data.states;
  const el = document.createElement("room-tiles-panel") as HTMLElement & { hass?: HomeAssistant; narrow?: boolean };
  /** "Not saved": a Room Tiles edit - the demo page's bar says so for a
   *  moment (index.html, this page's parent). */
  const unsaved = () => window.parent?.postMessage("room-tiles-demo:unsaved", location.origin);

  const areas: HomeAssistant["areas"] = {};
  for (const a of (data.feed as any).data?.areas ?? []) areas![a.id] = { area_id: a.id, name: a.name };

  const set = (next: Record<string, HassEntity>) => {
    states = next;
    el.hass = { ...hass, states };
  };

  /** Room Tiles' area lights (a light group of its own): its members too. */
  const members = (id: string): string[] => {
    const m = states[id]?.attributes?.entity_id;
    return Array.isArray(m) && id.startsWith("light.") ? m : [];
  };

  const hass: HomeAssistant = {
    states,
    entities: data.entities,
    devices: data.devices,
    areas,
    services: {},
    user: { is_admin: true },
    language: "en",
    locale: { language: navigator.language?.split("-")[0] || "en", time_format: "language", time_zone: "local" },
    config: { time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone },
    async callService(domain, service, svcData, target) {
      if (domain === "room_tiles" && service === "area_lights") {
        // the area's lights button: any on -> all off, else all on (as the
        // integration does)
        const lights = (data.feed as any).data?.area_lights?.[String(svcData?.area)] ?? [];
        const anyOn = lights.some((id: string) => states[id]?.state === "on");
        return hass.callService("light", anyOn ? "turn_off" : "turn_on", { entity_id: lights });
      }
      if (domain === "room_tiles" && service === "clear_appliance") {
        // a tap on a finished unit empties it
        const entity = Object.keys(states).find((id) => states[id].attributes?.appliance === svcData?.appliance);
        if (!entity) return {};
        const s = states[entity];
        const units = (s.attributes.units ?? []).map((u: Attrs) =>
          u.id === svcData?.unit ? { ...u, phase: "idle", running: false, status: "", status_word: "", time_left: "", minutes: null } : u,
        );
        const busy = units.some((u: Attrs) => u.phase !== "idle");
        set({ ...states, [entity]: { ...s, state: busy ? s.state : "idle", attributes: { ...s.attributes, units } } });
        return {};
      }
      if (domain === "room_tiles") {
        unsaved();
        return {};
      }
      const next = { ...states };
      for (const id of targets(svcData, target)) {
        const d = domain === "homeassistant" ? id.split(".", 1)[0] : domain;
        for (const one of [id, ...members(id)]) {
          const s = next[one] && apply(next[one], d, service, svcData ?? {});
          if (s) next[one] = s;
        }
      }
      // every light group (Room Tiles' area lights): on when any member is
      for (const [gid, g] of Object.entries(next)) {
        const m = gid.startsWith("light.") ? g.attributes?.entity_id : undefined;
        if (Array.isArray(m) && m.length) next[gid] = { ...g, state: m.some((x: string) => next[x]?.state === "on") ? "on" : "off" };
      }
      set(next);
      return {};
    },
    connection: {
      async subscribeMessage(callback: (msg: any) => void, msg: Record<string, unknown>) {
        if (msg.type === "room_tiles/subscribe") setTimeout(() => callback(data.feed), 0);
        return async () => {};
      },
      async sendMessagePromise<T>(): Promise<T> {
        unsaved();
        return {} as T;
      },
    },
    formatEntityState: (s: HassEntity) => s.state,
  } as HomeAssistant;

  el.narrow = window.matchMedia("(max-width: 870px)").matches;
  el.hass = hass;
  document.getElementById("demo-root")!.append(el);
}

void main();
