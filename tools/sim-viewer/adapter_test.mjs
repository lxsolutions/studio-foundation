// The renderer observes: viewer frames must equal kernel snapshots, and the
// geometry derived from them must be real.
//
//   node tools/sim-viewer/adapter_test.mjs <sim_kernel.wasm> <replay.json> [entity-doc.json]
//
// The second half is new, and it is here because the first half was not enough.
// This suite used to assert that each frame's `angleDeg` followed the World IR
// hinge range — inside an `if (joint)` branch that never held, because the joint
// table was keyed by part and looked up by instance. The assertion never ran,
// the angle was always 0, and the gates in the viewer never moved. So the
// binding is now exercised for real: same World IR, same layout the viewer uses,
// and a hinge that must swing when the kernel says its gate opened.
import { readFileSync } from "node:fs";
import path from "node:path";
import { framesFromSnapshots, runReplayWasm } from "./adapter.js";
import {
  bindingsFromFrame,
  nodesInModel,
  resolveModel,
} from "../../shared/runtime/scene_binding.mjs";

const [wasmPath, replayPath, docPath] = process.argv.slice(2);
const result = await runReplayWasm(readFileSync(wasmPath), readFileSync(replayPath, "utf8"));
if (result.error) {
  console.error(`kernel rejected the replay: ${result.code} ${result.error}`);
  process.exit(1);
}

const frames = framesFromSnapshots(result.snapshots);

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
    // Presentation geometry must not creep back into the state frame: it is the
    // binding layer's job, where the axis comes from World IR and three engines
    // are held to the same answer.
    check(!("angleDeg" in entity), `frame ${i} ${name} must carry state only, not geometry`);
  }
}

if (docPath) {
  const entity = path.basename(docPath, ".json");
  const docs = { [entity]: JSON.parse(readFileSync(docPath, "utf8")) };
  const layout = JSON.parse(
    readFileSync(new URL("./fortress_layout.json", import.meta.url), "utf8")
  );
  const model = resolveModel(layout, docs);
  const jointNodes = nodesInModel(model).filter((n) => n.parent !== null);
  check(jointNodes.length > 0, `${entity} declares no joints — the binding would be inert`);

  // The rotation axis is READ from World IR, never chosen by the renderer.
  const declared = Object.values(docs[entity].joints ?? {}).map((j) => j.axis.join(","));
  for (const instance of Object.values(model.instances)) {
    for (const joint of instance.joints) {
      check(
        declared.includes(joint.axis.map((n) => (Object.is(n, -0) ? 0 : n)).join(",")),
        `${joint.node} rotates about ${joint.axis} which World IR never declared`
      );
    }
  }

  // A gate the kernel opened must produce a changing rotation.
  const swept = new Map();
  for (const frame of frames) {
    for (const binding of bindingsFromFrame(frame, model)) {
      const seen = swept.get(binding.node) ?? new Set();
      seen.add(binding.rotate.radians.toFixed(9));
      swept.set(binding.node, seen);
    }
  }
  // Max openness across the whole replay, not the last frame: a gate that opened
  // and then shut would otherwise read as one that never moved.
  const opened = new Set();
  for (const frame of frames) {
    for (const [name, entity] of Object.entries(frame.entities)) {
      if (entity.openness > 0) opened.add(name);
    }
  }
  check(opened.size > 0, "no entity ever opened — this replay cannot prove the binding works");
  for (const [node, angles] of swept) {
    const instance = node.split("/")[0];
    check(
      opened.has(instance) ? angles.size > 1 : angles.size === 1,
      opened.has(instance)
        ? `${node} held a single angle (${[...angles]}) though ${instance} opened`
        : `${node} changed angle though ${instance} never opened`
    );
  }
}

if (failures) {
  console.error(`adapter test FAILED (${failures} failures)`);
  process.exit(1);
}
console.log(
  `adapter test OK (${frames.length} frames, ${Object.keys(frames[0].entities).length} entities` +
    (docPath ? ", binding exercised against World IR joints" : "") +
    ")"
);
