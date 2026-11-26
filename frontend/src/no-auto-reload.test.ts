import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

// The page reloads only when the user asks for it: a Reload button, or the
// Restart the user pressed. Never by itself after an update (a wall tablet,
// someone reading a board).
const SRC = join(__dirname);
const ALLOWED = [
  /@click=\$\{\(\) => location\.reload\(\)\}/, // a Reload button
  /this\._restarting && .*location\.reload\(\)/, // after the user's own Restart
];
// _reload(): the bar's Reload button (checked below to have no other caller)
const RELOAD_METHOD = /\n  private _reload\(\): void \{\n[\s\S]*?\n  \}\n/;

describe("no automatic reload", () => {
  it("location.reload() runs only from the user's own action", () => {
    const found: string[] = [];
    for (const f of readdirSync(SRC)) {
      if (!f.endsWith(".ts") || f.endsWith(".test.ts")) continue;
      readFileSync(join(SRC, f), "utf8")
        .replace(RELOAD_METHOD, "\n")
        .split("\n")
        .forEach((line, i) => {
          if (line.includes("location.reload(") && !ALLOWED.some((re) => re.test(line))) found.push(`${f}:${i + 1}: ${line.trim()}`);
        });
    }
    expect(found).toEqual([]);
  });

  it("the bar's Reload is the only caller of _reload()", () => {
    const src = readFileSync(join(SRC, "room-tiles-panel.ts"), "utf8");
    const calls = src.match(/this\._reload\(\)/g) ?? [];
    expect(calls).toHaveLength(1);
    expect(src).toMatch(/<button @click=\$\{\(\) => this\._reload\(\)\}>/);
  });
});
