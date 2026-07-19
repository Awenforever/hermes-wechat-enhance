#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


TOUCHED = (
    "gateway/platforms/weixin.py",
    "gateway/platforms/base.py",
    "gateway/run.py",
)


def run(
    *args: str,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    manager = Path(__file__).with_name(
        "manage-install-state.py"
    ).resolve()

    with tempfile.TemporaryDirectory(
        prefix="wechat-enhance-git-preservation-"
    ) as temporary:
        root = Path(temporary)
        gateway = root / "gateway-root"
        home = root / "home"
        hook = home / "hooks" / "hermes-wechat-enhance"
        source = home / "skills" / "hermes-wechat-enhance"

        gateway.mkdir()
        for relative in TOUCHED:
            target = gateway / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                f"official:{relative}\n",
                encoding="utf-8",
            )

        unrelated = gateway / "unrelated.txt"
        unrelated.write_text("official-unrelated\n", encoding="utf-8")

        run("git", "init", cwd=gateway)
        run(
            "git",
            "config",
            "user.email",
            "fixture@local.invalid",
            cwd=gateway,
        )
        run(
            "git",
            "config",
            "user.name",
            "Fixture",
            cwd=gateway,
        )
        run("git", "add", "-A", cwd=gateway)
        run(
            "git",
            "-c",
            "user.email=fixture@local.invalid",
            "-c",
            "user.name=Fixture",
            "-c",
            "commit.gpgSign=false",
            "commit",
            "-m",
            "official",
            cwd=gateway,
        )

        expected_files: dict[str, bytes] = {}
        for relative in TOUCHED:
            target = gateway / relative
            target.write_text(
                f"legacy-runtime:{relative}\n",
                encoding="utf-8",
            )
            expected_files[relative] = target.read_bytes()

        unrelated.write_text(
            "intentional-unrelated-dirty-state\n",
            encoding="utf-8",
        )
        expected_unrelated = unrelated.read_bytes()

        hook.mkdir(parents=True)
        (hook / "PREVIOUS_HOOK.txt").write_text(
            "PREVIOUS_HOOK\n",
            encoding="utf-8",
        )
        source.mkdir(parents=True)
        (source / "PREVIOUS_SOURCE.txt").write_text(
            "PREVIOUS_SOURCE\n",
            encoding="utf-8",
        )

        head_before = run(
            "git",
            "rev-parse",
            "HEAD",
            cwd=gateway,
        ).stdout
        config_before = (gateway / ".git" / "config").read_bytes()
        status_before = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z"],
            cwd=gateway,
            check=True,
            stdout=subprocess.PIPE,
        ).stdout

        common = [
            "--gateway",
            str(gateway),
            "--home",
            str(home),
            "--hook",
            str(hook),
            "--source",
            str(source),
        ]

        snapshot = run(
            sys.executable,
            str(manager),
            "snapshot",
            *common,
        )
        require(
            "INSTALL_STATE_SNAPSHOT_OK" in snapshot.stdout,
            "snapshot marker missing",
        )

        for relative in TOUCHED:
            (gateway / relative).write_text(
                f"installed:{relative}\n",
                encoding="utf-8",
            )
        (hook / "PREVIOUS_HOOK.txt").write_text(
            "INSTALLED_HOOK\n",
            encoding="utf-8",
        )
        (source / "PREVIOUS_SOURCE.txt").write_text(
            "INSTALLED_SOURCE\n",
            encoding="utf-8",
        )

        record = run(
            sys.executable,
            str(manager),
            "record-installed",
            *common,
        )
        require(
            "INSTALL_STATE_RECORDED_OK" in record.stdout,
            "record-installed marker missing",
        )

        rollback = run(
            sys.executable,
            str(manager),
            "rollback",
            *common,
        )
        require(
            "INSTALL_STATE_RESTORE_OK" in rollback.stdout,
            "rollback marker missing",
        )

        for relative, expected in expected_files.items():
            require(
                (gateway / relative).read_bytes() == expected,
                f"file snapshot not restored: {relative}",
            )
        require(
            unrelated.read_bytes() == expected_unrelated,
            "unrelated dirty file was altered",
        )
        require(
            (hook / "PREVIOUS_HOOK.txt").read_text(
                encoding="utf-8"
            ) == "PREVIOUS_HOOK\n",
            "previous hook not restored",
        )
        require(
            (source / "PREVIOUS_SOURCE.txt").read_text(
                encoding="utf-8"
            ) == "PREVIOUS_SOURCE\n",
            "previous source not restored",
        )

        require(
            run("git", "rev-parse", "HEAD", cwd=gateway).stdout
            == head_before,
            "Git HEAD changed",
        )
        require(
            (gateway / ".git" / "config").read_bytes()
            == config_before,
            "Git config changed",
        )

        status_after = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z"],
            cwd=gateway,
            check=True,
            stdout=subprocess.PIPE,
        ).stdout
        require(
            status_after == status_before,
            (
                "Git working-tree/index status changed:\n"
                f"before={status_before!r}\n"
                f"after={status_after!r}"
            ),
        )

        print("INSTALL_STATE_GIT_WORKTREE_PRESERVATION_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
