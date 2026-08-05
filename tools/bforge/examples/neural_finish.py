"""The neural finishing line: external mesh -> game-ready, rigged, animated.

Takes the dense, unrigged triangle soup an image-to-3D generator (TRELLIS,
Hunyuan3D, a scan, a download) emits and runs it through the enforced loop:
voxel retopo -> fresh UVs -> transfer-baked textures -> auto-fit skeleton ->
synthesized clips -> quality gate -> gated export with a review sheet.
The generator can change next month; the finishing line is generator-agnostic.

    uv run --project tools python tools/bforge/examples/neural_finish.py INPUT.glb OUT_DIR [plan] [voxel_mm]

plan: canine | feline | equine | generic | insect | humanoid (default canine;
humanoid uses char.rig, the rest char.creature_rig). voxel_mm defaults to 20.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge import Forge  # noqa: E402


def main() -> None:
    source = Path(sys.argv[1]).resolve()
    out_dir = Path(sys.argv[2] if len(sys.argv) > 2 else "neural_finish")
    plan = sys.argv[3] if len(sys.argv) > 3 else "canine"
    voxel = (float(sys.argv[4]) if len(sys.argv) > 4 else 20.0) / 1000.0
    out_dir.mkdir(parents=True, exist_ok=True)
    asset_id = source.stem + "_game"

    with Forge() as forge:
        forge.call("session.reset")
        imp = forge.call("session.import", path=str(source), prefix="src")
        imported = imp.get("objects") or []
        meshes = [n for n in imported
                  if not n.lower().endswith(("_rig", "_armature")) and "rig" not in n.lower()]
        if not meshes:
            raise SystemExit(f"no mesh found in {source.name}: {imported}")
        src = meshes[0]
        if len(meshes) > 1:
            forge.call("object.join", names=meshes, into=src)

        forge.call("object.duplicate", name=src, new_name=asset_id)
        retopo = forge.call("mesh.retopo", name=asset_id, voxel_size=voxel)
        print(f"retopo: {retopo['triangles_before']} -> {retopo['triangles_after']} tris")

        forge.call("uv.unwrap", object=asset_id, style="smart_packed")
        forge.call("uv.pack", object=asset_id, margin=0.01)
        forge.call("bake.transfer", source=src, target=asset_id,
                   maps=["base_color", "normal"], size=1024, samples=16,
                   ray_distance=voxel * 4)

        if plan == "humanoid":
            rig = forge.call("char.rig", name=asset_id, height=0, build="realistic")
            clips = ("idle", "walk", "attack", "death")
        else:
            rig = forge.call("char.creature_rig", name=asset_id, plan=plan,
                             length=0, shoulder=0)
            clips = ("idle", "walk", "trot") if plan != "insect" else ("idle", "walk")
        print(f"rig: {rig['armature']} ({rig['bone_count']} bones, "
              f"{rig['weighted_vertices']} weighted verts)")
        for clip in clips:
            forge.call("char.animate", rig=rig["armature"], clip=clip, length=24)

        objects = [asset_id, rig["armature"]]
        review = forge.call("gameready.review", objects=objects)
        if not review["passed"]:
            raise SystemExit(f"{asset_id} failed the gate: {review['findings']}")
        result = forge.call("export.asset", asset_id=asset_id, out_dir=str(out_dir),
                            objects=objects, engine="threejs", category="character",
                            ai_prompt=f"neural-mesh finishing line: {source.name} -> game-ready")
        print(f"{asset_id}: {result['triangles']} tris, {result['bytes'] // 1024} KiB "
              f"-> {out_dir}")


if __name__ == "__main__":
    main()
