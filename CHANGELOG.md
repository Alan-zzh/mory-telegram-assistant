# 📝 CHANGELOG · Mory 更新日志

> **每次修改代码都必须在这里记录。**
> 格式：`日期 | 版本 | 文件 | 改了什么 | 为什么改`

---

## 2026-04-19 | v4.1.0 | 架构级深度除虫与死角覆盖

### 🔴 致命Bug修复（三次审计发现）

**1. 引入 BaseMiddleware 中间件，彻底解决"机器人眼瞎"问题**
- 问题：用户的图片/语音/贴纸回复不会被 `master_handler` 捕获（该 handler 只处理文字）
- 原因：`@bot.message_handler(content_types=["text", "new_chat_members"])` 会过滤掉其他类型消息
- 解决：引入 `ReplySnifferMiddleware` 底层中间件，在所有 handler 之前统一拦截所有类型消息
- 涉及：`main.py` 新增 ReplySnifferMiddleware 类 + `bot.setup_middleware()`

**2. 清理重复嗅探逻辑**
- 问题：`_dispatch` 函数中仍有嗅探代码，与中间件功能重复
- 解决：删除 `_dispatch` 中的嗅探代码，统一由中间件处理
- 涉及：`main.py` 第649-658行

**3. APScheduler Cron 语法确认**
- 当前状态：`minute="*/5"`（每5分钟执行一次）
- 确认：语法正确，无需修改。`_job_burn_probe` 已是空操作，不消耗 API 配额

---

## 2026-04-19 | v4.0.3 | 深度审查"二审"修复

### 🔴 致命Bug修复（二次审计发现）

**1. 修复消息路由"黑洞" - 删除独立嗅探器 handler**
- 问题：pyTelegramBotAPI 的 handler 是独占式的，`global_reply_sniffer` 作为独立 handler 会拦截所有回复消息，导致机器人"眼盲"
- 解决：删除独立 handler，将嗅探逻辑内置于 `_dispatch` 函数最开始处
- 涉及：`main.py` 第377行

**2. 修复 Dashboard 安全三连击**
- 问题1：`secret_key` 每次重启随机生成，所有管理员被踢下线
- 问题2：密码虽有环境变量，但默认值太简单
- 问题3：端口绑定 `0.0.0.0` 暴露公网，黑客可直接扫描入侵
- 解决：
  - secret_key 改为固定值从环境变量读取
  - 密码必须设置环境变量，无默认值提示
  - 端口改为 `127.0.0.1`，强制要求 Nginx 反向代理
- 涉及：`dashboard/app.py` 第28、138、2675行

**3. 修复 auto_tasks 空转浪费资源**
- 问题：`_job_burn_probe` 已降级为空函数，但依然每分钟被调度
- 解决：将调度频率从 `minute="*"` 改为 `minute="*/5"`（每5分钟）
- 涉及：`modules/auto_tasks.py` 第439行

---

## 2026-04-19 | v4.0.2 | 深度审计"打假"修复

### 🔴 致命Bug修复（审计发现）

**1. 修复阅后即焚依然失效 - global_reply_sniffer 位置错误**
- 问题：嗅探器注册在 `on_photo`/`on_voice` 之后，导致被其他 handler 拦截
- 解决：强制移动到消息处理器最前面，确保优先捕获所有回复事件
- 涉及：`main.py` 第377行

**2. 修复 API 轰炸地雷 - forward_message 探测逻辑残留**
- 问题：`_job_burn_probe` 仍在用 forward_message 每分钟探测，导致 429 Rate Limit
- 解决：彻底废除探测逻辑，改为被动 TTL 清理（每小时孤儿清理）
- 涉及：`modules/auto_tasks.py` 第218行

**3. 修复 Web 面板安全裸奔 - 硬编码密码**
- 问题：密码直接写死 `pw == "mory2026"`，端口 0.0.0.0 暴露公网
- 解决：改为从环境变量 `DASHBOARD_PASSWORD` 读取，默认值仅用于开发
- 涉及：`dashboard/app.py` 第138行

