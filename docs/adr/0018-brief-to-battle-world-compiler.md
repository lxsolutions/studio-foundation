# ADR 0018: BRIEF→BATTLE — the proof-carrying world compiler

- Status: Accepted
- Date: 2026-08-05
- Extends: [ADR 0014](0014-bforge-agent-asset-authoring.md) (bforge),
  [ADR 0008](0008-own-the-distribution-not-the-engine.md) (distribution, not engine)
- Relates: the TypeScript/Three.js peer-runtime proposal (ADR 0017, PR #50) is
  an open draft at time of writing; this ADR's milestone M2 (World IR compiled
  to two runtimes) composes with whichever runtime decision lands.

## Context

bforge proved the doctrine at asset level: generate, inspect the actual
artifact, measure it, reject failures, encode the failure as a permanent gate,
regenerate. The quality gate, the byte-identical bench, the catalog parity
checks, and the claims gate all exist because that loop works.

Two independent reviews of the repository (2026-08) reached the same
conclusion about what is next. The durable asset is not any single operation,
renderer patch, or demo — it is the production substrate. And the substrate
currently stops at the asset boundary. GLB carries geometry, skins, materials,
and animations; it does not carry what an object *is* in a game — its parts,
joints, affordances, state, physics, network authority, or the proof that any
of those work.

Meanwhile the field is converging on the thesis from both ends: neural
generators produce increasingly strong geometry with weak semantics; world
models produce convincing audiovisual experience with no durable state;
code-native asset research (Nova3D, 3DCodeBench) shows executable source beats
opaque meshes on editability and determinism; agentic game benchmarks
(GameDevBench, GameEngineBench) show the whole production loop is unsolved.
The missing middle is a system that materializes, normalizes, compiles, and
*proves*.

## Decision

Studio Foundation's north star is **BRIEF→BATTLE**: given a creative brief,
produce a playable, persistent, networkable world — and ship the proof bundle
with it. Worlds as code. Assets as programs. AI output as untrusted input.
Every world ships with proof.

The program has four durable contracts, in dependency order:

1. **Asset Recipe IR.** Assets are declared, not performed: a versioned,
   canonical, content-hashed recipe (inputs, steps, requirements) compiled by
   bforge workers into artifacts plus a **proof capsule** — recipe hash, tool
   identities, gate results, artifact hashes. Content-addressed caching makes
   regeneration free; proof makes acceptance mechanical.
2. **World IR.** The semantic layer GLB lacks: parts, hierarchy, joints,
   affordances, state schemas, physics/navigation contracts, network
   authority, budgets, provenance. World IR sits *between* OpenUSD/`.blend`
   source composition and GLB/KTX2 runtime payloads; it references artifacts
   rather than replacing formats.
3. **Deterministic simulation kernel.** Fixed-step, renderer-independent;
   initial state + seed + event stream ⇒ final state hash. Native Rust server
   and Wasm client run the same replay to the same hash. Agents steer intent,
   never per-frame state.
4. **BRIEF→BATTLE, the public benchmark.** One frozen brief → faction,
   battlefield, playable battle, deterministic replay, proof package — scored
   on validity, semantic correctness, visual quality, gameplay correctness,
   systems quality, and agent efficiency, across models, in public.

Milestone sequence: **M0** truth becomes generated (claims gate, full-schema
catalog parity, generated status surfaces — done 2026-08-05); **M1** bforge
becomes a compiler (Recipe IR, content-addressed builds, proof capsules);
**M2** World IR compiled to two runtimes; **M3** deterministic simulation with
browser/server parity; **M4** the public benchmark; **M5** constrained
runtime (living-world) generation that must pass the same proofs before
becoming authoritative state.

## First increment (this ADR's prototype)

`bforge cook` compiles a Recipe IR v1 document: canonicalize → hash inputs and
parameters → consult the content-addressed cache → execute steps on a Blender
worker → run the requirement gates → export → write the proof capsule. A cache
hit returns the verified proof without booting Blender. Recipes are JSON, not
YAML, because the tooling is deliberately stdlib-only
([ADR 0013](0013-dependency-license-policy.md)).

## What this is not (yet)

- Not a new engine. Official Godot stays upstream; the WebGPU series remains
  a replaceable distribution (ADR 0008).
- Not a USD/glTF replacement — World IR is the semantic contract between them.
- Not arbitrary runtime code generation: runtime creativity compiles
  constrained World IR data through approved systems, never model-emitted
  executable code into production state.
- Not photorealism chasing. Structure, semantics, determinism, editability,
  and proof are the durable advantage.

## Consequences

- Every production failure becomes a reusable gate, recipe, or proof field —
  institutional knowledge compounds in executable form.
- The public surfaces (README counts, bench numbers, proof capsules) are
  generated or gated, so the proof system proves itself.
- Benchmark results become comparable across models and across time because
  briefs, recipes, and hashes are frozen and published.
