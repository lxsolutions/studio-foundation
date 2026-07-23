#!/usr/bin/env python3
"""Probe Nakama device authentication and the optional neutral application RPC."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from typing import Any


class ProbeError(RuntimeError):
    pass


def request_json(
    url: str,
    body: dict[str, Any],
    *,
    headers: dict[str, str],
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **headers,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:300]
        raise ProbeError(f"HTTP {error.code} from {url}: {detail}") from error
    except urllib.error.URLError as error:
        raise ProbeError(f"could not reach {url}: {error.reason}") from error
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ProbeError(f"non-JSON response from {url}") from error
    if not isinstance(value, dict):
        raise ProbeError(f"unexpected response shape from {url}")
    return value


def authenticate(base_url: str, server_key: str, device_id: str, timeout: float) -> str:
    basic = base64.b64encode(f"{server_key}:".encode()).decode("ascii")
    result = request_json(
        f"{base_url}/v2/account/authenticate/device?create=true",
        {"id": device_id},
        headers={"Authorization": f"Basic {basic}"},
        timeout=timeout,
    )
    token = result.get("token")
    if not isinstance(token, str) or not token:
        raise ProbeError("device authentication did not return a session token")
    return token


def rpc(
    base_url: str,
    session_token: str,
    rpc_id: str,
    payload: Any,
    timeout: float,
) -> dict[str, Any]:
    result = request_json(
        f"{base_url}/v2/rpc/{rpc_id}",
        {"payload": json.dumps(payload, separators=(",", ":"))},
        headers={"Authorization": f"Bearer {session_token}"},
        timeout=timeout,
    )
    encoded = result.get("payload")
    if not isinstance(encoded, str):
        raise ProbeError(f"RPC {rpc_id} did not return a string payload")
    try:
        decoded = json.loads(encoded)
    except json.JSONDecodeError as error:
        raise ProbeError(f"RPC {rpc_id} returned malformed JSON") from error
    if not isinstance(decoded, dict):
        raise ProbeError(f"RPC {rpc_id} returned an unexpected payload shape")
    return decoded


def run(
    base_url: str,
    server_key: str,
    timeout: float,
    application_payload: Any | None = None,
) -> None:
    session = authenticate(
        base_url,
        server_key,
        f"studio-foundation-probe-{uuid.uuid4().hex}",
        timeout,
    )

    identity = rpc(base_url, session, "studio_identify", {}, timeout)
    if identity.get("ok") is not True:
        raise ProbeError("studio_identify did not report ok=true")
    user_id = identity.get("userId")
    if not isinstance(user_id, str) or user_id == "anonymous":
        raise ProbeError("identity was not authenticated")
    print(f"[nakama-probe] identity ok: {user_id}")

    if application_payload is None:
        return

    result = rpc(
        base_url,
        session,
        "studio_application_request",
        application_payload,
        timeout,
    )
    if not isinstance(result.get("accepted"), bool) or not isinstance(
        result.get("summary"), str
    ):
        raise ProbeError("application RPC returned an invalid result contract")
    print(
        "[nakama-probe] application response: "
        f"accepted={result['accepted']} summary={result['summary']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("STUDIO_NAKAMA_URL", "http://127.0.0.1:7350"),
    )
    parser.add_argument(
        "--server-key",
        default=os.environ.get("STUDIO_NAKAMA_SERVER_KEY", "defaultkey"),
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--application-json",
        help="optionally send this JSON value through studio_application_request",
    )
    args = parser.parse_args()
    try:
        payload = (
            json.loads(args.application_json)
            if args.application_json is not None
            else None
        )
        run(args.base_url.rstrip("/"), args.server_key, args.timeout, payload)
    except (json.JSONDecodeError, ProbeError) as error:
        print(f"[nakama-probe] FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
