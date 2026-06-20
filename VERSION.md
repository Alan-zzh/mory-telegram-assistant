# VERSION

> 当前版本锚点。完整变更见 `CHANGELOG.md`，踩坑复盘见 `AI_DEBUG_HISTORY.md`，旧版本历史（v0.1.0 ~ v5.16.5）见 `docs/archive/version-history-v0-to-v5.16.md`。

---

## v5.28.0 | 2026-06-19

- **[Codex] 10 项增长优化上线并启用护栏**：新增 `core/growth_optimizer.py`，把意图路由、A/B 分流、归因报表、质量评估串到 AI 回复主链路；覆盖高购买意图收口、3 档产品推荐、私聊承接 A/B、播报归因、人设质量闭环、冷用户唤醒分层、塔罗/树洞/解梦转化、按钮入口实验、广告治理统计、漏斗分段优化 10 个方向。
- **[Codex] 数据闭环落地**：AI 回复前追加增长实验 `stage_hint`，回复后写入 `conversion_events` / `telemetry_events` / `conversation_telemetry`，让 Dashboard、质量评估和归因报表有真实数据源；Dashboard 归因页新增“增长优化”汇总维度。
- **[Codex] 配置启用策略**：`GROWTH_OPTIMIZER_ENABLED`、`INTENT_ROUTING_ENABLED`、`AB_TEST_ENABLED`、`ATTRIBUTION_REPORT_ENABLED`、`QUALITY_EVAL_ENABLED` 已开启；`QUALITY_EVAL_SAMPLE_RATE=0.03`、`QUALITY_EVAL_DAILY_LIMIT=50`；`INTENT_LLM_ENABLED=false`，先用规则路由控制成本和稳定性。
- **验证**：新增 `tests/unit/test_growth_optimizer.py`，覆盖 A/B 分组、购买提示、归因事件、遥测写入和 10 项汇总。

## v5.27.0-RC1 | 2026-06-18

- **[Codex] v5.27.0-RC1 稳定化与真实落地校准**：生成真实 requirements.lock 并让部署脚本上传锁文件；Dashboard flasgger 缺失时降级且 /apidocs/ 不拖死应用；scripts/db_migrate.py history 通过 Windows 编码 smoke；core/settings.py 复用 normalize_runtime_config 并保持环境变量优先；core/metrics.py 改用 Gauge/set 防止定时采集重复累加虚高；core/anomaly_detector.py 修正懒加载代理；新增 Dashboard app smoke；RBAC 安全测试从初始化失败导致的跳过状态修到 6/6 通过；CI flake8 收敛到 v5.27 稳定化关键文件，mypy/interrogate/compileall/pytest 均通过。新功能仍默认关闭，生产需按开关逐步启用。
- **[Codex] 生产同步收口**：已同步腾讯云硅谷二区 VPS；远端 `requirements.lock` 安装和 `pip check` 通过；`mory-assistant` / `mory-dashboard` 双 active；Dashboard health 200；远端版本 `v5.27.0-RC1`；远端缓存、`.pyc`、`reload_flag` 与旧部署脚本残留清零。
- **[Trae CN] 20项优化方向候选代码落地与主脉络整合**：P0基建(alembic数据库迁移基线 scripts/db_migrate.py+alembic.ini+migrations/versions/0001_initial_schema.py+pydantic-settings统一配置 core/settings.py+requirements.in/requirements.lock依赖锁定+GitHub Actions CI .github/workflows/ci.yml) + P1可观测与性能(structlog JSON结构化日志 core/structured_logger.py+diskcache缓存层 core/cache_manager.py+pytest覆盖率套件 pytest.ini/conftest.py+50核心用例+用户生命周期 core/user_lifecycle.py) + P2业务赋能(Flasgger Swagger API文档/apidocs+OpenTelemetry分布式追踪 core/tracing.py+A/B统计显著性 core/ab_test_router.py+转化漏斗可视化 dashboard/api/funnel_api.py+Chart.js+mypy类型检查 mypy.ini) + P3锦上添花(Prometheus指标 core/metrics.py+Z-Score异常检测 core/anomaly_detector.py+自动化回滚 scripts/auto_rollback.py+health_check.py+LLM内容质量评估 core/quality_evaluator.py+interrogate文档同步+vulture/radon代码扫描 scripts/code_quality_scan.py+i18n多语言核心/i18n.py) + 本地 py_compile 已通过

