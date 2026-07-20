<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# AI 调试病历（去重重写）

> 模板：**问题 | 根因 | 解法 | 预防**。完整历史（截至 2026-07-06）已归档至 `docs/archive/AI_DEBUG_HISTORY_archive_20260707.md`。
> 本文件只保留反复出现、有结构风险的暗病；新增条目按模板追加，超 300 行先归档。

## 反复暗病清单

### 1. 部署脚本卡死导致服务长期停摆（外部超时强杀跳过 finally 重启）
| 字段 | 内容 |
|------|------|
| **问题** | `deploy_vps.py` 被 bash 工具超时(300s)杀死后，`finally` 不执行 → services stay `inactive(dead)`。同时 `finally` 引用未定义 `logger` → `NameError` 雪上加霜 |
| **根因** | `pip install -r requirements.lock` 参数 `timeout=300` 在网络下载时 socket 不触发超时 → 进程被外部 SIGTERM 硬杀 → `finally` 被跳过。停止服务(stop)和启动服务(start)相隔 170 行，中间全部是慢步骤(upload + pip + apt) |
| **解法** | (1) pip 安装前用 `import` 预检跳过（已满足直接跳过，无需网络）；(2) 注册 `signal.signal(SIGTERM, handler)` 在进程被杀前拉起服务；(3) `finally` 改用**全新 SSH 连接**重启（主连接可能已损坏）；(4) 启动后加 health 轮询（10×3s）确认真正起来 |
| **预防** | ① 任何长时间网络步骤(pip/apt)必须做 skip-if-satisfied 预检 ② finally 不能依赖主连接存活 ③ 信号兜底是最后防线 ④ 系统级 `restart=always` 或 systemd watchdog 可作为额外防护 |

### 3. 解封指令不生效（私聊路由吞掉）
- 问题：`/unban`、解封等指令在私聊场景下不触发完整解封链，用户权限未恢复；同名显示名盲选解封错人。
- 根因：解封入口注册过晚，被兜底分发器/私聊路由吞掉；显示名解析无候选去歧。
- 解法：`main.py` 在兜底分发前注册 `/unban` 专用 handler；解封前移 P5.6 早路由；同名显示名返回候选 ID 不盲选。
- 预防：新增解封类入口必须在 dispatcher 早路由注册，并回归私聊+群聊双场景。

### 4. 签到 / 打卡误封
- 问题：正常业务动作（签到、打卡、checkin）被广告资料层和延迟封禁累计误判为广告。
- 根因：业务动作未从广告检测入口排除。
- 解法：签到/打卡/checkin 不进入广告资料层与延迟封禁累计；解封统一清理 `blacklist`/`global_blacklist`/`mute_records`/`ad_suspicious_users`。
- 预防：新增"正常业务动作"清单需在广告检测前显式排除。

### 5. 广告资料层（Bio / emoji）误封
- 问题：群管理员 / 白名单用户被资料层检测误封。
- 根因：免检前置（白名单/管理员）排在 Bio/emoji 检测之后。
- 解法：白名单/群管理员免检前移到 Bio/emoji 检测之前；广告处置通知加"解封"按钮。
- 预防：任何检测层新增前，确认免检前置已在最前。

### 6. AI 失败兜底尴尬
- 问题：AI 调用失败时返回拟人化尴尬文案，体验差且无意义。
- 根因：兜底文案写死且过度拟人。
- 解法：未知/普通/特殊模式全失败直接静默；转化/联系模式只给固定入口。
- 预防：AI 失败路径默认静默，禁止新增拟人兜底文案。

### 7. 新闻 / 问候消息超时不删
- 问题：定时播报 / 问候消息发出后未清理，长期堆积。
- 根因：发送与清理链未同步接入。
- 解法：播报 / 问候发送须接入统一清理（burn_orphan）链路。
- 预防：新增播报 / 消息能力必须显式接入 dispatcher 与 burn_orphan。

### 8. burn_orphan 漏清 channel_tracking
- 问题：孤儿清理漏清 `channel_tracking` 表，脏数据累积。
- 根因：清理任务未覆盖该表。
- 解法：清理任务补充 `channel_tracking` 清理。
- 预防：新增数据表若会产生孤儿记录，必须同步接入 burn_orphan。

