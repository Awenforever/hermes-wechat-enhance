#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import importlib.util
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


async def main() -> None:
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="wechat-startup-target-") as raw:
        home = Path(raw)
        db = sqlite3.connect(home / "state.db")
        db.execute(
            "CREATE TABLE sessions (source TEXT, user_id TEXT, started_at REAL, ended_at REAL)"
        )
        db.execute("INSERT INTO sessions VALUES ('weixin', 'human-peer', 1, 2)")
        db.commit()
        db.close()

        os.environ["HERMES_HOME"] = str(home)
        os.environ["HERMES_WECHAT_ENHANCE_SOURCE_DIR"] = str(root)
        os.environ["HERMES_WEIXIN_STARTUP_READY_NOTIFY"] = "1"
        os.environ.pop("HERMES_PROACTIVE_WEIXIN_CHAT_ID", None)
        sys.path.insert(0, str(root))

        path = root / "hooks" / "hermes-wechat-enhance" / "handler.py"
        spec = importlib.util.spec_from_file_location("startup_ready_handler", path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        calls = []

        class Adapter:
            _account_id = "bot-account"

            async def send(self, chat_id, content, metadata=None):
                calls.append((chat_id, content, metadata or {}))
                return SimpleNamespace(success=True, message_id="ready")

        await module._send_startup_ready({"adapters": {"weixin": Adapter()}})
        assert len(calls) == 1
        assert calls[0][0] == "human-peer"
        assert calls[0][2]["_delivery_id"] == "hermes-wechat-enhance-startup-ready"
        print("WECHAT_STARTUP_TARGET_INHERIT_TEST=PASS")


if __name__ == "__main__":
    asyncio.run(main())
