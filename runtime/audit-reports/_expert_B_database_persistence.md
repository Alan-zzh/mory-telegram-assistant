# 专家 B 审计报告 · 数据库 + 持久化专项

- 项目：mory_assistant
- 审计范围：v5.32.0 → v5.35.0（HEAD=77e849a，工作区 38 modified + 55 untracked）
- 审计时间：2026-07-18
- 审计角色：专家 B（数据库 + 持久化）
- 审计方式：本地只读 + 临时库 CRUD/并发/重启测试 + WriteQueue 真实启动测试 + grep + 真实文件:行号证据
- 授权边界：本地读取/运行检查/临时库测试/必要最小修复（未做代码修复）；生产部署/上传未授权

---

## 1. 执行摘要

### 总体结论

数据库核心基础设施**健康度可接受**，但**v5.34.0/v5.35.0 新模块对数据库的访问存在严重系统性问题**：
- **基础设施（v5.32.0 之前）**：VERIFIED — 142 张表 / 97 索引 / WAL+busy_timeout / WriteQueue 单线程串行写入 / 179 个 Repo 方法注册零缺失零孤儿 / 启动自检四层防御实装。
- **v5.34.0 sales_repo**：VERIFIED — 12 个方法全部注册，CRUD 测试全过，但 `create_order` 有 P0 级 order_no 重复缺陷。
- **v5.35.0 36 个新模块对数据库的访问**：BROKEN — 12 处 `INSERT OR REPLACE` 用错表名（复数化/后缀化）+ 14 处 `INSERT INTO` 操作完全不存在的表 + `INSERT OR REPLACE` 缺 NOT NULL 字段（即使修复 ImportError 也会立即触发 IntegrityError）。专家 A 已确认这 36 个模块全部 ImportError 无法加载，所以**当前运行时不会触发**这些 DB 错误，但代码本身错误。

### 核心数据（实测）

| 指标 | 实测值 | 文档声明值 | 偏差 |
|---|---|---|---|
| CREATE TABLE 数 | **142** | 142 (snapshot METRICS) | **0** ✅ |
| 索引数 | 97 | — | — |
| `_REPO_METHOD_MAP` 注册方法数 | **179** | CHANGELOG v5.33.1 称 167 | +12（新增 sales 12 方法） |
| Repo public 方法自检（missing + orphaned） | **0 + 0** | 0 + 0 | ✅ |
| sales_repo 实际 public 方法 | **12** | CHANGELOG v5.34.0 声明 **13** | **-1** ⚠️ |
| `journal_mode` | WAL | WAL | ✅ |
| `busy_timeout` | 30000ms | 30000ms | ✅ |
| `synchronous` | 1 (NORMAL) | NORMAL | ✅ |
| `cache_size` | -4000 (4MB) | -4000 | ✅ |
| `mmap_size` | 268435456 (256MB) | 256MB | ✅ |
| 外键约束表数 | **0** | — | 无数据库层引用完整性 |
| CHECK 约束表数 | 5 | — | 仅 channel_tracking/checkin_records/checkin_config/group_members/interaction_quality_scores |
| `scripts/verify_db_methods.py` | **不存在** | AGENTS.md/runbook-ship-gate.md 多处引用 | 文档失真 |
| version.py VERSION | v5.33.1 | VERSION.md v5.35.0 | **不一致**（专家 A 已记录） |
| WriteQueue 并发写入 | 50 orders + 200 events / 0.04s | — | 无 `database is locked` |

### v5.35.0 新模块对 DB 访问的失败模式（按问题严重度）

1. **BROKEN - 表名复数化错误**（6 处）：模块代码用 `group_reports`/`word_clouds`/`force_channels`/`valid_speak_records`/`group_todos`/`channel_links`，实际表名是 `group_report`/`word_cloud`/`force_channel`/`valid_speak`/`group_todo`/`channel_link`。
2. **BROKEN - 表名完全不存在**（14 处）：`member_info`/`member_actions`/`global_ad_blacklist`/`user_points`/`chat_points_usage`/`bot_registry`/`group_registry`/`premium_usage`/`group_configs`/`config_templates`/`config_template_applications`/`content_archives`/`image_records` 等表名 `_init_tables` 中完全没有定义。
3. **BROKEN - INSERT OR REPLACE 缺 NOT NULL 字段**（8 处）：表 `chat_settings`/`join_settings`/`group_commands`/`bot_settings`/`afool_member`/`super_afool`/`new_member_probation`/`group_report` 等的 `updated_at` 字段是 `INTEGER NOT NULL`，但模块代码 `INSERT OR REPLACE INTO chat_settings (chat_id, data) VALUES (?, ?)` 没有提供 `updated_at`，会触发 `IntegrityError: NOT NULL constraint failed`。

> 注：上述错误**当前运行时不触发**，因为 v5.35.0 36 个新模块 ImportError 无法加载（专家 A 已记录）。但**修复 ImportError 后立即触发 DB IntegrityError**，必须同步修复。

---

## 2. CREATE TABLE 审计表

### 2.1 v5.34.0 新增 12 张表