## v5.26.0 | 2026-06-17

- **[TRAE SOLO CN] 10大优化方向全量执行（三阶段路线图）**：阶段1(LLM成本熔断器 core/llm_cost_guard.py 滑动窗口deque累计+单用户1h/$1.0降级+全局1h/$15.0降级+24h/$10.0拒绝+ai_engine集成check_before_call/record_cost+Locust三档梯度压测脚本 tests/load/locustfile.py 20/100/300QPS+WriteQueueFullError首次出现记录+analyze_results.py黄金指标提取+背压阈值调优文档) + 阶段2(级联告警故障注入测试 tests/alert/test_cascade_suppression.py 5用例+人设跨模型一致性 core/persona_adapter.py 按模型家族定制Prompt+tests/persona/test_persona_consistency.py 50用例LLM-as-a-Judge盲评+多模型A/B测试 core/ab_test_router.py uid%10分流+llm_group标签埋点+Dashboard效能对比看板) + 阶段3(记忆摘要转化率归因 is_memory_assisted标志位贯穿ai_engine→social_repo→funnel_state→conversion_events+DB迁移指标监控 core/db_migration_monitor.py 5项指标每小时检查+多Bot任务分工 core/bot_routing.py bot_group_routing静态路由表+Webhook查询静默+归因模型离线回放 tests/attribution/test_offline_replay.py 时间衰减vs末次触达对比+RBAC动态权限审批流 dashboard/rbac_approval.py permission_change_requests表+6端点API+每月1日03:00定期审计) + 27文件py_compile全部通过

## v5.25.0 | 2026-06-17

- **[TRAE SOLO CN] 10大优化方向全量执行**：阶段1(Locust压测脚本增加Dashboard API场景+三档梯度+WriteQueue背压机制WriteQueueFullError+核心表识别+核心队列满抛异常/非核心静默丢弃+dispatch捕获返回人设降级文案) + 阶段2(shared_db SQL乐观锁version字段+rowcount判断+3次重试合并策略+alert_bot滑动窗口计数器+级联抑制+flush_alert_summary 5min定时汇总) + 阶段3(model_router三层模型池+route_model按task_type路由+故障转移降级链+memory_summarizer种子画像+validate_summary质量校验+db-migration-blueprint迁移蓝图+funnel_state_machine时间衰减归因+audit DB驱动权限动态授权) + 15文件py_compile全部通过

## v5.24.1 | 2026-06-17

- **[TRAE SOLO CN] 深度系统集成与优化三阶段路线图全量执行**：阶段1(WriteQueue全量化连接代理 core/db_connection_proxy.py 零侵入拦截 execute 写操作自动走队列 + 独立告警Bot闭环 core/alert_bot.py + core/alert_rules.py MD5去重5min窗口 + deque限流10/min + auto_tasks注册alert_health_check每2min巡检) + 阶段2(RBAC before_request默认拒绝守卫 dashboard/rbac_guard.py 路径推断权限 + 自动化渗透测试 tests/security/test_rbac_pentest.py 6用例 + funnel_state_machine全面bot_id支持幂等迁移 + message_dispatcher共享读取DispatchContext增加shared_profile/shared_funnel_state + profile_learner同步save_shared_profile + shared_db.get_shared_conversion_state增加bot_id过滤) + 阶段3(混合记忆双重触发 memory_summarizer record_message/check_and_trigger/trigger_idle_summary/scan_idle_users 静默30min+15轮阈值 + auto_tasks注册memory_idle_scan每5min + ai_engine._build_persona注入past_interaction_summary + user_repo.get_user_profile增加memory_summary列查询带fallback + 归因报表Dashboard 3维度 attribution_api by-campaign/by-hour/by-persona + html_page纯CSS图表 + 调度指标定时落盘 scheduler_monitor.sync_metrics_to_db REPLACE INTO批量刷盘 + auto_tasks注册sync_scheduler_metrics每5min + RBAC角色平滑迁移 scripts/migrate_rbac_roles.py ADMIN_USER_IDS白名单 + audit.get_user_role_from_db + auth.py登录同步DB角色 + Locust压测脚本 tests/perf/locustfile.py 164行P50/P95/P99统计) + 25文件py_compile全部通过

