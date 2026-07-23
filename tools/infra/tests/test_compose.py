from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

COMPOSE_PATH = Path(__file__).resolve().parents[1] / "compose.py"
SPEC = importlib.util.spec_from_file_location("studio_infra_compose", COMPOSE_PATH)
assert SPEC is not None and SPEC.loader is not None
compose = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compose)


class RemoteSyncTests(unittest.TestCase):
    def test_sync_copies_generic_infra_and_nakama_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            with (
                mock.patch.object(compose, "REPO", repo),
                mock.patch.object(compose.subprocess, "call", return_value=0) as call,
            ):
                self.assertEqual(compose._sync("dev-host", "~/studio-infra"), 0)

        calls = [entry.args[0] for entry in call.call_args_list]
        self.assertEqual(
            calls[0],
            ["ssh", "dev-host", "mkdir -p ~/studio-infra/nakama"],
        )
        self.assertEqual(
            calls[1],
            [
                "scp",
                "-r",
                "-q",
                str(repo / "infra" / "compose.yaml"),
                str(repo / "infra" / "postgres"),
                "dev-host:~/studio-infra/",
            ],
        )
        self.assertEqual(
            calls[2],
            [
                "scp",
                "-r",
                "-q",
                str(repo / "infra" / "nakama" / "build"),
                str(repo / "infra" / "nakama" / "local.yml"),
                "dev-host:~/studio-infra/nakama/",
            ],
        )
        self.assertNotIn("node_modules", " ".join(calls[2]))

    def test_sync_copies_optional_env_after_static_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / ".env").write_text(
                "STUDIO_PG_HOST=127.0.0.1\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(compose, "REPO", repo),
                mock.patch.object(compose.subprocess, "call", return_value=0) as call,
            ):
                self.assertEqual(compose._sync("dev-host", "/srv/studio"), 0)

        self.assertEqual(
            call.call_args_list[-1].args[0],
            ["scp", "-q", str(repo / ".env"), "dev-host:/srv/studio/.env"],
        )


if __name__ == "__main__":
    unittest.main()
