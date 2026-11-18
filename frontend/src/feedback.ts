// <rt-feedback>: Send feedback (settings menu). What would you like to send?
//   - Something's wrong with an appliance, pool or vacuum: which one, then
//     its card's Report a problem (<rt-problem>) - that sends its cycle data.
//   - Report a bug: what happened, and where - this dashboard (the browser
//     and Room Tiles' recent errors go with it: errors.ts), a touch panel
//     (HA adds its board, firmware, memory and restarts), an appliance,
//     pool or vacuum (handed to its Report a problem as above, the words
//     kept; "Send without the data" goes on as a bug), somewhere else.
//   - Suggest an idea / Ask a question: the user's words.
// Then the usual report steps (<rt-report>, kind bug / idea / question).
// Names (a panel's, a device's) are shown here only, never sent.

import { LitElement, css, html, nothing, type TemplateResult } from "lit";
import { dialogStyles, noSelectStyles, ScrollFades } from "./ui";
import type { HomeAssistant, RecordingView, RoomTilesDoc } from "./types";
import { t } from "./i18n";
import { problemText, type ProblemSubject } from "./problem";
import { recentErrors } from "./errors";
import type { FeedbackKind } from "./report";
import "./problem";
import "./report";

type Where = "dashboard" | "panel" | "device" | "other";

/** An appliance, pool or robot vacuum that has Report a problem. */
export interface FeedbackDevice {
  subject: ProblemSubject;
  id: string;
  name: string;
  units: { id: string; label: string }[];
}

/** The appliances, pools and vacuums set up, by name. */
export function feedbackDevices(doc: RoomTilesDoc | undefined): FeedbackDevice[] {
  const out: FeedbackDevice[] = [
    ...(doc?.appliances ?? []).map((a) => ({ subject: "appliance" as const, id: a.id, name: a.name, units: a.units.map((u) => ({ id: u.id, label: u.label })) })),
    ...(doc?.pools ?? []).map((p) => ({ subject: "pool" as const, id: p.id, name: p.name, units: [] })),
    ...(doc?.robots ?? []).map((r) => ({ subject: "robot" as const, id: r.id, name: r.name, units: [] })),
  ];
  return out.sort((a, b) => a.name.localeCompare(b.name));
}

/** The browser a bug happened in: its name, major version, system and window
 *  size - never the whole user agent. */
export function browserFacts(ua: string, width: number, height: number): Record<string, string> {
  const pick = (re: RegExp) => ua.match(re)?.[1];
  let name = "other";
  let version: string | undefined;
  const app = pick(/Home ?Assistant\/(\d+)/i);
  if (app !== undefined || /Home ?Assistant/i.test(ua)) {
    name = "ha_app";
    version = app;
  } else if ((version = pick(/Edg[A-Za-z]*\/(\d+)/))) name = "edge";
  else if ((version = pick(/(?:OPR|Opera)\/(\d+)/))) name = "opera";
  else if ((version = pick(/(?:Firefox|FxiOS)\/(\d+)/))) name = "firefox";
  else if ((version = pick(/(?:CriOS|Chrome)\/(\d+)/))) name = "chrome";
  else if ((version = pick(/Version\/(\d+)[\d.]* .*Safari/))) name = "safari";
  const os = /Android/.test(ua)
    ? "android"
    : /iPhone|iPad|iPod/.test(ua)
      ? "ios"
      : /CrOS/.test(ua)
        ? "chromeos"
        : /Windows/.test(ua)
          ? "windows"
          : /Mac OS X|Macintosh/.test(ua)
            ? "macos"
            : /Linux/.test(ua)
              ? "linux"
              : "other";
  return { name, ...(version ? { version } : {}), os, window: `${Math.round(width)}x${Math.round(height)}` };
}

export class RtFeedback extends LitElement {
  protected readonly _scrollFades = new ScrollFades(this, ".scroll");

  static properties = {
    hass: { attribute: false },
    doc: { attribute: false },
    _kind: { state: true },
    _picking: { state: true },
    _words: { state: true },
    _where: { state: true },
    _panel: { state: true },
    _device: { state: true },
    _problem: { state: true },
    _report: { state: true },
  };

  hass?: HomeAssistant;
  doc?: RoomTilesDoc;
  /** what's being written (else: "What would you like to send?") */
  private _kind?: FeedbackKind;
  /** "Something's wrong with an appliance, pool or vacuum": which one? */
  private _picking = false;
  private _words = "";
  private _where?: Where;
  /** a touch panel's device id (Which panel?) */
  private _panel = "";
  /** the appliance, pool or vacuum a bug happened with */
  private _device?: FeedbackDevice;
  /** handed over to Report a problem */
  private _problem?: FeedbackDevice;
  /** the report steps, with what to build it from */
  private _report?: { kind: FeedbackKind; draft: Record<string, unknown> };

  private _close(): void {
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  }

  private _panels() {
    return this.doc?.panel_firmware?.panels ?? [];
  }

