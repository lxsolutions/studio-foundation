"""Lockfile-driven dependency inventory shared by release tooling."""

from __future__ import annotations

import base64
import json
import re
import subprocess
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from studio_tools import env as senv

NOASSERTION = "NOASSERTION"
PYTHON_LICENSES = {
    "pyyaml": "MIT",
    "ruff": "MIT",
    "scons": "MIT",
    "studio-tools": "MIT",
}
MetadataRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


class InventoryError(RuntimeError):
    """Dependency metadata could not be resolved from the committed inputs."""


def normalize_license_expression(expression: str) -> str:
    """Translate Cargo's legacy alternative-license slash to SPDX OR."""
    return expression.replace("/", " OR ")


@dataclass(frozen=True)
class Component:
    ecosystem: str
    name: str
    version: str
    license: str
    source: str
    checksum: str = ""
    local: bool = False

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.ecosystem.lower(), self.name.lower(), self.version, self.source)

    @property
    def purl(self) -> str:
        purl_type = {
            "Cargo": "cargo",
            "PyPI": "pypi",
            "npm": "npm",
            "Generic": "generic",
        }.get(self.ecosystem, "generic")
        safe = "/" if purl_type == "npm" else ""
        return f"pkg:{purl_type}/{quote(self.name, safe=safe)}@{quote(self.version)}"

    @property
    def spdx_id(self) -> str:
        import hashlib

        digest = hashlib.sha256("|".join(self.key).encode()).hexdigest()[:16]
        label = re.sub(r"[^A-Za-z0-9.-]", "-", self.name).strip("-") or "package"
        return f"SPDXRef-Package-{label[:40]}-{digest}"

    def spdx_checksum(self) -> dict[str, str] | None:
        if not self.checksum or "-" not in self.checksum:
            return None
        algorithm, value = self.checksum.split("-", 1)
        algorithm = algorithm.upper()
        if algorithm not in {"SHA256", "SHA512"}:
            return None
        if not re.fullmatch(r"[0-9a-fA-F]+", value):
            try:
                value = base64.b64decode(value).hex()
            except (ValueError, TypeError):
                return None
        return {"algorithm": algorithm, "checksumValue": value.lower()}


def discover_rust_manifests(root: Path) -> list[Path]:
    candidates = [root / "services" / "Cargo.toml"]
    for parent in (root / "games", root / "templates"):
        if parent.is_dir():
            candidates.extend(sorted(parent.glob("*/server/Cargo.toml")))
    return [path for path in candidates if path.is_file()]


def _cargo_checksums(lock_path: Path) -> dict[tuple[str, str, str], str]:
    if not lock_path.is_file():
        raise InventoryError(f"missing Rust lockfile: {lock_path}")
    with lock_path.open("rb") as handle:
        lock = tomllib.load(handle)
    checksums = {}
    for package in lock.get("package", []):
        source = str(package.get("source", ""))
        checksum = str(package.get("checksum", ""))
        if source and checksum:
            checksums[(str(package["name"]), str(package["version"]), source)] = (
                f"sha256-{checksum}"
            )
    return checksums


