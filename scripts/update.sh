#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Hermes WeChat Enhance Updater ==="
echo "Update delegates to the idempotent transactional installer."
exec bash "$SCRIPT_DIR/install.sh" "$@"
