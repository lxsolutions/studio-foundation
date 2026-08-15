# Studio Foundation verification report

Last updated: 2026-08-15

This report separates verified repository behavior from work still in progress.
It is not a product roadmap. The numbers it and the README state publicly are
enforced against the pinned artifacts by `tools/ci/check_claims.py`
(rules: `docs/claims.toml`), so this file cannot quietly drift from the code
again.

## Public scope

Studio Foundation contains reusable Godot integration, a neutral project
template, asset/export/release tooling, mechanics-neutral transport and service
scaffolding, optional provider adapters, the bforge headless-Blender asset
forge, and their tests.

It does not define a game's content, entities, mechanics, domain schema,
identity policy, persistence semantics, or production deployment. The optional
server and Nakama adapter carry opaque application payloads supplied by a
consumer.

## Verified

| Area | Evidence |
|---|---|
| Official engine source | Godot 4.7.1 stable commit `a13da4feb8d8aefc283c3763d33a2f170a18d541` is the sole active upstream pin |
| WebGPU patch series | 33 ordered patches (`engine/patches/0001`–`0033`), each SHA-256-locked in `engine-lock.toml`; `.github/workflows/patch-series.yml` re-verifies checksums and a clean-tree apply on every push and PR |
| Build configuration | WebGPU templates explicitly use `webgpu=yes`, `opengl3=no`, and `threads=no` |
| Template installation | The installer selects only the archive matching the lock's thread mode and rejects archives missing the WebGPU loader bridge or compiled backend marker |
| Export templates | The accepted release/debug pair is recorded by filename, byte count, and SHA-256 in `engine-lock.toml [artifacts.export_templates]`; the same pair is published as release `godot-4.7.1-webgpu-p0033` |
| 3D render, Forward Mobile | Verified in-browser on an NVIDIA Tesla P40: a minimal PBR + shadow scene at 59–60 fps / 36 draws per frame, and a full game (The Chariot Club) at a locked 60 fps, ~490–630 draws and ~23M primitives per frame — both with 0 `GPUValidationError` |
| 3D render, Forward+ | First verified frame 2026-07-28, patch series 0023–0033, Tesla P40, headed Chrome/WebGPU, non-fallback adapter: the clustered renderer presents at 59 fps, 188 objects / 2,015,266 primitives, with 0 invalid `commandEncoder.finish` out of 10,842, 0 rejected `queue.submit`, and 0 bind-group failure classes. **Three WebGPU validation errors remain outside the presented-frame path** |
| WebGPU shader coverage | 199 of 205 shader modules translate to valid WGSL offline with 0 GLSL compile failures, measured at the engine's real target env (Vulkan 1.1 / SPIR-V 1.3). None of the 6 remaining failures blocks Forward+: two are Forward Mobile's subpass tonemap, one is FSR's 16-bit variant (fallback translates), two are subgroup variants WebGPU does not select, one is an editor debug gizmo |
| bforge determinism | `tools/bforge/bench.py` runs six briefs twice through the persistent daemon; all six pass the quality gate and the two GLB exports hash byte-identical (SHA-256 in `bench/report.json`). CI installs the pinned Blender 4.5.12 LTS, reruns the bench, and diffs the committed summary |
| bforge surface | 138 whitelisted, typed operations across 21 namespaces; the committed `catalog.json` is checked against the live registry by full-schema comparison (not just op names), and `docs/bforge/OPS.md` is a generated file with a freshness gate |
| bforge tests | 224 test methods in `tools/bforge/tests` — 177 in suites that boot a real Blender daemon, the rest pure schema/protocol/compiler units; the public CI bench job runs the full suite, not a subset |
| Browser evidence | The runtime probe instruments engine-owned adapter, device, and canvas-context requests, rejects fallback adapters and any WebGL request, and reports `inconclusive` rather than passing on incomplete evidence |
| Prose/artifact consistency | `tools/ci/check_claims.py` derives op, namespace, test, and patch counts from the pinned artifacts and fails the hosted policy job when a documented surface disagrees; absolute-exclusivity claims ("only public …") are rejected outright |
| Optional Nakama bridge | The bridge carries opaque consumer-owned payloads and remains optional |

## Engine lineage

Official Godot is upstream. Studio Foundation has no active dependency on a
separate LX Solutions engine fork. Historical MIT-licensed WebGPU lineage is
retained in [NOTICE.md](NOTICE.md); the maintained 4.7.1 delta, patch curation,
build commands, fallback, and validation live in this repository.

## External game status

OSWT is an external demo candidate, not accepted WebGPU proof. Independent live
inspection found that the current Asha Arena OSWT route requests WebGL 2. It has
not been overwritten or relabeled. A future proof release must use a clean
locked template, pass the engine-owned context instrumentation, and publish
matching source and artifact provenance.

## Not yet claimed

- Forward+ on any GPU other than the one NVIDIA Tesla P40 — AMD, Intel, and Apple are unmeasured, and the verification matrix so far is one scene class, one browser (headed Chrome), one OS
- The Forward+ D24 fallback on adapters without `depth32float-stencil8` (implemented in patch 0028; the verification box has the feature, so the fallback path has never run)
- The three remaining WebGPU validation errors outside the presented-frame path
- Safari/iOS WebGPU behavior
- Native Android and iOS device runs
- A published OSWT (or other real-game) WebGPU capture and deployment produced from the accepted templates
- Database-backed integration tests against a live disposable PostgreSQL stack
- Console support beyond the documented licensed-provider path

## Reproduce the fast evidence

```sh
just test
just lint
just check-claims
just test-generated
just release-validate --allow-dirty
```

The longer engine sequence is:

```sh
just engine-fetch
just engine-build
just engine-validate
just engine-record-artifacts
just release-validate --allow-dirty
```

A WebGPU screenshot is accepted only when the runtime probe confirms engine-owned
adapter, device, and WebGPU canvas-context requests with no WebGL request.
