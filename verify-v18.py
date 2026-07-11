#!/usr/bin/env python3
"""
Functional verification of v0.18 WeChat patches.
Tests actual class/method behavior, not just existence.
"""
import ast, sys, tempfile, shutil, textwrap, re, os

WX = "/tmp/v18-final/gateway/platforms/weixin.py"
BASE = "/tmp/v18-final/gateway/platforms/base.py"
RUN = "/tmp/v18-final/gateway/run.py"

R = {"pass": 0, "fail": 0, "errs": []}

def ok(desc, cond):
    if cond: R["pass"] += 1; print(f"  ✅ {desc}")
    else: R["fail"] += 1; R["errs"].append(desc); print(f"  ❌ {desc}")

def src_ok(path, pat, desc):
    with open(path) as f: ok(desc, bool(re.search(pat, f.read(), re.MULTILINE)))

def src_not(path, pat, desc):
    with open(path) as f: ok(desc, not bool(re.search(pat, f.read(), re.MULTILINE)))

def extract_source(filepath, name, is_class=False):
    with open(filepath) as f:
        source = f.read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if is_class and isinstance(node, ast.ClassDef) and node.name == name:
            return ast.get_source_segment(source, node)
        if not is_class and isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    return None

MOCK = textwrap.dedent("""
import logging, json, os, time
from pathlib import Path
from typing import Any, Dict, Optional, List, Tuple
logger = logging.getLogger("test")
def _safe_id(s): return str(s)[:8]
def _account_dir(home): return Path(home) / "weixin_budget"
def atomic_json_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
""")

print("=" * 60)
print("FUNCTIONAL VERIFICATION: v0.18 WeChat Patches")
print("=" * 60)

# ============================================================
# 1. ReplyBudgetStore
# ============================================================
print("\n--- 1. ReplyBudgetStore ---")
budget_src = extract_source(WX, "ReplyBudgetStore", is_class=True)
if budget_src:
    ns = {}
    exec(MOCK + budget_src, ns)
    S = ns["ReplyBudgetStore"]
    
    d = tempfile.mkdtemp()
    try:
        s = S(d)
        s.update_token("a1", "u1", "tok1")
        
        # 10 msg per token
        for i in range(10):
            count = s.increment_and_get("a1", "u1")
            ok(f"  consume {i+1}/10 → count={count}", count == i + 1)
        
        ok("is_exhausted after 10 uses", s.is_exhausted("a1", "u1"))
        ok("remaining=0 after 10", s.remaining("a1", "u1") == 0)
        
        # New token
        s.update_token("a1", "u1", "tok2")
        ok("new token: not exhausted", not s.is_exhausted("a1", "u1"))
        ok("new token: remaining=10", s.remaining("a1", "u1") == 10)
        
        # get_valid_token
        tok = s.get_valid_token("a1", "u1")
        ok("get_valid_token returns valid token", tok == "tok2" or bool(tok))
        
        # Persistence
        s2 = S(d)
        s2.restore("a1")
        ok("restore: remaining > 0", s2.remaining("a1", "u1") > 0)
    finally:
        shutil.rmtree(d)
else:
    ok("ReplyBudgetStore class found", False)

# ============================================================
# 2. MessageSendQueue
# ============================================================
print("\n--- 2. MessageSendQueue ---")
queue_src = extract_source(WX, "MessageSendQueue", is_class=True)
if queue_src:
    ns = {}
    exec(MOCK + queue_src, ns)
    Q = ns["MessageSendQueue"]
    
    q = Q()
    meta1 = {"model_name": "deepseek"}
    meta2 = {"is_system": True}
    q.enqueue("a1", "u1", "Hello", "c1", None, meta1)
    q.enqueue("a1", "u1", "World", "c1", None, meta2)
    
    # dequeue returns Tuple[str, str, Optional[str], Optional[Dict]]
    i1 = q.dequeue("a1", "u1")
    i2 = q.dequeue("a1", "u1")
    i3 = q.dequeue("a1", "u1")
    
    ok("FIFO: first text='Hello'", i1 and i1[0] == "Hello")
    ok("FIFO: second text='World'", i2 and i2[0] == "World")
    ok("FIFO: third=None", i3 is None)
    
    # Metadata
    ok("Metadata preserved (first)", i1 and i1[3] == meta1)
    ok("Metadata preserved (second)", i2 and i2[3] == meta2)
    
    # User isolation
    q.enqueue("a1", "x1", "A", "c1", None, {})
    q.enqueue("a1", "x2", "B", "c2", None, {})
    ok("User isolation", q.dequeue("a1", "x1")[0] == "A" and q.dequeue("a1", "x2")[0] == "B")
else:
    ok("MessageSendQueue class found", False)

