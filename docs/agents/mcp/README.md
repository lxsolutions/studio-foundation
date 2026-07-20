# MCP integrations

MCP servers are **privileged software**: reviewed, pinned, least-privilege.
Security model: ADR 0009. Never commit tokens or machine-specific absolute
paths in MCP configs.

## studio-mcp (local, ours)

Stdio-only, stdlib-only, allowlisted tools (see
[tools/studio-mcp/README.md](../../../tools/studio-mcp/README.md)). The
committed [.mcp.json](../../../.mcp.json) enables it for Claude Code
automatically (project scope, approval prompted on first use).

**Codex** (`~/.codex/config.toml`):

```toml
[mcp_servers.studio]
command = "uv"
args = ["run", "--project", "tools", "python", "tools/studio-mcp/server.py"]
# cwd must be the repository root when launching codex
```

**Kimi Code**: see [kimi.md](kimi.md) for the currently-supported configuration
format (verified against Kimi's docs; re-verify on Kimi CLI updates).

## GitHub (official server)

Use GitHub's official MCP server with a **least-privilege fine-grained PAT**
(contents: read, issues: RW, pull_requests: RW on studio repos only — no admin,
no delete). Two supported modes:

- Hosted (OAuth, recommended): `claude mcp add --transport http github https://api.githubcopilot.com/mcp/`
- Local docker: pin the image digest in your user config:

```json
{
  "mcpServers": {
    "github": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
               "ghcr.io/github/github-mcp-server:v0.26.3"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PAT}" }
    }
  }
}
```

The token comes from your user environment — never from a committed file.

## Playwright (official Microsoft server)

Local stdio only; never exposed on a network interface. Uses an **isolated
browser profile** (the server's default is isolated; do not point it at your
personal profile) and the system Chrome/Edge channel so no browser downloads
are needed:

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp@0.0.41", "--browser=chrome", "--isolated"]
    }
  }
}
```

Pin the exact `@playwright/mcp` version in your user config and update it
deliberately (`npm view @playwright/mcp version` to check current; record
bumps in the dependency table).

## Rules that apply to every MCP server

- Local/stdio by default; anything network-exposed needs an ADR.
- No production credentials, ever. Database access = local dev, read-only role.
- Community Blender MCP servers stay **disabled**: unaudited remote code
  execution inside Blender. The supported automation path is our whitelisted
  scripts under `tools/blender/` (ADR 0006/0009).
