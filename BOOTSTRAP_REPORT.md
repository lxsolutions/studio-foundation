# Studio Foundation verification report

Last updated: 2026-07-22

This report separates verified repository behavior from work still in progress.
It is not a product roadmap.

## Public scope

Studio Foundation contains reusable Godot integration, a neutral project
template, asset/export/release tooling, mechanics-neutral transport and service
scaffolding, optional provider adapters, and their tests.

It does not define a game's content, entities, mechanics, domain schema,
identity policy, persistence semantics, or production deployment. The optional
server and Nakama adapter carry opaque application payloads supplied by a
consumer.

## Verified in this change

| Area | Evidence |
|---|---|
| Official engine source | Godot 4.7.1 stable commit `a13da4feb8d8aefc283c3763d33a2f170a18d541` is the sole active upstream pin |
| WebGPU source preparation | Seven checksum-pinned patches pass path-containment, reusable-source preparation, candidate-isolation, dry-run, resume, and conflict-handling tests |
| Build configuration | WebGPU templates explicitly use `webgpu=yes`, `opengl3=no`, and `threads=no` |
| Template installation | The installer selects only the archive matching the lock's thread mode and rejects archives missing the WebGPU loader bridge or compiled backend marker |
| Browser evidence | The smoke test instruments engine-owned adapter, device, and canvas-context requests and rejects any WebGL/WebGL 2 request |
| Artifact acceptance | The recorder requires a complete release/debug pair; the artifact lock has no accepted entries while the runtime gate is red |
| Current engine result | A no-threads build reaches a WebGPU adapter, device, canvas context, and the Mobile renderer without requesting WebGL; startup then fails in Tint texture lowering at `texture.cc:606` |
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

- A WebGPU runtime that completes shader translation and reaches an interactive frame
- Accepted release/debug WebGPU template artifacts and checksums
- A published OSWT WebGPU capture and deployment produced from those exact templates
- Safari/iOS WebGPU behavior
- Native Android and iOS device runs
- Database-backed integration tests against a live disposable PostgreSQL stack
- Console support beyond the documented licensed-provider path

## Reproduce the fast evidence

```sh
just test
just lint
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