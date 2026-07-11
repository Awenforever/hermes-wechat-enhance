# Isolated Audit Pattern

> 在完全不触碰生产环境的前提下，全量验证 patches/skill 的正确性。

## 触发

用户要求"全量审计""隔离环境验证""实机测试"时使用。

## 步骤

### 1. 准备隔离环境

```bash
mkdir -p /tmp/hermes-audit-test/
cd /tmp/hermes-audit-test/

# 克隆官方源码（如已缓存则复用）
if [ ! -d hermes-official ]; then
    git clone --depth 1 --branch v2026.7.1 https://github.com/NousResearch/hermes-agent.git hermes-official
fi

# 模拟 /opt/hermes 目录结构
cp -r hermes-official /tmp/hermes-audit-test/hermes-gw-test
cd /tmp/hermes-audit-test/hermes-gw-test
git init && git config user.email "t@x" && git config user.name "Test"
git add -A && git commit -m "pristine"
```

### 2. 补丁兼容性检查

```bash
# Patches 路径带 gateway/ 前缀，需要从 repo root apply（或 -p1）
for p in 002 003 004 005 001; do
    echo -n "$p: "
    git apply --check /opt/data/skills/hermes-wechat-enhance/patches/${p}-*.patch \
        && echo "OK" || echo "FAIL"
done
```

### 3. 应用补丁（正确顺序）

```bash
# 002→003→004→005→001，用 -p1（strip gateway/ 前缀）
# 005 可能需要 --recount --ignore-whitespace
for p in 002 003 004 005 001; do
    git apply /opt/data/skills/hermes-wechat-enhance/patches/${p}-*.patch
done

# 005 兜底：
git apply --recount --ignore-whitespace .../005-weixin-send-queue.patch
```

### 4. 编译检查

```bash
python3 -c "import py_compile; py_compile.compile('gateway/platforms/weixin.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('gateway/platforms/base.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('gateway/run.py', doraise=True)"
```

### 5. 运行 verify.py

```bash
python3 /opt/data/skills/hermes-wechat-enhance/verify.py
# 期望：43/43 passed
```

### 6. 审计 install.sh 行为

```bash
export HERMES_GATEWAY_SRC=/tmp/hermes-audit-test/hermes-gw-test
bash /opt/data/skills/hermes-wechat-enhance/scripts/install.sh
```

## 发现的常见问题

| 问题 | 修复 |
|------|------|
| patch 路径含 `gateway/` 前缀 | 从 repo root apply，或用 `-p1` |
| 005 报 "corrupt patch at line 181" | `--recount --ignore-whitespace` |
| file mode 100644 vs 100755 | `chmod 755` 或 `--ignore-whitespace` |
| install.sh 字母序 apply（001→002） | 显式排序 `002 003 004 005 001` |

## 原则

- **不碰生产** — 一切在 `/tmp/` 下
- **不留痕迹** — 测试完 `rm -rf /tmp/hermes-audit-test/`
- **验证编译 + 运行** — 不只是存在性检查