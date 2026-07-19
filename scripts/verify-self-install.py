#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import py_compile
import subprocess
import sys
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", "/opt/data"))
HOME = Path(os.environ.get("HOME", str(HERMES_HOME / ".hermes-home")))
HOOK_DIR = Path(os.environ.get("HERMES_HOOKS_DIR", str(HERMES_HOME / "hooks"))) / "hermes-wechat-enhance"
GATEWAY_SRC = Path(os.environ.get("HERMES_GATEWAY_SRC", "/opt/hermes"))
SKILL_ROOT = Path(__file__).resolve().parent.parent
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
require("WECHAT_ENHANCE_IMPORT_BOOTSTRAP_V2" in handler_text, "handler lacks portable import bootstrap")
install_text = Path(__file__).with_name("install.sh").read_text(
    encoding="utf-8"
)
require(
    "WECHAT_ENHANCE_HOOK_IDEMPOTENT_NO_BACKUP_RESIDUE_V1"
    in install_text,
    "installer lacks no-backup-residue hook marker",
)
require(
    "normalized_tree_hash" in install_text,
    "installer lacks normalized hook comparison",
)
require(
    ".before-install-" not in install_text,
    "installer still creates timestamped hook backup residue",
)
require(
    "detect_source_profile" in install_text,
    "installer lacks source-profile detection",
)
require(
    "series_for_profile" in install_text,
    "installer lacks profile-specific series selection",
)
require(
    "HERMES_WECHAT_VERSION_FROM_VERIFIED_SOURCE_PROFILE_V1" in install_text,
    "installer lacks verified source-profile version fallback",
)
require(
    'detect_version "$source_profile"' in install_text,
    "installer does not resolve version after source-profile detection",
)
require(
    "VERSION_SOURCE=verified-source-profile" in install_text,
    "installer does not expose inferred version provenance",
)
require(
    "HERMES_WECHAT_V018_VERSION_FAMILY_NORMALIZATION_V1" in install_text,
    "installer lacks v0.18 version-family normalization",
)
require(
    "normalize_version_family" in install_text,
    "installer lacks normalize_version_family",
)
for accepted_alias in (
    "v2026.7.1",
    "v0.18.0",
    "v0.18",
):
    require(
        accepted_alias in install_text,
        f"installer lacks accepted version alias {accepted_alias}",
    )
require(
    'apply_patches "$patch_dir" "$version_family" "$source_profile"'
    in install_text,
    "installer does not apply patches by normalized version family",
)
require(
    "HERMES_WECHAT_TRANSACTIONAL_SOURCE_STATE_V1" in install_text,
    "installer lacks transactional source-state marker",
)
require(
    "HERMES_WECHAT_FAULT_INJECTION_TEST_V1" in install_text,
    "installer lacks deterministic fault-injection marker",
)
require(
    "--source" in install_text,
    "installer does not pass canonical source to state manager",
)
require(
    "before-source-install-" not in install_text,
    "installer still creates source backup residue",
)
require(
    "fault_inject after-source-install" in install_text
    and "fault_inject after-hook-install" in install_text,
    "installer lacks required fault-injection stages",
)
require(
    "git config user." not in install_text,
    "installer still mutates persistent Git identity",
)
require(
    "git add -A" not in install_text,
    "installer still mutates the Git index",
)
require(
    "commit -m" not in install_text,
    "installer still creates Git commits",
)
require(
    "HERMES_WECHAT_GIT_METADATA_PRESERVATION_V1"
    in install_text,
    "installer lacks Git metadata preservation marker",
)
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
require(hasattr(mod, "_SKILL_DIR"), "handler has no resolved skill directory")
require(
    Path(mod._SKILL_DIR).resolve() == SKILL_ROOT.resolve(),
    f"portable bootstrap resolved {mod._SKILL_DIR}, expected {SKILL_ROOT}",
)
print("IMPORT_OK")
print("IMPORT_BOOTSTRAP_PORTABLE_OK")

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
    require("HERMES_WECHAT_SLASH_COMMAND_CONTENT_DEDUP_EXEMPTION_V1" in wx_text, "weixin.py lacks HERMES_WECHAT_SLASH_COMMAND_CONTENT_DEDUP_EXEMPTION_V1")
    require("HERMES_WECHAT_CONTEXT_TOKEN_REFRESH_BEFORE_CONTENT_DEDUP_V1" in wx_text, "weixin.py lacks HERMES_WECHAT_CONTEXT_TOKEN_REFRESH_BEFORE_CONTENT_DEDUP_V1")
    require("HERMES_WECHAT_CONTEXT_DELIVERY_SERIALIZATION_V1" in wx_text, "weixin.py lacks HERMES_WECHAT_CONTEXT_DELIVERY_SERIALIZATION_V1")
    require("HERMES_WECHAT_CONTEXT_TOKEN_GENERATION_FENCE_V1" in wx_text, "weixin.py lacks HERMES_WECHAT_CONTEXT_TOKEN_GENERATION_FENCE_V1")
    require("HERMES_WECHAT_CONTEXT_BUDGET_RECONCILIATION_V1" in wx_text, "weixin.py lacks HERMES_WECHAT_CONTEXT_BUDGET_RECONCILIATION_V1")
    require("HERMES_WECHAT_MEDIA_CONTEXT_BUDGET_V1" in wx_text, "weixin.py lacks HERMES_WECHAT_MEDIA_CONTEXT_BUDGET_V1")
    require("HERMES_WECHAT_ORDINARY_REPLY_APPEND_THEN_DRAIN_V1" in wx_text, "weixin.py lacks HERMES_WECHAT_ORDINARY_REPLY_APPEND_THEN_DRAIN_V1")
    require("HERMES_WECHAT_V018_SOURCE_PROFILE_DISPATCH_V1" in wx_text, "weixin.py lacks HERMES_WECHAT_V018_SOURCE_PROFILE_DISPATCH_V1")
    require("HERMES_WECHAT_V018_CONSOLIDATED_PATCH_V1" in wx_text, "weixin.py lacks HERMES_WECHAT_V018_CONSOLIDATED_PATCH_V1")
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

