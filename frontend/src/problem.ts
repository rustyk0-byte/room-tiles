// <rt-problem>: "Report a problem" for one appliance, pool or robot vacuum
// (DESIGN.md "Privacy: what reports send" > Report a problem). First step,
// its own: which unit (two on one tile), "What went wrong?" in the user's
// own words, and which cycle - a recent one from HA's history
// (room_tiles/problem_cycles; times shown here only, the report has seconds
// from the start), for a pool also the last 6 / 24 hours, or "Record the
// next cycle" (room_tiles/recording: Room Tiles listens until it's over, the
// Appliances card says when it's ready). Then the usual report steps
// (<rt-report kind="problem">). Opened for a finished recording: its
// cycle, the words saved with it.

import { LitElement, css, html, nothing, type TemplateResult } from "lit";
import { dialogStyles, noSelectStyles, ScrollFades } from "./ui";
import type { HomeAssistant, RecordingView } from "./types";
import { language, num, t } from "./i18n";
import "./report";

interface Cycle {
  start: number;
  end: number;
}
interface Found {
  history: boolean;
  running: boolean;
  cycles: Cycle[];
  windows: (Cycle & { hours: number })[]; // (a pool: the last hours)
}

export type ProblemSubject = "appliance" | "pool" | "robot";

/** A text in its subject's words: an appliance's cycle, a pool's pump run,
 *  a vacuum's clean (problem.<key>, problem.<key>_pool, problem.<key>_robot). */
export const problemText = (key: string, subject: ProblemSubject): string =>
  t(subject === "appliance" ? `problem.${key}` : `problem.${key}_${subject}`);

/** A time the user's way (their HA profile's format and time zone). */
export function when(hass: HomeAssistant | undefined, seconds: number, withDay: boolean): string {
  const loc = hass?.locale;
  const hour12 = loc?.time_format === "12" ? true : loc?.time_format === "24" ? false : undefined;
  const timeZone = loc?.time_zone === "server" ? hass?.config?.time_zone : undefined;
  const opts: Intl.DateTimeFormatOptions = { hour: "numeric", minute: "2-digit", hour12, timeZone };
  if (withDay) Object.assign(opts, { weekday: "short", month: "short", day: "numeric" });
  try {
    return new Intl.DateTimeFormat(loc?.language ?? language(), opts).format(new Date(seconds * 1000));
  } catch {
    return new Date(seconds * 1000).toLocaleString();
  }
}

/** "Tue, Nov 17, 1:05 PM – 2:10 PM · 65 min" */
export function cycleText(hass: HomeAssistant | undefined, start: number, end: number): string {
  return t("problem.cycle", {
    start: when(hass, start, true),
    end: when(hass, end, false),
    minutes: num(Math.max(1, Math.round((end - start) / 60)), 0),
  });
}

export class RtProblem extends LitElement {
  protected readonly _scrollFades = new ScrollFades(this, ".scroll");

  static properties = {
    hass: { attribute: false },
    subject: { type: String },
    target: { type: String },
    name: { type: String },
    units: { attribute: false },
    recording: { attribute: false },
    words: { type: String },
    _unit: { state: true },
    _words: { state: true },
    _found: { state: true },
    _pick: { state: true },
    _report: { state: true },
    _error: { state: true },
  };

  hass?: HomeAssistant;
  /** what it's about: an appliance, a pool system, a robot vacuum - its id */
  subject: ProblemSubject = "appliance";
  target = "";
  /** its name in this home (shown on the last step, never sent) */
  name = "";
  /** an appliance's units (two on one tile: "Which one?") */
  units: { id: string; label: string }[] = [];
  /** a finished recording to send (else: pick a cycle) */
  recording?: RecordingView;
  /** what the user already wrote (Send feedback hands a problem over) */
  words = "";
  private _unit = "";
  private _words = "";
  private _found?: Found;
  /** a cycle's index, "w<i>" (a window: the last hours), or "record" */
  private _pick: number | string = "";
  /** the report steps, with what to build it from */
  private _report?: Record<string, unknown>;
  private _error = "";