def _default_metadata_runner(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return senv.run(command, cwd=cwd, timeout=300)


def cargo_components(root: Path, runner: MetadataRunner | None = None) -> list[Component]:
    runner = runner or _default_metadata_runner
    cargo = senv.find_cargo() or "cargo"
    components: dict[tuple[str, str, str, str], Component] = {}
    for manifest in discover_rust_manifests(root):
        checksums = _cargo_checksums(manifest.parent / "Cargo.lock")
        command = [
            cargo,
            "metadata",
            "--format-version=1",
            "--locked",
            "--manifest-path",
            str(manifest),
        ]
        proc = runner(command, root)
        if proc.returncode != 0:
            detail = ((proc.stdout or "") + (proc.stderr or ""))[-3000:]
            raise InventoryError(f"cargo metadata failed for {manifest}:\n{detail}")
        try:
            metadata = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise InventoryError(f"invalid cargo metadata for {manifest}: {exc}") from exc
        tree_command = [
            cargo,
            "tree",
            "--locked",
            "--manifest-path",
            str(manifest),
            "--edges",
            "all",
            "--target",
            "all",
            "--prefix",
            "none",
            "--format",
            "{p}",
        ]
        tree = runner(tree_command, root)
        if tree.returncode != 0:
            detail = ((tree.stdout or "") + (tree.stderr or ""))[-3000:]
            raise InventoryError(f"cargo tree failed for {manifest}:\n{detail}")
        active_packages = set()
        for line in tree.stdout.splitlines():
            fields = line.removesuffix(" (*)").split()
            if len(fields) >= 2 and fields[1].startswith("v"):
                active_packages.add((fields[0], fields[1][1:]))
        if not active_packages:
            raise InventoryError(f"cargo tree returned no packages for {manifest}")
        for package in metadata.get("packages", []):
            identity = (str(package["name"]), str(package["version"]))
            if identity not in active_packages:
                continue
            source = package.get("source")
            local = source is None
            if local:
                package_manifest = Path(package["manifest_path"]).resolve()
                try:
                    source_label = "path:" + package_manifest.relative_to(root).as_posix()
                except ValueError:
                    source_label = "path:" + package_manifest.as_posix()
            else:
                source_label = str(source)
            license_name = package.get("license")
            if not license_name and package.get("license_file") and local:
                # Local licensing is validated against repository policy
                # separately; NOASSERTION is valid SPDX and avoids inventing an
                # extracted LicenseRef without embedding its full legal text.
                license_name = NOASSERTION
            checksum = checksums.get(
                (str(package["name"]), str(package["version"]), str(source or "")), ""
            )
            component = Component(
                "Cargo",
                str(package["name"]),
                str(package["version"]),
                normalize_license_expression(str(license_name or NOASSERTION)),
                source_label,
                checksum,
                local,
            )
            components[component.key] = component
    return sorted(components.values(), key=lambda item: item.key)


def python_components(root: Path) -> list[Component]:
    lock_path = root / "tools" / "uv.lock"
    if not lock_path.is_file():
        raise InventoryError(f"missing Python lockfile: {lock_path}")
    with lock_path.open("rb") as handle:
        lock = tomllib.load(handle)
    components = []
    for package in lock.get("package", []):
        name = str(package["name"])
        source = package.get("source", {})
        local = isinstance(source, dict) and bool(source.get("editable") or source.get("virtual"))
        source_label = NOASSERTION
        if isinstance(source, dict):
            for field in ("registry", "url", "git", "editable", "virtual"):
                if field in source:
                    source_label = f"{field}:{source[field]}"
                    break
        checksum = ""
        sdist = package.get("sdist")
        if isinstance(sdist, dict):
            checksum = str(sdist.get("hash", ""))
        components.append(
            Component(
                "PyPI",
                name,
                str(package["version"]),
                PYTHON_LICENSES.get(name.lower(), NOASSERTION),
                source_label,
                checksum,
                local,
            )
        )
    return components


def npm_components(root: Path) -> list[Component]:
    lock_path = root / "tests" / "browser" / "package-lock.json"
    if not lock_path.is_file():
        raise InventoryError(f"missing npm lockfile: {lock_path}")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    components = []
    for package_path, package in lock.get("packages", {}).items():
        name = package.get("name")
        if not name and package_path.startswith("node_modules/"):
            name = package_path.removeprefix("node_modules/")
        if not name or not package.get("version"):
            continue
        local = package_path == ""
        components.append(
            Component(
                "npm",
                str(name),
                str(package["version"]),
                str(package.get("license") or (NOASSERTION if not local else "MIT")),
                str(package.get("resolved") or f"path:{lock_path.parent.relative_to(root)}"),
                str(package.get("integrity", "")),
                local,
            )
        )
    return components


def engine_components(root: Path) -> list[Component]:
    lock_path = root / "engine" / "engine-lock.toml"
    if not lock_path.is_file():
        raise InventoryError(f"missing engine lockfile: {lock_path}")
    with lock_path.open("rb") as handle:
        lock = tomllib.load(handle)
    official = lock["godot"]["official"]
    integration = lock["godot"]["webgpu"]
    return [
        Component(
            "Generic",
            "Godot Engine",
            str(official.get("tag") or official["commit"]),
            str(official.get("license") or NOASSERTION),
            str(official.get("repo") or NOASSERTION),
            local=False,
        ),
        Component(
            "Generic",
            "Godot WebGPU source lineage",
            str(integration["source_lineage_commit"]),
            str(integration.get("license") or NOASSERTION),
            str(integration.get("source_lineage_repo") or NOASSERTION),
            local=False,
        ),
    ]


def collect_inventory(
    root: Path | None = None, runner: MetadataRunner | None = None
) -> list[Component]:
    root = (root or senv.repo_root()).resolve()
    components = [
        *cargo_components(root, runner),
        *python_components(root),
        *npm_components(root),
        *engine_components(root),
    ]
    deduplicated: dict[tuple[str, str, str, str], Component] = {}
    for component in components:
        existing = deduplicated.get(component.key)
        if existing is None or (
            existing.license == NOASSERTION and component.license != NOASSERTION
        ):
            deduplicated[component.key] = component
    return sorted(deduplicated.values(), key=lambda item: item.key)
