# v2026.7.1 模型名传播断裂 — 根因分析与修复

**发现日期**: 2026-07-06
**修复日期**: 2026-07-07 (Codex audit)
**症状**: 每条微信消息 footer 都显示 "hermes"（或 "error"）

## 两个独立根因

### 根因 1: `_mark_notify_metadata(None)` → TypeError

**位置**: `gateway/platforms/base.py` — 最终发送前处理 metadata

**触发条件**: `_thread_metadata` 为 None 时，调用 `_mark_notify_metadata(None)`，内部尝试 `None.get("notify")` 触发 TypeError，被裸 `except` 吞掉，返回 `{"notify": True}` — 无 `model_name`。

**修复**: 函数入口增加 `if metadata is None: metadata = {}`。

### 根因 2: agent_result 不含 "model" 字段

**位置**: `gateway/run.py` — agent 结果处理

**触发条件**: v2026.7.1 的 `_run_agent_inner` 返回值不包含 `"model"` 字段（v17 有 `"model": _resolved_model`）。patch 004 的 `agent_result.get("model")` 读不到，整个链断裂。

**修复**: 多级 fallback 链：
- `agent_result.get("model")` → `agent_result.get("model_name")` → `agent_result.get("resolved_model")`
- 回退到 `getattr(event, "resolved_model/model_name")`、`getattr(event.source, ...)`
- 再回退到 `_last_resolved_model`、`_resolve_gateway_model()`

## 完整传播链（修复后）

```
_resolve_session_agent_runtime()
  → model 变量 (真实模型，含 session override)
  → _model_thread_metadata["model_name"]
  → adapter.send(metadata={"model_name": "deepseek-v4-pro"})
  → weixin._footer_model_name(metadata)
    → _is_system_meta? → "hermes"
    → metadata.get("model_name") → "deepseek-v4-pro" ✅
```

## Patch 005 修复（_footer_model_name）

新增三个辅助函数替代内联逻辑：

```python
def _is_system_meta(meta: dict) -> bool:
    """检查 is_system / actor / source / message_origin / origin"""

def _footer_model_name(metadata) -> str:
    """完整 fallback 链"""
    if _is_system_meta(metadata): return "hermes"
    return env_var or metadata.model_name or resolved_model or
           routed_model or metadata.model or "hermes"
```

## 验证

```
2026-07-07 03:39:17 INFO weixin: Weixin queued send count=1 model='deepseek-v4-pro'
```

修复前: `model='hermes'` 或 `model='error'`
修复后: `model='deepseek-v4-pro'` ✅