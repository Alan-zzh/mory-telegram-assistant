# 任务健康监控真相源

> v5.38.13 起适用。健康检查不得把“任务类存在”或“task_log 没有静态 task_id”当作任务未执行。

## 四类状态

- `scheduler_metrics`：APScheduler 最近状态与累计成功、失败、miss，跨进程恢复。
- `task_execution_history`：业务执行的 running / success / failed / aborted 四态。
- `task_log`：当天任务抢占与防重锁，不是执行历史；审计器只检查同 key 重复记录。
- SQLite 查询异常：系统错误，必须上抛给 APScheduler，不能转成 `False`、空列表或“任务缺失”。

## 重启语义

`attach_to_scheduler(..., db=rm.db)` 在监听事件前水合 `scheduler_metrics`。当前进程已经观察到的 status、last_run、last_error 优先；持久 success/fail/miss 只作为累计基线。晚水合和空表都要标记完成，禁止把本进程刚落盘的计数再次相加；水合未成功时禁止 REPLACE 覆盖历史计数。

新进程在后台任务启动前调用 `cleanup_zombie_running(timeout_seconds=0)`：旧进程遗留的 running 统一记 failed，duration 使用真实 `now-start_ts`，并在同一事务删除对应 `task_log` 锁。

## 任务结果

- 正常完成：success，APScheduler EXECUTED。
- 预期业务空集（如 FAQ 无候选）：`TaskAbort(expected=True)`，历史记 aborted，APScheduler EXECUTED。
- SQLite、代码、网络或审计异常：历史记 failed 并继续抛出，APScheduler ERROR。

## 验证

最小回归覆盖：重启后持久 success 不误报；当前 error 不被旧 success 掩盖；晚水合计数单调；空基线不自增；DB locked 不发送“任务未执行”；审计起点失败释放 task_log；重启回收 running 与锁。