| 表名 | 是否 IF NOT EXISTS | 是否在 `_init_tables()` | 状态 | 证据 |
|---|---|---|---|---|
| `sales_products` | ✅ | ✅ | VERIFIED | `core/database.py:1374` |
| `sales_orders` | ✅ | ✅ | VERIFIED | `core/database.py:1389` |
| `sales_events` | ✅ | ✅ | VERIFIED | `core/database.py:1407` |
| `sales_commissions` | ✅ | ✅ | VERIFIED | `core/database.py:1420` |
| `user_risk_profile` | ✅ | ✅ | VERIFIED | `core/database.py:1432` |
| `security_events` | ✅ | ✅ | VERIFIED | `core/database.py:1439` |
| `managed_groups` | ✅ | ✅ | VERIFIED | `core/database.py:1454` |
| `managed_group_features` | ✅ | ✅ | VERIFIED | `core/database.py:1470` |
| `content_violations` | ✅ | ✅ | VERIFIED | `core/database.py:1479` |
| `user_membership` | ✅ | ✅ | VERIFIED | `core/database.py:1494` |
| `membership_subscriptions` | ✅ | ✅ | VERIFIED | `core/database.py:1505` |
| `user_questions`（v5.15 已存在） | ✅ | ✅ | OBSOLETE 重复 | 不计入 12 张 |

### 2.2 v5.35.0 新增 23 张表

| 表名 | 是否 IF NOT EXISTS | 是否在 `_init_tables()` | 状态 | 证据 |
|---|---|---|---|---|
| `chat_settings` | ✅ | ✅ | VERIFIED 但模块代码 BROKEN | `core/database.py:1519` |
| `join_settings` | ✅ | ✅ | VERIFIED 但模块代码 BROKEN | `core/database.py:1526` |
| `group_commands` | ✅ | ✅ | VERIFIED 但模块代码 BROKEN | `core/database.py:1533` |
| `bot_settings` | ✅ | ✅ | VERIFIED 但模块代码 BROKEN | `core/database.py:1540` |
| `afool_member` | ✅ | ✅ | VERIFIED 但模块代码 BROKEN | `core/database.py:1547` |
| `super_afool` | ✅ | ✅ | VERIFIED 但模块代码 BROKEN | `core/database.py:1557` |
| `bot_list` | ✅ | ✅ | VERIFIED 但模块代码 BROKEN | `core/database.py:1566` |
| `new_member_probation` | ✅ | ✅ | VERIFIED | `core/database.py:1576` |
| `group_report` | ✅ | ✅ | VERIFIED 但模块代码用错表名 `group_reports` | `core/database.py:1585` |
| `word_cloud` | ✅ | ✅ | VERIFIED 但模块代码用错表名 `word_clouds` | `core/database.py:1593` |
| `language_whitelist` | ✅ | ✅ | VERIFIED | `core/database.py:1602` |
| `force_channel` | ✅ | ✅ | VERIFIED 但模块代码用错表名 `force_channels` | `core/database.py:1610` |
| `valid_speak` | ✅ | ✅ | VERIFIED 但模块代码用错表名 `valid_speak_records` | `core/database.py:1618` |
| `chat_points_cost` | ✅ | ✅ | VERIFIED 但模块代码操作不存在表 `user_points`/`chat_points_usage` | `core/database.py:1626` |
| `auto_rules` | ✅ | ✅ | VERIFIED | `core/database.py:1634` |
| `user_marking` | ✅ | ✅ | VERIFIED | `core/database.py:1642` |
| `group_todo` | ✅ | ✅ | VERIFIED 但模块代码用错表名 `group_todos` | `core/database.py:1651` |
| `invite_link_manager` | ✅ | ✅ | VERIFIED | `core/database.py:1658` |
| `channel_link` | ✅ | ✅ | VERIFIED 但模块代码用错表名 `channel_links` | `core/database.py:1665` |
| `group_safety_center` | ✅ | ✅ | VERIFIED | `core/database.py:1673` |
| `group_message_push` | ✅ | ✅ | VERIFIED | `core/database.py:1680` |
| `punishment_center` | ✅ | ✅ | VERIFIED | `core/database.py:1687` |
| `entertainment_games` | ✅ | ✅ | VERIFIED | `core/database.py:1694` |

### 2.3 v5.35.0 任务清单中提到但实际**未创建**的表

任务清单第 1 节列出以下表，但 `_init_tables()` 中无 CREATE TABLE：

| 任务清单声称的表 | 实际状态 | 备注 |
|---|---|---|
| `bottom_button` 相关表 | MISSING | 模块代码也无对应 INSERT |
| `config_template` 相关表 | MISSING | 模块代码操作 `config_templates`/`group_configs`/`config_template_applications` 但表不存在 |
| `content_archive` 相关表 | MISSING | 模块代码操作 `content_archives` 但表不存在 |
| `message_library` 相关表 | MISSING | 模块代码无对应 INSERT |
| `random_drop` 相关表 | MISSING | 模块代码无对应 INSERT |
| `group_props` 相关表 | MISSING | 模块代码无对应 INSERT |
| `image_manager` 相关表 | MISSING | 模块代码操作 `image_records` 但表不存在 |
| `crypto_detector` 相关表 | MISSING | 模块代码无对应 INSERT |
| `group_list` 相关表 | MISSING | 模块代码操作 `group_registry` 但表不存在 |
| `stats_report` 相关表 | MISSING | 模块代码无对应 INSERT |
| `ad_blocker` 相关表 | MISSING | 模块代码操作 `global_ad_blacklist` 但表不存在 |
| `group_migration` 相关表 | MISSING | 模块代码无对应 INSERT |
| `new_member_analytics` 相关表 | MISSING | 模块代码无对应 INSERT（可能复用现有表） |

**所有 142 张表都用 `CREATE TABLE IF NOT EXISTS`**，无遗漏。

---

## 3. ALTER TABLE 审计

### 3.1 `_safe_add_column` 幂等添加列（共 8 处，全部幂等）

