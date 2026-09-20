"""Operator CLI for the v0.21 Weixin enhancement package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
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
    actions.add_parser("status", help="Show install, budget, and durable queue status")
    queue_list = actions.add_parser("queue-list", help="List pending deliveries without message content")
    queue_list.add_argument("--limit", type=int, default=100)
    queue_clear = actions.add_parser("queue-clear", help="Back up then clear pending deliveries")
    queue_clear.add_argument("--yes", action="store_true")
    actions.add_parser("install-hook", help="Install or refresh the profile-scoped gateway hook")
    migrate = actions.add_parser("migrate-v018", help="Archive and retire v0.18 queued messages")
    migrate.add_argument("--queue-file", default=None, help="Legacy queue JSON path")
    bootstrap = actions.add_parser("bootstrap-pack", help="Configure the four-plugin production pack")
    bootstrap.add_argument("--email-to", action="append", default=[])
    bootstrap.add_argument("--keyword", action="append", default=[])
    bootstrap.add_argument("--email-onboarding-json", default=None)
    bootstrap.add_argument("--enable-alive", action="store_true")
    bootstrap.add_argument("--enable-email-watchdog", action="store_true")
    bootstrap.add_argument("--skip-weekly-schedule", action="store_true")
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


def _runtime_db_path() -> Path:
    configured = os.environ.get("HERMES_WECHAT_ENHANCE_RUNTIME_DB", "").strip()
    if configured:
        return Path(configured).expanduser()
    return _hermes_home() / "plugin-data" / "hermes-wechat-enhance" / "runtime.sqlite3"


def _runtime_status(path: Path) -> dict:
    if not path.is_file():
        return {"database": str(path), "exists": False, "pending": 0, "chats": 0, "budgets": 0}
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=10.0)) as conn:
        pending, chats = conn.execute(
            "SELECT COUNT(*),COUNT(DISTINCT chat_key) FROM outbound_queue WHERE state='queued'"
        ).fetchone()
        budgets = conn.execute("SELECT COUNT(*) FROM budgets").fetchone()[0]
        oldest = conn.execute(
            "SELECT MIN(created_at) FROM outbound_queue WHERE state='queued'"
        ).fetchone()[0]
    return {
        "database": str(path), "exists": True, "pending": int(pending or 0),
        "chats": int(chats or 0), "budgets": int(budgets or 0), "oldest_created_at": oldest,
    }


def _runtime_queue_list(path: Path, limit: int) -> int:
    if not path.is_file():
        print(json.dumps({"ok": True, "database": str(path), "items": []}, indent=2))
        return 0
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=10.0)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT seq,chat_key,delivery_id,chunk_index,model_name,created_at,expires_at,"
            "LENGTH(content) AS content_chars,last_error FROM outbound_queue "
            "WHERE state='queued' ORDER BY seq LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["chat"] = str(item.pop("chat_key"))[:12]
        item["delivery"] = hashlib.sha256(str(item.pop("delivery_id")).encode()).hexdigest()[:12]
        items.append(item)
    print(json.dumps({"ok": True, "database": str(path), "items": items}, indent=2))
    return 0


def _runtime_queue_clear(path: Path, confirmed: bool) -> int:
    if not confirmed:
        raise SystemExit("queue-clear requires --yes")
    if not path.is_file():
        print(json.dumps({"ok": True, "database": str(path), "cleared": 0, "backup": None}))
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = _hermes_home() / "plugin-data" / "hermes-wechat-enhance" / "queue-backups" / f"runtime.{stamp}.sqlite3"
    backup.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(path), timeout=10.0)) as source, closing(sqlite3.connect(str(backup))) as target:
        source.backup(target)
        cursor = source.execute("DELETE FROM outbound_queue WHERE state='queued'")
        cleared = cursor.rowcount
        source.commit()
    print(json.dumps({"ok": True, "database": str(path), "cleared": cleared, "backup": str(backup)}))
    return 0


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


def _hermes_cli() -> str:
    candidate = shutil.which("hermes")
    if candidate:
        return candidate
    if Path(sys.argv[0]).is_file():
        return str(Path(sys.argv[0]).resolve())
    raise RuntimeError("cannot locate the Hermes CLI")


def _bootstrap_pack(args: argparse.Namespace) -> int:
    results: list[dict[str, object]] = []
    _install_hook()
    results.append({"step": "wechat-hook", "ok": True})
    cli = _hermes_cli()

    def run(step: str, command: list[str]) -> bool:
        completed = subprocess.run(command, text=True, capture_output=True, timeout=240)
        results.append({"step": step, "ok": completed.returncode == 0, "returncode": completed.returncode})
        return completed.returncode == 0

    required = [
        ("alive-runtime", [cli, "alive", "install-runtime"]),
        ("email-runtime", [cli, "email-watchdog", "install-runtime"]),
    ]
    for step, command in required:
        if not run(step, command):
            print(json.dumps({"ok": False, "results": results}, indent=2))
            return 2

    onboarding = getattr(args, "email_onboarding_json", None)
    if onboarding and not run(
        "email-onboarding",
        [cli, "email-watchdog", "onboarding-apply", "--input-json", onboarding],
    ):
        print(json.dumps({"ok": False, "results": results}, indent=2))
        return 2

    weekly = [cli, "weekly-briefing", "init"]
    for address in list(getattr(args, "email_to", []) or []):
        weekly.extend(["--email-to", address])
    for keyword in list(getattr(args, "keyword", []) or []):
        weekly.extend(["--keyword", keyword])
    if not run("weekly-init", weekly):
        print(json.dumps({
            "ok": False,
            "customization_required": "provide --email-to and --keyword for a new profile",
            "results": results,
        }, indent=2))
        return 2
    if not bool(getattr(args, "skip_weekly_schedule", False)) and not run(
        "weekly-schedule", [cli, "weekly-briefing", "schedule-install"]
    ):
        print(json.dumps({"ok": False, "results": results}, indent=2))
        return 2
    if bool(getattr(args, "enable_alive", False)):
        run("alive-enable", [cli, "alive", "enable"])
    if bool(getattr(args, "enable_email_watchdog", False)):
        if not onboarding:
            results.append({"step": "email-enable", "ok": False, "reason": "onboarding input required"})
        elif run("email-doctor", [cli, "email-watchdog", "doctor"]):
            run("email-enable", [cli, "email-watchdog", "enable"])
    ok = all(bool(item.get("ok")) for item in results)
    print(json.dumps({
        "ok": ok,
        "results": results,
        "restart_required": True,
        "next": "review status, then restart the Hermes gateway once",
    }, indent=2))
    return 0 if ok else 2


def wechat_enhance_command(args: argparse.Namespace) -> int:
    action = getattr(args, "wechat_enhance_action", None)
    if action == "install-hook":
        return _install_hook()
    if action == "migrate-v018":
        return _migrate(_legacy_queue_path(getattr(args, "queue_file", None)))
    if action == "bootstrap-pack":
        return _bootstrap_pack(args)
    if action == "queue-list":
        return _runtime_queue_list(_runtime_db_path(), getattr(args, "limit", 100))
    if action == "queue-clear":
        return _runtime_queue_clear(_runtime_db_path(), bool(getattr(args, "yes", False)))
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
                    "v021_reliable_delivery": _runtime_status(_runtime_db_path()),
                },
                indent=2,
            )
        )
        return 0
    print(f"Unknown action: {action}")
    return 2
