#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() { printf 'FAIL %s\n' "$*" >&2; exit 1; }

grep -q 'requires_hermes: ">=0.21.3,<0.22"' plugin.yaml || fail "unsupported Hermes range"
grep -q 'version: 3.1.0' plugin.yaml || fail "release version mismatch"
grep -q 'install_v021_bubble_footer_hook' hooks/hermes-wechat-enhance/handler.py || fail "current hook missing"

if grep -RInE 'v0\.18|v018|MessageSendQueue|ReplyBudgetStore|legacy_runtime_compat|current_official_runtime_compat' \
  --exclude='check-consistency.sh' --exclude='verify-self-install.py' \
  plugin.yaml hooks hermes_wechat_enhance scripts/install.sh plugin_cli.py SKILL.md README.md README_CN.md; then
  fail "legacy Hermes runtime contract remains in distributable code or documentation"
fi

python3 -m py_compile plugin_cli.py hooks/hermes-wechat-enhance/handler.py hermes_wechat_enhance/*.py
printf 'CURRENT_HERMES_DISTRIBUTION_CONSISTENCY_OK\n'
