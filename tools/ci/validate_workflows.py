#!/usr/bin/env python3
"""Validate GitHub Actions workflows: parse as YAML and check the fields the
studio's CI depends on (no undefined action SHAs-pinned policy is advisory-only;
this is a structural lint, not a full schema check).

Exit 0 when every .github/workflows/*.{yml,yaml} parses and has `on` + `jobs` with
`runs-on` + at least one step; exit 1 otherwise. PyYAML is in the tools dev group.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"


def validate_file(path: Path) -> list[str]:
    problems: list[str] = []
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        return [f"{path.name}: YAML parse error: {err}"]
    if not isinstance(doc, dict):
        return [f"{path.name}: top level is not a mapping"]
    # `on` is a YAML 1.1 boolean key (True) when unquoted.
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
    return problems


def main() -> int:
    if not WORKFLOWS.is_dir():
        print("no .github/workflows directory — nothing to validate")
        return 0
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    if not files:
        print("no workflow files found")
        return 0
    all_problems: list[str] = []
    for path in files:
        all_problems.extend(validate_file(path))
    if all_problems:
        for p in all_problems:
            print(f"FAIL {p}")
        return 1
    print(f"workflows ok ({len(files)} file(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
