---
name: hermes-wechat-enhance
description: "Use when working on Hermes WeChat gateway enhancements: startup-ready lifecycle notification, JSONL message capture, /continue pass-through, footer with context-token count + model name, and patch management (001-005 for v0.18 migration)."
---

# Hermes WeChat Enhance

This skill provides Hermes WeChat enhancement artifacts without modifying the production gateway tree.

## Contents

- `hooks/hermes-wechat-enhance/`: Hermes hook package. Subscribes to `gateway:startup`, `agent:start`, and `agent:end` — sends the WeChat startup-ready notification and captures inbound/outbound messages to JSONL store.
- `hermes_wechat_enhance/`: self-contained Python helpers used by the hook handler, including `startup_ready.py`.
- `patches/001-weixin-continue-hook.patch`: /continue interception. **Must be applied LAST.**
- `patches/002-weixin-footer-hook.patch`: Inline footer model name from metadata.
- `patches/003-gateway-system-metadata.patch`: Tag system messages `is_system=True`.
- `patches/004-gateway-model-propagation.patch`: agent.model → event → metadata chain.
- `patches/005-weixin-send-queue.patch`: ReplyBudgetStore + MessageSendQueue + footer count.
- `CUSTOMIZATIONS.md`: Complete modification checklist + upgrade protocol.
- `IMPACT_MATRIX.md`: Change impact tracking — which scripts to update when modifying a feature.
- `scripts/install.sh`: One-command install (version detect → git pristine → apply patches → hooks).
- `scripts/update.sh`: Revert to pristine → apply new patches → restore user changes.
- `scripts/uninstall.sh`: Git checkout pristine → remove hooks.
- `scripts/check-consistency.sh`: Audit patches vs docs cross-references.
- `verify-v18.py`: Functional verification (63 checks).
- `references/development-blueprint.md`: **Cross-session recall anchor** — architecture, conventions, lifecycle, task list.

## Install Hooks

Install by copying or symlinking the hook directory into the Hermes hook scan path:

```bash
mkdir -p ~/.hermes/hooks
ln -sfn /opt/data/skills/hermes-wechat-enhance/hooks/hermes-wechat-enhance ~/.hermes/hooks/hermes-wechat-enhance
```

Make the helper package importable by the gateway hook runtime:

```bash
export PYTHONPATH="/opt/data/skills/hermes-wechat-enhance:${PYTHONPATH:-}"
```

**Note:** The `hermes-wechat-enhance` hook also requires `PYTHONPATH` to include the skill directory. Without it, the hook handler's imports fail with `ImportError`. Set this in your Dockerfile or environment configuration:

```dockerfile
ENV PYTHONPATH="/opt/data/skills/hermes-wechat-enhance:${PYTHONPATH}"
```

Restart Hermes gateway after installing the hook.

## Message Storage

The hook stores captured messages in:

```text
~/.hermes/wechat_enhance/messages.jsonl
```

Each record includes `message_id`, `platform`, `user_id`, `chat_id`, `session_id`, `direction`, `content`, `timestamp`, and `model_name`.

## Applying Patches

All five patches (002→003→004→005→001) must be applied to restore full v0.17-equivalent functionality. To review and apply:

```bash
cd /opt/hermes
# Check each patch
for p in 002 003 004 005 001; do
  git apply --check /opt/data/skills/hermes-wechat-enhance/patches/${p}-*.patch
done

# Apply in correct order
for p in 002 003 004 005 001; do
  git apply /opt/data/skills/hermes-wechat-enhance/patches/${p}-*.patch
done

# Verify
bash /opt/data/skills/hermes-wechat-enhance/verify-v18.sh /opt/hermes/gateway
```

### Patch Versioning

When upgrading Hermes to a new version, patches may need regeneration if `weixin.py` changed:

```
patches/
├── 001-weixin-continue-hook.patch        ← current (latest Hermes version)
├── 001-weixin-continue-hook.v017.patch   ← archive: v0.17 compatible
├── 002-weixin-footer-hook.patch          ← current
├── 002-weixin-footer-hook.v017.patch     ← archive: v0.17 compatible
└── CHANGELOG.md                          ← record per-version adaptations
```

**Upgrade workflow:**
1. Run `git apply --check` for both patches on the new Hermes version
2. If clean: no action needed, current patches still work
3. If fail: regenerate patches for new version, archive old ones with version suffix, update CHANGELOG

