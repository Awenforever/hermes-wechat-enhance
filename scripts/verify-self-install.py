#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import py_compile
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", "/opt/data"))
HOME = Path(os.environ.get("HOME", str(HERMES_HOME / ".hermes-home")))
HOOK_DIR = Path(os.environ.get("HERMES_HOOKS_DIR", str(HERMES_HOME / "hooks"))) / "hermes-wechat-enhance"
GATEWAY_SRC = Path(os.environ.get("HERMES_GATEWAY_SRC", "/opt/hermes"))
DEFAULT_READY = "♻️ Gateway online — Hermes is back and ready."
_ready_env = os.environ.get("HERMES_WEIXIN_STARTUP_READY_NOTIFY", "").strip()
# VERIFY_READY_ENV_BOOL_CONTRACT_V1: the runtime treats empty or "1" as "use default".
READY = DEFAULT_READY if (not _ready_env or _ready_env == "1") else _ready_env

def require(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit("FAIL " + msg)

def read(path: Path) -> str:
    return path.read_text("utf-8")

print("VERIFY HERMES_HOME=", HERMES_HOME)
print("VERIFY HOOK_DIR=", HOOK_DIR)

hook_yaml = HOOK_DIR / "HOOK.yaml"
handler_py = HOOK_DIR / "handler.py"

require(hook_yaml.exists(), f"missing {hook_yaml}")
require(handler_py.exists(), f"missing {handler_py}")

hook_text = read(hook_yaml)
require("gateway:startup" in hook_text, "HOOK.yaml lacks gateway:startup")
require("agent:start" in hook_text, "HOOK.yaml lacks agent:start")
require("agent:end" in hook_text, "HOOK.yaml lacks agent:end")

handler_text = read(handler_py)
require("WECHAT_ENHANCE_IMPORT_BOOTSTRAP_V1" in handler_text, "handler lacks import bootstrap")
require("WECHAT_ENHANCE_STARTUP_READY_OWNER_V1" in handler_text, "handler lacks startup ready owner marker")
require("WECHAT_ENHANCE_STARTUP_READY_ACK_V2" in handler_text, "handler lacks startup ready ack marker")
require("Hermes WeChat Enhance: startup ready notification sent" in handler_text, "handler lacks ready sent log")
require("startup ready not delivered" in handler_text, "handler lacks ready failure log")
require("Hermes Alive: startup ready notification sent" not in handler_text, "handler contains alive ready log")

py_compile.compile(str(handler_py), doraise=True)
spec = importlib.util.spec_from_file_location("verify_hermes_wechat_enhance_hook", str(handler_py))
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)
require(hasattr(mod, "handle"), "handler has no handle()")
require(hasattr(mod, "_send_startup_ready"), "handler has no _send_startup_ready()")
print("IMPORT_OK")

class FakeResult:
    def __init__(self, success=True, error=None):
        self.success = success
        self.error = error

class FakeAdapter:
    def __init__(self):
        self.sent = []

    async def send(self, chat_id, content, metadata=None):
        self.sent.append({"chat_id": chat_id, "content": content, "metadata": metadata or {}})
        return FakeResult(success=True)

async def main_async():
    os.environ["HERMES_PROACTIVE_WEIXIN_CHAT_ID"] = "test-chat"
    os.environ["HERMES_WEIXIN_STARTUP_READY_NOTIFY"] = READY
    fake = FakeAdapter()
    await mod.handle("gateway:startup", {"adapters": {"weixin": fake}})
    require(len(fake.sent) == 1, "startup ready did not send exactly once")
    sent = fake.sent[0]
    require(sent["chat_id"] == "test-chat", "ready chat id mismatch")
    require(sent["content"] == READY, f"ready content mismatch: {sent['content']!r}")
    meta = sent["metadata"]
    require(meta.get("is_system") is True, "ready metadata missing is_system=True")
    require(meta.get("model_name") == "hermes", "ready metadata model_name not hermes")
    require(meta.get("resolved_model") == "hermes", "ready metadata resolved_model not hermes")
    require(meta.get("routed_model") == "hermes", "ready metadata routed_model not hermes")
    require(meta.get("source") == "wechat-enhance-startup-ready", "ready metadata source mismatch")
    print("FAKE_SEND_OK")
    print("STARTUP_READY_ACK_OK")

    ctx_in = {
        "platform": "weixin",
        "user_id": "u1",
        "chat_id": "c1",
        "session_id": "s1",
        "message": "hello",
        "metadata": {"model_name": "deepseek-v4-pro"},
    }
    ctx_out = {
        "platform": "weixin",
        "user_id": "u1",
        "chat_id": "c1",
        "session_id": "s1",
        "response": "world",
        "metadata": {"model_name": "deepseek-v4-pro"},
    }
    await mod.handle("agent:start", ctx_in)
    await mod.handle("agent:end", ctx_out)

asyncio.run(main_async())

store_path = HOME / ".hermes" / "wechat_enhance" / "messages.jsonl"
require(store_path.exists(), f"message store not created: {store_path}")
rows = [json.loads(x) for x in store_path.read_text("utf-8").splitlines() if x.strip()]
require(any(r.get("direction") == "in" for r in rows), "no inbound record")
require(any(r.get("direction") == "out" for r in rows), "no outbound record")
print("MESSAGE_CAPTURE_OK")

