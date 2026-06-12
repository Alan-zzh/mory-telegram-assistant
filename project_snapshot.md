# Mory小助理 项目快照 v5.16.2

> 新AI会话必读：本文件 + `AGENTS.md`（项目规则+老坑铁律） + `AI_DEBUG_HISTORY.md`
> 最后更新：2026-06-12（v5.16.2 [Codex] 广告治理不踢人策略纠正）

---

## 1. 项目概览

| 项目 | 值 |
|------|-----|
| 名称 | Mory小助理 - 运营型商业 AI 转化机器人 |
| 版本 | v5.16.2 |
| 技术栈 | Python3 + pyTelegramBotAPI + SQLite(WAL) + Flask + gunicorn+gevent |
| 部署 | VPS（systemd作为唯一进程管理） |
| 存储 | `mory.db`(SQLite) + `config.json`(配置) |
| 红线 | 绝对不能因报错导致程序卡死崩溃 |
| 广告治理 | [Codex] 不踢人：永久禁言 + 删除消息 + 双黑名单 + 历史消息追踪清理 |

---

## 2. 目录结构

```
mory_assistant/
├── main.py                 # 精简入口（133行：初始化→注册→启动）
├── config.json             # 运行时配置（Token/管理员/模型池/人设）
├── config.json.example     # 配置模板（无密钥，可提交Git）
├── .env                    # 环境变量（不提交Git）
├── .env.example            # 环境变量模板
├── .gitignore              # Git忽略规则
├── requirements.txt        # Python 依赖
├── version.py              # 版本号统一管理
├── deploy_vps.py           # VPS一键部署脚本（systemd管理+安全配置合并）
├── sync_vps.py             # VPS同步代理脚本
├── windows_helper.py       # Windows辅助工具
├── start_dashboard.py      # Dashboard启动脚本
├── deploy.bat              # Windows部署入口
├── start_dashboard.bat     # Windows启动Dashboard
├── Dockerfile              # Docker镜像定义
├── docker-compose.yml      # Docker编排配置
├── core/
│   ├── __init__.py         # 核心模块导出
│   ├── bot_initializer.py  # Bot初始化工厂（BotContext+22步初始化流程）
│   ├── message_dispatcher.py # 消息分发核心（P0-P10优先级+DispatchContext，1627行）
│   ├── ai_engine.py        # AI引擎（三层路由+多模型轮换+TTS语音）
│   ├── trendradar_news.py  # 新闻获取（TrendRadar+fetch_real_news）
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
│   ├── migrate.py          # 数据库迁移工具
│   ├── vps_config.py       # VPS连接配置
│   ├── handlers/           # 消息处理器（按优先级组织）
│   │   ├── __init__.py
│   │   ├── member_handlers.py    # P0入群/退群
│   │   ├── callback_handlers.py  # 回调查询+/settings
│   │   ├── media_handlers.py     # 图片/语音/频道帖子
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
├── modules/
│   ├── __init__.py
│   ├── admin_cmds.py       # 管理员指令
│   ├── ad_detector.py      # 广告检测引擎（五级检测L0-L4+延迟封禁）
│   ├── ad_patterns_encoded.py  # 编码后的广告关键词（Unicode转义防拦截）
│   ├── auto_tasks.py       # 定时任务（TaskTransactionManager统一事务+原子抢占防重复+数据库持久化+失败重试）
│   ├── avatar_detector.py  # 色情头像检测
│   ├── emoji_mask_detector.py # Emoji面具检测
│   ├── content.py          # 内容处理（图片打码+频道转发+勋章）
│   ├── group_mgr.py        # 群管理（入群欢迎/敏感词/刷屏/黑名单/广告拦截）
│   ├── keyword_trigger.py  # 关键词触发（静态/AI/动作三种回复模式）
│   ├── natural_cmd.py      # 自然语言指令（塔罗/解梦/树洞/配置修改）
│   └── optimizer_admin.py  # 运营管理指令（数据看板/转化统计）
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
│   │   ├── settings_api.py # 设置面板API
│   │   └── faq_api.py      # 【v5.15.0新增】FAQ统计与管理API（10端点）
│   └── templates/
│       └── html_page.py    # 前端HTML模板
├── config/                 # 服务配置
│   ├── mory-assistant.service      # Bot systemd服务（含EnvironmentFile）
│   ├── mory-dashboard.service       # Dashboard systemd服务（gunicorn+gevent）
│   ├── mory-media-assistant.service # 媒体Bot systemd服务
│   └── mory-media-dashboard.service # 媒体Bot Dashboard（端口6617，独立数据库）
├── scripts/                # 调试/诊断/扫描工具
│   ├── debug_db.py         # VPS数据库查询诊断
│   ├── debug_vps.py        # VPS全面诊断脚本
│   ├── deep_check.py       # 深度关键词触发诊断
│   ├── find_bug.py         # 历史日志错误排查
│   ├── full_diagnosis.py   # VPS全功能诊断报告
│   ├── get_keyword_module.py  # 关键词模块获取
│   ├── restart_bot.py      # Bot重启工具
│   ├── restore_after_reinstall.py  # 重装后恢复
│   ├── test_connection.py  # 通义千问API连接测试
│   ├── test_vps_ai.py      # VPS AI功能数据检查
│   └── README.md           # 工具说明
├── backups/                # 自动备份（保留最近2个server_pull备份）
├── BOT_投喂与自然语言配置说明.md  # Bot投喂与配置说明
├── project_snapshot.md     # 本文件
├── AI_DEBUG_HISTORY.md     # 调试病历本
├── CHANGELOG.md            # 变更日志
├── VERSION.md              # 版本号
└── README.md               # 项目入口文档
```

