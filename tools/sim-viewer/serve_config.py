#!/usr/bin/env python3
"""Write tools/sim-viewer/config.json after compiling the fortress world.

The viewer page fetches this to know which kernel, replay, entity doc, scene
layout, and forged GLB to observe. Run via `just sim-viewer`.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VIEWER = REPO / "tools" / "sim-viewer"


def main() -> int:
    glbs = sorted(
        (REPO / "tools" / "worldc" / "cache" / "asset-cache" / "objects").glob(
            "*/fortress_gate.glb"
        )
    )
    if not glbs:
        raise SystemExit("no fortress_gate.glb in the asset cache — run `just worldc-world` first")
    glb = glbs[0]
    config = {
        "wasm": "/services/target/wasm32-unknown-unknown/release/sim_kernel.wasm",
        "replay": "/tools/worldc/examples/fortress_battle.json",
        "entityDoc": "/tools/worldc/examples/fortress_gate.json",
        # The entity name the layout refers to, and the placement itself. Scene
        # placement is data, not renderer code: it is what stops a viewer from
        # inventing which way a leaf swings (ADR 0020).
        "entityName": "fortress_gate",
        "layout": "/tools/sim-viewer/fortress_layout.json",
        "glbDir": "/" + glb.parent.relative_to(REPO).as_posix() + "/",
        "glb": glb.name,
    }
    out = VIEWER / "config.json"
    out.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    print("open http://localhost:8077/tools/sim-viewer/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
