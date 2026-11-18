// <rt-report>: sending a report about one device, or Send feedback's bug /
// idea / question (DESIGN.md "Privacy: what reports send"). Three steps,
// nothing collected before the last:
//   1. "Send a report?" - what a report is, that it goes up as a public
//      GitHub issue from the user's own account. Yes / Not now.
//   2. "Do you have a GitHub account?" - Yes (remembered in this browser:
//      skipped next time) / No, how do I get one? (it's free: the sign-up
//      page; nothing prepared) / Not now.
//   3. "Check before sending" - the report from room_tiles/report_preview
//      (scrubbed in HA with this home's own words): which device it's about
//      (its name in this home: shown here only, never sent), what it holds,
//      what it never holds, the exact payload on request; Cancel / Open
//      GitHub. Open GitHub opens a new issue with it filled in - the user
//      reviews it there and submits it themselves.

import { LitElement, css, html, nothing, type TemplateResult } from "lit";
import { dialogStyles, noSelectStyles, ScrollFades } from "./ui";
import type { HomeAssistant, ReportPreview } from "./types";
import { t } from "./i18n";

export type ReportKind = "test" | "model" | "unknown_state" | "recording" | "problem" | FeedbackKind;
/** Send feedback (feedback.ts): the user's words - a bug also where it happened */
export type FeedbackKind = "bug" | "idea" | "question";
const FEEDBACK: readonly string[] = ["bug", "idea", "question"];

/** The address of a new issue with the report filled in: in its kind's
 *  issue form (it applies the kind's label) when it has one. */
export function issueUrl(issue: ReportPreview["issue"], body: string): string {
  const q = new URLSearchParams();
  if (issue.template) q.set("template", issue.template);
  q.set("title", issue.title);
  q.set(issue.template && issue.field ? issue.field : "body", body);
  return `${issue.url}?${q.toString().replace(/\+/g, "%20")}`;
}

const GITHUB_OK = "room_tiles.github_ok"; // (this browser: the user has a GitHub account)
const SIGN_UP = "https://github.com/signup";
const MAX_URL = 7000; // (GitHub turns away longer addresses: then the report is copied instead)
const MAX_BODY = 60000; // (GitHub's limit for an issue is 65,536 characters: longer goes as a file to attach)

function githubOk(): boolean {
  try {
    return localStorage.getItem(GITHUB_OK) === "1";
  } catch {
    return false;
  }
}

export class RtReport extends LitElement {
  /** fades where the report scrolls (ui.ts ScrollFades) */
  protected readonly _scrollFades = new ScrollFades(this, ".scroll");

  static properties = {
    hass: { attribute: false },
    kind: { type: String },
    draft: { attribute: false },
    about: { type: String },
    _step: { state: true },
    _preview: { state: true },
    _raw: { state: true },
    _error: { state: true },
    _opened: { state: true },
  };

  hass?: HomeAssistant;
  kind: ReportKind = "test";
  /** the report as built for the device (scrubbed in HA before it's shown) */
  draft?: Record<string, unknown>;
  /** the device's name in this home - shown on the last step, never sent */
  about = "";
  private _step: "intro" | "account" | "how" | "check" = "intro";
  private _preview?: ReportPreview;
  private _raw = false;
  private _error = "";
  private _opened: "" | "url" | "copied" | "file" = "";

  private _close(): void {
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  }

  private _yes(): void {
    if (githubOk()) void this._check();
    else this._step = "account";
  }

  private _haveAccount(): void {
    try {
      localStorage.setItem(GITHUB_OK, "1");
    } catch {
      /* (private window: asked again next time) */
    }
    void this._check();
  }

  private async _check(): Promise<void> {
    this._step = "check";
    this._error = "";
    try {
      this._preview = await this.hass!.connection.sendMessagePromise!<ReportPreview>({
        type: "room_tiles/report_preview",
        kind: this.kind,
        ...(this.draft ? { draft: this.draft } : {}),
      });
    } catch (err) {
      this._error = String((err as { message?: string })?.message ?? err);
    }
  }

