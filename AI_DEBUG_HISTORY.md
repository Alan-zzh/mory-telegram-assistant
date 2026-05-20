# AI_DEBUG_HISTORY.md 调试病历本

> **本文件专门写给AI自己看**
> 新会话开始时，AI 必须先读 `project_snapshot.md` + 本文件
> **最后更新**：2026-05-19（v4.9.2 统一故障通知中心）

---

## 重要：项目上下文

### 基本信息
- **项目**：Mory小助理 - Telegram群管机器人
- **当前版本**：v4.9.2
- **技术栈**：Python 3 + pyTelegramBotAPI + SQLite(WAL) + Flask
- **VPS**：通过环境变量配置（VPS_HOST / VPS_SSH_PASS），无硬编码
- **VPS路径**：通过环境变量 VPS_PATH 配置，默认 /root/mory

### 关键路径
| 用途 | 路径 |
|------|------|
| Bot日志 | `/home/ubuntu/mory_assistant/mory.log`（以实际 VPS_PATH 为准） |
| 重启（唯一允许） | `sudo systemctl restart mory-assistant` |
| 状态 | `systemctl status mory-assistant` |
| 日志 | `journalctl -u mory-assistant -n 200 --no-pager` |

**红线**：
- 禁止用 `pm2` 或 `bash start.sh start` 或手动 `python main.py` 触碰生产进程。
- 违反会导致同 token 多开 long polling，触发 Telegram `409 Conflict`，表现为“机器人不回消息”。

### 核心功能
1. **阅后即焚** - 由 `ReplySnifferMiddleware` 中间件捕获回复
2. **AI对话** - 多模型轮换（通义千问/MiniMax/Kimi/GLM），过期自动跳过
3. **自动任务** - 新闻播报(TTS语音)/问候/塔罗/背刺泄密等后台定时任务
4. **优化引擎** - 语义缓存 + 熔断器 + 令牌桶限流
5. **管理员指令** - 人设管理/群管/黑名单/日志查询
6. **Dashboard** - Flask网页后台，CSRF+速率限制+登录频率限制

---

## 历史Bug记录（倒序）

### v4.9.4 | 2026-05-20 | 根治任务并发异常误报

#### 踩坑24：`reactivate`/`cart_recovery`每小时稳定触发"300秒内被调用2次"告警

**现象**：Telegram 每小时收到"任务并发异常"告警，`reactivate`（x:05）和 `cart_recovery`（x:10）规律出现。

**根因三层叠加**：

| # | 根因 | 说明 | 修复 |
|---|------|------|------|
| 24a | `record_call` 位置错误 | `_TaskGuard.record_call()` 在 `_try_claim_and_lock` **最开头**调用，内存锁/数据库锁拦截的调用也被计入 `call_history`。当 APScheduler 因 misfire 补发一次调用，第二次被锁拦截，但 `record_call` 已记录两次，触发误报。 | `record_call` 移到 `db.claim_task()` **成功之后**，只有真正准备执行的任务才记录 |
| 24b | `coalesce=True` 遗漏 | v4.5.31 踩坑1 已明确记录"所有APScheduler job添加`coalesce=True`"，但 v4.9.x 重构时 `_job_reactivate`/`_job_cart_recovery` 等每小时任务遗漏。`coalesce=False` 时 APScheduler 可能堆积补发多个错过实例。 | 全部每小时任务补上 `coalesce=True` |
| 24c | 缺少防重入保护 | `start_background` 没有检查 `_scheduler_instance` 是否已运行，如果因模块重载或其他原因被调用两次，会创建多个 scheduler 实例独立调度。 | `start_background` 增加 `if _scheduler_instance is not None and _scheduler_instance.running: return` |

**关键认知**：数据库锁（`INSERT OR IGNORE` + `UNIQUE`）已经确保了真正的并发重复执行**不可能发生**。告警全是误报。`TaskGuard` 应该监控"真正成功执行的并发"，而不是"被调用的次数"。

**修复文件**：`modules/auto_tasks.py`

---

### v4.9.0 | 2026-05-19 | 并发重复播报根治

#### 踩坑23：v4.7.0"先执行后确认"流程导致并发重复播报

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 23a | 🔴严重 | 新闻/问候等定时任务并发重复播报 | v4.7.0"先执行后确认"流程：两个线程同时通过`_try_claim_task`和`is_task_executed_today`检查，都执行了发送，然后`_confirm_task_done`中第二次被数据库拦截，但消息已发出 | 新增`_try_claim_and_lock`原子抢占：内存检查+数据库`claim_task`一步完成，执行前就锁定数据库，确保只有一个线程能执行 | auto_tasks.py |
| 23b | 🟡中等 | 原子抢占后任务失败无法重试 | `claim_task`在执行前写入数据库锁，失败后重试被`is_task_executed_today`拦截 | 新增`_release_task`：任务失败时删除数据库锁记录，允许重试 | auto_tasks.py |
| 23c | 🟡中等 | `_confirm_task_done`职责过重 | v4.7.0中`_confirm_task_done`同时设内存锁+数据库锁，但数据库锁已在`_try_claim_and_lock`中设置 | `_confirm_task_done`简化为仅设内存锁，数据库锁由`_try_claim_and_lock`负责 | auto_tasks.py |

**新流程**：`_try_claim_and_lock`(原子抢占) → 执行 → 成功→`_confirm_task_done`(仅设内存锁) / 失败→`_release_task`(释放数据库锁)

**永久纪律**：
- **任务锁必须"先锁后执行"且原子化**：内存检查+数据库锁定必须在同一步完成，不能分两步（否则有并发窗口）
- **任务失败必须释放数据库锁**：否则重试会被拦截，任务永远无法恢复
- **`_confirm_task_done`只设内存锁**：数据库锁在`_try_claim_and_lock`中已设置，不需要重复
- **v4.7.0的"先执行后确认"纪律已过时**：被v4.9.0的"原子抢占+失败释放"取代

### v4.7.0 | 2026-05-18 | 定时任务全面修复

#### 踩坑22：定时任务锁机制"先锁后执行"导致任务失败后无法重试

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 22a | 🔴严重 | 任务失败后2小时内无法重跑 | `_try_claim_task` 在执行前就设置 `_last_task_run` 内存锁 | `_try_claim_task` 改为仅检查不锁定，新增 `_confirm_task_done` 在成功后才锁定 | auto_tasks.py |
| 22b | 🔴严重 | 任务失败后重试被数据库锁拦截 | `claim_task()` 在执行前就写入数据库锁，`_retry_task` 只清内存锁不清数据库锁 | 改为"先执行后确认"流程：`is_task_executed_today()` 检查 → 执行 → `_confirm_task_done()` 确认 | auto_tasks.py |
| 22c | 🔴严重 | 日报/周报/塔罗/背刺泄密仍用旧 `claim_task()` 流程 | 上一轮只修改了问候/新闻/醋意/购物车挽回，遗漏了其余任务 | 全部改用新流程 + 添加 `_retry_task` 重试 | auto_tasks.py |
| 22d | 🔴严重 | 醋意挽回/购物车挽回报错 `'DB' object has no attribute 'execute'` | 代码调用了不存在的 `rm.db.execute()` 方法 | database.py 新增 `delete_user()` 方法，auto_tasks.py 改用 `rm.db.delete_user(uid)` | database.py, auto_tasks.py |
| 22e | 🟡中等 | 废弃的 `_job_burn_probe` 仍在 APScheduler 每5分钟调度 | 函数已标注废弃但调度未移除 | 移除 `scheduler.add_job(_job_burn_probe, ...)` | auto_tasks.py |
| 22f | 🟡中等 | 任务静默失败无感知 | 没有定时健康检查机制 | 新增 `_job_health_check`：每6小时检查关键任务是否执行 | auto_tasks.py |

**永久纪律**：
- **任务锁必须"先执行后确认"**：任何任务都不应在执行前锁定，否则失败后无法重试
- **`_try_claim_task` 仅检查**：只读 `_last_task_run`，不写入
- **`_confirm_task_done` 成功后才锁定**：同时设置内存锁和数据库锁
- **所有任务必须添加 `_retry_task`**：失败后5分钟自动重试，仍失败则通知管理员
- **Database类不能直接暴露execute()**：需要什么操作就封装什么方法

### v4.6.5 | 2026-05-17 | 色情引流暗号扩展+误判修复

#### 踩坑20：单字规则导致正常用户被误判

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 20 | 🟡中等 | "按摩""小姐""约""上门""服务""接待"等单字规则误判正常用户 | 单字规则太宽泛，正常社交也包含这些词 | 全部改为组合规则：按摩+小姐/接待/全套/特服、小姐+接待/全套/上门/特服（精确匹配）、约+小姐/少妇/学生妹（间距≤1）、上门+按摩/特服/全套 | ad_patterns_encoded.py |

**永久纪律**：
- **单字规则是误判之源**：任何可能出现在正常社交中的词（按摩、小姐、约、上门、服务、接待、美女等），必须搭配色情特征词组合使用
- **组合规则间距要严格控制**：`[\s\S]{0,5}` 太宽容易误判，一般用 `[\s\S]{0,1}` 或紧邻匹配
- **"小姐+服务"不是广告**，"小姐+接待/全套/上门/特服"才是 → 用 `(?:接待|全套|上门|特服)` 精确匹配而非字符集
- **"约了同学"不是广告**，"约小姐/约少妇"才是 → 间距缩短到≤1
- **"姐妹一起去按摩"不是广告**，"姐妹一起+干活/赚钱"才是 → 招募规则改为组合

#### 踩坑21：VPS Bot崩溃 - pytz模块缺失

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 21 | 🔴严重 | VPS上Bot无限重启循环，所有功能失效（包括广告检测） | `core/telegram_stats.py` 强依赖 `pytz`，但VPS未安装该模块 | 将 `pytz` 改为可选依赖，未安装时回退到 Python 内置 `timezone(timedelta(hours=8))` | core/telegram_stats.py |

**永久纪律**：
- **部署后必须验证Bot是否正常运行**：不能只看"部署成功"就完事，要检查日志确认Bot启动无报错
- **强依赖第三方库是隐患**：优先使用Python内置模块，第三方库要有回退方案
- **部署脚本应包含依赖检查**：`pip install -r requirements.txt` 后验证关键模块是否可用

---

### [Trae] 色情引流检测规则设计原则与避开指南（v4.6.5 归档）

> **本节是广告检测规则的"防失忆档案"**，新AI会话修改规则前必读。
> 最后更新：2026-05-17

#### 一、规则体系架构

广告检测分三层，每层独立运作：

| 层级 | 机制 | 文件 | 触发条件 |
|------|------|------|----------|
| L1 入群封禁 | 用户名关键词匹配 | group_mgr.py AUTO_MUTE_NAMES | 用户名含一眼广告词 → 入群即永久封禁 |
| L2 内容检测 | 8维度评分 + 延迟封禁 | ad_detector.py + ad_patterns_encoded.py | 单条评分≥2 → 即时封禁；评分>0但<3 → 30分钟累计追踪 |
| L3 兜底检测 | 旧版关键词检测 | group_mgr.py check_ad_content | 兜底防线，L2漏检时触发 |

#### 二、8维度评分体系（ad_patterns_encoded.py）

| 维度 | 变量名 | 权重 | 覆盖范围 |
|------|--------|------|----------|
| 赚钱承诺 | MONEY_PATTERNS | 2 | 日入/日赚/稳赚/躺赚/暴利/保底/月入/年入 + 间隔符规避变体 |
| 色情引流 | ADULT_PATTERNS | 2 | 30+条组合规则（详见下方完整清单） |
| 灰色产业 | GRAY_PATTERNS | 2 | 假钞/精仿/盘口/毒品/赌博/码车/卡车/人头费/开户代投 |
| 加密货币 | CRYPTO_PATTERNS | 2 | USDT/搬砖/洗米/跑分/搞米/不实名/放电宝/充电宝/发车/上车 + 交易所/合约/杠杆等 |
| 联系方式 | CONTACT_PATTERNS | 1 | 加微信/加薇信/加VX/ZFB/支付宝/t.me链接/看我简介变体 |
| 招募拉人 | RECRUIT_PATTERNS | 1 | 招团队/找几个/兄弟一起/姐妹一起+干活/来几个+兄弟/矿工+来人/看置顶 |
| 低门槛 | LOW_BARRIER_PATTERNS | 1 | 轻资产/零成本/小白也能/入门就会/无套路/无门槛/免学费 |
| 引流暗示 | PROFILE_HINT_PATTERNS | 1 | 纯"简介"/"主页"/"资料"三词（仅匹配整条消息） |

**评分规则**：
- 单维度多次命中只计一次分（v4.6.5新增，防同维度规则重复加分）
- 用户名异常 + 内容评分 ≥ 2 = 高置信度广告
- 内容评分 ≥ 2 = 即时封禁
- 内容评分 > 0 但 < 3 = 进入30分钟延迟追踪窗口

#### 三、ADULT_PATTERNS 完整规则清单（v4.6.5）

**设计原则：组合规则 > 单字规则**

| 规则类型 | 规则示例 | 设计原因 |
|----------|----------|----------|
| 纯暗号（无歧义） | 口爆、全套服务、特服、约炮、裸聊、一夜情、包夜、寻花问柳、学生妹、色情 | 这些词在正常社交中几乎不会出现，可单独匹配 |
| 身材描述暗号 | 身材火辣、年轻漂亮、活好、正点、白嫖 | 色情引流专用描述，正常社交极少用 |
| 价格暗号 | 数字+P/S/套/次/晚/夜、数字+E/F级+奶/胸/美、奶+数字/尺/美型、一次+数字、一晚+数字、数字+元一次、数字+元一晚 | 数字+单位是色情服务标价特征 |
| 特殊暗号 | M36D（罩杯暗号）、白虎（体貌暗号）、反差M（反差婊暗号）、淫姑/淫娃 | 黑话暗号，正常社交不会用 |
| 组合规则（核心） | 按摩+小姐/接待/全套/特服 | "按摩"单字太宽，必须搭配色情特征词 |
| 组合规则 | 小姐+(?:接待\|全套\|上门\|特服) | "小姐服务"不是广告，"小姐接待/全套/上门/特服"才是 |
| 组合规则 | 少妇+服务/接待/约/全套/特服 | "少妇"单字太宽，必须搭配 |
| 组合规则 | 接待+全套/上门/特服 | "接待"单字太宽，必须搭配 |
| 组合规则 | 全套+按摩/特服 | "全套"单字太宽，必须搭配 |
| 组合规则 | 约+小姐/少妇/学生妹/奶/美女（间距≤1） | "约了同学"不是广告，"约小姐"才是，间距必须≤1 |
| 组合规则 | 同城+约/小姐/少妇/学生妹 | "同城"单字太宽，必须搭配 |
| 组合规则 | 上门+按摩/特服/全套（间距≤3） | "上门修电脑"不是广告，"上门按摩"才是 |
| 组合规则 | 到店+约/特服/全套 | 到店+色情特征词 |
| 组合规则 | 美女+约/接待/特服/全套 | "美女"单字太宽，必须搭配 |
| 组合规则 | 成人+约/视频/特服 | "成人"单字太宽，必须搭配 |
| 组合规则 | 洗浴+全套/上门/特服 | "洗浴"单字太宽，必须搭配 |
| 组合规则 | KTV+小姐/特服/全套（间距≤3） | "去KTV唱歌"不是广告，"KTV小姐"才是 |
| 组合规则 | 足浴+小姐/特服/全套 | "足浴"单字太宽，必须搭配 |
| 行为暗号 | 约起、来约、快约 | 色情约炮行为特征 |
| 场景暗号 | 上门服务、同城约、视频聊 | 色情引流场景特征 |
| 招募暗号 | 各地+学生、各地+约、传递+各地、学生+约 | 招募话术+色情特征组合 |

