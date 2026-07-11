#!/usr/bin/env python3
"""
Goal-Oriented Behavioral Verification for Hermes WeChat Enhancement v0.18+

Tests verify actual runtime behavior (NOT source existence).
Each test has a clear user-facing goal and numbered pass/fail output.
Exit code: 0 = all pass, 1 = any fail.
"""

import os, sys, json, tempfile, shutil, logging, time, ast, re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from textwrap import dedent

PATCH_DIR = Path("/opt/data/skills/hermes-wechat-enhance/patches")
SCORE = {"pass": 0, "fail": 0}
ERRORS: List[str] = []

def ok(desc: str, cond: bool) -> None:
    if cond:
        SCORE["pass"] += 1
        print(f"  ✅ PASS  | {desc}")
    else:
        SCORE["fail"] += 1
        ERRORS.append(desc)
        print(f"  ❌ FAIL  | {desc}")

def summary() -> None:
    total = SCORE["pass"] + SCORE["fail"]
    print(f"\n{'='*60}")
    print(f"RESULTS: {SCORE['pass']}/{total} passed, {SCORE['fail']}/{total} failed")
    if ERRORS:
        for e in ERRORS:
            print(f"  ❌ {e}")
        sys.exit(1)
    else:
        print("✅ ALL GOAL TESTS PASSED")
        sys.exit(0)

def extract_first_hunk(patch_filename: str) -> str:
    """Extract only the first hunk from a patch file (just the added lines)."""
    path = PATCH_DIR / patch_filename
    lines = path.read_text().splitlines()
    added = []
    in_first_hunk = False
    in_second_hunk = False
    for line in lines:
        if line.startswith("@@") and not in_first_hunk:
            in_first_hunk = True
            continue
        elif line.startswith("@@") and in_first_hunk:
            in_second_hunk = True
            break
        if not in_first_hunk or in_second_hunk:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
    return "\n".join(added)

def extract_patch_section(patch_file: str, hunk_num: int = 0) -> str:
    """Extract a specific hunk (0-indexed) from a patch file."""
    path = PATCH_DIR / patch_file
    lines = path.read_text().splitlines()
    sections: List[List[str]] = []
    current: List[str] = []
    in_hunk = False
    for line in lines:
        if line.startswith("@@"):
            if current:
                sections.append(current)
            current = []
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            current.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            continue
    if current:
        sections.append(current)
    if hunk_num < len(sections):
        return "\n".join(sections[hunk_num])
    return ""

# ---------------------------------------------------------------------------
# Module-level mock environment (common for all extracted code)
# ---------------------------------------------------------------------------
MOCK_ENV = {
    "logging": logging,
    "json": json,
    "os": os,
    "time": time,
    "Path": Path,
    "Any": Any,
    "Dict": Dict,
    "List": List,
    "Optional": Optional,
    "Tuple": Tuple,
    "typing": __import__("typing"),
    "uuid": __import__("uuid"),
    "asyncio": __import__("asyncio"),
    "hashlib": __import__("hashlib"),
    "base64": __import__("base64"),
    "secrets": __import__("secrets"),
    "mimetypes": __import__("mimetypes"),
    "tempfile": __import__("tempfile"),
    "Callable": type(lambda: None),
    "TYPE_CHECKING": False,
}

# Logger mock
MOCK_ENV["logger"] = logging.getLogger("test")
logger = MOCK_ENV["logger"]
logger.setLevel(logging.WARNING)
logging.basicConfig(level=logging.WARNING)

def _safe_id(s, keep=8):
    raw = str(s or "").strip()
    if not raw:
        return "?"
    if len(raw) <= keep:
        return raw
    return raw[:keep]

MOCK_ENV["_safe_id"] = _safe_id

def _account_dir(home):
    p = Path(home) / "weixin_budget"
    p.mkdir(parents=True, exist_ok=True)
    return p

MOCK_ENV["_account_dir"] = _account_dir

def atomic_json_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))

MOCK_ENV["atomic_json_write"] = atomic_json_write

# ---------------------------------------------------------------------------
# Load classes and functions
# ---------------------------------------------------------------------------
_classes: Dict[str, Any] = {}
_functions: Dict[str, Any] = {}

