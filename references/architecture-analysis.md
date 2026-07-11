# Architecture Analysis — WeChat Enhance Hook Migration

## Research Date: 2026-07-06

## Target Hermes Version: v0.17.0

## Key Source Files Analyzed

| File | Purpose |
|------|---------|
| `/opt/hermes/gateway/hooks.py` | Hook registry: emit(), emit_collect(), HOOK.yaml discovery |
| `/opt/hermes/gateway/platforms/weixin.py:1634-1679` | /continue local interception |
| `/opt/hermes/gateway/platforms/weixin.py:2081-2146` | Footer resolution (_resolve_model_name_for_footer) |
| `/opt/hermes/gateway/platforms/weixin.py:2136-2185` | send() method — footer applied here |
| `/opt/hermes/gateway/run.py` | Gateway main loop, hook dispatch points |

## Hook Events (Existing)

| Event | Use for |
|-------|---------|
| `agent:start` | Capture inbound messages |
| `agent:end` | Capture outbound messages (response truncated to 500 chars) |
| `command:*` | Intercept slash commands (wildcard match) |
| `gateway:startup` | Initialization |

## Gap Analysis

### Message Queue Storage — ✅ Pure Hook
`agent:start` + `agent:end` provide all needed context. Write to independent JSONL store.

### /continue — ⚠️ Needs Minimal Patch
`command:continue` hook fires, but weixin.py (line 1675) intercepts `/continue` BEFORE gateway routing. Hook never sees the command. Solution: inject `emit_collect("command:continue")` before `_drain_pending()`, let hook decide whether to skip local drain.

### Footer — ⚠️ Needs Minimal Patch
No `message:send` event exists. `_resolve_model_name_for_footer()` in weixin.py:2081 runs inside `send()` without any hook point. Solution: inject `emit_collect("message:send")` before footer resolution, let hook inject metadata.

## Hook System Capabilities

- `emit()` — fire and forget, ignores return values
- `emit_collect()` — fire and collect return values (not used by gateway core)
- Handler: `async def handle(event_type, context) -> Optional[Dict]`
- Discovery: `~/.hermes/hooks/<name>/HOOK.yaml` + `handler.py`
- Gateway only scans `~/.hermes/hooks/`, not `/opt/data/skills/`
- Deployment requires symlink from hooks dir to skill dir, plus PYTHONPATH

## Decision Log

1. **No monkey-patching** — rejected in favor of minimal source patches
2. **Patches as files** — saved in skill's `patches/` directory, not applied to production
3. **Independent storage** — MessageStore uses JSONL, does not touch gateway's state.db
4. **Hook return values for decisions** — handler returns `{"action": "skip_drain"}` to control adapter behavior