"""Helpers shared by the whitelisted Blender scripts (run INSIDE Blender's
Python: `blender -b file.blend -P script.py -- args`). Keep bpy imports here so
tools/ linting (which has no bpy) skips this directory."""

import json
import sys


def script_args() -> list[str]:
    argv = sys.argv
    return argv[argv.index("--") + 1 :] if "--" in argv else []


def emit(marker: str, payload: dict) -> None:
    """Single-line machine-readable result the pipeline greps for."""
    print(f"{marker} {json.dumps(payload)}")
    sys.stdout.flush()


def arg_value(args: list[str], name: str, default: str = "") -> str:
    prefix = f"--{name}="
    for arg in args:
        if arg.startswith(prefix):
            return arg[len(prefix) :]
    return default
