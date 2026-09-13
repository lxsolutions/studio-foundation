// The engine-neutral presentation contract (ADR 0020, drives ADR 0023).
//
// The kernel produces snapshots. A renderer must turn them into scene motion
// without inventing anything — and "without inventing anything" has to mean
// something checkable, or it decays into a renderer that quietly makes up the
// parts the contract forgot to specify.
//
// This module is the whole translation, and it holds no engine types: snapshot
// frames plus World IR plus a declared layout in, neutral scene instructions
// out. Every engine adapter is then a dumb applier of those instructions, which
// is what makes "engine-neutral" a property that can be tested rather than a
// claim in a README.
//
// The instruction shape is deliberately narrow — one of two:
//
//   { node: "gate_main/leaf_l", rotate:    { axis: [0,0,1], radians: -1.91 }, hidden: false }
//   { node: "cargo_lift/platform", translate: { axis: [0,1,0], units: 1.8 },  hidden: false }
//
// Axis-angle for a hinge, because it is the one rotation form all of three.js,
// Babylon and PlayCanvas accept without argument about Euler order or
// handedness; a signed distance along the axis for a slider. The axis is READ
// FROM WORLD IR, never chosen here — and so is WHICH STATE VAR moves the joint:
// a joint declares its `drive`, and the binding this replaced hardcoded
// `openness`, which is why a lift and a lever simulated for weeks without a
// renderer able to show them.

/** milli-units are the kernel's fixed-point scale for World IR floats. */
const MILLI = 1000;

/**
 * Resolve each simulated entity to the World IR document describing its parts.
 *
 * This exists because the obvious version is wrong in a way that hides: kernel
 * snapshots are keyed by INSTANCE ("gate_main"), World IR joints are keyed by
 * PART ("leaf_l"), and indexing one with the other silently yields undefined
 * for every entity — no error, no missing frame, just a scene that never moves.
 * The layout is what maps between them, so it is required, not optional.
 */
export function resolveModel(layout, docs) {
  const instances = {};
  for (const [instanceName, placement] of Object.entries(layout.instances ?? {})) {
    const doc = docs[placement.entity];
    if (!doc) {
      throw new Error(
        `layout instance '${instanceName}' names entity '${placement.entity}', ` +
          `which is not among the World IR docs (${Object.keys(docs).join(", ") || "none"})`
      );
    }
    const joints = [];
    for (const [jointName, joint] of Object.entries(doc.joints ?? {})) {
      const where = `${placement.entity}.${jointName}`;
      const part = placement.parts?.[joint.child] ?? {};
      const type = joint.type ?? "hinge";
      if (type !== "hinge" && type !== "slider") {
        throw new Error(`World IR joint ${where} has unknown type '${type}'`);
      }
      joints.push({
        joint: jointName,
        part: joint.child,
        node: `${instanceName}/${joint.child}`,
        type,
        axis: normalizeAxis(joint.axis, where),
        range: normalizeRange(type === "hinge" ? joint.range_degrees : joint.range_units, type, where),
        drive: resolveDrive(doc, joint, where),
        // Which way THIS leaf swings is placement, not simulation and not
        // semantics: a double door mirrors because of how it was hung. Declaring
        // it in the layout keeps the renderer from inventing the sign per frame.
        sign: part.sign ?? 1,
      });
    }
    instances[instanceName] = { entity: placement.entity, offset: placement.offset ?? [0, 0, 0], joints };
  }
  return { instances };
}

function normalizeAxis(axis, where) {
  if (!Array.isArray(axis) || axis.length !== 3 || !axis.every((n) => Number.isFinite(n))) {
    throw new Error(`World IR joint ${where} has no usable axis: ${JSON.stringify(axis)}`);
  }
  const length = Math.hypot(...axis);
  if (length === 0) throw new Error(`World IR joint ${where} has a zero-length axis`);
  return axis.map((n) => n / length);
}

function normalizeRange(range, type, where) {
  const key = type === "hinge" ? "range_degrees" : "range_units";
  if (!Array.isArray(range) || range.length !== 2 || !range.every((n) => Number.isFinite(n))) {
    throw new Error(`World IR ${type} joint ${where} has no usable ${key}: ${JSON.stringify(range)}`);
  }
  return range;
}

/**
 * Which state var moves a joint, in KERNEL units. A World IR float is held by
 * the kernel as integer milli-units, so a drive declared as `from 0 to 1` on a
 * float var spans 0..1000 in the snapshot; an int var is what it says; a bool
 * var has no range — false is the joint's minimum, true its maximum. A joint
 * that declares no drive inherits the door convention (`openness` over the
 * whole travel), and only if the entity actually has a float `openness`.
 */
function resolveDrive(doc, joint, where) {
  const state = doc.state ?? {};
  let drive = joint.drive;
  if (!drive) {
    if (state.openness !== "float") {
      throw new Error(
        `World IR joint ${where} declares no drive and the entity has no float 'openness' to default to`
      );
    }
    drive = { var: "openness", from: 0, to: 1 };
  }
  const kind = state[drive.var];
  if (!kind) throw new Error(`World IR joint ${where} drive reads undeclared state var '${drive.var}'`);
  if (kind === "bool") return { var: drive.var, kind: "bool" };
  if (kind !== "float" && kind !== "int") {
    throw new Error(`World IR joint ${where} drive cannot read ${kind} var '${drive.var}'`);
  }
  const scale = kind === "float" ? MILLI : 1;
  if (!Number.isFinite(drive.from) || !Number.isFinite(drive.to) || drive.from >= drive.to) {
    throw new Error(`World IR joint ${where} drive needs from < to`);
  }
  return { var: drive.var, kind: "number", from: drive.from * scale, to: drive.to * scale };
}

/**
 * One frame of kernel state -> the scene instructions that represent it.
 * Pure: same frame and model in, same instructions out, no engine loaded.
 */
export function bindingsFromFrame(frame, model) {
  const bindings = [];
  for (const [instanceName, entity] of Object.entries(frame.entities)) {
    const instance = model.instances[instanceName];
    if (!instance) continue; // simulated but not placed in this scene
    for (const joint of instance.joints) {
      const fraction = driveFraction(joint.drive, entity);
      const [low, high] = joint.range;
      const amount = (low + fraction * (high - low)) * joint.sign;
      const binding = { node: joint.node, hidden: entity.destroyed === true };
      if (joint.type === "hinge") {
        binding.rotate = { axis: joint.axis, radians: (amount * Math.PI) / 180 };
      } else {
        binding.translate = { axis: joint.axis, units: amount };
      }
      bindings.push(binding);
    }
  }
  return bindings;
}

/** Where the drive var sits in its declared range, clamped to 0..1. */
function driveFraction(drive, entity) {
  const value = entity[drive.var];
  if (drive.kind === "bool") return value === true ? 1 : 0;
  const v = typeof value === "number" ? value : drive.from;
  return clamp((v - drive.from) / (drive.to - drive.from), 0, 1);
}

function clamp(value, low, high) {
  return value < low ? low : value > high ? high : value;
}

/** Every node an adapter must create before the first frame is applied. */
export function nodesInModel(model) {
  const nodes = [];
  for (const [instanceName, instance] of Object.entries(model.instances)) {
    nodes.push({ node: instanceName, parent: null, offset: instance.offset });
    for (const joint of instance.joints) {
      nodes.push({ node: joint.node, parent: instanceName, offset: [0, 0, 0] });
    }
  }
  return nodes;
}
