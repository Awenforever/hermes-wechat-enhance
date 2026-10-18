#!/usr/bin/env python3
"""I1.T1.2 /btw side-question model provenance on the outbound rail.

Red on 3.4.2: Core sends the model-authored /btw answer with reply-only
metadata, so the footer falls closed to hermes.  Green after the plugin binds
the resolved model to the side-question task scope.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hermes_wechat_enhance import v021_bubble_footer as v

CHAT = "peer@chat"


class FakeTurn:
    def _resolve_session_agent_runtime(self, **kwargs):
        return "deepseek-flash", {"api_key": "synthetic"}


class FakeSlash(FakeTurn):
    def __init__(self, sent, answer_module):
        self.sent = sent
        self.answer_module = answer_module

    async def _handle_btw_command(self, event):
        model, _rt = self._resolve_session_agent_runtime(source=None)
        sent = self.sent
        answer_module = self.answer_module

        async def _run():
            try:
                answer = answer_module.answer_side_question("q", [])
            except Exception:
                # Core turns a failed side question into a system error bubble.
                model_name, _completed = v._resolve_model(CHAT, "btw failed", {"reply_to": None})
                sent.append(model_name)
                return
            model_name, _completed = v._resolve_model(CHAT, answer, {"reply_to": None})
            sent.append(model_name)

        asyncio.create_task(_run())
        return "started"


async def main():
    sent = []
    answer_module = SimpleNamespace(answer_side_question=lambda q, h: "the answer")
    installed = v.patch_side_question_provenance(
        slash_cls=FakeSlash, turn_cls=FakeTurn, answer_module=answer_module
    )
    assert installed is True, "patch_side_question_provenance did not install"

    handler = FakeSlash(sent, answer_module)
    assert await handler._handle_btw_command(None) == "started"
    await asyncio.sleep(0.05)
    assert sent == ["deepseek-flash"], f"expected model footer, got {sent}"

    # Control: an unmarked send still fails closed to hermes.
    model_name, _completed = v._resolve_model(CHAT, "system text", {})
    assert model_name == "hermes", model_name

    # A failed side question must not borrow the model label.
    def _boom(q, h):
        raise RuntimeError("provider failed")

    answer_module2 = SimpleNamespace(answer_side_question=_boom)
    sent2 = []
    installed2 = v.patch_side_question_provenance(
        slash_cls=FakeSlash, turn_cls=FakeTurn, answer_module=answer_module2
    )
    assert installed2 is True
    handler2 = FakeSlash(sent2, answer_module2)
    assert await handler2._handle_btw_command(None) == "started"
    await asyncio.sleep(0.05)
    assert sent2 == ["hermes"], f"failed side question must fail closed to hermes, got {sent2}"

    print("BTW_RAIL_PROVENANCE_OK")


asyncio.run(main())