wx = GATEWAY_SRC / "gateway" / "platforms" / "weixin.py"
run = GATEWAY_SRC / "gateway" / "run.py"
base = GATEWAY_SRC / "gateway" / "platforms" / "base.py"

if wx.exists():
    wx_text = read(wx)
    require("class ReplyBudgetStore" in wx_text, "weixin.py lacks ReplyBudgetStore")
    require("class MessageSendQueue" in wx_text, "weixin.py lacks MessageSendQueue")
    require("async def _drain_pending" in wx_text, "weixin.py lacks _drain_pending")
    require("WECHAT_ENHANCE_RELIABLE_DELIVERY_V2" in wx_text, "weixin.py lacks reliable delivery marker")
    require("WECHAT_ENHANCE_REPLY_BUDGET_COMMIT_AFTER_ACK_V2" in wx_text, "weixin.py lacks commit-after-ack budget marker")
    require("WECHAT_ENHANCE_QUEUE_PEEK_COMMIT_V2" in wx_text, "weixin.py lacks queue peek/commit marker")
    require("WECHAT_ENHANCE_DELIVERY_ID_DEDUPE_V2" in wx_text, "weixin.py lacks delivery_id dedupe marker")
    require("def next_count" in wx_text and "def commit_count" in wx_text, "weixin.py lacks budget next/commit methods")
    require("def peek" in wx_text, "weixin.py lacks non-destructive queue peek")
    require("Weixin send attempt bubble_count" in wx_text, "weixin.py lacks corrected send attempt log")
    require("Weixin queued send count" not in wx_text, "weixin.py still has misleading queued send count log")
    require("delivery_id_present" in wx_text and "context_token_present" in wx_text, "weixin.py lacks safe delivery/token observability")
    require("/continue: drain pending" in wx_text, "weixin.py lacks /continue drain marker")
    require("def _footer_model_name" in wx_text, "weixin.py lacks _footer_model_name")
    require("def _is_system_meta" in wx_text, "weixin.py lacks _is_system_meta")
if run.exists():
    run_text = read(run)
    require("_non_conversational_metadata" in run_text, "run.py lacks _non_conversational_metadata")
    require("is_system" in run_text, "run.py lacks is_system metadata marker")
    require("HERMES_WECHAT_INTERIM_MODEL_METADATA_V1" in run_text, "run.py lacks interim model metadata marker")
    require("_current_turn_model_metadata" in run_text, "run.py lacks interim model metadata helper")
    require("HERMES_WECHAT_INTERIM_MODEL_METADATA_STRICT_SOURCE_V2" in run_text, "run.py lacks strict-source interim model metadata marker")
    require("wechat interim assistant model metadata source=" in run_text, "run.py lacks strict-source interim model metadata observability")
    helper_block = run_text.split("def _current_turn_model_metadata", 1)[1].split("def _interim_assistant_cb", 1)[0]
    require("_resolve_gateway_model()" not in helper_block, "run.py interim helper still uses config/default model fallback")
    require("HERMES_WECHAT_STREAM_CONSUMER_MODEL_METADATA_V3" in run_text, "run.py lacks stream consumer model metadata marker")
    require("HERMES_WECHAT_QUEUED_FIRST_RESPONSE_MODEL_METADATA_V3" in run_text, "run.py lacks queued first_response model metadata marker")
    require("HERMES_WECHAT_BACKGROUND_REVIEW_SYSTEM_METADATA_V3B" in run_text, "run.py lacks background review system metadata marker")
    bg_block = run_text.split("def _deliver_bg_review_message", 1)[1].split("def _release_bg_review_messages", 1)[0]
    require("_non_conversational_metadata(_status_thread_metadata, platform=source.platform)" in bg_block, "background review must remain system/non-conversational metadata")
    require("_current_turn_model_metadata(_status_thread_metadata)" not in bg_block, "background review must not use model metadata")
    require("HERMES_WECHAT_HANDOFF_MODEL_METADATA_V3" in run_text, "run.py lacks handoff model metadata marker")
    require("HERMES_WECHAT_FINAL_MODEL_STRICT_SOURCE_V3" in run_text, "run.py lacks final strict-source model metadata marker")
    final_block = run_text.split("Propagate resolved model to event", 1)[1].split("response = agent_result", 1)[0]
    require("_resolve_gateway_model()" not in final_block, "run.py final footer metadata still uses config/default model fallback")
    require("_stream_consumer.metadata = _current_turn_model_metadata(_status_thread_metadata)" in run_text, "run.py stream consumer metadata not refreshed with model metadata")
    require("wechat queued first_response model metadata source=" in run_text, "run.py lacks queued first_response metadata observability")
if base.exists():
    base_text = read(base)
    require("_mark_notify_metadata" in base_text, "base.py lacks _mark_notify_metadata")

print("PATCH_MARKERS_OK")
print("SELF_INSTALL_VERIFY_OK")