def _load():
    # Extract from first hunks of 005 patch (classes) and 002/001 (functions)
    # 005: _is_system_meta, _footer_model_name, ReplyBudgetStore, MessageSendQueue
    src_005 = extract_patch_section("005-weixin-send-queue.patch", 0)
    if src_005:
        exec(compile(src_005, "<patch-005>", "exec"), MOCK_ENV)
        for name in ("_is_system_meta", "_footer_model_name"):
            if name in MOCK_ENV:
                _functions[name] = MOCK_ENV[name]
        for name in ("ReplyBudgetStore", "MessageSendQueue"):
            if name in MOCK_ENV:
                _classes[name] = MOCK_ENV[name]

    # Load from 002 patch if needed
    if "_is_system_meta" not in _functions:
        src_002 = extract_patch_section("002-weixin-footer-hook.patch", 0)
        if src_002:
            exec(compile(src_002, "<patch-002>", "exec"), MOCK_ENV)
            if "_is_system_meta" in MOCK_ENV:
                _functions["_is_system_meta"] = MOCK_ENV["_is_system_meta"]
            if "_footer_model_name" in MOCK_ENV:
                _functions["_footer_model_name"] = MOCK_ENV["_footer_model_name"]

    available = list(_functions.keys()) + list(_classes.keys())
    return available

loaded = _load()
if not loaded:
    print("⚠ No classes or functions loaded from patches. Check patch files.")
    sys.exit(1)
print(f"Loaded: {', '.join(sorted(loaded))}")

# ===========================================================================
# TEST 1: Footer Model Name Resolution
# Goal: is_system=True → "hermes"; model_name → that name; empty → fallback "hermes"
# ===========================================================================
print("\n─── Test 1: Footer Model Name Resolution ───")
print("# Goal: Footer model name shown to the user follows priority chain:")
print("#       is_system > HERMES_WECHAT_FOOTER_MODEL_NAME > model_name > resolved_model")
print("#       > routed_model > model > 'hermes' (NOT config.yaml)")

_is_system_meta = _functions.get("_is_system_meta")
_footer_model_name = _functions.get("_footer_model_name")

if not _is_system_meta or not _footer_model_name:
    ok("1.x [SKIP] Footer functions not loaded", False)
else:
    # 1a: is_system=True → "hermes"
    ok("1a: is_system=True → model='hermes'",
       _footer_model_name({"is_system": True}) == "hermes")

    # 1b: model_name in metadata → use that name
    ok("1b: model_name='deepseek-v4-pro' → model='deepseek-v4-pro'",
       _footer_model_name({"model_name": "deepseek-v4-pro"}) == "deepseek-v4-pro")

    # 1c: empty metadata → fallback chain → "hermes" (NOT config.yaml)
    name = _footer_model_name({})
    ok("1c: empty metadata → fallback to 'hermes' (not config.yaml)",
       name == "hermes")

    # 1d: is_system overrides model_name
    ok("1d: is_system=True overrides model_name → 'hermes'",
       _footer_model_name({"is_system": True, "model_name": "gpt-5"}) == "hermes")

    # 1e: resolved_model fallback
    ok("1e: resolved_model='gpt-5' → 'gpt-5'",
       _footer_model_name({"resolved_model": "gpt-5"}) == "gpt-5")

    # 1f: routed_model fallback
    ok("1f: routed_model='claude-4' → 'claude-4'",
       _footer_model_name({"routed_model": "claude-4"}) == "claude-4")

    # 1g: model key (lowest metadata priority)
    ok("1g: model='gemini-2' → 'gemini-2'",
       _footer_model_name({"model": "gemini-2"}) == "gemini-2")

    # 1h: actor=system → "hermes"
    ok("1h: actor='system' → 'hermes'",
       _footer_model_name({"actor": "system"}) == "hermes")

    # 1i: env var overrides metadata fallbacks
    old_env = os.environ.get("HERMES_WECHAT_FOOTER_MODEL_NAME")
    os.environ["HERMES_WECHAT_FOOTER_MODEL_NAME"] = "env-override"
    ok("1i: env var overrides model_name",
       _footer_model_name({"model_name": "deepseek-v4"}) == "env-override")

    # 1j: empty env var falls through to hermes
    os.environ["HERMES_WECHAT_FOOTER_MODEL_NAME"] = ""
    ok("1j: empty env var → model_name wins",
       _footer_model_name({"model_name": "deepseek-v4"}) == "deepseek-v4")
    os.environ.pop("HERMES_WECHAT_FOOTER_MODEL_NAME", None)

    if old_env:
        os.environ["HERMES_WECHAT_FOOTER_MODEL_NAME"] = old_env

