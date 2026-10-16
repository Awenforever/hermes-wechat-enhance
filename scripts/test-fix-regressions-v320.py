"""Same-path regressions for the v3.2.0 round.

Covers three changes shipped together:
  1. Context-fill progress bar in the bubble footer (Block Elements, constant
     width, inline-code).
  2. FIFO drain anti-stranding: connectivity errors classify as transient, and
     ANY enqueue is guaranteed a bounded future drain attempt (probe).
  3. Blocking sqlite/JSONL I/O moved off the gateway event loop (asyncio.to_thread).

Run inside the gateway container with HERMES_WECHAT_ENHANCE_SOURCE_DIR set to the
plugin checkout.  Only the physical transport is faked; everything else is the
real plugin + real core modules.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
import threading

ROOT = os.environ.get("HERMES_WECHAT_ENHANCE_SOURCE_DIR") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
sys.path.insert(0, ROOT)

from hermes_wechat_enhance import v021_bubble_footer as M  # noqa: E402

PASS = 0
FAIL = 0


def check(label: str, condition: bool) -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ok   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}")


# Sandbox HERMES_HOME so persistence writes never touch the real profile.
_SANDBOX = os.path.join(os.environ.get("TMPDIR", "/tmp"), "hwe-context-fill-test")
os.makedirs(_SANDBOX, exist_ok=True)
os.environ["HERMES_HOME"] = _SANDBOX


def set_fill(chat: str, used: int, limit: int) -> None:
    M._CONTEXT_FILL.clear()
    M._remember_context_fill(chat, used, limit)


print("== 1. context bar mapping (constant 8-char width, no trailing cap) ==")
cases = [
    (5, 100, "▍       "),
    (6, 100, "▌       "),
    (25, 100, "██      "),
    (50, 100, "████    "),
    (75, 100, "██████  "),
    (100, 100, "████████"),
]
for used, limit, want in cases:
    set_fill("chatA", used, limit)
    got = M.context_bar("chatA")
    check(f"ratio {used}/{limit} -> {want!r}", got == want)
    check(f"ratio {used}/{limit} width==8", len(got) == M.CONTEXT_BAR_CELLS)
    check(f"ratio {used}/{limit} unused is blank not ░", "░" not in got)
    check(f"ratio {used}/{limit} no trailing cap glyph", not got.endswith("▏"))
set_fill("chatA", 0, 100)
check("zero used = no API reading -> unknown", M.context_bar("chatA") == "")
M._CONTEXT_FILL.clear()
M._CONTEXT_FILL_LOADED = True
check("unknown chat -> empty", M.context_bar("chatUnknown") == "")
os.environ["HERMES_WECHAT_FOOTER_CONTEXT_BAR"] = "0"
set_fill("chatA", 100, 100)
check("env disable -> empty", M.context_bar("chatA") == "")
os.environ.pop("HERMES_WECHAT_FOOTER_CONTEXT_BAR", None)
M._remember_context_fill("chatBad", 0, 0)
check("zero/zero ignored", M.context_bar("chatBad") == "")

print("== 1b. fill persists across a simulated restart ==")
set_fill("chatP", 50, 100)
check("persist file written", os.path.exists(M._context_fill_path()))
M._CONTEXT_FILL.clear()
M._CONTEXT_FILL_LOADED = False  # simulate fresh process / gateway restart
check("after restart bar restored from disk", M.context_bar("chatP") == "████    ")

print("== 2. footer decoration wraps bar in inline code ==")
set_fill("chatB", 100, 100)
decorated = M._decorate_footer("hello", 3, "deepseek-flash", "chatB")
check("footer keeps count+model spans", "`3` `deepseek-flash`" in decorated)
check("footer appends bar span", decorated.endswith("`████████`"))
check("footer separator preserved", "\n\n---\n\n" in decorated)
M._CONTEXT_FILL.clear()
M._CONTEXT_FILL_LOADED = True
decorated_none = M._decorate_footer("hello", 3, "deepseek-flash", "chatB")
check("no bar when unknown -> unchanged footer", decorated_none.endswith("`deepseek-flash`"))

print("== 3. connectivity errors classify as transient ==")
connect_err = "Cannot connect to host ilinkai.weixin.qq.com:443 ssl:default [None]"
check("connect error -> delay", M._transient_retry_delay(None, connect_err, 1) is not None)
rate_err = "iLink sendmessage rate limited; cooldown active for 30.0s"
check("rate-limit still transient", M._transient_retry_delay(None, rate_err, 1) is not None)
permanent = "permanent budget exhausted forbidden 403"
check("permanent still non-transient", M._transient_retry_delay(None, permanent, 1) is None)

print("== 3b. explicit cooldown honored, not stacked under exponential backoff ==")
short_cd = "iLink sendmessage rate limited; cooldown active for 0.01s"
d_short = M._transient_retry_delay(None, short_cd, 1)
check("0.01s cooldown resumes within 0.08s", d_short is not None and d_short <= 0.08)
check("0.01s cooldown >= its own remaining", d_short is not None and d_short >= 0.01)
d_long = M._transient_retry_delay(None, rate_err, 1)
check("30s cooldown resumes at ~30s, not backoff", d_long is not None and 30.0 <= d_long <= 30.5)
check("no-cooldown transient keeps exponential floor", M._transient_retry_delay(None, connect_err, 1) == 2.0)

print("== 4. drain guarantee probes even for unclassified errors ==")
check("probe delay for permanent at attempt 1", M._drain_delay(None, permanent, 1) == M.DRAIN_PROBE_DELAY_SECONDS)
check("probe delay within cap", M._drain_delay(None, permanent, M.MAX_DRAIN_PROBES) == M.DRAIN_PROBE_DELAY_SECONDS)
check("no probe beyond cap", M._drain_delay(None, permanent, M.MAX_DRAIN_PROBES + 1) is None)
check("transient preferred over probe", M._drain_delay(None, rate_err, 1) != M.DRAIN_PROBE_DELAY_SECONDS)

print("== 5. send-path I/O is offloaded off the event loop ==")
src = " ".join(inspect.getsource(M.patch_adapter).split())
for needle in (
    "asyncio.to_thread(queue.count",
    "asyncio.to_thread( queue.enqueue",
    "asyncio.to_thread( store.preview",
    "asyncio.to_thread( store.commit",
    "asyncio.to_thread(queue.peek",
    "asyncio.to_thread( queue.record_failure",
):
    check(f"offloaded: {needle[:44]}", needle in src)


async def _probe_thread() -> str:
    def _work() -> str:
        return threading.current_thread().name

    return await asyncio.to_thread(_work)


loop_thread = threading.current_thread().name
worker_thread = asyncio.run(_probe_thread())
check("to_thread runs off loop thread", worker_thread != loop_thread)

print("== 6. queue is in-place: failures never duplicate; only success dequeues ==")
from pathlib import Path  # noqa: E402

_qpath = Path(os.path.join(_SANDBOX, "pending-inplace-test.sqlite3"))
if _qpath.exists():
    _qpath.unlink()
Q = M.PendingBubbleStore(_qpath)
# A first physical-send failure enqueues the bubble exactly once.
Q.enqueue("acct", "peer", "client-1", "hello", "deepseek-flash", "boom")
check("one enqueue -> depth 1", Q.count("acct", "peer") == 1)
# The SAME client_id re-enqueued (upstream retry / re-entry) must not duplicate:
# this is the accumulation bug the old retry cap was papering over.
Q.enqueue("acct", "peer", "client-1", "hello", "deepseek-flash", "boom")
check("same client_id re-enqueue idempotent (INSERT OR IGNORE + UNIQUE)", Q.count("acct", "peer") == 1)
# peek never pops.
_item = Q.peek("acct", "peer")
check("peek returns the queued item", _item is not None and _item["client_id"] == "client-1")
check("peek does not dequeue", Q.count("acct", "peer") == 1)
# Repeated drain failures annotate in place; depth never grows.
for _ in range(5):
    _got = Q.peek("acct", "peer")
    Q.record_failure(int(_got["seq"]), "cooldown active for 0.01s")
check("5 failed drains -> still depth 1 (failure stays in place, no re-enqueue)", Q.count("acct", "peer") == 1)
_after = Q.peek("acct", "peer")
check("failures bump attempts in place", int(_after["attempts"]) == 5)
# Only a successful send dequeues.
Q.remove(int(_after["seq"]))
check("success (remove) -> depth 0", Q.count("acct", "peer") == 0)

print("== 7. drain worker is drain-until-empty and cooldown-preemptive ==")
check("worker loops until the queue is empty", "while True:" in src)
check("no bounded 'awaiting fresh inbound token' give-up", "awaiting fresh inbound token" not in src)
check("backoff capped at DRAIN_BACKOFF_CEILING_SECONDS", "DRAIN_BACKOFF_CEILING_SECONDS" in src)
check("a sooner retry preempts a longer-sleeping worker", "current.cancel()" in src)
check("worker tracks a wake deadline for preemption", "retry_deadlines[key]" in src)

print("== 8. v3.3.4 turn-start live context-fill read (kills /compress lag) ==")


class _Comp:
    def __init__(self, used, limit):
        self.last_prompt_tokens = used
        self.context_length = limit


class _Agent:
    def __init__(self, used, limit):
        self.context_compressor = _Comp(used, limit)


class _Src:
    def __init__(self, chat, skey, plat="weixin"):
        self.chat_id = chat
        self.session_key = skey
        self.platform = plat


class _Runner:
    def __init__(self, cache, lock=True):
        self._agent_cache = cache
        self._agent_cache_lock = threading.Lock() if lock else None


CHAT = "compress-chat"
SKEY = "weixin:compress-chat"

# Stale pre-compress snapshot (the bug): footer would render ~full.
set_fill(CHAT, 900_000, 1_000_000)
runner = _Runner({SKEY: (_Agent(77_809, 1_000_000), "sig")})
M._refresh_context_fill_from_cached_agent(runner, _Src(CHAT, SKEY))
check("turn-start read overrides stale pre-compress snapshot",
      M._CONTEXT_FILL[CHAT][0] == 77_809 and M._CONTEXT_FILL[CHAT][1] == 1_000_000)
check("post-compress ratio is low, not full",
      M._CONTEXT_FILL[CHAT][0] / M._CONTEXT_FILL[CHAT][1] < 0.1)

# -1 sentinel right after /compress (awaiting real usage) must NOT be written.
set_fill(CHAT, 55_000, 1_000_000)
prev = M._CONTEXT_FILL[CHAT][0]
runner_neg = _Runner({SKEY: (_Agent(-1, 1_000_000), "sig")})
M._refresh_context_fill_from_cached_agent(runner_neg, _Src(CHAT, SKEY))
check("-1 sentinel invalidates obsolete snapshot", CHAT not in M._CONTEXT_FILL)
check("invalidated snapshot not resurrected from persistence", M.context_bar(CHAT) == "")
set_fill(CHAT, prev, 1_000_000)

# Zero / missing compressor / missing cache / missing session_key: no crash, no change.
runner_zero = _Runner({SKEY: (_Agent(0, 1_000_000), "sig")})
M._refresh_context_fill_from_cached_agent(runner_zero, _Src(CHAT, SKEY))
check("0 usage ignored", M._CONTEXT_FILL[CHAT][0] == prev)


class _NoComp:
    pass


runner_nocomp = _Runner({SKEY: (_NoComp(), "sig")})
M._refresh_context_fill_from_cached_agent(runner_nocomp, _Src(CHAT, SKEY))
check("agent without compressor ignored", M._CONTEXT_FILL[CHAT][0] == prev)


class _BareRunner:
    pass


M._refresh_context_fill_from_cached_agent(_BareRunner(), _Src(CHAT, SKEY))
check("runner without _agent_cache degrades silently", M._CONTEXT_FILL[CHAT][0] == prev)

M._refresh_context_fill_from_cached_agent(runner, _Src(CHAT, ""))
check("source without session_key ignored", M._CONTEXT_FILL[CHAT][0] == prev)

# Non-tuple cache entry (layout drift) must not raise and must not corrupt.
runner_flat = _Runner({SKEY: _Agent(12_345, 1_000_000)})
M._refresh_context_fill_from_cached_agent(runner_flat, _Src(CHAT, SKEY))
check("non-tuple cache entry handled (uses entry itself)", M._CONTEXT_FILL[CHAT][0] == 12_345)

src_pg = " ".join(inspect.getsource(M.patch_gateway_runner).split())
check("turn-start refresh invoked in wrapped_run",
      "_refresh_context_fill_from_cached_agent(runner, source, call.get(\"session_key\"))" in src_pg)
check("turn-start refresh precedes original_run",
      src_pg.index("_refresh_context_fill_from_cached_agent(runner, source, call.get(\"session_key\"))")
      < src_pg.index("result = await original_run(*args, **kwargs)"))
check("end-of-turn authoritative remember retained",
      src_pg.count("_remember_context_fill(") == 1
      and "result.get(\"last_prompt_tokens\")" in src_pg)

print(f"\nRESULT pass={PASS} fail={FAIL}")
sys.exit(1 if FAIL else 0)