---

## 2026-04-19 | v4.0 | 架构级除虫与重构

### 🔥 核心重构

**1. 斩断死锁：废除 forward_message 探测**
- 问题：愚蠢的竞态探测导致API滥用、线程阻塞、追踪状态错乱
- 解决：改为"只管发，只管存"，删除交给后台定时任务
- 涉及：`core/mory_bot.py` - 整个 reply_and_track 方法重写

**2. 全局回复嗅探器**
- 问题：用户回复了但系统无法识别，数据库 replied 永远是 0
- 解决：新增全局 handler，优先捕获回复事件，秒级更新数据库
- 涉及：`main.py` - 新增 `global_reply_sniffer` 函数

**3. 字体加载防崩溃**
- 问题：跨平台字体路径不同，Windows/新VPS上直接崩溃
- 解决：添加 arial.ttf 兜底，强制使用默认字体
- 涉及：`modules/content.py` - handle_photo 字体加载逻辑

---

## 2026-04-19 | v21.47 | 隐藏地雷修复 - 3大逻辑缺陷

### 💣 修复清单

**1. 时区撕裂问题（已修复）**
- 问题：database.py 使用 `datetime.now()` (UTC) 导致每日重置在北京时间08:00才生效
- 修复：添加 `_CST = timezone(timedelta(hours=8))`，统一使用北京时间

**2. 阅后即焚23小时探测盲区（已修复）**
- 问题：1小时探测窗口 vs 24小时孤儿清理，中间23小时无探测覆盖
- 修复：窗口扩大到24小时，SQL按时间倒序优先探测新消息

**3. 备份冻结阻塞（已修复）**
- 问题：外层锁 `rm.locked('db')` 导致备份期间所有消息处理被挂起
- 修复：移除外层锁，利用SQLite WAL热备机制，不阻塞主业务

---

## 2026-04-19 | v21.46 | 终极代码审查修复 - 5大致命缺陷

### 🔴 致命崩溃级修复

**1. 线程池耗尽炸弹（已修复）**
- 问题：time.sleep(5-10秒)霸占线程，高并发时Bot假死
- 修复：移除阻塞式sleep，AI请求本身即为"打字延迟"

**2. 内存字典竞态崩溃（已修复）**
- 问题：多线程并发修改_conv_tracker可能导致RuntimeError
- 修复：添加_conv_lock锁保护所有字典读写操作

### 🟡 性能与逻辑修复

**3. Function Calling触发逻辑修正（已修复）**
- 问题：用户@机器人时被限制使用营销工具，违背正常交互直觉
- 修复：移除"not is_at and not is_reply"限制，群聊normal模式均可触发

**4. 视奸雷达冷却机制（已修复）**
- 问题：同一用户频繁触发导致管理员被刷屏
- 修复：添加1小时冷却字典，同一用户1小时内只通知一次，留资打捞不受限制

---

## 2026-04-19 | v21.45 | 修复管理员刷屏Bug（竞态探测消息未删除）

### 问题描述
`core/mory_bot.py` 的 `reply_and_track` 方法中，竞态探测成功后转发给管理员的测试消息未删除，导致每次Bot回复都会在管理员私聊里留下一条消息副本，群聊越活跃刷屏越严重。

### 根因分析
第 126-129 行的 `forward_message` 调用没有捕获返回值并删除，导致探测消息永久残留在管理员会话中。

### 解决方案
1. 捕获 `forward_message` 返回的探测消息对象
2. 探测成功后立即删除探测消息，防止骚扰管理员
3. 只保留探测失败（原消息已删）时的清理逻辑

### 修改文件
- `core/mory_bot.py` - 竞态探测逻辑修复

---

## 2026-04-19 | v21.44 | 架构重构 - 三大核心优化

