"""Asset Recipe IR v1 — declarative, content-hashed, proof-carrying builds.

ADR 0018: an asset is declared, not performed. A recipe names its inputs,
its op steps, and its requirements; the compiler canonicalizes and hashes
them, consults a content-addressed cache, and only then pays for a Blender
worker. Whatever happens, the run writes a proof capsule — recipe hash, tool
identities, gate results, artifact hashes — so an asset is accepted because
it carries evidence, not because an agent says it is finished.

A cache hit returns the verified proof without constructing a Forge at all,
so proof retrieval works on machines with no Blender installed. The cache key
fingerprints the COMPILER, not just the recipe: the bforge source tree (so a
dirty working tree is a different compiler), the committed catalog, the pinned
Blender toolchain, and the canonicalization version. A hit is re-verified —
every artifact is re-hashed against the proof before it is returned.

Recipes are JSON because the tooling is deliberately stdlib-only (ADR 0013).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import secrets
import shutil
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path

RECIPE_VERSION = 1
PROOF_VERSION = 1
CANONICALIZATION = "bforge-json-c14n-v1"
CACHE_SCHEMA = "bforge.recipe.v1"

BFORGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = BFORGE_ROOT / "cache"

_META_FILES = ("proof.json", "recipe.canonical.json")


class RecipeError(Exception):
    """A recipe is malformed, an input does not match its declared hash, or a
    requirement/gate failed."""


def _strict_loads(text: str, source: str):
    """JSON with no NaN/Infinity — non-finite floats are not valid JSON and
    must never silently enter a proof or a recipe."""

    def reject(value):
        raise RecipeError(f"{source}: non-finite constant {value!r} is not valid JSON")

    try:
        return json.loads(text, parse_constant=reject)
    except json.JSONDecodeError as exc:
        raise RecipeError(f"{source}: not valid JSON: {exc}") from exc


def load_recipe(path: Path) -> dict:
    recipe = _strict_loads(Path(path).read_text(encoding="utf-8"), str(path))
    if not isinstance(recipe, dict):
        raise RecipeError(f"{path}: a recipe is a JSON object")
    version = recipe.get("recipe_version")
    if version != RECIPE_VERSION:
        raise RecipeError(f"{path}: unsupported recipe_version {version!r} (want {RECIPE_VERSION})")
    asset_id = recipe.get("asset_id")
    if not asset_id or not isinstance(asset_id, str):
        raise RecipeError(f"{path}: asset_id is required")
    steps = recipe.get("steps")
    if not isinstance(steps, list) or not steps:
        raise RecipeError(f"{path}: steps must be a non-empty list")
    for i, step in enumerate(steps):
        if not isinstance(step, dict) or not isinstance(step.get("op"), str):
            raise RecipeError(f"{path}: step {i} needs an op name")
        if not isinstance(step.get("args", {}), dict):
            raise RecipeError(f"{path}: step {i} args must be an object")
    for key in ("inputs", "requirements", "export"):
        if key in recipe and not isinstance(recipe[key], dict):
            raise RecipeError(f"{path}: {key} must be an object")
    return recipe


def canonicalize(recipe: dict) -> bytes:
    """Byte-stable form: the same recipe always hashes the same, regardless of
    key order or whitespace in the source file."""
    return json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_inputs(recipe: dict, base_dir: Path) -> dict[str, str]:
    """Hash every declared input file. A declared sha256 is verified — recipes
    treat their inputs as untrusted, so a silent substitution is a hard error."""
    hashes: dict[str, str] = {}
    for name, spec in sorted(recipe.get("inputs", {}).items()):
        if not isinstance(spec, dict) or not spec.get("path"):
            raise RecipeError(f"input {name!r} needs a path")
        path = (base_dir / spec["path"]).resolve()
        if not path.is_file():
            raise RecipeError(f"input {name!r}: no such file: {path}")
        actual = _sha256_file(path)
        declared = spec.get("sha256")
        if declared and declared != actual:
            raise RecipeError(
                f"input {name!r} hash mismatch: declared {declared}, actual {actual} "
                "— the input changed; update the recipe deliberately"
            )
        hashes[name] = actual
    return hashes


def content_hash(recipe: dict, input_hashes: dict[str, str]) -> str:
    """One hash covering the recipe document and the real bytes of its inputs."""
    digest = hashlib.sha256()
    digest.update(canonicalize(recipe))
    for name, value in sorted(input_hashes.items()):
        digest.update(f"{name}={value}\n".encode())
    return digest.hexdigest()


def compiler_fingerprint() -> dict:
    """Fingerprint the COMPILER, so a cache entry is only reused by the same
    implementation that produced it.

    The tree hash covers every bforge client/runtime Python source — including
    uncommitted edits, because a dirty working tree IS a different compiler.
    A git commit alone could not say that. The pinned Blender identity comes
    from blender-lock.toml (the archive hash CI verifies), and the catalog
    hash pins the published op surface.
    """
    tree = hashlib.sha256()
    sources = sorted(BFORGE_ROOT.glob("bforge/*.py")) + sorted(BFORGE_ROOT.glob("runtime/**/*.py"))
    for path in sources:
        if "__pycache__" in path.parts:
            continue
        tree.update(path.relative_to(BFORGE_ROOT).as_posix().encode())
        tree.update(_sha256_file(path).encode())
    blender: dict = {}
    lock_path = BFORGE_ROOT / "blender-lock.toml"
    if lock_path.is_file():
        lock = tomllib.loads(lock_path.read_text(encoding="utf-8")).get("blender", {})
        blender = {"version": lock.get("version"), "archive_sha256": lock.get("sha256")}
    catalog_path = BFORGE_ROOT / "catalog.json"
    return {
        "bforge_tree_sha256": tree.hexdigest(),
        "catalog_sha256": _sha256_file(catalog_path) if catalog_path.is_file() else None,
        "blender": blender,
        "python": platform.python_version(),
    }


def cache_key(
    recipe: dict, input_hashes: dict[str, str], fingerprint: dict | None = None
) -> tuple[str, dict]:
    """The content address: recipe + inputs + compiler, canonicalized."""
    envelope = {
        "schema": CACHE_SCHEMA,
        "canonicalization": CANONICALIZATION,
        "recipe_sha256": content_hash(recipe, input_hashes),
        "inputs": input_hashes,
        "compiler": fingerprint if fingerprint is not None else compiler_fingerprint(),
    }
    return hashlib.sha256(canonicalize(envelope)).hexdigest(), envelope


def _verify_cached_artifacts(proof: dict, out_dir: Path) -> bool:
    """Artifact-level integrity: every recorded artifact exists, hashes match,
    and the directory contains exactly the recorded set (no stale passengers)."""
    artifacts = proof.get("artifacts", [])
    if not artifacts:
        return False
    recorded: set[str] = set()
    for artifact in artifacts:
        rel = artifact.get("path", "")
        # normalized, contained relative paths only
        if not rel or rel.startswith("/") or rel.startswith("../") or "/../" in rel or "\\" in rel:
            return False
        recorded.add(rel)
        path = out_dir / rel
        if not path.is_file() or _sha256_file(path) != artifact.get("sha256"):
            return False
    on_disk = {
        p.relative_to(out_dir).as_posix()
        for p in out_dir.rglob("*")
        if p.is_file() and p.name not in _META_FILES
    }
    return recorded == on_disk


def verify_entry(proof: dict, out_dir: Path, expected: dict) -> bool:
    """Full identity check for a cache entry: the proof must BE the answer to
    THIS request, not merely a pass-stamped file with intact artifacts.

    Checking only the artifacts named by a proof lets edited metadata (a
    tampered toolchain or gate verdict) ride along — that is a chain of hashes
    attached to an unverified claim, not a cryptographic chain.
    """
    if proof.get("proof_version") != PROOF_VERSION or proof.get("status") != "pass":
        return False
    for field in ("asset_id", "recipe_hash", "cache_key", "inputs"):
        if proof.get(field) != expected[field]:
            return False
    if proof.get("cache", {}).get("envelope") != expected["envelope"]:
        return False
    canonical = out_dir / "recipe.canonical.json"
    if not canonical.is_file() or canonical.read_bytes() != expected["canonical"]:
        return False
    # the toolchain record must match the pinned identity it claims
    pinned = expected.get("pinned")
    if pinned and proof.get("cache", {}).get("cacheable") is not False:
        reported = proof.get("toolchain", {}).get("blender", "")
        if not reported.startswith(pinned):
            return False
    # the recorded gates must be exactly the ones the requirements demand,
    # with passing verdicts — a flipped or dropped verdict invalidates the entry
    requirements = expected.get("requirements", {})
    gates = proof.get("gates", {})
    needs_check = any(
        k in requirements
        for k in ("max_triangles", "max_materials", "require_collision", "require_lods")
    )
    if needs_check and gates.get("check.asset", {}).get("ok") is not True:
        return False
    if not needs_check and "check.asset" in gates:
        return False
    if (
        "platform" in requirements
        and gates.get("gameready.budget", {}).get("within_budget") is not True
    ):
        return False
    if "platform" not in requirements and "gameready.budget" in gates:
        return False
    return _verify_cached_artifacts(proof, out_dir)


class _KeyLock:
    """A per-content-address mkdir lock: one builder per key. Others wait, then
    re-verify — the winner's entry may already satisfy them."""

    def __init__(self, cache_root: Path, digest: str, timeout_s: float = 120.0):
        self.lock_dir = cache_root / "locks" / f"{digest}.lock"
        self.timeout_s = timeout_s

    def __enter__(self):
        self.lock_dir.parent.mkdir(parents=True, exist_ok=True)
        waited = 0.0
        while True:
            try:
                self.lock_dir.mkdir()
                return self
            except FileExistsError as exc:
                if waited >= self.timeout_s:
                    raise RecipeError(
                        f"cache key locked by another build: {self.lock_dir}"
                    ) from exc
                time.sleep(0.25)
                waited += 0.25

    def __exit__(self, *_exc):
        try:
            self.lock_dir.rmdir()
        except OSError:
            pass


