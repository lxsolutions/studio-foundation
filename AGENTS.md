# Agent instructions (Codex, Kimi Code, and compatible agents)

Follow **[docs/agents/WORKING_AGREEMENTS.md](docs/agents/WORKING_AGREEMENTS.md)** —
it is the source of truth. Summary of the non-negotiables:

- Read `GOAL.md` + relevant ADRs before major work; search for existing code
  before adding new code; state acceptance criteria first.
- Tests accompany every change. Narrow suite first, `just ci-local` before done.
- Never: silently change APIs/serialized formats, edit applied migrations,
  edit generated dirs, store secrets, merge your own PR.
- New dependencies require a license/health row in
  `docs/architecture/dependency-licenses.md`.

## Commands

`just` lists everything. Most used: `just doctor` · `just test` ·
`just test-godot` / `test-rust` / `test-mcp` · `just lint` · `just services-up`
· `just asset-cook` · `just export-browser-webgl` · `just ci-local`.

Reusable step-by-step workflows (exports, engine rebuilds, migrations, triage):
[docs/agents/skills/](docs/agents/skills/). MCP setup:
[docs/agents/mcp/](docs/agents/mcp/README.md).

Machine notes: Windows uses Rust `windows-gnu` (pure-Rust workspace policy);
Godot/Blender resolved via `.env` (`GODOT_BIN`/`BLENDER_BIN`) if not on PATH.