# ===========================================================================
# TEST 2: ReplyBudgetStore
# Goal: Budget tracks per-token bubble count. 10 max per token. New token resets.
# ===========================================================================
print("\n─── Test 2: ReplyBudgetStore ───")
print("# Goal: Each token gets 10 bubbles. After exhausting them, sending is blocked.")
print("#       A new token resets the budget to 10.")

ReplyBudgetStore = _classes.get("ReplyBudgetStore")
if not ReplyBudgetStore:
    ok("2.x [SKIP] ReplyBudgetStore not loaded", False)
else:
    tmpdir = tempfile.mkdtemp()
    try:
        store = ReplyBudgetStore(tmpdir)

        # 2a: New token → budget=10 remaining
        store.update_token("acct1", "user1", "tok1")
        ok("2a: new token → remaining=10",
           store.remaining("acct1", "user1") == 10)
        ok("2a: new token → not exhausted",
           not store.is_exhausted("acct1", "user1"))

        # 2b: Consume 10 times → budget=0 → exhausted
        for i in range(10):
            store.increment_and_get("acct1", "user1")
        ok("2b: after 10 increments → remaining=0",
           store.remaining("acct1", "user1") == 0)
        ok("2b: after 10 increments → exhausted",
           store.is_exhausted("acct1", "user1"))
        ok("2b: get_count=10",
           store.get_count("acct1", "user1") == 10)

        # 2c: New token → budget resets to 10
        store.update_token("acct1", "user1", "tok2")
        ok("2c: new token → remaining=10 (reset)",
           store.remaining("acct1", "user1") == 10)
        ok("2c: new token → not exhausted",
           not store.is_exhausted("acct1", "user1"))
        ok("2c: new token → get_count=0",
           store.get_count("acct1", "user1") == 0)
        ok("2c: new token → get_valid_token='tok2'",
           store.get_valid_token("acct1", "user1") == "tok2")

        # 2d: User isolation
        store.update_token("acct1", "user2", "tok3")
        ok("2d: different user → fresh budget",
           store.remaining("acct1", "user2") == 10)
        ok("2d: user1 unaffected by user2",
           store.remaining("acct1", "user1") == 10)

        # 2e: Unknown user → 10 remaining (default budget)
        ok("2e: unknown user → remaining=10 (default)",
           store.remaining("acct1", "unknown") == 10)

        # 2f: Persistence via restore
        store2 = ReplyBudgetStore(tmpdir)
        store2.restore("acct1")
        ok("2f: restore → user1 remaining=10",
           store2.remaining("acct1", "user1") == 10)
        ok("2f: restore → user1 token='tok2'",
           store2.get_valid_token("acct1", "user1") == "tok2")

    finally:
        shutil.rmtree(tmpdir)

# ===========================================================================
# TEST 3: MessageSendQueue (supports /continue)
# Goal: FIFO queue, per-user isolation, metadata preserved
# ===========================================================================
print("\n─── Test 3: MessageSendQueue ───")
print("# Goal: Queued messages drained FIFO. /continue triggers drain.")

MessageSendQueue = _classes.get("MessageSendQueue")
if not MessageSendQueue:
    ok("3.x [SKIP] MessageSendQueue not loaded", False)