Patches were regenerated for v0.18.0 (2026-07-06) — v0.18's `weixin.py` removed `_drain_pending`, `_resolve_model_name_for_footer`, and `ReplyBudgetStore`, requiring new insertion points. See `references/v018-weixin-changes.md`.

## Hermes Version Compatibility

| Hermes | Patch status | Notes |
|--------|-------------|-------|
| v0.17.0 | `.v017.patch` (archived) | Initial patch set, production |
| v2026.7.1 | `.patch` (current) | Patches regenerated and verified — `weixin.py` significantly refactored |
| v2026.6.19 | untested | Should be close to v2026.7.1 |

**Note:** Hermes uses date tags (e.g. `v2026.7.1`), not semver. The "v0.18" we referred to earlier is actually `v2026.7.1`.

See `references/v018-migration-pitfalls.md` for config format changes and container CMD differences.

## ⚠️ Model Sourcing Principle

**Footer model MUST come from the actual model used by the agent, never from config.yaml.**

`agent_result["model"]` ← `getattr(_agent, "model", None)` ← **the real model**. Config.yaml's `model.default` is a static fallback that hides bugs — it shows the default model even when a different model was actually used (e.g., via session override or model routing).

`error` as footer means: metadata had no model_name. The fix is to ensure the gateway always passes the real model name in metadata (patch 004), NOT to add a config fallback that masks the root cause.

**Principle:** Read the real model from the agent object. Never fall back to config. Config is not the truth.

## ⚠️ Migration Debugging Philosophy

**Root cause over piecemeal fixes.** When multiple bugs surface after a migration, do NOT fix them one at a time. The only reliable approach is a full three-way diff audit:

1. **Clone official source** for both old and new Hermes versions (`git clone --branch v2026.X.Y`)
2. **Diff production vs official** for the old version → produces the COMPLETE customization list
3. **Diff test vs official** for the new version → reveals what was actually migrated
4. **Cross-reference** — every customization must have a corresponding patch or a documented skip reason
5. **Check hooks independently** — patches and hooks are separate systems; verify both

This approach was forced by the user after a painful v0.18 migration where piecemeal debugging missed the /continue break, hooks loading failure, and semantic confusion issues. The audit revealed 28 customizations across 3 files; without it, at least 5 issues would have remained hidden.

**When debugging footer/WeChat issues:** Do NOT claim a fix works without seeing actual WeChat messages. Code-level analysis is insufficient. Start a test container connected to real WeChat, send messages, inspect the footer in the actual client.

## Upgrade Resources

- **`CUSTOMIZATIONS.md`**: Complete modification checklist. Maps every custom feature → patch → file → line count. Includes upgrade hazards per patch and a step-by-step upgrade protocol. Read this FIRST when upgrading to a new Hermes version.
- **`verify-v18.sh`**: Automated verification script. 25+ checks: compilation, class existence, method signatures, metadata flow, footer format. Run after every patch application. `bash verify-v18.sh /opt/hermes/gateway`
- **`references/v017-full-audit.md`**: Line-level diff methodology used for the v0.17→v0.18 audit. Reusable procedure for any version upgrade.

## Footer Controls

The Weixin footer patch reads metadata directly. If `is_system` is True → `hermes`. Otherwise reads from a strict fallback chain:

1. `HERMES_WECHAT_FOOTER_MODEL_NAME` env var
2. `metadata.model_name`
3. `metadata.resolved_model`
4. `metadata.routed_model`
5. `metadata.model`
6. `"hermes"` (hardcoded final fallback — **never** reads config.yaml)

**Config.yaml fallback is forbidden.** If metadata lacks a model name, the footer shows "hermes". Reading config.yaml's `model.default` would hide propagation chain bugs — the fix is to ensure the gateway passes the real model name, not to mask the absence with a default.

- `HERMES_WECHAT_FOOTER_MODEL_NAME`: overrides the non-system footer model name.

## Docker Build Pitfalls

When building the patched image (e.g., `FROM hermes-agent:v2026.7.1`):

1. **`git apply` requires user identity.** The base image has `git` but no `user.name`/`user.email`. Always set them before `git commit`:
   ```dockerfile
   RUN cd /opt/hermes \
       && git init \
       && git config user.email "build@hermes.local" \
       && git config user.name "Hermes Builder" \
       && git add -A && git commit -m base \
       && git apply /tmp/*.patch
   ```

2. **`patch` command is NOT installed.** Use `git apply` or Python difflib, never the `patch` CLI.

