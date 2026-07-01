# Mory小助理 生产日志事件调查报告

> 调查时段：2026-06-25 00:00 ~ 2026-06-28 23:59（实际日志采集到 2026-06-28 03:05 左右）  
> 数据来源：VPS SSH 远程采集，`mory.log` / `journalctl` / SQLite `task_log` 表  
> 报告生成时间：2026-06-28  

---

## 核心结论

1. **定时播报未执行（P0）**：**2026-06-27 的早安、午安问候缺失**，当晚 23:05 的晚安问候成功。根因是任务 `task_key` 未带日期后缀导致数据库 `claim_task` 冲突/重复执行拦截，叠加 6-27 当天多次服务重启，任务未能在正确时间被调度。21:31 重启后版本已使用 `greeting_evening_2026-06-27` 这类日期后缀 key，当晚任务成功写入 `task_log`。
2. **图片相关问题**：**在 4 天日志中未发现** `send_photo` / `send_rich` / `Bad Gateway` / `Conflict` / 广告图片识别等异常。广告检测模块启动检查正常。图片/富文本链路在该时段没有触发或未产生错误日志。
3. **AI 模型全部失败**：**2026-06-28 03:01 左右发生“所有模型均失败”**。模型切换链：qwen3.6-plus → glm-5.1 → kimi-k2.6（403 免费额度耗尽被拉黑）→ qwen3.5-plus → qwen3.6-27b → qwen3.6-plus，全部超时或失败。此前 6-26 已批量拉黑过期 `qwen3.5-omni-*` 模型，进一步压缩了可用池。
4. **备份目录为空告警**：**当前备份目录非空**。`/home/ubuntu/mory_assistant/backup` 有到 2026-06-28 03:15 的每小时/每日备份，`backups` 目录有到 6-27 的配置备份，`daily_backup` 任务在 6-28 03:00 执行成功。告警可能是误报或告警脚本检查的路径/时刻与真实备份不一致。

---

## 1. 定时播报任务未执行

### 关键日志

`task_log` 表 2026-06-25 ~ 2026-06-28 的部分记录：

```text
('greeting_morning', '2026-06-25', 1782345900.0033538)
('broadcast_morning_nudge', '2026-06-25', 1782352800.0018106)
('greeting_afternoon', '2026-06-25', 1782362100.0026603)
...
('greeting_morning', '2026-06-26', 1782432300.002784)
('broadcast_morning_nudge', '2026-06-26', 1782439200.0020454)
('greeting_afternoon', '2026-06-26', 1782448500.0022812)
...
('scheduled_broadcast_morning_nudge_-1003004701688_2026-06-27', '2026-06-27', 1782563514.2383685)
('scheduled_broadcast_night_whisper_-1003004701688_2026-06-27', '2026-06-27', 1782570600.0057695)
('greeting_evening_2026-06-27', '2026-06-27', 1782572700.0035803)
```

6-27 当天 **没有** `greeting_morning` 与 `greeting_afternoon` 记录，只有晚间任务。

`claim_task` 关键片段：

```text
{"event": "📋 [DB] claim_task(greeting_morning, 2026-06-27) rowcount=0 result=False"}
{"event": "📋 [DB] claim_task(greeting_afternoon, 2026-06-27) rowcount=0 result=False"}
{"event": "📋 [DB] is_task_executed_today(greeting_morning, 2026-06-27) = False"}
{"event": "📋 [DB] claim_task(greeting_evening_2026-06-27, 2026-06-27) rowcount=0 result=False"}
```

6-27 多次服务重启（仅注册了 `check_expired_redpackets`，说明重启时任务注册不完整）：

```text
2026-06-27 02:52:10,526 [INFO] apscheduler.scheduler: Added job "_job_check_expired_redpackets" to job store "default"
2026-06-27 02:52:10,529 [INFO] auto_tasks:   - check_expired_redpackets     cron[minute='35']                                            → _job_check_expired_redpackets
...
2026-06-27 20:25:10,266 [INFO] apscheduler.scheduler: Added job "_job_check_expired_redpackets" to job store "default"
2026-06-27 21:31:08,683 [INFO] apscheduler.scheduler: Added job "_job_check_expired_redpackets" to job store "default"
```

