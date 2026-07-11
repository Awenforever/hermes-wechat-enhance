#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
GATEWAY_SRC="${HERMES_GATEWAY_SRC:-/opt/hermes}"
HERMES_HOME_DIR="${HERMES_HOME:-/opt/data}"
HOOKS_DIR="${HERMES_HOOKS_DIR:-${HERMES_HOME_DIR}/hooks}"
HOOK_MODE="${HERMES_WECHAT_ENHANCE_HOOK_MODE:-copy}"

# WECHAT_ENHANCE_SOURCE_INSTALL_CONTRACT_V1
# Fresh Docker installs need the source package under HERMES_HOME because
# the active hook imports hermes_wechat_enhance from:
#   $HERMES_HOME/skills/hermes-wechat-enhance
SOURCE_ROOT="${HERMES_SKILLS_DIR:-${HERMES_HOME_DIR}/skills}"
CANONICAL_SOURCE_DIR="${HERMES_WECHAT_ENHANCE_SOURCE_DIR:-${SOURCE_ROOT}/hermes-wechat-enhance}"
SOURCE_REEXEC_FLAG="${HERMES_WECHAT_ENHANCE_SOURCE_REEXEC:-0}"

log() { printf '%s\n' "$*"; }
die() { printf '[FAIL] %s\n' "$*" >&2; exit 1; }

install_canonical_source_if_needed() {
  local src_real dst_real backup
  mkdir -p "$(dirname "$CANONICAL_SOURCE_DIR")"
  src_real="$(cd "$SKILL_DIR" && pwd -P)"
  if [ -d "$CANONICAL_SOURCE_DIR" ]; then
    dst_real="$(cd "$CANONICAL_SOURCE_DIR" && pwd -P)"
  else
    dst_real=""
  fi

  if [ "$src_real" = "$dst_real" ]; then
    log "[OK] Source already canonical: $CANONICAL_SOURCE_DIR"
    return
  fi

  if [ "$SOURCE_REEXEC_FLAG" = "1" ]; then
    die "Source re-exec requested but SKILL_DIR is still not canonical: $SKILL_DIR"
  fi

  if [ -e "$CANONICAL_SOURCE_DIR" ] || [ -L "$CANONICAL_SOURCE_DIR" ]; then
    backup="${CANONICAL_SOURCE_DIR}.before-source-install-$(date +%Y%m%d-%H%M%S)"
    mv "$CANONICAL_SOURCE_DIR" "$backup"
    log "[OK] Existing source backed up: $backup"
  fi

  mkdir -p "$CANONICAL_SOURCE_DIR"
  (
    cd "$SKILL_DIR"
    tar       --exclude='./__pycache__'       --exclude='./.pytest_cache'       --exclude='./.mypy_cache'       --exclude='./.ruff_cache'       --exclude='./*.pyc'       --exclude='./*.pyo'       --exclude='./.self_install_dev_backups'       --exclude='./.self_install_dev_v3safe3_backups'       -cf - .
  ) | (cd "$CANONICAL_SOURCE_DIR" && tar -xf -)

  find "$CANONICAL_SOURCE_DIR" -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.mypy_cache' -o -name '.ruff_cache' -o -name '.self_install_dev_backups' -o -name '.self_install_dev_v3safe3_backups' \) -prune -exec rm -rf {} + 2>/dev/null || true
  find "$CANONICAL_SOURCE_DIR" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete 2>/dev/null || true
  log "[OK] Source copied: $CANONICAL_SOURCE_DIR"
  log "SOURCE_INSTALL_OK path=$CANONICAL_SOURCE_DIR"

  log "[OK] Re-exec installer from canonical source"
  HERMES_WECHAT_ENHANCE_SOURCE_REEXEC=1 exec bash "$CANONICAL_SOURCE_DIR/scripts/install.sh" "$@"
}

detect_version() {
  cd "$GATEWAY_SRC"
  if git describe --tags 2>/dev/null; then return; fi
  if [ -f VERSION ]; then cat VERSION; return; fi
  python3 - <<'PY' 2>/dev/null || true
try:
    import importlib.metadata as m
    print(m.version("hermes-agent"))
except Exception:
    pass
PY
  echo "unknown"
}

