// The neutral binding contract, checked with no engine installed (ADR 0020).
//
//   node tests/runtime/scene_binding_test.mjs
//
// cross_engine.mjs proves three renderers agree; this proves the thing they
// agree about is correct. It needs no npm packages, so it runs everywhere and
// is the suite that fails first when the contract itself is wrong.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { bindingsFromFrame, nodesInModel, resolveModel } from "../../shared/runtime/scene_binding.mjs";

const REPO = path.resolve(new URL("../../", import.meta.url).pathname);
const DOC = JSON.parse(readFileSync(path.join(REPO, "tools/worldc/examples/fortress_gate.json"), "utf8"));
const LAYOUT = JSON.parse(readFileSync(path.join(REPO, "tools/sim-viewer/fortress_layout.json"), "utf8"));
const DOCS = { fortress_gate: DOC };
const LIFT = JSON.parse(readFileSync(path.join(REPO, "tools/worldc/examples/cargo_lift.json"), "utf8"));
const LEVER = JSON.parse(readFileSync(path.join(REPO, "tools/worldc/examples/signal_lever.json"), "utf8"));
const DEPOT_LAYOUT = JSON.parse(readFileSync(path.join(REPO, "tools/sim-viewer/depot_layout.json"), "utf8"));
const DEPOT = { cargo_lift: LIFT, signal_lever: LEVER };

let failures = 0;
const test = (name, fn) => {
  try {
    fn();
  } catch (error) {
    console.error(`FAIL ${name}: ${error.message}`);
    failures += 1;
  }
};
const frame = (entities) => ({ entities });

test("the rotation axis comes from World IR, not from the renderer", () => {
  const model = resolveModel(LAYOUT, DOCS);
  const declared = Object.values(DOC.joints).map((j) => j.axis);
  for (const instance of Object.values(model.instances)) {
    for (const joint of instance.joints) {
      assert.ok(
        declared.some((axis) => axis.every((n, i) => Math.abs(n - joint.axis[i]) < 1e-12)),
        `${joint.node} uses ${joint.axis}, which World IR never declared`
      );
    }
  }
  // The fortress hinges turn about Z. The viewer this replaced rotated about Y.
  assert.deepEqual(model.instances.gate_main.joints[0].axis, [0, 0, 1]);
});

test("instance names and part names are not confused", () => {
  // The defect this contract exists to prevent: joints keyed by part
  // ("leaf_l") looked up by instance ("gate_main") silently yields nothing.
  const model = resolveModel(LAYOUT, DOCS);
  const nodes = nodesInModel(model).map((n) => n.node);
  assert.ok(nodes.includes("gate_main"), "instance root missing");
  assert.ok(nodes.includes("gate_main/leaf_l"), "joint node must be instance-qualified");
  assert.ok(!nodes.includes("leaf_l"), "a bare part name would collide across instances");
});

test("a layout naming an unknown entity fails loudly", () => {
  assert.throws(
    () => resolveModel({ instances: { g: { entity: "nope" } } }, DOCS),
    /not among the World IR docs/
  );
});

test("a joint with no usable axis fails loudly", () => {
  const broken = { fortress_gate: { joints: { h: { child: "leaf_l", axis: [0, 0, 0] } } } };
  assert.throws(() => resolveModel(LAYOUT, broken), /zero-length axis/);
  const missing = { fortress_gate: { joints: { h: { child: "leaf_l" } } } };
  assert.throws(() => resolveModel(LAYOUT, missing), /no usable axis/);
});

test("openness maps across the declared hinge range", () => {
  const model = resolveModel(LAYOUT, DOCS);
  const at = (openness) =>
    bindingsFromFrame(frame({ gate_main: { openness } }), model)
      .filter((b) => b.node === "gate_main/leaf_r")[0].rotate.radians;
  const [minDeg, maxDeg] = Object.values(DOC.joints)[0].range_degrees;
  assert.equal(at(0), (minDeg * Math.PI) / 180);
  assert.ok(Math.abs(at(1000) - (maxDeg * Math.PI) / 180) < 1e-12, "fully open must reach the max");
  assert.ok(Math.abs(at(500) - (((minDeg + maxDeg) / 2) * Math.PI) / 180) < 1e-12, "half open");
});

test("openness outside the kernel's range is clamped, not extrapolated", () => {
  const model = resolveModel(LAYOUT, DOCS);
  const at = (openness) =>
    bindingsFromFrame(frame({ gate_main: { openness } }), model)[0].rotate.radians;
  assert.equal(at(-500), at(0), "negative openness must not swing a hinge backwards");
  assert.equal(at(9999), at(1000), "over-open must not push past the declared range");
});

