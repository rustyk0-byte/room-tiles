// <rt-appliances>: washers, dryers, dishwashers. Lists what's set up (with what
// each unit is doing now), offers the supported ones Room Tiles found in HA
// ("Add"), and says plainly when nothing supported is there. Add and the
// pencil both open <rt-appliance-editor>: ONE dialog whose first section is
// the tile choice (cards - one tile / separate tiles / share with...); a card
// only changes what's shown below, nothing happens until Save (docs/UI.md).

import { LitElement, css, html, nothing } from "lit";
import { live } from "lit/directives/live.js";
import { DialogPin } from "./dialog-pin";
import type {
  RobotProfile,
  PoolProfile,
  ApplianceProfile,
  ApplianceUnitProfile,
  HassEntity,
  HomeAssistant,
  RoomTilesDoc,
  SetupNote,
} from "./types";
import { dialogStyles, noSelectStyles, rowStyles, groupStyles, setUpDevice, ScrollFades } from "./ui";
import "./unsaved";
import "./pools";
import "./robots";
import "./report";
import { problemText, type ProblemSubject } from "./problem";
import "./model-report";
import { bodiesOf, tilesOf } from "./pools";
import { listOf, num, t, th } from "./i18n";
import { localText, wordText } from "./words";

const MAX_SHORT = 15;
/** The full supported-devices page (docs/SUPPORTED.md): brands, models, features by model. */
export const SUPPORTED_URL = "https://github.com/rustyk0-byte/room-tiles/blob/main/docs/SUPPORTED.md";
/** A phase's word when the sensor has no status line (appliances.phase_*). */
const phaseText = (phase: string): string => t(`appliances.phase_${phase}`);

/** An answer to tell Room Tiles about: an appliance unit's state, or a
 *  vacuum's error code (`robot`). */
type Told = { appliance?: string; unit?: string; robot?: string; state: string; answer: string; name: string };

const plain = (p: ApplianceProfile & { notes?: SetupNote[] }): ApplianceProfile => ({ id: p.id, name: p.name, units: p.units });
const friendly = (hass: HomeAssistant | undefined, e: string | null) =>
  (e && (hass?.states[e]?.attributes.friendly_name as string | undefined)) || e || "";

const CONTACT = ["door", "opening", "window", "garage_door"];
const MOTION = ["motion", "occupancy", "presence"];

/** An entity's HA area: its own, else its device's. */
function areaOf(hass: HomeAssistant | undefined, entity: string | null): string | undefined {
  const e = entity ? hass?.entities?.[entity] : undefined;
  return e?.area_id ?? (e?.device_id ? (hass?.devices?.[e.device_id]?.area_id ?? undefined) : undefined);
}

/** "Kitchen Door opening" / "Laundry detecting motion" - a name that already
 *  ends in what it senses ("Garage Door Motion") doesn't say it twice. */
export function sensorText(hass: HomeAssistant | undefined, entity: string): string {
  const dc = hass?.states[entity]?.attributes.device_class as string | undefined;
  const motion = MOTION.includes(dc ?? "");
  const name = friendly(hass, entity);
  const trimmed = name.replace(motion ? /\s+(motion sensor|motion|occupancy|presence|sensor)$/i : /\s+(contact|opening|sensor)$/i, "");
  return t(motion ? "appliances.sensor_motion" : "appliances.sensor_opening", { name: trimmed || name });
}

/** The appliance's live Room Tiles sensor (its `appliance` attribute). */
export function applianceSensor(hass: HomeAssistant | undefined, id: string): HassEntity | undefined {
  return Object.values(hass?.states ?? {}).find((s) => s.entity_id.startsWith("sensor.") && s.attributes.appliance === id);
}

export class RtAppliances extends LitElement {
  /** fades where a scrolling area has more (ui.ts ScrollFades) */
  protected readonly _scrollFades = new ScrollFades(this, ".list");

  /** the dialog's top edge stays put while its content changes (dialog-pin.ts) */
  readonly dialogPin = new DialogPin(this);
  static properties = {
    hass: { attribute: false },
    doc: { attribute: false },
    _edit: { state: true },
    _adding: { state: true },
    _poolEdit: { state: true },
    _poolAdding: { state: true },
    _robotEdit: { state: true },
    _robotAdding: { state: true },
    _told: { state: true },
    _report: { state: true },
    _problem: { state: true },
    _model: { state: true },
  };

  hass?: HomeAssistant;
  doc?: RoomTilesDoc;
  /** an unknown state just answered: "Also tell Room Tiles?" on its card */
  private _told?: Told;
  /** that report's steps open (report.ts) */
  private _report?: Told;
  /** "Report a problem" open for an appliance / pool / vacuum (problem.ts) */
  private _problem?: { subject: ProblemSubject; id: string; name: string; units: { id: string; label: string }[] };
  /** Report how it went: a beta one (its beta units) */
  private _model?: { subject: ProblemSubject; id: string; name: string; units: { id: string; label: string }[] };
  /** a set-up appliance being edited */
  private _edit?: string;
  /** a found appliance being added (nothing stored until its Add) */
  private _adding?: ApplianceProfile;
  /** a pool / spa system being edited, or a found one being added */
  private _poolEdit?: string;
  private _poolAdding?: PoolProfile;
  /** a robot vacuum being edited, or a found one being added */
  private _robotEdit?: string;
  private _robotAdding?: RobotProfile;
  private _opened = Date.now();

  private _close(): void {
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  }

  /** States the appliance reported that its preset doesn't know: asked
   *  once, the answer saved for that unit (its overrides). */
  private _questions(a: ApplianceProfile) {
    const qs = (applianceSensor(this.hass, a.id)?.attributes.questions ?? []) as { unit: string; label: string; state: string }[];
    return qs.map((q) => {
      const unit = a.units.find((u) => u.id === q.unit);
      if (!unit) return nothing;
      const running = unit.appliance === "dryer" ? "drying" : "washing";
      const answer = (phase: string) => {
        const p = JSON.parse(JSON.stringify(a)) as ApplianceProfile;
        const u = p.units.find((x) => x.id === q.unit)!;
        u.overrides = { ...u.overrides, [q.state.toLowerCase()]: phase };
        void this.hass?.callService("room_tiles", "set_appliance", { appliance: p });
        // then: also tell Room Tiles? (its presets learn from it)
        this._told = { appliance: a.id, unit: q.unit, state: q.state, answer: phase, name: a.name };
      };
      return html`<div class="question">
        <div>${th("appliances.question", { name: q.label, state: html`<b>“${q.state}”</b>` })}</div>
        <div class="answers">
          <button class="plain" @click=${() => answer(running)}>${t("appliances.answer_running")}</button>
          <button class="plain" @click=${() => answer("paused")}>${t("appliances.answer_paused")}</button>
          <button class="plain" @click=${() => answer("off")}>${t("appliances.answer_off")}</button>
          <button class="plain" @click=${() => answer("error")}>${t("appliances.answer_error")}</button>
        </div>
      </div>`;
    });
  }

