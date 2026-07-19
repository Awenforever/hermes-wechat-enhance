#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
import types
from pathlib import Path
from typing import Any

GATEWAY_SRC = Path(os.environ.get("HERMES_GATEWAY_SRC", "/opt/hermes"))
if str(GATEWAY_SRC) not in sys.path:
    sys.path.insert(0, str(GATEWAY_SRC))

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter
from gateway.platforms.helpers import MessageDeduplicator
from gateway.platforms.weixin import (
    ContextTokenStore,
    ITEM_TEXT,
    MessageSendQueue,
    ReplyBudgetStore,
    WeixinAdapter,
)

class TokenStore:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set(self, account_id: str, user_id: str, token: str) -> None:
        self.values[(account_id, user_id)] = token

    def get(self, account_id: str, user_id: str) -> str | None:
        return self.values.get((account_id, user_id))

    def items_for_account(self, account_id: str) -> dict[str, str]:
        return {
            user_id: token
            for (current_account, user_id), token in self.values.items()
            if current_account == account_id
        }

class NoDedup:
    def is_duplicate(self, key: str) -> bool:
        return False

def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)

def parse_footer(text: str) -> tuple[int, str]:
    match = re.search(r"\n---\n\n`(\d+)`\s+`([^`]+)`\s*$", text)
    require(match is not None, f"footer missing: {text!r}")
    assert match is not None
    return int(match.group(1)), match.group(2)

def adapter(root: Path, *, real_dedup: bool = False) -> WeixinAdapter:
    # TEST_WEIXIN_ADAPTER_REAL_INIT_V1
    # Use the real constructor so the harness inherits every official runtime
    # field, including split_multiline_messages and future additions.
    instance = WeixinAdapter(
        PlatformConfig(
            enabled=True,
            token="transport",
            extra={
                "account_id": "acct",
                "base_url": "https://invalid.local",
                "split_multiline_messages": False,
                "send_chunk_delay_seconds": 0.0,
                "send_chunk_retries": 0,
                "send_chunk_retry_delay_seconds": 0.0,
                "dm_policy": "pairing",
                "group_policy": "disabled",
            },
        )
    )

    # Replace only external side effects and persistent stores.
    instance._account_id = "acct"
    instance._token = "transport"
    instance._base_url = "https://invalid.local"
    instance._send_queue = MessageSendQueue()
    instance._budget_store = ReplyBudgetStore(str(root))
    instance._token_store = TokenStore()
    instance._dedup = (
        MessageDeduplicator(ttl_seconds=300) if real_dedup else NoDedup()
    )
    instance._poll_session = object()
    instance._send_session = object()
    instance._send_chunk_delay_seconds = 0.0
    instance._send_chunk_retries = 0
    instance._send_chunk_retry_delay_seconds = 0.0
    instance._context_delivery_locks = {}
    instance._is_dm_intake_allowed = lambda sender_id: True
    instance._events: list[str] = []

    async def no_typing(sender_id: str, token: str | None) -> None:
        return None

    async def no_media(items: Any, paths: Any, types_: Any) -> None:
        return None

    instance._maybe_fetch_typing_ticket = no_typing
    instance._collect_media = no_media
    instance.build_source = lambda **kwargs: types.SimpleNamespace(
        platform="weixin",
        chat_id=kwargs.get("chat_id"),
        chat_type=kwargs.get("chat_type"),
        user_id=kwargs.get("user_id"),
        user_name=kwargs.get("user_name"),
    )
    instance._enqueue_text_event = lambda event: instance._events.append(
        str(getattr(event, "text", ""))
    )
    return instance

def incoming(text: str, message_id: str, token: str) -> dict[str, Any]:
    return {
        "from_user_id": "user",
        "message_id": message_id,
        "item_list": [{"type": ITEM_TEXT, "text_item": {"text": text}}],
        "context_token": token,
    }

async def adapter_runtime_initialization(root: Path) -> None:
    current = adapter(root / "adapter-runtime-init")
    require(current.platform is Platform.WEIXIN, "platform initialization failed")
    require(current.name.lower() == "weixin", "adapter name initialization failed")
    require(
        hasattr(current, "_split_multiline_messages"),
        "real Weixin constructor did not initialize split_multiline_messages",
    )
    require(
        current._split_multiline_messages is False,
        "unexpected split_multiline_messages test default",
    )
    require(
        hasattr(current, "_send_text_gate"),
        "real Weixin constructor did not initialize send gate",
    )
    print("SYNTHETIC_ADAPTER_RUNTIME_INIT_OK")


