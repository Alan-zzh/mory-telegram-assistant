# Mory 小助理能力真相索引

> 本文只保留稳定边界和真相源，不复制易漂移的文件数、路由数、任务数或行号。
> 当前数量统一读取 `project_snapshot.md` 的 `METRICS` 块并由 `scripts/doc_consistency.py` 校验。

## 1. 用户可见能力

| 能力 | 当前状态 | 运行入口 | 事实边界 |
|---|---|---|---|
| 群聊与私聊回复 | 在用 | `core/message_dispatcher.py` | 经过治理、关键词、FAQ、成交和 AI 分发；私聊不挂销售按钮 |
| 广告治理 | 在用 | `modules/ad_enforcement.py` | 逐条证据后删除消息、永久禁言并写双黑名单；不踢人 |
| 误封恢复 | 管理员审核 | `/unban`、审核回调 | 普通用户反馈只能提交复核，不能自行清状态或恢复权限 |
| 三档传统文化栏目 | 生产启用 | `tasks/broadcast/mystic_broadcast_task.py` | 北京时间黄历、塔罗、易经三档；模式固定，不串台 |
| 普通问候 | 默认关闭 | `tasks/broadcast/greeting_task.py` | 开关改变后由热重载真实增删任务 |
| 定点自定义播报 | 可配置 | `modules/scheduled_broadcast.py` | 按配置注册；失败必须释放防重锁并向调度器上浮 |
| 新闻播报 | 已删除 | 无 | 执行链、Dashboard 写入口和配置键均删除，不保留幽灵开关 |
| Dashboard | 在用 | `dashboard/app.py`、`dashboard/api/` | 登录后管理配置和查看运行证据；写操作受 RBAC/CSRF 约束 |

## 2. 运行架构

- Bot：`mory-assistant.service`，唯一入口 `main.py`。
- Dashboard：`mory-dashboard.service`，与 Bot 分进程；不能直接读取 Bot 内存 scheduler。
- 调度：`tasks/task_scheduler.py` 自动发现 `BaseTask`；场景触发器经 `modules/triggers/base.py` 同步刷新。
- 资源：BotContext、消息链和后台任务共用同一个 `ResourceManager` 锁域。
- 数据库：SQLite WAL；`task_log` 只用于任务抢占/防重锁，不是执行历史。

## 3. 健康与调度数据语义

| 表面 | 真实语义 |
|---|---|
| `/api/health` | DB 与 Bot 心跳探活；不返回版本，也不证明业务成功 |
| `/api/health/task-success-rate` | 仅统计进入 `TaskTransactionManager` 的事务任务四态，不覆盖全部 APScheduler 作业 |
| `task_execution_history` | 事务任务的 success/failed/aborted/running 历史 |
| `scheduler_metrics` | 跨重启累计历史指标；可能含已删除或已禁用任务，不能当当前注册清单 |
| Bot 进程 `scheduler.get_jobs()` | 当前注册任务的唯一直接真相；Dashboard 分进程不可用时必须显示 unavailable |
| journal | 运行补充证据；日志轮转后不构成完整历史 |

健康页没有实测的维度必须显示“未知”，不得用固定 70/75/80/100 分代替探测。

## 4. 配置与部署

- 配置模板：`config.json.example`；生产 `config.json` 含运行态与敏感字段，禁止直接覆盖。
- 新功能默认关闭；动态开关必须覆盖 `false → true → false` 的真实 job 集测试。
- 部署：`deploy_vps.py`；双 systemd 服务，unit 必须 `root:root 0644`。
- 凭据：`.env` 和 `config.json` 生产权限 `0600`；root cron 只执行 root-owned watchdog 副本。
- 生产验收：双服务/PID、health liveness、VPS 版本或受影响文件 hash、启动窗口日志和真实业务探针；调度变更另附当前执行与事务四态，详见 `runbook-ship-gate.md`。

## 5. 代码入口索引

- 对话与成交：`docs/technical/persona-engine.md`
- 广告治理：`docs/technical/ad-detection.md`
- 架构边界：`docs/technical/architecture-truth.md`
- 生产侦察：`docs/technical/runbook-vps-recon.md`
- 发布门禁：`docs/technical/runbook-ship-gate.md`
- 安全删除与重构：`docs/technical/runbook-safe-change.md`

历史详尽矩阵已归档在 `docs/archive/20260805_governance/capability-matrix.md`，仅用于追溯，不能作为当前运行依据。
