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

### 5. 广告资料审核的活入口、数据时序与旧头像兜底互相打架
- 问题：广告资料曾因入口断链漏审；接入 NudeNet 后，两张正常头像又在名字正常、Bio 为空时被单独永久禁言。
- 根因：`restricted→member` 补审和四信号主链修好后，`check_avatar_marketing()` 后面仍串着旧 PIL 尺寸/比例/文件大小/平均颜色兜底；高置信模型放行后，颜色启发式反而能独立翻盘执法，其他旧入口也仍在调用它。
- 解法：白名单/管理员免检前置并保留资料补审；头像执法只采纳高置信明确暴露、广告文字/二维码或批量相似证据；所有入口移除弱启发式执法调用，兼容接口固定只记录并放行。
- 预防：头像审核回归必须同时覆盖正例、普通人物/玩偶反例和“高置信模型放行但旧兜底命中”顺序反例；尺寸、比例、文件大小、肤色等统计特征永远不能成为广告处置证据。

### 6. AI 失败兜底尴尬
- 问题：AI 调用失败时返回拟人化尴尬文案，体验差且无意义。
- 根因：兜底文案写死且过度拟人。
- 解法：未知/普通/特殊模式全失败直接静默；转化/联系模式只给固定入口。
- 预防：AI 失败路径默认静默，禁止新增拟人兜底文案。

### 6.1 多套成交提示互相覆盖导致跳步和硬推
- 问题：主回复、增长实验、连续对话追加和群商业搭讪各自决定 CTA，价格咨询会跳过预览，普通聊天按固定轮数突然下单，群内回复后又额外私聊，定制话术还会承诺不存在的表单或交付。
- 根因：成交目标没有单一判定源，随机性被错误用来决定业务路径；生产旧人设和提示词仍按聊天轮数强推。
- 解法：统一 `none/preview/subscribe` 单目标判定并让所有提示、正文校正和按钮消费同一结果；随机性只改变人设措辞，低频主动推进最多到预览；移除无上下文追加回复和群后私聊。
- 预防：新增自动回复入口必须回归概念咨询、价格/内容、明确下单、拒绝、近期 CTA 去重、私聊零按钮、群聊单按钮七类场景；禁止用对话轮数直接决定销售目标。

### 6.2 同步冲突副本进入动态部署清单
- 问题：同步盘生成的 `*.sync-conflict-*.py` 虽已被 Git 忽略，但部署脚本递归扫描所有 `.py`，仍可能把冲突副本上传到生产。
- 根因：版本控制忽略规则与部署文件收集器是两套独立边界，部署器没有显式排除同步冲突文件。
- 解法：部署清单按文件名排除 `.sync-conflict-`，并把根目录六件套纳入同一发布清单，避免运行版本与服务器文档版本漂移。
- 预防：动态发布清单必须有回归测试，证明临时/冲突副本不进入生产且版本真相文件会同步。

### 6.3 拒绝短句漏判与模型虚构销售事实
- 问题：生产探针中“算了不用了”仍被 `convert` 兜底推进到预览；真实模型回答价格时自行声称“4K原档、独家动态”。
- 根因：拒绝词表只覆盖“不需要了”等长短句；提示词只能降低幻觉概率，没有发送前的业务事实门禁。
- 解法：补齐“算了/不用了/暂时不用”等退出表达；成交回复发送前移除未经证实的价格、画质、独家权益、定制能力和交付承诺，再由确定性代码补唯一入口。
- 预防：生产验收必须把拒绝反例和真实模型销售事实一起检查，不能只断言 CTA 指向正确。

### 6.4 新人验证数字污染聊天统计与 AI
- 问题：群里新人回复算术验证码时，纯数字先进入对话历史、last_active、画像、消息快照、积分和 AI，既污染统计又可能触发尴尬回复。
- 根因：验证码检查位于 P0，但通用上下文与采集逻辑在 P0 之前已经执行。
- 解法：群内纯数字先交给验证码模块，随后无条件在所有聊天采集与 AI 前短路；无活动验证会话也静默忽略，含文字的正常数字聊天继续处理。
- 预防：系统/验证流量的识别必须早于任何业务统计或模型调用，不能只把验证码 handler 排在 AI 前。

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

