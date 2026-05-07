# Mory小助理 项目快照 v4.5.32

> 新AI会话必读：本文件 + `AI_DEBUG_HISTORY.md`
> 最后更新：2026-05-02（彻底根治多进程连发+数据库级原子抢占）

---

## 1. 项目概览

| 项目 | 值 |
|------|-----|
| 名称 | Mory小助理 - Telegram群管机器人 |
| 版本 | v4.5.32 |
| 技术栈 | Python3 + pyTelegramBotAPI + SQLite(WAL) + Flask |
| 部署 | VPS（start.sh作为唯一进程管理） |
| 存储 | `mory.db`(SQLite) + `config.json`(配置) |
| 红线 | 绝对不能因报错导致程序卡死崩溃 |

---

## 2. 目录结构

```
mory_assistant/
├── main.py                 # 主入口（消息分发+中间件注册）
├── config.json             # 运行时配置（Token/管理员/模型池/人设）
├── .env                    # 环境变量（不提交Git）
├── .env.example            # 环境变量模板
├── requirements.txt        # Python 依赖
├── version.py              # 版本号统一管理
├── core/
│   ├── __init__.py
│   ├── ai_engine.py        # AI引擎（三层路由+多模型轮换+TTS语音）
│   ├── trendradar_news.py  # TrendRadar新闻获取（共享去重缓存）
│   ├── database.py         # SQLite数据层（13张表+线程安全+task_log持久化）
│   ├── logging_util.py     # 日志工具（按大小轮转+错误分级）
│   ├── mory_bot.py         # Bot封装类（中间件+消息路由+阅后即焚追踪）
│   ├── optimizer.py        # 运营优化器（语义缓存+熔断+限流）
│   ├── resource_manager.py # 资源管理（图片/语音池+线程安全锁30s超时）
│   ├── monitoring.py       # 系统监控
│   ├── token_statistics.py # Token统计
│   └── vps_config.py       # VPS连接配置（SSH+环境变量）
├── modules/
│   ├── __init__.py
│   ├── admin_cmds.py       # 管理员指令
│   ├── auto_tasks.py       # 定时任务（_can_run/_mark_done防重复+数据库持久化+失败重试）
│   ├── content.py          # 内容处理（图片打码+频道转发+勋章）
│   ├── group_mgr.py        # 群管理（入群欢迎/敏感词/刷屏/黑名单）
│   ├── keyword_trigger.py  # 关键词触发（静态/AI/动作三种回复模式）
│   ├── natural_cmd.py      # 自然语言指令（塔罗/解梦/树洞/配置修改）
│   └── optimizer_admin.py  # 运营管理指令（数据看板/转化统计）
├── dashboard/
│   └── app.py              # Flask网页后台
├── universal_ai_router/    # 通用AI路由模块（智能模型选择+Token统计）
├── scripts/                # 调试和诊断工具
│   ├── debug_db.py         # VPS数据库查询诊断
│   ├── debug_vps.py        # VPS全面诊断脚本
│   ├── deep_check.py       # 深度关键词触发诊断
│   ├── find_bug.py         # 历史日志错误排查
│   ├── full_diagnosis.py   # VPS全功能诊断报告
│   ├── get_keyword_module.py
│   ├── test_connection.py  # 通义千问API连接测试
│   ├── test_vps_ai.py      # VPS AI功能数据检查
│   └── README.md           # 工具说明
├── backups/                # 自动备份
├── deploy.sh / deploy.bat  # 部署脚本
├── deploy_vps.py           # VPS一键部署
├── start.sh                # VPS启停脚本
├── sync_vps.py             # VPS同步工具
├── 一键部署.bat            # Windows一键部署
├── Dockerfile              # Docker镜像
├── docker-compose.yml      # Docker编排
├── project_snapshot.md     # 本文件
└── AI_DEBUG_HISTORY.md     # 调试病历本
```

---

## 3. 数据库表（mory.db · 14张表）

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

---

## 4. 关键架构约束

### 4.1 消息分发
- pyTelegramBotAPI handler是独占式，`return False`不流转
- 唯一方案：`BaseMiddleware`拦截所有消息
- 优先级：P0(入群)→P1(黑名单)→P2(积分)→P3(敏感词)→P4(刷屏)→P5(野生Bot)→P6(管理员)→P6.5(关键词)→P7(视奸)→P8(彩蛋)→P9(画像)→P10(AI)

