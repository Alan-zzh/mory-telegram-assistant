# Mory小助理 项目快照 v5.31.2

> 新AI会话必读：本文件 + `AGENTS.md`（项目规则+老坑铁律）+ `AI_DEBUG_HISTORY.md`
> 最后更新：2026-07-06（广告资料层误封止血 + 管理员一键解封按钮）

---

## 1. 项目概览

| 项目 | 值 |
|------|-----|
| 名称 | Mory小助理 - 运营型商业 AI 转化机器人 |
| 版本 | v5.31.2 |
| 部署状态 | 2026-07-01 起 `scripts/puzan_loop_monitor.py` 本地无限 LOOP 持续监控（间隔 300s，日志 `logs/puzan_loop_monitor_live_20260630.log`；当前本地 lock PID 28388）；VPS `43.153.23.115` RUNNING；`scripts/vps_watchdog.py` 由 root cron 每 2min 检查 health；`mory-assistant` / `mory-dashboard` 双 active；✅ verify_db_methods 164 方法无缺失无孤儿；✅ /api/health 返回 200 且 version=v5.31.2；L4 已按真实 schema 统计 task/token/成本；2026-07-02 22:37 AI 复发热修已部署，远端备份 `ai_engine.py.bak.20260702_223745`、`health_check_task.py.bak.20260702_223745`，22:51 二次加固备份 `ai_engine.py.bak.20260702_225119`，2026-07-03 03:06 最终告警加固备份 `ai_engine.py.bak.20260703_030627`；2026-07-03 09:37 群聊露馅兜底与阅后即焚热修已精确部署，远端备份 `ai_engine.py.bak.20260703_093729`、`ai_reply_handler.py.bak.20260703_093729`、`ai_handlers.py.bak.20260703_093729`、`tracking_repo.py.bak.20260703_093729`、`burn_orphan_task.py.bak.20260703_093729`、`auto_tasks.py.bak.20260703_093729`、`bot_initializer.py.bak.20260703_093729`；2026-07-03 10:06 AI 运行池与后台任务锁二次加固已精确部署，远端备份 `ai_engine.py.bak.20260703_100613`、`greeting_task.py.bak.20260703_100613`、`reactivate_task.py.bak.20260703_100613`、`cart_recovery_task.py.bak.20260703_100613`、`leak_task.py.bak.20260703_100613`、`auto_tasks.py.bak.20260703_100613`；2026-07-04 01:10 主动播报超时清理热修已精确部署，远端备份 `tracking_repo.py.bak.20260704_011055`、`database.py.bak.20260704_011055`、`burn_orphan_task.py.bak.20260704_011055`、`auto_tasks.py.bak.20260704_011055`、`models_api.py.bak.20260704_011055`；生产 47 小时内新闻/问候/定点播报残留已处理，最终 `reply_tracking=0`、`broadcast_tracking_recent=0`、`channel_tracking_recent=0`；`burn_orphan` 继续每 6 小时执行，但现在会合并清理 `reply_tracking` 与 `channel_tracking`，并统一清 `broadcast_tracking` 残留；普通群聊 AI 全失败返回空串不再发模型故障文案，私聊返回短人设兜底；`qwen3.6-plus-2026-04-02`、`glm-5.2` 已从运行时候选池剔除；`greeting` / `reactivate` / `cart_recovery` / `leak` 不再持有 `config` / `ai` / `bot` 锁等待外部模型；真实 AI smoke 返回 `正常`，10:06 后 journal 无 `AI模型全部失败` / `三层路由全失败` / `Traceback` / `CRITICAL` / 锁超时；03:00-03:03 复盘无 402/403/余额/额度日志，只有超时和空 content，结论不是整体没额度；外部模型全失败但已返回兜底文案时不再发送 `AI模型全部失败` 管理员故障，只有明确 HTTP 402/403 才发送 `AI模型额度或权限异常`；远端强制失败 smoke journal 无 `AI模型全部失败` / `三层路由全失败`；早间任务缺失已确认是进程晚于任务窗口启动导致，健康检查已改为“任务窗口已错过”信息归类；注意 `WatchdogUSec=0`，当前依赖外部 watchdog 而非 systemd watchdog |
| 防御体系 | v5.31.1 四层防御：L1启动自检(_self_check_repo_methods) + L2__getattr__ CRITICAL+re-raise + L3 scripts/verify_db_methods.py 部署前门禁 + L4 core/scheduler_monitor.py:check_critical_jobs_health 调度健康监控。v5.31.2 新增：① LLMCostGuard 成本熔断器（用户1h $1.0，全局1h $5.0，data/router_usage.db 12列schema记录token_usage）② 腾讯云 Lighthouse API 监控（实例 lhins-4ney4np5，IP 43.153.23.115）③ Loop 多智能体暗病搜索机制 ④ RLock 替代 Lock 解决 add_points 重入死锁 ⑤ 原子 UPDATE 防止 TOCTOU 余额检查竞态 ⑥ 独立看门狗 scripts/vps_watchdog.py（每2min检查health，连续3次失败自动重启，已去重日志）⑦ _CST 时区常量全域覆盖（累计修复 40+ 处 datetime.now() 时区错位）⑧ WriteQueue 停机 drain，降低重启尾部写丢失风险 |
| 技术栈 | Python3 + pyTelegramBotAPI + SQLite(WAL+busy_timeout=30s+单线程写入队列+连接代理全量化+背压Fail-Fast+Alembic迁移) + Flask + gunicorn+gevent + structlog + diskcache |
| 部署 | VPS（systemd作为唯一进程管理）+ GitHub Actions CI/CD（待启用Secrets） |
| 存储 | `mory.db`(SQLite) + `config.json`(业务配置) + `.env`(敏感凭据) + `requirements.lock`(锁定依赖) |
| 红线 | 绝对不能因报错导致程序卡死崩溃 |
| 广告治理 | v5.30.1 修复 _REPO_METHOD_MAP 注册缺失（snapshot_message/mark_message_deleted/get_user_messages/get_user_undeleted_messages），message_snapshots 30+ 版本空表根因消除。不踢人：永久禁言 + 删除消息 + 双黑名单 + 历史消息追踪清理 + Premium emoji 状态 OCR + 新版反应/付费媒体权限禁用；v5.31.2 Hotfix 2026-07-06 起白名单/群管理员免检在资料层检测之前执行，签到/打卡/checkin 等正常业务动作不进入广告资料层和延迟封禁累计；管理员广告处置通知带“解封”按钮，`/unban ID`、`/unban @username`、回复 `/unban`、`解封 ID`、私聊自助解封均可清 `blacklist` + `global_blacklist` + `mute_records` + `ad_suspicious_users` 并恢复发言权限；管理员可在私聊中继回复 `拉黑` 手动拉黑原用户 |
| 人设引擎 | v5.21.0 4桶反模板(cold/savage/soft/common)+动态LLM参数矩阵(亲密度×场景×时段21组) + 12条去AI痕迹铁律（默认开启 `PERSONA_ENGINE_ENABLED=true`） |
| 安全加固 | v5.22.0 全量审计修复 + v5.24.0 RBAC before_request默认拒绝守卫 + 自动化渗透测试6用例 + v5.25.0 RBAC DB驱动动态权限 + v5.26.0 RBAC权限变更审批流 |
| 架构优化 | v5.26.0 10大优化：①LLM成本熔断器 ②Locust三档梯度压测 ③级联告警故障注入测试 ④人设跨模型一致性 ⑤多模型A/B测试分流 ⑥记忆摘要转化率归因 ⑦DB迁移指标监控 ⑧多Bot任务分工 ⑨归因模型离线回放 ⑩RBAC动态权限审批流 |

