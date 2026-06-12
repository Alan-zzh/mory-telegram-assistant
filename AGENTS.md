# Mory小助理 项目规则（所有 AI 必读）

> **位置**：项目根目录 `AGENTS.md`（大写显式，**不是** `.agents` 也不是 `.trae/rules/`）
> **最后核验**：2026-06-12 · v5.16.2 [Codex]
> （技术细节详尽展开见 `docs/technical/`，不锁行数）

***

## 1. 🎯 业务核心目标

> ⚠️ **本节是项目核心**：Mory小助理 ≠ 普通群管机器人，是**运营型商业 AI 转化机器人**。
> 任何 AI 接手前必须先读懂本节，**理解项目真实定位**再动手。

### 1.1 项目定位与产品矩阵

| 项        | 值                                                                                                                                                                     |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **项目名称** | Mory小助理（`config.json.example:BOT_NAME`）                                                                                                                               |
| **真实定位** | **运营型商业 AI 转化机器人**（不是普通群管）                                                                                                                                            |
| **核心目标** | 通过人设对话+商业引导，引导用户通过 `@MorychannelBot` **自助下单**                                                                                                                         |
| **业务红线** | **绝对不能因报错导致程序卡死崩溃**（用户原话："绝对不能死"）                                                                                                                                     |
| **次要红线** | ①不说自己是AI/机器人/模型 ②不直白营销 ③不重复话术模板 ④不破坏商业产品边界                                                                                                                            |
| **商业产品** | 至臻精选（月 149.9 / 季 349.9）/ 至臻全享（年 999，3 群）/ 精选图集（季 228.8 / 年 666.6）                                                                                                     |
| **下单渠道** | **`@MorychannelBot`** **自助下单**（Bot 内不支付，发送价格表+链接引导）                                                                                                                   |
| **服务器**  | VPS（systemd 托管，禁止 start.sh/nohup/pm2 混用）                                                                                                                              |
| **核心配置** | `SYSTEM_PROMPT`（人设灵魂 10 维）+ `PRICE_LIST`（3 档商业产品）+ `SLANG_DICT`（5 词隐晦黑话）+ `PROMPT_TEMPLATES`（4 模式扩展）+ `MODE_ROUTING`（25 mode 路由）+ `MODEL_POOLS`（4 有模型 + 5 占位 = 9 池键名） |

### 1.2 6 大核心能力矩阵（精简版）

| 大类              | 能力                                                                                                                                                                     | 关键模块/配置                                                                                                                                              |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **🤖 人设对话**     | SYSTEM\_PROMPT 真人女孩 + 10 维商业目标 + 对话轮次递进 3 段（1-2 轮→3-4 轮→5 轮+）+ 1 句兜底 + 4 PROMPT\_TEMPLATES（tarot/treehole/dream/fortune）+ 25 MODE\_ROUTING                             | `config.json.example:SYSTEM_PROMPT` + `PROMPT_TEMPLATES` + `MODE_ROUTING`（llm\_light 11 + llm\_standard 8 + llm\_premium 6）                          |
| **🎯 商业引导**     | 关键词三件套（SLANG\_DICT 5 词黑话 + PHOTO\_KEYWORDS 5 词 + HATE\_KEYWORDS 7 词）+ natural\_cmd（"把 X 改成 Y"自然语言配置）+ keyword\_trigger（static/ai/action 3 模式触发）+ 9 池模型路由（4 有模型 + 5 占位） | `keyword_trigger.py` + `natural_cmd.py` + `slang_dict.py` + `photo_keywords.py` + `hate_keywords.py` + `MODEL_POOLS`（9 池键名）                          |
| **💰 商业闭环**     | 积分系统（签到+游戏+邀请+商城+衰减）+ Shop 商城 + Coupon 优惠券 + Redpacket 红包 + Lottery 抽奖 + 盲盒/幸运转盘 + **Cart\_recovery 购物车挽回**（每小时 AI 个性化消息）+ 转化追踪（conversions/conversion\_events 表）      | `points_enhanced.py` + `shop.py` + `coupon.py` + `redpacket.py` + `lottery.py` + `auto_tasks._job_cart_recovery` + `conversions/conversion_events` 表 |
| **🛡 群管 83 模块** | 入群验证+强制订阅+全局黑名单+警告禁言+慢模式+防刷屏+广告拦截 5 层（L0-L4）+反 R-aid+AFK+NSFW+Avatar+EmojiMask+EditDetect+Antidelete + 83 个业务模块（modules/）                                              | `group_mgr.py` + `ad_detector.py` + `antiflood.py` + `anti_raid.py` + `verification.py` + 78+ 其他（见 modules/）                                         |
| **📊 运营观察**     | Dashboard 22+ API + 95+ 实际端点 + 8 类 115 按钮 + 转化统计（`conversions` 表）+ 数据看板 + 私聊告警 + 孤儿清理可视化                                                                               | `dashboard/app.py` + `dashboard/api/*` + `optimizer_admin.py` + `conversions` 表 + `orphan_api.py`                                                    |
| **🚀 消息分发**     | 25 个 P 级别拦截器（P0-P10 + P0.5/0.6/0.7/P2.2/2.5/2.6/P3.2/3.5/3.8/P4.5/4.6/4.7/P5.5/P6.3/6.4/6.5/6.6/P8.5/8.8/8.85/P9.3/9.5/9.7）                                            | `core/message_dispatcher.py` + `BaseMiddleware` 拦截                                                                                                   |

