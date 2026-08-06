# World IR v0.1 — the semantic contract above the mesh

Status: prototype (ADR 0018, milestone M2 precursor)
Schema id: `"world_ir": "0.1"`

GLB says what an object looks like. World IR says what it *is*: its parts,
hierarchy, joints, affordances, state, physics and navigation contracts, and
network authority. `worldc` compiles an entity document into a proof-carrying
package by delegating geometry to bforge Recipe IR (ADR 0018) and then
verifying the compiled artifact honors the semantic contract.

v0.1 is deliberately narrow: the entity document **references** its own
geometry recipe; the compiler's job is validation, verification, and proof.
Synthesizing geometry from pure semantics is later work.

## Document

JSON (the tooling is stdlib-only, ADR 0013). One entity per document.

```json
{
  "world_ir": "0.1",
  "entity": "fortress_gate",
  "parts": {
    "frame":  { "role": "static" },
    "leaf_l": { "parent": "frame" },
    "leaf_r": { "parent": "frame" }
  },
  "joints": {
    "hinge_l": { "parent": "frame", "child": "leaf_l",
                 "axis": [0, 0, 1], "range_degrees": [0, 110] }
  },
  "state":   { "openness": "float", "locked": "bool",
               "health": "int", "destroyed": "bool" },
  "affordances": ["open", "close", "lock", "attack", "repair"],
  "navigation": { "blocks_below_openness": 0.7,
                  "never_blocks_when_destroyed": true },
  "network": { "authority": "server",
               "replicated": ["openness", "locked", "health", "destroyed"] },
  "requirements": { "max_triangles": 4000, "require_collision": true,
                    "payload_kb_max": 900 },
  "recipe": { "recipe_version": 1, "...": "Recipe IR v1 (ADR 0018)" }
}
```

## Validation rules (compile-time, hard errors)

- Unknown top-level fields are rejected; nonstandard data belongs under
  `extensions`.
- `entity`, part names, joint names, state vars, and affordances are
  snake_case identifiers; affordances are unique.
- Every part spec is an object; every `parent` reference exists; the parent
  graph has no cycles.
- Every joint is an object naming two different existing parts, with `axis`
  exactly three finite numbers (nonzero) and `range_degrees` `[min, max]`
  with `min <= max`.
- `state` values are one of `float | int | bool | string`.
- `network.replicated` is a duplicate-free subset of `state` keys;
  `authority` is `server | client | shared`.
- `navigation` knows two rule forms: `never_blocks_when_destroyed` (bool) and
  `blocks_below_<var>` (a float state var).
- `requirements.require_collision` is `true` (any proxy) **or names the part
  that owns the proxy** — collision ownership is part of the contract.
- World-level requirements are **authoritative**: `max_triangles`,
  `max_materials`, `require_lods`, `platform`, `asset_class` are injected into
  the embedded recipe before compilation (a recipe that undercuts the entity
  contract cannot stand); a named collision owner becomes the recipe layer's
  boolean `require_collision`.
- Recipe input paths resolve against the entity document's directory, never
  against the compiler's scratch space.
- `recipe` must itself pass Recipe IR validation, and its `asset_id` must
  equal `entity` — the semantic and geometric identities are one.

## Artifact verification (against the compiled GLB, hard gates)

The GLB reader is strict: duplicate node names, out-of-range child indices,
and multiple parents are structure errors, not silent overwrites.

- Every declared part is a GLB node with the same name.
- Every declared parent edge appears in the GLB node tree.
- `require_collision: "frame"` ⇒ a `frame-col`/`frame-convcol` proxy node
  exists; `true` ⇒ any proxy node exists.
- `payload_kb_max` ⇒ the GLB artifact is within budget.
- Recipe requirements (`max_triangles`, platform budget, quality gate) are
  enforced by the Recipe IR layer and referenced by hash, not re-checked here.

## The entity proof capsule and cache

World compilation has its own content address, separate from the asset store:

```text
cache-root/
  asset-cache/<asset-cache-key>/     # written by Recipe IR only
    recipe.canonical.json
    <asset>.glb
    proof.json
  entity-cache/<entity-cache-key>/   # written by worldc only
    entity.canonical.json
    entity_proof.json
```

`entity_cache_key = sha256(canonical(envelope))` where the envelope covers
the canonical World IR document hash, the exact asset proof's SHA-256 and
cache key, and the worldc compiler fingerprint (worldc + GLB reader + spec +
Python). Two entities sharing one asset recipe therefore can never collide,
and the asset cache is immutable from worldc's perspective.

`entity_proof.json` carries `world_ir_sha256`, `asset.cache_key`,
`asset.proof_sha256`, a portable relative `asset.proof_uri` (resolvable from
the proof's own directory), the worldc fingerprint, every check result, and
`status: pass|fail`. Entries publish atomically (staging directory + rename
under a per-key lock); a cache hit re-validates the full proof identity,
re-hashes the referenced asset proof, and re-computes the checks against the
artifact — a tampered asset proof or an edited check verdict invalidates the
entry. A failed proof is still written (to the failure store) — it is
evidence — but it never satisfies a cache.

## Explicitly deferred

- The deterministic simulation kernel (state machines executing `state`),
  runtime adapters (Godot/Babylon), replay hashes — milestone M3.
- Geometry synthesis from semantics alone.
- Multiple entities per document, world graphs, streaming groups.
