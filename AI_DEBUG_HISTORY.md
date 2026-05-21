# AI_DEBUG_HISTORY.md 调试病历本

> **本文件专门写给AI自己看**
> 新会话开始时，AI 必须先读 `project_snapshot.md` + 本文件
> **最后更新**：2026-05-21（v4.13.0 项目清理）

---

## 重要：项目上下文

### 基本信息
- **项目**：Mory小助理 - Telegram群管机器人
- **当前版本**：v4.13.0
- **技术栈**：Python 3 + pyTelegramBotAPI + SQLite(WAL) + Flask
- **VPS**：通过环境变量配置（VPS_HOST / VPS_SSH_PASS），无硬编码
- **VPS路径**：通过环境变量 VPS_PATH 配置，默认 /home/ubuntu/mory_assistant/

### 关键路径
| 用途 | 路径 |
|------|------|
| Bot日志 | `/home/ubuntu/mory_assistant/mory.log`（以实际 VPS_PATH 为准） |
| 重启（唯一允许） | `sudo systemctl restart mory-assistant` |
| 状态 | `systemctl status mory-assistant` |
| 日志 | `journalctl -u mory-assistant -n 200 --no-pager` |

**红线**：
- 禁止用 `pm2` 或 `bash start.sh start` 或手动 `python main.py` 触碰生产进程。
- 违反会导致同 token 多开 long polling，触发 Telegram `409 Conflict`，表现为"机器人不回消息"。

### 核心功能
1. **阅后即焚** - 由 `ReplySnifferMiddleware` 中间件捕获回复
2. **AI对话** - 多模型轮换（通义千问/MiniMax/Kimi/GLM），过期自动跳过
3. **自动任务** - 新闻播报(TTS语音)/问候/塔罗/背刺泄密等后台定时任务
4. **优化引擎** - 语义缓存 + 熔断器 + 令牌桶限流
5. **管理员指令** - 人设管理/群管/黑名单/日志查询
6. **Dashboard** - Flask网页后台，CSRF+速率限制+登录频率限制

---

## 历史Bug记录（倒序）

### v4.13.0 | 2026-05-21 | 项目清理精简

[Trae CN] 病历本从1576行压缩至≤500行，保留v4.9.0+详细记录，v4.3.x~v4.5.x压缩为摘要表，合并永久纪律为统一清单。

### v4.12.2 | 2026-05-21 | 广告检测持续漏检根治

**踩坑26**：截图案例广告（"虚拟货币搬砖日挣1千U"）一直漏检。根因四层：名称不参与内容评分；"日挣"≠"日赚"漏变体；低门槛话术缺失；入群/兜底也漏。修复：名称参与评分+日挣变体+9条低门槛规则+入群兜底同步补全。

**踩坑26b**：修复后误伤正常用户。根因三层：CRYPTO_PATTERNS含中性词权重过高；阈值2太低；"约"字模式过宽。修复：拆分CRYPTO_NEUTRAL_PATTERNS(weight=1)；阈值2→3；"约"改为约+色情特征词组合。

### v4.12.1 | 2026-05-21 | 群数据统计全面修复

**踩坑25**：日报统计完全错误（入群0/离群0/净增+1矛盾）。根因六层：growth_today月份前缀匹配；messages_today同样匹配错误；昨日数据重复调用API；活跃度定义错误；频道只追踪Bot消息；入群/离群无幂等保护。修复：精确日期匹配+昨日数据从DB读+活跃互动重定义+channel_posts表+幂等保护。

### v4.12.0 | 2026-05-21 | 反馈消息智能拦截

**踩坑**：用户发"被封了"/"解封"等反馈消息，Bot输出撩人内容。根因：detect_keywords()无反馈类模式识别，走normal模式AI按撩人人设回复。修复：新增feedback/contact_mory模式+P9.7处理逻辑+固定安抚回复+通知管理员+拦截AI闲聊。

### v4.11.3 | 2026-05-21 | 广告检测误杀Bot命令 + 任务并发告警误报

