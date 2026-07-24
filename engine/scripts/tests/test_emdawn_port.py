from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from emdawn_port import EmdawnPortError, prepare_locked_emdawn_port  # noqa: E402


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class LockedEmdawnPortTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = self.root / "engine"
        self.package = self.root / "builtin"
        self.patch = (
            self.engine
            / "toolchain"
            / "patches"
            / "0001-emdawn-private-namespace.patch"
        )
        self.source = self.package / "webgpu" / "src" / "webgpu.cpp"
        self.source.parent.mkdir(parents=True)
        (self.package / "emdawnwebgpu.port.py").write_text(
            "# fixture\n", encoding="utf-8"
        )
        (self.package / "VERSION.txt").write_text(
            "fixture-v1 fixture-revision\n", encoding="utf-8"
        )
        source_bytes = b"class RefCounted {};\n"
        patched_bytes = b"namespace {\nclass RefCounted {};\n}  // namespace\n"
        self.source.write_bytes(source_bytes)
        self.patch.parent.mkdir(parents=True)
        self.patch.write_bytes(
            (
                "diff --git a/webgpu/src/webgpu.cpp b/webgpu/src/webgpu.cpp\n"
                "--- a/webgpu/src/webgpu.cpp\n"
                "+++ b/webgpu/src/webgpu.cpp\n"
                "@@ -1 +1,3 @@\n"
                "+namespace {\n"
                " class RefCounted {};\n"
                "+}  // namespace\n"
            ).encode()
        )
        self.lock = {
            "toolchain": {
                "emdawnwebgpu": {
                    "version": "fixture-v1",
                    "revision": "fixture-revision",
                    "source_sha256": _sha256(source_bytes),
                    "patched_sha256": _sha256(patched_bytes),
                    "patch": "toolchain/patches/0001-emdawn-private-namespace.patch",
                    "patch_sha256": _sha256(self.patch.read_bytes()),
                    "upstream_fix_commit": "fixture-fix",
                }
            }
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def prepare(self) -> Path:
        return prepare_locked_emdawn_port(
            self.lock,
            engine_dir=self.engine,
            cache_dir=self.engine / ".cache",
            emscripten_dir=self.root / "emscripten",
            emcc=self.root / "emcc",
            env={},
            source_package=self.package,
        )

    def test_prepares_and_reuses_exact_locked_port(self) -> None:
        port = self.prepare()
        patched = port.parent / "webgpu" / "src" / "webgpu.cpp"
        self.assertEqual(
            patched.read_text(encoding="utf-8"),
            "namespace {\nclass RefCounted {};\n}  // namespace\n",
        )
        self.assertEqual(self.prepare(), port)

    def test_rejects_changed_builtin_source(self) -> None:
        self.source.write_text("class RefCounted { int changed; };\n", encoding="utf-8")
        with self.assertRaisesRegex(EmdawnPortError, "source checksum mismatch"):
            self.prepare()

    def test_rejects_changed_locked_patch(self) -> None:
        self.patch.write_text(self.patch.read_text() + "# changed\n", encoding="utf-8")
        with self.assertRaisesRegex(EmdawnPortError, "patch checksum mismatch"):
            self.prepare()

    def test_rejects_tampered_prepared_cache(self) -> None:
        port = self.prepare()
        patched = port.parent / "webgpu" / "src" / "webgpu.cpp"
        patched.write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(EmdawnPortError, "does not match"):
            self.prepare()
