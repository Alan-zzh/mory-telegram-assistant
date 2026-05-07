# 🔍 Mory小助理 全面代码审查报告（二次修订版）

**审查人**：测试与质量保障层  
**审查日期**：2026-05-01  
**审查版本**：v4.5.16  
**审查范围**：5个核心文件 + 2个关联文件（resource_manager.py, database.py）  
**修订说明**：二次深度审查后，纠正6个已修复问题，新增7个遗漏问题

---

## 📊 总览

| 文件 | 所属板块 | 审查结果 | 🔴严重 | 🟡中等 | 🔵轻微 |
|------|---------|----------|--------|--------|--------|
| main.py | 板块A（主控层） | ⚠️ 有条件通过 | 2 | 3 | 2 |
| core/ai_engine.py | 板块B（核心引擎层） | ⚠️ 有条件通过 | 2 | 3 | 2 |
| modules/auto_tasks.py | 板块C（功能模块层） | ⚠️ 有条件通过 | 1 | 3 | 2 |
| dashboard/app.py | Dashboard板块（可视化面板层） | ❌ 不通过 | 2 | 3 | 1 |
| core/deploy_utils.py | 板块D（部署层） | ✅ 通过 | 0 | 0 | 1 |

---

## ✅ 二次审查确认：已修复的问题（6个，从初版报告中移除）

以下问题在当前代码中已被修复，初版报告误报，现予以纠正：

| 原编号 | 原问题 | 修复状态 | 修复方式 |
|--------|--------|---------|---------|
| S-DH-01 | SQL注入（f-string拼接ORDER BY） | ✅已修复 | L298-306使用`order_by_map`字典映射，已符合避让表X-02的if/else分支要求 |
| S-DH-02 | XSS漏洞 | ✅已修复 | L643-646定义了`escHtml()`函数，对所有用户输入做HTML实体编码 |
| S-DH-03 | 登录计数器不持久化 | ✅已修复 | L90-116改用SQLite表`login_failures`持久化存储 |
| M-DH-02 | 数据库连接未统一管理 | ✅已修复 | L78-88使用Flask `g`对象 + `teardown_appcontext` |
| M-DH-03 | 自然语言配置返回敏感字段 | ✅已修复 | L444-445已过滤`_sensitive_keys` |
| M-DU-01 | sed命令shell注入 | ✅已修复 | L202-249改用SFTP读写.env文件 |
| L-DH-01 | AutoAddPolicy | ✅已修复 | L139改用`paramiko.WarningPolicy()` |
| S-AT-01 | 线程泄漏（APScheduler路径） | ✅部分修复 | L312-320 APScheduler路径已改用`scheduler.add_job`，但L321-332 fallback路径仍创建线程 |
| M-AT-01 | 重试线程无法取消（APScheduler路径） | ✅部分修复 | L200-207 APScheduler路径已改用`scheduler.add_job`，但L208-214 fallback路径仍创建线程 |

---

## 🔴 严重问题（7个，按严重程度排序）

### 1. S-DH-04 · Dashboard板块 · 用户搜索API变量名错误导致NameError崩溃
- **文件**：dashboard/app.py L307, L309
- **问题**：`api_stats_users`函数中，L285定义了`where_clause = ""`，但L307和L309的SQL语句中使用了`{where}`而非`{where_clause}`。`where`变量未定义，调用用户搜索API时会直接抛出`NameError: name 'where' is not defined`，**用户搜索功能完全不可用**
- **修复建议**：将L307和L309的`{where}`改为`{where_clause}`

### 2. S-DH-05 · Dashboard板块 · 配置修改forbidden_keys子串匹配过于宽泛
- **文件**：dashboard/app.py L397-398
- **问题**：`forbidden_keys = ['token', 'key', 'password', 'secret', 'api_key', 'admin_id', 'group_id']`，检查逻辑是`any(fk in key.lower() for fk in forbidden_keys)`。这意味着任何包含"key"子串的配置项都会被禁止修改，例如`keyword_triggers`、`BANNED_WORDS`中的"key"等合法配置项也会被误拦截
- **修复建议**：改为精确匹配或单词边界匹配，如`key.lower() in forbidden_keys`或使用正则`\b(key|token|...)\b`