**踩坑27**：Bot命令`/me@afoolGroupBot`被误判为"联系方式/引流"封禁。根因：CONTACT_PATTERNS中`@\w{3,}`匹配任何@开头+3字符。修复：改为`(?<!\w)@\w{3,}`负向后行断言。

**踩坑24**：reactivate/cart_recovery每小时稳定触发并发告警。根因三层：record_call位置错误（锁拦截也计入）；coalesce=True遗漏；缺防重入保护。修复：record_call移到claim成功后+补coalesce=True+start_background防重入检查。

### v4.11.2 | 2026-05-20 | 广告检测持续漏检根治

（详见v4.12.2踩坑26/26b，同一次修复分两个版本号记录）

### v4.11.1 | 2026-05-20 | 群数据统计全面修复

（详见v4.12.1踩坑25，同一次修复分两个版本号记录）

### v4.9.3 | 2026-05-21 | 用户反馈消息AI瞎撩人修复

（详见v4.12.0，同一次修复分两个版本号记录）

### v4.9.2 | 2026-05-19 | 并发重复播报根治

**踩坑23**：v4.7.0"先执行后确认"流程导致并发重复播报。根因：两个线程同时通过_try_claim_task和is_task_executed_today检查，都执行了发送。修复：新增`_try_claim_and_lock`原子抢占（内存检查+数据库claim_task一步完成）+`_release_task`失败释放数据库锁+`_confirm_task_done`简化为仅设内存锁。

### v4.9.0 | 2026-05-19 | 并发重复播报根治

（同v4.9.2，版本号调整）

### v4.7.0 | 2026-05-18 | 定时任务全面修复

**踩坑22**：任务锁"先锁后执行"导致失败后无法重试（6项修复）。修复：改为"先执行后确认"流程+_confirm_task_done成功后才锁定+_retry_task重试+_job_health_check健康检查+移除废弃_job_burn_probe调度。

### v4.6.5 | 2026-05-17 | 色情引流暗号扩展+误判修复

**踩坑20**：单字规则导致正常用户被误判。修复：全部改为组合规则（按摩+小姐/接待/全套/特服等）。

**踩坑21**：VPS Bot崩溃-pytz模块缺失。修复：pytz改为可选依赖，未安装时回退到Python内置timezone。

### v4.6.3 | 2026-05-17 | 智能广告拦截增强

**踩坑18**：广告第一条消息难判断。修复：新增延迟封禁机制，30分钟窗口期内累计评分达阈值触发封禁。

**踩坑19**：一眼广告用户名入群不被拦截。修复：扩充AUTO_MUTE_NAMES 6大类关键词。

### v4.6.0 | 2026-05-16 | 深度用户挑刺报告P0/P1修复

**踩坑15**：Dashboard日志查询列名与reply_tracking表不匹配。修复：修复SQL查询和前端表头匹配实际列名。

**踩坑16**：绑定主人首次绑定无安全验证。修复：首次绑定限制只能在私聊中执行。

**踩坑17**：Dashboard会话无过期机制。修复：添加PERMANENT_SESSION_LIFETIME=30分钟。

---

## [Trae CN] 色情引流检测规则设计原则与避开指南（v4.6.5 归档）

> **本节是广告检测规则的"防失忆档案"**，新AI会话修改规则前必读。

### 一、规则体系架构

| 层级 | 机制 | 文件 | 触发条件 |
|------|------|------|----------|
| L1 入群封禁 | 用户名关键词匹配 | group_mgr.py AUTO_MUTE_NAMES | 用户名含一眼广告词 → 入群即永久封禁 |
| L2 内容检测 | 8维度评分 + 延迟封禁 | ad_detector.py + ad_patterns_encoded.py | 单条评分≥3 → 即时封禁；评分>0但<3 → 30分钟累计追踪 |
| L3 兜底检测 | 旧版关键词检测 | group_mgr.py check_ad_content | 兜底防线，L2漏检时触发 |

