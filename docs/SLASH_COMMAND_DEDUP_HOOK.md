# Repeated slash command handling

`hermes-wechat-enhance` installs a runtime-scoped Weixin adapter wrapper during
`gateway:startup`.

The wrapper preserves provider `message_id` replay protection and ordinary-text
content deduplication. It exempts only the exact sender+content fingerprint
lookup for inbound text whose normalized content starts with `/`.

This solves repeated commands such as two separately sent `/status` messages
without modifying `gateway/platforms/weixin.py`.

Marker: `HERMES_WECHAT_SLASH_COMMAND_DEDUP_HOOK_V1`
