# Release acceptance — Hermes WeChat Enhance

**Current status as of 2026-10-25 22:10 +08 (Asia/Shanghai).**
Production runs the `3.5.0` release metadata over the queue-driven FIFO runtime
tree `ce418de`; the four metadata files now match release commit `7f0f14f`
(§12.9). T1, T2 and the T3 WSL2 thin smoke pass on the 3.4.4 baseline; T4
passes through Gateway boot on Windows 11 native; a real user-triggered Weixin
round trip completed on 2026-10-25; the Gateway was restarted under the FIFO
redesign and again for the 3.5.0 metadata alignment. Full 3.5.0 four-platform
acceptance has **not** been re-executed: the 3.5.0 delta is the FIFO drain logic
plus metadata, and §12.7–§12.9 record the evidence actually collected. Do not
describe 3.5.0 as fully accepted on every platform until a fresh four-platform
run is recorded.

**Update 2026-10-25 (deployed):** PR #8 merged, production K5 cleanup and a
Gateway restart are done, and T4 passes through Gateway boot on Windows 11
native. The queue-driven FIFO redesign (`afe4dd7`, docs `ce418de`) was deployed
to production on 2026-10-25 18:12 +08 and the Gateway restarted under it
(pid 2648379); boot checks pass and the queue is empty. A real user-triggered
Weixin round trip completed on 2026-10-25: an authorized restart recovered a
wedged send session at 18:29 +08, and a fresh round trip at 18:33 +08 completed
without intervention; details in §12.7. Release `3.5.0` was tagged from
`7f0f14f` at 18:53 +08; production metadata was aligned and the Gateway
restarted at 22:06–22:08 +08 (§12.8–§12.9).

**Reading order:** §12 is the current record. §1–§11 preserve the 3.4.4
baseline; where they conflict with §12, §12 wins.

This record follows `PLUGIN_TEST_CONTRACT.md` and the release gate in
`SKILL.md`. It supplements, but never replaces, `scripts/verify-self-install.py`
and the regression suite.

## 1. Release identity

| Item | Value |
|---|---|
| Version | `3.4.4` (`plugin.yaml`) |
| Public tag | annotated `v3.4.4`, tag object `6dccc98528f8b01b2b5317e09034c6a02d6e63d6` |
| Commit | `f82fbc797e885c5599e65afb7b17d23f9ad538c5` |
| Tree | `02112851e61c3c4ef0dea66b8c9b7a84c496e966` |
| Published | 2026-10-18T10:18:08Z |
| Declared Hermes range | `>=0.21.3,<0.22` |
| Production reference | NAS/Docker gateway runs the same commit, tree, version and hook hashes; checked 2026-10-24 13:11 +08 |

The acceptance branch `qoder/residual-closure-20261024` adds one test-only
commit, `5c9d51147a1f12af9969b98b741ecba53f580500`. It is not part of the
published tag and does not change runtime code.

> **Not the current release:** this table records the 3.4.4 baseline. The 3.5.0
> release identity and production alignment are in §12.8 and §12.9.

## 2. Platform matrix

| Target | Environment | Result | Evidence |
|---|---|---|---|
| T1 | NAS/Docker, fresh container, s6-overlay | **PASS** | `t1-residual.log` |
| T2 | Linux native, isolated state root | **PASS** | `t2-regression.log`, `t2-lifecycle.log` |
| T3 | WSL2 Ubuntu-24.04, thin smoke | **PASS after test fix** | `t3-wsl.log`, `t3-repeat.log`, `wsl/repro-flake.log`, `wsl/fix-and-test.log` |
| T4 | Windows 11 native, `os.name == "nt"` | **NOT RUN — no claim** | not applicable |
| Real Weixin behavior | Production transport | **NOT RUN in this cycle** | production runtime-status only |
| Gateway restart | Production gateway | **NOT RUN in this cycle** | not applicable |

## 3. T1 — NAS/Docker (PASS)

Run on 2026-10-24 in a disposable container from the 3.4.4 release tree mounted
read-only at `/release`, with `--network none`, tmpfs `/opt/data` and the
runtime uid set to production's `10000`.

