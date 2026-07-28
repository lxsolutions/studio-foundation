#!/usr/bin/env python3
"""One command that answers "does this build render?" and writes down the answer.

Reproducing the Forward+ result used to take five manual steps: serve the export,
launch a browser with the right flags, run the probe, run the binding trace, read
two JSON blobs. Every step was a place to diverge, and a reproduction that
diverges is not a reproduction.

This runs the whole gate and emits ONE evidence file, so a result from someone
else's machine is directly comparable to ours field by field. It also records
what the run could not establish, because a reproduction attempt that fails
halfway is still useful evidence and should not be silently discarded.

  verify_renderer.py --game games/chariot --renderer forward_plus

Exit status:
  0  rendered
  1  not rendered -- a definite negative
  2  inconclusive -- the run proved neither, and says why
  3  preconditions missing (no templates, no node, no browser)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools import env as senv  # noqa: E402

REPO = senv.repo_root()
BROWSER_DIR = REPO / "tests" / "browser"


def _free_port() -> int:
    with closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _preconditions(renderer: str) -> list[str]:
    """Everything that must be true before a result can mean anything."""
    problems = []
    templates = REPO / "engine" / "artifacts" / "templates"
    if not templates.is_dir() or not any(templates.glob("*web*.zip")):
        problems.append(
            "no WebGPU export templates in engine/artifacts/templates — download them "
            "from the latest release or run `just engine-build`"
        )
    if not shutil.which("node"):
        problems.append("node is not on PATH (needed for the browser probe)")
    if not (BROWSER_DIR / "node_modules" / "playwright").is_dir() and not (
        BROWSER_DIR / "node_modules" / "playwright-core"
    ).is_dir():
        problems.append(f"playwright is not installed — run `npm ci` in {BROWSER_DIR}")
    if not senv.find_godot():
        problems.append("Godot editor binary not found (set GODOT_BIN, or run `just doctor`)")
    if renderer == "forward_plus" and os.name != "nt" and not shutil.which("xvfb-run"):
        # Not fatal: a real display works too. Worth saying, since headless
        # Chrome silently falls back to a software adapter and the probe will
        # then refuse to report a hardware result.
        problems.append(
            "NOTE xvfb-run not found — the probe needs a real or virtual display; "
            "headless falls back to a software adapter and will be reported inconclusive"
        )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", default="games/chariot")
    parser.add_argument("--renderer", default="forward_plus", choices=["forward_plus", "mobile"])
    parser.add_argument("--seconds", type=int, default=45, help="observation window; cold start alone can take ~20s")
    parser.add_argument("--out", default="verification/renderer", help="directory for the evidence file")
    parser.add_argument("--skip-export", action="store_true", help="reuse an existing export")
    args = parser.parse_args()

    senv.load_dotenv()
    out_dir = REPO / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    label = f"{Path(args.game).name}-{args.renderer}"

    evidence: dict = {
        "schema": 1,
        "label": label,
        "game": args.game,
        "renderer_requested": args.renderer,
        "recorded_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "host": {"platform": sys.platform},
    }

    # Preconditions first: a missing browser must not be reported as "does not render".
    problems = [p for p in _preconditions(args.renderer) if not p.startswith("NOTE")]
    notes = [p for p in _preconditions(args.renderer) if p.startswith("NOTE")]
    evidence["notes"] = notes
    if problems:
        evidence["verdict"] = "inconclusive"
        evidence["verdict_reason"] = "preconditions not met"
        evidence["preconditions_missing"] = problems
        (out_dir / f"{label}.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print("cannot verify — preconditions not met:")
        for p in problems:
            print(f"  - {p}")
        return 3

    # Which patch series produced the templates being tested. Without this a
    # result cannot be attributed to a build.
    try:
        from studio_tools.provenance import series_from_lock, series_id  # noqa: PLC0415
        import tomllib  # noqa: PLC0415

        with (REPO / "engine" / "engine-lock.toml").open("rb") as fh:
            evidence["series_id"] = series_id(*series_from_lock(tomllib.load(fh)))
    except Exception as exc:  # pragma: no cover - provenance is advisory here
        evidence["series_id"] = None
        evidence["notes"].append(f"NOTE could not compute series id: {exc}")

    project = REPO / args.game / "project"
    export_dir = project / "exports" / "web-webgpu"

    if not args.skip_export:
        print(f"[verify] exporting {args.game} with --rendering-method {args.renderer}")
        rc = subprocess.call(
            [sys.executable, str(REPO / "tools" / "godot" / "export_game.py"),
             "--game", args.game, "--preset", "web-webgpu", "--rendering-method", args.renderer],
            cwd=REPO,
        )
        if rc != 0:
            evidence["verdict"] = "inconclusive"
            evidence["verdict_reason"] = f"export failed (exit {rc})"
            (out_dir / f"{label}.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            print("[verify] export failed — nothing to measure")
            return 3

    if not (export_dir / "index.html").is_file():
        evidence["verdict"] = "inconclusive"
        evidence["verdict_reason"] = f"no export at {export_dir}"
        (out_dir / f"{label}.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        return 3

    port = _free_port()
    url = f"http://127.0.0.1:{port}/index.html"
    print(f"[verify] serving {export_dir} on {url}")
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=export_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(1.5)
        probe_out = out_dir / "probe"
        probe_cmd = ["node", str(BROWSER_DIR / "render-probe.mjs"),
                     "--url", url, "--out", str(probe_out), "--label", label,
                     "--seconds", str(args.seconds)]
        # A virtual display where one exists; the probe rejects software adapters
        # itself, so a wrong choice here degrades to "inconclusive", never a pass.
        if shutil.which("xvfb-run"):
            probe_cmd = ["xvfb-run", "-a", "--server-args=-screen 0 1280x720x24", *probe_cmd]
        print(f"[verify] probing for {args.seconds}s (cold start alone can take ~20s)")
        subprocess.call(probe_cmd, cwd=BROWSER_DIR)

        report_path = probe_out / f"{label}.json"
        if report_path.is_file():
            evidence["probe"] = json.loads(report_path.read_text(encoding="utf-8"))
        else:
            evidence["probe"] = None

        # The binding trace is what distinguishes "renders" from "renders and is
        # actually valid", so a clean frame with rejected command buffers cannot
        # be reported as clean.
        trace_cmd = ["node", str(BROWSER_DIR / "binding-trace.mjs"),
                     "--url", url, "--seconds", str(min(args.seconds, 35)), "--max", "3", "--json"]
        if shutil.which("xvfb-run"):
            trace_cmd = ["xvfb-run", "-a", *trace_cmd]
        print("[verify] tracing bind groups and command-buffer validity")
        trace = subprocess.run(trace_cmd, cwd=BROWSER_DIR, capture_output=True, text=True)
        try:
            evidence["bindings"] = json.loads(trace.stdout[trace.stdout.index("{"):])
        except (ValueError, json.JSONDecodeError):
            evidence["bindings"] = None
            evidence["notes"].append("NOTE binding trace produced no parsable output")
    finally:
        server.terminate()

    probe = evidence.get("probe") or {}
    evidence["verdict"] = probe.get("verdict", "inconclusive")
    evidence["verdict_reason"] = probe.get("verdict_reason", "probe produced no report")

    cb = ((evidence.get("bindings") or {}).get("command_buffers") or {})
    evidence["summary"] = {
        "verdict": evidence["verdict"],
        "renderer_reported": (probe.get("engine_counters") or {}).get("renderer"),
        "draws": (probe.get("engine_counters") or {}).get("draws"),
        "primitives": (probe.get("engine_counters") or {}).get("primitives"),
        "fps": (probe.get("engine_counters") or {}).get("fps"),
        "adapter_is_fallback": (probe.get("adapter") or {}).get("isFallbackAdapter"),
        "canvas_dominant_colour_fraction": (probe.get("canvas") or {}).get("dominantColorFraction"),
        "gpu_validation_errors": probe.get("gpu_validation_errors"),
        "bind_group_failure_classes": len(((evidence.get("bindings") or {}).get("counts") or {})),
        "command_buffers_invalid": cb.get("finish_failed"),
        "submissions_rejected": cb.get("submit_failed"),
    }

    path = out_dir / f"{label}.json"
    path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")

    print()
    print(f"verdict : {evidence['verdict']}  ({evidence['verdict_reason']})")
    for k, v in evidence["summary"].items():
        if k != "verdict":
            print(f"  {k:34s} {v}")
    print()
    print(f"evidence written to {path.relative_to(REPO)}")
    print("If this differs from the published result, please open an issue and attach that file.")

    return {"rendered": 0, "not-rendered": 1}.get(evidence["verdict"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
