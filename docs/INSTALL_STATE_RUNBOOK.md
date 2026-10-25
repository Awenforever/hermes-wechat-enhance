# Install-state runbook

**Revision 2026-10-25 (Asia/Shanghai):** reviewed against
`scripts/manage-install-state.py` in the 3.5.0 tree. `--home` is the Hermes
home (`/opt/data` in the NAS container), not `/opt/data/.hermes`; the state
path is `<home>/.hermes/wechat-enhance/install-state`.

This runbook covers the shell installer transaction state managed by
`scripts/manage-install-state.py`. The state exists so that install and
uninstall can be transactional. It is not runtime user data and it is not a
lock.

Use this document only for diagnosis or an authorized repair. Normal installs,
upgrades and uninstalls must go through `install.sh` / `uninstall.sh`.

## 1. Layout and fields

State root: `<HERMES_HOME>/.hermes/wechat-enhance/install-state/`.

```
install-state/
  manifest.json          0600, atomically replaced
  backups/hook/          pre-install copy, present only if the hook existed
  backups/source/        pre-install copy, present only if the source existed
```

Version 3 manifest fields:

| Field | Meaning |
|---|---|
| `version` | `3` |
| `active` | State is in use |
| `installed_recorded` | `record-installed` completed |
| `gateway` / `hook` / `source` | Absolute paths this state is bound to |
| `hook_existed` / `source_existed` | Whether a pre-install copy was made |
| `hook_pre_hash` / `source_pre_hash` | Hash captured by `snapshot` |
| `hook_installed_hash` / `source_installed_hash` | Hash captured by `record-installed` |
| `core_mutation` | Always `false`; the plugin does not modify Core |

`atomic_json` writes a temporary file in the same directory, replaces the
manifest, and chmods it to `0600`.

## 2. Hash semantics

`tree_hash()` sorts entries, then hashes the relative path, entry type and
content (or symlink target). It ignores `__pycache__`, `.pytest_cache`,
`.mypy_cache`, `.ruff_cache` directories anywhere in the tree, and `.pyc` /
`.pyo` files.

It does **not** ignore `.git`. A fetch, checkout, reset, commit or even a ref
update can change `tree_hash()` while the working files appear unchanged.
After any such Git operation, either run `record-installed` again or accept
that `restore` will fail closed.

A missing path hashes to `None`; an empty existing directory hashes to the
SHA-256 of the empty string.

## 3. Command semantics

All commands take the same path arguments:

```
--gateway /opt/hermes
--home /opt/data
--hook /opt/data/hooks/hermes-wechat-enhance
--source /opt/data/plugins/hermes-wechat-enhance
```

| Command | Behavior |
|---|---|
| `snapshot` | If an **active v3** manifest exists, print `INSTALL_STATE_REUSED` and return without writing anything. Otherwise remove the state root, copy existing hook/source into `backups/`, write pre-hashes and `installed_recorded=false`. |
| `record-installed` | Requires a manifest. Recomputes the current hook/source hashes into `*_installed_hash` and sets `installed_recorded=true`. Leaves paths and pre-hashes untouched. |
| `restore` | Resolves all three paths and rejects a mismatch with `gateway path mismatch`, `hook path mismatch` or `source path mismatch`. Then compares current hook/source hashes against `{pre, installed}`. Any divergence prints `SOURCE_DIVERGED; refusing restore: hook,source` (only the divergent names) and returns non-zero. On success, removes current hook/source and restores the backups where `*_existed` is true, then removes the state root. |
| `rollback` | Same as `restore` but skips the divergence check. Destructive; use only with explicit authorization and a fresh backup. |
| `status` | Prints `active`, `installed_recorded`, `core_mutation`, `hook_existed`, `source_existed`. |

Critical: **`snapshot` is not a repair.** If a stale active manifest exists, it
reuses the stale `gateway`/`hook`/`source` paths. Re-running `install.sh` in that
condition prints `INSTALL_STATE_REUSED` and does not fix path drift. This was
the production failure mode repaired on 2026-10-24.

Also note that the manager keeps a **pre-install** backup, not a backup of the
previous installed release. After `record-installed` refreshes the installed
hash, `restore` accepts the current tree and restores the pre-install tree.

## 4. Preflight

Before any write:

