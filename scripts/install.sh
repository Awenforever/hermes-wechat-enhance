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
STATE_MANAGER="$SKILL_DIR/scripts/manage-install-state.py"
INSTALL_STATE_ACTIVE=0
# HERMES_WECHAT_PATCH_VARIANT_DISPATCH_V1
# WECHAT_ENHANCE_HOOK_IDEMPOTENT_NO_BACKUP_RESIDUE_V1
# HERMES_WECHAT_V018_SOURCE_PROFILE_DISPATCH_V1
# HERMES_WECHAT_VERSION_FROM_VERIFIED_SOURCE_PROFILE_V1
# HERMES_WECHAT_V018_VERSION_FAMILY_NORMALIZATION_V1
# HERMES_WECHAT_TRANSACTIONAL_SOURCE_STATE_V1
# HERMES_WECHAT_FAULT_INJECTION_TEST_V1
# HERMES_WECHAT_GIT_METADATA_PRESERVATION_V1
# HERMES_WECHAT_EXACT_FILE_BACKUP_RESTORE_V1
OFFICIAL_V018_WEIXIN_SHA256="2fae85eb726afaa209ac1ba87869eb9a249ad22dc8727732a19e416953065633"
LEGACY_V018_WEIXIN_SHA256="926b74e3476a78317560fadc5367eb37a061edba72b1fb225cf7e1de80cc5920"

log() { printf '%s\n' "$*"; }
die() { printf '[FAIL] %s\n' "$*" >&2; exit 1; }

install_state() {
  python3 "$STATE_MANAGER" "$@" \
    --gateway "$GATEWAY_SRC" \
    --home "$HERMES_HOME_DIR" \
    --hook "$HOOKS_DIR/hermes-wechat-enhance" \
    --source "$CANONICAL_SOURCE_DIR"
}

install_exit_guard() {
  local rc=$?
  trap - EXIT
  if [ "$INSTALL_STATE_ACTIVE" = "1" ] && [ "$rc" -ne 0 ]; then
    log "[ROLLBACK] Restoring pre-install gateway and hook state"
    install_state rollback || true
  fi
  exit "$rc"
}
trap install_exit_guard EXIT

fault_inject() {
  local stage="$1"
  if [ "${HERMES_WECHAT_ENHANCE_FAULT_INJECT_STAGE:-}" = "$stage" ]; then
    log "[FAULT-INJECT] stage=$stage"
    die "Synthetic transactional fault at $stage"
  fi
}

install_canonical_source_if_needed() {
  local src_real dst_real
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

  # Transaction snapshot is the sole rollback source.
  rm -rf "$CANONICAL_SOURCE_DIR"
  mkdir -p "$CANONICAL_SOURCE_DIR"
  (
    cd "$SKILL_DIR"
    tar       --exclude='./__pycache__'       --exclude='./.pytest_cache'       --exclude='./.mypy_cache'       --exclude='./.ruff_cache'       --exclude='./*.pyc'       --exclude='./*.pyo'       --exclude='./.self_install_dev_backups'       --exclude='./.self_install_dev_v3safe3_backups'       -cf - .
  ) | (cd "$CANONICAL_SOURCE_DIR" && tar -xf -)

  find "$CANONICAL_SOURCE_DIR" -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.mypy_cache' -o -name '.ruff_cache' -o -name '.self_install_dev_backups' -o -name '.self_install_dev_v3safe3_backups' \) -prune -exec rm -rf {} + 2>/dev/null || true
  find "$CANONICAL_SOURCE_DIR" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete 2>/dev/null || true
  log "[OK] Source copied: $CANONICAL_SOURCE_DIR"
  log "SOURCE_INSTALL_OK path=$CANONICAL_SOURCE_DIR"
  fault_inject after-source-install

  log "[OK] Re-exec installer from canonical source"
  HERMES_WECHAT_ENHANCE_SOURCE_REEXEC=1 exec bash "$CANONICAL_SOURCE_DIR/scripts/install.sh" "$@"
}

