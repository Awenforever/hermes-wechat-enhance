# Release acceptance — Hermes WeChat Enhance

**Current status as of 2026-10-24 (Asia/Shanghai): partial acceptance.**
The 3.4.4 production tree is byte-identical to the public release and passes
T1, T2 and the T3 WSL2 thin smoke. T4 (Windows native E2E), a real-Weixin
delivery run and a Gateway restart were not executed in this cycle, so 3.4.4
must not be described as fully accepted across every supported platform.

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
