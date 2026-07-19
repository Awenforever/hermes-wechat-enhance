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

## 010 — Context-token kernel hardening

- slash-command content-dedup exemption
- token refresh ordering, send serialization and generation fence
- media budget accounting and restart reconciliation
- transactional install/uninstall state

## 010 v3 — Ordinary reply append-and-drain contract

- ordinary replies append behind existing pending items;
- normal `send()` drains the complete FIFO queue immediately;
- new Context token numbering starts at 1 for the oldest pending item;
- dynamic regression asserts `A=1, B=2, C=3, pending=0`.

## 011 — Consolidated Hermes v0.18 Weixin patch

- generated as a clean official-v0.18-to-final-runtime diff;
- supersedes legacy Weixin patches 001/002/005/009/010 for fresh v0.18 installs;
- removes malformed patch 005 from the active series;
- retains slash-command exemption, token ordering, delivery serialization,
  media budget, restart reconciliation and ordinary reply append-then-drain.

## v5 — Portable hook import bootstrap

- removes the hard dependency on `/opt/data` from the copied hook;
- resolves skill source through environment and hook-relative paths;
- verifies the resolved path equals the canonical installed source;
- adds `WECHAT_ENHANCE_IMPORT_BOOTSTRAP_V2`.

## v6 — Real adapter initialization in contract harness

- constructs the test adapter through `WeixinAdapter(...)`;
- removes the fragile hand-written partial constructor;
- verifies `_split_multiline_messages` and the send gate;
- adds `SYNTHETIC_ADAPTER_RUNTIME_INIT_OK`.

## v7 — Idempotent hook deployment and strict zero residue

- ignores runtime caches when comparing installed hook content;
- removes timestamped hook backup creation;
- uses install-state snapshot as the sole rollback source;
- validates all matching sibling paths after uninstall.

## v8 — Current-image legacy upgrade profile

- adds exact source-profile detection for official, legacy and hardened v0.18 runtimes;
- routes pristine source through patch 011;
- routes the existing released runtime through patch 012;
- makes both paths converge to one byte-identical final Weixin source;
- fails closed for unknown modified source profiles.

## v9 — Version inference from verified source profile

- detects source profile before version resolution;
- fixes package metadata detection being overwritten by `unknown`;
- permits fallback only for verified v0.18 source profiles;
- reports external versus inferred version provenance.

## v10 — Hermes v0.18 version-family normalization

- accepts both runtime version `v0.18.0` and release tag `v2026.7.1`;
- preserves raw version and provenance in logs;
- routes patch lookup and selection through canonical `VERSION_FAMILY=v2026.7.1`;
- keeps unknown versions and sources fail-closed.

## v11 — Transactional canonical source

- snapshots source before replacement;
- restores source/hook/gateway after injected failures;
- records source installed hash and refuses divergent uninstall;
- removes source backup residue and persistent Git identity changes.

## v12 — Canonical source-path snapshot fix

- fixes `snapshot()` parameter shadowing by gateway-file iteration;
- preserves the canonical source path in the manifest;
- adds a direct manifest and source-backup regression test.

## v13 — Exact dirty-working-tree restoration

- removes installer-created Git commits and index changes;
- removes git-reset-based rollback;
- always restores managed gateway files from byte snapshots;
- preserves Git HEAD, config, status and unrelated dirty files;
- fails closed if Git HEAD changes externally before uninstall.