### 二、8维度评分体系

| 维度 | 变量名 | 权重 | 覆盖范围 |
|------|--------|------|----------|
| 赚钱承诺 | MONEY_PATTERNS | 2 | 日入/日赚/稳赚/躺赚/暴利/保底/月入/年入+间隔符变体 |
| 色情引流 | ADULT_PATTERNS | 2 | 30+条组合规则 |
| 灰色产业 | GRAY_PATTERNS | 2 | 假钞/精仿/盘口/毒品/赌博/码车/人头费 |
| 加密货币 | CRYPTO_PATTERNS | 2 | USDT/搬砖/洗米/跑分/搞米/不实名+中性词weight=1 |
| 联系方式 | CONTACT_PATTERNS | 1 | 加微信/加薇信/加VX/ZFB/t.me链接/看我简介变体 |
| 招募拉人 | RECRUIT_PATTERNS | 1 | 招团队/找几个/兄弟一起+干活/看置顶 |
| 低门槛 | LOW_BARRIER_PATTERNS | 1 | 轻资产/零成本/小白也能/新手当天上手/无需经验 |
| 引流暗示 | PROFILE_HINT_PATTERNS | 1 | 纯"简介"/"主页"/"资料"三词（仅匹配整条消息） |

**评分规则**：单维度多次命中只计一次分；评分≥3即时封禁；>0但<3进入30分钟延迟追踪。

### 三、ADULT_PATTERNS 规则类型

| 规则类型 | 示例 | 设计原因 |
|----------|------|----------|
| 纯暗号 | 口爆/全套服务/特服/约炮/裸聊/一夜情/包夜/学生妹 | 正常社交几乎不会出现 |
| 身材/价格暗号 | 身材火辣/活好/正点；数字+P/S/套/次/晚；数字+E/F级+奶/胸 | 色情服务特征 |
| 特殊暗号 | M36D/白虎/反差M/淫姑/淫娃 | 黑话，正常社交不用 |
| 组合规则（核心） | 按摩+小姐/接待/全套/特服；小姐+(?:接待\|全套\|上门\|特服)；约+小姐/少妇/学生妹（间距≤1）；上门+按摩/特服/全套（间距≤3）；KTV+小姐/特服/全套（间距≤3）；同城+约/小姐；美女+约/接待/特服 | 单字太宽必须搭配色情特征词 |
| 行为/场景暗号 | 约起/来约/快约；上门服务/同城约/视频聊 | 色情引流行为/场景特征 |
| 招募暗号 | 各地+学生/约；传递+各地；学生+约 | 招募+色情组合 |

### 四、避开指南

| 编号 | 禁止操作 | 原因 | 正确做法 |
|------|----------|------|----------|
| R-01 | 添加单字规则（按摩/小姐/约/上门/美女/少妇等） | 误判之源 | 必须搭配色情特征词组合 |
| R-02 | 用字符集匹配`[服务接待全套]` | 匹配单字符，"小姐服务"中"服"误匹配 | 精确匹配`(?:接待\|全套\|上门\|特服)` |
| R-03 | 组合间距用`[\s\S]{0,5}` | 太宽泛 | 缩短到`[\s\S]{0,1}`或紧邻 |
| R-04 | KTV/上门组合含"约" | "去KTV唱歌约不约"是正常社交 | 只搭配色情特征词 |
| R-05 | "姐妹一起"单独匹配招募 | "姐妹一起去按摩"正常 | 改为"姐妹一起+干活/赚钱" |
| R-06 | 不验证就部署新规则 | 可能误判 | 部署前跑test_detect.py验证 |
| R-07 | 部署后不验证Bot运行 | pytz缺失导致崩溃 | `systemctl status mory-assistant`确认 |
| R-08 | 强依赖第三方库无回退 | VPS可能缺库 | try-except+Python内置回退 |
| R-09 | 同维度规则重复加分 | 评分虚高 | v4.6.5已修复：每维度break后只计一次 |
| R-10 | 不更新文档就改规则 | AI失忆重复犯错 | 改规则必须同步更新本节 |

