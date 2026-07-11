# Hermes WeChat Enhance

`hermes-wechat-enhance` is the Hermes Weixin gateway enhancement skill. It owns the Weixin platform-layer patch set and the active hook that support startup-ready notification, `/continue`, footer model attribution, streaming/queued/handoff metadata propagation, and reliable text delivery using `_delivery_id` plus `SendResult.success`.

## Ownership boundary

This skill owns and may patch:

```text
/opt/hermes/gateway/platforms/weixin.py
/opt/data/hooks/hermes-wechat-enhance/handler.py
/opt/data/skills/hermes-wechat-enhance/
```

Email Watchdog and other business skills must not overwrite `weixin.py`. Business-critical callers should maintain their own durable outbox and pass stable `metadata._delivery_id` to `adapter.send`.

## Fresh-container validation order

Before applying to production, validate in a fresh isolated test container:

1. Clone this repository/branch into `/opt/data/skills/hermes-wechat-enhance`.
2. Let Hermes/assistant read this README and run the documented install procedure.
3. Run self-install verification.
4. Run function matrix tests.
5. Run reliable-delivery contract tests.
6. Run stress tests.
7. Run real Weixin pairing/e2e with a spare account only when explicitly approved.
8. Run clean uninstall verification.
9. Only after every step is zero-error may the skill be applied to production.

## Install

```bash
cd /opt/data/skills/hermes-wechat-enhance
bash scripts/install.sh
python3 scripts/verify-self-install.py
python3 scripts/test-reliable-delivery-contract.py
```

A controlled restart of only the Hermes gateway container may be required for Python source patches to load. Do not restart the Docker daemon.

## Verify

```bash
cd /opt/data/skills/hermes-wechat-enhance
python3 scripts/verify-self-install.py
python3 scripts/test-reliable-delivery-contract.py
python3 scripts/verify-persistence.py
bash scripts/check-consistency.sh
```

## Uninstall

```bash
cd /opt/data/skills/hermes-wechat-enhance
bash scripts/uninstall.sh
```

## Patch series

Current patch series reaches `009`.

Important current markers:

```text
HERMES_WECHAT_STREAM_CONSUMER_MODEL_METADATA_V3
HERMES_WECHAT_QUEUED_FIRST_RESPONSE_MODEL_METADATA_V3
HERMES_WECHAT_BACKGROUND_REVIEW_SYSTEM_METADATA_V3B
HERMES_WECHAT_HANDOFF_MODEL_METADATA_V3
HERMES_WECHAT_FINAL_MODEL_STRICT_SOURCE_V3

WECHAT_ENHANCE_RELIABLE_DELIVERY_V2
WECHAT_ENHANCE_REPLY_BUDGET_COMMIT_AFTER_ACK_V2
WECHAT_ENHANCE_QUEUE_PEEK_COMMIT_V2
WECHAT_ENHANCE_DELIVERY_ID_DEDUPE_V2
WECHAT_ENHANCE_STARTUP_READY_ACK_V2
```

## Reliable delivery contract

For text sends:

```text
queue.peek -> send chunk -> iLink acknowledgement -> commit budget -> dequeue -> SendResult.success=true
```

On failure:

```text
SendResult.success=false
pending chunk remains queued in memory
budget is not committed
caller retains durable business outbox item
```

Idempotency:

```text
metadata._delivery_id + metadata._delivery_chunk_index
```

## Safety rules

- Do not use a production WeChat account during fresh-container real pairing tests.
- Do not send real messages unless explicitly approved.
- Do not restart the Docker daemon.
- Do not apply to production until clean-container install, matrix, stress, real e2e, and uninstall verification all pass with zero errors.
