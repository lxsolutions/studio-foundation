"""Manual smoke run: boot the daemon, list ops, build one prop, render it.

python tools/bforge/tests/smoke.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge import Forge  # noqa: E402


def main() -> int:
    started = time.time()
    forge = Forge(workdir=".", out_dir="assets-generated/bforge", verbose=False)
    try:
        info = forge.start()
        print(f"READY in {time.time() - started:.1f}s: {json.dumps(info)}")
        ops = forge.catalog()
        print(f"OPS: {len(ops)}")
        by_tag: dict[str, list[str]] = {}
        for entry in ops:
            for tag in entry["tags"] or ["untagged"]:
                by_tag.setdefault(tag, []).append(entry["name"])
        for tag in sorted(by_tag):
            print(f"  {tag:12} {len(by_tag[tag]):3}  {', '.join(sorted(by_tag[tag])[:8])}")

        print("\n-- prop.crate --")
        t0 = time.time()
        result = forge.call("prop.crate", name="crate_a", size=[0.9, 0.9, 0.9], seed=7)
        print(f"{time.time() - t0:.2f}s  {json.dumps(result)}")

        print("\n-- check.critique --")
        critique = forge.call("check.critique")
        print(json.dumps(critique["findings"], indent=2)[:1500])

        print("\n-- render.view --")
        t0 = time.time()
        shot = forge.call(
            "render.view", out="smoke/crate.png", resolution=256, samples=8, _timeout=600
        )
        print(f"{time.time() - t0:.1f}s  {json.dumps(shot)}")
        return 0
    finally:
        forge.stop()


if __name__ == "__main__":
    sys.exit(main())
