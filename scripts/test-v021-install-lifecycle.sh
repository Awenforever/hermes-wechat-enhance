#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GATEWAY_SRC="${HERMES_GATEWAY_SRC:-/opt/hermes}"
TEST_HOME="$(mktemp -d /tmp/hermes-wechat-v021-install.XXXXXX)"
trap 'rm -rf "$TEST_HOME"' EXIT

export HERMES_HOME="$TEST_HOME/profile"
export HERMES_GATEWAY_SRC="$GATEWAY_SRC"
export HOME="$TEST_HOME/home"
mkdir -p "$HERMES_HOME" "$HOME"

hash_core() {
  sha256sum \
    "$GATEWAY_SRC/gateway/platforms/weixin.py" \
    "$GATEWAY_SRC/gateway/platforms/base.py" \
    "$GATEWAY_SRC/gateway/run.py"
}

hash_core >"$TEST_HOME/core.before"
bash "$ROOT/scripts/install.sh"
hash_core >"$TEST_HOME/core.after-first"
cmp "$TEST_HOME/core.before" "$TEST_HOME/core.after-first"
test -f "$HERMES_HOME/hooks/hermes-wechat-enhance/HOOK.yaml"
test -f "$HERMES_HOME/skills/hermes-wechat-enhance/hermes_wechat_enhance/v021_bubble_footer.py"

bash "$HERMES_HOME/skills/hermes-wechat-enhance/scripts/install.sh"
hash_core >"$TEST_HOME/core.after-second"
cmp "$TEST_HOME/core.before" "$TEST_HOME/core.after-second"

python3 "$HERMES_HOME/skills/hermes-wechat-enhance/scripts/manage-install-state.py" status \
  --gateway "$GATEWAY_SRC" --home "$HERMES_HOME" \
  --hook "$HERMES_HOME/hooks/hermes-wechat-enhance" \
  --source "$HERMES_HOME/skills/hermes-wechat-enhance"

bash "$HERMES_HOME/skills/hermes-wechat-enhance/scripts/uninstall.sh"
hash_core >"$TEST_HOME/core.after-uninstall"
cmp "$TEST_HOME/core.before" "$TEST_HOME/core.after-uninstall"
test ! -e "$HERMES_HOME/hooks/hermes-wechat-enhance"
test ! -e "$HERMES_HOME/skills/hermes-wechat-enhance"

echo "V021_INSTALL_LIFECYCLE_OK"
