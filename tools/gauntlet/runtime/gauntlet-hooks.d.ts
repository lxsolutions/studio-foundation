// Types for the runtime contract.
//
// The implementation stays plain JS deliberately: it is a verified component
// that the harness depends on, and there is no reason to churn it. Call sites
// get full checking from this declaration, which is where the errors actually
// happen.

export interface GauntletStats {
  frames: number;
  paused: boolean;
  frameMsP50: number | null;
  frameMsP99: number | null;
  scriptMsP50: number | null;
  scriptMsP99: number | null;
  longTasks: number;
  [extra: string]: unknown;
}

export interface NanScanResult {
  objects: number;
  nonFinite: number;
  offenders: string[];
}

/** Everything is optional — register only what the game can actually provide. */
export interface GauntletHooks {
  /** Resolves once the game has drawn real frames. */
  ready?: Promise<unknown>;
  /** Rebuild the world deterministically from a seed. */
  seed?: (n: number) => void;

  /**
   * Swap the whole scene between shading modes so the harness can measure how
   * much of a frame's detail is modelled versus textured. `'beauty'` is the
   * real look; `'flat'` is a neutral matte with no maps. Games that skip this
   * simply do not get the geometry pass -- the harness reports it as skipped
   * rather than inventing a number.
   */
  materials?: (mode: 'beauty' | 'flat') => void;
  /** Named camera poses. Named poses are what make captures comparable. */
  camera?: Record<string, () => void>;
  /** Renderer/scene counters merged into stats(). */
  stats?: () => Record<string, unknown>;
  /** Game state as named scalars/vectors, for playability assertions. */
  probe?: () => Record<string, unknown>;
  /** A THREE.Scene (or anything with .traverse) to enable the NaN scan. */
  scene?: { traverse(cb: (o: any) => void): void };
}

export interface Gauntlet {
  readonly version: number;
  register(hooks: GauntletHooks): void;
  readonly ready: Promise<void>;
  pause(): boolean;
  resume(): boolean;
  /**
   * Advance exactly n frames at a fixed dt while paused.
   *
   * Pass dtMs = 0 to re-render the SAME simulation time — that is what isolates
   * non-deterministic rendering (z-fighting, TAA jitter) from legitimate
   * animation. Advancing real time here made a rotating textured prop register
   * as "instability" and cost two rounds.
   */
  step(n?: number, dtMs?: number): Promise<number>;
  seed(n: number): { ok: boolean; reason?: string };

  /** Switch shading mode; see `GauntletHooks.materials`. */
  setMaterialMode(mode: 'beauty' | 'flat'): { ok: boolean; mode?: string; reason?: string };
  cameras(): string[];
  setCamera(name: string): { ok: boolean; reason?: string; available?: string[] };
  stats(): GauntletStats;
  probe(): Record<string, unknown>;
  nanScan(): NanScanResult | null;
  resetMetrics(): boolean;
}

export const gauntlet: Gauntlet;
export default gauntlet;

declare global {
  // eslint-disable-next-line no-var
  var __gauntlet: Gauntlet | undefined;
}
