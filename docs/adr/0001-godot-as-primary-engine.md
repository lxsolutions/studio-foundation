# ADR 0001: Godot 4.x (official stable) as the primary engine

- Status: Accepted
- Date: 2026-07-19

## Context

We need one engine that ships the same game project to web, iOS, Android, Windows,
Linux, macOS, and headless servers, under FOSS-first and commercial-compatible
licensing, maintainable by a small human team plus AI agents.

Alternatives considered:

- **Unity / Unreal** — proprietary licensing/royalties, opaque source (Unity) or
  copyleft-adjacent terms (Unreal EULA); violates principles 1–4.
- **Bevy (Rust)** — permissive and technically strong, but no mature editor, unstable
  APIs, weak mobile/web export story for artists and agents; content iteration cost is
  too high for a content-heavy ARPG/MMO studio today.
- **Custom engine** — explicitly out of scope (GOAL.md principle 14).

## Decision

Official stable **Godot 4.x** is the studio engine. The pinned version lives in
`engine/engine-lock.toml` (currently `4.7.1-stable`, commit `a13da4feb…`), which is also
the latest upstream stable as of this ADR. Godot is MIT-licensed, has first-class
mobile + desktop + web exports, headless mode for CI/servers-side tooling, and a
scriptable editor.

## Consequences

- All game projects must open and pass tests in the pinned official editor. The WebGPU
  Studio patch series (ADR 0002) is an export backend, never the editor of record.
- Engine upgrades are deliberate: bump `engine-lock.toml`, run full test + export +
  visual-regression suites, record results, then merge.
- Godot's Mobile renderer feature set is the common modern baseline across platforms
  (revisit only when cross-platform benchmarks justify it).
- We accept Godot's constraints (GDScript performance ceilings → ADR 0003 hotspot
  policy; export template management → `engine/` scripts).

## Revisit when

- A game's measured needs exceed what Godot + C++ modules can deliver, or
- Godot licensing/governance changes materially.
