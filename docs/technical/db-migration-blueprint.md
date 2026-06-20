# 数据库升级时机评估与 Postgres 迁移蓝图

> **被 [AGENTS.md](../../AGENTS.md) 索引引用 · 适用版本：v5.24.0+（阶段3-D 评估文档）**
> **最后更新**：2026-06-17（v5.24.0 阶段3-D 创建）
> **文档性质**：决策依据文档，非实施计划。任一阶段动手前需重新评估并经人工确认。

## 概述

Mory 小助理当前数据库为 SQLite（WAL + busy_timeout=30s + 单线程写入队列 `core/write_queue.py` + 连接代理全量化 `core/db_connection_proxy.py`），部署在 VPS 单机（2C4G，ubuntu@22.04）。AGENTS.md 第 4 章明确规定：**不排斥 Postgres/MySQL，经评估可替换，前提是迁移脚本幂等 + 数据零丢失 + 回滚方案就绪**。

本文档定义：
1. **何时**应该启动迁移评估（量化触发指标）
2. 迁移前**必须完成**的评估清单
3. **如何**无缝迁移（Zero-Loss Blueprint，5 阶段 + 回滚）
4. Schema 差异映射表（SQLite → PostgreSQL）
5. 风险与缓解策略

**当前结论**：v5.24.0 现状未触发任一迁移指标，SQLite 仍是单机 VPS 的最优解。本文档为前瞻性蓝图，**不构成迁移指令**。

## 适用场景

- 评估"是否该换数据库"时，按"迁移触发指标"逐项核对
- 业务量增长到需要多实例负载均衡时，按"无缝迁移方案"分阶段执行
- 新人接手时建立"SQLite 不是终点，Postgres 是预设演进方向"的认知
- 写迁移脚本时对照"Schema 差异映射表"避免类型踩坑

## 关键内容

### 一、迁移触发指标（何时迁往 PostgreSQL）

> 任一指标**持续命中**即应启动迁移评估；同时命中 2 项以上应**立即启动**评估。
> "持续"定义：连续 7 天中至少 5 天出现，且非一次性活动（如群发播报）造成。

| 序号 | 指标 | 阈值 | 数据来源 | 命中含义 |
|:----:|------|------|----------|----------|
| T1 | 单机持续写入并发峰值 | Writes/sec > 80 | `write_queue._stats["total"]` 差值/秒 | WriteQueue Worker 串行执行已接近吞吐上限，写入延迟将显著上升 |
| T2 | WriteQueue 积压任务数 | `qsize` 经常性 > 200 且持续 ≥ 5 秒 | `write_queue._queue.qsize()` 采样 | 队列消费速度跟不上生产速度，背压机制（v5.25.0 阶段1-B）开始丢非核心写入 |
| T3 | 业务架构扩展 | 决定扩展为多实例负载均衡部署 | 架构决策 | SQLite 单文件无法跨进程/跨机器共享，必须迁移到独立 DB 进程 |
| T4 | 数据库文件大小 | `mory.db` > 1 GB | `ls -lh /home/ubuntu/mory_assistant/mory.db` | SQLite 大文件下 VACUUM/checkpoint 耗时剧增，启动慢，备份难 |
| T5 | 并发读连接数 | 同时活跃读连接 > 50 | `PRAGMA wal_checkpoint` + 连接计数 | SQLite 读并发虽优于写，但连接数过高仍会触发 lock contention |

**指标采集建议**：
- T1/T2：在 `core/monitoring.py` 增加 `write_queue.qsize` 与 `writes/sec` 采样，每 30 秒落盘到 `scheduler_metrics` 或独立 `db_health_metrics` 表
- T4：crontab 每日记录 `mory.db` 大小到 `AI_DEBUG_HISTORY.md` 或独立监控
- T5：Dashboard `/api/health` 增加当前连接数返回字段

**重要说明**：
- T1/T2 的阈值基于 VPS 2C4G + 单线程 Worker 的实测推算，硬件升级后阈值需重新校准
- T3 是**架构驱动**而非性能驱动，即使 T1/T2/T4/T5 全部未命中，只要业务决定多实例部署就必须迁移
- 单次活动（如群发播报峰值）造成的瞬时 T1/T2 命中**不计入**"持续命中"

### 二、迁移前评估清单

> 启动迁移前**必须全部完成**，缺一项不得进入阶段1。

#### 2.1 压测数据确认（Locust 三档梯度结果）

基于 `tests/perf/locustfile.py` 执行三档梯度压测，确认当前 SQLite 架构的真实瓶颈：

