# Docker Image Build & Migration Test

## Building the patched image

On UGREEN NAS (DXP4800PLUS, Docker via SSH as `vive`):

```bash
# 1. Copy patches to vive-accessible location (data dir is 700)
docker run --rm -v /volume2/Hermes-v017-current:/src:ro \
  -v /tmp/patches:/dst alpine \
  cp /src/skills/hermes-wechat-enhance/patches/001-weixin-continue-hook.patch /dst/
docker run --rm -v /volume2/Hermes-v017-current:/src:ro \
  -v /tmp/patches:/dst alpine \
  cp /src/skills/hermes-wechat-enhance/patches/002-weixin-footer-hook.patch /dst/

# 2. Create Dockerfile (git user identity mandatory)
cat > /tmp/Dockerfile.v018 << 'EOF'
FROM hermes-agent:v0.18.0
COPY 001-weixin-continue-hook.patch /tmp/
COPY 002-weixin-footer-hook.patch /tmp/
RUN cd /opt/hermes \
    && git init \
    && git config user.email "build@hermes.local" \
    && git config user.name "Hermes Builder" \
    && git add -A \
    && git commit -m base \
    && git apply /tmp/001-weixin-continue-hook.patch \
    && git apply /tmp/002-weixin-footer-hook.patch \
    && python3 -m py_compile gateway/platforms/weixin.py \
    && grep -q "passing /continue through to gateway command router" gateway/platforms/weixin.py \
    && grep -q "footer_metadata = dict(metadata or {})" gateway/platforms/weixin.py \
    && ! grep -q "emit_collect" gateway/platforms/weixin.py \
    && ! grep -q "self._hooks" gateway/platforms/weixin.py \
    && rm -rf .git /tmp/*.patch
EOF

# 3. Build
docker build -t hermes-agent:v0.18.0-patched -f /tmp/Dockerfile.v018 /tmp/patches/
```

## Migration test pattern

1. **Copy production data** via docker (avoids sudo/UID issues):
   ```bash
   docker run --rm -v /volume2/Hermes-v017-current:/src:ro \
     -v /volume2:/dst alpine cp -a /src /dst/Hermes-v018-test
   ```

2. **Fix log file ownership** (alpine cp preserves root ownership, v0.18 entrypoint drops to hermes):
   ```bash
   docker run --rm --entrypoint /bin/sh \
     -v /volume2/Hermes-v018-test:/opt/data:rw hermes-agent:v0.18.0-patched \
     -c "chown 10000:10000 /opt/data/logs/agent.log"
   ```

3. **Start test gateway** (bypass s6-overlay to avoid double-instance):
   ```bash
   docker run -d --name hermes-test-gateway --network host --restart no \
     --entrypoint /opt/hermes/.venv/bin/hermes \
     --cap-add SYS_ADMIN \
     --security-opt seccomp=unconfined \
     --security-opt apparmor=unconfined \
     -v /volume2/Hermes-v018-test:/opt/data:rw \
     -v /home/vive/Work:/home/vive/Work:rw \
     -e HERMES_HOME=/opt/data \
     -e HERMES_ACCEPT_HOOKS=1 \
     -e HERMES_ALLOW_ROOT_GATEWAY=1 \
     -e HERMES_DASHBOARD=0 \
     -e TZ=Asia/Shanghai \
     -e HERMES_WRITE_SAFE_ROOT=/opt/data \
     -e HERMES_DISABLE_LAZY_INSTALLS=1 \
     -e HOME=/tmp/htg/home \
     -e TMPDIR=/tmp/htg/tmp \
     hermes-agent:v0.18.0-patched \
     gateway run --replace --force --no-supervise --accept-hooks -v
   ```

4. **Verification checklist** (20+ items):
   - Container running, no FATAL
   - config.yaml, state.db, skills/, hooks/ readable
   - Hermes Alive hook loaded
   - weixin.py syntax OK + inline /continue/footer logic present
   - no `self._hooks` / `emit_collect` references in weixin.py
   - Skills synced, config migrated
   - voice_state.json, context_queue.json valid
   - Dashboard HTTP responds
   - Cron jobs readable
   - Write test passes

5. **WARNING:** Test container may connect to real WeChat if credentials present in data dir. Stop immediately after verification.

## Common failures

| Failure | Cause | Fix |
|---------|-------|-----|
| `git commit` exits 128 | No user.email/name set | Add `git config` before commit |
| `PermissionError: agent.log` | File owned by root, process runs as hermes | `chown 10000:10000 logs/agent.log` |
| "Another gateway instance" | s6-overlay started its own gateway | Use `--entrypoint` to bypass |
| Docker build context not found | Data dir 700, NAS user can't read | Copy files to /tmp/ first |
| Patches fail to apply | weixin.py structure changed | Regenerate patches for new version |
