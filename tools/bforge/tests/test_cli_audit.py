from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge import cli  # noqa: E402


class FakeForge:
    def __init__(self, *, errors: int = 0, warnings: int = 0):
        self.errors = errors
        self.warnings = warnings
        self.calls: list[tuple[str, dict]] = []
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True
        return {}

    def stop(self):
        self.stopped = True

    def call(self, op: str, **kwargs):
        self.calls.append((op, kwargs))
        if op == "session.import":
            return {"objects": ["mesh"], "triangles": 12, "materials": ["stone"]}
        if op == "session.info":
            sequence = sum(name == "session.info" for name, _ in self.calls)
            triangles = sequence * 12
            return {
                "objects": [{
                    "name": "mesh",
                    "triangles": triangles,
                    "bounds": {"size": [1.0, 0.5, 1.0 + sequence * 0.05]},
                }],
                "total_triangles": triangles,
                "materials": ["stone", *(["bronze"] if sequence > 1 else [])],
            }
        if op == "check.critique":
            return {
                "errors": self.errors,
                "warnings": self.warnings,
                "findings": [],
            }
        if op == "check.image":
            return {
                "size": [1200, 1200],
                "subject_coverage": 0.42,
                "luma": {"contrast": 0.61},
                "findings": ["sprite highlights are clipped"] if self.warnings else [],
                "ok": not self.warnings,
            }
        if op == "render.contact_sheet":
            return {"rel": kwargs["out"]}
        raise AssertionError(f"unexpected op: {op}")


def test_audit_imports_inspects_and_renders_each_asset(tmp_path, monkeypatch):
    first = tmp_path / "Greek Tower.glb"
    second = tmp_path / "wolf.obj"
    first.write_bytes(b"glTF")
    second.write_text("o wolf", encoding="utf-8")
    fake = FakeForge()
    monkeypatch.setattr(cli, "_forge", lambda _args: fake)

    args = cli.build_parser().parse_args([
        "audit",
        str(first),
        str(second),
        "--render-dir",
        "review",
    ])

    assert args.func(args) == 0
    assert fake.started and fake.stopped
    assert [op for op, _ in fake.calls] == [
        "session.import", "session.info", "check.critique", "render.contact_sheet",
        "session.import", "session.info", "check.critique", "render.contact_sheet",
    ]
    first_import = fake.calls[0][1]
    assert first_import["reset_first"] is True
    assert first_import["prefix"] == "audit_greek_tower"
    assert fake.calls[3][1]["out"] == "review/Greek Tower-contact.png"


def test_audit_exit_policy_is_ci_usable(tmp_path, monkeypatch):
    asset = tmp_path / "tower.glb"
    asset.write_bytes(b"glTF")

    warning_forge = FakeForge(warnings=1)
    monkeypatch.setattr(cli, "_forge", lambda _args: warning_forge)
    warning_args = cli.build_parser().parse_args([
        "audit", str(asset), "--fail-on", "warning",
    ])
    assert warning_args.func(warning_args) == 1

    error_forge = FakeForge(errors=1)
    monkeypatch.setattr(cli, "_forge", lambda _args: error_forge)
    never_args = cli.build_parser().parse_args([
        "audit", str(asset), "--fail-on", "never",
    ])
    assert never_args.func(never_args) == 0


def test_audit_rejects_missing_assets_without_starting_blender(tmp_path, monkeypatch):
    fake = FakeForge()
    monkeypatch.setattr(cli, "_forge", lambda _args: fake)
    args = cli.build_parser().parse_args(["audit", str(tmp_path / "missing.glb")])
    assert args.func(args) == 1
    assert not fake.started


def test_audit_measures_shipping_raster_without_importing_a_scene(tmp_path, monkeypatch, capsys):
    sprite = tmp_path / "greek-miner.webp"
    sprite.write_bytes(b"RIFF")
    fake = FakeForge()
    monkeypatch.setattr(cli, "_forge", lambda _args: fake)
    args = cli.build_parser().parse_args(["audit", str(sprite), "--render-dir", "review"])

    assert args.func(args) == 0
    result = json.loads(capsys.readouterr().out)
    row = result["assets"][0]
    assert row["kind"] == "image"
    assert row["image"]["size"] == [1200, 1200]
    assert row["status"] == {"errors": 0, "warnings": 0}
    assert [op for op, _ in fake.calls] == ["check.image"]
    assert fake.calls[0][1]["path"] == str(sprite.resolve())


def test_raster_findings_follow_audit_warning_policy(tmp_path, monkeypatch):
    sprite = tmp_path / "pickaxe.png"
    sprite.write_bytes(b"PNG")
    fake = FakeForge(warnings=1)
    monkeypatch.setattr(cli, "_forge", lambda _args: fake)
    args = cli.build_parser().parse_args([
        "audit", str(sprite), "--fail-on", "warning",
    ])

    assert args.func(args) == 1


def test_audit_progression_report_compares_ordered_asset_family(tmp_path, monkeypatch, capsys):
    assets = []
    for name in ("pilgrim.glb", "repeater.glb", "aegis.glb"):
        path = tmp_path / name
        path.write_bytes(b"glTF")
        assets.append(path)
    fake = FakeForge()
    monkeypatch.setattr(cli, "_forge", lambda _args: fake)
    args = cli.build_parser().parse_args([
        "audit", *(str(path) for path in assets), "--progression-report",
    ])

    assert args.func(args) == 0
    result = json.loads(capsys.readouterr().out)
    report = result["progression"]
    assert report["count"] == 3
    assert report["strictly_increasing_triangles"] is True
    assert [item["triangles"] for item in report["items"]] == [12, 24, 36]
    assert report["items"][1]["materials"] == ["bronze", "stone"]
    assert report["warnings"] == 0


def test_progression_warning_can_fail_ci(tmp_path, monkeypatch):
    first = tmp_path / "hero.glb"
    second = tmp_path / "legend.glb"
    first.write_bytes(b"glTF")
    second.write_bytes(b"glTF")
    fake = FakeForge()
    original_call = fake.call

    def flat_info(op: str, **kwargs):
        value = original_call(op, **kwargs)
        if op == "session.info":
            value["total_triangles"] = 12
            value["objects"][0]["triangles"] = 12
        return value

    fake.call = flat_info
    monkeypatch.setattr(cli, "_forge", lambda _args: fake)
    args = cli.build_parser().parse_args([
        "audit", str(first), str(second),
        "--progression-report", "--fail-on", "warning",
    ])
    assert args.func(args) == 1


def test_progression_report_tolerates_importers_without_bounds():
    report = cli._progression_report([
        {"asset": "first.obj", "info": {"total_triangles": 10, "objects": []}},
        {"asset": "second.obj", "info": {"total_triangles": 20, "objects": []}},
    ])
    assert report["strictly_increasing_triangles"] is True
    assert report["max_extent_ratio"] is None
    assert report["warnings"] == 0
    assert "unavailable" in report["findings"][0]["detail"]
