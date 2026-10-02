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
        os.environ.pop("HERMES_WEIXIN_STARTUP_READY_NOTIFY", None)
        os.environ.pop("HERMES_PROACTIVE_WEIXIN_CHAT_ID", None)
        sys.path.insert(0, str(root))

        path = root / "hooks" / "hermes-wechat-enhance" / "handler.py"
        spec = importlib.util.spec_from_file_location("startup_ready_handler", path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        import hermes_wechat_enhance.settings as settings

        calls = []

        class Adapter:
            _account_id = "bot-account"

            async def send(self, chat_id, content, metadata=None):
                calls.append((chat_id, content, metadata or {}))
                return SimpleNamespace(success=True, message_id="ready")

        await module._send_startup_ready({"adapters": {"weixin": Adapter()}})
        assert len(calls) == 1
        assert calls[0][0] == "human-peer"
        assert calls[0][1] == "♻️ Gateway online — Hermes is back and ready."
        assert calls[0][2]["_delivery_id"] == "hermes-wechat-enhance-startup-ready"

        # Hermes plugin settings are a real runtime input, not merely a
        # manifest declaration. Explicit disable must win over the default.
        settings._load_config = lambda: {
            "plugins": {"entries": {"hermes-wechat-enhance": {"settings": {
                "startup_notification": False,
            }}}}
        }
        await module._send_startup_ready({"adapters": {"weixin": Adapter()}})
        assert len(calls) == 1

        settings._load_config = lambda: {
            "plugins": {"entries": {"hermes-wechat-enhance": {"settings": {
                "startup_notification": True,
                "startup_message": "custom ready",
            }}}}
        }
        await module._send_startup_ready({"adapters": {"weixin": Adapter()}})
        assert calls[-1][1] == "custom ready"

        # Consume both the corrected profile-relative path and the legacy
        # 2.1.7 path so upgrades cannot leave a stale one-shot suppression.
        for relative in (
            Path("wechat-enhance/suppress-startup-ready-once"),
            Path(".hermes/wechat-enhance/suppress-startup-ready-once"),
        ):
            sentinel = home / relative
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.touch()
            before = len(calls)
            await module._send_startup_ready({"adapters": {"weixin": Adapter()}})
            assert len(calls) == before
            assert not sentinel.exists()

        # A root-owned or otherwise undeletable sentinel suppresses exactly
        # once. Its receipt prevents permanent suppression on every restart.
        sentinel = home / "wechat-enhance" / "suppress-startup-ready-once"
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.touch()
        original_unlink = Path.unlink

        def guarded_unlink(path, *args, **kwargs):
            if path == sentinel:
                raise PermissionError("fixture-owned sentinel")
            return original_unlink(path, *args, **kwargs)

        Path.unlink = guarded_unlink
        try:
            before = len(calls)
            await module._send_startup_ready({"adapters": {"weixin": Adapter()}})
            assert len(calls) == before
            await module._send_startup_ready({"adapters": {"weixin": Adapter()}})
            assert len(calls) == before + 1
        finally:
            Path.unlink = original_unlink
            sentinel.unlink(missing_ok=True)
        print("WECHAT_STARTUP_TARGET_INHERIT_TEST=PASS")


if __name__ == "__main__":
    asyncio.run(main())