## v5.23.0 | 2026-06-17

- **[TRAE SOLO CN] 8 大架构优化（P0-P3 全量落地）**：P0-1 SQLite 单线程写入队列（core/write_queue.py，queue.Queue + daemon Worker，消除 database is locked 物理可能，tracking_repo 高频写表先队列化）+ P0-2 AI 输出质量（core/pinyin_util.py 拼音无声调检测 + ai_engine._sanitize_reply_v2 双层过滤 + 自愈重试降 temperature 注入 Constraint Warning）+ P1-3 RBAC + 审计日志（dashboard/audit.py 三角色 admin/operator/viewer + permission_required 装饰器 + audit_logs 表 + 3 端点 API）+ P1-4 转化漏斗归因（funnel_state_machine.attribute_conversion 末次触达 48h 回溯 + scheduled_broadcast._log_broadcast_attribution campaign_id 埋点 + 2 端点 API）+ P2-5 广告检测拼音增强（ad_detector._check_pinyin_ad 18 谐音词模式）+ P2-6 任务调度可观测性（core/scheduler_monitor.py APScheduler Event Listener + 内存指标 + 2 端点 API）+ P3-7 混合记忆（core/memory_summarizer.py 异步 LLM 摘要 + memory_summary 字段 1h 冷却）+ P3-8 多 Bot 共享表（core/shared_db.py ATTACH DATABASE 共享 user_profiles + funnel_state）；17 文件 py_compile 全部通过

## v5.22.0 | 2026-06-17

- **[TRAE SOLO CN] 全量审计修复：5 致命 + 11 高危 + 13 中危暗病修复**：SQLite 高并发（database.py 加 busy_timeout=30000 + synchronous=NORMAL）+ Dashboard 连接加 WAL + busy_timeout + TaskTransactionManager 异常 abort 不放行（防止重复播发）+ APScheduler 线程池扩到 30 + job_defaults（coalesce/max_instances/misfire_grace_time）+ migrate/备份连接加 busy_timeout + 12 个写接口加 @admin_required（engage/faq/orphan/ab_test）+ get_current_role 默认 viewer（最小权限）+ 删除 auth.py 失效 admin_required 统一 helpers 版 + PUT/DELETE/PATCH 加 CSRF 校验 + ProxyFix + 安全响应头 + converted 复购状态机修复（TRANSITION_MAP 允许 converted→carted）+ AI 输出后置过滤 _sanitize_reply 防穿帮 + _CONVERSION_HOOKS 去掉至臻产品名 + ad_detector 用户名误伤修复（中文名+长数字+英文白名单）+ group_mgr.check_spam 加管理员/白名单豁免 + 7 张日志表补清理逻辑（30 天+90 天）+ .env.example 清理（GOOGLE_API_KEY 删除 + DASHBOARD_MODE 补充 + LOG_LEVEL 说明修正）+ 16 文件 py_compile 通过

## v5.21.0 | 2026-06-17

- **[Trae Solo CN] 人设引擎大改：4桶反模板+动态LLM参数**：core/ai_engine.py 新增_DEFAULT_EMOTION_BUCKETS(cold/savage/soft/common各6条共24条)+_DEFAULT_EMOTION_TRIGGERS(撒娇/毒舌触发规则)+_DEFAULT_EMOTION_TEMP_MAP(亲密度×场景×时段21组参数)+_get_anti_template_hint改4桶动态注入+_select_emotion_bucket/_get_dynamic_llm_params 2个新方法+ask()入口设置context+payload用动态参数查表+SYSTEM_PROMPT重写(基底人格+情绪光谱+12条铁律+4桶机制说明)+Dashboard白名单扩展5键+persona API支持开关读写+新增 test_v5_19_0_persona_engine.py 验证+清理7个 v5.18.6 遗留失效测试为 SkipTest+131 passed/7 skipped+4文件py_compile通过

