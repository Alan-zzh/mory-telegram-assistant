# Mory小助理 项目审计与整改报告（给克劳德）

> **生成日期**：2026-07-13
> **当前版本**：v5.31.6（含本次新增广告规则）
> **报告性质**：无上下文完整版 — 你（克劳德）不需要任何额外背景，读完本报告即可理解整个项目并开始整改
> **铁律**：本报告由独立审计AI生成，未修改业务代码（仅新增2条广告检测规则），所有结论有代码证据

---

## 一、项目一句话介绍

**Mory小助理**是一个运行在单机VPS上的Telegram群组助手机器人，核心能力是：AI人设对话回复、广告/色情/垃圾消息自动封禁、群管（禁言/踢人/入群验证）、积分商城与娱乐游戏、定时新闻播报、运营Dashboard（Web管理面板，端口6616）。技术栈：Python + pyTelegramBotAPI + SQLite(WAL模式) + Flask/Gunicorn(Dashboard) + 阿里千问LLM。

---

## 二、目录结构（你必须先搞清楚布局）

```
mory_assistant/
├── main.py                    # 唯一入口：初始化→注册handler→bot.infinity_polling()
├── version.py                 # 代码版本号（唯一真相源）
├── config.json.example        # 配置模板（真实config.json不入库）
├── .env.example               # 密钥模板（真实.env不入库）
├── requirements.txt           # Python依赖
│
├── core/                      # 核心框架层（基础设施，不直接处理业务消息）
│   ├── bot_initializer.py     # 工厂：加载.env/配置/DB/AI/Bot，返回BotContext
│   ├── database.py            # DB主类+9个Repo委托+108张表+启动自检
│   ├── db_connection_proxy.py # WriteQueue写队列代理（消SQLite "database is locked"）
│   ├── write_queue.py         # 单线程写队列
│   ├── message_dispatcher.py  # 主分发器：P0-P10优先级链
│   ├── mory_bot.py            # Bot扩展类
│   ├── ai_engine.py           # LLM调用核心（重试/降级/成本控制）
│   ├── model_router.py        # 三层模型池路由（llm_light/standard/premium）
│   ├── persona_adapter.py     # 人设适配（按模型家族调整prompt）
│   ├── http_client.py         # 统一HTTP客户端（重试/超时/异常）
│   ├── llm_cost_guard.py      # LLM成本熔断器（防刷资金红线）
│   ├── logging_util.py        # 日志工具
│   ├── structured_logger.py   # 结构化JSON日志
│   ├── settings.py            # 配置读取
│   ├── helpers.py             # 工具函数
│   ├── pinyin_util.py         # 拼音转换（广告谐音检测）
│   ├── telebot_compat.py      # Telegram API兼容层
│   ├── bot_routing.py         # 多Bot路由（默认关闭）
│   ├── metrics.py             # Prometheus指标（降级dummy）
│   ├── tracing.py             # OpenTelemetry追踪（默认关闭）
│   ├── telemetry.py           # 遥测
│   ├── alert_bot.py/alert_rules.py  # 告警
│   ├── anomaly_detector.py    # 异常检测
│   ├── keyword_manager.py     # 关键词管理
│   ├── funnel_state_machine.py # 转化漏斗状态机
│   ├── growth_optimizer.py    # 增长优化
│   ├── memory_summarizer.py   # 记忆摘要
│   ├── profile_learner.py     # 用户画像学习（6维，sticker维度未入库）
│   ├── quality_evaluator.py   # 质量评估
│   ├── resource_manager.py    # 资源管理
│   ├── theme_engine.py        # 播报主题引擎
│   ├── trendradar_news.py     # 新闻抓取
│   ├── user_lifecycle.py      # 用户生命周期
│   ├── scheduler_monitor.py   # 调度监控
│   ├── db_migration_monitor.py# DB迁移监控
│   ├── vps_config.py          # VPS配置
│   ├── i18n.py                # 国际化
│   ├── task_transaction.py    # 任务事务
│   ├── ab_test_router.py/ab_testing.py  # A/B测试
│   ├── router_database.py     # 路由数据库
│   ├── shared_db.py           # 共享DB
│   ├── config_compat.py       # 配置兼容
│   ├── broadcast_formatter.py # 播报格式化
│   ├── optimizer.py           # 优化器
│   │
│   ├── db_repos/              # 数据访问层（9个Repo）
│   │   ├── user_repo.py       # 用户表CRUD
│   │   ├── group_repo.py      # 群组表
│   │   ├── points_repo.py     # 积分/签到/等级
│   │   ├── tracking_repo.py   # 追踪表（reply_tracking等）
│   │   ├── config_repo.py     # 配置KV
│   │   ├── social_repo.py     # 社交/转化漏斗
│   │   ├── question_repo.py   # 问答库
│   │   ├── relay_repo.py      # 消息转发
│   │   └── ab_test_repo.py    # A/B测试
│   │
│   └── handlers/              # 消息处理器（按优先级/类型分文件）
│       ├── member_handlers.py     # P0新人入群（最先注册）
│       ├── callback_handlers.py   # 回调查询/settings按钮
│       ├── media_handlers.py      # 图片/语音/退群/频道帖子
│       ├── business_handlers.py   # Telegram Business/Guest新事件
│       ├── security_handlers.py   # 广告检测/封禁/安全（P2-P3）
│       ├── command_handlers.py    # 斜杠命令（/start/help等）
│       ├── ai_reply_handler.py    # P10 AI回复（v5.31+主AI入口）
│       ├── ai_handlers.py         # 旧版AI入口（DEPRECATED，部分函数仍被调用）
│       ├── ai_reply_core.py       # ⚠️ 废弃文件（标记DEPRECATED但仍存在）
│       ├── feature_handlers.py    # 功能命令分发
│       ├── module_handlers.py     # 工具命令（与command_handlers有重复！）
│       ├── group_admin_handlers.py# 群管命令
│       ├── flood_handlers.py      # 反刷屏
│       ├── points_handlers.py     # 积分相关
│       ├── utility_dispatch.py    # 工具分发
│       └── relay_handler.py       # 消息转发
│
├── modules/                   # 业务模块层（91个.py，被handlers调用或自注册）
│   ├── ad_detector.py         # 🔥 广告检测引擎（L0-L4五层评分+延迟封禁）
│   ├── ad_patterns_encoded.py # 🔥 编码后的广告正则模式（Unicode转义防拦截）
│   ├── ad_enforcement.py      # 广告执行（封禁/删消息/通知）
│   ├── ad_profile_signals.py  # 广告资料层信号（头像/emoji/bio）
│   ├── auto_tasks.py          # 定时任务调度（53个_job_xxx函数）
│   ├── global_blacklist.py    # 全局黑名单
│   ├── verification.py        # 入群验证（button/puzzle）
│   ├── antiflood.py/anti_raid.py/anti_channel.py  # 反刷屏/反 raid
│   ├── silent_actions.py      # 静默操作（ban/restrict不通知）
│   ├── nsfw_detect.py         # NSFW图片检测
│   ├── avatar_detector.py     # 头像广告检测
│   ├── emoji_mask_detector.py # emoji遮挡用户名检测
│   ├── edit_detector.py       # 编辑消息检测
│   ├── natural_cmd.py         # 自然语言命令（"把X改成Y"）
│   ├── settings_panel.py      # 设置面板（inline button）
│   ├── keyword_trigger.py     # 关键词触发回复
│   ├── scheduled_broadcast.py # 定时播报
│   ├── scheduled_msg.py       # 定时消息
│   ├── proactive_engage.py    # 主动触达用户
│   ├── points_enhanced.py/checkin.py/daily_quest.py/achievement.py/ranking.py  # 积分体系
│   ├── redpacket.py/lucky_wheel.py/lottery.py/blind_box.py/coupon.py/shop.py  # 娱乐/商城
│   ├── welcome_customization.py/night_mode.py/slow_mode.py/message_clean.py/warning.py  # 群管工具
│   ├── vote_kick.py/spam_watch.py/zombie_clean.py/inactive_clean.py/group_mgr.py  # 群管
│   ├── weather.py/translate.py/calculator.py/exchange_rate.py  # 工具
│   ├── games.py/sticker_tools.py/fancy_text.py  # 娱乐
│   ├── url_shortener.py/qr_code.py/telegraph.py/search.py  # 工具
│   ├── report.py/user_info.py/profile_card/user_tags.py  # 用户信息
│   ├── group_backup.py/group_notes.py/group_info.py/invite.py/pin_manage.py  # 群工具
│   ├── remote_connect.py/clean_service.py/cmd_control.py  # 远程管理
│   ├── afk.py/reminder.py/tip.py/poll_create.py/echo.py  # 小功能
│   ├── content.py/speech_stats.py/visual_dashboard.py  # 内容/统计
│   ├── admin_cmds.py/admin_log.py/admin_promote.py  # 管理员命令
│   ├── blocklist_modes.py/certify.py/federation.py/message_locks.py  # 杂项
│   ├── custom_commands.py  # 自定义命令
│   ├── ab_guardian.py/ab_insights.py  # A/B测试守护
│   ├── optimizer_admin.py  # 优化器管理
│   ├── orphan_cleanup不在这里，实际在tasks/maintenance/burn_orphan_task.py  # 注意孤儿清理在tasks/
│   │
│   └── triggers/             # 触发式子模块
│       ├── base.py
│       ├── cold_group.py     # 冷群激活
│       ├── flood_mediate.py  # 吵架调解
│       └── night_hint.py     # 夜间提示
│
├── tasks/                     # 新版定时任务（分目录组织，与modules/auto_tasks.py的_job_共存！）
│   ├── base_task.py
│   ├── task_scheduler.py
│   ├── analytics/    # 日报/周报/月报/FAQ蒸馏/AB守护
│   ├── broadcast/    # 问候/新闻/塔罗
│   ├── interaction/ # 购物车挽回/流失召回/唤醒
│   ├── maintenance/ # 备份/清理/TTL清理/孤儿清理/night_mode
│   ├── monitoring/  # 健康检查/看门狗/心跳/内存扫描
│   └── support/     # 公共工具（fault_reporter等）
│
├── dashboard/                 # Web管理面板（Flask + Gunicorn，端口6616）
│   ├── app.py                 # Flask应用+RBAC注册
│   ├── auth.py                # 认证（admin/viewer + hmac.compare_digest）
│   ├── rbac_guard.py          # RBAC守卫（默认拒绝）
│   ├── rbac_approval.py       # RBAC审批
│   ├── audit.py               # 审计日志
│   ├── helpers.py
│   ├── wsgi.py                # Gunicorn入口
│   ├── templates/html_page.py # HTML页面模板
│   └── api/                   # 23个蓝图，157个路由
│       ├── health_api.py      # /api/health（含版本号）
│       ├── config_api.py      # 配置CRUD
│       ├── stats_api.py       # 统计
│       ├── metrics_api.py     # 指标
│       ├── group_api.py       # 群组管理
│       ├── features_api.py    # 功能开关
│       ├── models_api.py      # 模型池管理
│       ├── settings_api.py    # 设置
│       ├── orphan_api.py      # 孤儿清理
│       ├── audit_api.py       # 审计
│       ├── ab_test_api.py     # A/B测试
│       ├── user_lifecycle_api.py  # 用户生命周期
│       ├── quality_api.py     # 质量评估
│       ├── monitor_api.py     # 监控
│       ├── scheduler_api.py   # 任务调度
│       ├── bot_routing_api.py # Bot路由
│       ├── faq_api.py         # FAQ
│       ├── engage_api.py      # 主动触达
│       ├── funnel_api.py      # 转化漏斗
│       ├── attribution_api.py # 归因
│       └── rbac_approval_api.py  # RBAC审批
│       # （还有部分蓝图：banned_words/welcome/global_blacklist/ad_records/group_config/logs/trigger/media/auto_reply/backup/analytics/debug/user_view/keyword_management）
│
├── scripts/                   # 运维脚本
│   ├── doc_consistency.py     # 文档数字一致性检查
│   ├── code_quality_scan.py   # 代码质量扫描（Windows下有路径问题）
│   ├── db_migrate.py          # DB迁移
│   ├── deploy_vps.py          # VPS部署
│   ├── restart_bot.py         # 重启Bot
│   ├── health_check.py        # 健康检查
│   ├── auto_rollback.py       # 自动回滚
│   ├── verify_db_methods.py   # DB Repo方法注册验证
│   ├── ssh_helper.py          # SSH工具
│   ├── cleanup_vps.py/cleanup_vps_full.py  # VPS清理
│   ├── puzan_loop_monitor.py  # 监控
│   ├── restore_after_reinstall.py  # 重装恢复
│   ├── migrate_rbac_roles.py  # RBAC角色迁移
│   └── rollback_config.json   # 回滚配置
│
├── tests/                     # 测试（39个.py）
│   ├── unit/                  # 单元测试（广告检测/配置/handlers等）
│   ├── security/              # 安全测试（RBAC渗透）
│   ├── alert/                 # 告警测试
│   ├── attribution/           # 归因测试
│   ├── persona/               # 人设一致性测试
│   ├── load/ + perf/          # 性能测试（locust）
│   └── conftest.py            # pytest配置
│
├── migrations/                # Alembic DB迁移
├── config/                    # systemd service文件
│   ├── mory-assistant.service
│   └── mory-dashboard.service
├── i18n/                      # 国际化JSON（zh-CN/en-US）
├── docs/                      # 文档
│   ├── technical/             # 技术文档（30+篇）
│   ├── plans/                 # 计划
│   ├── vision/                # 愿景
│   ├── reference/             # 参考
│   └── archive/               # 归档
├── runtime/                   # 运行时产物
│   └── audit-reports/         # 审计报告（本文件在这里）
│
├── AGENTS.md                  # 项目规则（必须遵守）
├── VERSION.md                 # 版本号
├── CHANGELOG.md               # 变更日志
├── AI_DEBUG_HISTORY.md        # 调试病历（反复暗病清单）
├── project_snapshot.md        # 项目状态快照（含METRICS块）
├── README.md                  # 简介
└── deploy_vps.py              # VPS部署脚本（根目录也有一份）
```