3. **s6-overlay entrypoint interferes with custom commands.** The base image has s6-overlay as entrypoint, which starts its own gateway. For test containers, bypass with `--entrypoint`:
   ```bash
   docker run --entrypoint /opt/hermes/.venv/bin/hermes hermes-agent:v0.18.0-patched gateway run ...
   ```

4. **`--user 0:0` is silently overridden by s6.** The entrypoint drops privileges to `hermes` user regardless of `--user`. For file permission fixes, use `--entrypoint /bin/sh` to bypass s6 entirely.

5. **Docker build context must be readable by the NAS user.** On UGREEN NAS, `/volume2/Hermes-v017-current/` is `700` owned by UID 10000 — `vive` can't read it. Copy patches to `/tmp/` first, then build from there.

## Testing Deployment Pitfalls

When deploying a test v18 container alongside production v17 on the same NAS:

### PID File Conflict

**Symptom:** `ERROR gateway.run: Another gateway instance (PID N) started during our startup. Exiting.`

**Cause:** `--replace --force` sends SIGTERM to the old PID, but s6-rc restarts the gateway. The replacement process detects the PID file and exits. Creates a loop.

**Fix:** Do NOT use `--replace --force`. Start with:
```bash
hermes gateway run --no-supervise --accept-hooks -v
```
Remove stale PID/lock files before container start: `rm -f $HERMES_HOME/hermes.pid $HERMES_HOME/.gateway.lock`.

### s6-rc Log Pipeline

**Important:** s6-rc routes gateway stdout through `s6-log`. Application logs (WeChat connection, footer, etc.) go to `$HERMES_HOME/logs/gateway.log` but the startup banner goes to `$HERMES_HOME/logs/gateways/default/current`. Always check BOTH files.

### WeChat Authorization with Isolated HOME

**Symptom:** `WARNING gateway.run: Unauthorized user: <user_id> on weixin`

**Cause:** New `HERMES_HOME` lacks the pairing/authorization data from production's state.db.

**Fix:** Set `GATEWAY_ALLOW_ALL_USERS=true` env var for test containers. Do NOT copy production state.db — it contains production sessions and could cause conflicts.

### Container CMD Shell Quirks

The `docker run ... sh -c "..."` wrapper must include `mkdir -p` for the cache directories BEFORE `exec hermes gateway run`. The cache dirs (`/tmp/hermes-v18-cache/*`) are ephemeral and must exist before s6-rc drops privileges.

### Hooks Not Loaded (Missing --accept-hooks)

**Symptom:** No `[hooks] Loaded hook ...` message in gateway startup log. Hermes Alive watcher never starts, and hermes-wechat-enhance never sends the startup ready notification.

**Cause:** Gateway run command omitted `--accept-hooks`. v0.18 does NOT auto-accept hooks by default.

**Fix:** Always include `--accept-hooks` in the gateway command:
```bash
hermes gateway run --no-supervise --accept-hooks -v
```
Verify with `docker logs <container> 2>&1 | grep "hooks"` — should show `[hooks] Loaded hook ...`.

## Footer Metadata Root Cause

**Gateway does not distinguish "system" vs "model" outbound messages.** All messages — LLM responses, `/steer` acknowledgments, status messages — go through `adapter.send()` with identical metadata (only thread routing info, no `is_system` flag).

```text
/steer ack  →  adapter.send()  →  weixin.send()  →  WeChat  (no is_system)
LLM reply   →  adapter.send()  →  weixin.send()  →  WeChat  (no is_system)
```

The adapter can't tell them apart unless the gateway tags system messages. Fix requires a gateway source patch: tag system outbound sends with `is_system=True` in metadata, then the inline Weixin footer logic reads it to set footer to `hermes` vs model name.

**Principle:** "模型的归模型，系统的归系统" — footer determination must be based on structured metadata, never content heuristics.

## Side-by-Side Testing

Complete procedure for running v17 (production) + v18 (test) simultaneously on the same WeChat account with isolated state. See `references/side-by-side-testing.md`.

**v0.18 WeixinAdapter does NOT have `self._hooks`.** The hooks system lives on the Gateway object, not the adapter. This means `self._hooks.emit_collect()` calls injected into `weixin.py` will fail with `AttributeError: 'WeixinAdapter' object has no attribute '_hooks'`.

**Solution: Inline patches instead of hook calls.** Footer and /continue logic must be directly inlined into the weixin.py patches — no `emit_collect()`:

