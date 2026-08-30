#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path
from typing import Any, Dict

SKILL_DIR = Path(__file__).resolve().parents[1]
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from hermes_wechat_enhance.slash_command_dedup import patch_weixin_adapter


class FakeDedup:
    def __init__(self) -> None:
        self.seen: set[str] = set()

    def is_duplicate(self, key: str) -> bool:
        duplicate = key in self.seen
        self.seen.add(key)
        return duplicate


class FakeWeixinAdapter:
    name = "Weixin"

    def __init__(self) -> None:
        self._dedup = FakeDedup()
        self.accepted: list[tuple[str, str]] = []

    async def _process_message(self, message: Dict[str, Any]) -> None:
        sender_id = str(message.get("from_user_id") or "").strip()
        message_id = str(message.get("message_id") or "").strip()
        if message_id and self._dedup.is_duplicate(message_id):
            return
        text = str(message["item_list"][0]["text_item"]["text"])
        await asyncio.sleep(0)  # Exercise ContextVar isolation across tasks.
        if text:
            content_key = f"content:{sender_id}:{hashlib.md5(text.encode()).hexdigest()}"
            if self._dedup.is_duplicate(content_key):
                return
        self.accepted.append((message_id, text))


def msg(message_id: str, text: str, sender: str = "user-1") -> Dict[str, Any]:
    return {
        "message_id": message_id,
        "from_user_id": sender,
        "item_list": [{"type": 1, "text_item": {"text": text}}],
    }


async def main() -> None:
    adapter = FakeWeixinAdapter()
    assert patch_weixin_adapter(adapter) is True
    assert patch_weixin_adapter(adapter) is False, "patch must be idempotent"

    await adapter._process_message(msg("cmd-1", "/status"))
    await adapter._process_message(msg("cmd-2", "/status"))
    assert [text for _, text in adapter.accepted] == ["/status", "/status"], adapter.accepted

    await adapter._process_message(msg("text-1", "hello"))
    await adapter._process_message(msg("text-2", "hello"))
    assert [text for _, text in adapter.accepted].count("hello") == 1, adapter.accepted

    await adapter._process_message(msg("same-id", "/help"))
    await adapter._process_message(msg("same-id", "/help"))
    assert [text for _, text in adapter.accepted].count("/help") == 1, adapter.accepted

    # Concurrent slash and ordinary text paths must not leak exemption state.
    await asyncio.gather(
        adapter._process_message(msg("cmd-3", "/status", "user-2")),
        adapter._process_message(msg("txt-3", "same", "user-3")),
        adapter._process_message(msg("txt-4", "same", "user-3")),
    )
    assert [text for _, text in adapter.accepted].count("/status") == 3, adapter.accepted
    assert [text for _, text in adapter.accepted].count("same") == 1, adapter.accepted

    print("SLASH_COMMAND_DEDUP_HOOK_TEST=PASS")
    print("provider_message_id_dedup_preserved=true")
    print("repeated_slash_command_allowed=true")
    print("ordinary_text_content_dedup_preserved=true")
    print("contextvar_concurrency_isolation=true")


if __name__ == "__main__":
    asyncio.run(main())
