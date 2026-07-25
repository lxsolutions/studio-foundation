"""End-to-end character test: blockout -> rig -> skin -> clips -> attach -> export.

Verifies the part most AI-Blender tooling cannot do at all: producing a skinned,
animated character headlessly and getting the skin weights and actions to
survive a glTF round trip.

    python tools/bforge/tests/character.py
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge import Forge  # noqa: E402


def read_glb_json(path: Path) -> dict:
    """Parse a GLB container's JSON chunk — proof the file is really valid."""
    data = path.read_bytes()
    magic, _version, _length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67, f"not a GLB file: magic={magic:#x}"
    chunk_length, chunk_type = struct.unpack_from("<II", data, 12)
    assert chunk_type == 0x4E4F534A, "first GLB chunk is not JSON"
    return json.loads(data[20 : 20 + chunk_length].decode("utf-8"))


def main() -> int:
    forge = Forge(workdir=".", out_dir="assets-generated/bforge")
    failures = []
    try:
        forge.start()
        forge.call("session.reset")

        body = forge.call("char.humanoid", name="knight", height=1.85, build="heroic", seed=3)
        print(
            f"humanoid : {body['triangles']} tris, {body['height_m']} m, "
            f"head unit {body['head_unit_m']} m"
        )

        rig = forge.call("char.rig", name="knight", build="heroic")
        print(
            f"rig      : {rig['bone_count']} bones, roots={rig['root_bones']}, "
            f"{rig['weighted_vertices']} vertices weighted into "
            f"{rig['vertex_groups']} groups"
        )
        if rig["root_bones"] != ["hips"]:
            failures.append(f"expected a single 'hips' root, got {rig['root_bones']}")
        if rig["weighted_vertices"] == 0:
            failures.append("no vertices were weighted — the mesh will not deform")

        clips = {}
        for clip in ("idle", "walk", "run", "attack"):
            result = forge.call("char.animate", rig=rig["armature"], clip=clip, length=24)
            clips[clip] = result
            print(f"clip     : {clip:7} {result['fcurves']:3} curves, {result['keyframes']:3} keys")
            if result["keyframes"] == 0:
                failures.append(f"clip '{clip}' produced no keyframes")

        forge.call("prop.weapon", name="blade", kind="sword", length=1.0, seed=5)
        attach = forge.call(
            "char.attach",
            prop="blade",
            rig=rig["armature"],
            bone="hand_r",
            offset=[0, 0, -0.08],
        )
        print(f"attach   : {attach['prop']} -> {attach['bone']}")

        forge.call("char.pose", rig=rig["armature"], preset="a_pose")
        check = forge.call("check.asset", triangle_budget=8000, material_budget=4)
        print(
            f"validate : {'ok' if check['ok'] else 'FAILED'} "
            f"({check['errors']} errors, {check['warnings']} warnings)"
        )
        for failure in check["failures"]:
            print(f"           [{failure['level']}] {failure['id']}: {failure['msg']}")
        if not check["ok"]:
            failures.append(f"studio validation failed: {check['errors']} errors")

        glb = forge.call("export.gltf", out="character/knight.glb", engine="godot", strict=False)
        print(f"export   : {glb['bytes']} bytes, animations={glb['animations']}")

        path = Path(glb["path"])
        gltf = read_glb_json(path)
        skins = gltf.get("skins", [])
        animations = gltf.get("animations", [])
        nodes = gltf.get("nodes", [])
        print(
            f"glb      : {len(gltf.get('meshes', []))} meshes, {len(skins)} skins, "
            f"{len(animations)} animations, {len(nodes)} nodes"
        )
        print(f"           animation names: {[a.get('name') for a in animations]}")
        joints = skins[0].get("joints", []) if skins else []
        print(f"           skin joints: {len(joints)}")

        if not skins:
            failures.append("GLB has no skin — the character exported unrigged")
        if len(joints) < 15:
            failures.append(f"GLB skin has only {len(joints)} joints, expected the full humanoid")
        if len(animations) < 4:
            failures.append(f"GLB has {len(animations)} animations, expected 4")

        sheet = forge.call(
            "render.contact_sheet",
            out="character/knight_sheet.png",
            tile=320,
            samples=16,
            panels=["hero", "front", "left", "wireframe"],
            columns=4,
            _timeout=900,
        )
        print(f"sheet    : {sheet['rel']}")
    finally:
        forge.stop()

    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\ncharacter pipeline: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
