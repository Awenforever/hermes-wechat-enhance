#!/usr/bin/env python3
"""Exercise the enhancement against Hermes v0.21's real WeixinAdapter."""

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
        from hermes_wechat_enhance.v021_bubble_footer import (
            _set_context_token,
            patch_adapter,
            patch_stream_consumer,
        )
        from gateway.stream_consumer import GatewayStreamConsumer

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
        # Hermes v0.21 normally hard-wraps this source line at 120 columns,
        # which turns Weixin's Markdown link into multiple visual paragraphs.
        # The enhancement keeps the logical Markdown line byte-for-byte intact.
        markdown = (
            "- [A deliberately long research title that remains one semantic link label across "
            "the final Weixin transport boundary without inserted source newlines or broken "
            "Markdown](https://example.test/paper)"
        )
        assert adapter.format_message(markdown) != markdown
        assert patch_adapter(adapter)
        assert adapter.format_message(markdown) == markdown
        state = Path(td) / "plugin-data" / "hermes-wechat-enhance" / "bubble-counters.json"
        assert not state.exists()

        # Exercise Hermes' real approval/clarification boundary fallback.  The
        # core fallback omits metadata on adapter.send; the enhancement must
        # retain model provenance only for this pre-prompt body and then clear
        # it before the following control prompt.
        assert patch_stream_consumer()
        consumer = GatewayStreamConsumer(
            adapter=adapter,
            chat_id="boundary-peer",
            metadata={"actor": "model", "model_name": "deepseek-flash"},
        )
        consumer._accumulated = "model preamble before confirmation"

        async def no_native_frame(_text, *, finalize=False):
            return False

        consumer._send_frame = no_native_frame
        assert await consumer._finalize_boundary_stream("Clarification")
        assert sent[-1][1].endswith("`deepseek-flash`")
        control = await adapter.send("boundary-peer", "confirmation prompt")
        assert control.success
        assert sent[-1][1].endswith("`hermes`")

        body = "z" * 3900
        chunks = adapter._split_text(body)
        assert len(chunks) >= 2
        assert all(len(chunk) <= adapter.MAX_MESSAGE_LENGTH - 160 for chunk in chunks)

        # The official v0.21 store is synchronous while older fixtures and
        # compatible runtimes may be asynchronous; the hook supports both.
        await _set_context_token(
            adapter._token_store, "test-account", "format-peer", "context-format"
        )
        assert adapter._token_store.get("test-account", "format-peer") == "context-format"

        assert state.exists()
        print("V021_REAL_WEIXIN_ADAPTER_TEST_OK")


if __name__ == "__main__":
    asyncio.run(main())