detect_version() {
  local source_profile="${1:-}"
  local explicit="${HERMES_WECHAT_ENHANCE_HERMES_VERSION:-}"
  local detected=""

  if [ -n "$explicit" ]; then
    echo "$explicit"
    return
  fi

  cd "$GATEWAY_SRC"

  detected="$(git describe --tags 2>/dev/null || true)"
  if [ -n "$detected" ]; then
    echo "$detected"
    return
  fi

  if [ -s VERSION ]; then
    detected="$(head -n 1 VERSION | tr -d '\r')"
    if [ -n "$detected" ]; then
      echo "$detected"
      return
    fi
  fi

  detected="$(
    python3 - <<'PY' 2>/dev/null || true
try:
    import importlib.metadata as metadata
    value = metadata.version("hermes-agent").strip()
    if value:
        print(value)
except Exception:
    pass
PY
  )"
  if [ -n "$detected" ]; then
    case "$detected" in
      v*) echo "$detected" ;;
      *)  echo "v$detected" ;;
    esac
    return
  fi

  # HERMES_WECHAT_VERSION_FROM_VERIFIED_SOURCE_PROFILE_V1
  case "$source_profile" in
    pristine-v018|legacy-v018|hardened-v018)
      echo "v2026.7.1-inferred-$source_profile"
      return
      ;;
  esac

  echo "unknown"
}


normalize_version_family() {
  local version="$1"

  # HERMES_WECHAT_V018_VERSION_FAMILY_NORMALIZATION_V1
  # Hermes v0.18.0 is released under the calendar tag v2026.7.1. Runtime
  # package metadata may legitimately expose either identifier.
  case "$version" in
    v2026.7.1*|2026.7.1*|v0.18|v0.18.0|0.18|0.18.0)
      echo "v2026.7.1"
      ;;
    *)
      echo "unsupported"
      ;;
  esac
}


is_supported_version() {
  local version_family="$1"
  [ "$version_family" = "v2026.7.1" ]
}


detect_source_profile() {
  local weixin="$GATEWAY_SRC/gateway/platforms/weixin.py"
  [ -f "$weixin" ] || die "Missing Weixin source: $weixin"

  local digest
  digest="$(sha256sum "$weixin" | awk '{print $1}')"

  if [ "$digest" = "$OFFICIAL_V018_WEIXIN_SHA256" ]; then
    echo "pristine-v018"
    return
  fi

  if [ "$digest" = "$LEGACY_V018_WEIXIN_SHA256" ]; then
    echo "legacy-v018"
    return
  fi

  if grep -q "HERMES_WECHAT_V018_SOURCE_PROFILE_DISPATCH_V1" "$weixin" \
     && grep -q "HERMES_WECHAT_V018_CONSOLIDATED_PATCH_V1" "$weixin" \
     && grep -q "HERMES_WECHAT_SLASH_COMMAND_CONTENT_DEDUP_EXEMPTION_V1" "$weixin"
  then
    echo "hardened-v018"
    return
  fi

  die "Unsupported v0.18 Weixin source profile sha256=$digest"
}

series_for_profile() {
  local patch_dir="$1"
  local profile="$2"
  local series="$patch_dir/series.$profile"
  [ -f "$series" ] || die "Missing patch series for source profile: $series"
  echo "$series"
}

