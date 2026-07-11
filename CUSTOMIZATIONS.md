# Hermes WeChat Enhance — Customization Checklist

> **Purpose:** Track EVERY customization made to Hermes gateway source files, for seamless upgrades from v0.18 → v0.19 and beyond.
>
> **Last updated:** 2026-07-07 (v0.18 migration audit)
>
> **Apply order:** 002 → 003 → 004 → 005 → 001

---

## Summary

| Category | Files | Lines | Patches |
|----------|-------|-------|---------|
| Budget + Queue | weixin.py | ~200 | 005 |
| Footer (model + count) | weixin.py | ~80 | 002, 005 |
| /continue interception | weixin.py | ~7 | 001 |
| System metadata marking | base.py, run.py | ~80 | 003 |
| Model name propagation | base.py, run.py | ~60 | 004 |
| Protocol leak guard | weixin.py | ~38 | SKIPPED |
| Cron badge override | weixin.py | ~5 | SKIPPED |
| **TOTAL** | | **~470 lines** | **5 patches** |

---

## Patch-by-Patch Audit

### Patch 001: /continue Interception

**File:** `gateway/platforms/weixin.py`  
**Lines:** ~7 added  
**Must apply AFTER 005** (requires `_drain_pending()`)

**What it does:**
- Intercepts `/continue` text in the intake method BEFORE event creation
- Calls `_drain_pending(sender_id)` to flush queued messages
- Returns early — never routes `/continue` to gateway command router or agent

**Insertion point:** After `_maybe_fetch_typing_ticket()` call in intake, before `media_paths`

**v0.17 equivalent:** `HERMES_V017_WEIXIN_CONTINUE_DRAIN_PARITY_V1` (6 lines)

**Upgrade hazard:** Insertion line numbers shift when upstream adds code before the intake method. Regenerate patch with `diff -u` targeting the `asyncio.create_task(self._maybe_fetch_typing_ticket` call site context.

---

### Patch 002: Footer Model Name

**File:** `gateway/platforms/weixin.py`  
**Lines:** ~15 added

**What it does:**
- Adds inline footer logic to `send()` method
- Reads `is_system` from metadata to decide: `hermes` vs actual model name
- Appends footer to text chunks: `` `{count}` `{model}` ``

**Upgrade hazard:** Modifies `send()` method. If upstream refactors send(), regenerate.

---

### Patch 003: System Metadata Tagging

**Files:** `gateway/platforms/base.py`, `gateway/run.py`  
**Lines:** ~80 added

**What it does:**
- `_non_conversational_metadata()` in run.py: tags lifecycle/status/platform messages with `is_system=True`
- `_mark_hermes_system_notify_metadata()` in base.py: marks slash command results as system
- All "Hermes-authored" messages (commands, errors, status) get `is_system=True` → footer renders `hermes`

**Upgrade hazard:** Touch points in both files. If upstream changes the metadata flow or adds new message types, verify ALL system message paths still get tagged.

---

### Patch 004: Model Name Propagation Chain

**Files:** `gateway/platforms/base.py`, `gateway/run.py`  
**Lines:** ~60 added

**What it does:**
- Extracts `agent.model` → `agent_result["model"]` → `event.model_name` → `_thread_metadata["model_name"]`
- Multi-level fallback: agent_result.model → model_name → resolved_model → event attributes → `_last_resolved_model`
- Fixes `_mark_notify_metadata(None)` crash in base.py

**Data flow:**
```
agent.model → agent_result["model"] → event.model_name
→ _thread_metadata["model_name"] → adapter.send(metadata)
→ weixin footer
```

**Upgrade hazard:** If upstream changes agent_result structure or removes the `model` field, this chain breaks. Verify by checking `_run_agent_inner()` return value includes model field.

---

### Patch 005: Reply Budget + Send Queue

**File:** `gateway/platforms/weixin.py`  
**Lines:** ~330 added (largest patch)  
**Must apply AFTER 002** (references footer metadata)

**What it does:**
1. **ReplyBudgetStore** class (~55 lines): persistent per-token message budget (10 msgs/token)
2. **MessageSendQueue** class (~55 lines): FIFO outbound queue
3. **Context token → budget**: `_budget_store.update_token()` on new context_token
4. **_drain_pending()**: drains queue with budget check + footer per chunk
5. **send() rewrite**: text chunks enqueued instead of directly sent
6. **Footer helpers**: `_is_system_meta()`, `_footer_model_name()`
7. **Control command dedup bypass**: /approve, /deny, /steer, /continue, etc.
8. **Content heuristic disabled**: `_content_looks_like_system_error` always returns False
9. **Image metadata fix**: media sends use footer_metadata