### 1.3 业务红线（不可触碰）

| # | 红线                | 出处                                            |
| - | ----------------- | --------------------------------------------- |
| 1 | **绝对不能死**（用户原话）   | 因报错导致程序卡死崩溃 = 业务失败                            |
| 2 | **绝对不说自己是 AI**    | SYSTEM\_PROMPT 第 2 条铁律，违反=人设崩                 |
| 3 | **绝对不直白营销**       | "想看更多？""@MorychannelBot 那边有惊喜"温和引导，不喊"买买买"    |
| 4 | **绝对不重复话术模板**     | 话术池 v4.5.12 起强制每次换说法                          |
| 5 | **绝对不破坏 3 档产品边界** | 至臻精选/全享/精选图集价格、群数、权益必须严格遵循 `PRICE_LIST`       |
| 6 | **绝对不在 Bot 内收款**  | 一律引导 @MorychannelBot 自助下单（支付/订单在 channel bot） |

### 1.4 详尽能力矩阵 →

- 人设对话/话术/价格/分流/4 PROMPT\_TEMPLATES/25 MODE\_ROUTING/9 模型池 完整版 → [docs/technical/capability-matrix.md](docs/technical/capability-matrix.md)
- 商业引导话术演进史 → `AI_DEBUG_HISTORY.md` v4.5.12\~v5.11.0
- 83 个业务模块完整列表与功能（modules/）→ [project\_snapshot.md](project_snapshot.md) + `ls modules/`
- 84 张数据库表 → [project\_snapshot.md](project_snapshot.md) + `core/database.py` 行 127-927
- 35+ 自动任务（auto\_tasks._job_\*）→ [docs/technical/auto-tasks.md](docs/technical/auto-tasks.md) （如不存在则跳过）
- 95+ Dashboard API 端点 → `dashboard/api/*.py` 路由清单

***

## 2. 🗺️ 历史文档优先原则（强制）

**遇 Bug/需求，第一步查阅三个文档，禁止直接写新代码**：

| 文档                    | 查什么               |
| --------------------- | ----------------- |
| `project_snapshot.md` | 当前架构/数据库/配置       |
| `CHANGELOG.md`        | 最近 2 条变更（避免重复造轮子） |
| `AI_DEBUG_HISTORY.md` | 病历本（避让失败路线）       |

- 文档里有现成方案 → **直接复用**
- 文档里踩过坑 → **绝对避开**
- 全新问题 → 才允许写新逻辑

***

## 3. ⚙️ 技术边界

| 项             | 规则                                                         |
| ------------- | ---------------------------------------------------------- |
| 技术栈识别         | 自动识别（Python + pyTelegramBotAPI + SQLite + Flask），按当前框架最佳实践 |
| 代码注释          | **必须中文**（变量名/函数名英文，注释中文）                                   |
| 报错处理          | **写入本地** **`logs/`** **文件夹**，严禁全屏打印红字代码给 User 审查           |
| 凭据管理          | 唯一存 `.env`（代码用 `os.environ["KEY"]`）；文档只写 KEY\_NAME         |
| 配置开关          | 新功能**默认关闭**（`config.get('KEY', False)`），测试通过后手动开启          |
| Dashboard 改配置 | Bot **5-8 秒内自动生效**（reload\_flag 信号）                        |