Passed, in order:

- Clean `install.sh` (`INSTALL_OK`, `SELF_INSTALL_VERIFY_OK`,
  `INSTALL_STATE_RECORDED_OK`), installed hook byte-identical to the release
  hook, `plugin.yaml` byte-identical to the release.
- `uid 10000` could read the plugin, hook and manifest and import
  `hermes_wechat_enhance.v021_bubble_footer` plus `gateway.platforms.base`.
- 17/17 regressions: `ENHANCE_REGRESSION_PASS count=17 native=True`.
- Second install was idempotent: `INSTALL_STATE_REUSED` + `INSTALL_OK`.
- Uninstall removed hook, source and install state while preserving
  `plugin-data` user data; reinstall restored the hook and kept the user data.
- Final marker: `T1_LIFECYCLE_OK`.

K5 semantics observed in the disposable container (not product failures):

- The release archive preserved delivery ownership; files arrived as
  `1000:10`, so the operator chowned the installed plugin and hook to
  `1000:1000`, matching production.
- `verify-self-install.py` compiles plugin and hook sources with
  `py_compile.compile(..., doraise=True)`, which writes `__pycache__` even when
  `PYTHONDONTWRITEBYTECODE=1` is set. The test removed both cache directories
  explicitly and asserted zero remain.
- The install-state manifest was created `0600 root:root` when the installer ran
  as root. Production runs the manager as uid `10000`; alternating installer
  users is a known hazard. See `docs/INSTALL_STATE_RUNBOOK.md`.

Evidence: `t1-residual.sh` sha256 `67e1d92c…9b1fe`; `t1-residual.log` sha256
`610a0221…1da7`.

## 4. T2 — Linux native (PASS)

Run on 2026-10-24 in an isolated Native environment with a one-shot state root:

- 17/17 regressions with the native adapter:
  `ENHANCE_REGRESSION_PASS count=17 native=True`, including the native adapter
  and final-origin producer.
- Public installation lifecycle from 3.1.0 through 3.4.1 to the target:
  `SELF_INSTALL_VERIFY_OK`, uninstall preserved user data, reinstall:
  `PUBLIC_GIT_INSTALL_UPGRADE_UNINSTALL_REINSTALL_OK`.
- Results match the public CI `ubuntu-latest` lifecycle leg.

Evidence: `t2-regression.log` sha256 `44947aff…2c3b`;
`t2-lifecycle.log` sha256 `bfea0841…b96e`.

## 5. T3 — WSL2 thin smoke (PASS after test fix)

Environment: Windows 11 host `desktop-kfscv8c-1`, WSL2 Ubuntu-24.04, kernel
`6.6.87.2-microsoft-standard-WSL2`, `systemd-detect-virt=wsl`, systemd running,
Python 3.12.3. Per the contract, T3 repeats only the environment-sensitive
layer and does not rerun all of T2.

Thin checks passed:

- `check-consistency.sh` → `CURRENT_HERMES_DISTRIBUTION_CONSISTENCY_OK`.
- 36 plugin `.py` files compiled.
- Pure regression suite passed 3/3 consecutive runs
  (`ENHANCE_REGRESSION_PASS count=11 native=False`).
- ext4 inside WSL2 and `/mnt/c` showed the expected case-sensitivity
  difference; WSL2 NAT reached `https://api.github.com/zen` with HTTP 200.

### First-run flake and closure

The first cold run failed in `scripts/test-hook-transaction.py` at the manifest
byte-equality assertion. It did not reproduce on the next runs, so the test was
instrumented rather than dismissed:

- The test captured `previous_manifest` early, then executed two successful
  no-op `_install_hook()` calls before forcing an activation failure.
- Each no-op install legitimately rewrites `installed_at` at second
  resolution. Crossing a second boundary changes the manifest bytes even
  though no state semantics changed.
- Forcing a 1.1-second delay reproduced the failure deterministically:
  `installed_at` was `2026-10-24T11:36:39+00:00` before and
  `2026-10-24T11:36:40+00:00` after, with no other field changed.
