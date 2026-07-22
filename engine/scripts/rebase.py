"""Safely test Studio Foundation's WebGPU patch series on a Godot update."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from patch_series import PatchSeriesError, verified_patches

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_DIR = REPO_ROOT / "engine"
CACHE_DIR = ENGINE_DIR / ".cache"
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class RebaseError(RuntimeError):
    """A safe, actionable engine-rebase preparation failure."""


def git_result(
    args: list[str], cwd: Path, check: bool = True
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and proc.returncode != 0:
        detail = (proc.stdout + proc.stderr).strip()
        raise RebaseError(f"git {' '.join(args)} failed: {detail}")
    return proc


def _safe_name(value: str, label: str) -> str:
    if not SAFE_NAME.fullmatch(value) or value in {".", ".."}:
        raise RebaseError(
            f"{label} must contain only letters, numbers, dot, underscore, or hyphen"
        )
    return value


def rebase_workspace(name: str, cache_dir: Path = CACHE_DIR) -> Path:
    """Resolve a safe worktree name beneath the dedicated rebase cache."""
    name = _safe_name(name, "workspace name")
    rebases_root = (cache_dir / "rebases").resolve()
    workspace = (rebases_root / name).resolve()
    if not workspace.is_relative_to(rebases_root):
        raise RebaseError("rebase workspace escaped engine/.cache/rebases")
    return workspace


def _resolve_commit(repo: Path, ref: str, label: str) -> str:
    proc = git_result(["rev-parse", "--verify", f"{ref}^{{commit}}"], repo, check=False)
    if proc.returncode != 0:
        raise RebaseError(f"{label} ref is not available in {repo}: {ref}")
    return proc.stdout.strip()


def _existing_workspace_status(
    workspace: Path, expected_branch: str, base_commit: str, patch_count: int
) -> dict[str, object]:
    if not (workspace / ".git").exists():
        raise RebaseError(
            f"workspace already exists and is not a Git worktree: {workspace}"
        )
    branch = git_result(["branch", "--show-current"], workspace).stdout.strip()
    if branch != expected_branch:
        raise RebaseError(
            f"workspace branch does not match: expected {expected_branch}, found {branch}"
        )
    target_commit = git_result(["rev-parse", "HEAD"], workspace).stdout.strip()
    conflicts = [
        line
        for line in git_result(
            ["diff", "--name-only", "--diff-filter=U"], workspace
        ).stdout.splitlines()
        if line
    ]
    status = "conflicts" if conflicts else "workspace_exists"
    return _result(
        status,
        base_commit,
        target_commit,
        workspace,
        branch,
        patch_count,
        len(conflicts),
    )


def prepare_rebase(
    lock: dict,
    *,
    official_ref: str = "",
    branch: str = "",
    workspace_name: str = "",
    dry_run: bool = False,
    cache_dir: Path = CACHE_DIR,
    engine_dir: Path = ENGINE_DIR,
) -> dict[str, object]:
    """Prepare an official-Godot worktree and three-way apply the locked patches."""
    official_dir = cache_dir / "godot-official"
    if not (official_dir / ".git").is_dir():
        raise RebaseError(
            f"official source is not fetched at {official_dir}; run engine-fetch"
        )

    try:
        patches = verified_patches(lock, engine_dir)
    except PatchSeriesError as exc:
        raise RebaseError(str(exc)) from exc

    base_commit = str(lock["godot"]["webgpu"]["base_commit"])
    official_ref = official_ref or str(lock["godot"]["official"]["commit"])
    target_commit = _resolve_commit(official_dir, official_ref, "official")
    suffix = (
        re.sub(r"[^A-Za-z0-9._-]+", "-", official_ref).strip("-.")[:48]
        or target_commit[:12]
    )
    workspace_name = workspace_name or f"studio-webgpu-{suffix}"
    branch = branch or f"studio-webgpu-port-{suffix}"
    if (
        git_result(
            ["check-ref-format", "--branch", branch], official_dir, check=False
        ).returncode
        != 0
    ):
        raise RebaseError(f"invalid Git branch name: {branch}")

    workspace = rebase_workspace(workspace_name, cache_dir)
    if workspace.exists():
        return _existing_workspace_status(workspace, branch, base_commit, len(patches))
    if target_commit == base_commit:
        return _result(
            "up_to_date",
            base_commit,
            target_commit,
            workspace,
            branch,
            len(patches),
            0,
        )
    if dry_run:
        return _result(
            "planned",
            base_commit,
            target_commit,
            workspace,
            branch,
            len(patches),
            None,
        )

    workspace.parent.mkdir(parents=True, exist_ok=True)
    branch_exists = (
        git_result(
            ["show-ref", "--verify", f"refs/heads/{branch}"],
            official_dir,
            check=False,
        ).returncode
        == 0
    )
    if branch_exists:
        raise RebaseError(
            f"branch already exists without the expected workspace: {branch}; "
            "inspect it before choosing a different --branch"
        )
    git_result(
        ["worktree", "add", "-b", branch, str(workspace), target_commit],
        official_dir,
    )

    for patch in patches:
        applied = git_result(
            ["apply", "--3way", "--index", str(patch.path)],
            workspace,
            check=False,
        )
        if applied.returncode == 0:
            continue
        conflicts = [
            line
            for line in git_result(
                ["diff", "--name-only", "--diff-filter=U"], workspace
            ).stdout.splitlines()
            if line
        ]
        if conflicts:
            result = _result(
                "conflicts",
                base_commit,
                target_commit,
                workspace,
                branch,
                len(patches),
                len(conflicts),
            )
            result["failed_patch"] = patch.relative
            return result
        detail = (applied.stdout + applied.stderr).strip()
        raise RebaseError(f"failed to apply {patch.relative}: {detail}")

    return _result(
        "patches_applied",
        base_commit,
        target_commit,
        workspace,
        branch,
        len(patches),
        0,
    )


def _result(
    status: str,
    base_commit: str,
    target_commit: str,
    workspace: Path,
    branch: str,
    patch_count: int,
    conflicts: int | None,
) -> dict[str, object]:
    return {
        "status": status,
        "base_commit": base_commit,
        "official_commit": target_commit,
        "workspace": str(workspace),
        "branch": branch,
        "patches": patch_count,
        "conflicts": conflicts,
    }


def cmd_rebase(lock: dict, args: argparse.Namespace) -> int:
    try:
        result = prepare_rebase(
            lock,
            official_ref=args.official_ref,
            branch=args.branch,
            workspace_name=args.workspace,
            dry_run=args.dry_run,
        )
    except RebaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    status = result["status"]
    print(f"[rebase] {status}: {result['branch']}")
    print(f"[rebase] workspace: {result['workspace']}")
    if status == "conflicts":
        print(
            f"[rebase] {result['conflicts']} conflict(s) while applying "
            f"{result.get('failed_patch')}"
        )
        print(
            "[rebase] next: python engine/scripts/classify_conflicts.py "
            f'--source-dir "{result["workspace"]}"'
        )
    elif status == "patches_applied":
        print(
            "[rebase] patch series applied; inspect, build, and validate the candidate"
        )
    elif status == "up_to_date":
        print(
            "[rebase] lock already targets this official commit; no workspace created"
        )
    elif status == "planned":
        print("[rebase] dry run only; no branch or worktree state changed")
    return 0