---

## 三、核心架构与数据流（必须理解）

### 3.1 启动流程
1. `main.py` → `initialize_bot()`：加载.env → 加载config.json → 初始化DB（建表+Repo+自检）→ 初始化AI引擎 → 初始化Bot → preflight_check（5项致命检查）→ 启动WriteQueue → 初始化LLM成本熔断 → 初始化HTTP客户端 → 初始化追踪
2. 按优先级注册专用handler：新人入群(P0) → 回调查询 → 媒体 → Business事件 → /unban管理员解封
3. 最后注册兜底handler：`@bot.message_handler(func=lambda m: True)` → `master_handler(message, ctx)`
4. `bot.infinity_polling()` 开始轮询

### 3.2 消息分发优先级链（core/message_dispatcher.py）
- P0：新人入群（member_handlers独立注册，不走master_handler）
- P1：安全/广告检测（security_handlers → ad_detector评分→达到阈值则ban+delete）
- P2：指令处理（command_handlers，/start/help等）
- P3：群管命令（group_admin_handlers）
- P4：功能指令（feature_handlers）
- P5：模块工具（module_handlers，与command_handlers有重复）
- P6-P9：反刷屏/积分/业务模块
- P10：AI回复（ai_reply_handler._dispatch_p10_ai，兜底：前面都没处理才走AI）

