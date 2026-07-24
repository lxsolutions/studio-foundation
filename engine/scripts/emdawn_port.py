"""Prepare Studio Foundation's checksum-locked Emdawn WebGPU port.

The pinned Emscripten port predates Dawn's isolation of private implementation
types. Godot and that port both define a global C++ ``RefCounted`` class, which
allows the linker to select Godot's larger constructor for Emdawn objects.
This module copies the built-in port into the repository cache, verifies its
exact source bytes, applies the locked upstream backport, and returns a local
``--use-port`` path without mutating the Emscripten installation.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


class EmdawnPortError(RuntimeError):
    """The locked Emdawn port could not be prepared safely."""


def sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _locked_spec(lock: dict, engine_dir: Path) -> dict[str, str]:
    try:
        raw = lock["toolchain"]["emdawnwebgpu"]
        spec = {
            key: str(raw[key])
            for key in (
                "version",
                "revision",
                "source_sha256",
                "patched_sha256",
                "patch",
                "patch_sha256",
                "upstream_fix_commit",
            )
        }
    except (KeyError, TypeError) as exc:
        raise EmdawnPortError(
            "engine-lock.toml is missing the locked Emdawn port metadata"
        ) from exc

    patch_root = (engine_dir / "toolchain" / "patches").resolve()
    patch_path = (engine_dir / spec["patch"]).resolve()
    if not patch_path.is_relative_to(patch_root):
        raise EmdawnPortError(
            f"Emdawn patch escapes engine/toolchain/patches: {spec['patch']}"
        )
    if not patch_path.is_file():
        raise EmdawnPortError(f"locked Emdawn patch is missing: {spec['patch']}")
    actual_patch_sha = sha256_file(patch_path)
    if actual_patch_sha != spec["patch_sha256"]:
        raise EmdawnPortError(
            "Emdawn patch checksum mismatch: "
            f"expected {spec['patch_sha256']}, got {actual_patch_sha}"
        )
    spec["patch_path"] = str(patch_path)
    return spec


def _builtin_package_path(emscripten_dir: Path, env: dict[str, str]) -> Path:
    cache_root = Path(env.get("EM_CACHE", str(emscripten_dir / "cache")))
    return cache_root / "ports" / "emdawnwebgpu" / "emdawnwebgpu_pkg"


def _materialize_builtin_package(
    *,
    package: Path,
    emcc: Path,
    env: dict[str, str],
    cache_dir: Path,
) -> None:
    if package.is_dir():
        return
    probe_dir = cache_dir / "toolchains" / "probes"
    probe_dir.mkdir(parents=True, exist_ok=True)
    source = probe_dir / "emdawn_probe.cpp"
    output = probe_dir / "emdawn_probe.o"
    source.write_text(
        "#include <webgpu/webgpu.h>\nint main() { return 0; }\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            str(emcc),
            str(source),
            "--use-port=emdawnwebgpu",
            "-std=c++20",
            "-c",
            "-o",
            str(output),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise EmdawnPortError(
            f"Emscripten could not materialize its Emdawn port: {detail}"
        )
    if not package.is_dir():
        raise EmdawnPortError(
            f"Emscripten completed but its Emdawn package is absent: {package}"
        )


def _expected_state(spec: dict[str, str]) -> dict[str, str]:
    return {
        key: spec[key]
        for key in (
            "version",
            "revision",
            "source_sha256",
            "patched_sha256",
            "patch",
            "patch_sha256",
            "upstream_fix_commit",
        )
    }


def _verify_preimage(package: Path, spec: dict[str, str]) -> Path:
    version_file = package / "VERSION.txt"
    source_file = package / "webgpu" / "src" / "webgpu.cpp"
    port_file = package / "emdawnwebgpu.port.py"
    if (
        not version_file.is_file()
        or not source_file.is_file()
        or not port_file.is_file()
    ):
        raise EmdawnPortError(f"incomplete Emdawn package: {package}")
    version_text = version_file.read_text(encoding="utf-8")
    if spec["version"] not in version_text or spec["revision"] not in version_text:
        raise EmdawnPortError(
            "Emscripten Emdawn version does not match engine-lock.toml"
        )
    actual = sha256_file(source_file)
    if actual != spec["source_sha256"]:
        raise EmdawnPortError(
            "Emscripten Emdawn source checksum mismatch: "
            f"expected {spec['source_sha256']}, got {actual}"
        )
    return source_file


def prepare_locked_emdawn_port(
    lock: dict,
    *,
    engine_dir: Path,
    cache_dir: Path,
    emscripten_dir: Path,
    emcc: Path,
    env: dict[str, str] | None = None,
    source_package: Path | None = None,
) -> Path:
    """Return a verified local ``emdawnwebgpu.port.py`` for the engine build."""

    spec = _locked_spec(lock, engine_dir)
    build_env = dict(os.environ if env is None else env)
    package = source_package or _builtin_package_path(emscripten_dir, build_env)
    if source_package is None:
        _materialize_builtin_package(
            package=package,
            emcc=emcc,
            env=build_env,
            cache_dir=cache_dir,
        )
    _verify_preimage(package, spec)

    destination = cache_dir / "toolchains" / "emdawnwebgpu"
    state_file = destination / ".studio-foundation-port-state.json"
    patched_source = destination / "webgpu" / "src" / "webgpu.cpp"
    expected_state = _expected_state(spec)
    if destination.exists():
        try:
            current_state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EmdawnPortError(
                f"invalid locked Emdawn state in {destination}"
            ) from exc
        if (
            current_state == expected_state
            and patched_source.is_file()
            and sha256_file(patched_source) == spec["patched_sha256"]
        ):
            return destination / "emdawnwebgpu.port.py"
        raise EmdawnPortError(
            f"{destination} does not match engine-lock.toml; "
            "move this disposable cache aside and rebuild"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(package, destination)
    patch_path = Path(spec["patch_path"])
    apply_env = os.environ.copy()
    # This destination lives below the Studio Foundation worktree, but it is a
    # standalone third-party package. Prevent Git from discovering the parent
    # repository and force byte-stable LF handling on Windows.
    apply_env["GIT_CEILING_DIRECTORIES"] = str(destination.parent.resolve())
    for check_args in (
        ["git", "-c", "core.autocrlf=false", "apply", "--check", str(patch_path)],
        ["git", "-c", "core.autocrlf=false", "apply", str(patch_path)],
    ):
        proc = subprocess.run(
            check_args,
            cwd=destination,
            env=apply_env,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()
            shutil.rmtree(destination)
            raise EmdawnPortError(f"failed to apply locked Emdawn patch: {detail}")
    actual_patched = sha256_file(patched_source)
    if actual_patched != spec["patched_sha256"]:
        shutil.rmtree(destination)
        raise EmdawnPortError(
            "patched Emdawn checksum mismatch: "
            f"expected {spec['patched_sha256']}, got {actual_patched}"
        )
    state_file.write_text(
        json.dumps(expected_state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination / "emdawnwebgpu.port.py"
