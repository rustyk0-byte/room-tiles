// <rt-model-report>: "Report how it went" for a beta appliance, pool or
// robot vacuum (DESIGN.md "Privacy: what reports send" > Model reports).
// One step of its own: which unit (two on one tile, only the beta ones), how
// it went overall (works / partly / doesn't work), each feature of its kind
// (room_tiles/problem_cycles' `features`: works / partly / doesn't work /
// not tried), anything to add in the user's own words, and a recent cycle,
// pump run or clean's data to add (the most recent picked; or none). Then
// the usual report steps (<rt-report kind="model">).

import { LitElement, css, html, nothing, type TemplateResult } from "lit";
import { dialogStyles, noSelectStyles, ScrollFades } from "./ui";
import type { HomeAssistant } from "./types";
import { t } from "./i18n";
import { cycleText, type ProblemSubject } from "./problem";
import "./report";

type Outcome = "works" | "partly" | "broken";
type Answer = Outcome | "not_tried";
const ANSWERS: Answer[] = ["works", "partly", "broken", "not_tried"];

interface Found {
  history: boolean;
  cycles: { start: number; end: number }[];
  windows: { start: number; end: number; hours: number }[];
  features: string[];
}

/** The data to add first: the most recent cycle, else a pool's longest
 *  window, else none. */
export function firstPick(f: Pick<Found, "history" | "cycles" | "windows">): number | string {
  if (!f.history) return "none";
  if (f.cycles.length) return 0;
  if (f.windows.length) return `w${f.windows.length - 1}`;
  return "none";
}

export class RtModelReport extends LitElement {
  protected readonly _scrollFades = new ScrollFades(this, ".scroll");

  static properties = {
    hass: { attribute: false },
    subject: { type: String },
    target: { type: String },
    name: { type: String },
    units: { attribute: false },
    _unit: { state: true },
    _found: { state: true },
    _outcome: { state: true },
    _answers: { state: true },
    _words: { state: true },
    _pick: { state: true },
    _report: { state: true },
    _error: { state: true },
  };

  hass?: HomeAssistant;
  subject: ProblemSubject = "appliance";
  target = "";
  /** its name in this home (shown on the last step, never sent) */
  name = "";
  /** an appliance's beta units (two on one tile: "Which one?") */
  units: { id: string; label: string }[] = [];
  private _unit = "";
  private _found?: Found;
  private _outcome?: Outcome;
  private _answers: Record<string, Answer> = {};
  private _words = "";
  /** the data to add: a cycle's index, "w<i>" (a pool: the last hours), or "none" */
  private _pick: number | string = "none";
  private _report?: Record<string, unknown>;
  private _error = "";

  connectedCallback(): void {
    super.connectedCallback();
    this._unit = this.units[0]?.id ?? "";
    void this._load();
  }