### 3.3 广告检测引擎（modules/ad_detector.py）— 最复杂模块
**五层检测(L0-L4)**：
- L0：CAS黑名单 + SPB垃圾评分（外部API查询）
- L1：Bio/资料检测（BIO_PATTERNS，需bot.get_chat()获取）
- L2：关键词多维度评分（8个模式组：money/contact/adult/crypto/recruit/low_barrier/gray/profile_hint），SCORE_THRESHOLD=3
- L3：零宽字符检测+全角数字/形近字规范化（反规避）
- L4：延迟封禁追踪（30分钟窗口累计评分到3才ban，防误判）

**关键常量**：
- 8个BUILTIN_KEYWORD_GROUPS权重：adult_content=4, gray_industry=4, money_promise=3, contact_info=3, recruit=3, crypto_money=3, low_barrier=1, crypto_neutral=1, profile_hint=1
- 总评分≥3触发ban
- 单独用户名命中（看简介变体等）直接ban（high severity）
- 明确色情话术（水多多/看b吗/无毛鲍鱼B直播等）单条直接ban（explicit_adult_patterns兜底）
- 谐音字映射：吱→支、伏→付、結→钻、唰→刷等
- 拼音级检测（pinyin_util）：将文本转拼音后检测谐音广告词

### 3.4 数据库层
- 108张表，全部 `CREATE TABLE IF NOT EXISTS`
- 9个Repo类分文件管理，通过DB.__getattr__委托
- **铁律**：新增Repo方法必须在database.py的_REPO_METHOD_MAP和_REPO_ATTR_MAP注册，否则启动自检失败
- WAL模式 + busy_timeout=30s + WriteQueue单线程写队列 + 4MB页缓存 + 256MB mmap
- 全局锁_db_lock（RLock可重入）

