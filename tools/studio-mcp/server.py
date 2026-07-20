#!/usr/bin/env python3
"""studio-mcp entry point (stdio transport only — bind-nothing by default).

Agent configs run: uv run --project tools python tools/studio-mcp/server.py
Self-check (used by doctor): server.py --self-check
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools import env as senv  # noqa: E402
from studio_tools.mcp import server_core  # noqa: E402


def main() -> int:
    senv.load_dotenv()
    if "--self-check" in sys.argv:
        return server_core.self_check()
    return server_core.serve_stdio()


if __name__ == "__main__":
    sys.exit(main())