| 档位 | 并发用户 | 加速率 | 运行时长 | 必须采集的指标 |
|------|----------|--------|----------|----------------|
| 轻载 | 20 | 5/s | 60s | P50/P95/P99 响应时间、Writes/sec、qsize 峰值 |
| 中载 | 100 | 10/s | 60s | 同上 + 错误率、`database is locked` 出现次数 |
| 极限 | 300 | 20/s | 60s | 同上 + WriteQueue 丢弃数、背压触发次数 |

**判定标准**：
- 若极限档 Writes/sec 仍 < 80 且 qsize < 200 → **不迁移**，SQLite 足够
- 若中载档已出现 P95 > 2s 或错误率 > 1% → **迁移收益明确**，进入后续评估
- 压测仅本地开发环境执行，**禁止对生产 VPS 压测**

#### 2.2 业务量增长趋势分析

- 近 30/60/90 天的日活用户数、日消息量、日写入量趋势（从 `users`/`message_snapshots`/`reply_tracking` 表统计）
- 预测 6 个月内是否会触发 T1/T4 任一指标
- 是否有业务计划（如新增群、接入新 Bot、开放 API）会导致写入量阶跃式增长

#### 2.3 VPS 资源升级 vs 迁移成本对比

| 维度 | 升级 VPS（4C8G/8C16G） | 迁移 Postgres |
|------|------------------------|---------------|
| 一次性成本 | 低（改套餐） | 中高（脚本+测试+双写+切换） |
| 持续成本 | 月租上涨 | 月租上涨 + 运维复杂度 |
| 解决 T1/T2 | 缓解（Worker 更快） | 根治（多写并发） |
| 解决 T3（多实例） | ❌ 无法解决 | ✅ 根治 |
| 解决 T4（大文件） | ❌ 延缓不根治 | ✅ 根治 |
| 运维难度 | 不变 | 上升（需 Postgres 运维能力） |
| 回滚难度 | 极易（降套餐） | 中等（见阶段5回滚方案） |

**决策原则**：仅 T1/T2 命中且 T3/T4 未命中 → 优先升级 VPS；T3 或 T4 命中 → 必须迁移。

#### 2.4 团队 Postgres 运维能力评估

- 是否有 Postgres 部署/备份/监控/排错经验
- 是否熟悉 Postgres 连接池（pgbouncer）、复制（streaming replication）、扩展（pg_stat_statements）
- 是否有 7x24 oncall 能力处理 Postgres 故障
- 若团队无 Postgres 经验 → 迁移前必须完成培训 + 演练，否则**推迟迁移**或引入外部运维

### 三、无缝迁移方案（Zero-Loss Blueprint）

> 核心原则：**任一阶段异常可一键回滚到 SQLite，数据零丢失**。
> 每个阶段完成后需观察 ≥ 24 小时无异常方可进入下一阶段。

#### 阶段总览

```
阶段1 脚本幂等化  →  阶段2 双写测试  →  阶段3 读流量切换  →  阶段4 写流量切换  →  阶段5 下线 SQLite
   (离线)              (Shadow Write)      (读切 PG)           (写切 PG)           (保留7天回滚)
   风险：低             风险：低            风险：中            风险：高            风险：低
   可回滚：N/A          可回滚：关闭双写     可回滚：读切回SQLite 可回滚：写切回SQLite 可回滚：重启SQLite
```

#### 阶段1：脚本幂等化（离线，风险低）

**目标**：编写可重复执行的迁移脚本，将 SQLite 全量数据导入 Postgres，多次执行结果一致。

**实现要点**：
- Python 脚本读取 SQLite schema（`SELECT sql FROM sqlite_master WHERE type='table'`）+ 数据（`SELECT * FROM <table>`）
- 按 Schema 差异映射表（见第四节）转换类型后建表
- 数据导入用 BULK INSERT（`psycopg2.extras.execute_values`），批量 1000 行/次
- 幂等保证：所有 INSERT 使用 `ON CONFLICT DO NOTHING`（基于主键/唯一约束）
- 表级事务：每张表一个事务，失败回滚该表但不影响其他表
- 进度可观测：每张表导入完成后打印 `[表名] rows= N, duration= Xs`
- 校验：导入后对比 SQLite 与 Postgres 各表 `COUNT(*)`，不一致则报错终止

**验收标准**：
- 脚本可连续执行 3 次无报错，最终数据行数一致
- 所有表 `COUNT(*)` 与 SQLite 源一致
- 抽样 100 行关键字段值与 SQLite 一致

#### 阶段2：双写测试（Shadow Write，风险低）