  /** Error codes a vacuum reported that Room Tiles has no words for: asked
   *  once, the answer saved on the vacuum (its overrides) - then it shows
   *  as a "needs you", a fault or nothing. */
  private _robotQuestions(r: RobotProfile) {
    const sensor = Object.values(this.hass?.states ?? {}).find((st) => st.entity_id.startsWith("sensor.") && st.attributes.robot === r.id);
    const qs = (sensor?.attributes.questions ?? []) as { code: string }[];
    return qs.map((q) => {
      const answer = (said: string) => {
        const robot = { ...r, overrides: { ...(r.overrides ?? {}), [q.code]: said } };
        void this.hass?.callService("room_tiles", "set_robot", { robot });
        this._told = { robot: r.id, state: q.code, answer: said, name: r.name };
      };
      return html`<div class="question">
        <div>${th("appliances.question", { name: r.name, state: html`<b>“${q.code}”</b>` })}</div>
        <div class="answers">
          <button class="plain" @click=${() => answer("attention")}>${t("appliances.answer_needs_you")}</button>
          <button class="plain" @click=${() => answer("error")}>${t("appliances.answer_fault")}</button>
          <button class="plain" @click=${() => answer("none")}>${t("appliances.answer_nothing")}</button>
        </div>
      </div>`;
    });
  }

  /** After an answer: "Thanks - also tell Room Tiles about "steam_fresh"?"
   *  (the report steps, report.ts; a one-device report: that state and the
   *  answer, the device's brand and model - HA builds it) */
  /** Report a problem: the button, or where its recording is (waiting,
   *  recording, ready to send - "did it go through?" once GitHub opened).
   *  Appliances, pools and robot vacuums alike. */
  private _problemRow(subject: ProblemSubject, id: string, name: string, units: { id: string; label: string }[] = []) {
    const rec = this.doc?.recordings?.[`${subject}:${id}`];
    const send = (action: string, extra: Record<string, unknown> = {}) =>
      void this.hass?.connection.sendMessagePromise?.({ type: "room_tiles/recording", action, subject, target: id, ...extra });
    const open = () => (this._problem = { subject, id, name, units });
    const row = (text: string, buttons: unknown) =>
      html`<div class="recording"><div>${text}</div><div class="answers">${buttons}</div></div>`;
    if (!rec) {
      return html`<button class="link" @click=${open}>
        <ha-icon icon="mdi:message-alert-outline"></ha-icon>${t("problem.button")}
      </button>`;
    }
    if (rec.status === "waiting") {
      return row(problemText("waiting", subject), html`<button class="plain" @click=${() => send("delete")}>${t("common.cancel")}</button>`);
    }
    if (rec.status === "recording") {
      return row(
        problemText("recording", subject),
        html`<button class="plain" @click=${() => send("stop")}>${t("problem.stop")}</button>
          <button class="plain" @click=${() => send("delete")}>${t("common.cancel")}</button>`,
      );
    }
    if (rec.status === "no_cycle") {
      return row(problemText("no_cycle", subject), html`<button class="plain" @click=${() => send("delete")}>${t("common.ok")}</button>`);
    }
    if (rec.opened) {
      return row(
        t("problem.sent_ask"),
        html`<button class="plain" @click=${() => send("delete")}>${t("problem.sent_yes")}</button>
          <button class="plain" @click=${() => send("update", { opened: false })}>${t("problem.keep")}</button>`,
      );
    }
    return row(
      problemText("ready", subject),
      html`<button class="primary" @click=${open}>${t("problem.review")}</button>
        <button class="plain" @click=${() => send("delete")}>${t("problem.delete")}</button>`,
    );
  }

  /** A beta one (not confirmed on real hardware - the feed's "beta"): says
   *  so, with Report how it went (model-report.ts). */
  private _betaRow(subject: ProblemSubject, id: string, name: string, units: { id: string; label: string }[] = []) {
    const beta = this.doc?.beta?.[`${subject}:${id}`];
    if (!beta?.length) return nothing;
    const mine = units.filter((u) => beta.includes(u.id));
    const text =
      subject === "pool"
        ? t("model.beta_pool")
        : units.length > 1 && mine.length === 1
          ? t("model.beta_unit", { unit: mine[0].label })
          : t("model.beta");
    return html`<div class="beta">
      <span>${text}</span>
      <button class="link" @click=${() => (this._model = { subject, id, name, units: mine.map((u) => ({ id: u.id, label: u.label })) })}>
        <ha-icon icon="mdi:clipboard-check-outline"></ha-icon>${t("model.button")}
      </button>
    </div>`;
  }

  private _readyRecording(p: { subject: ProblemSubject; id: string }) {
    const rec = this.doc?.recordings?.[`${p.subject}:${p.id}`];
    return rec?.status === "ready" ? rec : undefined;
  }

  private _tellOffer(told: NonNullable<RtAppliances["_told"]>) {
    return html`<div class="question tell">
      <div>${th("appliances.tell_offer", { state: html`<b>“${told.state}”</b>` })}</div>
      <div class="answers">
        <button class="primary" @click=${() => ((this._report = told), (this._told = undefined))}>${t("appliances.tell_yes")}</button>
        <button class="plain" @click=${() => (this._told = undefined)}>${t("appliances.tell_no")}</button>
      </div>
    </div>`;
  }

  /** Ignore a found device: it moves to Ignored (bottom of the page) and the
   *  dot stops counting it; Add there brings it back. */
  private _ignore(kind: "appliance" | "pool" | "robot", device: unknown): void {
    void this.hass?.callService("room_tiles", "ignore_device", { kind, device });
  }

  private _ignoredCards() {
    const ig = this.doc?.ignored_found;
    const card = (name: string, sub: string, add: () => void) => html`<div class="card ignored">
      <div class="grow">
        <div class="name">${name}</div>
        <div class="sub">${sub}</div>
      </div>
      <button class="primary" @click=${add}>${t("appliances.set_up")}</button>
    </div>`;
    return [
      ...(ig?.appliances ?? []).map((f) =>
        card(f.name, f.units.map((u) => u.label).join(" · "), () => (this._adding = plain(f))),
      ),
      ...(ig?.pools ?? []).map((f) =>
        card(f.name, listOf(tilesOf(f.layout)), () => (this._poolAdding = { ...f, notes: undefined } as unknown as PoolProfile)),
      ),
      ...(ig?.robots ?? []).map((f) =>
        card(f.name, t("robot.title"), () => (this._robotAdding = { id: f.id, name: f.name, vacuum: f.vacuum, error: f.error, preset: f.preset })),
      ),
    ];
  }

  private _presetName(id: string): string {
    return this.doc?.appliance_presets?.find((p) => p.id === id)?.name ?? id;
  }

  private _unitNow(apId: string, unitId: string): string {
    const u = (
      applianceSensor(this.hass, apId)?.attributes.units as
        | { id: string; phase: string; status: string; time_left: string; status_word?: unknown; time_word?: unknown }[]
        | undefined
    )?.find((x) => x.id === unitId);
    if (!u) return "";
    // (this device's language: the words, when the sensor gives them)
    const status = localText(u.status_word, u.status);
    return [status || (u.phase ? phaseText(u.phase) : ""), localText(u.time_word, u.time_left)].filter(Boolean).join(" ");
  }

  /** a pool body's live status line (its Room Tiles sensor) */
  private _poolNow(poolId: string, body: string): string {
    const st = Object.values(this.hass?.states ?? {}).find(
      (s) => s.entity_id.startsWith("sensor.") && s.attributes.pool === poolId && s.attributes.body === body && !("mode" in s.attributes),
    );
    if (!st) return "";
    const temp = st.attributes.temperature;
    return [typeof temp === "number" ? `${num(temp)}°` : "", localText(st.attributes.status_word, st.attributes.status)].filter(Boolean).join(" · ");
  }