| 文件:行号 | 表.列 | 定义 | 是否幂等 | 是否常量默认值 | 状态 |
|---|---|---|---|---|---|
| `core/database.py:697` | `lucky_wheel_results.spin_count` | `INTEGER NOT NULL DEFAULT 1` | ✅ PRAGMA 检查 | ✅ 常量 | VERIFIED |
| `core/database.py:1209` | `user_profiles.activity_score` | `REAL DEFAULT 0.0` | ✅ | ✅ | VERIFIED |
| `core/database.py:1210` | `user_profiles.flirt_affinity` | `REAL DEFAULT 0.0` | ✅ | ✅ | VERIFIED |
| `core/database.py:1211` | `user_profiles.spend_tendency` | `REAL DEFAULT 0.0` | ✅ | ✅ | VERIFIED |
| `core/database.py:1212` | `user_profiles.resistance_idx` | `REAL DEFAULT 0.5` | ✅ | ✅ | VERIFIED |
| `core/database.py:1213` | `user_profiles.peak_hours` | `TEXT DEFAULT '[]'` | ✅ | ✅ | VERIFIED |
| `core/database.py:1214` | `user_profiles.persona_tags` | `TEXT DEFAULT '[]'` | ✅ | ✅ | VERIFIED |
| `core/database.py:1217` | `user_profiles.lifecycle_stage` | `TEXT DEFAULT 'New'` | ✅ | ✅ | VERIFIED |
| `core/database.py:1222` | `user_profiles.conv_turn_count` | `INTEGER DEFAULT 0` | ✅ | ✅ | VERIFIED（v5.33.0 修复） |
| `core/database.py:1223` | `user_profiles.conv_last_active` | `TIMESTAMP`（允许 NULL） | ✅ | N/A | VERIFIED（v5.33.0 修复） |

### 3.2 v5.33.0 `conv_turn_count` / `conv_last_active` 修复验证

**修复前**（AI_DEBUG_HISTORY.md #13）：`ALTER TABLE user_profiles ADD COLUMN conv_last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP` 触发 `sqlite3.OperationalError: Cannot add a column with non-constant default`，导致 mory-assistant 启动崩溃循环（restart counter 7）。

**修复后实测**：`core/database.py:1222-1223` 已改为 `INTEGER DEFAULT 0` 和 `TIMESTAMP`（允许 NULL），由 `update_conversation_turn()` 在 UPDATE 时显式赋值 `CURRENT_TIMESTAMP`。`core/db_repos/user_repo.py:412-413` 在调用前再次幂等补列。

**状态**：VERIFIED — 临时库 `_init_tables()` 成功执行，无 OperationalError。

### 3.3 其他 ALTER TABLE 使用（11 处，全部幂等）

| 文件:行号 | 表.列 | 模式 | 状态 |
|---|---|---|---|
| `core/database.py:1053` | `reply_tracking.replied` | try/except + ALTER | VERIFIED |
| `core/database.py:1062` | `reply_tracking.chat_id` | PRAGMA + ALTER | VERIFIED |
| `core/database.py:1070` | `users.conversion_status` | try/except + ALTER | VERIFIED |
| `core/database.py:1077` | `group_stats.chat_id` | try/except + ALTER | VERIFIED |
| `core/database.py:1085` | `checkin_records.current_streak` | try/except + ALTER | VERIFIED |
| `core/growth_optimizer.py:166-178` | `conversion_events.{source,campaign_id,attribution_model,weight,is_memory_assisted}` | PRAGMA 检查 + ALTER | VERIFIED |
| `core/funnel_state_machine.py:63-79` | `funnel_state.bot_id` | PRAGMA + ALTER + UPDATE 迁移 | VERIFIED |
| `core/funnel_state_machine.py:312-317` | `conversion_events.{column}` | PRAGMA + ALTER | VERIFIED |
| `core/shared_db.py:127-135` | `user_profiles.{version,memory_summary}` | PRAGMA + ALTER | VERIFIED |
| `core/user_lifecycle.py:101-107` | `user_profiles.lifecycle_stage` | PRAGMA + ALTER | VERIFIED |
| `core/memory_summarizer.py:407-411,437` | `user_profiles.memory_summary` | try/except + ALTER（重复 2 处） | VERIFIED（重复但不破坏） |

### 3.4 `DEFAULT CURRENT_TIMESTAMP` 使用（9 处，**全部在 CREATE TABLE 中**，合法）

`core/database.py:271/1164/1165/1175/1195/1351/1352/1367/1368` — 全部在 `CREATE TABLE` 中使用 `DEFAULT CURRENT_TIMESTAMP`，SQLite 允许此用法（仅 ALTER TABLE ADD COLUMN 不允许非常量默认值）。

**状态**：VERIFIED — 不触发 v5.33.0 暗病。

---

## 4. Repo 注册验证

### 4.1 `verify_db_methods.py` 文档失真

| 引用位置 | 引用内容 | 实际状态 |
|---|---|---|
| `AGENTS.md:46` | "部署前跑 `python scripts/verify_db_methods.py`，输出'✅ DB 方法注册验证通过'才可上线" | **脚本不存在** |
| `docs/technical/runbook-ship-gate.md:23` | `python scripts/verify_db_methods.py` | **脚本不存在** |
| `CHANGELOG.md:22`（v5.31.1） | "第三层部署前验证脚本 scripts/verify_db_methods.py" | **声明已实装但实际未实装** |
| `version.py:14`（v5.33.1） | "verify_db_methods 167方法" | **声称已运行但脚本不存在** |

