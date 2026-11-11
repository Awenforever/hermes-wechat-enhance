#!/usr/bin/env python3
"""Context bar capture: persistence, precedence, isolation, observability.

Pinned failures:

* a persisted reading was discarded on load once older than the six-hour
  turn-metadata TTL, so the bar vanished after any idle period spanning a
  restart;
* pruning by that same TTL on every capture erased *other* chats' readings as
  soon as one chat finished a turn;
* the first turn after a restart captured nothing, because the turn result
  carries no context length and the pre-turn snapshot needs a warm cache;
* rejections were silent, and the warning leaked the raw peer id.
"""
import asyncio
import json
import logging
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
os.environ.pop('HERMES_WECHAT_FOOTER_CONTEXT_BAR', None)
os.environ.pop('HERMES_WECHAT_FOOTER_CONTEXT_PIE', None)
from hermes_wechat_enhance import v021_bubble_footer as M  # noqa: E402

CHAT = 'synthetic-peer'
OTHER = 'synthetic-peer-two'
STATE = Path(HOME) / 'plugin-data' / 'hermes-wechat-enhance' / 'context-fill.json'


class Captured(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def reset():
    M._CONTEXT_FILL.clear()
    M._CONTEXT_FILL_LOADED = False
    if hasattr(M, "_CONTEXT_FILL_WARNED"):
        M._CONTEXT_FILL_WARNED.clear()
    if hasattr(M, "_CONTEXT_FILL_STALE"):
        M._CONTEXT_FILL_STALE.clear()
    M._CONTEXT_FILL_SCOPE = None
    STATE.parent.mkdir(parents=True, exist_ok=True)


def bar_shape_ok(bar):
    return len(bar) == M.CONTEXT_BAR_CELLS


def case_persisted_reading_survives_age():
    reset()
    STATE.write_text(json.dumps({CHAT: [250_000, 1_000_000, time.time() - 30 * 24 * 3600]}),
                     encoding='utf-8')
    M._CONTEXT_FILL.clear()
    M._CONTEXT_FILL_LOADED = False
    bar = M.context_bar(CHAT)
    assert bar.strip(), 'a persisted reading must still render after a long idle'
    assert bar_shape_ok(bar), 'the bar keeps a constant width'
    assert bar.startswith('██ ') and not bar.startswith('███'), '25%% renders as two cells'


def case_one_chat_cannot_evict_another():
    reset()
    STATE.write_text(json.dumps({OTHER: [250_000, 1_000_000, time.time() - 30 * 24 * 3600]}),
                     encoding='utf-8')
    M._CONTEXT_FILL.clear()
    M._CONTEXT_FILL_LOADED = False
    assert M.context_bar(OTHER).strip()
    assert M._remember_context_fill(CHAT, 900_000, 1_000_000)
    assert M.context_bar(OTHER).strip(), 'capturing one chat must not drop another'
    persisted = json.loads(STATE.read_text(encoding='utf-8'))
    assert OTHER in persisted and CHAT in persisted, 'both readings survive on disk'


def case_result_reading_wins_over_the_engine():
    reset()
    comp = SimpleNamespace(last_prompt_tokens=222_222, last_real_prompt_tokens=222_222,
                           context_length=1_000_000)
    reading = M._resolve_context_reading({'last_prompt_tokens': 111_111}, comp)
    assert reading == (111_111, 1_000_000), 'the turn result is authoritative for the fill'
    reading = M._resolve_context_reading({}, comp)
    assert reading == (222_222, 1_000_000), 'the engine covers a result without usage'
    assert M._resolve_context_reading({}, SimpleNamespace(context_length=0)) is None


def case_first_turn_after_restart_captures():
    reset()
    STATE.write_text('{}', encoding='utf-8')
    M._CONTEXT_FILL.clear()
    M._CONTEXT_FILL_LOADED = False
    comp = SimpleNamespace(last_prompt_tokens=123_456, last_real_prompt_tokens=123_456,
                           context_length=1_000_000)
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


def case_rejection_is_reported_without_the_peer_id():
    reset()
    handler = Captured()
    M.logger.addHandler(handler)
    try:
        assert not M._remember_context_fill(CHAT, 0, 0), 'a zero reading is not a reading'
        M._warn_context_fill_once(CHAT, 'no usable reading')
        M._warn_context_fill_once(CHAT, 'no usable reading')
    finally:
        M.logger.removeHandler(handler)
    assert handler.messages, 'a rejected capture must be observable'
    assert len(handler.messages) == 1, 'each chat is reported once per process'
    message = handler.messages[0]
    assert 'peer=' in message and CHAT not in message, 'the peer id must not be logged raw'


def case_save_then_reload_round_trips():
    reset()
    assert M._remember_context_fill(CHAT, 640_000, 1_000_000)
    M._CONTEXT_FILL.clear()
    M._CONTEXT_FILL_LOADED = False
    bar = M.context_bar(CHAT)
    assert bar.strip() and bar_shape_ok(bar), 'a saved reading must come back'
    assert M._CONTEXT_FILL[CHAT][0] == 640_000


def case_no_capture_when_the_sentinel_says_unknown():
    reset()
    assert M._remember_context_fill(CHAT, 500_000, 1_000_000)
    comp = SimpleNamespace(last_prompt_tokens=-1, context_length=1_000_000)
    agent = SimpleNamespace(context_compressor=comp)
    runner = SimpleNamespace(_agent_cache={'k': (agent, 'sig')}, _agent_cache_lock=threading.Lock())
    source = SimpleNamespace(chat_id=CHAT, platform=SimpleNamespace(value='weixin'))
    M._refresh_context_fill_from_cached_agent(runner, source, 'k')
    assert not M.context_bar(CHAT).strip(), 'compression withdraws the reading (kept contract)'



def case_dict_result_supplies_the_limit_without_a_cache():
    """A provider fallback evicts the agent cache; the result is all we have."""
    reset()
    reading = M._resolve_context_reading(
        {"last_prompt_tokens": 111_111, "context_length": 1_000_000}, None)
    assert reading == (111_111, 1_000_000), "a dict result must be read with .get"
    assert M._remember_context_fill(CHAT, reading[0], reading[1])
    assert M.context_bar(CHAT).strip()


def case_state_file_is_written_atomically():
    reset()
    assert M._remember_context_fill(CHAT, 300_000, 1_000_000)
    leftovers = sorted(x.name for x in STATE.parent.iterdir() if x.name.endswith(".tmp"))
    assert not leftovers, "a successful save leaves no temporary file behind"
    parsed = json.loads(STATE.read_text(encoding="utf-8"))
    assert str(CHAT) in parsed, "the file is valid JSON after the replace"
    mode = oct(STATE.stat().st_mode & 0o777)
    assert mode == "0o600", "the state file is private, mode=%s" % mode


def case_one_corrupt_entry_keeps_the_others():
    reset()
    STATE.write_text(json.dumps({
        CHAT: [250_000, 1_000_000, time.time()],
        "broken-peer": "not-a-triple",
    }), encoding="utf-8")
    M._CONTEXT_FILL.clear()
    M._CONTEXT_FILL_LOADED = False
    assert M.context_bar(CHAT).strip(), "a corrupt sibling must not discard the good entry"
    assert M.context_bar("broken-peer") == ""


def case_corrupt_file_does_not_raise():
    reset()
    STATE.write_text("{not json", encoding="utf-8")
    M._CONTEXT_FILL.clear()
    M._CONTEXT_FILL_LOADED = False
    assert M.context_bar(CHAT) == ""


def case_near_zero_fill_is_not_an_empty_code_span():
    reset()
    assert M._remember_context_fill(CHAT, 10, 1_000_000)
    bar = M.context_bar(CHAT)
    assert bar and not bar.strip(), "a near-zero fill renders as blank cells"
    decorate = getattr(M, "_decorate_footer", None)
    if decorate is not None:
        footer = decorate("x", 3, "m", CHAT)
        bt = chr(96)
        assert (bt + bar + bt) not in footer, "an all-blank bar must not become a code span"


def case_first_capture_merges_with_the_persisted_file():
    """A process that captures before it ever renders must not clobber the file."""
    reset()
    STATE.write_text(json.dumps({OTHER: [111_000, 1_000_000, time.time()]}), encoding="utf-8")
    M._CONTEXT_FILL.clear()
    M._CONTEXT_FILL_LOADED = False          # deliberately not loaded
    assert M._remember_context_fill(CHAT, 222_000, 1_000_000)
    persisted = json.loads(STATE.read_text(encoding="utf-8"))
    assert OTHER in persisted, "the unloaded chat must survive the first save"
    assert M.context_bar(OTHER).strip()


def case_compression_turn_withdraws_the_bar():
    """The bubble that announces a compression must not repaint the old fill."""
    reset()
    assert M._remember_context_fill(CHAT, 900_000, 1_000_000)
    comp = SimpleNamespace(last_prompt_tokens=-1, last_real_prompt_tokens=900_000,
                           context_length=1_000_000)
    agent = SimpleNamespace(context_compressor=comp)
    runner = SimpleNamespace(_agent_cache={"k": (agent, "sig")},
                             _agent_cache_lock=threading.Lock())
    M._capture_turn_context_fill(
        runner, None, "k", {"last_prompt_tokens": -1}, CHAT)
    assert not M.context_bar(CHAT).strip(), "the pre-compression fill must be withdrawn"
    persisted = json.loads(STATE.read_text(encoding="utf-8"))
    assert str(CHAT) not in persisted



def _set_stale(chat_id, stale):
    fn = getattr(M, "_set_context_fill_stale", None)
    if fn is not None:
        fn(chat_id, stale)


def _is_stale(chat_id):
    fn = getattr(M, "context_bar_is_stale", None)
    return bool(fn(chat_id)) if fn is not None else False
def _runner_with_entry(tokens):
    """Runner whose persisted session entry reports a given reading."""
    entry = SimpleNamespace(last_prompt_tokens=tokens)
    store = SimpleNamespace(_entries={"k": entry}, _lock=threading.Lock())
    return SimpleNamespace(session_store=store, _agent_cache={}, _agent_cache_lock=threading.Lock())


def case_truncated_transcript_withdraws_the_stored_reading():
    """/compress sets the entry reading to 0; the bar described the old context."""
    reset()
    assert M._remember_context_fill(CHAT, 900_000, 1_000_000)
    assert M.context_bar(CHAT).strip()
    source = SimpleNamespace(chat_id=CHAT, platform=SimpleNamespace(value="weixin"))
    M._refresh_context_fill_from_cached_agent(_runner_with_entry(0), source, "k")
    assert not M.context_bar(CHAT).strip(), "a truncated transcript invalidates the reading"
    persisted = json.loads(STATE.read_text(encoding="utf-8"))
    assert str(CHAT) not in persisted, "the withdrawal must reach the disk"


def case_restart_keeps_the_reading_when_the_entry_still_has_one():
    """A restart restores a positive entry reading; that must not blank the bar."""
    reset()
    assert M._remember_context_fill(CHAT, 900_000, 1_000_000)
    source = SimpleNamespace(chat_id=CHAT, platform=SimpleNamespace(value="weixin"))
    M._refresh_context_fill_from_cached_agent(_runner_with_entry(900_000), source, "k")
    assert M.context_bar(CHAT).strip(), "a valid entry reading keeps the bar"


def case_unknown_entry_state_never_withdraws():
    """No store, no entry, or no lock: fail open and keep what we have."""
    reset()
    assert M._remember_context_fill(CHAT, 900_000, 1_000_000)
    source = SimpleNamespace(chat_id=CHAT, platform=SimpleNamespace(value="weixin"))
    for runner in (
        SimpleNamespace(),
        SimpleNamespace(session_store=SimpleNamespace()),
        SimpleNamespace(session_store=SimpleNamespace(_entries={}, _lock=threading.Lock())),
        SimpleNamespace(session_store=SimpleNamespace(_entries={"k": SimpleNamespace()}, _lock=None)),
    ):
        M._refresh_context_fill_from_cached_agent(runner, source, "k")
        assert M.context_bar(CHAT).strip(), "an unknowable state must not blank the bar"


def _cold_runner_without_reading():
    comp = SimpleNamespace(last_prompt_tokens=0, last_real_prompt_tokens=0,
                           context_length=1_000_000)
    agent = SimpleNamespace(context_compressor=comp)
    return SimpleNamespace(_agent_cache={"k": (agent, "sig")},
                           _agent_cache_lock=threading.Lock())


def case_a_turn_without_a_reading_marks_the_bar_stale():
    """The bubble after a failed capture must not present an old number as current."""
    reset()
    assert M._remember_context_fill(CHAT, 900_000, 1_000_000)
    _set_stale(CHAT, False)
    footer = M._decorate_footer("body", 7, "synthetic-model", CHAT)
    assert "~" not in footer, "a fresh reading carries no marker"
    M._capture_turn_context_fill(_cold_runner_without_reading(), None, "k", {}, CHAT)
    assert _is_stale(CHAT), "a turn with no reading marks the bar stale"
    footer = M._decorate_footer("body", 8, "synthetic-model", CHAT)
    assert "~" + M.context_bar(CHAT) in footer, "the leftover reading is marked"


def case_a_successful_capture_clears_the_marker():
    reset()
    assert M._remember_context_fill(CHAT, 900_000, 1_000_000)
    _set_stale(CHAT, True)
    comp = SimpleNamespace(last_prompt_tokens=400_000, last_real_prompt_tokens=400_000,
                           context_length=1_000_000)
    agent = SimpleNamespace(context_compressor=comp)
    runner = SimpleNamespace(_agent_cache={"k": (agent, "sig")},
                             _agent_cache_lock=threading.Lock())
    M._capture_turn_context_fill(runner, None, "k", {}, CHAT)
    assert not _is_stale(CHAT), "a fresh reading clears the marker"
    assert M._CONTEXT_FILL[CHAT][0] == 400_000


def case_withdrawing_the_reading_also_clears_the_marker():
    reset()
    assert M._remember_context_fill(CHAT, 900_000, 1_000_000)
    _set_stale(CHAT, True)
    assert M._forget_context_fill(CHAT)
    assert not _is_stale(CHAT), "nothing drawn means nothing to mark"


def case_an_idle_chat_keeps_its_reading_unmarked():
    """Age is not staleness: no turn ran, so the number is still the truth."""
    reset()
    STATE.write_text(json.dumps({CHAT: [900_000, 1_000_000, time.time() - 30 * 24 * 3600]}),
                     encoding="utf-8")
    M._CONTEXT_FILL.clear()
    M._CONTEXT_FILL_LOADED = False
    _set_stale(CHAT, False)
    assert M.context_bar(CHAT).strip()
    assert not _is_stale(CHAT), "an old but unturned reading needs no marker"


# Tolerant on older trees: missing resolvers fall back to the environment, which
# is exactly the pre-fix behaviour this case is meant to catch.
_ORIGINAL_HOME_ROOT = getattr(M, "_hermes_home_root", None)
_ORIGINAL_HOME_SCOPE = getattr(M, "_hermes_home_scope", None)


def _use_profile(root, scope):
    M._hermes_home_root = lambda: Path(root)
    M._hermes_home_scope = lambda: scope


def _restore_profile():
    if _ORIGINAL_HOME_ROOT is not None:
        M._hermes_home_root = _ORIGINAL_HOME_ROOT
    if _ORIGINAL_HOME_SCOPE is not None:
        M._hermes_home_scope = _ORIGINAL_HOME_SCOPE
    if hasattr(M, "_CONTEXT_FILL_SCOPE"):
        M._CONTEXT_FILL_SCOPE = None


def case_two_profiles_keep_separate_state_files():
    """Hermes profiles are a ContextVar; each one owns its own reading."""
    reset()
    profile_a = Path(tempfile.mkdtemp(prefix="profile-a-"))
    profile_b = Path(tempfile.mkdtemp(prefix="profile-b-"))
    try:
        _use_profile(profile_a, "scope-a")
        assert M._remember_context_fill(CHAT, 111_000, 1_000_000)
        path_a = M._context_fill_path()
        assert path_a.exists(), "profile A writes its own file"

        _use_profile(profile_b, "scope-b")
        assert not M.context_bar(CHAT).strip(), "profile B must not see A reading"
        assert M._remember_context_fill(CHAT, 222_000, 1_000_000)
        path_b = M._context_fill_path()
        assert path_a != path_b, "the two profiles must not share a file"

        _use_profile(profile_a, "scope-a")
        assert M.context_bar(CHAT).strip(), "switching back reloads A"
        assert M._CONTEXT_FILL[CHAT][0] == 111_000
        assert json.loads(path_a.read_text(encoding="utf-8"))[str(CHAT)][0] == 111_000
        assert json.loads(path_b.read_text(encoding="utf-8"))[str(CHAT)][0] == 222_000
    finally:
        _restore_profile()


def case_default_profile_keeps_the_original_path():
    """No override configured: the file must stay where 3.5.0 wrote it."""
    reset()
    try:
        M._hermes_home_root = lambda: Path(HOME)
        M._hermes_home_scope = lambda: str(HOME)
        assert M._context_fill_path() == STATE, "the default layout is unchanged"
    finally:
        _restore_profile()

for case in (
    case_persisted_reading_survives_age,
    case_one_chat_cannot_evict_another,
    case_result_reading_wins_over_the_engine,
    case_first_turn_after_restart_captures,
    case_rejection_is_reported_without_the_peer_id,
    case_save_then_reload_round_trips,
    case_no_capture_when_the_sentinel_says_unknown,
    case_dict_result_supplies_the_limit_without_a_cache,
    case_state_file_is_written_atomically,
    case_one_corrupt_entry_keeps_the_others,
    case_corrupt_file_does_not_raise,
    case_near_zero_fill_is_not_an_empty_code_span,
    case_first_capture_merges_with_the_persisted_file,
    case_compression_turn_withdraws_the_bar,
    case_truncated_transcript_withdraws_the_stored_reading,
    case_restart_keeps_the_reading_when_the_entry_still_has_one,
    case_unknown_entry_state_never_withdraws,
    case_a_turn_without_a_reading_marks_the_bar_stale,
    case_a_successful_capture_clears_the_marker,
    case_withdrawing_the_reading_also_clears_the_marker,
    case_an_idle_chat_keeps_its_reading_unmarked,
    case_two_profiles_keep_separate_state_files,
    case_default_profile_keeps_the_original_path,
):
    case()

print('CONTEXT_FILL_RESTART_PERSISTENCE_OK cases=23')