## 结构性风险（推断，附依据）
- 历史误封集中在"检测链与入口/清理链不一致"类问题（见上 3–7）。推断系统存在"新增能力未同步接入统一入口/清理"的结构性风险，新功能易重蹈覆辙。应对：所有新增检测/播报必须显式接入 dispatcher 与 burn_orphan，并加回归测试固化（依据：AI_DEBUG_HISTORY 多次同类 hotfix）。

### 9. Dashboard worker timeout
- 问题：生产 `mory-dashboard` 在 2026-07-07 08:31–08:33 出现连续 Gunicorn `WORKER TIMEOUT` / `SIGKILL`，服务自恢复但后台存在慢请求拖死 worker 的隐患。
- 根因：Dashboard systemd 使用 Gunicorn 默认 30 秒 timeout，后台页面包含数据库、SSH、审计等慢操作，2 worker 配置下容易被长请求占满。
- 解法：`config/mory-dashboard.service` 增加 `--timeout 120 --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100`，部署后重启 Dashboard 并复核 health / journal。
- 预防：Dashboard 新增慢接口必须设置应用层 timeout，生产巡检除 10 分钟错误外要抽查最近 1 小时 Dashboard journal。

### 10. 同机浏览器容器拖垮 Mory
- 问题：2026-07-08 生产机出现“各种报错不能用”，`mory-assistant`/`mory-dashboard` 表面 active，但整机 swap 接近打满，内核 OOM 杀过 `headless_shell`，Dashboard 出现 `WORKER TIMEOUT` / `SIGKILL`。
- 根因：同机 `dreamina-bridge` 容器内 Playwright/Chromium 进程占用约 1.8GiB 内存并触发 OOM，拖慢 systemd、调度任务和 Dashboard worker。
- 解法：重启 `dreamina-bridge` 释放内存，并用 `docker update --memory 1536m --memory-swap 1792m dreamina-bridge` 限制容器内存；同时修复 `conversion_events` 重复 `ALTER TABLE ADD COLUMN` 的日志噪声。
- 预防：生产巡检不能只看 Mory 双服务 active，必须同时看 `free -m`、`docker stats`、内核 OOM 日志和最近 1 小时 Dashboard journal。

### 11. Rich Message 400 "object expected as rich message"
- 问题：`send_rich_message_compat` 发送 Rich Message 触发 Telegram API 400 "object expected as rich message"，被迫 `rich_enabled = False` 硬编码禁用。
- 根因：`_html_to_rich_components` 返回 `List[Dict]` 组件列表，但官方 Bot API 10.1 期望 `rich_message` 参数是 `InputRichMessage` 对象 `{"html": "..."}`。
- 解法：`send_rich_message_compat` 改为：str → `{"html": str}`；list → 拼接 HTML 后包装；dict → 直接用。恢复 `RICH_MESSAGE_ENABLED` 从 config 读取。
- 预防：接入新 Bot API 方法时，必须先查官方参数类型定义，不能凭组件列表臆测对象格式。

### 12. 解封链路不对称（mute_records 写入缺失 + ad_suspicious_users 残留）
- 问题：解封后用户仍可能被再次触发禁封，且管理员无二次通知。
- 根因：①`_mute_forever` 只调 `restrict_chat_member` 不写 `mute_records`，但 `_remove_blacklists` 解封时清理 `mute_records`，路径不对称；②`_remove_blacklists` 不清理 `ad_suspicious_users`，而 `ad_detector.clear_user_tracking` 受 `if user_key in self.suspicious_users` 内存条件门控，Bot 重启后内存清空导致数据库残留；③`restore_ad_user` 无管理员通知。
- 解法：`_mute_forever` 增加 `INSERT OR REPLACE INTO mute_records`；`_remove_blacklists` 增加 `DELETE FROM ad_suspicious_users`；`restore_ad_user` 增加管理员通知。
- 预防：禁封/解封操作必须对称——写入什么表，解封就清理什么表；数据库层兜底清理不依赖内存条件门控。