### 20. VPS→本地反向同步覆盖已修代码 + watchdog 消失仍误报正常
- 问题：Git `main` 中 4 个模块恢复为断链 import，但生产热修文件仍正确；同时生产 watchdog cron 消失 12 天，loop-monitor 却因只把 ERROR/CRITICAL 纳入最终建议而输出 `all normal`。
- 根因：反向同步未做“生产文件 vs 已验证 commit”语义比较，直接用 VPS 文件覆盖本地；监控各层的 WARN 未统一汇总，且 cron 缺失本身未设 WARN。
- 解法：以生产正确文件和历史已验证 commit 交叉还原模块，保留 50 个回归测试；EXPECTED_VERSION 改读 `version.py`；L1-L6 任一非 OK 都进入 NEEDS_REVIEW，cron 缺失显式 WARN；生产备份 root crontab 后恢复每 2 分钟 watchdog。
- 预防：禁止无 diff/测试的 VPS→本地反向覆盖；反向同步必须先比较 hash/行为测试并以 commit 为唯一部署源；监控最终结论必须聚合 WARN，且自愈链要验证“调度入口 + 实际二次触发”。

### 21. 播报内部说明泄漏、问候僵硬且缺按钮、迁移监控假警报
- 问题：新闻正文向用户展示“多源汇总/均衡筛选/TrendRadar”等内部聚合说明；早午晚问候没有联系按钮，生产 08:05 两个模型连续各超时 30 秒后发出短而生硬的兜底；福利/定制只命中静态黑话，无法按独立提示词润色或统计；02:46 出现数据库迁移阈值 WARN。
- 根因：两套新闻渲染器都把 `source_name` 映射成可见角标；问候发送函数未透传 `reply_markup`；时段提示词过长且强制虚构生活场景/营销钩子，部分配置又会整块覆盖默认提示词；生产模型池未声明思考能力，实时任务误用仅支持思考模式的模型，两个 30 秒请求连续超时；关键话题链路没有规则级提示词、输出有效性门禁和埋点；写队列零吞吐时把任一 pending 瞬时值硬算成 999 秒延迟。
- 解法：来源仅保留内部日志；问候与新闻所有格式/降级路径统一联系按钮；四时段改为短提示词、禁止编造及固定套路，并明确禁止杜撰 Mory 本人经历，移除问候固定尾段；新增输出质量门禁，内部字样、引擎异常和已确认的抒情/疗愈套话一律回退可信底稿，默认提示词与局部配置合并；模型池增加 `enable_thinking` 能力标记，实时场景跳过仅思考模型并对已验证模型显式关闭思考；福利/定制增加规则级必含词/禁用词、受约束 AI 润色、可信底稿回退和 30 天无原文统计；零吞吐样本不推算平均延迟，交由持续积压指标判断。
- 预防：回归测试同时覆盖 HTML/Rich 渲染、问候按钮、AI 异常回退、匿名统计、局部配置合并和零吞吐监控；生产验收必须包含真实短提示词模型调用与用户可见消息预览，不能只看服务 active。

### 22. 联系 Mory 与自助售卖机器人身份混用
- 问题：早中晚问候和新闻全部显示“联系 Mory”类按钮，但实际统一跳转到自助售卖机器人 `@MorychannelBot`，用户看到的动作与落点不一致。
- 根因：公共按钮函数把“联系本人”和“自助下单/订阅”合并成一个概念，名称、文案和 URL 又全部硬编码；定点播报配置复制了同一错误入口；生产配置还保留历史播报 ID，不能只按本地示例 ID 更新。
- 解法：保留兼容调用但按场景分流：晨间/晚间及定制确认跳转 `@Moryfansbot` 联系 Mory；午间/新闻/夜间及福利/开通明确标注自助下单或订阅并跳转 `@MorychannelBot`。生产配置按 `id` 或 `period` 语义匹配，并保留原启用状态、时刻和其他运行字段。
- 预防：按钮回归测试必须成对断言“用户可见文案 + URL”，禁止只测按钮存在；新增入口前先确认机器人业务身份；列表配置上线前必须读取线上真实 ID，更新时以稳定语义字段兜底且半匹配立即熔断回滚。

