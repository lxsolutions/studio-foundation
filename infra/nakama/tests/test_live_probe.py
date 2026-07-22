from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "live_probe.py"
SPEC = importlib.util.spec_from_file_location("asha_nakama_live_probe", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class LiveProbeTests(unittest.TestCase):
    def test_authentication_uses_basic_server_key_and_requires_token(self) -> None:
        with mock.patch.object(
            probe, "request_json", return_value={"token": "session"}
        ) as request:
            self.assertEqual(
                probe.authenticate("http://nakama", "server-key", "device-12345", 3.0),
                "session",
            )
        self.assertEqual(
            request.call_args.kwargs["headers"]["Authorization"],
            "Basic c2VydmVyLWtleTo=",
        )

        with mock.patch.object(probe, "request_json", return_value={}):
            with self.assertRaisesRegex(probe.ProbeError, "session token"):
                probe.authenticate("http://nakama", "server-key", "device-12345", 3.0)

    def test_rpc_wraps_and_decodes_nakama_string_payload(self) -> None:
        response = {"payload": json.dumps({"applied": True, "summary": "settled"})}
        with mock.patch.object(probe, "request_json", return_value=response) as request:
            result = probe.rpc(
                "http://nakama", "session", "asha_world_event", {"Event": {}}, 3.0
            )

        self.assertEqual(result, {"applied": True, "summary": "settled"})
        self.assertEqual(
            request.call_args.args[0], "http://nakama/v2/rpc/asha_world_event"
        )
        self.assertEqual(
            request.call_args.kwargs["headers"], {"Authorization": "Bearer session"}
        )
        self.assertEqual(
            json.loads(request.call_args.args[1]["payload"]),
            {"Event": {}},
        )

    def test_end_to_end_contract_requires_apply_then_duplicate(self) -> None:
        responses = [
            {"token": "session"},
            {"payload": json.dumps({"ok": True, "userId": "user-42"})},
            {"payload": json.dumps({"applied": True, "summary": "settled"})},
            {"payload": json.dumps({"applied": False, "summary": "duplicate ignored"})},
        ]
        with (
            mock.patch.object(probe, "request_json", side_effect=responses),
            mock.patch("builtins.print"),
        ):
            probe.run("http://nakama", "server-key", 3.0)

        responses[-1] = {
            "payload": json.dumps({"applied": True, "summary": "applied twice"})
        }
        with mock.patch.object(probe, "request_json", side_effect=responses):
            with self.assertRaisesRegex(probe.ProbeError, "applied twice"):
                probe.run("http://nakama", "server-key", 3.0)


if __name__ == "__main__":
    unittest.main()