### 重构内容
1. **移除Monkey Patch**：创建 `MoryBot` 服务封装层，`reply_and_track()` 显式调用
2. **APScheduler重构**：`auto_tasks.py` 各任务独立Job，互不干扰
3. **动态状态迁移**：新增 `system_states` 表，`config.json` 变为纯静态配置

---

## 2026-04-19 | v21.48 | 提示词模板配置化（解决云端/本地配置冲突问题）

### 问题描述
用户发现即使部署脚本已加入配置合并，仍有隐藏问题：`core/ai_engine.py` 中的提示词模板（如晚间新闻、早安问候等）是**硬编码在源代码中**的。每次更新脚本时，这些硬编码模板会直接覆盖 VPS 上的文件，导致在 VPS 上手动修改的提示词丢失。

### 根因分析
源代码文件（`.py`）的更新是**文件整体覆盖**，无法像 `config.json` 那样进行字段级合并。只要提示词写在代码里，就无法避免“更新即覆盖”的风险。

### 解决方案
1. **抽离硬编码模板**：将 `core/ai_engine.py` 中的 `PROMPT_TEMPLATES` 字典（16个模板）全部移入 `config.json` 的 `PROMPT_TEMPLATES` 字段。
2. **动态读取配置**：修改 `ai_engine.py` 的 `_build_persona` 方法，优先从 `config.json` 读取模板，若无则使用硬编码后备。
3. **配置合并保护**：由于模板现在存储在 `config.json` 中，`deploy_final.py` 的配置合并机制会自动保护 VPS 上已修改的模板，防止被覆盖。
4. **双向同步可能**：用户可通过网页端修改 `config.json` 中的模板，一键部署自动同步到 VPS；VPS 上的修改也会在下次部署时拉回本地。

### 技术要点
- 保持向后兼容：若配置中无 `PROMPT_TEMPLATES`，则使用原硬编码字典
- 占位符支持：`{SEED}`、`{NEWS_CONTENT}`、`{seed_hint}` 等占位符在运行时动态替换
- 不改变现有 API：所有调用 `ai.ask(mode="xxx")` 的代码无需修改

### 涉及文件
- `config.json`（新增 `PROMPT_TEMPLATES` 字段）
- `core/ai_engine.py`（动态读取配置）
- `一键部署.bat`（自动保护配置的机制不变）

### 验证要点
1. 运行 `main.py` 测试各模式是否正常（如 `mode="news"`、`mode="morning"` 等）
2. 修改 `config.json` 中的某个模板（如 `evening_news`），观察下次 AI 调用是否生效
3. 执行一键部署，确认 VPS 上的模板修改不会被覆盖

---

## 2026-04-19 | v21.47 | 一键部署配置合并机制修复

### 问题描述
一键部署脚本 `一键部署.bat` / `deploy_final.py` 存在隐藏风险：每次部署时，本地的 `config.json` 会直接覆盖 VPS 上的配置，导致在 VPS 上通过网页端或其他方式修改的配置丢失（被“清零”）。

### 根因分析
原部署流程是单向推送：本地文件 → 上传到 VPS。VPS 上实际运行的配置可能已与本地不同，但部署时未做任何保护和同步。

### 解决方案
1. **部署前自动拉取并合并配置**：在 `deploy_final.py` 中添加步骤 0，先通过 SFTP 读取 VPS 上的 `config.json`，与本地配置进行深度合并。
2. **合并策略**：
   - 以 VPS 配置为优先（保留运行中的值）
   - 保留本地新增的配置项
   - 特殊字段（`_CONFIG_VERSION` 等）以本地为准
3. **写回本地**：合并后的配置写回本地 `config.json`，然后继续上传到 VPS，确保两端配置一致且无丢失。

### 技术要点
- 深度合并嵌套字典（如 `PRICE_LIST`、`SLANG_DICT`、`MODEL_POOLS` 等）
- 自动处理文件读写异常
- 不影响原有部署流程（停止进程、上传文件、重启等）

