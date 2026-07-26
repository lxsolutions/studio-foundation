# ADR 0015: Two consumption models for the foundation

- Status: Accepted
- Date: 2026-07-23
- Constrains: how game projects reference shared foundation code and assets

## Context

Game projects reuse the foundation's protocol crates, dedicated-server
extension, `studio_core` addon, and asset tooling. Generated projects have
referenced these by relative path since the first template, and several docs
(`games/*/docs/README.md`) already cite this ADR by number for that rule; this
file records the decision those citations point to.

A single consumption model cannot serve both ends of a game's life. Early
development wants zero-friction iteration on shared code; a stable game wants
its dependencies pinned so a foundation change cannot silently alter shipped
behavior.

## Decision

1. **Early development:** relative-path references to the shared platform
   inside the monorepo (path deps in `Cargo.toml`, the synced `studio_core`
   addon copy, `just` recipes). Zero-friction iteration on shared code.
2. **Stable games:** pin versioned releases of `studio-protocol` /
   `studio-dedicated-server` (git tags or a registry) and a released
   `studio_core` addon; upgrade deliberately.

Switching models is a dependency edit, not a restructure. Nothing in game code
may depend on the foundation repository's absolute filesystem location.

## Consequences

- A generated project works immediately inside the monorepo and can leave it
  without rewriting game code.
- Foundation refactors may move files freely; only relative-path consumers in
  the same tree need to follow, and pinned consumers are untouched until they
  choose to upgrade.
- Release tooling must produce versioned artifacts for the crates and the
  addon so the stable model has something to pin.
