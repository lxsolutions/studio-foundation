#!/usr/bin/env python3
"""Audit resolved Cargo, PyPI, and npm dependencies against OSV.dev."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pylib"))

from studio_tools import env as senv  # noqa: E402
from studio_tools.release import Component, InventoryError, collect_inventory  # noqa: E402

OSV_BATCH_ENDPOINT = "https://api.osv.dev/v1/querybatch"
OSV_QUERY_ENDPOINT = "https://api.osv.dev/v1/query"
OSV_ECOSYSTEMS = {"Cargo": "crates.io", "PyPI": "PyPI", "npm": "npm"}
JsonRequester = Callable[[str, dict[str, object], int], dict[str, object]]


class AuditError(RuntimeError):
    """The advisory service could not provide a trustworthy result."""


def request_json(url: str, payload: dict[str, object], timeout: int) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "studio-foundation-dependency-audit/1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", errors="replace").strip()
        raise AuditError(f"OSV request failed: HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AuditError(f"OSV request failed: {exc}") from exc
    if not isinstance(value, dict):
        raise AuditError("OSV returned a non-object response")
    return value


def osv_query(component: Component) -> dict[str, object]:
    return {
        "package": {
            "ecosystem": OSV_ECOSYSTEMS[component.ecosystem],
            "name": component.name,
        },
        "version": component.version,
    }


def query_osv(
    components: list[Component],
    requester: JsonRequester = request_json,
    timeout: int = 30,
    batch_size: int = 100,
) -> dict[Component, list[str]]:
    auditable = [
        component
        for component in components
        if not component.local and component.ecosystem in OSV_ECOSYSTEMS
    ]
    findings: dict[Component, list[str]] = {}
    for offset in range(0, len(auditable), batch_size):
        batch = auditable[offset : offset + batch_size]
        response = requester(
            OSV_BATCH_ENDPOINT,
            {"queries": [osv_query(component) for component in batch]},
            timeout,
        )
        results = response.get("results")
        if not isinstance(results, list) or len(results) != len(batch):
            raise AuditError("OSV batch response did not match the requested package count")
        for component, result in zip(batch, results, strict=True):
            if not isinstance(result, dict):
                raise AuditError(f"OSV returned an invalid result for {component.purl}")
            ids = {
                str(vulnerability["id"])
                for vulnerability in result.get("vulns", [])
                if isinstance(vulnerability, dict) and vulnerability.get("id")
            }
            page_token = result.get("next_page_token")
            seen_page_tokens = set()
            while page_token:
                page_token = str(page_token)
                if page_token in seen_page_tokens:
                    raise AuditError(f"OSV repeated a page token for {component.purl}")
                seen_page_tokens.add(page_token)
                payload = osv_query(component)
                payload["page_token"] = page_token
                page = requester(OSV_QUERY_ENDPOINT, payload, timeout)
                ids.update(
                    str(vulnerability["id"])
                    for vulnerability in page.get("vulns", [])
                    if isinstance(vulnerability, dict) and vulnerability.get("id")
                )
                page_token = page.get("next_page_token")
            if ids:
                findings[component] = sorted(ids)
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args(argv)
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    try:
        components = collect_inventory(senv.repo_root())
        findings = query_osv(components, timeout=args.timeout)
    except (AuditError, InventoryError, OSError) as exc:
        print(f"audit failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        payload = {
            component.purl: vulnerabilities
            for component, vulnerabilities in sorted(findings.items(), key=lambda item: item[0].key)
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif findings:
        for component, vulnerabilities in sorted(findings.items(), key=lambda item: item[0].key):
            print(f"{component.purl}: {', '.join(vulnerabilities)}")
    else:
        audited = sum(
            not component.local and component.ecosystem in OSV_ECOSYSTEMS
            for component in components
        )
        print(f"dependency audit ok: {audited} resolved packages, no OSV findings")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