  private async _load(): Promise<void> {
    this._found = undefined;
    this._answers = {};
    try {
      this._found = await this.hass!.connection.sendMessagePromise!<Found>({
        type: "room_tiles/problem_cycles",
        ...this._who(),
      });
      this._pick = firstPick(this._found);
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

  private _next(): void {
    const f = this._found;
    if (!f || !this._outcome) return;
    const checklist = Object.fromEntries(f.features.map((k) => [k, this._answers[k] ?? "not_tried"]));
    const draft: Record<string, unknown> = { ...this._who(), outcome: this._outcome, checklist, description: this._words.trim() };
    if (typeof this._pick === "number" && f.cycles[this._pick]) {
      Object.assign(draft, { start: f.cycles[this._pick].start, end: f.cycles[this._pick].end });
    } else if (typeof this._pick === "string" && this._pick.startsWith("w")) {
      const w = f.windows[Number(this._pick.slice(1))];
      if (w) Object.assign(draft, { start: w.start, end: w.end, window: true });
    }
    this._report = draft;
  }

  render(): TemplateResult {
    if (this._report) {
      return html`<rt-report
        .hass=${this.hass}
        kind="model"
        .draft=${this._report}
        .about=${this.name}
        @words=${(e: CustomEvent) => {
          this._report = { ...this._report, description: e.detail.description };
          this._words = e.detail.description;
        }}
        @close=${(e: Event) => {
          e.stopPropagation();
          this._close();
        }}
      ></rt-report>`;
    }
    const title = t("model.title");
    return html`
      <div class="scrim" @click=${this._close}></div>
      <div class="dialog" role="dialog" aria-label=${title}>
        <div class="head">
          <div class="title">${title}</div>
          <button class="x" aria-label=${t("common.close")} title=${t("common.close")} @click=${this._close}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        <div class="scroll">
          ${this._renderUnits()}
          <div class="ask">${t("model.how")}</div>
          <div class="choices" role="radiogroup" aria-label=${t("model.how")}>
            ${(["works", "partly", "broken"] as Outcome[]).map((o) =>
              this._radio(this._outcome === o, t(`model.outcome.${o}`), () => (this._outcome = o)),
            )}
          </div>
          ${this._renderFeatures()}
          <label class="ask" for="words">${t("model.words")}</label>
          <textarea
            id="words"
            rows="3"
            maxlength="2000"
            placeholder=${t("model.words_hint")}
            .value=${this._words}
            @input=${(e: Event) => (this._words = (e.target as HTMLTextAreaElement).value)}
          ></textarea>
          ${this._renderData()}
          ${this._error ? html`<p class="warn">${this._error}</p>` : nothing}
        </div>
        <div class="buttons end">
          <button @click=${this._close}>${t("common.cancel")}</button>
          <button class="primary" ?disabled=${!this._outcome || !this._found} @click=${this._next}>${t("problem.next")}</button>
        </div>
      </div>
    `;
  }

  private _renderUnits(): TemplateResult | typeof nothing {
    if (this.units.length < 2) return nothing;
    return html`
      <div class="ask">${t("problem.which_unit")}</div>
      <div class="choices row">
        ${this.units.map(
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

  /** Each feature: Works / Partly / Doesn't work / Not tried (not tried
   *  until answered). */
  private _renderFeatures(): TemplateResult {
    const f = this._found;
    if (!f) return html`<p class="dim">${this._error ? "" : t("problem.loading")}</p>`;
    return html`
      <div class="ask">${t("model.check")}</div>
      <div class="features">
        ${f.features.map((k) => {
          const now = this._answers[k] ?? "not_tried";
          return html`<div class="feature" role="radiogroup" aria-label=${t(`model.feature.${k}`)}>
            <div class="fname">${t(`model.feature.${k}`)}</div>
            <div class="chips">
              ${ANSWERS.map(
                (a) => html`<button
                  class="chip ${a === now ? "on" : ""} ${a}"
                  role="radio"
                  aria-checked=${a === now ? "true" : "false"}
                  @click=${() => (this._answers = { ...this._answers, [k]: a })}
                >${t(`model.answer.${a}`)}</button>`,
              )}
            </div>
          </div>`;
        })}
      </div>
    `;
  }

  /** The data to add: a recent cycle (pump run, clean), a pool's last hours,
   *  or none. */
  private _renderData(): TemplateResult | typeof nothing {
    const f = this._found;
    if (!f) return nothing;
    const cycles = f.history ? f.cycles.slice(0, 3) : [];
    const windows = f.history ? f.windows : [];
    return html`
      <div class="ask">${this._addText()}</div>
      <div class="choices" role="radiogroup" aria-label=${this._addText()}>
        ${cycles.map((c, i) => this._radio(this._pick === i, cycleText(this.hass, c.start, c.end), () => (this._pick = i)))}
        ${windows.map((w, i) =>
          this._radio(this._pick === `w${i}`, t("problem.last_hours", { n: w.hours }), () => (this._pick = `w${i}`)),
        )}
        ${this._radio(this._pick === "none", t("model.add_none"), () => (this._pick = "none"))}
      </div>
    `;
  }

  /** "Add a recent cycle's data" in its subject's words (pump run, clean) */
  private _addText(): string {
    return t(this.subject === "appliance" ? "model.add" : `model.add_${this.subject}`);
  }

  private _radio(on: boolean, label: string, go: () => void): TemplateResult {
    return html`<button class="choice ${on ? "on" : ""}" role="radio" aria-checked=${on ? "true" : "false"} @click=${go}>
      <ha-icon icon=${on ? "mdi:radiobox-marked" : "mdi:radiobox-blank"}></ha-icon>${label}
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
        min-height: 72px;
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
      .features {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .feature {
        display: flex;
        flex-direction: column;
        gap: 4px;
        padding: 8px 10px;
        border-radius: 10px;
        background: var(--rt-panel-dark);
        border: 1px solid var(--rt-tile-border);
      }
      .fname {
        font-size: 0.92rem;
      }
      .chips {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
      }
      .chip {
        min-height: 40px;
        padding: 6px 12px;
        border-radius: 20px;
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        color: var(--rt-text);
        font: inherit;
        font-size: 0.88rem;
      }
      .chip.on {
        border-color: var(--rt-accent);
        background: var(--rt-accent);
        color: var(--rt-on-accent);
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

if (!customElements.get("rt-model-report")) customElements.define("rt-model-report", RtModelReport);