---

## 3. 数据库表（mory.db · 88张表）

> 实际数量：core/database.py 中 85 个 `CREATE TABLE IF NOT EXISTS` 语句（v5.13.0 实测，含 `conversions` 新表 + `orphan_cleanup_log` 和 `broadcast_tracking`）

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
| L1 | 用户名+Bio+头像 | 用户资料 | 三层命中=直接ban | 高置信度组合信号 |
| L2 | 消息内容关键词 | 消息文本 | 1~4/维度 | 9个维度权重各异 |
| L3 | 零宽字符+元数据 | 消息结构 | +1~+2 | 零宽占比>20%额外+2 |
| L4 | 追溯扫描 | 历史消息/数据库 | — | Bot启动时自动扫描+手动/scan_ads |

**L0 外部数据库**：CAS（api.cas.chat）+SPB（api.intellivoid.net），仅辅助评分防误封，结果缓存1小时

**L1 用户资料检测**：
- 用户名检测（USERNAME_PATTERNS）："看简介"变体→直接ban；短随机用户名→score+2
- Bio检测（BIO_PATTERNS）：赚钱承诺/引流话术/t.me链接/刷礼物/私信/滴滴/1000U→score+3
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
- Dashboard权限分级：admin（读写）/ viewer（只读）

### 4.4 进程红线（务必遵守）
- **生产环境只允许 systemd 管理本项目进程**：只用 `sudo systemctl restart mory-assistant` / `systemctl status mory-assistant`。
- **Dashboard 也由 systemd 管理**：`sudo systemctl restart mory-dashboard` / `systemctl status mory-dashboard`（服务文件：config/mory-dashboard.service）。
- **绝对禁止**：`pm2`、手动 `python main.py`、`nohup python start_dashboard.py` 去启动/重启生产服务，否则极易多开导致 Telegram `409 Conflict`（同 token 多个 getUpdates）或端口冲突。
- `start.sh` 已在v5.1.0中删除，统一使用systemd管理。

---

## 5. 定时任务

| 任务 | 时间 | 防重复 |
|------|------|--------|
| 早安问候 | 8:05 | _try_claim_and_lock原子抢占+task_log持久化 |
| 早间新闻 | 9:05 | 同上 |
| 每日报告 | 9:10 | 同上 |
| 午安问候 | 12:35 | 同上 |
| 午间新闻 | 13:05 | 同上 |
| 塔罗搭讪 | 15:00 | 同上 |
| TrendRadar播报 | 18:00 | 同上 |
| 晚间新闻 | 20:35 | 同上 |
| 晚安问候 | 23:05 | 同上 |
| 频道浏览量 | 每小时 | — |
| 阅后即焚清理 | 每10分钟 | — |

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
| VPS_SSH_PASS | VPS密码 | 是 |
| VPS_PORT | SSH端口 | 否(默认22) |
| VPS_PATH | 项目路径 | 否(默认/home/ubuntu/mory_assistant) |
| BOT_ROLE | Bot角色（避免后台任务冲突；默认 MAIN） | 否 |

---

## 7. 多项目同机边界（重要）

- 服务器上可能同时运行其他项目/其他机器人。排查本项目时，**只操作本项目目录与本项目 systemd 服务**，不要"看到 409 就乱杀进程"。
- 目前同机存在 `mory_media_assistant`（独立宣发号），它会读取主项目 `mory.db` 的 `promotions` 表做定时广播：主项目侧务必避免长事务/长时间独占锁，尽量保持写事务短小，避免把库锁死影响宣发号读取。

---

## 8. 修复历史摘要

