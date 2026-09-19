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


class FakeAdapter:
    name = "weixin"
    MAX_MESSAGE_LENGTH = 400

    def __init__(self):
        self._account_id = "account"
        self._token_store = Tokens()
        self._split_multiline_messages = False
        self.sent = []
        self.fail_next = False

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
            register_turn_model,
        )

        adapter = FakeAdapter()
        assert patch_adapter(adapter) is True
        assert patch_adapter(adapter) is False

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
        assert adapter.sent[-1][1].endswith("`1` `qwen3.6-chat`")

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

        print("V021_BUBBLE_FOOTER_TEST_OK")


if __name__ == "__main__":
    asyncio.run(main())
