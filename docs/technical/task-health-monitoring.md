# 任务健康监控真相源

> v5.38.13 起适用。健康检查不得把“任务类存在”或“task_log 没有静态 task_id”当作任务未执行。

## 四类状态

- `scheduler_metrics`：APScheduler 最近状态与累计成功、失败、miss，跨进程恢复。
- `task_execution_history`：仅覆盖进入 `TaskTransactionManager` 的业务事务四态，不覆盖全部 APScheduler job；最近窗口为 0 只表示该窗口无事务任务记录，必须同时看历史总数、最新记录和 `scheduler_metrics`。
- `task_log`：当天任务抢占与防重锁，不是执行历史；审计器只检查同 key 重复记录。
- SQLite 查询异常：系统错误，必须上抛给 APScheduler，不能转成 `False`、空列表或“任务缺失”。

Dashboard 的 `last_error` 只表示当前 `last_status=error` 的故障；任务恢复成功后，旧原因保留在 `last_failure_error`，并以 `error_scope=historical` 标明历史范围。生产巡检保留 `scheduler_metrics_cumulative_failures` 原始字符串供兼容，同时以 `scheduler_metrics_failure_history` 输出 `job_id`、`current_status`、`cumulative_fail_count`、`cumulative_miss_count`、`last_run`、`last_status_at`、`error_scope` 与 `last_failure_error`。其中 `last_status_at` 才是当前状态事件时间，`0` 表示旧记录时间不可证明；`last_run` 只为旧消费者保留，禁止用刷盘时间 `synced_at` 或最新成功时间冒充当前错误、missed 的发生时间。累计失败次数不清零；当前一小时错误和 missed 必须按 `last_status_at` 判定。

生产巡检保留旧 `task_1h/task_5min` 字段供兼容，但人类可读输出使用 `transactional_task_1h/5min`，并固定附带 `coverage=TaskTransactionManager_only`、`task_history_total` 与最新历史记录。`scheduler_metrics` 的 EXECUTED 仅证明 callable 未向外抛异常，不得冒充业务动作完成。

## 重启语义

`attach_to_scheduler(..., db=rm.db)` 在监听事件前水合 `scheduler_metrics`。当前进程已经观察到的 status、last_run、last_error 优先；持久 success/fail/miss 只作为累计基线。晚水合和空表都要标记完成，禁止把本进程刚落盘的计数再次相加；水合未成功时禁止 REPLACE 覆盖历史计数。

新进程在后台任务启动前调用 `cleanup_zombie_running(timeout_seconds=0)`：旧进程遗留的 running 统一记 failed，duration 使用真实 `now-start_ts`，并在同一事务删除对应 `task_log` 锁。

## 停机语义

启动成员扫描与历史清理运行在独立维护线程，但仍共享 `ResourceManager` 和 SQLite。停机时，调度器 drain 与启动维护线程 join 共用一个单调时钟总预算；只有两者都结束才关闭数据库。维护线程未在时限内退出时必须失败可见并保留数据库连接，禁止强杀线程后假报优雅停机。

## 任务结果

- 正常完成：success，APScheduler EXECUTED。
- 预期业务空集（如 FAQ 无候选）：`TaskAbort(expected=True)`，历史记 aborted，APScheduler EXECUTED。
- SQLite、代码、网络或审计异常：历史记 failed 并继续抛出，APScheduler ERROR。

## 验证

最小回归覆盖：重启后持久 success 不误报；当前 error 不被旧 success 掩盖；晚水合计数单调；空基线不自增；DB locked 不发送“任务未执行”；审计起点失败释放 task_log；重启回收 running 与锁。
