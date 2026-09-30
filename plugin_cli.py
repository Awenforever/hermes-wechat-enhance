"""Operator CLI for the v0.21 Weixin enhancement package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
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


def _install_manifest_path() -> Path:
    return _hermes_home() / "plugin-data" / "hermes-wechat-enhance" / "install" / "manifest.json"


def _config_path() -> Path:
    return _hermes_home() / "config.yaml"


def _split_lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def _display_block(lines: list[str]) -> tuple[int | None, int | None, int | None]:
    display = None
    end = None
    busy = None
    for index, line in enumerate(lines):
        if re.match(r"^display\s*:\s*(?:#.*)?(?:\r?\n)?$", line):
            display = index
            break
    if display is None:
        return None, None, None
    end = len(lines)
    for index in range(display + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line.lstrip().startswith("#") and not line[:1].isspace():
            end = index
            break
        if re.match(r"^[ \t]+busy_input_mode\s*:", line):
            busy = index
    return display, end, busy


def _busy_raw_value(line: str) -> str:
    match = re.match(r"^[ \t]+busy_input_mode\s*:\s*([^#\r\n]*?)\s*(?:#.*)?(?:\r?\n)?$", line)
    return match.group(1).strip() if match else ""


def _normalized_scalar(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.strip().lower()


def _atomic_write_text(path: Path, text: str) -> None:
    mode = path.stat().st_mode
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _ensure_queue_mode(previous: dict) -> dict:
    """Make Hermes queue concurrent inbound messages without owning its config."""
    path = _config_path()
    if not path.is_file():
        return {"changed": False, "config_present": False, "reason": "config_missing"}
    text = path.read_text(encoding="utf-8")
    lines = _split_lines(text)
    display, end, busy = _display_block(lines)
    current = _busy_raw_value(lines[busy]) if busy is not None else ""
    if _normalized_scalar(current) == "queue":
        existing = previous.get("busy_input_mode")
        if isinstance(existing, dict) and existing.get("changed"):
            return existing
        return {"changed": False, "config_present": True, "already_queue": True}

    existing = previous.get("busy_input_mode")
    if isinstance(existing, dict) and existing.get("changed"):
        record = dict(existing)
    else:
        record = {
            "changed": True,
            "config_present": True,
            "had_display": display is not None,
            "had_key": busy is not None,
            "previous_raw_value": current if busy is not None else None,
        }

    newline = "\r\n" if "\r\n" in text else "\n"
    if busy is not None:
        indent = re.match(r"^([ \t]+)", lines[busy]).group(1)
        comment = ""
        if "#" in lines[busy]:
            comment = "  #" + lines[busy].split("#", 1)[1].rstrip("\r\n")
        lines[busy] = f"{indent}busy_input_mode: queue{comment}{newline}"
    elif display is not None:
        lines.insert(display + 1, f"  busy_input_mode: queue{newline}")
    else:
        if text and not text.endswith(("\n", "\r")):
            lines.append(newline)
        lines.extend([f"display:{newline}", f"  busy_input_mode: queue{newline}"])
    _atomic_write_text(path, "".join(lines))
    return record


def _restore_queue_mode(record: object) -> dict:
    if not isinstance(record, dict) or not record.get("changed"):
        return {"restored": False, "reason": "not_owned"}
    path = _config_path()
    if not path.is_file():
        return {"restored": False, "reason": "config_missing"}
    text = path.read_text(encoding="utf-8")
    lines = _split_lines(text)
    display, end, busy = _display_block(lines)
    if busy is None or _normalized_scalar(_busy_raw_value(lines[busy])) != "queue":
        return {"restored": False, "reason": "changed_by_user"}
    newline = "\r\n" if "\r\n" in text else "\n"
    if record.get("had_key"):
        indent = re.match(r"^([ \t]+)", lines[busy]).group(1)
        lines[busy] = f"{indent}busy_input_mode: {record.get('previous_raw_value')}{newline}"
    else:
        lines.pop(busy)
        if not record.get("had_display") and display is not None:
            lines.pop(display)
    _atomic_write_text(path, "".join(lines))
    return {"restored": True}


def _tree_hash(path: Path) -> str | None:
    if not path.is_dir():
        return None
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        relative = item.relative_to(path)
        if "__pycache__" in relative.parts or item.suffix.lower() in {".pyc", ".pyo"}:
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        if item.is_file():
            digest.update(b"F")
            digest.update(item.read_bytes())
        elif item.is_dir():
            digest.update(b"D")
    return digest.hexdigest()


def _read_manifest() -> dict:
    try:
        value = json.loads(_install_manifest_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_manifest(value: dict) -> None:
    path = _install_manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _runtime_status() -> dict:
    path = _hermes_home() / "plugin-data" / "hermes-wechat-enhance" / "runtime-status.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def register_cli(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="wechat_enhance_action")
    actions.add_parser("status", help="Show install and legacy-queue status")
    actions.add_parser("install-hook", help="Install or refresh the profile-scoped gateway hook")
    actions.add_parser("uninstall-hook", help="Remove owned hook code while preserving all user state")
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
    previous = _read_manifest()
    current_hash = _tree_hash(target)
    source_hash = _tree_hash(source)
    previous_owned = bool(
        previous.get("installed") is True
        and current_hash
        and current_hash == previous.get("installed_hash")
    )
    backup = str(previous.get("original_backup") or "") or None
    if target.exists() and not previous_owned and current_hash != source_hash:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = _hook_backup_root() / stamp
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        target.replace(backup_path)
        backup = str(backup_path)
    elif target.exists():
        shutil.rmtree(target)
    stage.replace(target)
    installed_hash = _tree_hash(target)
    busy_input_mode = _ensure_queue_mode(previous)
    _write_manifest({
        "schema_version": 1,
        "owner": "hermes-wechat-enhance",
        "installed": True,
        "hook": str(target),
        "installed_hash": installed_hash,
        "original_backup": backup,
        "busy_input_mode": busy_input_mode,
        "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    print(json.dumps({"ok": True, "hook": str(target), "backup": str(backup) if backup else None}))
    return 0


def _uninstall_hook() -> int:
    target = _hook_target()
    manifest = _read_manifest()
    if manifest.get("owner") != "hermes-wechat-enhance" or manifest.get("installed") is not True:
        print(json.dumps({"ok": False, "reason": "owned_install_manifest_missing"}))
        return 2
    current_hash = _tree_hash(target)
    if current_hash is not None and current_hash != manifest.get("installed_hash"):
        print(json.dumps({"ok": False, "reason": "hook_changed_outside_plugin"}))
        return 3
    restored = False
    backup_text = str(manifest.get("original_backup") or "").strip()
    backup = Path(backup_text) if backup_text else None
    if backup is not None and not backup.is_dir():
        print(json.dumps({"ok": False, "reason": "original_hook_backup_missing"}))
        return 4
    if target.exists():
        shutil.rmtree(target)
    if backup_text:
        target.parent.mkdir(parents=True, exist_ok=True)
        assert backup is not None
        backup.replace(target)
        restored = True
    config_restore = _restore_queue_mode(manifest.get("busy_input_mode"))
    manifest.update({
        "installed": False,
        "installed_hash": None,
        "original_backup": None,
        "last_uninstalled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "busy_input_mode_restore": config_restore,
    })
    _write_manifest(manifest)
    print(json.dumps({"ok": True, "hook_removed": not target.exists() or restored, "restored_previous": restored, "config_restore": config_restore}))
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
    if action == "uninstall-hook":
        return _uninstall_hook()
    if action == "migrate-v018":
        return _migrate(_legacy_queue_path(getattr(args, "queue_file", None)))
    if action in {None, "status"}:
        queue = _legacy_queue_path()
        runtime = _runtime_status()
        capabilities = runtime.get("capabilities") if isinstance(runtime.get("capabilities"), dict) else {}
        runtime_active = (
            not runtime.get("errors")
            and bool(runtime.get("installed") or runtime.get("already"))
            and capabilities.get("durable_fifo") is True
            and capabilities.get("continue_intercept") is True
        )
        print(
            json.dumps(
                {
                    "ok": runtime_active,
                    "hermes_home": str(_hermes_home()),
                    "hook_installed": (_hook_target() / "HOOK.yaml").is_file(),
                    "runtime_active": runtime_active,
                    "runtime": runtime,
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
