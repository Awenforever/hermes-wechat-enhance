# hermes-wechat-enhance

Hermes Weixin gateway enhancement skill.

## Purpose

This skill owns the Weixin adapter enhancement layer for Hermes. It provides `/continue`, startup-ready notification, footer model attribution, system-message classification, model metadata propagation across streaming/queued/handoff send rails, and reliable text delivery using stable `_delivery_id` plus `SendResult.success`.

## Owned files

```text
/opt/hermes/gateway/platforms/weixin.py
/opt/data/hooks/hermes-wechat-enhance/handler.py
/opt/data/skills/hermes-wechat-enhance/
```

## Install

```bash
cd /opt/data/skills/hermes-wechat-enhance
bash scripts/install.sh
python3 scripts/verify-self-install.py
python3 scripts/test-reliable-delivery-contract.py
```

## Uninstall

```bash
cd /opt/data/skills/hermes-wechat-enhance
bash scripts/uninstall.sh
```

## Validation requirement

A production apply is valid only after a fresh test container completes:

```text
README-driven self install
function matrix tests
stress tests
real Weixin e2e with spare account if explicitly approved
safe clean uninstall
zero-error package review
```

## Current reliable delivery markers

```text
WECHAT_ENHANCE_RELIABLE_DELIVERY_V2
WECHAT_ENHANCE_REPLY_BUDGET_COMMIT_AFTER_ACK_V2
WECHAT_ENHANCE_QUEUE_PEEK_COMMIT_V2
WECHAT_ENHANCE_DELIVERY_ID_DEDUPE_V2
WECHAT_ENHANCE_STARTUP_READY_ACK_V2
```

## Complete patch and reference inventory

The current patch inventory is deliberately listed here so `scripts/check-consistency.sh` can verify that documentation and patch files stay synchronized.

### Patch IDs

- 001
- 002
- 003
- 004
- 005
- 006
- 007
- 008
- 009

### Patch files

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

### Reference files

- `references/development-blueprint.md`
- `references/migration-test-patterns.md`
- `references/v018-model-propagation-bug.md`
- `references/isolated-audit-pattern.md`
- `references/v017-full-audit.md`
- `references/side-by-side-testing.md`
- `references/docker-build-and-test.md`
- `references/architecture-analysis.md`
- `references/v018-migration-pitfalls.md`
- `references/v018-weixin-changes.md`
- `references/v017-model-propagation-chain.md`


## Reference inventory

The following reference documents are part of the skill package and are intentionally retained:

- `references/development-blueprint.md`
- `references/migration-test-patterns.md`
- `references/v018-model-propagation-bug.md`
- `references/isolated-audit-pattern.md`
- `references/v017-full-audit.md`
- `references/side-by-side-testing.md`
- `references/docker-build-and-test.md`
- `references/architecture-analysis.md`
- `references/v018-migration-pitfalls.md`
- `references/v018-weixin-changes.md`
- `references/v017-model-propagation-chain.md`

