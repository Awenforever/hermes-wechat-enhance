"""``message:inbound`` may rewrite the user text and still let the turn route."""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _install_gateway_stubs():
    """Run off-gateway: the plugin imports these lazily, so stub them."""
    if "gateway" in sys.modules:
        return sys.modules["gateway.run"]
    gateway = types.ModuleType("gateway")
    gateway.__path__ = []
    platforms = types.ModuleType("gateway.platforms")
    platforms.__path__ = []
    weixin = types.ModuleType("gateway.platforms.weixin")
    weixin._guess_chat_type = lambda message, account: (
        "dm",
        str(message.get("from_user_id") or ""),
    )
    run_mod = types.ModuleType("gateway.run")
    run_mod._gateway_runner_ref = lambda: None
    sys.modules.setdefault("gateway", gateway)
    sys.modules.setdefault("gateway.platforms", platforms)
    sys.modules.setdefault("gateway.platforms.weixin", weixin)
    sys.modules.setdefault("gateway.run", run_mod)
    return run_mod


RUN_MOD = _install_gateway_stubs()

PASS = 0
FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print("  ok   " + label)
    else:
        FAIL += 1
        print("  FAIL " + label + ((" :: " + detail) if detail else ""))


class FakeHooks:
    def __init__(self, results):
        self.results = results
        self.contexts = []

    async def emit_collect(self, event, context):
        self.contexts.append(context)
        return list(self.results)


class FakeAdapter:
    name = "weixin"

    def __init__(self):
        self._account_id = "account"
        self.sent = []

    def _is_dm_intake_allowed(self, _sender):
        return True

    def _is_group_allowed(self, _chat):
        return False

    async def send(self, chat_id, content, metadata=None):
        self.sent.append((chat_id, content, metadata))


def message_with_text(value):
    return {
        "message_id": "m-1",
        "from_user_id": "peer",
        "context_token": "tok",
        "item_list": [{"text": value}],
    }


async def run(M, results, value):
    hooks = FakeHooks(results)
    adapter = FakeAdapter()
    message = message_with_text(value)
    normalized = {"text": value, "reference": {"present": False}}
    previous = RUN_MOD._gateway_runner_ref
    RUN_MOD._gateway_runner_ref = lambda: types.SimpleNamespace(hooks=hooks)
    try:
        claimed = await M._emit_inbound_action(adapter, message, normalized)
    finally:
        RUN_MOD._gateway_runner_ref = previous
    return claimed, message, adapter, hooks


async def main():
    from hermes_wechat_enhance import v021_bubble_footer as M

    print("== A. rewrite replaces the text and keeps routing ==")
    claimed, message, adapter, _ = await run(
        M,
        [{"decision": "rewrite", "message": "QUESTION\n\nEMAIL BODY", "source": "hermes-email-watchdog"}],
        "@原文\n这封邮件要我做什么？",
    )
    check("not claimed by the hook", claimed is False)
    check("text rewritten", message["item_list"][0]["text"].startswith("QUESTION"))
    check("hook sent nothing", adapter.sent == [])

    print("== B. handled still sends and claims ==")
    claimed, message, adapter, _ = await run(
        M, [{"decision": "handled", "message": "卡片", "source": "hermes-email-watchdog"}], "@原文"
    )
    check("claimed", claimed is True)
    check("reply sent once", len(adapter.sent) == 1)
    check("text untouched", message["item_list"][0]["text"] == "@原文")

    print("== C. blank rewrite is ignored ==")
    claimed, message, _adapter, _ = await run(M, [{"decision": "rewrite", "message": "   "}], "@原文\n问题")
    check("not claimed", claimed is False)
    check("text untouched", message["item_list"][0]["text"] == "@原文\n问题")

    print("== D. unknown decision falls through ==")
    claimed, _message, adapter, _ = await run(M, [{"decision": "ignore"}], "@原文")
    check("not claimed", claimed is False)
    check("nothing sent", adapter.sent == [])

    print("== E. rewrite then handled in one event ==")
    claimed, message, _adapter, _ = await run(
        M,
        [
            {"decision": "rewrite", "message": "WITH CONTEXT"},
            {"decision": "handled", "message": "card"},
        ],
        "@原文\n问题",
    )
    check("handled still claimed", claimed is True)
    check("rewrite kept", message["item_list"][0]["text"] == "WITH CONTEXT")

    print()
    print("RESULT pass=%d fail=%d" % (PASS, FAIL))
    if FAIL:
        raise SystemExit(1)
    print("INBOUND_REWRITE_OK")


if __name__ == "__main__":
    asyncio.run(main())