- Fix: capture `previous_manifest` immediately before the failing activation
  (local commit `5c9d511`). This is a test-only change.

Verification of the fix:

| Case | Expected | Result |
|---|---|---|
| Fixed test with forced 1.1 s delay | pass | pass (`FIXED_DELAYED_RC=0`) |
| Negative control: manifest corrupted immediately before failure | fail | fail (`FIXED_NEGATIVE_RC=1`) |
| Full pure suite, 10 consecutive runs | 10 pass | 10/10 pass |

Evidence: `t3-wsl.log` sha256 `789334d7…b43b`; `t3-repeat.log` sha256
`9613ae46…65a9`; `wsl/repro-flake.log` sha256 `ff2afa5b…5bb5`;
`wsl/fix-and-test.log` sha256 `79eb1a35…e544`; patch sha256
`36dedff1…3160`.

T3 remains a thin smoke, not a substitute for T2 or T4.

## 6. T4 — Windows native (NOT RUN)

T4 was not executed for this plugin in this cycle, so no Windows-native
acceptance is claimed.

- `win11-test` currently has Hermes Agent 0.22.2. 3.4.4 declares
  `>=0.21.3,<0.22`, so that installation is outside the supported range.
- No downgrade or side-by-side Hermes installation was performed on the shared
  VM. The upstream installer exposes `-HermesHome`, `-InstallDir` and
  `-Commit`; a side-effect-free `-ShowResolvedPaths` probe confirmed isolated
  paths. Hermes `v0.21.6` maps to commit
  `818c13be1dc4fd28987e1e881a9408224afd4535`; there is no upstream `v0.21.3`
  tag. Provisioning that environment and performing real Weixin sends require
  an explicitly authorized maintenance window.
- The public CI `Public Git lifecycle · windows-latest` leg is L2 Windows
  lifecycle coverage. It is real Windows execution, but it is not a T4 GUI and
  Gateway E2E run and must not be recorded as T4.

## 7. L0/L1/L2 evidence

- L0: 17/17 regressions in T1 and T2; 11/11 in the T3 thin smoke.
- L1: `check-consistency.sh` OK; 36 files compiled in WSL2; static checks green
  in the published CI.
- L2: public v3.4.4 CI 7/7 success. PR #8 adds a Core `v0.21.6`
  `plugins validate` / `plugins doctor` Docker gate and has CI 8/8 success;
  local gates returned `rc=0` on Hermes 0.21.3 and 0.21.6. PR #8 remains open
  and unmerged.

## 8. Release-gate checklist

`SKILL.md` requires clean install, upgrade with state retention, Gateway
restart, real Weixin behavior, uninstall and reinstall on Linux, WSL2,
Windows-hosted and NAS/Docker.

| Requirement | Status |
|---|---|
| Clean install | PASS in T1 and T2 |
| Upgrade with state retention | PASS in T2 public lifecycle |
| Gateway restart | NOT RUN in this cycle |
| Real Weixin behavior | NOT RUN in this cycle |
| Uninstall | PASS in T1 and T2 |
| Reinstall | PASS in T1 and T2 |
| Linux | PASS (T2) |
| WSL2 | PASS (T3 thin smoke) |
| Windows-hosted | NOT RUN (T4) |
| NAS/Docker | PASS (T1) |

Therefore: production consistency is proven, but the full four-platform release
acceptance is **not** complete. The next release candidate must close T4, the
real-Weixin run and the Gateway restart, and include the T3 test fix.

> **Status change on 2026-10-25:** Gateway restart and real Weixin behavior now
> pass (§12.7, §12.9); T4 is boot-level only (§12.1). The remaining gap for the
> 3.5.0 line is a fresh full four-platform run of the FIFO delta.

## 9. Open findings carried with this record

- **I1 — Core provenance:** Hermes 0.21.3 and 0.22.2 `/btw` and `/bg` rails
  send reply-only metadata, so the plugin cannot observe a provider fallback
  and fails closed to `hermes`. This is a Core limitation, not a plugin defect;
  the upstream proposal is `I1.T1-core-provenance-proposal.md`. No Core change
  was made.