  private _poolCards(found: (PoolProfile & { notes: SetupNote[] })[], set: PoolProfile[]) {
    const layout = (p: PoolProfile) => t(`appliances.pool_${p.layout}`);
    return {
      found: found.map(
        (f) => html`<div class="card found">
          <div class="grow">
            <div class="name">${f.name}</div>
            <div class="sub">${layout(f)} · ${t("appliances.tiles", { list: listOf(tilesOf(f.layout)) })}</div>
            ${f.notes.map((n) => html`<div class="note">${wordText(n)}</div>`)}
          </div>
          <div class="btns">
            <button class="plain" @click=${() => this._ignore("pool", { ...f, notes: undefined } as unknown as PoolProfile)}>${t("common.ignore")}</button>
            <button class="primary" @click=${() => (this._poolAdding = { ...f, notes: undefined } as unknown as PoolProfile)}>${t("appliances.set_up")}</button>
          </div>
        </div>`,
      ),
      set: set.map(
        (p) => html`<div class="card">
          <div class="grow">
            <div class="name">${p.name}</div>
            ${bodiesOf(p.layout).map(
              (b) => html`<div class="sub"><b>${t(`pools.tile_${b}`)}</b> ${this._poolNow(p.id, b)}</div>`,
            )}
            ${this._betaRow("pool", p.id, p.name)} ${this._problemRow("pool", p.id, p.name)}
          </div>
          <button class="pencil" aria-label=${t("common.edit_name", { name: p.name })} title=${t("common.edit")} @click=${() => (this._poolEdit = p.id)}>
            <ha-icon icon="mdi:pencil"></ha-icon>
          </button>
        </div>`,
      ),
    };
  }

  private _robotCards() {
    const status = (id: string) => {
      const a = Object.values(this.hass?.states ?? {}).find((st) => st.entity_id.startsWith("sensor.") && st.attributes.robot === id)?.attributes;
      return localText(a?.status_word, a?.status); // (this device's language)
    };
    return {
      found: (this.doc?.robot_found ?? []).map(
        (f) => html`<div class="card found">
          <div class="grow">
            <div class="name">${f.name}</div>
            <div class="sub">${[t("robot.title"), f.error ? t("appliances.matter_alerts") : "", f.clean_area ? t("appliances.room_cleaning") : ""].filter(Boolean).join(" · ")}</div>
            ${f.notes
              .filter((n) => typeof n === "object" && n !== null && (n as { k?: string }).k === "setup_note.rooms_no")
              .map((n) => html`<div class="note">${wordText(n)}</div>`)}
          </div>
          <div class="btns">
            <button class="plain" @click=${() => this._ignore("robot", { id: f.id, name: f.name, vacuum: f.vacuum, error: f.error, preset: f.preset })}>
              ${t("common.ignore")}
            </button>
            <button
              class="primary"
              @click=${() => (this._robotAdding = { id: f.id, name: f.name, vacuum: f.vacuum, error: f.error, preset: f.preset })}
            >
              ${t("appliances.set_up")}
            </button>
          </div>
        </div>`,
      ),
      set: (this.doc?.robots ?? []).map(
        (r) => html`<div class="card">
          <div class="grow">
            <div class="name">${r.name}</div>
            <div class="sub">${status(r.id)}</div>
            ${this._robotQuestions(r)} ${this._told?.robot === r.id ? this._tellOffer(this._told) : nothing}
            ${this._betaRow("robot", r.id, r.name)} ${this._problemRow("robot", r.id, r.name)}
          </div>
          <button class="pencil" aria-label=${t("common.edit_name", { name: r.name })} title=${t("common.edit")} @click=${() => (this._robotEdit = r.id)}>
            <ha-icon icon="mdi:pencil"></ha-icon>
          </button>
        </div>`,
      ),
    };
  }

