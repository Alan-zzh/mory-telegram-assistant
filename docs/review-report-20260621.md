# 文档审查报告

> **审查时间**：2026-06-21
> **审查范围**：README.md、project_snapshot.md、docs/ 目录
> **审查方法**：实际代码/配置文件验证 vs 文档声称数据

---

## 1. 数据准确性问题（高优先级）

### 1.1 模块数量 ✅ 准确

| 位置 | 声称 | 实测 | 状态 |
|------|------|------|------|
| README.md §1.8 | 88 个 | 88 个 | ✅ 准确 |

---

### 1.2 数据库表数量 ❌ 内部矛盾 + 偏差

| 位置 | 声称 | 实测 | 状态 |
|------|------|------|------|
| README.md §1.12 | 107 个 | 108 个 | ❌ 偏差 |
| README.md §7.1 | **108 张** | 108 个 | ✅ 准确 |
| project_snapshot.md | 107 张 | 108 个 | ❌ 偏差 |

**问题**：
1. README.md 内部自相矛盾（§1.12 写 107，§7.1 写 108）
2. v5.27.0-RC1 版本新增了 `interaction_quality_scores` 表，但 §1.12 未同步更新

**建议修正**：
- 统一为 **108 张**（与 §7.1 一致）
- 更新 §1.12 的表计数

---

### 1.3 API 端点数量 ❌ 严重偏差

| 位置 | 声称 | 实测 | 状态 |
|------|------|------|------|
| README.md §1.9 | **11 个文件 / 124 个路由** | **21 个文件 / 156 个路由** | ❌ 严重过时 |

**实际文件数量**：21 个（README 只列了 11 个）

**遗漏的文件**（10 个）：
| 文件 | 端点数 |
|------|--------|
| `attribution_api.py` | 8 |
| `audit_api.py` | 3 |
| `bot_routing_api.py` | 4 |
| `funnel_api.py` | 2 |
| `metrics_api.py` | 1 |
| `monitor_api.py` | 1 |
| `quality_api.py` | 2 |
| `rbac_approval_api.py` | 6 |
| `scheduler_api.py` | 2 |
| `user_lifecycle_api.py` | 1 |

**建议修正**：
- 更新文件数量为 **21 个**
- 更新路由总数为 **156 个**
- 补充遗漏的 10 个 API 文件

---

### 1.4 任务数量 ❌ 严重偏差

| 位置 | 声称 | 实测 | 状态 |
|------|------|------|------|
| README.md §1.11 | **37 个 _job_*** | **52 个 _job_*** | ❌ 严重过时 |
| project_snapshot.md | 37 个 _job_* | 52 个 | ❌ 严重过时 |

**新增的 15 个任务**（v5.26.0 后添加）：
1. `_job_ab_guardian` - A/B 测试守护
2. `_job_ab_weekly` - A/B 周报
3. `_job_alert_health_check` - 告警健康检查
4. `_job_check_db_migration` - 数据库迁移检查
5. `_job_clean_relay_sessions` - 中继会话清理
6. `_job_daily_backup` - 每日备份
7. `_job_evaluate_conversation_quality` - 对话质量评估
8. `_job_faq_distill` - FAQ 蒸馏
9. `_job_flush_alert_summary` - 告警摘要刷新
10. `_job_log_cleanup` - 日志清理
11. `_job_memory_idle_scan` - 记忆空闲扫描
12. `_job_rbac_audit` - RBAC 审计
13. `_job_startup_history_cleanup` - 启动历史清理
14. `_job_sync_scheduler_metrics` - 调度器指标同步
15. `_job_sync_user_lifecycle_buckets` - 用户生命周期桶同步
16. `_job_update_prometheus_metrics` - Prometheus 指标更新

**建议修正**：
- 更新任务总数为 **52 个**
- 补充新增任务到表格中

---

## 2. 文档内部一致性问题（中优先级）

### 2.1 README.md 内部矛盾

| 章节 | 问题 |
|------|------|
| §1.12 | 声称 107 张表 |
| §7.1 | 声称 108 张表 |
| **结论** | 两处数字不一致，应统一 |

### 2.2 与 project_snapshot.md 不一致

| 项目 | README.md | project_snapshot.md | 实测 |
|------|-----------|---------------------|------|
| 数据库表 | 107/108（矛盾） | 107 | 108 |
| API 端点 | 124 | 124 | 156 |
| 任务数量 | 37 | 37 | 52 |

---

## 3. 过时信息问题（中优先级）

### 3.1 v5.26.0 后新增内容未同步

以下 v5.26.0-v5.28.0 新增的组件在 README.md 中缺失：