- **I2 — Weixin connectivity:** production logs show intermittent DNS/TCP
  failures to `ilinkai.weixin.qq.com` and occasional Core media-send failures.
  Text delivery recovered through the plugin FIFO; the transport is Core-owned.
  No plugin defect was identified, and the condition is environmental.
- **Install-state drift:** the stale 3.0.1 state in production was repaired on
  2026-10-24 under a separate authorization. The procedure and its limits are
  recorded in `docs/INSTALL_STATE_RUNBOOK.md`.
- **K5 production ownership and caches:** the installed plugin and hook remain
  `1000:1000` with root-owned `__pycache__` directories. Runtime uid 10000 can
  read them, so this is a maintenance nonconformance, not a live failure.
  Production cleanup was not authorized in this cycle.
- **PR #8:** open, minimal (one workflow file), CI-green. Merge is not part of
  this acceptance record.
- **3.4.5:** merged through PR #7 and reverted by `1be549c`; it is not a public
  release. Only a local shallow clone carries a `v3.4.5` tag.
- **DSH documentation:** `DEEPSEEK_HARNESS_STATUS.md` still ends at 3.4.4 and
  does not record 3.4.5, the revert or PR #8. A proposed delta exists; DSH owns
  that document and it was not edited here.

## 10. Evidence index

| Artifact | SHA256 |
|---|---|
| `t1-residual.sh` | `67e1d92c43da1682b6c27ad573158c3416de3611f56c26cc5ed4d1a6fdb9b1fe` |
| `t1-residual.log` | `610a02216e39a3bd259707d2128767ce8fb3e42e9ad4eb8801e8fce5b7311da7` |
| `t2-regression.log` | `44947affaa0000d60d13ca97807f95429b3db14745f052bbb1a75642381f2c3b` |
| `t2-lifecycle.log` | `bfea084159414a8549a5bf66c8e9b9554761b09094637877376ea86b0ca3b96e` |
| `t3-wsl.log` | `789334d706cbfccd173a6aab4b965da1b6f04a0d0c999c6eeb2cf4bf6bb5b43b` |
| `t3-repeat.log` | `9613ae46295028b8d2f05c2af5364669d6c6cceb7e5423ec294e6fa231cd65a9` |
| `wsl/repro-flake.log` | `ff2afa5bed350b85cb7209e87607d9aafac29ed84443f382647a519851e65bb5` |
| `wsl/fix-and-test.log` | `79eb1a35027a71fbb4cbe8ffc9cd9218b1b70327efa3b5809b0c1368b925e544` |
| `wsl/repro-flake.sh` | `27f3a5742e3d0361c62f365fe8627cb64eb532497e6d930d08101cf40bd853b2` |
| `wsl/fix-and-test.sh` | `34259ec6cd72d46c22b28248358ea8a5cfd810ce0362eb7021f2f664fd22fe9d` |
| `wsl/repo-v344.tar.gz` | `a6a7fbad07d2ce0969322bc1ea106524edec96416aa0edfa7212becad70a85ad` |
| `fix-t3-flake.patch` | `36dedff1872064997d69ead8c8950aa28b8c587db25eb63bb552723ff6163160` |
| `repair-sim.py` | `9b8341474aac773eb5a19eff500386a355156a580721ae772a85b342842dfd18` |
| `repair-sim.out` | `dc446b60b0ad5a60f0cf6dee9157eba5e69b256f9896d439faaec6a1205d3e88` |
| residual-closure evidence archive | `b7d6957b0fd7ea9942e41d3580f7d655069850905f8b3614242cfe8016840b0e` |
| earlier verification archive | `6fd7f2c8f174648fbb5c026a5b4747ce0f0921fae001cdaf382d5d70002778a2` |
| install-state repair archive | `2d4ca2c5a00c204736190c9acb5e2635ff01e703bfb0fb63be922738a86b8ec4` |

## 11. Reproduction