### 4.2 线程安全
- `_db_lock`保护所有数据库操作
- ResourceManager锁超时30秒
- 内存缓存有上限（_conv_tracker≤1000）

### 4.3 安全
- Dashboard密钥通过环境变量设置
- VPS信息通过环境变量读取，无硬编码
- 所有SQL参数化查询，禁止f-string拼接
- 密码校验用`hmac.compare_digest()`

### 4.4 进程红线（务必遵守）
- **生产环境只允许 systemd 管理本项目进程**：只用 `sudo systemctl restart mory-assistant` / `systemctl status mory-assistant`。
- **绝对禁止**：`pm2`、`bash start.sh start`、手动 `python main.py` 去启动/重启生产服务，否则极易多开导致 Telegram `409 Conflict`（同 token 多个 getUpdates）。
- `start.sh` 仅保留为历史/本地应急脚本，不作为生产启停入口。

---

## 5. 定时任务

| 任务 | 时间 | 防重复 |
|------|------|--------|
| 早安问候 | 8:05 | _can_run+_mark_done+task_log |
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

**防重复机制**：_can_run()仅检查 → 执行 → 成功后_mark_done() → 数据库task_log持久化
**失败重试**：关键任务失败5分钟后重试1次，仍失败私聊通知管理员

---

## 6. 环境变量

| 变量 | 用途 | 必填 |
|------|------|------|
| DASHBOARD_SECRET | Dashboard密钥(≥16位) | 是 |
| DASHBOARD_PASSWORD | Dashboard密码(≥6位) | 是 |
| VPS_HOST | VPS IP | 是 |
| VPS_SSH_PASS | VPS密码 | 是 |
| VPS_PORT | SSH端口 | 否(默认22) |
| VPS_PATH | 项目路径 | 否(默认/root/mory) |
| BOT_ROLE | Bot角色（避免后台任务冲突；默认 MAIN） | 否 |

## 9. 多项目同机边界（重要）

- 服务器上可能同时运行其他项目/其他机器人。排查本项目时，**只操作本项目目录与本项目 systemd 服务**，不要“看到 409 就乱杀进程”。
- 目前同机存在 `mory_media_assistant`（独立宣发号），它会读取主项目 `mory.db` 的 `promotions` 表做定时广播：主项目侧务必避免长事务/长时间独占锁，尽量保持写事务短小，避免把库锁死影响宣发号读取。

---

## 7. 修复历史摘要