| 组件 | 版本 | 说明 |
|------|------|------|
| `core/growth_optimizer.py` | v5.28.0 | 10 项增长优化 |
| `core/quality_evaluator.py` | v5.27.0-RC1 | 质量评估 |
| `core/user_lifecycle.py` | v5.27.0-RC1 | 用户生命周期 |
| `dashboard/api/attribution_api.py` | v5.23.0 | 归因报表 |
| `dashboard/api/audit_api.py` | v5.23.0 | 审计日志 |
| `dashboard/api/bot_routing_api.py` | v5.26.0 | 多 Bot 路由 |
| `dashboard/api/funnel_api.py` | v5.27.0-RC1 | 漏斗可视化 |
| `dashboard/api/metrics_api.py` | v5.27.0-RC1 | Prometheus 指标 |
| `dashboard/api/rbac_approval_api.py` | v5.26.0 | RBAC 审批流 |
| `dashboard/api/scheduler_api.py` | v5.23.0 | 调度监控 |
| `dashboard/api/user_lifecycle_api.py` | v5.27.0-RC1 | 生命周期分布 |

---

## 4. 未来规划写成已完成的情况（低优先级）

### 4.1 部分功能标注为"待启用"

以下配置项在文档中标注为"待启用"或"默认关闭"，属于合理描述：
- `INTENT_LLM_ENABLED=false`
- `TRACING_ENABLED=false`
- `QUALITY_EVAL_SAMPLE_RATE=0.03`

**结论**：无明显的"未来规划写成已完成"问题，但部分新功能的文档说明不够充分。

---

## 5. docs/ 目录规范性（低优先级）

### 5.1 目录结构

```
docs/
├── archive/          # 过时文档归档
├── plans/            # 计划文档（仅 README.md）
├── reference/        # 参考资料
├── technical/        # 技术文档（18 篇，规范）
└── vision/           # 愿景文档（仅 README.md）
```

### 5.2 问题

| 目录 | 问题 |
|------|------|
| `docs/plans/` | 仅含 README.md，无实际计划文档 |
| `docs/vision/` | 仅含 README.md，无实际愿景文档 |
| `docs/technical/` | 18 篇文档，结构清晰，✅ 规范 |

---

## 6. 重复内容问题（低优先级）

### 6.1 README.md 内部重复

| 重复内容 | 出现位置 |
|----------|----------|
| "124 API 端点" | §1.9、§2.2、§3.5、§6.2 共 4 处 |
| "8 类设置面板 115 按钮" | §1.9、§3.4、§6.3 共 3 处 |
| "34 个拦截点" | §1.10、§3.6 共 2 处 |
| "107 张表" | §1.12、§7.1、§7.2 共 3 处 |

**建议**：使用交叉引用减少重复，如"详见 §1.9"

---

## 7. 修正建议汇总

### 7.1 必须修正（高优先级）

| 文件 | 位置 | 当前值 | 建议值 | 原因 |
|------|------|--------|--------|------|
| README.md | §1.9 | 11 个文件 / 124 路由 | 21 个文件 / 156 路由 | 严重偏差 |
| README.md | §1.11 | 37 个 _job_* | 52 个 _job_* | 严重偏差 |
| README.md | §1.12 | 107 张表 | 108 张表 | 与 §7.1 矛盾 |
| project_snapshot.md | §3 | 37 个任务 | 52 个任务 | 严重偏差 |
| project_snapshot.md | §3 | 107 张表 | 108 张表 | 偏差 |

### 7.2 建议修正（中优先级）

| 文件 | 建议 |
|------|------|
| README.md | 补充 v5.26.0-v5.28.0 新增的 10 个 API 文件 |
| README.md | 补充 v5.26.0-v5.28.0 新增的核心模块说明 |
| README.md | 统一 §1.12 和 §7.1 的表计数 |
| project_snapshot.md | 同步更新所有数字 |

### 7.3 可选优化（低优先级）

| 文件 | 建议 |
|------|------|
| README.md | 减少重复内容，使用交叉引用 |
| docs/plans/ | 补充实际计划文档 |
| docs/vision/ | 补充实际愿景文档 |

---

## 8. 审查结论

| 维度 | 评分 | 说明 |
|------|------|------|
| 数据准确性 | ⚠️ 中等 | 模块数量准确，但 API/任务/表数量严重偏差 |
| 内部一致性 | ⚠️ 中等 | README.md 内部存在矛盾 |
| 时效性 | ❌ 较差 | v5.26.0 后新增内容大量未同步 |
| 完整性 | ✅ 良好 | docs/technical/ 结构清晰 |
| 重复度 | ⚠️ 一般 | 存在多处重复，但不影响理解 |

**总体评价**：README.md 和 project_snapshot.md 的数字需要紧急修正，建议在下个版本更新时统一修复。

---

**审查人**：puzan-reviewer
**审查时间**：2026-06-21
**状态**：ready_for_review
