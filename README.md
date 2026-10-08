<div align="center">

# Hermes WeChat Enhance

**Reliable Weixin delivery with truthful per-bubble model attribution.**

[![Hermes](https://img.shields.io/badge/Hermes-%3E%3D0.21.3%2C%20%3C0.22-5965f2)](https://github.com/NousResearch/hermes-agent)
[![Channel](https://img.shields.io/badge/channel-Weixin-07c160)](#what-it-does)
[![Release](https://img.shields.io/badge/release-2.2.0-7950f2)](plugin.yaml)
[![License](https://img.shields.io/badge/license-MIT-2f9e44)](LICENSE)

[简体中文](README_CN.md) · [Install](#install) · [Configure](#configure) · [Troubleshoot](#troubleshoot)

</div>

---

Hermes WeChat Enhance is a channel-layer extension for Hermes. It makes every
successfully delivered Weixin text bubble auditable at a glance, keeps failed
delivery in strict FIFO order, and preserves the user's existing Hermes model,
channel, pairing, and profile configuration.

## What it does

| Capability | Guarantee |
|---|---|
| **Truthful model footer** | Model-written bubbles show the actual routed/fallback model; Hermes-owned controls show `hermes`. |
| **Acknowledged counter** | A number is committed only after Weixin confirms delivery. Failed attempts do not consume it. |
| **Consistent multipart replies** | Every physical bubble in a split response keeps the same model identity and gets its own counter. |
| **Durable FIFO recovery** | Failed bubbles survive restart and are delivered before newer replies. |
| **Automatic Context Token refresh** | Every inbound Weixin message refreshes the reply window before deduplication. |
| **Silent `/continue`** | Refreshes the token and resumes pending delivery without entering the conversation context. |
| **Repeatable slash commands** | Fresh `/approve`, `/continue`, and other slash commands are not discarded because their text repeats; provider message-ID replay protection remains active. |
| **Markdown-safe transport** | Logical Markdown lines and links are preserved; the client performs visual wrapping. |
| **Ready notification** | An optional startup message confirms that the Gateway is available again. |
| **Authorized quote actions** | Publishes typed text and the quoted bubble as a structured event for optional plugins; unhandled messages continue normally. |

Each delivered text bubble ends with:

```text
---

`3` `deepseek-flash`
```

System notifications, approval controls, progress notices, and lifecycle
messages use `hermes`. Model commentary, pre-confirmation prose, final answers,
split chunks, and recovered queued chunks retain their actual model identity.

## Scope

This plugin owns Weixin transport behavior only. It does **not** choose a model,
log in to Weixin, approve pairing, or generate business content. Models remain
configured by Hermes; pairing and credentials remain owned by the Hermes
profile. Installation does not require a new QR scan when that profile is
healthy.

The quote-action bridge is channel infrastructure, not a dependency on any
business plugin. With no consumer installed, ordinary Weixin behavior is
unchanged.

## Requirements

- Hermes `>=0.21.3,<0.22`
- A configured Hermes Weixin channel
- Python 3.11+
- Linux, WSL2, or a Linux-based Docker/NAS deployment

## Install

```bash
hermes plugins install Awenforever/hermes-wechat-enhance
hermes plugins enable hermes-wechat-enhance
hermes wechat-enhance install-hook
hermes gateway restart
hermes wechat-enhance status
```

`install-hook` is idempotent. It also sets `display.busy_input_mode: queue` so
messages received during a busy turn are processed in order. On uninstall, the
previous value is restored only if the user has not changed it since install.

> When installing through an assistant, ask it to read `SKILL.md`. The contract
> requires preserving existing state, presenting customization, and obtaining
> confirmation before enabling the plugin or sending a real message.

## Configure

Defaults for an already paired personal profile:

```yaml
plugins:
  entries:
    hermes-wechat-enhance:
      settings:
        startup_notification: true
        startup_message: "♻️ Gateway online — Hermes is back and ready."
        capture_messages: true
        legacy_runtime_compat: false
```

| Setting | Default | Meaning |
|---|---:|---|
| `startup_notification` | `true` | Send a ready message after Gateway startup. |
| `startup_message` | shown above | Customize the ready message. |
| `capture_messages` | `true` | Keep a bounded local audit copy of inbound and outbound messages. |
| `legacy_runtime_compat` | `false` | Legacy v0.18 migration only; never enable on v0.21. |

`HERMES_WEIXIN_STARTUP_READY_NOTIFY` takes precedence: `1` selects the default
message, `0`/`false`/`off` disables it, and another non-empty value becomes the
custom message.

## Everyday use

Use Weixin normally. Send `/continue` only for a silent manual resume: every
ordinary inbound message already refreshes the Context Token and attempts FIFO
recovery. Fresh repeated slash commands are accepted; an exact provider replay
is still rejected.

## Upgrade

```bash
hermes plugins install --force Awenforever/hermes-wechat-enhance
hermes wechat-enhance install-hook
hermes gateway restart
hermes wechat-enhance status
```

Queues, counters, audit data, pairing, authorization, and profile configuration
live outside plugin source and are retained across a normal upgrade.

## Migrate from Hermes v0.18

Back up `HERMES_HOME`, install the current plugin, then archive the legacy queue:

```bash
hermes wechat-enhance migrate-v018
```

Legacy pending messages are archived and **not replayed**. New v0.21 installs
must leave `legacy_runtime_compat` disabled.

## Data and privacy

```text
HERMES_HOME/
├── plugins/hermes-wechat-enhance/       plugin source
├── hooks/hermes-wechat-enhance/         runtime hook
└── plugin-data/hermes-wechat-enhance/   counters, FIFO, audit, install state
```

Counter keys use irreversible hashes rather than raw Context Tokens or peer
IDs. Audit records may contain message text and should be protected like chat
backups. Docker deployments must mount `HERMES_HOME` on persistent storage.

## Troubleshoot

<details><summary><strong>Footer is missing or always says <code>hermes</code></strong></summary>

Run `hermes wechat-enhance status`, confirm plugin and hook are enabled, and
restart the Gateway after an upgrade. Model output should show the actual model;
control output should deliberately say `hermes`.
</details>

<details><summary><strong><code>/continue</code> or repeated slash commands are ignored</strong></summary>

Refresh the hook and restart the Gateway. Keep provider message-ID replay
protection enabled; the plugin bypasses only the secondary content fingerprint
for fresh slash-command messages.
</details>

<details><summary><strong>Messages remain pending</strong></summary>

Send any new Weixin message, or `/continue` for a silent resume. If delivery
still fails, inspect channel/network health before clearing any queue.
</details>

<details><summary><strong>A container rebuild lost pairing or state</strong></summary>

Restore the previous `HERMES_HOME` persistent volume before pairing again.
Installing this plugin must not replace Hermes credentials.
</details>

## Uninstall

```bash
hermes wechat-enhance uninstall-hook
hermes plugins remove hermes-wechat-enhance
```

User state, pairing, queues, and audit data are retained unless the operator
explicitly removes them after backup.

## Documentation

- [`SKILL.md`](SKILL.md) — installation and automation contract
- [`docs/PERSISTENCE_CONTRACT.md`](docs/PERSISTENCE_CONTRACT.md) — state ownership and rebuild rules
- [`docs/MAINTAINER_REFERENCE.md`](docs/MAINTAINER_REFERENCE.md) — legacy and maintainer reference

Development incident history and regression invariants are intentionally kept
outside this user-facing README.

## License

[MIT](LICENSE)