---

### 1.1 最新生产增量

- 2026-07-06：广告资料层误封已止血。`core/handlers/security_handlers.py` 将 `AD_WHITELIST.user_ids` 和群管理员免检前移到 Bio / Premium emoji 状态检测之前；`modules/ad_enforcement.py` 管理员处置通知新增“解封”按钮；`core/handlers/callback_handlers.py` 新增 `ad_unban:` 回调，仅 `ADMIN_ID` / `ADMIN_IDS` 可操作，点击后移除 `blacklist`、`global_blacklist`、`mute_records` 并尝试恢复群内发言权限。本地验证：py_compile 通过，相关单测 17 passed，`verify_db_methods.py` 164 方法通过。VPS 已部署：远端 py_compile 和 DB 方法注册检查通过，`grep` 确认 `ad_unban:` 与免检前移逻辑已在 `/home/ubuntu/mory_assistant/`；双服务 active，`/api/health` 返回 v5.31.2，新进程启动后 journal 错误过滤为空。
- 2026-07-06：签到误封根因已修复。生产日志确认 `uid=8187862648` 因多次正常 `签到` 叠加资料层低置信 `profile_score`，最终触发 `延迟广告累计评分4`；现已新增正常业务动作前置放行，签到/打卡/checkin 不再进入广告资料层和延迟封禁累计，并会清旧追踪分。解封能力增强为回复消息、数字 ID、`@username`、按钮、私聊自助均走统一恢复链，清 `blacklist`、`global_blacklist`、`mute_records`、`ad_suspicious_users`。生产已立即解封 `8187862648`，四项 DB 残留均为 0，Telegram 权限恢复返回 `unrestrict ok`。VPS 精确热修备份 `/home/ubuntu/mory_assistant/backups/unban_checkin_false_positive_20260706_003936`；远端 py_compile / DB 方法检查 / health / journal 错误过滤通过；远端 smoke 确认 `签到`、`/checkin@MoryMateBot` 放行，`签到 看我简介` 不放行。
- 2026-07-05：AI 真实失败根因已修复。近 2 小时生产日志确认无 402/403 额度/权限证据，主要是慢模型超时和空 content；生产配置已把 `qwen3.5-plus-2026-04-20`、`qwen3.7-max-preview` 加入黑名单，standard 首发 `glm-5.1`，light/premium 首发 `qwen3.7-max-2026-05-17/06-08`，AI 调用预算为 30 秒/2 次。VPS 备份：`/home/ubuntu/mory_assistant/backups/ai_timeout_budget_fix_20260705_134701`、`/home/ubuntu/mory_assistant/backups/ai_model_route_fix_20260705_134956/config.json`；真实 smoke normal 8.52s、morning 25.72s、convert 21.67s。
- 2026-07-05：AI 失败拟人化兜底已取消。`core/ai_engine.py`、`core/handlers/ai_reply_handler.py`、`core/handlers/ai_handlers.py` 三处统一改为普通/未知/特殊模式失败静默；转化/联系模式失败只给预览群 `@moryselect` 与自助下单 `@MorychannelBot` 固定入口。VPS 精确部署备份：`/home/ubuntu/mory_assistant/backups/no_humanized_ai_fallback_20260705_132757`；远端强制超时 smoke、双服务 active、`/api/health` v5.31.2、journal 过滤均通过。
- 2026-07-05：入口类强转化需求已加硬收口。用户明确说“链接给我 / 怎么加群 / 群入口 / 自助机器人链接”等时，`core/handlers/ai_reply_handler.py` 不再交给 LLM 闲聊，直接回复预览群 `@moryselect` 和自助下单 `@MorychannelBot`；`core/keyword_manager.py` 已补默认商业关键词。VPS 精确部署备份：`/home/ubuntu/mory_assistant/backups/direct_access_reply_20260705_061648`，远端 smoke 确认 4 个样例均 `convert=true` 且 `direct=true`，服务 active，`/api/health` 返回 v5.31.2。

## 2. 目录结构

