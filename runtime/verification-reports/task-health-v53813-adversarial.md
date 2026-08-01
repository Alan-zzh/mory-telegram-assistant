PASS

# v5.38.13 任务健康最终对抗审计

日期：2026-08-02
对象：`codex/task-health-lock-fix` 未提交 worktree（基线 `42c033b`）
结论：本地发布候选无未解决 P0/P1；P0=0，P1=0。生产仍为 v5.38.12，本报告不代表已部署或已取得真实 Telegram 回执。

## 关键结论

- 43 项“今日未执行”误报根因已消除：`task_log` 只审计同日同 key 重复，不再把 45 个已发现任务类与动态防重 key 做集合差。
- SQLite、抢占、审计起点、资源锁、任务正文、单群/多群发送失败均不会再被 APScheduler 记作正常成功；预期空集才使用 `TaskAbort(expected=True)`。
- `scheduler_metrics` 支持跨重启水合，当前进程 error/missed 优先，晚水合累计不丢失、不重复；数据库不可读时拒绝猜测健康。
- 旧进程 `running` 与对应 `task_log` 锁在启动前同一事务回收；回收连续失败、任务发现/实例化/注册、触发器注册或监控附加失败均阻止残缺调度器启动。
- 干净检出所需的包入口、部署工具、强制频道/订阅模块和两个 check task 已从宽泛忽略规则中恢复；实测发现 45 个任务类、46 个静态调度项。

## 对抗复验

| 门禁 | 命令 | 结果 |
|---|---|---|
| 整仓测试 | `python -m pytest -q -p no:cacheprovider` | `830 collected; 804 passed, 26 skipped` |
| 高风险专项 | `python -m pytest -q -p no:cacheprovider tests/unit/test_task_transaction.py tests/unit/test_task_outcome_recovery.py tests/unit/test_startup_background_health.py tests/unit/test_task_guard.py tests/unit/test_scheduler_monitor_persistence.py tests/unit/test_task_exception_truth.py tests/unit/test_scheduled_broadcast_rich.py tests/unit/test_automatic_reply_contract.py` | 修复中间点 `99 passed, 2 skipped`；最终行为由整仓复验覆盖 |
| DB 委托注册 | `python scripts/verify_db_methods.py` | `197 个委托方法，无缺失、无孤儿` |
| 文档数字 | `python scripts/doc_consistency.py` | 全部一致 |
| Diff | `git diff --check` | PASS（仅换行格式提示，无 whitespace error） |
| 源码编译 | 对 `core/modules/tasks/scripts/dashboard` 共 323 个 `.py` 使用内存 `compile()` | 0 error |
| 任务结构 | AST 扫描 BaseTask 顶层 broad handler，接受直接 re-raise 或最终 `ExceptionGroup` 聚合 | 0 个未交代 handler |
| 任务发现 | `TaskScheduler._discover_and_load_tasks()` + `sum(task.schedule())` | 45 个类、46 个静态调度项，两个恢复的 check task 均存在 |

故障注入覆盖了：真实 `sqlite3.OperationalError("database is locked")`、历史水合失败/晚水合、抢占和 `record_task_start` 失败、资源锁未知/超时、旧 running 回收执行/commit 失败、任务包 import/实例化/add_job/监听器附加失败、动态日期非法、定点播报媒体失败、购物车/召回/问候部分投递失败。以上路径均表现为失败上浮或启动 fail closed，而不是假 success。

## 已在复审中发现并修复

1. `TaskTransactionManager` 审计起点或资源锁失败曾可能遗留锁或返回正常；现释放锁、写 failed 并上抛。
2. 指标晚水合曾可能丢累计或重复相加；现以 `_metrics_hydrated/_persisted_loaded` 控制单次合并。
3. DB 查询错误曾被折叠成 `False/[]`，触发假“任务缺失”；现查询链与健康任务均上抛。
4. 定点播报、购物车、召回、启动扫描和多群问候曾能在部分失败后写 success；现继续独立步骤后聚合失败，多群问候部分成功时禁止整批重试以免重复发送。
5. 任务包/模块导入、实例化、重复 task id、schedule/add_job、触发器和监控附加曾可 warning 后残缺启动；现收集错误后 fail closed，首个持久心跳只在 scheduler 真正启动后写入。
6. 宽泛 `_*.py` 忽略规则曾排除真实运行文件；否定规则已后置，`git status --short` 可见全部待纳入文件。

## 剩余 P2 与发布边界

1. `scheduler_metrics` 每 5 分钟刷盘；SIGKILL 最多仍可能丢最近不足 5 分钟的累计事件，但不会用旧 success 覆盖当前进程 error。
2. `dashboard/api/health_api.py` 在 heartbeat 行不存在或 `system_states` 查询失败时仍可能返回 200；现有生产库通常已有该行，但新环境/表损坏场景需另行收紧为 fail closed。
3. 自定义的深夜动态播报若使用非默认 ID 且截止时间晚于当日最后一次 `HealthCheckTask`，主要依赖 APScheduler ERROR/日志；硬编码 `CriticalJobsHealth` 不覆盖所有自定义 ID。部署后需用真实配置逐项核对 next-run 与回执。
4. `deploy_vps.py` 会创建备份并在失败后重启服务，但不会自动把代码恢复到备份，且备份失败当前是非致命；它不能单独作为“失败已回滚”的证据。生产发布必须先取得可恢复备份，并在任一 hash/启动/health/journal/业务回执失败时显式恢复该备份。

## 生产放行条件

1. 提交时必须纳入当前所有未跟踪运行文件及测试；不能只提交已跟踪 diff。
2. 按 `docs/technical/runbook-vps-recon.md` 先只读侦察，备份后只增量上传；不得覆盖 `.env`、`config.json`、`mory.db`。
3. 重启后验证 `mory-assistant`、`mory-dashboard` 均 `active+enabled`，`localhost:6616/api/health=200`，运行版本为 v5.38.13，MainPID 当前 journal 无新错误。
4. 复验 45 个任务类、生产配置对应的完整 APScheduler job 清单、重启后 `scheduler_metrics` 水合、旧 running/锁回收，并取得至少一条真实管理员任务健康回执。
5. 任一条件不满足即恢复部署前备份；未取得以上生产证据前只能称“本地 PASS”，不能称生产完成。