### 根因推断

- **直接原因**：6-27 08:05 / 12:35 的任务触发后，`claim_task` 返回 `rowcount=0 result=False`，任务被数据库去重/锁机制拦截，没有进入执行逻辑。
- **深层原因**：`task_key` 缺少日期后缀，跨天/跨重启时与历史 `task_log` 记录产生唯一键冲突（或重复执行判断），导致新一天的任务无法 claim。21:31 重启后的版本对 `greeting_evening` 使用了 `greeting_evening_2026-06-27`，当晚成功执行。
- **诱发因素**：6-27 当天 02:52、20:25、21:31 的多次重启使 APScheduler 任务注册状态不稳定，进一步导致上午/下午任务未被正常调度。

### 涉及文件/函数/配置

- `modules/auto_tasks.py`：`_job_greeting_morning` / `_job_greeting_afternoon` / `_job_scheduled_broadcast`
- `core/database.py`：`task_log` 表、`claim_task` / `is_task_executed_today`
- `modules/task_transaction.py`：`TaskTransactionManager`
- 配置：`MANAGED_GROUPS`、`GREETING_*` 开关

### 修复建议

1. 确保所有定时任务的 `task_key` 都带 `_YYYY-MM-DD` 或 `_{chat_id}_YYYY-MM-DD` 后缀。
2. 检查 `scheduled_broadcast` 是否同样对每条群、每一天使用独立 key。
3. 部署前运行 `python scripts/verify_db_methods.py`，确认 `_REPO_METHOD_MAP` 无漏注册。
4. 增加 APScheduler `MISSED` 事件监控，任务miss时立即告警。

---

## 2. 图片 / 广告 / Telegram API 相关问题

### 关键日志

在 `/home/ubuntu/mory_assistant/logs/` 中针对图片、富文本、Telegram 错误的远程搜索**无任何命中**：

```bash
grep -REi 'send_photo|send_rich|send_animation|send_media|Bad Gateway|Conflict|terminated by other getUpdates|web_page_preview|caption' /home/ubuntu/mory_assistant/logs/
grep -REi 'ad_detector|ad_detection|广告检测|含图片|has_photo|is_ad|ad_text' /home/ubuntu/mory_assistant/logs/
```

广告检测模块启动日志正常：

```text
2026-06-25 21:55:35,609 [INFO] ad_detector: [AD] 启动检查：无待处理的封禁任务
```

### 根因推断

- 在调查窗口内，**没有证据**表明图片发送失败、富文本发送失败、Telegram API 图片相关错误，或广告检测对含图片消息识别异常。
- 可能原因：6-27 上午/下午播报被跳过，因此富文本/图片发送路径根本没有被触发；或该功能在配置中被关闭。

### 涉及文件/函数/配置

- `modules/ad_enforcement.py`：`enforce_ad_user()`
- 广告检测相关模块（`ad_detector` 等）
- `modules/broadcast_rich_format.py` / 相关 `send_photo` / `send_message` 调用
- Telegram Bot API 调用层

### 修复建议

1. 在媒体发送前后增加结构化日志（`send_photo` / `send_rich` 的 chat_id、message_id、成功/失败状态）。
2. 手动触发一条带图片的富文本播报，验证 CDN、Telegram API、文件路径均正常。
3. 确认 `config.json` 中富文本/图片播报开关已开启。

---

## 3. AI 模型全部失败（2026-06-28 03:01）

### 关键日志