### 3. S-AT-01 · 板块C（功能模块层） · fallback路径仍存在线程泄漏（APScheduler未安装时）
- **文件**：modules/auto_tasks.py L321-332
- **问题**：APScheduler路径已修复，但fallback路径（L321-332）仍为每条定时消息创建24h休眠线程。如果VPS上APScheduler未安装，每天10-15条×24h=240+线程常驻
- **修复建议**：将APScheduler从可选依赖改为必须依赖，或在fallback路径中也使用定时器替代长休眠线程

### 4. S-AT-03 · 板块C（功能模块层） · _job_burn_orphan中bot API调用未加锁
- **文件**：modules/auto_tasks.py L614, L638, L645, L654
- **问题**：`_job_burn_orphan`中多处调用`rm.bot.delete_message()`和`rm.bot.forward_message()`均未使用`rm.locked('bot')`，而其他函数（如`_send_and_track`）都使用了`rm.locked('bot')`。如果主线程同时在发送消息，可能导致API调用交错或异常
- **修复建议**：将所有`rm.bot.xxx()`调用包裹在`with rm.locked('bot'):`中

### 5. S-AI-01 · 板块B（核心引擎层） · API密钥日志泄露风险
- **文件**：core/ai_engine.py L794-797, L963
- **问题**：`Authorization: Bearer {api_key}`写入请求头，若日志系统记录请求头或异常堆栈，密钥会泄露
- **修复建议**：在logger配置中过滤Authorization头；确保requests异常不打印headers

### 6. S-AI-02 · 板块B（核心引擎层） · 响应时间字典无限增长
- **文件**：core/ai_engine.py L525-535
- **问题**：`_response_times`和`_slow_models`按模型名存储，过期模型换名后旧记录永不清理
- **修复建议**：添加定期清理机制，删除超过1小时未被访问的模型记录

### 7. S-MN-01 · 板块A（主控层） · 数据库操作竞态条件
- **文件**：main.py L791-875
- **问题**：P2活跃度更新（`db.upsert_user` + `db.add_points`）与P7视奸雷达（`db.set_cart` + `db.log_conversion_event`）的数据库操作之间无事务保护，同一用户两条消息被不同线程同时处理时可能积分计算错误
- **修复建议**：在database.py层面使用INSERT OR REPLACE + 事务保证原子性

---

## 🟡 中等问题（12个）

### 8. M-DH-01 · Dashboard板块 · 速率限制字典内存泄漏
- **文件**：dashboard/app.py L30-42
- **问题**：`_dashboard_rate_limits`以IP为key，虽有`_RATE_LIMIT_MAX_ENTRIES=10000`上限和LRU淘汰（L36-43），但过期记录只在超限时清理，日常运行中过期记录仍会堆积
- **修复建议**：在`_check_rate_limit`中每次都清理过期记录（而非仅在超限时）

### 9. M-DH-06 · Dashboard板块 · 概览API每次调用都建立SSH连接
- **文件**：dashboard/app.py L273
- **问题**：`api_stats_overview`每次被调用都执行`get_vps_status()`，该函数建立SSH连接执行3-4条命令。如果前端每30秒轮询一次，每小时120次SSH连接，非常消耗资源且响应慢
- **修复建议**：缓存VPS状态，每5分钟更新一次；或改为前端手动触发

### 10. M-MN-03 · 板块A（主控层） · 私聊转发Markdown链接不渲染
- **文件**：main.py L1025-1029
- **问题**：`bot.send_message(admin_id, f"...[{uname}](tg://user?id={uid})...")` 使用了Markdown链接语法，但`send_message`未指定`parse_mode="Markdown"`，链接不会渲染为可点击
- **修复建议**：添加`parse_mode="Markdown"`参数，或改用HTML格式

### 11. M-AT-04 · 板块C（功能模块层） · _notify_admin_system_failure缓存永不清理
- **文件**：modules/auto_tasks.py L271-278
- **问题**：`_notify_admin_system_failure._cache`字典用于5分钟去重，但过期条目从不清理。每种故障类型会留下一条永久记录，长期运行后字典会缓慢增长
- **修复建议**：在写入缓存时顺便清理超过10分钟的过期条目

