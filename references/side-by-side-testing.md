# Side-by-Side Testing: v17 (production) + v18 (test)

**Date**: 2026-07-07

## Goal

Run v18 test container alongside v17 production, both connected to the same WeChat account, to verify footer/model propagation fixes without disrupting production.

## Prerequisites

- Both containers can simultaneously connect to WeChat with the same token
- Test container uses isolated `HERMES_HOME` (no sharing with production)
- Production remains untouched

## Container Config

### Isolated HOME

```bash
# Create via running v17 container (write access):
docker exec hermes-hermes-1 mkdir -p /opt/data/v18-test-home/.hermes/logs
docker exec hermes-hermes-1 cp /opt/data/config.yaml /opt/data/v18-test-home/.hermes/
docker exec hermes-hermes-1 cp /opt/data/.env /opt/data/v18-test-home/.hermes/
```

### Essential Env Vars

```bash
HERMES_HOME=/opt/data/v18-test-home/.hermes     # Isolated!
GATEWAY_ALLOW_ALL_USERS=true                     # Bypass pairing
HERMES_ALLOW_ROOT_GATEWAY=1
HERMES_ACCEPT_HOOKS=1
HERMES_DASHBOARD=0
HERMES_WEIXIN_STARTUP_READY_NOTIFY=1
```

### Gateway Command

```bash
# Do NOT use --replace --force (PID conflict with s6-rc)
hermes gateway run --no-supervise --accept-hooks -v
```

## Pitfalls Encountered

### 1. PID File Conflict (Critical)

**Symptom**: `ERROR: Another gateway instance (PID N) started during our startup. Exiting.`

**Root cause**: `--replace --force` kills old PID via SIGTERM → s6-rc restarts it → replacement detects PID → exits → loop.

**Fix**: Use `--no-supervise` without `--replace`. Remove stale PID/lock files before start.

### 2. Unauthorized User

**Symptom**: `WARNING: Unauthorized user: ... on weixin`

**Fix**: Set `GATEWAY_ALLOW_ALL_USERS=true`. Do NOT copy production `state.db` (contains sessions).

### 3. `rm -f` in CMD doesn't work

**Why**: s6-rc checks and creates the PID file before the CMD `rm -f` runs. Must remove PID file from outside the container (on NAS filesystem) before container start.

### 4. s6-rc Log Pipeline

Gateway app logs: `$HERMES_HOME/logs/gateway.log`
Startup banner: `$HERMES_HOME/logs/gateways/default/current`
Always check both.

## Test Procedure

1. Build patched image on NAS
2. Create isolated HOME with `docker exec hermes-hermes-1`
3. Remove stale PID: `rm -f $HOME/hermes.pid $HOME/.gateway.lock`
4. Start: `docker run -d --name hermes-v18-test ...`
5. Wait for `✓ weixin connected` in gateway.log
6. Send test messages, verify footer via:
   ```bash
   docker exec hermes-v18-test grep "queued send" $HOME/logs/gateway.log | tail -5
   ```
7. Expected: `model='deepseek-v4-pro'` (not `model='hermes'` or `model='error'`)

## Cleanup

```bash
docker stop hermes-v18-test && docker rm hermes-v18-test
# Isolated HOME can be kept for next test or removed
```