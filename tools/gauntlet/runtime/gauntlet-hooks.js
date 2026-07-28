// gauntlet-hooks — drop this into any browser game and the harness can pose it.
//
// WHY THIS EXISTS
//
// Screenshotting a game that is rendering flat out costs ~19 seconds, because
// the page starves the compositor. Measured, not guessed. A loop that can only
// observe its work every 19 seconds is not a loop.
//
// Worse: if the camera is wherever gameplay left it, then frame N and frame
// N-1 differ for reasons that have nothing to do with the change you made. You
// cannot tell improvement from noise. Every "it looks better now" is unfalsifiable.
//
// So the game exposes control instead. The harness pauses it, poses it, steps
// it a fixed number of frames from a fixed seed, and captures. Same input,
// same pixels, every run. Now a diff means something.
//
// USAGE (minimal — works with any engine, no cooperation required):
//
//     import './gauntlet-hooks.js';
//
// USAGE (full — deterministic posing):
//
//     import { gauntlet } from './gauntlet-hooks.js';
//     gauntlet.register({
//       seed:   (n) => world.reseed(n),
//       camera: { hero: () => cam.set(...), wide: () => cam.set(...) },
//       stats:  () => ({ drawCalls: r.info.render.calls, tris: r.info.render.triangles }),
//       ready:  somePromiseThatResolvesWhenFirstFrameIsDrawn,
//     });

const state = {
  paused: false,
  queued: [],
  virtualNow: 0,
  frameCount: 0,
  stepBudget: 0,
  registered: {},
  readyResolved: false,
};

const realRaf = globalThis.requestAnimationFrame?.bind(globalThis);
const realCancel = globalThis.cancelAnimationFrame?.bind(globalThis);

let readyResolve;
const readyPromise = new Promise((r) => (readyResolve = r));

// ---------------------------------------------------------------------------
// rAF interception
//
// Pausing at the rAF boundary works for every engine that animates via rAF,
// which is all of them in a browser. We do not need engine buy-in for pause,
// step, or frame timing -- only for seeding and camera posing.

if (realRaf) {
  globalThis.requestAnimationFrame = function (cb) {
    if (state.paused && state.stepBudget <= 0) {
      // Hold the callback. The engine thinks it asked for a frame; it just
      // will not get one until we say so. No busy-wait, no GPU load.
      const token = { cb, id: ++tokenSeq };
      state.queued.push(token);
      return -token.id;
    }
    return realRaf((t) => runCallback(cb, t));
  };

  globalThis.cancelAnimationFrame = function (id) {
    if (id < 0) {
      const want = -id;
      const i = state.queued.findIndex((q) => q.id === want);
      if (i >= 0) state.queued.splice(i, 1);
      return;
    }
    return realCancel?.(id);
  };
}

let tokenSeq = 0;

function runCallback(cb, realT) {
  // Feed a virtual clock when stepping so physics and animation advance by a
  // fixed dt regardless of how long the machine actually took. This is what
  // makes captures reproducible on a busy laptop.
  const t = state.stepBudget > 0 || state.paused ? state.virtualNow : realT;
  const start = performance.now();
  try {
    cb(t);
  } finally {
    const cost = performance.now() - start;
    metrics.cb.push(cost);
    if (metrics.lastT !== null) metrics.dt.push(t - metrics.lastT);
    metrics.lastT = t;
    if (metrics.cb.length > 12000) {
      metrics.cb.splice(0, 4000);
      metrics.dt.splice(0, 4000);
    }
    state.frameCount++;
    if (!state.readyResolved && state.frameCount >= 2) {
      state.readyResolved = true;
      readyResolve();
    }
    if (state.stepBudget > 0) state.stepBudget--;
  }
}

const metrics = { dt: [], cb: [], lastT: null, longTasks: 0 };

try {
  new PerformanceObserver((l) => {
    metrics.longTasks += l.getEntries().length;
  }).observe({ entryTypes: ['longtask'] });
} catch {
  /* longtask not supported everywhere */
}

// ---------------------------------------------------------------------------
// public control surface