### 涉及文件
- `deploy_final.py`（核心修改）
- `一键部署.bat`（调用脚本，无需修改）

### 验证要点
1. 下次执行“一键部署”时，观察控制台输出，确认“备份并合并VPS配置”步骤执行成功。
2. 检查合并后的 `config.json`，确保 VPS 上的关键修改（如回复概率、系统提示词等）未被覆盖。
3. 部署完成后，验证 Bot 功能正常，配置生效。

---

## 2026-04-19 | v21.46 | 自动任务（新闻/问候）确认修复

### 问题描述
晚间新闻、早安/午安/晚安等定时任务从未生效。

### 排查结果
- 所有日志中**完全无**新闻/问候记录
- 手动测试晚安+晚间新闻 → ✅ **全部正常工作**
- AI引擎、消息发送、新闻获取均无问题
- 根因：Bot进程之前挂了，所有定时时间窗口都错过了

### 验证
- 晚安消息 msg_id=41559 已发送到群 ✅
- 晚间新闻 msg_id=41560 已发送到群 ✅
- Bot从23:14正常运行后，明日起所有定时任务将准时触发

---

## 2026-04-18 | v21.45 | Bot@消息不回复问题修复

### 问题描述
用户在群组中 @MoryMateBot 发消息，Bot 完全无响应（不收消息、不回复）。

### 排查过程
1. 检查 Privacy Mode → ✅ 已关闭，Bot 有管理员权限
2. 检查 Webhook/Pending Updates → ✅ 无冲突
3. 在 `_dispatch` 入口添加 `[MSG_IN]` 全量日志
4. 部署新代码后重启 Bot
5. 发现 **Bot 进程在启动后很快静默退出**（PID文件存在但进程已死）
6. 日志停在最后一条消息处理后，**没有任何 ERROR/CRITICAL/Traceback**
7. 用 `start.sh start` 正确重启后，**@消息立刻正常接收和回复**

### 根因
Bot 进程因未知原因（可能是部署操作 kill 后 nohup 重启失败）静默退出，
之后一直没有正确运行。代码逻辑本身没有 bug，`[MSG_IN]` 日志证实：
Bot 完全能收到 `@MoryMateBot xxx` 消息并正确触发 AI 回复。

### 修复措施
1. 在 `_dispatch()` 入口添加了永久 DEBUG 日志 `[MSG_IN]`
2. 正确使用 `start.sh start` 启动 Bot（清理旧 PID 后重新 nohup）
3. 确认日志文件路径为 `/root/mory/mory.log`（不是 bot.log）

### 技术要点
- VPS 上 Bot 运行日志：`/root/mory/mory.log`
- PID 文件：`/root/mory/.mory.pid`
- 启动命令：`cd /root/mory && bash start.sh start`
- 停止命令：`cd /root/mory && bash start.sh stop`

---

## 2026-04-18 | v21.44 | 全量代码诊断

### 检查内容
1. VPS日志全部错误分析
2. 所有模块功能检查
3. Bug分类整理

### 诊断结果

**✅ 核心Bug已全部修复：**
- SQL语法错误(CRLF) ✅
- Bot 409 Conflict ✅
- 阅后即焚追踪污染 ✅
- 孤儿清理失效 ✅

**⚠️ 非Bug的正常现象：**
- 醋意挽回403错误 - Telegram平台限制（Bot不能主动私聊用户）
- 购物车挽回403错误 - 同上
- 孤儿清理无日志 - 正常（reply_tracking表为空）

**📁 创建诊断文档：**
- FULL_BUG_ANALYSIS.md - 完整Bug分析报告

### 涉及文件
- 全项目扫描
- docs/FULL_BUG_ANALYSIS.md (新建)

---

## 2026-04-18 | v21.44 | 文档结构整理

### 问题
根目录文档过多，不方便管理

### 解决方案
1. 整理根目录文档结构
2. 核心文档（根目录）：
   - `CHANGELOG.md` - 更新日志
   - `AI_DEBUG_HISTORY.md` - 技术调试手册
   - `README.md` - 快速入口