Isolated T1/T2-style checks must use a disposable `HERMES_HOME` or a fresh
container; never point them at production data. The T3 flake is reproducible
with `wsl/repro-flake.sh` and verifiable with `wsl/fix-and-test.sh`; both take
the 3.4.4 tree from `wsl/repo-v344.tar.gz` and build their own sandboxes.

When a later candidate is evaluated, append a new section with its commit and
tree; do not rewrite the historical results above.

## 12. Residual closure — 2026-10-25 (Asia/Shanghai)

Branch head for everything below: `31309e2` (`qoder/residual-closure-20261024`),
which adds `09487e5` (Windows-only test skip) and `31309e2` (FIFO backoff fix)
on top of the 3.4.4 tree. Runtime behavior is unchanged except for the backoff
guard; no release was cut.

### 12.1 T4 — Windows 11 native (PASS for transport-free boot)

Environment: `win11-test` (Windows 11 10.0.26300), Hermes 0.21.6 at
`818c13be1dc4fd28987e1e881a9408224afd4535`, Python 3.14.7, isolated
`HERMES_HOME`.

| Item | Result |
|---|---|
| Core PM install from `file://`, pinned `eceaf0bd` | PASS (`--force --yes-deps --enable`) |
| Hook install (`plugin_cli._install_hook()`) | PASS — `gateway:startup`, `agent:start`, `agent:end` |
| `verify-self-install` | `SELF_INSTALL_VERIFY_OK` |
| Lifecycle (install → upgrade → uninstall → reinstall) | `PUBLIC_GIT_INSTALL_UPGRADE_UNINSTALL_REINSTALL_OK` at `09487e52` |
| Regressions | `ENHANCE_REGRESSION_PASS count=17 native=True`; Q5 32/32 after `09487e5` |
| Gateway boot | hook loaded; webhook bound `127.0.0.1:18080`; `GET /health` → 200 |
| runtime-status | `errors: []`, `model_route=true`, `installed=0` (isolated profile has no Weixin adapter) |

Findings:

- Enabling the plugin makes Core prepend the per-install PM runtime venv to
  `sys.path`, so Core optional dependencies (here `aiohttp`) must exist *in that
  venv*. The earlier `Webhook: aiohttp not installed` was this redirection, not
  a missing wheel in the Core venv.
- The test gateway was stopped after capture. No real Weixin send/receive ran on
  T4; that still needs a production send.

### 12.2 PR #8 and production state

- PR #8 (workflow-only) merged; GitHub `main` =
  `1469a2ed8173d3ad3b3a567813ef6c555045ca5f`.
- K5 cleanup done: `/opt/data/plugins/hermes-wechat-enhance` and `.../hooks` are
  `1000:1000`; no `__pycache__` remains.
- Gateway restarted 2026-10-24 20:31:07 +08 (pid 2418157); hooks reloaded;
  runtime-status `errors: []`.

### 12.3 Production FIFO stall — root cause and first fix (superseded by §12.7)

- From 2026-10-25 07:43:40 +08 the deferred FIFO stopped draining after
  transient iLink connect failures. The queue held 4 bubbles (seq 582–585);
  seq 582 had 1274 attempts; new bubbles only enqueued behind the backlog.
- Cause: `_transient_retry_delay` computed `2 ** (attempt - 1)` in float space.
  At `attempt >= 1024` this raises `OverflowError`, which killed the retry
  worker; the enqueue path alone never restarts a worker.
- Fix (`31309e2`): cap the exponent before float conversion, plus a regression
  check (`huge attempt count does not overflow backoff`) in
  `scripts/test-fix-regressions-v320.py`. The full native suite passes with the
  fix.
- iLink connectivity is back (TLS 1.3 handshake from the container,
  2026-10-25 11:2x). The fix is **not** deployed to production and the backlog
  is not yet drained.
- `31309e2` only removed the overflow; it did not close the structural gap (a
  dead worker or an enqueue-only path could still strand rows). §12.7 replaces
  the retry model with a queue-driven drain.

### 12.4 Core I1 provenance patch (not upstreamed)

- Local Core commit `883d03f9` on 0.21.6: 8 files, +383/−32; 32 focused + 40
  auxiliary-client tests pass.
