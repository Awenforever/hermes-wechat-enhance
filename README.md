<div align="center">

# Hermes WeChat Enhance

**Reliable Weixin delivery, truthful model attribution, and safer lifecycle management for Hermes.**

[简体中文](README_CN.md) · [Quick Start](#quick-start) · [Features](#features) · [Troubleshooting](#troubleshooting)

![Hermes](https://img.shields.io/badge/Hermes-v0.18-4c6ef5)
![Platform](https://img.shields.io/badge/Platform-Weixin-07c160)
![Install](https://img.shields.io/badge/Install-Transactional-7950f2)
![Runtime](https://img.shields.io/badge/Runtime-Docker%20%7C%20Linux-495057)

</div>

---

## What is it?

Hermes WeChat Enhance is a community add-on for the Hermes Weixin gateway. It improves what users see in Weixin and makes delivery, installation, upgrades, rollback, and container rebuilds safer.

It is designed for the Hermes v0.18 release family (`v0.18.0` / `v2026.7.1`). Unknown or modified gateway sources are rejected before any gateway file is changed.

## Features

| Feature | What it means for users |
|---|---|
| **Truthful model footer** | Model-generated replies show the real model name. Hermes lifecycle and control messages show `hermes`. |
| **Per-message context counter** | Every accepted inbound message starts a fresh Context token. The first acknowledged reply starts at `1`. |
| **Acknowledgement-first accounting** | Failed sends do not consume the counter. A message is counted only after Weixin acknowledges it. |
| **Reliable FIFO delivery** | Pending messages keep their order. New replies are appended behind older pending items. |
| **Silent `/continue`** | Refreshes the Context token and drains pending messages without sending a command reply. |
| **Idempotent delivery metadata** | Stable delivery IDs help business callers avoid duplicate delivery. |
| **Transactional install and rollback** | Failed installation restores the previous gateway, hook, source, and Git state. |
| **Container persistence** | Weixin pairing, configuration, and source survive a correctly configured container rebuild. |
| **Fail-closed uninstall** | Uninstall refuses to overwrite unrelated external changes. |

## What you will see in Weixin

A model reply ends with a footer similar to:

```text
`1` `deepseek-v4-pro`
```

A Hermes system message uses:

```text
`2` `hermes`
```

The number is the successful outbound-message count for the latest Context token.

### Counter rules

- Every valid inbound user message refreshes the Context token.
- The first acknowledged outbound message under the new token is `1`.
- Text and media acknowledgements share the same counter.
- Failed sends do not consume a number.
- The maximum is 10 acknowledged messages per Context token.
- A later Hermes system message may therefore appear as `2`, `3`, and so on.
- `/continue` silently refreshes the token and drains pending messages.

### Slash-command dedup behavior

- Every `text.strip().startswith("/")` slash command bypasses the native
  300-second content-fingerprint dedup layer.
- Native `message_id` replay protection remains enabled.
- Context-token refresh happens before ordinary text-content suppression.

This prevents a repeated slash command from being incorrectly discarded by
content-based deduplication while still blocking replay of the same inbound
message ID.

## Requirements

- Hermes v0.18 family: `v0.18.0` or release tag `v2026.7.1`.
- Python and Bash available in the Hermes runtime.
- For Docker, the Hermes data root should be mounted persistently, normally at `/opt/data`.
- The Gateway must be started with `--accept-hooks`.
- Use a spare Weixin account for real end-to-end testing.

> Do not restart the Docker daemon. Restart only the Hermes Gateway process or its container when a source patch must be reloaded.

## Quick Start

### 1. Install the source

Choose the persistent Hermes data root:

```bash
export HERMES_HOME="${HERMES_HOME:-/opt/data}"
mkdir -p "$HERMES_HOME/skills"
git clone https://github.com/Awenforever/hermes-wechat-enhance.git \
  "$HERMES_HOME/skills/hermes-wechat-enhance"
cd "$HERMES_HOME/skills/hermes-wechat-enhance"
```

When installing from a release branch or tag, switch to it before running the installer.

### 2. Install and verify

```bash
bash scripts/install.sh
python3 scripts/verify-self-install.py
python3 scripts/test-reliable-delivery-contract.py
python3 scripts/verify-persistence.py
bash scripts/check-consistency.sh
```

The installer is transactional. If a supported source profile cannot be verified, installation stops before modifying the Gateway.

### 3. Reload only the Gateway

Restart only the Hermes Gateway process or Gateway container so the patched Python source is loaded.

Example:

```bash
docker restart <your-hermes-gateway-container>
```

Do not restart the Docker daemon.

### 4. Pair Weixin and start the Gateway

```bash
hermes gateway --accept-hooks setup
hermes gateway --accept-hooks run
```

If `hermes` is not in `PATH` inside the official container:

```bash
/opt/hermes/.venv/bin/hermes gateway --accept-hooks setup
/opt/hermes/.venv/bin/hermes gateway --accept-hooks run
```

Complete the Weixin pairing flow in the target environment. Pairing state belongs in the persistent Hermes data volume, not in the repository.

## Daily Use

Use Hermes in Weixin normally. No special prefix is required.

### `/continue`

Send:

```text
/continue
```

It does not produce a command reply. It refreshes the Context token and attempts to drain pending outbound messages in FIFO order.

### Reliable delivery behavior

For a successful text send:

```text
peek pending item
→ send
→ receive Weixin acknowledgement
→ commit the counter
→ remove the item from the queue
```

On failure, the item remains pending and the counter is unchanged. Business-critical integrations should also maintain their own durable outbox and reuse a stable delivery ID.

## Update

From the installed source directory:

```bash
git fetch --all --prune
git pull --ff-only
bash scripts/install.sh
python3 scripts/verify-self-install.py
python3 scripts/test-reliable-delivery-contract.py
python3 scripts/verify-persistence.py
bash scripts/check-consistency.sh
```

Then restart only the Hermes Gateway process or container.

The installer recognizes supported pristine, legacy, and already-hardened v0.18 source profiles. Unknown modifications fail closed.

## Verify an Existing Installation

```bash
cd "${HERMES_HOME:-/opt/data}/skills/hermes-wechat-enhance"
python3 scripts/verify-self-install.py
python3 scripts/test-reliable-delivery-contract.py
python3 scripts/verify-persistence.py
bash scripts/check-consistency.sh
```

A healthy installation should pass every command without changing Weixin credentials or sending a real message.

## Uninstall

```bash
cd "${HERMES_HOME:-/opt/data}/skills/hermes-wechat-enhance"
bash scripts/uninstall.sh
```

Safe uninstall restores the exact pre-install managed Gateway files and previous hook/source state. Weixin pairing and user/runtime data are preserved by default.

Uninstall fails closed when managed files have unrelated external changes. Do not force-delete the install state; inspect and resolve the divergence first.

## Removing User Data

There is intentionally no automatic one-command purge in the public workflow.

Pairing, account, and runtime data are preserved to prevent accidental loss. Full deletion is destructive and must be performed only after:

1. stopping the Gateway;
2. completing safe uninstall;
3. backing up the persistent Hermes data root;
4. explicitly confirming that Weixin pairing and runtime history may be erased.

See [Persistence Contract](docs/PERSISTENCE_CONTRACT.md) before deleting any data.

## Docker and Persistence

In Docker:

- mount the Hermes data root persistently, normally at `/opt/data`;
- keep skills, hooks, configuration, pairing, and account state on that volume;
- treat the container filesystem as disposable;
- recreate the container with the same volume and required network configuration;
- reinstall the skill from the source retained on the persistent volume.

In bare Linux or WSL, normal local filesystem persistence is sufficient.

See [Persistence Contract](docs/PERSISTENCE_CONTRACT.md) for the complete source-versus-user-data rules.

## Troubleshooting

### `hermes: command not found`

Use the runtime path:

```bash
/opt/hermes/.venv/bin/hermes
```

### Weixin reports `session timeout`

The saved Weixin session has expired. Run setup again in the same target environment:

```bash
hermes gateway --accept-hooks setup
```

Then start the Gateway again.

### Replies have no model footer

Confirm that:

- installation verification passes;
- the Gateway was reloaded after installation;
- the Gateway was started with `--accept-hooks`;
- no other skill overwrote the managed Weixin gateway file.

### The counter does not reset to `1`

Run:

```bash
python3 scripts/test-reliable-delivery-contract.py
python3 scripts/verify-self-install.py
```

Check the Gateway log for the latest Context-token refresh and send acknowledgement. Do not edit reply-budget state manually.

### Messages remain pending

Send `/continue` after the Weixin session is healthy. It refreshes the Context token and retries pending messages in FIFO order.

### Uninstall refuses to continue

A managed Gateway, hook, or source file differs from both the pre-install and installed state. This is a safety stop. Preserve the install state and inspect the external change instead of forcing removal.

### Container rebuild loses configuration or pairing

The persistent Hermes data root was not mounted correctly, or the replacement container does not use the same volume. Restore the correct volume before running setup again.

## Security and Privacy

- Never commit `.env`, account files, pairing data, cookies, tokens, logs, or QR URLs.
- Keep the Hermes data root private and persist it outside the disposable container layer.
- Use a spare account for real Weixin acceptance testing.
- Do not send real messages from automated tests without explicit approval.
- The installer does not store Weixin credentials in its transaction snapshot.
- Git metadata, index state, configuration, and unrelated dirty files are preserved.

## Limitations

- Fresh installation currently targets the Hermes v0.18 family only.
- Weixin sessions can expire and may require re-pairing.
- The in-process queue is not a replacement for a durable business outbox.
- The shared counter is limited to 10 acknowledged outbound messages per Context token.
- Full user-data purge is intentionally not automated.
- This add-on cannot remove limitations imposed by Hermes, Weixin, the selected model provider, or the host network.

## Documentation

| Document | Audience |
|---|---|
| [README_CN.md](README_CN.md) | Chinese user guide |
| [SKILL.md](SKILL.md) | Hermes skill contract |
| [Persistence Contract](docs/PERSISTENCE_CONTRACT.md) | Storage and container-rebuild rules |
| [Maintainer Reference](docs/MAINTAINER_REFERENCE.md) | Patch architecture and historical technical details |
| [Customization Checklist](CUSTOMIZATIONS.md) | Upgrade and patch-maintenance checklist |
| [Impact Matrix](IMPACT_MATRIX.md) | Managed files and behavior impact |
| [Patch Changelog](patches/CHANGELOG.md) | Patch evolution |

## Support

Before reporting an issue, include:

- Hermes version;
- container or bare-Linux environment;
- the failing verification command;
- sanitized error lines;
- whether the Gateway was started with `--accept-hooks`.

Never include credentials, account identifiers, tokens, cookies, QR URLs, or full configuration files.

## License

This release candidate does not currently declare a repository license. Do not assume redistribution rights until the maintainers add a `LICENSE` file.

<details>
<summary><strong>Maintainer inventory used by consistency checks</strong></summary>


### Patch files

- [`patches/001-weixin-continue-hook.patch`](patches/001-weixin-continue-hook.patch)
- [`patches/001-weixin-continue-hook.v017.patch`](patches/001-weixin-continue-hook.v017.patch)
- [`patches/002-weixin-footer-hook.patch`](patches/002-weixin-footer-hook.patch)
- [`patches/002-weixin-footer-hook.v017.patch`](patches/002-weixin-footer-hook.v017.patch)
- [`patches/003-gateway-system-metadata.patch`](patches/003-gateway-system-metadata.patch)
- [`patches/004-gateway-model-propagation.patch`](patches/004-gateway-model-propagation.patch)
- [`patches/005-weixin-send-queue.patch`](patches/005-weixin-send-queue.patch)
- [`patches/006-gateway-interim-model-metadata.patch`](patches/006-gateway-interim-model-metadata.patch)
- [`patches/007-gateway-interim-model-strict-source.patch`](patches/007-gateway-interim-model-strict-source.patch)
- [`patches/008-gateway-footer-model-full-send-rails.patch`](patches/008-gateway-footer-model-full-send-rails.patch)
- [`patches/009-weixin-reliable-delivery-contract.patch`](patches/009-weixin-reliable-delivery-contract.patch)
- [`patches/010-weixin-context-token-kernel-hardening.patch`](patches/010-weixin-context-token-kernel-hardening.patch)
- [`patches/011-weixin-v018-consolidated.patch`](patches/011-weixin-v018-consolidated.patch)
- [`patches/012-weixin-v018-legacy-upgrade.patch`](patches/012-weixin-v018-legacy-upgrade.patch)

### Reference documents

- [`references/architecture-analysis.md`](references/architecture-analysis.md)
- [`references/development-blueprint.md`](references/development-blueprint.md)
- [`references/docker-build-and-test.md`](references/docker-build-and-test.md)
- [`references/isolated-audit-pattern.md`](references/isolated-audit-pattern.md)
- [`references/migration-test-patterns.md`](references/migration-test-patterns.md)
- [`references/side-by-side-testing.md`](references/side-by-side-testing.md)
- [`references/v017-full-audit.md`](references/v017-full-audit.md)
- [`references/v017-model-propagation-chain.md`](references/v017-model-propagation-chain.md)
- [`references/v018-migration-pitfalls.md`](references/v018-migration-pitfalls.md)
- [`references/v018-model-propagation-bug.md`](references/v018-model-propagation-bug.md)
- [`references/v018-weixin-changes.md`](references/v018-weixin-changes.md)

</details>