async def slash_matrix(root: Path) -> None:
    commands = [
        "/continue", "/new", "/reset", "/help", "/status",
        "/model deepseek-v4-pro", "/email status", "/unknown-command",
        "  /continue  ", "/CONTINUE",
    ]
    for index, command in enumerate(commands):
        current = adapter(root / f"slash-{index}", real_dedup=True)
        await current._process_message(incoming(command, "id-1", "token-1"))
        await current._process_message(incoming(command, "id-2", "token-2"))
        require(
            current._budget_store.get_valid_token("acct", "user") == "token-2",
            f"slash command did not refresh second token: {command!r}",
        )
    print("SLASH_COMMAND_CONTENT_DEDUP_EXEMPTION_OK")

async def message_id_replay(root: Path) -> None:
    current = adapter(root / "message-id", real_dedup=True)
    await current._process_message(incoming("/status", "same", "token-1"))
    await current._process_message(incoming("/help", "same", "token-2"))
    require(
        current._budget_store.get_valid_token("acct", "user") == "token-1",
        "message-id replay protection was lost",
    )
    print("MESSAGE_ID_REPLAY_DEDUP_OK")

async def normal_content_order(root: Path) -> None:
    current = adapter(root / "normal", real_dedup=True)
    await current._process_message(incoming("same text", "normal-1", "token-1"))
    first_dispatches = len(current._events)
    await current._process_message(incoming("same text", "normal-2", "token-2"))
    require(
        current._budget_store.get_valid_token("acct", "user") == "token-2",
        "normal duplicate lost the new context token",
    )
    require(
        first_dispatches == 1 and len(current._events) == 1,
        "ordinary content suppression changed",
    )
    print("CONTEXT_REFRESH_BEFORE_CONTENT_DEDUP_OK")

async def continue_contract(root: Path) -> None:
    current = adapter(root / "continue")
    agent_called = False
    sent: list[tuple[int, bool]] = []

    def forbidden(**kwargs: Any) -> Any:
        nonlocal agent_called
        agent_called = True
        raise AssertionError("/continue routed to Agent")

    async def capture(
        *, chat_id: str, chunk: str, context_token: str | None, client_id: str
    ) -> None:
        sent.append((parse_footer(chunk)[0], context_token == "new"))

    current.build_source = forbidden
    current._send_text_chunk = capture
    current._budget_store.update_token("acct", "user", "old")
    current._budget_store.commit_count("acct", "user", 7)
    for index in range(2):
        current._send_queue.enqueue(
            "acct", "user", f"pending-{index}", "user", None,
            {
                "is_system": True,
                "_delivery_id": f"pending-{index}",
                "_delivery_chunk_index": 0,
            },
        )
    await current._process_message(incoming("/continue", "continue-1", "new"))
    require([item[0] for item in sent] == [1, 2], "continue footer sequence")
    require(all(item[1] for item in sent), "continue did not use new token")
    require(not agent_called, "continue called Agent")
    require(current._budget_store.get_count("acct", "user") == 2, "continue count")
    print("CONTINUE_SILENT_REFRESH_DRAIN_OK")

async def shared_count(root: Path) -> None:
    current = adapter(root / "shared")
    current._budget_store.update_token("acct", "user", "token")
    current._token_store.set("acct", "user", "token")
    numbers: list[int] = []

    async def capture(*, chunk: str, **kwargs: Any) -> None:
        numbers.append(parse_footer(chunk)[0])

    current._send_text_chunk = capture
    producers = [
        ("system", {"is_system": True}),
        ("model", {"model_name": "model-A"}),
        ("alive", {"model_name": "model-B", "source": "hermes-alive"}),
        ("email", {"is_system": True, "source": "email-watchdog"}),
    ]
    for index, (body, metadata) in enumerate(producers):
        current._send_queue.enqueue(
            "acct", "user", body, "user", None,
            dict(metadata, _delivery_id=f"d-{index}", _delivery_chunk_index=0),
        )
    result = await current._drain_pending("user")
    require(result.success and numbers == [1, 2, 3, 4], "shared footer count")
    print("SHARED_CONTEXT_TOKEN_COUNT_OK")