  private _recording(d: FeedbackDevice): RecordingView | undefined {
    return this.doc?.recordings?.[`${d.subject}:${d.id}`];
  }

  private _next(): void {
    const kind = this._kind;
    if (!kind) return;
    const draft: Record<string, unknown> = { description: this._words.trim() };
    if (kind === "bug" && this._where) {
      draft.where = this._where;
      if (this._where === "dashboard") {
        draft.browser = browserFacts(navigator.userAgent, window.innerWidth, window.innerHeight);
        const errors = recentErrors();
        if (errors.length) draft.errors = errors; // (Room Tiles' own, scrubbed in HA)
      }
      if (this._where === "panel") {
        // (HA adds what it knows of it: report.py panel_facts)
        const panels = this._panels();
        const p = panels.length === 1 ? panels[0] : panels.find((x) => x.device_id === this._panel);
        if (p) draft.panel_device = p.device_id;
      }
    }
    this._report = { kind, draft };
  }

  render(): TemplateResult {
    if (this._problem) {
      const d = this._problem;
      const rec = this._recording(d);
      return html`<rt-problem
        .hass=${this.hass}
        .subject=${d.subject}
        .target=${d.id}
        .name=${d.name}
        .units=${d.units}
        .words=${this._words.trim()}
        .recording=${rec?.status === "ready" ? rec : undefined}
        @close=${(e: Event) => {
          e.stopPropagation();
          this._close();
        }}
      ></rt-problem>`;
    }
    if (this._report) {
      return html`<rt-report
        .hass=${this.hass}
        .kind=${this._report.kind}
        .draft=${this._report.draft}
        @words=${(e: CustomEvent) => (this._words = e.detail.description)}
        @close=${(e: Event) => {
          e.stopPropagation();
          this._close();
        }}
      ></rt-report>`;
    }
    const title = t("feedback.title");
    return html`
      <div class="scrim" @click=${this._close}></div>
      <div class="dialog" role="dialog" aria-label=${title}>
        <div class="head">
          <div class="title">${title}</div>
          <button class="x" aria-label=${t("common.close")} title=${t("common.close")} @click=${this._close}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        ${this._kind ? this._renderWrite(this._kind) : this._picking ? this._renderPickDevice() : this._renderStart()}
      </div>
    `;
  }

  private _renderStart(): TemplateResult {
    const devices = feedbackDevices(this.doc);
    const kind = (k: FeedbackKind) => () => {
      this._kind = k;
      this._where = undefined;
    };
    const row = (icon: string, label: string, go: () => void) =>
      html`<button class="choice big" @click=${go}><ha-icon icon=${icon}></ha-icon><span>${label}</span><ha-icon class="chev" icon="mdi:chevron-right"></ha-icon></button>`;
    return html`
      <div class="scroll">
        <div class="ask">${t("feedback.what")}</div>
        <div class="choices">
          ${devices.length ? row("mdi:washing-machine-alert", t("feedback.device"), () => (this._picking = true)) : nothing}
          ${row("mdi:bug-outline", t("feedback.bug"), kind("bug"))}
          ${row("mdi:lightbulb-on-outline", t("feedback.idea"), kind("idea"))}
          ${row("mdi:help-circle-outline", t("feedback.question"), kind("question"))}
        </div>
      </div>
      <div class="buttons end">
        <button @click=${this._close}>${t("common.cancel")}</button>
      </div>
    `;
  }

  /** Which appliance, pool or vacuum? - then its Report a problem. */
  private _renderPickDevice(): TemplateResult {
    return html`
      <div class="scroll">
        <div class="ask">${t("problem.which_unit")}</div>
        <p class="dim">${t("feedback.device_info")}</p>
        <div class="choices">${feedbackDevices(this.doc).map((d) => this._deviceChoice(d, () => (this._problem = d), false))}</div>
      </div>
      <div class="buttons end">
        <button @click=${() => (this._picking = false)}>${t("common.back")}</button>
      </div>
    `;
  }

  /** A device to pick: its name, and its recording when one is going (it
   *  can't take another - the card says when it's ready). */
  private _deviceChoice(d: FeedbackDevice, go: () => void, radio: boolean): TemplateResult {
    const rec = this._recording(d);
    const busy = rec?.status === "waiting" || rec?.status === "recording";
    const on = radio && this._device === d;
    return html`<button
      class="choice ${on ? "on" : ""}"
      ?disabled=${busy}
      role=${radio ? "radio" : "button"}
      aria-checked=${radio ? (on ? "true" : "false") : nothing}
      @click=${go}
    >
      ${radio ? html`<ha-icon icon=${on ? "mdi:radiobox-marked" : "mdi:radiobox-blank"}></ha-icon>` : nothing}
      <span class="grow">
        ${d.name}
        ${busy ? html`<span class="sub">${problemText(rec!.status, d.subject)}</span>` : nothing}
        ${rec?.status === "ready" ? html`<span class="sub">${problemText("ready", d.subject)}</span>` : nothing}
      </span>
      ${radio ? nothing : html`<ha-icon class="chev" icon="mdi:chevron-right"></ha-icon>`}
    </button>`;
  }

