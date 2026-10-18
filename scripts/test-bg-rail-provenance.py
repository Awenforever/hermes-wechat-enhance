#!/usr/bin/env python3
"""I1.T1.3 /bg background-task model provenance.

Red on 3.4.2: the background task sends the agent's final text with reply-only
metadata.  Green after the plugin attributes the completed run's model and
fails closed when the run failed or produced no final response.
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


class FakeAgent:
    def __init__(self, result):
        self.model = "deepseek-flash"
        self._result = result

    def run_conversation(self, **kwargs):
        return dict(self._result)


class FakeBg(FakeTurn):
    def __init__(self, sent, result):
        self.sent = sent
        self.result = result

    async def _run_background_task_inner(self, *args, **kwargs):
        _model, _rt = self._resolve_session_agent_runtime(source=None)
        agent = FakeAgent(self.result)
        result = agent.run_conversation(user_message="x")
        self.sent.append(v._resolve_model(CHAT, result.get("final_response", ""), {"reply_to": None})[0])


async def main():
    sent = []
    installed = v.patch_background_task_provenance(turn_cls=FakeBg, agent_cls=FakeAgent)
    assert installed is True, "patch_background_task_provenance did not install"

    ok = FakeBg(sent, {"final_response": "background answer", "failed": False})
    await ok._run_background_task_inner()
    assert sent == ["deepseek-flash"], f"expected model footer, got {sent}"

    sent2 = []
    failed = FakeBg(sent2, {"final_response": "Error: boom", "failed": True})
    await failed._run_background_task_inner()
    assert sent2 == ["hermes"], f"failed background run must fail closed, got {sent2}"

    sent3 = []
    empty = FakeBg(sent3, {"final_response": "", "failed": False})
    await empty._run_background_task_inner()
    assert sent3 == ["hermes"], f"empty background run must fail closed, got {sent3}"

    print("BG_RAIL_PROVENANCE_OK")


asyncio.run(main())