async def ordinary_reply_append_then_drain(root: Path) -> None:
    current = adapter(root / "ordinary-reply")
    current._budget_store.update_token("acct", "user", "old-token")
    current._token_store.set("acct", "user", "old-token")
    current._budget_store.commit_count("acct", "user", 6)

    for body in ("old-A", "old-B"):
        current._send_queue.enqueue(
            "acct",
            "user",
            body,
            "user",
            None,
            {
                "_delivery_id": f"pending-{body}",
                "_delivery_chunk_index": 0,
            },
        )

    sent: list[tuple[str, int, bool]] = []

    async def capture(
        *,
        chat_id: str,
        chunk: str,
        context_token: str | None,
        client_id: str,
    ) -> None:
        body = chunk.split("\n---\n", 1)[0].strip()
        number, _ = parse_footer(chunk)
        sent.append((body, number, context_token == "new-token"))

    current._send_text_chunk = capture

    # The ordinary inbound message establishes a new Context token and resets
    # its count. Its generated reply is then sent through the normal send()
    # path, which must append it behind the existing pending items and drain
    # the complete FIFO queue.
    await current._process_message(
        incoming("ordinary inbound", "ordinary-id", "new-token")
    )
    require(
        current._budget_store.get_count("acct", "user") == 0,
        "ordinary inbound did not reset the new token budget",
    )
    require(
        current._send_queue.pending_count("acct", "user") == 2,
        "ordinary inbound unexpectedly reordered or drained pending replies",
    )

    result = await current.send(
        chat_id="user",
        content="new-C",
        metadata={
            "model_name": "model-C",
            "_delivery_id": "ordinary-reply-C",
        },
    )

    require(result.success, "ordinary reply drain returned failure")
    require(
        [(body, number) for body, number, _ in sent]
        == [("old-A", 1), ("old-B", 2), ("new-C", 3)],
        f"ordinary reply FIFO sequence incorrect: {sent!r}",
    )
    require(
        all(uses_new_token for _, _, uses_new_token in sent),
        "ordinary reply drain did not use the newest Context token",
    )
    require(
        current._send_queue.pending_count("acct", "user") == 0,
        "ordinary reply did not drain the complete queue",
    )
    require(
        current._budget_store.get_count("acct", "user") == 3,
        "ordinary reply final budget count is not 3",
    )
    print("ORDINARY_REPLY_APPEND_THEN_DRAIN_OK")