patch_matches_version() {
  local version_family="$1"
  local patch_file="$2"
  local name
  name="$(basename "$patch_file")"

  case "$version_family" in
    v2026.7.1)
      # Hermes v0.18 uses standard patches. Historical .v017.patch variants
      # are retained as evidence and must never be selected.
      [ "${name%.v017.patch}" = "$name" ]
      ;;
    *)
      return 1
      ;;
  esac
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

  # Existing images may intentionally have runtime files that differ from
  # their embedded Git HEAD. Do not alter HEAD, index, config or repository
  # structure. git apply can operate without creating commits.
  if git rev-parse --git-dir >/dev/null 2>&1; then
    log "[OK] Existing Git metadata preserved; installer will not commit"
  else
    log "[OK] Git metadata absent; using standalone git apply mode"
  fi
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
    010)
      grep -q "HERMES_WECHAT_SLASH_COMMAND_CONTENT_DEDUP_EXEMPTION_V1" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null \
        && grep -q "HERMES_WECHAT_CONTEXT_TOKEN_REFRESH_BEFORE_CONTENT_DEDUP_V1" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null \
        && grep -q "HERMES_WECHAT_CONTEXT_DELIVERY_SERIALIZATION_V1" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null \
        && grep -q "HERMES_WECHAT_CONTEXT_TOKEN_GENERATION_FENCE_V1" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null \
        && grep -q "HERMES_WECHAT_CONTEXT_BUDGET_RECONCILIATION_V1" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null \
        && grep -q "HERMES_WECHAT_MEDIA_CONTEXT_BUDGET_V1" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null
      ;;
    011)
      grep -q "HERMES_WECHAT_V018_CONSOLIDATED_PATCH_V1" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null \
        && grep -q "HERMES_WECHAT_SLASH_COMMAND_CONTENT_DEDUP_EXEMPTION_V1" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null \
        && grep -q "HERMES_WECHAT_CONTEXT_TOKEN_REFRESH_BEFORE_CONTENT_DEDUP_V1" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null \
        && grep -q "HERMES_WECHAT_CONTEXT_DELIVERY_SERIALIZATION_V1" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null \
        && grep -q "HERMES_WECHAT_CONTEXT_TOKEN_GENERATION_FENCE_V1" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null \
        && grep -q "HERMES_WECHAT_CONTEXT_BUDGET_RECONCILIATION_V1" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null \
        && grep -q "HERMES_WECHAT_MEDIA_CONTEXT_BUDGET_V1" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null \
        && grep -q "HERMES_WECHAT_ORDINARY_REPLY_APPEND_THEN_DRAIN_V1" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null \
        && grep -q "WECHAT_ENHANCE_RELIABLE_DELIVERY_V2" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null
      ;;
    012)
      grep -q "HERMES_WECHAT_V018_SOURCE_PROFILE_DISPATCH_V1" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null         && grep -q "HERMES_WECHAT_V018_CONSOLIDATED_PATCH_V1" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null         && grep -q "HERMES_WECHAT_SLASH_COMMAND_CONTENT_DEDUP_EXEMPTION_V1" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null         && grep -q "HERMES_WECHAT_ORDINARY_REPLY_APPEND_THEN_DRAIN_V1" "$GATEWAY_SRC/gateway/platforms/weixin.py" 2>/dev/null
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
  local version_family="$2"
  local profile="$3"
  local series_file
  [ -n "$patch_dir" ] || die "No patch directory"

  series_file="$(series_for_profile "$patch_dir" "$profile")"
  log "SOURCE_PROFILE=$profile"
  log "SERIES_FILE=$series_file"

  cd "$GATEWAY_SRC"

  while read -r patch_id; do
    [ -z "$patch_id" ] && continue
    [ "${patch_id#\#}" != "$patch_id" ] && continue

    local matched=()
    for patch_file in "$patch_dir"/${patch_id}-*.patch; do
      [ -f "$patch_file" ] || continue
      patch_matches_version "$version_family" "$patch_file" || continue
      matched+=("$patch_file")
    done

    [ ${#matched[@]} -eq 1 ] || \
      die "Patch $patch_id selected ${#matched[@]} variants for $version_family"

    log "[SELECT] $patch_id -> $(basename "${matched[0]}")"
    apply_one_patch "$patch_id" "${matched[0]}"
  done < "$series_file"

  # The transaction manager owns rollback through exact byte snapshots.
  # No Git commit, index update or config write is performed.
  log "[OK] Gateway patches applied without Git metadata mutation"
}

normalized_tree_hash() {
  local root="$1"
  python3 - "$root" <<'PY'
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
if not root.exists() and not root.is_symlink():
    print("MISSING")
    raise SystemExit(0)

ignored_parts = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
ignored_suffixes = {
    ".pyc",
    ".pyo",
}

digest = hashlib.sha256()
if root.is_symlink():
    digest.update(b"L")
    digest.update(os.readlink(root).encode())
elif root.is_file():
    digest.update(b"F")
    digest.update(root.read_bytes())
else:
    for item in sorted(root.rglob("*")):
        relative = item.relative_to(root)
        if any(part in ignored_parts for part in relative.parts):
            continue
        if relative.suffix.lower() in ignored_suffixes:
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
print(digest.hexdigest())
PY
}

install_hooks() {
  local hook_src="$SKILL_DIR/hooks/hermes-wechat-enhance"
  local hook_dst="$HOOKS_DIR/hermes-wechat-enhance"

  [ -d "$hook_src" ] || die "Hook source not found: $hook_src"
  mkdir -p "$HOOKS_DIR"

  if [ "$HOOK_MODE" = "symlink" ]; then
    if [ -L "$hook_dst" ] && [ "$(readlink "$hook_dst")" = "$hook_src" ]; then
      log "[SKIP] Hook symlink already current: $hook_dst"
      return
    fi
    rm -rf "$hook_dst"
    ln -s "$hook_src" "$hook_dst"
    log "[OK] Hook symlink installed: $hook_dst -> $hook_src"
    return
  fi

  if [ -d "$hook_dst" ]; then
    local source_hash
    local destination_hash
    source_hash="$(normalized_tree_hash "$hook_src")"
    destination_hash="$(normalized_tree_hash "$hook_dst")"
    if [ "$source_hash" = "$destination_hash" ]; then
      log "[SKIP] Hook already current (runtime caches ignored): $hook_dst"
      return
    fi
  fi

  # The install-state snapshot is the sole rollback source. Do not create
  # untracked timestamped sibling backups.
  rm -rf "$hook_dst"
  mkdir -p "$hook_dst"
  cp -a "$hook_src/." "$hook_dst/"
  log "[OK] Hook copied/refreshed without backup residue: $hook_dst"
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

  [ -d "$GATEWAY_SRC" ] || die "Gateway source not found: $GATEWAY_SRC"

  install_state snapshot
  INSTALL_STATE_ACTIVE=1
  fault_inject after-state-snapshot

  install_canonical_source_if_needed "$@"

  local version
  local version_family
  local patch_dir
  local source_profile

  source_profile="$(detect_source_profile)"
  version="$(detect_version "$source_profile" | tail -1)"
  version_family="$(normalize_version_family "$version")"

  log "SOURCE_PROFILE=$source_profile"
  log "VERSION=$version"
  log "VERSION_FAMILY=$version_family"
  case "$version" in
    *-inferred-*) log "VERSION_SOURCE=verified-source-profile" ;;
    *)            log "VERSION_SOURCE=external-metadata" ;;
  esac

  is_supported_version "$version_family" ||     die "Unsupported Hermes version: $version; normalized family=$version_family; accepted family=v2026.7.1"

  patch_dir="$(find_patch_dir "$version_family")"
  [ -n "$patch_dir" ] || die "No matching patch set found"
  log "PATCH_DIR=$patch_dir"

  ensure_git_baseline

  apply_patches "$patch_dir" "$version_family" "$source_profile"
  fault_inject after-gateway-patches

  install_hooks
  fault_inject after-hook-install

  verify_install
  fault_inject after-verification

  install_state record-installed

  INSTALL_STATE_ACTIVE=0
  log "INSTALL_OK"
}

main "$@"