**目标**：生产环境写操作同时写 SQLite（主）+ Postgres（影），Postgres 写异常不阻断主流程。

**实现要点**：
- 修改 `core/db_connection_proxy.py` 的 `WriteQueueConnectionProxy`，在 `execute` 拦截写操作时：
  - 主路径：投递到 SQLite WriteQueue（现有逻辑不变）
  - 影路径：异步投递到 Postgres 写队列（独立线程，异常仅记日志）
- Postgres 连接独立配置（`.env` 新增 `PG_HOST`/`PG_PORT`/`PG_DB`/`PG_USER`/`PG_PASSWORD`）
- 影写入失败不影响 SQLite 主流程，仅 `logger.warning` + 计数
- 配置开关：`config.get('PG_SHADOW_WRITE_ENABLED', False)`，默认关闭

**验收标准**：
- 双写运行 ≥ 7 天，Postgres 影写入成功率 > 99.9%
- 每日定时校验 SQLite 与 Postgres 各表 `COUNT(*)` 差值 < 10（允许双写窗口内的时间差）
- 无主流程因双写导致的延迟或错误

#### 阶段3：读流量切换（风险中）

**目标**：读请求切向 Postgres，对比数据一致性。

**实现要点**：
- `core/db_connection_proxy.py` 读操作（SELECT/PRAGMA）增加路由：`config.get('PG_READ_ENABLED', False)` 开启后读走 Postgres
- 双读对比模式：同时读 SQLite + Postgres，对比结果集，不一致记 `logger.error` + 告警
- 按表灰度：先切低频读表（如 `puzzle_scores`/`wake_up`），再切高频读表（如 `users`/`user_profiles`）
- 读切换期间双写（阶段2）持续运行，保证 Postgres 数据实时

**验收标准**：
- 全表读切 Postgres 运行 ≥ 3 天，双读对比不一致率 < 0.01%
- 读延迟 P95 不高于 SQLite 时期 1.5 倍
- 无业务功能因读切换异常

#### 阶段4：写流量切换（风险高）

**目标**：写请求切向 Postgres，SQLite 降级为只读备份。

**实现要点**：
- `WriteQueueConnectionProxy` 写操作主路径切到 Postgres，SQLite 改为影写（与阶段2 反向）
- 切换前执行一次阶段1 全量同步（补齐阶段2-3 期间可能的数据差异）
- 切换后立即校验关键表（`user_profiles`/`funnel_state`/`conversion_events`）行数与最近写入
- 保留 SQLite 双写 ≥ 24 小时作为热备

**验收标准**：
- 写切 Postgres 运行 ≥ 24 小时无异常
- 关键表写入成功率 100%
- WriteQueue qsize 与 Writes/sec 在正常范围

#### 阶段5：下线 SQLite（风险低）

**目标**：关闭双写，SQLite 保留 7 天作为回滚备份后归档。

**实现要点**：
- 关闭 `PG_SHADOW_WRITE_ENABLED`，停止 SQLite 写入
- SQLite 文件保留 7 天（不删除），期间可作为紧急回滚数据源
- 7 天后归档 `mory.db` 到 `backup/mory_db_final_<date>.db`，停止 SQLite 进程
- 更新 `AGENTS.md` 第 4 章数据库章节，标注已迁移至 Postgres

**验收标准**：
- Postgres 单写运行 ≥ 7 天无异常
- 备份归档完成
- 文档同步更新

#### 回滚方案（任一阶段异常）

| 阶段 | 回滚动作 | 数据损失 |
|------|----------|----------|
| 阶段1 | N/A（离线脚本，不影响生产） | 无 |
| 阶段2 | 关闭 `PG_SHADOW_WRITE_ENABLED` | 无（SQLite 为主） |
| 阶段3 | 关闭 `PG_READ_ENABLED`，读切回 SQLite | 无（SQLite 持续双写） |
| 阶段4 | 关闭 `PG_WRITE_ENABLED`，写切回 SQLite | 无（阶段4 期间 SQLite 持续影写） |
| 阶段5 | 7 天内：重启 SQLite 双写 + 反向同步 Postgres→SQLite；7 天后：从归档恢复 | 无（7 天内可回滚） |

**回滚触发条件**（任一即触发）：
- Postgres 写入错误率 > 0.1%
- 数据一致性校验失败（行数差值 > 100 且无法解释）
- 业务功能大面积异常且定位到 DB 层

### 四、Schema 差异映射表（SQLite → PostgreSQL）