- **Footer (002 patch):** Read `metadata.get("is_system")` and `os.environ.get("HERMES_WECHAT_FOOTER_MODEL_NAME")` directly in `send()` method. No hook round-trip.
- **/continue (001 patch):** Intercepts `/continue` in the intake method before it reaches the gateway. Calls `_drain_pending(sender_id)` to flush queued messages, then returns early. **Must be applied LAST (after 005) because it depends on `_drain_pending()`.** Never lets `/continue` reach the gateway command router.
- **Hook handler.py:** Only subscribes to `agent:start` and `agent:end` (message queue storage). `command:continue` and `message:send` removed from HOOK.yaml.

**Gateway-level system tagging (003 patch):** To distinguish system messages from model messages at the adapter level, a separate gateway patch tags all system outbound sends with `is_system=True` in metadata. The inline footer logic reads this flag.

## v0.17 Production Audit (Full — 2026-07-07)

Full three-way diff: official v0.17.0 vs production v0.17, then official v2026.7.1 vs patched v2026.7.1. **28 customizations across 3 files, ~539 lines total.**

### weixin.py (20 items, +371 lines)

| # | Feature | Description |
|---|---------|-------------|
| 1 | **ReplyBudgetStore** | Per-token message counter (10/token), persisted to disk |
| 2 | **MessageSendQueue** | In-memory FIFO queue for outbound text chunks |
| 3 | **Footer: count + model** | `` `{count}` `{model}` `` appended to each message |
| 4 | **/continue drain** | `/continue` intercepts in intake → `_drain_pending()` + `return` early |
| 5 | **inbound token→budget** | New context_token resets counter for that user |
| 6 | **Protocol leak guard** | Replaces raw tool JSON with Hermes notice (skipped in v0.18) |
| 7 | **send()→queue→drain** | Text chunks enqueued, drained with budget+footer |
| 8 | **Footer metadata-only** | Attribution via metadata.is_system, never content heuristics |
| 9 | **Cron badge override** | Cron messages use custom badge (skipped) |
| 10 | **Image metadata fix** | Images get footer_metadata |
| 11 | **Control command dedup bypass** | /approve, /deny, /steer, /continue etc. bypass content dedup |
| 12 | **Content heuristic disabled** | `_content_looks_like_system_error()` always returns False |
| 13 | **Budget store init + restore** | ReplyBudgetStore created in `__init__`, restored in `connect()` |
| 14 | **Footer model resolution** | `_resolve_model_name_for_footer()`: is_system→hermes, else metadata→model |
| 15 | **Config fallback removed** | `_footer_model_name()` never reads config.yaml — final fallback is `"hermes"` |
| 16 | **Queue metadata footer** | Per-chunk footer attribution in drain loop |
| 17 | **Footer format** | `chunk + "\n\n---\n\n`{count}` `{model}`"` |

### base.py (5 items, +85 lines)

| # | Feature | Description |
|---|---------|-------------|
| 18 | **_mark_hermes_system_notify_metadata** | Marks slash-command/control responses as Hermes-authored (is_system=True) |
| 19 | **Metadata always dict** | Ensures `_thread_metadata` is always dict, never None |
| 20 | **Model name propagation** | event.model_name/resolved_model → _thread_metadata |
| 21 | **Slash command system tag** | Command results inherit session model, force-overwritten to hermes |
| 22 | **Final send origin metadata** | command→system, agent response→model |

### run.py (4 items, +83 lines)

| # | Feature | Description |
|---|---------|-------------|
| 23 | **_non_conversational_metadata** | Lifecycle/status/platform messages → is_system=True for Weixin |
| 24 | **Agent result model propagation** | agent_result["model"] → event.model_name → metadata chain |
| 25 | **Model-origin thread metadata** | Model name injected into _model_thread_metadata for agent responses |
| 26 | **Startup ready notification** | `HERMES_WEIXIN_STARTUP_READY_NOTIFY` env var controls gateway ready msg |

### Known Gaps in v0.18 Patched Image (Resolved 2026-07-07)

| Issue | Status | Fix |
|-------|--------|-----|
| Patch 001 only adds debug log, no /continue intercept | ✅ Fixed | Rewrote patch 001: intercepts in intake with `_drain_pending()` + `return` |
| Hooks not loaded (missing `--accept-hooks`) | ✅ Fixed | Added to gateway start command + documented in P1 |
| Protocol leak guard intentionally skipped | ⏭️ | Optional enhancement |
| Cron badge override intentionally skipped | ⏭️ | Optional enhancement |
| Patch ordering was wrong (001→005) | ✅ Fixed | Correct order: 002→003→004→005→001 |
| Everything else via patches 002-005 | ✅ | Verified compile + feature audit |

