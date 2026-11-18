// <rt-panels>: the wall panels and their firmware (settings menu > Panels).
// Each panel: its name, area and board, and where its firmware stands - up
// to date, an update to install (Install = its HA update entity), updating,
// built by hand. "Update panels automatically" (Room Tiles' setting, on by
// default): they install it on their own when nobody's using them. Upload
// firmware (admins): a panel image becomes its board's image (the
// integration's update.py FirmwareUploadView). The list is the feed's
// "panel_firmware" (update.py firmware_rows), live.

import { LitElement, css, html, nothing, type TemplateResult } from "lit";
import { dialogStyles, groupStyles, noSelectStyles, rowStyles, toggle, ScrollFades } from "./ui";
import { DEFAULT_THEME, type ThemeName } from "./theme";
import type { HomeAssistant, PanelFirmwareRow, RoomTilesDoc } from "./types";
import { t } from "./i18n";

const UPLOAD_URL = "/api/room_tiles/firmware";

/** A board id as people know it - what's printed on it: `elecrow-p4-10in-v1.2-es`
 *  -> 10.1" V1.2; the round one -> 2.1" round. */
export function boardName(board: string | null | undefined): string {
  if (!board) return "";
  const round = /round-(\d+(?:\.\d+)?)/.exec(board);
  if (round) return t("panels.round", { size: round[1] });
  const m = /-(\d+)in-v([\d.]+)/.exec(board);
  if (!m) return board;
  const size = m[1] === "10" ? "10.1" : m[1];
  return `${size}" V${m[2]}`;
}

export class RtPanels extends LitElement {
  /** fades where a scrolling area has more (ui.ts ScrollFades) */
  protected readonly _scrollFades = new ScrollFades(this, ".list");

  static properties = {
    hass: { attribute: false },
    doc: { attribute: false },
    theme: { type: String },
    _busy: { state: true },
    _message: { state: true },
    _error: { state: true },
  };

  hass?: HomeAssistant;
  doc?: RoomTilesDoc;
  theme: ThemeName = DEFAULT_THEME;
  private _busy = false;
  private _message = "";
  private _error = "";
  private _opened = Date.now();

  private _close(): void {
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  }

  private _scrimClick(): void {
    if (Date.now() - this._opened > 400) this._close();
  }

  private _setAuto(on: boolean): void {
    void this.hass?.callService("room_tiles", "set_settings", { auto_update_panels: on });
  }

  private _install(p: PanelFirmwareRow): void {
    if (p.entity_id) void this.hass?.callService("update", "install", {}, { entity_id: p.entity_id });
  }

  private async _upload(file: File | undefined): Promise<void> {
    if (!file || !this.hass?.fetchWithAuth) return;
    this._busy = true;
    this._message = "";
    this._error = "";
    try {
      const res = await this.hass.fetchWithAuth(UPLOAD_URL, { method: "POST", body: file });
      const answer = (await res.json()) as { ok: boolean; error?: string; board?: string; label?: string };
      if (answer.ok) this._message = t("panels.uploaded", { board: boardName(answer.board), label: answer.label ?? "" });
      else if (answer.error === "older") this._error = t("panels.err.older", { board: boardName(answer.board) });
      else if (["not_firmware", "hand_built", "other_version"].includes(answer.error ?? ""))
        this._error = t(`panels.err.${answer.error}`);
      else this._error = t("panels.err.failed");
    } catch {
      this._error = t("panels.err.failed");
    } finally {
      this._busy = false;
    }
  }

  private _status(p: PanelFirmwareRow): TemplateResult {
    switch (p.status) {
      case "available":
        return html`<span class="state">${t("panels.available")}: ${p.latest}</span>
          ${p.entity_id ? html`<button class="primary" @click=${() => this._install(p)}>${t("panels.install")}</button>` : nothing}`;
      case "updating":
        return html`<span class="state busy">${t("panels.updating")}</span>`;
      case "waiting": // (an automatic update: until nobody's using the panel - Install starts it now)
        return html`<span class="state">${t("panels.waiting")}: ${p.latest}</span>
          ${p.entity_id ? html`<button class="primary" @click=${() => this._install(p)}>${t("panels.install")}</button>` : nothing}`;
      case "hand_built":
        return html`<span class="state">${t("panels.hand_built")}</span>`;
      case "unknown":
        return html`<span class="state">${t("panels.unknown")}</span>`;
      default:
        return html`<span class="state">${t("panels.current")}${p.running ? html` · ${p.running}` : nothing}</span>`;
    }
  }

