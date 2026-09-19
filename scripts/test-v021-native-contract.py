#!/usr/bin/env python3
"""Hermes v0.21 native Weixin persistence and FIFO acceptance contract."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


GATEWAY_SRC = Path(os.environ.get("HERMES_GATEWAY_SRC", "/opt/hermes"))
if str(GATEWAY_SRC) not in sys.path:
    sys.path.insert(0, str(GATEWAY_SRC))

from gateway.config import Platform, PlatformConfig
from gateway.platforms import weixin
from gateway.platforms.base import BasePlatformAdapter, SendResult
from gateway.platforms.event import MessageEvent, MessageType
from gateway.run import GatewayRunner


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class StubAdapter(BasePlatformAdapter):
    def __init__(self) -> None:
        super().__init__(
            PlatformConfig(enabled=True, token="test"),
            Platform.WEIXIN,
        )

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        return SendResult(success=True, message_id="test")

    async def get_chat_info(self, chat_id: str) -> dict[str, str]:
        return {"id": chat_id, "type": "dm"}


async def token_persistence_contract() -> None:
    with tempfile.TemporaryDirectory(prefix="wechat-v021-token-") as raw:
        store = weixin.ContextTokenStore(raw)
        writes: list[dict[str, str]] = []
        calls = 0
        original = weixin.atomic_json_write

        def slow_first_write(path: Path, data: dict[str, str]) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                time.sleep(0.05)
            writes.append(dict(data))

        weixin.atomic_json_write = slow_first_write
        try:
            first = asyncio.create_task(store.set("acct", "user-1", "token-1"))
            await asyncio.sleep(0.005)
            second = asyncio.create_task(store.set("acct", "user-2", "token-2"))
            await asyncio.gather(first, second)
        finally:
            weixin.atomic_json_write = original

        require(
            writes[-1] == {"user-1": "token-1", "user-2": "token-2"},
            "concurrent context-token persistence landed out of order",
        )


async def stale_token_fallback_contract() -> None:
    adapter = weixin.WeixinAdapter(
        PlatformConfig(
            enabled=True,
            token="test-token",
            extra={
                "account_id": "acct",
                "send_chunk_retries": 1,
                "send_chunk_retry_delay_seconds": 0,
            },
        )
    )
    adapter._send_session = object()
    calls: list[str | None] = []
    original = weixin._send_message

    async def fake_send_message(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs.get("context_token"))
        if len(calls) == 1:
            return {"ret": -14, "errmsg": "expired"}
        return {"ret": 0}

    weixin._send_message = fake_send_message
    try:
        await adapter._send_text_chunk(
            chat_id="peer",
            chunk="acceptance",
            context_token="stale-token",
            client_id="acceptance-id",
        )
    finally:
        weixin._send_message = original
    require(calls == ["stale-token", None], "stale token did not degrade to tokenless send")


def fifo_contract() -> None:
    runner = GatewayRunner.__new__(GatewayRunner)
    adapter = StubAdapter()
    runner.adapters = {Platform.WEIXIN: adapter}
    session_key = "weixin:user:fifo"
    source = adapter.build_source(
        chat_id="peer",
        chat_type="dm",
        user_id="peer",
    )
    texts = ["one", "two", "three", "four", "five"]
    for index, text in enumerate(texts):
        runner._queue_or_replace_pending_event(
            session_key,
            MessageEvent(
                text=text,
                message_type=MessageType.TEXT,
                source=source,
                message_id=f"m-{index}",
            ),
        )

    require(adapter._pending_messages[session_key].text == "one", "FIFO head changed")
    queued = runner._session_state(session_key).conversation.queued_events
    require([event.text for event in queued] == texts[1:], "FIFO overflow order changed")
    require(runner._queue_depth(session_key, adapter=adapter) == len(texts), "FIFO lost messages")


def config_contract() -> None:
    home = os.environ.get("HERMES_HOME", "").strip()
    if not home:
        return
    path = Path(home) / "config.yaml"
    if not path.is_file():
        return
    import yaml

    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    mode = ((config.get("display") or {}).get("busy_input_mode"))
    require(mode == "queue", f"display.busy_input_mode must be queue, got {mode!r}")


async def main() -> None:
    await token_persistence_contract()
    await stale_token_fallback_contract()
    fifo_contract()
    config_contract()
    print(json.dumps({"ok": True, "contract": "HERMES_WECHAT_V021_NATIVE_FIFO_V1"}))


if __name__ == "__main__":
    asyncio.run(main())