async def acknowledgement_and_maximum(root: Path) -> None:
    current = adapter(root / "ack")
    current._budget_store.update_token("acct", "user", "token")
    current._send_queue.enqueue(
        "acct", "user", "payload", "user", None,
        {"_delivery_id": "retry", "_delivery_chunk_index": 0},
    )
    calls = 0

    async def fail_once(**kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic failure")

    current._send_text_chunk = fail_once
    first = await current._drain_pending("user")
    require(not first.success, "failed send returned success")
    require(current._budget_store.get_count("acct", "user") == 0, "failure consumed count")
    require(current._send_queue.pending_count("acct", "user") == 1, "failure dequeued")
    second = await current._drain_pending("user")
    require(second.success, "retry did not succeed")
    require(current._budget_store.get_count("acct", "user") == 1, "retry count")

    maximum = adapter(root / "max")
    maximum._budget_store.update_token("acct", "user", "token")
    numbers: list[int] = []

    async def capture(*, chunk: str, **kwargs: Any) -> None:
        numbers.append(parse_footer(chunk)[0])

    maximum._send_text_chunk = capture
    for index in range(11):
        maximum._send_queue.enqueue(
            "acct", "user", f"m-{index}", "user", None,
            {"_delivery_id": f"m-{index}", "_delivery_chunk_index": 0},
        )
    result = await maximum._drain_pending("user")
    require(not result.success, "11-message drain unexpectedly succeeded")
    require(numbers == list(range(1, 11)), "maximum sequence")
    require(maximum._send_queue.pending_count("acct", "user") == 1, "11th not pending")
    print("ACK_COMMIT_AND_MAXIMUM_TEN_OK")

async def token_and_drain_races(root: Path) -> None:
    current = adapter(root / "token-race")
    current._budget_store.update_token("acct", "user", "old")
    current._token_store.set("acct", "user", "old")
    current._budget_store.commit_count("acct", "user", 9)
    current._send_queue.enqueue(
        "acct", "user", "old", "user", None,
        {"_delivery_id": "old", "_delivery_chunk_index": 0},
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked(**kwargs: Any) -> None:
        started.set()
        await release.wait()

    current._send_text_chunk = blocked
    drain = asyncio.create_task(current._drain_pending("user"))
    await asyncio.wait_for(started.wait(), timeout=3)
    refresh = asyncio.create_task(
        current._process_message(incoming("/continue", "new-id", "new"))
    )
    await asyncio.sleep(0.05)
    require(not refresh.done(), "new token bypassed in-flight delivery lock")
    release.set()
    await asyncio.wait_for(drain, timeout=3)
    await asyncio.wait_for(refresh, timeout=3)
    require(
        current._budget_store.get_count("acct", "user") == 0,
        "old ack contaminated new token",
    )

    parallel = adapter(root / "parallel")
    parallel._budget_store.update_token("acct", "user", "token")
    for body in ("A", "B"):
        parallel._send_queue.enqueue(
            "acct", "user", body, "user", None,
            {"_delivery_id": body, "_delivery_chunk_index": 0},
        )
    calls: list[tuple[str, int]] = []
    first_started = asyncio.Event()
    first_release = asyncio.Event()

    async def serialized(*, chunk: str, **kwargs: Any) -> None:
        calls.append((chunk.split("\n", 1)[0], parse_footer(chunk)[0]))
        if len(calls) == 1:
            first_started.set()
            await first_release.wait()

    parallel._send_text_chunk = serialized
    task_one = asyncio.create_task(parallel._drain_pending("user"))
    await asyncio.wait_for(first_started.wait(), timeout=3)
    task_two = asyncio.create_task(parallel._drain_pending("user"))
    await asyncio.sleep(0.05)
    first_release.set()
    await asyncio.wait_for(asyncio.gather(task_one, task_two), timeout=5)
    require(calls == [("A", 1), ("B", 2)], f"concurrent drain calls={calls!r}")
    require(parallel._budget_store.get_count("acct", "user") == 2, "parallel count")
    print("TOKEN_GENERATION_AND_DRAIN_SERIALIZATION_OK")

async def media_budget(root: Path) -> None:
    current = adapter(root / "media")
    current._budget_store.update_token("acct", "user", "token")
    current._token_store.set("acct", "user", "token")
    text_numbers: list[int] = []

    async def text_send(*, chunk: str, **kwargs: Any) -> None:
        text_numbers.append(parse_footer(chunk)[0])

    async def media_send(
        chat_id: str,
        path: str,
        caption: str,
        force_file_attachment: bool = False,
    ) -> str:
        require(caption == "", "raw media send received caption")
        return "media-id"

    current._send_text_chunk = text_send
    current._send_file = media_send
    with tempfile.NamedTemporaryFile() as handle:
        result = await current.send_document(
            chat_id="user",
            file_path=handle.name,
            caption=None,
            metadata={"is_system": True},
        )
        require(result.success, "media without caption failed")
        require(current._budget_store.get_count("acct", "user") == 1, "media did not count")

        result = await current.send_document(
            chat_id="user",
            file_path=handle.name,
            caption="caption",
            metadata={"is_system": True},
        )
        require(result.success, "media with caption failed")
        require(text_numbers == [2], f"caption footer sequence={text_numbers!r}")
        require(current._budget_store.get_count("acct", "user") == 3, "caption+media count")
    print("MEDIA_CONTEXT_TOKEN_BUDGET_OK")

def persistence_reconciliation(root: Path) -> None:
    token_store = ContextTokenStore(str(root / "persist"))
    budget_store = ReplyBudgetStore(str(root / "persist"))
    token_store.set("acct", "user", "old")
    budget_store.update_token("acct", "user", "old")
    budget_store.commit_count("acct", "user", 7)
    token_store.set("acct", "user", "new")

    restored_tokens = ContextTokenStore(str(root / "persist"))
    restored_budget = ReplyBudgetStore(str(root / "persist"))
    restored_tokens.restore("acct")
    restored_budget.restore("acct")
    restored_budget.reconcile_from_context_tokens(
        "acct", restored_tokens.items_for_account("acct")
    )
    require(restored_budget.get_valid_token("acct", "user") == "new", "reconcile token")
    require(restored_budget.get_count("acct", "user") == 0, "reconcile count")
    print("CONTEXT_BUDGET_RECONCILIATION_OK")

async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="context-kernel-contract-") as directory:
        root = Path(directory)
        await adapter_runtime_initialization(root)
        await slash_matrix(root)
        await message_id_replay(root)
        await normal_content_order(root)
        await continue_contract(root)
        await shared_count(root)
        await ordinary_reply_append_then_drain(root)
        await acknowledgement_and_maximum(root)
        await token_and_drain_races(root)
        await media_budget(root)
        persistence_reconciliation(root)
    print("CONTEXT_TOKEN_KERNEL_CONTRACT_OK")

if __name__ == "__main__":
    asyncio.run(main())
