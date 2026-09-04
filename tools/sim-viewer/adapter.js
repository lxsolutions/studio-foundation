// sim-viewer adapter — the renderer's only window into the simulation.
//
// The kernel produces per-tick world snapshots; this module maps them to
// presentation frames. It runs identically in the browser and in node (test),
// and it has NO way to write simulation state — observation only.
//
// Frame shape:
//   { tick, entities: { name: { openness, blocked, destroyed, locked, health } } }
//
// Frames carry simulation STATE and nothing else. They used to also carry an
// `angleDeg`, derived here from World IR joints — which never once worked: the
// joint table was keyed by part ("leaf_l") and looked up by instance
// ("gate_main"), so the lookup missed on every entity and the angle was always
// exactly 0. The gate leaves in the viewer never moved, and the test that meant
// to cover it kept its only assertion inside `if (joint)`, which never held.
//
// Geometry now lives in shared/runtime/scene_binding.mjs, where the rotation
// axis is read from World IR rather than chosen by a renderer, and where three
// engines are held to the same answer (ADR 0020).

/** Derive presentation frames from kernel snapshots. State only, no geometry. */
export function framesFromSnapshots(snapshots, navThresholdMilli = 700) {
  return snapshots.map((world, tick) => {
    const entities = {};
    for (const [name, entry] of Object.entries(world)) {
      const state = entry.state ?? {};
      const openness = state.openness ?? 0;
      const destroyed = state.destroyed ?? false;
      entities[name] = {
        openness,
        // Navigation is derived from the snapshot, never from a parallel truth.
        blocked: destroyed ? false : openness < navThresholdMilli,
        destroyed,
        locked: state.locked ?? false,
        health: state.health ?? 0,
      };
    }
    return { tick, entities };
  });
}

/** Run a replay through the wasm kernel and return the parsed result. */
export async function runReplayWasm(wasmBytes, replayText) {
  const { instance } = await WebAssembly.instantiate(wasmBytes, {});
  const { sim_alloc, sim_run, sim_free, memory } = instance.exports;
  const input = new TextEncoder().encode(replayText);
  const inPtr = sim_alloc(input.length);
  new Uint8Array(memory.buffer, inPtr, input.length).set(input);
  const packed = sim_run(inPtr, input.length);
  sim_free(inPtr, input.length);
  const outPtr = Number(packed >> 32n);
  const outLen = Number(packed & 0xffffffffn);
  const out = new TextDecoder().decode(new Uint8Array(memory.buffer, outPtr, outLen));
  sim_free(outPtr, outLen);
  return JSON.parse(out);
}
