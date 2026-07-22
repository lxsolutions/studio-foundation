#!/usr/bin/env python3
"""Validate GitHub Actions structure and the studio's CI security contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
FULL_ACTION_SHA = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def _triggers(doc: dict) -> dict:
    value = doc.get("on", doc.get(True, {}))
    return value if isinstance(value, dict) else {}


def _run_commands(job: dict) -> list[str]:
    commands: list[str] = []
    for step in job.get("steps", []):
        if isinstance(step, dict) and isinstance(step.get("run"), str):
            commands.append(step["run"])
    return commands


def _labels(job: dict) -> set[str]:
    value = job.get("runs-on")
    if isinstance(value, str):
        return {value}
    return {str(item) for item in value} if isinstance(value, list) else set()


def _validate_action_pins(path: Path, jobs: dict) -> list[str]:
    problems: list[str] = []
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for index, step in enumerate(job.get("steps", []), start=1):
            if not isinstance(step, dict) or not isinstance(step.get("uses"), str):
                continue
            action = step["uses"]
            if action.startswith("./") or action.startswith("docker://"):
                continue
            if not FULL_ACTION_SHA.fullmatch(action):
                problems.append(
                    f"{path.name}: job '{job_name}' step {index} action is not pinned "
                    f"to a full commit: {action}"
                )
    return problems


def _validate_trust_boundary(path: Path, doc: dict, jobs: dict) -> list[str]:
    problems: list[str] = []
    if "pull_request" not in _triggers(doc):
        return problems
    for job_name, job in jobs.items():
        if not isinstance(job, dict) or "self-hosted" not in _labels(job):
            continue
        condition = str(job.get("if", ""))
        if "github.event_name == 'push'" not in condition:
            problems.append(
                f"{path.name}: self-hosted job '{job_name}' is not restricted to trusted pushes"
            )
    return problems


def _validate_studio_workflow(path: Path, doc: dict, jobs: dict) -> list[str]:
    if path.name != "validate.yml":
        return []
    problems: list[str] = []
    triggers = _triggers(doc)
    for trigger in ("push", "pull_request", "schedule", "workflow_dispatch"):
        if trigger not in triggers:
            problems.append(f"{path.name}: studio workflow must trigger on {trigger}")
    permissions = doc.get("permissions")
    if permissions != {"contents": "read"}:
        problems.append(f"{path.name}: top-level permissions must be exactly contents: read")

    policy = jobs.get("pr-policy", {})
    trusted = jobs.get("trusted-ci", {})
    engine = jobs.get("engine-validate", {})
    if "ubuntu" not in " ".join(_labels(policy)):
        problems.append(f"{path.name}: pr-policy must run on an isolated Ubuntu runner")
    if not {"self-hosted", "windows", "plato-ci"}.issubset(_labels(trusted)):
        problems.append(f"{path.name}: trusted-ci is missing required runner labels")
    if not {"self-hosted", "windows", "plato-ci"}.issubset(_labels(engine)):
        problems.append(f"{path.name}: engine-validate is missing required runner labels")
    if engine.get("needs") != "trusted-ci":
        problems.append(f"{path.name}: engine-validate must depend on trusted-ci")

    policy_commands = "\n".join(_run_commands(policy))
    for command in ("tools/ci/validate_workflows.py", "tools/ci/secret_scan.py"):
        if command not in policy_commands:
            problems.append(f"{path.name}: pr-policy does not run {command}")
    trusted_commands = "\n".join(_run_commands(trusted))
    for dependency in ("npm.cmd ci --prefix infra/nakama", "npm.cmd ci --prefix tests/browser"):
        if dependency not in trusted_commands:
            problems.append(f"{path.name}: trusted-ci does not install {dependency}")
    if not any("just ci-local" in command for command in _run_commands(trusted)):
        problems.append(f"{path.name}: trusted-ci must run just ci-local")
    if "scripts/ci/run_all.py --stage nightly" not in trusted_commands:
        problems.append(f"{path.name}: trusted-ci must schedule the nightly release stage")

    engine_commands = _run_commands(engine)
    if not any("npm.cmd ci --prefix tests/browser" in value for value in engine_commands):
        problems.append(f"{path.name}: engine-validate does not install browser dependencies")
    required = ("just engine-fetch", "just engine-build", "just engine-validate")
    positions: list[int] = []
    for command in required:
        matches = [index for index, value in enumerate(engine_commands) if command in value]
        if not matches:
            problems.append(f"{path.name}: engine-validate job does not run {command}")
        else:
            positions.append(matches[0])
    if len(positions) == len(required) and positions != sorted(positions):
        problems.append(f"{path.name}: engine fetch/build/validate steps are out of order")
    if sum("just engine-validate" in value for value in engine_commands) < 2:
        problems.append(f"{path.name}: both template and Asha World must pass engine-validate")
    return problems


def validate_file(path: Path) -> list[str]:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        return [f"{path.name}: YAML parse error: {error}"]
    if not isinstance(doc, dict):
        return [f"{path.name}: top level is not a mapping"]
    problems: list[str] = []
    if "on" not in doc and True not in doc:
        problems.append(f"{path.name}: missing required 'on' trigger")
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        problems.append(f"{path.name}: missing or empty 'jobs'")
        return problems
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            problems.append(f"{path.name}: job '{job_name}' is not a mapping")
            continue
        if "runs-on" not in job:
            problems.append(f"{path.name}: job '{job_name}' missing 'runs-on'")
        steps = job.get("steps")
        if not isinstance(steps, list) or not steps:
            problems.append(f"{path.name}: job '{job_name}' has no steps")
    problems.extend(_validate_action_pins(path, jobs))
    problems.extend(_validate_trust_boundary(path, doc, jobs))
    problems.extend(_validate_studio_workflow(path, doc, jobs))
    return problems


def main() -> int:
    if not WORKFLOWS.is_dir():
        print("FAIL no .github/workflows directory")
        return 1
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    if not files:
        print("FAIL no workflow files found")
        return 1
    all_problems: list[str] = []
    for path in files:
        all_problems.extend(validate_file(path))
    if all_problems:
        for problem in all_problems:
            print(f"FAIL {problem}")
        return 1
    print(f"workflows ok ({len(files)} file(s); trust and action-pin policy enforced)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
