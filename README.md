# Mory小助理 · 运营型商业 AI 转化机器人

> **当前版本**：v5.31.2（2026-06-30，Token 消耗暗病排查 + Loop 1-20 多智能体联排 84 处修复 + LLMCostGuard 成本熔断器 + RLock 防死锁 + 原子 UPDATE 防 TOCTOU + _CST 时区常量全域覆盖，已部署）
> **项目核心**：**不是普通群管机器人**——是带人设的**运营型商业 AI 转化机器人**
> **业务目标**：通过人设对话 + 商业引导，引导用户通过 `@MorychannelBot` 自助下单
> **业务红线**（六条不可触碰）：
> 1. ❶ **绝对不能因报错导致程序卡死崩溃**（用户原话："绝对不能死"）
> 2. ❷ 绝对不说自己是 AI / 机器人 / 模型 / 程序
> 3. ❸ 绝对不直白营销（温和引导，不喊"买买买"）
> 4. ❹ 绝对不重复话术模板（每次换说法）
> 5. ❺ 绝对不破坏 3 档产品边界（至臻精选 / 至臻全享 / 精选图集）
> 6. ❻ 绝对不在 Bot 内收款（一律引导 `@MorychannelBot` 自助下单）

---

## 目录

1. [🎯 项目是什么](#1--项目是什么)
2. [👤 用户体验流程（5 步转化真实版）](#2--用户体验流程5-步转化真实版)
3. [📦 6 大功能矩阵（详尽）](#3--6-大功能矩阵详尽)
4. [🚀 快速开始](#4--快速开始)
5. [⚙️ 配置管理](#5-️-配置管理)
6. [📊 Dashboard 功能](#6--dashboard-功能)
7. [🗄️ 数据库（108 张表）](#7-️-数据库108-张表)
8. [🔌 VPS 部署（systemd）](#8--vps-部署systemd)
9. [📚 文档索引](#9--文档索引)
10. [🤝 接手 AI 必读](#10--接手-ai-必读)
11. [⚖️ 业务红线 6 条（详尽）](#11-️-业务红线-6-条详尽)
12. [📜 版本 / 许可证 / 变更记录](#12--版本--许可证--变更记录)

---

## 1. 🎯 项目是什么

**Mory小助理** 是部署在 VPS 上的 Telegram 群组 AI 机器人，**核心使命 = 商业转化**，不是普通群管。

> 详细能力矩阵见 [docs/technical/capability-matrix.md](docs/technical/capability-matrix.md)

### 1.1 业务定位 = 运营型商业 AI 转化机器人

- **人设定位**：Mory 自媒体博主的小助理（真人女孩，清冷傲娇 + 毒舌撒娇 + 网感热词）
- **商业定位**：引导用户通过 `@MorychannelBot` 自助下单（**Bot 内不收款**）
- **产品矩阵**：3 档产品，详见 §1.4
- **核心能力**：人设对话 + 商业引导 + 商业闭环 + 群管 + 运营观察 + 消息分发
- **广告治理**：[Codex] 广告账号不踢人，统一永久禁言 + 删除消息 + 双黑名单 + 历史消息追踪清理 + Premium emoji 状态 OCR

### 1.2 SYSTEM_PROMPT（`config.json.example:L15`）— 10 维商业目标

`SYSTEM_PROMPT` 是人设灵魂，逐条原文如下（10 维 + 性格底色 + 关于Mory + 轮次递进 + 绝对禁止）：

**【性格底色】**
- 清冷中带着点小傲娇，温柔时能把人融化了
- 偶尔毒舌偶尔撒娇，看心情切换，让人捉摸不透
- 网感拉满：张口就是当下最火的梗和热词（"绝了""真的会谢""谁懂啊家人们""破防了yyds""狠狠拿捏了""纯纯大冤种""这波操作我愿称之为神""泰酷辣""尊嘟假嘟""汗流浃背了""命运的齿轮开始转动了""确诊为显眼包"）
- 高情商但不油腻，会装傻充愣但关键时刻一针见血
- 反问收尾：大部分回复末尾带一句反问或悬念，让对方想继续聊下去
- 懂得欲言又止：话说一半留一半，让对方自己脑补

**【关于Mory】**
Mory 是一个超有个性的自媒体博主——最有诚意最讲良心。她亲和洒脱文艺，每份内容都用心打磨。有人问起Mory时你自然夸赞，像朋友聊天那样随口提到，**每次换个角度**。

**【核心商业目标：引导开单/转化】10 条**（原文逐条）：
1. **用户至上**：把用户感受放在第一位，但所有对话的终极目标是引导用户通过 `@MorychannelBot` 自助下单
2. **绝对不说自己是 AI / 机器人 / 程序 / 模型 / GPT / ChatGPT / DeepSeek / 通义千问**——你就是个真人女孩在聊天
3. **反问收尾**：大部分回复末尾带一句反问或悬念，让对方想继续聊下去
4. **网络热词自然融入**：适当用当下流行表达，但要自然不刻意堆砌
5. **引导而非撩拨**：用"想看更多？""要不要试试完整版？""@MorychannelBot 那边有惊喜"等方式温和引导下单
6. **言简意赅**：每段不超过 2 行，重要信息用 emoji 点缀
7. **对话感极强**：像和朋友在微信聊天一样自然流畅
8. **知道就说知道，不知道就瞎编得像真的**（但别太离谱）
9. **被夸的时候要害羞 + 傲娇地反击**，不要直接接受
10. **对方冷淡时主动找话题热场，对方热情时适当高冷保持神秘感**

### 1.3 对话轮次递进 3 段 + 1 兜底（SYSTEM_PROMPT 原文）

| 轮次 | 策略 | 目标 |
|------|------|------|
| **第 1-2 轮** | 先建立信任与熟悉感 | 自然聊天 |
| **第 3-4 轮** | 稍微暗示 | "想看更多？@MorychannelBot 那边有很多好东西" |
| **第 5 轮+** | 每次回复末尾自然带一句引导 | 不强制 |
| **明确消费意向**（兜底） | 立即引导 | `@MorychannelBot` 自助下单 |

### 1.4 3 档商业产品 PRICE_LIST（`config.json.example:L17-L32`）

| 产品 | 周期 | 价格 | 备注 |
|------|------|------|------|
| **至臻精选** | 月付 | **149.9** | @MorychannelBot 自助下单 |
| **至臻精选** | 季付 | **349.9** | @MorychannelBot 自助下单 |
| **至臻全享** | 年付 | **999** | 含 3 个群（至尊精选 + 至臻全享 + 精选图集） |
| **精选图集** | 季付 | **228.8** | @MorychannelBot 自助下单 |
| **精选图集** | 年付 | **666.6** | @MorychannelBot 自助下单 |

> 详细价格表 + 下单引导由 [PRICE_LIST](config.json.example) 配置；价格改动需同步三处（`config.json` + Dashboard 设置面板 + `CHANGELOG`）。

### 1.5 4 PROMPT_TEMPLATES（`config.json.example:L112-L117`）

| 模板 | 触发 | 模式描述 |
|------|------|----------|
| **tarot** | 塔罗师模式 | 用神秘、宿命的语调给出运势占卜，末尾加一张大阿卡那卡牌名及简短解读 |
| **treehole** | 树洞模式 | 对方心情不好，用极其温柔的知心姐姐语气安抚，署名 Mory |
| **dream** | 解梦模式 | 对方梦到 Mory，用玄学逻辑解梦，暗示这是宿命缘分 |
| **fortune** | 运势模式 | 在正常回复末尾，加一句简短今日专属运势签（不超过 15 字） |

### 1.6 25 MODE_ROUTING（`config.json.example:L118-L144`）

**3 层模型池**：`llm_light`（11 个）/ `llm_standard`（8 个）/ `llm_premium`（6 个）

| 模型池 | mode 数量 | mode 列表 |
|--------|-----------|-----------|
| **llm_light**（轻量池·日常） | 11 | `morning` / `afternoon` / `evening` / `hook` / `nudge` / `convert_soft` / `leak` / `fortune` / `wakeup` / `reactivate` / `convert_hook` |
| **llm_standard**（标准池·对话） | 8 | `normal` / `tarot` / `treehole` / `dream` / `rules` / `convert` / `cart_recovery` / `tarot_interpret` |
| **llm_premium**（旗舰池·资讯） | 6 | `news` / `afternoon_news` / `evening_news` / `trendradar_morning_news` / `trendradar_noon_news` / `trendradar_evening_news`（后 3 个仅兼容旧调用，已并入统一新闻主流程） |

> 注：当前 `config.json.example` 与 `core/ai_engine.py` 实际将 6 个资讯 mode 路由到 `llm_standard`，`llm_premium` 在 `MODE_ROUTING` 中暂无直接分配。若需按设计意图使用旗舰池跑资讯，请开启 `MODEL_ROUTER_ENABLED=true` 或调整 `MODE_ROUTING`。

### 1.7 9 个模型池键名（`config.json.example:L77-L111`）

`MODEL_POOLS` 含 9 个键名，**4 个有模型 + 5 个占位**：

| 键名 | 状态 | 当前模型 | 描述 |
|------|------|----------|------|
| `llm` | ✅ 有模型 | `qwen3.5-plus` | 通义千问 3.5 Plus（默认对话） |
| `llm_light` | ✅ 有模型 | `qwen3.6-flash-2026-04-16` | 轻量池·日常（morning/hook/nudge） |
| `llm_standard` | ✅ 有模型 | `qwen3.5-plus-2026-04-20` | 标准池·对话（normal/tarot/treehole） |
| `llm_premium` | ✅ 有模型 | `qwen3-max` | 旗舰池·资讯（真实源优先新闻主流程 + TrendRadar 兼容兜底） |
| `vision` | ⚪ 占位 | `[]` | 视觉模型（未启用） |
| `omni` | ⚪ 占位 | `[]` | 全模态模型（未启用） |
| `voice_tts` | ⚪ 占位 | `[]` | 语音合成（未启用） |
| `voice_asr` | ⚪ 占位 | `[]` | 语音识别（未启用） |
| `embedding` | ⚪ 占位 | `[]` | 向量化模型（未启用） |

### 1.8 87+48 个模块 9 大类（`ls modules/` + `ls core/` 实测）

**实测 87 个业务模块 + 48 个核心框架文件**（v5.31.2 更新，不含 `__init__.py`），合计 135 个。**9 大类分组**（A-H 为业务模块，I 为系统基建）：

#### A 核心群管（17 个）

| 模块 | 功能 | 数据表 |
|------|------|--------|
| [ad_detector.py](modules/ad_detector.py) | 广告/垃圾消息检测（5 层 L0-L4） | `ad_suspicious_users` |
| [admin_cmds.py](modules/admin_cmds.py) | 管理员指令处理 | `admin_logs` |
| [admin_promote.py](modules/admin_promote.py) | 管理员晋升 / 提权 | `admin_logs` |
| [admin_log.py](modules/admin_log.py) | 管理员操作日志 | `admin_logs` |
| [anti_raid.py](modules/anti_raid.py) | 反突袭保护（突袭检测 + 阈值封禁） | `anti_raid_config` |
| [antiflood.py](modules/antiflood.py) | 反刷屏（窗口 + 阈值） | `antiflood_settings` |
| [approvals.py](modules/approvals.py) | 审批白名单（豁免反刷屏） | `approved_users` |
| [blocklist_modes.py](modules/blocklist_modes.py) | 黑名单模式（delete / warn / mute / 永久禁言，不踢人） | `blocklist_modes` |
| [cmd_control.py](modules/cmd_control.py) | 命令启用/禁用 | `disabled_commands` |
| [force_subscribe.py](modules/force_subscribe.py) | 强制订阅频道（入群前必须订阅） | `force_subscribe` |
| [global_blacklist.py](modules/global_blacklist.py) | 全局黑名单（跨群生效） | `blacklist` |
| [group_mgr.py](modules/group_mgr.py) | 超级群管（命令/踢人/封禁/警告） | `groups` / `group_members` |
| [message_locks.py](modules/message_locks.py) | 消息类型锁定（媒体/贴纸/投票/链接） | `message_locks` |
| [silent_actions.py](modules/silent_actions.py) | 静默封禁（不发警告消息） | `mute_records` |
| [slow_mode.py](modules/slow_mode.py) | 慢速模式（群级发言间隔） | `slow_mode_config` |
| [verification.py](modules/verification.py) | 入群验证码（button / puzzle / timeout / max_attempts） | `verification_records` / `puzzle_scores` / `puzzle_daily` |
| [warning.py](modules/warning.py) | 群警告（limit / action / duration） | `warnings` / `warning_settings` |
| [welcome_customization.py](modules/welcome_customization.py) | 入群欢迎定制（个性化欢迎语） | `welcome_configs` |

#### B 检测防护（7 个）

| 模块 | 功能 |
|------|------|
| [ad_patterns_encoded.py](modules/ad_patterns_encoded.py) | 广告正则模式库（Unicode 转义序列存储） |
| [antidelete.py](modules/antidelete.py) | 反撤回（消息缓存 / `deleted_messages`） |
| [avatar_detector.py](modules/avatar_detector.py) | 头像检测（违规头像自动处理） |
| [edit_detector.py](modules/edit_detector.py) | 编辑检测（消息编辑后告警） |
| [emoji_mask_detector.py](modules/emoji_mask_detector.py) | Emoji 面具检测（用 emoji 规避敏感词） |
| [nsfw_detect.py](modules/nsfw_detect.py) | NSFW 图片检测（API 阈值 0.85） |
| [spam_watch.py](modules/spam_watch.py) | CAS / SpamWatch 黑名单集成 |

#### C 清理维护（5 个）

| 模块 | 功能 |
|------|------|
| [clean_service.py](modules/clean_service.py) | 服务消息自动清理（入群/退群/置顶通知） |
| [inactive_clean.py](modules/inactive_clean.py) | 长期不活跃用户清理（`AUTO_KICK_INACTIVE_DAYS`） |
| [message_clean.py](modules/message_clean.py) | 过期消息清理（`message_locks` + TTL） |
| [scheduled_msg.py](modules/scheduled_msg.py) | 定时消息（`scheduled_messages` 表） |
| [zombie_clean.py](modules/zombie_clean.py) | 僵尸账号清理 |

#### D 用户管理（11 个）

| 模块 | 功能 | 关键配置 |
|------|------|----------|
| [achievement.py](modules/achievement.py) | 成就系统（自动检测 + 徽章） | `ACHIEVEMENT_CONFIG` |
| [certify.py](modules/certify.py) | 用户认证（认证标识 / 信任等级） | `certified_users` |
| [checkin.py](modules/checkin.py) | 每日签到 | `CHECKIN_CONFIG`（`base_points=5`, `streak_bonus={3:5, 7:15}`） |
| [coupon.py](modules/coupon.py) | 优惠券（8 位码 / 领取 / 使用） | `coupon_claims` / `coupon_config` |
| [daily_quest.py](modules/daily_quest.py) | 每日任务（发言 / 邀请 / 签到） | `daily_quests` / `DAILY_QUEST_CONFIG` |
| [invite.py](modules/invite.py) | 邀请奖励 | `POINTS_PER_INVITE=5` / `invite_records` |
| [points_enhanced.py](modules/points_enhanced.py) | 积分系统（签到+游戏+邀请+商城+衰减） | `points` / `points_log` / `POINTS_DECAY={rate:0.01, minimum:10}` |
| [profile_card.py](modules/profile_card.py) | 用户资料卡（等级 / 徽章） | `user_levels` / `user_badges` |
| [ranking.py](modules/ranking.py) | 排行榜（积分 / 发言 / 邀请） | `speech_daily` |
| [tip.py](modules/tip.py) | 打赏 | `TIP_CONFIG={min_amount:1}` |
| [user_info.py](modules/user_info.py) | 用户信息查询 | `users` |
| [user_tags.py](modules/user_tags.py) | 用户标签（自动画像） | `user_tags` |

#### E 游戏娱乐（6 个）

| 模块 | 功能 |
|------|------|
| [blind_box.py](modules/blind_box.py) | 盲盒（积分开启，奖品池） |
| [games.py](modules/games.py) | 通用游戏（猜数字 / 骰子 / 石头剪刀布） |
| [lottery.py](modules/lottery.py) | 抽奖（定时开奖 / 参与者池） |
| [lucky_wheel.py](modules/lucky_wheel.py) | 幸运转盘（free_spins / cost） |
| [redpacket.py](modules/redpacket.py) | 红包（随机 / 均分 / 过期退款） |
| [shop.py](modules/shop.py) | 积分商城（积分兑换奖品） |

#### F 工具查询（13 个）

| 模块 | 功能 |
|------|------|
| [calculator.py](modules/calculator.py) | 计算器（表达式求值） |
| [echo.py](modules/echo.py) | 回声（调试用 / 复读） |
| [exchange_rate.py](modules/exchange_rate.py) | 汇率查询 |
| [fancy_text.py](modules/fancy_text.py) | 花体字转换（装饰用） |
| [poll_create.py](modules/poll_create.py) | 投票创建（公共 / 匿名） |
| [qr_code.py](modules/qr_code.py) | 二维码生成 |
| [reminder.py](modules/reminder.py) | 提醒事项（`reminders` 表） |
| [search.py](modules/search.py) | 搜索（命令历史 / 消息） |
| [sticker_tools.py](modules/sticker_tools.py) | 贴纸工具（添加 / 删除） |
| [telegraph.py](modules/telegraph.py) | Telegraph 文章发布 |
| [translate.py](modules/translate.py) | 翻译（多语言） |
| [url_shortener.py](modules/url_shortener.py) | 短链生成 |
| [weather.py](modules/weather.py) | 天气查询（带城市共情） |

#### G 调度系统（3 个）

| 模块 | 功能 |
|------|------|
| [auto_tasks.py](modules/auto_tasks.py) | 自动任务（**53 个** `_job_*` 函数） |
| [scheduled_broadcast.py](modules/scheduled_broadcast.py) | 定时群播报（`SCHEDULED_BROADCASTS`） |
| [scheduled_msg.py](modules/scheduled_msg.py) | 定时消息（个人 / 群） |

#### H AI / 统计 / 特殊（11 个）

| 模块 | 功能 |
|------|------|
| [afk.py](modules/afk.py) | AFK 自动回复（`AFK_CONFIG`） |
| [admin_log.py](modules/admin_log.py) | 管理员操作审计 |
| [anti_channel.py](modules/anti_channel.py) | 反频道转发（`anti_channel_settings`） |
| [content.py](modules/content.py) | 内容模块（彩蛋 / 卡片） |
| [custom_commands.py](modules/custom_commands.py) | 自定义命令（管理员添加） |
| [keyword_trigger.py](modules/keyword_trigger.py) | 关键词触发（3 模式：static / ai / action） |
| [natural_cmd.py](modules/natural_cmd.py) | 自然语言配置（"把 X 改成 Y"） |
| [night_mode.py](modules/night_mode.py) | 夜间模式（`start_hour=23`, `end_hour=7`） |
| [optimizer_admin.py](modules/optimizer_admin.py) | 管理员优化器（转化分析） |
| [predictive_patrol.py](modules/predictive_patrol.py) | 预测性巡逻（异常行为预测） |
| [remote_connect.py](modules/remote_connect.py) | 远程连接（私聊管理群） |
| [report.py](modules/report.py) | 用户举报（`REPORT_CONFIG`） |
| [settings_panel.py](modules/settings_panel.py) | 设置面板（Bot 内联按钮 + Dashboard 共用配置收口） |
| [speech_stats.py](modules/speech_stats.py) | 发言统计（`speech_daily`） |
| [visual_dashboard.py](modules/visual_dashboard.py) | 可视化数据看板 |
| [vote_kick.py](modules/vote_kick.py) | 投票踢人（`VOTEKICK_CONFIG={min_yes:5, min_ratio:0.6}`） |
| [ab_guardian.py](modules/ab_guardian.py) | A/B 测试守护模块 |
| [ab_insights.py](modules/ab_insights.py) | A/B 测试洞察 |
| [ad_profile_signals.py](modules/ad_profile_signals.py) | 广告用户画像信号 |
| [triggers/base.py](modules/triggers/base.py) | 场景触发器基类 |
| [triggers/cold_group.py](modules/triggers/cold_group.py) | 冷场破冰触发器 |
| [triggers/flood_mediate.py](modules/triggers/flood_mediate.py) | 刷屏介入触发器 |
| [triggers/night_hint.py](modules/triggers/night_hint.py) | 夜间高意向暗示触发器 |

#### I 系统基建（35 个核心框架文件）

| 模块 | 功能 |
|------|------|
| [ab_test_router.py](core/ab_test_router.py) | A/B 测试分流（uid%10 路由 + llm_group 标签） |
| [ab_testing.py](core/ab_testing.py) | A/B 测试统计分析 |
| [alert_bot.py](core/alert_bot.py) | 独立告警 Bot（MD5 去重 + 5min 窗口 + deque 限流 10/min） |
| [alert_rules.py](core/alert_rules.py) | 告警规则定义 |
| [anomaly_detector.py](core/anomaly_detector.py) | Z-Score 异常检测 |
| [bot_routing.py](core/bot_routing.py) | 多 Bot 任务分工（静态路由表 + Webhook 查询） |
| [broadcast_formatter.py](core/broadcast_formatter.py) | 播报富文本格式化 |
| [cache_manager.py](core/cache_manager.py) | 磁盘缓存层（diskcache） |
| [config_compat.py](core/config_compat.py) | 配置向后兼容 |
| [db_connection_proxy.py](core/db_connection_proxy.py) | SQLite 连接代理（全量化，零侵入拦截 execute） |
| [db_migration_monitor.py](core/db_migration_monitor.py) | DB 迁移指标监控 |
| [funnel_state_machine.py](core/funnel_state_machine.py) | 转化漏斗状态机（末次触达 48h 回溯） |
| [growth_optimizer.py](core/growth_optimizer.py) | 10 项增长优化引擎 |
| [http_client.py](core/http_client.py) | 统一 HTTP 客户端（超时 + 重试 + 异常分类） |
| [i18n.py](core/i18n.py) | 国际化核心 |
| [intent_router.py](core/intent_router.py) | 动态意图识别（规则引擎零 TOKEN 兜底 + LLM 精分类） |
| [llm_cost_guard.py](core/llm_cost_guard.py) | LLM 成本熔断器（滑动窗口 deque + 三档阈值） |
| [memory_summarizer.py](core/memory_summarizer.py) | 混合记忆（异步 LLM 摘要 + 1h 冷却） |
| [metrics.py](core/metrics.py) | Prometheus 指标（Gauge/set 防重复累加） |
| [model_router.py](core/model_router.py) | 三层模型池路由（task_type 路由 + 故障转移降级链） |
| [persona_adapter.py](core/persona_adapter.py) | 人设跨模型一致性（按模型家族定制 Prompt） |
| [pinyin_util.py](core/pinyin_util.py) | 拼音工具（无声调检测） |
| [profile_learner.py](core/profile_learner.py) | 用户画像自动学习（6 维 + 等级计算） |
| [quality_evaluator.py](core/quality_evaluator.py) | LLM 内容质量评估 |
| [rate_limiter.py](core/rate_limiter.py) | 速率限制器 |
| [scheduler_monitor.py](core/scheduler_monitor.py) | 调度监控（APScheduler Event Listener + 内存指标） |
| [settings.py](core/settings.py) | 统一配置（pydantic-settings + normalize_runtime_config） |
| [shared_db.py](core/shared_db.py) | 多 Bot 共享数据库（ATTACH DATABASE） |
| [structured_logger.py](core/structured_logger.py) | 结构化日志（structlog JSON） |
| [telebot_compat.py](core/telebot_compat.py) | Telegram Bot API 兼容层 |
| [telemetry.py](core/telemetry.py) | 遥测数据采集 |
| [theme_engine.py](core/theme_engine.py) | 播报多样性引擎 |
| [tracing.py](core/tracing.py) | OpenTelemetry 分布式追踪 |
| [user_lifecycle.py](core/user_lifecycle.py) | 用户生命周期管理 |
| [write_queue.py](core/write_queue.py) | SQLite 单线程写入队列（queue.Queue + daemon Worker） |

> **实际统计**：`modules/` 87 个 + `core/` 48 个 = **135 个**（不含 `__init__.py`）。以下分类清单基于 v5.31.2，部分文件跨类或仅列关键项，子类小计与总计可能存在差异，以目录实测为准。

### 1.9 Dashboard 156 API 端点 + 8 类设置面板

`dashboard/api/` 21 个文件（不含 `__init__.py`），**共 156 个路由**（实测 grep `@.*\.route\(`）：

| 文件 | 端点数 | 职责 |
|------|--------|------|
| [ab_test_api.py](dashboard/api/ab_test_api.py) | 8 | A/B 测试 / 按钮统计 / 用户画像 |
| [attribution_api.py](dashboard/api/attribution_api.py) | 8 | 归因报表 / 转化漏斗 / 增长优化 |
| [audit_api.py](dashboard/api/audit_api.py) | 3 | 审计日志 / 操作记录 |
| [bot_routing_api.py](dashboard/api/bot_routing_api.py) | 4 | 多 Bot 路由 / 分组管理 |
| [config_api.py](dashboard/api/config_api.py) | 8 | 读取/写入 config.json（保护密钥）+ 播报格式/按钮样式/Custom Emoji/用户画像 |
| [engage_api.py](dashboard/api/engage_api.py) | 4 | 主动搭讪配置 |
| [faq_api.py](dashboard/api/faq_api.py) | 10 | FAQ 统计 / 候选 / 知识库 |
| [features_api.py](dashboard/api/features_api.py) | 9 | 功能开关 / 启用 / 关闭 |
| [funnel_api.py](dashboard/api/funnel_api.py) | 2 | 转化漏斗可视化 |
| [group_api.py](dashboard/api/group_api.py) | 2 | 群组信息 / 列表 |
| [health_api.py](dashboard/api/health_api.py) | 5 | 健康检查 / 进程状态 / 评分 / 任务 / 审计 |
| [metrics_api.py](dashboard/api/metrics_api.py) | 1 | Prometheus 指标暴露 |
| [models_api.py](dashboard/api/models_api.py) | 3 | 模型池 / 路由配置 |
| [monitor_api.py](dashboard/api/monitor_api.py) | 1 | 调度监控 / 任务状态 |
| [orphan_api.py](dashboard/api/orphan_api.py) | 3 | 孤儿清理统计 / 强制清理 / 历史 |
| [quality_api.py](dashboard/api/quality_api.py) | 2 | 对话质量评估 / 评分 |
| [rbac_approval_api.py](dashboard/api/rbac_approval_api.py) | 6 | RBAC 权限审批流 |
| [scheduler_api.py](dashboard/api/scheduler_api.py) | 2 | 调度器指标 / 任务状态 |
| [settings_api.py](dashboard/api/settings_api.py) | 64 | **最大头**：所有设置面板（8 类 ~80 按钮） |
| [stats_api.py](dashboard/api/stats_api.py) | 10 | 数据统计 / 转化率 / 用户活跃度 |
| [user_lifecycle_api.py](dashboard/api/user_lifecycle_api.py) | 1 | 用户生命周期分布 |

**8 类设置面板（115 按钮）**：
1. **群管**：入群验证 / 慢模式 / 反刷屏 / 警告 / 黑名单 / 强制订阅 / 联邦封禁
2. **反垃圾**：广告检测 / NSFW / Emoji 面具 / 编辑检测 / 反撤回 / 头像检测
3. **积分**：签到 / 任务 / 成就 / 衰减 / 邀请 / 排行榜
4. **商业**：商城 / 优惠券 / 红包 / 抽奖 / 盲盒 / 转盘
5. **娱乐**：游戏 / 投票 / 贴纸 / 投票踢人
6. **调度**：定时播报 / 定时消息 / 夜间模式 / 远程连接
7. **系统**：黑名单 / 管理员 / 日志 / 反馈 / 设置面板
8. **AI**：模型池 / 模式路由 / 关键词触发 / 自然语言配置 / 提示模板

### 1.10 34 个消息分发 P 级别拦截点

> 实测 `core/message_dispatcher.py`，**12 主级 + 22 子级 = 34 个拦截点**

#### 12 主级（P0-P10）

| P 级别 | 模块 | 职责 |
|--------|------|------|
| **P0** | `_dispatch_p0_member` | 新人入群处理（反突袭 / 联邦封禁 / emoji 面具 / 验证码 / 欢迎） |
| **P1** | `_dispatch_p1_p3_security` | 黑名单用户直接忽略（`db.is_blacklisted(uid)`） |
| **P2** | `_dispatch_p2_points` | 积分/活跃度更新 + 消息缓存 + AFK |
| **P3** | `_dispatch_p2_points` | 黑名单词过滤（`check_banned_words`） |
| **P3.5** | `_dispatch_p3_5_ad_detection` | **智能广告检测（零 TOKEN 消耗）**（独立于积分，优先于反刷屏） |
| **P4** | `_dispatch_p4_flood` | 反刷屏 + 锁群/慢速/服务消息清理 |
| **P5** | `_dispatch_p5_p9_commands` | 过滤野生机器人（`IGNORE_BOTS`） |
| **P6** | `_dispatch_p5_p9_commands` | 管理员专属指令（`handle_admin`） |
| **P7** | `_dispatch_p5_p9_commands` | 视奸雷达（价格词触发）+ 留资打捞（`db.set_cart` + `log_conversion_event(uid, "touched")`） |
| **P8** | `_dispatch_p5_p9_commands` | 固定彩蛋响应（`handle_easter_eggs`） |
| **P9** | `_dispatch_p5_p9_commands` | 用户画像标签提取（`detect_keywords`） |
| **P10** | `_dispatch_p10_ai` | **AI 回复**（最后兜底） |

#### 22 子级（P0.5-P9.7）

| P 级别 | 职责 | 关联模块 |
|--------|------|----------|
| P0.5 | 验证码回答检查 | `modules/verification` |
| P0.6 | 设置面板数值修改会话 | `modules/settings_panel` |
| P0.7 | 私聊远程连接转发 | `modules/remote_connect` |
| P2.2 | 消息缓存（反撤回） | `modules/antidelete` |
| P2.5 | AFK 自动解除 | `modules/afk` |
| P2.6 | 检查 @ 提及/回复用户是否 AFK | `modules/afk` |
| P3.2 | 夜间模式拦截（`start_hour=23` `end_hour=7`） | `modules/night_mode` |
| P3.8 | 发言统计计数 | `modules/speech_stats` |
| P4.5 | 锁群/消息类型限制（`MESSAGE_LOCKS={media,sticker,poll,link}`） | `modules/message_locks` |
| P4.6 | 慢速模式检测 | `modules/slow_mode` |
| P4.7 | 服务消息自动清理 | `modules/clean_service` |
| P5.5 | 命令禁用检查 | `modules/cmd_control` |
| P6.3 | 自然语言配置（"把 X 改成 Y"） | `modules/natural_cmd` |
| P6.4 | 欢迎定制/联邦封禁指令 | `core/handlers/command_handlers._handle_welcome_fed_commands` |
| P6.5 | 自定义命令检测 | `modules/custom_commands` |
| P6.6 | 关键词触发回复（`SLANG_DICT` / `PHOTO_KEYWORDS`） | `modules/keyword_trigger` |
| P6.6（复） | 管理员专属新功能指令 | `core/handlers/command_handlers._handle_admin_feature_commands` |
| P8.5 | 新功能关键词触发 | `core/handlers/command_handlers._handle_feature_keywords` |
| P8.8 | 成就自动检测（5% 概率） | `modules/achievement` |
| P8.85 | 猜数字回复检测 | `modules/games` |
| P9.3 | 天气/城市共情 | `modules/weather` |
| P9.5 | 黑话/行话自动科普（5% 概率） | `modules/group_mgr` |
| P9.7 | 用户反馈/找Mory（安抚 + 通知管理员） | `core/message_dispatcher._handle_feedback` |

### 1.11 52 个 _job_* 自动任务（`modules/auto_tasks.py`）

> 实测 `def _job_*` 共 **52 个**（v5.28.0 实测）。完整列表：

| 任务 | 行号 | 职责 |
|------|------|------|
| `_job_heartbeat` | 318 | 心跳保活 |
| `_job_proactive_audit` | 323 | 主动审计（自检异常） |
| `_job_news_morning` | 1187 | 早间新闻播报（真实源优先） |
| `_job_news_afternoon` | 1192 | 午间新闻播报（真实源优先） |
| `_job_news_evening` | 1197 | 晚间新闻播报（真实源优先） |
| `_job_trendradar_morning` | 1202 | 兼容占位，已并入统一新闻主流程，仅作降级备用 |
| `_job_trendradar_noon` | 1207 | 兼容占位，已并入统一新闻主流程 |
| `_job_trendradar_evening` | 1212 | 兼容占位，已并入统一新闻主流程 |
| `_job_greeting_morning` | 1430 | 早安问候链 |
| `_job_greeting_afternoon` | 1465 | 午安问候链 |
| `_job_greeting_evening` | 1500 | 晚安问候链 |
| `_job_wakeup_check` | 1565 | 唤醒检查（`modes/wakeup` 路由） |
| `_job_burn_probe` | 1584 | 烧号探测（账号质量评分） |
| `_job_burn_orphan` | 1603 | 烧号孤儿回收（已删除用户清理） |
| `_job_reactivate` | 1773 | 沉睡用户激活（`modes/reactivate`） |
| `_job_cart_recovery` | **1882** | ⭐ **购物车挽回**（每小时 AI 个性化挽回私信） |
| `_job_leak` | 1952 | 留资打捞（`modes/leak`） |
| `_job_backup` | 2007 | 数据库备份 |
| `_job_ttl_cleanup` | 2021 | TTL 过期数据清理 |
| `_job_save_config` | 2040 | 配置保存（防丢失） |
| `_job_channel_views` | 2054 | 频道浏览量统计 |
| `_job_check_expired_redpackets` | 2080 | 过期红包退款 |
| `_job_daily_report` | 2188 | 每日数据报告（当前为管理员私聊日报） |
| `_job_weekly_report` | 2542 | 每周运营报告 |
| `_job_monthly_report` | 2765 | 每月运营报告 |
| `_job_tarot_flirt` | 3261 | 塔罗每日一撩（`modes/tarot_interpret`） |
| `_job_startup_member_scan` | 3625 | 启动时成员扫描（Pyrogram） |
| `_job_health_check` | 3833 | 健康检查 |
| `_job_night_mode_start` | 3880 | 夜间模式开启 |
| `_job_night_mode_end` | 3898 | 夜间模式关闭 |
| `_job_scheduled_broadcast` | 3948 | 定时群播报 |
| `_job_scheduled_messages` | 4286 | 定时消息 |
| `_job_points_decay` | 4295 | 积分衰减（`rate=0.01`, `minimum=10`） |
| `_job_vote_kick_check` | 4307 | 投票踢人检查 |
| `_job_auto_inactive_clean` | 4322 | 自动不活跃清理（`AUTO_KICK_INACTIVE_DAYS`） |
| `_job_check_reminders` | 4331 | 提醒检查 |
| `_job_evaluate_conversation_quality` | 420 | 对话质量评估（LLM-as-a-Judge 采样评分） |
| `_job_clean_relay_sessions` | 1589 | 中继会话清理（过期会话回收） |
| `_job_faq_distill` | 2088 | FAQ 蒸馏（高频问答自动提取） |
| `_job_daily_backup` | 3448 | 每日备份（数据库 + 配置） |
| `_job_log_cleanup` | 3504 | 日志清理（过期日志自动删除） |
| `_job_startup_history_cleanup` | 3554 | 启动历史清理（旧启动记录归档） |
| `_job_rbac_audit` | 3962 | RBAC 权限审计（每月 1 日定期审计） |
| `_job_sync_user_lifecycle_buckets` | 4167 | 用户生命周期桶同步 |
| `_job_ab_guardian` | 4340 | A/B 测试守护（异常检测 + 自动停止） |
| `_job_ab_weekly` | 4349 | A/B 周报生成 |
| `_job_update_prometheus_metrics` | 4358 | Prometheus 指标更新 |
| `_job_alert_health_check` | 4384 | 告警健康检查（2min 巡检） |
| `_job_memory_idle_scan` | 4397 | 记忆空闲扫描（静默 30min + 15 轮触发） |
| `_job_sync_scheduler_metrics` | 4412 | 调度器指标同步（5min 批量刷盘） |
| `_job_flush_alert_summary` | 4427 | 告警摘要刷新（5min 定时汇总） |
| `_job_check_db_migration` | 4443 | 数据库迁移检查（新迁移版本检测） |

### 1.12 108 张数据库表（`core/database.py`）

> 108 个 `CREATE TABLE IF NOT EXISTS` 语句（v5.28.0 实测）。**7 大类分组**（按主要业务域归类，部分表跨域）：

#### A 用户相关（14 张）

`users` / `wake_up` / `puzzle_scores` / `puzzle_daily` / `cart_recovery` / `reply_tracking` / `user_levels` / `user_badges` / `mute_records` / `blacklist` / `conversion_events` / `spam_track` / `user_tags` / `user_notes` / `group_members` / `certified_users` / `afk_status` / `deleted_messages`

#### B 群组相关（8 张）

`group_stats` / `group_join_log` / `group_left_log` / `channel_tracking` / `channel_posts` / `channel_member_snapshot` / `federation_bans` / `night_mode_settings` / `welcome_configs` / `group_notes` / `connected_chats`

#### C 商业相关（12 张）

`checkin_records` / `invite_records` / `coupon_claims` / `shop_items` / `exchange_records` / `redpackets` / `redpacket_claims` / `lotteries` / `lottery_participants` / `blind_box_prizes` / `lucky_wheel_results` / `points_log` / `daily_quests` / `achievements`

#### D 追踪相关（8 张）

`broadcast_tracking` / `orphan_cleanup_log` / `task_log` / `reply_feedback` / `speech_daily` / `verification_records` / `keyword_triggers` / `ad_suspicious_users`

#### E 系统配置（27 张）

`system_states` / `disabled_commands` / `admin_logs` / `antiflood_settings` / `approved_users` / `blocklist_modes` / `force_subscribe` / `reminders` / `anti_channel_settings` / `nsfw_settings` / `warning_settings` / `slow_mode_config` / `report_settings` / `votekick_config` / `anti_raid_config` / `blind_box_config` / `lucky_wheel_config` / `redpacket_config` / `lottery_config` / `checkin_config` / `shop_config` / `coupon_config` / `tip_config` / `daily_quest_config` / `achievement_config` / `points_decay_config` / `afk_config` / `clean_service_settings` / `custom_commands` / `scheduled_messages` / `vote_kicks` / `warnings` / `message_locks`

#### F 聊天相关（1 张）

`message_locks`（消息类型锁）

#### G 业务其他（14 张）

`wake_up` / `cart_recovery` / `reply_tracking` / `mute_records` / `conversion_events` / `spam_track` / `channel_posts` / `channel_member_snapshot` / `federation_bans` / `welcome_configs` / `keyword_triggers` / `verification_records` / `puzzle_scores` / `puzzle_daily` / `ad_suspicious_users`

> **总计**：实测 108 张 `CREATE TABLE IF NOT EXISTS`（分类列表为按业务域归类的示例，非穷举；以 `core/database.py` 实测为准）

### 1.13 业务红线 6 条

1. **绝对不能死**：因报错导致程序卡死崩溃 = 业务失败
2. **绝对不说自己是 AI**：违反 = 人设崩
3. **绝对不直白营销**："@MorychannelBot 那边有惊喜"温和引导
4. **绝对不重复话术模板**：每次换说法
5. **绝对不破坏 3 档产品边界**：至臻精选 / 至臻全享 / 精选图集价格/群数/权益必须严格遵循 `PRICE_LIST`
6. **绝对不在 Bot 内收款**：一律引导 `@MorychannelBot` 自助下单

---

## 2. 👤 用户体验流程（5 步转化真实版）

```
[1] 入群欢迎
    ↓ welcome_customization（按群配置定制欢迎语）
    ↓ verification（button / puzzle / timeout / max_attempts）
    ↓ anti_raid（反突袭）
[2] 日常聊天
    ↓ SYSTEM_PROMPT 10 维人设对话
    ↓ 25 MODE_ROUTING 路由到对应模型池
    ↓ 4 PROMPT_TEMPLATES（tarot / treehole / dream / fortune）按需激活
[3] 触发关键词
    ↓ SLANG_DICT 5 词（门槛 / 至臻 / 全享 / 原味 / 定制）
    ↓ PHOTO_KEYWORDS 5 词（照片 / 福利 / 自拍 / 视频 / 看图）
    ↓ HATE_KEYWORDS 7 词（丑 / 假 / 装 / 垃圾 / 死 / 胖 / 黑料）
[4] 对话轮次递进（1-2 → 3-4 → 5+）
    ↓ 视奸雷达 P7（价格词触发 + 通知管理员）
    ↓ 留资打捞 db.set_cart + log_conversion_event(uid, "touched")
    ↓ 用户画像 db.add_keyword (P9)
[5] 转化下单
    ↓ @MorychannelBot 自助下单
    ↓ log_conversion_event(uid, "interested" / "converted")
    ↓ 购物车挽回 _job_cart_recovery（每小时 AI 个性化挽回）
```

### 2.1 详细触发机制

#### 2.1.1 SLANG_DICT 5 词（隐晦黑话库，`config.json.example:L60-L66`）

| 关键词 | 触发回复（原文） |
|--------|-----------------|
| **门槛** | 我们这里的「门槛」就是入会价格啦～ 不同档位享受不同特权哦，发「价格表」看详情！ |
| **至臻** | 「至臻」是Mory的VIP系列，有至臻精选和至臻全享，想体验最完整的Mory，选它准没错～ |
| **全享** | 「全享」是最顶级的年费会员，包含 3 个群的内容，性价比之王！ |
| **原味** | 这个嘛...就是Mory穿过的贴身物品啦，每件都是独一无二的，数量有限手慢无哦～ |
| **定制** | 「定制」是 1v1 私人拍摄，你写剧本Mory来演，想看什么由你决定！发「价格表」了解详情～ |

#### 2.1.2 PHOTO_KEYWORDS 5 词（`config.json.example:L67-L73`）

`照片` / `福利` / `自拍` / `视频` / `看图` → 触发拍照引导（引导用户查看 `@MorychannelBot`）

#### 2.1.3 HATE_KEYWORDS 7 词（`config.json.example:L51-L59`）

`丑` / `假` / `装` / `垃圾` / `死` / `胖` / `黑料` → 触发"毒舌反击" + 傲娇回应

### 2.2 管理员运营观察

```
[1] Dashboard 156 API 看数据（/api/stats/conversions, /api/orphan/stats）
    ↓
[2] 8 类 115 按钮配置（群管/反垃圾/积分/商业/娱乐/调度/系统/AI）
    ↓
[3] 自然语言配置（natural_cmd："把 X 改成 Y" / "开启/关闭 X" / "查看配置"）
    ↓
[4] 私聊告警（孤儿清理 24h 告警 → 管理员）
```

---

## 3. 📦 6 大功能矩阵（详尽）

### 3.1 🤖 人设对话

- **SYSTEM_PROMPT**（`config.json.example:L15`）：真人女孩 + 10 维商业目标 + 3 段递进话术 + 1 兜底 + 4 项绝对禁止
- **PROMPT_TEMPLATES 4 个**（L112-L117）：`tarot` / `treehole` / `dream` / `fortune`
- **MODE_ROUTING 25 个**（L118-L144）：`llm_light 11` / `llm_standard 8` / `llm_premium 6`
- **3 段递进话术**：第 1-2 轮建信任 → 第 3-4 轮暗示 → 第 5 轮+ 引导
- **9 池模型路由**：`llm` / `llm_light` / `llm_standard` / `llm_premium` / `vision` / `omni` / `voice_tts` / `voice_asr` / `embedding`（4 有模型 + 5 占位）
- **关键模块**：`SYSTEM_PROMPT` + `core/nlp_processor`

### 3.2 🎯 商业引导

| 维度 | 实现 | 配置位置 |
|------|------|----------|
| **SLANG_DICT 5 词** | 隐晦黑话 → 引向"价格表" | `config.json.example:L60-L66` |
| **PHOTO_KEYWORDS 5 词** | 照片/福利/自拍/视频/看图 → 拍照引导 | `config.json.example:L67-L73` |
| **HATE_KEYWORDS 7 词** | 丑/假/装/垃圾/死/胖/黑料 → 毒舌反击 | `config.json.example:L51-L59` |
| **natural_cmd** | "把 X 改成 Y" / "开启/关闭 X" / "查看配置" | `modules/natural_cmd.py` |
| **keyword_trigger 3 模式** | `static`（直接）/ `ai`（AI 生成）/ `action`（执行动作） | `modules/keyword_trigger.py` |
| **9 池模型路由** | 按 `mode` 路由到对应模型 | `config.json.example:L77-L111` |
| **AUTO_REPLY_ENABLE** | 自动回复总开关（默认 `false`） | `config.json.example:L245` |

### 3.3 💰 商业闭环

| 模块 | 功能 | 关键配置 / 数据表 |
|------|------|-------------------|
| [points_enhanced.py](modules/points_enhanced.py) | 积分系统（签到+游戏+邀请+商城+衰减） | `points` / `points_log` / `points_decay_config` / `POINTS_DECAY={rate:0.01, minimum:10}` |
| [shop.py](modules/shop.py) | 积分商城 | `shop_items` / `shop_config` / `exchange_records` |
| [coupon.py](modules/coupon.py) | 优惠券（8 位码 / 领取 / 使用） | `coupon_claims` / `coupon_config` |
| [redpacket.py](modules/redpacket.py) | 红包（随机 / 均分 / 过期退款） | `redpackets` / `redpacket_claims` / `redpacket_config` |
| [lottery.py](modules/lottery.py) | 抽奖（定时开奖） | `lotteries` / `lottery_participants` / `lottery_config` |
| [blind_box.py](modules/blind_box.py) | 盲盒（积分开启） | `blind_box_prizes` / `blind_box_config` |
| [lucky_wheel.py](modules/lucky_wheel.py) | 幸运转盘 | `lucky_wheel_results` / `lucky_wheel_config` |
| [checkin.py](modules/checkin.py) | 每日签到 | `checkin_records` / `checkin_config`（`base_points=5`） |
| [invite.py](modules/invite.py) | 邀请奖励 | `invite_records` / `POINTS_PER_INVITE=5` |
| [daily_quest.py](modules/daily_quest.py) | 每日任务 | `daily_quests` / `daily_quest_config` |
| [achievement.py](modules/achievement.py) | 成就系统 | `achievements` / `achievement_config` / `user_badges` |
| **购物车挽回** ⭐ | [auto_tasks.py:L1535 `_job_cart_recovery`](modules/auto_tasks.py#L1535) | 每小时 AI 个性化挽回私信 |
| **转化追踪** | `conversion_events` 表 + `log_conversion_event(uid, stage)` | `conversion_events` |

**转化漏斗 4 阶段**（`conversion_events` 表）：

```
[1] touched    → 视奸雷达 P7 触发（价格词：多少钱/价格/怎么买/门槛/开通/会员）
[2] interested → 画像标签 P9 检测到 is_cart（`db.set_cart(uid)`）
[3] carted     → 购物车已加但未下单
[4] converted  → 已下单
```

### 3.4 🛡 群管 95+35 模块（详尽 9 大类）

详见 §1.8（**95+35 个 modules 9 大类**），**不只列名，含功能+数据表**。

### 3.5 📊 运营观察

- **Dashboard 156 API 端点**（实测，见 §1.9）
- **8 类设置面板 115 按钮**：群管 / 反垃圾 / 积分 / 商业 / 娱乐 / 调度 / 系统 / AI
- **认证分级**：
  - `admin`（读写 / 配置修改 / 重启 / 日志查看）→ `DASHBOARD_PASSWORD`
  - `viewer`（只读 / 查看数据 / 日志）→ `DASHBOARD_VIEWER_PASSWORD`
- **转化统计**：`conversion_events` 表 + `log_conversion_event(uid, stage)`
- **数据看板**：`/api/stats/*`（群数据 / 活跃度 / 频道浏览量 / 转化率）
- **私聊告警**：故障 / 告警 → 管理员（24h 防刷）
- **孤儿清理可视化**：
  - `orphan_cleanup_log` 表：每次清理任务记录发现 / 删除 / 跳过 / 错误 / trigger
  - `/api/orphan/stats`：`tracked_count / bot_msg_count / unreplied_count / orphan_24h_count / last_cleanup / enable_deletion`
  - `/api/orphan/cleanup-history?limit=20`：最近 N 条清理记录
  - `/api/orphan/force-clean`（POST）：手动触发一次清理
  - 端到端验证脚本：`python scripts/verify_orphan_cleanup.py [--dry-run] [--force-clean]`

### 3.6 🚀 消息分发 P 级别（34 个拦截点）

详见 §1.10（**12 主级 + 22 子级 = 34 个拦截点**），实现于 `core/message_dispatcher.py`。

**主调度函数**：[`core/message_dispatcher.py:dispatch`](core/message_dispatcher.py)（使用 `BaseMiddleware` 拦截 + 短路返回）

---

## 4. 🚀 快速开始

### 4.1 VPS 部署（推荐）

```bash
# 一键部署（本地执行，自动 stop → 上传 → start → 验证）
python deploy_vps.py
```

**部署流程**：
1. 本地改代码 → `python -m py_compile` 无语法错误
2. `python deploy_vps.py`（自动 stop → 上传 → start → 验证）
3. 手动重启（如需） → `sudo systemctl restart mory-assistant`
4. 看日志 → `journalctl -u mory-assistant -n 100 --no-pager`

### 4.2 Windows 本地开发

```bash
pip install -r requirements.txt
cp .env.example .env       # 填入真实 TG_TOKEN / DASHSCOPE_KEY / DASHBOARD_SECRET / DASHBOARD_PASSWORD
python main.py
```

### 4.3 VPS 环境要求

| 项 | 要求 |
|----|------|
| 操作系统 | Ubuntu 22.04+ LTS |
| Python | 3.12+ |
| 用户 | `ubuntu`（**禁止 root**，v5.10.3 起统一） |
| 路径 | `/home/ubuntu/mory_assistant/` |
| 进程管理 | systemd only（**禁止** `start.sh` / `nohup` / `pm2` 混用） |
| 部署前 | `sudo chown -R ubuntu:ubuntu {VPS_PATH}/{core,modules,dashboard}` |

---

## 5. ⚙️ 配置管理

### 5.1 环境变量（`.env`）

| 变量 | 用途 | 必填 |
|------|------|------|
| `TG_TOKEN` | Telegram Bot Token | ✅ |
| `DASHSCOPE_KEY` | 通义千问 API Key | ✅ |
| `DASHBOARD_SECRET` | Dashboard 密钥（**至少 16 位**） | ✅ |
| `DASHBOARD_PASSWORD` | Dashboard 管理员密码（**至少 6 位**） | ✅ |
| `DASHBOARD_VIEWER_PASSWORD` | Dashboard 只读查看者密码 | ❌ |
| `DASHBOARD_HTTPS` | 是否 HTTPS 模式（决定 `SESSION_COOKIE_SECURE`） | ❌ |
| `VPS_HOST` | VPS IP 地址 | 部署时需要 |
| `VPS_SSH_PASS` | VPS SSH 密码（未配置 `VPS_SSH_KEY` 时需要） | 部署时需要 |
| `VPS_SSH_KEY` | VPS SSH 私钥路径（可选；未填时尝试本机默认 key） | ❌ |
| `VPS_PORT` | SSH 端口（默认 22） | ❌ |
| `VPS_PATH` | VPS 项目路径（默认 `/home/ubuntu/mory_assistant`） | ❌ |

### 5.2 主配置（`config.json`）

**核心配置项**（**均来自 `config.json.example`**，非硬编）：

| 配置 | 行号 | 必填 | 说明 |
|------|------|------|------|
| `BOT_NAME` | L14 | ✅ | 机器人名称（默认 `Mory小助理`） |
| `SYSTEM_PROMPT` | L15 | ✅ | **人设灵魂**（10 维商业目标 + 性格底色） |
| `KNOWLEDGE` | L16 | ✅ | 知识库（VIP 介绍 / 价格表 / 邀请文案） |
| `PRICE_LIST` | L17-L32 | ✅ | **3 档产品价格矩阵**（详 §1.4） |
| `REPLY_CHANCE` | L33 | ❌ | 群消息回复概率（百分比） |
| `IGNORE_BOTS` | L34-L40 | ❌ | 过滤的野生机器人列表 |
| `BANNED_WORDS` | L41-L45 | ❌ | 黑名单词（硬过滤） |
| `SPAM_LIMIT` | L46-L49 | ❌ | 刷屏阈值（`messages_per_minute=10`, `ban_minutes=5`） |
| `PUZZLE_WORD` | L50 | ❌ | 验证词（默认 `心动`） |
| `HATE_KEYWORDS` | L51-L59 | ❌ | 7 词毒舌反击（详 §2.1.3） |
| `SLANG_DICT` | L60-L66 | ✅ | 5 词隐晦黑话（详 §2.1.1） |
| `PHOTO_KEYWORDS` | L67-L73 | ❌ | 5 词拍照引导（详 §2.1.2） |
| `MODEL_POOLS` | L77-L111 | ✅ | **9 池模型路由**（4 有模型 + 5 占位） |
| `PROMPT_TEMPLATES` | L112-L117 | ✅ | 4 模式扩展（详 §1.5） |
| `MODE_ROUTING` | L118-L144 | ✅ | **25 mode 路由**（详 §1.6） |
| `WARNING_CONFIG` | L147-L151 | ❌ | 警告配置（`limit=3, action=mute, duration=3600`） |
| `CHECKIN_CONFIG` | L194-L201 | ❌ | 签到（`base_points=5, streak_bonus={3:5, 7:15}`） |
| `POINTS_DECAY` | L218-L222 | ❌ | 积分衰减（`rate=0.01, minimum=10`） |
| `NIGHT_MODE_CONFIG` | L253-L257 | ❌ | 夜间模式（`start_hour=23, end_hour=7`） |
| `VERIFICATION_CONFIG` | L258-L263 | ❌ | 入群验证（`mode=button, timeout=120, max_attempts=3`） |
| `ENABLE_MESSAGE_DELETION` | L285 | ❌ | 全局消息删除开关（默认 `false`） |
| `BROADCAST_AUTO_DELETE` | L286-L289 | ❌ | 群播报自动删除（`orphan_seconds=30, greeting_chain_delete=true`） |

### 5.3 三大配置源

1. **`config.json` / `config.json.example`**：运行时配置（95+ 配置项）
2. **`.env` / `.env.example`**：敏感凭据（10 项）
3. **5 个独立技术文档**（[docs/technical/](docs/technical/)）：技术细节

### 5.4 配置热重载

- **Dashboard 改 → 5-8 秒 Bot 自动生效**（`reload_flag` 文件 + 5 秒轮询）
- 实现：[`core/bot_initializer.py`](core/bot_initializer.py)（v5.12.0 起）
- 部署保护：[`core/deploy_utils.safe_upload_config()`](core/deploy_utils.py) 自动合并 + 保护密钥

### 5.5 群播报自动删除 + 孤儿清理可视化（v5.12.0+）

```json
{
  "ENABLE_MESSAGE_DELETION": true,
  "BROADCAST_AUTO_DELETE": {
    "orphan_seconds": 30,
    "greeting_chain_delete": true
  }
}
```

| 配置 | 作用 | 默认 |
|------|------|------|
| `ENABLE_MESSAGE_DELETION` | 全局消息删除开关 | `false` |
| `BROADCAST_AUTO_DELETE.orphan_seconds` | 孤儿播报多少秒后自动删除（`0`=不删） | `30` |
| `BROADCAST_AUTO_DELETE.greeting_chain_delete` | 早安/午安/晚安是否互删 | `true` |

**孤儿清理可观测**：
- `orphan_cleanup_log` 表：每次清理任务记录发现 / 删除 / 跳过 / 错误 / trigger
- Dashboard 端点 `/api/orphan/stats`：返回 `tracked_count / bot_msg_count / unreplied_count / orphan_24h_count / last_cleanup / enable_deletion`
- Dashboard 端点 `/api/orphan/cleanup-history?limit=20`：最近 N 条清理记录
- Dashboard 端点 `/api/orphan/force-clean`（POST）：手动触发一次清理
- 端到端验证脚本：`python scripts/verify_orphan_cleanup.py [--dry-run] [--force-clean]`

`ENABLE_MESSAGE_DELETION=false` 时清理任务**改发管理员私聊告警**（每 24h 一次不刷屏），让用户知道"开关关了所以没删"，而不是静默跳过。详见 [AGENTS.md](AGENTS.md) + [docs/technical/orphan-cleanup.md](docs/technical/orphan-cleanup.md)。

---

## 6. 📊 Dashboard 功能

### 6.1 端口与认证

- **端口**：**6616**（固定）
- **认证分级**：
  - `admin`（读写）：`DASHBOARD_PASSWORD`（至少 6 位）
  - `viewer`（只读）：`DASHBOARD_VIEWER_PASSWORD`（未配置则无 viewer）
- **密钥**：`DASHBOARD_SECRET`（**至少 16 位**）

### 6.2 156 API 端点（详 §1.9）

22 个文件 / 156 路由。

### 6.3 8 类设置面板 115 按钮

详 §1.9。

### 6.4 关键页面

- **群管理**：入群验证 / 慢模式 / 反刷屏 / 警告 / 黑名单 / 强制订阅
- **积分**：签到配置 / 衰减 / 任务 / 成就
- **商业**：商城 / 优惠券 / 红包 / 抽奖 / 盲盒 / 转盘
- **统计**：群数据 / 活跃度 / 频道浏览量 / 转化率 / 孤儿清理
- **AI**：模型池 / 模式路由 / 关键词触发 / 自然语言配置

---

## 7. 🗄️ 数据库（108 张表）

### 7.1 数据库概览

- **类型**：SQLite（WAL 模式）
- **总表数**：**108 张**（实测 `core/database.py` `CREATE TABLE IF NOT EXISTS`）
- **初始化**：`core/database.py` 自动建表
- **迁移**：见 `core/migrations/`（v5.x 系列逐步迁移）

### 7.2 表分类（详 §1.12）

> 分类为按业务域归类的示例，完整列表以 `core/database.py` 实测 108 张为准。

| 分类 | 关键表 |
|------|--------|
| **A 用户相关** | `users` / `user_levels` / `user_badges` / `mute_records` / `blacklist` / `conversion_events` |
| **B 群组相关** | `group_stats` / `channel_tracking` / `federation_bans` / `welcome_configs` |
| **C 商业相关** | `shop_items` / `redpackets` / `lotteries` / `points_log` / `achievements` |
| **D 追踪相关** | `broadcast_tracking` / `orphan_cleanup_log` / `task_log` / `ad_suspicious_users` |
| **E 系统配置** | `disabled_commands` / `admin_logs` / `antiflood_settings` / 22+ 其他 |
| **F 消息锁** | `message_locks` |
| **G 其他业务** | `cart_recovery` / `keyword_triggers` / `verification_records` / `puzzle_scores` |

### 7.3 备份

- **自动备份**：[`_job_backup`](modules/auto_tasks.py#L1619)（周期可配）
- **手动备份**：`cp mory.db backup/mory_$(date +%Y%m%d).db`
- **重要**：部署前**禁止** `sftp.put('mory.db')` 上传数据库（v5.9.0 禁令）

---

## 8. 🔌 VPS 部署（systemd）

### 8.1 服务管理

| 服务 | 命令 | 说明 |
|------|------|------|
| Bot | `sudo systemctl {start,stop,restart,status} mory-assistant` | 主进程 |
| Dashboard | `sudo systemctl {start,stop,restart,status} mory-dashboard` | Flask 后台 |
| 日志 | `journalctl -u mory-assistant -n 100 --no-pager` | 最近 100 行 |
| 实时日志 | `journalctl -u mory-assistant -f` | 实时跟踪 |

### 8.2 服务文件

- `mory-assistant.service`（**必须**含 `EnvironmentFile=.../mory_assistant/.env`）
- `mory-dashboard.service`（同上）

### 8.3 部署铁律（v5.10.3 起）

- **用户**：`ubuntu`（**禁 root**）
- **路径**：`/home/ubuntu/mory_assistant/`
- **进程**：systemd only
- **部署前**：`sudo chown -R ubuntu:ubuntu {VPS_PATH}/{core,modules,dashboard}`
- **多 Bot 区分**：`ps -ef | grep '/home/ubuntu/mory_assistant/main.py' | grep -v mory_media`
- **Dashboard 端口**：**6616**（固定）
- **详情**：[docs/technical/vps-deploy-trap.md](docs/technical/vps-deploy-trap.md)

### 8.4 部署流程

1. 本地改代码 → `python -m py_compile` 无语法错误
2. `python deploy_vps.py`（自动 stop → 上传 → start → 验证）
3. 手动重启（如需） → `sudo systemctl restart mory-assistant`
4. 看日志 → `journalctl -u mory-assistant -n 100 --no-pager`

### 8.5 部署安全

- `.env` / 密钥**不**上传 Git（`.gitignore` 排除）
- 部署用 `safe_upload_config()`，**不会覆盖 VPS 密钥**
- 所有 SQL 用**参数化查询**（禁止 f-string 拼接）
- 密码校验用 `hmac.compare_digest()`

---

## 9. 📚 文档索引

| 文档 | 位置 | 说明 |
|------|------|------|
| **AGENTS.md** | [项目根目录](AGENTS.md) | **项目规则 + 老坑铁律**（所有 AI 开工/修 bug/部署前必读） |
| **project_snapshot.md** | [项目根目录](project_snapshot.md) | 项目快照（数据库/模块/配置） |
| **AI_DEBUG_HISTORY.md** | [项目根目录](AI_DEBUG_HISTORY.md) | 病历本（Bug 修复记录/失败方案避让） |
| **CHANGELOG.md** | [项目根目录](CHANGELOG.md) | 变更日志（用户可感知变更） |
| **VERSION.md** | [项目根目录](VERSION.md) | 版本号锚点 |
| **MEMBER_SCAN_METHOD.md** | [docs/reference/](docs/reference/MEMBER_SCAN_METHOD.md) | 群成员扫描方案（Pyrogram） |
| **BOT 投喂与自然语言配置说明** | [docs/reference/](docs/reference/BOT_投喂与自然语言配置说明.md) | Telegram/网页端投喂 |
| **scripts/README.md** | [scripts/](scripts/README.md) | 调试工具说明 |
| **capability-matrix.md** | [docs/technical/](docs/technical/capability-matrix.md) | **详尽能力矩阵**（v5.12.2 新建） |
| **vps-deploy-trap.md** | [docs/technical/](docs/technical/vps-deploy-trap.md) | VPS 部署陷阱 |
| **orphan-cleanup.md** | [docs/technical/](docs/technical/orphan-cleanup.md) | 孤儿清理机制 |
| **config-reload.md** | [docs/technical/](docs/technical/config-reload.md) | 配置热重载 |
| **ad-detection.md** | [docs/technical/](docs/technical/ad-detection.md) | 广告检测 5 层 |
| **anti-patterns-code.md** | [docs/technical/](docs/technical/anti-patterns-code.md) | 核心代码 5 大类反模式 |
| **anti-patterns-ops.md** | [docs/technical/](docs/technical/anti-patterns-ops.md) | 运维 4 大类反模式 |

---

## 10. 🤝 接手 AI 必读

### 10.1 必读顺序

1. [AGENTS.md](AGENTS.md) — 项目规则（最高优先级）
2. [docs/technical/capability-matrix.md](docs/technical/capability-matrix.md) — 详尽能力矩阵
3. [project_snapshot.md](project_snapshot.md) — 项目当前状态
4. [CHANGELOG.md](CHANGELOG.md) — 最近 2 条变更（避免重复造轮子）
5. [AI_DEBUG_HISTORY.md](AI_DEBUG_HISTORY.md) — 病历本（避让失败路线）

### 10.2 严禁行为（事实优先）

1. **不混搭不同维度概念**：
   - `PROMPT_TEMPLATES`（4 个）≠ `MODE_ROUTING`（25 个）≠ 对话轮次递进（3 段）
   - `MODEL_POOLS`（9 池）≠ 3 层路由（**9 池 ≠ 3 层**；3 层是 MODE_ROUTING 的视角）
    - 群管文件总数：实测 95 个 modules + 35 个 core
2. **引用配置前必须 grep 实测**：
   - 价格：先 `grep -A 3 "PRICE_LIST" config.json.example`
   - 话术：先 `grep -B 1 -A 1 "SLANG_DICT" config.json.example`
   - 模块：先 `ls modules/ | wc -l` 确认数量
3. **不设定违背文档本质的硬限制**：
   - 文档展开字数限制 ≤ 400 行 → **应按需详尽**，不锁行数
4. **不写"未做/未来调整"偷懒话术**：
   - 已实现的模块需详写（功能+数据表+行号引用）
   - 占位/未启用的要明确标注（5 个占位模型池）
5. **不重复踩病历本里的旧坑**：
   - v5.9.0 禁 `sftp.put('mory.db')`
   - v5.10.2 禁 `sftp.put('config.json')`（必须用 `safe_upload_config`）
   - v5.11.0 禁 root SSH
   - v5.7.1 禁 `start.sh` / `nohup` / `pm2`

### 10.3 失败升级机制

| 失败次数 | 动作 |
|:-------:|------|
| 第 1 次 | 检查命令/参数/环境，自动重试 |
| 第 2 次 | 换参数/换路径/换依赖版本 |
| 第 3 次 | 换方案（不同技术路线） |
| 3 次都失败 | 回滚到稳定状态，告知用户需人工介入 |

### 10.4 凭据管理

- **存储**：只放项目根目录 `.env`，格式 `KEY=VALUE`
- **引用**：代码用 `os.environ["KEY"]`，文档写"见 .env"
- **标记**：AI_DEBUG_HISTORY 只写 `[凭据已获取] KEY_NAME`，绝不写值
- **首次需要**：问用户 → 写入 `.env` → 标记 `[凭据已获取]`
- **后续使用**：从 `.env` 读取，不再问用户
- **凭据失效（401/403）**：重新问用户 → 更新 `.env`
- **项目交接**：`.env` 不上传 Git；新 AI 从 `.env.example` 知道需要哪些凭据，问用户获取

---

## 11. ⚖️ 业务红线 6 条（详尽）

### 11.1 ❶ 绝对不能死（用户原话）

- 因报错导致程序卡死崩溃 = 业务失败
- 实施：每个 P 级别拦截点都包裹 `try / except`（P1-P10 + 22 子级）
- 日志：所有异常写入 `logs/` 文件夹
- 监控：`_job_health_check` 每 5 分钟一次
- 验证：`python scripts/verify_main_flow.py`

### 11.2 ❷ 绝对不说自己是 AI

- SYSTEM_PROMPT 第 2 条铁律（10 维商业目标第 2 条）
- 实施：LLM 提示词硬约束 + 后过滤（关键词检测）
- 检测词：AI / 机器人 / 程序 / 模型 / GPT / ChatGPT / DeepSeek / 通义千问
- 违规：触发傲娇反击（"你觉得我是 AI？哈哈你才 AI"）

### 11.3 ❸ 绝对不直白营销

- 话术示例："想看更多？""要不要试试完整版？""@MorychannelBot 那边有惊喜"
- 反例：❌ "买买买！""快来下单！""限时优惠！"
- 实施：自然语言引导（SYSTEM_PROMPT 第 5 条 + 25 MODE_ROUTING）

### 11.4 ❹ 绝对不重复话术模板

- 实施：话术池随机抽取（每次换说法）
- 失效：连续 2 次相同触发自动刷新模板
- 验证：`_job_proactive_audit` 检测重复率

### 11.5 ❺ 绝对不破坏 3 档产品边界

- 3 档产品严格遵循 `PRICE_LIST`（详 §1.4）
- 价格改动：必须同步三处（`config.json` + Dashboard 设置面板 + CHANGELOG）
- 群数：至臻全享含 3 群（至尊精选 + 至臻全享 + 精选图集）
- 权益：详细功能对照见 `docs/technical/capability-matrix.md`

### 11.6 ❻ 绝对不在 Bot 内收款

- 一律引导 `@MorychannelBot` 自助下单
- Bot 内**不显示**支付二维码 / 链接
- 实施：所有 `PRICE_LIST` 引导话术都包含 `@MorychannelBot`
- 验证：grep 全文确保 `payment` / `wechat_pay` / `alipay` 等支付关键词不存在于产品文案

---

## 12. 📜 版本 / 许可证 / 变更记录

### 12.1 当前版本

**v5.31.2**（2026-06-30）— Token 消耗暗病排查 + Loop 1-20 多智能体联排 84 处修复：高频任务 task_log 死锁、LLMCostGuard 成本熔断器启用、token_usage 记录、WriteQueue rowcount 丢失、RLock 防死锁、原子 UPDATE 防 TOCTOU、腾讯云 Lighthouse 监控接入、独立看门狗、_CST 时区常量全域覆盖、shop.py P0 SQL 列名错误修复、health_api.py 时区残留修复、12 处静默吞异常升级、shop.py TOCTOU 漏洞修复、emergency_ban 时区+类型不一致修复、bot_initializer/pinyin_util 静默吞异常修复、dashboard/app.py finally 修复、文档失真治理 16 处纠正。

### 12.2 版本演进

> 完整历史见 `VERSION.md` 与 `CHANGELOG.md`。近 10 个版本：

| 版本 | 日期 | 摘要 |
|------|------|------|
| v5.31.2 | 2026-06-30 | Token 暗病排查+Loop 1-20 联排84处修复：task_log死锁/LLMCostGuard/RLock防死锁/原子UPDATE防TOCTOU/腾讯云监控/独立看门狗/_CST时区常量/shop.py P0+TOCTOU/health_api时区/静默吞异常升级/dashboard finally/文档失真治理 |
| v5.31.1 | 2026-06-27 | 四层防御体系根治 _REPO_METHOD_MAP 漏注册沉默失败：启动自检+__getattr__加固+部署前验证+调度健康监控 |
| v5.30.3 | 2026-06-25 | 多智能体协作诊断+彻底修复：补注册30方法/VPS_HOST修正/属主修复/删除硬编码密码/7处静默吞错改日志 |
| v5.28.0 | 2026-06-19 | 10项增长优化上线：增长优化编排层、AI回复前stage_hint、回复后归因/遥测、Dashboard增长汇总、低采样质量评估 |
| v5.27.0-RC1 | 2026-06-18 | 稳定化候选：requirements.lock 真实生成，Dashboard/迁移可启动，RBAC 安全测试不再跳过，metrics 防重复虚高，CI targeted flake8/mypy/pytest/interrogate 通过 |
| v5.26.0 | 2026-06-17 | 10大优化方向全量执行（LLM成本熔断+压测+级联告警+人设一致性+A/B测试+记忆归因+DB迁移监控+多Bot路由+归因回放+RBAC审批流） |
| v5.25.0 | 2026-06-17 | 10大优化（Dashboard API压测+WriteQueue背压+SQL乐观锁+告警风暴控制+ModelRouter多模型协同+记忆摘要+DB迁移蓝图+funnel归因+audit DB驱动权限+Locust压测） |
| v5.24.1 | 2026-06-17 | 深度系统集成三阶段（WriteQueue全量化+独立告警Bot+RBAC守卫+混合记忆+归因报表+调度指标落盘+RBAC角色迁移） |
| v5.23.0 | 2026-06-17 | 8大架构优化（SQLite写入队列+AI输出质量+RBAC审计+转化漏斗归因+广告拼音增强+调度可观测+混合记忆+多Bot共享表） |
| v5.22.0 | 2026-06-17 | 全量审计修复（5致命+11高危+13中危暗病） |
| v5.21.0 | 2026-06-17 | 人设引擎大改（4桶反模板+动态LLM参数矩阵） |
| v5.20.0 | 2026-06-17 | 动态意图识别与场景触发引擎 |
| v5.19.0 | 2026-06-17 | 播报多样性引擎 + 人设引擎大改 |
| v5.18.5 | 2026-06-17 | Telegram Bot API 10.1 完整实装 |
| v5.18.4 | 2026-06-16 | 每日播报系统全面优化（话术+画像+提示词重构） |
| v5.18.3 | 2026-06-16 | 全量审计+代码质量修复（164处空except+自动备份+日志清理） |
| v5.18.2 | 2026-06-15 | 富文本播报上线核查补强 |
| v5.18.1 | 2026-06-15 | Dashboard 6新页面+用户画像自动学习+A/B测试+按钮统计 |
| v5.18.0 | 2026-06-15 | Telegram API 2026 适配（富文本+彩色按钮+人物画像） |
| v5.17.0 | 2026-06-15 | 网络请求异常处理重构（统一HTTP客户端） |
| v5.16.5 | 2026-06-14 | Telegram Bot API 10.x 富文本与群能力兼容 |
| v5.16.4 | 2026-06-13 | Premium emoji状态识别 + 历史消息删除边界修复 |
| v5.16.3 | 2026-06-12 | 工作区脏改动收敛 + 目录分层清理 |
| v5.16.2 | 2026-06-12 | 广告治理不踢人策略纠正 + emoji/头像/播报/搭讪暗病修复 |
| v5.12.0 | 2026-05-30 | 配置热重载 + 群播报自动删除 + 孤儿清理可视化 |
| v5.11.0 | 2026-05-25 | 禁 root SSH 部署（统一 ubuntu 用户） |
| v5.10.3 | 2026-05-20 | 配置上传 `safe_upload_config`（自动合并 + 保护密钥） |
| v5.10.2 | 2026-05-15 | 禁 `sftp.put('config.json')` 直接覆盖 VPS |
| v5.9.0 | 2026-05-10 | 禁 `sftp.put('mory.db')` 上传数据库 |
| v5.7.1 | 2026-04-25 | 禁 `start.sh` / `nohup` / `pm2` 启动（统一 systemd） |
| v5.0.0 | 2026-01-01 | 设置面板完全体（115 按钮） |
| v4.8.0 | 2025-08-15 | SYSTEM_PROMPT 精细化（10 维商业目标） |

> 详细变更见 [CHANGELOG.md](CHANGELOG.md)

### 12.3 许可证

本项目为私有项目，**未经授权禁止复制、修改、分发**。

### 12.4 致谢

- **Telegram Bot API**（pyTelegramBotAPI / Pyrogram）
- **通义千问**（DashScope / qwen3.5-plus / qwen3.6-flash / qwen3-max）
- **SQLite**（WAL 模式）
- **Flask**（Dashboard）
- **APScheduler**（定时任务）
- **systemd**（进程管理）

### 12.5 反馈

- 提交问题：在 Dashboard → 系统 → 反馈
- 联系管理员：私聊 Bot → 自动转交
- 文档错误：PR → 修订 [AGENTS.md](AGENTS.md) 或 [README.md](README.md)

---

> **文档维护**：每次 `CHANGELOG.md` 更新时同步 `README.md` 与 `VERSION.md`
> **核心原则**：**事实优先** — 所有数据均来自 `config.json.example` / `ls modules/` / `core/database.py` / `core/message_dispatcher.py` 实测
