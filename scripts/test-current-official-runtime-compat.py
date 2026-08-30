#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

GATEWAY_SRC = Path(os.environ.get("HERMES_GATEWAY_SRC", "/opt/hermes"))
if str(GATEWAY_SRC) not in sys.path:
    sys.path.insert(0, str(GATEWAY_SRC))

SKILL_ROOT = Path(
    os.environ.get(
        "HERMES_WECHAT_ENHANCE_TEST_SKILL_ROOT",
        str(Path(__file__).resolve().parent.parent),
    )
).resolve()
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

KERNEL_TEST = Path(
    os.environ.get(
        "HERMES_WECHAT_ENHANCE_KERNEL_TEST",
        str(Path(__file__).with_name("test-context-token-kernel-contract.py")),
    )
).resolve()

from hermes_wechat_enhance.current_official_runtime_compat_core import (
    EXPECTED_WEIXIN_SHA256,
    MARKER as CORE_MARKER,
    patch_weixin_adapter,
)
from hermes_wechat_enhance.current_official_runtime_compat import (
    _MARKER as DISPATCHER_MARKER,
    install_weixin_runtime_compat_hook,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit("FAIL " + message)


require(
    CORE_MARKER == "HERMES_WECHAT_CURRENT_OFFICIAL_RUNTIME_COMPAT_CANDIDATE_V1",
    "proven core marker changed",
)
require(
    EXPECTED_WEIXIN_SHA256
    == "85e06cea1673ae20e336820e9cac5a7dc467bdd8c2796a73c3e2bf1042c76dc4",
    "proven core source gate changed",
)
require(
    DISPATCHER_MARKER == "HERMES_WECHAT_CURRENT_OFFICIAL_RUNTIME_COMPAT_HOOK_V1",
    "dispatcher marker changed",
)
require(KERNEL_TEST.exists(), f"historical kernel missing: {KERNEL_TEST}")

spec = importlib.util.spec_from_file_location(
    "current_official_historical_kernel",
    KERNEL_TEST,
)
kernel = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(kernel)

original_adapter = kernel.adapter


def compat_adapter(root: Path, *, real_dedup: bool = False):
    current = original_adapter(root, real_dedup=real_dedup)
    patch_weixin_adapter(current)
    return current


kernel.adapter = compat_adapter


async def extra_reliable_delivery_contract() -> None:
    with tempfile.TemporaryDirectory(prefix="current-official-compat-extra-") as d:
        current = original_adapter(Path(d))
        patch_weixin_adapter(current)
        current._budget_store.update_token("acct", "user", "token")

        metadata = {"_delivery_id": "same-delivery", "_delivery_chunk_index": 0}
        first = current._send_queue.enqueue(
            "acct", "user", "payload", "user", None, metadata
        )
        second = current._send_queue.enqueue(
            "acct", "user", "payload", "user", None, metadata
        )
        require(first is True, "first delivery-id enqueue rejected")
        require(second is False, "duplicate delivery-id/chunk enqueue accepted")
        require(
            current._send_queue.pending_count("acct", "user") == 1,
            "delivery-id dedupe queue length mismatch",
        )
        print("DELIVERY_ID_CHUNK_DEDUPE_OK")

        client_ids = []
        calls = 0

        async def fail_then_succeed(**kwargs):
            nonlocal calls
            calls += 1
            client_ids.append(kwargs["client_id"])
            if calls == 1:
                raise RuntimeError("synthetic fail")

        current._send_text_chunk = fail_then_succeed
        failed = await current._drain_pending("user")
        require(not failed.success, "synthetic failed send reported success")
        require(current._budget_store.get_count("acct", "user") == 0, "failed send consumed reply budget")
        require(current._send_queue.pending_count("acct", "user") == 1, "failed send dequeued pending item")

        succeeded = await current._drain_pending("user")
        require(succeeded.success, "retry did not succeed")
        require(current._budget_store.get_count("acct", "user") == 1, "successful retry did not commit reply budget")
        require(current._send_queue.pending_count("acct", "user") == 0, "successful retry did not dequeue item")
        require(
            len(client_ids) == 2 and client_ids[0] == client_ids[1],
            "failed retry changed deterministic client_id",
        )
        print("FAILED_SEND_RETRY_STABLE_CLIENT_ID_OK")


async def incompatible_stub_skip_contract() -> None:
    class FakeAdapter:
        name = "weixin"

    result = await install_weixin_runtime_compat_hook(
        {"adapters": {"weixin": FakeAdapter()}}
    )
    require(
        result.get("profile") == "current-official-v018",
        f"stub skip profile mismatch: {result}",
    )
    require(
        result.get("discovery_source") == "hook-context",
        f"stub skip discovery source mismatch: {result}",
    )
    require(
        int(result.get("installed", 0)) == 0,
        f"stub unexpectedly patched: {result}",
    )
    require(
        int(result.get("skipped_incompatible", 0)) == 1,
        f"stub skip count mismatch: {result}",
    )
    require(not result.get("errors"), f"stub skip reported errors: {result}")
    print("CURRENT_OFFICIAL_RUNTIME_COMPAT_INCOMPATIBLE_STUB_SKIP_OK")


async def dispatcher_smoke_contract() -> None:
    with tempfile.TemporaryDirectory(prefix="current-official-dispatcher-") as d:
        current = original_adapter(Path(d))
        result = await install_weixin_runtime_compat_hook(
            {"adapters": {"weixin": current}}
        )

        require(
            result.get("marker")
            == "HERMES_WECHAT_CURRENT_OFFICIAL_RUNTIME_COMPAT_HOOK_V1",
            "dispatcher marker mismatch",
        )
        require(result.get("profile") == "current-official-v018", "dispatcher did not select current-official profile")
        require(
            result.get("discovery_source") == "hook-context",
            f"dispatcher did not use hook context: {result}",
        )
        require(int(result.get("installed", 0)) == 1, f"dispatcher installed count mismatch: {result}")
        require(not result.get("errors"), f"dispatcher errors: {result}")
        require(
            getattr(current, "_hermes_wechat_current_official_runtime_compat_v1", False) is True,
            "dispatcher did not patch adapter instance",
        )
        print("CURRENT_OFFICIAL_RUNTIME_COMPAT_CONTEXT_DISCOVERY_OK")
        print("CURRENT_OFFICIAL_RUNTIME_COMPAT_DISPATCHER_OK")


async def main() -> None:
    await kernel.main()
    await extra_reliable_delivery_contract()
    await incompatible_stub_skip_contract()
    await dispatcher_smoke_contract()
    print("CURRENT_OFFICIAL_RUNTIME_COMPAT_TEST=PASS")


asyncio.run(main())