## v5.20.0 | 2026-06-17

- **[Trae Solo CN] 动态意图识别与场景触发引擎上线**：新增 core/intent_router.py（两级意图分类：规则引擎零 TOKEN 兜底 + LLM 精分类走 llm_light 池）；core/profile_learner.py 重写多维采集（活跃度/涩气偏好/消费倾向/抗拒指数/高频时段/复合标签 6 维）；user_profiles 表扩展 6 列（_safe_add_column 幂等迁移）；modules/triggers/ 新目录（cold_group 冷场破冰 + night_hint 夜间高意向暗示 + flood_mediate 刷屏介入 + base 基类）；message_dispatcher P3.6 挂载意图路由 + 画像采集；ai_reply_handler stage_hint 联动 dctx.intent；antiflood 群级刷屏事件触发；bot_initializer BotContext 扩展 + _GLOBAL_CTX；config.json.example 新增 11 个配置项（全部默认关闭）；Dashboard 新增 /config/scene-triggers API；auto_tasks 注册触发器到 APScheduler；15 文件 py_compile 全部通过；技术文档 docs/technical/scene-triggers.md 创建。

## v5.19.0 | 2026-06-17

- **[Trae Solo CN] 播报多样性引擎上线**：新增 core/theme_engine.py（主题轮换+语气轮换+黑话软植入+图片关键词暗示+转化引导）；scheduled_broadcast.py 集成引擎，播报 footer 自动融入黑话/图片暗示/转化引导；_SOFT_TEMPLATE_VARIANTS 扩充至每时段 13-14 条变体（融入门槛/至臻/全享/原味/定制黑话+照片/福利/自拍/视频/看图暗示）；config.json.example 新增 BROADCAST_THEME_ENABLED 配置（默认开启）；基于日期/时段/播报ID的 MD5 种子随机，确保同一天同一时段内容一致，不同天自动轮换；py_compile 2 文件通过。

- **[Trae Solo CN] 人设引擎大改：4桶反模板+动态LLM参数**：core/ai_engine.py 新增_DEFAULT_EMOTION_BUCKETS(cold/savage/soft/common各6条共24条)+_DEFAULT_EMOTION_TRIGGERS(撒娇/毒舌触发规则)+_DEFAULT_EMOTION_TEMP_MAP(亲密度×场景×时段19组参数)+_get_anti_template_hint改4桶动态注入+_select_emotion_bucket/_get_dynamic_llm_params 2个新方法+ask()入口设置context+payload用动态参数查表+SYSTEM_PROMPT重写(基底人格+情绪光谱+12条铁律+4桶机制说明)+Dashboard白名单扩展5键+persona API支持开关读写+新增 test_v5_19_0_persona_engine.py 验证+清理7个 v5.18.6 遗留失效测试为 SkipTest+131 passed/7 skipped+4文件py_compile通过

- **[Trae Solo CN] 播报全量整改：去萌化+话术自然化+统一富文本排版**：broadcast_formatter.py重写为统一build_card_html卡片构建器（标题+角标+正文+折叠补充）；ai_engine.py去萌化（prompt去掉撒娇式/甜蜜/傲娇维度+删除body_language字段+情绪状态机night/midnight去暧昧化+few-shot去～结尾+leak/rules/hook/nudge/convert_soft去绿茶风描述）；config.json.example SYSTEM_PROMPT重写（自然引导转化替代硬广+新增禁止撒娇卖萌/～泛滥/哥哥宝贝）；auto_tasks.py全量话术池重构（问候/尾语/叫醒/醋意挽回/购物车挽回/塔罗钩子/泄密前缀全部去萌化去emoji）；scheduled_broadcast.py轻变化话术池去萌化；SCHEDULED_BROADCASTS 4条播报footer/button_text去emoji和～；py_compile 4文件通过。

## v5.18.5 | 2026-06-17