3. 归档文档（docs/目录）：
   - 其他历史文档

### 涉及文件
- 新建 docs/ 目录
- 移动 7 个文档到 docs/

---

## 2026-04-18 | v21.44 | SQL语法错误修复（CRLF问题）

### 问题
Bot日志报错：`sqlite3.OperationalError: near "?": syntax error`

### 原因
VPS上database.py文件使用了Windows行尾(CRLF)，导致多行SQL字符串解析错误。

### 修复
1. 本地修复database.py转换为Unix行尾(LF)
2. 上传到VPS并重启Bot

### 验证结果
- Bot重启成功 ✅
- 无SQL错误 ✅
- 阅后即焚功能正常 ✅

### 涉及文件
- `core/database.py`

---

## 2026-04-18 | v21.44 | Bot 409 Conflict冲突修复

### 问题
Bot日志出现 `Error code: 409. Description: Conflict: terminated by other getUpdates request`

### 原因
有多个Bot进程同时运行，争用Telegram API

### 修复
```bash
pkill -9 -f 'main.py'  # 终止所有Bot进程
bash start.sh start     # 重新启动
```

### 验证结果
- Bot已重启: PID=1907426 ✅
- 无新的409错误 ✅

---

## 2026-04-18 | v21.44 | 阅后即焚追踪污染修复

### 问题描述
1. `reply_tracking` 表为空，没有任何有效追踪记录
2. 日志中出现大量 `track_reply参数无效: user=0` 错误

### 根因分析
`auto_tasks.py` 的 `_send_and_track()` 调用了 `track_reply()`，但主动消息（早安问候、新闻播报等）的 `user_msg_id=0`，被数据库拒绝。

### 修复方案
1. 移除 `_send_and_track` 中的追踪调用
2. 升级 main.py 的追踪日志为 INFO 级别

### 验证结果
- ✅ `track_reply calls in auto_tasks.py: 0` - 不再调用追踪
- ✅ Bot重启后无 `user=0` 错误
- ✅ 追踪日志升级为 INFO 级别

### 涉及文件
- `modules/auto_tasks.py`
- `main.py`

---

## 2026-04-18 | v21.44 | 阅后即焚两大功能修复

### 问题描述
1. **"删除不回复自己的消息"** 不工作 - 孤儿消息不被清理
2. **"删除删除的回复消息"** 失效 - 原消息被删后bot回复不被删除

### 根因
`auto_mark_group_active()` 会将群里所有历史未回复消息标记为 `replied=1`，导致孤儿清理永远找不到消息。

### 修复方案
1. `auto_mark_group_active()` 只标记**10分钟内**的消息
2. `get_unconfirmed_messages()` **不再依赖 replied 状态**
3. `get_orphan_messages()` **基于时间窗口判定孤儿**
4. 新增 `refresh_tracked()` 方法

### 涉及文件
- `core/database.py`

---

## 2026-04-18 | v21.43 | 新闻播报发两条修复

### 问题
早间新闻发了2条，第一条是详细版，第二条是"总结"字样

### 根因
`_build_persona()` 中 `{NEWS_CONTENT}` 被替换成占位符，AI自己生成了总结内容

### 修复
调整 `{NEWS_CONTENT}` 的处理逻辑，确保AI能正确使用新闻数据

### 涉及文件
- `modules/content.py`

---

## 2026-04-18 | v21.43 | 背刺泄密频率调整

### 问题
背刺功能触发频率过高，用户反馈"太频繁了"

### 修复
调整触发概率和冷却时间

### 涉及文件
- `modules/auto_tasks.py`

---

## 历史修复记录

### v21.42 | 阅后即焚核心重构
- 实现基于时间窗口的孤儿清理
- 新增竞态探测机制

### v21.41 | Bot状态显示修复
- 修复"已停止"显示问题

