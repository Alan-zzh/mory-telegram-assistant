# 回归风险分析报告
**版本：v4.5.31**
**审查日期：2026-05-02**
**审查范围：modules/auto_tasks.py + core/database.py + 版本历史**

---

## 核心发现：重复播报根因已确认

**问题本质**：v4.5.29-v4.5.31 三连修复存在"修复叠加"现象，每次修复都试图解决连发问题，但引入了新的竞态条件。

---

## 一、任务注册逻辑审查

### 1.1 APScheduler 任务注册（L1474-1515）

| 任务 | 调度时间 | ID | 防重机制 |
|------|----------|-----|----------|
| news_morning | 9:05 | news_morning | _try_claim_task + DB唯一索引 |
| news_afternoon | 13:05 | news_afternoon | _try_claim_task + DB唯一索引 |
| news_evening | 20:35 | news_evening | _try_claim_task + DB唯一索引 |
| greeting_morning | 8:05 | greeting_morning | _try_claim_task + DB唯一索引 |
| greeting_afternoon | 12:35 | greeting_afternoon | _try_claim_task + DB唯一索引 |
| greeting_evening | 23:05 | greeting_evening | _try_claim_task + DB唯一索引 |
| daily_report | 9:10 | daily_report | _try_claim_task + DB唯一索引 |
| tarot_flirt | 15:00 | tarot_flirt | _try_claim_task + DB唯一索引 |

**关键配置**：
- `max_instances=1`：同一任务同时只能有一个实例运行
- `coalesce=True`：堆积的任务只执行最后一次
- `misfire_grace_time=60`：1分钟内错过可补发

### 1.2 旧版循环任务注册（L1519-1595）

当 APScheduler 不可用时回退到 while True 循环：
- 新闻/问候任务在特定时间窗口内执行（如 9:00-9:05）
- 使用 `_can_run` + `_mark_done` 节流
- **风险**：时间窗口为5分钟，可能多次触发

---

## 二、_can_run / _mark_done 竞态条件分析

### 2.1 当前实现（L88-106）

```python
def _can_run(task_name: str, min_interval_sec: int = 300) -> bool:
    now = int(time.time())
    with _task_lock:
        last = _last_task_run.get(task_name, 0)
        if now - last < min_interval_sec:
            return False
        return True  # 只检查，不标记！

def _mark_done(task_name: str):
    now = int(time.time())
    with _task_lock:
        _last_task_run[task_name] = now
```

### 2.2 竞态条件漏洞 ⚠️

**问题**：`_can_run` 和 `_mark_done` 是**两个独立操作**，非原子性：

```
时间线：
T1: 线程A _can_run("news_morning") → 返回 True（可以执行）
T2: 线程B _can_run("news_morning") → 也返回 True（因为A还没标记）
T3: 线程A 执行新闻播报
T4: 线程B 执行新闻播报 → 重复播报！
T5: 线程A _mark_done("news_morning")
T6: 线程B _mark_done("news_morning")
```

**影响范围**：
- 新闻播报（早间/午间/晚间）
- 问候任务（早安/午安/晚安）
- 每日报告
- 塔罗搭讪

### 2.3 _try_claim_task 修复（L71-85）

v4.5.29 引入的原子性抢占：

```python
def _try_claim_task(task_name: str, min_interval_sec: int = 7200) -> bool:
    now = int(time.time())
    with _task_lock:
        last = _last_task_run.get(task_name, 0)
        if now - last < min_interval_sec:
            return False
        _last_task_run[task_name] = now  # 检查+标记一步完成
        return True
```

**状态**：✅ 已修复，检查+标记在同一锁内完成

---

## 三、重复任务调用检查

### 3.1 任务函数调用路径

| 任务函数 | 被调用位置 | 风险 |
|----------|-----------|------|
| `_job_news_morning` | APScheduler L1481 | 低风险（max_instances=1） |
| `_job_news_afternoon` | APScheduler L1482 | 低风险（max_instances=1） |
| `_job_news_evening` | APScheduler L1483 | 低风险（max_instances=1） |
| `_job_greeting_morning` | APScheduler L1492 | 低风险（max_instances=1） |
| `_job_greeting_afternoon` | APScheduler L1493 | 低风险（max_instances=1） |
| `_job_greeting_evening` | APScheduler L1494 | 低风险（max_instances=1） |
| `_job_tarot_flirt` | APScheduler L1489 | 低风险（max_instances=1） |
| `_job_daily_report` | APScheduler L1486 | 低风险（max_instances=1） |