***

## 4. 💥 5 条核心教训（用户新增重点）

| # | 教训                 | 说明                                                   |
| - | ------------------ | ---------------------------------------------------- |
| 1 | **代码未部署 = 修改未生效**  | 本地代码改完必须 `python deploy_vps.py` 部署到 VPS，Bot 跑的是服务器代码 |
| 2 | **SQLite 迁移可能假成功** | 迁移记录写入但 ALTER TABLE 可能因表锁失败，部署后**必须验证表结构**           |
| 3 | **二次修改必须二次部署**     | 修了 bug 但只本地改没重新 deploy，服务器仍跑旧代码                      |
| 4 | **数据库结构同步**        | 改 `schema.py` 后必须同步执行 migration 或手动 `ALTER TABLE`    |
| 5 | **日志是唯一真相**        | 怀疑功能不生效→先 `tail mory.log` 或 `journalctl`，错误信息比假设更可信  |

***

## 5. 🛡 跨 AI 一致性铁律（F1-F8）

| 编号     | 铁律                                                                                                     |
| ------ | ------------------------------------------------------------------------------------------------------ |
| **F1** | 测试文件位置：`tests/unit/` 或 `tests/integration/`，**根目录禁止** **`_*.py`** **临时文件**                             |
| **F2** | 工具脚本位置：`scripts/`（含验证脚本、诊断脚本）                                                                          |
| **F3** | 技术细节文档：`docs/technical/`（kebab-case 命名），**详尽写实不限字数**（技术细节文档要详细展开）                                      |
| **F4** | `core/ modules/ dashboard/` 单文件 ≤ 200 行（超 200 行拆函数不拆文件）；`docs/technical/` **详尽优先不限字数**；README 也应详尽不锁行数 |
| **F5** | 根目录禁止临时文件（`_check_*.py` / `_test_*.py` / `_debug_*.py` 一律归档 `tests/_archive/`）                         |
| **F6** | 不自己造规则/不重复发明轮子（改前先 grep + 查 project\_snapshot/AI\_DEBUG\_HISTORY）                                      |
| **F7** | 引用代码前先 grep（不凭空报行号，先 `grep -n "xxx" core/database.py`）                                                 |
| **F8** | 版本号查 `AI_DEBUG_HISTORY.md` 头部 + `version.py`（不在 AGENTS.md 硬编版本案例）                                      |

***

## 6. 🔴 绝对禁止（违反会出大事）

| #      | 禁令                                                           | 出处      |
| ------ | ------------------------------------------------------------ | ------- |
| 1      | 禁止 `sftp.put('config.json')` 直接覆盖 VPS                        | v5.10.2 |
| 2      | 禁止 `sftp.put('mory.db')` 上传数据库                               | v5.9.0  |
| 3      | 禁止用 root 用户 SSH 部署                                           | v5.11.0 |
| 4      | 禁止 `start.sh` / `nohup python main.py` 启动（与 systemd 冲突致 409） | v5.7.1  |
| 5      | 禁止 `.env`/密钥 提交到 Git                                         | v5.0.0  |
| 6      | 禁止在代码/文档/AI\_DEBUG\_HISTORY 写敏感值明文                           | 全局      |
| <br /> | <br />                                                       | <br />  |
| 7      | 禁止凭据写到 .env 以外文件                                             | 全局      |

**禁令#1 修复**：必须用 `core/deploy_utils.safe_upload_config()`（自动合并+保护密钥）。

***

## 7. 🟡 VPS 部署铁律

- 用户：`ubuntu`（禁 root，v5.10.3 起统一）
- 路径：`/home/ubuntu/mory_assistant/`
- 进程：systemd only（`sudo systemctl {start,stop,restart} mory-assistant`）
- 服务文件：`mory-assistant.service` + `mory-dashboard.service` 必须有 `EnvironmentFile=.../mory_assistant/.env`
- 部署前：`sudo chown -R ubuntu:ubuntu {VPS_PATH}/{core,modules,dashboard}`
- 多 Bot 区分：`ps -ef | grep '/home/ubuntu/mory_assistant/main.py' | grep -v mory_media`
- Dashboard 端口：**6616**（固定）
- 详情 → [docs/technical/vps-deploy-trap.md](docs/technical/vps-deploy-trap.md)