### 12. M-AI-01 · 板块B（核心引擎层） · _build_persona方法过长
- **文件**：core/ai_engine.py L600-692
- **问题**：节日人格、模式叠加、新闻注入全挤一个方法（~90行），可维护性差
- **修复建议**：拆分为`_get_festival_persona()`、`_get_mode_persona()`、`_inject_news_content()`

### 13. M-AI-02 · 板块B（核心引擎层） · 新闻获取无连接池复用
- **文件**：core/ai_engine.py L213
- **问题**：每次`fetch_real_news()`创建7个线程+7个TCP连接，无Session复用
- **修复建议**：使用requests.Session()复用连接，或在模块级创建共享Session

### 14. M-AI-03 · 板块B（核心引擎层） · 重试最多80秒阻塞
- **文件**：core/ai_engine.py L739
- **问题**：10次重试×8秒退避=最坏80秒，对Telegram Bot响应太长
- **修复建议**：将max_attempts降为5，或根据tier层级限制重试次数

### 15. M-AT-02 · 板块C（功能模块层） · forward探测仍有429风险
- **文件**：modules/auto_tasks.py L601-625
- **问题**：Phase 2每10分钟探测3条消息=每天432次转发API调用，持续高频可能触发限流
- **修复建议**：将Phase 2频率降到每小时一次

### 16. M-AT-03 · 板块C（功能模块层） · 塔罗缓存清理边界问题
- **文件**：modules/auto_tasks.py L1019-1021
- **问题**：`_get_tarot_cache`中清理逻辑依赖`_tarot_cache_last_date`，如果某天无用户触发塔罗，旧缓存不会被清理（但实际影响很小，因为下次触发时会清理）
- **修复建议**：在`_job_tarot_flirt`入口处主动清空前一天缓存

### 17. M-MN-01 · 板块A（主控层） · 内存清理依赖消息触发
- **文件**：main.py L207-241
- **问题**：`_conv_tracker`和`_radar_cooldown`的清理只在收到消息时执行，深夜无消息时过期条目不清理
- **修复建议**：在auto_tasks.py的定时任务中增加定期清理逻辑

### 18. M-MN-02 · 板块A（主控层） · 异常处理重复创建ResourceManager
- **文件**：main.py L735-738, L750-753
- **问题**：`master_handler`和`_dispatch`的异常处理各创建一个新RM实例，每次异常都new一个
- **修复建议**：在模块级创建共享ResourceManager实例，异常处理时复用

### 19. M-MN-04 · 板块A（主控层） · 连续对话超时保护形同虚设
- **文件**：main.py L1004-1011
- **问题**：5秒超时检查在AI调用完成后才执行，只能决定是否使用结果，无法真正中断AI调用
- **修复建议**：使用concurrent.futures + timeout真正中断AI调用，或将追加逻辑移到后台线程

---

## 🔵 轻微问题（6个）

### 20. L-AI-01 · 板块B（核心引擎层） · mode映射缺失时无告警
- **文件**：core/ai_engine.py L340-349
- **问题**：新增mode忘记加映射会默认走`llm_standard`，无warning日志
- **修复建议**：在`_get_tier_for_mode`中增加warning日志

### 21. L-AI-02 · 板块B（核心引擎层） · TTS模型配置字段名不一致
- **文件**：core/ai_engine.py L1043-1044
- **问题**：TTS用`model`/`key`字段，其他池用`name`+全局API_KEY
- **修复建议**：统一使用`name`字段 + 全局API_KEY

### 22. L-AT-01 · 板块C（功能模块层） · 重复导入get_logger
- **文件**：modules/auto_tasks.py L851
- **问题**：文件顶部已导入，L851函数内又导入一次（注意：当前代码中L851是`_job_channel_views`函数，该函数内无重复导入，此问题可能已在某次更新中修复）
- **修复建议**：确认是否仍存在，如不存在则关闭

