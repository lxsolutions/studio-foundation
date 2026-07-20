#!/usr/bin/env python3
"""Serve a web export locally with the headers browser Godot builds need
(COOP/COEP for SharedArrayBuffer-threaded builds; correct wasm MIME).

  python tools/godot/serve_web.py --game templates/godot-game [--preset web-webgl]
Binds 127.0.0.1 only, by design.
"""

from __future__ import annotations

import argparse
import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools import env as senv  # noqa: E402


class GodotWebHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".wasm": "application/wasm",
        ".pck": "application/octet-stream",
    }

    def end_headers(self) -> None:
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:  # quieter default
        sys.stderr.write("  http: " + fmt % args + "\n")


def serve_dir(game: str, preset: str) -> Path:
    root = senv.repo_root() / game
    project = root / "project" if (root / "project").is_dir() else root
    export_dir = project / "exports" / preset
    if not (export_dir / "index.html").is_file():
        raise SystemExit(
            f"no export at {export_dir} — run: just export-browser-{preset.split('-')[1]} GAME={game}"
        )
    return export_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", default="templates/godot-game")
    parser.add_argument("--preset", default="web-webgl")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    senv.load_dotenv()
    port = args.port or int(os.environ.get("STUDIO_WEB_SERVE_PORT", "8060"))
    directory = serve_dir(args.game, args.preset)
    handler = partial(GodotWebHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"serving {directory}\n  -> http://127.0.0.1:{server.server_address[1]}/  (Ctrl+C stops)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
