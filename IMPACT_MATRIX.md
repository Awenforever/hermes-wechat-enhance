# 🔗 变更联动追踪表 — Impact Matrix

> 当开发者修改了 hermes-wechat-enhance 的某类功能时，此表指示**哪些脚本/文件需要同步检查或更新**。
>
> **原则**：每次修改前先查表，修改后按表逐项核对，避免遗漏联动文件。

---

## 联动矩阵

| 改动类型 | install.sh | update.sh | uninstall.sh | verify | README | CUSTOMIZATIONS | SKILL.md |
|:---|---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 新增 patch | ✅ | ✅ | — | ✅ | ✅ | ✅ | — |
| 删除 patch | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| patch 重排序 | ✅ | ✅ | — | ✅ | — | ✅ | — |
| 新增 hook | ✅ | — | ✅ | — | ✅ | — | — |
| 新增 env var | ✅ | — | ✅ | ✅ | ✅ | — | — |
| 修改 footer 逻辑 | — | — | — | ✅ | — | ✅ | — |
| 修改 `/continue` 逻辑 | — | — | — | ✅ | — | ✅ | ✅ |
| 修改预算/队列逻辑 | — | — | — | ✅ | — | ✅ | — |
| 新增依赖 | ✅ | — | — | — | ✅ | — | — |
| 版本升级适配 | ✅ | ✅ | — | ✅ | — | — | — |

> **图例**：✅ = 需要同步检查/更新 ｜ — = 无需操作

---

## 使用说明

1. **修改前**：在「改动类型」列中找到本次变更所属的行。
2. **筛选列**：查看该行中标记 ✅ 的列，它们是需要同步更新的文件。
3. **逐项检查**：对每个 ✅ 文件执行必要的修改或确认无需修改。
4. **不可遗漏**：即使改动看似微小，也应按表核对——❌ 跳过联动检查是 CI 失败和 bug 的第一来源。

---

## 示例

### 场景：新增一个 patch

假设你新增了一个 `patches/02-fix-copy.patch`：

| 改动类型 | install.sh | update.sh | uninstall.sh | verify | README | CUSTOMIZATIONS | SKILL.md |
|:---|---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 新增 patch | ✅ | ✅ | — | ✅ | ✅ | ✅ | — |

你需要同步更新：

- **install.sh** — 追加 `apply_patch "patches/02-fix-copy.patch"` 调用
- **update.sh** — 同上，追加 patch apply 调用
- **verify** — 增加对新增 patch 应用结果的校验逻辑
- **README** — 在 patch 列表中记录新增 patch 的作用和编号
- **CUSTOMIZATIONS** — 如果该 patch 影响自定义行为，同步更新说明

### 场景：修改 `/continue` 逻辑

| 改动类型 | install.sh | update.sh | uninstall.sh | verify | README | CUSTOMIZATIONS | SKILL.md |
|:---|---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 修改 `/continue` 逻辑 | — | — | — | ✅ | — | ✅ | ✅ |

你需要同步更新：

- **verify** — 更新 `/continue` 行为验证规则
- **CUSTOMIZATIONS** — 同步变更自定义配置项
- **SKILL.md** — 更新技能说明文档中关于 `/continue` 的描述