  connectedCallback(): void {
    super.connectedCallback();
    if (this.recording) {
      this._unit = this.recording.unit;
      this._words = this.recording.description;
    } else {
      this._unit = this.units[0]?.id ?? "";
      this._words = this.words;
      void this._load();
    }
  }

  private async _load(): Promise<void> {
    this._found = undefined;
    this._pick = "";
    try {
      this._found = await this.hass!.connection.sendMessagePromise!<Found>({
        type: "room_tiles/problem_cycles",
        ...this._who(),
      });
      if (!this._found.history || (!this._found.cycles.length && !this._found.windows.length)) this._pick = "record";
    } catch (err) {
      this._error = String((err as { message?: string })?.message ?? err);
    }
  }

  private _who(): Record<string, string> {
    return { subject: this.subject, target: this.target, ...(this._unit ? { unit: this._unit } : {}) };
  }

  private _close(): void {
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  }

  private async _next(): Promise<void> {
    const description = this._words.trim();
    if (this.recording) {
      void this._send("update", { description });
      this._report = { ...this._who(), recorded: true, description };
    } else if (this._pick === "record") {
      await this._send("start", { description });
      this._close();
    } else if (typeof this._pick === "number" && this._found) {
      const c = this._found.cycles[this._pick];
      this._report = { ...this._who(), start: c.start, end: c.end, description };
    } else if (typeof this._pick === "string" && this._pick.startsWith("w") && this._found) {
      const w = this._found.windows[Number(this._pick.slice(1))];
      this._report = { ...this._who(), start: w.start, end: w.end, window: true, description };
    }
  }

  private async _send(action: string, extra: Record<string, unknown>): Promise<void> {
    try {
      await this.hass!.connection.sendMessagePromise!({ type: "room_tiles/recording", action, ...this._who(), ...extra });
    } catch (err) {
      this._error = String((err as { message?: string })?.message ?? err);
    }
  }

  render(): TemplateResult {
    if (this._report) {
      return html`<rt-report
        .hass=${this.hass}
        kind="problem"
        .draft=${this._report}
        .about=${this.name}
        @words=${(e: CustomEvent) => {
          this._report = { ...this._report, description: e.detail.description };
          this._words = e.detail.description;
          if (this.recording) void this._send("update", { description: this._words });
        }}
        @opened=${() => {
          if (this.recording) void this._send("update", { opened: true });
        }}
        @close=${(e: Event) => {
          e.stopPropagation();
          this._close();
        }}
      ></rt-report>`;
    }
    const title = t("problem.title");
    const ready = !!this._words.trim() && (!!this.recording || this._pick !== "");
    return html`
      <div class="scrim" @click=${this._close}></div>
      <div class="dialog" role="dialog" aria-label=${title}>
        <div class="head">
          <div class="title">${title}</div>
          <button class="x" aria-label=${t("common.close")} title=${t("common.close")} @click=${this._close}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        <div class="scroll">
          ${this._renderUnits()}
          <label class="ask" for="words">${t("problem.what")}</label>
          <textarea
            id="words"
            rows="4"
            maxlength="2000"
            placeholder=${t("problem.what_hint")}
            .value=${this._words}
            @input=${(e: Event) => (this._words = (e.target as HTMLTextAreaElement).value)}
          ></textarea>
          ${this.recording ? this._renderRecorded(this.recording) : this._renderCycles()}
          ${this._error ? html`<p class="warn">${this._error}</p>` : nothing}
        </div>
        <div class="buttons end">
          <button @click=${this._close}>${t("common.cancel")}</button>
          <button class="primary" ?disabled=${!ready} @click=${this._next}>
            ${this._pick === "record" && !this.recording ? t("problem.start") : t("problem.next")}
          </button>
        </div>
      </div>
    `;
  }

