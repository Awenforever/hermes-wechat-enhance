# Hermes WeChat Enhance

Hermes 微信增强 skill，提供 WeChat adapter 的增强功能：启动就绪通知、消息 footer（token 计数 + 模型名）、`/continue` 命令拦截、回复消息预算管理。

所有文件位于 `/opt/data/skills/hermes-wechat-enhance/`，不会直接修改 `/opt/hermes/` 或 `/opt/data/hooks/`。

## 安装

### 依赖
- git
- bash

### 安装命令
```bash
cd /opt/data/skills/hermes-wechat-enhance && bash scripts/install.sh
```

### 卸载
```bash
cd /opt/data/skills/hermes-wechat-enhance && bash scripts/uninstall.sh
```

### 升级
```bash
cd /opt/data/skills/hermes-wechat-enhance && bash scripts/update.sh
```

> ⚠️ **安装/升级后必须重启 gateway 才能生效。**

## 环境变量

| 变量 | 说明 | 必需 |
|------|------|------|
| `HERMES_HOME` | Hermes 主目录路径（默认 `/opt/data`） | ✅ |
| `HERMES_WEIXIN_STARTUP_READY_NOTIFY` | 控制 gateway 启动就绪通知，默认启用；设为 `0`/`false`/`off` 可关闭 | 可选 |
| `HERMES_WEIXIN_STARTUP_READY_MESSAGE` | 覆盖启动就绪通知文本，默认 `Gateway online — Hermes is back and ready` | 可选 |
| `WEIXIN_HOME_CHANNEL` | WeChat home channel；启动通知优先读 gateway config，然后读该变量 | 推荐 |
| `HERMES_WECHAT_FOOTER_MODEL_NAME` | 覆盖 footer 中显示的模型名 | 可选 |
| `GATEWAY_SRC` | Gateway 源码路径 | 由 install.sh 自动检测 |

## Patch 列表

### 001 — /continue 命令拦截
拦截 WeChat 用户发送的 `/continue` 消息，触发 pending 消息队列的排空（drain），**不路由到 agent 或 gateway command router**，直接返回。

### 002 — 消息 footer 追加
在 WeChat 出站消息末尾追加 footer，包含 token 计数和模型名。模型名来自结构化 metadata 或 `HERMES_WECHAT_FOOTER_MODEL_NAME`，不会读取 config.yaml 来伪造模型名；system 类消息（`is_system=True`）显示为 `hermes`。

### 003 — System metadata 标记
修改 `gateway/run.py` 中的 `_non_conversational_metadata()`，将 lifecycle/status 类发送统一标记为 `is_system: True`（原仅 Discord），确保 WeChat adapter 能正确识别并跳过 system 消息的 footer 处理。

### 004 — 模型名传播
在 `gateway/platforms/base.py` 和 `gateway/run.py` 中将 AI agent 响应的 resolved model 名称传播到 thread metadata，供 footer 显示正确的模型名。支持多级 fallback 查找。

### 005 — 回复预算与消息队列
核心 patch。在 `gateway/platforms/weixin.py` 中添加：

- **`ReplyBudgetStore`** — 基于 token 的用户级别回复预算管理，支持持久化存储（JSON 文件），含 TTL 和消息条数上限
- **`_is_system_meta()`** — 检测 metadata 是否为系统消息，支持 `is_system`、`actor`、`source`、`message_origin`、`origin` 五个字段
- **`_footer_model_name()`** — 确定 footer 中显示的模型名，优先级：`HERMES_WECHAT_FOOTER_MODEL_NAME` > metadata 中的模型字段 > `"hermes"`（默认）

## 原理

该 skill 通过 patch 方式直接修改 gateway 源码（`gateway/platforms/weixin.py`、`gateway/run.py`、`gateway/platforms/base.py`），为 WeChat adapter 增加：

1. **Startup ready notification** — `gateway:startup` 时向 WeChat home channel 发送 `Gateway online — Hermes is back and ready`
2. **Message logging** — 通过 `agent:start` / `agent:end` hook 旁路记录入站、出站消息，存储至 `~/.hermes/wechat_enhance/messages.jsonl`
3. **Footer** — 每条回复自动追加 token 计数和模型名，便于用户直观感知消耗
4. **`/continue`** — 排空 pending 队列继续未完成的对话，不重新触发 agent
5. **Budget** — 每个用户基于 token 的回复预算，防止滥用，数据持久化至 `~/.hermes/wechat_enhance/`
