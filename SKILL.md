# Hermes WeChat Enhance

Hermes Weixin transport enhancement for current Hermes releases.

## Installation contract

The public release supports the Hermes range declared by `plugin.yaml`. It is
hook-only: installation must never edit files in Hermes Core.

When installing or upgrading:

1. Inspect the active Hermes version, configured Weixin account, active hook,
   and persistent state before changing anything.
2. Preserve pairing, credentials, counters, pending FIFO entries, quotes,
   authorization, audit records, and user configuration.
3. Offer customization of the startup-ready message and bounded audit capture.
4. Ask for explicit confirmation before enabling the plugin, restarting the
   Gateway, or sending a real message.
5. Run `scripts/verify-self-install.py` before restart and verify `status`
   after restart. Roll back source and hook code if verification fails.
6. Never request a new QR scan or pairing code while the existing Hermes
   profile is healthy.

Do not choose or hard-code a model. Footer attribution uses the model selected
by Hermes. The plugin activates only for a Weixin adapter already configured by
Hermes and does not assume that Weixin is the user's only channel.

## Lifecycle

```bash
hermes plugins install Awenforever/hermes-wechat-enhance
hermes plugins enable hermes-wechat-enhance       # after confirmation
hermes wechat-enhance install-hook
python3 ~/.hermes/plugins/hermes-wechat-enhance/scripts/verify-self-install.py
hermes gateway restart                            # after confirmation
hermes wechat-enhance status
```

Upgrade uses the same idempotent lifecycle. Uninstall with:

```bash
hermes wechat-enhance uninstall-hook
hermes plugins uninstall hermes-wechat-enhance
```

Persistent user data under
`$HERMES_HOME/plugin-data/hermes-wechat-enhance/` is intentionally retained.

## Runtime guarantees

- Every inbound Weixin message refreshes its Context Token before secondary
  content deduplication.
- `/continue` is consumed locally and drains pending FIFO messages without
  entering conversation context.
- All fresh slash commands bypass content-fingerprint deduplication while
  provider message-ID replay protection remains active.
- Only acknowledged text and media sends advance the bubble counter.
- Every split text bubble carries the truthful model or `hermes` system tag.
- Pending sends survive restart and are released in strict FIFO order.
- Startup-ready notification is enabled by default and may be explicitly
  disabled or customized by the user.
- Quoted and leading `@` actions are offered to independently installed
  consumers; unhandled input continues to Hermes normally.

## Verification and release

`scripts/verify-self-install.py` is the only authoritative installed-runtime
verifier. It checks the live Hermes API surface and current hook behavior; it
must not import historical Hermes classes or classify the runtime by source
hash.

A release is acceptable only when clean install, upgrade with state retention,
Gateway restart, real Weixin behavior, uninstall, and reinstall pass on the
supported Linux, WSL2, Windows-hosted and NAS/Docker environments.

Maintain implementation lessons and regression obligations in
`docs/DEVELOPMENT_MEMORANDUM.md`, never in the public README.