  private async _openGitHub(): Promise<void> {
    const issue = this._preview?.issue;
    if (!issue) return;
    let url = issueUrl(issue, issue.body);
    this._opened = "url";
    this.dispatchEvent(new CustomEvent("opened", { detail: { draft: this.draft } }));
    if (issue.body.length > MAX_BODY) {
      // too long even to paste: saved as a file to attach on GitHub
      const file = new Blob([issue.body], { type: "text/markdown" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(file);
      link.download = "room-tiles-report.md";
      link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 60000);
      url = issueUrl(issue, t("report.attach_here"));
      this._opened = "file";
    } else if (url.length > MAX_URL) {
      // too long for an address: copied, and GitHub opened with a note to paste it
      try {
        await navigator.clipboard.writeText(issue.body);
      } catch {
        /* (no clipboard: the report is still shown here to copy by hand) */
        this._raw = true;
      }
      url = issueUrl(issue, t("report.paste_here"));
      this._opened = "copied";
    }
    window.open(url, "_blank", "noopener");
  }

  render(): TemplateResult {
    const feedback = FEEDBACK.includes(this.kind);
    const title =
      this._step === "intro"
        ? t(feedback ? "feedback.title" : "report.title")
        : this._step === "check"
          ? t("report.check_title")
          : t("report.account_title");
    return html`
      <div class="scrim" @click=${this._close}></div>
      <div class="dialog" role="dialog" aria-label=${title}>
        <div class="head">
          <div class="title">${title}</div>
          <button class="x" aria-label=${t("common.close")} title=${t("common.close")} @click=${this._close}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        ${this._step === "intro" ? this._renderIntro() : nothing}
        ${this._step === "account" ? this._renderAccount() : nothing}
        ${this._step === "how" ? this._renderHow() : nothing}
        ${this._step === "check" ? this._renderCheck() : nothing}
      </div>
    `;
  }

  private _renderIntro(): TemplateResult {
    return html`
      <p>${t(FEEDBACK.includes(this.kind) ? "report.intro_feedback" : "report.intro")}</p>
      <p class="ask">${t(FEEDBACK.includes(this.kind) ? "report.intro_ask_feedback" : "report.intro_ask")}</p>
      <div class="buttons">
        <button class="primary" @click=${this._yes}>${t("report.yes")}</button>
        <button @click=${this._close}>${t("report.not_now")}</button>
      </div>
    `;
  }

  private _renderAccount(): TemplateResult {
    return html`
      <p class="ask">${t("report.account_ask")}</p>
      <div class="buttons column">
        <button class="primary" @click=${this._haveAccount}>${t("report.account_yes")}</button>
        <button @click=${() => (this._step = "how")}>${t("report.account_no")}</button>
        <button @click=${this._close}>${t("report.not_now")}</button>
      </div>
    `;
  }

  private _renderHow(): TemplateResult {
    return html`
      <p>${t("report.account_how")}</p>
      <p><a href=${SIGN_UP} target="_blank" rel="noopener">github.com/signup</a></p>
      <div class="buttons">
        <button class="primary" @click=${this._close}>${t("common.close")}</button>
      </div>
    `;
  }

  private _renderCheck(): TemplateResult {
    if (this._error) return html`<p class="warn">${this._error}</p>`;
    const p = this._preview;
    if (!p) return html`<p class="dim">${t("report.preparing")}</p>`;
    return html`
      <div class="scroll">
        ${this.about ? html`<p class="about">${t("report.about", { name: this.about })}</p>` : nothing}
        ${this._renderWords(p)}
        <p>${t("report.holds")}</p>
        <ul>
          ${p.summary.map((key) => html`<li>${t(key)}</li>`)}
        </ul>
        <p>${p.report.description ? t("report.never_data") : t("report.never")}</p>
        <button class="link" aria-expanded=${this._raw ? "true" : "false"} @click=${() => (this._raw = !this._raw)}>
          <ha-icon icon=${this._raw ? "mdi:chevron-down" : "mdi:chevron-right"}></ha-icon>${t("report.show")}
        </button>
        ${this._raw ? html`<pre>${JSON.stringify(p.report, null, 2)}</pre>` : nothing}
        <p class="note">${t("report.github_note")}</p>
        ${this._opened === "url" ? html`<p class="done">${t("report.opened")}</p>` : nothing}
        ${this._opened === "copied" ? html`<p class="done">${t("report.copied")}</p>` : nothing}
        ${this._opened === "file" ? html`<p class="done">${t("report.attach")}</p>` : nothing}
      </div>
      <div class="buttons end">
        <button @click=${this._close}>${this._opened ? t("common.close") : t("common.cancel")}</button>
        <button class="primary" @click=${this._openGitHub}><ha-icon icon="mdi:github"></ha-icon>${t("report.open")}</button>
      </div>
    `;
  }

  /** A problem report: the user's own words, sent as written - with what
   *  looks like a name, address or time pointed out (Remove it). */
  private _renderWords(p: ReportPreview): TemplateResult | typeof nothing {
    const words = p.report.description;
    if (typeof words !== "string" || !words) return nothing;
    return html`
      <p class="about">${t("report.your_words")}</p>
      <div class="words">${words}</div>
      ${(p.warnings ?? []).map(
        (w) => html`<div class="warning">
          <span>${t(`report.warn.${w.why}`, { text: w.text })}</span>
          <button class="plain" @click=${() => this._remove(w.text)}>${t("report.remove")}</button>
        </div>`,
      )}
    `;
  }

  private _remove(text: string): void {
    const words = String(this.draft?.description ?? "");
    const escaped = text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const next = words.replace(new RegExp(escaped, "gi"), "[…]");
    this.draft = { ...this.draft, description: next };
    this.dispatchEvent(new CustomEvent("words", { detail: { description: next } }));
    void this._check();
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
      .about {
        font-weight: 600;
      }
      .dim {
        color: var(--rt-text-secondary);
      }
      .warn {
        color: var(--rt-light);
      }
      .done {
        color: var(--rt-accent);
      }
      .note {
        color: var(--rt-text-secondary);
        font-size: 0.92rem;
      }
      .words {
        white-space: pre-wrap;
        padding: 8px 10px;
        border-radius: 10px;
        background: var(--rt-panel-dark);
        border: 1px solid var(--rt-tile-border);
        user-select: text;
        -webkit-user-select: text;
      }
      .warning {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 6px 8px;
        border-radius: 10px;
        border: 1px solid var(--rt-light);
        font-size: 0.92rem;
      }
      .warning span {
        flex: 1;
      }
      .warning button {
        min-height: 40px;
        padding: 6px 12px;
        border-radius: 10px;
        border: 1px solid var(--rt-tile-border);
        background: var(--rt-button);
        color: var(--rt-text);
        white-space: nowrap;
      }
      ul {
        margin: 0;
        padding-left: 1.2em;
        line-height: 1.5;
      }
      .scroll {
        display: flex;
        flex-direction: column;
        gap: 10px;
        overflow-y: auto;
        min-height: 0;
      }
      pre {
        margin: 0;
        padding: 10px;
        max-height: 40dvh;
        overflow: auto;
        border-radius: 10px;
        background: var(--rt-panel-dark);
        border: 1px solid var(--rt-tile-border);
        font-size: 0.8rem;
        user-select: text;
        -webkit-user-select: text;
      }
      a {
        color: var(--rt-accent);
      }
      .buttons {
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        padding-top: 4px;
      }
      .buttons.column {
        flex-direction: column;
        align-items: stretch;
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
        --mdc-icon-size: 18px;
      }
      .buttons button.primary {
        border-color: var(--rt-accent);
        background: var(--rt-accent);
        color: var(--rt-on-accent);
      }
      button.link {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        align-self: flex-start;
        border: none;
        background: none;
        padding: 6px 0;
        color: var(--rt-accent);
        --mdc-icon-size: 20px;
      }
    `,
  ];
}

if (!customElements.get("rt-report")) customElements.define("rt-report", RtReport);