  render() {
    const ignored = this._ignoredCards();
    const robots = this._robotCards();
    const robotEditing = this._robotAdding ?? (this.doc?.robots ?? []).find((r) => r.id === this._robotEdit);
    const pools = this._poolCards(this.doc?.pool_found ?? [], this.doc?.pools ?? []);
    const poolEditing = this._poolAdding ?? (this.doc?.pools ?? []).find((p) => p.id === this._poolEdit);
    const set = this.doc?.appliances ?? [];
    const found = this.doc?.appliance_found ?? [];
    const editing = this._adding ?? (this._edit !== undefined ? set.find((a) => a.id === this._edit) : undefined);
    return html`
      <div class="scrim" @click=${() => Date.now() - this._opened > 400 && this._close()}></div>
      <div class="dialog" role="dialog" aria-label=${t("appliances.title")}>
        <div class="head">
          <div class="title">${t("appliances.title")}</div>
          <button class="x" aria-label=${t("common.close")} title=${t("common.close")} @click=${this._close}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        <div class="intro">
          ${th("appliances.intro", { link: html`<a href=${SUPPORTED_URL} target="_blank" rel="noreferrer">${t("appliances.supported_devices")}</a>` })}
        </div>
        <div class="list">
          ${found.length || pools.found.length || robots.found.length
            ? html`<div class="group found-list">
                <div class="group-head"><ha-icon icon="mdi:magnify"></ha-icon>${t("appliances.found")}</div>
                ${pools.found} ${robots.found}
                ${found.map(
                  (f) => html`<div class="card found">
                    <div class="grow">
                      <div class="name">${f.name}</div>
                      <div class="sub">${f.units.map((u) => `${u.label} (${this._presetName(u.preset)})`).join(" · ")}</div>
                      ${f.notes.map((n) => html`<div class="note">${wordText(n)}</div>`)}
                    </div>
                    <div class="btns">
                      <button class="plain" @click=${() => this._ignore("appliance", plain(f))}>${t("common.ignore")}</button>
                      <button class="primary" @click=${() => (this._adding = plain(f))}>${t("appliances.set_up")}</button>
                    </div>
                  </div>`,
                )}
              </div>`
            : nothing}
          ${set.length || pools.set.length || robots.set.length
            ? html`<div class="group set-up">
                <div class="group-head"><ha-icon icon="mdi:check-circle-outline"></ha-icon>${t("appliances.set_up_list")}</div>
                ${pools.set} ${robots.set}
                ${set.map(
                  (a) => html`<div class="card">
                    <div class="grow">
                      <div class="name">${a.name}</div>
                      ${a.units.map((u) => html`<div class="sub"><b>${u.label}</b> ${this._unitNow(a.id, u.id)}</div>`)}
                      ${this._questions(a)}
                      ${this._told?.appliance === a.id ? this._tellOffer(this._told) : nothing}
                      ${this._betaRow("appliance", a.id, a.name, a.units)}
                      ${this._problemRow("appliance", a.id, a.name, a.units)}
                    </div>
                    <button class="pencil" aria-label=${t("common.edit_name", { name: a.name })} title=${t("common.edit")} @click=${() => (this._edit = a.id)}>
                      <ha-icon icon="mdi:pencil"></ha-icon>
                    </button>
                  </div>`,
                )}
              </div>`
            : nothing}
          ${!set.length && !found.length && !pools.set.length && !pools.found.length && !robots.set.length && !robots.found.length
            ? html`<div class="empty">${t("appliances.none_found")}</div>`
            : nothing}
          <div class="group">
          <div class="group-head"><ha-icon icon="mdi:power-plug-outline"></ha-icon>${t("appliances.by_hand")}</div>
          <div class="info">${t("appliances.by_hand_info")}</div>
          <div class="by-hand">
            ${(["washer", "dryer", "dishwasher"] as const).map(
              (k) => html`<button class="plain" @click=${() => (this._adding = byHand(k, this.doc))}>
                <ha-icon icon=${UNIT_ICON[k]}></ha-icon> ${t(`appliances.kind_${k}`)}
              </button>`,
            )}
          </div>
          </div>
          ${ignored.length
            ? html`<div class="group ignored-list">
                <div class="group-head"><ha-icon icon="mdi:eye-off-outline"></ha-icon>${t("appliances.ignored")}</div>
                <div class="info">${t("appliances.ignored_info")}</div>
                ${ignored}
              </div>`
            : nothing}
        </div>
        <div class="footer">
          <button class="primary" @click=${this._close}>${t("common.done")}</button>
        </div>
      </div>
      ${this._report
        ? html`<rt-report
            .hass=${this.hass}
            kind="unknown_state"
            .draft=${this._report.robot
              ? { robot: this._report.robot, code: this._report.state, answer: this._report.answer }
              : { appliance: this._report.appliance, unit: this._report.unit, state: this._report.state, answer: this._report.answer }}
            .about=${this._report.name}
            @close=${(e: Event) => {
              e.stopPropagation(); // back to this list, not out of it
              this._report = undefined;
            }}
          ></rt-report>`
        : nothing}
      ${this._model
        ? html`<rt-model-report
            .hass=${this.hass}
            .subject=${this._model.subject}
            .target=${this._model.id}
            .name=${this._model.name}
            .units=${this._model.units}
            @close=${(e: Event) => {
              e.stopPropagation(); // back to this list, not out of it
              this._model = undefined;
            }}
          ></rt-model-report>`
        : nothing}
      ${this._problem
        ? html`<rt-problem
            .hass=${this.hass}
            .subject=${this._problem.subject}
            .target=${this._problem.id}
            .name=${this._problem.name}
            .units=${this._problem.units}
            .recording=${this._readyRecording(this._problem)}
            @close=${(e: Event) => {
              e.stopPropagation(); // back to this list, not out of it
              this._problem = undefined;
            }}
          ></rt-problem>`
        : nothing}
      ${robotEditing
        ? html`<rt-robot-editor
            .hass=${this.hass}
            .doc=${this.doc}
            .profile=${robotEditing}
            .adding=${!!this._robotAdding}
            @close=${(e: Event) => {
              e.stopPropagation(); // back to this list, not out of it
              this._robotAdding = undefined;
              this._robotEdit = undefined;
            }}
          ></rt-robot-editor>`
        : nothing}
      ${poolEditing
        ? html`<rt-pool-editor
            .hass=${this.hass}
            .doc=${this.doc}
            .profile=${poolEditing}
            .adding=${!!this._poolAdding}
            @close=${(e: Event) => {
              e.stopPropagation(); // back to this list, not out of it
              this._poolAdding = undefined;
              this._poolEdit = undefined;
            }}
          ></rt-pool-editor>`
        : nothing}
      ${editing
        ? html`<rt-appliance-editor
            .hass=${this.hass}
            .doc=${this.doc}
            .profile=${editing}
            .adding=${!!this._adding}
            @close=${(e: Event) => {
              // back to this list: the editor's close must not reach the
              // panel, which would close the Appliances dialog too
              e.stopPropagation();
              this._adding = undefined;
              this._edit = undefined;
            }}
          ></rt-appliance-editor>`
        : nothing}
    `;
  }

  static styles = [
    noSelectStyles,
    groupStyles,
    dialogStyles,
    rowStyles,
    css`
      :host {
        --dialog-w: 560px;
      }
      .card {
        display: flex;
        gap: 10px;
        align-items: center;
        padding: 10px 12px;
        border-radius: 12px;
        background: var(--rt-panel-dark);
      }
      .grow {
        flex: 1;
        min-width: 0;
      }
      .name {
        font-weight: 500;
      }
      .sub {
        font-size: 0.85rem;
        color: var(--rt-text-secondary);
      }
      .sub b {
        font-weight: 500;
        color: var(--rt-text);
      }
      .note {
        font-size: 0.85rem;
        color: var(--rt-light);
      }
      .intro a {
        color: var(--rt-accent);
      }
      .empty {
        font-size: 0.85rem;
        color: var(--rt-text-secondary);
        padding: 4px 2px 8px;
      }
      .pencil {
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        border-radius: 8px;
        padding: 6px;
        --mdc-icon-size: 22px;
      }
      .info {
        font-size: 0.85rem;
        color: var(--rt-text-secondary);
        padding: 2px 4px 6px;
      }
      .btns {
        display: flex;
        gap: 6px;
        flex: none;
      }
      /* a card's actions: Ignore plain, Set up the accent pill (as the
         footer's main button) - it must read as "set this up" */
      .card button.plain,
      .card button.primary {
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        color: var(--rt-text);
        border-radius: 10px;
        padding: 7px 12px;
        font-size: 0.9rem;
        white-space: nowrap;
        cursor: pointer;
      }
      .card button.primary {
        background: var(--rt-accent);
        color: var(--rt-on-accent);
        border-color: var(--rt-accent);
        font-weight: 500;
      }
      .beta {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        column-gap: 10px;
        margin-top: 4px;
        font-size: 0.85rem;
        color: var(--rt-text-secondary);
      }
      .beta button.link {
        margin-top: 0;
      }
      .recording {
        margin-top: 6px;
        padding: 6px 8px;
        border-radius: 10px;
        border: 1px solid var(--rt-tile-border);
        font-size: 0.85rem;
      }
      .card button.link {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        margin-top: 4px;
        min-height: 44px;
        padding: 0;
        border: none;
        background: none;
        color: var(--rt-accent);
        font-size: 0.85rem;
        cursor: pointer;
        --mdc-icon-size: 18px;
      }
      .question {
        margin-top: 6px;
        padding: 6px 8px;
        border-radius: 10px;
        border: 1px solid var(--rt-light);
        font-size: 0.85rem;
      }
      .question .answers,
      .recording .answers {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
        margin-top: 6px;
      }
      .question .answers button,
      .recording .answers button {
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        color: var(--rt-text);
        border-radius: 10px;
        padding: 5px 10px;
        min-height: 40px;
      }
      .recording .answers button.primary {
        background: var(--rt-accent);
        color: var(--rt-on-accent);
        border-color: var(--rt-accent);
      }
      .card.ignored {
        opacity: 0.75;
      }
      .group.found-list,
      .group.set-up,
      .group.ignored-list {
        gap: 6px;
      }
      /* item cards inside a framed group: a shade lighter than the group */
      .group .card {
        background: var(--rt-dialog);
      }
      .by-hand {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }
      .by-hand button {
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        border-radius: 10px;
        padding: 8px 12px;
        display: inline-flex;
        align-items: center;
        gap: 6px;
        --mdc-icon-size: 20px;
      }
    `,
  ];
}

/** A tile arrangement the editor offers: what appliances (tiles) result. */
interface Arrangement {
  key: string; // "together" | "separate" | "keep" | "with:<id>"
  icon: string;
  label: string;
  sub: string;
  result: ApplianceProfile[];
  partner?: string;
}

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

