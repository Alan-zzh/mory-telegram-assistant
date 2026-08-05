# 孤儿消息清理机制详解

> 本文档为独立技术说明，未被 AGENTS.md 直接索引 · 适用版本：v5.12.0+ / v5.38.x 现行机制
> **最后更新**：2026-06-02（v5.12.1 .agents→AGENTS.md）

## 概述

Mory 小助理作为群管理 Bot，会主动发送大量"播报型"消息（早安/午安/晚安问候、用户升级祝贺、新闻播报等）。这类消息**没有用户会回复**（不是问题、不是命令），如果不主动清理，群消息历史会很快被这类"孤儿消息"占满。

本文档详述 v5.12.0 实现的**孤儿消息自动清理**完整方案。**现行机制（v5.38.x）**：定时兜底任务已迁移至 `tasks/maintenance/burn_orphan_task.py`（`BurnOrphanTask`，每 6 小时，由 `task_scheduler.py` 自动发现注册），受独立开关 `ORPHAN_CLEANUP_ENABLED` 控制；`modules/auto_tasks.py` 中的 `_job_burn_orphan` 为 legacy 保留实现。

## 适用场景

- 排查"为什么孤儿消息没被删除"时查阅
- 新增播报类功能时，参考此机制接入
- 调试 `ENABLE_MESSAGE_DELETION` 全局开关时查阅

## 关键内容

### 一、三层保障机制

| 层级 | 触发时机 | 实现 | 适用场景 |
|------|---------|------|---------|
| **第一层** | 实时（30秒后） | `threading.Timer` 调度单条删除 | 升级播报"恭喜X升级到Lv2" |
| **第二层** | 定时（每6小时） | `tasks/maintenance/burn_orphan_task.py`（`BurnOrphanTask`，task_scheduler 自动注册；`_job_burn_orphan` 为 legacy） | 所有 30 分钟超时孤儿兜底 |
| **第三层** | 发新消息时 | 链式互删（发午安自动删早安） | 早安/午安/晚安链式清理 |

### 二、数据库表设计

#### 2.1 `broadcast_tracking` 表（v5.11.0 引入）

```sql
CREATE TABLE IF NOT EXISTS broadcast_tracking (
    chat_id INTEGER NOT NULL,
    category TEXT NOT NULL,        -- 'level_up' / 'greeting' / 'news' / 'custom'
    msg_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    PRIMARY KEY (chat_id, category)  -- 复合主键：同群同类型只保留最新一条
);
```

**关键设计**：复合主键 `(chat_id, category)` 确保同群同类型播报只保留最新一条，发新播报时自动 REPLACE 旧记录。

#### 2.2 `orphan_cleanup_log` 表（v5.12.0 引入）

```sql
CREATE TABLE IF NOT EXISTS orphan_cleanup_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at INTEGER NOT NULL,
    found_count INTEGER NOT NULL DEFAULT 0,   -- 发现孤儿数
    deleted_count INTEGER NOT NULL DEFAULT 0, -- 实际删除数
    skipped_count INTEGER NOT NULL DEFAULT 0, -- 跳过数
    error TEXT DEFAULT NULL,                  -- 错误信息
    trigger TEXT DEFAULT 'scheduled'          -- 'scheduled' / 'manual' / 'force'
);
CREATE INDEX IF NOT EXISTS idx_orphan_cleanup_log_run_at ON orphan_cleanup_log(run_at);
```

**用途**：每次 `burn_orphan` 定时任务执行都写入一条记录，**让清理结果可观测**（v5.12.0 核心目标：解决"以为清理在跑实际从未生效"的问题）。

### 三、关键代码位置

| 模块 | 文件 | 关键函数/方法 |
|------|------|--------------|
| 配置读取 | [core/helpers.py](../../core/helpers.py) | `get_broadcast_auto_delete_config()` / `safe_delete_broadcast()` / `can_delete_message()` |
| 数据库 | [core/database.py](../../core/database.py) | 表创建 SQL + `_REPO_METHOD_MAP` 委托 |
| Repo 方法 | [core/db_repos/tracking_repo.py](../../core/db_repos/tracking_repo.py) | `track_broadcast / get_last_broadcast / delete_broadcast / cleanup_old_broadcasts / log_orphan_cleanup / get_last_orphan_cleanup / get_orphan_cleanup_history / get_orphan_stats` |
| 定时清理 | [tasks/maintenance/burn_orphan_task.py](../../tasks/maintenance/burn_orphan_task.py) | `BurnOrphanTask`（每6小时，`ORPHAN_CLEANUP_ENABLED` 开关）；[modules/auto_tasks.py](../../modules/auto_tasks.py) `_job_burn_orphan()` 为 legacy 保留 |
| 实时清理 | [modules/points_enhanced.py](../../modules/points_enhanced.py) | `check_level_up()` 30S 删除 |
| API 端点 | [dashboard/api/orphan_api.py](../../dashboard/api/orphan_api.py) | `/api/orphan/stats` / `/api/orphan/cleanup-history` / `/api/orphan/force-clean` |
| 验证脚本 | [scripts/verify_orphan_cleanup.py](../../scripts/verify_orphan_cleanup.py) | 端到端验证 |

### 四、配置项

```json
{
  "ORPHAN_CLEANUP_ENABLED": true,     // 孤儿清理独立开关（v5.12.4 起，默认 true，不再依赖 ENABLE_MESSAGE_DELETION）
  "BROADCAST_AUTO_DELETE": {
    "orphan_seconds": 30,             // 孤儿消息多少秒后删除（0=不删）
    "greeting_chain_delete": true     // 早安/午安/晚安是否发新删旧
  },
  "ENABLE_MESSAGE_DELETION": true     // 全局消息删除开关（与孤儿清理解耦）
}
```