| 版本 | 修复数 | 关键内容 |
|------|--------|----------|
| v4.5.32 | 2项 | 彻底根治多进程连发：数据库级原子抢占(db.claim_task纯INSERT OR IGNORE)+start.sh强力清理(SIGTERM→等5秒→SIGKILL) |
| v4.5.31 | 4项 | 彻底根治连发（三层防护）：task_log添加UNIQUE约束+INSERT OR IGNORE+_try_claim_task全局替换+coalesce=True+misfire_grace_time=60 |
| v4.5.30 | 1项 | 修复misfire补发连发(misfire_grace_time改为1秒) |
| v4.5.29 | 2项 | 修复早安/新闻连发(_try_claim_task原子锁+APScheduler max_instances=1)+新增AI广告检测(check_ad_content纯规则匹配零消耗) |
| v4.5.28 | 2项 | 日报群成员数直接调API(get_chat_member_count)+入群名字检测虚拟币/搬砖等关键词自动永久禁言(AUTO_MUTE_NAMES配置化) |
| v4.5.27 | 4项 | 日报数据全0修复：_send_and_track加track_channel_message+_job_channel_views修复None判断+加锁+日报增加活跃用户/Bot消息数/互动率/群成员数+database新增4个查询方法 |
| v4.5.26 | 1项 | S-AI-01修复：ContextLogger没有addFilter方法，改为logger.logger.addFilter() |
| v4.5.25 | 1项 | S-AT-01 fallback路径线程泄漏彻底修复：移除长休眠Timer，APScheduler不可用时跳过定时删除，依赖孤儿清理机制处理 |
| v4.5.24 | 7项 | 板块C功能模块层二次审查：S-AT-01 fallback路径Timer替代长休眠线程+S-AT-03 burn_orphan加锁+M-AT-02 Phase2每小时一次+M-AT-03塔罗缓存入口主动清空+M-AT-04通知缓存过期清理+L-AT-01重复导入确认已修+L-AT-02旧版循环全任务隔离 |
| v4.5.23 | 7项 | 板块A主控层7项修复：S-MN-01数据库竞态(upsert_user_with_points原子操作)+M-MN-01内存清理依赖消息(auto_tasks定时清理)+M-MN-02重复创建RM(模块级_emergency_rm)+M-MN-03私聊转发Markdown改HTML+转义+M-MN-04超时保护无效(concurrent.futures真超时)+L-MN-01 .env多行值(python-dotenv)+L-MN-02连续对话追加超时(concurrent.futures) |
| v4.5.22 | 5项 | 板块A主控层5项修复：S-MN-01数据库竞态(upsert_user_with_points原子操作)+S-MN-02超时保护无效(concurrent.futures真超时)+M-MN-01内存清理依赖消息(auto_tasks定时清理)+M-MN-02重复创建RM(模块级_emergency_rm)+L-MN-01 .env多行值(python-dotenv) |
| v4.5.21 | 4项 | Dashboard二次审查修复：S-DH-04变量名NameError+S-DH-05 forbidden_keys精确匹配+M-DH-01速率限制每次清理+M-DH-06 VPS状态5分钟缓存 |
| v4.5.19 | 7项 | Dashboard安全漏洞7项修复：S-DH-01 SQL注入(ORDER BY白名单映射)+S-DH-02 XSS(escHtml转义)+S-DH-03登录失败持久化(login_failures表)+M-DH-01速率限制内存泄漏清理+M-DH-02数据库连接Flask g统一管理+M-DH-03自然语言配置敏感字段过滤+L-DH-01 SSH AutoAddPolicy→WarningPolicy |
| v4.5.18 | 7项 | S-AT-01线程泄漏(24h休眠线程→APScheduler)+S-AT-02新闻缓存竞态加锁+M-AT-01重试线程APScheduler化+M-AT-02 Phase2转发降频(limit8→3)+M-AT-03塔罗缓存简化+L-AT-01重复导入清理+L-AT-02旧版循环超时保护 |
| v4.5.17 | 5项 | Dashboard安全审计(CSRF补全+频率限制过期+漏斗/群组频道渲染)+M-DU-01 shell注入修复+L-DU-01 配置下载告警 |
| v4.5.16 | 3项 | Dashboard密码hmac比较+图表真实数据绑定+删除重复死代码 |
| v4.5.13 | 4项 | 老板/boss/Mory称呼联动+特定词自动回复配置化+价格咨询AI润色+完整版/联系引导 |
| v4.5.12 | 3项 | 早午晚安提示词强化随机性+隐晦联系引导+完整版/至臻圈层暗示 |
| v4.5.11 | 5项 | 早中晚新闻合并单条主流程+TrendRadar改为优先新闻源+新闻成功后再去重+问候文案去广告腔+标题播报停用 |
| v4.5.10 | 4项 | 全模态优先用于文本聊天+三层路由接入omni优先+熔断日志按实际模型对齐+启动脚本版本自动读取 |
| v4.5.6 | 4项 | 全局故障通知升级+定时消息24h自动删除+AI教指令+话术随机化 |
| v4.5.9 | 6项 | 模型切换熔断修正+llm当前模型指针修复+独立路由去硬编码密钥+账号失败冷却+过期模型移除+router_config同步规则修复 |
| v4.5.8 | 12项 | Windows脚本全英文化+Dashboard去硬编码密码+sync_vps代理修复+裸except收窄+本地VPS预检+服务器只读巡检+部署前备份+全量同步+停旧进程后上传+依赖补齐+模型索引兜底+版本对齐 |
| v4.5.5 | 3项 | 全局故障通知+指令识别修复+回复风格优化 |
| v4.5.4 | 3项 | 晚间新闻零token+7新闻源+故障通知 |
| v4.5.3 | 4项 | 新闻零token播报+早安/问候加长+去重修复 |
| v4.5.0 | 36项 | 定时任务防重复重构+task_log持久化+seed_hint修复+锁超时+重试机制+深度扫描18项 |
| v4.4.8 | 4项 | 阅后即焚彻底修复 |
| v4.4.1 | 2项 | 进程级单例锁+原子操作去重 |
| v4.4.0 | 32项 | 终极核查修复(3致命+4高危+16中+9低) |
| v4.3.2 | 27项 | 致命修复+灾难恢复 |

详细修复记录见 `AI_DEBUG_HISTORY.md`。

---

## 8. 已知平台限制

1. 群组历史消息无法访问（Telegram API限制）
2. Bot主动私信403（用户必须先联系Bot）
