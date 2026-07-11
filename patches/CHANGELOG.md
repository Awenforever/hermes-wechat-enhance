# Patch Changelog

## 2026-07-06
- v0.18.0: Regenerated patches for Hermes Agent v0.18.0
  - 001: /continue pass-through - no adapter hook access
  - 002: inline footer metadata/env resolution - no adapter hook access
  - 003: gateway system-message metadata tagging for platform footers
  - 004: propagate resolved agent model into event/thread metadata for Weixin footer
  - 005: restore Weixin outbound send queue and per-context-token reply budget from v0.17 production path

## 2026-07-02
- v0.17.0: Initial patches for Hermes Agent v0.17.0
- 006-gateway-interim-model-metadata.patch: propagate current turn model metadata to interim assistant commentary so Weixin footers show the real model instead of hermes; system/status/tool/control messages remain hermes.
- 007-gateway-interim-model-strict-source.patch: remove config/default model fallback from interim assistant footer metadata; only runtime turn/resolved model fields are accepted, with source-only observability logging.
- 008-gateway-footer-model-full-send-rails.patch: extend real runtime model metadata to stream consumer sends, queued first_response, and handoff synthetic responses; remove final footer config/default model fallback; keep background self-improvement review as system/non-conversational metadata.
- v3b-background-system correction: background self-improvement review is system/self-maintenance output and must keep footer=hermes; only model conversation rails receive model metadata.
- 009-weixin-reliable-delivery-contract.patch: reliable Weixin text delivery contract owned by hermes-wechat-enhance; queue peek/ack/dequeue, commit budget after ack, delivery_id/chunk_index dedupe, deterministic client_id, bounded cooldown retry, corrected SendResult semantics, startup ready ack verification. Restart persistence strategy is caller-owned outbox with idempotent replay (方案 B).