function drain(frames, dtMs) {
  // Release exactly `frames` held callbacks, advancing the virtual clock by a
  // fixed dt each time.
  return new Promise((resolve) => {
    let remaining = frames;
    const pump = () => {
      if (remaining <= 0) return resolve(state.frameCount);
      const batch = state.queued.splice(0, state.queued.length);
      state.virtualNow += dtMs;
      state.stepBudget = batch.length || 1;
      if (batch.length === 0) {
        // Engine is idle (not requesting frames). Nothing to step.
        return resolve(state.frameCount);
      }
      for (const q of batch) realRaf(() => runCallback(q.cb, state.virtualNow));
      remaining--;
      realRaf(pump);
    };
    pump();
  });
}

export const gauntlet = {
  version: 1,

  /** Games call this to expose deterministic posing. All fields optional. */
  register(hooks) {
    Object.assign(state.registered, hooks);
    if (hooks.ready && typeof hooks.ready.then === 'function') {
      hooks.ready.then(() => {
        state.readyResolved = true;
        readyResolve();
      });
    }
  },

  /** Resolves once the game has drawn real frames. */
  get ready() {
    return readyPromise;
  },

  pause() {
    state.paused = true;
    state.virtualNow = state.virtualNow || performance.now();
    return true;
  },

  resume() {
    state.paused = false;
    const batch = state.queued.splice(0, state.queued.length);
    for (const q of batch) realRaf((t) => runCallback(q.cb, t));
    return true;
  },

  /** Advance exactly n frames at a fixed dt while paused. */
  async step(n = 1, dtMs = 1000 / 60) {
    if (!state.paused) this.pause();
    return drain(n, dtMs);
  },

  /** Reseed the world, if the game registered a seed hook. */
  seed(n) {
    if (!state.registered.seed) return { ok: false, reason: 'no seed hook registered' };
    state.registered.seed(n);
    return { ok: true };
  },

  cameras() {
    return Object.keys(state.registered.camera ?? {});
  },

  setCamera(name) {
    const c = state.registered.camera?.[name];
    if (!c) return { ok: false, reason: `no camera "${name}"`, available: this.cameras() };
    c();
    return { ok: true };
  },

  /**
   * Game state as named scalars/vectors, for playability assertions.
   *
   * Borrowed from Claude-of-Duty's tools/playtest.mjs, which checks something
   * this harness originally missed entirely: not "does it look right" but
   * "does pressing W actually move you". A beautiful build with dead controls
   * passes every visual gate ever written.
   */
  probe() {
    return state.registered.probe ? state.registered.probe() : {};
  },

  /**
   * Walk the scene for non-finite transforms. A single NaN propagates through
   * a matrix and silently deletes geometry -- it shows up as "things vanished"
   * long after the frame where it happened. Requires the game to register its
   * scene; returns null if it did not.
   */
  nanScan() {
    const scene = state.registered.scene;
    if (!scene || typeof scene.traverse !== 'function') return null;
    let objects = 0;
    let bad = 0;
    const names = [];
    const finite = (v) => v == null || (Number.isFinite(v.x) && Number.isFinite(v.y) && Number.isFinite(v.z));
    scene.traverse((o) => {
      objects++;
      const ok =
        finite(o.position) &&
        finite(o.scale) &&
        (!o.quaternion ||
          (Number.isFinite(o.quaternion.x) &&
            Number.isFinite(o.quaternion.y) &&
            Number.isFinite(o.quaternion.z) &&
            Number.isFinite(o.quaternion.w)));
      if (!ok) {
        bad++;
        if (names.length < 12) names.push(o.name || o.type || 'unnamed');
      }
    });
    return { objects, nonFinite: bad, offenders: names };
  },

  stats() {
    const extra = state.registered.stats ? state.registered.stats() : {};
    const sorted = (a) => [...a].sort((x, y) => x - y);
    const pct = (a, p) => (a.length ? +a[Math.min(a.length - 1, Math.round((p / 100) * (a.length - 1)))].toFixed(2) : null);
    const dt = sorted(metrics.dt);
    const cb = sorted(metrics.cb);
    return {
      frames: state.frameCount,
      paused: state.paused,
      frameMsP50: pct(dt, 50),
      frameMsP99: pct(dt, 99),
      scriptMsP50: pct(cb, 50),
      scriptMsP99: pct(cb, 99),
      longTasks: metrics.longTasks,
      ...extra,
    };
  },

  resetMetrics() {
    metrics.dt.length = 0;
    metrics.cb.length = 0;
    metrics.lastT = null;
    metrics.longTasks = 0;
    return true;
  },
};

// The harness looks for exactly this global.
globalThis.__gauntlet = gauntlet;

export default gauntlet;