def _run_gates(forge, requirements: dict) -> dict:
    """Map recipe requirements onto the live gate ops. Only declared
    requirements are checked — an absent requirement is not a silent default."""
    gates: dict[str, dict] = {}
    check_args: dict = {}
    if "max_triangles" in requirements:
        check_args["triangle_budget"] = int(requirements["max_triangles"])
    if "max_materials" in requirements:
        check_args["material_budget"] = int(requirements["max_materials"])
    if requirements.get("require_collision"):
        check_args["require_collision"] = True
    if requirements.get("require_lods"):
        check_args["require_lods"] = True
    if check_args:
        gates["check.asset"] = forge.call("check.asset", **check_args)
    if "platform" in requirements:
        gates["gameready.budget"] = forge.call(
            "gameready.budget",
            profile=requirements["platform"],
            asset_class=requirements.get("asset_class", "prop"),
        )
    return gates


def _gate_failures(gates: dict) -> list[str]:
    """Fail closed: a gate result without its verdict field is a failure, not a pass."""
    failures: list[str] = []
    check = gates.get("check.asset")
    if check is not None:
        if "ok" not in check:
            failures.append("check.asset: malformed result (no 'ok' verdict)")
        elif not check["ok"]:
            failures.append(f"check.asset: {check.get('errors', '?')} error(s)")
    budget = gates.get("gameready.budget")
    if budget is not None:
        if "within_budget" not in budget:
            failures.append("gameready.budget: malformed result (no 'within_budget' verdict)")
        elif not budget["within_budget"]:
            failures.append("gameready.budget: over budget")
    return failures


