# studio-mcp

Local, stdlib-only MCP server exposing narrow, schema-validated studio
operations to AI agents. Security model: ADR 0009; configs for each agent tool:
[docs/agents/mcp/](../../docs/agents/mcp/README.md).

## Run

```sh
just mcp-serve          # stdio transport (what agent configs invoke)
just test-mcp           # protocol + security suite
python tools/studio-mcp/server.py --self-check
```

## Security properties (tested in tests/)

- stdio only; binds no network ports
- repository-relative paths only — traversal, absolute paths, and symlink
  escapes rejected before anything executes
- fixed argv allowlists per tool; no `shell=True`, no generic shell/eval/SQL/
  Python/GDScript/Blender-Python execution surface
- per-argument schemas (type/enum/pattern/range, unknown args rejected)
- execution timeouts on every subprocess; 64 KiB output cap
- SQL: single read-only statement, `studio_ro` role, `default_transaction_read_only=on`,
  local (127.0.0.1) databases only — production access is structurally absent
- `server_stop_local` only touches processes studio-mcp itself started (pidfiles)
- hours-long/destructive operations (engine builds) return guidance instead of
  executing; they run only via `just` in a human terminal
- audit log at `.mcp-log/studio-mcp.log` (gitignored) with secret-name redaction
