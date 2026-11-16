#!/usr/bin/env python3
"""Runtime status must report the durable queue, not a stale zero.

A startup refresh ran before any adapter existed, so runtime-status.json said
pending_bubbles=0 while three bubbles sat in the sqlite queue. The status file
now falls back to the queue on disk when no adapter is in hand, and the send
and drain paths refresh it on every transition.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location(
    "status_fixtures", ROOT / "scripts/test-v021-bubble-footer.py"
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


def status() -> dict:
    path = M._queue_path().parent / "runtime-status.json"
    return json.loads(path.read_text(encoding="utf-8"))


async def main(raw: str) -> None:
    home = os.path.join(raw, "status")
    os.makedirs(home, exist_ok=True)
    os.environ["HERMES_HOME"] = home

    adapter = fixtures.FakeAdapter()
    M.patch_adapter(adapter)
    queue = adapter._hermes_wechat_v021_pending_queue
    check("queue starts empty", queue.total() == 0)

    queue.enqueue(adapter._account_id, "peer-status", "c1", "held one", "model")
    queue.enqueue(adapter._account_id, "peer-status", "c2", "held two", "model")
    check("two rows on disk", queue.total() == 2)

    print("== A. no adapter in hand reads the disk ==")
    M.refresh_runtime_status()
    check("status reports the durability, not zero", status().get("pending_bubbles") == 2, str(status().get("pending_bubbles")))

    print("== B. adapter path agrees ==")
    M.refresh_queue_status(adapter)
    check("adapter refresh reports two", status().get("pending_bubbles") == 2)

    print("== C. draining empties the reported count ==")
    adapter._token_store.value = "token-fresh"
    M.DRAIN_PROBE_DELAY_SECONDS = 0.01
    adapter._hermes_wechat_v021_ensure_drainer("peer-status", delay=0.0, reason="test")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5.0
    while loop.time() < deadline and queue.total() != 0:
        await asyncio.sleep(0.01)
    check("rows drained", queue.total() == 0)
    M.refresh_queue_status(adapter)
    check("status follows the drain to zero", status().get("pending_bubbles") == 0)

    tasks = list(adapter._hermes_wechat_v021_retry_tasks.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    print()
    print("RESULT pass=%d fail=%d" % (PASS, FAIL))
    if FAIL:
        raise SystemExit(1)
    print("RUNTIME_STATUS_PENDING_OK")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="enhance-status-") as raw:
        asyncio.run(main(raw))
