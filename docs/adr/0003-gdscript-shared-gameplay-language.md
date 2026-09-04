# ADR 0003: GDScript as the shared gameplay language

- Status: Accepted
- Date: 2026-07-19
- Extended by: [ADR 0019](0019-compiled-gameplay-on-the-web.md), which explains *why*
  .NET cannot ship to the browser (Godot's runtime and .NET's both need the
  WebAssembly main-module slot) and says where the requirement C# was carrying —
  typed, compiled rules shared by client and server — goes instead.

## Context

Client code must run everywhere — including browsers. Godot's C#/.NET support does not
cover web export, and a per-platform language split would violate the one-project rule.

The web-export limit is architectural, not a gap someone will close with a template:
a page has one WebAssembly main module, and Godot's Emscripten runtime and the .NET
runtime are both built to be it. ADR 0019 covers the mechanism and the consequences.

## Decision

- **GDScript** (typed, warnings-as-errors) for gameplay, UI, content orchestration, and
  editor tooling.
- **Godot shading language** for effects.
- **C++ (engine modules or GDExtension)** only for *measured* hotspots: a profile
  capture demonstrating the cost must be attached to the PR that introduces native
  code, plus a GDScript reference implementation or golden tests to pin behavior.
- **No C# in shared client code.** A game may not add C# without an ADR that also
  removes browser from its platform list. `tools/godot/export_game.py` refuses a
  `.csproj`/`[dotnet]` project on a web preset and explains why (ADR 0019).
- **Compiled, cross-target gameplay rules** belong in the deterministic sim kernel
  (`services/sim-kernel`), which the client reaches through `StudioSimKernel`. It
  compiles to a zero-import module, so it loads inside a Godot web export instead
  of competing with it for the main-module slot — the path C# does not have.
- GDExtension caution for web: extensions require `dlink_enabled=yes` web builds and
  are a known browser-compat risk; browser-targeted games prefer engine-module patches
  (via `engine/patches/`) over GDExtension for web-critical hotspots.

## Style rules (enforced by hooks/CI)

- Static typing required; `treat_warnings_as_errors` is on in template projects.
- Known footguns documented in `docs/architecture/gdscript-pitfalls.md` (Packed*Array
  copy-on-write value semantics; `var x := dict.get(...)` Variant-inference parse
  errors; per-function local scope).

## Consequences

- Single gameplay codebase per game across all seven targets.
- Performance ceilings are handled by design (data-oriented GDScript, server
  authority) first, native hotspots second.
- AI agents get one language surface with strict static checks — better generation
  and review quality.