| SQLite 类型/特性 | PostgreSQL 对应 | 转换说明 | 注意事项 |
|------------------|-----------------|----------|----------|
| `INTEGER` | `BIGINT` | 整型统一用 BIGINT 避免溢出 | SQLite INTEGER 是动态宽度，PG 需明确选 INT/BIGINT |
| `TEXT` | `TEXT` | 直接映射 | 无差异 |
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGSERIAL PRIMARY KEY` | 自增主键转换 | PG 用 SERIAL/BIGSERIAL，无需 AUTOINCREMENT 关键字 |
| `REAL` | `DOUBLE PRECISION` | 浮点数映射 | 或用 `NUMERIC(p,s)` 需要精确小数时 |
| `BLOB` | `BYTEA` | 二进制数据 | 项目目前无 BLOB 字段 |
| `BOOLEAN`（SQLite 用 INTEGER 0/1） | `BOOLEAN` | 需数据转换 0→false/1→true | 检查所有 `is_xxx` 字段 |
| `DATETIME`（SQLite 存 INTEGER 时间戳） | `BIGINT`（保持时间戳）或 `TIMESTAMPTZ` | **建议保持 BIGINT 时间戳**避免时区问题 | 见风险4：时区处理差异 |
| `PRAGMA journal_mode=WAL` | `wal_level=replica` + `max_wal_senders` | Postgres 配置参数 | 在 `postgresql.conf` 设置 |
| `PRAGMA busy_timeout=30000` | `lock_timeout=30s` + `statement_timeout` | 锁等待超时 | 在 `postgresql.conf` 或会话级设置 |
| `PRAGMA synchronous=NORMAL` | `synchronous=on`（默认） | PG 默认更安全 | 单机可保持默认，性能敏感可评估 `off`（有数据丢失风险） |
| `PRAGMA wal_autocheckpoint=1000` | `checkpoint_timeout=5min` + `max_wal_size` | WAL 检查点 | PG 自动管理，一般无需手动调 |
| `ATTACH DATABASE 'shared.db'` | 跨库查询 / `postgres_fdw` | 跨数据库访问 | PG 用 FDW 或 schema 隔离替代 ATTACH |
| `INSERT OR IGNORE` | `INSERT ... ON CONFLICT DO NOTHING` | 冲突忽略 | 需有主键/唯一约束 |
| `INSERT OR REPLACE` | `INSERT ... ON CONFLICT DO UPDATE` | 冲突替换 | 需明确 SET 字段 |
| `CREATE TABLE IF NOT EXISTS` | `CREATE TABLE IF NOT EXISTS` | 直接兼容 | 无差异 |
| `PRAGMA table_info(<table>)` | `\d <table>` 或 `information_schema.columns` | 查表结构 | 迁移脚本需适配 |

**特殊处理：`shared_db.py` 的 ATTACH DATABASE**

`core/shared_db.py` 用 `ATTACH DATABASE 'shared.db'` 实现多 Bot 共享 `user_profiles`/`funnel_state`。迁移到 Postgres 后：
- 方案 A（推荐）：共享表放入独立 schema（如 `shared.user_profiles`），各 Bot 连同库不同 schema
- 方案 B：共享表放入独立 Postgres database，用 `postgres_fdw` 跨库访问
- 方案 C：所有 Bot 共用同一 database 同一 schema，通过 `bot_id` 字段隔离（v5.24.0 阶段2 已支持 `bot_id` 过滤）

### 五、风险与缓解

| 序号 | 风险 | 影响 | 缓解措施 |
|:----:|------|------|----------|
| R1 | **并发模型差异**：SQLite 单写 → Postgres 多写 | WriteQueue 单线程串行设计失去意义；多写并发可能暴露原串行掩盖的竞态 | 迁移前审计所有"先 SELECT 后 INSERT/UPDATE"逻辑，加 `SELECT ... FOR UPDATE` 或唯一约束；保留 WriteQueue 作为背压保护，不立即拆除 |
| R2 | **事务隔离级别差异**：SQLite 默认 SERIALIZABLE（单写天然串行）→ PG 默认 READ COMMITTED | 原依赖串行隔离的逻辑可能出现幻读/不可重复读 | 关键事务显式 `SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`；或用 `SELECT ... FOR UPDATE` 加锁；阶段3 双读对比期重点观察 |
| R3 | **字符编码差异**：SQLite 默认 UTF-8 → PG 创建时需指定 `ENCODING='UTF8'` | 若 PG 库编码非 UTF-8，中文/emoji 乱码 | 建库强制 `CREATE DATABASE mory WITH ENCODING='UTF8' LC_COLLATE='C.UTF-8' LC_CTYPE='C.UTF-8'`；迁移脚本导入前校验编码 |
| R4 | **时区处理差异**：SQLite 存裸时间戳（INTEGER），PG `TIMESTAMPTZ` 会带时区转换 | `database.py` 用 `_CST = timezone(timedelta(hours=8))` 统一北京时间，若 PG 用 TIMESTAMPTZ 可能双重偏移 | **建议 PG 仍用 BIGINT 存时间戳**（与 SQLite 一致），避免时区转换；若用 TIMESTAMPTZ 需统一设 `timezone='Asia/Shanghai'` 且代码层不再手动 +8 |
| R5 | **SQL 方言差异**：`sqlite3` 占位符 `?` → `psycopg2` 占位符 `%s` | 所有 Repo 层 SQL 需改写 | 用 `psycopg2` 的 `?` 兼容层，或统一改用命名参数 `:name`；阶段1 脚本需全量扫描替换 |
| R6 | **连接池差异**：SQLite 单连接共享 → PG 需连接池 | 直接每请求建连会耗尽 PG 连接 | 引入 `psycopg2.pool` 或 `pgbouncer`；WriteQueue Worker 持有独立长连接 |
| R7 | **备份策略差异**：SQLite 直接 `cp mory.db` → PG 需 `pg_dump`/`pg_basebackup` | 原备份脚本失效 | 迁移前重写备份脚本为 `pg_dump --format=custom`；crontab 每日备份 + 保留 7 天 |
| R8 | **监控指标差异**：`write_queue._stats` 语义变化 | 原 SQLite 写队列指标不再适用 | 阶段2-4 期间双监控；迁移完成后新增 PG 指标（连接数/锁等待/慢查询） |
| R9 | **回滚窗口收窄**：阶段5 7 天后 SQLite 归档 | 超过 7 天无法零损失回滚 | 阶段5 延长观察期至 14 天；归档 SQLite 保留 30 天不删除 |
| R10 | **VPS 资源占用**：Postgres 常驻内存高于 SQLite | 2C4G VPS 可能内存吃紧 | 迁移前评估是否需同步升级 VPS 到 4C8G；或 Postgres 独立部署到第二台 VPS |

## 决策流程图

```
                  ┌─────────────────────────┐
                  │  是否命中任一迁移触发指标？ │
                  └────────────┬────────────┘
                               │
              ┌────────────────┼────────────────┐
              ↓                                  ↓
         命中 T3/T4                          仅命中 T1/T2
              │                                  │
              ↓                                  ↓
    ┌─────────────────┐               ┌─────────────────────┐
    │ 必须迁移 Postgres│               │ 优先升级 VPS 硬件     │
    │ 进入评估清单     │               │ 重新压测校准阈值      │
    └─────────────────┘               └─────────────────────┘
              │
              ↓
    ┌─────────────────────────┐
    │ 评估清单 4 项全部完成？   │
    └────────────┬────────────┘
                   │
        ┌──────────┴──────────┐
        ↓                     ↓
       是                     否
        │                     │
        ↓                     ↓
  ┌──────────┐        ┌─────────────────┐
  │ 阶段1 脚本│        │ 补齐评估/培训    │
  │ 幂等化   │        │ 推迟迁移         │
  └──────────┘        └─────────────────┘
