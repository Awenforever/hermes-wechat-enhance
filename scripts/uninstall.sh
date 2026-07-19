#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
GATEWAY_SRC="${HERMES_GATEWAY_SRC:-/opt/hermes}"
HERMES_HOME_DIR="${HERMES_HOME:-/opt/data}"
HOOKS_DIR="${HERMES_HOOKS_DIR:-${HERMES_HOME_DIR}/hooks}"
HOOK_DST="$HOOKS_DIR/hermes-wechat-enhance"
SOURCE_ROOT="${HERMES_SKILLS_DIR:-${HERMES_HOME_DIR}/skills}"
CANONICAL_SOURCE_DIR="${HERMES_WECHAT_ENHANCE_SOURCE_DIR:-${SOURCE_ROOT}/hermes-wechat-enhance}"
STATE_MANAGER="$SKILL_DIR/scripts/manage-install-state.py"

echo "=== Hermes WeChat Enhance Uninstaller ==="
echo "GATEWAY_SRC=$GATEWAY_SRC"
echo "HERMES_HOME=$HERMES_HOME_DIR"

python3 "$STATE_MANAGER" restore \
  --gateway "$GATEWAY_SRC" \
  --home "$HERMES_HOME_DIR" \
  --hook "$HOOK_DST" \
  --source "$CANONICAL_SOURCE_DIR"

echo "[OK] Canonical source restored or removed by install-state manager."

echo "User/runtime message data preserved."
echo "UNINSTALL_OK"