### 13. SQLite ALTER TABLE ADD COLUMN 非常量默认值导致服务启动崩溃循环
- 问题：`v5.33.0` 部署后 mory-assistant 启动崩溃循环（`restart counter is at 7`），日志报 `sqlite3.OperationalError: Cannot add a column with non-constant default`。
- 根因：`database.py` 的 `_safe_add_column` 调用 `ALTER TABLE user_profiles ADD COLUMN conv_last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP`，SQLite 不允许 `ADD COLUMN` 带非常量默认值（`CURRENT_TIMESTAMP`/`RANDOM()` 等每次调用返回不同值），仅 `CREATE TABLE` 时允许。`conv_turn_count INTEGER DEFAULT 0` 因 `0` 是常量成功添加，`conv_last_active` 失败导致整个 `_init_tables()` 抛异常，DB 初始化失败 → 启动崩溃。
- 解法：`conv_last_active` 改为 `TIMESTAMP`（允许 NULL），由 `update_conversation_turn()` 在 UPDATE 时显式赋值 `CURRENT_TIMESTAMP`；`user_repo.py` 同步修改。
- 预防：①`_safe_add_column` 只用常量默认值（数字/字符串字面量），需要时间戳默认值的列改为代码层显式赋值；②`CREATE TABLE IF NOT EXISTS` 不受此限制，可继续用 `DEFAULT CURRENT_TIMESTAMP`；③新增列部署后必须验证 mory-assistant 启动成功，不能只看 `is-active`（systemd 会 restart 重试掩盖首次失败）。

### 14. AI 引擎黑名单（BLACKLISTED_MODELS）重启丢失 + 启动日志多池重复刷屏
- 问题：模型到期或没钱时 ai_engine 把模型加入 `BLACKLISTED_MODELS` 内存拉黑，但每次服务重启都重新加载过期模型 → 重新触发 `_is_model_expired → _blacklist_model` → 日志重复刷"🚫 模型拉黑"；4 个池都含同一过期模型时启动刷 4-5 行重复日志；Dashboard 显示的黑名单永远是旧的（config.json 没落盘）。
- 根因：`ai_engine._blacklist_model()` 只改内存 `self.config["BLACKLISTED_MODELS"]`，不主动调用 `save_config()`；`save_config_task.py` 逻辑为"仅 `CURRENT_MODEL_INDEX` 变化时才落盘"——黑名单变化但 idx 没变 → 永远不落盘；同时 `_filter_runtime_pool` 对每个池独立调用 `_blacklist_model`，无去重。
- 解法：①`_blacklist_model`/`_restore_model` 在拉黑/恢复时置 `self._blacklist_dirty = True`；②新增 `consume_blacklist_dirty()` 公开方法（线程安全，读后清标记）；③`save_config_task.execute()` 检测 dirty 标记，dirty 或 idx 变化任一触发即落盘；④`_filter_runtime_pool` 调 `_blacklist_model` 前先 `_is_blacklisted` 判重。
- 预防：①内存态配置变更必须配合"脏标记 + 异步落盘"机制，不能依赖"另一个任务偶尔保存"；②多池共享同一对象时，过滤逻辑必须考虑"已被其他池拉黑过"的情况，避免重复触发副作用（日志/告警/写盘）；③`save_config_task` 这种"按条件落盘"任务，触发条件变更（新增 dirty 标记）必须同步更新其文档注释。

### 15. v5.35.0 36 新模块 SQL 三类错误（表名复数/表名不存在/NOT NULL 缺字段）
- 问题：v5.35.0 一次性补 36 个新模块，import 修好后 SQL 层暴露 3 类错误：①表名复数化（`group_reports`/`word_clouds`/`force_channels` 等 12 处，实际表名单数）；②表名完全不存在（`member_info`/`global_ad_blacklist` 等 14 处未在 `_init_tables()` 建表）；③`INSERT OR REPLACE INTO chat_settings (chat_id, data) VALUES (?, ?)` 没提供 `updated_at` 但表定义 `INTEGER NOT NULL` → `IntegrityError`。
- 根因：①模块作者按"业务概念复数"命名 SQL 表名（如"举报"→`group_reports`），与 `_init_tables()` 中"单数表名"约定不一致；②模块作者假设了一些表（`member_info`/`bot_registry` 等）会被自动创建，但实际 `_init_tables()` 没建；③v5.35.0 新表 `updated_at INTEGER NOT NULL` 设计与模块代码"INSERT OR REPLACE 只更新部分字段"的写法不兼容（INSERT OR REPLACE 会用 NULL 覆盖未提供字段）。
- 解法：①统一扫描 36 模块 SQL，复数表名→单数（7 模块 20 处）；②`database.py:_init_tables()` 末尾补 25 张 `CREATE TABLE IF NOT EXISTS`（不破坏现有表结构）；③23 处 v5.35.0 新表 `updated_at INTEGER NOT NULL`→`updated_at INTEGER`（允许 NULL），5 处 pre-v5.35.0 NOT NULL 保留不动。
- 预防：①新增模块写 SQL 前必须 grep `_init_tables()` 真实表名，禁止凭概念命名；②模块使用 `INSERT OR REPLACE` 时，目标表的 NOT NULL 字段必须能在 REPLACE 路径全部覆盖，否则改成 `INSERT ... ON CONFLICT DO UPDATE` 只更新指定字段；③批量补模块时必须配套"import + DB 启动 + SQL 表名扫描"三连验证，不能只看 import 通过。

