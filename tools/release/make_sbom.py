#!/usr/bin/env python3
"""Generate a deterministic-inventory SPDX 2.3 JSON SBOM."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools import env as senv  # noqa: E402
from studio_tools.release import Component, InventoryError, collect_inventory  # noqa: E402


def build_spdx(components: list[Component]) -> dict[str, object]:
    fingerprint = hashlib.sha256(
        "\n".join(component.purl for component in components).encode()
    ).hexdigest()
    packages = []
    relationships = []
    for component in components:
        package: dict[str, object] = {
            "SPDXID": component.spdx_id,
            "name": component.name,
            "versionInfo": component.version,
            "downloadLocation": (
                component.source
                if component.source.startswith(("http://", "https://"))
                else "NOASSERTION"
            ),
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": component.license,
            "copyrightText": "NOASSERTION",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": component.purl,
                }
            ],
            "comment": f"ecosystem={component.ecosystem}; local={str(component.local).lower()}",
        }
        if checksum := component.spdx_checksum():
            package["checksums"] = [checksum]
        packages.append(package)
        relationships.append(
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": component.spdx_id,
            }
        )
    created = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "studio-foundation-dependency-sbom",
        "documentNamespace": (
            f"https://github.com/lxsolutions/studio-foundation/spdx/studio-foundation-{fingerprint}"
        ),
        "creationInfo": {
            "created": created,
            "creators": ["Tool: studio-foundation/tools/release/make_sbom.py"],
        },
        "packages": packages,
        "relationships": relationships,
    }


def output_path(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("output must stay inside the repository")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="build/sbom/studio-foundation.spdx.json")
    args = parser.parse_args(argv)
    root = senv.repo_root().resolve()
    try:
        components = collect_inventory(root)
        output = output_path(root, args.output)
        document = build_spdx(components)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (InventoryError, OSError, ValueError) as exc:
        print(f"sbom failed: {exc}", file=sys.stderr)
        return 1
    print(f"SBOM: {output.relative_to(root)} ({len(components)} packages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