contract_test = Path(__file__).with_name("test-context-token-kernel-contract.py")
require(contract_test.exists(), f"missing {contract_test}")
contract_text = contract_test.read_text(encoding="utf-8")
require(
    "TEST_WEIXIN_ADAPTER_REAL_INIT_V1" in contract_text,
    "contract harness does not use real WeixinAdapter initialization",
)
environment = dict(os.environ)
environment["HERMES_GATEWAY_SRC"] = str(GATEWAY_SRC)
process = subprocess.run(
    [sys.executable, str(contract_test)],
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    env=environment,
    check=False,
)
print(process.stdout, end="")
require(process.returncode == 0, "context-token kernel contract test failed")
require(
    "SYNTHETIC_ADAPTER_RUNTIME_INIT_OK" in process.stdout,
    "adapter runtime initialization preflight did not pass",
)

state_manager_text = Path(__file__).with_name(
    "manage-install-state.py"
).read_text(encoding="utf-8")
require(
    '"source_installed_hash"' in state_manager_text,
    "state manager does not record installed source hash",
)
require(
    'divergences.append("source")' in state_manager_text,
    "state manager does not fail closed on source divergence",
)
require(
    'copy_path(root / "backups" / "source", source)' in state_manager_text,
    "state manager does not restore prior canonical source",
)
require(
    "HERMES_WECHAT_TRANSACTION_SNAPSHOT_SOURCE_PATH_V2"
    in state_manager_text,
    "state manager lacks snapshot source-path marker",
)
require(
    "gateway_file = gateway / relative" in state_manager_text,
    "state manager still risks source parameter shadowing",
)
require(
    "source = gateway / relative" not in state_manager_text,
    "state manager still shadows canonical source parameter",
)
require(
    "HERMES_WECHAT_GIT_METADATA_PRESERVATION_V1"
    in state_manager_text,
    "state manager lacks Git metadata preservation marker",
)
require(
    "HERMES_WECHAT_EXACT_FILE_BACKUP_RESTORE_V1"
    in state_manager_text,
    "state manager lacks exact file restore marker",
)
require(
    'run_git(gateway, "reset"' not in state_manager_text,
    "state manager still restores through git reset",
)
require(
    'copy_path(root / entry["backup"], gateway / relative)'
    in state_manager_text,
    "state manager does not always restore file backups",
)

print("PATCH_MARKERS_OK")
source_path_test = Path(__file__).with_name(
    "test-install-state-source-path.py"
)
process = subprocess.run(
    [sys.executable, str(source_path_test)],
    check=False,
    text=True,
    capture_output=True,
)
print(process.stdout, end="")
if process.stderr:
    print(process.stderr, end="", file=sys.stderr)
require(
    process.returncode == 0,
    "install-state source-path regression test failed",
)
require(
    "INSTALL_STATE_SOURCE_PATH_REGRESSION_OK" in process.stdout,
    "install-state source-path regression marker missing",
)

git_preservation_test = Path(__file__).with_name(
    "test-install-state-git-preservation.py"
)
process = subprocess.run(
    [sys.executable, str(git_preservation_test)],
    check=False,
    text=True,
    capture_output=True,
)
print(process.stdout, end="")
if process.stderr:
    print(process.stderr, end="", file=sys.stderr)
require(
    process.returncode == 0,
    "Git working-tree preservation regression failed",
)
require(
    "INSTALL_STATE_GIT_WORKTREE_PRESERVATION_OK"
    in process.stdout,
    "Git preservation regression marker missing",
)

print("TRANSACTIONAL_SOURCE_STATE_OK")
print("SELF_INSTALL_VERIFY_OK")
