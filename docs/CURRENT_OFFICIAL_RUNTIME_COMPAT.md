# Current Official v0.18 Runtime Compatibility

`current-official-v018` deliberately leaves
`gateway/platforms/weixin.py` and `gateway/platforms/base.py` byte-identical to
the official Hermes image.

The legacy WeChat Enhance reliable-delivery/context-token contracts formerly
provided by Weixin source patches are restored at gateway startup by a
skill-owned runtime compatibility layer. The startup dispatcher discovers the
already-created Weixin adapter from the Hook context first. Candidates are
type-gated to the real current-official `WeixinAdapter`, so verifier/startup
stubs are skipped without patch attempts or traceback noise. The dispatcher
only falls back to the global gateway runner when the Hook context does not
expose any Weixin candidate.

## Exact source gate

The compatibility core is enabled only for official `weixin.py` SHA256:

`85e06cea1673ae20e336820e9cac5a7dc467bdd8c2796a73c3e2bf1042c76dc4`

Historical/hardened profiles retain their existing source-patch behavior and use
the existing slash-command runtime hook fallback.

## Restored contracts

- provider message-id replay remains first;
- repeated slash commands with distinct message IDs are allowed;
- context token refresh occurs after a new provider message ID is accepted but
  before content-fingerprint suppression;
- ACK-only reply-budget commit and queue dequeue;
- maximum ten replies per context token;
- per-chat delivery serialization and token-generation fence;
- media/caption context-budget accounting;
- context-token/reply-budget persistence reconciliation;
- delivery-ID + chunk-index queue deduplication;
- deterministic client ID across failed-send retry;
- context-first adapter discovery, avoiding eager import of the full gateway
  runner during standalone installation verification;
- exact `WeixinAdapter` type gate, preventing runtime patch attempts against
  fake or incompatible adapter stubs used by verification.

The proven compatibility core is kept byte-identical to the isolated candidate
that passed the unchanged historical kernel and additional reliable-delivery
proofs.