def _hash_artifacts(directory: Path) -> list[dict]:
    artifacts = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.name not in ("proof.json", "recipe.canonical.json"):
            artifacts.append(
                {
                    "path": path.relative_to(directory).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    return artifacts


def pinned_blender_version() -> str | None:
    lock_path = BFORGE_ROOT / "blender-lock.toml"
    if not lock_path.is_file():
        return None
    return tomllib.loads(lock_path.read_text(encoding="utf-8")).get("blender", {}).get("version")


def _check_toolchain(reported: str, allow_unpinned: bool) -> None:
    """The byte-identical claim holds only under the pinned Blender. A cache
    miss must be built by the pinned toolchain — otherwise the content address
    (which fingerprints the DECLARED toolchain) would store artifacts produced
    by a different one."""
    pinned = pinned_blender_version()
    if not pinned or allow_unpinned:
        return
    if not reported.startswith(pinned):
        raise RecipeError(
            f"pinned toolchain violation: blender-lock.toml requires {pinned}, "
            f"the daemon reports {reported!r}. Install the pinned Blender or pass "
            "--allow-unpinned (results are then never cached)."
        )


def cook(
    recipe_path,
    cache_dir: Path | None = None,
    no_cache: bool = False,
    forge_factory=None,
    allow_unpinned: bool = False,
) -> dict:
    """Compile a recipe into artifacts plus a proof capsule.

    The cache is a content-addressed store: builds happen in a unique staging
    directory, pass full verification, and are published by atomic rename
    under a per-key lock. Accepted entries are immutable. Failures go to the
    failure store; `--no-cache` and unpinned builds produce verified but
    ephemeral packages that never touch the store.

    `forge_factory` is called with no arguments only on a cache miss and must
    return a started-or-startable Forge (kept injectable so a hit never needs
    Blender and tests can fake the worker).
    """
    recipe_path = Path(recipe_path).resolve()
    recipe = load_recipe(recipe_path)
    input_hashes = hash_inputs(recipe, recipe_path.parent)
    digest, envelope = cache_key(recipe, input_hashes)
    cache_root = Path(cache_dir) if cache_dir else DEFAULT_CACHE
    objects_dir = cache_root / "objects" / digest
    canonical = canonicalize(recipe)
    expected = {
        "asset_id": recipe["asset_id"],
        "recipe_hash": content_hash(recipe, input_hashes),
        "cache_key": digest,
        "inputs": input_hashes,
        "envelope": envelope,
        "canonical": canonical,
        "requirements": recipe.get("requirements", {}),
        "pinned": pinned_blender_version(),
    }

    if not no_cache and (objects_dir / "proof.json").is_file():
        proof = _strict_loads(
            (objects_dir / "proof.json").read_text(encoding="utf-8"), "proof.json"
        )
        if verify_entry(proof, objects_dir, expected):
            proof["cache"]["hit"] = True
            return proof
        # unverifiable or tampered entries fall through to a rebuild

    if forge_factory is None:
        from bforge.client import Forge

        forge_factory = Forge

    staging = cache_root / "staging" / f"{digest}.{os.getpid()}.{secrets.token_hex(4)}"
    proof: dict = {
        "proof_version": PROOF_VERSION,
        "asset_id": recipe["asset_id"],
        "recipe_hash": expected["recipe_hash"],
        "cache_key": digest,
        "recipe_file": recipe_path.name,
        "inputs": input_hashes,
        "started_utc": datetime.now(UTC).isoformat(),
        "status": "fail",
    }

    forge = None
    cacheable = not no_cache
    try:
        forge = forge_factory()
        info = forge.start()
        reported_blender = info.get("blender", "unknown")
        _check_toolchain(reported_blender, allow_unpinned)
        pinned = pinned_blender_version()
        cacheable = cacheable and (not pinned or reported_blender.startswith(pinned))
        staging.mkdir(parents=True, exist_ok=False)
        (staging / "recipe.canonical.json").write_bytes(canonical)
        proof["cache"] = {"hit": False, "dir": str(objects_dir), "envelope": envelope}
        if not cacheable:
            proof["cache"]["cacheable"] = False
            reason = f"unpinned Blender {reported_blender!r} (lock pins {pinned})"
            proof["cache"]["reason"] = "forced rebuild" if no_cache and pinned else reason
        blender_bin = getattr(forge, "blender", None)
        proof["toolchain"] = {
            "blender": reported_blender,
            "blender_binary_sha256": (
                _sha256_file(Path(blender_bin))
                if blender_bin and Path(blender_bin).is_file()
                else None
            ),
            "python": info.get("python", "unknown"),
            "ops": info.get("ops", 0),
        }
        forge.call("session.reset")

        steps = []
        for step in recipe["steps"]:
            started = time.time()
            result = forge.call(
                step["op"], _timeout=step.get("timeout", 900), **step.get("args", {})
            )
            steps.append(
                {
                    "op": step["op"],
                    "ok": True,
                    "ms": int((time.time() - started) * 1000),
                    "result": result,
                }
            )
        proof["steps"] = steps

        requirements = recipe.get("requirements", {})
        gates = _run_gates(forge, requirements)
        proof["gates"] = gates
        failures = _gate_failures(gates)

        export_spec = recipe.get("export", {})
        proof["export"] = forge.call(
            "export.asset",
            asset_id=recipe["asset_id"],
            out_dir=str(staging),
            engine=export_spec.get("engine", "godot"),
            category=export_spec.get("category", "prop"),
            ai_prompt=export_spec.get("ai_prompt", recipe.get("brief", "")),
            contact_sheet=export_spec.get("contact_sheet", True),
            strict=export_spec.get("strict", True),
            _timeout=1200,
        )

        if failures:
            proof["status"] = "fail"
            proof["failures"] = failures
        else:
            proof["status"] = "pass"
    except Exception as exc:  # proof of failure is still proof — record it
        proof["status"] = "fail"
        proof["failures"] = [f"{type(exc).__name__}: {exc}"]
        if not staging.is_dir():
            # toolchain violations never reach the store; re-raise bare
            if forge is not None:
                forge.stop()
            raise
    finally:
        if forge is not None:
            forge.stop()

    if staging.is_dir():
        proof["duration_s"] = round(
            time.time() - datetime.fromisoformat(proof["started_utc"]).timestamp(), 3
        )
        proof["artifacts"] = _hash_artifacts(staging)
        (staging / "proof.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")

    if proof["status"] == "pass":
        # verify the staged package before it can be published or returned
        staged_proof = _strict_loads(
            (staging / "proof.json").read_text(encoding="utf-8"), "staged proof"
        )
        if not verify_entry(staged_proof, staging, expected):
            proof["status"] = "fail"
            proof["failures"] = ["staged package failed self-verification"]
            (staging / "proof.json").write_text(
                json.dumps(proof, indent=2) + "\n", encoding="utf-8"
            )

    if proof["status"] != "pass":
        failure_dir = (
            cache_root / "failures" / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{digest[:12]}"
        )
        if staging.is_dir():
            failure_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staging), str(failure_dir))
        raise RecipeError(
            f"recipe {recipe_path.name} failed: {'; '.join(proof.get('failures', ['unknown']))} "
            f"(proof: {failure_dir / 'proof.json'})"
        )

    if cacheable:
        with _KeyLock(cache_root, digest):
            objects_dir.parent.mkdir(parents=True, exist_ok=True)
            if objects_dir.is_dir():
                # another builder won the race; verify and reuse their entry
                theirs = _strict_loads(
                    (objects_dir / "proof.json").read_text(encoding="utf-8"), "proof.json"
                )
                if verify_entry(theirs, objects_dir, expected):
                    shutil.rmtree(staging)
                    theirs["cache"]["hit"] = True
                    return theirs
                shutil.move(
                    str(objects_dir),
                    str(
                        cache_root
                        / "failures"
                        / f"corrupt-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{digest[:12]}"
                    ),
                )
            os.rename(staging, objects_dir)
        proof["cache"]["dir"] = str(objects_dir)
        return proof

    proof["cache"]["dir"] = str(staging)  # ephemeral: verified, never published
    proof["cache"]["ephemeral"] = True
    return proof
