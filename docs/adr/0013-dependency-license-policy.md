# ADR 0013: Dependency and license policy

- Status: Accepted
- Date: 2026-07-21

## Context

The platform combines Rust services, Python developer tools, npm browser tests,
Godot, Blender, and a separately licensed proprietary game tree. Release claims
must come from resolved lockfiles, and dependency security checks must not
silently become no-ops when an optional local utility is absent.

## Decision

- Platform code remains dual MIT and CC BY 4.0; games/ remains governed by
  games/LICENSE unless a game supplies its own license.
- Linked/runtime dependencies require reviewed SPDX license expressions.
  Approved permissive identifiers are MIT, MIT-0, Apache-2.0 (including the
  LLVM exception), BSD-2-Clause, BSD-3-Clause, 0BSD, ISC, Zlib, PostgreSQL,
  Unicode-3.0, CC0-1.0, Unlicense, BSL-1.0, and CDLA-Permissive-2.0.
- GPL/AGPL/LGPL or other reciprocal dependencies require a new ADR documenting
  their boundary. GPL developer applications such as Blender and Git may be
  used only as standalone processes; their code is not linked into a product.
- Every direct dependency change updates
  docs/architecture/dependency-licenses.md with purpose, license,
  maintenance health, and rejected alternatives.
- just sbom and just attribution derive their inventories from committed
  Cargo, uv, npm, and engine lockfiles. Unknown third-party licenses fail the
  release gate.
- just audit queries the OSV batch API for exact Cargo, PyPI, and npm package
  versions. Network or malformed advisory responses fail closed; an unavailable
  advisory service is never reported as a clean audit.
- These automated checks are engineering controls, not legal advice. Release
  owners still retain upstream license texts and perform product-specific
  review.

## Consequences

Release inventory generation needs Cargo package metadata and may fetch missing
registry metadata without changing lockfiles. Vulnerability audit requires
network access to OSV.dev. Generated SBOM and attribution files live under
build/ and are reproducible from the committed dependency inputs except for
the SPDX creation timestamp.
