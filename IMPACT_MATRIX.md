# 🔗 变更联动追踪表 — Impact Matrix

> 修改 `hermes-wechat-enhance` 的某类功能时，此表指示**哪些文件需要同步检查或更新**。
> 原则：修改前先查表，修改后逐项核对。仓库已是 **hook-only** 架构，不存在
> `patches/`、`CUSTOMIZATIONS` 或根目录 `verify`；旧架构的联动项已移除。
> 最后修订：2026-10-25（Qoder），按 3.5.0 树核对。

---

## 联动矩阵

| 改动类型 | 核心代码 | Hook / 安装器 | 测试 / CI | 用户文档 | 维护文档 |
|:---|:---|:---|:---|:---|:---|
| 版本升级 / 发布 | `plugin.yaml` | — | `scripts/check-consistency.sh`、CI | `README.md`、`README_CN.md` 的版本徽章 | `docs/RELEASE_ACCEPTANCE.md`、`docs/DEVELOPMENT_MEMORANDUM.md` |
| 发送 / FIFO / Token / 重试 | `hermes_wechat_enhance/v021_bubble_footer.py` | `hooks/hermes-wechat-enhance/handler.py`（入口变更时） | `scripts/test-fifo-backlog-invariant.py`、`test-restart-drain.py`、`test-v021-real-adapter.py`、`run-regressions.py` | — | `docs/DEVELOPMENT_MEMORANDUM.md`、`docs/RELEASE_ACCEPTANCE.md` |
| 气泡计数 / 模型尾注 | `hermes_wechat_enhance/v021_bubble_footer.py` | — | `scripts/test-v021-bubble-footer.py`、`test-final-origin-producer.py`、`test-btw-rail-provenance.py`、`test-bg-rail-provenance.py` | — | `docs/DEVELOPMENT_MEMORANDUM.md` |
| Hook 安装 / 升级 / 卸载 | `plugin_cli.py` | `hooks/hermes-wechat-enhance/HOOK.yaml`、`scripts/{install,update,uninstall}.sh`、`scripts/verify-self-install.py` | `scripts/test-hook-transaction.py`、`test-plugin-cli-lifecycle.py`、`test-public-install-lifecycle.py` | `README.md`、`README_CN.md`、`SKILL.md` | `docs/PERSISTENCE_CONTRACT.md` |
| 安装事务状态机 | — | `scripts/manage-install-state.py`、`scripts/{install,update,uninstall}.sh` | `scripts/test-install-state-source-path.py`、`tests/test_dual_source_install.py` | — | `docs/INSTALL_STATE_RUNBOOK.md` |
| 持久化路径 / 数据归属 / 表结构 | `hermes_wechat_enhance/store.py`、`hermes_wechat_enhance/settings.py` | — | `scripts/verify-persistence.py`、`scripts/queue-admin.py`（只读运维） | — | `docs/PERSISTENCE_CONTRACT.md`、`docs/RELEASE_ACCEPTANCE.md` |
| Slash 去重 / `/continue` | `hermes_wechat_enhance/slash_command_dedup.py` | — | `scripts/test-slash-command-dedup-hook.py`、`scripts/test-context-fill-call-boundary.py` | — | `docs/SLASH_COMMAND_DEDUP_HOOK.md` |
| 传输回执 / 撤回 | `hermes_wechat_enhance/v021_bubble_footer.py`、`store.py` | — | `scripts/test-transport-receipt-publisher.py`、`test-transport-withdrawal.py` | — | `docs/transport-receipt-development.md` |
| 公共 CLI 命令 | `plugin_cli.py` | — | `scripts/test-plugin-cli-lifecycle.py` | `README.md`、`README_CN.md`、`SKILL.md` | — |
| Hermes 兼容范围 / CI / 依赖 | `plugin.yaml`（`requires_hermes`） | — | `.github/workflows/candidate-validation.yml`、`hermes-compat.yml`、`scripts/run-regressions.py` | `README.md`、`README_CN.md`、`SKILL.md` | `docs/RELEASE_ACCEPTANCE.md` |
| 目录 / 文档结构 | — | — | `scripts/check-consistency.sh`（必需文件清单在 CI 中重复一次） | `README.md`、`README_CN.md` | `IMPACT_MATRIX.md`（本表）、`.github/workflows/candidate-validation.yml` |

> 图例：写出的文件 = 需要同步检查 / 更新；`—` = 通常无需改动，但仍以实际 diff 为准。

---

## 使用说明

1. **修改前**：在左列找到本次变更类型；跨类型的改动取并集。
2. **修改后**：逐项核对「核心代码 / Hook 安装器 / 测试 CI / 用户文档 / 维护文档」五列。
3. **测试**：先跑 `scripts/run-regressions.py`；发布候选还必须走
   `scripts/check-consistency.sh` 与 GitHub Actions 的两条 workflow。
4. **验收记录**：行为或发布状态变化必须同时写入 `docs/RELEASE_ACCEPTANCE.md`
   的对应小节；设计取舍写入 `docs/DEVELOPMENT_MEMORANDUM.md`。只改代码不改
   记录 = 未完成。
5. **不可遗漏**：CI 的 `required` 文件清单与可执行位检查在
   `.github/workflows/candidate-validation.yml` 中；新增/删除脚本时两处都要改。

---

## 发布门（摘要）

- `bash scripts/check-consistency.sh` → `CURRENT_HERMES_DISTRIBUTION_CONSISTENCY_OK`
- `python3 scripts/run-regressions.py` 全绿
- 四平台验收按 `PLUGIN_TEST_CONTRACT.md`；缺任一平台的真实证据时，不得宣称该平台通过
- 生产部署 / 重启 / 真实发送都是**单独的、逐窗口的用户授权动作**；本表不授予任何生产权限