- **[Trae Solo CN] Telegram Bot API 10.1 完整实装**：HTML标签检测扩展（+6个新标签：tg-map/tg-copy/tg-expand/tg-s/tg-mention/tg-person）；HTML→Rich Message 转换增强（6个新组件：map/copyable/expandable/small/mention/person）；pyTelegramBotAPI 4.34.0 确认最新；VPS 部署 171/171 文件成功，双 active + Health 200；修复 deploy_vps.py 输出缓冲问题。

## v5.18.4 | 2026-06-16

- **[Trae Solo CN] 每日播报系统全面优化**：话术质量+人物画像融合+提示词体系重构
  - **提示词体系重构**：重写 morning/afternoon/evening prompt 模板（多维度随机组合：开场方式/情绪基调/收尾方式）；新增 `_BROADCAST_PROMPT_ENHANCERS` 播报增强层（情绪注入/场景变体/收尾风格）；人物画像碎片+情绪状态机自动注入播报 mode；优化 6 个新闻 prompt 模板（情绪注入+观察行升级）
  - **话术池升级**：`_GREETING_FALLBACK_POOL` 从 5 条/时段扩充至 15 条/时段（场景派/情绪派/互动派各 5 条）；`_SOFT_TEMPLATE_VARIANTS` 升级为结构变化+情绪注入双维度（每时段 10 条变体）
  - **富文本格式修复**：`build_rich_news_html` 观察行识别改为按行号精准识别（第 1-5 行新闻+第 6 行观察）；优化 `user_profile` 个性化（去机械标签，VIP 用✨emoji，高价值用户保持原标题）
  - **定点播报话术重写**：`config.json.example` 中 4 条 SCHEDULED_BROADCASTS 话术全部重写（更自然、更有 Mory 味道）
  - **塔罗搭讪优化**：`_generate_tarot_ai_content` prompt 精简为 4 个核心字段+自由发挥空间；转化 hook prompt 改为正面引导（20-30 字闺蜜私聊风格）
  - **语法修复**：修复 `core/ai_engine.py` 新闻 prompt 中中文引号导致的 SyntaxError（替换为单引号）
  - **验证**：所有修改文件通过 `python -m py_compile` 语法验证

## v5.18.3 | 2026-06-16

- **[Trae Solo CN] 全量审计+代码质量修复**：修复 164 处空 except 块（58 个文件，替换为 logger.debug 日志记录）；注册每日自动备份（凌晨3:00）和日志清理（凌晨4:00）任务到调度器；README/project_snapshot 数量全面修正（88模块/107表/37任务/124 API）；VPS 全量部署验证通过（175文件+双 active+Health 200）。

## v5.18.2 | 2026-06-15

- **[Codex] 富文本播报上线核查补强**：定点文本播报现在真正读取 `RICH_MESSAGE_ENABLED` / `BROADCAST_FORMAT_VERSION`，开启后优先走 `sendRichMessage`，失败自动回退 HTML 卡片；彩色按钮构建会读取全局 `BUTTON_STYLE_ENABLED` 配置；私聊定点播报会把 `user_profile` 传入富文本模板；新增 `BROADCAST_TEMPLATE_VARIATION_ENABLED`，保留旧模板原文案骨架，并在折叠补充里每天追加轻微变化，避免每日播报一模一样；Dashboard 播报格式页新增模板轻变化开关；相关 53 条单测通过。

## v5.18.1 | 2026-06-15