### 3.5 配置系统
- config.json（主配置，不入库）
- .env（密钥，不入库）
- 热重载：config_reload_watcher（30s轮询文件mtime）
- **铁律**：改配置三处同步：config.json.example + 代码.get()默认值 + Dashboard面板

---

## 四、客观数据（METRICS真相源，勿手改）

| 指标 | 数值 | 说明 |
|------|------|------|
| modules_py | 91 | modules/目录.py文件数 |
| core_py | 74 | core/目录.py文件数 |
| job_count | 53 | modules/auto_tasks.py中_job_函数数 |
| db_tables | 108 | CREATE TABLE IF NOT EXISTS数量 |
| dashboard_routes | 157 | dashboard/api中@*.route(数量 |
| dispatch_funcs | 9 | P0-P10分发函数（8定义+1导入） |
| model_router_mappings | 10 | model_router.py中task_type映射 |
| ad_pattern_groups | 11 | MONEY/ADULT/GRAY/CRYPTO/CRYPTO_NEUTRAL/CONTACT/RECRUIT/LOW_BARRIER/PROFILE_HINT/USERNAME/BIO |
| ad_pattern_total | 565 | 所有正则模式总数（MONEY:55+ADULT:154+GRAY:23+CRYPTO:58+CONTACT:64+RECRUIT:41+LOW_BARRIER:30+CRYPTO_NEUTRAL:11+PROFILE_HINT:8+USERNAME:51+BIO:70） |

---

## 五、本次新增的广告规则（v5.31.6→v5.31.7-dev）

### 5.1 新增规则背景
用户提交2个新广告变体截图：
1. **jikong用户**：「无毛鲍鱼B我在直播」— 色情直播招嫖（无毛=白虎、鲍鱼=女阴黑话、B=逼）
2. **晴华汤用户**：「有吱,付宝就行 10分钟3Oo♠」— 谐音支付宝+时长+价格色情交易（吱=支、逗号分隔、Oo=0、♠黑桃=性暗示）

### 5.2 已修改文件
1. [ad_patterns_encoded.py](file:///d:/Documents/Syncdisk/Work/project/mory_assistant/modules/ad_patterns_encoded.py#L221-L232)：在ADULT_PATTERNS末尾新增11条正则
   - 无毛+鲍鱼/B/逼+直播组合
   - 鲍鱼/B/逼+直播组合
   - 无毛/白虎+直播组合
   - 直播+鲍鱼/无毛/白虎/B/逼组合
   - 支付宝谐音（支/吱+付/伏+宝/寶）+数字+分钟
   - 数字+分钟+数字/Oo+元/块/♠/♥/♣/♦
   - 支付宝谐音独立匹配
   - 数字+分钟+数字/Oo
   - ♠/♥/♣/♦+数字+分钟
   - 数字+分钟+♠/♥/♣/♦

2. [ad_detector.py](file:///d:/Documents/Syncdisk/Work/project/mory_assistant/modules/ad_detector.py#L267-L270)：在_normalize_ad_evasion的variant_map新增谐音映射
   - '吱'→'支'、'伏'→'付'、'寶'→'宝'

3. [ad_detector.py](file:///d:/Documents/Syncdisk/Work/project/mory_assistant/modules/ad_detector.py#L883-L891)：在explicit_adult_patterns兜底新增7条规则
   - 色情直播招嫖组合
   - 数字+分钟+价格+色情符号/单位
   - ♠开头+数字+分钟
   - 支付宝谐音+数字+分钟
   - 支付宝谐音+就行（接受付款）

### 5.3 本地验证结果
- 消息「无毛鲍鱼B我在直播」命中3条ADULT_PATTERNS ✅
- 消息「有吱,付宝就行 10分钟3Oo♠」命中5条ADULT_PATTERNS ✅
- 语法检查：两个文件py_compile通过 ✅

---

## 六、审计发现的问题清单（按严重度排序）

### 🔴 P0 严重问题（必须立即修复）

**P0-01：config.get()默认值不一致（REPLY_CHANCE显示30%实际10%）**
- 位置：[admin_cmds.py:262](file:///d:/Documents/Syncdisk/Work/project/mory_assistant/modules/admin_cmds.py#L262)
- 现象：显示回复概率时用`config.get('REPLY_CHANCE', 30)`（30%），但实际AI回复逻辑用`config.get('REPLY_CHANCE', 10)`（10%）。当配置缺失时，Dashboard和管理员命令显示30%，但机器人实际按10%运行——用户看到的和实际行为不一致
- 修复：统一所有REPLY_CHANCE的get默认值为10

**P0-02：废弃文件core/handlers/ai_reply_core.py仍存在且未清理**
- 位置：[ai_reply_core.py](file:///d:/Documents/Syncdisk/Work/project/mory_assistant/core/handlers/ai_reply_core.py)
- 现象：文件头部标记`⚠️ DEPRECATED 废弃文件`，但未被删除。新开发者可能误用
- 同时存在：ai_handlers.py:335-339标记旧版P10入口DEPRECATED，auto_tasks.py:781-877有6个DEPRECATED函数保留兼容
- 修复：确认无引用后删除废弃文件/函数；若确需保留兼容，加明确注释说明谁在调用

**P0-03：广告正则模式跨文件重复5处（短随机用户名检测）**
- 位置：
  - [security_handlers.py:290](file:///d:/Documents/Syncdisk/Work/project/mory_assistant/core/handlers/security_handlers.py#L290)
  - [security_handlers.py:365](file:///d:/Documents/Syncdisk/Work/project/mory_assistant/core/handlers/security_handlers.py#L365)
  - [ad_detector.py:528](file:///d:/Documents/Syncdisk/Work/project/mory_assistant/modules/ad_detector.py#L528)
  - [auto_tasks.py:3975](file:///d:/Documents/Syncdisk/Work/project/mory_assistant/modules/auto_tasks.py#L3975)
  - [startup_member_scan_task.py:144](file:///d:/Documents/Syncdisk/Work/project/mory_assistant/tasks/maintenance/startup_member_scan_task.py#L144)
- 现象：同一正则`^[a-z]{1,4}\d{2,4}$`（短随机广告用户名）在5个文件中各自定义，白名单也可能不一致
- 风险：修改时漏改某一处导致检测不一致
- 修复：提取到`core/constants.py`作为公共常量

### 🟡 P1 中等问题（应尽快修复）

**P1-01：工具命令路由重复两份**
- 位置：[module_handlers.py:227-275](file:///d:/Documents/Syncdisk/Work/project/mory_assistant/core/handlers/module_handlers.py#L227-L275) 与 [command_handlers.py:1349-1394](file:///d:/Documents/Syncdisk/Work/project/mory_assistant/core/handlers/command_handlers.py#L1349-L1394)
- 现象：同一批工具命令分发代码逐行重复
- 修复：抽公共函数`dispatch_utility_commands()`

**P1-02：AUTO_MUTE_NAMES默认值不一致**
- 位置：emoji_mask_detector.py:89（默认[]）vs keyword_manager.py:48/group_mgr.py:71（用_DEFAULT_AUTO_MUTE_NAMES含预定义列表）
- 现象：配置缺失时行为不一致
- 修复：统一默认值

**P1-03：塔罗牌解析正则重复2处**
- 位置：modules/auto_tasks.py:3327-3410 与 tasks/broadcast/tarot_task.py:90-162
- 现象：同一套塔罗牌解析正则定义了两份
- 修复：提取公共模块

**P1-04：定时任务体系新旧两套并存**
- 现象：modules/auto_tasks.py（53个_job_，单文件1500+行）与tasks/目录（分文件分目录，新架构）同时存在
- 风险：新功能不知道该放哪里，两套调度器可能冲突
- 建议：制定迁移计划，逐步将auto_tasks.py中的_job_迁移到tasks/目录

**P1-05：profile_learner的sticker维度不入库**
- 位置：profile_learner.py:240-242注释"暂不入库，仅内存"
- 现象：号称6维画像，实际1维为死维度（重启丢失）
- 修复：实现持久化或文档标注为未启用

### 🟢 P2 低优先级问题（可分批处理）

**P2-01：BOT_NAME默认值不一致（显示'未设置'vs逻辑"Mory"）**
- 位置：admin_cmds.py:258显示默认'未设置'，其他地方默认"Mory"
- 影响：UI显示问题，不影响逻辑

**P2-02：natural_cmd.py内多处正则重复（分隔符/引号/关键词等）**
- 位置：modules/natural_cmd.py内
- 修复：提取局部常量

**P2-03：trendradar_news.py内新闻解析正则重复3处**
- 修复：提取公共解析函数

**P2-04：CONTACT_PATTERNS中"支付宝"独立匹配导致误伤正常消息**
- 位置：modules/ad_patterns_encoded.py CONTACT_PATTERNS第9条（`\u652f\u4ed8\u5b9d`，即"支付宝"）
- 现象：只要消息中出现"支付宝"三个字就命中contact_info(+3)，刚好达到SCORE_THRESHOLD=3直接封禁。正常消息如"支付宝到账100万元"会被误封
- 注意：这是原有规则的问题，不是本次新增规则引入的（本次新增的谐音支付宝规则均要求"分钟"或"就行"上下文）
- 修复建议：将独立"支付宝"匹配从CONTACT_PATTERNS移到需要上下文的模式中（如支付宝+vx/加/转/联系方式等组合词），或降低权重到+1/+2，避免单出现就ban

---

## 七、需要重点验证的检查清单（克劳德你必须逐项验证）

### 7.1 功能真实性验证（别信文档，信代码和测试）

| 检查项 | 验证方法 | 通过标准 |
|--------|----------|----------|
| 广告检测不封禁正常用户 | `pytest tests/unit/test_ad_detector_core.py -v` | 全部通过 |
| 签到/checkin不被误封 | `pytest tests/unit/test_ad_enforcement_cleanup.py -v` | 全部通过 |
| DB Repo方法注册完整 | `python scripts/verify_db_methods.py` | 输出"✅ DB 方法注册验证通过" |
| 文档数字一致性 | `python scripts/doc_consistency.py` | 输出"✅ 文档一致性检查通过" |
| Dashboard启动正常 | `python -c "from dashboard.app import app; print('OK')"` | 无导入错误 |
| 新广告规则不误伤 | 构造正常消息（"我在看直播""等了30分钟"） | 不触发广告检测 |
| 新广告规则不漏判 | 用本次2条测试消息验证 | 命中并判定is_ad=True |
| 解封功能完整 | 人工检查：ban后/unban恢复blacklist/global_blacklist/mute_records/ad_suspicious_users四表 | 四表全部清理 |

### 7.2 配置一致性验证

| 检查项 | 验证方法 |
|--------|----------|
| REPLY_CHANCE所有.get默认值都是10 | grep全仓`REPLY_CHANCE.*get`检查 |
| BOT_NAME默认值统一 | grep全仓`BOT_NAME.*get`检查 |
| AUTO_MUTE_NAMES默认值统一 | 检查emoji_mask_detector和keyword_manager/group_mgr |
| config.json.example包含所有config.get()读取的key | 对比config.json.example和代码中所有CONFIG.get/config.get |
| Dashboard面板配置项和代码一致 | 检查dashboard/api/config_api.py暴露的配置项 |

### 7.3 死代码/废弃代码验证

| 检查项 | 验证方法 |
|--------|----------|
| ai_reply_core.py是否真的无任何import引用 | grep全仓`ai_reply_core` |
| ai_handlers.py中DEPRECATED函数是否仍被调用 | 检查import链 |
| auto_tasks.py中6个DEPRECATED函数调用者 | grep全仓找调用点 |
| structured_logger.py的get_struct_logger/clear_context是否真的0引用 | grep全仓（7月7日审计曾报告，可能已修复） |
| pinyin_util.py的has_pinyin_leak是否真的0引用 | grep全仓 |

### 7.4 部署与运维验证

| 检查项 | 验证方法 |
|--------|----------|
| systemd服务文件正确 | 检查config/mory-assistant.service和mory-dashboard.service |
| 部署后双服务active | `systemctl status mory-assistant mory-dashboard` |
| 健康检查正常 | `curl localhost:6616/api/health`返回版本号200 |
| graceful shutdown不丢数据 | 测试SIGTERM后WriteQueue排空、DB关闭 |
| preflight_check阻断无效TOKEN | 用占位TOKEN启动，确认阻断 |

### 7.5 安全验证

| 检查项 | 检查方法 |
|--------|----------|
| .env/config.json/mory.db在.gitignore | `git check-ignore`验证 |
| 硬编码密钥 | grep全仓`sk-`/`BEGIN.*PRIVATE KEY`/`api_key.*=.*['"][^'"]+['"]` |
| RBAC默认拒绝 | dashboard/rbac_guard.py before_request检查 |
| 广告误封恢复路径 | 确认管理员通知带"一键解封"按钮 |
| SQL参数化 | grep全仓`execute(f"`或字符串拼接SQL（应全用?参数化） |

### 7.6 广告检测专项验证

| 测试消息 | 预期结果 |
|----------|----------|
| "大家好，我是新来的" | 不封禁（score=0） |
| "今天天气不错" | 不封禁 |
| "签到"（配合签到按钮流程） | 不封禁 |
| "日入3千U 招团队合作" | 封禁（money+recruit组合） |
| "加我vx: abc123" | 封禁（contact_info） |
| "无毛鲍鱼B我在直播" | 封禁（本次新增规则）✅已验证 |
| "有吱,付宝就行 10分钟3Oo♠" | 封禁（本次新增规则）✅已验证 |
| "我在直播写代码" | 不封禁（无鲍鱼/B/逼/白虎/无毛关键词）⚠️需验证 |
| "这个视频10分钟30M大小" | 不封禁（无支付/色情符号/色情词）⚠️需验证 |
| "支付宝到账100万元" | 不封禁（无分钟/色情词/招嫖语境）⚠️需验证 |

---

## 八、架构层面的深层问题（供克劳德判断）

### 8.1 单文件过大问题
- `modules/auto_tasks.py`：1500+行，53个_job_函数——应该按tasks/目录模式拆分
- `modules/ad_detector.py`：1090+行——可考虑拆分为评分器/规则引擎/追踪器
- `modules/natural_cmd.py`：1800+行——自然语言命令解析过于臃肿
- `core/database.py`：1600+行——虽然拆分了Repo，但主类仍过大

### 8.2 两套体系并存（技术债）
1. **定时任务**：旧的`modules/auto_tasks.py`（单文件大杂烩）vs 新的`tasks/`目录（分模块清晰）
2. **AI回复入口**：旧的`ai_handlers.py._dispatch_p10` vs 新的`ai_reply_handler._dispatch_p10_ai`
3. **文档数字**：多处历史数字未统一到project_snapshot.md的METRICS块（虽已加doc_consistency.py检查）

### 8.3 广告检测的持续对抗问题
- 广告发送者持续变异（谐音/分隔符/零宽字符/全角/形近字/字母代数字/emoji夹杂）
- 当前反规避：_clean_zero_width + _normalize_ad_evasion + pinyin拼音检测
- **遗漏点**：没有图片OCR检测（图片广告无法检测）、没有语音转文字检测
- **风险**：规则越来越多（565条正则），维护成本上升，误判风险增加
- **建议**：考虑引入视觉模型API做图片广告检测（已有视觉池qwen3.5-ocr），但需成本控制

### 8.4 数据库Repo方法注册机制脆弱
- 新增方法必须手动在两个MAP注册，漏掉会启动失败或AttributeError
- 虽然有启动自检（v5.31.1四层防御），但开发体验差
- **建议**：考虑用装饰器自动注册，或用元类自动扫描public方法

### 8.5 异常处理不一致
- 部分地方`except Exception: pass`静默吞错
- 部分地方`except HTTPRequestError:`后又`except Exception: pass`双重捕获
- **建议**：统一异常处理策略，关键路径必须log.error+上报fault_reporter

### 8.6 测试覆盖不足
- 39个测试文件，但核心路径（ad_enforcement封禁链路、AI回复降级、定时任务调度）覆盖不够
- 没有集成测试（实际连Telegram API测试）
- **建议**：增加广告检测回归测试集（包含历史漏判/误判案例）

---

## 九、已知反复暗病（来自AI_DEBUG_HISTORY.md，别再踩）

1. **解封入口必须早注册**：main.py中/unban handler必须在兜底分发器前注册，否则私聊被AI/反馈路由吞掉
2. **白名单/管理员免检必须前置**：广告检测前先检查是否是管理员/白名单，否则误封管理员
3. **正常业务动作（签到/checkin/打卡）必须从广告检测排除**：否则触发延迟封禁累计误封
4. **播报/问候消息必须接入burn_orphan清理链**：否则消息长期堆积
5. **新增数据表若有孤儿记录必须同步接入burn_orphan**：否则脏数据累积
6. **pip安装必须做skip-if-satisfied预检**：部署脚本pip安装无超时，被SIGTERM杀后finally不执行导致服务停摆
7. **版本号来源唯一**：启动横幅用version.VERSION（代码版本），不要混用config._CONFIG_VERSION（schema版本）
8. **DB.close()和__del__用self.__dict__.get('conn')**：不要用self.conn，会触发__getattr__委托机制输出错误日志
9. **同机其他Docker容器可能OOM拖垮Mory**：生产巡检不能只看双服务active，还要看free -m/docker stats/OOM日志

---

## 十、整改优先级建议（给克劳德的执行顺序）

### 第一阶段：紧急修复（1-2小时）
1. 修复REPLY_CHANCE默认值不一致（admin_cmds.py:262的30→10）
2. 验证新广告规则不误伤（3个边界case："我在直播写代码""视频10分钟30M""支付宝到账"）
3. 确认ai_reply_core.py无引用后删除或加明确注释
4. 运行现有单元测试确认新规则不破坏既有功能：`pytest tests/unit/test_ad_detector_core.py tests/unit/test_ad_patterns_v5161.py -v`
5. 运行DB方法注册验证：`python scripts/verify_db_methods.py`
6. 运行文档一致性检查：`python scripts/doc_consistency.py`

### 第二阶段：短期改进（半天）
7. 将短随机用户名正则提取到core/constants.py，消除5处重复
8. 合并module_handlers.py和command_handlers.py中重复的工具命令路由
9. 统一AUTO_MUTE_NAMES默认值
10. 确认structured_logger.py两个函数和pinyin_util.has_pinyin_leak是否真的0引用，0引用则删除
11. 检查ai_handlers.py中DEPRECATED函数的调用者，逐步迁移到ai_reply_handler

### 第三阶段：中期重构（1-2天）
12. 制定auto_tasks.py→tasks/目录迁移计划
13. 提取塔罗牌解析等重复正则到公共模块
14. 增加广告检测回归测试用例集（含历史漏判/误判case）
15. 全面扫描`except Exception: pass`静默吞错，关键路径加日志
16. 验证config.json.example覆盖所有config.get()读取的key

### 第四阶段：长期优化（按需）
17. 考虑图片广告OCR检测（用qwen3.5-ocr视觉池）
18. 考虑Repo方法自动注册机制（装饰器/元类）
19. 拆分过大文件（auto_tasks/natural_cmd/database）
20. 增加Dashboard慢接口应用层timeout（当前Gunicorn timeout=120但无应用层timeout）

---

## 十一、如何开始工作

1. **先读AGENTS.md**：[AGENTS.md](file:///d:/Documents/Syncdisk/Work/project/mory_assistant/AGENTS.md) — 项目铁律（先验证后动手/最小修改/证据式完工/改后必验证/新功能默认关闭等）
2. **再读本报告**：你正在读
3. **跑验证命令**：先跑第七章的验证命令，确认基线是绿的
4. **从第一阶段开始**：按第十章的优先级顺序整改
5. **每改完一个问题**：运行相关测试+py_compile，记录证据
6. **最后收工六件套**：更新CHANGELOG.md/project_snapshot.md/AI_DEBUG_HISTORY.md/VERSION.md（如升版）/README.md（如入口变化），跑doc_consistency.py

---

## 十二、快速参考：常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 语法检查
python -m py_compile modules/ad_detector.py

# 运行广告检测单元测试
pytest tests/unit/test_ad_detector_core.py tests/unit/test_ad_patterns_v5161.py -v

# DB方法注册验证
python scripts/verify_db_methods.py

# 文档一致性检查
python scripts/doc_consistency.py

# 启动Dashboard开发服务器
python start_dashboard.py

# 本地快速测试广告检测
python -c "
import sys; sys.path.insert(0,'.')
from modules.ad_detector import AdDetector
detector = AdDetector({}, db=None)
result = detector.detect('测试用户', '无毛鲍鱼B我在直播')
print('is_ad:', result['is_ad'], 'score:', result['score'], 'reason:', result['reason'])
"
```

---

**报告结束。如果你（克劳德）在整改过程中发现本报告未提及的问题，请补充到问题清单中。**
