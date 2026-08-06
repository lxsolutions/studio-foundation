"""Conformance corpus runner (Python side).

Every valid fixture must produce the committed final state, hash log, and
navigation; every invalid fixture must fail with the committed error code.
The same corpus drives the Rust and Wasm kernels — that is what makes
"same semantics" a checked property rather than one lucky hash.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import kernel  # noqa: E402

CORPUS = Path(__file__).resolve().parents[1] / "conformance" / "v0.1"


class Conformance(unittest.TestCase):
    def test_valid_fixtures_match_committed_expectations(self):
        fixtures = sorted((CORPUS / "valid").glob("*.json"))
        self.assertGreaterEqual(len(fixtures), 5)
        for path in fixtures:
            with self.subTest(fixture=path.name):
                fixture = json.loads(path.read_text())
                result = kernel.run_replay(path)
                expect = fixture["expect"]
                self.assertEqual(result["final_state"], expect["final_state"])
                self.assertEqual(result["hash_log"], expect["hash_log"])
                self.assertEqual(result["state_hash"], expect["state_hash"])
                self.assertEqual(result["navigation"], expect["navigation"])

    def test_invalid_fixtures_fail_with_the_committed_error_code(self):
        fixtures = sorted((CORPUS / "invalid").glob("*.json"))
        self.assertGreaterEqual(len(fixtures), 8)
        for path in fixtures:
            with self.subTest(fixture=path.name):
                fixture = json.loads(path.read_text())
                with self.assertRaises(kernel.SimError) as ctx:
                    kernel.run_replay(path)
                self.assertEqual(ctx.exception.code, fixture["expect_error"])

    def test_same_visible_state_different_drive_pair(self):
        a = kernel.run_replay(CORPUS / "state" / "same_visible_different_drive_a.json")
        b = kernel.run_replay(CORPUS / "state" / "same_visible_different_drive_b.json")
        self.assertEqual(
            a["final_state"]["fortress_gate"]["state"]["openness"],
            b["final_state"]["fortress_gate"]["state"]["openness"],
        )
        self.assertNotEqual(a["state_hash"], b["state_hash"])


if __name__ == "__main__":
    unittest.main()