- Artifact: `I1.T1-core-provenance-patch/i1-provenance.patch`, SHA256
  `f338742e54a162d1b264b7681b47f60bcc876e031ffdfd91efcbf569244da89a`.
- No Core push; production Core untouched.

### 12.5 Evidence and status

- T4/FIFO evidence archive:
  `/home/vive/Work/.scratch/2026-10-25-wechat-t4-fifo-evidence.tar.gz`,
  SHA256 `c0790c0fe3fead5d794caa2cfa0eae48151feced3c0ca202c408e99ea93a53de`.
- Still open: real Weixin delivery run, production deployment of `afe4dd7` with
  backlog drain, and the branch push/PR. 3.4.4 stays at "partial acceptance"
  until the first two run.

### 12.6 Drained by an inbound message — 2026-10-25 15:49 +08

A user-sent `/continue` in the affected chat refreshed the context token
(`/opt/data/weixin/accounts/…context-tokens.json` mtime 15:49:18) and the
plugin drained locally: `sent=4 pending=0 ok=True`. The FIFO queue is empty.
This confirms the drain path revives on inbound (`process_message` →
`drain_pending`) and that the outage was a dead worker plus no inbound, not a
permanently invalid token. The `31309e2` overflow fix was **not** deployed for
this recovery; it remains preventive work, and no session-side production write
was made. The structural gap is addressed by §12.7.

### 12.7 Queue-driven FIFO redesign — 2026-10-25 (deployed)

Required invariant: while `pending_bubbles` holds rows and a usable reply window
exists, the plugin keeps draining in strict `seq` order; a failed send never
leaves the queue; only a successful acknowledgement or an explicit withdrawal
removes a row; no separate retry task may be the sole owner of that wakeup.

- Commit `afe4dd7` on `qoder/residual-closure-20261024`:
  - `DRAIN_BACKOFF_CEILING_SECONDS` 120 → **60**; every cadence is capped,
    including explicit iLink cooldowns. The exponent is capped before the float
    conversion, so a huge `attempts` value cannot raise `OverflowError`.
  - Removed the `MAX_DRAIN_PROBES` give-up. Unclassified/permanent-looking
    errors keep a 45s probe forever; only iLink `-14` (session expired) pauses
    the queue until a fresh inbound refreshes the token.
  - A missing cached token does **not** pause: Core deliberately sends tokenless
    as a degraded fallback. This matters for groups, where `_process_message`
    stores the token under `sender_id` but `_guess_chat_type` sends to the room
    id, so a room-scoped token never exists.
  - `ensure_drainer()` revives a dead worker from every producer/consumer edge:
    enqueue behind a backlog, every inbound, startup recovery, and the worker's
    own exit. Failed rows are never re-enqueued (`client_id` UNIQUE +
    `INSERT OR IGNORE`), so revival cannot duplicate a bubble.
  - The worker catches any exception from `drain_pending` and continues at the
    capped cadence; `CancelledError` (shutdown/preemption) is the only exit
    besides an empty queue or a session-expiry pause.
  - Startup recovery arms every persisted `pending_routes_v1` route, not only
    routes derivable from the in-memory token cache.
  - Attempts only drive warning logs (`MAX_TRANSIENT_DRAIN_RETRIES`, then every
    20 attempts); nothing is dropped or skipped.
- Tests:
  - New `scripts/test-fifo-backlog-invariant.py` (18 checks, stdlib fixtures):
    60s ceiling/no overflow, five unclassified failures still drain, enqueue-only
    revival without inbound, strict older-before-newer order, `-14` pause then
    inbound resume, tokenless startup drain, and survival of a crash inside
    `drain_pending`.
  - `scripts/test-fix-regressions-v320.py`: 88/88 with the 60s expectations and
    the new pause/revival assertions.
  - Full `scripts/run-regressions.py --hermes-root /opt/hermes`: 18/18 test
    files pass in a disposable `nousresearch/hermes-agent:v0.21.6` container
    (`--network none`, repo mounted read-only; no production container or
    plugin-data touched).
  - NAS host: `test-v021-bubble-footer.py` OK, `test-restart-drain.py` OK,
    `test-fifo-backlog-invariant.py` 18/18.