### 23. 新闻源固定 403、10 条数据被截成 5 条、Telegram 轮询异常重复刷屏
- 问题：生产每次新闻任务固定出现微博/知乎/澎湃直连 403；抓取层已有 10–12 条，但 AI 提示词和两套排版器只保留 5 条；选题常被科技、财经占据；Telegram getUpdates 的 502 和读取超时被 SDK 重复打印整段堆栈。
- 根因：把反爬直连与可用聚合接口同时放进常态源池；NewsNow 同域 8 路并发会触发整域超时/限流；“10 条”只改了抓取上限，未同步 AI 输出契约、兜底和 HTML/Rich 渲染，且生产 `PROMPT_TEMPLATES` 仍以 5 条旧模板覆盖代码默认、类目上限还会把已有候选截成 6 条；分类轮询不参考榜单位置或来源权重，科技/财经配额合计过高；TeleBot 默认异常处理对同一轮询故障在 threaded polling 和 infinity polling 两层记录。
- 解法：VPS 逐源探测后删除三条稳定 403 直连，接入返回 200 的 NewsNow 头条/澎湃/早报；NewsNow 同域并发限制为 2，部分源失败仅记汇总，首源不足 10 条继续后备源并可合并，全部来源仍不足 10 条则不发送并进入既有重试；按来源权重、榜单位置、类目和单源上限选 10 条，类目集中时逐级放宽但科技≤1、财经≤2；AI/真实标题兜底/HTML/Rich 全链统一 10+1，不满足 10+1 契约的生产旧覆盖自动忽略，AI 条数不合格或复述 NewsNow/TrendRadar/类目来源标签时直接回退；只接管 getUpdates 的 5xx/连接超时并做 1/2/4/8/15 秒退避和限频日志，sendMessage 等业务错误继续抛出。
- 预防：新闻回归必须同时断言活跃源 URL、同域并发上限、稀疏源仍补齐 10 条、首源不足继续后备源、10 条完整渲染、类目配额、来源信息不泄漏和 AI 少写回退；生产源变更必须从 VPS 实测状态码、并发行为与条数；轮询韧性测试必须证明只处理 getUpdates，禁止全局吞异常。

### 24. 后台候选条数与用户可见条数混为同一契约
- 问题：v5.35.8 为解决来源不足和选题偏科，把抓取、AI 输出、排版展示都统一成 10 条，虽然信息完整，但用户实际阅读卡片过长。
- 根因：把“后台需要足够候选才能保证综合性”和“用户应该看到多少条”视为同一个数字，缺少候选层与展示层的独立契约。
- 解法：后台继续抓取、去重并均衡筛选 10 条，AI 再按公共影响、时效性和进展明确度挑最重要 5 条；可见输出、HTML/Rich、门禁和真实标题兜底统一 5 条 + 1 句观察。
- 预防：以后调整新闻条数必须分别确认候选数、AI 输出数、渲染数和兜底数；候选丰富度不等于用户可见篇幅。

### 25. 人设碎片把正常聊天推成动作旁白
- 问题：普通“在吗”会回复“（托腮看窗外，听到提示音才回过神来）在呀……”之类舞台化内容，显得傻且爱加戏。
- 根因：旧 `BASE_PERSONA` 明确鼓励 `*动作*` 和“肢体暗示”；默认 `PERSONA_FRAGMENTS.body_language`、反应风格、时段情绪、场景模板又持续注入歪头/托腮/窗边/咖啡/刚睡醒等虚构画面；原后置过滤只防 AI 身份泄露，不处理动作旁白。
- 解法：保留清冷/傲娇/温柔、亲密度和群聊/私聊差异，但所有动态碎片改为语气与回应策略；`body_language` 兼容读取但永不注入；旧动作指令行自动移除；最终输出合同禁止括号/星号动作、心理旁白与虚构现场；后置过滤识别舞台化片段，混合回复删旁白保正文，纯动作回复触发重试；历史语义缓存命中也先过滤，新回复只缓存清理后的正文。
- 预防：人设只能描述“怎么说”，不能描述“正在做什么”；输出门禁必须覆盖模型响应与缓存命中两条返回路径；回归同时覆盖用户原始问题样例、纯动作、正常事实括号、旧配置残留、缓存和真实 `ask()` 返回链路。