```
mory_assistant/
├── main.py                 # 精简入口（219行：初始化→注册→启动）
├── config.json             # 运行时配置（Token/管理员/模型池/人设）
├── config.json.example     # 配置模板（无密钥，可提交Git）
├── .env                    # 环境变量（不提交Git）
├── .env.example            # 环境变量模板
├── .gitignore              # Git忽略规则
├── requirements.txt        # Python 直接依赖
├── requirements.in         # pip-compile 输入
├── requirements.lock       # pip-compile 锁定依赖版本（生产部署优先来源）
├── alembic.ini             # Alembic 数据库迁移主配置
├── mypy.ini                # mypy 类型检查配置
├── pytest.ini              # pytest + coverage 配置
├── version.py              # 版本号统一管理
├── deploy_vps.py           # VPS一键部署脚本（systemd管理+安全配置合并）
├── start_dashboard.py      # Dashboard启动脚本
├── Dockerfile              # Docker镜像定义（deploy_vps.py 显式上传，供可选 Docker 交付使用）
├── docker-compose.yml      # Docker编排配置（deploy_vps.py 显式上传）
├── core/
│   ├── __init__.py         # 核心模块导出
│   ├── bot_initializer.py  # Bot初始化工厂（BotContext+22步初始化流程）
│   ├── telebot_compat.py   # pyTelegramBotAPI兼容补丁：保留新字段+新发送参数+Business update分发钩子
│   ├── http_client.py      # 统一HTTP客户端（超时管理+自动重试+异常分类+日志记录+拦截器）
│   ├── message_dispatcher.py # 消息分发核心（P0-P10优先级+DispatchContext）
│   ├── ai_engine.py        # AI引擎（三层路由+多模型轮换+TTS语音）
│   ├── trendradar_news.py  # 新闻获取（真实源优先 + TrendRadar兜底）
│   ├── database.py         # DB基类（连接管理+表初始化+7个Repo实例+__getattr__委托）
│   ├── logging_util.py     # 日志工具（按大小轮转+错误分级）
│   ├── mory_bot.py         # Bot封装类（阅后即焚追踪）
│   ├── optimizer.py        # 运营优化器（语义缓存+熔断+限流）
│   ├── resource_manager.py # 资源管理（图片/语音池+线程安全锁）
│   ├── deploy_utils.py     # 安全部署工具库（safe_upload_config等）
│   ├── monitoring.py       # 系统监控
│   ├── router_database.py  # 路由使用统计数据库（从universal_ai_router内联）
│   ├── router_statistics.py # 路由统计逻辑（从universal_ai_router内联）
│   ├── task_transaction.py # TaskTransactionManager统一事务管理上下文
│   ├── theme_engine.py     # 播报多样性引擎（主题轮换+语气轮换+黑话软植入+图片暗示+转化引导）
│   ├── migrate.py          # 数据库迁移工具
│   ├── vps_config.py       # VPS连接配置
│   ├── llm_cost_guard.py   # 【v5.26.0】LLM成本熔断器（滑动窗口deque+单用户/全局降级）
│   ├── persona_adapter.py  # 【v5.26.0】人设跨模型适配（按模型家族定制Prompt）
│   ├── ab_test_router.py   # 【v5.26.0】多模型A/B测试分流（uid%10分组+指标埋点）【v5.27.0-RC1】新增统计显著性检验
│   ├── db_migration_monitor.py # 【v5.26.0】DB迁移指标监控（5项指标每小时检查）
│   ├── bot_routing.py      # 【v5.26.0】多Bot任务分工（bot_group_routing静态路由表）
│   ├── settings.py         # 【v5.27.0-RC1】Pydantic Settings 统一配置（.env + config.json）
│   ├── structured_logger.py # 【v5.27.0-RC1】structlog JSON 结构化日志 + request_id 绑定
│   ├── cache_manager.py    # 【v5.27.0-RC1】diskcache 磁盘缓存（命名空间+TTL+@cached装饰器）
│   ├── user_lifecycle.py   # 【v5.27.0-RC1】用户生命周期五阶段管理
│   ├── tracing.py          # 【v5.27.0-RC1】OpenTelemetry 分布式追踪（默认关闭）
│   ├── metrics.py          # 【v5.27.0-RC1】Prometheus 业务指标导出
│   ├── anomaly_detector.py # 【v5.27.0-RC1】Z-Score 滑动窗口异常检测
│   ├── quality_evaluator.py # 【v5.27.0-RC1】LLM-as-a-Judge 内容质量评估（默认关闭）
│   ├── i18n.py             # 【v5.27.0-RC1】JSON 语言包多语言支持
│   ├── growth_optimizer.py # 【v5.28.0】10项增长优化编排（意图/A-B/归因/质量评估闭环）
│   ├── handlers/           # 消息处理器（按优先级组织）
│   │   ├── __init__.py
│   │   ├── member_handlers.py    # P0入群/退群
│   │   ├── callback_handlers.py  # 回调查询+/settings
│   │   ├── media_handlers.py     # 图片/语音/频道帖子
│   │   ├── business_handlers.py  # Business连接观测+deleted_business_messages本地删除标记同步
│   │   ├── security_handlers.py  # P1黑名单/P3敏感词/P3.5广告
│   │   ├── points_handlers.py    # P2积分/签到/等级
│   │   ├── flood_handlers.py     # P4反刷屏
│   │   ├── command_handlers.py   # P5-P6命令（6个handler从message_dispatcher迁出）
│   │   ├── feature_handlers.py   # P8.5功能关键词
│   │   ├── group_admin_handlers.py # P8.6群管功能
│   │   ├── module_handlers.py    # P8.7-P8.8模块命令
│   │   ├── ai_handlers.py        # P7-P10 AI回复入口
│   │   └── ai_reply_core.py      # P10 AI回复核心逻辑
│   └── db_repos/           # 数据库功能域仓库
│       ├── __init__.py
│       ├── user_repo.py    # 用户/等级/徽章/标签
│       ├── group_repo.py   # 群管/黑名单/警告/禁言
│       ├── points_repo.py  # 积分/签到/商城/排行榜
│       ├── tracking_repo.py # 追踪/频道/发言统计
│       ├── config_repo.py  # 系统配置/关键词/定时消息
│       ├── social_repo.py  # AFK/邀请/验证/联邦
│       └── question_repo.py # 【v5.15.0新增】问题追踪/FAQ匹配/蒸馏/候选审核
├── modules/                # 87 个模块 .py（含 triggers/ 4 个），详见 README.md §1.8 模块能力矩阵
│   ├── __init__.py
│   ├── auto_tasks.py       # 定时任务（53个_job_*函数）
│   ├── ... 86 个模块文件（完整列表见 README.md §1.8）
│   └── triggers/           # 场景触发器子目录
│       ├── __init__.py
│       ├── base.py         # 触发器基类
│       ├── cold_group.py   # 冷群唤醒
│       ├── flood_mediate.py # 刷屏调解
│       └── night_hint.py   # 深夜暗示
├── dashboard/
│   ├── app.py              # 精简入口（57行：create_app+Blueprint注册）
│   ├── wsgi.py             # gunicorn WSGI入口（生产环境用）
│   ├── auth.py             # 认证模块（登录/登出/CSRF/速率限制+admin/viewer角色）
│   ├── helpers.py          # 公共工具（DB/配置/VPS/认证装饰器+DASHBOARD_MODE分区）
│   ├── api/                # API蓝图模块
│   │   ├── stats_api.py    # 数据统计API
│   │   ├── config_api.py   # 配置管理API
│   │   ├── group_api.py    # 群组设置API
│   │   ├── features_api.py # 功能配置API
│   │   ├── models_api.py   # 模型/任务状态API
│   │   ├── settings_api.py # 设置面板API（最大头，~80按钮回调）
│   │   ├── orphan_api.py   # 孤儿清理API
│   │   ├── ab_test_api.py  # A/B测试API
│   │   ├── engage_api.py   # 主动搭讪配置API
│   │   ├── faq_api.py      # 【v5.15.0新增】FAQ统计与管理API（10端点）
│   │   ├── audit_api.py    # 【v5.23.0】RBAC审计日志API（3端点：logs/stats/cleanup）
│   │   ├── attribution_api.py # 【v5.23.0】转化漏斗归因API（2端点：report/user）+【v5.26.0】A/B测试报告+记忆归因端点
│   │   ├── scheduler_api.py # 【v5.23.0】任务调度监控API（2端点：stats/jobs）
│   │   ├── monitor_api.py   # 【v5.26.0】DB迁移监控API（1端点：db-migration/status）
│   │   ├── bot_routing_api.py # 【v5.26.0】多Bot路由管理API（4端点：list/assign/remove/check）
│   │   ├── rbac_approval_api.py # 【v5.26.0】RBAC权限审批流API（6端点：request/approve/reject/cancel/list/detail）
│   │   ├── health_api.py   # 【v5.27.0-RC1】健康检查API（5端点：health/version/uptime/routes/db）
│   │   ├── user_lifecycle_api.py # 【v5.27.0-RC1】用户生命周期分布API
│   │   ├── funnel_api.py   # 【v5.27.0-RC1】转化漏斗可视化API
│   │   ├── metrics_api.py  # 【v5.27.0-RC1】Prometheus 指标端点
│   │   └── quality_api.py  # 【v5.27.0-RC1】内容质量评分API
│   │   # 共 21 个 API 文件（不含 __init__.py）/ 156 条路由（实测 grep @.*.route(），见 README.md §1.9
│   ├── audit.py            # 【v5.23.0】RBAC权限+审计日志（三角色admin/operator/viewer+permission_required装饰器）
│   ├── rbac_approval.py    # 【v5.26.0】RBAC权限变更审批流（permission_change_requests表+6核心函数）
│   └── templates/
│       └── html_page.py    # 前端HTML模板
├── config/                 # 服务配置
│   ├── mory-assistant.service      # Bot systemd服务（含EnvironmentFile）
│   ├── mory-dashboard.service       # Dashboard systemd服务（gunicorn+gevent）
│   ├── mory-media-assistant.service # 媒体Bot systemd服务
│   └── mory-media-dashboard.service # 媒体Bot Dashboard（端口6617，独立数据库）
├── scripts/                # 运维/验证/扫描工具
│   ├── cleanup_vps.py      # VPS 残留脚本清理（基础版）
│   ├── cleanup_vps_full.py # VPS 完整清理（垃圾文件+__pycache__+logrotate+journal，v5.22.0）
│   ├── restart_bot.py      # Bot重启工具
│   ├── restore_after_reinstall.py  # 重装后恢复
│   ├── ssh_helper.py       # SSH 辅助
│   ├── db_migrate.py       # 【v5.27.0-RC1】Alembic 迁移命令封装
│   ├── health_check.py     # 【v5.27.0-RC1】部署后健康检查
│   ├── auto_rollback.py    # 【v5.27.0-RC1】不健康时自动回滚
│   ├── rollback_config.json # 【v5.27.0-RC1】回滚策略配置
│   ├── code_quality_scan.py # 【v5.27.0-RC1】vulture+radon 代码扫描
│   ├── puzan_loop_monitor.py # 【v5.31.2】Puzan OS 6层LOOP持续监控（L1 VPS/L2 服务/L3 应用/L4 业务/L5 调度/L6 看门狗+腾讯云Lighthouse）
│   ├── vps_watchdog.py     # 【v5.31.2】VPS端独立看门狗，每2分钟检查 /api/health，连续3次失败自动 systemctl restart
│   └── README.md           # 工具说明
├── backups/                # 自动备份（保留最近2个server_pull备份）
├── tests/                  # 测试目录
│   ├── unit/               # 单元测试【v5.27.0-RC1】新增广告检测/RBAC/Settings核心用例
│   ├── security/           # 安全测试
│   ├── perf/               # 【v5.23.0 阶段3-E】性能压测（Locust，模拟高并发 Webhook）
│   │   ├── locustfile.py   # Locust 压测脚本（独立运行，不依赖项目内部模块）
│   │   └── README.md       # 压测使用说明
│   ├── alert/              # 【v5.26.0】级联告警故障注入测试
│   │   └── test_cascade_suppression.py # 5用例（DB锁级联抑制/根因解除/5min汇总/限流/非级联正常）
│   ├── persona/            # 【v5.26.0】人设跨模型一致性测试
│   │   └── test_persona_consistency.py # 50用例+LLM-as-a-Judge 4维盲评
│   ├── attribution/        # 【v5.26.0】归因模型离线回放
│   │   └── test_offline_replay.py # 时间衰减vs末次触达对比+CLI参数
│   ├── load/               # 【v5.26.0】三档梯度压测
│   │   ├── locustfile.py   # Locust压测脚本（20/100/300 QPS三档+WriteQueueFullError记录）
│   │   └── analyze_results.py # 黄金指标提取+阈值调优建议
│   └── README.md           # 测试目录说明
├── migrations/             # 【v5.27.0-RC1】Alembic 迁移脚本目录
│   ├── env.py              # Alembic 环境配置（SQLite batch 模式）
│   ├── script.py.mako      # 迁移脚本模板
│   └── versions/           # 版本脚本
│       └── 0001_initial_schema.py # 108 张表基线版本
├── i18n/                   # 【v5.27.0-RC1】多语言包目录
│   ├── zh-CN.json          # 中文语言包示例
│   └── en-US.json          # 英文语言包示例
├── .github/workflows/      # 【v5.27.0-RC1】GitHub Actions CI/CD
│   └── ci.yml              # pytest + flake8 + mypy + compileall + 部署模板
├── docs/reference/BOT_投喂与自然语言配置说明.md  # Bot投喂与配置说明
├── project_snapshot.md     # 本文件
├── AI_DEBUG_HISTORY.md     # 调试病历本
├── CHANGELOG.md            # 变更日志
├── VERSION.md              # 版本号
└── README.md               # 项目入口文档

---

## 3. 数据库表（mory.db · 108张表）

> 实际数量：core/database.py 中 108 个 `CREATE TABLE IF NOT EXISTS` 语句（v5.28.0 实测）

| 表名 | 用途 |
|------|------|
| users | 用户画像（uid, name, tags, first_seen, last_active） |
| user_levels | 用户等级积分（uid, level, points, join_date, last_active） |
| points | 积分等级（uid, points, level, consecutive_days） |
| blacklist | 黑名单 |
| channel_tracking | 频道浏览量追踪 |
| cart_recovery | 购物车挽回 |
| coupon_claims | 优惠券 |
| daily_reports | 每日报告 |
| badges | 勋章 |
| group_events | 群事件 |
| conversions | 转化追踪 |
| tarot_cache | 塔罗缓存 |
| task_log | 定时任务执行日志（task_key, exec_date, exec_ts） |
| keyword_triggers | 关键词触发规则 |
| reply_tracking | 阅后即焚回复追踪（bot_msg_id, chat_id, user_msg_id, ts, replied） |
| group_join_log | 入群幂等记录（uid, chat_id, join_date） |
| group_left_log | 离群幂等记录（uid, chat_id, left_date） |
| channel_posts | 频道原生帖子（chat_id, message_id, post_type, views, ts） |
| login_failures | Dashboard登录失败计数（ip, count, first_fail_at） |
| spam_track | 刷屏追踪（uid, chat_id, count, ts） |
| mute_records | 禁言记录（uid, chat_id, muted_by, reason, ts） |
| ad_suspicious_users | 广告可疑用户追踪（uid, chat_id, score, msg_ids, ts） |
| group_members | 群成员追踪（uid, chat_id, username, display_name, first_seen, last_active） |
| **interaction_quality_scores** | 【v5.27.0-RC1】内容质量评分(id, conversation_id, naturalness_score, relevance_score, persona_score, evaluated_at) |
| **broadcast_tracking** | 【v5.11.0新增】孤儿播报追踪(chat_id, category, msg_id, ts)，复合主键(chat_id,category)同群同类型只保留最新一条，用于孤儿播报30S删和早安/午安/晚安链式互删 |
| **user_questions** | 【v5.15.0新增】用户问题记录(id, uid, chat_id, question_text, mode, intent, keyword_tag, question_category, is_convert, ai_reply_summary, faq_hit_id, ts)，P10 AI回复前自动写入 |
| **faq_knowledge** | 【v5.15.0新增】FAQ知识库(id, question_pattern, question_category, answer_template, ai_polish, match_mode, priority, hit_count, status, created_by, created_at, updated_at)，审核通过的话术模板 |
| **faq_candidates** | 【v5.15.0新增】FAQ蒸馏候选(id, question_pattern, question_category, sample_questions, frequency, mode, intent, status, reviewed_by, reviewed_at, created_at)，高频问题自动聚类待审核 |

---

## 4. 关键架构约束

### 4.1 消息分发
- pyTelegramBotAPI handler是独占式，`return False`不流转
- 唯一方案：`BaseMiddleware`拦截所有消息
- 优先级：P0(入群)→P1(黑名单)→P2(积分)→P3(敏感词)→P3.5(智能广告检测)→P4(刷屏)→P5(野生Bot)→P6(管理员)→P6.5(关键词)→P7(视奸)→P8(彩蛋)→P9(画像)→P10(AI)

### 4.1.1 广告检测五级处理（v5.8.0）

| 层级 | 检测内容 | 信号来源 | 评分 | 说明 |
|------|---------|---------|------|------|
| L0 | CAS/SPB 外部数据库 | 外部 API | +1~+2（辅助） | 仅辅助评分，不直接 ban |
| L1 | 用户名+Bio+头像+Premium emoji状态 | 用户资料 | 高置信命中=直接处置 | 高置信度组合信号；广告账号不踢人，统一永久禁言 |
| L2 | 消息内容关键词 | 消息文本 | 1~4/维度 | 9个维度权重各异 |
| L3 | 零宽字符+元数据 | 消息结构 | +1~+2 | 零宽占比>20%额外+2 |
| L4 | 追溯扫描 | 历史消息/数据库 | — | Bot启动时自动扫描+手动/scan_ads |

**L0 外部数据库**：CAS（api.cas.chat）+SPB（api.intellivoid.net），仅辅助评分防误封，结果缓存1小时

**L1 用户资料检测**：
- 用户名检测（USERNAME_PATTERNS）："看简介"变体→直接ban；短随机用户名→score+2
- Bio检测（BIO_PATTERNS）：赚钱承诺/引流话术/t.me链接/刷礼物/私信/滴滴/1000U→score+3
- Premium emoji状态检测（v5.16.4）：通过 `emoji_status_custom_emoji_id` + `getCustomEmojiStickers` 读取状态贴纸；元数据无文字时下载缩略图走 OCR，识别截图类"看我简介"
- Telegram Bot API 10.x 兼容（v5.16.5）：富文本卡片播报、Rich Message/Poll/Checklist 原始直通、反应治理、Business 消息映射、Business 删除事件同步本地 `message_snapshots`
- **v5.14.1 新增**：`_normalize_ad_evasion()` 反规避规范化（全角数字/形近字/繁体→简体，18个变体映射）
- 头像检测：用户名异常/Bio可疑/短随机用户名时触发
- 两层组合（用户名+Bio）→直接ban；三层组合（用户名+Bio+头像）→直接ban

**L2 消息内容关键词（9个维度）**：

| 维度 | 标签 | 权重 |
|------|------|:----:|
| money_promise | 赚钱承诺 | 3 |
| low_barrier | 低门槛 | 1 |
| contact_info | 联系方式/引流 | 3 |
| profile_hint | 引流暗示 | 1 |
| recruit | 招募/拉人 | 2 |
| crypto_money | 加密货币/洗钱 | 3 |
| crypto_neutral | 中性加密词汇 | 1 |
| adult_content | 色情引流 | 4 |
| gray_industry | 灰色产业 | 4 |

- 阈值 SCORE_THRESHOLD = 3
- 每个维度只计一次最高分
- 2字符消息只检测高权重维度（权重>=4）

**L3 零宽字符+元数据**：
- 零宽字符清理（U+200B~U+200F等43个字符），清理后再做正则匹配
- 零宽占比>20% → 额外score+2
- URL数量>2 → score+1；URL短链 → score+1；转发+用户名可疑 → score+1

**L4 追溯扫描**：
- Bot启动时自动扫描最近200条消息
- 双模式：forwardMessage模式（无保护内容群组）+ 数据库驱动模式（有保护内容群组）
- /scan_ads管理员命令手动触发
- 配置项：RETROACTIVE_SCAN_ENABLED / RETROACTIVE_SCAN_RANGE

**误封防护**：白名单（群管理员/群主免检+可配置用户免检）+ 阈值保护（>=3）+ CAS/SPB仅辅助 + 延迟封禁（30分钟窗口）

**核心设计原则**（详见 AI_DEBUG_HISTORY.md "色情引流检测规则设计原则与避开指南"）：
- **组合规则 > 单字规则**：按摩/小姐/约/上门/服务/接待等单字必须搭配色情特征词
- **精确匹配 > 字符集**：`(?:接待|全套|上门|特服)` 优于 `[服务接待全套]`
- **间距严格控制**：组合规则间距≤1~3，避免误判正常社交
- **单维度只计一次分**：同维度多条规则命中不重复加分

### 4.2 线程安全
- `_db_lock`保护所有数据库操作
- ResourceManager锁超时30秒
- 内存缓存有上限（_conv_tracker≤1000）

### 4.3 安全
- Dashboard密钥通过环境变量设置
- VPS信息通过环境变量读取，无硬编码
- 所有SQL参数化查询，禁止f-string拼接
- 密码校验用`hmac.compare_digest()`
- Dashboard权限分级：admin（读写）/ operator（有限写）/ viewer（只读）
- **v5.27.0-RC1**：新增 `core/settings.py` 兼容配置门面；CI 当前对稳定化关键文件运行 flake8/mypy，并执行 pytest/interrogate/compileall

### 4.4 进程红线（务必遵守）
- **生产环境只允许 systemd 管理本项目进程**：只用 `sudo systemctl restart mory-assistant` / `systemctl status mory-assistant`。
- **Dashboard 也由 systemd 管理**：`sudo systemctl restart mory-dashboard` / `systemctl status mory-dashboard`（服务文件：config/mory-dashboard.service）。
- **绝对禁止**：`pm2`、手动 `python main.py`、`nohup python start_dashboard.py` 去启动/重启生产服务，否则极易多开导致 Telegram `409 Conflict`（同 token 多个 getUpdates）或端口冲突。
- `start.sh` 已在v5.1.0中删除，统一使用systemd管理。
- **v5.27.0-RC1**：部署后建议调用 `scripts/health_check.py` 验证；不健康时 `scripts/auto_rollback.py` 可回滚到上一版本目录。

---

## 5. 定时任务

| 任务 | 时间 | 防重复 |
|------|------|--------|
| 早安问候 | 8:05 | _try_claim_and_lock原子抢占+task_log持久化 |
| 早间新闻 | 9:05 | 同上 |
| 每日报告 | 9:10 | 同上 |
| **morning_nudge** | **10:00** | **同上** |
| 午安问候 | 12:35 | 同上 |
| 午间新闻 | 13:05 | 同上 |
| **afternoon_tease** | **14:30** | **同上** |
| 塔罗搭讪 | 15:00 | 同上 |
| **evening_warm** | **19:00** | **同上** |
| 晚间新闻 | 20:35 | 同上 |
| **night_hook** | **22:30** | **同上** |
| 晚安问候 | 23:05 | 同上 |
| 频道浏览量 | 每小时 | — |
| 阅后即焚清理 | 每6小时 | — |
| **sync_user_lifecycle_buckets** | **每日 02:00** | **v5.27.0-RC1** |
| **sync_scheduler_metrics / update_prometheus_metrics** | **每5分钟** | **v5.27.0-RC1** |
| **evaluate_conversation_quality** | **每日 03:00** | **v5.28.0（低采样开启）** |

### 5.1 定点播报（SCHEDULED_BROADCASTS）

4 组富文本卡片播报（v5.18.2 无缝升级版），当前全部 `enabled: true`：

| ID | 时间 | 时段 | 定位 | 标题 | 角标 | 正文 | 折叠补充 | 按钮 |
|---|---|---|---|---|---|---|---|---|
| `morning_nudge` | 10:00 | morning | 早间轻撩 | ☀️ 早上好呀 | ✨ Mory来报到啦 | 上午场景化问候+隐晦牵引 | 💬 想聊的随时来找我～ | 💌 找Mory聊聊 → @MorychannelBot |
| `afternoon_tea` | 14:30 | afternoon | 午后小确幸 | 🍵 下午茶时间到 | 🍵 Mory的小确幸 | 午后松弛场景+生活小确幸 | ☕ 累了就来找我聊聊天～ | ☕ 和Mory喝杯茶 → @MorychannelBot |
| `evening_wind` | 19:00 | evening | 傍晚陪伴 | 🌆 傍晚的风刚好 | 🌆 Mory陪你吹风 | 傍晚陪伴感+放松引导 | 🌆 一天的疲惫就让它随风去吧～ | 🌙 陪Mory看日落 → @MorychannelBot |
| `night_whisper` | 22:30 | night | 深夜悄悄话 | 🌙 夜深了 | 🌙 Mory的悄悄话 | 深夜走心+悄悄话引导 | 🌙 夜深了，有些话只适合在夜里说～ | 💌 和Mory说悄悄话 → @MorychannelBot |

**播报特性（v5.18.2 无缝升级版）**：
- HTML 卡片排版：`<b><i>emoji 标题</i></b>` + `<i>斜体角标</i>` + 正文 + `<blockquote expandable><i>折叠补充</i></blockquote>`
- Rich Message：`RICH_MESSAGE_ENABLED=true` 且 `BROADCAST_FORMAT_VERSION=rich/auto` 时优先尝试 `sendRichMessage`，失败自动回退 HTML
- 时段样式映射：`period` 字段自动选择 emoji（morning=☀️ / afternoon=🍃 / evening=🌆 / night=🌙）
- 单按钮引导：`button_text` + `button_url` 指向 @MorychannelBot
- 彩色按钮：`BUTTON_STYLE_ENABLED=true` 时读取 `button_style` / `button_emoji_id`
- 用户画像：私聊定点播报可根据 `user_profile` 做 VIP/高等级/兴趣个性化
- 模板轻变化：`BROADCAST_TEMPLATE_VARIATION_ENABLED=true` 时保留旧模板正文和按钮，只在折叠补充里每日追加轻变化句
- 静默发送：`night_whisper` 配置 `silent: true`，深夜不打扰
- 防重复：TaskTransactionManager 原子抢占，每日每播报只执行一次
- 问候话术池兜底：AI 生成失败时从 `_GREETING_FALLBACK_POOL` 随机选择，避免重复

**防重复机制**：_try_claim_and_lock原子抢占+task_log持久化
**失败重试**：关键任务失败5分钟后重试1次，仍失败私聊通知管理员

---

## 6. 环境变量

| 变量 | 用途 | 必填 |
|------|------|------|
| DASHBOARD_SECRET | Dashboard密钥(≥16位) | 是 |
| DASHBOARD_PASSWORD | Dashboard管理员密码(≥6位) | 是 |
| DASHBOARD_VIEWER_PASSWORD | Dashboard只读查看者密码 | 否 |
| DASHBOARD_PORT | Dashboard端口 | 否(默认6616) |
| VPS_HOST | VPS IP | 是 |
| VPS_SSH_PASS | VPS密码（未配置 SSH key 时需要） | 条件必填 |
| VPS_SSH_KEY | VPS SSH 私钥路径（可选；未填时尝试本机默认 key） | 否 |
| VPS_PORT | SSH端口 | 否(默认22) |
| VPS_PATH | 项目路径 | 否(默认/home/ubuntu/mory_assistant) |
| BOT_ROLE | Bot角色（避免后台任务冲突；默认 MAIN） | 否 |

---

## 7. 多项目同机边界（重要）

- 服务器上可能同时运行其他项目/其他机器人。排查本项目时，**只操作本项目目录与本项目 systemd 服务**，不要"看到 409 就乱杀进程"。
- 目前同机存在 `mory_media_assistant`（独立宣发号），它会读取主项目 `mory.db` 的 `promotions` 表做定时广播：主项目侧务必避免长事务/长时间独占锁，尽量保持写事务短小，避免把库锁死影响宣发号读取。

---

## 8. 修复历史摘要

> 仅列近期关键版本。完整修复记录见 `AI_DEBUG_HISTORY.md`，版本演进见 `CHANGELOG.md`。

| 版本 | 关键内容 |
|------|---------|
| v5.31.2 | Token 消耗暗病排查 + Loop 监控轮 1-20 多智能体联排暗病搜索 84 处修复：① 高频任务 task_log 死锁（task_key 加时间窗口后缀）② LLMCostGuard 成本熔断器启用（用户1h $1.0/全局1h $5.0）③ token_usage 记录到 data/router_usage.db（12列schema）④ WriteQueue rowcount 丢失导致所有定时任务失效 ⑤ LLMCostGuard flush_to_db 从未被调用修复 ⑥ RLock 替代 Lock 解决 add_points 重入死锁 ⑦ get_user_profile 重复定义重命名为 get_user_persona_profile ⑧ 原子 UPDATE 防止 TOCTOU 余额检查竞态 ⑨ 腾讯云 Lighthouse 监控接入 ⑩ 独立看门狗 scripts/vps_watchdog.py ⑪ _CST 时区常量全域覆盖（累计修复 40+ 处 datetime.now() 时区错位）⑫ shop.py:126 P0 SQL 列名错误修复（兑换功能 100% 失败）⑬ health_api.py 3 处 datetime.now(_CST) 残留修复 ⑭ 12 处静默吞异常升级日志级别 ⑮ 3 处幂等添加列加注释 ⑯ shop.py TOCTOU 漏洞修复（原子 SQL + rowcount 检查防积分负数）⑰ emergency_ban_ad_user.py 时区+类型不一致修复 ⑱ bot_initializer/pinyin_util 静默吞异常修复 ⑲ dashboard/app.py sqlite3.connect finally 修复。162 委托方法远程验证注册成功 |
| v5.31.1 | 四层智能体联排防御体系根治 _REPO_METHOD_MAP 漏注册沉默失败：L1启动自检(_self_check_repo_methods) + L2__getattr__ CRITICAL+re-raise + L3 scripts/verify_db_methods.py 部署前门禁 + L4 core/scheduler_monitor.py:check_critical_jobs_health 调度健康监控。162 委托方法注册验证 |
| v5.30.3 | 多智能体协作诊断+彻底修复：① `core/database.py` `_REPO_METHOD_MAP` 补注册 30 方法（ab_test 17+user 8+social 5，消除 A/B 测试持久化/增长遥测/用户画像/购物车恢复静默失效）② 服务器 `.env` `VPS_HOST` 错指 TokenLab VPS 修正 ③ `config.json` 属主修复 ④ 删除硬编码密码文件 `query_final.py` / `query_extra.py` ⑤ `core/ai_engine.py` 7 处 `except: pass` 静默吞错改 `logger.debug`。共 158 方法远程验证注册成功 |
| v5.30.1 | 修复 `_REPO_METHOD_MAP` 注册缺失（snapshot_message/mark_message_deleted/get_user_messages/get_user_undeleted_messages 4 方法），message_snapshots 30+ 版本空表根因消除 |
| v5.28.0 | 10项增长优化上线：意图路由/A-B/归因/质量评估串入AI回复链路；Dashboard增长优化汇总；质量评估低采样开启；LLM意图精分保持关闭 |
| v5.27.0-RC1 | 稳定化候选：requirements.lock 真实生成；VPS 端锁文件安装和 pip check 通过；远端缓存/pyc/reload_flag 清零；Dashboard/迁移 smoke 通过；RBAC 安全测试 6/6；metrics 改 Gauge/set 防重复虚高；双服务 active + health 200；高风险能力默认关闭 |
| v5.26.0 | 10大优化：LLM成本熔断器+Locust压测+级联告警测试+人设跨模型一致性+多模型A/B测试+记忆归因+DB迁移监控+多Bot路由+归因回放+RBAC审批流 |
| v5.25.0 | 10大优化：Dashboard API压测+WriteQueue背压+SQL乐观锁+告警风暴控制+ModelRouter多模型协同+记忆摘要+DB迁移蓝图+funnel归因+audit DB驱动权限+Locust压测 |
| v5.24.1 | 深度系统集成：WriteQueue全量化+独立告警Bot+RBAC守卫+混合记忆+归因报表+调度指标落盘+RBAC角色迁移 |
| v5.23.0 | 8大架构优化：SQLite写入队列+AI输出质量+RBAC审计+转化漏斗归因+广告拼音增强+调度可观测+混合记忆+多Bot共享表 |
| v5.22.0 | 全量审计修复：5致命+11高危+13中危暗病（SQLite高并发+CSRF+安全响应头+AI输出过滤+广告误伤修复等） |
| v5.21.0 | 人设引擎大改：4桶反模板(cold/savage/soft/common)+动态LLM参数矩阵(亲密度×场景×时段21组)+12条去AI铁律 |
| v5.20.0 | 动态意图识别与场景触发引擎：intent_router+profile_learner 6维画像+modules/triggers/ 4个场景化触发器 |
| v5.18.3 | 全量审计+代码质量修复：164处空except+每日自动备份+日志清理+文档数量修正 |
| v5.16.5 | Telegram Bot API 10.x 兼容：HTML卡片+Rich Message/Poll/Checklist+Business消息映射+广告反应治理 |
| v5.15.0 | 用户问题追踪与FAQ蒸馏系统：三表+17方法+P10钩子+FAQ匹配+自动蒸馏+10端点API |
| v5.13.0 | 全面健康诊断与暗病修复：6个VPS运行时+8个代码严重+5个中等 |
| v5.12.0 | 孤儿消息实际清理+8大类老坑规则化+项目规则归一化 |
| v5.10.3 | VPS用户统一ubuntu+项目规则整合 |
| v5.10.2 | 配置热重载+VPS配置自动补齐 |
| v5.9.0 | 项目深度清理+安全修复+Dashboard权限分级 |
| v5.7.1 | 409 Conflict死循环修复+禁用 start.sh/nohup/pm2 |
| v5.0.0 | 深度架构重构：main.py/database.py/dashboard三大巨石文件拆分 |

---

## 9. 已知平台限制

1. 群组历史消息无法访问（Telegram API限制）
2. Bot主动私信403（用户必须先联系Bot）
