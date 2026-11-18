// <rt-unsaved>: asked only when leaving an editor with unsaved changes (the
// one loss a draft + undo can't protect - docs/UI.md). One tap for each way
// out. Fires "save", "discard" or "keep" (also on the backdrop / X / Esc).

import { LitElement, css, html } from "lit";
import { DialogPin } from "./dialog-pin";
import { dialogStyles, noSelectStyles } from "./ui";
import { t } from "./i18n";

export class RtUnsaved extends LitElement {
  /** the dialog's top edge stays put while its content changes (dialog-pin.ts) */
  readonly dialogPin = new DialogPin(this);
  static properties = { what: { type: String } };
  /** what has unsaved changes: "map" (every editor today) */
  what: "map" = "map";
  private _opened = Date.now();

  private _fire(name: "save" | "discard" | "keep"): void {
    this.dispatchEvent(new CustomEvent(name, { bubbles: true, composed: true }));
  }

  render() {
    return html`
      <div class="scrim" style="--z:40" @click=${() => Date.now() - this._opened > 400 && this._fire("keep")}></div>
      <div class="dialog" style="--z:40" role="alertdialog" aria-label=${t("unsaved.dialog")}>
        <div class="head">
          <div class="title">${t(`unsaved.title_${this.what}`)}</div>
          <button class="x" aria-label=${t("common.keep_editing")} @click=${() => this._fire("keep")}><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        <div class="intro">${t(`unsaved.intro_${this.what}`)}</div>
        <div class="footer">
          <button class="discard" @click=${() => this._fire("discard")}>${t("common.discard")}</button>
          <span class="grow"></span>
          <button @click=${() => this._fire("keep")}>${t("common.keep_editing")}</button>
          <button class="primary" @click=${() => this._fire("save")}>${t("common.save_changes")}</button>
        </div>
      </div>
    `;
  }

  static styles = [noSelectStyles, 
    dialogStyles,
    css`
      :host {
        --dialog-w: 420px;
      }
      .grow {
        flex: 1;
      }
      .footer {
        flex-wrap: wrap;
      }
    `,
  ];
}

if (!customElements.get("rt-unsaved")) customElements.define("rt-unsaved", RtUnsaved);