/** What a finished unit shows on its tile (the integration's status text). */
const finishedText = (u: ApplianceUnitProfile): string =>
  u.finished === "waiting" ? t("appliances.finish_waiting") : u.appliance === "dishwasher" ? t("appliances.finish_clean") : t("appliances.finish_done");

/** "When it finishes, show": Done (Clean for a dishwasher), Switch Over
 *  (washers), or Idle - no finished state at all. */
const finishOptions = (u: ApplianceUnitProfile): [ApplianceUnitProfile["finished"], string][] => [
  ["done", u.appliance === "dishwasher" ? t("appliances.finish_clean") : t("appliances.finish_done")],
  ...(u.appliance === "washer" ? ([["waiting", t("appliances.finish_waiting")]] as [ApplianceUnitProfile["finished"], string][]) : []),
  ["idle", t("appliances.finish_idle")],
];

const UNIT_ICON: Record<string, string> = {
  washer: "mdi:washing-machine",
  dryer: "mdi:tumble-dryer",
  dishwasher: "mdi:dishwasher",
};

/** A new appliance added by hand: a smart plug's power (the generic profile). */
export function byHand(kind: "washer" | "dryer" | "dishwasher", doc?: RoomTilesDoc): ApplianceProfile {
  const taken = new Set((doc?.appliances ?? []).map((a) => a.id));
  let id: string = kind;
  for (let n = 2; taken.has(id); n++) id = `${kind}_${n}`;
  const label = t(`appliances.kind_${kind}`);
  // a washer: with a dryer around, Switch Over until it (its own tile)
  // starts; with none, straight back to idle (the integration's washer_default)
  const apps = doc?.appliances ?? [];
  const dryerTiles = apps.filter((a) => a.units.length === 1 && a.units[0].appliance === "dryer").map((a) => a.id);
  const anyDryer = apps.some((a) => a.units.some((u) => u.appliance === "dryer"));
  const finished: ApplianceUnitProfile["finished"] = kind !== "washer" ? "done" : anyDryer ? "waiting" : "idle";
  const clear = kind === "washer" && dryerTiles.length === 1 ? [`appliance:${dryerTiles[0]}`] : [];
  return {
    id,
    name: label,
    units: [
      {
        id: kind,
        label,
        appliance: kind,
        preset: `power_${kind}`,
        status: "",
        time: null,
        door: null,
        door_clears: true,
        finished,
        clear,
        drawer: false,
        overrides: {},
        power_on_w: 5,
        // a dishwasher dries with almost no power: give it longer
        power_off_min: kind === "dishwasher" ? 20 : 3,
      },
    ],
  };
}

/** Default name for two appliances sharing a tile (the integration's rule). */
function pairName(a: ApplianceProfile, b: ApplianceProfile): string {
  const kinds = new Set([...a.units, ...b.units].map((u) => u.appliance));
  if (kinds.size === 2 && kinds.has("washer") && kinds.has("dryer")) return t("appliances.name_laundry");
  if (kinds.size === 1 && kinds.has("dishwasher")) return t("appliances.name_dishwashers");
  return `${a.name} + ${b.name}`;
}

/** Two units on one tile: a washer with a dryer waits for it (switch over
 *  until the dryer starts) - setup's pairing. No other "unit" rules. */
function pairRules(units: ApplianceUnitProfile[]): void {
  const dryer = units.find((u) => u.appliance === "dryer");
  for (const u of units) {
    u.clear = u.clear.filter((c) => !c.startsWith("unit:") && !c.startsWith("appliance:"));
    if (u.appliance === "washer" && dryer && u.finished !== "idle") {
      u.finished = "waiting";
      u.clear = [...u.clear, `unit:${dryer.id}`];
    }
  }
}

/** An appliance's settings - and, first, its tile: one dialog, a draft until
 *  Save. Picking a tile card only changes what's shown below. Adding a found
 *  appliance uses the same dialog (`adding`: Save adds it). */
export class RtApplianceEditor extends LitElement {
  /** fades where a scrolling area has more (ui.ts ScrollFades) */
  protected readonly _scrollFades = new ScrollFades(this, ".list");

  /** the dialog's top edge stays put while its content changes (dialog-pin.ts) */
  readonly dialogPin = new DialogPin(this);
  static properties = {
    hass: { attribute: false },
    doc: { attribute: false },
    profile: { attribute: false },
    adding: { type: Boolean },
    _choice: { state: true },
    _drafts: { state: true },
    _ask: { state: true },
    _confirmRemove: { state: true },
    _busy: { state: true },
    _error: { state: true },
  };

  hass?: HomeAssistant;
  doc?: RoomTilesDoc;
  profile?: ApplianceProfile;
  /** a found appliance, not stored yet: Save adds it */
  adding = false;
  private _choice = "";
  /** the user's edits per tile choice (switching cards keeps them) */
  private _drafts: Record<string, ApplianceProfile[]> = {};
  private _ask = false;
  private _confirmRemove = false;
  private _busy = false;
  private _error = "";
  private _opened = Date.now();

  /** The id the integration gives a split-off unit (its unit id, made unique). */
  private _newId(base: string, also: string[] = []): string {
    const taken = new Set([...(this.doc?.appliances ?? []).map((a) => a.id), ...also]);
    let id = base;
    for (let n = 2; taken.has(id); n++) id = `${base}_${n}`;
    return id;
  }

  /** The tile choices for this appliance; the first is how it is now. */
  private get _arrangements(): Arrangement[] {
    const p = this.profile!;
    if (p.units.length === 2) {
      const [a, b] = p.units;
      const ids: string[] = [];
      const apart = p.units.map((u, i) => {
        const unit = clone(u);
        unit.clear = unit.clear.filter((c) => !c.startsWith("unit:"));
        // splitting keeps the first on this appliance's id; adding makes two new ones
        const id = i === 0 && !this.adding ? p.id : this._newId(u.id, ids);
        ids.push(id);
        return { id, name: u.label, units: [unit] };
      });
      // a washer keeps its Switch Over - emptied by the dryer's own tile starting
      const dryerTile = apart.find((t) => t.units[0].appliance === "dryer");
      for (const t of apart) {
        const unit = t.units[0];
        if (unit.finished !== "waiting") continue;
        if (dryerTile && t !== dryerTile) unit.clear = [...unit.clear, `appliance:${dryerTile.id}`];
        else unit.finished = "done";
      }
      return [
        { key: "together", icon: "mdi:view-agenda-outline", label: t("appliances.one_tile"), sub: t("appliances.above", { top: a.label, bottom: b.label }), result: [clone(p)] },
        { key: "separate", icon: "mdi:view-grid-outline", label: t("appliances.separate_tiles"), sub: t("appliances.each_own", { a: a.label, b: b.label }), result: apart },
      ];
    }
    const own: Arrangement = { key: "keep", icon: "mdi:square-outline", label: t("appliances.own_tile"), sub: t("appliances.just_this"), result: [clone(p)] };
    if (this.adding) return [own];
    const partners = (this.doc?.appliances ?? []).filter((x) => x.id !== p.id && x.units.length === 1);
    return [
      own,
      ...partners.map((o) => {
        const mine = clone(p.units[0]);
        const theirs = clone(o.units[0]);
        if (theirs.id === mine.id) theirs.id = `${theirs.id}_2`;
        // a dryer always goes above its washer (Swap order changes it)
        const units = [mine, theirs].sort((x, y) => Number(x.appliance !== "dryer") - Number(y.appliance !== "dryer"));
        pairRules(units);
        return {
          key: `with:${o.id}`,
          icon: "mdi:view-agenda-outline",
          label: t("appliances.share_with", { name: o.name }),
          sub: t("appliances.above", { top: units[0].label, bottom: units[1].label }),
          result: [{ id: p.id, name: pairName(p, o), units }],
          partner: o.id,
        };
      }),
    ];
  }

