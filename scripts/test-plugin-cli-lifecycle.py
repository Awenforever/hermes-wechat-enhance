#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("wechat_plugin_cli_test", ROOT / "plugin_cli.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="wechat-plugin-lifecycle-") as raw:
        home = Path(raw) / "home"
        hermes_constants = types.ModuleType("hermes_constants")
        hermes_constants.get_hermes_home = lambda: home
        sys.modules["hermes_constants"] = hermes_constants

        target = home / "hooks" / "hermes-wechat-enhance"
        target.mkdir(parents=True)
        (target / "original.txt").write_text("original\n", encoding="utf-8")

        require(MODULE._install_hook() == 0, "install failed")
        manifest = json.loads(MODULE._install_manifest_path().read_text(encoding="utf-8"))
        backup = Path(manifest["original_backup"])
        require(backup.is_dir(), "original hook was not backed up")
        require(MODULE._install_hook() == 0, "idempotent reinstall failed")
        require(Path(json.loads(MODULE._install_manifest_path().read_text(encoding="utf-8"))["original_backup"]) == backup, "reinstall replaced original backup")

        require(MODULE._uninstall_hook() == 0, "uninstall failed")
        require((target / "original.txt").read_text(encoding="utf-8") == "original\n", "original hook was not restored")

        require(MODULE._install_hook() == 0, "second install failed")
        (target / "external-change.txt").write_text("owned elsewhere\n", encoding="utf-8")
        require(MODULE._uninstall_hook() == 3, "external modification was not protected")
        require((target / "external-change.txt").is_file(), "modified hook was removed")

    print("PLUGIN_CLI_LIFECYCLE_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
