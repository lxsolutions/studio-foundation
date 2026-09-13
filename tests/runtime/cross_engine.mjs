// Three renderers, one simulation, identical geometry (ADR 0020).
//
//   node tests/runtime/cross_engine.mjs
//
// The claim under test is that Studio Foundation's presentation layer is
// engine-neutral. That is easy to assert and easy to get wrong, so it is
// checked the only way that means anything: run the real deterministic kernel,
// derive neutral scene instructions from its snapshots and the World IR joint
// declarations, hand the SAME instructions to three.js, Babylon.js and
// PlayCanvas, and require all three to place the same points in the same world
// coordinates on every tick.
//
// All three run with no GPU and no display — three.js needs no renderer for
// scene-graph maths, Babylon has NullEngine, and PlayCanvas's GraphNode works
// without an Application. So this is a normal test, not a hardware ritual.
//
// It also asserts the scene MOVES. That is not padding: the binding this work
// replaced computed an angle that was always exactly zero, and the test meant
// to cover it kept its only assertion inside an `if (joint)` that never held.
// A conformance suite that would pass against a frozen scene proves nothing.

import { readFileSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { runReplayWasm } from "../../tools/sim-viewer/adapter.js";
import { bindingsFromFrame, nodesInModel, resolveModel } from "../../shared/runtime/scene_binding.mjs";
import { createBabylonAdapter } from "../../shared/runtime/adapters/babylon_adapter.mjs";
import { createPlayCanvasAdapter } from "../../shared/runtime/adapters/playcanvas_adapter.mjs";
import { createThreeAdapter } from "../../shared/runtime/adapters/three_adapter.mjs";

const REPO = path.resolve(new URL("../../", import.meta.url).pathname);
const WASM = path.join(REPO, "services/target/wasm32-unknown-unknown/release/sim_kernel.wasm");
const REQUIRE_ENGINES = Boolean(process.env.RUNTIME_REQUIRE_ENGINES);

// Two worlds, so the suite is held to more than the door it was written for
// (ADR 0023): the fortress (hinges driven by openness) and the depot (a slider
// driven by a float height, a hinge driven by a bool).
const WORLDS = [
  {
    name: "fortress",
    replay: "tools/worldc/examples/fortress_battle.json",
    docs: { fortress_gate: "tools/worldc/examples/fortress_gate.json" },
    layout: "tools/sim-viewer/fortress_layout.json",
  },
  {
    name: "depot",
    replay: "tools/worldc/examples/depot_shift.json",
    docs: {
      cargo_lift: "tools/worldc/examples/cargo_lift.json",
      signal_lever: "tools/worldc/examples/signal_lever.json",
    },
    layout: "tools/sim-viewer/depot_layout.json",
  },
];

// A point off the rotation axis, so any disagreement about axis, sign, units or
// handedness moves it. Probing the origin would agree no matter what.
const PROBE = [1, 0.25, 0];
// Agreement is exact only to single precision, and that is a real property of
// the engines rather than a fudge factor: three.js keeps Matrix4 in a float64
// JS array, while Babylon and PlayCanvas store transforms in Float32Array. A
// coordinate near 3.2 therefore carries ~4e-7 of representation error before
// anything in this repository runs. Demanding 1e-9 would fail every tick and
// teach the reader that "engine-neutral" is false, when what is actually true
// is "engine-neutral to the precision the engines keep".
const TOLERANCE = 1e-6;

const failures = [];
const check = (ok, what) => {
  if (!ok) failures.push(what);
  return ok;
};

async function loadEngines() {
  // The engine packages are resolved HERE, from tests/runtime/node_modules.
  // Node resolves bare specifiers relative to the importing file, so an import
  // inside shared/ would look next to shared/ and never find them — which is
  // also why the adapters take the module as an argument.
  const wanted = [
    ["three.js", () => import("three"), createThreeAdapter],
    // The babylonjs UMD package hangs every symbol off the ESM default export;
    // a named import of NullEngine silently yields undefined.
    ["babylon.js", async () => (await import("babylonjs")).default, createBabylonAdapter],
    ["playcanvas", () => import("playcanvas"), createPlayCanvasAdapter],
  ];
  const engines = [];
  const missing = [];
  for (const [name, load, factory] of wanted) {
    try {
      const module = await load();
      engines.push(() => factory(module)); // a fresh adapter per world
    } catch (error) {
      missing.push(`${name} (${error.message.split("\n")[0]})`);
    }
  }
  return { engines, missing };
}

/** Per joint node: did its drive var ever change over the replay? */
function driveChanged(frames, model) {
  const changed = {};
  for (const instance of Object.values(model.instances)) {
    for (const joint of instance.joints) {
      const instanceName = joint.node.split("/")[0];
      const seen = new Set(frames.map((f) => JSON.stringify(f.entities[instanceName]?.[joint.drive.var])));
      changed[joint.node] = { var: joint.drive.var, changed: seen.size > 1 };
    }
  }
  return changed;
}

async function runWorld(world, engines, wasmBytes) {
  const adapters = engines.map((make) => make());
  const replayText = readFileSync(path.join(REPO, world.replay), "utf8");
  const result = await runReplayWasm(wasmBytes, replayText);
  if (result.error) {
    check(false, `${world.name}: kernel rejected the replay: ${result.code} ${result.error}`);
    return null;
  }
  const docs = Object.fromEntries(
    Object.entries(world.docs).map(([name, file]) => [name, JSON.parse(readFileSync(path.join(REPO, file), "utf8"))])
  );
  const layout = JSON.parse(readFileSync(path.join(REPO, world.layout), "utf8"));
  const model = resolveModel(layout, docs);
  const nodes = nodesInModel(model);
  const jointNodes = nodes.filter((n) => n.parent !== null).map((n) => n.node);
  check(jointNodes.length >= 1, `${world.name}: expected joint nodes, got ${jointNodes.length}`);

  for (const adapter of adapters) adapter.build(nodes);

  // Frames carry simulation state only; the geometry is derived here, from the
  // axis and the drive World IR declares — the renderer never picks either.
  const frames = result.snapshots.map((snapshot) => ({
    entities: Object.fromEntries(
      Object.entries(snapshot).map(([name, entry]) => [name, entry.state ?? {}])
    ),
  }));

  const travel = new Map(jointNodes.map((node) => [node, 0]));
  let previous = null;

  for (const [tick, frame] of frames.entries()) {
    const bindings = bindingsFromFrame(frame, model);
    check(bindings.length === jointNodes.length, `${world.name} tick ${tick}: binding count`);
    for (const adapter of adapters) adapter.apply(bindings);

    const reference = adapters[0];
    const current = {};
    for (const node of jointNodes) {
      const expected = reference.probe(node, PROBE);
      current[node] = expected;
      for (const adapter of adapters.slice(1)) {
        const actual = adapter.probe(node, PROBE);
        const drift = Math.max(...expected.map((v, i) => Math.abs(v - actual[i])));
        check(
          drift <= TOLERANCE,
          `${world.name} tick ${tick} ${node}: ${adapter.name} is ${drift.toExponential(2)} from ` +
            `${reference.name} (${actual.map((n) => n.toFixed(9))} vs ${expected.map((n) => n.toFixed(9))})`
        );
        check(
          adapter.visible(node) === reference.visible(node),
          `${world.name} tick ${tick} ${node}: ${adapter.name} visibility disagrees with ${reference.name}`
        );
      }
    }
    if (previous) {
      for (const node of jointNodes) {
        const delta = Math.hypot(...current[node].map((v, i) => v - previous[node][i]));
        travel.set(node, travel.get(node) + delta);
      }
    }
    previous = current;
  }

  // The anti-vacuity gate, tied to the data rather than to an assumption: a
  // joint must move exactly when the state var that DRIVES it changed, and
  // must not when it did not. Requiring every joint to move would be wrong —
  // the fortress replay opens `gate_side` while it is still locked, so it
  // correctly stays shut for all 21 ticks, and a blunter assertion would call
  // that a defect.
  const drives = driveChanged(frames, model);
  let movers = 0;
  for (const [node, distance] of travel) {
    const { var: drive, changed } = drives[node];
    if (changed) movers += 1;
    check(
      changed ? distance > 0.1 : distance === 0,
      changed
        ? `${world.name}: ${node} never moved (travel ${distance.toFixed(6)}) though its drive ` +
          `'${drive}' changed — an inert binding is the exact failure this suite exists to catch`
        : `${world.name}: ${node} moved ${distance.toFixed(6)} though its drive '${drive}' never changed`
    );
  }
  check(movers > 0, `${world.name}: no joint moved in the whole replay — the fixture proves nothing`);
  const swept = [...travel.values()].reduce((a, b) => a + b, 0) / travel.size;
  return { ticks: frames.length, joints: jointNodes.length, swept, adapters: adapters.map((a) => a.name) };
}

async function main() {
  let wasmBytes;
  try {
    wasmBytes = readFileSync(WASM);
  } catch {
    console.error(`sim_kernel.wasm not found at ${WASM}\nBuild it: just sim-parity`);
    return 2;
  }

  const { engines, missing } = await loadEngines();
  if (missing.length && REQUIRE_ENGINES) {
    console.error(`RUNTIME_REQUIRE_ENGINES=1 but engines are unavailable:\n  ${missing.join("\n  ")}`);
    return 1;
  }
  if (engines.length < 2) {
    console.log(
      `SKIP: cross-engine conformance needs at least two engines; missing ${missing.join(", ")}\n` +
        "Install them: cd tests/runtime && npm ci"
    );
    return 0;
  }

  const summaries = [];
  for (const world of WORLDS) {
    const summary = await runWorld(world, engines, wasmBytes);
    if (summary) summaries.push(`${world.name}: ${summary.ticks} ticks x ${summary.joints} joints, mean travel ${summary.swept.toFixed(3)}`);
  }

  if (failures.length) {
    console.error(`\ncross-engine conformance FAILED (${failures.length}):`);
    for (const failure of failures.slice(0, 20)) console.error(`  - ${failure}`);
    if (failures.length > 20) console.error(`  ... and ${failures.length - 20} more`);
    return 1;
  }
  console.log(
    `cross-engine conformance OK — ${engines.map((make) => make().name).join(", ")} agree to within ` +
      `${TOLERANCE.toExponential(0)} on ${WORLDS.length} worlds (${summaries.join("; ")})` +
      (missing.length ? `\n  note: skipped ${missing.length} unavailable engine(s)` : "")
  );
  return 0;
}

process.exit(await main());
