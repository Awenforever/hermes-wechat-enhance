<div align="center">

# Hermes WeChat Enhance

**让 Hermes 的每一个微信气泡都可追溯、可恢复、名副其实。**

[![Hermes](https://img.shields.io/badge/Hermes-%3E%3D0.21.3%2C%20%3C0.22-5965f2)](https://github.com/NousResearch/hermes-agent)
[![微信](https://img.shields.io/badge/通道-Weixin-07c160)](#核心能力)
[![版本](https://img.shields.io/badge/版本-2.1.13-7950f2)](plugin.yaml)
[![许可证](https://img.shields.io/badge/许可证-MIT-2f9e44)](LICENSE)

[English](README.md) · [快速安装](#快速安装) · [个性化配置](#个性化配置) · [故障排查](#故障排查)

</div>

---

Hermes WeChat Enhance 是 Hermes 的微信通道增强插件。它为每个真正发送成功的
文本气泡标注序号与真实模型，严格维护失败消息的 FIFO 顺序，同时完整保留用户
已有的模型、微信配对、授权和 Profile 配置。

## 核心能力

| 能力 | 能得到什么 |
|---|---|
| **真实模型尾注** | 模型正文显示实际路由或 fallback 模型；Hermes 控制消息显示 `hermes`。 |
| **确认后才计数** | 只有微信确认送达才提交序号；失败和重试不会提前消耗编号。 |
| **多气泡一致归因** | 长回复拆成多个气泡后，每个气泡都保留正确模型名称并独立计数。 |
| **持久 FIFO 恢复** | 发送失败的气泡跨重启保存，恢复时永远排在新回复之前。 |
| **自动刷新 Context Token** | 每一条微信入站消息都会在去重前刷新回复窗口。 |
| **静默 `/continue`** | 手动刷新 Token 并恢复积压，但不会进入 Hermes 对话上下文。 |
| **斜杠命令可重复** | 新发送的 `/approve`、`/continue` 等不会因文字相同而被误去重；相同 message ID 的重放仍会拦截。 |
| **Markdown 安全传输** | 不再按显示宽度破坏 Markdown 源码行、列表或超链接。 |
| **启动就绪通知** | Gateway 恢复后可主动告知用户已经可以继续使用。 |

微信气泡末尾会显示：

```text
---

`3` `deepseek-flash`
```

模型生成的中间说明、确认前正文、最终回复、分片和积压恢复消息都会保留实际模型；
审批提示、交互控件、进度、错误和生命周期通知则明确标为 `hermes`。

## 职责边界

本插件只负责微信传输层，不替用户选择模型，不负责微信登录或配对，也不生成业务
内容。模型仍由 Hermes 统一配置，认证和配对仍属于当前 Hermes Profile。只要原有
Profile 健康，安装或升级本插件不需要重新扫码、重新配对。

## 环境要求

- Hermes `>=0.21.3,<0.22`
- Hermes 中已有可用的 Weixin 通道
- Python 3.11+
- Linux、WSL2 或基于 Linux 的 Docker / NAS 环境

## 快速安装

```bash
hermes plugins install Awenforever/hermes-wechat-enhance
hermes plugins enable hermes-wechat-enhance
hermes wechat-enhance install-hook
hermes gateway restart
hermes wechat-enhance status
```

`install-hook` 可以安全重复执行。它会把 `display.busy_input_mode` 设为 `queue`，
让 Hermes 忙碌时收到的消息仍按先后顺序处理；卸载时仅在该设置仍由插件持有的情况
下恢复旧值，不会覆盖用户之后的修改。

> 如果由 Hermes 自动安装，请让它先阅读 `SKILL.md`。安装契约要求保留现有认证和
> 数据、主动展示可定制项，并在启用插件或发送真实消息前征得用户确认。

## 个性化配置

对于已配对的个人 Hermes，默认配置可以直接使用：

```yaml
plugins:
  entries:
    hermes-wechat-enhance:
      settings:
        startup_notification: true
        startup_message: "♻️ Gateway online — Hermes is back and ready."
        capture_messages: true
        legacy_runtime_compat: false
```

| 配置项 | 默认值 | 作用 |
|---|---:|---|
| `startup_notification` | `true` | Gateway 启动后发送就绪消息。 |
| `startup_message` | 如上 | 自定义就绪消息正文。 |
| `capture_messages` | `true` | 保存有界的本地收发审计副本。 |
| `legacy_runtime_compat` | `false` | 仅供 v0.18 遗留迁移；v0.21 不得开启。 |

兼容环境变量 `HERMES_WEIXIN_STARTUP_READY_NOTIFY` 优先级更高：`1` 使用默认文案，
`0/false/off` 关闭，其他非空字符串会直接作为自定义文案。

## 日常使用

像平时一样通过微信对话即可，不需要特殊前缀。只有希望“静默续传”时才需要
`/continue`；普通微信消息本身已经会刷新 Context Token 并尝试恢复 FIFO 积压。
文字相同但 message ID 不同的斜杠命令会被视为新的控制操作，真正的 provider
重放仍然会被阻止。

## 升级

```bash
hermes plugins install --force Awenforever/hermes-wechat-enhance
hermes wechat-enhance install-hook
hermes gateway restart
hermes wechat-enhance status
```

正常升级不会删除运行队列、计数、审计记录、微信配对、授权或 Profile 配置。

## 从 Hermes v0.18 迁移

先备份 `HERMES_HOME`，安装当前插件，然后归档旧队列：

```bash
hermes wechat-enhance migrate-v018
```

旧版积压会作为迁移档案保存，但**不会补发**。全新的 v0.21 安装必须保持
`legacy_runtime_compat: false`。

## 数据与隐私

```text
HERMES_HOME/
├── plugins/hermes-wechat-enhance/       插件源码
├── hooks/hermes-wechat-enhance/         运行 Hook
└── plugin-data/hermes-wechat-enhance/   计数、FIFO、审计与安装状态
```

计数状态只保存不可逆摘要，不保存原始 Context Token 或会话 ID。审计记录可能包含
聊天正文，应像聊天备份一样保护。Docker 环境必须把 `HERMES_HOME` 放在持久卷中。

## 故障排查

<details><summary><strong>没有尾注，或者模型正文始终显示 <code>hermes</code></strong></summary>

运行 `hermes wechat-enhance status`，确认插件和 Hook 均已启用，并在升级后重启
Gateway。模型正文应显示实际模型；控制消息显示 `hermes` 是正确行为。
</details>

<details><summary><strong><code>/continue</code> 或重复斜杠命令没有生效</strong></summary>

刷新 Hook 并重启 Gateway。不要关闭 message ID 重放保护；插件只绕过新斜杠命令
的第二层文字指纹去重。
</details>

<details><summary><strong>消息一直积压</strong></summary>

发送任意一条新微信消息，或者发送 `/continue` 静默恢复。如果仍失败，应先检查
微信通道和网络，不要直接清空队列。
</details>

<details><summary><strong>容器重建后丢失配对或状态</strong></summary>

应先恢复原来的 `HERMES_HOME` 持久卷，而不是立即重新配对；安装插件不应替换
Hermes 凭据。
</details>

## 卸载

```bash
hermes wechat-enhance uninstall-hook
hermes plugins remove hermes-wechat-enhance
```

用户状态、配对、队列和审计数据默认保留，只有在备份并明确确认后才应另行删除。

## 文档

- [`SKILL.md`](SKILL.md)：自动安装与交互契约
- [`docs/PERSISTENCE_CONTRACT.md`](docs/PERSISTENCE_CONTRACT.md)：数据归属和重建规则
- [`docs/MAINTAINER_REFERENCE.md`](docs/MAINTAINER_REFERENCE.md)：遗留版本与维护者参考

历史故障、实现细节和不可回归约束刻意不写进面向用户的 README。

## 许可证

[MIT](LICENSE)