find_patch_dir() {
  local ver="$1"
  local candidates=(
    "$SKILL_DIR/patches/$ver"
    "$SKILL_DIR/patches/v${ver#v}"
  )
  for d in "${candidates[@]}"; do
    if [ -f "$d/series" ]; then
      echo "$d"
      return
    fi
  done
  if ls "$SKILL_DIR/patches/"*.patch >/dev/null 2>&1; then
    echo "$SKILL_DIR/patches"
    return
  fi
  echo ""
}

ensure_git_baseline() {
  cd "$GATEWAY_SRC"
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    git init >/dev/null
    git config user.email "install@hermes-wechat-enhance.local"
    git config user.name "Hermes WeChat Enhance Installer"
    git add -A
    git commit -m "pristine before hermes-wechat-enhance" >/dev/null || true
    log "[OK] Created git baseline"
    return
  fi
  git config user.email "install@hermes-wechat-enhance.local" || true
  git config user.name "Hermes WeChat Enhance Installer" || true
  log "[OK] Git repository available"
}

marker_present() {
  local patch_id="$1"
  case "$patch_id" in
    001)
      grep -q "/continue: drain pending" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null \
        && grep -q "_drain_pending(sender_id)" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null
      ;;
    002)
      grep -q "def _footer_model_name" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null \
        && grep -q "def _is_system_meta" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null
      ;;
    003)
      grep -q "def _non_conversational_metadata" "$GATEWAY_SRC/gateway/run.py" 2>/dev/null \
        && grep -q "is_system" "$GATEWAY_SRC/gateway/run.py" 2>/dev/null
      ;;
    004)
      grep -q "model_name" "$GATEWAY_SRC/gateway/run.py" 2>/dev/null \
        && grep -q "resolved_model" "$GATEWAY_SRC/gateway/run.py" 2>/dev/null
      ;;
    005)
      grep -q "class ReplyBudgetStore" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null \
        && grep -q "class MessageSendQueue" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null \
        && grep -q "async def _drain_pending" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null
      ;;
    006)
      grep -q "HERMES_WECHAT_INTERIM_MODEL_METADATA_V1" "$GATEWAY_SRC/gateway/run.py" 2>/dev/null \
        && grep -q "_current_turn_model_metadata" "$GATEWAY_SRC/gateway/run.py" 2>/dev/null
      ;;
    007)
      grep -q "HERMES_WECHAT_INTERIM_MODEL_METADATA_STRICT_SOURCE_V2" "$GATEWAY_SRC/gateway/run.py" 2>/dev/null \
        && grep -q "wechat interim assistant model metadata source=" "$GATEWAY_SRC/gateway/run.py" 2>/dev/null
      ;;
    008)
      grep -q "HERMES_WECHAT_STREAM_CONSUMER_MODEL_METADATA_V3" "$GATEWAY_SRC/gateway/run.py" 2>/dev/null \
        && grep -q "HERMES_WECHAT_QUEUED_FIRST_RESPONSE_MODEL_METADATA_V3" "$GATEWAY_SRC/gateway/run.py" 2>/dev/null \
        && grep -q "HERMES_WECHAT_BACKGROUND_REVIEW_SYSTEM_METADATA_V3B" "$GATEWAY_SRC/gateway/run.py" 2>/dev/null \
        && grep -q "HERMES_WECHAT_HANDOFF_MODEL_METADATA_V3" "$GATEWAY_SRC/gateway/run.py" 2>/dev/null \
        && grep -q "HERMES_WECHAT_FINAL_MODEL_STRICT_SOURCE_V3" "$GATEWAY_SRC/gateway/run.py" 2>/dev/null
      ;;
    009)
      grep -q "WECHAT_ENHANCE_RELIABLE_DELIVERY_V2" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null         && grep -q "WECHAT_ENHANCE_REPLY_BUDGET_COMMIT_AFTER_ACK_V2" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null         && grep -q "WECHAT_ENHANCE_QUEUE_PEEK_COMMIT_V2" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null         && grep -q "WECHAT_ENHANCE_DELIVERY_ID_DEDUPE_V2" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null
      ;;
    *)
      return 1
      ;;
  esac
}