| 版本 | 修复数 | 关键内容 |
|------|--------|---------|
| v5.15.0 | 新增 | 用户问题追踪与FAQ蒸馏系统：user_questions/faq_knowledge/faq_candidates三表+QuestionRepo 17方法+P10问题记录钩子+FAQ匹配回复(ai_polish润色)+_job_faq_distill自动蒸馏+Dashboard /api/faq/* 10端点+双开关(FAQ_TRACKING_ENABLED/FAQ_AUTO_REPLY_ENABLED) |
| v5.14.2 | 1项 | 入群即检测三重广告信号：member_handlers步骤2.5+50个历史可疑用户清理 |
| v5.14.0 | 新增 | 商业问题主动搭讪引导：convert关键词6→50+/P7.5主动搭讪层/30分钟冷却/4端点Dashboard API |
| v5.13.0 | 19项 | 全面健康诊断与暗病修复：6个VPS运行时（开机自启+speech_stats Cursor+不活跃清理类型+fault_reporter缺失+conversions表+last_active不更新）+8个代码严重（网络超时+沉默失败11处+循环依赖确认+TOKEN泄露+无锁全局状态+N+1查询+漏注册确认+12配置键缺失）+5个中等（Dashboard /api/health+API信息泄露22处+API Key脱敏+积分转账原子性+孤儿清理修复） |
| v5.12.1 | 5项 | 项目规则归一化（.agents→AGENTS.md 大写显式+业务核心目标/历史文档优先原则/技术边界/5条核心教训/8条跨AI一致性铁律F1-F8）+ 47 个根目录 _*.py 归档 tests/_archive/ + 5 个 docs 迁到 docs/technical/（kebab-case）+ 6 个技术文档全部 ≤200 行 + 活跃引用清理 |
| v5.12.0 | 10项 | 孤儿消息实际清理（orphan_cleanup_log + /api/orphan/stats 3 端点 + verify_orphan_cleanup.py 脚本 + ENABLE_MESSAGE_DELETION 关闭告警）+ 8 大类老坑规则化（.agents 新增铁律章节 + docs/ 技术细节文档索引）+ project_rules.md 合并删除 |
| v5.11.0 | 5项 | 群播报自动删除：孤儿 30S 删 + 早安/午安/晚安链式互删 + broadcast_tracking 表 + 顺手修 track_bot_message 漏注册 |
| v5.10.4 | 1项 | AI 认知纠正文档：Bot API 限制已有解决方案写入项目规则 |
| v5.10.3 | 2项 | VPS 用户统一 ubuntu + .agents 项目规则整合 |
| v5.10.2 | 5项 | 配置热重载 + VPS 配置自动补齐 + 3 项 Bug 修复（ANTI_CHANNEL_DEFAULT / ANTIFLOOD_CONFIG / SESSION_COOKIE_SECURE） |
| v5.10.1 | 6项 | 强制订阅 + 全局黑名单 + 35+ 开关默认关闭 + P9-P12 完成 + threading 崩溃修复 |
| v5.9.0 | 10项 | 项目深度清理(19垃圾文件+5脚本迁移+ai_engine_standalone删除+telegram_stats删除)+安全修复(anti_raid私聊+monitoring数据库读取+deploy_utils重叠消除)+Dashboard权限分级(admin/viewer) |
| v5.8.4 | 4项 | Pyrogram全量扫描5811人(95.7%覆盖)+封禁2广告号+HIGH_NAME级封禁规则 |
| v5.8.3 | 7项 | 广告检测5规则漏洞修复+2误报修正+全量扫描封禁11人 |
| v5.8.2 | 4项 | 消息发送者追踪+显示名广告检测+UNAME_ONLY级别+消息历史扫描 |
| v5.8.1 | 5项 | 两层组合直接封禁+全量扫描+group_members表+chat_member handler |
| v5.8.0 | 6项 | CAS/SPB集成+白名单+三层组合封禁+消息元数据检测+L0-L4规范 |
| v5.7.5 | 5项 | Bio检测(BIO_PATTERNS)+短随机用户名+头像检测触发扩展 |
| v5.7.4 | 4项 | 零宽字符绕过修复+零宽占比可疑信号+谐音变体补全 |
| v5.7.3 | 4项 | 阅后即焚三层保障+track_bot_message+启动补清理 |
| v5.7.2 | 4项 | L4追溯广告扫描+双模式+/scan_ads命令+RETROACTIVE_SCAN配置 |
| v5.7.1 | 3项 | 409 Conflict死循环修复+分发顺序修复 |
| v5.7.0 | 9项 | AI引擎全量修复：user_profile/seed+news_content+模型遍历+线程安全+VPS空TOKEN |
| v5.6.2 | 6项 | 广告检测彻底修复：L3兜底+连续消息独立化+强制删除+评分权重+2字符词 |
| v5.6.1 | 3项 | 连续消息模式检测+色情引流词扩充+uname_clean修复 |
| v5.6.0 | 4项 | 广告检测全面升级：头像检测+名称检测+头像相似度+启动追溯 |
| v5.5.0 | 3项 | 广告检测去重(130行→1行)+密钥环境变量优先+Dashboard缓存 |
| v5.4.0 | 8项 | SSH密钥验证+CSRF Token+死锁修复+DB锁优化+签到N+1+校准逻辑 |
| v5.3.0 | 6项 | 意图分类+亲密度5级系统+4级挑逗话术+7场景模拟+转化引导+去AI化 |
| v5.2.0 | 4项 | 动态人格随机化系统：碎片池+情绪状态机+Few-shot+反模板 |
| v5.0.0 | 15项 | 深度架构重构：main.py/database.py/dashboard三大巨石文件拆分 |

详细修复记录见 `AI_DEBUG_HISTORY.md`。

---

## 9. 已知平台限制

1. 群组历史消息无法访问（Telegram API限制）
2. Bot主动私信403（用户必须先联系Bot）