#### 四、AUTO_MUTE_NAMES 入群封禁词清单（group_mgr.py）

入群时用户名匹配即永久封禁，分6大类：

| 类别 | 关键词 |
|------|--------|
| 加密货币 | 虚拟币/搬砖/币圈/炒币/数字货币/加密货币/区块链投资/合约交易/量化交易/USDT/BTC/ETH交易/空投/挖矿 |
| 赚钱黑话 | 日入/日赚/躺赚/稳赚/暴利/月入/年入/保底/零成本/无风险/搞米/安全搞米/放电宝/充电宝 |
| 招募引流 | 招团队/拉人头/招代理/招加盟/兼职/副业/刷单/做任务 |
| 色情引流 | 裸聊/约炮/同城交友/上门服务 |
| 灰色产业 | 洗钱/跑分/代付/代收/资金盘/博彩/赌博/娱乐城/菠菜 |
| 联系方式 | 加我/私聊我/私我/关注我/点击链接/微信号/QQ群/Telegram群/群号/看简介/看我简介/看我主页/看我资料 |
| v4.6.4新增 | 各地/约/学生/M36D/白虎/传递/800约/各地约 |

#### 五、避开指南（绝对不要做的事）

| 编号 | 禁止操作 | 原因 | 正确做法 |
|------|----------|------|----------|
| R-01 | 添加单字规则（如"按摩""小姐""约""上门""服务""接待""美女""少妇"） | 单字规则是误判之源，正常社交中这些词极常见 | 必须搭配色情特征词组合使用，如"按摩+小姐""约+少妇" |
| R-02 | 用字符集匹配（如`[服务接待全套上门特服]`） | 字符集匹配单个字符，"小姐服务"中的"服"会被误匹配 | 用精确匹配`(?:接待\|全套\|上门\|特服)` |
| R-03 | 组合规则间距用`[\s\S]{0,5}` | 太宽泛，"约了同学周末打球"中"约"和"学"间距3就被误匹配 | 缩短到`[\s\S]{0,1}`或紧邻匹配 |
| R-04 | 在KTV/上门组合中包含"约" | "去KTV唱歌，约不约"是正常社交 | KTV/上门组合只搭配色情特征词（小姐/特服/全套） |
| R-05 | "姐妹一起"单独匹配为招募 | "姐妹一起去按摩"是正常社交 | 改为"姐妹一起+干活/赚钱/做事"组合 |
| R-06 | 不验证就部署新规则 | 新规则可能误判正常用户，部署后Bot崩溃也不自知 | 部署前跑test_detect.py验证，部署后检查Bot状态 |
| R-07 | 部署后不验证Bot是否运行 | pytz缺失导致Bot崩溃，所有功能（包括广告检测）失效 | 部署后必须`systemctl status mory-assistant`确认active |
| R-08 | 强依赖第三方库无回退 | VPS可能缺少pytz等库，导致Bot无法启动 | 第三方库用try-except包裹，提供Python内置回退方案 |
| R-09 | 同维度规则重复加分 | 一条消息匹配多条ADULT规则，评分虚高 | v4.6.5已修复：每个维度break后只计一次分 |
| R-10 | 不更新文档就改规则 | 以后AI失忆不知道为什么这样设计，可能重复犯错 | 改规则必须同步更新本节文档 |

#### 六、规则变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v4.6.4 | 2026-05-17 | 新增M36D/白虎/800约/各地+约/传递+各地等色情暗号；修复emoji夹杂用户名检测 |
| v4.6.5 | 2026-05-17 | 大幅扩展30+条组合规则；所有单字规则改为组合规则；修复6处误判；修复pytz缺失崩溃；单维度只计一次分 |

---

### v4.6.3 | 2026-05-17 | 智能广告拦截增强（延迟封禁+入群即封）

#### 踩坑18：广告第一条消息难判断，后续才露出马脚

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 18 | 🟡中等 | 高级广告用户第一条消息很隐蔽（如"新项目来了"），无法即时判定为广告，但后续连续发广告内容 | 单条消息检测阈值过高，无法捕捉渐进式广告行为 | 新增延迟封禁机制：`track_suspicious_user()` 累计评分，30分钟窗口期内达到阈值（默认3分）后触发封禁，并删除该用户所有历史消息 | modules/ad_detector.py + main.py |

**永久纪律**：
- 广告检测不能只看单条消息，要追踪用户在一段时间内的行为模式
- 累计评分机制可以有效识别"试探→逐步暴露"的广告策略
- 封禁后必须清理历史消息，避免广告残留

#### 踩坑19：一眼广告的用户名ID入群不被拦截

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 19 | 🟡中等 | 用户名明显是广告（如"虚拟货币搬砖日挣1000U"、"搞米加我"）的用户入群后，要等到发言才被检测 | AUTO_MUTE_NAMES 关键词列表不够全，缺少赚钱黑话和组合关键词 | 扩充 AUTO_MUTE_NAMES：新增赚钱黑话（搞米/日入/躺赚）、招募引流、色情引流、灰色产业、联系方式引流等6大类关键词 | modules/group_mgr.py |

**永久纪律**：
- 用户名是广告的第一道防线，一眼广告的ID应该在入群时就拦截
- 关键词列表要覆盖各种变体：简写、谐音、组合词
- 定期根据实际漏检案例补充关键词

---

### v4.6.0 | 2026-05-16 | 深度用户挑刺报告P0/P1修复（10项）

#### 踩坑15：Dashboard日志查询列名与reply_tracking表不匹配

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 15 | 🔴严重 | Dashboard `/api/logs` 和 `/api/logs/search` 查询 `id, user_id, user_name, bot_mid, reply_type, ts, content_preview` 列，但 `reply_tracking` 表实际列名为 `bot_msg_id, chat_id, user_msg_id, ts, replied`，导致日志页面完全不可用 | 前后端列名与实际表结构不一致 | 修复SQL查询和前端表头，匹配实际列名，replied字段用✅/⏳状态徽章展示 | dashboard/app.py |

**永久纪律**：
- Dashboard查询数据库时，列名必须与实际表schema一致，禁止凭想象写列名
- 修改查询后必须同步更新前端渲染的表头和字段映射

#### 踩坑16：绑定主人首次绑定无安全验证

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 16 | 🔴严重 | `绑定主人`指令在ADMIN_ID为0时，任何人在群聊中发送即可劫持Bot管理员权限，先到先得无安全验证 | 首次绑定无环境限制，群聊中任何人都能执行 | 首次绑定（ADMIN_ID==0）限制只能在私聊中执行，群聊发送返回警告 | modules/admin_cmds.py |

**永久纪律**：
- 首次绑定管理员等高权限操作，必须限制在私聊环境中执行
- 群聊中暴露此类操作入口等于把管理权拱手让人

#### 踩坑17：Dashboard会话无过期机制

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 17 | 🔴严重 | Dashboard登录后session永不过期，公共电脑上登录后忘记退出，任何人都能访问后台 | Flask默认session未设置PERMANENT_SESSION_LIFETIME | 添加 `app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)` | dashboard/app.py |

**永久纪律**：
- 所有Web后台必须有会话超时机制，30分钟无操作自动登出是最低标准
- Flask的PERMANENT_SESSION_LIFETIME必须显式设置，不能依赖默认值

### v4.5.35 | 2026-05-08 | 全面暗病修复（9项安全/性能/功能问题）

#### 踩坑11：bare except子句隐藏关键错误

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 11 | 🟡中等 | `natural_cmd.py`中`except:`裸捕获会吞掉KeyboardInterrupt/SystemExit等致命异常，导致Bot无法正常退出 | bare except不区分异常类型，连Ctrl+C都无法退出 | 改为`except (json.JSONDecodeError, TypeError, ValueError):`精准捕获 | modules/natural_cmd.py |

**永久纪律**：
- 严禁使用bare except（裸except），必须指定具体异常类型
- 至少捕获`except Exception:`，绝不能`except:`

#### 踩坑12：敏感词通知泄露用户消息内容

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 12 | 🟡中等 | `check_banned_words`给管理员发通知时包含用户原始消息摘要（前50字），可能泄露隐私内容 | 通知中拼接了`_safe_preview = msg[:50]` | 管理员通知只显示触发词，不显示原始消息内容，改为"消息已删除，原始内容未记录" | modules/group_mgr.py |

**永久纪律**：
- 敏感词拦截通知中严禁泄露用户原始消息内容
- 只通知触发词和用户身份，原始内容已在群内删除即可

#### 踩坑13：代发频道不支持HTML格式

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 13 | 🟡中等 | "代发频道"命令发送含HTML标签的内容时，标签被当纯文本显示而非渲染 | `bot.send_message(cid, content)`未指定`parse_mode="HTML"` | 自动检测内容是否含HTML标签（`<b>/<i>/<u>/<a href=`等），有则启用`parse_mode="HTML"` | modules/admin_cmds.py |

**永久纪律**：
- 发送频道消息时，需检测内容是否含HTML标签并自动启用HTML模式
- 常见HTML标签：`<b>`, `<i>`, `<u>`, `<s>`, `<code>`, `<pre>`, `<a href=`

#### 踩坑14：burn_probe空函数仍被调度

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 14 | 🟢轻微 | `_job_burn_probe`已降级为空操作（只打日志），但APScheduler仍每5分钟调度一次，浪费调度资源 | v4.0已废弃forward探测，但函数保留且调度未移除 | 函数改为纯`pass`空实现，docstring注明彻底废弃原因 | modules/auto_tasks.py |

**永久纪律**：
- 已废弃的定时任务必须同时：①函数体改为pass ②从APScheduler移除add_job
- 保留空函数仅为了兼容旧版循环调用

#### 其他修复项（v4.5.35）
- **购物车挽回清理无效用户**：捕获400错误自动清理users+cart_recovery表（踩坑9已记录）
- **阅后即焚Phase2废弃**：跳过forward探测，依赖Phase1 TTL清理（踩坑14相关）
- **塔罗缓存500上限**：防止群成员过多导致内存泄漏，触发时随机淘汰20%旧缓存
- **HTML全字段转义**：塔罗消息中所有动态内容统一`html.escape()`，防止XSS/格式错乱

---

### v4.5.36 | 2026-05-15 | 群统计全面修复：getChatStatistics接入 + chat_id=0硬编码 + 入群遗漏 + 校准机制

#### 踩坑10：周报 chat_id=0 硬编码导致数据永远为0

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 10 | 🔴严重 | 周报入群/离群/净增永远为0 | `get_weekly_group_stats()` SQL 写死 `AND chat_id=0`，但 `record_group_join/left` 传入实际 chat_id | 新增 `chat_id` 参数，调用方传入 GROUP_ID | core/database.py |
| 11 | 🟡中等 | 可疑用户入群不计入统计 | `handle_new_members()` 中可疑用户 `continue` 跳过 `record_group_join()` | 将 `record_group_join()` 移到可疑检测之前 | modules/group_mgr.py |
| 12 | 🟡中等 | 入群/离群事件无校准，Bot宕机漏记 | 纯事件驱动，无 reconciliation 机制 | 新增 `calibrate_group_stats()` 每小时对比 API 实时人数修正 | core/database.py, modules/auto_tasks.py |

#### [Trae] 踩坑8修正：getChatStatistics Bot API 7.0+ 已支持

之前记录"Bot API不支持getChatStatistics"是**不准确的**。Bot API 7.0+（2023年12月）已正式支持，前提是 Bot 必须是频道/群组管理员。之前返回404可能是 Bot 当时不是管理员。新增 `core/telegram_stats.py` 封装此 API，日报/周报优先使用 API 数据。

---

### v4.5.34 | 2026-05-08 | 频道日报/周报修复 + 醋意/购物车挽回400修复 + 代发频道track消息

#### 踩坑8：getChatStatistics API返回404 Not Found

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 8 | 🔴严重 | 频道日报/周报中发帖数/浏览量全0 | `getChatStatistics`是Telegram客户端专属API，Bot API不支持（返回404）；`channel_tracking`表里只有群消息没有频道消息 | 日报/周报改为：成员数用`get_chat_member_count` API实时获取，浏览/发帖提示"请在Telegram客户端查看" | modules/auto_tasks.py |

**永久纪律**：
- Telegram Bot API **不支持**`getChatStatistics`和`getMessageStatistics`，这两个API只在Telegram客户端可用
- 频道/群的浏览/转发/互动等详细统计，只能引导用户在Telegram客户端查看
- Bot API只能获取成员数（`get_chat_member_count`）

#### 踩坑9：醋意/购物车挽回给无效用户发消息报400

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 9 | 🟡中等 | 醋意挽回/购物车挽回定时任务给未启动私聊或已拉黑的用户发消息，报400 "chat not found" | `get_inactive_users`和`get_expired_carts`返回的用户可能已经删除对话或拉黑Bot，但数据库未清理 | 捕获400错误，识别"chat not found"/"bot was blocked"/"forbidden"关键词，自动从users表清理无效用户 | modules/auto_tasks.py |

**永久纪律**：
- 给陌生用户主动发消息前，无法预知是否有效（Bot API无预检方法）
- 必须在catch中识别400错误关键词，自动清理无效用户
- 关键词清单：`chat not found`、`bot was blocked`、`forbidden`

#### 踩坑10：代发频道命令不track消息

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 10 | 🟡中等 | `admin_cmds.py`的"代发频道"命令发送消息后不调用`track_channel_message`，导致频道消息未入库 | 代发频道只调用`bot.send_message`，遗漏了数据库追踪 | 发送成功后加`db.track_channel_message(cid, sent.message_id, "text")` | modules/admin_cmds.py |

**永久纪律**：
- 所有向频道/群发送消息的地方，发送成功后必须调用`track_channel_message`入库
- 包括：代发频道、自动推送、定时任务等所有发送场景

---

### v4.5.32 | 2026-05-07 | 获取隐私频道ID踩坑全记录 + Telegram频道统计API接入

#### 踩坑1：Bot handler只处理text消息，转发图片/视频完全收不到

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 1 | 🔴严重 | 用户转发频道消息给Bot，Bot完全收不到 | `master_handler`只注册了`content_types=["text", "new_chat_members"]`，转发图片/视频/文档等非text消息被Telegram直接丢弃，Bot根本不处理 | 注册`channel_post_handler`捕获频道消息，注册全content_types的forward handler捕获转发消息 | main.py |

