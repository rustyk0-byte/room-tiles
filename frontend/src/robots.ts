// <rt-robot-editor>: a robot vacuum's settings (Add and the pencil on the
// Appliances page) - its name, and what it can do: alerts (Matter robots) and
// room cleaning (needs HA's clean_area and its rooms linked to HA areas; the tile opens its room queue).
// A draft: nothing is stored until Add / Save changes.

import { LitElement, css, html, nothing } from "lit";
import { DialogPin } from "./dialog-pin";
import type { HomeAssistant, RobotProfile, RoomTilesDoc } from "./types";
import { dialogStyles, noSelectStyles, rowStyles, groupStyles, setUpDevice, ScrollFades } from "./ui";
import "./unsaved";
import { t } from "./i18n";

const CLEAN_AREA = 16384; // VacuumEntityFeature.CLEAN_AREA

export class RtRobotEditor extends LitElement {
  /** fades where a scrolling area has more (ui.ts ScrollFades) */
  protected readonly _scrollFades = new ScrollFades(this, ".list");

  /** the dialog's top edge stays put while its content changes (dialog-pin.ts) */
  readonly dialogPin = new DialogPin(this);
  static properties = {
    hass: { attribute: false },
    doc: { attribute: false },
    profile: { attribute: false },
    adding: { type: Boolean },
    _draft: { state: true },
    _ask: { state: true },
    _confirmRemove: { state: true },
    _busy: { state: true },
    _error: { state: true },
  };

  hass?: HomeAssistant;
  doc?: RoomTilesDoc;
  profile?: RobotProfile;
  adding = false;
  private _draft?: RobotProfile;
  private _ask = false;
  private _confirmRemove = false;
  private _busy = false;
  private _error = "";
  private _opened = Date.now();

  private get _view(): RobotProfile {
    return this._draft ?? this.profile!;
  }

  private get _dirty(): boolean {
    return this.adding || (this._draft !== undefined && JSON.stringify(this._draft) !== JSON.stringify(this.profile));
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

  private _save(): Promise<void> {
    const p = this._view;
    const robot = { id: p.id, name: p.name.trim() || this.profile!.name, vacuum: p.vacuum, error: p.error, preset: p.preset };
    return this._run(() => setUpDevice(this, this.hass!, "set_robot", { robot }, robot.name));
  }

  private _remove(): void {
    if (!this._confirmRemove) {
      this._confirmRemove = true;
      return;
    }
    void this._run(() =>
      this.hass!.callService("room_tiles", "ignore_device", { kind: "robot", device: this.profile!, set_up_id: this.profile!.id }),
    );
  }

  private get _cleanArea(): boolean {
    const st = this.hass?.states[this._view.vacuum];
    return !!(Number(st?.attributes.supported_features ?? 0) & CLEAN_AREA);
  }

  render() {
    const p = this._view;
    const name = (e: string | null) => (e && (this.hass?.states[e]?.attributes.friendly_name as string | undefined)) || e || "";
    return html`
      <div class="scrim" style="--z:30" @click=${() => Date.now() - this._opened > 400 && this._tryClose()}></div>
      <div class="dialog" style="--z:30" role="dialog" aria-label=${t("common.settings_of", { name: p.name })}>
        <div class="head">
          <div class="title">${this.adding ? t("common.add_name", { name: this.profile!.name }) : this.profile!.name}</div>
          <button class="x" aria-label=${t("common.close")} title=${t("common.close")} @click=${this._tryClose}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        <div class="list">
          <div class="group">
          <div class="group-head"><ha-icon icon="mdi:robot-vacuum"></ha-icon>${t("robot.title")}</div>
          <div class="setting">
            <span class="label">${t("common.name")}</span>
            <input
              .value=${p.name}
              aria-label=${t("common.name")}
              @input=${(e: Event) => (this._draft = { ...p, name: (e.target as HTMLInputElement).value })}
            />
          </div>
          </div>
          <div class="group">
          <div class="group-head"><ha-icon icon="mdi:format-list-checks"></ha-icon>${t("robot.can_do")}</div>
          <div class="info">${t("robot.tile_shows", { name: name(p.vacuum) })}</div>
          <div class="info">
            ${p.error ? t("robot.alerts_needs_you") : t("robot.alerts_faults")}
          </div>
          ${(() => {
            const vac = this.doc?.vacuums?.[p.vacuum];
            if (!this._cleanArea) return html`<div class="info">${t("robot.rooms_not_supported")}</div>`;
            // none mapped, or a room it reports isn't: one message, no list
            return !(vac?.areas ?? []).length || vac?.unmapped
              ? html`<div class="info warn">${t("robot.rooms_not_set_up")}</div>`
              : html`<div class="info">${t("robot.rooms_supported")}</div>`;
          })()}
          </div>
          ${!this.adding
            ? html`<div class="group">
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
          <button class="primary" ?disabled=${this._busy || !this._dirty} @click=${() => this._save()}>
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
        --dialog-w: 480px;
      }
      .info {
        font-size: 0.85rem;
        color: var(--rt-text-secondary);
        padding: 2px 4px 6px;
      }
      .info.warn {
        color: var(--rt-light);
      }
      input:not([type]) {
        width: 11em;
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

if (!customElements.get("rt-robot-editor")) customElements.define("rt-robot-editor", RtRobotEditor);
