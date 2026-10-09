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

        # Hook reload/re-entry in the same gateway process must not create a
        # second ready bubble once delivery (or durable FIFO acceptance) has
        # been acknowledged.
        await module._send_startup_ready({"adapters": {"weixin": Adapter()}})
        assert len(calls) == 1

        # Hermes plugin settings are a real runtime input, not merely a
        # manifest declaration. Explicit disable must win over the default.
        settings._load_config = lambda: {
            "plugins": {"entries": {"hermes-wechat-enhance": {"settings": {
                "startup_notification": False,
            }}}}
        }
        await module._send_startup_ready({"adapters": {"weixin": Adapter()}})
        assert len(calls) == 1

        receipt = home / "plugin-data" / "hermes-wechat-enhance" / "startup-ready-receipt.json"
        receipt.unlink()

        settings._load_config = lambda: {
            "plugins": {"entries": {"hermes-wechat-enhance": {"settings": {
                "startup_notification": True,
                "startup_message": "custom ready",
            }}}}
        }
        await module._send_startup_ready({"adapters": {"weixin": Adapter()}})
        assert calls[-1][1] == "custom ready"

        # Historical deployment sentinels must never suppress a ready notice.
        for relative in (
            Path("wechat-enhance/suppress-startup-ready-once"),
            Path(".hermes/wechat-enhance/suppress-startup-ready-once"),
        ):
            sentinel = home / relative
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.touch()
            receipt.unlink(missing_ok=True)
            before = len(calls)
            await module._send_startup_ready({"adapters": {"weixin": Adapter()}})
            assert len(calls) == before + 1

        # Core's one shared option controls both shutdown and startup.  The
        # plugin must suppress only Core's startup calls at runtime, restore
        # the option immediately, and never silence future shutdown notices.
        from hermes_wechat_enhance.lifecycle import patch_core_weixin_startup_notifications

        weixin_cfg = SimpleNamespace(gateway_restart_notification=True)

        class Runner:
            config = SimpleNamespace(platforms={"weixin": weixin_cfg})

            def __init__(self):
                self.core_startup_sends = 0

            async def _send_restart_notification(self):
                if self.config.platforms["weixin"].gateway_restart_notification:
                    self.core_startup_sends += 1

            async def _send_home_channel_startup_notifications(self, **_kwargs):
                if self.config.platforms["weixin"].gateway_restart_notification:
                    self.core_startup_sends += 1
                return set()

        runner = Runner()
        assert patch_core_weixin_startup_notifications(runner) is True
        assert patch_core_weixin_startup_notifications(runner) is False
        await runner._send_restart_notification()
        await runner._send_home_channel_startup_notifications(skip_targets=None)
        assert runner.core_startup_sends == 0
        assert weixin_cfg.gateway_restart_notification is True
        print("WECHAT_STARTUP_TARGET_INHERIT_TEST=PASS")


if __name__ == "__main__":
    asyncio.run(main())