---

## v4.3.x~v4.5.x 摘要表

| 版本 | 修复数 | 关键内容 |
|------|--------|----------|
| v4.5.36 | 3项 | 周报chat_id=0硬编码+入群遗漏+校准机制；getChatStatistics Bot API 7.0+已支持 |
| v4.5.35 | 9项 | bare except→精准捕获+敏感词通知不泄露内容+代发频道HTML+burn_probe空函数+购物车清理+塔罗缓存上限+HTML转义 |
| v4.5.34 | 3项 | getChatStatistics API 404+醋意/购物车挽回400+代发频道track消息 |
| v4.5.33 | 2项 | start.sh误杀mory_media+部署后多进程残留→改用systemd管理 |
| v4.5.32 | 6项 | 获取隐私频道ID全流程+Telegram频道统计API接入+彻底根治多进程连发（数据库原子抢占+start.sh强力kill） |
| v4.5.31 | 2项 | 彻底根治连发：task_log UNIQUE约束+_try_claim_task全局替换+coalesce=True+misfire_grace_time=60 |
| v4.5.30 | 1项 | misfire补发连发→grace_time从300改为1（后改为60） |
| v4.5.29 | 2项 | 早安/新闻连发→_try_claim_task原子锁+max_instances=1；AI广告检测自动删除+永久禁言 |
| v4.5.28 | 2项 | 日报群成员数修复+入群自动禁言AUTO_MUTE_NAMES |
| v4.5.27 | 4项 | 日报浏览量永远为0+Bot主动消息不track+日报指标单一+缺按日查询方法 |
| v4.5.25 | 1项 | fallback线程泄漏→移除Timer，依赖孤儿清理 |
| v4.5.24 | 7项 | 板块C二次审查：fallback线程+API加锁+Phase2降频+塔罗缓存+通知缓存清理+任务隔离 |
| v4.5.23 | 6项 | 板块A主控层：数据库竞态→原子方法+内存清理定时化+异常RM共享+HTML转义+真超时+dotenv |
| v4.5.22 | 5项 | 板块A安全修复：数据库竞态+超时保护+内存清理+RM共享+dotenv |
| v4.5.21 | 4项 | Dashboard二次审查：SQL变量名+forbidden_keys过宽+速率限制清理+VPS缓存 |
| v4.5.20 | 7项 | AI引擎：API密钥日志脱敏+响应时间字典清理+方法拆分+新闻连接池+重试降5次+mode告警+TTS字段 |
| v4.5.19 | 7项 | Dashboard安全：SQL注入白名单+XSS转义+登录持久化+速率限制清理+DB连接管理+敏感字段过滤+SSH WarningPolicy |
| v4.5.18 | 7项 | 线程泄漏→APScheduler调度+新闻缓存加锁+重试APScheduler化+Phase2降频+塔罗缓存清理 |
| v4.5.17 | 5项 | 部署工具SFTP替代sed+safe_upload_config错误处理+CSRF头+登录频率限制+漏斗/群组渲染 |
| v4.5.16 | 4项 | 密码hmac.compare_digest+图表真实数据+死代码清理+快照表数量修正 |
| v4.5.15 | 4项 | 自然语言配置接通TG+Dashboard后端API+特定词自动回复+部署前配置回流 |
| v4.5.14 | 2项 | 自动回复部署同步→MERGE_FIELDS补入+远端验证 |
| v4.5.13 | 4项 | 称呼联动+特定词自动回复+AI润色+预置转化规则 |
| v4.5.12 | 3项 | 问候随机性+隐晦转化+禁止直白营销词 |
| v4.5.11 | 5项 | 新闻连发→停用独立TrendRadar+标题去重改发送后+问候去广告化+新闻自然转述 |
| v4.5.10 | 4项 | 全模态优先文本+chat逻辑池+启动横幅读version.py |
| v4.5.9 | 6项 | 熔断检查移到模型确定后+current_model读llm池+路由配置环境变量+账号失败分级+状态码传递+router_config同步 |
| v4.5.8 | 12项 | BAT全英文+python-dotenv+Dashboard临时密码+裸except收窄+版本同步+部署全量上传+模型索引越界兜底 |
| v4.5.6 | 4项 | 全局故障通知+24h自动删除+AI教指令+话术随机化 |
| v4.5.5 | 3项 | 故障通知去重+指令识别+问题处理法则 |
| v4.5.4 | 3项 | 晚间新闻零token+7新闻源+故障通知 |
| v4.5.3 | 4项 | 新闻零token播报+早安加长+去重共享缓存 |
| v4.5.0-深度扫描 | 18项 | 致命：group_stats缺chat_id+_CST未定义；严重：等级阈值+TTL绕锁+vision_pool引用修改 |
| v4.5.0 | 15项 | 致命：_should_run先标后执行+占位符未替换+task_log缺失+变量未传入；严重：重试被拦截+锁超时 |
| v4.4.8 | 4项 | fetchall AttributeError+孤儿清理频率+日志追踪+ReplySnifferMiddleware启用 |
| v4.4.7 | 3项 | 防重复_should_run+异常处理+购物车挽回日志 |
| v4.4.6 | 3项 | mory_bot参数+SQL注入白名单+Dashboard API恢复 |
| v4.4.3 | 14项 | 致命：硬编码VPS密码+sync_vps无上传+bat指向错误；严重：SyntaxError+locked_multi+pending_tasks上限 |
| v4.4.2 | 3项 | Legacy Loop逻辑反转+task_log联合主键+热词字段 |
| v4.4.1 | 2项 | 多进程重复发送→进程级单例锁+原子操作try_mark_task_executed |
| v4.4.0 | 32项 | 致命：fetchall多线程污染+密钥明文+AI无超时；高危：SQL注入+路径泄漏+SSH注入；中低危25项 |
| v4.3.9 | 1项 | 内存字典→数据库task_log持久化（10个任务） |
| v4.3.8 | 21项 | Dashboard 7项+禁言4项+AI引擎2项+定时任务8项 |
| v4.3.7 | 0项 | 敏感词覆盖+语义缓存隔离审查，无需修改 |
| v4.3.6 | 3项 | 防重复字典迭代+新闻源过滤+备用新闻 |
| v4.3.5 | 2项 | 午安每分钟重复→防重复机制+线程安全 |
| v4.3.4 | 4项 | channel_views浪费API+旧版循环重复+群总结失效+调度不完整 |
| v4.3.3 | 17项 | 致命：硬编码VPS IP；严重：mory_bot未定义+SQL注入+假数据；中等10项 |
| v4.3.2 | 27项 | 致命5项（SQL注入+硬编码+密码缺陷+连接泄漏）；严重14项；中等5项；灾难恢复3项 |
| v4.3.1 | 2项 | API_KEY配置冲突+互斥锁 |
| v4.3.0 | 4项 | Docker部署+AI识图+勋章系统+热更新配置 |
| v4.2.8 | 3项 | 模型过期检查+数据库索引+塔罗解析重写 |
| v4.2.1 | 1项 | AI问候跑题→加强prompt禁止时事政治 |