**严重度**：P1 — 文档失真。但**实际防御有效**，因为 `core/database.py:88` 的 `_self_check_repo_methods()` 在 DB 启动时强制 RuntimeError 阻止启动，覆盖了 verify_db_methods.py 的设计意图。

### 4.2 `_REPO_METHOD_MAP` 实测结果

替代 `verify_db_methods.py` 的等价检查（直接调用 `_self_check_repo_methods` 同款逻辑）：

```
Total _REPO_METHOD_MAP entries: 179
Missing (Repo method not registered): 0
Orphaned (registered but no method): 0
```

**状态**：VERIFIED — 179 个方法注册，0 缺失，0 孤儿。

### 4.3 sales_repo 13 方法声明 vs 12 方法实测

CHANGELOG.md 第 18 行（v5.34.0）声称 "sales_repo 13 个方法"，实测：

| # | 方法名 | 是否注册 | 状态 |
|---|---|---|---|
| 1 | `add_product` | ✅ | VERIFIED |
| 2 | `update_product` | ✅ | VERIFIED |
| 3 | `list_products` | ✅ | VERIFIED |
| 4 | `get_product` | ✅ | VERIFIED |
| 5 | `create_order` | ✅ | VERIFIED（但有 P0 bug） |
| 6 | `update_order_status` | ✅ | VERIFIED |
| 7 | `get_user_orders` | ✅ | VERIFIED |
| 8 | `get_order_stats` | ✅ | VERIFIED |
| 9 | `track_sales_event` | ✅ | VERIFIED |
| 10 | `get_funnel_stats` | ✅ | VERIFIED |
| 11 | `add_commission` | ✅ | VERIFIED |
| 12 | `get_commission_stats` | ✅ | VERIFIED |
| — | (第 13 个方法不存在) | — | MISSING |

**结论**：CHANGELOG 声明 13 方法但代码实测只有 12 个，文档失真 P3。

---

## 5. 临时库 CRUD 测试结果

### 5.1 sales_repo 12 方法 CRUD 测试（临时库真实执行）

| 方法 | Create | Read | Update | Delete | 幂等重复 | 非法输入 | 不存在记录 |
|---|---|---|---|---|---|---|---|
| `add_product` | PASS pid=1 | — | — | — | — | WARN（负 price 可插入）/ PASS（None name 拒绝） | — |
| `get_product` | — | PASS | — | — | — | — | PASS 返回 `{}` |
| `update_product` | — | — | PASS | — | PASS（3x 重复 OK） | PASS（空 kwargs 返回 False） | WARN（不存在返回 True，无 rowcount 检查） |
| `list_products` | — | PASS | — | — | — | — | — |
| `create_order` | PASS oid=1 | — | — | — | — | WARN（负 uid/amount 可插入） | — |
| `get_user_orders` | — | PASS | — | — | — | — | PASS 返回 `[]` |
| `update_order_status` | — | — | PASS | — | — | — | WARN（不存在返回 True） |
| `get_order_stats` | — | PASS | — | — | — | — | — |
| `track_sales_event` | PASS | — | — | — | — | — | — |
| `get_funnel_stats` | — | PASS | — | — | — | — | — |
| `add_commission` | PASS cid=1 | — | — | — | — | — | — |
| `get_commission_stats` | — | PASS | — | — | — | — | PASS 返回全 0 |

**汇总**：26 测试用例，21 PASS / 1 FAIL / 4 WARN。

### 5.2 P0 缺陷实测：`create_order` 同秒重复下单 UNIQUE 冲突

```python
oid1 = db.sales.create_order(uid=8888, product_id=1, amount=1.0)
oid2 = db.sales.create_order(uid=8888, product_id=1, amount=1.0)  # 同秒
# 结果: IntegrityError('UNIQUE constraint failed: sales_orders.order_no')
```

**根因**：`core/db_repos/sales_repo.py:85` `order_no = f"ORD{now}{uid}{product_id}"` 不含唯一性后缀（自增 ID / UUID / 随机数）。

**影响**：业务场景"用户连点两次下单按钮"/"高并发秒杀"/"同一秒同 uid 同 product_id 下两单"会触发 IntegrityError，**调用方收到 lastrowid=-1 但 sales_repo.add_product 仍 `return cur.lastrowid`**，调用方拿到 -1 误以为成功。

### 5.3 WriteQueue 并发测试（50 orders + 200 events）

```
=== 2. 并发 create_order (10 线程) ===
[PASS] wq.concurrent_create_orders: 50 orders in 0.01s (10 threads x 5 = 50 expected)
=== 3. 检查 WriteQueue 统计 ===
[INFO] wq.stats: total=53, success=13, failed=40, last_error=UNIQUE constraint failed: sales_orders.order_no
=== 4. 验证订单数 ===
[FAIL] wq.order_count: DB has 10 orders (<50 expected)
```

**关键发现**：
- 50 个并发订单只有 10 个成功（每个 uid 唯一去重）
- 40 个失败被 WriteQueue Worker 的 `logger.error` 捕获，但**调用方完全不知情**
- WriteQueue 设计注释承认"队列化后每条写操作独立 commit，多语句事务的原子性降级为顺序执行"，但未提及**写失败时调用方无感知**这一严重问题
- 200 个 track_sales_event 全部成功（无 UNIQUE 约束）→ 说明 WriteQueue 本身无问题，问题在 sales_repo 设计

---

## 6. 事务边界问题

### 6.1 WriteQueue 多语句事务原子性降级

**证据**：`core/db_connection_proxy.py:17-19` 注释：
```
事务说明：
  队列化后每条写操作独立 commit，多语句事务的原子性降级为顺序执行。
  现有代码的多语句事务多为 INSERT OR IGNORE + UPDATE，拆开安全。
```