  private _renderUnits(): TemplateResult | typeof nothing {
    const units = this.units;
    if (units.length < 2 || this.recording) return nothing;
    return html`
      <div class="ask">${t("problem.which_unit")}</div>
      <div class="choices row">
        ${units.map(
          (u) => html`<button
            class="choice ${u.id === this._unit ? "on" : ""}"
            aria-pressed=${u.id === this._unit ? "true" : "false"}
            @click=${() => {
              if (u.id === this._unit) return;
              this._unit = u.id;
              void this._load();
            }}
          >${u.label}</button>`,
        )}
      </div>
    `;
  }

  private _renderRecorded(r: RecordingView): TemplateResult {
    return html`<p class="dim">${t("problem.recorded", { cycle: cycleText(this.hass, r.started ?? r.armed, r.ended ?? r.armed) })}</p>`;
  }

  private _renderCycles(): TemplateResult {
    const f = this._found;
    if (!f && !this._error) return html`<div class="ask">${t("problem.which_cycle")}</div><p class="dim">${t("problem.loading")}</p>`;
    const choice = (pick: number | string, label: string) =>
      html`<button
        class="choice ${this._pick === pick ? "on" : ""}"
        role="radio"
        aria-checked=${this._pick === pick ? "true" : "false"}
        @click=${() => (this._pick = pick)}
      >
        <ha-icon icon=${this._pick === pick ? "mdi:radiobox-marked" : "mdi:radiobox-blank"}></ha-icon>${label}
      </button>`;
    return html`
      <div class="ask">${t("problem.which_cycle")}</div>
      ${f && !f.history ? html`<p class="dim">${t("problem.no_history")}</p>` : nothing}
      ${f && f.history && !f.cycles.length && !f.windows.length ? html`<p class="dim">${t("problem.none")}</p>` : nothing}
      <div class="choices" role="radiogroup" aria-label=${t("problem.which_cycle")}>
        ${(f?.cycles ?? []).map((c, i) => choice(i, cycleText(this.hass, c.start, c.end)))}
        ${(f?.history ? f.windows : []).map((w, i) => choice(`w${i}`, t("problem.last_hours", { n: w.hours })))}
        ${choice("record", problemText(f?.running ? "record_now" : "record_next", this.subject))}
      </div>
      ${this._pick === "record" ? html`<p class="dim">${t("problem.record_info")}</p>` : nothing}
    `;
  }

  static styles = [
    noSelectStyles,
    dialogStyles,
    css`
      :host {
        --z: 40;
      }
      p {
        margin: 0;
        line-height: 1.4;
      }
      .ask {
        font-weight: 600;
      }
      .dim {
        color: var(--rt-text-secondary);
      }
      .warn {
        color: var(--rt-light);
      }
      .scroll {
        display: flex;
        flex-direction: column;
        gap: 10px;
        overflow-y: auto;
        min-height: 0;
      }
      textarea {
        box-sizing: border-box;
        width: 100%;
        min-height: 96px;
        padding: 10px;
        border-radius: 10px;
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-panel-dark);
        color: var(--rt-text);
        font: inherit;
        resize: vertical;
        user-select: text;
        -webkit-user-select: text;
      }
      .choices {
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .choices.row {
        flex-direction: row;
        flex-wrap: wrap;
      }
      .choice {
        display: flex;
        align-items: center;
        gap: 8px;
        min-height: 44px;
        padding: 8px 12px;
        border-radius: 10px;
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        color: var(--rt-text);
        text-align: left;
        font: inherit;
        --mdc-icon-size: 20px;
      }
      .choice.on {
        border-color: var(--rt-accent);
      }
      .choice.on ha-icon {
        color: var(--rt-accent);
      }
      .buttons {
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        padding-top: 4px;
      }
      .buttons.end {
        justify-content: flex-end;
      }
      .buttons button {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        min-height: 44px;
        padding: 8px 16px;
        border-radius: 10px;
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        color: var(--rt-text);
      }
      .buttons button.primary {
        border-color: var(--rt-accent);
        background: var(--rt-accent);
        color: var(--rt-on-accent);
      }
      .buttons button:disabled {
        opacity: 0.5;
      }
    `,
  ];
}

if (!customElements.get("rt-problem")) customElements.define("rt-problem", RtProblem);
