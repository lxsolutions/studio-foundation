#!/usr/bin/env python3
"""Generate a third-party dependency attribution inventory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools import env as senv  # noqa: E402
from studio_tools.release import (  # noqa: E402
    NOASSERTION,
    Component,
    InventoryError,
    collect_inventory,
)


def _cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", " ")


def render_attribution(components: list[Component]) -> str:
    third_party = [component for component in components if not component.local]
    missing = [component.purl for component in third_party if component.license == NOASSERTION]
    if missing:
        raise InventoryError("missing declared license: " + ", ".join(missing))
    lines = [
        "# Third-party dependency attribution",
        "",
        "Generated from committed Cargo, uv, npm, and engine lockfiles.",
        "This inventory is not a substitute for the upstream license texts.",
        "",
        "| Ecosystem | Package | Version | Declared license | Source |",
        "|---|---|---|---|---|",
    ]
    for component in third_party:
        lines.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    component.ecosystem,
                    component.name,
                    component.version,
                    component.license,
                    component.source,
                )
            )
            + " |"
        )
    lines.extend(["", f"Total third-party packages: {len(third_party)}", ""])
    return "\n".join(lines)


def output_path(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("output must stay inside the repository")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="build/attribution/THIRD_PARTY_NOTICES.md")
    args = parser.parse_args(argv)
    root = senv.repo_root().resolve()
    try:
        components = collect_inventory(root)
        rendered = render_attribution(components)
        output = output_path(root, args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    except (InventoryError, OSError, ValueError) as exc:
        print(f"attribution failed: {exc}", file=sys.stderr)
        return 1
    print(f"attribution: {output.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
