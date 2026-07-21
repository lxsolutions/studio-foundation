#!/bin/sh
# Start the world-sim server and the static export server together.
set -e

/app/server &
SERVER_PID=$!

# Static export with COOP/COEP headers (serve_web.py binds a port; game/preset
# are already baked into /app/web, so serve it directly).
python3 - "$@" <<'PY' &
import http.server, functools, sys
class H(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".wasm": "application/wasm", ".pck": "application/octet-stream"}
    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()
http.server.ThreadingHTTPServer(("0.0.0.0", 8080),
    functools.partial(H, directory="/app/web")).serve_forever()
PY
WEB_PID=$!

trap "kill $SERVER_PID $WEB_PID" INT TERM
wait $SERVER_PID