  private get _key(): string {
    const keys = this._arrangements.map((a) => a.key);
    return keys.includes(this._choice) ? this._choice : keys[0];
  }

  /** what Save stores: one or two appliances (tiles) */
  private get _views(): ApplianceProfile[] {
    return this._drafts[this._key] ?? this._arrangements.find((a) => a.key === this._key)!.result;
  }

  private get _dirty(): boolean {
    if (this.adding) return true;
    const first = this._arrangements[0];
    return this._key !== first.key || JSON.stringify(this._views) !== JSON.stringify(first.result);
  }

  private _change(ap: number, fn: (p: ApplianceProfile) => void): void {
    const views = clone(this._views);
    fn(views[ap]);
    this._drafts = { ...this._drafts, [this._key]: views };
  }

  private _close(): void {
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  }

  private _tryClose(): void {
    if (this._dirty && !this.adding) this._ask = true;
    else this._close();
  }

  private async _run(fn: () => Promise<unknown>): Promise<void> {
    this._busy = true;
    this._error = "";
    try {
      await fn();
      this._close();
    } catch (err) {
      this._error = (err as { message?: string })?.message ?? String(err);
    } finally {
      this._busy = false;
    }
  }

  /** Save: the tile change (split / combine) first, then each resulting
   *  appliance's settings. Adding: just store what's shown. */
  private _save(): Promise<void> {
    const views = clone(this._views).map((ap) => {
      ap.units.forEach((u) => (u.label = u.label.trim() || u.label));
      ap.name = ap.name.trim() || ap.units[0].label;
      return ap;
    });
    const arr = this._arrangements.find((a) => a.key === this._key)!;
    const p = this.profile!;
    const call = (service: string, data: Record<string, unknown>) => this.hass!.callService("room_tiles", service, data);
    return this._run(async () => {
      if (!this.adding && arr.key === "separate") await call("split_appliance", { appliance: p.id, unit: p.units[1].id });
      if (!this.adding && arr.partner) await call("combine_appliances", { appliance: p.id, with: arr.partner });
      // a tile another one waits for (a dryer) is stored first: the rule needs it
      const waitedFor = (ap: ApplianceProfile) => views.some((v) => v.units.some((u) => u.clear.includes(`appliance:${ap.id}`)));
      views.sort((x, y) => Number(waitedFor(y)) - Number(waitedFor(x)));
      for (const ap of views) await setUpDevice(this, this.hass!, "set_appliance", { appliance: ap }, ap.name);
    });
  }

  /** what setup would make of this appliance's hardware now */
  private get _again(): ApplianceProfile | undefined {
    const a = this.doc?.appliance_again?.[this.profile!.id];
    return a ? { id: a.id, name: a.name, units: a.units } : undefined;
  }

  /** A fresh setup of its hardware, as a draft (Save keeps it). */
  private _setUpAgain(): void {
    const a = this._again;
    if (!a) return;
    const key = this._arrangements[0].key;
    this._choice = key;
    this._drafts = { ...this._drafts, [key]: [clone(a)] };
  }

  private _remove(): void {
    if (!this._confirmRemove) {
      this._confirmRemove = true;
      return;
    }
    void this._run(() =>
      this.hass!.callService("room_tiles", "ignore_device", { kind: "appliance", device: this.profile!, set_up_id: this.profile!.id }),
    );
  }

  /** Motion and contact sensors in the same HA area as the appliance (its
   *  status entity / device) - offered unticked in the checklist. */
  private _nearby(u: ApplianceUnitProfile): string[] {
    const area = areaOf(this.hass, u.status);
    if (!area) return [];
    return Object.values(this.hass?.states ?? {})
      .filter(
        (st) =>
          st.entity_id.startsWith("binary_sensor.") &&
          [...CONTACT, ...MOTION].includes(st.attributes.device_class as string) &&
          !this.hass?.entities?.[st.entity_id]?.entity_category &&
          st.entity_id !== u.door &&
          !u.clear.includes(st.entity_id) &&
          areaOf(this.hass, st.entity_id) === area,
      )
      .map((st) => st.entity_id)
      .sort((a, b) => friendly(this.hass, a).localeCompare(friendly(this.hass, b)));
  }

  /** binary sensors that can say "emptied" - doors / openings first */
  private _sensors(): HassEntity[] {
    // not diagnostic / config entities (battery, cloud connection...): only
    // what the sensor actually senses
    const all = Object.values(this.hass?.states ?? {}).filter(
      (s) => s.entity_id.startsWith("binary_sensor.") && !this.hass?.entities?.[s.entity_id]?.entity_category,
    );
    const doorish = (s: HassEntity) => ["door", "opening", "window", "garage_door"].includes(s.attributes.device_class as string);
    const name = (s: HassEntity) => String(s.attributes.friendly_name ?? s.entity_id);
    return all.sort((a, b) => Number(doorish(b)) - Number(doorish(a)) || name(a).localeCompare(name(b)));
  }

  /** The dryer whose starting resets washer `u`'s Switch Over: one on its
   *  tile (unit:), else the one dryer on its own tile (appliance:); none
   *  with several (the user ticks one). */
  private _dryerKey(ap: number, u: ApplianceUnitProfile): string | undefined {
    const same = this._views[ap].units.find((x) => x.id !== u.id && x.appliance === "dryer");
    if (same) return `unit:${same.id}`;
    const tiles = this._dryerTiles(ap);
    return tiles.length === 1 ? `appliance:${tiles[0].id}` : undefined;
  }

  /** Dryers on their own tile besides tile `ap`: this dialog's other tile,
   *  or ones already set up. */
  private _dryerTiles(ap: number): ApplianceProfile[] {
    const mine = this._views[ap].id;
    return [
      ...this._views.filter((t) => t.id !== mine),
      ...(this.doc?.appliances ?? []).filter((t) => t.id !== mine && t.id !== this.profile?.id && !this._views.some((v) => v.id === t.id)),
    ].filter((t) => t.units.length === 1 && t.units[0].appliance === "dryer");
  }

