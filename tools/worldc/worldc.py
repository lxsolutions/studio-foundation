#!/usr/bin/env python3
"""worldc — the World IR compiler (ADR 0018, spec: docs/specs/world-ir-v0.1.md).

Compiles an entity document into a proof-carrying package:

  validate the semantic contract (hard errors, not warnings)
    -> compile the embedded Recipe IR through bforge (content-addressed)
    -> verify the compiled GLB honors the contract (parts, hierarchy,
       collision ownership, payload)
    -> write an entity proof capsule into a SEPARATE entity cache

The asset cache is immutable from worldc's perspective: the entity layer
references the asset proof by hash (asset_cache_key + asset_proof_sha256) and
never writes into the asset store. The entity cache key covers the canonical
World IR document, the exact asset proof, and the worldc compiler itself, so
two entities sharing one asset recipe can never collide.

Usage: python tools/worldc/worldc.py compile ENTITY.json [--cache-dir DIR] [--no-cache]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import secrets
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # glb.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bforge"))  # bforge

import glb as glb_mod  # noqa: E402

from bforge import recipe as recipe_mod  # noqa: E402

WORLD_IR_VERSION = "0.1"
ENTITY_SCHEMA = "studio.world-entity.v0.1"
CANONICALIZATION = "studio-json-c14n-v1"
PROOF_VERSION = 1

WORLDC_ROOT = Path(__file__).resolve().parent
SPEC_PATH = WORLDC_ROOT.parents[1] / "docs" / "specs" / "world-ir-v0.1.md"

STATE_TYPES = {"float", "int", "bool", "string"}
AUTHORITIES = {"server", "client", "shared"}
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
TOP_LEVEL_KEYS = {
    "world_ir",
    "entity",
    "brief",
    "parts",
    "joints",
    "state",
    "affordances",
    "navigation",
    "network",
    "requirements",
    "sim",
    "recipe",
    "extensions",  # the only place nonstandard fields may live
}


class WorldIRError(Exception):
    """The entity document is invalid, or the compiled artifact broke the contract."""


# ---------------------------------------------------------------- validation


def load_entity(path: Path) -> dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorldIRError(f"{path}: not valid JSON: {exc}") from exc
    return validate_entity(doc, source=str(path))


def _require_obj(value, what: str, source: str) -> dict:
    if not isinstance(value, dict):
        raise WorldIRError(f"{source}: {what} must be an object")
    return value


def validate_entity(doc: dict, source: str = "<document>") -> dict:
    if not isinstance(doc, dict):
        raise WorldIRError(f"{source}: an entity is a JSON object")
    unknown = sorted(set(doc) - TOP_LEVEL_KEYS)
    if unknown:
        raise WorldIRError(
            f"{source}: unknown top-level fields {unknown} — nonstandard data belongs under 'extensions'"
        )
    if doc.get("world_ir") != WORLD_IR_VERSION:
        raise WorldIRError(
            f"{source}: unsupported world_ir {doc.get('world_ir')!r} (want {WORLD_IR_VERSION})"
        )
    entity = doc.get("entity")
    if not isinstance(entity, str) or not IDENTIFIER.match(entity):
        raise WorldIRError(f"{source}: entity must be a snake_case identifier")

    parts = _require_obj(doc.get("parts"), "parts", source)
    if not parts:
        raise WorldIRError(f"{source}: parts must be a non-empty object")
    for name, spec in parts.items():
        if not IDENTIFIER.match(name):
            raise WorldIRError(f"{source}: part name {name!r} must be a snake_case identifier")
        spec = _require_obj(spec, f"part {name!r}", source)
        parent = spec.get("parent")
        if parent is not None and parent not in parts:
            raise WorldIRError(f"{source}: part {name!r} parents unknown part {parent!r}")
    for name in parts:  # parent graph must be acyclic
        seen = set()
        cursor = name
        while (cursor := (parts.get(cursor) or {}).get("parent")) is not None:
            if cursor in seen:
                raise WorldIRError(f"{source}: parent cycle through part {name!r}")
            seen.add(cursor)

    for jname, joint in _require_obj(doc.get("joints", {}), "joints", source).items():
        if not IDENTIFIER.match(jname):
            raise WorldIRError(f"{source}: joint name {jname!r} must be a snake_case identifier")
        joint = _require_obj(joint, f"joint {jname!r}", source)
        parent, child = joint.get("parent"), joint.get("child")
        if parent not in parts or child not in parts:
            raise WorldIRError(f"{source}: joint {jname!r} references unknown parts")
        if parent == child:
            raise WorldIRError(f"{source}: joint {jname!r} joins a part to itself")
        axis = joint.get("axis")
        if (
            not isinstance(axis, list)
            or len(axis) != 3
            or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in axis)
        ):
            raise WorldIRError(f"{source}: joint {jname!r} axis must be three finite numbers")
        if all(v == 0 for v in axis):
            raise WorldIRError(f"{source}: joint {jname!r} axis must be nonzero")
        rng = joint.get("range_degrees")
        if (
            not isinstance(rng, list)
            or len(rng) != 2
            or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in rng)
            or rng[0] > rng[1]
        ):
            raise WorldIRError(
                f"{source}: joint {jname!r} range_degrees must be [min, max] with min <= max"
            )

    state = _require_obj(doc.get("state", {}), "state", source)
    for var, kind in state.items():
        if not IDENTIFIER.match(var):
            raise WorldIRError(f"{source}: state var {var!r} must be a snake_case identifier")
        if kind not in STATE_TYPES:
            raise WorldIRError(
                f"{source}: state {var!r} has unknown type {kind!r} (want one of {sorted(STATE_TYPES)})"
            )

    affordances = doc.get("affordances", [])
    if not isinstance(affordances, list) or not affordances:
        raise WorldIRError(f"{source}: affordances must be a non-empty list")
    for verb in affordances:
        if not isinstance(verb, str) or not IDENTIFIER.match(verb):
            raise WorldIRError(f"{source}: affordance {verb!r} must be a snake_case identifier")
    if len(set(affordances)) != len(affordances):
        raise WorldIRError(f"{source}: duplicate affordances are not allowed")

    network = _require_obj(doc.get("network", {}), "network", source)
    if network:
        if network.get("authority") not in AUTHORITIES:
            raise WorldIRError(f"{source}: network.authority must be one of {sorted(AUTHORITIES)}")
        replicated = network.get("replicated", [])
        if len(set(replicated)) != len(replicated):
            raise WorldIRError(f"{source}: network.replicated contains duplicates")
        unknown_vars = [v for v in replicated if v not in state]
        if unknown_vars:
            raise WorldIRError(f"{source}: replicated state not declared in state: {unknown_vars}")

    nav = _require_obj(doc.get("navigation", {}), "navigation", source)
    for key, value in nav.items():
        if key == "never_blocks_when_destroyed":
            if not isinstance(value, bool):
                raise WorldIRError(f"{source}: navigation.{key} must be a boolean")
        elif key.startswith("blocks_below_"):
            var = key.removeprefix("blocks_below_")
            if state.get(var) != "float":
                raise WorldIRError(f"{source}: navigation.{key} needs a float state var {var!r}")
        else:
            raise WorldIRError(f"{source}: unknown navigation rule {key!r}")

    requirements = _require_obj(doc.get("requirements", {}), "requirements", source)
    collision = requirements.get("require_collision")
    if collision is not None and collision is not True and collision not in parts:
        raise WorldIRError(
            f"{source}: requirements.require_collision must be true or name a part (got {collision!r})"
        )

    recipe = _require_obj(doc.get("recipe"), "recipe", source)
    if recipe.get("asset_id") != entity:
        raise WorldIRError(
            f"{source}: recipe.asset_id {recipe.get('asset_id')!r} must equal entity {entity!r}"
        )
    return doc


# ------------------------------------------------------------- fingerprinting


def worldc_fingerprint() -> dict:
    """Fingerprint the entity compiler: its own sources, the GLB reader, the
    spec the validation implements, and Python. A changed compiler is a changed
    cache key."""

    def _sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    return {
        "worldc_sha256": _sha(WORLDC_ROOT / "worldc.py"),
        "glb_reader_sha256": _sha(WORLDC_ROOT / "glb.py"),
        "world_ir_spec_sha256": _sha(SPEC_PATH) if SPEC_PATH.is_file() else None,
        "python": platform.python_version(),
    }


def entity_key(doc: dict, asset_proof_sha256: str, asset_cache_key: str) -> tuple[str, dict]:
    envelope = {
        "schema": ENTITY_SCHEMA,
        "canonicalization": CANONICALIZATION,
        "world_ir_sha256": hashlib.sha256(recipe_mod.canonicalize(doc)).hexdigest(),
        "asset_proof_sha256": asset_proof_sha256,
        "asset_cache_key": asset_cache_key,
        "worldc_compiler": worldc_fingerprint(),
    }
    return hashlib.sha256(recipe_mod.canonicalize(envelope)).hexdigest(), envelope


# ------------------------------------------------------------- artifact gates


def verify_artifact(doc: dict, glb_path: Path) -> list[dict]:
    """Check the compiled GLB against the semantic contract."""
    gltf = glb_mod.read_glb_json(glb_path)
    by_name, parent_of = glb_mod.node_index(gltf)
    checks: list[dict] = []

    for name, spec in doc["parts"].items():
        present = name in by_name
        checks.append(
            {
                "check": f"part present: {name}",
                "ok": present,
                "detail": "node found" if present else "no such GLB node",
            }
        )
        expected_parent = (spec or {}).get("parent")
        if present and expected_parent is not None:
            actual = parent_of.get(name)
            checks.append(
                {
                    "check": f"hierarchy: {name} under {expected_parent}",
                    "ok": actual == expected_parent,
                    "detail": f"parent is {actual!r}",
                }
            )

    collision = doc.get("requirements", {}).get("require_collision")
    if collision:
        if collision is True:
            found = [n for n in by_name if "-col" in n or "-convcol" in n]
            ok = bool(found)
            detail = f"proxy nodes: {found}" if ok else "no -col/-convcol node"
        else:
            ok = f"{collision}-convcol" in by_name or f"{collision}-col" in by_name
            detail = (
                f"proxy for {collision!r} found"
                if ok
                else f"no {collision}-col/-convcol proxy node"
            )
        checks.append({"check": "collision proxy present", "ok": ok, "detail": detail})

    budget = doc.get("requirements", {}).get("payload_kb_max")
    if budget:
        size_kb = glb_path.stat().st_size / 1024
        checks.append(
            {
                "check": f"payload <= {budget} KB",
                "ok": size_kb <= budget,
                "detail": f"{size_kb:.1f} KB",
            }
        )
    return checks


# ------------------------------------------------------ simulation contracts

SIM_CONTRACT_VERSION = "0.1"
SIM_STORAGE = {"float": "milli_i64", "int": "i64", "bool": "bool", "string": "string"}
SIM_PARAM_KEYS = {"open_rate_milli", "max_health"}


def sim_contract(doc: dict, source: str = "<document>") -> dict:
    """Compile a validated World IR entity document into the integer-only
    simulation contract that both kernels consume.

    This is where floats leave the simulation boundary: navigation thresholds
    convert to milli-units exactly once, here, and both kernels read integer
    parameters only. The contract carries the source document's canonical
    hash so a replay pins an unbroken chain back to World IR.
    """
    validate_entity(doc, source=source)

    sim = doc.get("sim", {})
    if not isinstance(sim, dict):
        raise WorldIRError(f"{source}: sim must be an object")
    unknown = sorted(set(sim) - SIM_PARAM_KEYS)
    if unknown:
        raise WorldIRError(f"{source}: unknown sim parameters {unknown}")
    parameters = {"open_rate_milli": 250, "max_health": 100}
    for key_name, value in sim.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise WorldIRError(f"{source}: sim.{key_name} must be a nonnegative integer")
        parameters[key_name] = value

    nav = doc.get("navigation", {})
    blocks_below = []
    for key_name, threshold in nav.items():
        if key_name.startswith("blocks_below_"):
            var = key_name.removeprefix("blocks_below_")
            blocks_below.append({"var": var, "threshold_milli": int(round(threshold * 1000))})
    navigation = {
        "blocks_below": sorted(blocks_below, key=lambda rule: rule["var"]),
        "never_blocks_when_destroyed": bool(nav.get("never_blocks_when_destroyed", False)),
    }

    return {
        "sim_contract": SIM_CONTRACT_VERSION,
        "source_world_ir_sha256": hashlib.sha256(recipe_mod.canonicalize(doc)).hexdigest(),
        "entity": doc["entity"],
        "state": {
            var: {"storage": SIM_STORAGE[kind]} for var, kind in doc.get("state", {}).items()
        },
        "affordances": list(doc.get("affordances", [])),
        "parameters": {**parameters, "navigation": navigation},
    }


# ------------------------------------------------------------------ compile

# World-level requirements are authoritative: they are injected into the
# embedded recipe before compilation, so the entity contract and the executed
# gates cannot disagree.
DELEGATED_REQUIREMENTS = (
    "max_triangles",
    "max_materials",
    "require_lods",
    "platform",
    "asset_class",
)


def _recipe_for_compile(doc: dict, base_dir: Path) -> dict:
    recipe = json.loads(json.dumps(doc["recipe"]))  # deep copy
    reqs = dict(recipe.get("requirements", {}))
    world_reqs = doc.get("requirements", {})
    for key_name in DELEGATED_REQUIREMENTS:
        if key_name in world_reqs:
            reqs[key_name] = world_reqs[key_name]
    if world_reqs.get("require_collision"):
        # boolean at the recipe layer; ownership is the entity-level check
        reqs["require_collision"] = True
    recipe["requirements"] = reqs
    # recipe input paths are relative to the ENTITY document, not to the
    # temporary file the recipe is compiled from
    for spec in recipe.get("inputs", {}).values():
        raw = spec.get("path") if isinstance(spec, dict) else None
        if raw and not Path(raw).is_absolute():
            spec["path"] = str((base_dir / raw).resolve())
    return recipe


def _entity_entry_valid(
    cached: dict, entity_dir: Path, envelope: dict, asset_proof_sha: str
) -> bool:
    """Full identity check for a cached entity proof — not just status."""
    if cached.get("proof_version") != PROOF_VERSION or cached.get("schema") != ENTITY_SCHEMA:
        return False
    if cached.get("status") != "pass":
        return False
    if cached.get("entity_cache_key") != entity_dir.name:
        return False
    if cached.get("world_ir_sha256") != envelope["world_ir_sha256"]:
        return False
    asset = cached.get("asset", {})
    if asset.get("proof_sha256") != asset_proof_sha:
        return False
    if asset.get("cache_key") != envelope["asset_cache_key"]:
        return False
    if cached.get("worldc_compiler") != envelope["worldc_compiler"]:
        return False
    checks = cached.get("checks", [])
    if not checks or not all(c.get("ok") for c in checks):
        return False
    canonical = entity_dir / "entity.canonical.json"
    return canonical.is_file()


def compile_entity(
    entity_path,
    cache_dir: Path | None = None,
    no_cache: bool = False,
    forge_factory=None,
) -> dict:
    entity_path = Path(entity_path).resolve()
    doc = load_entity(entity_path)
    entity = doc["entity"]

    cache_root = Path(cache_dir) if cache_dir else WORLDC_ROOT / "cache"
    asset_cache = cache_root / "asset-cache"
    entity_cache = cache_root / "entity-cache"

    # 1. the asset layer compiles the embedded recipe into its own store;
    #    world requirements are injected (authoritative), and recipe input
    #    paths resolve against the entity document's directory
    recipe_doc = _recipe_for_compile(doc, entity_path.parent)
    work = Path(tempfile.mkdtemp(prefix="worldc_recipe_"))
    recipe_path = work / f"{entity}.recipe.json"
    recipe_path.write_text(json.dumps(recipe_doc, indent=2), encoding="utf-8")
    recipe_mod.load_recipe(recipe_path)  # validate before paying for a worker

    asset_proof = recipe_mod.cook(
        recipe_path, cache_dir=asset_cache, no_cache=no_cache, forge_factory=forge_factory
    )
    asset_dir = Path(asset_proof["cache"]["dir"])
    asset_proof_path = asset_dir / "proof.json"
    asset_proof_sha = hashlib.sha256(asset_proof_path.read_bytes()).hexdigest()
    asset_cache_key = asset_proof["cache_key"]

    # 2. the entity layer has its own content address
    key, envelope = entity_key(doc, asset_proof_sha, asset_cache_key)
    entity_dir = entity_cache / key

    if not no_cache and (entity_dir / "entity_proof.json").is_file():
        cached = json.loads((entity_dir / "entity_proof.json").read_text(encoding="utf-8"))
        if _entity_entry_valid(cached, entity_dir, envelope, asset_proof_sha):
            # the recorded checks must still match the artifact — recompute
            # them so an edited check detail/verdict invalidates the entry
            primary_rel = cached["asset"].get("primary_artifact", "")
            try:
                recomputed = verify_artifact(doc, asset_dir / primary_rel)
            except (glb_mod.GLBStructureError, OSError):
                recomputed = []
            same = [(c["check"], c["ok"]) for c in recomputed] == [
                (c.get("check"), c.get("ok")) for c in cached.get("checks", [])
            ]
            if same:
                cached["cache"] = {"hit": True, "dir": str(entity_dir)}
                return cached
        # stale or tampered entries fall through to re-verification

    # 3. verify the compiled GLB against the contract (asset store is read-only here)
    glb_artifacts = [a for a in asset_proof["artifacts"] if a["path"].endswith(".glb")]
    if not glb_artifacts:
        raise WorldIRError(f"{entity}: recipe produced no GLB artifact")
    primary = next((a for a in glb_artifacts if a["path"] == f"{entity}.glb"), glb_artifacts[0])
    glb_path = asset_dir / primary["path"]
    try:
        checks = verify_artifact(doc, glb_path)
    except glb_mod.GLBStructureError as exc:
        raise WorldIRError(f"{entity}: malformed GLB artifact: {exc}") from exc
    failures = [c["check"] for c in checks if not c["ok"]]

    proof = {
        "proof_version": PROOF_VERSION,
        "schema": ENTITY_SCHEMA,
        "entity": entity,
        "world_ir": WORLD_IR_VERSION,
        "world_ir_sha256": envelope["world_ir_sha256"],
        "entity_cache_key": key,
        "asset": {
            "cache_key": asset_cache_key,
            "proof_sha256": asset_proof_sha,
            "proof_uri": os.path.relpath(asset_proof_path, start=entity_dir),
            "primary_artifact": primary["path"],
            "artifacts": asset_proof["artifacts"],
        },
        "worldc_compiler": envelope["worldc_compiler"],
        "checks": checks,
        "status": "pass" if not failures else "fail",
    }

    # 4. publish atomically: stage beside the store, rename into place
    staging = entity_cache / "staging" / f"{key}.{os.getpid()}.{secrets.token_hex(4)}"
    staging.mkdir(parents=True, exist_ok=False)
    (staging / "entity.canonical.json").write_bytes(recipe_mod.canonicalize(doc))
    (staging / "entity_proof.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")

    if failures:
        failure_dir = (
            entity_cache / "failures" / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{key[:12]}"
        )
        failure_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging), str(failure_dir))
        raise WorldIRError(
            f"{entity}: contract broken — {failures} (proof: {failure_dir / 'entity_proof.json'})"
        )

    with recipe_mod._KeyLock(entity_cache, key):
        if entity_dir.is_dir():
            existing = json.loads((entity_dir / "entity_proof.json").read_text(encoding="utf-8"))
            if _entity_entry_valid(existing, entity_dir, envelope, asset_proof_sha):
                shutil.rmtree(staging)
                existing["cache"] = {"hit": True, "dir": str(entity_dir)}
                return existing
            shutil.move(
                str(entity_dir),
                str(
                    entity_cache
                    / "failures"
                    / f"corrupt-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{key[:12]}"
                ),
            )
        os.rename(staging, entity_dir)
    proof["cache"] = {"hit": False, "dir": str(entity_dir)}
    return proof


# -------------------------------------------------------------------- worlds

WORLD_SCHEMA = "studio.world.v0.1"
WORLD_KEYS = {
    "world_ir",
    "world",
    "brief",
    "entities",
    "scenario",
    "expect_navigation",
    "extensions",
}


def load_world(path: Path) -> dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorldIRError(f"{path}: not valid JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise WorldIRError(f"{path}: a world is a JSON object")
    source = str(path)
    unknown = sorted(set(doc) - WORLD_KEYS)
    if unknown:
        raise WorldIRError(f"{source}: unknown top-level fields {unknown}")
    if doc.get("world_ir") != WORLD_IR_VERSION:
        raise WorldIRError(
            f"{source}: unsupported world_ir {doc.get('world_ir')!r} (want {WORLD_IR_VERSION})"
        )
    if not isinstance(doc.get("world"), str) or not IDENTIFIER.match(doc["world"]):
        raise WorldIRError(f"{source}: world must be a snake_case identifier")
    entities = doc.get("entities")
    if not isinstance(entities, dict) or not entities:
        raise WorldIRError(f"{source}: entities must be a non-empty object")
    for name, entry in entities.items():
        if not IDENTIFIER.match(name):
            raise WorldIRError(f"{source}: bad entity name {name!r}")
        if not isinstance(entry, dict) or not isinstance(entry.get("doc"), str):
            raise WorldIRError(f"{source}: entity {name!r} needs an object with a doc path")
    if not isinstance(doc.get("scenario"), str):
        raise WorldIRError(f"{source}: scenario (a replay path) is required")
    expect_nav = doc.get("expect_navigation", {})
    if not isinstance(expect_nav, dict) or any(
        k not in entities or not isinstance(v, bool) for k, v in expect_nav.items()
    ):
        raise WorldIRError(f"{source}: expect_navigation maps entity names to booleans")
    return doc


def compile_world(
    world_path,
    cache_dir: Path | None = None,
    no_cache: bool = False,
    forge_factory=None,
) -> dict:
    """Compile a world: entity proofs for every entity, then the scenario
    replay, then one world proof capsule binding both by hash."""
    world_path = Path(world_path).resolve()
    doc = load_world(world_path)
    world_name = doc["world"]

    cache_root = Path(cache_dir) if cache_dir else WORLDC_ROOT / "cache"
    world_cache = cache_root / "world-cache"

    # 1. entity proofs (each into the entity store; shared docs share proofs)
    entity_proofs: dict[str, dict] = {}
    entity_docs: dict[str, dict] = {}
    for name, entry in doc["entities"].items():
        entity_doc_path = (world_path.parent / entry["doc"]).resolve()
        entity_docs[name] = load_entity(entity_doc_path)
        entity_proofs[name] = compile_entity(
            entity_doc_path, cache_dir=cache_root, no_cache=no_cache, forge_factory=forge_factory
        )

    # 2. the scenario replay must name exactly this world's entities, and its
    #    inline contracts must be the ones these documents compile to
    replay_path = (world_path.parent / doc["scenario"]).resolve()
    sim_mod = _sim_kernel()
    replay = sim_mod.load_replay(replay_path)  # format validation
    replay_entities = replay.get("entities", {})
    if set(replay_entities) != set(doc["entities"]):
        raise WorldIRError(
            f"{world_path}: scenario entities {sorted(replay_entities)} do not match "
            f"the world's {sorted(doc['entities'])}"
        )
    for name, rent in replay_entities.items():
        compiled = sim_contract(entity_docs[name], source=str(world_path))
        compiled_sha = hashlib.sha256(recipe_mod.canonicalize(compiled)).hexdigest()
        inline_sha = hashlib.sha256(recipe_mod.canonicalize(rent["contract"])).hexdigest()
        if inline_sha != compiled_sha or rent["contract_sha256"] != compiled_sha:
            raise WorldIRError(
                f"{world_path}: scenario's contract for {name} does not match the "
                f"world's document ({rent['contract_sha256'][:12]}… vs {compiled_sha[:12]}…)"
            )

    # 3. run the scenario deterministically (self-contained replay)
    result = sim_mod.run_replay(replay_path)

    # 4. world-level checks
    checks: list[dict] = []
    for name, proof in entity_proofs.items():
        checks.append(
            {
                "check": f"entity proof passes: {name}",
                "ok": proof["status"] == "pass",
                "detail": f"entity-cache key {proof['entity_cache_key'][:12]}…",
            }
        )
    for name, expected in doc.get("expect_navigation", {}).items():
        actual = result["navigation"][name]
        checks.append(
            {
                "check": f"navigation outcome: {name} blocks == {expected}",
                "ok": actual is expected,
                "detail": f"blocks_navigation == {actual}",
            }
        )
    failures = [c["check"] for c in checks if not c["ok"]]

    # 5. one world proof capsule
    replay_sha = hashlib.sha256(recipe_mod.canonicalize(replay)).hexdigest()
    entity_refs = {}
    for name, proof in entity_proofs.items():
        proof_file = Path(proof["cache"]["dir"]) / "entity_proof.json"
        entity_refs[name] = {
            "entity_cache_key": proof["entity_cache_key"],
            "entity_proof_sha256": hashlib.sha256(proof_file.read_bytes()).hexdigest(),
        }
    envelope = {
        "schema": WORLD_SCHEMA,
        "canonicalization": CANONICALIZATION,
        "world_doc_sha256": hashlib.sha256(recipe_mod.canonicalize(doc)).hexdigest(),
        "entity_proofs": {name: ref["entity_proof_sha256"] for name, ref in entity_refs.items()},
        "replay_sha256": replay_sha,
        "worldc_compiler": worldc_fingerprint(),
    }
    key = hashlib.sha256(recipe_mod.canonicalize(envelope)).hexdigest()
    world_dir = world_cache / key
    for name, proof in entity_proofs.items():
        proof_file = Path(proof["cache"]["dir"]) / "entity_proof.json"
        entity_refs[name]["entity_proof_uri"] = os.path.relpath(proof_file, start=world_dir)

    proof = {
        "proof_version": PROOF_VERSION,
        "schema": WORLD_SCHEMA,
        "world": world_name,
        "world_cache_key": key,
        "entities": entity_refs,
        "scenario": {
            "replay": doc["scenario"],
            "replay_sha256": replay_sha,
            "state_hash": result["state_hash"],
            "navigation": result["navigation"],
            "fingerprints": result["fingerprints"],
        },
        "worldc_compiler": envelope["worldc_compiler"],
        "checks": checks,
        "status": "pass" if not failures else "fail",
    }

    staging = world_cache / "staging" / f"{key}.{os.getpid()}.{secrets.token_hex(4)}"
    staging.mkdir(parents=True, exist_ok=False)
    (staging / "world_proof.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    if failures:
        failure_dir = (
            world_cache / "failures" / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{key[:12]}"
        )
        failure_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging), str(failure_dir))
        raise WorldIRError(
            f"{world_name}: world contract broken — {failures} "
            f"(proof: {failure_dir / 'world_proof.json'})"
        )
    with recipe_mod._KeyLock(world_cache, key):
        if not world_dir.is_dir():
            os.rename(staging, world_dir)
        else:
            shutil.rmtree(staging)
    proof["cache"] = {"hit": False, "dir": str(world_dir)}
    return proof


def _sim_kernel():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sim"))
    import kernel

    return kernel


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="worldc", description=__doc__.split("\n")[1])
    sub = parser.add_subparsers(dest="command", required=True)
    comp = sub.add_parser("compile", help="Compile an entity document to a proof-carrying package")
    comp.add_argument("file")
    comp.add_argument("--cache-dir", default=None)
    comp.add_argument("--no-cache", action="store_true")
    world = sub.add_parser(
        "compile-world", help="Compile a world document (entities + scenario) to a world proof"
    )
    world.add_argument("file")
    world.add_argument("--cache-dir", default=None)
    world.add_argument("--no-cache", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.command == "compile-world":
            proof = compile_world(
                args.file,
                cache_dir=args.cache_dir,
                no_cache=args.no_cache,
            )
        else:
            proof = compile_entity(
                args.file,
                cache_dir=args.cache_dir,
                no_cache=args.no_cache,
            )
    except (WorldIRError, recipe_mod.RecipeError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(proof, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