***

## 8. 🟢 配置铁律

- **敏感词**：Unicode 转义序列存（直接写中文触发平台审核）→ `modules/ad_patterns_encoded.py`
- **配置键新增**：三处同步（`config.json.example` + 代码 `.get(key, default)` + Dashboard 设置面板）
- **热重载**：Dashboard 改 → 5-8 秒 Bot 自动生效（`reload_flag` 文件 + 5秒轮询）
- **默认值**：`config.get('KEY', False)` 显式声明，VPS 老 config 不会自动同步

***

## 9. 🔵 Bot API 限制与项目方案（AI 纪律）

| 限制               | 项目方案                                                                             |
| ---------------- | -------------------------------------------------------------------------------- |
| Bot API 无法枚举群成员  | **Pyrogram 全量扫描**（\~96% 覆盖）→ [MEMBER\_SCAN\_METHOD.md](MEMBER_SCAN_METHOD.md)    |
| Bot API 无法获取历史消息 | **双模式追溯扫描**（forwardMessage + DB 驱动）→ `modules/ad_detector.py:retroactive_scan()` |
| 群成员列表不完整         | **渐进式成员追踪**（chat\_member\_handler 实时 + group\_members 持久化）                       |
| 消息删除需要 msg\_id   | **消息追踪表**（`ad_suspicious_users` / `broadcast_tracking`）                          |
| "保护内容" ≠ 不能删     | `bot.delete_message()` **不受**保护内容影响                                              |

**AI 必读**：用户问"为什么无法 X"时，**先查代码+上述文档**，不得说"无法做到"。

***

## 10. ⚠️ 8 大类老坑铁律（反模式 → 详见 docs/technical/anti-patterns.md）

1. **沉默失败** 8 反模式（v5.10.0/v5.11.0 翻车）
2. **配置一致性** 5 铁律
3. **部署一致性** 6 铁律
4. **DB 方法注册** 4 铁律（v5.11.0 漏注册翻车）
5. **half-migrated** 3 铁律（v5.9.1 `_can_run` 拆分）
6. **关键路径 E2E** 5 铁律
7. **AI 自我审计** 4 铁律（不重复造轮子）
8. **VPS 部署** 5 铁律
9. **孤儿清理开关独立于消息删除开关（v5.12.4 新增铁律）**
   - `ORPHAN_CLEANUP_ENABLED` 控制 `_job_burn_orphan`，**严禁** 与 `ENABLE_MESSAGE_DELETION` 耦合
   - 业务原因：用户希望孤儿清理独立可控，不受全局消息删除开关影响
   - 反例（v5.12.0）：`_job_burn_orphan` 复用 `can_delete_message()` → 全局开关关 → 孤儿永远不删
   - 正例（v5.12.4）：`can_orphan_cleanup()` 独立判断 + `ORPHAN_CLEANUP_ENABLED` 默认 `true`
   - 验证命令：`grep -n "can_orphan_cleanup\|ORPHAN_CLEANUP_ENABLED" core/helpers.py modules/auto_tasks.py`
10. **部署必真实验证（v5.12.4 翻车后新增铁律）**
   - `deploy_vps.py` 显示"成功"≠ Bot 真的在跑 - 旧 dashboard `engage_bp` 未 import 导致 auto-restart 800+ 次都没起
   - **必须** 部署后 SSH 端验证：
     1. `sudo systemctl status mory-assistant` 看 active
     2. `sudo systemctl status mory-dashboard` 看 active
     3. `curl http://localhost:6616/api/health` 看 HTTP 200
     4. `journalctl -u mory-dashboard -n 30` 看无 ImportError
   - 反模式：只看 deploy_vps.py 输出 ✅ 就算完成 - 这种"成功"可能是 Dashboard 持续崩溃循环
11. **deploy_vps.py SCAN_DIRS 不含 scripts/（v5.12.4 翻车）**
   - 新增 `scripts/force_orphan_cleanup.py` 不会被自动上传到 VPS
   - 必须在 deploy_vps.py 增加 `scripts` 到 SCAN_DIRS，或手动 sftp.put 上传
   - 验证：`ls /home/ubuntu/mory_assistant/scripts/` 看新脚本是否存在
