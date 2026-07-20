# CLAUDE.md

Follow **[docs/agents/WORKING_AGREEMENTS.md](docs/agents/WORKING_AGREEMENTS.md)**
(source of truth). Skills for common workflows are in `.claude/skills/` (thin
pointers into `docs/agents/skills/`).

## Quick facts

- Front door: `just` (recipes listed by running it bare). Logic lives in
  `tools/` + `scripts/`; never put logic in the justfile or workflow YAML.
- Suites: `just test-godot` (headless GDScript), `just test-rust`,
  `just test-mcp`, `just test-python`, `just test-db` (needs `services-up`).
  Run the narrowest first; `just ci-local` before finishing.
- Godot tests: a parse error in any preloaded script can hang a scene-based
  runner SILENTLY. Our runner prints `[tests] runner alive` first — if that
  marker is missing, run the same command bare and read the first second of
  output. More pitfalls: `docs/architecture/gdscript-pitfalls.md`.
- Windows shell quirks: PowerShell 5.1 (no `&&`); prefer `just` recipes or
  Git-Bash. Piping cargo/npm through `tail` eats exit codes — capture to a
  file and `echo $?` instead.
- Rust on Windows: `x86_64-pc-windows-gnu`, pure-Rust deps only (ADR 0004).
  If `dlltool`/`as.exe` errors appear, re-run `scripts/bootstrap.ps1`.
- Never edit: `assets-generated/**`, `**/project/assets/generated/**`,
  `**/project/addons/studio_core/**` (synced copies — edit
  `shared/godot-addons/` then `just godot-sync-addons`), applied migrations.
- Protocol changes touch three places together: `services/shared-protocol`,
  `studio_core/net/protocol.gd`, `shared/protocol/fixtures/` (+ PROTOCOL.md).
- Commit style: imperative subject, body says why; never commit `.env`,
  exports, or `engine/.cache`.
