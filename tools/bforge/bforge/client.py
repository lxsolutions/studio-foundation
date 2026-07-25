"""Host-side client: owns the Blender daemon process and speaks its protocol.

Stdlib only, by studio policy. Runs outside Blender, so it must never import
bpy.

Design notes worth keeping:

* The daemon is spawned lazily and kept warm. Blender costs ~2-4 s to start;
  paying that once per session instead of once per call is the whole point.
* Framing is marker-based (``@@BF@@``), not line-position based, because
  Blender writes its own chatter to the same stdout and always will.
* stderr is drained on a background thread. Without this, a chatty Blender
  fills the pipe buffer and the whole thing deadlocks — a failure mode that
  looks exactly like "the model is thinking", which is the worst way to lose an
  hour.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

MARKER = "@@BF@@"
READY = "@@BF-READY@@"
DEFAULT_TIMEOUT = 300


class ForgeError(RuntimeError):
    """An op failed. `.kind` is 'op' for expected failures, 'internal' for bugs."""

    def __init__(self, message, kind="op", traceback_text=""):
        super().__init__(message)
        self.kind = kind
        self.traceback_text = traceback_text


class DaemonError(RuntimeError):
    """The Blender process itself failed to start, died, or stopped responding."""


def find_blender(explicit=None) -> str:
    """Locate Blender, preferring an explicit path, then $BLENDER_BIN, then PATH."""
    import glob
    import shutil

    for candidate in (explicit, os.environ.get("BLENDER_BIN")):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    found = shutil.which("blender")
    if found:
        return found
    patterns = []
    if os.name == "nt":
        patterns = [
            r"C:\Program Files\Blender Foundation\Blender *\blender.exe",
            r"C:\Program Files (x86)\Blender Foundation\Blender *\blender.exe",
        ]
    elif sys.platform == "darwin":
        patterns = [
            "/Applications/Blender.app/Contents/MacOS/Blender",
            "/Applications/Blender*/Blender.app/Contents/MacOS/Blender",
        ]
    else:
        patterns = ["/usr/share/blender/blender", "/opt/blender*/blender", "/snap/bin/blender"]
    matches: list[str] = []
    for pattern in patterns:
        matches.extend(glob.glob(pattern))
    if matches:
        # Highest version number wins when several are installed.
        return sorted(matches)[-1]
    raise DaemonError(
        "Blender not found. Install Blender 4.2+ and either put it on PATH or set "
        "BLENDER_BIN to the executable."
    )


class Forge:
    """A live Blender session you can send ops to.

    Usable as a context manager::

        with Forge() as forge:
            forge.call("prop.crate", size=[1, 1, 1])
            forge.call("export.gltf", out="crate.glb")
    """

    def __init__(
        self,
        blender=None,
        workdir=None,
        out_dir=None,
        runtime_dir=None,
        timeout=DEFAULT_TIMEOUT,
        verbose=False,
    ):
        self.blender = find_blender(blender)
        self.workdir = Path(workdir or os.getcwd()).resolve()
        self.out_dir = Path(out_dir or (self.workdir / "assets-generated" / "bforge")).resolve()
        self.runtime_dir = Path(
            runtime_dir or (Path(__file__).resolve().parents[1] / "runtime")
        ).resolve()
        self.timeout = timeout
        self.verbose = verbose
        self.process: subprocess.Popen | None = None
        self.info: dict = {}
        self._next_id = 1
        self._stderr_tail: deque[str] = deque(maxlen=200)
        self._stderr_thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # -- lifecycle ------------------------------------------------------
    def start(self) -> dict:
        if self.process is not None and self.process.poll() is None:
            return self.info
        daemon = self.runtime_dir / "daemon.py"
        if not daemon.is_file():
            raise DaemonError(f"bforge runtime not found at {daemon}")
        self.out_dir.mkdir(parents=True, exist_ok=True)

        argv = [
            self.blender,
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "-P",
            str(daemon),
            "--",
            f"--workdir={self.workdir}",
            f"--out={self.out_dir}",
        ]
        creation = 0
        if os.name == "nt":
            # Keep Ctrl+C in the parent from tearing down Blender mid-write.
            creation = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        self.process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=str(self.workdir),
            creationflags=creation,
        )
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

        deadline = time.time() + 120
        while time.time() < deadline:
            line = self.process.stdout.readline()
            if not line:
                raise DaemonError("Blender exited during startup.\n" + self._diagnostics())
            stripped = line.strip()
            if stripped.startswith(MARKER):
                payload = json.loads(stripped[len(MARKER) :].strip())
                if payload.get("ready"):
                    self.info = payload
            elif stripped == READY:
                if self.verbose:
                    print(f"[bforge] daemon ready: {self.info}", file=sys.stderr)
                return self.info
        raise DaemonError("timed out waiting for the Blender daemon to become ready")

    def _drain_stderr(self):
        assert self.process is not None
        for line in self.process.stderr:
            text = line.rstrip()
            if text:
                self._stderr_tail.append(text)
                if self.verbose:
                    print(f"[blender] {text}", file=sys.stderr)

    def _diagnostics(self) -> str:
        tail = "\n".join(list(self._stderr_tail)[-40:])
        return f"--- Blender stderr (last lines) ---\n{tail}" if tail else "(no stderr output)"

    def stop(self):
        if self.process is None:
            return
        try:
            if self.process.poll() is None:
                self.process.stdin.write(json.dumps({"id": 0, "op": "__shutdown__"}) + "\n")
                self.process.stdin.flush()
                self.process.wait(timeout=15)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            self.process.kill()
            self.process.wait(timeout=5)
        finally:
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                try:
                    if stream is not None:
                        stream.close()
                except OSError:
                    pass
            self.process = None

    def restart(self) -> dict:
        self.stop()
        return self.start()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_exc):
        self.stop()
        return False

    # -- protocol -------------------------------------------------------
    def call(self, op: str, _timeout=None, **args) -> dict:
        """Run one op. Raises ForgeError on failure, returns the result dict."""
        result = self.call_raw(op, args, timeout=_timeout)
        if not result.get("ok"):
            raise ForgeError(
                result.get("error", "unknown error"),
                kind=result.get("kind", "op"),
                traceback_text=result.get("traceback", ""),
            )
        payload = result.get("result", {})
        if result.get("notes"):
            payload = dict(payload)
            payload["_notes"] = result["notes"]
        return payload

    def call_raw(self, op: str, args: dict, timeout=None) -> dict:
        with self._lock:
            if self.process is None or self.process.poll() is not None:
                self.start()
            assert self.process is not None
            request_id = self._next_id
            self._next_id += 1
            message = json.dumps({"id": request_id, "op": op, "args": args or {}})
            try:
                self.process.stdin.write(message + "\n")
                self.process.stdin.flush()
            except (OSError, ValueError) as exc:
                raise DaemonError(
                    f"lost the Blender daemon while sending '{op}'.\n{self._diagnostics()}"
                ) from exc

            deadline = time.time() + (timeout or self.timeout)
            while time.time() < deadline:
                line = self.process.stdout.readline()
                if not line:
                    raise DaemonError(
                        f"Blender exited while running '{op}'.\n{self._diagnostics()}"
                    )
                stripped = line.strip()
                if not stripped.startswith(MARKER):
                    continue
                try:
                    payload = json.loads(stripped[len(MARKER) :].strip())
                except json.JSONDecodeError:
                    continue
                if payload.get("id") == request_id:
                    return payload
            raise DaemonError(
                f"op '{op}' exceeded {timeout or self.timeout}s. Renders and bakes are the "
                "usual culprits — pass a longer timeout or lower samples/resolution."
            )

    # -- discovery ------------------------------------------------------
    def catalog(self) -> list[dict]:
        response = self.call_raw("__catalog__", {})
        if not response.get("ok"):
            raise DaemonError(response.get("error", "catalog failed"))
        return response["result"]["ops"]

    def script(self, steps, stop_on_error=True) -> list[dict]:
        """Run a list of ``{"op": ..., "args": {...}}`` steps in order."""
        results = []
        for index, step in enumerate(steps):
            name = step.get("op")
            try:
                results.append(
                    {
                        "step": index,
                        "op": name,
                        "ok": True,
                        "result": self.call(name, **(step.get("args") or {})),
                    }
                )
            except ForgeError as exc:
                results.append({"step": index, "op": name, "ok": False, "error": str(exc)})
                if stop_on_error:
                    break
        return results
