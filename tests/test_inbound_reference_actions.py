import asyncio
import sys
import types
import unittest
from unittest.mock import AsyncMock

from hermes_wechat_enhance.v021_bubble_footer import (
    _emit_inbound_action,
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
                "text_item": {"text": "回复\n原样正文"},
                "ref_msg": {"message_item": {"type": 1, "msg_id": "quoted-7", "text_item": {"text": "邮件推送"}}},
            }],
        }

    def test_current_and_quoted_text_are_separate(self):
        normalized = normalize_weixin_inbound_reference(self.message())
        self.assertEqual(normalized["text"], "回复\n原样正文")
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
        self.assertEqual(context["message"], "回复\n原样正文")
        self.assertEqual(context["reference"]["text"], "邮件推送")
        self.assertIs(context["authorized"], True)


if __name__ == "__main__":
    unittest.main()