**Number of hunks:** 6 (classes + init + connect + intake + dedup + send)

**Upgrade hazard:** Very large, touches multiple methods. If upstream refactors weixin.py substantially, this patch will likely need regeneration. The `ReplyBudgetStore` and `MessageSendQueue` classes are self-contained and less likely to conflict.

---

## Intentionally Skipped Features

| Feature | Reason | Decision Date |
|---------|--------|---------------|
| Protocol leak guard (visible) | Optional enhancement; suppresses raw tool XML in chat | 2026-07-06 |
| Protocol leak guard (low-level) | Optional; same purpose in send_message_low_level | 2026-07-06 |
| Cron badge override | Cron messages share same counter; separate badge not needed | 2026-07-06 |

If desired, these can be added as additional patches. Code exists in v0.17 production weixin.py (tagged `HERMES_V017_WEIXIN_VISIBLE_PROTOCOL_GUARD_HELPERS_V2` and `HERMES_V017_WEIXIN_LOW_LEVEL_PROTOCOL_LEAK_GUARD_V2`).

---

## Hook Requirements

| Component | Purpose | Required |
|-----------|---------|----------|
| `--accept-hooks` flag | Load hooks on gateway startup | YES |
| `hermes-alive` hook | Startup notification ("✨ Gateway online — Hermes is back and ready.") | YES |
| `hermes-wechat-enhance` hook | JSONL message capture (optional) | No |
| `HERMES_WEIXIN_STARTUP_READY_NOTIFY=1` | Enable startup notification | Default |

---

## Upgrade Protocol (v0.18 → v0.19)

1. **Clone new version** and official source
2. **Run `git apply --check`** for each patch (order: 002→003→004→005→001)
3. If any patch fails:
   - Read the error to identify the conflicting context
   - Check upstream diff for breaking changes
   - Regenerate the failing patch targeting the new source
4. **Compile check**: `python3 -c "import py_compile; py_compile.compile('gateway/platforms/weixin.py', doraise=True)"`
5. **Feature verification**: run verify script (see below)
6. **Archive old patches** with version suffix (e.g., `*.v018.patch`)
7. **Update this file** with changes

---

## Verification Checklist

After applying all patches, verify:

- [ ] weixin.py compiles without syntax errors
- [ ] base.py compiles
- [ ] run.py compiles
- [ ] ReplyBudgetStore class present
- [ ] MessageSendQueue class present
- [ ] `_drain_pending()` method present
- [ ] `/continue` intercepts and returns early (not passed to gateway)
- [ ] Footer logic: `is_system=True` → `hermes`, else model name
- [ ] `_non_conversational_metadata()` marks lifecycle messages
- [ ] `_mark_hermes_system_notify_metadata()` exists in base.py
- [ ] Model name propagation chain intact (agent→event→metadata→footer)
- [ ] `--accept-hooks` in gateway command
- [ ] Hermes Alive hook loaded (check logs for "hermes-alive-proactive")
- [ ] Startup notification sent on connect

---

## File Version History

| Hermes Version | Patch Set | Status |
|---------------|-----------|--------|
| v0.17 (v2026.6.19) | `.v017.patch` set | Production |
| v0.18 (v2026.7.1) | Current patches (001-005) | In testing |
| v0.19 (future) | TBD | Regenerate from this checklist |

## Patch inventory 001–009

Current maintained patch IDs:

- 001
- 002
- 003
- 004
- 005
- 006
- 007
- 008
- 009

Current patch files:

- `patches/001-weixin-continue-hook.patch`
- `patches/001-weixin-continue-hook.v017.patch`
- `patches/002-weixin-footer-hook.patch`
- `patches/002-weixin-footer-hook.v017.patch`
- `patches/003-gateway-system-metadata.patch`
- `patches/004-gateway-model-propagation.patch`
- `patches/005-weixin-send-queue.patch`
- `patches/006-gateway-interim-model-metadata.patch`
- `patches/007-gateway-interim-model-strict-source.patch`
- `patches/008-gateway-footer-model-full-send-rails.patch`
- `patches/009-weixin-reliable-delivery-contract.patch`

