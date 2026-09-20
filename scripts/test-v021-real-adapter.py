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
        media_sent = []

        async def fake_transport(_self, *, chat_id, chunk, context_token, client_id):
            sent.append((chat_id, chunk, context_token, client_id))

        async def fake_media_transport(
            _self, chat_id, path, caption, force_file_attachment=False
        ):
            assert caption == ""
            media_sent.append((chat_id, path, force_file_attachment))
            return "media-id"

        adapter._send_text_chunk = MethodType(fake_transport, adapter)
        adapter._send_file = MethodType(fake_media_transport, adapter)
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

        # Media bubbles share the same ten-bubble budget. A caption remains a
        # separately numbered/model-tagged text bubble, matching v0.18.
        media_path = Path(td) / "sample.bin"
        media_path.write_bytes(b"sample")
        await adapter._token_store.set("test-account", "media-peer", "context-m1")
        register_turn_model({"platform": "weixin", "chat_id": "media-peer", "model": "qwen3.6-chat"})
        result = await adapter.send_document("media-peer", str(media_path))
        assert result.success
        assert adapter._hermes_wechat_runtime_v2.snapshot(
            "test-account", "media-peer", "context-m1"
        )[0] == 1
        result = await adapter.send_document("media-peer", str(media_path), caption="caption")
        assert result.success
        assert sent[-1][1].endswith("`2` `qwen3.6-chat`")
        assert adapter._hermes_wechat_runtime_v2.snapshot(
            "test-account", "media-peer", "context-m1"
        )[0] == 3
        assert len(media_sent) == 2

        # Exhaust one context budget and verify the overflow survives an adapter restart.
        await adapter._token_store.set("test-account", "queued-peer", "context-q1")
        register_turn_model({"platform": "weixin", "chat_id": "queued-peer", "model": "qwen3.6-chat"})
        for index in range(12):
            result = await adapter.send(
                "queued-peer", f"queued-{index}", metadata={"_delivery_id": f"real-{index}"}
            )
            assert result.success
        assert adapter._hermes_wechat_runtime_v2.pending_count("test-account", "queued-peer") == 2

        restarted = WeixinAdapter(
            PlatformConfig(
                enabled=True,
                token="test-token",
                extra={"account_id": "test-account", "send_chunk_delay_seconds": 0},
            )
        )
        restarted._send_session = object()
        restarted_sent = []

        async def restarted_transport(_self, *, chat_id, chunk, context_token, client_id):
            restarted_sent.append((chat_id, chunk, context_token, client_id))

        restarted._send_text_chunk = MethodType(restarted_transport, restarted)
        assert patch_adapter(restarted)
        from gateway.platforms import weixin as wx
        await restarted._process_message({
            "from_user_id": "queued-peer", "message_id": "continue-real-1",
            "context_token": "context-q2",
            "item_list": [{"type": wx.ITEM_TEXT, "text_item": {"text": "/continue"}}],
        })
        assert restarted._hermes_wechat_runtime_v2.pending_count("test-account", "queued-peer") == 0
        assert len(restarted_sent) == 2
        assert restarted_sent[0][1].startswith("queued-10")
        assert restarted_sent[1][1].startswith("queued-11")
        assert restarted_sent[0][1].endswith("`1` `qwen3.6-chat`")
        assert restarted_sent[1][1].endswith("`2` `qwen3.6-chat`")

        state = Path(td) / "plugin-data" / "hermes-wechat-enhance" / "runtime.sqlite3"
        raw = state.read_bytes().decode("latin1")
        assert "context-a" not in raw and "test-account" not in raw and "peer" not in raw
        print("V021_REAL_WEIXIN_ADAPTER_TEST_OK")


if __name__ == "__main__":
    asyncio.run(main())
