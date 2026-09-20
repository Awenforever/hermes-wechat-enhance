# hermes-wechat-enhance

Hermes v0.21 微信可靠投递扩展。当前实现通过 profile 级 Hook 在运行时增强 Weixin Adapter，不修改 Hermes Core。

## 提供的能力

- 每个成功发送的物理气泡附加计数和真实模型名，例如 `` `3` `qwen3.6-chat` ``；系统消息标记为 `hermes`。
- Context Token 内最多发送 10 个气泡；计数只在微信平台确认成功后提交。
- 超出预算的文本分片进入 SQLite 持久 FIFO，Gateway 重启后仍保留。
- `/continue` 在 Weixin Adapter 入站边界被静默截获，刷新 Token 后严格按 FIFO 继续发送，不进入 Agent 上下文。
- 附件、图片、视频、语音与文本共用气泡预算；带说明的媒体先发送带尾注的说明气泡。
- Gateway 启动就绪通知默认开启，可通过 `HERMES_WEIXIN_STARTUP_READY_NOTIFY=false` 关闭。
- 提供状态、无正文队列查看、备份后清空和 v0.18 积压归档命令。

## Hermes v0.21 安装

```bash
hermes plugins install Awenforever/hermes-wechat-enhance
hermes plugins enable hermes-wechat-enhance
hermes wechat-enhance install-hook
```

也可在源码目录运行事务式安装器：

```bash
bash scripts/install.sh
python3 scripts/verify-v021-install.py
```

安装器会快照现有 Hook、插件源码和相关 Core 文件以供回滚；v0.21 路径会验证 Core API，但不会修改 Core 文件。重复安装应为幂等操作。

## 运维

```bash
hermes wechat-enhance status
hermes wechat-enhance queue-list --limit 100
hermes wechat-enhance queue-clear --yes
```

`queue-clear` 会先创建 SQLite 完整备份。运行时数据库位于：

```text
$HERMES_HOME/plugin-data/hermes-wechat-enhance/runtime.sqlite3
```

## 升级与迁移约束

- 不得删除或覆盖 Hermes 的微信登录、配对、认证和 Context Token 状态。
- 从 v0.18 迁移时，历史积压只归档、不补发；使用 `hermes wechat-enhance migrate-v018`。
- 部署前先在相同 Hermes 版本的隔离容器中运行真实 Adapter 测试。
- 生产重启前创建可验证备份，并准备恢复 Hook、插件源码和运行时数据库。
- 首次受控部署可创建一次性抑制文件，避免测试重启发出未授权通知：

```text
$HERMES_HOME/.hermes/wechat-enhance/suppress-startup-ready-once
```

## 历史兼容

`patches/` 和 `references/` 保留 v0.17/v0.18 的补丁与审计资料。仅旧版显式迁移流程使用它们；Hermes v0.21 不应启用 `legacy_runtime_compat`，也不应应用旧 Core 补丁。