**永久纪律**：
- 如果需要捕获用户转发的消息，handler必须注册所有可能的content_types（photo/video/document/animation/sticker/voice/video_note）
- 频道消息（channel_post）和普通消息（message）是不同的update类型，需要分别注册handler
- `bot.message_handler`只能处理message类型，channel_post需要`bot.channel_post_handler`

#### 踩坑2：停Bot用getUpdates获取消息——被Bot进程消费了

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 2 | 🔴严重 | 停Bot后用getUpdates获取转发消息，始终返回空 | Bot使用long polling消费updates，停Bot后之前的updates已被消费完；用户在Bot运行时转发的消息被Bot吃掉了 | 不要用getUpdates方案，直接在Bot代码中加handler记录到文件 | temp脚本 |

**永久纪律**：
- Telegram Bot API的getUpdates和long polling互斥，Bot运行时getUpdates拿不到数据
- 停Bot再getUpdates的方案不可靠，因为用户可能在Bot运行时已经发了消息
- **正确方案**：在Bot代码中加handler，Bot运行时自动记录需要的信息到文件/数据库

#### 踩坑3：VPS上有多个Bot进程，停错了

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 3 | 🟡中等 | 停Bot时误停了mory_media_assistant，真正要停的mory_assistant还在运行 | VPS上运行了2个Bot进程（mory_assistant和mory_media_assistant），grep匹配不精确导致误杀 | 用精确路径匹配：`ps aux | grep 'mory_assistant/main.py' | grep -v grep` | 项目规则 |

**永久纪律**（已写入project_rules.md）：
- 停Bot/重启Bot时，必须精确匹配进程路径
- `mory_assistant`是本项目，`mory_media_assistant`是另一个独立项目
- 优先使用`deploy_vps.py`部署脚本，它已自动处理进程区分

#### 踩坑4：Telethon Bot模式API限制

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 4 | 🟡中等 | 用Telethon Bot token调用CheckChatInvite/GetDialogs报BotMethodInvalidError | Telegram Bot API对Bot用户限制很多，CheckChatInviteRequest和GetDialogsRequest都不允许Bot调用 | Bot无法通过邀请链接解析私有频道ID，必须用channel_post handler让用户在频道里发消息触发 | temp脚本 |

**永久纪律**：
- Telegram Bot API对Bot用户有严格限制：不能调用CheckChatInviteRequest、GetDialogsRequest等
- Bot不能通过邀请链接解析私有频道ID
- Bot不能获取自己加入的所有对话列表
- **获取私有频道ID的唯一可靠方案**：Bot是频道管理员 → 加channel_post_handler → 用户在频道发消息 → Bot自动捕获chat_id

#### 踩坑5：Bot API的sendMessage/getChat无法解析邀请链接

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 5 | 🟡中等 | 用sendMessage/getChat传入邀请链接，返回"chat not found" | Bot API的chat_id参数不支持邀请链接格式（https://t.me/+xxx），只支持数字ID或@username | 私有频道没有公开username，只能通过channel_post handler获取ID | temp脚本 |

**永久纪律**：
- Bot API的chat_id只支持：数字ID（如-100xxx）、@username（公开频道/群组）
- 邀请链接（https://t.me/+xxx）不能作为chat_id使用
- 私有频道没有公开username，无法通过Bot API直接获取其chat_id

#### 最终成功方案

**获取到的4个频道ID**：
| 频道名 | 频道ID | 类型 |
|--------|--------|------|
| Mory·至臻预览 | -1003875429116 | 公开频道(@moryselect) |
| Mory·至臻全享 | -1003852883272 | 私有频道 |
| Mory·精选图集 | -1003899594804 | 私有频道 |
| Mory· 至臻精选❤️ | -1003044739415 | 私有频道 |

**成功方案步骤**：
1. 在Bot代码中加`@bot.channel_post_handler(func=lambda m: True)`
2. 当频道有新消息时，handler自动记录chat_id和title到文件
3. 部署后让用户在3个频道各发一条消息
4. Bot自动捕获频道ID

#### Telegram频道统计API（getChatStatistics / getMessageStatistics）

**API说明**：
- `getChatStatistics`：获取频道整体统计（成员增长、浏览量、转发数、禁用人数等）
- `getMessageStatistics`：获取单条消息的统计（浏览量、转发数、反应数等）
- **前提条件**：Bot必须是频道管理员
- **返回数据**：每条帖子的详细数据（浏览量、转发数、反应数、禁用人数等）

**接入方式**：
- 这两个API是Telegram Bot API 6.3+新增的，需要直接调用HTTP API
- pyTelegramBotAPI可能没有封装，需要用requests直接调用
- 端点：`https://api.telegram.org/bot{TOKEN}/getChatStatistics?chat_id={CHAT_ID}`
- 端点：`https://api.telegram.org/bot{TOKEN}/getMessageStatistics?chat_id={CHAT_ID}&message_id={MSG_ID}`

---

### v4.5.32 | 2026-05-02 | 彻底根治多进程连发（数据库级原子抢占+start.sh强力kill）

| # | 严重度 | 问题 | 原因 | 修复方案 | 文件 |
|---|--------|------|------|----------|------|
| 1 | 🔴严重 | 早安/新闻连发两条（内容不同，说明两次独立执行） | **VPS存在多Bot进程同时运行**（日志大量409错误）内存锁`_try_claim_task`跨进程完全无效；`start.sh stop`只发SIGTERM不等待，旧进程残留时新进程就启动了 | **四层防护**：①`start.sh stop`改为SIGTERM→等待5秒→SIGKILL强制清理所有残留 ②新增`db.claim_task()`纯INSERT OR IGNORE原子抢占（无SELECT竞态窗口） ③所有定时任务在AI工作前调用`claim_task`抢占名额 ④内存锁`_try_claim_task`保留作快速拦截 ⑤APScheduler `coalesce=True`防堆积 | core/database.py, modules/auto_tasks.py, start.sh |
| 2 | 🔴回归 | v4.5.31的`claim_task`仍有SELECT竞态窗口 | v4.5.31的`claim_task`先SELECT再INSERT，跨进程时两个进程可能同时SELECT为空然后都INSERT | 删除SELECT，纯INSERT OR IGNORE依赖UNIQUE索引保证原子性（SQLite层面原子） | core/database.py |

**根因追溯**：
- v4.5.29→v4.5.31修复的都是**单进程内**的竞态（内存锁+数据库锁）
- 但真正的bug是**多进程**！VPS日志大量409错误证明至少2个Bot进程在同时跑

---

### v4.5.33 | 2026-05-07 | 日报/周报拆分 + start.sh误杀修复 + 部署后多进程残留

#### 踩坑6：start.sh stop用grep '[m]ain.py'会误杀mory_media_assistant

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 6 | 🔴严重 | `start.sh stop`中`ps aux \| grep '[m]ain.py'`匹配到所有main.py进程，包括mory_media_assistant/main.py，导致误杀另一个Bot | grep模式太宽泛，只匹配了"main.py"而没区分项目路径 | 改为精确匹配：`ps aux \| grep 'mory_assistant/main.py' \| grep -v grep` | start.sh |

**永久纪律**：
- VPS上运行多个Bot进程时，停止/重启必须精确匹配进程路径
- grep模式必须包含项目目录名，不能只匹配文件名
- `mory_assistant`和`mory_media_assistant`是两个独立项目，严禁混淆

#### 踩坑7：部署后出现2个mory_assistant进程导致409冲突

| # | 严重度 | 问题 | 原因 | 解决办法 | 文件 |
|---|--------|------|------|----------|------|
| 7 | 🔴严重 | 部署后VPS上同时存在2个mory_assistant进程，导致409 Conflict | **根因：VPS上有systemd服务`mory-assistant.service`配置了`Restart=always`**，deploy_vps.py用start.sh启动新进程后，systemd检测到旧进程被杀又自动重启了一个，导致2个进程同时运行 | deploy_vps.py改为用systemd管理Bot：`systemctl stop` → 上传文件 → `systemctl start`，不再用start.sh | deploy_vps.py, deploy_utils.py |

**永久纪律**：
- **Bot进程管理统一用systemd**：`systemctl start/stop/restart mory-assistant`
- 禁止用`start.sh start/stop`或手动`python main.py`，会和systemd冲突导致多进程
- 部署后必须检查进程数：`ps -ef | grep 'mory_assistant/main.py' | grep -v grep | wc -l`，应该只有1个
- 如果出现409错误，第一时间检查进程数，多余的进程必须杀掉
- systemd服务文件：`/etc/systemd/system/mory-assistant.service`，配置了`Restart=always`和`RestartSec=5`

#### 功能变更记录：日报/周报拆分

**变更内容**：
1. 日报拆分为2条消息：群数据日报 + 频道数据日报，都发到私聊(ADMIN_ID)
2. 新增周报功能：群数据周报 + 频道数据周报，每周一9:30发送
3. 周报包含：周环比变化百分比、留存率、各频道成员增长、发帖统计
4. 频道统计定时任务保持每小时25分执行一次（用户确认OK）

**新增数据库方法**：
- `get_weekly_group_stats(start_date, end_date)` - 群周统计聚合
- `get_weekly_channel_member_stats(chat_id, start_date, end_date)` - 频道成员数变化
- `get_channel_posts_in_range(chat_id, start_ts, end_ts)` - 频道发帖和浏览量统计

**新增定时任务**：
- `weekly_report` - 每周一9:30 CST，发送群+频道周报

**4个频道配置**（config.json CHANNEL_IDS）：
| 频道名 | 频道ID | 类型 |
|--------|--------|------|
| 至臻预览 | -1003875429116 | public |
| 至臻全享 | -1003852883272 | private |
| 精选图集 | -1003899594804 | private |
| 至臻精选 | -1003044739415 | private |
- 多线程锁（Python threading.Lock）跨进程完全不生效
- **只有SQLite的UNIQUE约束 + INSERT OR IGNORE才是跨进程原子操作**

**新增永久纪律**：
- 任何定时任务防重必须依赖数据库UNIQUE约束（跨进程安全），内存锁只是辅助
- `claim_task`绝不能有SELECT前置（引入竞态窗口），只能纯INSERT OR IGNORE
- `start.sh stop`必须等待旧进程彻底退出再启动，防止多进程重叠
- 定时任务必须在**所有重操作前**（AI/API调用前）就完成claim

### v4.5.31 | 2026-05-01 | 彻底根治连发（三层防护+全局替换）

| # | 严重度 | 问题 | 原因 | 修复方案 | 文件 |
|---|--------|------|------|----------|------|
| 1 | 🔴严重 | 数据日报连发3条（9:10同时发送3条完全相同消息） | 1. `_job_daily_report`仍用`_can_run`（非原子）+`_mark_done`，v4.5.29漏改 2. `task_log`表无UNIQUE约束，`mark_task_executed`用`INSERT`非`INSERT OR IGNORE` 3. APScheduler缺`coalesce=True`，任务堆积全部执行 4. `misfire_grace_time=1`太短，网络操作超1秒被判misfire后APScheduler重试 | **三层防护**：①`task_log`添加UNIQUE约束+`INSERT OR IGNORE`+清理历史重复值 ②全部APScheduler job改用`_try_claim_task`原子锁 ③所有APScheduler job添加`coalesce=True`+`misfire_grace_time=60` | core/database.py, modules/auto_tasks.py |
| 2 | 🔴严重 | `_can_run`+`_mark_done`模式在5个任务中残留（reactivate/cart_recovery/leak/tarot_flirt/daily_report） | v4.5.29仅修复了新闻和问候，其他5个任务仍用旧模式 | 全部改为`_try_claim_task`原子抢占，删除`_can_run`调用点和`_mark_done`标记 | modules/auto_tasks.py |

**新增永久纪律**：
- `_can_run`和`_mark_done`是危险的反模式，严禁在任何新任务中使用
- 所有定时任务必须用`_try_claim_task`（内存原子锁）+`coalesce=True`（APScheduler防堆积）+`task_log` UNIQUE约束（数据库级原子防重），三层防护缺一不可
- `misfire_grace_time`设为60秒（足够覆盖网络延迟，同时1分钟内错过可补发），绝不设为0或1
- 新增任务时必须同时登记到这3个防护层
- APScheduler `coalesce=True`含义：如果多次触发堆积，只执行最新的一次

### v4.5.30 | 2026-05-01 | 修复misfire补发连发（改为grace_time=1，但引入了新问题）

| # | 严重度 | 问题 | 原因 | 修复方案 | 文件 |
|---|--------|------|------|----------|------|
| 1 | 🔴严重 | 晚间新闻连发3条（早间+午间+晚间内容同时出现） | APScheduler的misfire_grace_time=300秒，Bot重启后5分钟内会补发所有错过的任务 | 新闻/问候/报告/塔罗等定时任务misfire_grace_time从300改为1，错过执行窗口立即跳过，绝不补发 | modules/auto_tasks.py |

**根因分析**：
- v4.5.29修复了"同一任务多实例并发"问题（max_instances=1+_try_claim_task原子锁）
- 但遗漏了APScheduler的misfire机制：grace_time=300表示错过执行时间后5分钟内重启，任务会被补发
- 截图显示20:35同时出现3条不同内容的新闻，说明早间9:05和午间13:05的任务在重启时被补发了

**新增永久纪律**：
- 所有定时任务（新闻/问候/报告）的misfire_grace_time必须设为1，错过就跳过，绝不补发
- 只有高频循环任务（每分钟/每5分钟）可以保留较大的grace_time

### v4.5.29 | 2026-05-01 | 修复早安/新闻连发+AI广告检测自动删除+永久禁言

| # | 严重度 | 问题 | 原因 | 修复方案 | 文件 |
|---|--------|------|------|----------|------|
| 1 | 🔴严重 | 早安/午安/晚安/新闻连发两条 | `_can_run`仅检查不标记，执行后`_mark_done`存在时间窗口；APScheduler未设`max_instances=1`，可能同时触发多个实例 | 1. 新增`_try_claim_task`原子性抢占（检查+标记一步完成） 2. 所有问候和新闻任务改用`_try_claim_task`替代`_can_run`+`_mark_done` 3. 所有APScheduler job添加`max_instances=1` | modules/auto_tasks.py |
| 2 | 🆕新功能 | 群内广告变体无法自动处理 | 仅有BANNED_WORDS敏感词检测，无广告/引流/营销内容检测能力 | 1. 新增`check_ad_content`函数：硬编码广告关键词快速过滤 2. 确认广告后：删除消息+永久禁言+通知管理员（用户名+@ID格式） 3. 在main.py消息处理链P3.5位置接入 | modules/group_mgr.py, main.py |

### v4.5.29-hotfix | 2026-05-01 | 生产故障：check_ad_content未导入NameError

| # | 严重度 | 问题 | 原因 | 修复方案 | 文件 |
|---|--------|------|------|----------|------|
| 1 | 🔴严重 | `NameError: name 'check_ad_content' is not defined` | v4.5.29新增`check_ad_content`函数在`modules/group_mgr.py`中定义，但`main.py`的导入语句中遗漏了该函数 | 在`main.py`的`from modules.group_mgr import`语句中追加`check_ad_content` | main.py |

