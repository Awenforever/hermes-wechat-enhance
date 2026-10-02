#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import types
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
        self.updates = []

    def get(self, _account, _chat):
        return self.value

    async def set(self, _account, _chat, value):
        self.value = value
        self.updates.append((_account, _chat, value))


class Dedup:
    def __init__(self):
        self.seen = set()

    def is_duplicate(self, value):
        if value in self.seen:
            return True
        self.seen.add(value)
        return False


class FakeAdapter:
    name = "weixin"
    MAX_MESSAGE_LENGTH = 400

    def __init__(self):
        self._account_id = "account"
        self._token_store = Tokens()
        self._split_multiline_messages = False
        self._dedup = Dedup()
        self.sent = []
        self.routed = []
        self.fail_next = False
        self.next_id = 0

    def _is_dm_intake_allowed(self, _sender):
        return True

    def _is_group_allowed(self, _chat):
        return False

    async def _process_message(self, message):
        self.routed.append(message)

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
            for chunk in self._split_text(content):
                self.next_id += 1
                await self._send_text_chunk(
                    chat_id=chat_id,
                    chunk=chunk,
                    context_token=self._token_store.get(self._account_id, chat_id),
                    client_id=f"id-{self.next_id}",
                )
            return Result(True)
        except Exception as exc:
            return Result(False, str(exc))