### 26. FAQ真实命中链类型错配 + 未回答问题没有运营回执
- 问题：`FAQ_AUTO_REPLY_ENABLED=true` 时，知识库即使命中也可能静默退回普通AI；AI答不上来的消息没有明确人工/自助入口，管理员每天也收不到具体待优化问题。
- 根因：`QuestionRepo.search_faq()` 返回按优先级排序的列表，`_try_faq_match()` 却直接调用 `.get()` 当单条字典使用，异常被兼容层静默吞掉；普通群聊问题仍受随机回复率限制；`ai_reply_summary` 没有未解决状态，原FAQ任务只报告候选数量。
- 解法：兼容列表/字典返回并选最高优先级FAQ；问题追踪开启时明显问句强制进入P10；FAQ未命中且AI返回空值、统一故障兜底或不确定表达时，发送“联系 Mory / 自助下单”同排双按钮，并以 `[UNRESOLVED]` 标记摘要；每日23:50汇总待优化原问题及AI已答但FAQ未命中样本。
- 预防：Repo与调用方测试必须断言真实返回类型，不能只用理想化字典测试桩；用户侧兜底要同时验证文案、按钮文字和URL；运营闭环必须包含具体问题样本，不能只报“新增N个候选”。

### 27. 签到开关与连续奖励在代码、示例配置、Dashboard三处键名漂移
- 问题：Dashboard显示“签到已开启”或保存了连续3/7天奖励，Bot仍可能静默不签到，奖励也继续使用代码常量。
- 根因：业务代码只读 `CHECKIN_CONFIG.enable` 和固定 `BONUS_DAYS`，示例配置与Dashboard却读写 `enabled`、`streak_bonus`；Dashboard POST 还漏存 `streak_bonus`。
- 解法：业务代码优先读 `enabled` 并兼容历史 `enable`，连续奖励优先读 `streak_bonus` 并兼容 `bonus_3d/bonus_7d/...`；Dashboard GET规范化历史配置，POST同时同步新旧启用键和奖励键。
- 预防：配置项变更必须做“示例配置→Dashboard保存→业务代码读取”的往返测试，不能只验证面板返回200或JSON字段可见。

### 28. deploy_vps.py 把 --help 当成真实部署
- 问题：执行 `python deploy_vps.py --help` 并未显示帮助，而是直接进入生产部署；命令被外部超时终止后，保险路径只确认 Bot 恢复，Dashboard 留在 inactive。
- 根因：脚本没有命令行参数解析，`__main__` 无条件调用 `main()`；信号恢复只看一次重启命令返回，未逐个确认双服务和 health。
- 解法：增加 fail-close 参数门禁，`--help/-h` 只输出用法，任何未知参数以退出码 2 拒绝执行；本次生产改用 commit 字节级最小发布、备份和双服务 health 轮询完成恢复。
- 预防：生产脚本的帮助/未知参数必须是无副作用测试；部署验证必须逐个检查 `mory-assistant`、`mory-dashboard` 和 `/api/health`，不能把 restart 命令返回 0 当成双服务已恢复。