  private _renderWrite(kind: FeedbackKind): TemplateResult {
    const bug = kind === "bug";
    const toDevice = bug && this._where === "device";
    const panelsToPick = bug && this._where === "panel" && this._panels().length > 1;
    const words = !!this._words.trim();
    const ready = words && (!bug || (!!this._where && (!panelsToPick || !!this._panel)));
    return html`
      <div class="scroll">
        <label class="ask" for="words">${t(`feedback.what_${kind}`)}</label>
        <textarea
          id="words"
          rows="4"
          maxlength="2000"
          placeholder=${t(`feedback.hint_${kind}`)}
          .value=${this._words}
          @input=${(e: Event) => (this._words = (e.target as HTMLTextAreaElement).value)}
        ></textarea>
        ${bug ? this._renderWhere() : nothing}
        ${panelsToPick ? this._renderPanels() : nothing}
        ${toDevice ? this._renderToDevice() : nothing}
      </div>
      <div class="buttons end">
        ${toDevice
          ? html`<button class="plain-link" ?disabled=${!words} @click=${this._next}>${t("feedback.without_data")}</button>`
          : nothing}
        <button @click=${() => (this._kind = undefined)}>${t("common.back")}</button>
        ${toDevice
          ? html`<button class="primary" ?disabled=${!words || !this._device} @click=${() => (this._problem = this._device)}>
              ${t("feedback.continue")}
            </button>`
          : html`<button class="primary" ?disabled=${!ready} @click=${this._next}>${t("problem.next")}</button>`}
      </div>
    `;
  }

  private _renderWhere(): TemplateResult {
    const options: [Where, string][] = [
      ["dashboard", t("feedback.where_dashboard")],
      ...(this._panels().length ? ([["panel", t("feedback.where_panel")]] as [Where, string][]) : []),
      ...(feedbackDevices(this.doc).length ? ([["device", t("feedback.where_device")]] as [Where, string][]) : []),
      ["other", t("feedback.where_other")],
    ];
    return html`
      <div class="ask">${t("feedback.where")}</div>
      <div class="choices" role="radiogroup" aria-label=${t("feedback.where")}>
        ${options.map(([w, label]) => this._radio(this._where === w, label, () => (this._where = w)))}
      </div>
    `;
  }

  private _renderPanels(): TemplateResult {
    return html`
      <div class="ask">${t("feedback.which_panel")}</div>
      <div class="choices" role="radiogroup" aria-label=${t("feedback.which_panel")}>
        ${this._panels().map((p) => this._radio(this._panel === p.device_id, p.name, () => (this._panel = p.device_id)))}
      </div>
    `;
  }

  /** A bug with an appliance, pool or vacuum: its Report a problem sends the
   *  cycle data too - which one? (or send it without the data) */
  private _renderToDevice(): TemplateResult {
    return html`
      <p class="note">${t("feedback.device_info")}</p>
      <div class="ask">${t("problem.which_unit")}</div>
      <div class="choices" role="radiogroup" aria-label=${t("problem.which_unit")}>
        ${feedbackDevices(this.doc).map((d) => this._deviceChoice(d, () => (this._device = d), true))}
      </div>
    `;
  }

  private _radio(on: boolean, label: string, go: () => void): TemplateResult {
    return html`<button class="choice ${on ? "on" : ""}" role="radio" aria-checked=${on ? "true" : "false"} @click=${go}>
      <ha-icon icon=${on ? "mdi:radiobox-marked" : "mdi:radiobox-blank"}></ha-icon><span class="grow">${label}</span>
    </button>`;
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
      .note {
        padding: 8px 10px;
        border-radius: 10px;
        border: 1px solid var(--rt-accent);
        line-height: 1.4;
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
      .choice {
        display: flex;
        align-items: center;
        gap: 10px;
        min-height: 48px;
        padding: 8px 12px;
        border-radius: 10px;
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        color: var(--rt-text);
        text-align: left;
        font: inherit;
        --mdc-icon-size: 22px;
      }
      .choice.big {
        min-height: 56px;
      }
      .choice:disabled {
        opacity: 0.6;
      }
      .choice.on {
        border-color: var(--rt-accent);
      }
      .choice.on ha-icon {
        color: var(--rt-accent);
      }
      .choice .grow,
      .choice span:not(.sub) {
        flex: 1;
      }
      .choice .grow {
        display: flex;
        flex-direction: column;
      }
      .sub {
        color: var(--rt-text-secondary);
        font-size: 0.9rem;
      }
      .chev {
        color: var(--rt-text-secondary);
      }
      .buttons {
        display: flex;
        align-items: center;
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
      .buttons button.plain-link {
        margin-right: auto;
        border: none;
        background: none;
        padding: 8px 4px;
        color: var(--rt-accent);
        font-size: 0.92rem;
      }
      .buttons button:disabled {
        opacity: 0.5;
      }
    `,
  ];
}

if (!customElements.get("rt-feedback")) customElements.define("rt-feedback", RtFeedback);