See `references/v017-full-audit.md` for line-level diff methodology and complete audit procedure.

**⚠️ 2026-07-06 v18 测试发现：每条消息 footer 都是 "hermes"，根因已确认。** Patch 004 从 `agent_result.get("model")` 读取模型名，但 v18 的 agent_result 可能不含 `"model"` 字段 — 如果返回 dict 没有这个 key，patch 004 读不到任何模型名，整个传播链断裂，weixin.py 走兜底 → `"hermes"`。v17 能工作是因为 `_run_agent_inner` 的 return 语句显式包含了 `"model": _resolved_model`（run.py:16084）。参见 `references/v018-model-propagation-bug.md`。

## Patch Family (Current)

```
patches/
├── 001-weixin-continue-hook.patch       ← Inline /continue pass-through
├── 002-weixin-footer-hook.patch         ← Inline footer: model name from metadata
├── 003-gateway-system-metadata.patch    ← Tag system messages with is_system=True
├── 004-gateway-model-propagation.patch  ← Propagate agent.model→event→metadata
├── 005-weixin-send-queue.patch          ← ReplyBudgetStore + MessageSendQueue + _drain_pending + footer count
├── *.v017.patch                         ← Archive
└── CHANGELOG.md
```

All five patches must be applied in order **(002→003→004→005→001)** on v0.18 base. **Critical ordering constraint:** Patch 001 must be applied LAST because it depends on `_drain_pending()` and `_safe_id()` added by patch 005. Patch 005 must be applied after 002 because its footer modifications reference metadata fields introduced by 002.

Patch 005 is the largest (~330 lines) — it adds the queue/drain infrastructure and the `` `{count}` `{model}` `` footer format.

### Gateway Startup Requirements

For the gateway to load hooks:

1. **Include `--accept-hooks`** in the gateway run command:
   ```bash
   hermes gateway run --replace --force --no-supervise --accept-hooks -v
   ```

2. **Ensure hermes-wechat-enhance hook is installed** (handles WeChat startup notification and message capture):
   ```bash
   mkdir -p ~/.hermes/hooks
   ln -sfn /opt/data/skills/hermes-wechat-enhance/hooks/hermes-wechat-enhance ~/.hermes/hooks/hermes-wechat-enhance
   ```

3. **Startup ready notification** is handled by hermes-wechat-enhance. On `gateway:startup`, it sends `Gateway online — Hermes is back and ready` to the WeChat home channel. Controlled by env vars:
   ```bash
   HERMES_WEIXIN_STARTUP_READY_NOTIFY=1  # default: enabled
   HERMES_WEIXIN_STARTUP_READY_MESSAGE="Gateway online — Hermes is back and ready"
   ```

It resolves the target from `GatewayConfig.get_home_channel(Platform.WEIXIN)`, then `HERMES_WEIXIN_HOME_CHANNEL`, `WEIXIN_HOME_CHANNEL`, and finally the legacy `HERMES_PROACTIVE_WEIXIN_CHAT_ID`.

Without `--accept-hooks`, the gateway will NOT load any hooks, including hermes-wechat-enhance which handles the startup notification.

### Patch 004: Model Name Propagation

**Problem:** v2026.7.1's `_mark_notify_metadata(None)` → `TypeError` (bare `except` swallows), stripping metadata to `{"notify": True}` — no `model_name`. Also `agent_result` may not include `"model"` field in newer versions.

**Root cause (confirmed 2026-07-07):** Two independent breaks:
1. `_mark_notify_metadata(None)` crashed when `_thread_metadata` was None — bare `except` returned `{"notify": True}` without `model_name`
2. `agent_result` did NOT contain `"model"` field in v2026.7.1 (unlike v17 which had `"model": _resolved_model` at run.py:16084)

**Fix (implemented by Codex):**
1. `_mark_notify_metadata(None)` → returns `{"notify": True}` (no crash)
2. Multi-level fallback: agent_result.model → agent_result.model_name → agent_result.resolved_model → event/source attributes → `_last_resolved_model` → `_resolve_gateway_model()`
3. Writes to `model_name`, `resolved_model`, AND `model` fields in metadata
4. In `base.py`, creates dict when `_thread_metadata is None` instead of passing None to `_mark_notify_metadata`

**Data flow:** agent.model → agent_result["model"] → event.model_name → _thread_metadata["model_name"] → adapter.send(metadata) → weixin `_footer_model_name()` → footer. Zero config reads for normal path.

