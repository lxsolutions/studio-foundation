"""bforge runtime daemon — runs *inside* Blender, in background mode.

    blender -b --factory-startup -P runtime/daemon.py -- --workdir=. --out=assets-generated/bforge

Speaks newline-delimited JSON on stdin and answers with marker-framed JSON on
stdout::

    <- {"id": 7, "op": "prop.crate", "args": {"size": [1,1,1]}}
    -> @@BF@@ {"id": 7, "ok": true, "result": {...}, "ms": 41}

The marker matters: Blender writes its own chatter (splash suppression notices,
addon warnings, "Blender quit") to the same stdout, so the client scans for
``@@BF@@`` rather than trusting line order. Diagnostics go to stderr.

Why a daemon at all: a cold ``blender -b`` costs ~2-4s of process + scene setup.
An agent iterating on a model does that dozens of times per asset. Holding one
process open makes the same calls land in tens of milliseconds and — the part
that matters more — lets ops *build on each other* instead of every call
starting from an empty scene.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

MARKER = "@@BF@@"
READY = "@@BF-READY@@"

from ctx import Ctx  # noqa: E402
from registry import OpError, catalog, dispatch  # noqa: E402

import ops  # noqa: E402,F401  (importing the package registers every op)


def _arg(name: str, default: str = "") -> str:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    prefix = f"--{name}="
    for item in argv:
        if item.startswith(prefix):
            return item[len(prefix) :]
    return default


def _write(payload: dict) -> None:
    sys.stdout.write(f"{MARKER} {json.dumps(payload, default=_fallback)}\n")
    sys.stdout.flush()


def _fallback(value):
    """Blender types (Vector, Color, ...) are iterable but not JSON-native."""
    try:
        return list(value)
    except TypeError:
        return str(value)


def _log(message: str) -> None:
    sys.stderr.write(f"[bforge] {message}\n")
    sys.stderr.flush()


def main() -> int:
    workdir = _arg("workdir", os.getcwd())
    out_dir = _arg("out", str(Path(workdir) / "assets-generated" / "bforge"))
    ctx = Ctx(workdir, out_dir)

    import bpy

    ops.session.reset_scene(ctx)  # deterministic empty scene, metric units

    _write(
        {
            "ready": True,
            "blender": bpy.app.version_string,
            "python": sys.version.split()[0],
            "ops": len(catalog()),
            "workdir": str(ctx.workdir),
            "out_dir": str(ctx.out_dir),
        }
    )
    sys.stdout.write(READY + "\n")
    sys.stdout.flush()
    _log(f"ready — {len(catalog())} ops, Blender {bpy.app.version_string}")

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        started = time.perf_counter()
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            _write({"id": None, "ok": False, "error": f"malformed JSON request: {exc}"})
            continue

        request_id = message.get("id")
        name = message.get("op")

        if name == "__shutdown__":
            _write({"id": request_id, "ok": True, "result": {"bye": True}})
            return 0
        if name == "__catalog__":
            _write({"id": request_id, "ok": True, "result": {"ops": catalog()}})
            continue

        try:
            result = dispatch(ctx, name, message.get("args") or {})
            payload = {
                "id": request_id,
                "ok": True,
                "result": result if result is not None else {},
                "ms": int((time.perf_counter() - started) * 1000),
            }
            notes = ctx.drain_notes()
            if notes:
                payload["notes"] = notes
            _write(payload)
        except OpError as exc:
            ctx.drain_notes()
            _write({"id": request_id, "ok": False, "error": str(exc), "kind": "op"})
        except Exception as exc:  # noqa: BLE001 - a bad op must not kill the daemon
            ctx.drain_notes()
            _write(
                {
                    "id": request_id,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "kind": "internal",
                    "traceback": traceback.format_exc(limit=12),
                }
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