### 29. 新闻总结与事实脱节，粉丝群问候变成效率/编程建议
- 问题：新闻卡片第6行出现“议题交织、现实关切”等与5条事实无关的万能总结，正文末尾重复展示订阅机器人；午安问候出现“多线程、弹窗、静音通知、任务窗口”等技术/效率文案。
- 根因：新闻门禁只校验5+1条数，不校验观察与新闻实体的关联；HTML/Rich渲染器把订阅入口硬编码为发送者署名。问候完整替换模板绕过 `BASE_PERSONA`，旧 `PROMPT_TEMPLATES` 可继续注入效率/虚构场景，质量门禁和兜底池又没有拦截同类词；局部 `MODE_ROUTING` 覆盖整张默认映射，单池当前索引还可落到 code 专用模型。
- 解法：观察必须与可见头条/真实来源共享具体事实短语，万能空话直接回退前两条完整事实短句；卡片署名固定 `@MoryMateBot`，订阅按钮继续独立指向 `@MorychannelBot`。问候提取主助理身份/性格作为底色，旧模板缺少粉丝群新契约时自动忽略，技术词门禁与走心底稿双保险；合并默认/局部路由并跳过 code/coder 模型。
- 预防：播报回归同时断言事实关联、身份署名和CTA落点；问候回归必须覆盖截图原文、旧配置、主助理人设继承、兜底池和实际模型选择，不能只断言“LLM返回了非空字符串”。

### 30. 新闻第6行被误当成更准确的新闻总结
- 问题：即使第6行引用了具体新闻事实，用户看到的仍是另一句新闻总结，无法承担粉丝群立人设、促互动和承接定制沟通的作用。
- 根因：上一轮把“总结不相干”理解成“总结必须事实锚定”，继续保留了总结这一产品方向；AI 提示词、输出门禁和真实标题兜底都要求第6行复盘新闻。
- 解法：前5条与第6行职责拆开；第6行禁止总结/复述新闻，必须用第一人称，并从温情自白、邀聊、人格表达、定制沟通四类策略随机生成；AI 不合格时也从同一人工策略池随机回退。
- 预防：截图反馈先区分“内容质量错”还是“内容职责错”；播报测试必须明确断言尾语不复用新闻事实且覆盖多种人设/互动策略，不能只优化原有总结。

### 31. 对话只写记忆却不把近期上下文交给本轮意图和模型
- 问题：用户连续说“定制舞→就是这个味→喜欢这种风格→打港舞/服装/卡点变装”，Bot 每轮都像第一次看到，反复让用户看预览，始终不进入自助下单。
- 根因：`memory_summarizer` 虽记录消息，但 `ai_engine.ask()` payload 只有当前一句；`detect_keywords()`、`IntentRouter` 和增长实验也只看当前句；“定制”不在商业关键词；语义缓存只按当前句+mode，可能把同一句在不同上下文的旧回复复用；生产旧关键词和 `business_engage` 配置还可覆盖代码新默认。
- 解法：从 `conversation_telemetry` 读取同一用户/同一聊天最近30分钟3轮真实问答，分别注入意图路由和模型消息；缓存键加入同一上下文；规则识别定制锚点后的偏好确认与需求补充短句，并排除拒绝、普通闲聊、跨群和过期消息；明确定制走确定性承接和自助下单按钮，旧运行配置不能移除定制关键词或恢复“引导私聊/重复预览”提示。
- 预防：多轮对话回归必须从消息历史→意图→mode→模型 payload→缓存键→最终 CTA 整链验证；任何“记录了历史”都不能冒充“本轮实际使用了历史”；购买承接规则必须同时覆盖正例、拒绝、无锚点闲聊、跨 chat 和时间窗。

### 32. 把“仍是购买意图”误写成“每一轮都重复下单入口”
- 问题：多轮上下文能识别定制需求后，机器人却在“就是这个味”“喜欢这种风格”“补充服装/卡点要求”等每一轮都机械重复自助下单，私聊还叠加同义按钮；泛问入口时预览和下单也可能混在一轮。
- 根因：购买意图、回复内容和 CTA 投放频率被绑成同一个布尔值；确定性承接回复每次都拼下单文案，发送层又不区分私聊；直接入口和未解决兜底各自生成多个目标。
- 解法：从最近 6 条助手历史检测已投放的下单 CTA，除非用户明确再次索要下单入口，否则后续只承接风格和需求；私聊销售回复统一零按钮，非私聊至多一个目标；泛问入口只给预览，明确下单才给订单入口，未解决问题只给人工入口。
- 预防：多轮回归必须分别断言“购买意图仍成立”和“本轮是否应该再次投放 CTA”；完整链至少覆盖首次定制、连续确认、连续补充、明确再次索要链接、私聊零按钮、非私聊单按钮和预览/下单互斥。

