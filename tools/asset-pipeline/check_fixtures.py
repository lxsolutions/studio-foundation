#!/usr/bin/env python3
"""Fast protocol-fixture sanity used by `just test-protocol` and CI glue.

The real cross-language guarantees are the Rust and GDScript suites, both of
which decode these fixtures. This check keeps the fixture SET itself honest:
parseable JSON, envelope fields present, naming convention respected — so a
bad fixture fails loudly here instead of confusingly in two language suites.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[2] / "shared" / "protocol" / "fixtures"
REQUIRED_ENVELOPE_FIELDS = ("v", "seq", "type")


def main() -> int:
    problems: list[str] = []
    fixtures = sorted(FIXTURES.glob("*.json"))
    if len(fixtures) < 5:
        problems.append(f"expected >=5 fixtures in {FIXTURES}, found {len(fixtures)}")
    for path in fixtures:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{path.name}: not valid JSON ({exc})")
            continue
        if not isinstance(data, dict):
            problems.append(f"{path.name}: fixture must be a JSON object")
            continue
        missing = [f for f in REQUIRED_ENVELOPE_FIELDS if f not in data]
        if missing:
            problems.append(f"{path.name}: missing envelope fields {missing}")
        if path.name.startswith("invalid_"):
            continue
        if data.get("v") != 2:
            problems.append(f"{path.name}: valid fixtures must use protocol v2")
    if problems:
        for problem in problems:
            print(f"FIXTURE ERROR: {problem}", file=sys.stderr)
        return 1
    print(f"protocol fixtures ok ({len(fixtures)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
