#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

# HERMES_WECHAT_TRANSACTION_SNAPSHOT_SOURCE_PATH_V2
# HERMES_WECHAT_GIT_METADATA_PRESERVATION_V1
# HERMES_WECHAT_EXACT_FILE_BACKUP_RESTORE_V1
TOUCHED = (
    "gateway/platforms/weixin.py",
    "gateway/platforms/base.py",
    "gateway/run.py",
)

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

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

def run_git(gateway: Path, *args: str) -> tuple[int, str]:
    process = subprocess.run(
        ["git", "-C", str(gateway), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return process.returncode, process.stdout.strip()

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
            print("INSTALL_STATE_REUSED")
            return

    remove_path(root)
    backups = root / "backups"
    files: dict[str, dict[str, Any]] = {}
    for relative in TOUCHED:
        gateway_file = gateway / relative
        if not gateway_file.is_file():
            raise SystemExit(
                f"missing gateway source file: {gateway_file}"
            )
        destination = backups / "gateway" / relative
        copy_path(gateway_file, destination)
        files[relative] = {
            "pre_sha256": sha256_file(gateway_file),
            "backup": str(destination.relative_to(root)),
        }

    hook_existed = hook.exists() or hook.is_symlink()
    if hook_existed:
        copy_path(hook, backups / "hook")

    source_existed = source.exists() or source.is_symlink()
    if source_existed:
        copy_path(source, backups / "source")

    git_rc, pre_head = run_git(gateway, "rev-parse", "HEAD")
    status_rc, pre_status = run_git(gateway, "status", "--porcelain")
    manifest = {
        "version": 2,
        "active": True,
        "installed_recorded": False,
        "gateway": str(gateway),
        "hook": str(hook),
        "source": str(source),
        "files": files,
        "hook_existed": hook_existed,
        "hook_pre_hash": tree_hash(hook),
        "source_existed": source_existed,
        "source_pre_hash": tree_hash(source),
        "git_present": git_rc == 0,
        "pre_git_head": pre_head if git_rc == 0 else None,
        "pre_git_clean": status_rc == 0 and not pre_status,
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
    for relative, entry in manifest["files"].items():
        entry["installed_sha256"] = sha256_file(gateway / relative)
    manifest["hook_installed_hash"] = tree_hash(hook)
    manifest["source_installed_hash"] = tree_hash(source)
    git_rc, installed_head = run_git(gateway, "rev-parse", "HEAD")
    manifest["installed_git_head"] = installed_head if git_rc == 0 else None
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
        for relative, entry in manifest["files"].items():
            current = gateway / relative
            current_hash = sha256_file(current) if current.is_file() else None
            if current_hash not in {entry.get("pre_sha256"), entry.get("installed_sha256")}:
                divergences.append(relative)
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

        if manifest.get("git_present") is True:
            git_rc, current_head = run_git(gateway, "rev-parse", "HEAD")
            allowed_heads = {
                manifest.get("pre_git_head"),
                manifest.get("installed_git_head"),
            }
            if git_rc != 0 or current_head not in allowed_heads:
                divergences.append("git-head")

        if divergences:
            raise SystemExit(
                "SOURCE_DIVERGED; refusing restore: " + ",".join(divergences)
            )

    # The pre-install working tree may intentionally differ from Git HEAD.
    # Restore the exact transaction snapshots and leave Git metadata untouched.
    for relative, entry in manifest["files"].items():
        copy_path(root / entry["backup"], gateway / relative)

    hook = Path(manifest["hook"])
    remove_path(hook)
    if manifest.get("hook_existed"):
        copy_path(root / "backups" / "hook", hook)

    source = Path(manifest["source"])
    remove_path(source)
    if manifest.get("source_existed"):
        copy_path(root / "backups" / "source", source)

    if manifest.get("git_present") is not True:
        remove_path(gateway / ".git")

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
                "git_present": manifest.get("git_present"),
                "pre_git_clean": manifest.get("pre_git_clean"),
                "file_count": len(manifest.get("files") or {}),
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
