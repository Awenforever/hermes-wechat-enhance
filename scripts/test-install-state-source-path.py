#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    manager = Path(__file__).with_name("manage-install-state.py").resolve()

    with tempfile.TemporaryDirectory(
        prefix="wechat-enhance-state-source-path-"
    ) as temporary:
        root = Path(temporary)
        gateway = root / "gateway"
        home = root / "home"
        hook = home / "hooks" / "hermes-wechat-enhance"
        source = home / "skills" / "hermes-wechat-enhance"

        for relative in (
            "gateway/platforms/weixin.py",
            "gateway/platforms/base.py",
            "gateway/run.py",
        ):
            target = gateway / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                f"fixture:{relative}\n",
                encoding="utf-8",
            )

        hook.mkdir(parents=True)
        (hook / "handler.py").write_text(
            "PREVIOUS_HOOK\n",
            encoding="utf-8",
        )
        source.mkdir(parents=True)
        (source / "PREVIOUS_SOURCE.txt").write_text(
            "PREVIOUS_SOURCE\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(manager),
                "snapshot",
                "--gateway",
                str(gateway),
                "--home",
                str(home),
                "--hook",
                str(hook),
                "--source",
                str(source),
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        require(
            result.returncode == 0,
            f"snapshot failed: {result.stdout}\n{result.stderr}",
        )
        require(
            "INSTALL_STATE_SNAPSHOT_OK" in result.stdout,
            "snapshot marker missing",
        )

        manifest_path = (
            home
            / ".hermes"
            / "wechat-enhance"
            / "install-state"
            / "manifest.json"
        )
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )

        require(
            Path(manifest["source"]).resolve() == source.resolve(),
            (
                "manifest source path was shadowed: "
                f"{manifest['source']} != {source}"
            ),
        )
        require(
            not str(manifest["source"]).endswith("gateway/run.py"),
            "manifest source incorrectly points to gateway/run.py",
        )
        require(
            manifest["source_existed"] is True,
            "existing canonical source not recorded",
        )
        require(
            (
                manifest_path.parent
                / "backups"
                / "source"
                / "PREVIOUS_SOURCE.txt"
            ).is_file(),
            "canonical source backup missing",
        )

        print("INSTALL_STATE_SOURCE_PATH_REGRESSION_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
