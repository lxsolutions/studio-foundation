// Node adapter test: the viewer's frames must equal the kernel's snapshots.
// The renderer observes; it must never invent state.
//
//   node tools/sim-viewer/adapter_test.mjs <sim_kernel.wasm> <replay.json> [entity-doc.json]
import { readFileSync } from "node:fs";
import { framesFromSnapshots, jointsFromEntityDocs, runReplayWasm } from "./adapter.js";

const [wasmPath, replayPath, docPath] = process.argv.slice(2);
const result = await runReplayWasm(readFileSync(wasmPath), readFileSync(replayPath, "utf8"));
if (result.error) {
  console.error(`kernel rejected the replay: ${result.code} ${result.error}`);
  process.exit(1);
}

const docs = docPath ? { doc: JSON.parse(readFileSync(docPath, "utf8")) } : {};
const frames = framesFromSnapshots(result.snapshots, jointsFromEntityDocs(docs));

let failures = 0;
const check = (ok, what) => {
  if (!ok) {
    console.error(`FAIL: ${what}`);
    failures += 1;
  }
};

check(frames.length === result.snapshots.length, "frame count must equal snapshot count");
for (const [i, frame] of frames.entries()) {
  const world = result.snapshots[i];
  check(frame.tick === i, `frame ${i} tick index`);
  for (const [name, entity] of Object.entries(frame.entities)) {
    const state = world[name].state;
    check(entity.openness === state.openness, `frame ${i} ${name}.openness matches snapshot`);
    check(entity.destroyed === (state.destroyed ?? false), `frame ${i} ${name}.destroyed matches`);
    check(entity.locked === (state.locked ?? false), `frame ${i} ${name}.locked matches`);
    check(entity.health === (state.health ?? 0), `frame ${i} ${name}.health matches`);
    // navigation is derived from snapshot, not from a parallel truth
    const expectBlocked = state.destroyed ? false : state.openness < 700;
    check(entity.blocked === expectBlocked, `frame ${i} ${name}.blocked derived from snapshot`);
    if (docPath) {
      const joint = jointsFromEntityDocs(docs)[name];
      if (joint) {
        const [minDeg, maxDeg] = joint.range_degrees;
        const expectedAngle = minDeg + (state.openness / 1000) * (maxDeg - minDeg);
        check(
          Math.abs(entity.angleDeg - expectedAngle) < 1e-9,
          `frame ${i} ${name}.angleDeg follows the hinge range`
        );
      }
    }
  }
}

if (failures) {
  console.error(`adapter test FAILED (${failures} failures)`);
  process.exit(1);
}
console.log(`adapter test OK (${frames.length} frames, ${Object.keys(frames[0].entities).length} entities)`);