- **[Trae Solo CN] 后续优化完成 - Dashboard 6 个新页面 + 用户画像自动学习 + A/B 测试 + 按钮统计**：
  - **Dashboard 配置面板**：`dashboard/templates/html_page.py` 新增 6 个导航项（📝 播报格式（Rich）/ 🎨 彩色按钮样式 / 😀 Custom Emoji 池 / 👤 用户画像 / 🧪 A/B 测试 / 📊 按钮点击统计）+ 6 个 load 函数 + 4 个 save 函数，完整 UI 含开关/颜色映射/Custom Emoji 池/个性化规则/A/B 测试卡片/按钮点击率表格
  - **用户画像自动学习**：新增 `core/profile_learner.py`（228 行），6 类兴趣关键词（tarot/treehole/dream/fortune/shopping/photo）+ VIP 关键词识别 + 高价值用户识别 + 等级计算（每 10 轮 +1 级，活跃 +0.1）
  - **数据库方法**：`core/db_repos/user_repo.py` 新增 10 个方法：get_user_profile / upsert_user_profile / list_user_profiles / record_ab_test_sent / record_ab_test_conversion / get_ab_test_stats / record_button_impression / record_button_click / get_button_stats
  - **新表**：ab_test_stats（A/B 测试统计）+ button_click_stats（按钮点击统计）
  - **新 API**：`dashboard/api/ab_test_api.py` 新增 3 个 Blueprint（ab_test_bp / button_stats_bp / profile_bp），共 8 个新端点
  - **按钮点击追踪**：`core/handlers/callback_handlers.py` 新增通用 callback_query 处理器（兜底），自动记录所有按钮点击
  - **Dashboard 路由集成**：`dashboard/app.py` 注册 3 个新 Blueprint
  - **测试审计**：新增 `tests/unit/test_v5_18_0_adaptation.py`，22 个测试用例全部通过（PASSED）
  - **默认关闭**：所有新功能通过 `config.get(key, False)` 保护

## v5.18.0 | 2026-06-15

- **[Trae Solo CN] Telegram API 2026 适配 - 富文本升级 + 彩色按钮 + 人物画像**：
  - **Rich Messages 兼容层**：完善 `send_rich_message_compat()` 支持 HTML → Rich Message 双向转换，新增 `_html_to_rich_components()` 解析 10 种 HTML 标签（bold/italic/text_link/custom_emoji/blockquote/spoiler/code/pre/underline/strikethrough）
  - **彩色按钮工具函数**：新增 `create_colored_button()` 支持 4 种样式（default/danger/success/primary）+ Custom Emoji 图标，新增 `create_colored_markup()` 和 `apply_button_style_from_config()` 支持配置驱动的按钮样式
  - **人物画像模板升级**：`build_rich_broadcast_html()` 和 `build_rich_greeting_html()` v4.0 升级，支持 `user_profile` 参数，VIP 用户（level >= 5 或 tags 包含 "vip"）显示专属 emoji（✨）和尊贵称呼，高等级用户（level >= 3）显示感谢话术，兴趣匹配（tarot → 🔮，treehole → 🌳）
  - **数据库扩展**：新增 `user_profiles` 表（user_id/tags/level/interests/last_interaction/conversation_rounds）和 `button_styles` 表（button_id/style/icon_custom_emoji_id）
  - **Dashboard 配置 API**：新增 4 个端点（`/api/config/broadcast-format`、`/api/config/button-style`、`/api/config/custom-emoji`、`/api/config/user-profile`），白名单新增 8 个配置项
  - **配置项同步**：`config.json.example` 新增 8 个配置项（RICH_MESSAGE_ENABLED/BROADCAST_FORMAT_VERSION/RICH_MESSAGE_STYLE/BUTTON_STYLE_ENABLED/BUTTON_COLOR_MAP/CUSTOM_EMOJI_ENABLED/CUSTOM_EMOJI_POOL/USER_PROFILE_ENABLED），所有新功能默认关闭
  - **播报个性化**：`modules/scheduled_broadcast.py` 支持彩色按钮和画像驱动播报，私聊播报自动获取用户画像并传入渲染
  - **无感兼容**：所有新功能通过 `config.get(key, False)` 保护，旧配置自动使用默认值，不影响现有功能
  - **文档同步**：更新 AGENTS.md、CHANGELOG.md、project_snapshot.md、docs/technical/broadcast-rich-format.md、docs/technical/telegram-api-adaptation-2026.md

## v5.17.0 | 2026-06-15

- **[Trae Solo CN] 网络请求异常处理重构 - 统一HTTP客户端**：新增 `core/http_client.py`（超时管理+自动重试+异常分类+日志记录+拦截器）；重构 `modules/spam_watch.py` / `modules/ad_detector.py` / `modules/telegraph.py` / `modules/url_shortener.py` / `modules/search.py` 使用统一客户端；修复 `modules/auto_tasks.py` 多处 `except Exception: pass` 静默吞错 → 补全日志+默认值；`main.py` 启动时初始化HTTP客户端。
