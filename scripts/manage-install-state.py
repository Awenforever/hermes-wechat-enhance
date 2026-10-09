#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

# HERMES_WECHAT_TRANSACTION_SNAPSHOT_SOURCE_PATH_V2
# HERMES_WECHAT_HOOK_ONLY_TRANSACTION_V1

TRANSIENT_TREE_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
TRANSIENT_TREE_SUFFIXES = {
    ".pyc",
    ".pyo",
}


def _is_transient_tree_path(relative: Path) -> bool:
    if any(part in TRANSIENT_TREE_PARTS for part in relative.parts):
        return True
    return relative.suffix.lower() in TRANSIENT_TREE_SUFFIXES


def tree_hash(path: Path) -> str | None:
    """Hash managed hook content while ignoring runtime cache artifacts."""
    if not path.exists() and not path.is_symlink():
        return None
    digest = hashlib.sha256()
    if path.is_file() or path.is_symlink():
        digest.update(path.name.encode())
        if path.is_symlink():
            digest.update(os.readlink(path).encode())
        else:
            digest.update(path.read_bytes())
        return digest.hexdigest()

    for item in sorted(path.rglob("*")):
        relative = item.relative_to(path)
        if _is_transient_tree_path(relative):
            continue
        digest.update(relative.as_posix().encode())
        if item.is_symlink():
            digest.update(b"L")
            digest.update(os.readlink(item).encode())
        elif item.is_file():
            digest.update(b"F")
            digest.update(item.read_bytes())
        elif item.is_dir():
            digest.update(b"D")
    return digest.hexdigest()

def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)
    path.chmod(0o600)

def state_paths(home: Path) -> tuple[Path, Path]:
    root = home / ".hermes" / "wechat-enhance" / "install-state"
    return root, root / "manifest.json"

def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)

def copy_path(source: Path, destination: Path) -> None:
    remove_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        destination.symlink_to(os.readlink(source))
    elif source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
    else:
        shutil.copy2(source, destination)

def snapshot(
    gateway: Path,
    home: Path,
    hook: Path,
    source: Path,
) -> None:
    root, manifest_path = state_paths(home)
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text("utf-8"))
        if manifest.get("active") is True:
            if int(manifest.get("version") or 0) < 3:
                for key in (
                    "files", "git_present", "pre_git_head", "pre_git_clean",
                    "installed_git_head",
                ):
                    manifest.pop(key, None)
                manifest["version"] = 3
                manifest["core_mutation"] = False
                remove_path(root / "backups" / "gateway")
                atomic_json(manifest_path, manifest)
                print("INSTALL_STATE_MIGRATED_TO_HOOK_ONLY")
            print("INSTALL_STATE_REUSED")
            return

    remove_path(root)
    backups = root / "backups"
    hook_existed = hook.exists() or hook.is_symlink()
    if hook_existed:
        copy_path(hook, backups / "hook")

    source_existed = source.exists() or source.is_symlink()
    if source_existed:
        copy_path(source, backups / "source")

    manifest = {
        "version": 3,
        "active": True,
        "installed_recorded": False,
        "gateway": str(gateway),
        "hook": str(hook),
        "source": str(source),
        "hook_existed": hook_existed,
        "hook_pre_hash": tree_hash(hook),
        "source_existed": source_existed,
        "source_pre_hash": tree_hash(source),
        "core_mutation": False,
    }
    atomic_json(manifest_path, manifest)
    print("INSTALL_STATE_SNAPSHOT_OK")

def record_installed(
    gateway: Path,
    home: Path,
    hook: Path,
    source: Path,
) -> None:
    root, manifest_path = state_paths(home)
    if not manifest_path.exists():
        raise SystemExit("install state manifest missing")
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["hook_installed_hash"] = tree_hash(hook)
    manifest["source_installed_hash"] = tree_hash(source)
    manifest["installed_recorded"] = True
    atomic_json(manifest_path, manifest)
    print("INSTALL_STATE_RECORDED_OK")

def restore_files(
    gateway: Path,
    root: Path,
    manifest: dict[str, Any],
    *,
    force: bool,
) -> None:
    if not force:
        divergences = []
        current_hook_hash = tree_hash(Path(manifest["hook"]))
        if current_hook_hash not in {
            manifest.get("hook_pre_hash"),
            manifest.get("hook_installed_hash"),
        }:
            divergences.append("hook")

        current_source_hash = tree_hash(Path(manifest["source"]))
        if current_source_hash not in {
            manifest.get("source_pre_hash"),
            manifest.get("source_installed_hash"),
        }:
            divergences.append("source")

        if divergences:
            raise SystemExit(
                "SOURCE_DIVERGED; refusing restore: " + ",".join(divergences)
            )

    hook = Path(manifest["hook"])
    remove_path(hook)
    if manifest.get("hook_existed"):
        copy_path(root / "backups" / "hook", hook)

    source = Path(manifest["source"])
    remove_path(source)
    if manifest.get("source_existed"):
        copy_path(root / "backups" / "source", source)


def restore(
    gateway: Path,
    home: Path,
    hook: Path,
    source: Path,
    *,
    force: bool,
) -> None:
    root, manifest_path = state_paths(home)
    if not manifest_path.exists():
        raise SystemExit("INSTALL_STATE_MISSING")
    manifest = json.loads(manifest_path.read_text("utf-8"))
    if Path(manifest["gateway"]).resolve() != gateway.resolve():
        raise SystemExit("gateway path mismatch in install state")
    if Path(manifest["hook"]).resolve() != hook.resolve():
        raise SystemExit("hook path mismatch in install state")
    if Path(manifest["source"]).resolve() != source.resolve():
        raise SystemExit("source path mismatch in install state")
    restore_files(gateway, root, manifest, force=force)
    remove_path(root)
    print("INSTALL_STATE_RESTORE_OK")

def status(home: Path) -> None:
    _, manifest_path = state_paths(home)
    if not manifest_path.exists():
        print(json.dumps({"active": False}, indent=2))
        return
    manifest = json.loads(manifest_path.read_text("utf-8"))
    print(
        json.dumps(
            {
                "active": manifest.get("active"),
                "installed_recorded": manifest.get("installed_recorded"),
                "core_mutation": False,
                "hook_existed": manifest.get("hook_existed"),
                "source_existed": manifest.get("source_existed"),
            },
            indent=2,
        )
    )

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("snapshot", "record-installed", "restore", "rollback", "status"),
    )
    parser.add_argument("--gateway", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--hook", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()

    gateway = args.gateway.resolve()
    home = args.home.resolve()
    hook = args.hook.resolve()
    source = args.source.resolve()

    if args.command == "snapshot":
        snapshot(gateway, home, hook, source)
    elif args.command == "record-installed":
        record_installed(gateway, home, hook, source)
    elif args.command == "restore":
        restore(gateway, home, hook, source, force=False)
    elif args.command == "rollback":
        restore(gateway, home, hook, source, force=True)
    else:
        status(home)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