**实际状态**：VERIFIED 但有 caveat — 拆开后单条失败不影响其他语句，但 `INSERT OR REPLACE INTO chat_settings (chat_id, data) VALUES (?, ?)` 这种依赖隐式 NOT NULL 默认值的语句拆开后立即失败（模块代码错误，非 WriteQueue 问题）。

### 6.2 WriteQueue 写失败调用方无感知（P0）

**证据**：`core/db_connection_proxy.py:248-274` `_write_via_queue`：
```python
if result.error is not None:
    # 非核心写入被丢弃（result.error = TimeoutError）或执行失败
    logger.debug(f"代理写降级: {result.error} | SQL: {sql[:80]}")
    return _FakeCursor(result)
```

`_FakeCursor.__init__` 在 `result.error is not None` 时设 `rowcount=-1, lastrowid=-1`，但调用方（如 sales_repo）`return cur.lastrowid` 直接返回 -1，**调用方拿到 -1 仍可能视为成功**。

**影响**：订单创建失败但用户看到"下单成功"提示；商品添加失败但管理员看到"添加成功"； commissions 写入失败但报表显示已记录。

**修复建议**：
- 方案 A（推荐）：`_write_via_queue` 在 `result.error is not None` 时直接 `raise result.error`，由调用方处理异常
- 方案 B：`_FakeCursor.lastrowid` 在 error 时返回 None（而非 -1），调用方检查 `if lastrowid is None: raise`

### 6.3 `database is locked` 验证

**实测**：50 并发 orders + 200 并发 events / 0.04s 全部完成（含 40 个 IntegrityError 失败），**无任何 `database is locked` 错误**。WAL + busy_timeout=30000 + WriteQueue 单线程串行写入的组合工作正常。

### 6.4 shutdown 排空验证

**实测**：`write_queue.stop(timeout=10.0)` 正确排空队列，`pending=0 after stop`，Worker 正确退出。

**证据**：`main.py:190` `write_queue.stop(timeout=10.0)` + `core/write_queue.py:120-131` `stop()` 投递哨兵任务 + join Worker。

---

## 7. 多群隔离问题

### 7.1 表设计层面的多群隔离（VERIFIED）

| 表名 | 主键 | chat_id 进入条件 | 状态 |
|---|---|---|---|
| `chat_settings` | `chat_id` | PK | ✅ 完美隔离 |
| `join_settings` | `chat_id` | PK | ✅ |
| `group_commands` | `chat_id` | PK | ✅ |
| `bot_settings` | `bot_id` | N/A（bot 级） | ✅ |
| `new_member_probation` | `chat_id` | PK | ✅ |
| `group_report` | `chat_id` | PK | ✅ |
| `word_cloud` | `chat_id` | PK | ✅ |
| `language_whitelist` | `chat_id` | PK | ✅ |
| `force_channel` | `chat_id` | PK | ✅ |
| `valid_speak` | `chat_id` | PK | ✅ |
| `chat_points_cost` | `chat_id` | PK | ✅ |
| `auto_rules` | `chat_id` | PK | ✅ |
| `user_marking` | `(uid, chat_id)` 复合 PK | 复合 PK | ✅ |
| `group_todo` | `chat_id` | PK | ✅ |
| `invite_link_manager` | `chat_id` | PK | ✅ |
| `channel_link` | `chat_id` | PK | ✅ |
| `group_safety_center` | `chat_id` | PK | ✅ |
| `group_message_push` | `chat_id` | PK | ✅ |
| `punishment_center` | `chat_id` | PK | ✅ |
| `entertainment_games` | `chat_id` | PK | ✅ |
| `managed_groups` | `id` + `UNIQUE(chat_id)` | UNIQUE | ✅ |
| `managed_group_features` | `(mg_id, feature)` | 通过 mg_id 关联 | ✅ |
| `content_violations` | `id` AUTOINCREMENT | 字段 `chat_id` | ✅ |
| `security_events` | `id` AUTOINCREMENT | 字段 `chat_id` | ✅ |

**实测**：临时库中 `chat_settings` 写入 `chat_id=-1001` 和 `chat_id=-1002` 数据完全隔离；`user_marking` 复合 PK `(uid=5001, chat_id=-1001)` 和 `(uid=5001, chat_id=-1002)` 互不干扰。

### 7.2 sales_orders 跨群返回（设计选择，非缺陷）

**证据**：`core/db_repos/sales_repo.py:106-114` `get_user_orders(uid, limit=20)` 只按 uid 过滤，不按 chat_id 过滤。

**判断**：这是**设计决定**（订单是用户级而非群级），不算 P 级缺陷。但同一用户在群 A 下单后，群 B 的管理员通过 `handle_my_orders` 命令也能看到该用户在群 A 的订单，可能存在跨群数据暴露风险，建议未来增加可选 `chat_id` 过滤参数。

### 7.3 sales_products 全局共享（设计选择）

**证据**：`list_products(active_only=True)` 返回全局商品列表，无 chat_id 过滤。

**判断**：当前所有群共享同一商品列表。未来如果需要按群隔离商品，需新增 `chat_id` 字段到 `sales_products` 表。

---

## 8. 重启持久化验证

### 8.1 sales_repo 重启持久化（VERIFIED）

| 测试 | 结果 |
|---|---|
| `restart_persistence(product)` | PASS — price=99.99 在重启后保留 |
| `restart_persistence(orders)` | PASS — 1 个订单在重启后保留 |
| `restart_persistence(events)` | PASS — 5 个销售事件在重启后保留 |
| `restart_persistence(commission)` | PASS — 1.99 佣金在重启后保留 |

