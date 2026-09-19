#!/usr/bin/env python3
"""Exercise the footer through Hermes v0.21's real WeixinAdapter.send path."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import MethodType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        os.environ["HERMES_HOME"] = td
        from gateway.config import PlatformConfig
        from gateway.platforms.weixin import WeixinAdapter
        from hermes_wechat_enhance.v021_bubble_footer import patch_adapter, register_turn_model

        adapter = WeixinAdapter(
            PlatformConfig(
                enabled=True,
                token="test-token",
                extra={"account_id": "test-account", "send_chunk_delay_seconds": 0},
            )
        )
        adapter._send_session = object()
        sent = []

        async def fake_transport(_self, *, chat_id, chunk, context_token, client_id):
            sent.append((chat_id, chunk, context_token, client_id))

        adapter._send_text_chunk = MethodType(fake_transport, adapter)
        await adapter._token_store.set("test-account", "peer", "context-a")
        assert patch_adapter(adapter)
        register_turn_model({"platform": "weixin", "chat_id": "peer", "model": "qwen3.6-chat"})

        result = await adapter.send("peer", "z" * 3900)
        assert result.success
        assert len(sent) >= 2
        for index, (_, text, token, _) in enumerate(sent, 1):
            assert text.endswith(f"`{index}` `qwen3.6-chat`")
            assert len(text) <= adapter.MAX_MESSAGE_LENGTH
            assert token == "context-a"

        state = Path(td) / "plugin-data" / "hermes-wechat-enhance" / "bubble-counters.json"
        raw = state.read_text(encoding="utf-8")
        assert "context-a" not in raw and "test-account" not in raw and "peer" not in raw
        print("V021_REAL_WEIXIN_ADAPTER_TEST_OK")


if __name__ == "__main__":
    asyncio.run(main())
