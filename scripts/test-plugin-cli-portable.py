#!/usr/bin/env python3
"""Cross-platform hook install and queue-management contract."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
gateway = os.environ.get("HERMES_GATEWAY_SRC", "").strip()
if gateway:
    sys.path.insert(0, gateway)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="wechat-cli-portable-") as directory:
        os.environ["HERMES_HOME"] = directory
        import plugin_cli
        from hermes_wechat_enhance.v021_bubble_footer import DurableRuntime

        assert plugin_cli._install_hook() == 0
        hook = Path(directory) / "hooks" / "hermes-wechat-enhance" / "HOOK.yaml"
        assert hook.is_file()

        path = plugin_cli._runtime_db_path()
        runtime = DurableRuntime(path)
        runtime.refresh_context("account", "chat", "token")
        assert runtime.enqueue(
            account_id="account", chat_id="chat", content="private body",
            reply_to=None, metadata={}, model_name="qwen3.6-chat", context_token="token",
            client_id="client", delivery_id="delivery", chunk_index=0,
        )
        status = plugin_cli._runtime_status(path)
        assert status["pending"] == 1 and status["chats"] == 1
        assert plugin_cli._runtime_queue_list(path, 10) == 0
        assert plugin_cli._runtime_queue_clear(path, True) == 0
        assert plugin_cli._runtime_status(path)["pending"] == 0
        backups = list((path.parent / "queue-backups").glob("runtime.*.sqlite3"))
        assert len(backups) == 1
    print("WECHAT_PLUGIN_CLI_PORTABLE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
