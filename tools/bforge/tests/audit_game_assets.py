"""Audit a game's existing GLB assets: import, measure, critique, render.

    python tools/bforge/tests/audit_game_assets.py games/chariot/project/assets/models

Answers the question you actually have about a shipping game: are these assets
any good, and what specifically is wrong with them?
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge import Forge, ForgeError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("--out", default="audit")
    parser.add_argument("--tile", type=int, default=300)
    parser.add_argument("--samples", type=int, default=14)
    parser.add_argument("--profile", default="browser_webgpu")
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args()

    root = Path(args.directory)
    files = sorted(p for p in root.rglob("*.glb")) + sorted(root.rglob("*.gltf"))
    if not files:
        print(f"no .glb/.gltf under {root}")
        return 1

    forge = Forge(workdir=".", out_dir="assets-generated/bforge")
    rows = []
    try:
        forge.start()
        for path in files:
            label = path.stem
            try:
                forge.call("session.reset")
                imported = forge.call("session.import", path=str(path), _timeout=600)
                critique = forge.call("check.critique", _timeout=600)
                budget = forge.call(
                    "gameready.budget", profile=args.profile, asset_class="environment"
                )
                row = {
                    "asset": label,
                    "file_kb": round(path.stat().st_size / 1024, 1),
                    "objects": len(imported["objects"]),
                    "triangles": imported["triangles"],
                    "materials": imported["materials"],
                    "armatures": imported["armatures"],
                    "within_budget": budget["within_budget"],
                    "errors": critique["errors"],
                    "warnings": critique["warnings"],
                    "findings": critique["findings"][:8],
                    "texel_densities": critique["texel_densities"],
                }
                if not args.no_render:
                    sheet = forge.call(
                        "render.contact_sheet",
                        out=f"{args.out}/{label}.png",
                        tile=args.tile,
                        samples=args.samples,
                        panels=["hero", "front", "top", "wireframe", "checker"],
                        columns=5,
                        _timeout=1800,
                    )
                    row["sheet"] = sheet["rel"]
                rows.append(row)
                print(
                    f"{label:22} {row['triangles']:>8} tris  {row['file_kb']:>7} KB  "
                    f"{len(row['materials'])} mats  "
                    f"{row['errors']}E/{row['warnings']}W  "
                    f"{'budget-ok' if row['within_budget'] else 'OVER BUDGET'}"
                )
                for finding in row["findings"][:4]:
                    print(
                        f"    [{finding['severity']:5}] {finding['issue']}: {finding['detail'][:96]}"
                    )
            except ForgeError as exc:
                rows.append({"asset": label, "error": str(exc)})
                print(f"{label:22} FAILED: {exc}")
    finally:
        forge.stop()

    report = Path("assets-generated/bforge") / f"{args.out}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nreport -> {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