---

## 通义千问模型命名重要说明

### 两种命名格式都是正式模型

| 命名格式 | 示例 | 含义 |
|---------|------|------|
| 有日期后缀 | qwen3.5-plus-2026-04-20 | 通义千问的正常命名，代表模型版本日期 |
| 无日期后缀 | qwen3.5-plus | 通义千问的基础命名 |

### 重要：模型名日期 ≠ 到期时间

**v4.11.0 重大认知纠正**：

| 字段 | 含义 | 来源 |
|------|------|------|
| 模型名中的日期 | 模型版本发布日期 | 模型Code本身 |
| config.json的expire | **免费额度到期时间** | 后台"过期时间"列 |

**两者完全无关！绝对不能把模型名日期当成到期时间**

### 当前验证可用的LLM模型名

- qwen-flash-character（简写可用）
- qwen3.6-flash-2026-04-16（必须带日期）
- qwen3.5-plus-2026-04-20（必须带日期）
- qwen3.6-plus-2026-04-02（必须带日期）
- qwen3-max（简写可用，带日期的反而不行）
- qwen3.6-max-preview（简写可用）
- glm-5.1（第三方，无日期）

---

## pyTelegramBotAPI Handler 机制警示

**pyTelegramBotAPI的`@bot.message_handler`是独占式的！**
- `return False`不会让消息流转到下一个handler
- **唯一正确方案**：`BaseMiddleware`拦截所有消息
- 中间件名：`ReplySnifferMiddleware`

