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

## Patch 010: Context-token Kernel Hardening

Markers:

- `HERMES_WECHAT_SLASH_COMMAND_CONTENT_DEDUP_EXEMPTION_V1`
- `HERMES_WECHAT_CONTEXT_TOKEN_REFRESH_BEFORE_CONTENT_DEDUP_V1`
- `HERMES_WECHAT_CONTEXT_DELIVERY_SERIALIZATION_V1`
- `HERMES_WECHAT_CONTEXT_TOKEN_GENERATION_FENCE_V1`
- `HERMES_WECHAT_CONTEXT_BUDGET_RECONCILIATION_V1`
- `HERMES_WECHAT_MEDIA_CONTEXT_BUDGET_V1`

Apply order: `002 → 003 → 004 → 005 → 001 → 006 → 007 → 008 → 009 → 010`.

## Patch variant dispatch

Fresh installation is currently accepted for Hermes `v2026.7.1*` (v0.18).
The installer deterministically selects exactly one standard patch per series
entry. Files ending in `.v017.patch` are retained as historical migration
evidence and are never applied to v0.18.

## Ordinary-message queue drain contract

An ordinary inbound message itself is not an outbound queue item. After Hermes
generates its reply, every reply chunk is appended behind all existing pending
items and the same FIFO queue is drained immediately.

Example after a new Context token resets the counter:

```text
existing pending A
existing pending B
new ordinary-message reply C

send order:
A -> 1
B -> 2
C -> 3
pending -> 0
```

The current token's maximum remains 10 acknowledged messages. If the combined
queue exceeds the remaining budget, draining stops at 10 and unacknowledged
items remain pending for a later Context token.

Stable marker: `HERMES_WECHAT_ORDINARY_REPLY_APPEND_THEN_DRAIN_V1`.
## Consolidated Hermes v0.18 patch plan

Fresh installation on Hermes `v2026.7.1*` uses the deterministic series:

```text
003 -> 004 -> 006 -> 007 -> 008 -> 011
```

Patch `011-weixin-v018-consolidated.patch` is a clean diff from the official
v0.18 `weixin.py` to the accepted final runtime. It supersedes legacy Weixin
patches 001, 002, 005, 009 and 010 for fresh v0.18 installation. Those files
remain only as development and migration history and are not executed.

This removes the previously detected malformed patch 005 from the active
installation path while preserving all accepted runtime markers and behavior.

## Portable hook import bootstrap

The active hook no longer assumes that the Hermes data directory is always
`/opt/data`.

It resolves the installed skill directory in this order:

1. `HERMES_WECHAT_ENHANCE_SOURCE_DIR`;
2. `HERMES_SKILLS_DIR/hermes-wechat-enhance`;
3. `HERMES_HOME/skills/hermes-wechat-enhance`;
4. the sibling `skills` directory derived from the hook file location;
5. `/opt/data/skills/hermes-wechat-enhance` as a compatibility fallback.

Installation verification imports the copied hook without injecting an
artificial `PYTHONPATH` and requires `IMPORT_BOOTSTRAP_PORTABLE_OK`.

## Contract-harness adapter initialization

The isolated contract test now constructs `WeixinAdapter` through its real
constructor before replacing network sessions and test stores. This preserves
all official runtime fields, including `split_multiline_messages`, instead of
maintaining a fragile hand-written partial initializer.

Required preflight:

```text
SYNTHETIC_ADAPTER_RUNTIME_INIT_OK
```

This is a test-harness correction and does not change the production queue
contract.

## Idempotent hook deployment and zero residue

The private install-state snapshot is the only rollback source. The installer
never creates untracked `hermes-wechat-enhance.before-install-*` sibling
directories.

Hook equality ignores runtime cache artifacts such as `__pycache__`, `.pyc`,
`.pyo`, `.pytest_cache`, `.mypy_cache` and `.ruff_cache`. A second install
therefore remains a true no-op after the hook has been imported.

