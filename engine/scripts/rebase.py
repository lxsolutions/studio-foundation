"""Safely prepare an isolated WebGPU-fork merge workspace."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "engine" / ".cache"
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


def _has_commit(repo: Path, commit: str) -> bool:
    return (
        git_result(
            ["cat-file", "-e", f"{commit}^{{commit}}"], repo, check=False
        ).returncode
        == 0
    )


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    return (
        git_result(
            ["merge-base", "--is-ancestor", ancestor, descendant], repo, check=False
        ).returncode
        == 0
    )


def _git_dir(workspace: Path) -> Path:
    return Path(
        git_result(["rev-parse", "--absolute-git-dir"], workspace).stdout.strip()
    )


def _existing_workspace_status(
    workspace: Path, expected_branch: str
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
    conflicts = [
        line
        for line in git_result(
            ["diff", "--name-only", "--diff-filter=U"], workspace
        ).stdout.splitlines()
        if line
    ]
    merge_active = (_git_dir(workspace) / "MERGE_HEAD").is_file()
    return {
        "status": "conflicts"
        if conflicts
        else ("merge_ready" if merge_active else "workspace_exists"),
        "workspace": str(workspace),
        "branch": branch,
        "conflicts": len(conflicts),
    }


def prepare_rebase(
    lock: dict,
    *,
    official_ref: str = "",
    branch: str = "",
    workspace_name: str = "",
    dry_run: bool = False,
    cache_dir: Path = CACHE_DIR,
) -> dict[str, object]:
    """Prepare a dedicated worktree merging an official Godot ref into the fork.

    The pinned fork checkout remains untouched. Merge conflicts are an expected,
    successful preparation result and are left in the dedicated worktree for
    classify_conflicts.py and human/agent review.
    """
    official_dir = cache_dir / "godot-official"
    fork_dir = cache_dir / "godot-webgpu"
    for path, label in ((official_dir, "official"), (fork_dir, "WebGPU fork")):
        if not (path / ".git").is_dir():
            raise RebaseError(
                f"{label} source is not fetched at {path}; run engine-fetch"
            )

    official_ref = official_ref or str(lock["godot"]["official"]["commit"])
    target_commit = _resolve_commit(official_dir, official_ref, "official")
    fork_commit = _resolve_commit(
        fork_dir, str(lock["godot"]["webgpu_fork"]["commit"]), "fork pin"
    )
    suffix = (
        re.sub(r"[^A-Za-z0-9._-]+", "-", official_ref).strip("-.")[:48]
        or target_commit[:12]
    )
    workspace_name = workspace_name or f"godot-webgpu-{suffix}"
    branch = branch or f"studio-webgpu-merge-{suffix}"
    if (
        git_result(
            ["check-ref-format", "--branch", branch], fork_dir, check=False
        ).returncode
        != 0
    ):
        raise RebaseError(f"invalid Git branch name: {branch}")

    workspace = rebase_workspace(workspace_name, cache_dir)
    rebases_root = workspace.parent
    if workspace.exists():
        return _existing_workspace_status(workspace, branch)

    target_in_fork = _has_commit(fork_dir, target_commit)
    if target_in_fork and _is_ancestor(fork_dir, target_commit, fork_commit):
        return _result("up_to_date", target_commit, fork_commit, workspace, branch, 0)
    if dry_run:
        result = _result("planned", target_commit, fork_commit, workspace, branch, None)
        result["fetch_official_into_fork"] = not target_in_fork
        return result

    rebases_root.mkdir(parents=True, exist_ok=True)
    if not target_in_fork:
        git_result(["fetch", "--no-tags", str(official_dir), target_commit], fork_dir)
    if _is_ancestor(fork_dir, target_commit, fork_commit):
        return _result("up_to_date", target_commit, fork_commit, workspace, branch, 0)

    branch_exists = (
        git_result(
            ["show-ref", "--verify", f"refs/heads/{branch}"], fork_dir, check=False
        ).returncode
        == 0
    )
    if branch_exists:
        raise RebaseError(
            f"branch already exists without the expected workspace: {branch}; "
            "inspect it before choosing a different --branch"
        )
    git_result(["worktree", "add", "-b", branch, str(workspace), fork_commit], fork_dir)
    merge = git_result(
        ["merge", "--no-commit", "--no-ff", target_commit], workspace, check=False
    )
    conflicts = [
        line
        for line in git_result(
            ["diff", "--name-only", "--diff-filter=U"], workspace
        ).stdout.splitlines()
        if line
    ]
    if merge.returncode not in (0, 1) or (merge.returncode == 1 and not conflicts):
        raise RebaseError(
            "merge preparation failed: " + (merge.stdout + merge.stderr).strip()
        )
    return _result(
        "conflicts" if conflicts else "merge_ready",
        target_commit,
        fork_commit,
        workspace,
        branch,
        len(conflicts),
    )


def _result(
    status: str,
    official_commit: str,
    fork_commit: str,
    workspace: Path,
    branch: str,
    conflicts: int | None,
) -> dict[str, object]:
    return {
        "status": status,
        "official_commit": official_commit,
        "fork_commit": fork_commit,
        "workspace": str(workspace),
        "branch": branch,
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
            f"[rebase] {result['conflicts']} conflict(s) require classification and review"
        )
        print(
            "[rebase] next: python engine/scripts/classify_conflicts.py "
            f'--fork-dir "{result["workspace"]}"'
        )
    elif status == "merge_ready":
        print(
            "[rebase] clean merge prepared but not committed; inspect, build, and validate first"
        )
    elif status == "up_to_date":
        print(
            "[rebase] fork pin already contains the selected official commit; no workspace created"
        )
    elif status == "planned":
        print("[rebase] dry run only; no repository or worktree state changed")
    return 0