```text
{"event": "⚠️ 超时(qwen3.6-plus-2026-04-02)，立即切换模型"}
{"event": "🔄 [llm_standard] 模型切换 → glm-5.1"}
{"event": "⚠️ 超时(glm-5.1)，立即切换模型"}
{"event": "🔄 [llm_standard] 模型切换 → kimi-k2.6"}
{"event": "⚠️ 模型kimi-k2.6额度/权限异常(403)，自动拉黑。响应: {\"error\":{\"message\":\"The free quota has been exhausted..."}
{"event": "🚫 模型拉黑：kimi-k2.6（原因：HTTP 403），不再使用"}
{"event": "🔄 [llm_standard] 模型切换 → qwen3.5-plus-2026-04-20"}
...
{"event": "⚠️ 超时(qwen3.5-plus-2026-04-20)，立即切换模型"}
{"event": "🔄 [llm_standard] 模型切换 → qwen3.6-27b"}
{"event": "⚠️ 超时(qwen3.6-27b)，立即切换模型"}
{"event": "🔄 [llm_standard] 模型切换 → qwen3.6-plus-2026-04-02"}
{"event": "❌ AI引擎：所有模型均失败"}
{"event": "[FaultReporter] 🚨 AI模型全部失败: 所有模型均失败，用户消息无法回复"}
```

同一时段 `daily_backup` / `quality_eval` 任务执行，质量评估耗时 101.1 秒，评估 0 条：

```text
{"event": "Running job \"_job_daily_backup (trigger: cron[hour='3', minute='0'], next run at: 2026-06-29 03:00:00 CST)\" (scheduled at 2026-06-28 03:00:00+08:00)"}
{"event": "Job \"_job_daily_backup ...\" executed successfully"}
...
{"event": "📊 质量评估完成: 评估 0 条，跳过 1 条，耗时 101.1s | 自然度=0.00 相关性=0.00 人格=0.00"}
{"event": "📊 内容质量评估任务完成: {'total': 1, 'sampled': 1, 'evaluated': 0, 'skipped': 1, 'elapsed_sec': 101.1, ...}"}
```

6-26 00:55 批量拉黑过期模型，进一步减少可用模型池：

```text
2026-06-26 00:55:36,429 [WARNING] ai_engine: 🚫 模型拉黑：qwen3.5-omni-plus-realtime（原因：已过期 2026-06-23），不再使用
2026-06-26 00:55:36,429 [INFO] ai_engine: ⏰ 模型 qwen3.5-omni-flash 已过期 (2026-06-23)，将跳过
...
```

### 根因推断

- **直接原因**：`llm_standard` 池内模型逐一超时或被拉黑，`kimi-k2.6` 返回 **HTTP 403 “free quota exhausted”**，最终没有任何可用模型。
- **次要原因**：6-26 启动时已将多个 `qwen3.5-omni-*` 过期模型自动拉黑，可用模型池本就被压缩。
- **触发场景**：03:00 的 `quality_eval` / `daily_backup` 等任务集中运行，产生 AI 调用高峰，模型响应慢/超时加剧。

### 涉及文件/函数/配置

- `core/model_router.py`（或 `modules/ai_engine.py`）模型切换与拉黑逻辑
- `modules/http_client.py`：HTTP 超时、重试
- `config.json`：`MODEL_POOLS` / `llm_standard` 模型池配置

### 修复建议

1. 立即刷新 `MODEL_POOLS`，移除/替换已过期和免费额度耗尽的模型（`kimi-k2.6`、`qwen3.5-omni-*` 等）。
2. 为模型调用增加额度监控，403 时区分“额度耗尽”与“权限错误”，避免一次性拉黑全部可用模型。
3. 调整超时阈值和重试策略，避免集中任务导致连锁超时。
4. 保留至少一个“fallback”模型，在标准池全灭时降级使用。

---

## 4. 备份目录为空告警

### 关键日志

当前目录列表（2026-06-28 调查时）：

