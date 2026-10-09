#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
GATEWAY_SRC="${HERMES_GATEWAY_SRC:-/opt/hermes}"
HERMES_HOME_DIR="${HERMES_HOME:-${HOME}/.hermes}"
HOOKS_DIR="${HERMES_HOOKS_DIR:-${HERMES_HOME_DIR}/hooks}"
HOOK_MODE="${HERMES_WECHAT_ENHANCE_HOOK_MODE:-copy}"
SOURCE_ROOT="${HERMES_SKILLS_DIR:-${HERMES_HOME_DIR}/skills}"
CANONICAL_SOURCE_DIR="${HERMES_WECHAT_ENHANCE_SOURCE_DIR:-${SOURCE_ROOT}/hermes-wechat-enhance}"
SOURCE_REEXEC_FLAG="${HERMES_WECHAT_ENHANCE_SOURCE_REEXEC:-0}"
STATE_MANAGER="$SKILL_DIR/scripts/manage-install-state.py"
INSTALL_STATE_ACTIVE=0

log() { printf '%s\n' "$*"; }
die() { printf '[FAIL] %s\n' "$*" >&2; exit 1; }

install_state() {
  python3 "$STATE_MANAGER" "$@" --gateway "$GATEWAY_SRC" \
    --home "$HERMES_HOME_DIR" --hook "$HOOKS_DIR/hermes-wechat-enhance" \
    --source "$CANONICAL_SOURCE_DIR"
}

install_exit_guard() {
  local rc=$?
  trap - EXIT
  if [ "$INSTALL_STATE_ACTIVE" = "1" ] && [ "$rc" -ne 0 ]; then
    log "[ROLLBACK] Restoring pre-install source and hook state"
    install_state rollback || true
  fi
  exit "$rc"
}
trap install_exit_guard EXIT

fault_inject() {
  [ "${HERMES_WECHAT_ENHANCE_FAULT_INJECT_STAGE:-}" != "$1" ] || \
    die "Synthetic transactional fault at $1"
}

install_canonical_source_if_needed() {
  local src_real dst_real
  mkdir -p "$(dirname "$CANONICAL_SOURCE_DIR")"
  src_real="$(cd "$SKILL_DIR" && pwd -P)"
  if [ -d "$CANONICAL_SOURCE_DIR" ]; then dst_real="$(cd "$CANONICAL_SOURCE_DIR" && pwd -P)"; else dst_real=""; fi
  if [ "$src_real" = "$dst_real" ]; then return; fi
  [ "$SOURCE_REEXEC_FLAG" != "1" ] || die "Canonical source re-exec did not converge"
  rm -rf "$CANONICAL_SOURCE_DIR"
  mkdir -p "$CANONICAL_SOURCE_DIR"
  (cd "$SKILL_DIR" && tar --exclude='./.git' --exclude='./__pycache__' \
    --exclude='./.pytest_cache' --exclude='./*.pyc' --exclude='./*.pyo' -cf - .) \
    | (cd "$CANONICAL_SOURCE_DIR" && tar -xf -)
  log "[OK] Source installed: $CANONICAL_SOURCE_DIR"
  HERMES_WECHAT_ENHANCE_SOURCE_REEXEC=1 exec bash "$CANONICAL_SOURCE_DIR/scripts/install.sh" "$@"
}

verify_current_hermes_contract() {
  [ -f "$GATEWAY_SRC/gateway/platforms/weixin.py" ] || die "Current Hermes Weixin adapter not found: $GATEWAY_SRC"
  python3 - "$GATEWAY_SRC" <<'PY'
from __future__ import annotations
import ast, sys
from pathlib import Path
root = Path(sys.argv[1])
wx_path = root / "gateway" / "platforms" / "weixin.py"
run_path = root / "gateway" / "run.py"
missing = []
def parse(path): return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
wx_tree = parse(wx_path)
classes = {n.name: n for n in wx_tree.body if isinstance(n, ast.ClassDef)}
for name in ("ContextTokenStore", "WeixinAdapter"):
    if name not in classes: missing.append(f"class:{name}")
adapter = classes.get("WeixinAdapter")
if adapter:
    methods = {n.name for n in adapter.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for name in ("_process_message", "_split_text", "_send_text_chunk", "send"):
        if name not in methods: missing.append(f"WeixinAdapter.{name}")
imports = {a.name for n in ast.walk(wx_tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
if "MessageDeduplicator" not in imports: missing.append("import:MessageDeduplicator")
if not run_path.is_file(): missing.append("gateway/run.py")
else:
    run_classes = {n.name for n in parse(run_path).body if isinstance(n, ast.ClassDef)}
    if "GatewayRunner" not in run_classes: missing.append("class:GatewayRunner")
if missing: raise SystemExit("Unsupported Hermes API surface: " + ", ".join(missing))
print("HERMES_CURRENT_API_CONTRACT_OK")
PY
}

normalized_tree_hash() {
  python3 - "$1" <<'PY'
import hashlib, os, sys
from pathlib import Path
root = Path(sys.argv[1])
if not root.exists() and not root.is_symlink(): print("MISSING"); raise SystemExit
h = hashlib.sha256()
for item in sorted(root.rglob("*")):
    rel = item.relative_to(root)
    if any(p in {"__pycache__", ".pytest_cache", ".git"} for p in rel.parts): continue
    if item.suffix in {".pyc", ".pyo"}: continue
    h.update(rel.as_posix().encode())
    if item.is_symlink(): h.update(b"L" + os.readlink(item).encode())
    elif item.is_file(): h.update(b"F" + item.read_bytes())
    else: h.update(b"D")
print(h.hexdigest())
PY
}

install_hooks() {
  local src="$SKILL_DIR/hooks/hermes-wechat-enhance" dst="$HOOKS_DIR/hermes-wechat-enhance"
  [ -d "$src" ] || die "Hook source not found: $src"
  mkdir -p "$HOOKS_DIR"
  if [ "$HOOK_MODE" = "symlink" ]; then
    if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then return; fi
    rm -rf "$dst"; ln -s "$src" "$dst"
  else
    if [ -d "$dst" ] && [ "$(normalized_tree_hash "$src")" = "$(normalized_tree_hash "$dst")" ]; then
      log "[SKIP] Hook already current: $dst"; return
    fi
    rm -rf "$dst"; mkdir -p "$dst"; cp -a "$src/." "$dst/"
  fi
  log "[OK] Hook installed: $dst"
}

verify_install() {
  HERMES_HOME="$HERMES_HOME_DIR" HERMES_GATEWAY_SRC="$GATEWAY_SRC" \
  HERMES_WECHAT_ENHANCE_SOURCE_DIR="$SKILL_DIR" \
  python3 "$SKILL_DIR/scripts/verify-self-install.py"
}

main() {
  log "=== Hermes WeChat Enhance current-Hermes installer ==="
  [ -d "$GATEWAY_SRC" ] || die "Hermes source not found: $GATEWAY_SRC"
  install_state snapshot
  INSTALL_STATE_ACTIVE=1
  fault_inject after-state-snapshot
  install_canonical_source_if_needed "$@"
  verify_current_hermes_contract
  log "PATCH_MODE=hook-only"
  log "[OK] Hermes Core left byte-for-byte unchanged"
  install_hooks
  fault_inject after-hook-install
  verify_install
  fault_inject after-verification
  install_state record-installed
  INSTALL_STATE_ACTIVE=0
  log "INSTALL_OK"
}

main "$@"