```

## 附录：现有架构关键文件索引

| 文件 | 职责 | 迁移影响 |
|------|------|----------|
| `core/database.py` | SQLite 主连接 + PRAGMA 配置 | 需新增 Postgres 连接分支 |
| `core/write_queue.py` | 单线程写入队列 | 阶段2 改为双写，阶段4 主路径切 PG |
| `core/db_connection_proxy.py` | 连接代理，拦截 execute 走队列 | 阶段2/3/4 路由切换核心修改点 |
| `core/shared_db.py` | ATTACH DATABASE 多 Bot 共享 | 需改为 schema/FDW/bot_id 隔离 |
| `core/db_repos/*.py` | 9 个 Repo 层 | SQL 方言适配（占位符 `?`→`%s`） |
| `core/migrate.py` | SQLite schema 迁移 | 需新增 PG schema 迁移分支 |
| `tests/perf/locustfile.py` | Locust 压测脚本 | 迁移前评估必用 |
| `config.json.example` | 配置样例 | 新增 PG_* 配置项 |
| `.env.example` | 环境变量样例 | 新增 PG_HOST/PG_PORT/PG_DB/PG_USER/PG_PASSWORD |

## 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-17 | v5.24.0 阶段3-D | 初始创建，定义迁移触发指标、评估清单、5 阶段无缝迁移方案、Schema 映射表、10 项风险缓解 |