### 8.2 v5.35.0 新表重启持久化（VERIFIED）

| 测试 | 结果 |
|---|---|
| `restart_persistence(chat_settings)` | PASS — `{"key":"value"}` 在重启后保留 |
| `restart_persistence(user_marking)` | PASS — `["ad"]` 标签在重启后保留 |

### 8.3 WriteQueue 重启排空（VERIFIED）

实测 50 orders + 200 events 在 WriteQueue 启动状态下写入，`stop(timeout=10.0)` 正确排空后，重启 DB 仍能读到全部数据。

---

## 9. 配置持久化验证

### 9.1 v5.33.1 `_blacklist_dirty` 标记机制（VERIFIED 但有 caveat）

**实测 6 项**：

| 测试 | 结果 |
|---|---|
| 初始 dirty 应为 False | PASS |
| `_blacklist_model` 后 dirty 应为 True | PASS |
| `consume_blacklist_dirty` 后 dirty 应再次为 False（读后清） | PASS |
| `_restore_model` 后 dirty 应为 True | PASS |
| 重复拉黑同一模型 dirty 不应重复设置 | **FAIL** — dirty 仍被设置为 True |
| `save_config_task` 检测 dirty 落盘流程 | PASS |

**P3 缺陷**：`_blacklist_model` 第 904 行 `self._blacklist_dirty = True` 在 `if model_name not in self.config["BLACKLISTED_MODELS"]` 块外，导致重复拉黑同一模型仍会设置 dirty。

**当前影响**：无。因为 `_filter_runtime_pool:883-890` 已先 `_is_blacklisted` 判重再决定是否调用 `_blacklist_model`，所以实际不会重复调用。但 `_blacklist_model` 自身没有去重逻辑，是脆弱设计。

### 9.2 save_config_task 调度间隔（P2）

**证据**：`tasks/maintenance/save_config_task.py:34-44` 调度 `cron minute=30`，即每小时的第 30 分钟触发。

**影响**：模型被拉黑后，**最多需要等 1 小时才会落盘**。在此期间如果服务重启，黑名单仍会丢失。

**修复建议**：拉黑后立即触发 save_config（同步或异步），不应依赖定时任务。

### 9.3 `_blacklist_dirty` 注释 vs 实装一致性（VERIFIED）

| 注释/声明 | 实装 | 状态 |
|---|---|---|
| AI_DEBUG_HISTORY.md #14 解法① `_blacklist_model`/`_restore_model` 在拉黑/恢复时置 `self._blacklist_dirty = True` | `core/ai_engine.py:904, 916` | VERIFIED |
| 解法② 新增 `consume_blacklist_dirty()` 公开方法（线程安全，读后清标记） | `core/ai_engine.py:921-930` | VERIFIED |
| 解法③ `save_config_task.execute()` 检测 dirty 标记，dirty 或 idx 变化任一触发即落盘 | `tasks/maintenance/save_config_task.py:54-60` | VERIFIED |
| 解法④ `_filter_runtime_pool` 调 `_blacklist_model` 前先 `_is_blacklisted` 判重 | `core/ai_engine.py:883-890` | VERIFIED |

---

## 10. P0/P1/P2/P3 缺陷表

### P0（致命，必须立即修复）

| # | 缺陷 | 证据 | 影响 | 修复建议 |
|---|---|---|---|---|
| P0-1 | `sales_orders.order_no` 生成规则导致同秒同 uid 同 product_id 重复下单触发 UNIQUE 冲突 | `core/db_repos/sales_repo.py:85` `order_no = f"ORD{now}{uid}{product_id}"` | 业务场景"连点两次下单"/"高并发秒杀"会失败；并发测试 50 orders 只成功 10 个 | order_no 加入自增 ID 或 `uuid4().hex[:8]` 或 `time.time_ns()` 提高时间精度 |
| P0-2 | WriteQueue 写失败调用方完全无感知 | `core/db_connection_proxy.py:270-273` 返回 `_FakeCursor(result)` 而非 raise；sales_repo 直接 `return cur.lastrowid` 返回 -1 | 订单/商品/佣金写入失败时用户看到"成功"，数据丢失但 UI 无错误 | `_write_via_queue` 在 `result.error is not None` 时 `raise result.error` |
| P0-3 | v5.35.0 新模块 `INSERT OR REPLACE` 缺 NOT NULL 字段 `updated_at`（8 处） | `modules/chat_settings.py:64` `INSERT OR REPLACE INTO chat_settings (chat_id, data) VALUES (?, ?)` 缺 `updated_at` | 修复 ImportError 后立即触发 `IntegrityError: NOT NULL constraint failed` | INSERT 语句补 `updated_at` 字段或表定义改 `DEFAULT 0` |

### P1（严重，应在下一版修复）