- Deployed 2026-10-25 18:12:14 +08 from `ce418de` (code tree `afe4dd7`) with
  `git archive` per K4; the transactional `scripts/install.sh` returned
  `SELF_INSTALL_VERIFY_OK` and `INSTALL_OK`. The hook tree is unchanged
  (`5dd5ac8a…`), so the installer skipped the hook copy. Delivery checks: the
  normalized production tree hash equals the commit archive
  (`2766eb79b0782a91b49fc9045a4e081867fec711bc81463d5c0450cb347097fd`), 38
  Python files compile, ownership is `1000:1000`, and no `__pycache__` remains.
- Gateway restarted 2026-10-25 18:12:53 +08 (`s6-svc -r`, single executor, queue
  empty). New pid **2648379**; the `gateway:startup` hook loaded at 18:13:33;
  `runtime-status.json` at 18:13:36 reports `installed=1`, `model_route=true`,
  `pending_bubbles=0`, `errors=[]`; `/health` returns 200; the startup-ready
  notification was delivered (`target=configured`). Queue depth after boot:
  `pending_bubbles=0`, `pending_routes_v1=0`.
- Pre-deployment backup:
  `/home/vive/hermes-production-backups/wechat-enhance-20261025-181044`
  (source, hook, install-state, plugin-data; consistent SQLite copies with
  `PRAGMA integrity_check=ok` and a clean `foreign_key_check`; 724 SHA-256
  entries).
- Production `.git` still reports `f82fbc7` because K4 delivery uses
  `git archive`; the deployed tree is identified by the commit and tree hash
  above, not by the production checkout's HEAD.