---

## 已知的平台限制（无法解决）

1. **群组历史消息无法访问** - Telegram API限制
2. **Bot主动私信403** - 用户必须先联系Bot

---

## 失败方案避让（绝对不要重试）

| 编号 | 失败方案 | 原因 | 正确做法 |
|------|----------|------|----------|
| X-01 | return False让handler流转 | pyTelegramBotAPI独占机制，return False无效 | BaseMiddleware拦截 |
| X-02 | f-string拼接SQL列名 | SQL注入风险 | if/else分支 |
| X-03 | fetchone连续调用c.fetchone()[0] if c.fetchone() | 第二次调用返回None | 先保存row=c.fetchone() |
| X-04 | 硬编码VPS IP/密码 | 安全漏洞 | 环境变量读取 |
| X-05 | 硬编码Dashboard Secret Key | 安全漏洞 | 环境变量+启动检查 |
| X-06 | IN子句无限长 | SQL长度溢出 | 限制100条 |
| X-07 | @app.before_request在app定义前 | NameError崩溃 | 装饰器必须在app=Flask()之后 |
| X-08 | 双重except语法except A except B | Python语法错误 | 合并为单个try-except |
| X-09 | 内存缓存无上限 | 内存无限增长 | 添加淘汰机制 |
| X-10 | 误以为日期后缀代表过期 | 通义千问模型有日期后缀是正常命名 | 不要默认把日期后缀当成过期标记 |
| X-11 | 裸except捕获所有异常 | 会吞掉KeyboardInterrupt和SystemExit | 使用except Exception: |
| X-12 | 相对路径做备份 | 工作目录变化时备份位置错误 | 使用os.path.abspath()绝对路径 |
| X-13 | ==比较密码 | 时序攻击风险 | hmac.compare_digest()恒定时间比较 |
| X-14 | fetchall()直接返回cursor结果 | 多线程环境下cursor结果可能被污染 | 深拷贝或改用fetchone()循环 |
| X-15 | 依赖内存字典去重 | 进程重启后数据丢失，多进程不共享 | 数据库持久化task_log表 |
| X-16 | is_task_executed_today() + mark_task_executed()分离调用 | 两次加锁存在竞争窗口 | 原子操作try_mark_task_executed() |
| X-17 | 无进程级单例锁 | 多进程同时运行 | _acquire_process_lock()文件锁 |
| X-18 | 塔罗搭讪用原子操作 | 30%概率触发，不触发时也被标记 | 保持is+mark分离模式 |
| X-19 | sync_vps.py只负责重启，无文件同步 | 名为sync但实际只restart | 新建deploy_vps.py实现完整SFTP流程 |
| X-20 | ai_engine.py prompt中用/n代替\n | /n不是有效转义字符 | 使用\n或字符串拼接 |
| X-21 | resource_manager.py对db资源也加锁 | 与database.py内部锁冲突 | locked_multi中跳过db资源 |
| X-22 | 只修改config.json的API_KEY | main.py启动时用.env的DASHSCOPE_KEY覆盖 | 必须同时修改.env和config.json |
| X-23 | deploy_utils把API_KEY列为保护字段 | VPS上的API_KEY可能是无效旧值 | safe_merge_config：VPS值为空时用本地值 |
| X-24 | 为每条定时消息创建24h休眠线程 | 每天新增10-15个线程，内存泄漏约2-3GB | APScheduler的date触发器调度延迟删除 |
| X-25 | Dashboard前端JS直接插入用户名/内容到HTML | XSS攻击风险 | 前端添加HTML转义函数 |
| X-26 | Dashboard登录失败计数器存在app对象上 | 多worker不共享，重启清零 | SQLite持久化登录失败计数 |
| X-27 | Dashboard api_config_natural返回完整配置 | 敏感字段未过滤 | 应用与api_config相同的敏感字段过滤 |
| X-28 | shell命令拼接用户可控内容 | shell注入风险 | SFTP读写文件，Python层面修改 |