Stable marker:

```text
WECHAT_ENHANCE_HOOK_IDEMPOTENT_NO_BACKUP_RESIDUE_V1
```

Lifecycle acceptance checks every matching hook and skill sibling after both
uninstalls.

## v0.18 source-profile upgrade routing

The installer supports three explicitly recognized source profiles:

- `pristine-v018`: official `v2026.7.1` Weixin source, routed through patch 011;
- `legacy-v018`: the previously released Hermes WeChat Enhance runtime,
  identified by its exact Weixin SHA256 and routed through patch 012;
- `hardened-v018`: the final current runtime, where all patches are skipped by
  verified markers.

Unknown modified Weixin sources fail closed before gateway modification.

Patches 011 and 012 converge to the same byte-identical final Weixin source.
This allows both new third-party installation and guarded upgrade from the
current production-image baseline.

## Version resolution in stripped runtime images

The installer verifies the source profile before resolving the Hermes version.
Resolution order is: explicit override, Git tag, `VERSION`, installed package
metadata, then an inference restricted to the verified `pristine-v018`,
`legacy-v018` or `hardened-v018` profiles.

Unknown source content still fails closed before gateway modification.

Stable marker:

```text
HERMES_WECHAT_VERSION_FROM_VERIFIED_SOURCE_PROFILE_V1
```

## Hermes v0.18 version-family normalization

Hermes v0.18.0 may be represented by runtime package metadata as `v0.18.0`
while the corresponding official release tag is `v2026.7.1`. These identifiers
belong to the same accepted source and patch family.

Accepted identifiers are normalized to:

```text
VERSION_FAMILY=v2026.7.1
```

The original detected version and its provenance remain in the install log.
Source-profile verification still occurs first, and unknown versions or source
content fail closed.

Stable marker:

```text
HERMES_WECHAT_V018_VERSION_FAMILY_NORMALIZATION_V1
```

## Transactional canonical-source lifecycle

The transaction covers the three gateway files, active hook and canonical
installed skill source. Snapshotting occurs before canonical-source replacement.

Existing source and hook trees are restored after a failed install or normal
uninstall. Freshly created trees are removed. Timestamped source backup
directories are not created.

Uninstall is fail-closed when gateway, hook or canonical source content has
diverged from both pre-install and installed states. The install state and
external change are preserved.

Test-only fault stages are selected with
`HERMES_WECHAT_ENHANCE_FAULT_INJECT_STAGE`.

Stable markers:

```text
HERMES_WECHAT_TRANSACTIONAL_SOURCE_STATE_V1
HERMES_WECHAT_FAULT_INJECTION_TEST_V1
```

## Install-state canonical source-path integrity

The transaction snapshot keeps the canonical skill source parameter separate
from gateway-file iteration. Gateway files use a dedicated `gateway_file`
variable, preventing the manifest source path from being overwritten with
`gateway/run.py`.

A direct regression test requires:

```text
INSTALL_STATE_SOURCE_PATH_REGRESSION_OK
```

Stable marker:

```text
HERMES_WECHAT_TRANSACTION_SNAPSHOT_SOURCE_PATH_V2
```

## Git metadata and dirty working-tree preservation

The installer applies patches without `git init`, `git add`, `git commit`,
`git reset` or persistent `git config` changes. Distributed runtime images may
intentionally contain valid working-tree files that differ from embedded Git
HEAD.

Rollback and uninstall always restore the three managed gateway files from
byte-for-byte transaction snapshots. Git HEAD, index/status, config and
unrelated dirty files remain unchanged.

Direct regression marker:

```text
INSTALL_STATE_GIT_WORKTREE_PRESERVATION_OK
```

Stable markers:

```text
HERMES_WECHAT_GIT_METADATA_PRESERVATION_V1
HERMES_WECHAT_EXACT_FILE_BACKUP_RESTORE_V1
```
