// The engine-neutral presentation contract (ADR 0020).
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
// The instruction shape is deliberately narrow:
//
//   { node: "gate_main/leaf_l", rotate: { axis: [0,0,1], radians: -1.91 }, hidden: false }
//
// Axis-angle, because it is the one rotation form all of three.js, Babylon and
// PlayCanvas accept without argument about Euler order or handedness. The axis
// is READ FROM WORLD IR, never chosen here: the semantic layer already declares
// which way a hinge turns, and a renderer that picks its own axis has silently
// become a second, unverified source of truth.

/** milli-units are the kernel's fixed-point scale for openness (0..1000). */
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
      const part = placement.parts?.[joint.child] ?? {};
      joints.push({
        joint: jointName,
        part: joint.child,
        node: `${instanceName}/${joint.child}`,
        axis: normalizeAxis(joint.axis, `${placement.entity}.${jointName}`),
        rangeDegrees: joint.range_degrees ?? [0, 110],
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
      const [minDeg, maxDeg] = joint.rangeDegrees;
      const openness = clamp(entity.openness ?? 0, 0, MILLI);
      const degrees = minDeg + (openness / MILLI) * (maxDeg - minDeg);
      bindings.push({
        node: joint.node,
        rotate: { axis: joint.axis, radians: (degrees * Math.PI * joint.sign) / 180 },
        hidden: entity.destroyed === true,
      });
    }
  }
  return bindings;
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
