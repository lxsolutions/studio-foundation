from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "pylib"))

from studio_tools import release  # noqa: E402


def load_script(name: str, relative: str):
    path = REPO / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


audit = load_script("studio_release_audit", "tools/release/audit_deps.py")
attribution = load_script("studio_release_attribution", "tools/release/attribution.py")
sbom = load_script("studio_release_sbom", "tools/release/make_sbom.py")
validator = load_script("studio_release_validator", "tools/release/release_validate.py")


class InventoryTests(unittest.TestCase):
    def test_legacy_cargo_license_is_normalized_to_spdx(self) -> None:
        self.assertEqual(
            release.normalize_license_expression("MIT/Apache-2.0"),
            "MIT OR Apache-2.0",
        )

    def test_cargo_metadata_and_lock_checksum_are_combined(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            services = root / "services"
            services.mkdir()
            manifest = services / "Cargo.toml"
            manifest.write_text("[workspace]\n", encoding="utf-8")
            checksum = "ab" * 32
            (services / "Cargo.lock").write_text(
                "\n".join(
                    [
                        "version = 4",
                        "",
                        "[[package]]",
                        'name = "serde"',
                        'version = "1.0.0"',
                        'source = "registry+https://github.com/rust-lang/crates.io-index"',
                        f'checksum = "{checksum}"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            metadata = {
                "packages": [
                    {
                        "id": "registry-serde",
                        "name": "serde",
                        "version": "1.0.0",
                        "license": "MIT OR Apache-2.0",
                        "license_file": None,
                        "source": "registry+https://github.com/rust-lang/crates.io-index",
                        "manifest_path": str(services / "serde" / "Cargo.toml"),
                    },
                    {
                        "id": "local-studio",
                        "name": "studio-local",
                        "version": "0.1.0",
                        "license": "MIT",
                        "license_file": None,
                        "source": None,
                        "manifest_path": str(services / "local" / "Cargo.toml"),
                    },
                    {
                        "id": "unused-rsa",
                        "name": "rsa",
                        "version": "0.9.10",
                        "license": "MIT OR Apache-2.0",
                        "license_file": None,
                        "source": "registry+https://github.com/rust-lang/crates.io-index",
                        "manifest_path": str(services / "rsa" / "Cargo.toml"),
                    },
                ],
            }

            def runner(command: list[str], cwd: Path):
                self.assertIn("--locked", command)
                self.assertEqual(cwd, root)
                if command[1] == "metadata":
                    return subprocess.CompletedProcess(command, 0, json.dumps(metadata), "")
                self.assertEqual(command[1], "tree")
                self.assertIn("--target", command)
                return subprocess.CompletedProcess(
                    command,
                    0,
                    "studio-local v0.1.0 (local)\nserde v1.0.0\n",
                    "",
                )

            components = release.cargo_components(root, runner)
            dependency = next(component for component in components if component.name == "serde")
            local = next(component for component in components if component.name == "studio-local")
            self.assertEqual(dependency.checksum, "sha256-" + checksum)
            self.assertEqual(dependency.purl, "pkg:cargo/serde@1.0.0")
            self.assertFalse(dependency.local)
            self.assertTrue(local.local)
            self.assertNotIn("rsa", {component.name for component in components})

    def test_spdx_checksum_decodes_npm_integrity(self) -> None:
        component = release.Component(
            "npm", "example", "1.0.0", "MIT", "registry", "sha512-YWJj", False
        )
        self.assertEqual(
            component.spdx_checksum(),
            {"algorithm": "SHA512", "checksumValue": "616263"},
        )


class OutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.components = [
            release.Component("Cargo", "serde", "1.0.0", "MIT", "registry", local=False),
            release.Component("PyPI", "studio-tools", "0.1.0", "MIT", "path", local=True),
        ]

    def test_sbom_has_spdx_packages_and_purls(self) -> None:
        document = sbom.build_spdx(self.components)
        self.assertEqual(document["spdxVersion"], "SPDX-2.3")
        self.assertEqual(len(document["packages"]), 2)
        self.assertEqual(
            document["packages"][0]["externalRefs"][0]["referenceLocator"],
            "pkg:cargo/serde@1.0.0",
        )

    def test_attribution_excludes_local_packages_and_requires_license(self) -> None:
        rendered = attribution.render_attribution(self.components)
        self.assertIn("serde", rendered)
        self.assertNotIn("studio-tools", rendered)
        with self.assertRaisesRegex(release.InventoryError, "missing declared license"):
            attribution.render_attribution(
                [release.Component("Cargo", "unknown", "1", release.NOASSERTION, "registry")]
            )

    def test_generated_output_cannot_escape_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(ValueError, "inside the repository"):
                sbom.output_path(root, "../outside.json")
            with self.assertRaisesRegex(ValueError, "inside the repository"):
                attribution.output_path(root, "../outside.md")


class AuditTests(unittest.TestCase):
    def test_osv_batch_and_pagination_are_merged(self) -> None:
        dependency = release.Component("Cargo", "serde", "1.0.0", "MIT", "registry")
        local = release.Component("Cargo", "local", "0.1.0", "MIT", "path", local=True)
        calls = []

        def requester(url: str, payload: dict[str, object], timeout: int):
            calls.append((url, payload, timeout))
            if url == audit.OSV_BATCH_ENDPOINT:
                return {
                    "results": [
                        {
                            "vulns": [{"id": "RUSTSEC-1"}],
                            "next_page_token": "next",
                        }
                    ]
                }
            return {"vulns": [{"id": "GHSA-2"}]}

        findings = audit.query_osv([dependency, local], requester=requester, timeout=9)
        self.assertEqual(findings[dependency], ["GHSA-2", "RUSTSEC-1"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1]["queries"][0]["package"]["ecosystem"], "crates.io")
        self.assertEqual(calls[1][1]["page_token"], "next")

    def test_mismatched_osv_response_fails_closed(self) -> None:
        dependency = release.Component("PyPI", "pyyaml", "1", "MIT", "registry")
        with self.assertRaisesRegex(audit.AuditError, "package count"):
            audit.query_osv([dependency], requester=lambda *_: {"results": []})

    def test_repeated_osv_page_token_fails_closed(self) -> None:
        dependency = release.Component("npm", "example", "1", "MIT", "registry")

        def requester(url: str, _payload: dict[str, object], _timeout: int):
            if url == audit.OSV_BATCH_ENDPOINT:
                return {"results": [{"next_page_token": "repeat"}]}
            return {"next_page_token": "repeat"}

        with self.assertRaisesRegex(audit.AuditError, "repeated a page token"):
            audit.query_osv([dependency], requester=requester)


class ValidationTests(unittest.TestCase):
    def test_engine_lock_and_patch_checksums_validate(self) -> None:
        self.assertEqual(validator.validate_engine_lock(REPO), [])

    def test_engine_inventory_retains_source_lineage_without_lx_fork(self) -> None:
        components = release.engine_components(REPO)
        by_name = {component.name: component for component in components}
        self.assertEqual(
            by_name["Godot WebGPU source lineage"].source,
            "https://github.com/dwalter/godotwebgpu",
        )
        self.assertNotIn(
            "lxsolutions/godot-webgpu",
            {component.source for component in components},
        )

    def test_license_expression_parser_and_policy(self) -> None:
        self.assertEqual(
            validator.license_ids("(MIT OR Apache-2.0) AND Unicode-3.0"),
            {"MIT", "Apache-2.0", "Unicode-3.0"},
        )
        self.assertFalse(
            validator.license_ids("MIT OR Apache-2.0") - validator.APPROVED_LICENSE_IDS
        )
        self.assertTrue(
            validator.license_expression_is_approved("MIT OR Apache-2.0 OR LGPL-2.1-or-later")
        )
        self.assertFalse(validator.license_expression_is_approved("MIT AND LGPL-2.1-or-later"))
        self.assertTrue(validator.license_expression_is_approved("MIT/Apache-2.0"))

    def test_proprietary_game_manifest_must_be_non_publishable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            server = root / "games" / "sample" / "server"
            server.mkdir(parents=True)
            (root / "games" / "LICENSE").write_text("proprietary", encoding="utf-8")
            manifest = server / "Cargo.toml"
            manifest.write_text(
                '[package]\nname = "sample"\nlicense-file = "../../LICENSE"\npublish = false\n',
                encoding="utf-8",
            )
            self.assertEqual(validator.validate_game_manifests(root), [])
            manifest.write_text(
                '[package]\nname = "sample"\nlicense = "MIT"\n',
                encoding="utf-8",
            )
            problems = validator.validate_game_manifests(root)
            self.assertEqual(len(problems), 2)


if __name__ == "__main__":
    unittest.main()
