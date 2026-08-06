// sim-viewer adapter — the renderer's only window into the simulation.
//
// The kernel produces per-tick world snapshots; this module maps them to
// presentation frames. It runs identically in the browser (rendering with
// Babylon.js) and in node (test), and it has NO way to write simulation
// state — observation only.
//
// Frame shape:
//   { tick, entities: { name: { openness, angleDeg, blocked, destroyed, locked, health } } }

/** Derive presentation frames from kernel snapshots and World IR joint data. */
export function framesFromSnapshots(snapshots, joints = {}, navThresholdMilli = 700) {
  return snapshots.map((world, tick) => {
    const entities = {};
    for (const [name, entry] of Object.entries(world)) {
      const state = entry.state ?? {};
      const openness = state.openness ?? 0;
      let angleDeg = 0;
      const joint = joints[name];
      if (joint) {
        const [minDeg, maxDeg] = joint.range_degrees ?? [0, 110];
        angleDeg = minDeg + (openness / 1000) * (maxDeg - minDeg);
      }
      const destroyed = state.destroyed ?? false;
      const blocked = destroyed ? false : openness < navThresholdMilli;
      entities[name] = {
        openness,
        angleDeg,
        blocked,
        destroyed,
        locked: state.locked ?? false,
        health: state.health ?? 0,
      };
    }
    return { tick, entities };
  });
}

/** Pull joint metadata (presentation-only) out of World IR entity docs. */
export function jointsFromEntityDocs(docs) {
  const joints = {};
  for (const [, doc] of Object.entries(docs)) {
    for (const [, joint] of Object.entries(doc.joints ?? {})) {
      joints[joint.child] = joint;
    }
  }
  return joints;
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
