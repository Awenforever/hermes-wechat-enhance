#!/usr/bin/env python3
"""Same-path regression suite for the hermes-wechat-enhance fixes (contract §7).

FAKE TRANSPORT EXPLICITLY MARKED: no network, no real WeChat, no real agent run.
Everything else drives REAL code:
  - REAL core `_sanitize_gateway_final_response` / `redact_for_egress` / `_guess_chat_type`
    / `_extract_text` / `WeixinAdapter` / `ContextTokenStore` / `TurnRunner._send_status_text`.
  - REAL plugin wrappers installed by `patch_gateway_runner`, `patch_turn_runner_status`,
    `patch_adapter`, and the real `MessageStore`.
Only the physical iLink send (`_send_text_chunk`) and core's `_process_message` /
`_run_agent_inner` bodies are replaced by recording stubs.

Each test asserts the FIXED behaviour and is written to FAIL on the pre-fix code:
  Q1  M2/M4 redaction-signature, M3 multi-bubble pop, M1 interim rail-B survival,
      plus the control-traffic safety invariant (fixes must NOT over-attribute).
  Q2  gap a (live-send failure schedules a retry), gap b (group backlog drains under
      the room id), gap c (tokenless inbound still drains), DM no-regression.
  Q5  audit 0600 (create + tighten pre-existing 0644), redaction before persist,
      rotation of messages.jsonl while pending.jsonl never rotates.
"""
from __future__ import annotations

import asyncio
import os
import stat
import sys
import tempfile
from pathlib import Path
from types import MethodType

