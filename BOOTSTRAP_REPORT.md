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
| WebGPU source preparation | Patch checksums, path containment, reusable-source preparation, candidate isolation, dry-run, resume, and conflict handling pass the engine-tool tests |
| Release template record | `godot.web.template_release.webgpu.zip`: 9,884,813 bytes; SHA-256 `86674b227822ada41b3d9326dbfe3a70e2d8e1bb8711288e34027688939a2acd` |
| Debug template record | `godot.web.template_debug.webgpu.zip`: 9,878,960 bytes; SHA-256 `dc4b60daa92593a491dc2863560d45a9271bcefbbd5df78a88de3a1d23207065` |
| Artifact acceptance | The recorder requires a complete release/debug pair; release validation checks metadata and verifies matching local files |
| Shared protocol v2 | Nine golden fixtures pass Rust, GDScript, and fixture-set validation |
| Godot template | Godot 4.7.1 imports cleanly; 25 test methods and 137 assertions pass |
| Rust service workspace | 16 fast tests pass; two PostgreSQL integration tests remain explicitly ignored without a live database |
| Generated server template | The standalone server test passes against its regenerated lockfile |
| Optional Nakama bridge | Six ES5 runtime tests and four Python probe tests pass |
| Infrastructure tools | Five local/remote Compose and database lifecycle tests pass |
| OSWT browser proof | Clean Foundation `61a92fa` and OSWT `a93d550` commits export with the locked template; Chrome reports `navigator.gpu`, an adapter, and an active WebGPU canvas context |

## Engine lineage

Official Godot is upstream. Studio Foundation has no active dependency on a
separate LX Solutions engine fork. Historical MIT-licensed WebGPU lineage is
retained in [NOTICE.md](NOTICE.md); the maintained 4.7.1 delta, patch curation,
build commands, fallback, and validation live in this repository.

## External game proof

The separate [OSWT integration branch](https://github.com/lxsolutions/OSWT/tree/studio-foundation-webgpu-demo)
is rebased onto Devon Rowkowski's `f6f8fe9` update. It passes 103/103 headless
gameplay and proof checks, exports from clean Foundation and OSWT commits using
the locked WebGPU template, and passes the strict Chrome WebGPU probe. Its
generated provenance records both source commits, patch/template hashes,
exported artifact hashes, and verification results. A hosted deployment is not
claimed yet.

## Not yet claimed

- A published OSWT browser capture produced from the exact locked templates
- A public OSWT deployment with a hosted provenance record
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

A WebGPU screenshot is accepted only when the runtime probe confirms the WebGPU
API, an adapter, and an active WebGPU canvas context.
