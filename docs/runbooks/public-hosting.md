# Runbook: Host Asha World publicly (a link anyone can play)

Goal: a public URL where a stranger plays the vertical slice in their browser,
with the world-sim authoritative underneath. Two halves:

1. **Static WebGPU export** — must be served with cross-origin isolation headers
   (`Cross-Origin-Opener-Policy: same-origin` + `Cross-Origin-Embedder-Policy:
   require-corp`) or the threaded WebGPU build will not start. **GitHub Pages and
   most static hosts cannot set these** — that rules them out for the threaded build.
2. **World-sim server** — the WebSocket endpoint the client connects to
   (`?ws=` query param, see `AshaWorldConfig`). Must be publicly reachable (wss://
   for an https page; browsers block ws:// from https).

## The turnkey path (one container, any host)

`games/asha_world/deploy/Dockerfile` packages BOTH halves in one container:
the world-sim ws server (port 8081) and the static export with COOP/COEP (port 8080).

```sh
# 1. Build the export first (on a dev box):
just export-browser-webgpu GAME=games/asha_world

# 2. Build + run the container on any public host (VPS, Fly.io, Render, a home box
#    behind port-forward):
docker build -f games/asha_world/deploy/Dockerfile -t asha-world-server .
docker run -p 8080:8080 -p 8081:8081 \
  -e DATABASE_URL=postgres://user:pass@db-host:5432/studio \
  asha-world-server

# 3. Hand out the link (wss in front of an https page):
#    https://<your-host>:8080/?ws=wss://<your-host>:8081
```

Omit `DATABASE_URL` to run the world in-memory (resets on restart) — fine for a demo.

## Host options (honest trade-offs)

| Option | Headers (COOP/COEP) | World-server | Effort |
|---|---|---|---|
| **Your VPS / VM** (any provider) | yes (our container) | yes (same container) | lowest — recommended |
| **Fly.io / Render / Railway** | yes (container) | yes (container) | low — point their CLI at the Dockerfile |
| **Cloudflare Pages + Workers** | yes (Pages `_headers`) | Durable Object later | medium — needs your CF account |
| **itch.io** | partial (no custom headers) | no | client-only demo, world offline |
| **GitHub Pages** | **no** | no | client-only, threaded build won't boot |

For an https front-end, terminate TLS in front of both ports (Caddy/nginx/Cloudflare)
and use `wss://` for the world-server URL.

## After it's live

- Verify with `tests/browser/capture.mjs --url https://<host>/` (screenshot) and a
  manual playthrough: mine → refine → build → deploy → capture → territory flips.
- Record the public URL in BOOTSTRAP_REPORT.md as an evidence-backed "playable
  from a link" claim.
