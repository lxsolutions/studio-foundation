// PlayCanvas binding for the neutral scene contract (ADR 0020).
//
// PlayCanvas needs no Application and no graphics device for this: `GraphNode`
// is a standalone scene-graph type, so the conformance suite runs it headless.
// The trap it does have is units — `Quat.setFromAxisAngle` takes DEGREES while
// three.js and Babylon take radians, which is exactly the kind of difference
// that looks fine until a door opens 57 times too far.
// The engine module is passed in rather than imported: `shared/` carries no npm
// dependencies (GOAL principle 5), and a consuming game already has its engine
// loaded — importing a second copy here would be a second copy at runtime.
export function createPlayCanvasAdapter(pc) {
  const nodes = new Map();
  const root = new pc.GraphNode("root");
  return {
    name: "playcanvas",
    build(list) {
      for (const spec of list) {
        const node = new pc.GraphNode(spec.node);
        node.setLocalPosition(...spec.offset);
        (spec.parent ? nodes.get(spec.parent) : root).addChild(node);
        nodes.set(spec.node, node);
      }
    },
    apply(bindings) {
      for (const binding of bindings) {
        const node = nodes.get(binding.node);
        if (!node) continue;
        const quaternion = new pc.Quat().setFromAxisAngle(
          new pc.Vec3(...binding.rotate.axis),
          (binding.rotate.radians * 180) / Math.PI
        );
        node.setLocalRotation(quaternion);
        node.enabled = !binding.hidden;
      }
    },
    probe(node, point) {
      const v = new pc.Vec3(...point);
      nodes.get(node).getWorldTransform().transformPoint(v, v);
      return [v.x, v.y, v.z];
    },
    // `enabled` (the public getter) resolves through the hierarchy, and that
    // propagation is maintained by an Application — on a detached GraphNode it
    // answers false no matter what was set. `_enabled` is the local flag the
    // public setter above actually writes, so it is the engine's own state and
    // the only comparable answer available without booting an Application.
    visible: (node) => nodes.get(node)._enabled,
    node: (name) => nodes.get(name),
  };
}
