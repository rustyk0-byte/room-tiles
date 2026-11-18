// The map editor's trace picture: a floor-plan image placed under the drawing
// to trace over. Kept in THIS browser only (IndexedDB, per map) - it's a
// drawing aid, never part of the map in HA. Everything here may fail (private
// windows, blocked storage): callers just carry on without it.

export interface TracePicture {
  blob: Blob;
  /** top-left corner and size in map units (before the tilt); without `h`
   *  the height follows the image's own shape */
  x: number;
  y: number;
  w: number;
  h?: number;
  /** quarter turns clockwise (0-3), and a fine tilt on top (degrees) */
  rot: number;
  tilt?: number;
  /** (from before the blend: the picture's opacity - not used any more) */
  opacity: number;
  /** picture <-> drawing: 0 = the picture, 1 = the drawing, 0.5 = both in
   *  full (traceBlend) */
  blend?: number;
  hidden?: boolean;
}

const DB = "room-tiles";
const STORE = "trace";

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function run<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest): Promise<T | undefined> {
  try {
    const db = await open();
    return await new Promise<T | undefined>((resolve, reject) => {
      const req = fn(db.transaction(STORE, mode).objectStore(STORE));
      req.onsuccess = () => resolve(req.result as T);
      req.onerror = () => reject(req.error);
    });
  } catch {
    return undefined;
  }
}

export const loadTrace = (map: string) => run<TracePicture>("readonly", (s) => s.get(map));
export const saveTrace = (map: string, t: TracePicture) => run("readwrite", (s) => s.put(t, map));
export const deleteTrace = (map: string) => run("readwrite", (s) => s.delete(map));
