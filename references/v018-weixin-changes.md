# v0.18 WeChat (weixin.py) Official Changes

Analysis from `hermes-agent:v0.17.0 → v0.18.0` weixin.py diff.

## Removed (v0.17-only)

| Component | Lines | Purpose | Replacement |
|-----------|-------|---------|-------------|
| `ReplyBudgetStore` class | ~318-417 | Per-user reply budget (10 bubbles/token) | None — removed |
| `MessageSendQueue` class | ~420-460 | Outbound message queue with drain | None — removed |
| `_content_looks_like_system_error()` | ~2062 | Content heuristics for footer | None — removed |
| `_default_model_name_for_footer()` | ~2070 | Default footer model from config.yaml | Standard metadata pipeline |
| `_resolve_model_name_for_footer()` | ~2081-2134 | Complex footer resolution with is_system metadata | Standard metadata pipeline |
| `_drain_pending()` | ~2205-2307 | /continue backlog drain with budget tracking | Simplified pass-through |
| `_hermes_visible_text_has_tool_protocol_leak()` | ~583 | Tool protocol leak detection | Removed |
| `_hermes_protocol_leak_notice()` | ~628 | Leak notice generation | Removed |

## Added (v0.18-only)

| Component | Lines | Purpose |
|-----------|-------|---------|
| `_open_dm_opted_in()` | ~1475 | DM opt-in state check |
| `_is_dm_intake_allowed()` | ~1489 | Fine-grained DM intake control |
| `TypingTicketCache` (module-level) | ~318 | Previously nested, now standalone class |

## Changed

- `connect(self) → connect(self, *, is_reconnect: bool = False)` — supports reconnect flow
- `send()`: ~100 lines shorter, no footer resolution, no drain_pending fallback
- `/continue`: now emits `command:continue` hook then passes through to normal text enqueueing (hook can return `{"action": "skip_drain"}` to suppress)
- Footer: uses standard platform adapter metadata, no custom resolution function

## Net Effect

- **2781 → 2379 lines** (400 lines removed)
- Message sending is now direct (no queue, no budget), text is split and sent immediately
- All "enhancement" logic (footer, /continue, queue) was stripped from the adapter
- This aligns with our hook-based approach — the adapter does pure transport, hooks do enhancement

## Impact on Our Patches

Both patches needed regeneration for v0.18 because:
1. `/continue` insertion point moved from ~1674 (drain_pending block) to ~1467 (before text event enqueue)
2. Footer/message:send insertion point moved from ~2144 (before footer resolution) to ~1886 (before text chunking)