# v5.38.13 任务健康管理员用户验收

日期：2026-08-02
验收对象：`mory_assistant-task-health-fix` 当前未提交 worktree
视角：生产管理员 / 高频使用者
结论：**PASS（本地用户验收）**

> 边界：本结论证明当前 worktree 已消除本次复现范围内的假“今日未执行 / 数据库锁异常”，不代表 v5.38.13 已部署。当前项目文档仍标明生产运行 v5.38.12，尚缺 VPS 重启、真实 Telegram 回执和生产 journal 证据。

## 管理员可感知结论

- 不再把 45 个已发现的 `BaseTask` 当成每天都该执行，也不再用静态 `task_id` 精确比对动态 `task_log` key；周任务、无 `schedule()` 任务和动态 key 不会再组成 43 项流水账。
- `task_log` 只作为防重记录审计：只有同日同 key 重复才发一条“任务防重记录异常”，不再冒充 SQLite `database is locked`。
- 未到计划日 / 未到截止时间不通知；持久化 success 在进程重启后仍能证明健康；当前进程 error 不会被旧 success 覆盖。
- SQLite 不可读时不发送假“未执行”或假“健康”：`HealthCheckTask` 与 `CriticalJobsHealthTask` 都进入 APScheduler `ERROR`。
- FAQ 无候选是正常业务空集：历史记 `aborted`、释放防重锁，APScheduler 仍为正常执行；真正异常才记 failed / scheduler error。

## 场景验收

| 场景 | 结果 | 观察 | 代码 / 测试证据 |
|---|---|---|---|
| 周六 weekly 未到期 | PASS | 2026-08-01（周六）配置仅周一 `monday_only` weekly 播报，生成的当日关键任务中没有该播报；管理员消息 0。 | `modules/auto_tasks.py:3898-3927,3973-3994`；`tests/unit/test_task_guard.py:242` |
| 无 schedule 任务 | PASS | `startup_member_scan` 等仅启动/独立线程任务即使被发现，也不会被 `task_log` 审计器判为“今日未执行”。 | `tasks/support/task_guard.py:124-142`；`tests/unit/test_task_guard.py:114` |
| 动态 task key | PASS | 10:30 模拟已有 `greeting_morning_2026-08-02` 与 `daily_report`，健康检查管理员消息 0。 | `modules/auto_tasks.py:3934-3971,4001-4007`；本轮内存 DB 黑盒 |
| 重启后 persisted success | PASS | DB 中最近的 `critical_interval=success` 被水合，健康检查返回 True；当前进程 error 保持 error，不被旧 success 覆盖。 | `core/scheduler_monitor.py:40-99,445-453`；`tests/unit/test_scheduler_monitor_persistence.py:49,62` |
| 真实 DB locked | PASS | 实际 BackgroundScheduler 同时运行普通健康检查和关键任务健康检查：两个 job 都收到 `ERROR`；管理员消息 0；monitor 状态均为 `error`；假 missing/alert 列表为空。 | `tasks/monitoring/health_check_task.py:88-147`；`core/scheduler_monitor.py:445-453`；`tasks/monitoring/critical_jobs_health_task.py:38-44`；`tests/unit/test_scheduler_monitor_persistence.py:170` |
| FAQ 无候选 | PASS | `distill_candidates=0` 记录 `aborted: 无新高频问题候选`，没有 failed，且释放 `faq_distill` 锁。 | `tasks/analytics/faq_distill_task.py:120-156`；`tests/unit/test_task_outcome_recovery.py:56` |
| 旧 running 锁恢复 | PASS | 两条旧进程 running 均变为 failed，原因 `process_restarted_before_completion`，duration 按真实时长计算，对应 `task_log` 清零。 | `core/db_repos/task_exec_history_repo.py:190-236`；`tests/unit/test_task_outcome_recovery.py:81` |
| 审计起点 / 报表真实失败 | PASS | `record_task_start` 失败先释放锁再抛出；日报/周报/月报保留 retry，同时继续上抛，APScheduler 不再误记 success。 | `core/task_transaction.py:197-222`；`tests/unit/test_task_transaction.py:116,158`；`tests/unit/test_task_outcome_recovery.py:132` |

## 运行证据

专项回归：

```text
$ python -m pytest -q -p no:cacheprovider \
    tests/unit/test_task_guard.py \
    tests/unit/test_scheduler_monitor_persistence.py \
    tests/unit/test_task_outcome_recovery.py \
    tests/unit/test_task_transaction.py

collected 33 items
33 passed in 0.39s
```

真实 APScheduler 事件黑盒（内存 DB 注入 `sqlite3.OperationalError("database is locked")`）：

```text
apscheduler_events= {
  'critical_db_locked_acceptance': 'ERROR',
  'health_db_locked_acceptance': 'ERROR'
}
admin_message_count= 0
monitor_statuses= {
  'critical_db_locked_acceptance': 'error',
  'health_db_locked_acceptance': 'error'
}
false_missing_alerts= []
```

动态 key / 非计划日黑盒：

```text
saturday_dynamic_broadcasts= []
dynamic_key_admin_messages= 0
```

## 首轮问题与复验

首轮验收曾发现三项 P1：周播在周六被误报、`scheduler_metrics` DB locked 被转成六项“从未执行”、日报/周报吞掉 DB 异常。当前 worktree 已分别补上日期门禁、指标不可读 fail-closed、任务 top-level re-raise；以上命令均在修复后重新运行并通过。

## 剩余用户风险

1. **尚未生产生效。** 当前只是未提交 worktree；部署前后仍需按 ship gate 验证双服务、`/api/health`、版本、重启水合、当前 MainPID journal，以及一条真实 Telegram 管理员回执。
2. `scheduler_metrics` 每 5 分钟落盘，进程被强杀时最近不足 5 分钟的累计事件仍可能丢失；本次已验证不会用旧 success 覆盖当前 error，也不会在 DB 不可读时猜测 missing。
3. 真实 DB 故障在本次验收中选择“不发假 Telegram 文案 + scheduler ERROR”；管理员能否及时收到根因通知仍依赖生产现有 scheduler/故障告警链，需上线后观察真实回执。
4. `modules/auto_tasks.py` 仍保留未注册的 legacy `_job_health_check` / `_TaskGuard` 副本；当前 `TaskScheduler` 路径不调用它，但未来若重新接回，必须同步 fail-closed 语义，避免旧逻辑回流。
