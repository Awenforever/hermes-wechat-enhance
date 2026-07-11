# v0.17 Full Migration Audit Methodology

## Three-Way Diff Procedure

When migrating v0.17 WeChat customizations to a new Hermes version (e.g., v0.18 / v2026.7.1), do NOT guess at what changed. Use this deterministic procedure:

### Step 1: Clone official versions

```bash
git clone --depth 1 --branch v2026.6.19 https://github.com/NousResearch/hermes-agent.git /tmp/hermes-v17-official
git clone --depth 1 --branch v2026.7.1  https://github.com/NousResearch/hermes-agent.git /tmp/hermes-v18-official
```

### Step 2: Diff production v0.17 vs official v0.17

```bash
diff -u /tmp/hermes-v17-official/gateway/platforms/weixin.py /opt/hermes/gateway/platforms/weixin.py
diff -u /tmp/hermes-v17-official/gateway/platforms/base.py   /opt/hermes/gateway/platforms/base.py
diff -u /tmp/hermes-v17-official/gateway/run.py              /opt/hermes/gateway/run.py
```

Count lines: `+N/-M` tells you how many lines were added/removed. Every `HERMES_V017_*` comment marks a deliberate customization block.

### Step 3: Diff patched v0.18 vs official v0.18

```bash
# Extract files from patched Docker image
docker run --rm --entrypoint cat hermes-agent:v0.18.0-patched /opt/hermes/gateway/platforms/weixin.py > /tmp/patched-weixin.py

diff -u /tmp/hermes-v18-official/gateway/platforms/weixin.py /tmp/patched-weixin.py
```

### Step 4: Cross-reference

For each customization found in Step 2, verify it appears in Step 3's diff. Any missing item is a **migration gap**.

Use `grep -n "HERMES_V017\|ReplyBudgetStore\|_drain_pending\|_non_conversational"` on the patched files to quickly verify.

## Audit Results (2026-07-07)

Production v0.17 has **28 customizations** across 3 files (+539 lines):

| File | Items | Lines |
|------|-------|-------|
| weixin.py | 17 | +371 |
| base.py | 5 | +85 |
| run.py | 4 | +83 |
| (hooks: Hermes Alive) | 2 | — |

v0.18 patched image (`hermes-agent:v0.18.0-weixin-enhanced-audit1`) had **3 gaps**:

1. **Patch 001** — /continue interception is BROKEN. Only adds debug log, no `_drain_pending()` + `return`.
2. **Hooks not loaded** — `--accept-hooks` missing from gateway command. Hermes Alive never started → no startup notification.
3. **Protocol leak guard** — intentionally skipped (optional enhancement).

## Critical: Patch 001 /continue Architecture

**Broken approach (current patch):**
```python
if text.strip() == "/continue":
    logger.debug("passing /continue through to gateway command router")
# Falls through → gateway sees unrecognized command → "unknown command" notice
```

**Correct approach (v0.17 production):**
```python
if text.strip() == "/continue":
    drained = await self._drain_pending(sender_id)
    if drained.message_id is not None:
        logger.info("[/continue drained backlog for %s", ...)
    return  # ← Early return. Never reaches gateway.
```

**Why the broken approach fails:** The gateway command router receives `/continue` as text. It strips the `/`, checks for known commands — `continue` is NOT a registered gateway command → sends "unrecognized slash command" notice. The notice carries the session's model metadata, not `is_system` → footer shows model name instead of `hermes`.

**Correct fix:** Patch 001 must intercept `/continue` in `weixin.py` intake method and handle it entirely there (drain pending queue, return). Never let `/continue` reach the gateway.

## Hooks Loading Requirement

Gateway must be started with `--accept-hooks`:
```bash
hermes gateway run --no-supervise --accept-hooks -v
```

Missing `--accept-hooks` means:
- No `[hooks] Loaded hook ...` in startup log
- Hermes Alive watcher never starts
- No gateway startup notification sent to user
- No proactive messaging

Verify with: `docker logs <container> 2>&1 | grep -i "hooks\|alive"`