1. Confirm an explicit, current authorization for the exact state repair. A
   previous authorization or a full-access permission mode does not carry over.
2. Confirm a single executor. Check that no `install.sh`, `uninstall.sh`,
   `manage-install-state.py`, `verify-self-install.py` or package operation is
   running. The state file is not a lock.
3. Record the gateway PID, its uid and start time; record `runtime-status.json`
   mtime and content hash. Do not restart the gateway for a state-only repair.
4. Record the manifest stat, bytes and SHA-256; record hook/source
   `tree_hash()` values and the source Git HEAD/status.
5. Verify that the manifest paths resolve to the active hook and source.
6. Prepare a root-only backup directory on the same filesystem. Back up before
   moving anything.

Never hand-edit the manifest and never delete the state directory as a "reset".

## 5. Diagnose drift

Read-only starting points:

```bash
STATE_ARGS="--gateway /opt/hermes --home /opt/data \
  --hook /opt/data/hooks/hermes-wechat-enhance \
  --source /opt/data/plugins/hermes-wechat-enhance"

python3 scripts/manage-install-state.py status $STATE_ARGS
stat -c '%a %u:%g %s %y %n' \
  /opt/data/.hermes/wechat-enhance/install-state/manifest.json
```

Interpretation:

| Observation | Meaning |
|---|---|
| `status` prints `"active": false` | No manifest, or an inactive one. `uninstall.sh` will fail with `INSTALL_STATE_MISSING`; this is not a no-op. |
| `source` or `hook` differs from the active path | Path drift. `snapshot` will reuse it; repair is required. |
| `installed_recorded=false` | Install did not reach the recording step. |
| Current hash not in `{pre, installed}` for hook or source | `restore` will fail closed. |
| Pre-hash equals installed hash and both equal the current active tree | The state was rebuilt against the current tree; `restore` is a current-tree no-op. |

To compute hashes without changing state:

```bash
python3 - <<'PY'
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location(
    "mis", "/opt/data/plugins/hermes-wechat-enhance/scripts/manage-install-state.py")
mis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mis)
for p in ("/opt/data/hooks/hermes-wechat-enhance",
          "/opt/data/plugins/hermes-wechat-enhance"):
    print(mis.tree_hash(Path(p)), p)
PY
```

Run this with `PYTHONDONTWRITEBYTECODE=1` and as the intended state owner.

## 6. Authorized repair procedure

This is the production pattern used on 2026-10-24. It rebuilds state only; it
does not reinstall the hook or source.

1. **Freeze the window.** Record start/end time in Asia/Shanghai, the executor,
   and confirm no concurrent track is writing the install tree.
2. **Capture pre-repair evidence.** Manifest bytes/SHA-256, `stat`, hook and
   source hashes, source Git state, gateway PID/start time, runtime-status
   snapshot. Store it root-only.
3. **Back up.** Under
   `plugin-data/hermes-wechat-enhance/install-state-backups/<timestamp>/`:
   - copy the whole state directory to `install-state.copy`;
   - move the original state directory to `install-state.removed`;
   - verify both manifests still hash to the pre-repair value;
   - verify the removed `backups/hook` and `backups/source` still match the old
     `hook_pre_hash` / `source_pre_hash`.
4. **Rebuild as the runtime uid.** Use the production manager, not a hand-edited
   manifest, with `PYTHONDONTWRITEBYTECODE=1`:

   ```bash
   python3 scripts/manage-install-state.py snapshot $STATE_ARGS
   python3 scripts/manage-install-state.py record-installed $STATE_ARGS
   ```

   Because the old state was moved aside, `snapshot` creates a new v3 manifest
   whose pre-hashes come from the current active trees; `record-installed` then
   records the installed hashes.
5. **Do not run `install.sh` to repair state.** With an active manifest it would
   reuse the stale state; with a fresh state it would perform a full install and
   may touch runtime paths that are outside a state-only authorization.
6. **Validate before declaring success.**
   - `status` shows `active=true` and `installed_recorded=true`.
   - Manifest paths equal the active gateway/hook/source.
   - `hook_pre_hash == hook_installed_hash == current hook == backups/hook`.
   - `source_pre_hash == source_installed_hash == current source ==
     backups/source`.
   - The current hook/source hashes are both in `{pre, installed}`, so
     `restore` would pass its precondition.
   - Gateway PID and `runtime-status.json` are unchanged.
   - Manifest is `0600` and owned by the intended runtime user.
