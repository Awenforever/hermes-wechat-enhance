#!/usr/bin/env python3
"""Actual Core SessionSource/signature, no model or physical transport call."""
import asyncio
import inspect
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gateway.session import SessionSource
from gateway.config import Platform
from gateway.run import GatewayRunner
from hermes_wechat_enhance import v021_bubble_footer as M


async def main():
    source = SessionSource(platform=Platform.WEIXIN, chat_id='synthetic-peer')
    assert not hasattr(source, 'session_key')
    real = inspect.signature(GatewayRunner._run_agent_inner)
    assert 'session_key' in real.parameters and 'source' in real.parameters
    key = 'explicit-isolated-session-key'
    comp = SimpleNamespace(last_prompt_tokens=77_809, context_length=1_000_000)
    agent = SimpleNamespace(context_compressor=comp)
    observed = []

    class Runner:
        def __init__(self):
            self._agent_cache = {key: (agent, 'signature')}
            self._agent_cache_lock = threading.Lock()

        def _resolve_session_agent_runtime(self, **kwargs):
            return ('synthetic-model',)

        async def _run_agent_inner(self, message, context_prompt, history, source,
                                   session_id, session_key=None):
            observed.append(M.context_bar(source.chat_id))
            return {}

    runner = Runner()
    assert M.patch_gateway_runner(runner)
    for positional in (False, True):
        M._remember_context_fill(source.chat_id, 900_000, 1_000_000)
        if positional:
            await runner._run_agent_inner('synthetic', '', [], source, 's', key)
        else:
            await runner._run_agent_inner(message='synthetic', context_prompt='', history=[],
                                          source=source, session_id='s', session_key=key)
        assert M._CONTEXT_FILL[source.chat_id][0] == 77_809
        assert observed[-1] == M.context_bar(source.chat_id)
    comp.last_prompt_tokens = -1
    await runner._run_agent_inner('synthetic', '', [], source, 's', key)
    assert observed[-1] == '' and M.context_bar(source.chat_id) == ''
    M._CONTEXT_FILL.clear()
    M._CONTEXT_FILL_LOADED = False
    assert M.context_bar(source.chat_id) == ''


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='enhance-fill-boundary-') as raw:
        os.environ['HERMES_HOME'] = raw
        asyncio.run(main())
    print('CONTEXT_FILL_CALL_BOUNDARY_OK')
