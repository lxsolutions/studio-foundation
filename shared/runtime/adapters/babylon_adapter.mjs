// Babylon.js binding for the neutral scene contract (ADR 0020).
//
// Two Babylon-specific facts are handled here so no caller has to know them:
//   * The `babylonjs` UMD package puts every symbol on the ESM default export,
//     so a named import of `NullEngine` silently yields undefined.
//   * NullEngine is the headless device; scene graph maths needs no GPU, so the
//     conformance suite runs this adapter on a machine with no display at all.
// The engine module is passed in rather than imported: `shared/` carries no npm
// dependencies (GOAL principle 5), and a consuming game already has its engine
// loaded — importing a second copy here would be a second copy at runtime.
export function createBabylonAdapter(BABYLON, options = {}) {
  // A caller with a real scene (the sim-viewer) passes it in and parents its
  // GLB meshes to the nodes this builds; with no scene, NullEngine gives the
  // conformance suite the same code path with no GPU.
  const scene = options.scene ?? new BABYLON.Scene(new BABYLON.NullEngine());
  const nodes = new Map();
  return {
    name: "babylon.js",
    build(list) {
      for (const spec of list) {
        const node = new BABYLON.TransformNode(spec.node, scene);
        node.position = new BABYLON.Vector3(...spec.offset);
        if (spec.parent) node.parent = nodes.get(spec.parent);
        nodes.set(spec.node, node);
      }
    },
    apply(bindings) {
      for (const binding of bindings) {
        const node = nodes.get(binding.node);
        if (!node) continue;
        node.rotationQuaternion = BABYLON.Quaternion.RotationAxis(
          new BABYLON.Vector3(...binding.rotate.axis),
          binding.rotate.radians
        );
        node.setEnabled(!binding.hidden);
      }
      for (const node of nodes.values()) node.computeWorldMatrix(true);
    },
    probe(node, point) {
      const v = BABYLON.Vector3.TransformCoordinates(
        new BABYLON.Vector3(...point),
        nodes.get(node).getWorldMatrix()
      );
      return [v.x, v.y, v.z];
    },
    visible: (node) => nodes.get(node).isEnabled(false),
    node: (name) => nodes.get(name),
  };
}
