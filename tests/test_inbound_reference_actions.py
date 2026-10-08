import asyncio
import sys
import types
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from hermes_wechat_enhance.v021_bubble_footer import (
    _emit_inbound_action,
    _install_outbound_quote_capture,
    OutboundQuoteStore,
    normalize_weixin_inbound_reference,
)


class InboundReferenceTests(unittest.TestCase):
    def setUp(self):
        gateway = types.ModuleType("gateway")
        platforms = types.ModuleType("gateway.platforms")
        weixin = types.ModuleType("gateway.platforms.weixin")
        run = types.ModuleType("gateway.run")
        weixin._extract_text = lambda items: (items[0].get("text_item") or {}).get("text", "")
        weixin._guess_chat_type = lambda message, account: ("dm", str(message["from_user_id"]))
        self.hooks = types.SimpleNamespace(emit_collect=AsyncMock(return_value=[]))
        run._gateway_runner_ref = lambda: types.SimpleNamespace(hooks=self.hooks)
        self.saved = {name: sys.modules.get(name) for name in ("gateway", "gateway.platforms", "gateway.platforms.weixin", "gateway.run")}
        sys.modules.update({"gateway": gateway, "gateway.platforms": platforms, "gateway.platforms.weixin": weixin, "gateway.run": run})

    def tearDown(self):
        for name, value in self.saved.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value

    def message(self):
        return {
            "message_id": 22,
            "from_user_id": "paired-user",
            "item_list": [{
                "type": 1,
                "text_item": {"text": "@回复\n原样正文"},
                "ref_msg": {"message_item": {"type": 1, "msg_id": "quoted-7", "text_item": {"text": "邮件推送"}}},
            }],
        }

    def test_current_and_quoted_text_are_separate(self):
        normalized = normalize_weixin_inbound_reference(self.message())
        self.assertEqual(normalized["text"], "@回复\n原样正文")
        self.assertEqual(normalized["reference"]["text"], "邮件推送")
        self.assertEqual(normalized["reference"]["message_id"], "quoted-7")

    def test_optional_hook_can_handle_without_plugin_dependency(self):
        self.hooks.emit_collect.return_value = [{"decision": "handled", "message": "草稿", "source": "test"}]
        adapter = types.SimpleNamespace(
            _account_id="bot", _is_dm_intake_allowed=lambda user: True,
            _is_group_allowed=lambda chat: False, send=AsyncMock(return_value=types.SimpleNamespace(success=True)),
        )
        handled = asyncio.run(_emit_inbound_action(adapter, self.message(), normalize_weixin_inbound_reference(self.message())))
        self.assertTrue(handled)
        context = self.hooks.emit_collect.await_args.args[1]
        self.assertEqual(context["message"], "@回复\n原样正文")
        self.assertEqual(context["reference"]["text"], "邮件推送")
        self.assertIs(context["authorized"], True)

    def test_new_ilink_title_only_reference_is_not_lost(self):
        message = self.message()
        message["item_list"][0]["ref_msg"] = {
            "svr_id": "server-message-9",
            "title": "### 📬 新邮件｜USTC · 2026-10-08 10:24…",
        }
        normalized = normalize_weixin_inbound_reference(message)
        self.assertEqual(normalized["text"], "@回复\n原样正文")
        self.assertTrue(normalized["reference"]["present"])
        self.assertEqual(normalized["reference"]["message_id"], "server-message-9")
        self.assertIn("新邮件｜USTC", normalized["reference"]["text"])

    def test_title_only_reference_reaches_optional_hook(self):
        message = self.message()
        message["item_list"][0]["ref_msg"] = {
            "svr_id": "server-message-10",
            "title": "### 📬 新邮件｜USTC · 2026-10-08 10:24…",
        }
        self.hooks.emit_collect.return_value = [{"decision": "handled", "message": "草稿", "source": "test"}]
        adapter = types.SimpleNamespace(
            _account_id="bot", _is_dm_intake_allowed=lambda user: True,
            _is_group_allowed=lambda chat: False, send=AsyncMock(return_value=types.SimpleNamespace(success=True)),
        )
        normalized = normalize_weixin_inbound_reference(message)
        handled = asyncio.run(_emit_inbound_action(adapter, message, normalized))
        self.assertTrue(handled)
        context = self.hooks.emit_collect.await_args.args[1]
        self.assertEqual(context["reference"]["message_id"], "server-message-10")

    def test_id_only_reference_is_resolved_from_restart_safe_cache(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "quotes.sqlite3"
            OutboundQuoteStore(path).put("bot", "paired-user", "server-11", "邮件推送正文")
            store = OutboundQuoteStore(path)
            message = self.message()
            message["item_list"][0]["ref_msg"] = {"svr_id": "server-11"}
            normalized = normalize_weixin_inbound_reference(
                message, quote_store=store, account_id="bot", chat_id="paired-user"
            )
            self.assertEqual(normalized["reference"]["text"], "邮件推送正文")
            self.assertTrue(normalized["reference"]["cache_hit"])

    def test_leading_at_command_without_quote_is_offered_to_plugins(self):
        message = self.message()
        message["item_list"][0].pop("ref_msg")
        message["item_list"][0]["text_item"]["text"] = "@回复\n正文"
        self.hooks.emit_collect.return_value = [{"decision": "handled", "message": "请重新引用", "source": "test"}]
        adapter = types.SimpleNamespace(
            _account_id="bot", _is_dm_intake_allowed=lambda user: True,
            _is_group_allowed=lambda chat: False, send=AsyncMock(return_value=types.SimpleNamespace(success=True)),
        )
        normalized = normalize_weixin_inbound_reference(message)
        self.assertTrue(asyncio.run(_emit_inbound_action(adapter, message, normalized)))
        self.assertFalse(normalized["reference"]["present"])

    def test_transport_response_message_id_is_cached(self):
        weixin = sys.modules["gateway.platforms.weixin"]

        async def low_level(_session=None, *, token, to, text, **_kwargs):
            return {"ret": 0, "message_id": "18446744073709551615"}

        weixin._send_message = low_level
        with tempfile.TemporaryDirectory() as td:
            store = OutboundQuoteStore(Path(td) / "quotes.sqlite3")
            adapter = types.SimpleNamespace(_token="secret", _account_id="bot")
            self.assertTrue(_install_outbound_quote_capture(adapter, store))
            result = asyncio.run(weixin._send_message(token="secret", to="peer", text="完整气泡"))
            self.assertEqual(result["message_id"], "18446744073709551615")
            self.assertEqual(store.get("bot", "peer", "18446744073709551615"), "完整气泡")


if __name__ == "__main__":
    unittest.main()