- Real user-triggered round trip (2026-10-25): inbound at 18:19:15 and
  18:24:05; the first reply was ready at 18:20:58, but every send then failed
  with `Cannot connect to host ilinkai.weixin.qq.com:443 ... [None]` during a
  network blip. The queue retained both replies (plus the shutdown notification
  enqueued at 18:27:57 and the next boot's startup-ready notice) in strict
  order; attempts grew to 10 and nothing was dropped or reordered. A fresh
  aiohttp connection from the same container reached the send endpoint (HTTP
  200) while the gateway's long-lived `_send_session` stayed unusable, so an
  authorized `s6-svc -r` restart was performed at 18:27:57. The new pid is
  2651648; startup recovery drained the queue at 18:29:12
  (`sent=4 attempts=1 pending=0`). The four bubbles were the two user replies,
  the shutdown notice, and the new startup-ready notice; the user received the
  replies. Poll traffic (`getupdates`) kept working through the same interval,
  isolating the fault to the send session rather than DNS or host egress.
- Post-recovery confirmation: a further user message at 18:32:50 +08 was
  answered at 18:33:58 with no FIFO row and no send failure (`pending=0`,
  `errors=[]`); the user confirmed receipt. A user-triggered round trip now
  completes end to end without operator intervention.
- Residual risk (Core-level): after a connection blip,
  `WeixinAdapter._send_session` can stay unusable until the process restarts;
  Core only recycles `_poll_session` on its failure streak. The plugin FIFO
  preserves every failed send, but automatic delivery recovery may require a
  Gateway restart until Core recycles the send session too. Core was not
  modified; this remains a follow-up.

### 12.8 Release 3.5.0 — 2026-10-25 (Asia/Shanghai)

- PR #9 (`fix: queue-driven Weixin FIFO drain with 60s cap`) merged into `main`
  as merge commit `d4b22dd4282b620297eda7aae70351e482b57520` at
  2026-10-25 18:53:11 +08, after 8/8 checks passed on head
  `7f0f14f0347dd2d5a1a7c39480a052d09f1cb4bb`. The merge commit then passed
  7/7 checks on `main`.
- The release commit `7f0f14f` sets `plugin.yaml` to `3.5.0` (minor: the
  backlog-drain contract changed; no config or API change). README badges and
  `scripts/check-consistency.sh` match.
- Annotated tag `v3.5.0` (tag object
  `62cb20d46aa41a7a83eea213ba0601a790246551`) points at the merge commit; the
  release tree is `7244f1f4b8d35a55fd599793708437f9b25759d7`. The GitHub
  release was published 2026-10-25 18:53 +08:
  `https://github.com/Awenforever/hermes-wechat-enhance/releases/tag/v3.5.0`.
- Production still runs the `ce418de` tree deployed at 18:12 +08. The release
  commit differs from it only in version metadata (`plugin.yaml`, README
  badges, consistency script). Re-deploying the exact tag tree and restarting
  the Gateway is a separate production action and was not performed.
- Core follow-up prepared on 2026-10-25: `_send_session` recycling after
  transport failures for text retries and media sends. `_is_transport_failure`
  keeps API-level errors on the same session, and a `stale` guard lets
  concurrent callers recycle only the session that failed. Seven of the eight
  new tests fail on the base tree, and all eight pass with the patch. The
  branch is pushed to a fork; it is not upstreamed and not deployed, and
  production Core is unchanged.

> **Superseded for the production deployment state by §12.9.** The metadata
> alignment was performed at 22:06–22:08 +08 under a separate authorization.

### 12.9 Production metadata alignment to 3.5.0 — 2026-10-25 22:06–22:08 +08

- Authorized separately after the release. Scope was metadata only: no Python,
  hook, `config.yaml`, database, queue or runtime-behaviour change.
- Four files were copied from release commit `7f0f14f` into the production
  plugin tree, preserving owner `1000:1000` and mode:
  - `plugin.yaml` — sha256 `ae9ae50d5e8735d747d80fe9de657572469679084582c51768e84e10b72e31f4`
  - `README.md` — sha256 `67a69b48f760595ca0fdf0bfa9d932a23052ea7cbb78ed21e6efcfaf4f8c1781`
  - `README_CN.md` — sha256 `17d9037457573b504facd53e659b34b9f5dd9e148b1b915bf4860a1315b9a3f0`
  - `scripts/check-consistency.sh` — sha256 `a80e6ecc4dfb191aedd1441b0e1c6ce5dae0b48e697d4e326d1550a4b606aac6`
- Pre-change backup:
  `~/Work/Hermes/2026-10-15-qoder-wechat-enhance-handoff/backups/2026-10-25-align-350/`
  contains the four old files, the old install-state manifest, `SHA256SUMS`,
  `PREFLIGHT.txt`, and `plugin-source-before-350.tar.gz` (131,166 B).
- Install state was refreshed with
  `scripts/manage-install-state.py record-installed --home /opt/data` (note:
  `--home /opt/data`, not `/opt/data/.hermes`). `source_installed_hash` became
  `cb8fc6edbfb55c29c5e473f545a7d8850f1bfecb92886176f4450ca45a725801`;
  `hook_installed_hash` stayed
  `5dd5ac8abb684486638fc9f197ca4a6597fa11a0e71955938372a30d21b67224`.
- The Gateway was restarted through s6 (`/run/service/gateway-default`) in a
  single-executor window. Verified afterward: s6 `up` (pid 2689830, pgid
  2689830); gateway health 200 at `http://127.0.0.1:8642/health`;
  `hermes plugins info hermes-wechat-enhance` reports `3.5.0`, enabled;
  3 hooks loaded and the plugin hook initialized with `errors=0`; Weixin
  connected and restored one context token; queue `pending_bubbles=0`,
  `pending_routes_v1=1`, `transport_receipts_v1=0`,
  `transport_withdrawals_v1=0`, `outbound_queue=0`.
- No new tracebacks in the post-restart error log (5,186 new bytes; warnings
  only). Real Weixin shutdown/startup notices were delivered at 22:06:51 and
  22:07:10 +08; no additional test message was sent.
- Runtime code is unchanged by this step: it remains the `ce418de` FIFO tree
  deployed at 18:12 +08. The production directory is a git worktree whose
  `HEAD` remains `f82fbc7`, so the four aligned metadata files appear as
  intentional local modifications. Do not run `git checkout` or `git clean`
  in that directory.