apply_one_patch() {
  local patch_id="$1"
  local patch_file="$2"
  local name
  name="$(basename "$patch_file")"
  cd "$GATEWAY_SRC"

  if git apply --check "$patch_file" 2>/dev/null; then
    git apply "$patch_file"
    log "[OK] Applied $name"
    return
  fi

  if marker_present "$patch_id"; then
    log "[SKIP] $name already represented by runtime markers"
    return
  fi

  if git apply --reverse --check "$patch_file" 2>/dev/null; then
    log "[SKIP] $name already applied according to reverse check"
    return
  fi

  die "Cannot apply or verify $name"
}

apply_patches() {
  local patch_dir="$1"
  [ -n "$patch_dir" ] || die "No patch directory"

  cd "$GATEWAY_SRC"

  if [ -f "$patch_dir/series" ]; then
    while read -r patch_id; do
      [ -z "$patch_id" ] && continue
      [ "${patch_id#\#}" != "$patch_id" ] && continue
      local matched=()
      for f in "$patch_dir"/${patch_id}-*.patch; do
        [ -f "$f" ] && matched+=("$f")
      done
      [ ${#matched[@]} -gt 0 ] || die "Patch $patch_id not found in $patch_dir"
      for f in "${matched[@]}"; do
        apply_one_patch "$patch_id" "$f"
      done
    done < "$patch_dir/series"
  else
    local ordered=(002 003 004 005 001)
    for patch_id in "${ordered[@]}"; do
      local matched=()
      for f in "$patch_dir"/${patch_id}-*.patch; do
        [ -f "$f" ] && matched+=("$f")
      done
      if [ ${#matched[@]} -eq 0 ]; then
        log "[WARN] No patch found for $patch_id"
        continue
      fi
      for f in "${matched[@]}"; do
        apply_one_patch "$patch_id" "$f"
      done
    done
  fi

  if [ -n "$(git status --porcelain 2>/dev/null || true)" ]; then
    git add -A
    git commit -m "hermes-wechat-enhance installed $(date -Iseconds)" >/dev/null || true
    log "[OK] Committed installer changes"
  else
    log "[OK] No gateway source changes needed"
  fi
}

install_hooks() {
  local hook_src="$SKILL_DIR/hooks/hermes-wechat-enhance"
  local hook_dst="$HOOKS_DIR/hermes-wechat-enhance"

  [ -d "$hook_src" ] || die "Hook source not found: $hook_src"
  mkdir -p "$HOOKS_DIR"

  if [ "$HOOK_MODE" = "symlink" ]; then
    ln -sfn "$hook_src" "$hook_dst"
    log "[OK] Hook symlink installed: $hook_dst -> $hook_src"
  else
    if [ -e "$hook_dst" ] || [ -L "$hook_dst" ]; then
      local backup="${hook_dst}.before-install-$(date +%Y%m%d-%H%M%S)"
      mv "$hook_dst" "$backup"
      log "[OK] Existing hook backed up: $backup"
    fi
    mkdir -p "$hook_dst"
    cp -a "$hook_src/." "$hook_dst/"
    log "[OK] Hook copied: $hook_dst"
  fi
}

verify_install() {
  HERMES_HOME="$HERMES_HOME_DIR" HOME="${HOME:-/opt/data/.hermes-home}" python3 "$SKILL_DIR/scripts/verify-self-install.py"
}

main() {
  log "=== Hermes WeChat Enhance Installer ==="
  log "SKILL_DIR=$SKILL_DIR"
  log "GATEWAY_SRC=$GATEWAY_SRC"
  log "HERMES_HOME=$HERMES_HOME_DIR"
  log "HOOKS_DIR=$HOOKS_DIR"
  log "HOOK_MODE=$HOOK_MODE"

  install_canonical_source_if_needed "$@"

  [ -d "$GATEWAY_SRC" ] || die "Gateway source not found: $GATEWAY_SRC"

  local version
  version="$(detect_version | tail -1)"
  log "VERSION=$version"

  local patch_dir
  patch_dir="$(find_patch_dir "$version")"
  [ -n "$patch_dir" ] || die "No matching patch set found"
  log "PATCH_DIR=$patch_dir"

  ensure_git_baseline
  apply_patches "$patch_dir"
  install_hooks
  verify_install

  log "INSTALL_OK"
}

main "$@"