**新增永久纪律**：
- 定时任务的检查+标记必须原子性完成，禁止分开操作（`_try_claim_task`替代`_can_run`+`_mark_done`）
- 所有APScheduler job必须设置`max_instances=1`，防止同一任务多实例并发
- 广告检测纯规则匹配，零token消耗
- 禁言通知管理员时必须用`用户名 + @username`格式，禁止发送数字ID

### v4.5.28 | 2026-05-01 | 日报群成员数修复 + 入群自动禁言功能

| # | 严重度 | 问题 | 原因 | 修复方案 | 文件 |
|---|--------|------|------|----------|------|
| 1 | 🟡中等 | 日报群成员数显示不对（实际5000+但显示错误） | get_group_total_members_latest从数据库group_stats表读取，该表只在_job_channel_views时更新，可能数据过时或为0 | 日报直接调bot.get_chat_member_count(gid)获取实时数据，失败时才回退到数据库 | modules/auto_tasks.py |
| 2 | 🆕新功能 | 入群名字含虚拟币/搬砖等关键词的用户应自动永久禁言 | 无此功能 | handle_new_members新增名字检测逻辑，匹配AUTO_MUTE_NAMES关键词则restrict_chat_member永久禁言，不入库不欢迎；关键词列表走config.json配置 | modules/group_mgr.py, config.json |

**新增永久纪律**：
- 日报中需要实时数据的指标（如群成员数）应直接调Telegram API，不依赖数据库缓存。
- 入群检测/禁言规则必须走config.json配置（AUTO_MUTE_NAMES），不硬编码。

### v4.5.27 | 2026-05-01 | 日报数据全0修复

| # | 严重度 | 问题 | 原因 | 修复方案 | 文件 |
|---|--------|------|------|----------|------|
| 1 | 🔴严重 | 日报浏览量永远为0 | _job_channel_views用forward_message到私聊获取views，但私聊消息没有views属性，msg_info.views为None，None>0抛TypeError被静默捕获 | 改用getattr(msg_info,'views',None)安全获取，None时跳过；加rm.locked('bot')锁；消息不存在时标记-1避免重复探测 | modules/auto_tasks.py |
| 2 | 🔴严重 | Bot主动消息不入channel_tracking表 | _send_and_track只做了_schedule_auto_delete，没调用rm.db.track_channel_message()，导致问候/新闻/塔罗等主动消息全部不追踪 | _send_and_track发送成功后，对群聊消息(chat_id<0)调用rm.db.track_channel_message() | modules/auto_tasks.py |
| 3 | 🟡中等 | 日报指标单一，入群/离群为0时整份报告无价值 | 只展示入群/离群/浏览量3个指标，小群可能全为0 | 新增活跃用户数/Bot消息数/用户回复数/互动率/群成员数5个指标，从users/reply_tracking/group_stats表查询 | modules/auto_tasks.py |
| 4 | 🟡中等 | database.py缺少日报所需的按日查询方法 | 只有get_group_stats_by_date和get_channel_stats_summary | 新增get_daily_active_users/get_daily_bot_messages/get_daily_replies/get_group_total_members_latest 4个方法 | core/database.py |

**新增永久纪律**：
- Bot主动发送的群消息必须调用track_channel_message入库，否则日报/浏览量统计永远为0。
- Telegram私聊消息没有views属性，获取频道消息浏览量时必须用getattr安全判断None。
- 日报必须包含"即使当天无入群离群也有值"的指标（如活跃用户数、Bot消息数），避免全0无价值。

### v4.5.25 | 2026-05-01 | S-AT-01 fallback线程泄漏彻底修复

| # | 严重度 | 问题 | 原因 | 修复方案 | 文件 |
|---|--------|------|------|----------|------|
| S-AT-01 | 🔴严重 | fallback路径创建24h长休眠Timer | threading.Timer即使daemon=True仍占用线程资源 | 移除Timer，APScheduler不可用时直接跳过定时删除，依赖孤儿清理机制处理 | modules/auto_tasks.py |

**失败路径避让**：v4.5.25后，APScheduler不可用环境下的定时删除功能将被跳过，消息删除依赖`_job_burn_orphan`每10分钟清理孤儿消息（30分钟未送达即删除）。

---

### v4.5.24 | 2026-05-01 | 板块C功能模块层二次审查7项修复

| # | 严重度 | 问题 | 原因 | 修复方案 | 文件 |
|---|--------|------|------|----------|------|
| S-AT-01 | 🔴严重 | fallback路径仍创建24h休眠线程 | APScheduler路径已修但fallback仍用time.sleep | 改用threading.Timer替代Thread+time.sleep，Timer不占线程栈 | modules/auto_tasks.py |
| S-AT-03 | 🔴严重 | _job_burn_orphan中4处bot API调用未加锁 | delete_message/forward_message直接调用 | 全部包裹在with rm.locked('bot')中 | modules/auto_tasks.py |
| M-AT-02 | 🟡中等 | Phase2每10分钟探测3条=每天432次转发API | cron minute="*/10"频率过高 | 改为minute="5"每小时一次，每天约72次 | modules/auto_tasks.py |
| M-AT-03 | 🟡中等 | 塔罗缓存跨天残留（无用户触发则不清理） | _get_tarot_cache被动清理依赖用户触发 | _job_tarot_flirt入口主动清空前一天缓存 | modules/auto_tasks.py |
| M-AT-04 | 🟡中等 | _notify_admin_system_failure._cache永不清理过期条目 | 只写入不清理，长期运行内存缓慢增长 | 写入时顺便清理超过10分钟的过期条目 | modules/auto_tasks.py |
| L-AT-01 | 🔵轻微 | 重复导入get_logger | 上轮已修复 | 确认已不存在，关闭 | modules/auto_tasks.py |
| L-AT-02 | 🔵轻微 | _legacy_task_loop串行执行无隔离 | 一个任务异常阻塞后续 | 所有任务加try-except隔离 | modules/auto_tasks.py |

**新增永久纪律**：
- threading.Timer替代Thread+time.sleep实现延迟回调，Timer内部用系统定时器不占线程栈。
- 所有rm.bot.xxx()调用必须包裹在with rm.locked('bot')中，防止并发冲突。
- 共享缓存写入时必须顺便清理过期条目，防止内存缓慢增长。

### v4.5.23 | 2026-05-01 | 板块A主控层7项修复完成（板块F二次审查）

