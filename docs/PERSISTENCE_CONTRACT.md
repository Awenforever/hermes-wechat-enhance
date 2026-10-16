# Persistence and recovery contract

`HERMES_HOME` is the active Hermes profile, not a second home nested inside it.
It must be durable on Docker/NAS and private to the operator on every platform.
Native Windows/Linux/WSL installations do not need Docker volume configuration.

| Owned resource | Location relative to HERMES_HOME | Lifecycle |
|---|---|---|
| Plugin source | `plugins/hermes-wechat-enhance` | Replaceable from public Git |
| Active hook | `hooks/hermes-wechat-enhance` | Installed/uninstalled through CLI |
| Runtime state | `plugin-data/hermes-wechat-enhance` | Preserved on upgrade/uninstall |
| CLI backup/manifest | `plugin-data/hermes-wechat-enhance/hook-backups`, `install` | Preserve for rollback |
| Shell installer transaction | `.hermes/wechat-enhance/install-state` | Existing management path; do not move blindly |

The shell installer also supports a canonical skill source selected by
`HERMES_WECHAT_ENHANCE_SOURCE_DIR`/`HERMES_SKILLS_DIR`. Never confuse replaceable
source with runtime state. Public installation uses the Hermes plugin installer
and native CLI.

## Runtime contents and privacy

Counters, context-fill snapshots, durable `send-queue.sqlite3`, quote cache,
audit and install metadata are user state. Queue rows contain pending text and
model labels. A private routing table retains destination IDs for restart
recovery, but no context tokens or credentials. Legacy hash-only routes recover
only from exact trusted Core peers; unresolved rows are preserved and reported.
Never infer a destination from a message body or latest conversation.

Scoped queued/acknowledged/withdrawn observations do not prove external
delivery, reading, consent or satisfaction. Withdrawal is local suppression,
not remote recall. Quote mappings may contain message text and server IDs.
Audit redaction is defense in depth, not a promise to recognize every secret.

POSIX files use private permissions; Windows state must live under a private
user/profile ACL. Do not place a profile in a public shared directory. Docker
must mount the actual HERMES_HOME, not just source.

## Upgrade, rollback and uninstall

- Preserve Core-owned pairing, authentication, authorization, sessions, memory,
  tasks and configuration. This plugin does not own or patch Core.
- Back up source, active hook and runtime state before production migration.
  SQLite requires its backup API or a confirmed stopped-writer snapshot;
  copying only a live database without its WAL is not a consistent backup.
- Schema changes are additive. Keep source rollback separate from state
  rollback: restoring an old whole profile can destroy newer traffic.
- Failed installation restores only managed source/hook state, and must not
  silently replace files changed by another actor.
- Uninstall preserves pending messages, counters, quotes, audit and all
  Core-owned state. Purge requires separate explicit destructive confirmation
  and must be limited to plugin-owned paths.
- A healthy profile must not need a new scan/pair merely for an upgrade.

`scripts/verify-persistence.py` checks storage placement, not Gateway loading,
actual delivery or full backup restorability. Qualify public-source
install→upgrade→uninstall→reinstall separately from live behavior.
