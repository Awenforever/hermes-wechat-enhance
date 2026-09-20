#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from argparse import Namespace
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="wechat-pack-bootstrap-") as directory:
        os.environ["HERMES_HOME"] = directory
        constants = types.ModuleType("hermes_constants")
        constants.get_hermes_home = lambda: Path(directory)
        sys.modules["hermes_constants"] = constants
        import plugin_cli

        calls = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            return Namespace(returncode=0, stdout="{}", stderr="")

        args = Namespace(
            email_to=["a@example.com"], keyword=["wildfire smoke"],
            email_onboarding_json="@setup.json", enable_alive=True,
            enable_email_watchdog=True, skip_weekly_schedule=False,
        )
        with mock.patch.object(plugin_cli, "_hermes_cli", return_value="hermes"), mock.patch.object(plugin_cli.subprocess, "run", side_effect=fake_run):
            assert plugin_cli._bootstrap_pack(args) == 0
        assert (Path(directory) / "hooks" / "hermes-wechat-enhance" / "HOOK.yaml").is_file()
        expected = {
            ("hermes", "alive", "install-runtime"),
            ("hermes", "email-watchdog", "install-runtime"),
            ("hermes", "weekly-briefing", "schedule-install"),
            ("hermes", "alive", "enable"),
            ("hermes", "email-watchdog", "doctor"),
            ("hermes", "email-watchdog", "enable"),
        }
        assert expected.issubset({tuple(command) for command in calls})
        weekly = next(command for command in calls if command[:3] == ["hermes", "weekly-briefing", "init"])
        assert "a@example.com" in weekly and "wildfire smoke" in weekly
    print(json.dumps({"ok": True, "test": "production-pack-bootstrap"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
