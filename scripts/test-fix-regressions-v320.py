"""Same-path regressions for the v3.2.0 round.

Covers three changes shipped together:
  1. Context-fill pie in the bubble footer (single monochrome glyph, inline-code).
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


def set_fill(chat: str, used: int, limit: int) -> None:
    M._CONTEXT_FILL.clear()
    M._remember_context_fill(chat, used, limit)


print("== 1. context pie mapping ==")
cases = [(5, 100, "○"), (25, 100, "◔"), (50, 100, "◑"), (75, 100, "◕"), (100, 100, "●")]
for used, limit, glyph in cases:
    set_fill("chatA", used, limit)
    check(f"ratio {used}/{limit} -> {glyph}", M.context_pie("chatA") == glyph)
set_fill("chatA", 0, 100)
check("zero used = no API reading -> unknown", M.context_pie("chatA") == "")
M._CONTEXT_FILL.clear()
check("unknown chat -> empty", M.context_pie("chatUnknown") == "")
os.environ["HERMES_WECHAT_FOOTER_CONTEXT_PIE"] = "0"
set_fill("chatA", 100, 100)
check("env disable -> empty", M.context_pie("chatA") == "")
os.environ.pop("HERMES_WECHAT_FOOTER_CONTEXT_PIE", None)
M._remember_context_fill("chatBad", 0, 0)
check("zero/zero ignored", M.context_pie("chatBad") == "")

print("== 2. footer decoration wraps pie in inline code ==")
set_fill("chatB", 100, 100)
decorated = M._decorate_footer("hello", 3, "deepseek-flash", "chatB")
check("footer keeps count+model spans", "`3` `deepseek-flash`" in decorated)
check("footer appends pie span", decorated.endswith("`●`"))
check("footer separator preserved", "\n\n---\n\n" in decorated)
M._CONTEXT_FILL.clear()
decorated_none = M._decorate_footer("hello", 3, "deepseek-flash", "chatB")
check("no pie when unknown -> unchanged footer", decorated_none.endswith("`deepseek-flash`"))

print("== 3. connectivity errors classify as transient ==")
connect_err = "Cannot connect to host ilinkai.weixin.qq.com:443 ssl:default [None]"
check("connect error -> delay", M._transient_retry_delay(None, connect_err, 1) is not None)
rate_err = "iLink sendmessage rate limited; cooldown active for 30.0s"
check("rate-limit still transient", M._transient_retry_delay(None, rate_err, 1) is not None)
permanent = "permanent budget exhausted forbidden 403"
check("permanent still non-transient", M._transient_retry_delay(None, permanent, 1) is None)

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

print(f"\nRESULT pass={PASS} fail={FAIL}")
sys.exit(1 if FAIL else 0)