### 23. L-AT-02 · 板块C（功能模块层） · 旧版循环任务串行执行
- **文件**：modules/auto_tasks.py L1493-1544
- **问题**：`_legacy_task_loop`中一个任务卡住阻塞后续所有任务
- **修复建议**：为耗时任务添加超时保护

### 24. L-MN-01 · 板块A（主控层） · .env解析不支持多行值
- **文件**：main.py L110-121
- **问题**：手动解析不处理`KEY="value\nnewline"`格式
- **修复建议**：使用python-dotenv库替代手动解析

### 25. L-DU-01 · 板块D（部署层） · VPS配置下载失败时静默忽略
- **文件**：core/deploy_utils.py L88-93
- **问题**：可能导致空配置覆盖VPS上的有效配置（但L104-110已有空配置保护逻辑）
- **修复建议**：下载失败时打印warning日志

---

## 📊 各板块问题统计（修订版）

| 板块 | 🔴严重 | 🟡中等 | 🔵轻微 | 合计 | 审查结果 |
|------|--------|--------|--------|------|---------|
| Dashboard板块（可视化面板层） | 2 | 2 | 0 | 4 | ❌ 不通过 |
| 板块A（主控层） | 1 | 4 | 2 | 7 | ⚠️ 有条件通过 |
| 板块B（核心引擎层） | 2 | 3 | 2 | 7 | ⚠️ 有条件通过 |
| 板块C（功能模块层） | 2 | 3 | 2 | 7 | ⚠️ 有条件通过 |
| 板块D（部署层） | 0 | 0 | 1 | 1 | ✅ 通过 |

---

## 🚨 最紧急修复TOP 3

1. **S-DH-04**（Dashboard板块）—— 用户搜索API变量名错误，搜索功能完全崩溃，NameError
2. **S-DH-05**（Dashboard板块）—— 配置修改拦截过于宽泛，合法配置项被误禁
3. **S-AT-03**（板块C）—— bot API调用未加锁，可能导致消息发送异常

---

## 📢 各板块需修复问题清单（修订版）

### Dashboard板块（4个问题，最紧急）
- S-DH-04: 变量名错误 → `{where}`改为`{where_clause}`
- S-DH-05: forbidden_keys过宽 → 改为精确匹配
- M-DH-01: 速率限制清理不及时 → 每次都清理过期记录
- M-DH-06: SSH连接太频繁 → 缓存VPS状态

### 板块A（主控层）（7个问题）
- S-MN-01: 数据库竞态 → 使用事务
- M-MN-01: 内存清理依赖消息 → 添加定时清理
- M-MN-02: 重复创建RM → 模块级共享实例
- M-MN-03: Markdown链接不渲染 → 添加parse_mode
- M-MN-04: 超时保护无效 → 用futures真正中断
- L-MN-01: .env不支持多行 → 用python-dotenv

### 板块B（核心引擎层）（7个问题）
- S-AI-01: 密钥日志泄露 → 过滤Authorization头
- S-AI-02: 字典无限增长 → 添加定期清理
- M-AI-01: 方法过长 → 拆分子方法
- M-AI-02: 无连接池 → 使用Session复用
- M-AI-03: 重试80秒阻塞 → 降低max_attempts
- L-AI-01: mode映射无告警 → 添加warning
- L-AI-02: TTS字段不一致 → 统一用name

### 板块C（功能模块层）（7个问题）
- S-AT-01: fallback线程泄漏 → APScheduler改为必须依赖
- S-AT-03: bot API未加锁 → 包裹rm.locked('bot')
- M-AT-02: forward探测429风险 → 降低频率
- M-AT-03: 塔罗缓存清理 → 主动清空
- M-AT-04: 通知缓存不清理 → 写入时清理过期
- L-AT-01: 重复导入 → 确认并删除
- L-AT-02: 旧版串行执行 → 添加超时

### 板块D（部署层）（1个问题）
- L-DU-01: 配置下载失败静默 → 添加warning日志

---

*病历本已同步更新，新增避让记录 X-24 至 X-27*  
*二次审查修订：纠正6个已修复问题，新增7个遗漏问题*
