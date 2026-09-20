#!/usr/bin/env python3
"""Offline post-install verification for Hermes v0.21.3."""
from __future__ import annotations

import importlib.util
import asyncio
import os
import py_compile
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()
GATEWAY = Path(os.environ.get("HERMES_GATEWAY_SRC", "/opt/hermes")).expanduser()
HOOK = Path(os.environ.get("HERMES_HOOKS_DIR", str(HERMES_HOME / "hooks"))) / "hermes-wechat-enhance"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit("FAIL " + message)


def main() -> int:
    weixin = GATEWAY / "gateway" / "platforms" / "weixin.py"
    run_turn = GATEWAY / "gateway" / "run_turn.py"
    require(weixin.is_file(), f"missing {weixin}")
    require(run_turn.is_file(), f"missing {run_turn}")
    weixin_text = weixin.read_text(encoding="utf-8")
    run_turn_text = run_turn.read_text(encoding="utf-8")
    for marker in (
        "class ContextTokenStore", "async def _send_text_chunk",
        "async def _process_message", "async def send_document",
    ):
        require(marker in weixin_text, f"v0.21 Weixin API missing {marker}")
    require("def _resolve_session_agent_runtime" in run_turn_text, "model router API missing")

    hook_yaml = HOOK / "HOOK.yaml"
    handler = HOOK / "handler.py"
    require(hook_yaml.is_file() and handler.is_file(), "installed hook incomplete")
    require("gateway:startup" in hook_yaml.read_text(encoding="utf-8"), "startup hook missing")
    for path in (
        handler, ROOT / "hermes_wechat_enhance" / "v021_bubble_footer.py",
        ROOT / "plugin_cli.py", ROOT / "scripts" / "queue-admin.py",
    ):
        py_compile.compile(str(path), doraise=True)

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("wechat_v021_installed_hook", handler)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    class FakeResult:
        success = True
        error = None

    class FakeAdapter:
        def __init__(self) -> None:
            self.sent = []

        async def send(self, chat_id, content, metadata=None):
            self.sent.append((chat_id, content, dict(metadata or {})))
            return FakeResult()

    fake = FakeAdapter()
    old_chat = os.environ.get("HERMES_PROACTIVE_WEIXIN_CHAT_ID")
    old_ready = os.environ.pop("HERMES_WEIXIN_STARTUP_READY_NOTIFY", None)
    os.environ["HERMES_PROACTIVE_WEIXIN_CHAT_ID"] = "verify-chat"
    try:
        asyncio.run(module._send_startup_ready({"adapters": {"weixin": fake}}))
    finally:
        if old_chat is None:
            os.environ.pop("HERMES_PROACTIVE_WEIXIN_CHAT_ID", None)
        else:
            os.environ["HERMES_PROACTIVE_WEIXIN_CHAT_ID"] = old_chat
        if old_ready is not None:
            os.environ["HERMES_WEIXIN_STARTUP_READY_NOTIFY"] = old_ready
    require(len(fake.sent) == 1, "default startup-ready notification did not send")
    require(fake.sent[0][1] == "♻️ Gateway online — Hermes is back and ready.", "ready text mismatch")
    require(fake.sent[0][2].get("model_name") == "hermes", "ready model tag mismatch")

    source = (ROOT / "hermes_wechat_enhance" / "v021_bubble_footer.py").read_text(encoding="utf-8")
    for marker in (
        "HERMES_WECHAT_V021_RELIABLE_DELIVERY_V2", "commit_external_ack",
        "_hermes_wechat_drain_pending_v2", 'text != "/continue"',
        "patch_gateway_runner", "runtime.sqlite3",
    ):
        require(marker in source, f"runtime contract missing {marker}")

    env = dict(os.environ)
    env["HERMES_HOME"] = str(HERMES_HOME / ".verify-v021")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "test-v021-bubble-footer.py")],
        env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=60, check=False,
    )
    require(result.returncode == 0, "v0.21 delivery contract failed: " + result.stdout[-2000:])
    require("V021_BUBBLE_FOOTER_TEST_OK" in result.stdout, "v0.21 test marker missing")
    print("V021_INSTALL_VERIFY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