### 16. v5.35.0/16 模块 fetchone() 两次调用导致统计/健康度恒为 0
- 问题：`group_safety_center._get_rules_health` 规则健康度恒为 0；`stats_report.get_message_stats/get_user_stats/get_activity_stats` 三个统计方法 8 处数据全部返回 0，整个统计模块形同虚设。
- 根因：典型错误写法 `value = cursor.fetchone()[0] if cursor.fetchone() else 0`：Python 表达式先求值条件 `cursor.fetchone()`（消费第一行），条件成立时再调用 `cursor.fetchone()[0]`（游标已空，返回 None → `[0]` IndexError 或回退 else 0），条件不成立时走 else 0。结果**恒为 0**，与查询实际数据无关。Python 短路求值在三元表达式里会两次求值同一个函数调用，无缓存。
- 解法：①统一改写为 `row = cursor.fetchone(); value = row[0] if row else 0`（先存 row，再判 row）；②v5.35.2 修复 group_safety_center 1 处 + stats_report 8 处共 9 处。
- 预防：①任何 `cursor.fetchone()` 必须只调用一次并保存到变量，禁止在三元表达式条件 + 真值处两次调用；②同类风险写法包括 `len(cursor.fetchall()) if cursor.fetchall() else 0`（fetchall 也会消费游标）；③模块写完后必须用真实非空数据走一次 e2e，禁止只看"返回 0 不报错"就以为正常。

### 17. datetime.datetime.timedelta 多层引用 AttributeError
- 问题：`valid_speak.get_stats` 调用 `datetime.timedelta(days=days)` 报 AttributeError: module 'datetime' has no attribute 'timedelta'。
- 根因：模块顶部 `from datetime import datetime`，此时 `datetime` 是 `datetime.datetime` 类（不是模块）。后续 `datetime.timedelta()` 等价于访问 `datetime.datetime.timedelta` 类属性，但 timedelta 在 `datetime.datetime` 类上不存在，而在 `datetime` 模块上。命名空间污染 + 多层引用混淆导致。
- 解法：①顶部改为 `from datetime import datetime, timedelta`（显式导入 timedelta）；②调用处改为 `timedelta(days=days)`（不再用 `datetime.timedelta`）。
- 预防：①`from datetime import datetime` 后禁止写 `datetime.timedelta` / `datetime.date`，必须显式 import；②代码审查时 grep `datetime\.(timedelta|date|time|timezone)` 检查是否在 `from datetime import datetime` 上下文下被误用；③推荐统一写法 `from datetime import datetime, timedelta` 同时导入两个常用类。

