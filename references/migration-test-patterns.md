# Migration Test Patterns — UGREEN NAS Docker

## Test Strategy: Sidecar Replica

Never test on production containers. Always:

1. Copy data directory to test location
2. Build patched image from test context
3. Start test containers with `--entrypoint` bypass (s6-overlay interference)
4. Run verification, then destroy

## Data Copy on NAS

Production data is `700 hermes:hermes` (UID 10000). `vive` user can't read it:

```bash
# Method: Use docker to copy (runs as root inside container)
docker run --rm -v /volume2/Hermes-v017-current:/src:ro \
  -v /volume2:/dst alpine cp -a /src /dst/Hermes-v018-test
```

## s6-overlay Bypass

v0.18 base image has s6-overlay as entrypoint. It starts its own gateway + dashboard services,
conflicting with our manual commands. **Always bypass with `--entrypoint`:**

```bash
docker run -d --name hermes-test-gateway \
  --entrypoint /opt/hermes/.venv/bin/hermes \
  hermes-agent:v0.18.0-patched \
  gateway run --replace --force --no-supervise --accept-hooks -v
```

## File Permission Fix

s6-overlay drops privileges to `hermes` user (UID 10000) even with `--user 0:0`.
Files copied via docker end up owned by root. Fix before starting:

```bash
# Bypass s6 to run as real root
docker run --rm --entrypoint /bin/sh \
  -v /volume2/Hermes-v018-test:/opt/data:rw \
  hermes-agent:v0.18.0-patched \
  -c "chown 10000:10000 /opt/data/logs/agent.log"
```

## Docker Build Context on NAS

NAS user `vive` can't read `700`-protected Hermes data directories.
Copy patches to `/tmp/` first, then build:

```bash
# Copy patches via docker
docker run --rm -v /volume2/Hermes-v017-current:/src:ro \
  -v /tmp/patches:/dst alpine \
  cp /src/skills/hermes-wechat-enhance/patches/001-*.patch /dst/

# Build from /tmp/patches/
docker build -t hermes-agent:v0.18.0-patched \
  -f /tmp/Dockerfile /tmp/patches/
```

## Dockerfile: git apply with identity

```dockerfile
FROM hermes-agent:v0.18.0
COPY *.patch /tmp/
RUN cd /opt/hermes \
    && git init \
    && git config user.email "build@hermes.local" \
    && git config user.name "Hermes Builder" \
    && git add -A && git commit -m base \
    && git apply /tmp/001-*.patch \
    && git apply /tmp/002-*.patch \
    && git apply /tmp/003-*.patch \
    && python3 -m py_compile gateway/platforms/weixin.py \
    && python3 -m py_compile gateway/run.py \
    && rm -rf .git /tmp/*.patch
```

## Test Container Isolation

- Container names: `hermes-test-gateway`, `hermes-test-dashboard`
- Dashboard port: `19120` (production uses `19119`)
- Do NOT set `HERMES_WEIXIN_*` env vars on test gateway (prevents WeChat connection)
- Use `--restart no` to avoid unexpected restarts

## Verification Checklist

1. Container running
2. No FATAL/CRASH in logs
3. config.yaml, state.db, skills/, hooks/ readable
4. Hermes Alive hook loaded
5. weixin.py + run.py syntax valid
6. inline /continue and footer logic present (weixin.py)
7. is_system tags present (run.py)
8. Skills synced, config migrated
9. voice_state.json, context_queue.json valid JSON
10. Dashboard HTTP responds
11. Cron jobs readable
12. Write test passes