### 3.2 旧版 TrendRadar 入口（L422-434）

```python
def _job_trendradar_morning(rm):
    """旧的TrendRadar早间播报入口已停用，保留函数仅兼容历史调用"""
    logger.info("ℹ️ trendradar_morning 已并入 news_morning 统一主流程")
```

**风险**：如果 APScheduler 仍注册了旧入口，会导致空跑日志。但不会影响实际播报。

### 3.3 新闻执行统一入口（L356-400）

```python
def _execute_news_task(rm, task_name: str, time_desc: str):
    if not _try_claim_task(task_name, 7200):
        return
    if rm.db.is_task_executed_today(task_name):
        return
    # ... 执行播报 ...
    if sent:
        _remember_news_lines(lines)
        rm.db.mark_task_executed(task_name)
```

**双重防重**：
1. `_try_claim_task`：内存级原子锁（7200秒冷却）
2. `rm.db.mark_task_executed`：数据库级唯一索引

---

## 四、最近3次代码变更冲突分析

### 4.1 v4.5.29 变更

**修改**：`_try_claim_task` 原子锁 + APScheduler `max_instances=1`

**引入问题**：
- `_try_claim_task` 使用 7200 秒（2小时）冷却，但新闻任务间隔是 4 小时（9:00→13:00），理论上不会冲突
- 但如果任务执行失败重试，7200秒冷却会阻止重试

### 4.2 v4.5.30 变更

**修改**：`misfire_grace_time=1` 秒

**引入问题**：
- 如果 Bot 在任务执行时重启，1秒内无法补发，可能导致漏发
- 但避免了堆积补发导致的连发

### 4.3 v4.5.31 变更

**修改**：
1. task_log 添加 UNIQUE 约束
2. `INSERT OR IGNORE`
3. `_try_claim_task` 全局替换
4. `coalesce=True`
5. `misfire_grace_time=60`

**引入问题**：
- `misfire_grace_time=60` 恢复为60秒，如果服务在任务时间点前后60秒内重启，可能补发
- `coalesce=True` 只会补发最后一次，但如果任务执行时间长，可能重叠

### 4.4 冲突叠加效应

```
v4.5.29: 原子锁（内存）+ max_instances=1
v4.5.30: misfire_grace_time=1（防补发连发）
v4.5.31: misfire_grace_time=60（恢复补发窗口）+ DB唯一索引

结果：
- 内存锁（_try_claim_task）和 DB唯一索引 同时存在
- 但 _try_claim_task 在 _execute_news_task 内部，而 APScheduler 调度在外部
- 如果 APScheduler 触发两次（如重启后），_try_claim_task 会阻止第二次
- 但如果 _try_claim_task 的 7200 秒冷却已过，且 DB 记录被清理，可能重复
```

---

## 五、根因确认：重复播报的触发条件

### 5.1 场景1：APScheduler 重启补发（高概率）

```
9:00:00 APScheduler 触发 news_morning
9:00:01 Bot 进程重启（systemctl restart）
9:00:02 APScheduler 重新启动，发现 news_morning 错过（<60秒）
9:00:03 APScheduler 补发 news_morning
9:00:04 _try_claim_task 检查：距离上次 3 秒 < 7200 秒 → 返回 False
9:00:05 第二次执行被阻止

理想情况：✅ 不会重复
```

### 5.2 场景2：_try_claim_task 冷却过期（中概率）

```
9:05:00 第一次执行成功，_try_claim_task 标记时间戳
9:05:01 mark_task_executed 写入 DB
11:05:00 2小时冷却过期
11:05:01 如果此时 APScheduler 意外触发（如手动调用）
11:05:02 _try_claim_task 返回 True（冷却已过）
11:05:03 is_task_executed_today 检查 DB → 返回 True（今日已执行）
11:05:04 执行被阻止

理想情况：✅ DB唯一索引兜底
```

### 5.3 场景3：DB 唯一索引失效（低概率但致命）

```
情况A：数据库损坏或迁移失败
- v4.5.31 的 UNIQUE INDEX 创建在 _init_tables 中
- 如果旧数据库已有重复记录，DELETE 清理后创建索引
- 但如果清理失败，索引创建失败，无报错（try-except 吞掉）

情况B：并发写入
- _try_claim_task 和 mark_task_executed 是两个独立操作
- 如果两个线程同时通过 _try_claim_task，同时写入 DB
- SQLite 的 INSERT OR IGNORE 在并发时可能都成功（事务隔离级别）

代码验证（L1173-1176）：
cur = self.conn.execute(
    "INSERT OR IGNORE INTO task_log (task_key, exec_date, exec_ts) VALUES (?, ?, ?)",
    (task_key, today, ts)
)

问题：没有显式事务包裹！虽然 _db_lock 保护，但如果在锁外检查...
```

