"""GLB structure, node-contract, and atomic publication tests."""

from __future__ import annotations

import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ASSET_PIPELINE = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


glb_contract = load_module("glb_contract_under_test", ASSET_PIPELINE / "glb_contract.py")
pipeline = load_module("asset_pipeline_contract_test", ASSET_PIPELINE / "pipeline.py")


def make_glb(
    document: dict,
    *,
    magic: bytes = b"glTF",
    version: int = 2,
    chunk_type: bytes = b"JSON",
    declared_length: int | None = None,
) -> bytes:
    json_payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_payload += b" " * (-len(json_payload) % 4)
    total_length = 12 + 8 + len(json_payload)
    header_length = total_length if declared_length is None else declared_length
    return (
        struct.pack("<4sII", magic, version, header_length)
        + struct.pack("<I4s", len(json_payload), chunk_type)
        + json_payload
    )


class GlbStructure(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "asset.glb"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_valid_glb_enforces_exact_case_sensitive_node_names(self) -> None:
        self.path.write_bytes(
            make_glb(
                {
                    "asset": {"version": "2.0"},
                    "nodes": [
                        {"name": "AetherDartHull"},
                        {"name": "FactionArmor"},
                        {"name": "FlightGlow"},
                    ],
                }
            )
        )

        names = glb_contract.validate_glb_contract(
            self.path,
            ("AetherDartHull", "FactionArmor", "FlightGlow"),
        )

        self.assertEqual(names, {"AetherDartHull", "FactionArmor", "FlightGlow"})
        with self.assertRaisesRegex(
            glb_contract.GlbContractError,
            r"missing required node\(s\): factionarmor.*FactionArmor",
        ):
            glb_contract.validate_glb_contract(self.path, ("factionarmor",))

    def test_rejects_invalid_glb_headers_and_json_chunks(self) -> None:
        valid = make_glb({"asset": {"version": "2.0"}, "nodes": []})
        truncated_chunk = bytearray(valid)
        struct.pack_into("<I", truncated_chunk, 12, len(valid))
        invalid_json = (
            struct.pack("<4sII", b"glTF", 2, 24) + struct.pack("<I4s", 4, b"JSON") + b"{bad"
        )
        cases = [
            ("short", b"glTF", "expected at least"),
            ("magic", make_glb({}, magic=b"NOPE"), "invalid GLB magic"),
            ("version", make_glb({}, version=1), "unsupported GLB version"),
            (
                "length",
                make_glb({}, declared_length=999),
                "invalid GLB length",
            ),
            (
                "chunk_type",
                make_glb({}, chunk_type=b"BIN\x00"),
                "expected JSON",
            ),
            ("truncated_chunk", bytes(truncated_chunk), "truncated GLB JSON chunk"),
            ("invalid_json", invalid_json, "invalid GLB JSON chunk"),
        ]

        for name, payload, expected in cases:
            with self.subTest(name=name):
                self.path.write_bytes(payload)
                with self.assertRaisesRegex(glb_contract.GlbContractError, expected):
                    glb_contract.read_glb_json(self.path)


class AtomicPublication(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.blend = self.root / "aether_dart.blend"
        self.output = self.root / "runtime/aether_dart.glb"
        self.output.parent.mkdir(parents=True)
        self.blend.touch()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def fake_export(self, document: dict):
        def run_blender(_blend: Path, _script: str, extra: list[str]) -> dict:
            candidate = Path(extra[0].split("=", 1)[1])
            candidate.write_bytes(make_glb(document))
            return {"ok": True, "bytes": candidate.stat().st_size}

        return run_blender

    def test_failed_node_contract_preserves_output_and_cache(self) -> None:
        original = b"known-good-runtime"
        self.output.write_bytes(original)
        cache = {"unchanged": "digest"}

        with (
            mock.patch.object(pipeline, "load_cache", return_value=cache),
            mock.patch.object(pipeline, "source_hash", return_value="new-digest"),
            mock.patch.object(pipeline, "cmd_validate", return_value=0),
            mock.patch.object(
                pipeline,
                "run_blender",
                side_effect=self.fake_export(
                    {"asset": {"version": "2.0"}, "nodes": [{"name": "WrongNode"}]}
                ),
            ),
            mock.patch.object(pipeline, "save_cache") as save_cache,
        ):
            code, published = pipeline.cmd_export(
                self.blend,
                force=True,
                requested_out=self.output,
                required_nodes=("AetherDartHull",),
            )

        self.assertEqual(code, 1)
        self.assertEqual(published, self.output.resolve())
        self.assertEqual(self.output.read_bytes(), original)
        self.assertEqual(cache, {"unchanged": "digest"})
        self.assertFalse(pipeline.candidate_path_for(self.output).exists())
        save_cache.assert_not_called()

    def test_valid_contract_atomically_publishes_then_updates_cache(self) -> None:
        self.output.write_bytes(b"old-runtime")
        cache = {"unchanged": "digest"}
        document = {
            "asset": {"version": "2.0"},
            "nodes": [{"name": "AetherDartHull"}, {"name": "FactionArmor"}],
        }

        with (
            mock.patch.object(pipeline, "load_cache", return_value=cache),
            mock.patch.object(pipeline, "source_hash", return_value="new-digest"),
            mock.patch.object(pipeline, "cmd_validate", return_value=0),
            mock.patch.object(
                pipeline,
                "run_blender",
                side_effect=self.fake_export(document),
            ),
            mock.patch.object(pipeline, "save_cache") as save_cache,
        ):
            code, published = pipeline.cmd_export(
                self.blend,
                force=True,
                requested_out=self.output,
                required_nodes=("AetherDartHull", "FactionArmor"),
            )

        self.assertEqual(code, 0)
        self.assertEqual(published, self.output.resolve())
        self.assertEqual(
            glb_contract.validate_glb_contract(
                self.output,
                ("AetherDartHull", "FactionArmor"),
            ),
            {"AetherDartHull", "FactionArmor"},
        )
        key = pipeline.cache_key_for(self.output)
        self.assertEqual(cache[key], "new-digest")
        self.assertFalse(pipeline.candidate_path_for(self.output).exists())
        save_cache.assert_called_once_with(cache)


if __name__ == "__main__":
    unittest.main()