  /** The "emptied by" checklist of tile `ap`'s unit `i`: the tap (always on,
   *  can't be unticked), its door (if it has one), the dryer starting (a
   *  washer sharing a tile with one), every picked sensor, then the motion /
   *  contact sensors in its area (offered unticked). */
  private _emptiedBy(ap: number, u: ApplianceUnitProfile, i: number) {
    const other = this._views[ap].units.find((x) => x.id !== u.id);
    const set = (fn: (x: ApplianceUnitProfile) => void) => this._change(ap, (d) => fn(d.units[i]));
    const row = (text: string, checked: boolean, onChange?: (on: boolean) => void, cls = "") =>
      html`<label class="check ${cls}">
        <input
          type="checkbox"
          .checked=${live(checked)}
          ?disabled=${!onChange}
          @change=${(e: Event) => onChange?.((e.target as HTMLInputElement).checked)}
        />
        ${text}
      </label>`;
    const rows = [row(t("appliances.clear_tap"), true, undefined, "always")];
    if (u.door)
      rows.push(row(t("appliances.clear_door", { name: friendly(this.hass, u.door) }), u.door_clears, (on) => set((x) => (x.door_clears = on))));
    // only a washer is emptied by its paired dryer starting (the load moved
    // on); nothing else makes sense (a dryer by the washer, one drawer by
    // the other)
    if (other && u.appliance === "washer" && other.appliance === "dryer") {
      const key = `unit:${other.id}`;
      rows.push(
        row(t("appliances.clear_starting", { name: other.label }), u.clear.includes(key), (on) =>
          set((x) => (x.clear = x.clear.filter((c) => c !== key).concat(on ? [key] : []))),
        ),
      );
    }
    // a washer on its own tile: a dryer on its own tile (this dialog's other
    // tile, or one already set up)
    if (!other && u.appliance === "washer") {
      for (const tile of this._dryerTiles(ap)) {
        const key = `appliance:${tile.id}`;
        rows.push(
          row(t("appliances.clear_starting", { name: tile.units[0].label }), u.clear.includes(key), (on) =>
            set((x) => (x.clear = x.clear.filter((c) => c !== key).concat(on ? [key] : []))),
          ),
        );
      }
    }
    // picked and nearby sensors in ONE list by name: ticking one doesn't move
    // it (rows keep their place; live() keeps each box in step with the data)
    const sensors = [...u.clear.filter((x) => !x.startsWith("unit:") && !x.startsWith("appliance:")), ...this._nearby(u)].sort((a, b) =>
      friendly(this.hass, a).localeCompare(friendly(this.hass, b)),
    );
    for (const e of sensors)
      rows.push(
        row(sensorText(this.hass, e), u.clear.includes(e), (on) =>
          set((x) => (x.clear = x.clear.filter((y) => y !== e).concat(on ? [e] : []))),
        ),
      );
    return rows;
  }

  private _unit(ap: number, u: ApplianceUnitProfile, i: number) {
    const presets = (this.doc?.appliance_presets ?? []).filter((x) => x.appliance === u.appliance);
    const set = (fn: (x: ApplianceUnitProfile) => void) => this._change(ap, (d) => fn(d.units[i]));
    return html`<div class="group">
      <div class="group-head"><ha-icon icon=${UNIT_ICON[u.appliance]}></ha-icon>${u.label}</div>
      <div class="setting">
        <span class="label">${t("appliances.name_on_tile")}</span>
        <input
          .value=${u.label}
          maxlength=${MAX_SHORT}
          aria-label=${t("appliances.name_on_tile_of", { name: u.label })}
          @input=${(e: Event) => set((x) => (x.label = (e.target as HTMLInputElement).value))}
        />
      </div>
      <div class="setting">
        <span class="label">${t("appliances.brand")}</span>
        <select @change=${(e: Event) => set((x) => (x.preset = (e.target as HTMLSelectElement).value))}>
          ${presets.map((x) => html`<option value=${x.id} ?selected=${x.id === u.preset}>${x.verified ? x.name : t("appliances.beta", { name: x.name })}</option>`)}
        </select>
      </div>
      ${this._isPower(u)
        ? this._powerFields(ap, u, i)
        : html`<div class="info">
            ${u.time
              ? t("appliances.reads_two", { a: friendly(this.hass, u.status), b: friendly(this.hass, u.time) })
              : t("appliances.reads", { a: friendly(this.hass, u.status) })}
          </div>`}
      <div class="setting">
        <span class="label">${t("appliances.when_finished")}</span>
        <div class="segmented">
          ${finishOptions(u).map(
            ([value, label]) =>
              html`<button
                class=${u.finished === value ? "on" : ""}
                @click=${() =>
                  set((x) => {
                    x.finished = value;
                    // Switch Over: reset by the dryer starting (when there's one to pick)
                    const key = value === "waiting" ? this._dryerKey(ap, x) : undefined;
                    if (key && !x.clear.includes(key)) x.clear = [...x.clear, key];
                  })}
              >
                ${label}
              </button>`,
          )}
        </div>
      </div>
      ${u.finished === "idle" ? nothing : this._transition(ap, u, i)}
    </div>`;
  }

  private _isPower(u: ApplianceUnitProfile): boolean {
    return !!this.doc?.appliance_presets?.find((p) => p.id === u.preset)?.power;
  }

  /** A smart plug: its power sensor, the threshold, how long low = finished. */
  private _powerFields(ap: number, u: ApplianceUnitProfile, i: number) {
    const set = (fn: (x: ApplianceUnitProfile) => void) => this._change(ap, (d) => fn(d.units[i]));
    const sensors = Object.values(this.hass?.states ?? {})
      .filter((s) => s.entity_id.startsWith("sensor.") && s.attributes.device_class === "power")
      .sort((a, b) => String(a.attributes.friendly_name ?? a.entity_id).localeCompare(String(b.attributes.friendly_name ?? b.entity_id)));
    const num = (v: string, d: number) => (Number.isFinite(Number(v)) && v.trim() !== "" ? Number(v) : d);
    return html`<div class="setting">
        <span class="label">${t("appliances.power_sensor")}</span>
        <select aria-label=${t("appliances.power_sensor")} @change=${(e: Event) => set((x) => (x.status = (e.target as HTMLSelectElement).value))}>
          <option value="" ?selected=${!u.status}>${t("common.choose_ellipsis")}</option>
          ${sensors.map(
            (st) => html`<option value=${st.entity_id} ?selected=${st.entity_id === u.status}>${st.attributes.friendly_name ?? st.entity_id}</option>`,
          )}
        </select>
      </div>
      <div class="setting">
        <span class="label">${t("appliances.running_above")}</span>
        <input
          class="num"
          inputmode="decimal"
          .value=${String(u.power_on_w ?? 5)}
          aria-label=${t("appliances.running_above")}
          @input=${(e: Event) => set((x) => (x.power_on_w = num((e.target as HTMLInputElement).value, 5)))}
        />
      </div>
      <div class="setting">
        <span class="label">${t("appliances.finished_after")}</span>
        <input
          class="num"
          inputmode="decimal"
          .value=${String(u.power_off_min ?? 3)}
          aria-label=${t("appliances.finished_after")}
          @input=${(e: Event) => set((x) => (x.power_off_min = num((e.target as HTMLInputElement).value, 3)))}
        />
      </div>`;
  }

  /** "Transition from Done to Idle when" + "Another sensor" - only when the
   *  unit has a finished state to leave. */
  private _transition(ap: number, u: ApplianceUnitProfile, i: number) {
    const set = (fn: (x: ApplianceUnitProfile) => void) => this._change(ap, (d) => fn(d.units[i]));
    return html`
      <div class="checks">
        <div class="sub-head">${t("appliances.transition", { state: finishedText(u), idle: t("appliances.finish_idle") })}</div>
        ${this._emptiedBy(ap, u, i)}
      </div>
      <div class="setting">
        <span class="label">${t("appliances.another_sensor")}</span>
        <select
          aria-label=${t("appliances.another_sensor_of", { name: u.label })}
          @change=${(e: Event) => {
            const sel = e.target as HTMLSelectElement;
            const v = sel.value;
            sel.value = "";
            if (v) set((x) => (x.clear = [...x.clear, v]));
          }}
        >
          <option value="" selected>${t("appliances.choose_sensor")}</option>
          ${this._sensors()
            .filter((st) => !u.clear.includes(st.entity_id))
            .map((st) => html`<option value=${st.entity_id}>${st.attributes.friendly_name ?? st.entity_id}</option>`)}
        </select>
      </div>
    `;
  }