**开关联动**（v5.12.4 起孤儿清理独立于全局删除开关）：
- `ORPHAN_CLEANUP_ENABLED=true` → 真删除（超时 30 分钟孤儿）
- `ORPHAN_CLEANUP_ENABLED=false` → 不删消息、保留追踪记录，但**每 24h 私聊管理员告警孤儿堆积数**（`_handle_orphan_disabled_alert`）
- `ENABLE_MESSAGE_DELETION` 为全局消息删除开关，与孤儿清理解耦

### 五、调用链

#### 5.1 升级播报（30S 删除）

```
用户获得积分
  ↓
message_dispatcher.check_level_up()
  ↓
points_enhanced.check_level_up(bot, chat_id, uid, ...)
  ↓
bot.send_message(...) → 拿到 message_id
  ↓
helpers.get_broadcast_auto_delete_config() 检查配置
  ↓
_schedule_orphan_delete(bot, chat_id, msg_id, 30, "level_up")
  ↓
threading.Timer(30, delete).start()  // 30S 后执行
  ↓
bot.delete_message(chat_id, msg_id)
  ↓
db.delete_broadcast(chat_id, "level_up")
```

#### 5.2 早安/午安/晚安（链式互删）

```
scheduler 触发 _job_send_morning_greeting
  ↓
send_greeting(rm, chat_id, "早安~", "greeting")  // tasks.support.common.send_greeting（问候链式互删现由 greeting_task 调用）
  ↓
db.get_last_broadcast(chat_id, "greeting")  // 查上一条
  ↓
bot.delete_message(chat_id, last_msg_id)  // 删旧的
  ↓
db.delete_broadcast(chat_id, "greeting")
  ↓
bot.send_message(chat_id, "早安~")  // 发新的
  ↓
db.track_broadcast(chat_id, "greeting", new_msg_id)  // 追踪
```

#### 5.3 24h 超时孤儿清理（兜底）

```
task_scheduler 每 6 小时触发 BurnOrphanTask（task_id=burn_orphan）
  ↓
db.get_orphan_messages()  // 查 30 分钟超时（v5.12.4 窗口由 86400 缩至 1800）
  ↓
can_orphan_cleanup(config) 检查（ORPHAN_CLEANUP_ENABLED，默认 true）
  ↓ (true)
bot.delete_message(...)  // 逐条删除
  ↓
db.delete_bot_message_records(...) / db.delete_tracked(...)
  ↓
db.log_orphan_cleanup(found, deleted, skipped, ...)  // 写日志
  ↓ (false 即 ORPHAN_CLEANUP_ENABLED 关闭)
db.log_orphan_cleanup(orphan_count, 0, 0, "ORPHAN_CLEANUP_ENABLED=False", "scheduled")
+ 24h 一次管理员私聊告警（_handle_orphan_disabled_alert）
```

### 六、API 端点

#### 6.1 `GET /api/orphan/stats` — 孤儿状态一站式查询

**返回示例**：
```json
{
  "ok": true,
  "data": {
    "tracked_count": 5,
    "bot_msg_count": 4,
    "unreplied_count": 1,
    "orphan_24h_count": 0,
    "enable_deletion": true,
    "last_cleanup": {
      "id": 12,
      "run_at": 1748836200,
      "run_at_str": "2026-06-02 11:30:00",
      "found_count": 0,
      "deleted_count": 0,
      "skipped_count": 0,
      "error": null,
      "trigger": "scheduled"
    }
  }
}
```

#### 6.2 `GET /api/orphan/cleanup-history?limit=20` — 最近清理历史

返回最近 N 条 `orphan_cleanup_log` 记录。

#### 6.3 `POST /api/orphan/force-clean` — 手动触发清理

写入一条 `trigger=force` 的日志，Bot 进程下次自动执行时清理。

### 七、端到端验证

```bash
# 1. 状态查看
python scripts/verify_orphan_cleanup.py

# 2. dry-run（不真删，只列出待删孤儿）
python scripts/verify_orphan_cleanup.py --dry-run

# 3. force-clean（手动触发一次清理）
python scripts/verify_orphan_cleanup.py --force-clean

# 4. Dashboard 端点
curl -u admin:password http://localhost:6616/api/orphan/stats
```

### 八、历史坑（病历本摘要）

| 版本 | 现象 | 根因 | 修复 |
|------|------|------|------|
| v5.7.3 | 阅后即焚从未生效 | `try/except: pass` 吞错 | 改用 `logger.error` |
| v5.11.0 | `track_bot_message` 抛 AttributeError | 未注册到 `_REPO_METHOD_MAP` | 注册 `'track_bot_message': 'tracking'` |
| v5.12.0 | 清理从未生效且无任何告警 | 缺可观测性 | 新增 `orphan_cleanup_log` 表 + `/api/orphan/stats` |

## 引用

- `AGENTS.md` 类别1（沉默失败 8 大反模式）→ 根目录 `AGENTS.md` 搜 `类别1`
- `AGENTS.md` 类别6（关键路径 5 条铁律）→ 根目录 `AGENTS.md` 搜 `类别6`
- [vps-deploy-trap.md](vps-deploy-trap.md) — VPS 部署陷阱
- [config-reload.md](config-reload.md) — 配置热重载机制

## 更新历史

- 2026-06-02 (v5.12.0) — 首次创建，记录孤儿消息自动清理完整方案
- 2026-08-05 (v5.38.x) — 修正机制描述：定时兜底迁移至 `tasks/maintenance/burn_orphan_task.py`（每 6 小时），独立开关 `ORPHAN_CLEANUP_ENABLED`；`_job_burn_orphan` / `modules/auto_tasks.py` 标注为 legacy