**Verified 2026-07-07:** Test container logs show `model='deepseek-v4-pro'` in footer (was `model='hermes'` before fix).

### Patch 005: Send Queue + Budget + Footer Count

Adds `ReplyBudgetStore`, `MessageSendQueue`, `_drain_pending()`, and the `` `{count}` `{model}` `` footer format. ~330 lines.

**Footer model resolution** (fixed 2026-07-07): Now uses `_footer_model_name(metadata)` helper which checks `_is_system_meta()` for multi-field system detection (is_system/actor/source/message_origin/origin), then a strict fallback chain: env var → metadata.model_name → resolved_model → routed_model → model → `"hermes"`. **Never reads config.yaml.** Config fallback would hide metadata chain bugs — the last resort is always `"hermes"`.

## Notes

`MessageStore` is self-contained and uses only Python standard library modules.

## ⚠️ Never Deploy Without Permission

**Do NOT start test containers, deploy to production, or modify running gateway instances without explicit user approval.** The user has strict deployment protocols (audit → confirm → rollback plan → execute). Violating this creates chaos — a test container connected to the same WeChat account will process messages in parallel with production, causing duplicate responses and rate-limit conflicts.

## ⚠️ Footer Truthfulness — No Fake Fallbacks

**Footer MUST uniquely and accurately reflect the actual content source. Never use fallbacks that hide bugs.** If the model name is missing from metadata, the fix is to trace and repair the propagation chain (patch 004), NOT to add a config.yaml fallback that silently shows a plausible-but-wrong model name. A footer of `hermes` or `error` is honest — a footer of `deepseek-v4-pro` when the actual model was something else is a lie. The user rejected this explicitly: "我要真实模型来源，不是要你给我弄个假的展示。"

## Development Operations Lifecycle

This skill modifies gateway source code — it is NOT a pure drop-in skill. It requires git-based state management for install/update/uninstall.

### Planned Architecture (not yet implemented)

```
hermes-wechat-enhance/
├── scripts/
│   ├── install.sh      ← detect version → git init → pristine commit → apply patches → hooks
│   ├── update.sh       ← revert to pristine → apply new patches
│   ├── uninstall.sh    ← git checkout pristine → remove hooks
│   └── verify.sh       ← goal-oriented behavioral tests
├── IMPACT_MATRIX.md    ← maps change type → which scripts/files must update
├── patches/
│   ├── v0.17/          ← version-specific patch sets
│   └── v0.18/
└── check-consistency.sh ← scan all scripts vs patches/ directory for drift
```

### Testing Philosophy: Goal-Oriented, NOT Existence-Checking

**Never test "does function X exist" — test "given input Y, does the system produce output Z?"** Existence tests give false confidence. The user explicitly rejected this: "你的很多测试都只验证函数/类存不存在, 而不是goal为导向的测试, 这容易导致,很多内容你声称完成了,但实际上运行不通."

| ❌ Bad test | ✅ Good test |
|------------|-------------|
| `ReplyBudgetStore` class exists? | Budget exhausted → drain rejects send with error |
| `_footer_model_name()` function exists? | `{is_system:True}` → output `"hermes"` |
| `/continue` interception code exists? | `/continue` received → `_drain_pending()` called, message NOT routed to agent |

Each test must be traceable to a user-facing requirement. Tests without a corresponding goal should be removed.

### Anti-Bloat Rules

- **One patch, one responsibility.** Never mix concerns in a single patch.
- **One in, one out.** Every new feature must offset by removing dead code.
- **Quarterly audit.** Run `check-consistency.sh` to find stale tests, unused patches, and orphaned scripts.

**v0.17 → v0.18 behavior change:** v0.18's official `weixin.py` removed `_drain_pending()`, `_resolve_model_name_for_footer()`, `ReplyBudgetStore`, and `MessageSendQueue`. The adapter no longer does reply-budget tracking or footer metadata injection.

**v0.17 → v0.18 official diff:** Only 39 lines changed. Key changes: DM policy default `open→pairing`, `connect(is_reconnect=bool)`, `_is_dm_intake_allowed()`, `splits_long_messages=True`. The bulk of our perceived changes were actually our own v0.17 custom patches being absent in official v0.18.

## Codex CLI Shell Parsing Pitfall

Codex CLI (`codex exec`) parses inline shell operators (`&&`, `||`, backticks) inside prompts as its own arguments. Always write complex logic as Python scripts on disk first, then tell Codex to execute them. Never embed shell one-liners with operators in Codex prompts.