| # | 缺陷 | 证据 | 影响 | 修复建议 |
|---|---|---|---|---|
| P1-1 | v5.35.0 新模块 `INSERT OR REPLACE` 用错表名（复数化，6 处） | `modules/group_report.py:165` `group_reports`（实际 `group_report`）；`modules/word_cloud.py:86` `word_clouds`；`modules/force_channel.py:109` `force_channels`；`modules/valid_speak.py:89` `valid_speak_records`；`modules/group_todo.py:147` `group_todos`；`modules/channel_link.py:128` `channel_links` | 修复 ImportError 后所有写入触发 `OperationalError: no such table` | 模块代码表名去掉复数 's' 或 '_records' 后缀 |
| P1-2 | v5.35.0 新模块 `INSERT INTO` 操作完全不存在的表（14 处） | `modules/afool_member.py:53` `member_info`；`modules/group_members.py:168` `member_actions`；`modules/ad_blocker.py:69` `global_ad_blacklist`；`modules/chat_points_cost.py:65,103` `user_points`/`chat_points_usage`；`modules/bot_list.py:63` `bot_registry`；`modules/group_list.py:96` `group_registry`；`modules/super_afool.py:103` `premium_usage`；`modules/config_template.py:132,144,197` `group_configs`/`config_templates`/`config_template_applications`；`modules/content_archive.py:134` `content_archives`；`modules/image_manager.py:140` `image_records`；`modules/bot_settings.py:60` 仅写 data 不写 bot_id（PK） | 修复 ImportError 后所有写入触发 `OperationalError: no such table` | 二选一：(a) 在 `_init_tables` 补 CREATE TABLE；(b) 修改模块代码用已有表名 |
| P1-3 | `scripts/verify_db_methods.py` 文档失真 | `AGENTS.md:46` / `docs/technical/runbook-ship-gate.md:23` / `CHANGELOG.md:22`（v5.31.1）/ `version.py:14`（v5.33.1）均引用此脚本，但 `scripts/` 目录下不存在 | 部署前验证流程缺失一环；CHANGELOG/version.py 声称已运行此脚本 | 二选一：(a) 实装 `scripts/verify_db_methods.py`；(b) 修订 AGENTS.md/runbook/CHANGELOG/version.py 移除引用 |
| P1-4 | CHANGELOG 声明 sales_repo 13 方法实际 12 个 | `CHANGELOG.md:18`（v5.34.0）"sales_repo 13 个方法" vs `core/db_repos/sales_repo.py` 实测 12 个 public 方法 | 文档失真；用户按 13 方法验收会误判 | 修订 CHANGELOG 改为 12 方法，或补 1 个方法（如 `delete_product`/`cancel_order`） |
| P1-5 | WriteQueue 多语句事务原子性降级 | `core/db_connection_proxy.py:17-19` 注释承认"多语句事务的原子性降级为顺序执行" | INSERT OR IGNORE + UPDATE 拆开后单条失败影响其他语句 | 关键业务（如订单+佣金）改用 `_real_conn` 直连 + 显式 `BEGIN/COMMIT/ROLLBACK` |

### P2（中等，应在下两版修复）

| # | 缺陷 | 证据 | 影响 | 修复建议 |
|---|---|---|---|---|
| P2-1 | `update_product` / `update_order_status` 不检查 rowcount | `core/db_repos/sales_repo.py:48-50, 99-104` 直接 `return True` 不检查 `cur.rowcount` | 不存在的 ID 更新返回 True，调用方误判成功 | 检查 `cur.rowcount > 0` 才返回 True |
| P2-2 | `_blacklist_model` 重复拉黑同一模型仍设置 dirty=True | `core/ai_engine.py:904` `self._blacklist_dirty = True` 在 if 块外 | 重复拉黑时 dirty 误触发；当前因调用方去重未暴露 | 把 `self._blacklist_dirty = True` 移入 if 块内 |
| P2-3 | `save_config_task` 调度间隔为 1 小时 | `tasks/maintenance/save_config_task.py:34-44` `cron minute=30` | 模型拉黑后最多 1 小时才落盘，期间重启会丢失 | 拉黑后立即触发 save_config，不依赖定时任务 |
| P2-4 | 销售相关表无 CHECK 约束 | `core/database.py:1374-1428` sales_products/sales_orders/sales_events/sales_commissions 表定义无 CHECK | 可插入负价格/负金额/负库存/负佣金 | 表定义加 `CHECK(price >= 0)` / `CHECK(amount >= 0)` 等 |
| P2-5 | 数据库无外键约束 | 实测 0 个 FOREIGN KEY | 引用完整性靠应用层，可能产生孤儿记录（如删除 product 后 order 仍引用 product_id） | 关键表（sales_orders→sales_products, sales_commissions→sales_orders）加 FOREIGN KEY + 启用 `PRAGMA foreign_keys=ON` |

### P3（轻微，可选修复）

| # | 缺陷 | 证据 | 影响 | 修复建议 |
|---|---|---|---|---|
| P3-1 | `get_user_orders` 不按 chat_id 过滤 | `core/db_repos/sales_repo.py:106-114` 只按 uid 过滤 | 同一用户在群 A 的订单会被群 B 管理员看到（设计选择） | 增加可选 `chat_id` 参数 |
| P3-2 | `_REPO_ATTR_MAP` 注释说"9 个 Repo"实际 10 个 | `core/database.py:1926` `logger.info("...9 个 Repo...")` | 日志失真 | 改为 10 个 |
| P3-3 | `memory_summarizer.py` 重复 ALTER TABLE 调用 | `core/memory_summarizer.py:409, 437` 都有 `ALTER TABLE user_profiles ADD COLUMN memory_summary` | 同一方法在两个地方重复加列逻辑，但幂等不会出错 | 统一到一个入口（如 shared_db.py） |
| P3-4 | `user_repo.update_conversation_turn` 每次调用都执行 2 次 PRAGMA 检查 | `core/db_repos/user_repo.py:412-413` 每次调用 `_safe_add_column` | 性能损失（每条对话都查 PRAGMA table_info 2 次） | 启动时一次性补列，运行时直接 UPDATE |

---

## 11. 关键发现（最多 10 项）

