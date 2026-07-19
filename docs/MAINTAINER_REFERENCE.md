# Maintainer Reference

> Archived technical README preserved during the user-facing bilingual redesign.
> This document is for maintainers, audits, migrations, and patch development.

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

## Context-token kernel contract

The accepted v0.18.0 installation applies patch 010.

- Every accepted inbound message refreshes its Context token before ordinary
  text-content suppression.
- Every `text.strip().startswith("/")` slash command bypasses the native
  300-second content-fingerprint dedup layer.
- Native `message_id` replay protection remains enabled.
- `/continue` remains silent: it refreshes the token and drains pending sends.
- All acknowledged text and media messages consume the shared 1–10 budget.
- Per-user delivery transactions are serialized and guarded by token generation.
- Context-token and reply-budget state are reconciled after restart.
- Safe uninstall restores the exact pre-install gateway source and previous hook.

Fresh-install acceptance currently targets Hermes v0.18.0 (`v2026.7.1`).
The `.v017.patch` files are historical migration evidence, not a complete
fresh-install support declaration.

## Patch variant dispatch

Fresh installation is currently accepted for Hermes `v2026.7.1*` (v0.18).
The installer deterministically selects exactly one standard patch per series
entry. Files ending in `.v017.patch` are retained as historical migration
evidence and are never applied to v0.18.

## Ordinary-message queue drain contract

An ordinary inbound message itself is not an outbound queue item. After Hermes
generates its reply, every reply chunk is appended behind all existing pending
items and the same FIFO queue is drained immediately.

Example after a new Context token resets the counter:

```text
existing pending A
existing pending B
new ordinary-message reply C

send order:
A -> 1
B -> 2
C -> 3
pending -> 0
```

The current token's maximum remains 10 acknowledged messages. If the combined
queue exceeds the remaining budget, draining stops at 10 and unacknowledged
items remain pending for a later Context token.

Stable marker: `HERMES_WECHAT_ORDINARY_REPLY_APPEND_THEN_DRAIN_V1`.
## Consolidated Hermes v0.18 patch plan

Fresh installation on Hermes `v2026.7.1*` uses the deterministic series:

```text
003 -> 004 -> 006 -> 007 -> 008 -> 011
```

Patch `011-weixin-v018-consolidated.patch` is a clean diff from the official
v0.18 `weixin.py` to the accepted final runtime. It supersedes legacy Weixin
patches 001, 002, 005, 009 and 010 for fresh v0.18 installation. Those files
remain only as development and migration history and are not executed.

This removes the previously detected malformed patch 005 from the active
installation path while preserving all accepted runtime markers and behavior.

## Portable hook import bootstrap

The active hook no longer assumes that the Hermes data directory is always
`/opt/data`.

It resolves the installed skill directory in this order:

1. `HERMES_WECHAT_ENHANCE_SOURCE_DIR`;
2. `HERMES_SKILLS_DIR/hermes-wechat-enhance`;
3. `HERMES_HOME/skills/hermes-wechat-enhance`;
4. the sibling `skills` directory derived from the hook file location;
5. `/opt/data/skills/hermes-wechat-enhance` as a compatibility fallback.

Installation verification imports the copied hook without injecting an
artificial `PYTHONPATH` and requires `IMPORT_BOOTSTRAP_PORTABLE_OK`.

## Contract-harness adapter initialization

The isolated contract test now constructs `WeixinAdapter` through its real
constructor before replacing network sessions and test stores. This preserves
all official runtime fields, including `split_multiline_messages`, instead of
maintaining a fragile hand-written partial initializer.

Required preflight:

```text
SYNTHETIC_ADAPTER_RUNTIME_INIT_OK
```

This is a test-harness correction and does not change the production queue
contract.

## Idempotent hook deployment and zero residue

The private install-state snapshot is the only rollback source. The installer
never creates untracked `hermes-wechat-enhance.before-install-*` sibling
directories.