ROOT = Path(os.environ.get("HERMES_WECHAT_ENHANCE_SOURCE_DIR", str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(ROOT))
GATEWAY_SRC = os.environ.get("HERMES_GATEWAY_SRC", "/opt/hermes")
if GATEWAY_SRC not in sys.path:
    sys.path.insert(0, GATEWAY_SRC)

ACCOUNT = "acct-r"
PEER = "peer-r"
MEMBER = "member-g"
ROOM = "room-g@chatroom"
REAL_MODEL = "deepseek-flash"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def check_posix_mode(name: str, path: Path, expected: int) -> None:
    # Windows has no POSIX mode bits: os.chmod(0o600) cannot be observed via st_mode.
    if os.name == "nt":
        print(f"  [SKIP] {name} :: POSIX modes N/A on Windows (NTFS ACLs)")
        return
    mode = stat.S_IMODE(os.stat(path).st_mode)
    check(name, mode == expected, f"mode={oct(mode)}")


def footer_of(chunk: str) -> str:
    return chunk.split("\n\n---\n\n", 1)[-1]


def model_of(chunk: str) -> str:
    parts = footer_of(chunk).strip().split("`")
    parts = [p for p in parts if p.strip()]
    return parts[-1].strip() if parts else ""


def get_platform():
    for mod, name in (("gateway.platforms.base", "Platform"), ("gateway.config", "Platform"),
                      ("gateway.run_turn", "Platform")):
        try:
            m = __import__(mod, fromlist=[name])
            P = getattr(m, name)
            if hasattr(P, "WEIXIN"):
                return P.WEIXIN
        except Exception:
            continue
    class _P:
        value = "weixin"
    return _P()


def build_adapter(home: str, sent: list, *, transport_raises: BaseException | None = None):
    """Real WeixinAdapter with only the physical send faked (marked FAKE TRANSPORT)."""
    from gateway.config import PlatformConfig
    from gateway.platforms.weixin import WeixinAdapter
    from gateway.platforms import weixin as wxmod

    adapter = WeixinAdapter(PlatformConfig(
        enabled=True, token="test-token",
        extra={"account_id": ACCOUNT, "send_chunk_delay_seconds": 0},
    ))
    adapter._token_store = wxmod.ContextTokenStore(home)
    adapter._send_session = object()

    state = {"raise": transport_raises}

    async def fake_transport(_self, *, chat_id, chunk, context_token, client_id):
        # FAKE TRANSPORT: records the physical bubble; optionally raises to simulate
        # a transient iLink failure.  No network is touched.
        if state["raise"] is not None:
            exc = state["raise"]
            state["raise"] = None  # fail once, then recover
            raise exc
        sent.append((chat_id, chunk, context_token, client_id))

    adapter._send_text_chunk = MethodType(fake_transport, adapter)
    adapter._fake_transport_state = state

    processed: list = []

    async def fake_process_message(_self, message):
        # FAKE CORE HANDLER: records that core processing was reached; no agent run.
        processed.append(message)
        return None

    adapter._process_message = MethodType(fake_process_message, adapter)
    adapter._fake_processed = processed
    return adapter


def make_source(plat, chat_id):
    class Src:
        pass
    src = Src()
    src.platform = plat
    src.chat_id = chat_id
    return src


# ═══════════════════════════ Q1: model attribution ═══════════════════════════
async def t_q1_m2m4_redaction_signature(home: str):
    """Runner-boundary signature must be the SANITIZED body so a redacted final still binds."""
    import hermes_wechat_enhance.v021_bubble_footer as bf
    from gateway.run import _sanitize_gateway_final_response

    print("=== Q1 M2/M4: redacted final attributes via real patch_gateway_runner ===")
    PLAT = get_platform()
    raw = (
        "## 诊断：PAT 权限不足\n\n"
        "你的 token `github_pat_11ABCDEFG_pa1bcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJ` "
        f"缺少 org 级权限。经典 token（`{'ghp_AB' + 'SYNTHETIC' * 4}`）需要 repo+read:org。\n\n"
        "| 场景 | 权限 |\n|---|---|\n| 读 issue | repo |\n"
    )
    shaped = _sanitize_gateway_final_response(PLAT, raw)
    discriminating = shaped.strip()[:500] != raw.strip()[:500]
    check("M2/M4 precondition: redaction changes first 500 chars", discriminating,
          "raw==shaped would make this test vacuous")

    bf._TURN_MODELS.clear()

    class RunnerStub:
        def _resolve_session_agent_runtime(self, *, source):
            return (REAL_MODEL, {"runtime": "stub"})

        async def _run_agent_inner(self, *, source):
            return {"final_response": raw, "model_name": REAL_MODEL}

    runner = RunnerStub()
    assert bf.patch_gateway_runner(runner) is True
    src = make_source(PLAT, PEER)
    runner._resolve_session_agent_runtime(source=src)          # seeds pending (completed=False)
    await runner._run_agent_inner(source=src)                  # records completed signature

    entry = bf._TURN_MODELS.get(PEER)
    recorded_sig = entry[3] if entry else ""
    check("M2/M4 recorded signature == sanitized delivery (not raw)",
          recorded_sig == shaped.strip()[:500],
          f"recorded[:40]={recorded_sig[:40]!r}")

    resolved, completed = bf._resolve_model(PEER, shaped, {})
    check("M2/M4 redacted final resolves to real model", resolved == REAL_MODEL and completed,
          f"resolved={resolved!r} completed={completed}")
    bf._TURN_MODELS.clear()
    print()


async def t_q1_m3_multibubble(home: str):
    """A multi-send turn must attribute EVERY bubble; the completed entry is no longer popped."""
    import hermes_wechat_enhance.v021_bubble_footer as bf

    print("=== Q1 M3: multi-bubble final keeps attributing (pop removed) ===")
    sent: list = []
    a = build_adapter(home, sent)
    assert bf.patch_adapter(a) is True
    bf._TURN_MODELS.clear()
    final_text = "第一段最终回复内容，比较长的那种，会被拆成多个气泡发送。"
    bf.register_turn_model({"platform": "weixin", "chat_id": PEER, "model": REAL_MODEL, "response": final_text})

    await a.send(PEER, final_text, metadata={})
    m1 = model_of(sent[-1][1])
    registry_after_1 = bf._TURN_MODELS.get(PEER)
    await a.send(PEER, final_text + "（续）", metadata={})
    m2 = model_of(sent[-1][1])

    check("M3 bubble#1 attributes to real model", m1 == REAL_MODEL, f"footer={footer_of(sent[-2][1])!r}")
    check("M3 registry survives bubble#1 (not consumed)", registry_after_1 is not None)
    check("M3 bubble#2 attributes to real model", m2 == REAL_MODEL, f"footer={footer_of(sent[-1][1])!r}")
    bf._TURN_MODELS.clear()
    print()


async def t_q1_m1_interim_rail_b(home: str):
    """Interim rail-B commentary attributes when the registry is seeded; empty stays hermes."""
    import hermes_wechat_enhance.v021_bubble_footer as bf
    from gateway.run_turn_runner import TurnRunner

    print("=== Q1 M1: interim rail-B (_send_status_text) attribution ===")
    bf.patch_turn_runner_status()
    assert getattr(TurnRunner, "_hermes_wechat_interim_origin_v1", False)
    PLAT = get_platform()

    class Ctx:
        pass

    def make_stub(adapter):
        ctx = Ctx()
        ctx.source = make_source(PLAT, PEER)
        ctx._status_adapter = adapter
        ctx._status_chat_id = PEER
        ctx._status_thread_metadata = {}
        stub = Ctx()
        stub._ctx = ctx
        scheduled: list = []
        stub._schedule = lambda coro, msg: (scheduled.append(coro), None)[1]
        return stub, scheduled

    async def drive(text: str, log_message: str = "interim_assistant_callback scheduling error"):
        sent: list = []
        a = build_adapter(home, sent)
        bf.patch_adapter(a)
        stub, scheduled = make_stub(a)
        TurnRunner._send_status_text(stub, text, {}, log_message)
        for coro in scheduled:
            await coro
        return sent[-1][1] if sent else ""

    # M1 fix: a surviving pending/completed entry (no longer popped mid-turn) lets rail-B attribute.
    bf._TURN_MODELS.clear()
    bf._remember_model(PEER, REAL_MODEL, completed=False)
    chunk = await drive("## ✅ 全部完成 (interim commentary)")
    check("M1 interim (pending seeded) attributes to real model", model_of(chunk) == REAL_MODEL,
          f"footer={footer_of(chunk)!r}")

    bf._TURN_MODELS.clear()
    bf._remember_model(PEER, REAL_MODEL, completed=True, response="an earlier final")
    chunk = await drive("## ✅ 全部完成 (interim commentary)")
    check("M1 interim (completed present) attributes to real model", model_of(chunk) == REAL_MODEL,
          f"footer={footer_of(chunk)!r}")

    # Documented fail-closed: with NO provenance at all, interim stays hermes (by design, not a regression).
    bf._TURN_MODELS.clear()
    chunk = await drive("## ✅ 全部完成 (interim commentary)")
    check("M1 interim (empty registry) fails closed to hermes", model_of(chunk) == "hermes",
          f"footer={footer_of(chunk)!r}")

    # Non-interim system status must never borrow the model even when the registry is seeded.
    bf._TURN_MODELS.clear()
    bf._remember_model(PEER, REAL_MODEL, completed=False)
    chunk = await drive("⏩ Steer queued", log_message="status_callback (steer) scheduling error")
    check("M1 non-interim status stays hermes", model_of(chunk) == "hermes", f"footer={footer_of(chunk)!r}")
    bf._TURN_MODELS.clear()
    print()


async def t_q1_control_safety(home: str):
    """CRITICAL: removing the pop must NOT let control traffic borrow the active model."""
    import hermes_wechat_enhance.v021_bubble_footer as bf

    print("=== Q1 safety: control traffic stays hermes with a completed entry present ===")
    sent: list = []
    a = build_adapter(home, sent)
    bf.patch_adapter(a)
    bf._TURN_MODELS.clear()
    final_text = "这是模型的最终回复正文，用于登记 completed 签名。"
    bf.register_turn_model({"platform": "weixin", "chat_id": PEER, "model": REAL_MODEL, "response": final_text})

    # Busy-ack / steer control text does not prefix-match the model final -> hermes.
    await a.send(PEER, "⏩ Steered into current run…. Your message arrives after the next tool call.", metadata={})
    check("safety: busy-ack (non-matching) stays hermes", model_of(sent[-1][1]) == "hermes",
          f"footer={footer_of(sent[-1][1])!r}")

    # is_system short-circuits even when the content WOULD prefix-match the final.
    await a.send(PEER, final_text, metadata={"is_system": True})
    check("safety: is_system content stays hermes", model_of(sent[-1][1]) == "hermes",
          f"footer={footer_of(sent[-1][1])!r}")

    # actor=system short-circuits.
    await a.send(PEER, final_text, metadata={"actor": "system"})
    check("safety: actor=system stays hermes", model_of(sent[-1][1]) == "hermes",
          f"footer={footer_of(sent[-1][1])!r}")

    # A genuine matching model final still attributes (fix did not break the happy path).
    await a.send(PEER, final_text, metadata={})
    check("safety: matching model final still attributes", model_of(sent[-1][1]) == REAL_MODEL,
          f"footer={footer_of(sent[-1][1])!r}")
    bf._TURN_MODELS.clear()
    print()


# ═══════════════════════════ Q2: FIFO drain ═══════════════════════════
async def t_q2_gap_a_live_failure_schedules_retry(home: str):
    """A transient LIVE send failure must enqueue AND schedule a deferred retry (gap a)."""
    import hermes_wechat_enhance.v021_bubble_footer as bf

    print("=== Q2 gap a: live-send failure schedules retry ===")
    sent: list = []
    a = build_adapter(home, sent, transport_raises=RuntimeError("cooldown retry 1s"))
    bf.patch_adapter(a)
    queue = a._hermes_wechat_v021_pending_queue
    await bf._set_context_token(a._token_store, ACCOUNT, PEER, "tok-a")

    # Drive the plugin's send_text_chunk wrapper directly (core send calls this per chunk).
    await a._send_text_chunk(chat_id=PEER, chunk="live bubble that fails", context_token="tok-a", client_id="c1")

    check("gap a: failed live bubble enqueued", queue.count(ACCOUNT, PEER) == 1,
          f"pending={queue.count(ACCOUNT, PEER)}")
    tasks = a._hermes_wechat_v021_retry_tasks
    check("gap a: deferred retry scheduled (not orphaned)", PEER in tasks and not tasks[PEER].done(),
          f"retry_tasks={list(tasks)}")
    for t in list(tasks.values()):
        t.cancel()
    await asyncio.gather(*tasks.values(), return_exceptions=True)

    # The enqueued backlog is drainable once the transport recovers (fake_transport fails once).
    result = await a._drain_pending(PEER)
    check("gap a: backlog drains after recovery", bool(result.get("ok")) and queue.count(ACCOUNT, PEER) == 0,
          f"result={result}")
    print()


async def t_q2_gap_b_group_drain(home: str):
    """Group backlog (enqueued under the room id) must drain on a member's inbound (gap b)."""
    import hermes_wechat_enhance.v021_bubble_footer as bf

    print("=== Q2 gap b: group backlog drains under room id ===")
    sent: list = []
    a = build_adapter(home, sent)
    bf.patch_adapter(a)
    queue = a._hermes_wechat_v021_pending_queue
    # A prior failed group send enqueued under the ROOM id (the physical destination).
    queue.enqueue(ACCOUNT, ROOM, "c0", "queued group bubble", REAL_MODEL)
    check("gap b precondition: backlog keyed by room id", queue.count(ACCOUNT, ROOM) == 1)

    msg = {
        "from_user_id": MEMBER, "room_id": ROOM, "context_token": "tok-g",
        "message_id": "mg1", "item_list": [{"type": 1, "text_item": {"text": "hello"}}],
    }
    await a._process_message(msg)

    check("gap b: room-id backlog drained by member inbound", queue.count(ACCOUNT, ROOM) == 0,
          f"room pending={queue.count(ACCOUNT, ROOM)}")
    drained = [c for (cid, c, _t, _cl) in sent if cid == ROOM and "queued group bubble" in c]
    check("gap b: queued group bubble physically sent to room", bool(drained),
          f"sent_to_room={len(drained)}")
    check("gap b: token stored under sender_id (core parity)",
          a._token_store.get(ACCOUNT, MEMBER) == "tok-g")
    check("gap b: core processing still reached", len(a._fake_processed) == 1)
    print()


async def t_q2_gap_c_tokenless_drain(home: str):
    """An inbound WITHOUT a context_token must still drain a backlog using the stored token (gap c)."""
    import hermes_wechat_enhance.v021_bubble_footer as bf

    print("=== Q2 gap c: tokenless inbound still drains ===")
    sent: list = []
    a = build_adapter(home, sent)
    bf.patch_adapter(a)
    queue = a._hermes_wechat_v021_pending_queue
    await bf._set_context_token(a._token_store, ACCOUNT, PEER, "prior-token")
    queue.enqueue(ACCOUNT, PEER, "c0", "stranded bubble", REAL_MODEL)

    msg = {"from_user_id": PEER, "message_id": "md1",
           "item_list": [{"type": 1, "text_item": {"text": "hello"}}]}  # NO context_token
    await a._process_message(msg)

    check("gap c: tokenless inbound drained the backlog", queue.count(ACCOUNT, PEER) == 0,
          f"pending={queue.count(ACCOUNT, PEER)}")
    check("gap c: stranded bubble physically sent",
          any("stranded bubble" in c for (_id, c, _t, _cl) in sent))
    print()


async def t_q2_dm_no_regression(home: str):
    """DM inbound with a token drains under sender_id==effective_chat_id and reaches core (no regression)."""
    import hermes_wechat_enhance.v021_bubble_footer as bf

    print("=== Q2 DM no-regression ===")
    sent: list = []
    a = build_adapter(home, sent)
    bf.patch_adapter(a)
    queue = a._hermes_wechat_v021_pending_queue
    queue.enqueue(ACCOUNT, PEER, "c0", "dm backlog bubble", REAL_MODEL)

    msg = {"from_user_id": PEER, "context_token": "tok-d", "message_id": "md2",
           "item_list": [{"type": 1, "text_item": {"text": "hello"}}]}
    await a._process_message(msg)

    check("DM: token stored under sender_id", a._token_store.get(ACCOUNT, PEER) == "tok-d")
    check("DM: backlog drained", queue.count(ACCOUNT, PEER) == 0)
    check("DM: core processing reached", len(a._fake_processed) == 1)
    print()


# ═══════════════════════════ Q5: audit store hardening ═══════════════════════════
def t_q5_permissions(home: str):
    import hermes_wechat_enhance.store as st

    print("=== Q5: audit file permissions 0600 (create + tighten) ===")
    with tempfile.TemporaryDirectory(prefix="q5perm-") as d:
        store = st.MessageStore(base_dir=d)
        store.append({"platform": "weixin", "user_id": PEER, "direction": "in", "content": "hi"})
        check_posix_mode("Q5 new messages.jsonl is 0600", store.messages_path, 0o600)

        # Pre-existing world-readable file (the production defect) is tightened on next append.
        os.chmod(store.messages_path, 0o644)
        store.append({"platform": "weixin", "user_id": PEER, "direction": "in", "content": "again"})
        check_posix_mode("Q5 pre-existing 0644 tightened to 0600", store.messages_path, 0o600)

        store.append_pending(PEER, "pending content")
        check_posix_mode("Q5 pending.jsonl is 0600", store.pending_path, 0o600)
    print()


def t_q5_redaction(home: str):
    import hermes_wechat_enhance.store as st

    print("=== Q5: secrets redacted before persisting ===")
    secret = 'ghp_AB' + 'SYNTHETIC' * 4
    with tempfile.TemporaryDirectory(prefix="q5red-") as d:
        store = st.MessageStore(base_dir=d)
        store.append({"platform": "weixin", "user_id": PEER, "direction": "in",
                      "content": f"my token is {secret} please use it"})
        raw_file = store.messages_path.read_text(encoding="utf-8")
        check("Q5 raw secret NOT persisted verbatim", secret not in raw_file)
        check("Q5 redaction marker present", "ghp_AB" in raw_file and "..." in raw_file,
              f"snippet={raw_file[:120]!r}")
    print()


def t_q5_rotation(home: str):
    import hermes_wechat_enhance.store as st

    print("=== Q5: audit rotation (messages rotate, pending never) ===")
    with tempfile.TemporaryDirectory(prefix="q5rot-") as d:
        old_max, old_backup = st.AUDIT_MAX_BYTES, st.AUDIT_BACKUP_COUNT
        st.AUDIT_MAX_BYTES = 200
        st.AUDIT_BACKUP_COUNT = 2
        try:
            store = st.MessageStore(base_dir=d)
            for i in range(40):
                store.append({"platform": "weixin", "user_id": PEER, "direction": "in",
                              "content": f"message number {i} with some padding to grow the audit log"})
            live = store.messages_path
            check("Q5 messages.jsonl rotated (.1 exists)", Path(f"{live}.1").exists())
            check("Q5 live messages.jsonl bounded under max",
                  os.stat(live).st_size <= st.AUDIT_MAX_BYTES + 4096,
                  f"size={os.stat(live).st_size}")
            # Backups are owner-only too.
            check_posix_mode("Q5 rotated backup is 0600", Path(f"{live}.1"), 0o600)

            # Pending must NEVER rotate (losing it would drop undelivered bubbles).
            for i in range(40):
                store.append_pending(PEER, f"pending bubble {i} with padding to grow the queue file")
            check("Q5 pending.jsonl does NOT rotate", not Path(f"{store.pending_path}.1").exists(),
                  f"pending_size={os.stat(store.pending_path).st_size}")
        finally:
            st.AUDIT_MAX_BYTES, st.AUDIT_BACKUP_COUNT = old_max, old_backup
    print()


async def main():
    with tempfile.TemporaryDirectory(prefix="hwe-reg-") as home:
        os.environ["HERMES_HOME"] = home
        await t_q1_m2m4_redaction_signature(home)
        await t_q1_m3_multibubble(home)
        await t_q1_m1_interim_rail_b(home)
        await t_q1_control_safety(home)
        await t_q2_gap_a_live_failure_schedules_retry(home)
        await t_q2_gap_b_group_drain(home)
        await t_q2_gap_c_tokenless_drain(home)
        await t_q2_dm_no_regression(home)
        t_q5_permissions(home)
        t_q5_redaction(home)
        t_q5_rotation(home)

    passed = sum(1 for _n, ok, _d in RESULTS if ok)
    failed = [(n, d) for (n, ok, d) in RESULTS if not ok]
    print("=" * 64)
    print(f"REGRESSION SUMMARY: {passed}/{len(RESULTS)} passed, {len(failed)} failed")
    for n, d in failed:
        print(f"  FAILED: {n} :: {d}")
    print("REGRESSION_FIXES_DONE" if not failed else "REGRESSION_FIXES_FAILED")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
