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
