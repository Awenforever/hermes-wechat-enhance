"""Operator CLI for the v0.21 Weixin enhancement package."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


def _hermes_home() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home()


def _source_root() -> Path:
    return Path(__file__).resolve().parent


def _hook_target() -> Path:
    return _hermes_home() / "hooks" / "hermes-wechat-enhance"


def _hook_backup_root() -> Path:
    return _hermes_home() / "plugin-data" / "hermes-wechat-enhance" / "hook-backups"


def register_cli(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="wechat_enhance_action")
    actions.add_parser("status", help="Show install and legacy-queue status")
    actions.add_parser("install-hook", help="Install or refresh the profile-scoped gateway hook")
    migrate = actions.add_parser("migrate-v018", help="Archive and retire v0.18 queued messages")
    migrate.add_argument("--queue-file", default=None, help="Legacy queue JSON path")
    parser.set_defaults(func=wechat_enhance_command)


def _read_queue_count(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return -1
    if isinstance(payload, dict):
        entries = payload.get("entries", payload.get("queue", payload))
        if isinstance(entries, list):
            return len(entries)
        if isinstance(entries, dict):
            return sum(len(value) if isinstance(value, list) else 1 for value in entries.values())
    return 0


def _legacy_queue_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    configured = os.environ.get("HERMES_WECHAT_QUEUE_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return _hermes_home() / "weixin_budget" / "message_send_queue.json"


def _install_hook() -> int:
    source = _source_root() / "hooks" / "hermes-wechat-enhance"
    target = _hook_target()
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.with_name(f".{target.name}.stage")
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(source, stage)
    backup = None
    if target.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = _hook_backup_root() / stamp
        backup.parent.mkdir(parents=True, exist_ok=True)
        target.replace(backup)
    stage.replace(target)
    print(json.dumps({"ok": True, "hook": str(target), "backup": str(backup) if backup else None}))
    return 0


def _migrate(queue_path: Path) -> int:
    count = _read_queue_count(queue_path)
    if not queue_path.exists():
        print(json.dumps({"ok": True, "legacy_queue": str(queue_path), "discarded": 0, "backup": None}))
        return 0
    archive_dir = _hermes_home() / "migration-archive" / "hermes-wechat-enhance-v018"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = archive_dir / f"{queue_path.name}.{stamp}.not-replayed"
    shutil.copy2(queue_path, backup)
    queue_path.unlink()
    receipt = archive_dir / f"migration-{stamp}.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": str(queue_path),
                "backup": str(backup),
                "discarded_without_replay": count,
                "migrated_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "legacy_queue": str(queue_path), "discarded": count, "backup": str(backup)}))
    return 0


def wechat_enhance_command(args: argparse.Namespace) -> int:
    action = getattr(args, "wechat_enhance_action", None)
    if action == "install-hook":
        return _install_hook()
    if action == "migrate-v018":
        return _migrate(_legacy_queue_path(getattr(args, "queue_file", None)))
    if action in {None, "status"}:
        queue = _legacy_queue_path()
        print(
            json.dumps(
                {
                    "ok": True,
                    "hermes_home": str(_hermes_home()),
                    "hook_installed": (_hook_target() / "HOOK.yaml").is_file(),
                    "legacy_queue": str(queue),
                    "legacy_queue_entries": _read_queue_count(queue),
                    "v021_native_context_tokens": True,
                },
                indent=2,
            )
        )
        return 0
    print(f"Unknown action: {action}")
    return 2