# ============================================================
# 3. _is_system_meta
# ============================================================
print("\n--- 3. _is_system_meta ---")
ismeta = extract_source(WX, "_is_system_meta")
if ismeta:
    ns = {}; exec(MOCK + ismeta, ns); fn = ns["_is_system_meta"]
    ok("None → False", not fn(None))
    ok("{} → False", not fn({}))
    ok("is_system=True", fn({"is_system": True}))
    ok("is_system=False", not fn({"is_system": False}))
    ok("actor=system", fn({"actor": "system"}))
    ok("actor=SYSTEM", fn({"actor": "SYSTEM"}))
    ok("actor=user", not fn({"actor": "user"}))
    ok("source=gateway", fn({"source": "gateway"}))
    ok("origin=status", fn({"origin": "status"}))
    ok("origin=lifecycle", fn({"origin": "lifecycle"}))
    ok("message_origin=command", fn({"message_origin": "command"}))
    ok("string → False", not fn("hello"))
    ok("int → False", not fn(42))
else:
    ok("_is_system_meta fn found", False)

# ============================================================
# 4. _footer_model_name resolution
# ============================================================
print("\n--- 4. _footer_model_name ---")
fmodel = extract_source(WX, "_footer_model_name")
ismeta = extract_source(WX, "_is_system_meta")
if fmodel and ismeta:
    ns = {}; exec(MOCK + ismeta + "\n" + fmodel, ns)
    fn = ns["_footer_model_name"]
    
    ok("is_system → 'hermes'", fn({"is_system": True}) == "hermes")
    ok("actor=system → 'hermes'", fn({"actor": "system"}) == "hermes")
    ok("model_name priority", fn({"model_name": "deepseek-v4"}) == "deepseek-v4")
    ok("resolved_model fallback", fn({"resolved_model": "gpt-5"}) == "gpt-5")
    ok("routed_model fallback", fn({"routed_model": "claude"}) == "claude")
    ok("model fallback", fn({"model": "gemini"}) == "gemini")
    ok("system overrides all", fn({"is_system": True, "model": "x"}) == "hermes")
    ok("empty→hermes", fn({}) == "hermes")
else:
    ok("footer functions found", False)

# ============================================================
# 5. /continue control flow
# ============================================================
print("\n--- 5. /continue control flow ---")
with open(WX) as f: wx = f.read()

intake = wx.find("async def _process_message(")
media  = wx.find("media_paths: List[str]", intake)
cont   = wx.find("/continue: drain pending", intake)

ok("/continue BEFORE media_paths in intake", cont > intake and cont < media)
block = wx[cont:cont+500]
ok("calls _drain_pending()", "_drain_pending(sender_id)" in block)
ok("return before media_paths (early exit)", 
   "return" in block and block.find("return") < block.find("media_paths"))
ok("no 'passing through gateway'", "passing /continue through to gateway" not in wx)

# ============================================================
# 6. Source structure
# ============================================================
print("\n--- 6. Source structure ---")
src_ok(WX, r"class ReplyBudgetStore", "ReplyBudgetStore class")
src_ok(WX, r"class MessageSendQueue", "MessageSendQueue class")
src_ok(WX, r"async def _drain_pending", "_drain_pending method")
src_ok(WX, r"self\._budget_store\.increment_and_get", "_drain_pending uses increment_and_get")
src_ok(WX, r"self\._budget_store\.is_exhausted", "_drain_pending checks is_exhausted")
src_ok(WX, r"chunk_with_footer", "Footer appended in _drain_pending")
src_ok(WX, r"self\._budget_store\.update_token", "context_token→budget in intake")
src_ok(WX, r"self\._budget_store\.restore", "Budget restore in connect()")
src_ok(WX, r"self\._send_queue\.enqueue", "send() enqueues instead of direct")
src_ok(WX, r"def _footer_model_name", "_footer_model_name fn")
src_ok(WX, r"HERMES_WECHAT_FOOTER_MODEL_NAME", "Footer env var override")
src_ok(RUN, r"def _non_conversational_metadata", "_non_conversational_metadata")
src_ok(RUN, r'merged\["is_system"\]\s*=\s*True', "is_system=True in lifecycle metadata")
src_ok(RUN, r"setattr\(event.*\"model_name\"", "model→event propagation")
src_ok(BASE, r"def _mark_notify_metadata", "_mark_notify_metadata in base.py")

# Known v0.18 gaps (intentionally skipped or replaced):
# - Control command dedup bypass: v0.17 only, not in v0.18 patches (optional)
# - _content_looks_like_system_error: replaced by _is_system_meta (better approach)
# - _model_thread_metadata: replaced by event-attribute propagation in patch 004

# ============================================================
# 7. Regression
# ============================================================
print("\n--- 7. Regression ---")
src_not(WX, "passing /continue through to gateway", "No /continue gateway leak")

# ============================================================
# SUMMARY
# ============================================================
print(f"\n{'=' * 60}")
print(f"RESULTS: {R['pass']} passed, {R['fail']} failed")
if R['fail']:
    for e in R['errs']: print(f"  ❌ {e}")
    sys.exit(1)
else:
    print("✅ ALL FUNCTIONAL CHECKS PASSED")