```text
$ ls -la /home/ubuntu/mory_assistant/backup | head -12
total 64540
drwxr-xr-x  2 ubuntu ubuntu   12288 Jun 28 04:15 .
-rw-r--r--  1 ubuntu ubuntu 2101248 Jun 28 03:15 mory_backup_20260628_0300.db
-rw-r--r--  1 ubuntu ubuntu 2101248 Jun 28 02:15 mory_backup_20260628_0200.db
-rw-r--r--  1 ubuntu ubuntu 2101248 Jun 28 01:15 mory_backup_20260628_0100.db
-rw-r--r--  1 ubuntu ubuntu 2101248 Jun 28 00:15 mory_backup_20260628_0000.db
-rw-r--r--  1 ubuntu ubuntu 2093056 Jun 27 23:15 mory_backup_20260627_2300.db
...

$ ls -la /home/ubuntu/mory_assistant/backups | head -12
total 4268
drwxrwxr-x  2 ubuntu ubuntu  4096 Jun 27 02:48 .
-rw-r--r--  1 root   root   53321 Jun 27 02:48 config_20260627_024800.json
...
```

`daily_backup` 任务执行成功：

```text
{"event": "Running job \"_job_daily_backup (trigger: cron[hour='3', minute='0'], next run at: 2026-06-29 03:00:00 CST)\" (scheduled at 2026-06-28 03:00:00+08:00)"}
{"event": "Job \"_job_daily_backup ...\" executed successfully"}
```

### 根因推断

- **当前备份链路正常**，不存在“备份目录为空”。
- 告警可能原因：
  1. 告警脚本检查的路径不是 `/home/ubuntu/mory_assistant/backup` 或 `backups`。
  2. 告警发生在 6-25 22:10 左右 `config.json` 损坏、服务反复重启的窗口，备份任务当时未正常写入。
  3. 告警规则仅检查某个特定子目录/文件，而真实备份写到其他目录。

### 涉及文件/函数/配置

- `modules/auto_tasks.py`：`_job_backup` / `_job_daily_backup`
- 系统 cron：`/opt/tokenpass/scripts/backup_db.sh`
- 告警规则/监控脚本

### 修复建议

1. 核对告警规则中检查的备份路径，确保与真实输出目录一致（`backup` vs `backups`）。
2. 在告警逻辑中增加“备份文件数量 + 最新文件时间 + 文件大小”三维判断，避免单点误报。
3. 检查备份脚本权限（`backups` 目录部分文件为 `root:root`，可能由 cron 写入，确保写入持续成功）。

---

## 额外发现

1. **config.json 损坏导致反复重启（6-25 22:10 ~ 22:13）**

   ```text
   2026-06-25 22:10:50,623 [CRITICAL] bot_initializer: ❌ config.json 格式损坏：Expecting value: line 540 column 19 (char 14992)
   2026-06-25 22:10:50,623 [CRITICAL] bot_initializer:    → 尝试加载内置最小默认配置...
   ```

   这会导致服务启动时回退到最小默认配置，可能丢失自定义播报内容、关键词、模型池等配置，与上述定时任务和 AI 失败存在关联。

2. **`WriteQueueConnectionProxy` 不支持上下文管理器**

   ```text
   {"event": "投票踢人过期检查异常：'WriteQueueConnectionProxy' object does not support the context manager protocol"}
   ```

   该异常在 `vote_kick_check` 中重复出现，说明 `core/db_connection_proxy.py` 与部分使用 `with self.conn:` 的代码不兼容，需要统一封装。

---

## 建议处理优先级

| 优先级 | 事项 |
|--------|------|
| P0 | 全量检查并统一所有定时任务的日期后缀 `task_key`，确认 `_REPO_METHOD_MAP` 注册完整。 |
| P0 | 刷新 `MODEL_POOLS`，移除过期/额度耗尽模型，恢复 AI 回复能力。 |
| P1 | 修复 `config.json` 损坏问题，避免服务反复回退到默认配置。 |
| P1 | 修复 `WriteQueueConnectionProxy` 上下文管理器兼容性。 |
| P2 | 为图片/富文本发送增加日志，手动验证一次完整链路。 |
| P2 | 校准备份告警路径与规则，减少误报。 |