  /** Another tile-picker entry already has this name (a heads-up, not a rule:
   *  repeated names are allowed). */
  private _sameName(ap: ApplianceProfile): boolean {
    const name = ap.name.trim().toLowerCase();
    const own = applianceSensor(this.hass, ap.id)?.entity_id;
    return !!name && (this.doc?.catalog.entries ?? []).some((e) => e.entity !== own && e.short_name.toLowerCase() === name);
  }

  /** The tile choice: cards; picking one only changes what's shown below. */
  private _tileCards() {
    const arrs = this._arrangements;
    if (arrs.length < 2)
      return html`<div class="group">
        <div class="group-head"><ha-icon icon="mdi:view-grid-outline"></ha-icon>${t("appliances.tile")}</div>
        <div class="info">${t("appliances.tile_only", { name: this.profile!.name })}</div>
      </div>`;
    return html`<div class="group">
      <div class="group-head"><ha-icon icon="mdi:view-grid-outline"></ha-icon>${t("appliances.tile")}</div>
      <div class="cards" role="radiogroup" aria-label=${t("appliances.tile")}>
        ${arrs.map(
          (a) => html`<button
            class="card ${a.key === this._key ? "on" : ""}"
            role="radio"
            aria-checked=${a.key === this._key ? "true" : "false"}
            @click=${() => (this._choice = a.key)}
          >
            <ha-icon icon=${a.icon}></ha-icon>
            <span>${a.label}</span><small>${a.sub}</small>
          </button>`,
        )}
      </div>
    </div>`;
  }

  /** One resulting appliance (tile): its name, order, units. */
  private _appliance(ap: ApplianceProfile, k: number, count: number) {
    return html`
      <div class="group">
      <div class="group-head">
        <ha-icon icon="mdi:tag-outline"></ha-icon>${count > 1 ? t("appliances.tile_n", { n: k + 1, name: ap.units[0].label }) : t("appliances.appliance")}
      </div>
      <div class="setting">
        <span class="label">${t("common.name")}</span>
        <input
          .value=${ap.name}
          aria-label=${t("appliances.appliance_name")}
          @input=${(e: Event) => this._change(k, (d) => (d.name = (e.target as HTMLInputElement).value))}
        />
      </div>
      ${this._sameName(ap)
        ? html`<div class="info note">${t("appliances.same_name", { name: ap.name.trim() })}</div>`
        : nothing}
      ${ap.units.length === 2
        ? html`<div class="setting">
            <span class="label">${t("appliances.on_tile", { order: t("appliances.above", { top: ap.units[0].label, bottom: ap.units[1].label }) })}</span>
            <button class="plain" @click=${() => this._change(k, (d) => d.units.reverse())}>${t("appliances.swap")}</button>
          </div>`
        : nothing}
      </div>
      ${ap.units.map((u, i) => this._unit(k, u, i))}
    `;
  }

  render() {
    const views = this._views;
    const p = this.profile!;
    const original = this._key === this._arrangements[0].key;
    return html`
      <div class="scrim" style="--z:30" @click=${() => Date.now() - this._opened > 400 && this._tryClose()}></div>
      <div class="dialog" style="--z:30" role="dialog" aria-label=${t("common.settings_of", { name: p.name })}>
        <div class="head">
          <div class="title">${this.adding ? t("common.add_name", { name: p.name }) : p.name}</div>
          <button class="x" aria-label=${t("common.close")} title=${t("common.close")} @click=${this._tryClose}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        <div class="list">
          ${this._tileCards()}
          ${views.map((ap, k) => this._appliance(ap, k, views.length))}
          ${!this.adding && original
            ? html`<div class="group">
                  <div class="group-head"><ha-icon icon="mdi:restore"></ha-icon>${t("appliances.start_over")}</div>
                  <div class="setting">
                    <span class="label">${t("appliances.again_info")}</span>
                    <button class="plain" ?disabled=${!this._again} @click=${this._setUpAgain}>${t("appliances.again")}</button>
                  </div>
                </div>
                <div class="group">
                  <div class="group-head"><ha-icon icon="mdi:eye-off-outline"></ha-icon>${t("common.ignore")}</div>
                  <div class="setting">
                  <span class="label">${t("common.ignore_info")}</span>
                  <button class="danger" ?disabled=${this._busy} @click=${this._remove}>
                    ${this._confirmRemove ? t("common.ignore_again") : t("common.ignore")}
                  </button>
                </div>
                </div>`
            : nothing}
        </div>
        ${this._error ? html`<div class="warn">${this._error}</div>` : nothing}
        <div class="footer">
          <button ?disabled=${this._busy} @click=${this._close}>${t("common.cancel")}</button>
          <button
            class="primary"
            ?disabled=${this._busy || !this._dirty || views.some((a) => a.units.some((u) => !u.status))}
            @click=${() => this._save()}
          >
            ${this.adding ? t("common.add") : t("common.save_changes")}
          </button>
        </div>
      </div>
      ${this._ask
        ? html`<rt-unsaved
            @keep=${() => (this._ask = false)}
            @discard=${() => this._close()}
            @save=${() => {
              this._ask = false;
              void this._save();
            }}
          ></rt-unsaved>`
        : nothing}
    `;
  }

  static styles = [
    noSelectStyles,
    groupStyles,
    dialogStyles,
    rowStyles,
    css`
      :host {
        --dialog-w: 520px;
      }
      .cards {
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding: 2px 0 6px;
      }
      .cards .card {
        display: grid;
        grid-template-columns: auto 1fr;
        grid-template-rows: auto auto;
        column-gap: 12px;
        align-items: center;
        text-align: left;
        padding: 12px 14px;
        border-radius: 14px;
        border: 2px solid var(--rt-tile-border);
        background: var(--rt-button);
        font-size: 1rem;
        --mdc-icon-size: 28px;
      }
      .cards .card.on {
        border-color: var(--rt-accent);
      }
      .cards ha-icon {
        grid-row: span 2;
      }
      .cards small {
        font-size: 0.8rem;
        color: var(--rt-text-secondary);
      }
      .note {
        color: var(--rt-light);
      }
      .info {
        font-size: 0.85rem;
        color: var(--rt-text-secondary);
        padding: 2px 4px 6px;
      }
      .sub-head {
        font-size: 0.85rem;
        padding: 8px 4px 2px;
      }
      input:not([type]) {
        width: 11em;
      }
      input.num {
        width: 5em;
      }
      select {
        max-width: 60%;
      }
      .checks {
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding: 4px 4px 8px;
      }
      .check.always {
        opacity: 0.7;
      }
      .plain {
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        border-radius: 10px;
        padding: 8px 12px;
        white-space: nowrap;
      }
      .danger {
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        border-radius: 10px;
        padding: 8px 12px;
        color: var(--rt-light);
      }
    `,
  ];
}

if (!customElements.get("rt-appliances")) customElements.define("rt-appliances", RtAppliances);
if (!customElements.get("rt-appliance-editor")) customElements.define("rt-appliance-editor", RtApplianceEditor);