test("the swing sign is placement data, and the two leaves mirror", () => {
  const model = resolveModel(LAYOUT, DOCS);
  const bindings = bindingsFromFrame(frame({ gate_main: { openness: 1000 } }), model);
  const left = bindings.find((b) => b.node === "gate_main/leaf_l").rotate.radians;
  const right = bindings.find((b) => b.node === "gate_main/leaf_r").rotate.radians;
  assert.ok(left < 0 && right > 0, "a double door's leaves must swing apart");
  assert.ok(Math.abs(left + right) < 1e-12, "and by equal amounts");
});

test("destroyed hides, and an unplaced entity is ignored rather than crashing", () => {
  const model = resolveModel(LAYOUT, DOCS);
  const bindings = bindingsFromFrame(
    frame({ gate_main: { openness: 400, destroyed: true }, ghost: { openness: 900 } }),
    model
  );
  assert.ok(bindings.every((b) => b.node.startsWith("gate_")), "simulated-but-unplaced must be skipped");
  assert.ok(
    bindings.filter((b) => b.node.startsWith("gate_main")).every((b) => b.hidden),
    "a destroyed entity's parts must be hidden"
  );
});

test("the binding is pure: same input, same output", () => {
  const model = resolveModel(LAYOUT, DOCS);
  const input = frame({ gate_main: { openness: 321 }, gate_side: { openness: 654 } });
  assert.deepEqual(bindingsFromFrame(input, model), bindingsFromFrame(input, model));
});

test("a joint without a drive inherits the door convention, and only then", () => {
  const model = resolveModel(LAYOUT, DOCS);
  assert.deepEqual(model.instances.gate_main.joints[0].drive, {
    var: "openness", kind: "number", from: 0, to: 1000,
  });
  const noOpenness = { fortress_gate: { ...DOC, state: { locked: "bool" } } };
  assert.throws(() => resolveModel(LAYOUT, noOpenness), /no float 'openness' to default to/);
});

test("a slider translates along its axis across range_units, scaled from milli", () => {
  // ADR 0023: the lift's rail is a slider driven by `height` (a float, held
  // as milli-units by the kernel) — nothing here is named openness.
  const model = resolveModel(DEPOT_LAYOUT, DEPOT);
  const at = (height) =>
    bindingsFromFrame(frame({ cargo_lift: { height } }), model)
      .find((b) => b.node === "cargo_lift/platform");
  const [minUnits, maxUnits] = LIFT.joints.rail.range_units;
  assert.equal(at(0).translate.units, minUnits);
  assert.ok(Math.abs(at(1000).translate.units - maxUnits) < 1e-12, "fully up reaches the top");
  assert.ok(Math.abs(at(500).translate.units - (minUnits + maxUnits) / 2) < 1e-12, "half way");
  assert.deepEqual(at(500).translate.axis, [0, 1, 0]);
  assert.equal(at(500).rotate, undefined, "a slider never rotates");
  assert.equal(at(-100).translate.units, at(0).translate.units, "clamped below");
  assert.equal(at(5000).translate.units, at(1000).translate.units, "clamped above");
});

test("a bool drive snaps a hinge to the ends of its range", () => {
  const model = resolveModel(DEPOT_LAYOUT, DEPOT);
  const at = (on) =>
    bindingsFromFrame(frame({ signal_lever: { on } }), model)
      .find((b) => b.node === "signal_lever/handle").rotate;
  const [minDeg, maxDeg] = LEVER.joints.pivot.range_degrees;
  assert.ok(Math.abs(at(false).radians - (minDeg * Math.PI) / 180) < 1e-12, "off is the minimum");
  assert.ok(Math.abs(at(true).radians - (maxDeg * Math.PI) / 180) < 1e-12, "on is the maximum");
  assert.deepEqual(at(true).axis, [1, 0, 0], "the pivot axis comes from World IR");
});

test("a drive on an undeclared var, or a bad type, fails loudly", () => {
  const broken = { ...LIFT, joints: { rail: { ...LIFT.joints.rail, drive: { var: "ghost", from: 0, to: 1 } } } };
  assert.throws(() => resolveModel(DEPOT_LAYOUT, { ...DEPOT, cargo_lift: broken }), /undeclared state var/);
  const badType = { ...LIFT, joints: { rail: { ...LIFT.joints.rail, type: "rope" } } };
  assert.throws(() => resolveModel(DEPOT_LAYOUT, { ...DEPOT, cargo_lift: badType }), /unknown type/);
  const noRange = { ...LIFT, joints: { rail: { ...LIFT.joints.rail, range_units: undefined } } };
  assert.throws(() => resolveModel(DEPOT_LAYOUT, { ...DEPOT, cargo_lift: noRange }), /no usable range_units/);
});

if (failures) {
  console.error(`scene binding contract FAILED (${failures})`);
  process.exit(1);
}
console.log("scene binding contract OK (no engine required)");