### 33. 主 AI 合同正确，但静态、Function Calling 和自动任务旁路仍会旧话重演
- 问题：主对话已经做到先预览后自助，旧关键词早路由、销售工具、legacy 定时任务和 modular 任务仍可能直接报价格、导私聊、假装真人、制造稀缺或重复推销；效果统计还可能绕过隐私开关直接保存原文。
- 根因：回复合同只落在主 handler，早返回、缓存 Function Call、广播和两套任务实现各自维护模板；进化数据也有 Telemetry 与 growth optimizer 两条写入路径。
- 解法：用 ReplyContract v1 统一主路径与全部旁路；新闻/问候/叫醒无销售，欢迎一次预览，召回默认关闭，购物车开启后一次预览即取消；销售工具只保留兼容拦截，不再发送旧价目表/私聊引导。风格样本须人工审核启用且安全，所有效果写入默认清空原始用户/助手文本。
- 预防：回复变更必须对主 AI、静态早路由、Function Calling、legacy/modular 自动任务、配置覆盖、迁移/API 和所有遥测写入做全链检索与测试，不能用主 handler 绿色冒充整体统一。

### 34. 广告黑话已做繁简规范化，但规则词典仍缺语义变体
- 问题：显示名“看我賺米”连续发送“1天1w米”“微信业务日1w米人”，广告检测仍返回 `score=0`，没有进入统一封禁链。
- 根因：繁体“賺”虽已规范化为“赚”，用户名规则只覆盖“看简介”；收益规则只覆盖日入/日赚及部分“一天+数字+单位”组合，没有覆盖用“米”代替钱的紧邻缩写。
- 解法：用户名层增加繁简“看我赚/賺米”高置信组合，消息层增加“1/一天或日+数字+w/k+米”收益黑话；命中后沿用 `enforce_ad_user()` 永久禁言、删消息和双黑名单，不新建旁路。
- 预防：截图漏判回归必须同时覆盖原始繁体显示名、规范化结果、两条原文、处置阈值，以及跑步距离和普通业务讨论反例；不能只证明字符串被规范化。

### 35. 并行部署争抢 SSH 连接导致部分上传与版本号先行
- 问题：普通全量 SFTP 部署在上传阶段断线，保险重连也失败；随后 health 已显示新版本，但关键运行文件哈希仍不一致，多次核验卡在 SSH banner。
- 根因：同一 VPS 同时存在另一条发布流程，多个 Paramiko/SFTP/SSH 会话争抢 sshd 连接槽；非原子全量上传先覆盖根版本文件，断线后留下“版本已新、代码未齐”的部分状态。
- 解法：停止重复重连，识别并等待并行流程；最终由带 `flock` 的单连接发布完成暂存哈希、备份、原子替换、双服务重启、health 和发布后哈希，不再用 health 版本号单独冒充完整部署。
- 预防：生产发布必须使用全局部署锁和 staging→hash→backup→atomic replace→restart→hash 顺序；检测到并行发布时只读等待，连接抖动后清理本机遗留会话并设置冷却窗口；验收至少核对行为相关文件哈希与业务探针。

### 35. 新闻兜底把“自然互动”写成固定模板腔
- 问题：新闻第 6 行出现“不急着下结论，群里有不同想法就说说”，与新闻本身无关，像强行要求群友表态。
- 根因：生产本轮 AI 不可用后走真实标题兜底，而兜底仍从“讨论/观点”文案池随机取句；此前只调整尾语策略，没有移除新闻卡必须互动的错误职责；新闻门禁还把“价格、福利”等普通事实词当成营销入口，可能静默丢弃合法标题。
- 解法：删除随机互动池；AI、输出门禁和真实标题兜底统一使用固定时效说明“以上是本次刚刚更新的最新新闻。”；抓取请求增加 no-cache 与时间戳参数；门禁只拦截下单、订阅、私聊、链接等真实入口动作，保留合法事实词。
- 预防：信息卡片只承担信息职责，互动、转化和人设栏目独立设计；生产验收必须覆盖 AI 失败兜底，因为截图问题实际来自该路径；内容门禁按动作与结构判定，不能用“价格、福利”这类泛名词做一票否决。

