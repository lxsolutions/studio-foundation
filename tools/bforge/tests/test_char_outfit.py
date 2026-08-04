"""Live tests for char.outfit / char.face / char.hands — the anti 'brown blob'
character layer. Verifies fit (shield outside the torso silhouette — the
warden failure), material separation measured through check.materials, rig
following, and byte-level determinism.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge.client import DaemonError, Forge, ForgeError, find_blender  # noqa: E402

FORGE: Forge | None = None
TEMP: tempfile.TemporaryDirectory | None = None


def setUpModule():
    global FORGE, TEMP
    if os.environ.get("BFORGE_SKIP_LIVE"):
        raise unittest.SkipTest("BFORGE_SKIP_LIVE is set")
    try:
        find_blender()
    except DaemonError as exc:
        raise unittest.SkipTest(f"Blender not available: {exc}") from exc
    TEMP = tempfile.TemporaryDirectory(prefix="bforge_outfit_test_")
    FORGE = Forge(workdir=TEMP.name, out_dir=str(Path(TEMP.name) / "out"))
    FORGE.start()


def tearDownModule():
    if FORGE is not None:
        FORGE.stop()
    if TEMP is not None:
        TEMP.cleanup()


class ForgeCase(unittest.TestCase):
    def setUp(self):
        FORGE.call("session.reset")

    @property
    def forge(self) -> Forge:
        return FORGE


def read_glb_json(path: Path) -> dict:
    data = path.read_bytes()
    assert data[:4] == b"glTF", "not a GLB"
    chunk_len, chunk_type = struct.unpack_from("<I4s", data, 12)
    assert chunk_type == b"JSON"
    return json.loads(data[20 : 20 + chunk_len])


def _humanoid(name="warden", height=1.8):
    FORGE.call("char.humanoid", name=name, height=height, build="heroic", seed=3)
    return name


class Outfit(ForgeCase):
    def test_pieces_fit_and_are_named(self):
        body = _humanoid()
        for piece in ("cuirass", "pteruges", "greaves", "bracers", "helmet", "shield"):
            result = FORGE.call("char.outfit", name=body, piece=piece, height=1.8)
            self.assertEqual(result["piece"], piece)
            self.assertTrue(result["object"].startswith(body))
            self.assertLess(result["triangles"], 4000, f"{piece} too heavy")

    def test_shield_does_not_eat_the_character(self):
        """The warden failure: shield centred on the torso, hiding the body."""
        body = _humanoid()
        FORGE.call("char.outfit", name=body, piece="cuirass", height=1.8)
        shield = FORGE.call("char.outfit", name=body, piece="shield", height=1.8)
        info = FORGE.call("object.inspect", name=shield["object"])
        center_x = (info["bounds"]["min"][0] + info["bounds"]["max"][0]) / 2.0
        torso_r = 1.8 * 0.078 * 1.18  # heroic bulk
        self.assertGreater(
            abs(center_x), torso_r,
            f"shield centre |x|={abs(center_x):.3f} is inside the torso silhouette "
            f"(torso_r={torso_r:.3f}) — the warden failure",
        )

    def test_materials_are_separated_by_construction(self):
        body = _humanoid()
        FORGE.call("char.outfit", name=body, piece="cuirass", height=1.8)   # bronze
        FORGE.call("char.outfit", name=body, piece="pteruges", height=1.8)  # leather
        FORGE.call("char.outfit", name=body, piece="helmet", height=1.8)    # bronze
        FORGE.call("char.outfit", name=body, piece="bracers", height=1.8)   # leather
        result = FORGE.call("check.materials")
        errors = [f for f in result["findings"] if f["severity"] == "error"]
        self.assertEqual(errors, [], f"outfit defaults must pass the blob gate: {errors}")
        self.assertGreater(result["max_delta_e"], 12.0)

    def test_pieces_follow_the_rig(self):
        body = _humanoid()
        rig = FORGE.call("char.rig", name=body, height=1.8, build="heroic")
        helmet = FORGE.call("char.outfit", name=body, piece="helmet", height=1.8)
        shield = FORGE.call("char.outfit", name=body, piece="shield", height=1.8)
        self.assertIn("head", helmet["follows"])
        self.assertIn("forearm_l", shield["follows"])
        glb = FORGE.call("export.gltf", out="rigged.glb", objects=[rig["armature"], body,
                                                                   helmet["object"],
                                                                   shield["object"]])
        parsed = read_glb_json(Path(glb["path"]))
        self.assertGreaterEqual(len(parsed.get("skins", [])), 1)
        # Bone-parented pieces export as children of their joint node.
        nodes = parsed["nodes"]
        parent_of = {}
        for index, node in enumerate(nodes):
            for child in node.get("children", []):
                parent_of[child] = index
        for piece_name, bone in ((helmet["object"], "head"),
                                 (shield["object"], "forearm_l")):
            piece_idx = next(i for i, n in enumerate(nodes) if n.get("name") == piece_name)
            self.assertEqual(nodes[parent_of[piece_idx]].get("name"), bone)

    def test_outfit_exports_cleanly(self):
        body = _humanoid()
        FORGE.call("char.outfit", name=body, piece="cuirass", height=1.8)
        FORGE.call("char.outfit", name=body, piece="shield", height=1.8)
        glb = FORGE.call("export.gltf", out="outfit.glb")
        parsed = read_glb_json(Path(glb["path"]))
        self.assertGreaterEqual(len(parsed["meshes"]), 3)


class FaceHands(ForgeCase):
    def test_face_adds_readable_features(self):
        body = _humanoid()
        before = FORGE.call("object.inspect", name=body)["triangles"]
        result = FORGE.call("char.face", name=body, height=1.8)
        self.assertGreater(result["faces_added"], 0)
        after = FORGE.call("object.inspect", name=body)["triangles"]
        self.assertGreater(after, before)
        self.assertLess(after - before, 3000, "face must stay cheap")

    def test_hands_add_fingers(self):
        body = _humanoid()
        result = FORGE.call("char.hands", name=body, height=1.8, curl=0.35)
        self.assertGreater(result["faces_added"], 0)
        FORGE.call("export.gltf", out="hands.glb")  # parses without error

    def test_determinism(self):
        def build_once(out):
            FORGE.call("session.reset")
            body = _humanoid()
            FORGE.call("char.face", name=body, height=1.8)
            FORGE.call("char.hands", name=body, height=1.8)
            FORGE.call("char.outfit", name=body, piece="cuirass", height=1.8)
            FORGE.call("char.outfit", name=body, piece="helmet", height=1.8)
            FORGE.call("char.outfit", name=body, piece="shield", height=1.8)
            return Path(FORGE.call("export.gltf", out=out)["path"]).read_bytes()

        self.assertEqual(build_once("det_a.glb"), build_once("det_b.glb"))


if __name__ == "__main__":
    unittest.main()
