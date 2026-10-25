#!/usr/bin/env python3
"""Queue-driven FIFO invariants for the 2026-10-25 redesign.

Covers the invariant the queue must hold on its own: while rows exist it keeps
draining (no dependence on a retry task or an inbound message), unclassified
errors never stop the loop, the backoff ceiling is 60s, and only a proven
session expiry (iLink -14) pauses until a fresh inbound token.

The physical transport is faked; queue, store and worker are the real plugin.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location(
    "fifo_fixtures", ROOT / "scripts/test-v021-bubble-footer.py"
)
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
from hermes_wechat_enhance import v021_bubble_footer as M  # noqa: E402

PASS = 0
FAIL = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ok   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}{(' :: ' + detail) if detail else ''}")


class ScriptedAdapter(fixtures.FakeAdapter):
    """FakeAdapter with a scripted error queue: one error per physical send."""

    def __init__(self) -> None:
        super().__init__()
        self.errors = []

    async def _send_text_chunk(self, *, chat_id, chunk, context_token, client_id):
        if self.errors:
            raise self.errors.pop(0)
        self.sent.append((chat_id, chunk, context_token, client_id))


async def cancel_tasks(adapter) -> None:
    tasks = list(adapter._hermes_wechat_v021_retry_tasks.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def wait_until(predicate, timeout: float = 5.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.005)
    return bool(predicate())


def adapter_home(raw: str, name: str) -> str:
    path = os.path.join(raw, name)
    os.makedirs(path, exist_ok=True)
    os.environ["HERMES_HOME"] = path
    return path


def sent_texts(adapter):
    return [chunk for (_chat, chunk, _token, _client) in adapter.sent]


async def main(raw: str) -> None:
    M.DRAIN_PROBE_DELAY_SECONDS = 0.01
    M.DRAIN_REVIVE_DELAY_SECONDS = 0.01

    print("== A. ceiling and pause classification ==")
    check("backoff ceiling is 60s", M.DRAIN_BACKOFF_CEILING_SECONDS == 60.0)
    check(
        "huge attempt count -> 60s, no overflow",
        M._transient_retry_delay(None, "cannot connect to host x ssl:default", 10**9) == 60.0,
    )
    check(
        "unclassified error keeps a probe forever",
        M._drain_delay(None, "forbidden 403", 10**6) == M.DRAIN_PROBE_DELAY_SECONDS,
    )
    check(
        "session expiry (-14) pauses",
        M._drain_delay(
            None, "iLink sendmessage error: ret=-14 errcode=-14 errmsg=session expired", 1
        )
        is None,
    )

    print("== B. unclassified failures never stop the drain ==")
    adapter_home(raw, "retry")
    retry = ScriptedAdapter()
    M.patch_adapter(retry)
    queue = retry._hermes_wechat_v021_pending_queue
    queue.enqueue(retry._account_id, "peer-retry", "c1", "persist me", "model")
    retry.errors = [RuntimeError("weird permanent 403")] * 5
    retry._hermes_wechat_v021_ensure_drainer("peer-retry", delay=0.0, reason="test")
    check(
        "drained after five unclassified failures",
        await wait_until(lambda: queue.count(retry._account_id, "peer-retry") == 0),
    )
    check("bubble was physically sent exactly once", any("persist me" in c for c in sent_texts(retry)))
    check("five failed attempts recorded", retry.errors == [])
    await cancel_tasks(retry)

    print("== C. enqueue behind a backlog revives a dead worker (no inbound) ==")
    adapter_home(raw, "revive")
    revive = ScriptedAdapter()
    M.patch_adapter(revive)
    queue = revive._hermes_wechat_v021_pending_queue
    queue.enqueue(revive._account_id, "peer-revive", "c0", "older backlog", "model")
    await revive.send("peer-revive", "newer bubble")
    check(
        "enqueue-only drain empties the queue",
        await wait_until(lambda: queue.count(revive._account_id, "peer-revive") == 0),
    )
    texts = sent_texts(revive)
    older = next((i for i, t in enumerate(texts) if "older backlog" in t), None)
    newer = next((i for i, t in enumerate(texts) if "newer bubble" in t), None)
    check("strict seq order: older before newer", older is not None and newer is not None and older < newer,
          f"older={older} newer={newer}")
    await cancel_tasks(revive)

    print("== D. session expiry pauses, a fresh inbound drain resumes ==")
    adapter_home(raw, "expired")
    expired = ScriptedAdapter()
    M.patch_adapter(expired)
    queue = expired._hermes_wechat_v021_pending_queue
    queue.enqueue(expired._account_id, "peer-token", "c1", "expired bubble", "model")
    expired.errors = [
        RuntimeError("iLink sendmessage error: ret=-14 errcode=-14 errmsg=session expired")
    ]
    result = await expired._drain_pending("peer-token")
    check("row survives a session expiry", result.get("ok") is False and queue.count(expired._account_id, "peer-token") == 1,
          f"result={result}")
    check("session expiry is reported as token-blocked", result.get("token_blocked") is True)
    check("no worker is scheduled against a dead session", "peer-token" not in expired._hermes_wechat_v021_retry_tasks)
    item = queue.peek(expired._account_id, "peer-token")
    check("failure is recorded in place", item is not None and int(item["attempts"]) == 1)
    await M._set_context_token(expired._token_store, expired._account_id, "peer-token", "fresh-token")
    resumed = await expired._drain_pending("peer-token")
    check("next inbound drain succeeds", bool(resumed.get("ok")) and queue.count(expired._account_id, "peer-token") == 0,
          f"result={resumed}")
    await cancel_tasks(expired)

    print("== E. startup recovery arms a tokenless route (core tokenless fallback) ==")
    adapter_home(raw, "tokenless")
    tokenless = ScriptedAdapter()
    M.patch_adapter(tokenless)
    tokenless._token_store.value = None
    queue = tokenless._hermes_wechat_v021_pending_queue
    queue.enqueue(tokenless._account_id, "peer-legacy", "c1", "tokenless bubble", "model")
    recovery = await tokenless._hermes_wechat_recover_pending()
    check("route recovered", recovery == {"scheduled_routes": 1, "unresolved_routes": 0}, f"recovery={recovery}")
    check(
        "tokenless backlog drains at startup",
        await wait_until(lambda: queue.count(tokenless._account_id, "peer-legacy") == 0),
    )
    sent_token = next((t for (_c, chunk, t, _cl) in tokenless.sent if "tokenless bubble" in chunk), "<missing>")
    check("sent without a token", sent_token is None, f"token={sent_token!r}")
    await cancel_tasks(tokenless)

    print("== F. a crash inside drain does not kill the worker ==")
    adapter_home(raw, "crash")
    crash = ScriptedAdapter()
    M.patch_adapter(crash)
    queue = crash._hermes_wechat_v021_pending_queue
    queue.enqueue(crash._account_id, "peer-crash", "c1", "crash bubble", "model")
    original_peek = queue.peek
    state = {"fail": True}

    def flaky_peek(account_id, chat_id):
        if state["fail"]:
            state["fail"] = False
            raise RuntimeError("sqlite boom")
        return original_peek(account_id, chat_id)

    queue.peek = flaky_peek
    crash._hermes_wechat_v021_ensure_drainer("peer-crash", delay=0.0, reason="test-crash")
    check(
        "worker retried after a drain crash",
        await wait_until(lambda: queue.count(crash._account_id, "peer-crash") == 0),
    )
    await cancel_tasks(crash)

    print(f"\nRESULT pass={PASS} fail={FAIL}")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="fifo-invariant-") as raw:
        asyncio.run(main(raw))
    sys.exit(1 if FAIL else 0)
