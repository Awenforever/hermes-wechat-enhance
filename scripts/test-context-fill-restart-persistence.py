#!/usr/bin/env python3
"""The context bar must survive a restart and a cold agent cache.

Two real failures are pinned here:

* a persisted reading was discarded on load once it was older than the TTL, so
  the bar vanished for any chat that had been idle before the restart — the
  opposite of what persisting the value is for;
* the first turn after every gateway restart captured nothing: the pre-turn
  snapshot needs a warm agent cache, and the turn result carried no usage.
"""
import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HOME = tempfile.mkdtemp(prefix='enhance-ctx-persist-')
os.environ['HERMES_HOME'] = HOME
from hermes_wechat_enhance import v021_bubble_footer as M  # noqa: E402

CHAT = 'synthetic-peer'
STATE = Path(HOME) / 'plugin-data' / 'hermes-wechat-enhance' / 'context-fill.json'


def reset():
    M._CONTEXT_FILL.clear()
    M._CONTEXT_FILL_LOADED = False


def case_persisted_reading_survives_age():
    STATE.parent.mkdir(parents=True, exist_ok=True)
    ancient = time.time() - 30 * 24 * 3600
    STATE.write_text(json.dumps({CHAT: [250_000, 1_000_000, ancient]}), encoding='utf-8')
    reset()
    bar = M.context_bar(CHAT)
    assert bar.strip(), 'a persisted reading must still render after a long idle'
    assert M._CONTEXT_FILL[CHAT][0] == 250_000


def case_first_turn_after_restart_captures():
    STATE.write_text('{}', encoding='utf-8')
    reset()
    comp = SimpleNamespace(last_prompt_tokens=123_456, context_length=1_000_000)
    agent = SimpleNamespace(context_compressor=comp)

    class Runner:
        def __init__(self):
            self._agent_cache = {}          # cold: exactly what a restart leaves
            self._agent_cache_lock = threading.Lock()

        def _resolve_session_agent_runtime(self, **kwargs):
            return ('synthetic-model',)

        async def _run_agent_inner(self, message, context_prompt, history, source,
                                   session_id, session_key=None):
            self._agent_cache[session_key] = (agent, 'signature')  # the turn warms it
            return {}                                              # and reports no usage

    runner = Runner()
    assert M.patch_gateway_runner(runner)
    source = SimpleNamespace(chat_id=CHAT, platform=SimpleNamespace(value='weixin'))
    asyncio.run(runner._run_agent_inner('synthetic', '', [], source, 's', 'cold-key'))
    assert M._CONTEXT_FILL.get(CHAT), 'the first turn after a restart must capture usage'
    assert M._CONTEXT_FILL[CHAT][0] == 123_456
    assert M.context_bar(CHAT).strip()


case_persisted_reading_survives_age()
case_first_turn_after_restart_captures()
print('CONTEXT_FILL_RESTART_PERSISTENCE_OK')
