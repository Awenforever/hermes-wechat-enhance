# Ownership and boundaries

**Status as of 2026-10-25 (Asia/Shanghai).** This document records artifact
ownership, authorization boundaries and the document authority map. It does
**not** appoint a product owner: product ownership is user-designated;
cross-agent execution registration lives in the shared handoff and, as of
2026-10-26, in the private `hermes-collab-center` (see "Current execution
tracks" below). This document grants no production
authorization.

## Artifacts

| Artifact | Location | Maintained by | Rules |
|---|---|---|---|
| Public source of truth | `https://github.com/Awenforever/hermes-wechat-enhance` | Repository maintainers acting for the user-designated product owner | Releases, tags and public merges are separate authorized actions |
| Release identity | Git tags / GitHub releases in that repository | Same | Acceptance evidence must be recorded in `docs/RELEASE_ACCEPTANCE.md` |
| Production plugin source | `/opt/data/plugins/hermes-wechat-enhance` inside the NAS gateway container `hermes-v0213-gateway` | The single executor holding the production window | Host mount is private (`0700`, uid 10000); use `docker exec`, not host access. The directory is a git worktree with intentional local modifications — never `git checkout` or `git clean` it |
| Active hook | `/opt/data/hooks/hermes-wechat-enhance` | Installed and replaced by `scripts/install.sh` / `scripts/update.sh` | Transactional install; do not edit in place |
| Runtime state | `/opt/data/plugin-data/hermes-wechat-enhance` | The plugin at runtime | Durable across upgrade/uninstall; back up with the SQLite online-backup API |
| Send queue | `.../send-queue.sqlite3` | The plugin only | Durable FIFO; rows leave only on acknowledged send or explicit withdrawal |
| Runtime queue mirror | `.../runtime.sqlite3` (`outbound_queue`) | The plugin only | Observability/compatibility mirror; not a second FIFO |
| Shared handoff | NAS `~/Work/Hermes/2026-10-15-qoder-wechat-enhance-handoff/` | Each agent writes only its own status | Not a lock; not an authorization |

## Hard boundaries

- This plugin is the sole owner of Weixin FIFO, Context Token refresh and
  transport retry. Other plugins must not build a second WeChat send queue
  (NAS `AGENTS.md` K16).
- Never modify Hermes Core (`/opt/hermes`) or another plugin to make this
  plugin work. Core changes require a separate, explicitly authorized track.
- Production writes, Gateway restarts and real Weixin sends each require
  per-window user authorization. Documentation, status files and a full-access
  permission mode do not grant it.
- Never write credentials, private message content, Weixin chat IDs, email
  subjects/senders or signatures into this repository or the shared documents.
- Tests must use a one-off `HERMES_*_STATE_ROOT`; never point tests at
  production data.

## Document authority map

| Fact | Authoritative document |
|---|---|
| Public behavior, install and troubleshooting | `README.md`, `README_CN.md`, `SKILL.md` |
| Release acceptance and evidence | `docs/RELEASE_ACCEPTANCE.md` |
| Design rationale and regression invariants | `docs/DEVELOPMENT_MEMORANDUM.md` |
| Data ownership and rebuild rules | `docs/PERSISTENCE_CONTRACT.md` |
| Install-state diagnosis and repair | `docs/INSTALL_STATE_RUNBOOK.md` |
| Change-impact checklist | `IMPACT_MATRIX.md` |
| Current cross-agent task/status registration | NAS handoff `README.md` and each agent's `*_STATUS.md` |
| Machine identities, network and production map | NAS `~/Work/AGENTS.md` (machine table is the SSOT) |
| Documentation rules (SSOT, banned terms, as-of) | NAS `~/Work/DOC_GOVERNANCE.md` |

## Current execution tracks

Do not copy volatile names or status into this file. Read the append-only
development log in the private `hermes-collab-center` repository
(`projects/plugins/wechat-enhance/LOG.md`) for current status, and the shared
handoff `README.md` (executor registration) plus the frozen `*_STATUS.md`
files for historical evidence. A registration is neither a lock nor an
authorization; the single-executor rule and per-window user authorization
still apply.

## Change control

A behavior or release change updates `docs/RELEASE_ACCEPTANCE.md` and
`docs/DEVELOPMENT_MEMORANDUM.md` in the same commit. A version bump also
updates `plugin.yaml`, both README badges and `scripts/check-consistency.sh`.
Adding or removing a required file updates both the CI required-file list and
`IMPACT_MATRIX.md`.