  private _panel(p: PanelFirmwareRow): TemplateResult {
    return html`<div class="panel">
      <div class="who">
        <span class="name">${p.name}</span>
        <span class="where">${[p.area, boardName(p.board)].filter(Boolean).join(" · ")}</span>
      </div>
      <div class="fw">${this._status(p)}</div>
    </div>`;
  }

  render() {
    const fw = this.doc?.panel_firmware;
    const panels = fw?.panels ?? [];
    const images = fw?.images ?? [];
    const auto = this.doc?.settings.auto_update_panels ?? true;
    const admin = this.hass?.user?.is_admin !== false;
    return html`
      <div class="scrim" @click=${this._scrimClick}></div>
      <div class="dialog" role="dialog" aria-label=${t("panels.title")}>
        <div class="head">
          <div class="title">${t("panels.title")}</div>
          <button class="x" aria-label=${t("common.close")} @click=${this._close}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        <div class="list">
          <div class="group">
            <div class="group-head"><ha-icon icon="mdi:tablet"></ha-icon>${t("panels.list")}</div>
            ${panels.length ? panels.map((p) => this._panel(p)) : html`<div class="hint">${t("panels.none")}</div>`}
          </div>
          <div class="group">
            <div class="group-head"><ha-icon icon="mdi:chip"></ha-icon>${t("panels.firmware")}</div>
            <div class="setting">
              <span class="label">${t("panels.auto")}</span>
              ${toggle(auto, (on) => this._setAuto(on), t("panels.auto"), this.theme)}
            </div>
            <div class="hint">${t("panels.auto_hint")}</div>
            ${images.length
              ? images.map((i) => html`<div class="image"><span class="board">${boardName(i.board)}</span><span class="label">${i.label}</span></div>`)
              : html`<div class="hint">${t("panels.no_firmware")}</div>`}
            ${admin && this.hass?.fetchWithAuth
              ? html`<div class="upload">
                  <label class="button ${this._busy ? "disabled" : ""}">
                    <ha-icon icon="mdi:upload"></ha-icon>
                    ${this._busy ? t("panels.uploading") : t("panels.upload")}
                    <input
                      type="file"
                      accept=".bin"
                      ?disabled=${this._busy}
                      @change=${(e: Event) => {
                        const input = e.target as HTMLInputElement;
                        void this._upload(input.files?.[0]).then(() => (input.value = ""));
                      }}
                    />
                  </label>
                  ${this._message ? html`<div class="done">${this._message}</div>` : nothing}
                  ${this._error ? html`<div class="warn">${this._error}</div>` : nothing}
                </div>`
              : nothing}
          </div>
        </div>
      </div>
    `;
  }

  static styles = [
    noSelectStyles,
    groupStyles,
    rowStyles,
    dialogStyles,
    css`
      :host {
        --dialog-w: 560px;
      }
      .panel {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 6px 12px;
        padding: 8px 2px;
        border-bottom: 1px solid var(--rt-tile-border);
      }
      .panel:last-child {
        border-bottom: none;
      }
      .who {
        display: flex;
        flex-direction: column;
        min-width: 0;
      }
      .name {
        font-weight: 600;
      }
      .where,
      .hint,
      .image .label {
        font-size: 0.85rem;
        color: var(--rt-text-secondary);
      }
      .hint {
        padding: 2px 0 6px;
      }
      .fw {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-left: auto;
      }
      .state {
        font-size: 0.9rem;
      }
      .state.busy {
        color: var(--rt-accent);
      }
      .image {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        padding: 4px 2px;
      }
      .upload {
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding: 8px 0 4px;
      }
      button.primary,
      label.button {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        align-self: flex-start;
        border-radius: 10px;
        padding: 7px 14px;
        min-height: 40px;
        box-sizing: border-box;
        border: 1px solid var(--rt-accent);
        background: var(--rt-accent);
        color: var(--rt-on-accent);
        cursor: pointer;
        --mdc-icon-size: 18px;
      }
      label.button {
        border-color: var(--rt-tile-border);
        background: var(--rt-button);
        color: var(--rt-text);
      }
      label.button.disabled {
        opacity: 0.6;
        cursor: default;
      }
      label.button input {
        display: none;
      }
      .done {
        color: var(--rt-text);
      }
      .warn {
        color: var(--rt-light);  /* (a warning: amber, like the editors') */
      }
    `,
  ];
}

if (!customElements.get("rt-panels")) customElements.define("rt-panels", RtPanels);
