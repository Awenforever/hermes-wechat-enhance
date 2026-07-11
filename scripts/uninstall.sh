#!/usr/bin/env bash
set -Eeuo pipefail

HERMES_HOME_DIR="${HERMES_HOME:-/opt/data}"
HOOKS_DIR="${HERMES_HOOKS_DIR:-${HERMES_HOME_DIR}/hooks}"
HOOK_DST="$HOOKS_DIR/hermes-wechat-enhance"

echo "=== Hermes WeChat Enhance Uninstaller ==="
echo "HERMES_HOME=$HERMES_HOME_DIR"
echo "HOOKS_DIR=$HOOKS_DIR"

if [ -e "$HOOK_DST" ] || [ -L "$HOOK_DST" ]; then
  rm -rf "$HOOK_DST"
  echo "[OK] Removed hook: $HOOK_DST"
else
  echo "[SKIP] Hook not installed: $HOOK_DST"
fi

echo "UNINSTALL_OK"
