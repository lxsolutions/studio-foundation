# ADR 0008: Own the distribution, not the engine

- Status: Accepted
- Date: 2026-07-20
- Last amended: 2026-07-22
- Constrains: engine strategy, `engine/engine-lock.toml`, ADR 0002

## Context

Studio Foundation needs browser WebGPU ahead of official Godot support, but a
small team cannot responsibly maintain a general-purpose engine fork. The
historical 4.7.1 WebGPU port also showed that a second LX Solutions repository
added operational and documentation overhead without creating a useful product
boundary.

## Decision

1. Do not maintain a separate `lxsolutions/godot-webgpu` repository. Keep the
   scoped WebGPU integration as checksum-pinned patches inside Studio Foundation.
2. Do not present Studio Foundation as a fork of Godot. Official Godot remains
   the clean upstream editor and engine; patched source trees exist only as
   reproducible build inputs for browser templates.
3. Own the distribution layer around Godot: shared addons, editor and asset
   tooling, optional backend scaffolding, infrastructure, agent-readable
   commands, validation, and release evidence.
4. Keep the integration replaceable. If official Godot supplies a suitable
   WebGPU backend, remove the local patches without changing game architecture.

## Consequences

- `engine-lock.toml` records official base, source lineage, patch ordering, and
  checksums. It contains no active dependency on a deleted LX Solutions fork.
- Studio Foundation accepts maintenance responsibility for the exact local
  patches it ships, while retaining attribution to the original backend.
- Godot version updates follow
  `docs/runbooks/godot-webgpu-update.md`.
- Public claims describe measured capabilities and current evidence, not
  exclusivity, market position, or ownership of Godot itself.

## Alternatives rejected

- Keep a separate backend fork: it duplicates repository administration and can
  make the real source of truth ambiguous.
- Fork all of Godot: it expands responsibility to editor, import, physics,
  platform, and export systems that Studio Foundation does not need to own.
- Replace Godot in this public repository with a JavaScript engine: that is a
  product-level choice for other repositories, not this foundation's mandate.