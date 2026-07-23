# Studio Foundation verification report

Last updated: 2026-07-22

This report separates verified repository behavior from work still in progress.
It is not a product roadmap.

## Public scope

Studio Foundation is a mechanics-neutral Godot toolkit. The public release
surface contains:

- official Godot pinning and a checksummed WebGPU patch series
- shared Godot addons and a neutral project template
- asset, export, browser, release, and agent tooling
- a versioned handshake/transport protocol with an opaque application hook
- optional Rust API, session, persistence, and administration scaffolding
- optional PostgreSQL, Nakama, and tracing development infrastructure

Game content, domain schemas, business rules, identity policy, and production
deployment configuration belong in consuming repositories. ADR 0014 records
this boundary.

## Verified in this change

| Area | Evidence |
|---|---|
| Official engine source | Godot 4.7.1 stable commit `a13da4feb8d8aefc283c3763d33a2f170a18d541` is the sole active upstream pin |
| WebGPU source preparation | Patch checksums, path containment, reusable-source preparation, candidate isolation, dry-run, resume, and conflict handling pass the engine-tool tests |
| Shared protocol v2 | Nine golden fixtures pass Rust, GDScript, and fixture-set validation |
| Godot template | Godot 4.7.1 imports cleanly; 25 test methods and 137 assertions pass |
| Rust service workspace | 16 fast tests pass; two PostgreSQL integration tests remain explicitly ignored without a live database |
| Generated server template | Standalone server test passes against the regenerated lockfile |
| Optional Nakama bridge | Six ES5 runtime tests and four Python probe tests pass |
| Infrastructure tools | Five local/remote Compose and database lifecycle tests pass |
| Workflow policy | Representative generic workflow passes trigger, immutable-action-pin, and self-hosted trust-boundary validation |
| Python tooling | Engine, release, security, generator, CI, connectivity, benchmark, and MCP unit suites pass after the generic workflow was installed |
| Browser capture guard | WebGPU capture requires `navigator.gpu`, a usable adapter, and an active WebGPU canvas context before accepting evidence |

## Engine lineage and responsibility

Official Godot is upstream. Studio Foundation does not depend on a separate LX
Solutions engine fork. The local patch series retains required historical
attribution in [NOTICE.md](NOTICE.md), while this repository owns the 4.7.1
forward port, patch curation, build orchestration, fallback, and validation
surface it ships.

## External consuming proof

OSWT is maintained in a separate game repository and is not embedded into the
Foundation tree. Its integration branch currently passes 55 headless gameplay
checks and includes a runtime proof panel. Publishing it as current WebGPU
evidence remains gated on fresh locked templates, strict browser validation,
and a clean provenance record.

## Not yet claimed

The following require additional evidence before a public claim is upgraded:

- fresh release and debug WebGPU template archives from the current lock
- WebGPU browser capture from those exact archives
- OSWT redeployment from a clean Foundation and OSWT commit pair
- Safari/iOS WebGPU behavior
- native Android and iOS device runs
- database-backed integration tests against a live disposable PostgreSQL stack
- console support beyond the documented licensed-provider path

## Reproduce the fast evidence

```sh
just test
just lint
just test-generated
just release-validate --allow-dirty
```

Engine evidence uses the longer sequence:

```sh
just engine-fetch
just engine-build
just engine-validate
```

A WebGPU screenshot is accepted only when the strict runtime probe confirms the
WebGPU API, adapter, and canvas context.
