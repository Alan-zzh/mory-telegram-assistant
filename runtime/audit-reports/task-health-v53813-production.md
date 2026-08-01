# v5.38.13 任务健康生产闭环

日期：2026-08-02 01:24–01:38 CST

## 结论

生产部署与核心业务验收 PASS。8 月 1 日的 43 项“今日未执行/数据库锁异常”是旧监控误报；v5.38.13 已删除错误集合差、恢复跨进程调度指标，并让数据库、任务正文、发送、发现和注册失败向调度器上浮。

## 发布与回滚

- 可信提交：`d83c153`
- 增量文件：73 个；远端编译和 73/73 SHA-256 一致
- 备份：`/home/ubuntu/mory_assistant/backups/deploy_v53813_20260802_012406`
- 备份包含本次远端文件清单、缺失文件清单与 `mory.db` SQLite 在线快照
- 未上传或覆盖 `.env`、`config.json`、`mory.db`

## 生产证据

- 版本：v5.38.13
- 服务：`mory-assistant`、`mory-dashboard` 均 active+enabled
- PID：`159369`、`159370`；NRestarts=0
- 健康接口：`{"status":"ok"}`
- 任务发现：45 个 BaseTask 子类；46 个静态调度项；运行时含触发器共注册 50 个 job
- 启动水合：从 `scheduler_metrics` 恢复 104 个任务
- 持久窗口：累计成功 `2777 → 2809 → 2845`，失败 0、错过 0
- 精确健康链：使用生产配置和只读数据库、假 Bot 执行 `HealthCheckTask`，管理员消息 0，旧假告警 0
- 当前 Bot PID 日志：`database is locked`、Traceback、ERROR、CRITICAL 均 0
- 旧文案日志：`今日未执行`、`数据库锁异常`、`数据库异常：…未执行` 均 0
- 旧进程遗留 1 条 running 已在启动时标记 failed 并释放对应 task_log

## 明确边界

启动成员扫描聚合 3993 个历史用户，发布观察结束时仍为真实 `running`，期间持续产生治理进度；scheduler 每分钟 heartbeat 与两个 5 分钟指标窗口均正常，说明扫描未再阻塞主调度。该长任务尚未伪报 success；若后续数据库或治理动作失败，新代码会以 failed/ERROR 收口。
