#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import py_compile
import subprocess
import sys
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
HOME = Path(os.environ.get("HOME", str(HERMES_HOME / ".hermes-home")))
HOOK_DIR = Path(os.environ.get("HERMES_HOOKS_DIR", str(HERMES_HOME / "hooks"))) / "hermes-wechat-enhance"
GATEWAY_SRC = Path(os.environ.get("HERMES_GATEWAY_SRC", "/opt/hermes"))
# HERMES_WECHAT_VERIFY_GATEWAY_IMPORT_BOOTSTRAP_V1
if str(GATEWAY_SRC) not in sys.path:
    sys.path.insert(0, str(GATEWAY_SRC))
SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_READY = "♻️ Gateway online — Hermes is back and ready."
_ready_env = os.environ.get("HERMES_WEIXIN_STARTUP_READY_NOTIFY", "").strip()
# VERIFY_READY_ENV_BOOL_CONTRACT_V2: the synthetic startup-ready smoke must remain
# enabled even when the real production setting intentionally disables startup
# notifications. Runtime behavior is not changed; only this fake-adapter fixture
# normalizes disabled values to the built-in ready text.
_ready_disabled = _ready_env.lower() in {"0", "false", "no", "off", "disabled"}
READY = DEFAULT_READY if (not _ready_env or _ready_env == "1" or _ready_disabled) else _ready_env

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
require(
    "HERMES_WECHAT_CURRENT_OFFICIAL_RUNTIME_COMPAT_HOOK_V1" in handler_text,
    "handler lacks current-official runtime compatibility marker",
)
require(
    "install_weixin_runtime_compat_hook" in handler_text,
    "handler does not install runtime compatibility dispatcher",
)
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
    "HERMES_WECHAT_CURRENT_OFFICIAL_NO_WEIXIN_MUTATION_PROFILE_V2" in install_text,
    "installer lacks current official no-weixin-mutation profile",
)
require(
    "CURRENT_OFFICIAL_V018_WEIXIN_SHA256" in install_text
    and "current-official-v018" in install_text,
    "installer lacks current official source recognition",
)
current_series = SKILL_ROOT / "patches" / "series.current-official-v018"
require(
    current_series.exists(),
    f"missing current official profile series: {current_series}",
)
current_series_ids = [
    line.strip()
    for line in current_series.read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.lstrip().startswith("#")
]
require(
    current_series_ids == ["006", "007", "008"],
    f"current official profile must select only 006/007/008, got {current_series_ids}",
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

# HERMES_WECHAT_CURRENT_OFFICIAL_PROFILE_VERIFY_V2
CURRENT_OFFICIAL_V018_WEIXIN_SHA256 = "85e06cea1673ae20e336820e9cac5a7dc467bdd8c2796a73c3e2bf1042c76dc4"
CURRENT_OFFICIAL_V018_BASE_SHA256 = "dbdf137f59c4e541ac4c3ad3cf761e7cd8d11b5e487ead12ba8c19a6e3be4984"
CURRENT_OFFICIAL_V018_RUN_SHA256 = "9832bc3e285f1616b6bceecd68a457f4bf0ee5fe39d825c0e745167e0f324754"
current_official_profile = False

if wx.exists():
    wx_text = read(wx)
    wx_digest = hashlib.sha256(wx.read_bytes()).hexdigest()
    current_official_profile = wx_digest == CURRENT_OFFICIAL_V018_WEIXIN_SHA256
    if current_official_profile:
        print("WEIXIN_PROFILE=current-official-v018")
        require("class ReplyBudgetStore" in wx_text, "current official weixin lacks ReplyBudgetStore")
        require("class MessageSendQueue" in wx_text, "current official weixin lacks MessageSendQueue")
        require("async def _drain_pending" in wx_text, "current official weixin lacks _drain_pending")
        require("/continue: drain pending" in wx_text, "current official weixin lacks /continue drain")
        require("def _footer_model_name" in wx_text, "current official weixin lacks footer helper")
        require("def _is_system_meta" in wx_text, "current official weixin lacks system metadata helper")
        require("Secondary content-fingerprint dedup for text messages" in wx_text, "current official weixin lacks content dedup")
        require('content_key = f"content:{sender_id}:' in wx_text, "current official content-dedup key shape changed")
        require(base.exists(), "current official base.py missing")
        require(hashlib.sha256(base.read_bytes()).hexdigest() == CURRENT_OFFICIAL_V018_BASE_SHA256, "current official base.py hash changed")
        print("CURRENT_OFFICIAL_WEIXIN_NATIVE_CAPABILITIES_OK")
        print("CURRENT_OFFICIAL_WEIXIN_BYTE_IDENTITY_OK")
    else:
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
    if current_official_profile:
        require(
            hashlib.sha256(run.read_bytes()).hexdigest()
            == CURRENT_OFFICIAL_V018_RUN_SHA256,
            "current official run.py does not match accepted 006/007/008 runtime",
        )
        print("CURRENT_OFFICIAL_RUN_EXACT_PARITY_OK")
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

compat_core = SKILL_ROOT / "hermes_wechat_enhance" / "current_official_runtime_compat_core.py"
compat_dispatcher = SKILL_ROOT / "hermes_wechat_enhance" / "current_official_runtime_compat.py"
compat_contract_test = Path(__file__).with_name("test-current-official-runtime-compat.py")
PROVEN_CURRENT_OFFICIAL_RUNTIME_COMPAT_CORE_SHA256 = (
    "7d0cac0671bf33f24b5682e5978f0502255e549817d9881ad069256215c95216"
)
require(compat_core.exists(), f"missing {compat_core}")
require(compat_dispatcher.exists(), f"missing {compat_dispatcher}")
require(compat_contract_test.exists(), f"missing {compat_contract_test}")
require(
    hashlib.sha256(compat_core.read_bytes()).hexdigest()
    == PROVEN_CURRENT_OFFICIAL_RUNTIME_COMPAT_CORE_SHA256,
    "current-official runtime compatibility core differs from proven candidate",
)

environment = dict(os.environ)
environment["HERMES_GATEWAY_SRC"] = str(GATEWAY_SRC)
environment["PYTHONDONTWRITEBYTECODE"] = "1"

if current_official_profile:
    process = subprocess.run(
        [sys.executable, str(compat_contract_test)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=environment,
        check=False,
    )
    print(process.stdout, end="")
    require(
        process.returncode == 0,
        "current-official runtime compatibility contract test failed",
    )
    for compat_marker in (
        "SYNTHETIC_ADAPTER_RUNTIME_INIT_OK",
        "SLASH_COMMAND_CONTENT_DEDUP_EXEMPTION_OK",
        "MESSAGE_ID_REPLAY_DEDUP_OK",
        "CONTEXT_REFRESH_BEFORE_CONTENT_DEDUP_OK",
        "CONTINUE_SILENT_REFRESH_DRAIN_OK",
        "SHARED_CONTEXT_TOKEN_COUNT_OK",
        "ORDINARY_REPLY_APPEND_THEN_DRAIN_OK",
        "ACK_COMMIT_AND_MAXIMUM_TEN_OK",
        "TOKEN_GENERATION_AND_DRAIN_SERIALIZATION_OK",
        "MEDIA_CONTEXT_TOKEN_BUDGET_OK",
        "CONTEXT_BUDGET_RECONCILIATION_OK",
        "CONTEXT_TOKEN_KERNEL_CONTRACT_OK",
        "DELIVERY_ID_CHUNK_DEDUPE_OK",
        "FAILED_SEND_RETRY_STABLE_CLIENT_ID_OK",
        "CURRENT_OFFICIAL_RUNTIME_COMPAT_DISPATCHER_OK",
        "CURRENT_OFFICIAL_RUNTIME_COMPAT_TEST=PASS",
    ):
        require(
            compat_marker in process.stdout,
            f"current-official compatibility marker missing: {compat_marker}",
        )
    print("CURRENT_OFFICIAL_RUNTIME_COMPAT_VERIFY_OK")
else:
    process = subprocess.run(
        [sys.executable, str(contract_test)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=environment,
        check=False,
    )
    print(process.stdout, end="")
    require(
        process.returncode == 0,
        "context-token kernel contract test failed",
    )
    require(
        "SYNTHETIC_ADAPTER_RUNTIME_INIT_OK" in process.stdout,
        "adapter runtime initialization preflight did not pass",
    )

# HERMES_WECHAT_SLASH_COMMAND_DEDUP_VERIFY_V1
slash_module = SKILL_ROOT / "hermes_wechat_enhance" / "slash_command_dedup.py"
slash_contract_test = Path(__file__).with_name(
    "test-slash-command-dedup-hook.py"
)
require(
    "HERMES_WECHAT_SLASH_COMMAND_DEDUP_HOOK_V1" in handler_text,
    "handler lacks repeated slash-command runtime hook marker",
)
require(
    slash_module.exists(),
    f"missing slash-command dedup module: {slash_module}",
)
require(
    slash_contract_test.exists(),
    f"missing slash-command dedup contract test: {slash_contract_test}",
)
slash_environment = dict(os.environ)
slash_environment["PYTHONDONTWRITEBYTECODE"] = "1"
slash_process = subprocess.run(
    [sys.executable, str(slash_contract_test)],
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    env=slash_environment,
    check=False,
)
print(slash_process.stdout, end="")
require(
    slash_process.returncode == 0,
    "slash-command dedup contract test failed",
)
for slash_marker in (
    "SLASH_COMMAND_DEDUP_HOOK_TEST=PASS",
    "provider_message_id_dedup_preserved=true",
    "repeated_slash_command_allowed=true",
    "ordinary_text_content_dedup_preserved=true",
    "contextvar_concurrency_isolation=true",
):
    require(
        slash_marker in slash_process.stdout,
        f"slash-command dedup contract marker missing: {slash_marker}",
    )
print("SLASH_COMMAND_DEDUP_VERIFY_OK")

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