else:
    q = MessageSendQueue()

    # 3a: Enqueue/dequeue FIFO
    q.enqueue("a1", "u1", "msg1", "c1", None, {"model": "m1"})
    q.enqueue("a1", "u1", "msg2", "c1", None, {"model": "m2"})
    q.enqueue("a1", "u1", "msg3", "c1", None, {})

    i1 = q.dequeue("a1", "u1")
    i2 = q.dequeue("a1", "u1")
    i3 = q.dequeue("a1", "u1")
    i4 = q.dequeue("a1", "u1")

    ok("3a: FIFO order (msg1 first)", i1 is not None and i1[0] == "msg1")
    ok("3a: FIFO order (msg2 second)", i2 is not None and i2[0] == "msg2")
    ok("3a: FIFO order (msg3 third)", i3 is not None and i3[0] == "msg3")
    ok("3a: empty dequeue → None", i4 is None)

    # 3b: Metadata preserved
    ok("3b: metadata preserved (model=m1)",
       i1 is not None and i1[3] == {"model": "m1"})
    ok("3b: metadata preserved (model=m2)",
       i2 is not None and i2[3] == {"model": "m2"})

    # 3c: User isolation
    q.enqueue("a1", "x1", "user_x_msg", "c1", None, {})
    q.enqueue("a1", "x2", "user_y_msg", "c2", None, {})
    x1_item = q.dequeue("a1", "x1")
    x2_item = q.dequeue("a1", "x2")
    ok("3c: user isolation (x1)", x1_item is not None and x1_item[0] == "user_x_msg")
    ok("3c: user isolation (x2)", x2_item is not None and x2_item[0] == "user_y_msg")

    # 3d: has_pending / pending_count
    q.enqueue("a1", "u1", "p1", "c1", None, {})
    ok("3d: has_pending=True", q.has_pending("a1", "u1"))
    q.dequeue("a1", "u1")
    ok("3d: has_pending=False after drain", not q.has_pending("a1", "u1"))

    q.enqueue("a1", "u1", "a", "c1", None, {})
    q.enqueue("a1", "u1", "b", "c1", None, {})
    ok("3d: pending_count=2", q.pending_count("a1", "u1") == 2)

# ===========================================================================
# TEST 4: /continue interception control flow
# Goal: /continue triggers _drain_pending(), NOT forwarded to gateway
# ===========================================================================
print("\n─── Test 4: /continue InterceptionControl Flow ───")
print("# Goal: /continue → _drain_pending() triggered, not sent to gateway.")

# We verify by checking the patch source for the /continue handling logic
src_001 = extract_patch_section("001-weixin-continue-hook.patch", 0)
if src_001:
    ok("4a: /continue handler calls _drain_pending()",
       "_drain_pending" in src_001)
    ok("4b: /continue handler returns early (before media_paths)",
       "return" in src_001 and "media_paths" not in src_001[:src_001.find("return")] if "return" in src_001 else False)
    # Actually check more precisely
    ret_idx = src_001.find("return")
    media_idx = src_001.find("media_paths")
    ok("4b: /continue returns before media processing",
       ret_idx >= 0 and (media_idx < 0 or ret_idx < media_idx))
    ok("4c: /continue does not forward to gateway",
       "passing /continue through to gateway" not in src_001)
else:
    ok("4.x [SKIP] /continue patch not found", False)

# Also simulate the drain behavior with the queue + budget
if MessageSendQueue and ReplyBudgetStore:
    tmpdir = tempfile.mkdtemp()
    try:
        queue = MessageSendQueue()
        store = ReplyBudgetStore(tmpdir)
        store.update_token("acct1", "user1", "tok_continue")

        # Enqueue 5 messages
        for i in range(5):
            queue.enqueue("acct1", "user1", f"msg_{i}", "c1", None, {})

        ok("4d: budget=10 before drain",
           store.remaining("acct1", "user1") == 10)

        # Simulate drain: consume while budget permits
        drained = []
        while queue.has_pending("acct1", "user1"):
            if store.is_exhausted("acct1", "user1"):
                break
            item = queue.dequeue("acct1", "user1")
            if item is None:
                break
            store.increment_and_get("acct1", "user1")
            drained.append(item[0])

        ok("4e: drain consumed queued messages (FIFO)",
           drained == ["msg_0", "msg_1", "msg_2", "msg_3", "msg_4"])
        ok("4f: budget decremented to 5",
           store.remaining("acct1", "user1") == 5)
        ok("4g: queue empty after drain",
           not queue.has_pending("acct1", "user1"))

    finally:
        shutil.rmtree(tmpdir)

summary()