7. **Keep the old state directory.** It contains the only automatic backup of
   the previous rollback target. Do not delete it as cleanup.
8. **Append** the result, evidence hashes and residual risks to
   `QODER_STATUS.md`.

## 7. After a repair: restore and uninstall behavior

- If the repaired state was built from the current tree, `restore` accepts the
  current hashes and restores the pre-install backup. When the tree existed
  before installation, this is a no-op against the current tree; when it did
  not exist, `restore` removes the hook/source and the state.
- The old rollback target (for example the 3.0.1 tree) exists only inside the
  backup's `install-state.removed/backups/`. The manager will not use it again.
- A Git-only change in the source invalidates `restore` because `.git` is
  hashed. Run `record-installed` to accept the new installed hash, or leave the
  state failing closed. Rebuilding with `snapshot` requires moving the current
  state aside first.
- `rollback` skips the divergence check. It removes current hook/source and
  restores the pre-install backup. Treat it as a destructive operation: take a
  fresh backup and obtain explicit authorization.

## 8. Permissions and K5

- The manifest is created `0600` by whichever user runs the manager. A manifest
  created by root is not readable by runtime uid 10000. Do not alternate
  installer users; use the runtime uid for state operations.
- The installer preserves delivery ownership and modes. In the 2026-10-24
  isolated T1 run, the release archive produced `1000:10` files, and the
  operator chowned the installed plugin and hook to `1000:1000`.
- `verify-self-install.py` calls `py_compile.compile(..., doraise=True)` and
  writes `__pycache__` even under `PYTHONDONTWRITEBYTECODE=1`. Clear both
  plugin and hook caches explicitly and verify they are gone.
- Do not mechanically `chown -R` or `rm -rf` an active hook/source as part of a
  state repair. Production currently retains `1000:1000` files and root-owned
  `__pycache__`; runtime uid 10000 can read them. Cleaning that up requires a
  separate authorized maintenance window.

## 9. Never do

- Delete or recreate the state directory without a verified backup.
- Hand-edit or merge manifest JSON.
- Run `install.sh` expecting it to fix a stale active manifest.
- Run `restore` or `rollback` without checking resolved paths and current
  hashes.
- Use `rollback` as a routine rollback command.
- Run two installers, or an installer and an uninstaller, at the same time.
- Treat the state manifest as a lock or as runtime user data.

## 10. Recorded production execution

| Item | Value |
|---|---|
| Machine | `ugreen-nas`, container `hermes-v0213-gateway` |
| Authorization | Separate 2026-10-24 authorization, install-state repair only |
| Write window | 2026-10-24 19:04:56–19:05:07 +08 |
| Old state | `source=/opt/data/skills/hermes-wechat-enhance` (stale 3.0.1), manifest SHA-256 `4873042cae72ebf7896708b6ad1dbd3ab7fb8768ea1955debc6a380c2773b5a4` |
| Backup | `/opt/data/plugin-data/hermes-wechat-enhance/install-state-backups/20261024T190456+0800/` |
| New manifest | 641 bytes, `600 hermes:hermes`, SHA-256 `c5a23e10507821843f7d85f05c36f28cb34deaff622ea63d7cd67b7d36690344` |
| Validation | 20/20 checks; hook/source pre = installed = current = backups |
| Unchanged | Gateway PID `2216614`; `runtime-status.json` content and mtime |
| Not run | `install.sh`, uninstall, restore/rollback, Gateway restart, real send |
| Evidence archive | `2026-10-24-qoder-wechat-install-state-repair-evidence.tar.gz`, SHA-256 `2d4ca2c5a00c204736190c9acb5e2635ff01e703bfb0fb63be922738a86b8ec4` |

Residual risks from that repair:

1. `restore` is a current-tree no-op; the automatic rollback target is now the
   current 3.4.4 tree, not 3.0.1.
2. The source hash includes `.git`, so later Git operations require
   `record-installed` or a fresh `snapshot`.
3. The legacy schema-1 manifest was backed up but not modified.
4. A full `install.sh` uninstall/reinstall cycle was not part of the
   state-only window.
5. The old state manifest is root-owned `0600`; reading it requires container
   root.
