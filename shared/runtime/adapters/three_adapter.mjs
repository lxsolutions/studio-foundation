// three.js binding for the neutral scene contract (ADR 0020).
// Right-handed, Y-up, radians — the glTF conventions the contract declares.
// The engine module is passed in rather than imported: `shared/` carries no npm
// dependencies (GOAL principle 5), and a consuming game already has its engine
// loaded — importing a second copy here would be a second copy at runtime.
export function createThreeAdapter(THREE) {
  const nodes = new Map();
  const root = new THREE.Object3D();
  return {
    name: "three.js",
    build(list) {
      for (const spec of list) {
        const object = new THREE.Object3D();
        object.position.set(...spec.offset);
        (spec.parent ? nodes.get(spec.parent) : root).add(object);
        nodes.set(spec.node, object);
      }
    },
    apply(bindings) {
      for (const binding of bindings) {
        const object = nodes.get(binding.node);
        if (!object) continue;
        object.quaternion.setFromAxisAngle(
          new THREE.Vector3(...binding.rotate.axis),
          binding.rotate.radians
        );
        object.visible = !binding.hidden;
      }
      root.updateMatrixWorld(true);
    },
    probe(node, point) {
      const v = new THREE.Vector3(...point).applyMatrix4(nodes.get(node).matrixWorld);
      return [v.x, v.y, v.z];
    },
    visible: (node) => nodes.get(node).visible,
    node: (name) => nodes.get(name),
  };
}