### 36. 用户要换栏目，却连续在旧新闻产品里修辞
- 问题：老板明确觉得新闻栏目整体尴尬后，连续多轮只修改第 6 行总结、互动尾语和“最新新闻”说明，仍保留新闻这一产品职责。
- 根因：把“内容方向不对”误判成“新闻文案质量不够”，没有及时确认老板是在否定句子还是否定整个栏目。
- 解法：早、午、晚三档新闻任务整体下线，替换为早间风水、午间塔罗和晚间能量签；内容从人工约束池按日期稳定随机，旧定向撩人塔罗默认关闭。
- 预防：截图反馈连续否定两次时，必须重新判断栏目职责；产品方向已被明确替换后，不再继续优化旧栏目内部措辞。

### 37. 群公共播报写成个人心理教练
- 问题：新闻替换为风水和塔罗后，卡片仍出现“给你的问题”“真正的选择交给你”、情绪判断和自责等私人化话术，放进群里像突然对某个人说教。
- 根因：内容池沿用了私聊式走心文案，没有先定义群播报的公共受众合同；“温情”被误写成了个人心理干预。
- 解法：三档栏目统一为短字段结构：风水只播宜忌/方位/参考色，塔罗只播牌面/关键词/适合/避免，晚间只播宜忌/明日准备；页脚只保留公共娱乐说明。
- 预防：群播内容回归必须拦截第二人称提问、个人情绪/内心判断和说教动作，并验证任何群成员看到都能成立。

### 38. “群通用”被误解成删到只剩四行万能短句
- 问题：为避免对个人说教，把三档卡片全部削成标题、四个短字段和同一句免责声明；黄历没有农历/冲煞/节气，塔罗只有一张牌，晚间仍是宜忌，三个时段既不专业也不形成不同产品。
- 根因：只做了措辞风险收缩，没有从信息来源、栏目结构、随机空间、互动目标和转化动作重新设计；用模板一致性代替了产品一致性。
- 解法：早间接入真实历法库，午间使用三张无重复大阿卡纳牌阵，晚间实现本卦/动爻/之卦；分区排版并加入受约束的组合解读；CTA 每卡严格一个，三个目标按日轮换且与正文一致。
- 预防：群通用不等于内容空泛。播报验收必须同时检查真实数据来源、时段差异、组合随机性、可读排版、同日幂等和 CTA 一致性；专业基础事实不用 LLM 自由生成。

### 39. 能力边界被重复写成用户可见免责声明
- 问题：三档卡片已经是轻量民俗栏目，仍在每张末尾重复一段“仅供参考/不替代判断”，内容显得冗长机械；私聊同类请求若继续落入通用 AI，还会产生不必要的模型 Token。
- 根因：把内部内容边界直接复制到每次用户输出，没有区分产品规则与可见正文；缺少位于 LLM 前的确定性私聊路由。
- 解法：HTML/Rich 与内容 payload 同时移除固定免责声明，组合解读改为直接行动建议；私聊明确风水、塔罗、算卦请求由本地日期稳定随机引擎提前回复并记录 `local_zero_token`，普通文化讨论不抢答。
- 预防：安全边界由数据源、措辞门禁和测试保证；除非确有高风险场景，不把同一说明机械附在每条轻量内容后。新增本地自动回复必须验证默认关闭、群聊不触发、讨论反例不触发及 AI 未被调用。

### 40. 明显彩票交易黑话未进词库，安全入口把广告交给普通 AI
- 问题：账号连续发送“六彩合单子有量，找靠谱庄”“港澳1-49特码有量，有收的庄吗？”，广告检测只记录开始检测，没有命中、删除或禁言，第二条继续进入普通 AI 回复。
- 根因：灰产规则只有“赌博/盘口”等直白词，没有覆盖“特码、六彩合、六码名单、有量、找庄”这套交易黑话；零分消息只能依赖后续重复模式，不能在首条调用统一处置。
- 解法：新增“彩票标识 + 有量/收量/找庄”的高置信组合规则，权重 4；首条直接走 `enforce_ad_user()`，永久禁言、删除消息并写双黑名单。
- 预防：截图漏判必须把截图原文和同日生产原文同时纳入回归，并补普通港澳、名单、农庄和新闻语境反例；还要断言首条进入统一处置，不能只测最终字符串评分。