12. **短引流词检测不能一刀切（v5.14.2-fix 翻车）**
   - `len(msg) < 3` 跳过2字符消息是过度优化，"在线"等2字符引流词权重>=4应被检测
   - 反例（v5.14.2前）：`message_dispatcher.py:900` + `security_handlers.py:109` 双重 `len(msg) < 3` → "在线"（2字符）被跳过 → 广告用户连续发6条短消息全部漏检
   - 正例（v5.14.2-fix）：`len(msg) < 2`，允许2字符消息进入检测引擎
   - 验证命令：`grep -n "len(msg) < " core/message_dispatcher.py core/handlers/security_handlers.py`
13. **广告治理=永久禁言+双黑名单+删消息（v5.14.2-fix 历史教训，v5.16.2 [Codex] 新策略纠正）**
   - [Codex] 2026-06-12 新口径：广告账号**不踢人**，不得在广告链路调用 `ban_chat_member` / `kick_chat_member`
   - [Codex] 当前标准动作：删除当前消息 + 永久禁言 `restrict_chat_member(can_send_messages=False)` + 写 `global_blacklist` + 写本地 `blacklist` + 清 `message_snapshots` 可追踪历史消息 + 通知管理员
   - [Codex] `ENABLE_MESSAGE_DELETION` 只控制删消息；永久禁言和黑名单不受它影响
   - [Codex] 需要统一入口：`modules/ad_enforcement.py:enforce_ad_user()`，新增广告处置路径必须复用它
   - 历史反例（v5.14.2）：只禁言且不删消息/不写黑名单会失效；历史“踢出”结论已废止，不再作为当前策略
   - 验证命令：`grep -n "ban_chat_member\|kick_chat_member" core/ modules/ | grep -v "vote_kick\|verification\|zombie_clean\|inactive_clean\|silent_actions\|federation\|warning"`，广告路径不得出现踢人
14. **新引流话术需持续更新关键词库（v5.14.2-fix 翻车）**
   - "联络我带你启飞"是新的引流话术变体，之前的关键词库没有覆盖
   - 每次发现新的引流话术，必须同步更新 `ad_patterns_encoded.py` 的 USERNAME_PATTERNS + CONTACT_PATTERNS + RECRUIT_PATTERNS
   - 繁体变体映射也需同步更新 `_normalize_ad_evasion`（線→线、聯→联、飛→飞等）
15. **广告处置必须全路径一致（v5.14.2-fix 联想铁律，v5.16.2 [Codex] 新策略纠正）**
   - [Codex] 同一操作（如"广告治理"）在代码中可能有多个入口（实时检测/延迟处置/启动扫描/启动追溯/入群资料检测），每个入口都必须执行同一套永久禁言动作
   - [Codex] 新增广告处置入口时，必须检查并复用 `enforce_ad_user()`，不得自己写半套删除/黑名单/禁言逻辑
   - 反模式：修了A入口忘了B入口，导致某个路径只删消息或只写黑名单
   - 验证：`grep -n "enforce_ad_user\|ban_chat_member\|kick_chat_member" core/ modules/ | grep -v "backup\|__pycache__"` 检查广告链路是否统一
16. **数据库表必须先创建再使用（v5.14.2-fix 联想铁律）**
   - 代码中 `INSERT INTO global_blacklist` 但表不存在 → `OperationalError: no such table`
   - 所有新增的数据库操作，必须先在 `core/database.py` 的 schema 中定义表，或代码中用 `CREATE TABLE IF NOT EXISTS` 保护
   - 反例：`auto_tasks.py` 尝试 `INSERT INTO global_blacklist` 但表从未创建
   - 正例：代码中先 `CREATE TABLE IF NOT EXISTS global_blacklist` 再 `INSERT`
   - 验证：`grep -n "global_blacklist\|CREATE TABLE" core/database.py modules/auto_tasks.py`
