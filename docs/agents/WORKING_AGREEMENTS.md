# Working agreements (humans and AI agents)

The single source of truth for how work happens here. `AGENTS.md` (Codex/Kimi)
and `CLAUDE.md` (Claude Code) are thin pointers to this file. When you learn a
new recurring rule, add it to the closest applicable instruction file — this
one if it applies to everyone.

## Before major work

1. Read `GOAL.md`, the relevant `docs/architecture/` pages, and the ADRs your
   change touches (`docs/adr/`). If your change contradicts an ADR, update the
   ADR in the same PR or don't make the change.
2. **Search for an existing implementation before writing a new one** —
   `studio_core`, `tools/pylib/studio_tools`, and `services/` already cover
   boot, config, logging, transport, validation, and subprocess plumbing.
3. For multi-file or architectural work: write a short execution plan and
   **state acceptance criteria before implementing**.

## While working

4. Add or update tests with every behavior change. New subsystem = new test file.
5. Run the narrowest relevant suite first (`just test-godot`, `just test-rust`,
   `just test-mcp`, `just test-python`), then `just ci-local` before completion.
6. **Never silently change an API or serialized format.** Protocol changes
   follow `shared/protocol/PROTOCOL.md` (fixtures + both implementations + ADR
   note). Save/config schema changes bump versions with migration hooks.
7. Database changes are **new** migrations (`NNNN_snake_case.sql`) — never edit
   an applied migration, never hand-modify database state (ADR 0005).
8. Respect performance budgets (`shared/godot-addons/studio_core/profiles.json`,
   `tests/performance/budgets.json`). If a budget must move, move it in a
   reviewed commit that says why.
9. New dependency? Document purpose, license, maintenance health, and the
   alternatives you rejected in `docs/architecture/dependency-licenses.md`
   (same PR). Permissive licenses only without an ADR (ADR 0013).
10. **Never store secrets** in the repo — including tests, fixtures, examples,
    and MCP configs. `.env` is gitignored; only `*.example` files are committed.
11. **Never edit generated outputs**: `assets-generated/`, `project/assets/generated/`,
    `project/addons/studio_core/` (synced), `exports/`, lockfiles by hand. Fix
    the source and regenerate. The pre-commit hook enforces this.
12. GDScript: typed, tab-indented, no game code in `studio_core`. Read
    `docs/architecture/gdscript-pitfalls.md` once — it is paid-for knowledge.
13. Platform differences go behind `StudioPlatform` / render profiles /
    `StudioTransport` — game code never sniffs OS names or fork-only APIs (ADR 0002).

## Finishing

14. **Never merge your own changes.** Open a PR; a human (or a designated
    reviewer agent with human sign-off) merges.
15. Keep PRs focused: one concern, reviewable in one sitting. Split refactors
    from behavior changes.
16. Update documentation in the same PR when behavior or architecture changes
    (README tables, runbooks, ADRs, this file).
17. Leave an implementation report in the PR description: commands run, tests
    passed (paste the summary lines), remaining risks, and rollback
    instructions.
18. If CI fails, fix it or revert — never leave main red overnight.

## Environment facts agents need

- Task runner front door: `just` (see README table). Business logic lives in
  `tools/` and `scripts/`, never in the justfile or workflow YAML.
- Godot/Blender are discovered via PATH, winget/Program Files conventions, or
  `.env` (`GODOT_BIN`, `BLENDER_BIN`). Never hardcode machine paths in
  committed files.
- Windows Rust host is `x86_64-pc-windows-gnu`; the workspace stays pure-Rust
  (no C-compiling crates) — see ADR 0004 before adding any dependency.
- Local services bind 127.0.0.1 only. Tests bind port 0 (ephemeral), never
  fixed ports, and pin `127.0.0.1` — not `localhost` — in URLs.
- Reusable task recipes live in `docs/agents/skills/` — check there before
  reconstructing a workflow from scratch.
