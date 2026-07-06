# 整改执行台账 (EXECUTION_LOG)

> 任务来源：根目录 `PROJECT_AUDIT_REPORT.md` 路线图 P0+P1+P2（首轮做 P0+P1+清理/迁移+文档治理，收尾轮做全部 P2）
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
| Phase 6 | 验收报告 + 最终 commit + P2 收尾 | ✅ 完成 | 本台账 + `EXECUTION_REPORT.md` |

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
| PH6-验收 | ✅ 完成 | `EXECUTION_REPORT.md` | 全量复检 + 最终 commit + P2 收尾 |

### 第二轮 P2 执行（2026-07-07 收尾，已全完成）

| 任务ID | 状态 | 证据 | 备注 |
|--------|------|------|------|
| ISSUE-002 | ✅ 完成 | `core/structured_logger.py` 删 get_struct_logger/clear_context；`core/pinyin_util.py` 删 has_pinyin_leak | 全仓 0 引用 |
| ISSUE-003 | ✅ 完成 | 新增 `core/handlers/utility_dispatch.py`；两 handler 改为 `dispatch_utility_commands` 调用 | py_compile 通过；19 命令分支仅存于公共模块 |
| ISSUE-005 | ✅ 已消解 | 重建后 README 已无"34 拦截点"；仅残留在归档旧文档/审计报告 | 无需改动 |
| ISSUE-006 | ✅ 误报 | 实测 config.json.example MODE_ROUTING=25；文档"25 mode"准确 | 审计误比对 config 配置项与 model_router 内部映射 |
| ISSUE-007 | ✅ 完成 | `docs/technical/capability-matrix.md` 两处"每小时"→"每5分钟" | 与 cron minute=*/5 一致 |
| ISSUE-010 | ✅ 完成 | `core/profile_learner.py` 新增 `STICKER_DIMENSION_ENABLED=False` | sticker 维度显式标注未启用 |
| ISSUE-011 | ✅ 完成 | `scripts/scan_group.py` 硬编码 api_hash 提升为命名常量 | 脚本为 gitignore，本地修正不进提交 |
| ISSUE-012 | ✅ 完成 | 新增 `docs/plans/remediation_roadmap.md` | 补齐计划文档 |

> 全程由 `scripts/doc_consistency.py` 门禁守护：P2 新增 `utility_dispatch.py` 后该脚本即时拦出 core_py 73→74 偏移，已同步 `project_snapshot.md` 与 `README.md`。

---

## 人工动作项（需用户确认，非代码可自动完成）

1. 审阅 `_quarantine_20260707/` 隔离内容，确认无误后可手动永久删除（已脱离 git 与同步盘噪声）。
2. VPS 部署目录若为旧版快照，需重新 `rsync` 根目录（本次清理未触碰运行时文件，但根目录结构已变）。
3. 如需恢复任一旧文档，从 `docs/archive/20260707/` 取回。