| # | 严重度 | 问题 | 原因 | 修复方案 | 文件 |
|---|--------|------|------|----------|------|
| 1 | 🔴严重 | S-MN-01: 数据库操作竞态条件 | upsert_user+add_points各自独立获取_db_lock，两次操作之间非原子 | database.py新增upsert_user_with_points()原子方法，main.py改用此方法 | core/database.py, main.py |
| 2 | 🟡中等 | M-MN-01: 内存清理依赖消息触发 | _conv_tracker和_radar_cooldown的清理只在收到消息时执行 | auto_tasks.py的_job_ttl_cleanup中增加定时清理调用 | modules/auto_tasks.py |
| 3 | 🟡中等 | M-MN-02: 异常处理重复创建ResourceManager | 3处异常处理各创建新RM实例 | 模块级创建_emergency_rm共享实例，3处复用 | main.py |
| 4 | 🟡中等 | M-MN-03: 私聊转发Markdown链接不渲染 | send_message未指定parse_mode，[uname](tg://user?id=uid)不渲染 | 改用parse_mode="HTML"+`<a href>`标签+HTML实体转义（防XSS） | main.py |
| 5 | 🟡中等 | M-MN-04: 连续对话超时保护形同虚设 | 5秒超时检查在AI调用完成后才执行 | 改用concurrent.futures.ThreadPoolExecutor+timeout=5真正中断 | main.py |
| 6 | 🟢轻微 | L-MN-01: .env解析不支持多行值 | 手动解析不处理KEY="value\nnewline"格式 | 优先使用python-dotenv库，fallback保留原手动解析 | main.py |

**新增永久纪律**：
- 数据库的upsert+积分更新必须用原子方法（单次锁内完成），禁止分开调用upsert_user+add_points。
- AI调用的超时保护必须用concurrent.futures真超时，禁止用"完成后检查耗时"的伪超时。
- 内存字典清理不能只依赖消息触发，必须有定时任务兜底。
- Telegram消息中用户输入必须HTML转义后再插入，禁止直接拼接。

### v4.5.22 | 2026-05-01 | 板块A主控层5项安全修复（板块F审查）

| # | 严重度 | 问题 | 原因 | 修复方案 | 文件 |
|---|--------|------|------|----------|------|
| 1 | 🔴严重 | S-MN-01: 数据库操作竞态条件 | upsert_user+add_points各自独立获取_db_lock，两次操作之间非原子，同一用户两条消息被不同线程同时处理时积分可能计算错误 | database.py新增upsert_user_with_points()方法，将upsert+add_points合并到一次锁内执行；main.py改用此原子方法 | core/database.py, main.py |
| 2 | 🔴严重 | S-MN-02: 连续对话超时保护形同虚设 | 5秒超时检查在AI调用完成后才执行（time.time()-_append_start<5），只能决定是否使用结果，无法真正中断AI调用 | 改用concurrent.futures.ThreadPoolExecutor+timeout=5真正中断追加AI调用，超时直接跳过 | main.py |
| 3 | 🟡中等 | M-MN-01: 内存清理依赖消息触发 | _conv_tracker和_radar_cooldown的清理只在收到消息时执行，深夜无消息时过期条目不清理 | 在auto_tasks.py的_job_ttl_cleanup中增加对_cleanup_conv_tracker和_cleanup_radar_cooldown的定时调用 | modules/auto_tasks.py |
| 4 | 🟡中等 | M-MN-02: 异常处理重复创建ResourceManager | master_handler/_dispatch/AI故障3处异常处理各创建新RM实例，每次异常都new一个 | 模块级创建_emergency_rm共享实例，3处异常处理复用 | main.py |
| 5 | 🟢轻微 | L-MN-01: .env解析不支持多行值 | 手动解析不处理KEY="value\nnewline"格式 | 优先使用python-dotenv库（项目其他脚本已依赖），fallback保留原手动解析 | main.py |

**新增永久纪律**：
- 数据库的upsert+积分更新必须用原子方法（单次锁内完成），禁止分开调用upsert_user+add_points。
- AI调用的超时保护必须用concurrent.futures真超时，禁止用"完成后检查耗时"的伪超时。
- 内存字典清理不能只依赖消息触发，必须有定时任务兜底。

### v4.5.20 | 2026-05-01 | 板块F审查AI引擎7项修复

| # | 严重度 | 问题 | 原因 | 修复方案 | 文件 |
|---|--------|------|------|----------|------|
| 1 | 🔴严重 | S-AI-01: API密钥日志泄露 | Authorization头写入请求头，异常堆栈可能暴露密钥 | 1.新增_ApiKeyRedacter日志过滤器自动脱敏 2.__init__中_register_api_key_for_redaction()注册密钥 3.异常日志只记录type(e).__name__ | core/ai_engine.py |
| 2 | 🔴严重 | S-AI-02: 响应时间字典无限增长 | _response_times/_slow_models按模型名存储，过期模型换名后旧记录永不清理 | 新增_cleanup_stale_response_data()，清理>1小时未访问的慢速标记+不在任何池中的响应记录，_record_response_time中>20条时触发 | core/ai_engine.py |
| 3 | 🟡中等 | M-AI-01: _build_persona方法过长 | 节日人格+模式叠加+新闻注入全挤一个方法(~90行) | 拆分为_get_festival_persona()+_get_mode_persona()，硬编码模板提升为_DEFAULT_PROMPT_TEMPLATES类属性，_build_persona精简为~8行 | core/ai_engine.py |
| 4 | 🟡中等 | M-AI-02: 新闻获取无连接池复用 | 每次fetch_real_news()创建7个线程+7个TCP连接 | 新增_news_session_local(threading.local)+_get_news_session()，线程级Session复用，7个_fetch_*函数改用_get_news_session().get() | core/ai_engine.py |
| 5 | 🟡中等 | M-AI-03: 重试最多80秒阻塞 | 10次重试×8秒退避=最坏80秒，对Telegram Bot响应太长 | max_attempts从10降为5 | core/ai_engine.py |
| 6 | 🟢轻微 | L-AI-01: mode映射缺失时无告警 | 新增mode忘记加映射默认走llm_standard，无warning | _get_tier_for_mode中增加warning日志 | core/ai_engine.py |
| 7 | 🟢轻微 | L-AI-02: TTS模型配置字段名不一致 | TTS用model/key字段，其他池用name+全局API_KEY | model_name优先用name字段(回退model)，api_key优先用全局API_KEY(回退key) | core/ai_engine.py |

### v4.5.21 | 2026-05-01 | Dashboard二次审查4项修复（板块F复核）

| # | 严重度 | 问题 | 原因 | 修复方案 | 文件 |
|---|--------|------|------|----------|------|
| 1 | 严重 | S-DH-04: 用户搜索SQL中引用了未定义变量 `{where}` | 上次修复S-DH-01时把变量名从 `where` 改为 `where_clause`，但漏改了2行SQL中的引用，导致搜索功能崩溃 | `{where}` → `{where_clause}` | dashboard/app.py |
| 2 | 严重 | S-DH-05: forbidden_keys子串匹配过宽，`keyword_triggers` 被误拦 | `'key' in 'keyword_triggers'` 为True，导致正常配置项无法修改 | 改为精确匹配：`forbidden_exact` 集合 + `key_parts & forbidden_words` 交集检查 | dashboard/app.py |
| 3 | 中等 | M-DH-01: 速率限制过期记录只在超上限时清理 | 低流量时过期记录堆积不释放内存 | 改为每次调用都先清理过期记录，再检查上限 | dashboard/app.py |
| 4 | 中等 | M-DH-06: VPS状态每次请求都SSH连接 | 概览页每30秒刷新一次，每次都SSH连接VPS执行命令 | 添加 `_vps_cache` 缓存，TTL=300秒（5分钟） | dashboard/app.py |

### v4.5.19 | 2026-05-01 | Dashboard安全漏洞7项修复（板块F审查）

| # | 严重度 | 问题 | 原因 | 修复方案 | 文件 |
|---|--------|------|------|----------|------|
| 1 | 🔴严重 | S-DH-01: SQL注入风险 | ORDER BY用f-string拼接sort/order，违反避让表X-02 | 改用order_by_map白名单映射，sort+order组合映射为完整ORDER BY子句 | dashboard/app.py |
| 2 | 🔴严重 | S-DH-02: XSS漏洞 | 前端JS中${u.name}/${l.content}等直接插入HTML，用户名含script标签可执行恶意代码 | 新增escHtml()函数，对所有用户输入转义后再插入DOM | dashboard/app.py |
| 3 | 🔴严重 | S-DH-03: 登录安全可绕过 | _login_fails存在Flask app对象上，多worker部署时计数器不共享，重启后清零 | 用SQLite持久化登录失败计数（新建login_failures表），_ensure_login_failures_table()懒初始化 | dashboard/app.py |
| 4 | 🟡中等 | M-DH-01: 速率限制字典内存泄漏 | _dashboard_rate_limits以IP为key，过期记录永不清理 | _check_rate_limit中每次调用先清理过期记录 | dashboard/app.py |
| 5 | 🟡中等 | M-DH-02: 数据库连接未统一管理 | get_db()每次创建新连接，部分异常路径未关闭连接 | 改用Flask g对象+teardown_appcontext管理连接生命周期，移除所有手动conn.close() | dashboard/app.py |
| 6 | 🟡中等 | M-DH-03: 自然语言配置返回敏感字段 | api_config_natural返回完整cfg字典，TOKEN/API_KEY等未过滤 | 应用与api_config相同的敏感字段过滤（_sensitive_keys白名单） | dashboard/app.py |
| 7 | 🟢轻微 | L-DH-01: SSH AutoAddPolicy中间人攻击风险 | paramiko.AutoAddPolicy()自动接受任何SSH主机密钥 | 改用WarningPolicy()，新主机连接时警告，密钥变更时拒绝（检测MITM） | dashboard/app.py |

**新增永久纪律**：
- Dashboard前端所有用户输入必须经过escHtml()转义后才能插入DOM，禁止直接拼接innerHTML。
- SQL的ORDER BY子句禁止用f-string拼接用户输入，必须用白名单映射为完整子句。
- 登录失败计数必须持久化到数据库，不能只存内存（多worker/重启会丢失）。
- 数据库连接统一用Flask g对象管理，禁止手动new+close，teardown_appcontext自动回收。

### v4.5.18 | 2026-05-01 | auto_tasks线程泄漏修复 + 新闻缓存竞态 + 重试线程APScheduler化

| # | 问题 | 原因 | 修复方案 | 文件 |
|---|------|------|----------|------|
| S-AT-01 | 每条定时消息创建24h休眠线程，每天10-15条×24h=240+线程常驻，约2-3GB内存泄漏 | _schedule_auto_delete用time.sleep(86400)的daemon线程实现延迟删除 | 改用APScheduler的scheduler.add_job(trigger='date', run_date=...)调度延迟删除，无APScheduler时才回退到线程 | modules/auto_tasks.py |
| S-AT-02 | _news_pushed_today集合跨日清空依赖函数属性last_day，竞态时清空晚于新闻任务触发导致重复推送 | 清空逻辑无锁保护，多线程可能同时读写 | 新增_news_cache_lock，_clear_news_cache_if_new_day/_prepare_news_lines/_remember_news_lines全部加锁 | modules/auto_tasks.py |
| M-AT-01 | _retry_task创建5分钟休眠线程，APScheduler又触发同一任务时两个线程同时执行 | 重试用time.sleep(5min)的线程，无法取消 | 改用APScheduler的scheduler.add_job(trigger='date')调度重试，replace_existing=True防止重复 | modules/auto_tasks.py |
| M-AT-02 | Phase2每10分钟8次转发=每天1152次API调用，持续高频可能触发429 | limit=8太大 | 将limit从8降为3，每天约432次，降低62% | modules/auto_tasks.py |
| M-AT-03 | 塔罗缓存按日期key过滤保留，如果某天无用户触发塔罗，旧缓存永远不清理 | 过滤条件date_key in k只保留当天，但跨天后旧key仍残留 | 直接清空_tarot_daily_cache = {}，新一天不需要保留旧缓存 | modules/auto_tasks.py |
| L-AT-01 | _job_channel_views函数内重复from core.logging_util import get_logger | 文件顶部已导入 | 删除函数内的重复导入 | modules/auto_tasks.py |
| L-AT-02 | _legacy_task_loop中_job_burn_orphan卡住会阻塞后续所有任务 | 串行执行无超时保护 | 为_job_burn_orphan加try-except隔离 | modules/auto_tasks.py |

**新增永久纪律**：
- 定时消息延迟删除必须用APScheduler调度，禁止创建长时间休眠的daemon线程（线程泄漏风险）。
- 共享内存缓存（如_news_pushed_today）的读写必须加锁保护，防止跨日竞态。
- 重试任务优先用APScheduler的date trigger调度，线程只作为无APScheduler时的回退。

### v4.5.17 | 2026-05-01 | 部署工具安全修复 + Dashboard安全审计 + 转化漏斗/群组频道渲染

| # | 问题 | 原因 | 修复方案 | 文件 |
|---|------|------|----------|------|
| 1 | M-DU-01: `sync_env_api_key()` 用 sed 命令拼接 API Key，存在 shell 注入风险 | `correct_api_key` 若含 `$`、反引号等 shell 特殊字符，sed 命令可能被注入 | 改用 SFTP 读取 .env → Python 逐行替换 → SFTP 写回，彻底消除 shell 注入面 | core/deploy_utils.py |
| 2 | L-DU-01: `safe_upload_config()` 下载 VPS 配置失败时静默忽略 | `except Exception: pass` 导致下载失败无任何提示，可能用空配置覆盖 VPS 有效配置 | 拆分异常类型（FileNotFoundError/JSONDecodeError/其他），每种打印不同 warning；合并前检查 vps_cfg 是否为空 | core/deploy_utils.py |
| 3 | `doLogout()` 调用 `/api/logout` 时缺少 `X-Requested-With` 头 | 被 `before_request` 的CSRF校验拦截，返回403 | 补全 `headers: { 'X-Requested-With': 'XMLHttpRequest' }` | dashboard/app.py |
| 4 | 登录频率限制5次后永久锁死，10分钟后仍无法登录 | `_login_fails` 只记计数不记时间，无过期清除机制 | 改为 `{"count": N, "first_fail_at": timestamp}` 结构，超600秒自动重置 | dashboard/app.py |
| 5 | 后端返回 `conversion_funnel`/`group_stats`/`channel_stats` 数据但前端概览页完全不渲染 | 前端只有4个统计卡片+2个图表，漏斗/群组/频道数据全部丢弃 | 新增转化漏斗横向柱状图 + 群组频道统计卡片，概览页从2行扩展为3行 | dashboard/app.py |

**新增永久纪律**：
- 部署工具中涉及 VPS 文件修改的操作，一律使用 SFTP 读写，禁止用 shell 命令拼接用户可控内容。

### v4.5.16 | 2026-05-01 | Dashboard安全修复 + 图表真实数据 + 死代码清理

| # | 问题 | 原因 | 修复方案 | 文件 |
|---|------|------|----------|------|
| 1 | 登录密码用 `==` 比较，存在时序攻击风险 | 病历X-13已记录但未修复 | 改用 `hmac.compare_digest(pw, admin_pw)` | dashboard/app.py |
| 2 | 数据看板7天趋势图和24小时柱状图显示假数据 | `renderCharts()` 里写死了固定数组，没走API | 新增 `_chartData` 全局变量存储API返回值，图表改为从 `_chartData.online_trend` 和 `_chartData.hourly_dist` 读取 | dashboard/app.py |
| 3 | 前端有两个 `applyNlConfig()` 函数，旧版49行死代码永远不会执行 | 旧版正则前端硬猜在前，新版调后端API在后，后者覆盖前者 | 删除旧版正则硬猜函数，只保留调 `/api/config/natural` 的版本 | dashboard/app.py |
| 4 | 项目快照数据库表数量错误（13→应为14） | `user_levels` 表存在于 `database.py` 但快照漏列 | 补入 `user_levels` 表，总数改为14 | project_snapshot.md |

### 2026-04-30 | systemd 全权接管与多项目同机边界（必须遵守）

- **进程管理红线**：主项目 `mory_assistant` 只允许 systemd 守护，启停只用 `sudo systemctl restart mory-assistant`（状态：`systemctl status mory-assistant`）。
- **禁止**：`pm2`、`bash start.sh start`、手动启动 `python main.py`。否则非常容易多开导致 Telegram `409 Conflict`。
- **后台任务防冲突**：`modules/auto_tasks.py` 的 `_start_with_apscheduler` 内有 `BOT_ROLE=os.getenv("BOT_ROLE","MAIN")` 判断；线上 `.env` 已配置 `BOT_ROLE=MAIN`，后续维护请保留此判断。
- **同源数据库配合**：同机的 `mory_media_assistant` 以轻量脚本读取主项目 `mory.db` 的 `promotions` 表做定时广播；主项目侧避免长事务/长时间锁库，防止影响宣发号读取。

### 2026-04-29 | VPS SSH 密码轮换同步

- 用户已在腾讯云控制台轮换 SSH 密码。
- 已用新密码验证 `ubuntu@43.159.168.175:22` 登录成功。
- 已同步本地 `.env` 与服务器 `/home/ubuntu/mory_assistant/.env` 的 `VPS_SSH_PASS`。
- 已重启 `mory-assistant.service` 与 `mory-dashboard.service`，两者均为 active。
- 密码明文不写入日志、更新日志或说明文档。

### 2026-04-29 | Telegram Token 与多项目服务器边界

- 用户确认本项目只保留 Bot ID `8009972336` 对应的 `@MoryMateBot` token。
- 已把本地 `.env`、`config.json` 与服务器 `/home/ubuntu/mory_assistant/.env`、`/home/ubuntu/mory_assistant/config.json` 统一为同一枚 token。
- 验证结果：本项目 active 配置文件中 token 数量均为 1，且没有其他 Telegram token。
- 重要边界：服务器上可能同时运行其他 AI/其他项目。以后排查本项目时，只能默认操作 `/home/ubuntu/mory_assistant` 目录和明确属于本项目的 systemd 服务；不能仅凭 `python main.py`、端口、进程名、409 日志就杀进程或改别的项目。
- 如需处理跨项目冲突，必须先向用户确认目标进程的完整路径、服务名、用途，再操作。

### v4.5.15 | 2026-04-29 | 自然语言配置接通与投喂配置回流

| # | 问题 | 原因 | 修复方案 | 文件 |
|---|------|------|----------|------|
| 1 | 项目里明明有 `natural_cmd.py`，但 Telegram 主流程没有真正接入 | 自然语言配置模块存在，但 `main.py` 没调用，导致管理员在 TG 里说自然语言配置时不会生效 | 在消息分发 P6 后接入 `handle_natural_admin`，管理员可直接在 Telegram 里改配置 | main.py, modules/natural_cmd.py |
| 2 | 网页端“自然语言配置”只是前端正则硬猜，复杂指令不可靠 | Dashboard 没走后端统一解析器，页面上看起来有入口，实际能力弱且和 TG 不一致 | 新增 `/api/config/natural`，网页端改为复用同一套自然语言配置解析逻辑 | dashboard/app.py, modules/natural_cmd.py |
| 3 | 特定词自动回复虽然加了配置区，但不方便直接口头维护 | 旧自然语言模块不认识 `SPECIAL_AUTO_REPLIES` 这种复杂结构 | 新增“查看/新增/修改/开启/关闭/删除特定回复”指令解析 | modules/natural_cmd.py |
| 4 | 用户在 Telegram/网页端投喂过的内容，后续部署可能又被本地旧配置盖掉 | 以前部署前只拉备份，不会把线上运行时配置回流到本地配置里 | 部署前先读取 VPS 当前配置，把投喂型运行字段先拉回本地，再继续同步 | core/deploy_utils.py, deploy_vps.py |

**新增永久纪律**：
- 对外宣称支持“自然语言配置”时，Telegram、网页端、部署同步三层要走同一套逻辑，不能只做表面入口。
- 线上人工投喂过的业务内容，部署前必须先回流到本地，否则视为高风险同步。

### v4.5.14 | 2026-04-28 | 自动回复配置部署同步修复

| # | 问题 | 原因 | 修复方案 | 文件 |
|---|------|------|----------|------|
| 1 | 本地新增 `SPECIAL_AUTO_REPLIES` 后服务器没有同步生效 | 部署安全合并白名单 `MERGE_FIELDS` 漏掉了这个新配置字段，上传时被保留成旧值 | 在部署合并白名单里补入 `SPECIAL_AUTO_REPLIES`，确保安全合并时把业务配置同步到服务器 | core/deploy_utils.py |
| 2 | 看起来像“代码写好了但线上没反应” | 功能代码已命中，但 VPS `config.json` 被安全合并拦掉，导致远端规则数组为空 | 重新部署并增加远端规则数量验证，确认线上实际读取到了4条默认规则 | core/deploy_utils.py, config.json, deploy_vps.py |

**新增永久纪律**：
- 以后新增 `config.json` 业务字段时，必须同步检查 `core/deploy_utils.py` 的 `MERGE_FIELDS`，否则本地配置可能不会下发到VPS。
- 所有“本地可用、线上失效”的配置类改动，部署后都要做一次远端实际读取验证，不能只看重启成功。

### v4.5.13 | 2026-04-28 | 称呼联动与特定词自动回复

| # | 问题 | 原因 | 修复方案 | 文件 |
|---|------|------|----------|------|
| 1 | 小助理只会单一叫“老板” | 系统人设里没有明确说明 `老板 / boss / Mory` 是同一人且允许自然切换 | 在 SYSTEM_PROMPT 中增加称呼联动规则 | config.json |
| 2 | 特定词自动回复只能依赖数据库关键词表 | 旧关键词系统只支持单关键词 + 固定文本/AI/动作，配置门槛高 | 新增 `SPECIAL_AUTO_REPLIES` 配置区，支持关键词数组和启停 | config.json, modules/keyword_trigger.py |
| 3 | 固定模板回复太死板 | 命中关键词后只会直接发模板，不够像真人 | 命中后先取模板，再交给 AI 润色成自然聊天回复 | modules/keyword_trigger.py |
| 4 | 价格/开通/完整版/联系类问题没有默认高质量引导 | 只能等 Function Calling 或人工加规则，缺少稳定入口 | 预置四类默认规则：价格咨询、开通咨询、完整版咨询、联系Mory | config.json |

**新增永久纪律**：
- 业务里提到核心人物时，`老板 / boss / Mory` 必须视作同一人，允许按语境自然切换。
- 特定词自动回复优先走“配置模板 + AI润色”，不要每次都硬编码到主分发器里。
- 转化型触发词要先给用户一个顺手的接话点，再隐晦往更深内容或私下联系引，不要一上来就直推。

### v4.5.12 | 2026-04-28 | 问候提示词随机性与隐晦转化强化

| # | 问题 | 原因 | 修复方案 | 文件 |
|---|------|------|----------|------|
| 1 | 早午晚安虽然自然了一些，但随机度还不够高 | 提示词只限制了场景和语气，没有强约束“句式和节奏必须变化” | 在三段问候提示词里加入“每次必须明显不同”的强随机要求 | config.json |
| 2 | 结尾没有稳定承担高情商转化功能 | 之前只留了泛化的“期待感”，没有明确约束隐晦引导方向 | 增加三类随机牵引：联系你、看更完整内容、靠近更深圈层 | config.json |
| 3 | 转化可能过直白或过营销 | 没有明确禁止词和允许的暗示边界 | 明确禁止直白营销词，同时允许隐晦暗示完整版、至臻精选、至臻全享、私聊和偏爱圈层 | config.json |

**新增永久纪律**：
- 问候文案的转化必须是“隐晦牵引”而不是“直白号召”，让人愿意主动靠近，而不是一眼看出在卖。
- 随机性不能只靠 seed，提示词本身要强制变化场景、句式、情绪和落点。

### v4.5.11 | 2026-04-28 | 新闻播报与问候文案整改

| # | 问题 | 原因 | 修复方案 | 文件 |
|---|------|------|----------|------|
| 1 | 早间和午间新闻被连续发两次 | `news_*` 和 `trendradar_*` 被分别排进定时器，两个时段都各发一遍 | 停用独立 TrendRadar 播报任务，只保留早中晚单条新闻主流程 | modules/auto_tasks.py |
| 2 | TrendRadar 标题被直接原样发群里 | 旧实现把标题列表直接拼消息，不走 AI 整理 | TrendRadar 改成“优先新闻源”，仍统一走 AI 播报模板 | modules/auto_tasks.py |
| 3 | 新闻去重写得太早，发送失败也会被记成“已播过” | 获取标题时就把标题写入共享缓存 | 改为发送成功后再写入当天去重缓存 | modules/auto_tasks.py, core/trendradar_news.py |
| 4 | 早安午安晚安文案过于广告化 | 提示词里硬塞 VIP、名额、手慢无 等直接转化语 | 改成自然生活场景 + 真诚问候 + 轻微期待感，不再硬广 | config.json |
| 5 | 新闻播报像机器摘抄标题 | 模板要求过短、主持腔重、还有固定收尾句 | 改成 5 条自然转述 + 1 句真人收尾，禁用固定主持腔 | config.json |

**新增永久纪律**：
- 同一时段只能保留一条新闻播报主任务，新闻源切换只能发生在任务内部，不能靠再加一个定时任务补发。
- 新闻标题去重必须在“发送成功后”落库或入缓存，不能在抓取阶段就提前占坑。
- 问候文案允许轻微期待感，但不能写成直白广告词或硬转化口号。

### v4.5.10 | 2026-04-28 | 全模态优先用于文本聊天

| # | 问题 | 原因 | 修复方案 | 文件 |
|---|------|------|----------|------|
| 1 | 文本聊天没有优先消耗全模态模型 | 三层路由只看llm_light/standard/premium，omni池不会进入主聊天候选 | 三层路由每档前置omni模型，omni不可用后再自动退回对应llm层级 | core/ai_engine.py |
| 2 | `current_model`改成只看llm后不符合业务策略 | 全模态和大模型文本能力有重合，免费时效内应优先使用 | `current_model`恢复为聊天组合池指针：omni优先，其次llm | core/ai_engine.py |
| 3 | 聊天池指针和熔断日志可能不一致 | 原默认切换池名是llm，组合聊天池没有独立指针 | 新增`chat`逻辑池，切换时同步`CURRENT_MODEL_INDEX`，熔断仍按本轮实际模型检查 | core/ai_engine.py |
| 4 | 服务器启动横幅仍显示旧版本 | `start.sh`里写死`v4.5.8`，实际代码已是新版本但显示误导 | 启动时自动读取`version.py`里的`VERSION`显示 | start.sh |

**新增永久纪律**：
- 只要全模态模型确认可走文本接口，主聊天要优先消耗全模态额度；失败、限流、配额异常时再自动退回普通大模型。
- “当前模型”指的是当前聊天实际候选模型，不等于单独llm池第几个模型。
- 启动脚本不得写死版本号，必须从统一版本文件读取，避免线上看起来像没同步。

### v4.5.9 | 2026-04-28 | 模型切换智能化加固 + 独立路由安全修复

| # | 问题 | 原因 | 修复方案 | 文件 |
|---|------|------|----------|------|
| 1 | 主业务熔断检查可能看错模型 | `ask()`先用旧`current_model`查熔断，三层路由后才确定实际模型 | 熔断检查移到每轮实际模型确定之后 | core/ai_engine.py |
| 2 | 当前模型可能显示到omni池 | `current_model`基于llm+omni合并池，和主聊天llm池指针不一致 | `current_model`优先读取llm池，并同步`_pool_indices["llm"]` | core/ai_engine.py |
| 3 | 独立路由配置硬编码API密钥 | `router_config.json`直接保存密钥 | 改为`${ENV:DASHSCOPE_KEY}`，`ConfigManager`自动读取`.env`并解析占位符 | universal_ai_router/config/router_config.json, config_manager.py |
| 4 | 独立账号失败一次就不可用 | `mark_account_failed()`直接把账号设为ERROR，阈值形同虚设 | 普通错误累计到阈值才禁用，429只冷却5分钟，402才标记配额耗尽 | universal_ai_router/core/account_manager.py |
| 5 | 失败响应没有状态码 | 账号管理器拿不到HTTP状态码，无法区分限流/配额/普通错误 | `UnifiedResponse.raw_response`写入`status_code`，调用层传给账号管理器 | api_adapter.py, uni_ai.py |
| 6 | `router_config.json`无法同步到VPS | 上传工具误把所有`*config.json`都当根配置跳过 | 只跳过根目录`config.json`，允许同步`router_config.json` | core/deploy_utils.py |

**新增永久纪律**：
- 独立路由配置不得保存明文API密钥，只能使用`${ENV:变量名}`占位符。
- 模型切换判断必须基于“本轮实际调用模型”，不能基于旧指针。
- 账号失败要区分普通错误、限流、配额耗尽，不能一次失败就永久踢出。

### v4.5.8 | 2026-04-28 | 本地自检 + Windows脚本安全修复 + VPS只读巡检

| # | 问题 | 原因 | 修复方案 | 文件 |
|---|------|------|----------|------|
| 1 | BAT脚本含中文，CMD环境下可能乱码闪退 | BAT文件直接输出中文和符号 | `deploy.bat`、`一键部署.bat`、`start_dashboard.bat`改为全英文 | deploy.bat, 一键部署.bat, start_dashboard.bat |
| 2 | 一键部署脚本使用`python -c` | CMD容易拆行或转义失败，违反项目纪律 | 新增`check_vps_local.py`，BAT只调用独立Python文件 | 一键部署.bat, check_vps_local.py |
| 3 | Dashboard启动脚本硬编码密钥和密码 | 固定密码有安全风险 | 新增`start_dashboard.py`，从`.env`读取，缺失时生成本次临时密钥/密码 | start_dashboard.py, start_dashboard.bat |
| 4 | `sync_vps.py`导入`deploy_vps.py`可能触发部署副作用 | `deploy_vps.py`是顶层脚本，import会执行部署流程 | 改为子进程执行`deploy_vps.py`，不再通过import触发 | sync_vps.py |
| 5 | 多处裸`except`会吞掉退出信号 | 捕获范围过大，不利于安全停机 | 收窄为`except Exception` | main.py, core/database.py, modules/auto_tasks.py, dashboard/app.py, core/deploy_utils.py, deploy_vps.py |
| 6 | 本地与VPS版本不一致 | VPS只读巡检显示线上仍为v4.5.3，本地已更新 | 已记录差异；本次未自动上传重启，避免未确认改动线上服务 | check_server_status.py |
| 7 | 新手需要中文提示，但BAT不能直接写中文 | CMD编码不稳定，中文BAT在部分机器会乱码或闪退 | 新增`windows_helper.py`承载中文提示，BAT保持纯英文启动壳 | windows_helper.py, deploy.bat |
| 8 | 线上版本长期不同步 | `deploy_vps.py`只上传3个文件，`main.py/version.py/config.json`等未全量同步 | 改为部署前拉回备份，停止旧进程后全量上传运行文件 | deploy_vps.py |
| 9 | 新配置会被旧进程覆盖 | 旧Bot停止时会把内存里的旧`config.json`写回磁盘 | 部署顺序改为：先备份 → 停旧进程 → 上传配置/代码 → 启动 | deploy_vps.py |
| 10 | 服务器缺Dashboard/部署工具依赖 | `start.sh install`只装3个包，缺Flask/Paramiko | `requirements.txt`补版本上限，`start.sh`按requirements安装 | requirements.txt, start.sh |
| 11 | 删除过期模型后启动失败 | 数据库动态状态里的`CURRENT_MODEL_INDEX=6`，模型池缩短后索引越界 | `main.py`启动时自动夹紧索引，服务器DB同步改为0 | main.py |
| 12 | 部署校验误判成功 | 校验只识别英文`not running`，没识别中文“未运行” | `verify_deployment()`增加中文未运行判断 | core/deploy_utils.py |

**新增永久纪律**：
- 兼容入口脚本不要通过`import`执行有副作用的部署脚本，统一用子进程执行。
- Dashboard本地启动脚本不得写死固定密码，缺失时只生成本次临时密码或要求`.env`配置。
- BAT脚本继续保持全英文，中文提示放到Python脚本里。
- 新手可见中文不等于BAT里写中文；正确做法是BAT只负责启动Python，中文交互放在`.py`文件里。
- VPS部署必须先拉回`mory.db`、`mory.log`、`config.json`、`.env`等关键文件到本地`backups/server_pull_*`。
- 上传新配置前必须先停止旧Bot，否则旧进程退出时会把旧配置保存回去，覆盖新配置。
- 部署不能只传局部文件，必须同步完整运行文件，否则会出现本地版本和线上版本长期错位。
- 模型池增删后必须校正`CURRENT_MODEL_INDEX`，索引越界必须自动兜底。

### v4.5.6 | 2026-04-27 | 全局故障通知升级 + 定时消息24h自动删除 + AI教指令 + 话术随机化

| # | 问题 | 原因 | 修复方案 | 文件 |
|---|------|------|----------|------|
| 1 | 全局故障通知不够全面 | 主分发器异常只记录日志，模块异常无通知 | master捕获任何未捕获异常都通知管理员 | main.py (master_handler/_dispatch) |
| 2 | 定时消息24小时无人理不自动删除 | 发送后没有自动清理机制 | 新增_schedule_auto_delete()，24小时后daemon线程删除 | modules/auto_tasks.py |
| 3 | 用户问指令时AI只甩帮助菜单 | SYSTEM_PROMPT缺少指令教学法则 | 新增【指令教学法则】，用聊天方式教 | config.json |
| 4 | 新闻/问候总结话术固定不变 | 固定问候语，每天一样 | 支持问候语列表，每次随机选，早/午/晚各3个备选 | modules/auto_tasks.py |

### v4.5.5 | 2026-04-27 | 全局故障通知 + 指令识别修复 + 回复风格优化

| # | 问题 | 原因 | 修复方案 | 文件 |
|---|------|------|----------|------|
| 1 | 只有新闻故障才通知 | API/数据库/Bot故障无通知 | 新增_notify_admin_system_failure()，5分钟内同类型不重复 | modules/auto_tasks.py, main.py |
| 2 | 用户说"指令"不触发帮助菜单 | 关键词列表缺少"指令"单独关键词 | help_keywords新增"指令"/"帮助文档"/"使用帮助" | modules/natural_cmd.py |
| 3 | 用户反馈问题时回复太生硬 | SYSTEM_PROMPT缺少问题处理法则 | 新增【问题处理法则】，先共情再解决 | config.json |

### v4.5.4 | 2026-04-27 | 晚间新闻零token + 7新闻源 + 故障通知

| # | 问题 | 原因 | 修复方案 | 文件 |
|---|------|------|----------|------|
| 1 | 晚间新闻发送了"鸡汤文"而非新闻 | 新闻源全失败时降级为"今日回顾"，AI生成感悟 | 改用TrendRadar零token方案，全失败时跳过并通知 | modules/auto_tasks.py |
| 2 | 新闻源太少，容易全部失败 | 只有百度/微博/头条3个源 | 新增知乎/抖音/36氪/澎湃，共7源并行 | core/ai_engine.py |
| 3 | 新闻源全故障时没有通知 | 只记录日志 | 新增_notify_admin_news_failure()私聊通知 | modules/auto_tasks.py |

### v4.5.3 | 2026-04-27 | 新闻零token播报 + 早安/问候加长 + 去重修复

| # | 问题 | 原因 | 修复方案 | 文件 |
|---|------|------|----------|------|
| 1 | 新闻太短看不懂 | prompt"简短"和"30-40字"矛盾 | 去掉AI润色，直接发标题，每条≤60字，整体≤280字 | modules/auto_tasks.py |
| 2 | 早安/午安/晚安太短 | prompt只要求50-70字，代码截断180字 | 改为60-100字+AI润色，截断250字 | modules/auto_tasks.py |
| 3 | 早午新闻冲突重复 | TrendRadar和auto_tasks各自有去重缓存 | trendradar_news改为导入auto_tasks的_news_pushed_today共享缓存 | core/trendradar_news.py |
| 4 | 午间新闻没总结 | prompt已有总结要求（15-20字） | 确认无需额外修改 | - |

### v4.5.0-深度扫描 | 2026-04-25 | 深度代码审计18项修复 + 28处版本号同步

#### 致命级（2项）
| # | 问题 | 文件 | 修复方案 |
|---|------|------|----------|
| F-23 | group_stats表缺chat_id列，入群事件必崩 | core/database.py | ALTER TABLE添加列+迁移逻辑 |
| F-24 | _CST变量未定义，check_and_award_badges必崩 | modules/content.py | 添加_CST定义 |

#### 严重级（4项）
| # | 问题 | 文件 | 修复方案 |
|---|------|------|----------|
| S-29 | 等级阈值与content.py不一致 | core/database.py | 统一为500/100/20 |
| S-30 | _job_ttl_cleanup绕过_db_lock直接操作数据库 | modules/auto_tasks.py | 新增cleanup_old_records()方法 |
| S-31 | _job_burn_orphan绕过_db_lock直接读库 | modules/auto_tasks.py | 新增get_tracking_stats()方法 |
| S-32 | analyze_image硬编码DashScope URL | core/ai_engine.py | 从config动态读取BASE_URL |
| S-33 | vision_pool引用修改config字典 | core/ai_engine.py | list()创建副本 |

#### 中等/低危级（12项）
| # | 问题 | 文件 | 修复方案 |
|---|------|------|----------|
| M-60 | 频道统计key不匹配，tracked_count永远为0 | modules/auto_tasks.py | 改为total_posts |
| M-61 | 频道统计时区UTC与北京差8小时 | core/database.py | +8 hours修正 |
| M-62 | 投喂资料KeyError | modules/admin_cmds.py | config.get防None |
| M-63 | 备份时间用本地时间非北京时间 | modules/auto_tasks.py | datetime.now(_CST) |
| M-64 | 备份路径用相对路径 | modules/auto_tasks.py | 改用base_dir绝对路径 |
| M-65 | 查追踪monkey-patch检测过时 | modules/admin_cmds.py | 改为检测_mory_bot_instance |
| M-66 | 晚上时间转换逻辑错误 | modules/natural_cmd.py | 检查原始msg+晚上12点=0点 |
| L-67 | .env文件句柄未关闭 | main.py | with open() |
| L-68 | 条件判断重复 | modules/natural_cmd.py | 去重 |
| L-69 | KeywordTrigger每条消息重新实例化 | main.py | 移到模块级初始化 |
| L-70 | aliases字典循环内重复创建 | modules/natural_cmd.py | 移到循环外 |

**版本号同步**：15个文件28处版本号统一到v4.5.0

### v4.5.0 | 2026-04-25 | 定时任务瘫痪修复 + 隐藏Bug全面修复

#### 致命级（6项）
| # | 问题 | 文件 | 修复方案 |
|---|------|------|----------|
| F-17 | _should_run()执行前标记"已运行"，失败后无法重试 | modules/auto_tasks.py | 拆分为_can_run()+_mark_done()两步式 |
| F-18 | {seed_hint}占位符从未替换 | core/ai_engine.py | 改为replace("{seed_hint}", seed_hint) |
| F-19 | task_log持久化去重完全缺失 | core/database.py | 新建task_log表+3个方法 |
| F-20 | KeywordTrigger引用未定义rm变量 | main.py | 改为传入mory_bot+ai |
| F-21 | 导入不存在的reply_and_track函数 | modules/keyword_trigger.py | 改用mory_bot.reply_and_track() |
| F-22 | mory_bot变量未传入函数 | modules/natural_cmd.py | 7个函数添加mory_bot参数 |

#### 严重/中等/低危级（9项）
| # | 问题 | 文件 | 修复方案 |
|---|------|------|----------|
| S-26 | _retry_task重试被_can_run拦截 | modules/auto_tasks.py | 重试前清除_last_task_run时间戳 |
| S-27 | _legacy_task_loop引用已删除的_should_run | modules/auto_tasks.py | 全部改为_can_run/_mark_done |
| S-28 | 锁超时5秒太短 | core/resource_manager.py | 默认超时改为30秒 |
| M-58 | AI模式用mode="default"不存在 | modules/keyword_trigger.py | 改为mode="normal" |
| M-59 | action模式不追踪阅后即焚 | modules/keyword_trigger.py | 改用mory_bot.reply_and_track |

### v4.4.8 | 2026-04-24 | 阅后即焚孤儿清理修复 + 数据库bug修复

| # | 问题 | 文件 | 修复方案 |
|---|------|------|----------|
| F-16 | 迁移检查代码直接调用self.conn.fetchall()导致AttributeError | core/database.py | 使用cursor对象执行fetchall() |
| S-23 | 阅后即焚孤儿清理频率太低 | modules/auto_tasks.py | 改为每10分钟执行一次，时间窗口缩短为2小时 |
| S-24 | 孤儿清理缺少详细日志追踪 | modules/auto_tasks.py | 添加数据库状态统计、删除结果统计等详细日志 |
| S-25 | ReplySnifferMiddleware未启用 | main.py | 在TeleBot初始化时添加use_class_middlewares=True |

### v4.4.7 | 2026-04-26 | 防重复机制 + 代码审查修复

| # | 问题 | 文件 | 修复方案 |
|---|------|------|----------|
| S-20 | 自动任务可能被重复触发 | modules/auto_tasks.py | 添加_should_run全局防重复机制 |
| S-21 | inc_puzzle_score缺少异常处理 | core/database.py | 添加try-except包裹 |
| S-22 | 购物车挽回失败无重试机制 | modules/auto_tasks.py | 添加日志记录但不需要重试 |

### v4.4.7 | 2026-04-24 | 通义千问模型名称重要发现（universal_ai_router）

| # | 问题 | 修复方案 |
|---|------|----------|
| M-03 | 同样的模型，有日期后缀的可以用，没有的不能用 | 必须使用有日期后缀的完整模型名（如qwen3.5-plus-2026-04-20），不要用简写名 |

### v4.4.6 | 2026-04-26 | Dashboard功能全面恢复 + 安全修复

| # | 问题 | 文件 | 修复方案 |
|---|------|------|----------|
| S-18 | _handle_admin_photo函数中mory_bot未定义 | modules/content.py | 添加mory_bot参数 |
| S-19 | api_stats_users的order参数可SQL注入 | dashboard/app.py | 添加allowed_orders白名单校验 |
| - | 缺少多个API端点和前端功能 | dashboard/app.py | 恢复/api/groups, /api/logs, /api/config等 |

### v4.4.3 | 2026-04-23 | 全面安全审计 + VPS部署链路重建

#### 致命级（3项）
| # | 问题 | 文件 | 修复方案 |
|---|------|------|----------|
| F-16 | ssh_server_check.py硬编码VPS IP和密码明文 | ssh_server_check.py | 改为从core/vps_config.py读取环境变量 |
| F-17 | sync_vps.py名为"同步"但无任何SFTP上传逻辑 | sync_vps.py + 新建deploy_vps.py | 重建完整同步脚本 |
| F-18 | 一键部署bat指向不存在的deploy_final.py | 一键部署.bat | 改为调用deploy_vps.py |

#### 高危/中等/低危级（8项）
| # | 问题 | 文件 | 修复方案 |
|---|------|------|----------|
| S-32 | ai_engine.py第75行/n应为\n，导致SyntaxError崩溃 | core/ai_engine.py | 修复prompt转义字符 |
| S-33 | resource_manager.py locked_multi中db资源报"未知资源" | core/resource_manager.py | locked_multi中跳过db资源 |
| M-74 | .env文件缺少环境变量 | .env | 补充完整环境变量模板 |
| M-75 | ai_engine.py _pending_tasks无线程安全保护 | core/ai_engine.py | 增加_MAX_PENDING=50上限+返回值检查 |
| M-76 | ai_engine.py新闻并发池f.result()无异常捕获 | core/ai_engine.py | 包裹try-except，单源异常不阻塞整体 |

### v4.4.3 | 2026-04-23 | 全面安全审计修复（核心模块）

| # | 问题 | 文件 | 修复方案 |
|---|------|------|----------|
| S-01 | _pending_tasks无限增长内存泄漏 | core/ai_engine.py | 增加_MAX_PENDING=50上限，_enqueue_task返回布尔值 |
| S-02 | 新闻并发f.result()无异常捕获 | core/ai_engine.py | 包裹try-except，单源异常不阻塞整体 |
| S-03 | SemanticCache无线程锁保护 | core/optimizer.py | 所有公开方法加_lock保护 |
| S-04 | SemanticCache无限增长 | core/optimizer.py | put()增加容量检查，超限时LRU淘汰 |
| S-05 | RateLimiter.acquire()无原子性 | core/optimizer.py | 增加_lock保护令牌读写 |
| M-01 | _tarot_daily_cache内存泄漏 | modules/auto_tasks.py | 改用.clear()彻底清空，增加1000条上限 |
| M-02 | _enqueue_task返回值未检查 | core/ai_engine.py | 调用方检查返回值，队列满返回友好提示 |

### v4.4.2 | 2026-04-22 | Legacy Loop定时任务全瘫痪修复

| # | 问题 | 文件 | 修复方案 |
|---|------|------|----------|
| F-13 | Legacy Loop中`if not try_mark`逻辑反转 | modules/auto_tasks.py | 改为`if try_mark` |
| F-14 | task_log表主键设计缺陷 | core/database.py | 改为联合主键(task_key, exec_date) |
| F-15 | 热词从旧字段读取 | modules/admin_cmds.py | 优先读STYLE_APPEND |

### v4.4.1 | 2026-04-22 | 消息重复发送根因修复

| # | 问题 | 修复方案 | 文件 |
|---|------|----------|------|
| 1 | 多进程同时运行导致重复发送 | 新增_acquire_process_lock()进程级单例锁，Windows使用msvcrt.locking，Linux使用fcntl.flock | modules/auto_tasks.py |
| 2 | 去重检查和标记分两次加锁，存在竞争窗口 | 新增try_mark_task_executed()原子操作，一次加锁内完成"检查+标记" | core/database.py, modules/auto_tasks.py |

**覆盖任务**：早安/午安/晚安问候、早/午/晚间新闻、每日报告（7个任务全部改用原子操作）

**特殊处理**：塔罗搭讪30%概率触发，不能用原子操作，保持is+mark分离模式

### v4.4.0 | 2026-04-21 | 终极核查修复（32项）

#### 致命级（3项）
| # | 问题 | 文件 | 修复方案 |
|---|------|------|----------|
| F-08 | fetchall()多线程数据污染 | core/database.py | fetchall()后立即深拷贝或改用fetchone()循环 |
| F-09 | config.json密钥明文存储 | config.json | 清除所有明文密钥，统一改为环境变量读取 |
| F-10 | 连续对话AI调用无超时保护 | core/ai_engine.py | 添加全局30秒超时，超时降级为备用回复 |

#### 高危级（4项）
| # | 问题 | 文件 | 修复方案 |
|---|------|------|----------|
| S-28 | Dashboard前端API路径与后端不匹配 | dashboard/app.py + 前端JS | 逐一核对修正所有API端点地址 |
| S-29 | Dashboard数据库连接异常时路径泄漏 | dashboard/app.py | 统一使用db_conn()上下文管理器 |
| S-30 | Dashboard SSH命令注入风险 | dashboard/app.py | 添加命令白名单校验 |
| S-31 | 备份路径使用相对路径 | core/database.py | 改为os.path.abspath()绝对路径 |

#### 中等级（16项）
| # | 问题 | 文件 | 修复方案 |
|---|------|------|----------|
| M-58 | 裸except吞掉KeyboardInterrupt/SystemExit | 多文件 | 全部替换为except Exception |
| M-59 | SPAM_LIMIT配置键名不一致 | config.json + 多模块 | 统一为SPAM_LIMIT |
| M-60 | 密码校验使用== | dashboard/app.py | 改用hmac.compare_digest() |
| M-61 | 文件句柄泄漏 | 多文件 | 统一改为with open()上下文管理器 |
| M-62 | Dashboard用户列表分页参数未传 | dashboard/app.py + 前端JS | 修复分页逻辑 |
| M-63 | Dashboard日志搜索HTML转义缺失 | dashboard/app.py | 添加html.escape() |
| M-64 | Dashboard SSE连接断开重连逻辑异常 | dashboard/app.py | 修复重连机制 |
| M-65 | Dashboard频道管理页面数据刷新异常 | dashboard/app.py | 修复数据刷新逻辑 |
| M-66 | Dashboard报表下载CSV编码问题 | dashboard/app.py | 添加BOM头支持中文Excel |
| M-67 | ai_engine模型切换未清理旧连接 | core/ai_engine.py | 切换时主动关闭旧连接 |
| M-68 | group_mgr敏感词检测大小写不一致 | modules/group_mgr.py | 统一转小写后比较 |
| M-69 | auto_tasks新闻源HTTP请求缺少User-Agent | modules/auto_tasks.py | 添加标准User-Agent |
| M-70 | database.py WAL检查点频率过高 | core/database.py | 调整wal_autocheckpoint |
| M-71 | resource_manager图片池并发竞态条件 | core/resource_manager.py | 添加线程锁保护 |
| M-72 | optimizer语义缓存过期清理不彻底 | core/optimizer.py | 增强清理逻辑 |
| M-73 | vps_config SSH连接超时未设置 | core/vps_config.py | 添加连接超时参数 |

#### 低危级（9项）
| # | 问题 | 文件 | 修复方案 |
|---|------|------|----------|
| L-01 | database.py核心方法缺失类型注解 | core/database.py | 添加类型注解 |
| L-02 | 日志格式不统一（中英混用） | 多文件 | 统一为中文日志格式 |
| L-03 | config.json配置项缺失时无默认值 | 多模块 | 添加默认值回退 |
| L-04 | start.sh进程检测macOS不兼容 | start.sh | 添加平台判断 |
| L-05 | docker-compose.yml缺少健康检查 | docker-compose.yml | 添加healthcheck配置 |
| L-06 | Dockerfile时区设置缺失 | Dockerfile | 添加TZ环境变量 |
| L-07 | requirements.txt无版本上限约束 | requirements.txt | 添加版本上限 |
| L-08 | .env.example注释格式不规范 | .env.example | 修正注释格式 |
| L-09 | sync_vps.py传输中断无重试 | sync_vps.py | 添加重试机制 |

### v4.3.9 | 2026-04-21 | 定时任务防重复机制：内存字典重构为数据库持久化

**触发原因**：用户反馈晚间问候在群里每分钟发一次相同消息（20:30-20:34连续）

**根因分析**：
1. 旧版使用内存字典（_apscheduler_executed / _executed_today）存储执行标志
2. 内存字典在进程生命周期内有效，但进程崩溃/重启后数据丢失
3. 进程重启后调度器再次触发，检查内存字典为None，重复执行发送

**修复方案**：创建task_log SQLite表，用数据库持久化代替内存字典

```sql
CREATE TABLE IF NOT EXISTS task_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_key TEXT NOT NULL,
    exec_date TEXT NOT NULL,
    exec_ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_log_key_date ON task_log(task_key, exec_date);
```

**新增3个数据库方法**（core/database.py）：
- mark_task_executed(task_key) - 标记任务今日已执行
- is_task_executed_today(task_key) - 查询任务今日是否已执行
- cleanup_old_task_log(days) - 清理N天前的执行记录

**覆盖任务**（10个）：
| 任务 | task_key | 执行时间 |
|------|----------|----------|
| 早安问候 | greeting_morning | 8:05 |
| 早间新闻 | news_morning | 9:05 |
| 每日报告 | daily_report | 9:10 |
| 午安问候 | greeting_afternoon | 12:35 |
| 午间新闻 | news_afternoon | 13:05 |
| 塔罗搭讪 | tarot_flirt | 15:00 |
| 醋意挽回 | jealousy_recovery | 16:00 |
| 购物车挽回 | cart_recovery | 20:00 |
| 晚间新闻 | news_evening | 20:35 |
| 晚安问候 | greeting_evening | 22:00 |

### v4.3.8 | 2026-04-21 | Dashboard全面修复 + 禁言系统重构 + AI引擎优化 + 定时任务加固

#### Dashboard模块（7项）
| # | 问题 | 修复方案 |
|---|------|----------|
| 1 | today_start计算错误（UTC而非北京时间） | 统一使用_CST计算 |
| 2 | api_user_profile SQL错误（使用不存在的列名） | 改为uid/name/tags |
| 3 | keyword搜索SQL注入风险 | 改用参数化查询LIKE ? |
| 4 | 前端字段名不匹配 | 统一前后端字段名 |
| 5 | hourly_trend计算错误 | 改为固定查询今日00:00至当前时间 |
| 6 | escHtml函数XSS风险 | 完善转义逻辑 |
| 7 | SSE线程泄漏 | try/finally确保stream_thread被清理，添加max_threads限制 |

#### 禁言系统（4项）
| # | 问题 | 修复方案 |
|---|------|----------|
| 1 | is_muted调用方式错误（参数不一致） | 全局搜索统一传入chat_id参数 |
| 2 | mute_records复合主键缺失 | 改为(uid, chat_id)复合主键 |
| 3 | chat_id参数传递缺失 | 函数签名统一添加chat_id |
| 4 | 模板seed_hint替换错误 | 修正模板渲染逻辑 |

#### AI引擎（2项）
| # | 问题 | 修复方案 |
|---|------|----------|
| 1 | analyze_image URL处理错误 | 添加本地文件路径判断，转为base64 data URI |
| 2 | spam_track复合主键缺失 | 改为(uid, chat_id)复合键 |

#### 定时任务（8项）
| # | 问题 | 修复方案 |
|---|------|----------|
| 1 | 单例守卫 | 添加全局_scheduler_instance变量 |
| 2 | max_instances=1 | 所有add_job()添加参数 |
| 3 | misfire_grace_time=300 | 所有任务设置5分钟补执行 |
| 4 | TTL 30分钟 | 执行记录附加时间戳 |
| 5 | 清理频率10分钟 | 新增_cleanup_expired_records() |
| 6 | burn_probe禁用 | 移除add_job调用 |
| 7 | 字典内存泄漏 | TTL+定期清理双重保障 |
| 8 | 缩进错误导致崩溃 | 修正为4空格 |

### v4.3.7 | 2026-04-21 | 敏感词覆盖与语义缓存隔离审查

- **Task 3.6**：敏感词检测已正确覆盖所有媒体类型（m.caption是Telegram统一说明字段），无需代码修改
- **Task 3.7**：语义缓存key已包含mode参数（f"{mode}:::{question}"），不同模式天然隔离，无需代码修改

### v4.3.6 | 2026-04-21 | 新闻播报重复发送与质量修复

| # | 问题 | 修复方案 | 文件 |
|---|------|----------|------|
| 1 | 防重复机制字典迭代修改风险 | 改用list()复制键列表，避免迭代时字典修改异常 | modules/auto_tasks.py |
| 2 | 新闻源获取失败时返回空内容 | 增强_dedup过滤函数，剔除广告关键词、特殊符号乱码、过长标题 | core/ai_engine.py |
| 3 | 备用新闻保障 | 所有源失败时返回高质量备用新闻标题 | modules/auto_tasks.py |

### v4.3.5 | 2026-04-21 | 定时任务重复发送修复

| # | 问题 | 修复方案 | 文件 |
|---|------|----------|------|
| 1 | 午安问候每分钟重复发送 | 为所有问候函数添加防重复机制，使用greeting_{morning/afternoon/evening}_{today}执行检查 | modules/auto_tasks.py |
| 2 | 线程安全 | 使用_apscheduler_lock确保并发安全 | modules/auto_tasks.py |

**影响任务**：早安问候(8:05)、午安问候(12:35)、晚安问候(23:05)

### v4.3.4 | 2026-04-21 | 群管机器人指令与定时任务修复

| # | 问题 | 修复方案 | 文件 |
|---|------|----------|------|
| S-24 | _job_channel_views仍用forward_message浪费API配额 | 改为仅处理频道消息，添加chat_id筛选 | modules/auto_tasks.py |
| F-08 | 旧版循环问候任务重复执行 | 添加每日执行标志 | modules/auto_tasks.py |
| F-09 | 每日群总结汇报功能失效 | 修复group_stats表结构，补充chat_id字段 | modules/auto_tasks.py |
| M-57 | 旧版循环任务调度不完整 | 重构_legacy_task_loop，添加每日报告和塔罗搭讪任务 | modules/auto_tasks.py |

### v4.3.3 | 2026-04-21 | 六轮审查全面修复（17项）

#### 致命级（1项）
| # | 问题 | 修复方案 |
|---|------|----------|
| F-06 | sync_vps.py硬编码VPS IP 43.159.168.175 | 统一使用core/vps_config.py环境变量 |

#### 严重级（6项）
| # | 问题 | 修复方案 |
|---|------|----------|
| S-17 | natural_cmd.py全部6个子函数使用未定义mory_bot | 参数统一为mory_bot |
| S-18 | content.py的handle_photo及子函数bot/mory_bot混用 | 统一为mory_bot，内部用mory_bot._bot访问TeleBot |
| S-19 | Dashboard /api/users的order参数可SQL注入 | 白名单校验 |
| S-20 | Dashboard /api/logs/search返回5条假数据 | 改为reply_tracking真实查询 |
| S-21 | Dashboard用户画像SQL使用不存在的列名 | 修正为uid/name/tags |
| S-22 | Dashboard报表下载使用random.randint假数据 | 改为数据库真实查询 |

#### 中等/基础设施（10项）
| # | 问题 | 修复方案 |
|---|------|----------|
| S-15 | ssh_exec输出无限长 | 限制65536字节 |
| S-16 | ai_engine全局超时常量 | 新增_REQUEST_TIMEOUT=30 |
| M-24/M-45 | ResourceManager.db锁与database._db_lock双重锁冲突 | 移除db锁，返回空操作上下文 |
| M-33/M-40 | _last_cleanup_ts被TTL和阅后即焚共用 | 新增_last_ttl_ts独立计时 |
| M-37 | start.sh只装3个包 | 优先从requirements.txt安装 |
| M-42 | Dashboard数据库连接泄漏 | 新增db_conn()上下文管理器 |
| M-44 | 孤儿delete_message失败不清理记录 | 无论成功与否都清理 |
| M-46 | 塔罗搭讪HTML注入 | html.escape()转义 |
| F-07 | 创建requirements.txt | 完整依赖文件 |
| S-26 | 创建.env.example | 环境变量模板 |

### v4.3.2 | 2026-04-21 | 全面安全审计 + 灾难恢复

#### 致命修复（5项）
- **F-01**: Dashboard SQL注入 - 删除_vps_query()死代码
- **F-02**: 硬编码Secret Key - 强制环境变量+长度检查
- **F-03**: VPS硬编码IP - 移除默认值，环境变量必填
- **F-04**: Dashboard密码校验缺陷 - 最小6位+登录频率限制+空密码拒绝
- **F-05**: SQLite连接泄漏 - 添加close()+__del__+atexit优雅停机

#### 严重修复（14项）
- **S-01**: channel_views频繁转发 - 6小时+转发后删除
- **S-02**: fetchone连续调用 - 先保存结果
- **S-03**: get_chat_history不存在 - 改用数据库查询
- **S-04**: optimizer_admin未定义变量 - 添加mory_bot参数
- **S-05**: 连续对话AI追加无超时 - 1次AI调用+5秒超时
- **S-06**: .env引号处理 - 自动去除首尾引号
- **S-07**: save_config无返回值 - 返回bool
- **S-08**: f-string拼接SQL列名 - if/else分支
- **S-09**: IN子句动态构建 - 100条上限
- **S-10**: Dashboard无CSRF - X-Requested-With校验
- **S-11**: Dashboard无速率限制 - 60次/分钟/IP
- **S-12**: 双重except语法错误 - 单个try-except
- **S-13**: paramiko导入错误 - 统一顶部import
- **S-14**: legacy_loop时间判断 - 时间戳差判断

#### 中等修复（5项）
- **M-01**: _conv_tracker内存无限增长 - 1000条上限
- **M-02**: _radar_cooldown内存无限增长 - 每小时清理
- **M-03**: _tarot_daily_cache内存无限增长 - 每天清理
- **M-23**: _calc_consecutive_days死锁 - 不重复获取_db_lock
- **M-26**: _ensure_deps Windows兼容 - 平台判断重定向语法

#### 灾难恢复（3项）
- **I-01**: 数据库损坏无自动修复 - 启动检查自动从备份恢复
- **I-02**: config.json损坏无回退 - 内置最小默认配置
- **I-06**: 无优雅停机 - atexit+信号处理

### v4.3.1 | 2026-04-21 | API_KEY配置冲突

| # | 问题 | 修复方案 |
|---|------|----------|
| 1 | ai_engine.py读取DASHSCOPE_KEY，但main.py映射到API_KEY | 统一读取API_KEY，兼容旧DASHSCOPE_KEY字段 |
| 2 | _radar_cooldown缺少互斥锁 | 添加_radar_lock互斥锁 |

### v4.3.0 | 2026-04-21 | 功能大版本

- Docker一键部署（Dockerfile + docker-compose.yml + docker_deploy.sh）
- AI识图互动（用户发图，10%概率AI识别+撩人评论）
- 活跃勋章系统（10种勋章自动授予+我的勋章命令）
- 热更新配置（管理员发"热更新"无需重启）

### v4.2.8 | 模型过期 + 数据库优化

| # | 修复内容 |
|---|----------|
| 1 | _is_model_expired()自动检查，到期模型加入黑名单并切换 |
| 2 | 数据库索引：idx_track_replied(ts, replied)复合索引 |
| 3 | 塔罗解析重写：正则表达式精准捕获 |

### v4.2.1 | AI问候跑题修复

| # | 问题 | 修复方案 |
|---|------|----------|
| 1 | 早/午/晚安生成时事政治内容 | 加强prompt，强制包含关键词，禁止时事政治 |

---

## 通义千问模型命名重要说明

### 两种命名格式都是正式模型

| 命名格式 | 示例 | 含义 |
|---------|------|------|
| 有日期后缀 | qwen3.5-plus-2026-04-20 | 通义千问的正常命名，代表模型版本日期 |
| 无日期后缀 | qwen3.5-plus | 通义千问的基础命名 |

### 正确理解

- 有日期后缀是正常的版本标识
- 有日期后缀不代表任何有效期
- 两种都是正式模型，都可以用
- 通过API调用失败来判断模型是否可用，而不是通过名称格式

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
| X-09 | 内存缓存无上限 | 内存无限增长 | 添加淘汰机制（1000条/小时清理/每天清理） |
| X-10 | 误以为日期后缀代表过期 | 通义千问模型有日期后缀是正常的命名习惯 | 不要默认把日期后缀当成过期标记 |
| X-11 | 裸except捕获所有异常 | 会吞掉KeyboardInterrupt和SystemExit | 使用except Exception: |
| X-12 | 相对路径做备份 | 工作目录变化时备份文件写入错误位置 | 使用os.path.abspath()绝对路径 |
| X-13 | ==比较密码 | 时序攻击风险 | hmac.compare_digest()恒定时间比较 |
| X-14 | fetchall()直接返回cursor结果 | 多线程环境下cursor结果可能被污染 | 深拷贝或改用fetchone()循环 |
| X-15 | 依赖内存字典去重 | 进程重启后数据丢失，多进程不共享 | 数据库持久化task_log表 |
| X-16 | is_task_executed_today() + mark_task_executed()分离调用 | 两次加锁存在竞争窗口 | 原子操作try_mark_task_executed() |
| X-17 | 无进程级单例锁 | 用户重启未杀旧进程，多进程同时运行 | _acquire_process_lock()文件锁 |
| X-18 | 塔罗搭讪用原子操作 | 30%概率触发，不触发时也被标记 | 保持is+mark分离模式 |
| X-19 | sync_vps.py只负责重启，无文件同步 | 名为sync但实际只restart | 新建deploy_vps.py实现完整SFTP流程 |
| X-20 | ai_engine.py prompt中用/n代替\n | /n不是有效转义字符，导致SyntaxError | 使用\n或字符串拼接 |
| X-21 | resource_manager.py对db资源也加锁 | 与database.py内部锁冲突 | locked_multi中跳过db资源 |
| X-22 | 只修改config.json的API_KEY | main.py启动时用.env的DASHSCOPE_KEY覆盖 | 必须同时修改.env和config.json |
| X-23 | deploy_utils把API_KEY列为保护字段 | VPS上的API_KEY可能是无效旧值 | safe_merge_config：VPS值为空时用本地值 |
| X-24 | 为每条定时消息创建24h休眠线程 | 每天新增10-15个线程×24h=240+线程常驻，内存泄漏约2-3GB | 改用APScheduler的date触发器调度延迟删除 |
| X-25 | Dashboard前端JS直接插入用户名/内容到HTML | XSS攻击风险，用户名含<script>标签可执行恶意代码 | 前端添加HTML转义函数 |
| X-26 | Dashboard登录失败计数器存在app对象上 | 多worker部署时计数器不共享，重启后清零，可绕过5次限制 | 用Redis或SQLite持久化登录失败计数 |
| X-27 | Dashboard api_config_natural返回完整配置 | 敏感字段（TOKEN/API_KEY等）未过滤直接返回 | 应用与api_config相同的敏感字段过滤 |
| X-28 | shell命令拼接用户可控内容（sed/echo等） | shell注入风险，特殊字符（$、反引号、分号等）可被利用 | SFTP读写文件，Python层面修改，禁止shell拼接 |

---

## 环境变量配置指南

启动Dashboard前必须设置：
```bash
export DASHBOARD_SECRET=$(python3 -c 'import secrets;print(secrets.token_hex(32))')
export DASHBOARD_PASSWORD="你的密码(至少6位)"
```

VPS功能需要设置：
```bash
export VPS_HOST="你的VPS_IP"
export VPS_SSH_PASS="你的SSH密码"
```

---

*最后更新：2026-04-28 v4.5.8（本地自检与Windows脚本安全修复）*
## 2026-04-29 - 服务器入侵后的恢复预案

现象：用户反馈服务器被多人入侵，计划直接重装系统。

处理：本地新增一键恢复预案和脚本，恢复策略改为“干净系统 + 本地可信数据 + 重新生成密钥/密码”，避免从旧服务器复制系统级脏配置。

后续：重装完成后填写 `restore_config.json`，先执行 dry-run，再正式恢复并检查服务状态。

## 2026-04-29 - 本机 PowerShell 8009001d

现象：Codex 调用本机 PowerShell 时失败，错误为 `Internal Windows PowerShell error. Loading managed Windows PowerShell failed with error 8009001d`。

处理：新增 `scripts/repair_powershell_8009001d.cmd`，用于在管理员 CMD/Windows Terminal 中执行 DISM、SFC、清理 PowerShell 缓存、临时禁用 profile，并重新测试 PowerShell。

注意：当前 Codex 命令工具依赖 PowerShell 启动，故无法在本回合直接执行该脚本，需要用户从 Windows 侧手动运行一次。

## 2026-04-29 - 腾讯云 VPS 重装后恢复

环境：腾讯云硅谷二区轻量服务器，Ubuntu 24.04.4 LTS，SSH 用户为 `ubuntu`。

处理：
- 通过本地备份打包上传项目到 `/home/ubuntu/mory_assistant`。
- 安装 Python3、venv、pip、字体、curl 等运行依赖。
- 创建虚拟环境并安装 `requirements.txt`。
- 从最新本地 server_pull 备份补齐 Telegram Bot Token 和 AI Key。
- 生成 Dashboard 密钥和登录密码。
- 创建并启用 `mory-assistant.service` 与 `mory-dashboard.service`。

验证：
- `mory-assistant.service` 状态为 active。
- `mory-dashboard.service` 状态为 active。
- Dashboard 监听 `0.0.0.0:8080`，本机 HTTP 检查返回 200。
- 机器人日志显示 Bot ID、用户名、管理员 ID、主群 ID、APScheduler 定时任务均已加载。

后续安全动作：
- 立即更换本次聊天中暴露过的 SSH 密码。
- 建议改为密钥登录并禁用 SSH 密码登录。
- 腾讯云控制台如需公网访问 Dashboard，需放行 8080；不需要公网后台时建议不要放行。