---

## [Trae CN] 统一永久纪律清单

> 从各版本记录中提取的不重复永久纪律，各版本记录中的重复段落已删除。

### 任务调度
- 任务锁必须"先锁后执行"且原子化：内存检查+数据库锁定必须在同一步完成（v4.9.0取代v4.7.0的"先执行后确认"）
- 任务失败必须释放数据库锁，否则重试被拦截（v4.9.0）
- `_confirm_task_done`只设内存锁，数据库锁在`_try_claim_and_lock`中已设置（v4.9.0）
- `_can_run`和`_mark_done`是危险反模式，严禁使用（v4.5.31）
- 所有定时任务必须用`_try_claim_task`+`coalesce=True`+`task_log` UNIQUE约束，三层防护缺一不可（v4.5.31）
- `misfire_grace_time`设为60秒，绝不设为0或1（v4.5.31）
- 所有APScheduler job必须设置`max_instances=1`（v4.5.29）
- 定时消息延迟删除必须用APScheduler调度，禁止创建长时间休眠daemon线程（v4.5.18）
- 共享内存缓存读写必须加锁保护（v4.5.18）
- 重试任务优先用APScheduler date trigger（v4.5.18）
- 已废弃定时任务必须同时：函数体改pass + 从APScheduler移除add_job（v4.5.35）

### 数据库
- 数据库upsert+积分更新必须用原子方法，禁止分开调用（v4.5.23）
- `claim_task`绝不能有SELECT前置，只能纯INSERT OR IGNORE（v4.5.32）
- 任何定时任务防重必须依赖数据库UNIQUE约束（跨进程安全），内存锁只是辅助（v4.5.32）
- 数据库连接统一用Flask g对象管理，禁止手动new+close（v4.5.19）

### 安全
- 严禁使用bare except，必须指定具体异常类型（v4.5.35）
- 敏感词拦截通知严禁泄露用户原始消息内容（v4.5.35）
- Dashboard前端所有用户输入必须escHtml()转义（v4.5.19）
- SQL的ORDER BY禁止用f-string拼接用户输入，必须用白名单映射（v4.5.19）
- 登录失败计数必须持久化到数据库（v4.5.19）
- 部署工具中VPS文件修改一律SFTP读写，禁止shell命令拼接用户可控内容（v4.5.17）
- 独立路由配置不得保存明文API密钥，只能用`${ENV:变量名}`占位符（v4.5.9）
- 首次绑定管理员等高权限操作必须限制在私聊中执行（v4.6.0）
- 所有Web后台必须有会话超时机制，30分钟最低标准（v4.6.0）
- 密码比较用hmac.compare_digest()，禁止==（v4.5.16/X-13）

### AI引擎
- AI调用超时保护必须用concurrent.futures真超时，禁止"完成后检查耗时"伪超时（v4.5.23）
- 熔断检查必须基于"本轮实际调用模型"，不能基于旧指针（v4.5.9）
- 账号失败要区分普通错误、限流、配额耗尽，不能一次失败就永久踢出（v4.5.9）
- 全模态模型确认可走文本接口时，主聊天优先消耗全模态额度（v4.5.10）

