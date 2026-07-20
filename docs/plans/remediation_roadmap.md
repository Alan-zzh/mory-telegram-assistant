# 整改路线图（Remediation Roadmap）

> 落点：`docs/plans/`（文档路由表规定的"计划/方案"目录）
> 创建：2026-07-07 | 状态：已完成（2026-07-07 第一轮 + 第二轮 P2 全部收尾）
> 最后更新：2026-07-18 状态归档（v5.32.0）

## 背景

2026-07-07 对 mory_assistant 执行了一次深度审计（产出见 `runtime/audit-reports/PROJECT_AUDIT_REPORT.md`）。
核心结论：项目**功能真实、非虚报**；主要病灶是文档数字夸大自相矛盾、文件卫生差、少量死代码，无 P0 阻塞项。
审计共登记 25 项 CLAIM（22 真实 / 3 过度乐观）、12 项 ISSUE（按 P0/P1/P2 分级）。

## 第一轮（已完成，2026-07-07）

范围：P0 + P1 + 清理/迁移 + 文档治理。

- 清理隔离区：9 项垃圾迁入 `_quarantine_20260707/`；删除根 `__pycache__`/`.pytest_cache`；保留 `_ssh_known_hosts`（部署依赖）。
- 新增 `scripts/doc_consistency.py`：文档数字（`project_snapshot.md` 的 `METRICS` 块）与代码实测指标对齐，CI/提交前可断言，退出码 0 通过。
- 归档 6 份膨胀旧文档至 `docs/archive/20260707/`；审计报告迁移至 `runtime/audit-reports/`。
- 重建 6 份根文档，行数 8593 → 289，全部在文档路由表上限内，并写入防失真 `METRICS` 块。
- 验收：`EXECUTION_REPORT.md` + `EXECUTION_LOG.md`。

## 第二轮（P2，2026-07-07 收尾）

范围：审计登记的全部 P2 项。

- [x] ISSUE-002 死代码：删除 `structured_logger.get_struct_logger` / `clear_context`、`pinyin_util.has_pinyin_leak`（全仓 0 引用）。
- [x] ISSUE-003 重复路由：抽取 `core/handlers/utility_dispatch.py::dispatch_utility_commands`，消除 `module_handlers` 与 `command_handlers` 重复的置顶/订阅/工具/提醒命令链。
- [x] ISSUE-007 文档数字：修正 `docs/technical/capability-matrix.md` 中 `cart_recovery`「每小时」→「每5分钟」（与 `auto_tasks` cron `minute=*/5` 一致，2 处）。
- [x] ISSUE-010 半实现：将 `profile_learner` 的 sticker 维度显式标注为未启用（`STICKER_DIMENSION_ENABLED=False`）。
- [x] ISSUE-011 硬编码凭证：`scripts/scan_group.py` 公开 api_hash 提升为命名常量（脚本为 gitignore，仅本地修正）。
- [x] ISSUE-012 规划缺失：本文件补齐 `docs/plans/` 实体计划。
- 经核实已消解（非真问题）：
  - ISSUE-005「34 拦截点」：仅残留在归档旧 README / 审计报告；重建后的 README 已无此矛盾。
  - ISSUE-006「25 mode」：指 `config.json.example` 的 `MODE_ROUTING`（实测 25 项），与 `model_router` 的 10 个内部 task_type 映射是两回事；审计属误比对，文档准确无需改。

## 后续观察项（非本轮）

- 文档数字仍依赖人工同步到 `METRICS` 块，已用 `doc_consistency.py` 兜底，建议接入 pre-commit / CI。
- `config.json.example` 的 `MODE_ROUTING` 与 `model_router` 的内部映射是两个层级，后续若扩展模型路由需同步两处。