17. **消息追踪是删除历史消息的前提（v5.14.2-fix 联想铁律）**
   - Bot API 无法枚举群历史消息，删除历史消息依赖 `message_snapshots` 表中的 msg_id 记录
   - 短消息（< 3字符）之前被跳过不入库 → 封禁后无法删除其历史消息
   - 所有进入消息处理流程的消息，都应写入 `message_snapshots` 表，即使最终不触发任何操作
   - 反例：`len(msg) < 3` 跳过的消息不入库 → 封禁后找不到消息ID → 无法删除
   - 验证：`grep -n "snapshot_message\|message_snapshots" core/handlers/security_handlers.py`
18. **"看我简介"变体字符集必须包含 个/jie/接/界/衔（v5.16.1 翻车）**
   - "看我简个"/"看我简jie"/"看我简接" 是 "看我简介" 的高频变体，**Alan 哥强调无数次的必封规则**
   - 原 USERNAME_PATTERNS 字符集只有 介(U+4ECB)/届(U+5C4A)/屆(U+5C46) 三字，"个" 不在内 → 漏判
   - 修复：字符集扩展 `[\u4ecb\u5c4a\u5c46\u4e2a\u63a5\u754c\u8854]` + 拼音变体 `看我...简...jie`
   - 验证命令：`grep -n "看我...简\|kanwo_jianjie" modules/ad_patterns_encoded.py`
   - 反模式：字符集只列"标准"字，广告用户用同音/形近字/拼音绕过
19. **bio 核心骗术话术必须单列规则（v5.16.1 翻车）**
   - "一天保X万打底" / "带X钱包" / "想做兄弟" / "进群找了解" 是 bio 中核心骗术信号
   - 原 BIO_PATTERNS 只有"进群+链接"和"t.me/+"兜底，bio 拉取到后单条命中阈值不一定超 3 → 漏判
   - 修复：BIO_PATTERNS 4 大类 11 条补充（一天+保X万 / 数字+打底 / 带X钱包 / 想做兄弟 / 进群找了解 / 付出保X）
   - 验证命令：`python -m pytest tests/unit/test_ad_patterns_v5161.py -v`（31 个测试全通过）
   - 原则：核心骗术话术优先于"通用关键词"，bio 拉取完整后必须能直接命中

***

## 11. 🆘 找不到答案时（按顺序查）

1. 本文件 `AGENTS.md` 全部章节 + 末尾索引
2. `AI_DEBUG_HISTORY.md` 历史病历
3. `project_snapshot.md` 当前状态
4. `docs/technical/` 技术细节
5. [MEMBER\_SCAN\_METHOD.md](MEMBER_SCAN_METHOD.md) 群成员/历史消息
6. SSH 上 VPS 看 `mory.log` 和 `journalctl`

***

## 12. 📂 项目结构速查（6 件套 + 关键目录）

```
mory_assistant/
├── AGENTS.md                # 项目规则（本文件）
├── main.py / version.py     # 入口/版本
├── deploy_vps.py            # VPS 一键部署
├── config.json.example      # 配置模板
├── .env.example             # 环境变量模板
├── core/                    # 核心（database/handlers/db_repos）
├── modules/                 # 45+ 功能模块
├── dashboard/               # Flask 后台（app/auth/helpers/api）
├── tests/                   # 测试（unit/integration/_archive）
├── scripts/                 # 工具脚本
├── docs/technical/          # 技术细节（kebab-case）
├── AI_DEBUG_HISTORY.md      # 病历本
├── project_snapshot.md      # 快照
├── CHANGELOG.md             # 变更日志
├── VERSION.md               # 版本号
├── README.md                # 项目入口
└── MEMBER_SCAN_METHOD.md    # 群成员扫描方案
```

### 部署流程

1. 本地改代码 → `python -m py_compile` 无语法错误
2. `python deploy_vps.py`（自动 stop → 上传 → start → 验证）
3. 手动重启：`sudo systemctl restart mory-assistant`
4. 看日志：`journalctl -u mory-assistant -n 100 --no-pager`

***

## 13. 🛠 通用工作纪律（速查）

- 凭据：`.env` 唯一来源，文档只写 KEY\_NAME
- 注释：中文；变量/函数名：英文
- 备份：改前 `backup/` 目录
- 失败升级：1次重试 → 2次换参数 → 3次换方案 → 仍失败告知用户
- 病历：`AI_DEBUG_HISTORY.md` 记所有失败
- 配置变更：Dashboard 5-8 秒内自动生效