### 广告检测
- 单字规则是误判之源，必须搭配色情特征词组合使用（v4.6.5）
- 组合规则间距要严格控制，一般用`[\s\S]{0,1}`或紧邻匹配（v4.6.5）
- 广告检测不能只看单条消息，要追踪用户行为模式（v4.6.3）
- 用户名是广告第一道防线，一眼广告ID应在入群时拦截（v4.6.3）
- CRYPTO中性词（搬砖/矿工/区块链等）weight=1，可疑词weight=3（v4.12.2）
- 广告评分阈值≥3才触发封禁（v4.12.2）
- 名称和消息是两个独立信息源，都必须参与广告评分（v4.12.2）

### 部署
- Bot进程管理统一用systemd，禁止start.sh或手动python main.py（v4.5.33）
- 部署后必须验证Bot是否正常运行（v4.6.5）
- 强依赖第三方库要有回退方案（v4.6.5）
- 新增config.json业务字段时必须同步检查deploy_utils.py的MERGE_FIELDS（v4.5.14）
- 所有"本地可用、线上失效"的配置类改动，部署后要做远端实际读取验证（v4.5.14）
- 上传新配置前必须先停止旧Bot，否则旧进程退出时写回旧配置（v4.5.8）
- 部署不能只传局部文件，必须同步完整运行文件（v4.5.8）
- 模型池增删后必须校正CURRENT_MODEL_INDEX（v4.5.8）

### Telegram API
- Bot API不支持getChatStatistics和getMessageStatistics（客户端专属）（v4.5.34→v4.5.36修正：Bot API 7.0+已支持，前提是Bot必须是管理员）
- Bot API的getUpdates和long polling互斥（v4.5.32）
- Bot API对Bot用户有严格限制：不能CheckChatInvite/GetDialogs（v4.5.32）
- Bot API的chat_id只支持数字ID或@username，不支持邀请链接（v4.5.32）
- handler必须注册所有需要的content_types（v4.5.32）
- channel_post和message是不同update类型，需分别注册handler（v4.5.32）
- Bot主动发送的群消息必须调用track_channel_message入库（v4.5.34）
- 给陌生用户主动发消息前无法预知是否有效，必须catch 400错误自动清理（v4.5.34）

### 内存管理
- 内存字典清理不能只依赖消息触发，必须有定时任务兜底（v4.5.23）
- 共享缓存写入时必须顺便清理过期条目（v4.5.24）
- Telegram消息中用户输入必须HTML转义后再插入（v4.5.23）

### 其他
- Telegram私聊消息没有views属性，获取频道浏览量必须用getattr安全判断None（v4.5.27）
- 日报必须包含"即使当天无入群离群也有值"的指标（v4.5.27）
- 日报实时数据指标应直接调Telegram API，不依赖数据库缓存（v4.5.28）
- 入群检测/禁言规则必须走config.json配置，不硬编码（v4.5.28）
- 发送频道消息时需检测内容是否含HTML标签并自动启用HTML模式（v4.5.35）
- 对外宣称支持"自然语言配置"时，TG/网页/部署三层要走同一套逻辑（v4.5.15）
- 线上人工投喂过的业务内容，部署前必须先回流到本地（v4.5.15）
- 问候文案的转化必须是"隐晦牵引"而不是"直白号召"（v4.5.12）
- 同一时段只能保留一条新闻播报主任务（v4.5.11）
- 新闻标题去重必须在"发送成功后"落库（v4.5.11）
- 启动脚本不得写死版本号，必须从统一版本文件读取（v4.5.10）
- 兼容入口脚本不要通过import执行有副作用的部署脚本，统一用子进程（v4.5.8）
- Dashboard本地启动脚本不得写死固定密码（v4.5.8）
- BAT脚本保持全英文，中文提示放Python脚本里（v4.5.8）
- VPS部署必须先拉回关键文件到本地backups（v4.5.8）
- VPS上运行多个Bot进程时，停止/重启必须精确匹配进程路径（v4.5.32）
