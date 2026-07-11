# v0.17 生产环境模型名传播链路（已验证）

生产环境中 footer 显示的模型名（如 `deepseek-v4-pro`）来自真实推理模型，不是 config.yaml 硬编码。

## 完整链路

### 步骤 1: 模型解析 — run.py

```
run.py:15155  model, runtime_kwargs = self._resolve_session_agent_runtime(
                  source=source,
                  session_key=session_key,
                  user_config=user_config,
              )
```

`_resolve_session_agent_runtime()` 内部（run.py:3218-3325）:

```
line 3238: model = _resolve_gateway_model(user_config)    ← config 默认值
line 3239: override = self._session_model_overrides.get(…)  ← /model 命令覆盖
line 3269: runtime_kwargs = _resolve_runtime_agent_kwargs() ← provider 覆盖
line 3271: runtime_model = runtime_kwargs.pop("model", None)
line 3277: model = runtime_model                            ← provider 指定模型
line 3278: model, runtime_kwargs = _apply_session_model_override(…) ← 再次应用 session override
line 3325: return model, runtime_kwargs
```

**关键**: `model` 变量经过了 config → session override → provider override → session override 的完整解析链。

### 步骤 2: 元数据注入 — run.py

```
line 15286: _model_for_footer = str(model or "").strip()
line 15288: _model_thread_metadata["model_name"] = _model_for_footer
line 15289: _model_thread_metadata["resolved_model"] = _model_for_footer
```

**关键**: line 15155 到 line 15286 之间 `model` 变量**没有重新赋值**。footer 用的就是实际推理模型。

`turn_route = self._resolve_turn_agent_config(message, model, runtime_kwargs)` (line 15296) 只是透传 `model`:

```
run.py:3348  route = {"model": model, …}
```

不做 smart routing，模型不变。

### 步骤 3: Footer 解析 — weixin.py

`_resolve_model_name_for_footer()` (weixin.py:2081-2134) 的优先级:

```
1. is_system 标记 → "hermes"
2. metadata["model_name"]        ← 来自步骤 2 的 _model_thread_metadata
3. metadata["resolved_model"]
4. metadata["routed_model"]
5. metadata["model"]
6. _default_model_name_for_footer() → config.yaml 兜底
7. "error"                        ← 最终兜底（极端边缘场景）
```

**正常路径永远是步骤 2**，metadata 中有 `model_name`。config.yaml 兜底（步骤 6）和 `"error"`（步骤 7）只在 metadata 缺失时触发。

### 步骤 4: Footer 格式 — weixin.py

```
weixin.py:2146  model_name, footer_metadata = self._resolve_model_name_for_footer(content, metadata)
```

然后拼接: `{content}\n\n---\n\n`{count}` `{model_name}``

## 完整链路（11步详细追踪）

### 步骤 1: 模型解析
```
run.py:15155  model, runtime_kwargs = self._resolve_session_agent_runtime(source, session_key, user_config)
```
`_resolve_session_agent_runtime()` (run.py:3218-3325):
- line 3238: `model = _resolve_gateway_model(user_config)` — config 默认
- line 3239: session override (`/model` 命令)
- line 3269-3277: provider runtime override
- line 3278: session override 再次应用
- line 3325: `return model, runtime_kwargs`

### 步骤 2: 元数据注入
```
run.py:15286  _model_for_footer = str(model or "").strip()
run.py:15288  _model_thread_metadata["model_name"] = _model_for_footer
```
line 15155→15286 之间 `model` 变量没有重新赋值。同一个变量。

### 步骤 3: turn_route 透传
```
run.py:15296  turn_route = self._resolve_turn_agent_config(message, model, runtime_kwargs)
run.py:3348   route = {"model": model, …}          ← 透传，不变
```

### 步骤 4: AIAgent 构造
```
run.py:11122  agent = AIAgent(model=turn_route["model"], …)
```
AIAgent 实例的 `self.model` = 真实推理模型。

### 步骤 5: 从 agent 实例回读
```
run.py:15909  _resolved_model = getattr(_agent, "model", None)
```
如果 agent 存在，`_resolved_model` = 真实模型。

### 步骤 6: agent_result 包含 model 字段 ⚠️ 关键依赖
```
run.py:16084  return {…"model": _resolved_model,…}
```
v17 的 `_run_agent_inner` 显式将 `"model"` 写入 agent_result dict。

### 步骤 7: 从 agent_result 读取
```
run.py:9488   for _key in ("model_name","resolved_model","routed_model","model"):
                  _candidate = str(agent_result.get(_key) or "").strip()
```
优先级: model_name → resolved_model → routed_model → **model**（第4优先级）。
agent_result["model"] = _resolved_model = 真实模型。

### 步骤 8: 写入 event
```
run.py:9514   setattr(event, "model_name", _result_model)
run.py:9518   setattr(event.source, "model_name", _result_model)
```

### 步骤 9: base.py 从 event 读取
```
base.py:4243  getattr(event, "resolved_model", None)  ← 第1优先级
base.py:4244  getattr(event, "model_name", None)     ← 第2优先级
base.py:4245  getattr(event.source, "resolved_model", None) ← 第3优先级
base.py:4246  getattr(event.source, "model_name", None)     ← 第4优先级
base.py:4254  response.get("model_name")             ← 第5优先级（agent_result 回退）
```

### 步骤 10: 注入 thread_metadata
```
base.py:4268  _thread_metadata["model_name"] = _model
```
此时 `_thread_metadata` 传给 adapter.send()。

### 步骤 11: weixin.py footer 渲染
```
weixin.py:2114  meta.get("model_name")  ← 返回真实模型名
```
`_resolve_model_name_for_footer()` 优先级:
1. `is_system` → "hermes"
2. `metadata["model_name"]` ← 来自步骤 10
3. `metadata["resolved_model"]`
4. `metadata["routed_model"]`
5. `metadata["model"]`
6. `_default_model_name_for_footer()` → config.yaml 兜底
7. `"error"` → 最终兜底

## ⚠️ v18 断裂点: 步骤 6

v18 的 agent_result 如果**不含 `"model"` 字段**，则:
- 步骤 7 读不到任何模型名 → `_result_model = ""`
- 步骤 8 不设 `event.model_name`
- 步骤 9 从 event 也读不到 → 回退到 response.get() → 同样没有
- 步骤 10 `_thread_metadata` 无 `model_name`
- 步骤 11 走兜底 → `"hermes"` 或 `"error"`

**v17 能工作是因为步骤 6 显式包含了 `"model": _resolved_model`。** 如果新版本去掉了这个字段，patch 004 必须从别处获取模型名（如 `getattr(_agent, "model")`）。

## 关键结论

- **不是 config 硬编码**: 正常路径读 metadata 中的 `model_name`，不是 config.yaml
- **是真实推理模型**: `model` 变量经过了 session override 和 provider override
- **唯一注意点**: line 2134 最终兜底是 `"error"`，应改成 `"hermes"`，但几乎不会走到