### 41. 明确订阅被旧商业搭讪旁路截断，发送失败仍误报成功
- 问题：用户在群里回复 Mory 的预览消息并问“怎么订阅”，系统识别到商业关键词却没有给自助下单正文和按钮。
- 根因：P7.5 在 P10 前抢先消费 convert 消息，先等待无历史的模型生成；生产 `mory_bot` 没有该旁路假定的 `.bot` 属性，实际群回复返回 `None`，但 `engage()` 仍入库并报“商业搭讪成功”，dispatcher 随后无条件 `return True`，真正的 P10 成交链永远没机会执行。
- 解法：明确订阅/开通目标在 P7.5 前判定并交回 P10；“怎么订阅”等直接入口问法结合近期预览历史生成安全人设承接，群聊挂唯一自助下单按钮且不等待模型；P7.5 只有拿到真实发送结果才可入库和返回成功，失败继续主链。
- 预防：成交回归不能只测 `resolve_conversion_target()` 和按钮构造，必须覆盖 P7.5→P10 的优先级、真实发送返回值、模型不调用、正文目标和按钮 URL；任何“已处理”分支都必须由真实发送回执驱动。

### 42. 明确订阅修通后仍只有一条长模板，近义问法覆盖不足
- 问题：虽然“怎么订阅”已经能给自助下单，但连续询问总是同一句，显得像客服模板；“咋订阅、订阅怎么弄、会员怎么开、开通一下、付费入口、繁体订阅”等自然变体覆盖不完整。
- 根因：确定性成交回复只有群聊/私聊各一条文本，意图词也分散在多份局部枚举里；修复链路时只保证了目标正确，没有把短句多样性、近期去重和近义表达矩阵作为同一合同。
- 解法：按群聊/私聊及有无近期预览建立简短人设回复池，选择时排除最近 6 条助手原句；统一扩展订阅、开通、会员、下单、付费、付款及繁体入口表达，P10 仍以统一 `conversion_target` 决定能否成交。
- 预防：成交文案回归同时断言近义表达矩阵、连续两次不重复、长度上限、群聊单按钮、私聊零按钮和普通商品反例；语气随机不得覆盖业务目标判定。

### 43. 行为追踪记录被启动扫描当成已确认广告
- 问题：部署重启后，正常的“怎么订阅”被启动追溯扫描删除，群内还出现 Bot 发送后删除“.”造成的删除提示。
- 根因：数据库模式把 `ad_suspicious_users.messages` 中所有消息都当广告，未看单条分数或确认标记；无记录时甚至按 ID 范围盲删，且查询未限制 30 分钟窗口。
- 解法：逐条持久化 `is_ad`，只允许显式确认或单条评分达阈值的当前窗口记录删除；无证据 fail-close；扫描末条 ID 改从 `message_snapshots` 只读获取。
- 预防：追踪不等于定罪。任何历史删除或封禁都必须有独立逐条证据；确认误封须恢复 Telegram 权限并清四项残留，重查持久态；无法复核正文时只能安全跳过。
### 44. 数字/字母拆字广告绕过完整词规则，扩展过宽又会误封
- 问题：同日“一日 4oO+ / 9Oo+”为 0 分，且联系方式、兼职招聘、彩票、色情、跑分洗钱也可用数字或字母拆开关键词绕过。
- 根因：旧规范化只处理部分数字与繁体；若全局替换 O/I/l 或删除所有插入字符，又会把型号、英文、跑1分、刷1单和普通上门服务误判。
- 解法：先做 NFKC；收益形近数字只在时间+金额语境转换，六类模板分别要求强语义锚点；歧义词再要求交易/薪酬/联系方式第二锚点，并移除“上门”单独定罪。
- 预防：每类规则必须同时具备生产式正例、反向语序、首条统一处置和歧义反例；禁止全局 leetspeak 替换或用单个日常词直接封禁。