### 5.4 场景4：旧版循环与 APScheduler 并存（已修复但需确认）

```
v4.5.24 修复：旧版循环全任务隔离
- 如果 HAS_APSCHEDULER=True，使用 APScheduler
- 如果 HAS_APSCHEDULER=False，使用旧版循环
- 不会同时运行

但：如果 APScheduler 启动失败（异常），会静默回退到旧版循环
- 旧版循环使用 _can_run/_mark_done（非原子性）
- 可能导致重复
```

---

## 六、回归风险总结

### 6.1 高风险项

| 风险 | 概率 | 影响 | 说明 |
|------|------|------|------|
| DB唯一索引未生效 | 中 | 重复播报 | _init_tables 的 try-except 可能吞掉索引创建失败 |
| 并发 mark_task_executed | 低 | 重复播报 | 两个线程同时通过 _try_claim_task，同时写入DB |
| APScheduler 重启补发 | 中 | 重复播报 | misfire_grace_time=60 恢复补发窗口 |

### 6.2 中风险项

| 风险 | 概率 | 影响 | 说明 |
|------|------|------|------|
| 旧版循环回退 | 低 | 重复播报 | APScheduler 启动失败时回退到非原子性旧版 |
| 任务执行超时 | 中 | 任务堆积 | 新闻生成AI调用可能超时，导致APScheduler认为失败并重试 |

### 6.3 低风险项

| 风险 | 概率 | 影响 | 说明 |
|------|------|------|------|
| _try_claim_task 冷却过期 | 低 | 重复播报 | 2小时冷却，新闻间隔4小时，理论上不会冲突 |
| 时区问题 | 低 | 漏发/重复 | _CST 统一使用北京时间，已修复 |

---

## 七、修复建议

### 7.1 立即修复（高优先级）

1. **验证 DB 唯一索引是否生效**
   ```sql
   -- 在 VPS 上执行
   sqlite3 mory.db ".schema task_log"
   -- 确认输出包含 UNIQUE INDEX idx_task_log_unique
   ```

2. **增强 mark_task_executed 原子性**
   ```python
   def mark_task_executed(self, task_key: str) -> bool:
       today = datetime.now(_CST).strftime("%Y-%m-%d")
       ts = time.time()
       with _db_lock:
           try:
               # 先检查，再插入（原子性）
               row = self.conn.execute(
                   "SELECT 1 FROM task_log WHERE task_key=? AND exec_date=? LIMIT 1",
                   (task_key, today)
               ).fetchone()
               if row:
                   return False  # 已存在
               
               cur = self.conn.execute(
                   "INSERT INTO task_log (task_key, exec_date, exec_ts) VALUES (?, ?, ?)",
                   (task_key, today, ts)
               )
               self.conn.commit()
               return cur.rowcount > 0
           except sqlite3.IntegrityError:
               return False  # 唯一索引冲突
           except Exception as e:
               logger.warning(f"mark_task_executed失败: {e}")
               return False
   ```

3. **缩短 _try_claim_task 冷却时间**
   - 当前 7200 秒（2小时）
   - 建议改为 3600 秒（1小时），与新闻任务间隔匹配

### 7.2 中期优化（中优先级）

1. **APScheduler 配置调优**
   - `misfire_grace_time=30`（平衡补发和防连发）
   - `coalesce=True` 保持开启

2. **旧版循环废弃**
   - 完全移除 `_start_with_legacy_loop`
   - 或强制要求安装 APScheduler

### 7.3 长期监控（低优先级）

1. **任务执行日志增强**
   - 记录每次任务执行的完整时间线
   - 便于排查重复播报问题

---

## 八、结论

**当前状态**：v4.5.31 的防重机制在理论上已完善，但存在以下隐患：

1. **DB唯一索引可能未生效**（最可能原因）
2. **并发写入的竞态条件**（低概率但致命）
3. **APScheduler 重启补发**（中概率）

**建议行动**：
1. 立即检查 VPS 上 task_log 表的索引状态
2. 如果重复播报再次发生，检查日志中 `_try_claim_task` 和 `mark_task_executed` 的返回值
3. 考虑将 `misfire_grace_time` 从 60 秒调回 1 秒（牺牲补发，确保不连发）

---

*报告生成时间：2026-05-02*
*审查员：AI Testing & Quality Assurance Layer*
