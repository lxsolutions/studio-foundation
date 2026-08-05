"""The bforge bench: the full loop, run out loud, with a public verdict.

Brief -> forged asset -> quality gate (must pass) -> GLB parsed back and
structure-verified -> measurements recorded. Every brief is built TWICE from
a reset session and the two GLB exports must hash identically — determinism
is not a slogan, it is a checked property. Every run is a claim checked by
a machine, and the report is committed so anyone can rerun it and diff.

    uv run --project tools python tools/bforge/bench.py [runs]

Exit 0 when every run passes the gate, every GLB parses with its required
structure, and every brief regenerates byte-identically. The report lands in
tools/bforge/bench/ (report.json + SUMMARY.md).

Scope, honestly: the briefs are programmatic op sequences (this bench proves
the ops, gates, and export are deterministic and green — it does not test
natural-language interpretation), and the daemon is persistent, so startup
is excluded from the timings. NL-brief -> tool-call evaluation is a separate
harness (the BRIEF->BATTLE track in strategy/FRONTIER.md).
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge import Forge  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "bench"


def read_glb_json(path: Path) -> dict:
    data = path.read_bytes()
    assert data[:4] == b"glTF", "not a GLB"
    chunk_len, chunk_type = struct.unpack_from("<I4s", data, 12)
    assert chunk_type == b"JSON"
    return json.loads(data[20 : 20 + chunk_len])


def _png_rgba(path: Path, w: int, h: int, pixel_fn) -> None:
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw += bytes(pixel_fn(x, y))

    def chunk(tag, data):
        body = struct.pack(">I", len(data)) + tag + data
        return body + struct.pack(">I", zlib.crc32(tag + data))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw)))
        + chunk(b"IEND", b"")
    )


def brief_crate(forge: Forge) -> dict:
    forge.call("prop.crate", name="bench_crate", seed=3)
    return {"objects": ["bench_crate"], "requires": {"meshes_min": 1}}


def brief_wolf(forge: Forge) -> dict:
    forge.call("char.creature", name="bench_wolf", plan="canine", length=1.3,
               shoulder=0.85, bulk=1.15, skin="#4a3c30", seed=13)
    rig = forge.call("char.creature_rig", name="bench_wolf", plan="canine",
                     length=1.3, shoulder=0.85)
    forge.call("char.gait", rig=rig["armature"], speed=2.0)
    return {"objects": ["bench_wolf", rig["armature"]],
            "requires": {"skins_min": 1, "animations_min": 1, "vertex_color": True}}


def brief_warden(forge: Forge) -> dict:
    forge.call("char.humanoid", name="bench_warden", height=1.82, build="heroic",
               skin="#b08a68", seed=3)
    forge.call("char.face", name="bench_warden", height=1.82)
    forge.call("char.hands", name="bench_warden", height=1.82)
    pieces = []
    for piece, mat in (("cuirass", "bronze"), ("pteruges", "leather"),
                       ("greaves", "bronze"), ("helmet", "bronze")):
        pieces.append(forge.call("char.outfit", name="bench_warden", piece=piece,
                                 height=1.82, material=mat)["object"])
    rig = forge.call("char.rig", name="bench_warden", height=1.82, build="heroic")
    forge.call("char.gait", rig=rig["armature"], speed=1.4)
    return {"objects": ["bench_warden", rig["armature"]] + pieces,
            "requires": {"skins_min": 1, "animations_min": 1, "materials_min": 4}}


def brief_camp(forge: Forge) -> dict:
    result = forge.call("env.camp", name="bench_camp", radius=8.0, shelters=3, seed=42)
    objects = [e["object"] for e in result["structures"]]
    return {"objects": objects, "requires": {"meshes_min": 5}}


def brief_concept(forge: Forge, concept: Path) -> dict:
    result = forge.call("image.to_mesh", path=str(concept), name="bench_medallion",
                        target_height=1.0, depth=0.2, texture="none")
    return {"objects": ["bench_medallion"],
            "requires": {"meshes_min": 1}, "iou": result["silhouette_iou"]}


BRIEFS = [
    ("crate from a one-line brief", brief_crate),
    ("a wolf with a synthesized trot", brief_wolf),
    ("an armored warden that walks", brief_warden),
    ("a whole Age-1 camp in one call", brief_camp),
    ("a 2D concept become a solid", brief_concept),
]


def verify(glb_path: Path, requires: dict) -> list[str]:
    parsed = read_glb_json(glb_path)
    failures = []
    meshes = parsed.get("meshes", [])
    if len(meshes) < requires.get("meshes_min", 1):
        failures.append(f"meshes {len(meshes)} < {requires['meshes_min']}")
    if len(parsed.get("skins", [])) < requires.get("skins_min", 0):
        failures.append("no skin exported")
    if len(parsed.get("animations", [])) < requires.get("animations_min", 0):
        failures.append("no animations exported")
    if len(parsed.get("materials", [])) < requires.get("materials_min", 0):
        failures.append(f"materials {len(parsed.get('materials', []))} < {requires['materials_min']}")
    if requires.get("vertex_color"):
        has_vcol = any(
            "COLOR_0" in (prim.get("attributes") or {})
            for mesh in meshes for prim in mesh.get("primitives", [])
        )
        if not has_vcol:
            failures.append("no COLOR_0 vertex colours exported")
    return failures


def main() -> None:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    concept = OUT_DIR / "_bench_concept.png"
    _png_rgba(concept, 128, 128,
              lambda x, y: (200, 30, 30, 255) if (x - 64) ** 2 + (y - 64) ** 2 < 40 ** 2
              else (12, 12, 16, 255))

    report = {"bench": "bforge bench v2", "runs": [], "aggregates": {}}
    all_ok = True
    with Forge(workdir=tempfile.mkdtemp(prefix="bforge_bench_"),
               out_dir=str(OUT_DIR / "out")) as forge:
        for title, brief_fn in BRIEFS:
            for iteration in range(runs):
                hashes = []
                first = None
                started = time.time()
                # Build the same brief twice from a reset session: the two
                # exports must be byte-identical, or "deterministic" is a lie.
                for attempt in (1, 2):
                    forge.call("session.reset")
                    if brief_fn is brief_concept:
                        built = brief_fn(forge, concept)
                    else:
                        built = brief_fn(forge)
                    glb = forge.call("export.gltf", out=f"{built['objects'][0]}.glb",
                                     objects=built["objects"])
                    hashes.append(hashlib.sha256(Path(glb["path"]).read_bytes()).hexdigest())
                    if attempt == 1:
                        first = (built, glb)
                built, glb = first
                review = forge.call("gameready.review", objects=built["objects"])
                materials = forge.call("check.materials", objects=built["objects"])
                seconds = round(time.time() - started, 1)

                failures = verify(Path(glb["path"]), built["requires"])
                deterministic = hashes[0] == hashes[1]
                if not deterministic:
                    failures.append(
                        f"nondeterministic export: {hashes[0][:12]} != {hashes[1][:12]}")
                ok = review["passed"] and not failures
                all_ok = all_ok and ok
                entry = {
                    "brief": title,
                    "iteration": iteration + 1,
                    "seconds": seconds,
                    "triangles": glb["triangles"],
                    "bytes": glb["bytes"],
                    "gate": "pass" if review["passed"] else "FAIL",
                    "deterministic": deterministic,
                    "glb_sha256": hashes[0],
                    "structure_failures": failures,
                    "max_delta_e": materials["max_delta_e"],
                    "ok": ok,
                }
                if "iou" in built:
                    entry["silhouette_iou"] = built["iou"]
                report["runs"].append(entry)
                mark = "ok " if ok else "FAIL"
                print(f"  {mark} {title} #{iteration + 1}: {glb['triangles']} tris, "
                      f"{seconds}s, gate {entry['gate']}, "
                      f"{'deterministic' if deterministic else 'NONDETERMINISTIC'}"
                      + (f" (iou {built['iou']})" if "iou" in built else ""))

    total = len(report["runs"])
    passed = sum(1 for r in report["runs"] if r["ok"])
    deterministic_all = all(r["deterministic"] for r in report["runs"])
    report["aggregates"] = {
        "runs": total,
        "passed": passed,
        "pass_rate": round(passed / max(1, total), 3),
        "mean_seconds": round(sum(r["seconds"] for r in report["runs"]) / max(1, total), 1),
        "total_triangles": sum(r["triangles"] for r in report["runs"]),
        "deterministic": deterministic_all,
        "verdict": "pass" if all_ok else "fail",
    }
    (OUT_DIR / "report.json").write_text(json.dumps(report, indent=2) + "\n")

    summary = ["# bforge bench", "",
               f"verdict: **{report['aggregates']['verdict'].upper()}** — "
               f"{passed}/{total} runs green, "
               f"{'all briefs byte-identical across regeneration' if deterministic_all else 'DETERMINISM FAILURE'} "
               f"({report['aggregates']['total_triangles']} triangles total)", "",
               "| brief | tris | gate | deterministic | structure |", "| --- | --- | --- | --- | --- |"]
    for r in report["runs"]:
        summary.append(
            f"| {r['brief']} | {r['triangles']} | {r['gate']} | "
            f"{'✓' if r['deterministic'] else 'FAIL'} | "
            f"{'ok' if not r['structure_failures'] else ', '.join(r['structure_failures'])} |"
        )
    summary.append("")
    summary.append("Every brief is forged twice from a reset session and the two GLB exports "
                   "must hash identically (SHA-256 in report.json) — determinism is a checked "
                   "property, not a slogan. Wall-clock seconds live in report.json "
                   "(machine-dependent); this file carries only deterministic outputs and is "
                   "what CI diffs.")
    summary.append("")
    summary.append("Scope: programmatic op briefs over the persistent daemon — this bench proves "
                   "the ops, gates, and export; natural-language brief evaluation is the "
                   "BRIEF->BATTLE track (strategy/FRONTIER.md).")
    summary.append("")
    summary.append("Rerun: `uv run --project tools python tools/bforge/bench.py [runs]` — "
                   "the numbers are produced by the runner, not by memory.")
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(summary) + "\n")

    print(f"\nbench verdict: {report['aggregates']['verdict']} "
          f"({passed}/{total} green, report -> {OUT_DIR})")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
