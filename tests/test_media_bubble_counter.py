import asyncio
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_wechat_enhance.v021_bubble_footer import patch_adapter


class _TokenStore:
    def __init__(self):
        self.value = "context-1"

    def get(self, _account, _chat):
        return self.value

    def set(self, _account, _chat, value):
        self.value = value


class _Adapter:
    MAX_MESSAGE_LENGTH = 2000
    name = "weixin"

    def __init__(self):
        self._account_id = "bot"
        self._token = "transport-token"
        self._token_store = _TokenStore()
        self._dedup = types.SimpleNamespace(is_duplicate=lambda _key: False)
        self.text_deliveries = []
        self.media_deliveries = []
        self.fail_media = False

    def format_message(self, content):
        return str(content or "")

    def _split_text(self, content):
        return [content]

    async def _send_text_chunk(self, *, chat_id, chunk, context_token, client_id):
        self.text_deliveries.append((chat_id, chunk, context_token, client_id))

    async def _send_file(self, chat_id, path, caption, force_file_attachment=False):
        if self.fail_media:
            raise RuntimeError("media transport failed")
        self.media_deliveries.append((chat_id, path, caption, force_file_attachment))
        return f"media-{len(self.media_deliveries)}"

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        await self._send_text_chunk(
            chat_id=chat_id,
            chunk=self.format_message(content),
            context_token=self._token_store.get(self._account_id, chat_id),
            client_id=f"text-{len(self.text_deliveries) + 1}",
        )
        return types.SimpleNamespace(success=True, message_id="text")

    async def _process_message(self, message):
        return message

    def _is_group_allowed(self, _chat):
        return True

    def _is_dm_intake_allowed(self, _user):
        return True


class MediaBubbleCounterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"HERMES_HOME": self.temp.name})
        self.env.start()
        self.adapter = _Adapter()
        self.assertTrue(patch_adapter(self.adapter))

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def _send_text(self, value="text"):
        return asyncio.run(self.adapter._send_text_chunk(
            chat_id="peer", chunk=value, context_token="context-1",
            client_id=f"client-{len(self.adapter.text_deliveries) + 1}",
        ))

    def test_acknowledged_media_consumes_counter_without_footer(self):
        self._send_text("first")
        asyncio.run(self.adapter._send_file("peer", "/tmp/image.png", ""))
        self._send_text("after media")
        self.assertIn("`1` `hermes`", self.adapter.text_deliveries[0][1])
        self.assertIn("`3` `hermes`", self.adapter.text_deliveries[1][1])
        self.assertEqual(self.adapter.media_deliveries[0][2], "")

    def test_failed_media_does_not_consume_counter(self):
        self.adapter.fail_media = True
        with self.assertRaisesRegex(RuntimeError, "media transport failed"):
            asyncio.run(self.adapter._send_file("peer", "/tmp/image.png", ""))
        self.adapter.fail_media = False
        self._send_text("after failure")
        self.assertIn("`1` `hermes`", self.adapter.text_deliveries[0][1])

    def test_each_physical_media_item_consumes_one_counter(self):
        asyncio.run(self.adapter._send_file("peer", "/tmp/a.png", ""))
        asyncio.run(self.adapter._send_file("peer", "/tmp/b.pdf", ""))
        self._send_text("after two files")
        self.assertIn("`3` `hermes`", self.adapter.text_deliveries[0][1])

    def test_caption_and_media_are_two_physical_bubbles(self):
        asyncio.run(self.adapter._send_file("peer", "/tmp/report.pdf", "caption"))
        self._send_text("after caption and file")
        self.assertIn("caption", self.adapter.text_deliveries[0][1])
        self.assertIn("`1` `hermes`", self.adapter.text_deliveries[0][1])
        self.assertIn("`3` `hermes`", self.adapter.text_deliveries[1][1])
        self.assertEqual(self.adapter.media_deliveries[0][2], "")

    def test_media_counter_survives_adapter_restart(self):
        asyncio.run(self.adapter._send_file("peer", "/tmp/report.pdf", ""))
        restarted = _Adapter()
        self.assertTrue(patch_adapter(restarted))
        asyncio.run(restarted._send_text_chunk(
            chat_id="peer", chunk="after restart", context_token="context-1",
            client_id="after-restart",
        ))
        self.assertIn("`2` `hermes`", restarted.text_deliveries[0][1])


if __name__ == "__main__":
    unittest.main()
