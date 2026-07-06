# 整改执行台账 (EXECUTION_LOG)

> 任务来源：根目录 `PROJECT_AUDIT_REPORT.md` 路线图 P0+P1（本轮仅做 P0 + P1 + 清理/迁移 + 文档治理；P2 留下一轮）
> 基线 commit：`e20abf1`（chore: 整改前基线）
> 台账创建：2026-07-07
> 格式：`任务ID | 状态 | 证据 | 备注`（证据均为真实路径/命令输出，禁止编造）

---

## 进度总览

| Phase | 动作 | 状态 | 证据 |
|-------|------|------|------|
| Phase 0 | 整改前基线 commit | ✅ 完成 | `e20abf1` |
| Phase 1 | 现场核实审计结论 | ✅ 完成 | 7 项指标实测；修正审计 2 处错误 |
| Phase 2 | P0 修复 | ⏭ 跳过 | 审计判定无 P0 阻塞项 |
| Phase 3 | 清理/隔离/迁移 | ✅ 完成 | `_quarantine_20260707/` + 根残留清空 |
| Phase 4 | P1 修复 | ✅ 完成 | `scripts/doc_consistency.py` + 归档 + 迁移审计报告 |
| Phase 5 | 重建六份根文档 | ✅ 完成 | 6 份文档 + 防失真 METRICS 块（自检通过） |
| Phase 6 | 验收报告 + 最终 commit | 🔄 进行中 | 本台账 + `EXECUTION_REPORT.md` |

---

## 任务明细（任务ID | 状态 | 证据 | 备注）

| 任务ID | 状态 | 证据 | 备注 |
|--------|------|------|------|
| PH1-核实 | ✅ 完成 | `python scripts/doc_consistency.py` 实测 7 项 | 审计称 modules=92 / model_router=11，**实测为 91 / 10**，以实测为准写入文档 |
| PH3-隔离 | ✅ 完成 | `_quarantine_20260707/`（9 项） | backup/ backups/ deploy_run.log deploy_run2.log deploy_run3.log fault_alerts.log fault_dedup_state.json reload_flag test_selfcheck.db |
| PH3-删缓存 | ✅ 完成 | 根目录 `__pycache__/` `.pytest_cache/` 已删 | 降低同步盘噪声 |
| PH3-保留 | ✅ 完成 | `_ssh_known_hosts` 仍在根目录 | VPS 部署依赖，非垃圾，列入白名单保留 |
| ISSUE-001 | ✅ 完成 | `scripts/doc_consistency.py` | 文档数字与代码挂钩，CI/提交前可断言 |
| ISSUE-004 | ✅ 完成 | `_quarantine_20260707/` | 根残留清理（与 PH3 合并执行） |
| ISSUE-008 | ✅ 完成 | `docs/archive/20260707/` + `runtime/audit-reports/PROJECT_AUDIT_REPORT.md` | 6 份旧文档归档；审计报告迁移至审计目录 |
| ISSUE-009 | ✅ 完成 | `scripts/doc_consistency.py` 退出码 0 | 文档一致性纳入自检脚本 |
| PH5-VERSION | ✅ 完成 | `VERSION.md`（12 行，≤30） | 删除"零暗病"过度乐观自评 |
| PH5-snapshot | ✅ 完成 | `project_snapshot.md`（44 行，≤150） | 覆盖式 + METRICS 块（7 项） |
| PH5-AGENTS | ✅ 完成 | `AGENTS.md`（110 行，≤300） | 含铁律/流程/路由表/防失真规则 |
| PH5-CHANGELOG | ✅ 完成 | `CHANGELOG.md`（20 行，≤400） | 一行式 + 旧日志归档 |
| PH5-AI_DEBUG | ✅ 完成 | `AI_DEBUG_HISTORY.md`（47 行，≤300） | 去重 6 条反复暗病 |
| PH5-README | ✅ 完成 | `README.md`（56 行） | 按当前真实状态重写 |
| PH6-验收 | 🔄 进行中 | `EXECUTION_REPORT.md`（待生成） | 全量复检 + 最终 commit |

---

## 下一轮待办（P2，本轮未做）

| 任务ID | 内容 | 备注 |
|--------|------|------|
| ISSUE-002 | 删除死代码 `structured_logger.py:104/150`、`pinyin_util.py:98` | 低风险，下一轮 |
| ISSUE-003 | 合并重复 handler 路由 `module_handlers.py:227-275` vs `command_handlers.py:1349-1394` | 需回归测试 |
| ISSUE-005 | 文档数字修正：34 拦截 | 与 METRICS 块对齐后自然消解 |
| ISSUE-006 | 文档数字修正：25 模式 | 同上 |
| ISSUE-007 | 文档数字修正：hourly-cart-recovery | 同上 |
| ISSUE-010 | 贴纸尺寸 | 下一轮 |
| ISSUE-011 | api_hash 纳入 config | 下一轮 |
| ISSUE-012 | plans 文档 | 下一轮 |

---

## 人工动作项（需用户确认，非代码可自动完成）

1. 审阅 `_quarantine_20260707/` 隔离内容，确认无误后可手动永久删除（已脱离 git 与同步盘噪声）。
2. VPS 部署目录若为旧版快照，需重新 `rsync` 根目录（本次清理未触碰运行时文件，但根目录结构已变）。
3. 如需恢复任一旧文档，从 `docs/archive/20260707/` 取回。
