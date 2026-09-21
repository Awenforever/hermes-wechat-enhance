#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class Result:
    def __init__(self, success=True, error=None):
        self.success = success
        self.error = error
        self.message_id = "sent" if success else None


class Tokens:
    def __init__(self):
        self.value = "token-a"

    def get(self, _account, _chat):
        return self.value

    async def set(self, _account, _chat, value):
        self.value = value


class FakeAdapter:
    name = "weixin"
    MAX_MESSAGE_LENGTH = 400

    def __init__(self):
        self._account_id = "account"
        self._token_store = Tokens()
        self._send_session = object()
        self._token = "token"
        self._split_multiline_messages = False
        self.sent = []
        self.fail_next = False
        self.processed = []

    async def _send_file(self, chat_id, path, caption, force_file_attachment=False):
        return "media-id"

    async def send_document(self, chat_id, file_path, caption=None, **kwargs):
        return Result(True)

    async def send_video(self, chat_id, video_path, caption=None, **kwargs):
        return Result(True)

    async def send_voice(self, chat_id, audio_path, caption=None, **kwargs):
        return Result(True)

    async def _process_message(self, message):
        self.processed.append(message)

    def _split_text(self, content):
        width = self.MAX_MESSAGE_LENGTH
        return [content[i : i + width] for i in range(0, len(content), width)]

    async def _send_text_chunk(self, *, chat_id, chunk, context_token, client_id):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("simulated failure")
        self.sent.append((chat_id, chunk, context_token, client_id))

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        try:
            for i, chunk in enumerate(self._split_text(content)):
                await self._send_text_chunk(
                    chat_id=chat_id,
                    chunk=chunk,
                    context_token=self._token_store.get(self._account_id, chat_id),
                    client_id=f"id-{i}",
                )
            return Result(True)
        except Exception as exc:
            return Result(False, str(exc))


async def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["HERMES_HOME"] = td
        from hermes_wechat_enhance.v021_bubble_footer import (
            install_v021_bubble_footer_hook,
            patch_adapter,
            patch_gateway_runner,
            register_turn_model,
        )

        class Source:
            platform = "weixin"
            chat_id = "route-peer"

        class Runner:
            def _resolve_session_agent_runtime(self, *, source):
                return "qwen3.6-chat", {"provider": "custom"}

        runner = Runner()
        assert patch_gateway_runner(runner)
        assert runner._resolve_session_agent_runtime(source=Source())[0] == "qwen3.6-chat"

        adapter = FakeAdapter()
        assert patch_adapter(adapter) is True
        assert patch_adapter(adapter) is False

        result = await adapter.send("route-peer", "routed before agent:end")
        assert result.success
        assert adapter.sent[-1][1].endswith("`1` `qwen3.6-chat`")

        register_turn_model({"platform": "weixin", "chat_id": "peer", "model": "qwen3.6-chat"})
        result = await adapter.send("peer", "first")
        assert result.success
        assert adapter.sent[-1][1].endswith("`1` `qwen3.6-chat`")

        result = await adapter.send("peer", "system", metadata={"is_system": True})
        assert result.success
        assert adapter.sent[-1][1].endswith("`2` `hermes`")

        restarted = FakeAdapter()
        installed = await install_v021_bubble_footer_hook({"adapters": {"weixin": restarted}})
        assert installed["installed"] == 1 and not installed["errors"]
        register_turn_model({"platform": "weixin", "chat_id": "peer", "model": "qwen3.6-chat"})
        result = await restarted.send("peer", "after restart")
        assert result.success
        assert restarted.sent[-1][1].endswith("`3` `qwen3.6-chat`")
        adapter = restarted

        adapter._token_store.value = "token-b"
        register_turn_model({"platform": "weixin", "chat_id": "peer", "model": "qwen3.6-chat"})
        result = await adapter.send("peer", "new context")
        assert result.success
        assert adapter.sent[-1][1].endswith("`1` `qwen3.6-chat`")

        adapter._token_store.value = "token-c"
        register_turn_model({"platform": "weixin", "chat_id": "peer", "model": "qwen3.6-chat"})
        adapter.fail_next = True
        result = await adapter.send("peer", "will fail")
        assert not result.success
        result = await adapter.send("peer", "retry")
        assert result.success
        assert adapter.sent[-2][1].startswith("will fail")
        assert adapter.sent[-2][1].endswith("`1` `qwen3.6-chat`")
        assert adapter.sent[-1][1].endswith("`2` `qwen3.6-chat`")

        # A transient provider failure retries itself; no new inbound message is required.
        os.environ["HERMES_WECHAT_RETRY_INITIAL_SECONDS"] = "0.01"
        os.environ["HERMES_WECHAT_RETRY_MAX_SECONDS"] = "0.02"
        automatic = FakeAdapter()
        automatic._token_store.value = "token-auto"
        assert patch_adapter(automatic) is True
        automatic.fail_next = True
        result = await automatic.send(
            "auto-peer", "automatic retry", metadata={"_delivery_id": "automatic-retry"}
        )
        assert not result.success
        await asyncio.sleep(0.08)
        assert automatic._hermes_wechat_runtime_v2.pending_count("account", "auto-peer") == 0
        assert automatic.sent[-1][1].startswith("automatic retry")
        assert automatic.sent[-1][1].endswith("`1` `hermes`")
        os.environ.pop("HERMES_WECHAT_RETRY_INITIAL_SECONDS", None)
        os.environ.pop("HERMES_WECHAT_RETRY_MAX_SECONDS", None)

        adapter._token_store.value = "token-d"
        register_turn_model({"platform": "weixin", "chat_id": "peer", "model": "qwen3.6-chat"})
        before = len(adapter.sent)
        result = await adapter.send("peer", "x" * 600)
        assert result.success
        bubbles = adapter.sent[before:]
        assert len(bubbles) >= 2
        assert bubbles[0][1].endswith("`1` `qwen3.6-chat`")
        assert bubbles[1][1].endswith("`2` `qwen3.6-chat`")
        assert bubbles[-1][1].endswith(f"`{len(bubbles)}` `qwen3.6-chat`")
        assert all(len(item[1]) <= adapter.MAX_MESSAGE_LENGTH for item in bubbles)

        # Ten physical bubbles per context; overflow remains durable and FIFO.
        adapter._token_store.value = "token-e"
        register_turn_model({"platform": "weixin", "chat_id": "peer", "model": "qwen3.6-chat"})
        before = len(adapter.sent)
        for index in range(12):
            result = await adapter.send(
                "peer", f"queued-{index}", metadata={"_delivery_id": f"delivery-{index}"}
            )
            assert result.success
        assert len(adapter.sent) - before == 10
        assert adapter._hermes_wechat_runtime_v2.pending_count("account", "peer") == 2

        # /continue refreshes the token, drains in FIFO order, and never reaches the agent.
        await adapter._process_message({
            "from_user_id": "peer", "message_id": "continue-1", "context_token": "token-f",
            "item_list": [{"type": 1, "text": "/continue", "text_item": {"text": "/continue"}}],
        })
        assert adapter.processed == []
        assert adapter._hermes_wechat_runtime_v2.pending_count("account", "peer") == 0
        assert adapter.sent[-2][1].startswith("queued-10")
        assert adapter.sent[-1][1].startswith("queued-11")
        assert adapter.sent[-2][1].endswith("`1` `qwen3.6-chat`")
        assert adapter.sent[-1][1].endswith("`2` `qwen3.6-chat`")

        print("V021_BUBBLE_FOOTER_TEST_OK")


if __name__ == "__main__":
    asyncio.run(main())
