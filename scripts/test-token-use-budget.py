#!/usr/bin/env python3
"""Context Token use budget: ten sends per token, the eleventh is held.

iLink accepts ten sends per Weixin Context Token. The footnote counter already
tracked usage but nothing enforced the budget, so a rate-limited retry walked
past the boundary and delivered an eleventh numbered bubble in production.

The physical transport is faked; queue, counter store and guard are the real
plugin code.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location(
    "budget_fixtures", ROOT / "scripts/test-v021-bubble-footer.py"
)
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
from hermes_wechat_enhance import v021_bubble_footer as M  # noqa: E402

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


def footer_number(chunk):
    found = re.findall(r"`(\d+)`", chunk)
    return found[-1] if found else ""


def sent_numbers(adapter):
    return [footer_number(chunk) for (_chat, chunk, _token, _client) in adapter.sent]


async def wait_until(predicate, timeout: float = 5.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.005)
    return bool(predicate())


async def cancel_tasks(adapter) -> None:
    tasks = list(adapter._hermes_wechat_v021_retry_tasks.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def main(raw: str) -> None:
    M.DRAIN_PROBE_DELAY_SECONDS = 0.01
    M.DRAIN_REVIVE_DELAY_SECONDS = 0.01

    print("== A. budget guard ==")
    check("budget is ten", M.TOKEN_USE_BUDGET == 10)
    check("tenth use allowed", M._budget_guard_reason(10) == "")
    check("eleventh use held", M._budget_guard_reason(11) != "")
    check("twelfth use held", M._budget_guard_reason(12) != "")
    check(
        "budget message blocks the drain",
        M._token_blocked_error("context token budget exhausted (10 used of 10)"),
    )
    check("rate limit short of the budget still retries", M._budget_guard_reason(9) == "")

    print("== B. ten sends, then the eleventh is held ==")
    home = os.path.join(raw, "budget")
    os.makedirs(home, exist_ok=True)
    os.environ["HERMES_HOME"] = home
    adapter = fixtures.FakeAdapter()
    M.patch_adapter(adapter)
    queue = adapter._hermes_wechat_v021_pending_queue
    for index in range(10):
        await adapter.send("peer-budget", "message " + str(index + 1))
    check("ten physical bubbles sent", len(adapter.sent) == 10, str(len(adapter.sent)))
    check("numbers run 1..10", sent_numbers(adapter) == [str(n) for n in range(1, 11)], str(sent_numbers(adapter)))

    await adapter.send("peer-budget", "eleventh message")
    check("eleventh is not sent", len(adapter.sent) == 10, str(len(adapter.sent)))
    check("eleventh is queued, not lost", queue.count(adapter._account_id, "peer-budget") == 1)

    print("== C. rotation resumes the held bubble at one ==")
    adapter._token_store.value = "token-rotated"
    adapter._hermes_wechat_v021_ensure_drainer("peer-budget", delay=0.0, reason="test")
    check(
        "held bubble drained after rotation",
        await wait_until(lambda: queue.count(adapter._account_id, "peer-budget") == 0),
    )
    numbers = sent_numbers(adapter)
    check("resumed bubble numbered 1", numbers[-1] == "1", str(numbers[-1]))
    check("no bubble exceeded the budget", all(int(n) <= 10 for n in numbers if n), str(numbers))
    await cancel_tasks(adapter)

    print()
    print("RESULT pass=%d fail=%d" % (PASS, FAIL))
    if FAIL:
        raise SystemExit(1)
    print("TOKEN_USE_BUDGET_OK")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="enhance-budget-") as raw:
        asyncio.run(main(raw))
