<div align="center">

# Hermes WeChat Enhance

**为 Hermes 微信通道提供可靠投递、真实模型标识和更安全的生命周期管理。**

[English](README.md) · [快速开始](#快速开始) · [特色功能](#特色功能) · [故障排查](#故障排查)

![Hermes](https://img.shields.io/badge/Hermes-v0.18-4c6ef5)
![Platform](https://img.shields.io/badge/Platform-Weixin-07c160)
![Install](https://img.shields.io/badge/Install-Transactional-7950f2)
![Runtime](https://img.shields.io/badge/Runtime-Docker%20%7C%20Linux-495057)

</div>

---

## 这是什么？

Hermes WeChat Enhance 是面向 Hermes 微信通道的社区增强组件。它改善用户在微信中看到的回复效果，同时让消息投递、安装、升级、回滚和容器重建更加可靠。

当前面向 Hermes v0.18 版本族（`v0.18.0` / `v2026.7.1`）。如果 Gateway 源码版本未知或存在未经识别的修改，安装程序会在修改任何 Gateway 文件前安全停止。

## 特色功能

| 功能 | 用户能够获得什么 |
|---|---|
| **真实模型页脚** | 模型生成的回复显示真实模型名称；Hermes 生命周期和控制消息显示 `hermes`。 |
| **逐条入站消息刷新计数** | 每条有效用户消息都会创建新的 Context token，首条成功回复从 `1` 开始。 |
| **确认后才计数** | 微信发送失败不会消耗计数；只有收到微信确认后才提交计数。 |
| **可靠 FIFO 投递** | 待发送消息保持先入先出顺序，新回复排在已有积压消息之后。 |
| **静默 `/continue`** | 刷新 Context token 并继续发送积压消息，不额外回复命令提示。 |
| **幂等投递元数据** | 稳定的 delivery ID 有助于业务调用方避免重复投递。 |
| **事务式安装和回滚** | 安装失败时恢复原 Gateway、hook、源码和 Git 状态。 |
| **容器持久化** | 正确挂载持久卷后，微信配对、配置和源码可跨容器重建保留。 |
| **安全卸载** | 遇到外部修改时拒绝覆盖，避免误删其他改动。 |

## 微信里会看到什么？

模型回复末尾会出现类似页脚：

```text
`1` `deepseek-v4-pro`
```

Hermes 系统消息会显示：

```text
`2` `hermes`
```

数字表示最新 Context token 下已经成功并获得微信确认的出站消息数量。

### 计数规则

- 每条有效用户入站消息都会刷新 Context token。
- 新 token 下首条成功确认的出站消息计为 `1`。
- 文本和媒体消息共用同一个计数器。
- 发送失败不会消耗数字。
- 每个 Context token 最多允许 10 条成功确认的出站消息。
- 后续 Hermes 系统消息可能显示为 `2`、`3` 等。
- `/continue` 会静默刷新 token，并继续发送待处理消息。

### 斜杠命令去重规则

- 所有由 `text.strip().startswith("/")` 识别的斜杠命令均绕过原生 300 秒内容指纹去重层。
- 原生 `message_id` 重放保护仍然启用。
- Context token 刷新发生在普通文本内容抑制之前。

这样可以避免重复发送的斜杠命令被内容去重错误丢弃，同时仍能阻止同一条
入站消息 ID 被重复处理。

## 使用要求

- Hermes v0.18 版本族：`v0.18.0` 或发布标签 `v2026.7.1`。
- Hermes 运行环境中可使用 Python 和 Bash。
- Docker 环境应持久化挂载 Hermes 数据根目录，通常为 `/opt/data`。
- Gateway 启动时必须带有 `--accept-hooks`。
- 真实端到端测试应使用备用微信账号。

> 不要重启 Docker daemon。需要重新加载 Python 补丁时，只重启 Hermes Gateway 进程或对应容器。

## 快速开始

### 1. 安装源码

确定持久化 Hermes 数据目录：

```bash
export HERMES_HOME="${HERMES_HOME:-/opt/data}"
mkdir -p "$HERMES_HOME/skills"
git clone https://github.com/Awenforever/hermes-wechat-enhance.git \
  "$HERMES_HOME/skills/hermes-wechat-enhance"
cd "$HERMES_HOME/skills/hermes-wechat-enhance"
```

通过发布分支或标签安装时，应先切换到对应版本，再执行安装脚本。

### 2. 安装并验证

```bash
bash scripts/install.sh
python3 scripts/verify-self-install.py
python3 scripts/test-reliable-delivery-contract.py
python3 scripts/verify-persistence.py
bash scripts/check-consistency.sh
```

安装过程是事务式的。如果无法确认受支持的源码类型，安装会在修改 Gateway 前停止。

### 3. 只重新加载 Gateway

只重启 Hermes Gateway 进程或 Gateway 容器，使修改后的 Python 源码生效。

示例：

```bash
docker restart <你的-Hermes-Gateway-容器名>
```

不要重启 Docker daemon。

### 4. 配置微信并启动 Gateway

```bash
hermes gateway --accept-hooks setup
hermes gateway --accept-hooks run
```

如果官方容器中的 `hermes` 不在 `PATH`：

```bash
/opt/hermes/.venv/bin/hermes gateway --accept-hooks setup
/opt/hermes/.venv/bin/hermes gateway --accept-hooks run
```

在目标环境中完成微信配对。配对数据应保存在 Hermes 持久卷中，不能放入 Git 仓库。

## 日常使用

在微信中正常与 Hermes 对话即可，不需要特殊前缀。

### `/continue`

发送：

```text
/continue
```

它不会返回命令提示，而是刷新 Context token，并按 FIFO 顺序尝试继续发送积压消息。

### 可靠投递过程

一次成功的文本发送遵循：

```text
读取队首消息
→ 发送
→ 收到微信确认
→ 提交计数
→ 从队列移除
```

发送失败时，消息仍保留在待发送队列中，计数保持不变。关键业务调用方还应维护自己的持久化 outbox，并复用稳定的 delivery ID。

## 更新

进入已安装的源码目录：

```bash
git fetch --all --prune
git pull --ff-only
bash scripts/install.sh
python3 scripts/verify-self-install.py
python3 scripts/test-reliable-delivery-contract.py
python3 scripts/verify-persistence.py
bash scripts/check-consistency.sh
```

随后只重启 Hermes Gateway 进程或容器。

安装程序可识别受支持的原始、旧版增强和已加固 v0.18 源码。未知修改会安全停止。

## 验证现有安装

```bash
cd "${HERMES_HOME:-/opt/data}/skills/hermes-wechat-enhance"
python3 scripts/verify-self-install.py
python3 scripts/test-reliable-delivery-contract.py
python3 scripts/verify-persistence.py
bash scripts/check-consistency.sh
```

健康安装应在不修改微信凭据、不发送真实消息的情况下通过全部命令。

## 卸载

```bash
cd "${HERMES_HOME:-/opt/data}/skills/hermes-wechat-enhance"
bash scripts/uninstall.sh
```

安全卸载会恢复安装前的受管 Gateway 文件，以及之前的 hook 和源码状态。微信配对与用户运行数据默认保留。

如果受管文件出现与安装前、安装后状态都不一致的外部修改，卸载会安全停止。不要强行删除 install-state，应先确认外部改动来源。

## 删除用户数据

公开流程刻意不提供“一键彻底清理”。

配对、账号和运行数据默认保留，以避免误删。彻底删除属于破坏性操作，只应在以下条件全部满足后进行：

1. 停止 Gateway；
2. 完成安全卸载；
3. 备份 Hermes 持久化数据根目录；
4. 明确确认微信配对和运行历史可以被删除。

删除任何数据前，请阅读[持久化契约](docs/PERSISTENCE_CONTRACT.md)。

## Docker 与持久化

Docker 环境应遵循：

- 将 Hermes 数据根目录持久化挂载，通常为 `/opt/data`；
- skill、hook、配置、配对和账号状态均保存在持久卷；
- 将容器文件系统视为可丢弃层；
- 重建容器时复用相同 volume 和必要网络配置；
- 使用持久卷中保留的源码重新安装本技能。

普通 Linux 或 WSL 环境使用本地文件系统持久化即可。

完整的源码与用户数据边界见[持久化契约](docs/PERSISTENCE_CONTRACT.md)。

## 故障排查

### 提示 `hermes: command not found`

使用运行时完整路径：

```bash
/opt/hermes/.venv/bin/hermes
```

### 微信提示 `session timeout`

已保存的微信会话过期。请在同一目标环境重新执行：

```bash
hermes gateway --accept-hooks setup
```

随后重新启动 Gateway。

### 回复没有显示模型页脚

确认：

- 安装验证全部通过；
- 安装后已重新加载 Gateway；
- Gateway 使用 `--accept-hooks` 启动；
- 没有其他 skill 覆盖受管微信 Gateway 文件。

### 计数没有重新从 `1` 开始

运行：

```bash
python3 scripts/test-reliable-delivery-contract.py
python3 scripts/verify-self-install.py
```

检查 Gateway 日志中的最新 Context-token 刷新和发送确认。不要手动编辑 reply-budget 状态。

### 消息一直处于积压状态

微信会话恢复正常后发送 `/continue`。它会刷新 Context token，并按 FIFO 顺序重试积压消息。

### 卸载拒绝继续

受管 Gateway、hook 或源码文件与安装前、安装后状态都不一致。这是安全保护。应保留 install-state 并检查外部改动，而不是强制删除。

### 容器重建后配置或配对丢失

Hermes 数据根目录没有正确持久化挂载，或新容器没有复用原 volume。先恢复正确持久卷，再考虑重新配对。

## 安全与隐私

- 不要提交 `.env`、账号文件、配对数据、cookie、token、日志或二维码链接。
- Hermes 数据根目录应保持私有，并位于可丢弃容器层之外。
- 真实微信验收使用备用账号。
- 未经明确同意，自动化测试不得发送真实消息。
- 安装事务快照不保存微信凭据。
- Git metadata、索引状态、配置和无关 dirty 文件保持不变。

## 能力边界

- 当前仅面向 Hermes v0.18 版本族进行全新安装。
- 微信会话可能过期，并需要重新配对。
- 进程内队列不能代替关键业务自己的持久化 outbox。
- 每个 Context token 最多 10 条成功确认的出站消息。
- 用户数据彻底清理不会自动执行。
- 本组件无法消除 Hermes、微信、模型 Provider 或宿主网络自身的限制。

## 文档导航

| 文档 | 面向对象 |
|---|---|
| [README.md](README.md) | 英文用户指南 |
| [SKILL.md](SKILL.md) | Hermes skill 契约 |
| [持久化契约](docs/PERSISTENCE_CONTRACT.md) | 存储与容器重建规则 |
| [维护者参考](docs/MAINTAINER_REFERENCE.md) | Patch 架构和历史技术细节 |
| [定制清单](CUSTOMIZATIONS.md) | 升级与 patch 维护 |
| [影响矩阵](IMPACT_MATRIX.md) | 受管文件和行为影响 |
| [Patch 变更记录](patches/CHANGELOG.md) | Patch 演进记录 |

## 获取支持

提交问题前，请提供：

- Hermes 版本；
- 容器或普通 Linux 环境；
- 失败的验证命令；
- 脱敏后的错误行；
- Gateway 是否使用 `--accept-hooks` 启动。

不要提供凭据、账号标识、token、cookie、二维码链接或完整配置文件。

## 许可证

当前候选版本尚未声明仓库许可证。在维护者添加 `LICENSE` 文件前，不应默认拥有再分发权。

<details>
<summary><strong>一致性检查使用的维护者清单</strong></summary>


### Patch 文件

- [`patches/001-weixin-continue-hook.patch`](patches/001-weixin-continue-hook.patch)
- [`patches/001-weixin-continue-hook.v017.patch`](patches/001-weixin-continue-hook.v017.patch)
- [`patches/002-weixin-footer-hook.patch`](patches/002-weixin-footer-hook.patch)
- [`patches/002-weixin-footer-hook.v017.patch`](patches/002-weixin-footer-hook.v017.patch)
- [`patches/003-gateway-system-metadata.patch`](patches/003-gateway-system-metadata.patch)
- [`patches/004-gateway-model-propagation.patch`](patches/004-gateway-model-propagation.patch)
- [`patches/005-weixin-send-queue.patch`](patches/005-weixin-send-queue.patch)
- [`patches/006-gateway-interim-model-metadata.patch`](patches/006-gateway-interim-model-metadata.patch)
- [`patches/007-gateway-interim-model-strict-source.patch`](patches/007-gateway-interim-model-strict-source.patch)
- [`patches/008-gateway-footer-model-full-send-rails.patch`](patches/008-gateway-footer-model-full-send-rails.patch)
- [`patches/009-weixin-reliable-delivery-contract.patch`](patches/009-weixin-reliable-delivery-contract.patch)
- [`patches/010-weixin-context-token-kernel-hardening.patch`](patches/010-weixin-context-token-kernel-hardening.patch)
- [`patches/011-weixin-v018-consolidated.patch`](patches/011-weixin-v018-consolidated.patch)
- [`patches/012-weixin-v018-legacy-upgrade.patch`](patches/012-weixin-v018-legacy-upgrade.patch)

### 参考文档

- [`references/architecture-analysis.md`](references/architecture-analysis.md)
- [`references/development-blueprint.md`](references/development-blueprint.md)
- [`references/docker-build-and-test.md`](references/docker-build-and-test.md)
- [`references/isolated-audit-pattern.md`](references/isolated-audit-pattern.md)
- [`references/migration-test-patterns.md`](references/migration-test-patterns.md)
- [`references/side-by-side-testing.md`](references/side-by-side-testing.md)
- [`references/v017-full-audit.md`](references/v017-full-audit.md)
- [`references/v017-model-propagation-chain.md`](references/v017-model-propagation-chain.md)
- [`references/v018-migration-pitfalls.md`](references/v018-migration-pitfalls.md)
- [`references/v018-model-propagation-bug.md`](references/v018-model-propagation-bug.md)
- [`references/v018-weixin-changes.md`](references/v018-weixin-changes.md)

</details>