Hook equality ignores runtime cache artifacts such as `__pycache__`, `.pyc`,
`.pyo`, `.pytest_cache`, `.mypy_cache` and `.ruff_cache`. A second install
therefore remains a true no-op after the hook has been imported.

Stable marker:

```text
WECHAT_ENHANCE_HOOK_IDEMPOTENT_NO_BACKUP_RESIDUE_V1
```

Lifecycle acceptance checks every matching hook and skill sibling after both
uninstalls.

## v0.18 source-profile upgrade routing

The installer supports three explicitly recognized source profiles:

- `pristine-v018`: official `v2026.7.1` Weixin source, routed through patch 011;
- `legacy-v018`: the previously released Hermes WeChat Enhance runtime,
  identified by its exact Weixin SHA256 and routed through patch 012;
- `hardened-v018`: the final current runtime, where all patches are skipped by
  verified markers.

Unknown modified Weixin sources fail closed before gateway modification.

Patches 011 and 012 converge to the same byte-identical final Weixin source.
This allows both new third-party installation and guarded upgrade from the
current production-image baseline.

## Version resolution in stripped runtime images

The installer verifies the source profile before resolving the Hermes version.
Resolution order is: explicit override, Git tag, `VERSION`, installed package
metadata, then an inference restricted to the verified `pristine-v018`,
`legacy-v018` or `hardened-v018` profiles.

Unknown source content still fails closed before gateway modification.

Stable marker:

```text
HERMES_WECHAT_VERSION_FROM_VERIFIED_SOURCE_PROFILE_V1
```

## Hermes v0.18 version-family normalization

Hermes v0.18.0 may be represented by runtime package metadata as `v0.18.0`
while the corresponding official release tag is `v2026.7.1`. These identifiers
belong to the same accepted source and patch family.

Accepted identifiers are normalized to:

```text
VERSION_FAMILY=v2026.7.1
```

The original detected version and its provenance remain in the install log.
Source-profile verification still occurs first, and unknown versions or source
content fail closed.

Stable marker:

```text
HERMES_WECHAT_V018_VERSION_FAMILY_NORMALIZATION_V1
```

## Transactional canonical-source lifecycle

The transaction covers the three gateway files, active hook and canonical
installed skill source. Snapshotting occurs before canonical-source replacement.

Existing source and hook trees are restored after a failed install or normal
uninstall. Freshly created trees are removed. Timestamped source backup
directories are not created.

Uninstall is fail-closed when gateway, hook or canonical source content has
diverged from both pre-install and installed states. The install state and
external change are preserved.

Test-only fault stages are selected with
`HERMES_WECHAT_ENHANCE_FAULT_INJECT_STAGE`.

Stable markers:

```text
HERMES_WECHAT_TRANSACTIONAL_SOURCE_STATE_V1
HERMES_WECHAT_FAULT_INJECTION_TEST_V1
```

## Install-state canonical source-path integrity

The transaction snapshot keeps the canonical skill source parameter separate
from gateway-file iteration. Gateway files use a dedicated `gateway_file`
variable, preventing the manifest source path from being overwritten with
`gateway/run.py`.

A direct regression test requires:

```text
INSTALL_STATE_SOURCE_PATH_REGRESSION_OK
```

Stable marker:

```text
HERMES_WECHAT_TRANSACTION_SNAPSHOT_SOURCE_PATH_V2
```

## Git metadata and dirty working-tree preservation

The installer applies patches without `git init`, `git add`, `git commit`,
`git reset` or persistent `git config` changes. Distributed runtime images may
intentionally contain valid working-tree files that differ from embedded Git
HEAD.

Rollback and uninstall always restore the three managed gateway files from
byte-for-byte transaction snapshots. Git HEAD, index/status, config and
unrelated dirty files remain unchanged.

Direct regression marker:

```text
INSTALL_STATE_GIT_WORKTREE_PRESERVATION_OK
```

Stable markers:

```text
HERMES_WECHAT_GIT_METADATA_PRESERVATION_V1
HERMES_WECHAT_EXACT_FILE_BACKUP_RESTORE_V1
```
