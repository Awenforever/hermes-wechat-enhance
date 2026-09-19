# Hermes WeChat Enhance

Hermes 微信通道的可靠性扩展。它为 Hermes v0.21 提供持久 FIFO 发送队列、可审计的消息记录，以及从旧版运行时迁移时的安全收尾工具。

## 功能

- 严格按入队顺序发送，不让新回复越过积压消息。
- 发送成功后才出队；失败消息保留并重试。
- 队列有容量和退避限制，避免故障期间无限增长。
- 可保存有界的本地收发审计记录。
- `/continue` 只恢复上下文并继续依次出队，不插队发送实时回复。
- 迁移旧版积压时只归档、不补发历史消息。

本插件不负责微信登录、配对、模型选择或业务内容生成。

## 要求

- Hermes `>=0.21.3,<0.22`
- 已在 Hermes 中正常配置的 Weixin 通道
- Python 3.11+

## 安装

```bash
hermes plugins install Awenforever/hermes-wechat-enhance
hermes plugins enable hermes-wechat-enhance
hermes wechat-enhance install-hook
```

重启 Hermes Gateway 后检查状态：

```bash
hermes wechat-enhance status
```

安装插件不会要求重新扫码或配对；微信会话凭据仍由 Hermes 自己管理。

同时安装整套生产插件，可让 Hermes 打开并安装：

```text
https://raw.githubusercontent.com/Awenforever/hermes-wechat-enhance/main/hermes-pack.yaml
```

该清单固定到已验收的提交；Hermes 仍会显示审核与授权界面，不会代替用户授予权限。

## 从 Hermes v0.18 迁移

升级前先备份 `HERMES_HOME`，然后运行：

```bash
hermes wechat-enhance migrate-v018
```

命令会把旧队列移到迁移归档目录，并清空待发送状态。它不会把历史积压重新发给用户。

## 配置

| 选项 | 默认值 | 作用 |
|---|---:|---|
| `capture_messages` | `true` | 保存有界的本地消息审计副本 |
| `startup_notification` | `false` | Gateway 启动后发送就绪提示 |
| `legacy_runtime_compat` | `false` | 仅用于 v0.18 兼容；v0.21 不应开启 |

配置和状态位于当前 Hermes profile 的 `plugins/`、`hooks/`、`plugin-data/` 目录中，不修改 Hermes Core 源码。

## 安全与隐私

审计记录可能包含聊天正文，应像聊天备份一样保护。生产部署应限制 `HERMES_HOME` 的访问权限并纳入加密备份。删除插件前请先决定是否保留其审计和迁移归档。

## License

[MIT](LICENSE)