### 18. v5.35.2 修复不完全导致 v5.35.3 二次修复（fetchone 漏修 + import 漏改 + eval 安全）
- 问题：v5.35.2 自称"全项目验收二轮修复"，但 GOAL MODE 9 阶段全量审计发现 5 个 P0 残留：①`stats_report.get_group_stats` 第 67/93 行 2 处 fetchone 两次调用 bug 漏修（v5.35.2 只修了同文件其他 8 处）；②`valid_speak.get_stats` 顶部 `from datetime import datetime` 漏改 `datetime, timedelta`（v5.35.2 CHANGELOG 称已修但实际只改了 `timedelta(days=days)` 调用处，import 没改 → NameError 模块即崩）；③`log_cleanup_task` 漏 `import os` 但用了 `os.path.dirname`，每天 04:00 触发即崩；④`security_center` 第 127 行 `eval(row[1])` 任意代码执行风险（用户可控的 factors 字段）；⑤`settings_api` 用 `logger.debug` 但没 import logger。
- 根因：①"全项目验收"未做静态代码审计，只跑了已有单测（已有单测没覆盖这些路径）；②修复时只看"测试通过"不看"代码语义正确"——`from datetime import datetime` 改成 `from datetime import datetime, timedelta` 是 import 行修改，CHANGELOG 写了但实际代码没改；③v5.35.2 修复 stats_report 时按 grep `fetchone()` 找的，但漏了 `cursor.fetchone()` 在三元表达式中的 2 处；④eval() 是历史遗留代码，多次审计都漏过。
- 解法：①GOAL MODE 9 阶段流程：阶段 0 基线 → 阶段 1 多智能体并行静态审计（2 subagent × 11 分区 A-K）→ 阶段 2 问题定级 P0/P1/P2/P3 → 阶段 3 修复策略 → 阶段 4 实施修复 → 阶段 5 验证（py_compile + doc_consistency + verify_db_methods + pytest）→ 阶段 6 部署 → 阶段 7 Git → 阶段 8 完工报告；②stats_report 第 67/93 行改 `row = cursor.fetchone(); value = row[0] if row else 0`；③valid_speak.py 顶部改 `from datetime import datetime, timedelta`；④log_cleanup_task.py 第 7 行加 `import os`；⑤security_center.py 加 `import ast` + `eval` → `ast.literal_eval`；⑥settings_api.py 加 `from core.logging_util import get_logger` + `logger = get_logger("settings_api")`。
- 预防：①"全项目验收"必须做静态代码审计（grep `eval(`/`fetchone\(\).*fetchone\(\)`/`except.*pass`/`import` 完整性），不能只跑单测；②修复 bug 时必须改 import 行 + 调用处两处，不能只改调用处；③CHANGELOG 写的修复点必须与 git diff 一一对应，写完跑一次 grep 确认；④历史 eval() 必须全量替换为 ast.literal_eval（安全且向后兼容 Python 字面量）；⑤GOAL MODE 9 阶段流程可作为"重大版本验收"的标准流程，比"快速修复+单测"更彻底。

### 19. v5.35.4 INSERT OR REPLACE 数据丢失模式（单行表主键不指定 + SELECT 无 WHERE）
- 问题：v5.35.0 引入的 6 个单行表模块（ad_blocker/bot_settings/bot_list/group_list/group_migration/super_afool）都存在数据丢失 bug：写入用 `INSERT OR REPLACE INTO tbl (data) VALUES (?)`，读取用 `SELECT data FROM tbl`（无 WHERE）。表象是"写入成功但读取总是返回旧数据或 None"。
- 根因：①表主键是 `id INTEGER PRIMARY KEY`（或 `bot_id`），但 INSERT 不指定主键 → SQLite 自增分配新 id → 每次写入新增一行；②SELECT 无 WHERE 子句 → SQLite 返回第一行（最早写入的）→ 永远读不到最新写入的数据；③"INSERT OR REPLACE"在没有唯一冲突时退化为"INSERT"，开发者误以为它会"替换"原行；④v5.35.0 验收时只跑了模块 import + 表创建，没跑读写往返测试（write→read→assert equal）。
- 解法：①单行表统一用固定主键 `id=1`：`INSERT OR REPLACE INTO tbl (id, data) VALUES (1, ?)`；②SELECT 加 `WHERE id=1`；③多行表（AUTOINCREMENT）也用固定 id=1 存储单条 JSON 数组（如 bot_registry/group_registry/migration_records）；④本轮同时修复 membership.set_membership SELECT 漏读 joined_at 字段、group_props.use_prop 缺参数、group_report sync 调 async 不 await 三类 P1。
- 预防：①新增"单行配置表"模式时必须用固定主键 `id=1` + `INSERT (id, ...) VALUES (1, ...)` + `SELECT ... WHERE id=1`；②"INSERT OR REPLACE"不等于"UPDATE"，没有冲突时就是"INSERT"；③新增模块必须跑读写往返测试（write→read→assert），不能只跑 import；④SQLite 表结构审查必须包括"主键策略"——单行表用 `id INTEGER PRIMARY KEY`（非 AUTOINCREMENT）+ 固定 id=1，多行表才用 `AUTOINCREMENT`；⑤sync 方法不能调 async 方法不 await（协程不执行），Python 不会报错但功能失效；⑥`return {'error': str(e)}` 给调用方会泄露内部信息，统一改 `'internal_error'` + `logger.error` 保留内部详情。