async def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["HERMES_HOME"] = td
        gateway = types.ModuleType("gateway")
        gateway.__path__ = []
        gateway_run = types.ModuleType("gateway.run")
        stream_consumer_module = types.ModuleType("gateway.stream_consumer")

        class FakeStreamConsumer:
            def __init__(self, adapter, chat_id, metadata=None, **_kwargs):
                self.adapter = adapter
                self.chat_id = chat_id
                self.metadata = metadata

        stream_consumer_module.GatewayStreamConsumer = FakeStreamConsumer
        platforms = types.ModuleType("gateway.platforms")
        platforms.__path__ = []
        weixin = types.ModuleType("gateway.platforms.weixin")
        weixin._extract_text = lambda items: str((items or [{}])[0].get("text") or "")
        weixin._guess_chat_type = lambda message, _account: ("dm", str(message.get("from_user_id") or ""))
        sys.modules.setdefault("gateway", gateway)
        sys.modules.setdefault("gateway.platforms", platforms)
        sys.modules["gateway.platforms.weixin"] = weixin
        sys.modules["gateway.stream_consumer"] = stream_consumer_module
        from hermes_wechat_enhance.v021_bubble_footer import (
            install_v021_bubble_footer_hook,
            patch_adapter,
            patch_gateway_runner,
            patch_stream_consumer,
            register_turn_model,
        )

        class Source:
            platform = "weixin"
            chat_id = "peer"

        class Runner:
            def _resolve_session_agent_runtime(self, **_kwargs):
                return "deepseek-flash", {"provider": "ustc"}

        runner = Runner()
        gateway_run._gateway_runner_ref = lambda: runner
        sys.modules["gateway.run"] = gateway_run

        adapter = FakeAdapter()
        assert patch_adapter(adapter) is True
        assert patch_adapter(adapter) is False

        # The route is captured before streaming begins, but only the model
        # output transport receives it. Unmarked gateway control traffic must
        # remain Hermes-owned even while that model turn is active.
        assert patch_gateway_runner(runner) is True
        assert patch_gateway_runner(runner) is False
        assert patch_stream_consumer() is True
        assert patch_stream_consumer() is False
        runner._resolve_session_agent_runtime(source=Source(), session_key="weixin:peer")
        adapter._token_store.value = "token-route-test"
        before = len(adapter.sent)
        consumer = FakeStreamConsumer(adapter=adapter, chat_id="peer")
        assert consumer.metadata["actor"] == "model"
        assert consumer.metadata["model_name"] == "deepseek-flash"
        for content in ("commentary one", "commentary two"):
            result = await adapter.send("peer", content, metadata=consumer.metadata)
            assert result.success
        for control in ("approval prompt", "command approved", "working heartbeat"):
            result = await adapter.send("peer", control)
            assert result.success
            assert adapter.sent[-1][1].endswith("`hermes`")
        register_turn_model({
            "platform": "weixin", "chat_id": "peer", "model": "deepseek-flash",
            "response": "final answer",
        })
        result = await adapter.send("peer", "final answer")
        assert result.success
        turn_bubbles = adapter.sent[before:]
        assert len(turn_bubbles) == 6
        assert all(item[1].endswith("`deepseek-flash`") for item in turn_bubbles[:2])
        assert all(item[1].endswith("`hermes`") for item in turn_bubbles[2:5])
        assert turn_bubbles[-1][1].endswith("`deepseek-flash`")
        adapter._token_store.value = "token-a"

        register_turn_model({
            "platform": "weixin", "chat_id": "peer", "model": "qwen3.6-chat", "response": "first",
        })
        result = await adapter.send("peer", "first")
        assert result.success
        assert adapter.sent[-1][1].endswith("`1` `qwen3.6-chat`")

        result = await adapter.send("peer", "system", metadata={"is_system": True})
        assert result.success
        assert adapter.sent[-1][1].endswith("`2` `hermes`")

        restarted = FakeAdapter()
        installed = await install_v021_bubble_footer_hook({"adapters": {"weixin": restarted}})
        assert installed["installed"] == 1 and not installed["errors"]
        register_turn_model({
            "platform": "weixin", "chat_id": "peer", "model": "qwen3.6-chat", "response": "after restart",
        })
        result = await restarted.send("peer", "after restart")
        assert result.success
        assert restarted.sent[-1][1].endswith("`3` `qwen3.6-chat`")
        adapter = restarted

        adapter._token_store.value = "token-b"
        register_turn_model({
            "platform": "weixin", "chat_id": "peer", "model": "qwen3.6-chat", "response": "new context",
        })
        result = await adapter.send("peer", "new context")
        assert result.success
        assert adapter.sent[-1][1].endswith("`1` `qwen3.6-chat`")

        adapter._token_store.value = "token-c"
        register_turn_model({
            "platform": "weixin", "chat_id": "peer", "model": "qwen3.6-chat", "response": "will fail",
        })
        adapter.fail_next = True
        result = await adapter.send("peer", "will fail")
        assert result.success
        assert adapter._hermes_wechat_v021_pending_queue.count("account", "peer") == 1
        result = await adapter.send("peer", "retry", metadata={"model_name": "qwen3.6-chat"})
        assert result.success
        assert adapter._hermes_wechat_v021_pending_queue.count("account", "peer") == 2
        before_drain = len(adapter.sent)
        await adapter._process_message({
            "from_user_id": "peer",
            "message_id": "continue-1",
            "context_token": "token-d",
            "item_list": [{"text": "/continue"}],
        })
        assert len(adapter.sent) == before_drain + 2
        assert adapter._hermes_wechat_v021_pending_queue.count("account", "peer") == 0
        assert not adapter.routed
        assert adapter.sent[-2][1].endswith("`1` `qwen3.6-chat`")
        assert adapter.sent[-1][1].endswith("`2` `qwen3.6-chat`")

        # Every ordinary inbound message refreshes the token before Hermes
        # dedup/routing and automatically resumes the FIFO; it still reaches
        # the normal conversation path.
        adapter.fail_next = True
        result = await adapter.send("peer", "queued for ordinary inbound", metadata={"model": "deepseek-flash"})
        assert result.success
        assert adapter._hermes_wechat_v021_pending_queue.count("account", "peer") == 1
        routed_before = len(adapter.routed)
        await adapter._process_message({
            "from_user_id": "peer",
            "message_id": "ordinary-1",
            "context_token": "token-ordinary",
            "item_list": [{"text": "hello"}],
        })
        assert adapter._token_store.value == "token-ordinary"
        assert adapter._token_store.updates[-1] == ("account", "peer", "token-ordinary")
        assert adapter._hermes_wechat_v021_pending_queue.count("account", "peer") == 0
        assert len(adapter.routed) == routed_before + 1
        assert adapter.sent[-1][1].endswith("`1` `deepseek-flash`")

        # Even a duplicate inbound message refreshes the context token before
        # the core adapter decides not to route it again.
        adapter._dedup.seen.add("duplicate-1")
        await adapter._process_message({
            "from_user_id": "peer",
            "message_id": "duplicate-1",
            "context_token": "token-duplicate-refresh",
            "item_list": [{"text": "hello again"}],
        })
        assert adapter._token_store.value == "token-duplicate-refresh"

        adapter._token_store.value = "token-e"
        register_turn_model({
            "platform": "weixin", "chat_id": "peer", "model": "qwen3.6-chat", "response": "x" * 600,
        })
        before = len(adapter.sent)
        result = await adapter.send("peer", "x" * 600)
        assert result.success
        bubbles = adapter.sent[before:]
        assert len(bubbles) >= 2
        assert bubbles[0][1].endswith("`1` `qwen3.6-chat`")
        assert bubbles[1][1].endswith("`2` `qwen3.6-chat`")
        assert bubbles[-1][1].endswith(f"`{len(bubbles)}` `qwen3.6-chat`")
        assert all(len(item[1]) <= adapter.MAX_MESSAGE_LENGTH for item in bubbles)

        print("V021_BUBBLE_FOOTER_TEST_OK")


if __name__ == "__main__":
    asyncio.run(main())