1. **数据库基础设施健康**：142 张表 = 文档声明 142 张表（零偏差），97 个索引，WAL+busy_timeout=30000+synchronous=NORMAL+cache_size=4MB+mmap=256MB 全部正确实装，无 `database is locked`（50 并发 orders + 200 并发 events / 0.04s 全部完成）。

2. **`_REPO_METHOD_MAP` 179 个方法注册零缺失零孤儿**：DB.__init__ 的 `_self_check_repo_methods()` 是真实实装的运行时强制自检，覆盖了 `verify_db_methods.py` 的设计意图（脚本不存在但防御有效）。

3. **sales_repo 12 方法全部注册**（CHANGELOG 声明 13 但实测 12），CRUD 测试 21 PASS / 1 FAIL / 4 WARN，重启持久化 4 项全过。

4. **P0 - `sales_orders.order_no` 生成规则有缺陷**：`f"ORD{now}{uid}{product_id}"` 不含唯一性后缀，同秒同 uid 同 product_id 下两单触发 `UNIQUE constraint failed`，并发测试 50 orders 只成功 10 个（40 个失败）。

5. **P0 - WriteQueue 写失败调用方完全无感知**：`_write_via_queue` 返回 `_FakeCursor` 而非 raise，`lastrowid=-1` 被调用方直接 `return -1` 视为成功，订单/商品/佣金写入失败时用户看到"成功"。

6. **P0 - v5.35.0 新模块 `INSERT OR REPLACE` 缺 NOT NULL 字段**（8 处）：表 `chat_settings`/`join_settings`/`group_commands`/`bot_settings`/`afool_member`/`super_afool`/`new_member_probation`/`group_report` 等的 `updated_at` 是 `INTEGER NOT NULL`，但模块代码 INSERT 没提供该字段，会触发 `IntegrityError`（当前因 ImportError 未暴露）。

7. **P1 - v5.35.0 新模块表名错误**（6 处复数化 + 14 处表完全不存在）：模块代码用 `group_reports`/`word_clouds`/`force_channels`/`valid_speak_records`/`group_todos`/`channel_links` 等不存在表名，`member_info`/`member_actions`/`global_ad_blacklist`/`user_points`/`chat_points_usage`/`bot_registry`/`group_registry`/`premium_usage`/`group_configs`/`config_templates`/`config_template_applications`/`content_archives`/`image_records` 等表完全不在 `_init_tables()` 中。

8. **v5.33.0 `conv_turn_count` / `conv_last_active` 修复 VERIFIED**：临时库 `_init_tables()` 成功执行无 OperationalError；`_safe_add_column` 8 处全部幂等；`user_repo.update_conversation_turn` 在 UPDATE 时显式赋值 `CURRENT_TIMESTAMP`（合法用法）。

9. **v5.33.1 `_blacklist_dirty` 标记机制 VERIFIED 但有 P3 caveat**：6 项测试 5 PASS / 1 FAIL；`_blacklist_model` 重复拉黑同一模型仍设置 dirty（在 if 块外），当前因调用方去重未暴露。`save_config_task` 调度间隔 1 小时（P2），模型拉黑后最多 1 小时才落盘。

10. **`scripts/verify_db_methods.py` 文档失真**：AGENTS.md / runbook-ship-gate.md / CHANGELOG.md / version.py 均引用此脚本，但 `scripts/` 目录下不存在。`_self_check_repo_methods()` 启动自检是真实有效的等价机制，但文档应修订。

---

## 附录：审计方式与命令记录

### 实测命令

```bash
# 表数统计
python -c "import re; src=open('core/database.py',encoding='utf-8').read(); tables=re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)', src); print(len(set(tables)))"
# → 142

# Repo 方法自检（替代 verify_db_methods.py）
python -c "from core.database import DB; db=DB(':memory:'); ..." 
# → Total _REPO_METHOD_MAP entries: 179, Missing: 0, Orphaned: 0

# 临时库 CRUD 测试
python runtime/audit-reports/_tmp_sales_crud_test.py
# → PASS=21, FAIL=1, WARN=4, TOTAL=26

# 并发测试
python runtime/audit-reports/_tmp_concurrency_test.py
# → 50 orders / 0.01s, 200 events / 0.03s, 0 database is locked

# blacklist dirty 测试
python runtime/audit-reports/_tmp_blacklist_dirty_test.py
# → PASS=5, FAIL=1, WARN=0, TOTAL=6

# 隔离测试
python runtime/audit-reports/_tmp_isolation_test.py
# → PASS=6, FAIL=2, WARN=0, TOTAL=8

# schema 检查
python runtime/audit-reports/_tmp_schema_check.py
# → 实际表数: 142, 索引数: 97, FOREIGN KEY: 0, CHECK: 5

# 文档一致性
python scripts/doc_consistency.py
# → 全部文档数字与代码一致
```

### 临时测试文件（已清理）

- `_tmp_sales_crud_test.py` — sales_repo 12 方法 CRUD + 幂等 + 非法输入 + 不存在记录 + 重启持久化
- `_tmp_isolation_test.py` — 多群隔离 + chat_settings INSERT OR REPLACE NOT NULL 验证 + order_no UNIQUE 冲突
- `_tmp_blacklist_dirty_test.py` — `_blacklist_dirty` 标记机制 6 项验证
- `_tmp_schema_check.py` — 表数 / 索引数 / journal_mode / busy_timeout / 外键 / CHECK 约束统计
- `_tmp_concurrency_test.py` — WriteQueue 启动后 10 线程并发 create_order + 20 线程并发 track_sales_event

所有临时测试文件在审计完成后已删除，仅本报告保留。
