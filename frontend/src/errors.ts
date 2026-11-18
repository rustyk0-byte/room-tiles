// The dashboard's recent errors, for Send feedback's bugs "on this dashboard"
// (DESIGN.md "Privacy: what reports send" > Send feedback): Room Tiles' own
// uncaught errors and rejected promises - not the rest of Home Assistant's
// page - the last 10, in this page's memory only (never stored; sent only
// in a bug the user sends, scrubbed in HA: report.py _error_text).

export interface RecentError {
  /** seconds ago (never a time of day) */
  ago_s: number;
  message: string;
  /** where in Room Tiles' code: "room-tiles-panel.js:3:51234" */
  where?: string;
}

const MAX = 10;
const OURS = /room[-_]tiles/i;
const recent: { at: number; message: string; where?: string }[] = [];
let installed = false;

/** The first place in Room Tiles' own code in a stack (or a file + line),
 *  as "file.js:line:column" - no folders, no query. */
export function whereIn(stack: string | undefined, file?: string, line?: number, col?: number): string | undefined {
  const frame = (stack ?? "").split("\n").find((l) => OURS.test(l));
  const m = frame?.match(/([\w.-]+\.m?js)(?:\?[^:)\s]*)?:(\d+)(?::(\d+))?/);
  if (m) return `${m[1]}:${m[2]}${m[3] ? `:${m[3]}` : ""}`;
  if (file && OURS.test(file)) {
    const base = file.split("?")[0].split("/").pop() ?? "";
    if (base) return `${base}:${line ?? 0}${col ? `:${col}` : ""}`;
  }
  return undefined;
}

/** Note one error - only Room Tiles' own (its stack or file says so). */
export function noteError(message: string, stack?: string, file?: string, line?: number, col?: number, now = Date.now()): void {
  const where = whereIn(stack, file, line, col);
  if (!where) return;
  recent.push({ at: now, message: String(message || "Error").slice(0, 300), where });
  if (recent.length > MAX) recent.shift();
}

/** Watch for errors (once). */
export function watchErrors(target: Window = window): void {
  if (installed) return;
  installed = true;
  target.addEventListener("error", (e: ErrorEvent) => {
    noteError(e.message, (e.error as Error | undefined)?.stack, e.filename, e.lineno, e.colno);
  });
  target.addEventListener("unhandledrejection", (e: PromiseRejectionEvent) => {
    const r = e.reason as { message?: string; stack?: string } | undefined;
    noteError(r?.message ?? String(e.reason), r?.stack);
  });
}

/** The errors so far, newest last. */
export function recentErrors(now = Date.now()): RecentError[] {
  return recent.map((r) => ({ ago_s: Math.max(0, Math.round((now - r.at) / 1000)), message: r.message, ...(r.where ? { where: r.where } : {}) }));
}

/** (tests) */
export function clearErrors(): void {
  recent.length = 0;
}
