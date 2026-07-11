# v0.18 Migration Pitfalls

Key differences from v0.17 that caused deployment issues.

## Config Format

- **v0.17**: Platform configs as top-level YAML keys (`weixin:`, `telegram:`)
- **v0.18**: Platform configs under `platforms:` key (`platforms.weixin:`) as `PlatformConfig` objects
- Config migration (v30→v32) does NOT automatically restructure platform keys

## Env Var Resolution

- **v0.17**: Platform credentials read from `.env` file via dotenv
- **v0.18**: Platform credentials read from `os.getenv()` — must be process env vars
- `_enable_from_env()` auto-enables platforms when their token env var is present (e.g., `WEIXIN_TOKEN`)
- `WEIXIN_ENABLED=true` in `.env` is NOT sufficient — must be a real env var

## Container Default CMD

- **v0.18 image**: `CMD=["sleep infinity"]` — gateway does NOT auto-start
- Must explicitly pass: `hermes gateway run --replace --force --no-supervise --accept-hooks -v`

## Env Vars to Pass for WeChat

```
WEIXIN_TOKEN=<token>
WEIXIN_ACCOUNT_ID=<id>
WEIXIN_BASE_URL=https://ilinkai.weixin.qq.com
WEIXIN_CDN_BASE_URL=https://novac2c.cdn.weixin.qq.com/c2c
WEIXIN_DM_POLICY=pairing
WEIXIN_GROUP_POLICY=disabled
WEIXIN_ALLOW_ALL_USERS=false
```

## Lost Custom Patches

v0.17 had custom code that was NOT present in v0.18 official:

1. **run.py**: Model name propagation from agent result to event object (~40 lines)
2. **base.py**: Model name propagation from event to _thread_metadata (~15 lines)
3. **weixin.py**: `_drain_pending()`, `_resolve_model_name_for_footer()`, `ReplyBudgetStore`

Without these, footer metadata is always empty → footer shows `error`.

## Testing Container

```bash
docker run -d --name hermes-wechat-test \
  --network host \
  -v /tmp/test-home:/opt/data \
  -e HERMES_HOME=/opt/data \
  -e HERMES_ALLOW_ROOT_GATEWAY=1 \
  -e HERMES_ACCEPT_HOOKS=1 \
  -e HERMES_DASHBOARD=0 \
  -e WEIXIN_TOKEN=... \
  -e WEIXIN_ACCOUNT_ID=... \
  ... (all WeChat env vars) \
  hermes-agent:v0.18.0-patched \
  hermes gateway run --replace --force --no-supervise --accept-hooks -v
```

Wait for: `✓ weixin connected`