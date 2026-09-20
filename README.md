# Hermes WeChat Enhance

Hermes 微信通道的可靠性扩展。它在 Hermes v0.21 原生可靠投递机制之上，为每个实际发送成功的消息气泡增加计数和真实模型标签，并提供本地消息审计与旧版迁移工具。

## 功能

- 每个文本气泡显示当前 Context Token 下的计数和该轮实际模型，例如 `` `3` `qwen3.6-chat` ``。
- 只有微信发送成功后才提交计数；失败重试不会提前消耗编号。
- Context Token 变化后计数从 1 重新开始；长回复分片按实际气泡逐个计数。
- 为微信物理气泡维护独立的持久 FIFO；只有平台确认成功后才出队，Gateway 重启后仍可恢复。
- 支持静默 `/continue`：新 Context Token 到达后按原顺序继续出队，不把命令交给 Agent。
- 文本、附件、图片、视频和语音共同遵守每个 Context Token 最多 10 个气泡的限制。
- Gateway 正常启动后发送一次带 `` `hermes` `` 标签的就绪通知，可显式关闭。
- 可保存有界的本地收发审计记录。
- 迁移旧版积压时只归档、不补发历史消息。

本插件不负责微信登录、配对、模型选择或业务内容生成。

微信文本气泡末尾格式：

```text
---

`3` `qwen3.6-chat`
```

系统消息使用 `hermes` 标签。计数状态只保存账号、会话和 Context Token 的不可逆摘要，不保存原始凭据。

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

查看积压（不显示正文）或在自动备份后清空：

```bash
hermes wechat-enhance queue-list
hermes wechat-enhance queue-clear --yes
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
| `startup_notification` | `true` | Gateway 启动后发送就绪提示；显式设为 `false` 可关闭 |
| `legacy_runtime_compat` | `false` | 仅用于 v0.18 兼容；v0.21 不应开启 |

配置和状态位于当前 Hermes profile 的 `plugins/`、`hooks/`、`plugin-data/` 目录中，不修改 Hermes Core 源码。

## 安全与隐私

审计记录可能包含聊天正文，应像聊天备份一样保护。生产部署应限制 `HERMES_HOME` 的访问权限并纳入加密备份。删除插件前请先决定是否保留其审计和迁移归档。

## License

[MIT](LICENSE)
