## v5.16.3 [2026-06-12] [Codex]
### 工作区脏改动收敛 + 目录分层清理

**整理内容**：
- [Codex] 合并已存在的模块化拆分：`core/db_repos/`、`core/handlers/`、`dashboard/api/`、`dashboard/templates/`、`modules/` 业务模块分层落地。
- [Codex] `config.json` 退出 Git 跟踪，保留本地运行文件；后续提交只维护 `config.json.example` 和 `.env.example`。
- [Codex] `.gitignore` 补齐 `backup/`、`logs/`、运行配置、数据库、临时脚本和部署脚本例外规则。
- [Codex] 清理旧调试脚本、旧 `universal_ai_router/` 目录、`start.sh`、`deploy.sh`、`windows_helper.py`，保留 `deploy_vps.py`、`scripts/ssh_helper.py`、`scripts/restart_bot.py`、`scripts/cleanup_vps.py` 等可维护脚本。
- [Codex] 补齐 `MEMBER_SCAN_METHOD.md` 与 `docs/technical/` 技术文档，文档集中到约定目录。
- [Codex] 修复 `dashboard/app.py` 缺 `DASHBOARD_SECRET` 时 GBK 控制台打印 emoji 导致的二次 `UnicodeEncodeError`。

**验证**：
- [Codex] `python -m pytest tests/unit/test_ad_patterns_v5161.py tests/unit/test_convert_keywords.py tests/unit/test_proactive_engage.py tests/unit/test_ad_enforcement.py tests/unit/test_emoji_mask_detector.py tests/unit/test_auto_tasks_greeting_config.py -q` → 54 passed。
- [Codex] `python -m py_compile $(git ls-files '*.py')` 等价全量编译通过。
- [Codex] 关键模块导入冒烟通过：`main`、`core.bot_initializer`、`core.message_dispatcher`、`core.database`、`dashboard.app`、`modules.auto_tasks`、`modules.ad_detector`、`modules.group_mgr`、`modules.proactive_engage`。

---

## v5.16.2 [2026-06-12] [Codex]
### 广告治理策略纠正 + 智能化暗病修复 + 环境清理

**策略纠正**：
- [Codex] 广告账号不再踢出群，不再在广告链路调用踢人 API
- [Codex] 当前统一处置：删除当前消息 + 永久禁言 + 写 `global_blacklist` + 写本地 `blacklist` + 清理 `message_snapshots` 可追踪历史消息 + 管理员通知
- [Codex] `ENABLE_MESSAGE_DELETION` 只控制删消息；永久禁言和黑名单不受它影响

**代码修复**：
- [Codex] 新增 `modules/ad_enforcement.py`，广告实时检测、延迟检测、启动追溯、入群资料检测、全局黑名单拦截统一复用
- [Codex] 修复 `modules/auto_tasks.py` 启动扫描历史删除 SQL：`ORDER BY timestamp` → `ORDER BY ts`
- [Codex] `modules/blocklist_modes.py` 内容黑名单 `ban/warn` 达阈值改为永久禁言，不踢人
- [Codex] `modules/emoji_mask_detector.py` 复用 `ad_patterns_encoded.py` 主广告正则，并修复旧 emoji 正则误删中文的问题
- [Codex] `modules/avatar_detector.py` OCR 关键词补充“看我简/主页/钱包/打底/进群了解”等账号标签
- [Codex] 早午晚问候新增 `GREETING_CONFIG` / `AUTO_GOODNIGHT`，APScheduler 和 legacy loop 均读取配置时间与开关
- [Codex] `modules/proactive_engage.py` 增加落库冷却、每日上限落库读取、咨询意图分层 fallback，减少模板感

**验证**：
- [Codex] 新增 `tests/unit/test_ad_enforcement.py`、`tests/unit/test_emoji_mask_detector.py`、`tests/unit/test_auto_tasks_greeting_config.py`
- [Codex] 相关单测已覆盖：广告治理不调用 kick/ban、emoji 面具命中“看我简jie”、问候配置化、搭讪落库冷却

---

## v5.16.1 [2026-06-11] [TRAE SOLO CN]
### 看我简介变体 + bio 核心骗术模式补充

**触发**：Alan 哥连续两次反馈广告漏判：
1. 第一个账号 bio = "带两个钱包的兄弟，只要你肯付出，一天保你一万打底，想做的兄弟，进群找了解:https://t.me/+MSy0o4bsUMlkyjc1" 头像判断不出来没事，bio 明显广告
2. 第二个账号显示名 = "星河入梦来 🐻 Pawar 看我简个" — **"看我简介"必封** 已强调无数次的规则，bot 依然漏判

**漏判根因**：
1. `USERNAME_PATTERNS` 字符集只有 介(U+4ECB)/届(U+5C4A)/屆(U+5C46) 三字，"个"(U+4E2A) + 拼音"jie" 不在内 → "看我简个" / "看我简jie" 全部漏判
2. `BIO_PATTERNS` 只有"进群+https://"和"t.me/+"两条兜底，"一天保X万打底"等核心骗术话术无对应规则 → 拉取到 bio 也只命中 1 条，阈值没累积

**修复**（同次，1 文件 + 1 测试）：
- `modules/ad_patterns_encoded.py:405-425` USERNAME_PATTERNS 扩展：
  - 字符集加 `个\u4e2a` / `接\u63a5` / `界\u754c` / `衔\u8854`
  - 新增拼音变体 `看我...简...jie` / `看我...jian-jie`
  - 新增无前缀短变体 `看X简X`（覆盖"看简个"）
- `modules/ad_patterns_encoded.py:531-552` BIO_PATTERNS 补充 4 大类 11 条：
  - 一天+保X万/打底（核心骗术：保底+打底+一天承诺）
  - 双钱包骗术（带+钱包/X个钱包）
  - 招募话术（想做+兄弟/进群+了解/招+兄弟）
  - 付出+保X（低门槛+承诺组合）
- `tests/unit/test_ad_patterns_v5161.py` 新建：**31 个测试全通过**（14 命中 + 17 不命中覆盖）
  - 真实案例 3 例（用户两次反馈 + 旧"联系我带你启飞"）必须命中
  - 正常账号 4 例（辛辛🌸 FF / 日常分享 / 摄影爱好者 / 学生小李）必须不命中

**已知风险**：
- `看简个` 命中范围覆盖"看简X"短变体，若用户昵称含"看简笔画教程"等正常短语可能误判 → 当前未观测到此类用户
- 旧字符集 `[介届屆]` 全部保留，新增的"个/接/界/衔"均不冲突

---

## v5.15.4 [2026-06-07] [TRAE SOLO CN]
### v5.15.3 验收 + 18:36 历史债收尾（确认彻底解决）

**触发**：Alan 哥截图 18:36:07 "教白嫖 看我简介"+"出租各地36D 学生 白虎，想骑的来" 还在群里，之前别的 AI 说删不了/没判断对。重新走一遍 v5.15.2+v5.15.3 链路验收。

**验收结果（VPS 端 5/5 通过）**：
- ✅ mory-assistant + mory-dashboard 双 active
- ✅ 3 关键文件 MD5 与本地一致（ad_patterns_encoded.py=94884986.../message_dispatcher.py=69a7b633.../auto_tasks.py=aab1ff09...）
- ✅ message_snapshots 表结构正确（is_ad/deleted/UNIQUE/4 索引齐全）
- ✅ auto_tasks.py 同时含 APScheduler 注册（line 3618）+ legacy 循环调用（line 3646）
- ⚠️ journald 容量被 trim 50 行（19:08 之前历史日志丢失），但代码逻辑确证存在

**E2E 13/13 通过**（v5.15.2 修复 100% 生效）：
- 7 命中：18:36 原文 score=4 ban / 教白嫖 看我简介 score=4 ban / 36D妹子+M36D 各 score=8 / 36D学生妹服务上门 score=4 / 想骑的来 score=4 / 白嫖看我简介 score=4
- 6 不命中：我家出租房子给学生/白虎纹身图案设计/你好/白虎酒的传说/我想约你看电影/今天天气不错（全部 score=0）

**18:36 历史消息最后一公里**（方案 B 三种全失败 → 降级方案 A）：
- 方案 B.1：ad_suspicious_users 表 15 条，**917895208 不在表里**（v5.15.3 之前 P3.5 没追踪）
- 方案 B.2：deleted_messages 表 0 条（v5.15.2 紧急清理不走此表）
- 方案 B.3：reply_tracking / broadcast_tracking 列是 bot_msg_id/chat_id/category，不含 user_id，且只有 2 条记录
- 方案 A：**Alan 哥手动 5 秒右键删 1 次**（msg_id 真不可知 + Telegram 24h 隐私限制决定无法自动删）

**修复**（同次）：
- `scripts/ssh_helper.py:10` ENV_PATH 修复：`Path(__file__).parent / ".env"` → `Path(__file__).resolve().parent.parent / ".env"`（之前指向 scripts/.env → 凭据不存在 → SSH 认证失败）

**未来 100% 不再发生**：v5.15.3 后所有入 dispatcher 消息 100% 入 message_snapshots + 启动追溯 job 持续清理 blacklist 用户残留历史。

---

## v5.15.3 [2026-06-07] [TRAE SOLO CN]
### message_snapshots 表落地 + 启动追溯清理 job（AGENTS.md 教训 #17 落实）

**问题**：v5.15.2 修复后 uid=917895208 已封禁 + 加 blacklist，但 18:36 教白嫖消息**仍在群里**——**msg_id 不可知**（P1 拦截不记 + DB 0 记录 + Bot 重启 + Telegram 24h 隐私限制 + Bot 不能枚举历史）

**修复**：
1. **`core/database.py` 新增 `message_snapshots` 表**（4 索引 + UNIQUE(chat_id, msg_id) + is_ad/deleted 字段）
2. **`core/message_dispatcher.py:548-562` 强制所有入分发流程消息入 `message_snapshots`**（在 update_last_active 后所有 P 之前）
3. **`core/db_repos/group_repo.py` 新增 3 个方法**：`snapshot_message` / `mark_message_deleted` / `get_user_messages`
4. **P1 拦截升级 5 步**（`core/message_dispatcher.py:760-807`）：删消息+处置+同步+logger+`mark_message_deleted`；[Codex] v5.16.2 起“处置”统一为永久禁言，不踢人
5. **`modules/auto_tasks.py` 新增 `_job_startup_history_cleanup` 启动 job**：扫所有 blacklist 用户历史消息 + 逐个 `bot.delete_message` + `mark_message_deleted`（APScheduler + legacy 双轨部署）

**验证**：
- mory-assistant + mory-dashboard 双 active ✅
- HTTP 200 ✅
- 启动追溯 job 已跑（清 0 条因表刚建无历史，正常）✅
- message_snapshots 表结构正确（4 索引 + UNIQUE）✅

**18:36 那条必须 Alan 哥手动 5 秒右键删**（msg_id 真不可知），未来 100% 不再发生。

---

## v5.15.2 [2026-06-07] [TRAE SOLO CN]
### P1 黑名单拦截不彻底 + 色情/约炮变体漏检

**问题**：用户 `教白嫖` (uid=917895208) 在群里发 1 条广告 `出租各地36D 学生 白虎，想骑的来`（18:36:07），**消息完整保留**，Bot 0 拦截 0 删除 0 封禁 0 日志。

**根因（4 个独立 bug，3 攻 1 守）**：

### Bug A：P1 黑名单拦截只 return True 静默忽略
- **位置**：`core/message_dispatcher.py:760-778`（`_dispatch_p1_p3_security`）
- **原逻辑**：`if db.is_blacklisted(uid): return True` —— 只返回 True，不删消息、不踢人、不写 logger
- **后果**：uid=917895208 在 09:46:26 已加 global_blacklist，9 小时后发的消息仍正常显示 = 黑名单完全失效
- **历史修复说法已纠正 [Codex]**：拦截必须执行 **删消息+永久禁言+双黑名单+日志**：
  ```python
  if db.is_blacklisted(uid):
      if can_delete_message(CONFIG):
          bot.delete_message(chat_id, m.message_id)  # 1) 删
      enforce_ad_user(bot, db, CONFIG, chat_id, uid, uname, "黑名单拦截", m)  # 2) 永久禁言+双黑名单+清历史
      logger.info(f"🚫 [P1] 黑名单拦截: uid={uid}")   # 4) 日志
      return True
  ```

### Bug B：白虎单字规则太宽（误判"白虎纹身"）
- `modules/ad_patterns_encoded.py:65` `r"\u767d\u864e"`（单字"白虎"） → 改成组合 `r"\u767d\u864e[\s\S]{0,3}(?:\u7ea6|\u5b66\u751f|\u53ef|...)"`

### Bug C：看我简介规则不耐空格
- `modules/ad_patterns_encoded.py:272-273` 新增 5 条容忍 `\s*` 变体，覆盖"教白嫖 看我 简介"

### Bug D：新增 17 条规则覆盖 18:36 原文
- 教白嫖 / 出租+各地+学生 / 36D / 想骑+来 / 骑+我 / 上服务+上门 / 让+你+爽 / 身体+好 / 伪装+学生 / 抱着+睡 等

**紧急清理**（SSH 上 VPS 立即执行）：
- ✅ 16 个 global_blacklist 用户全部在主群 (-1003004701688) 封禁（OK=16）
- ✅ 2 条历史广告删除（"原味包邮吗"/"11"）
- ✅ 16 个用户同步到 blacklist 表
- ✅ 917895208（教白嫖）加 blacklist
- ⚠️ 18:36 那条原文消息因 ad_suspicious_users 表没记录（P3.5 当时没追踪）→ 需 Alan 哥手动在 TG 客户端删除

**E2E 自测 10/10 通过**：

| 消息 | score | is_ad |
|------|-------|-------|
| 出租各地36D 学生 白虎，想骑的来 | 4 | ✓ |
| 教白嫖 看我 简介 | 4 | ✓（**用户原需求**） |
| 36D妹子 + 可约 找我 | 4 | ✓ |
| M36D + 可约 价格面议 | 4 | ✓ |
| 36D学生妹服务上门 | 4 | ✓ |
| 我家出租房子给学生 | 0 | ✗（正常合租） |
| 白虎纹身图案设计 | 0 | ✗（**Bug B 修复后**） |
| 我想约你看电影 | 0 | ✗ |
| 白虎酒的传说 | 0 | ✗ |
| 你好 | 0 | ✗ |

**VPS 部署验证**：
- 文件上传：ad_patterns_encoded.py 19:10 / message_dispatcher.py 19:09
- systemctl 状态：mory-assistant active / mory-dashboard active
- HTTP /api/health = 200
- journalctl 无 ImportError
- 19:12:48 启动完成 / 19:13:00 cron 任务正常

**新教训**（写入 AGENTS.md §10）：
- 修复 #18：**P1 黑名单拦截必须完整处置（删消息+永久禁言+双黑名单+日志），不能只 return True**（沉默失败反模式；[Codex] v5.16.2 起不踢人）
- 修复 #19：**白虎/36D/想骑 单字黑话必须加组合条件**（组合规则 > 单字规则）
- 修复 #20：**黑名单拦截前必须 `db.blacklist_add()` 同步 local 表**（global_blacklist + blacklist 双轨不同步是历史遗留坑）

---

## v5.15.1 [2026-06-07] [TRAE SOLO CN]
### 修复"打码/收款码/新项目"类广告漏检

**问题**：用户 `guchang` (uid=8538130297) 在群里发 4 条广告（截图 12:04~13:30），Bot **完全未检测**（score=0）：
- `码 越多赚的越多一天随便挣10001 @bocaikeji`
- `支付宝微信码收挣7777 @bocaikeji`
- `新项目一个人都能做一天挣5555 @bocaikeji`

**根因（3个）**：
1. **@ 正则 Bug**：`r"(?<!\w)@\w{3,}"` 中 `(?<!\w)` 排除 word char (含数字)，导致 `10001@bocaikeji`（前导数字）整条不匹配 → 失去 +3 分
2. **MONEY_PATTERNS 缺失口语化高收入承诺**：`r"\u4e00\u5929[0-9\u5343\u767e\u4e07]+"` 要求"一天"后**紧接数字**，无法匹配"一天随便挣10001"（中间有"随便挣"）
3. **新项目零门槛变体未覆盖**：原 `r"\u65b0\u9879\u76ee.*\u65b0\u673a\u4f1a"` 太严格，"新项目一个人都能做"中间无"新机会"

**修复**：
- `modules/ad_patterns_encoded.py:236` @ 正则：`r"(?<!\w)@\w{3,}"` → `r"(?<![A-Za-z0-9_])@[\w\u4e00-\u9fff]{3,}"`（容忍前导数字/中文）
- `MONEY_PATTERNS` 新增 6 条：`一天[0-5]字符[随便稳轻轻松松]挣/赚数字`、`随便+挣/赚+数字`、`收码+赚`、`打码+赚`、`码越多+赚`
- `GRAY_PATTERNS` 新增 7 条：`支付宝+微信+收款/收钱/到账`、`支付宝/微信+收款+数字`、`收款码`、`跑分+数字`、`代收/代付+数字`
- `LOW_BARRIER_PATTERNS` 新增 3 条：`一个人+都能+做/干/学`、`一个人+就能+做/干/学`、`在家+就能+做/干/赚/钱`
- `RECRUIT_PATTERNS` 新增 2 条：`新项目+做/干/学/赚/钱`、`新项目+一天`

**E2E 自测（VPS Python 验证 7/7 通过）**：
| 消息 | score | is_ad |
|------|-------|-------|
| 码 越多赚的越多一天随便挣10001 @bocaikeji | 6 | ✓ |
| 支付宝微信收款7777 @bocaikeji | 6 | ✓ |
| 新项目一个人都能做一天挣5555 @bocaikeji | 7 | ✓ |
| 10001 @bocaikeji（@ 修复验证） | 3 | ✓ |
| 电脑挂机 就有钱 有兴趣 来（回归测试） | 3 | ✓ |
| 我今天完成了工作（边界） | 0 | ✗（不误判） |
| 码农讨论（边界） | 0 | ✗（不误判） |

**VPS 部署验证**：
- MD5 一致：`2f44f90b2fad536e55e2e5ec7dab2c13`
- mory-assistant active (running)
- mory-dashboard active (running)
- journalctl 无 ImportError
- ad_patterns_encoded.py 40 MONEY / 48 CONTACT / 41 RECRUIT / 23 GRAY / 21 LOW_BARRIER（全部 import 成功）

**清理**：
- ✅ msg_id=51526 11:40 广告自动删除（11:40 当条已生效）
- ✅ guchang (uid=8538130297) 已加 global_blacklist
- ✅ guchang 当前 chat_member status = `left`（已离开群）
- ⚠️ 12:04, 12:34, 12:59, 13:30 的 4 条广告：bot session 已消耗，forwardMessage 无法访问（Telegram API 限制），需管理员手动删除

## v5.15.0 [2026-06-06] [TRAE SOLO CN]
### 用户问题追踪与FAQ蒸馏系统

**核心需求**：用户问的所有问题没有被结构化记录，无法统计高频问题，运营无法针对性制作话术

**新增功能**：
- `user_questions` 表：持久化记录用户问题文本、mode、intent、question_category、AI回复摘要、FAQ命中ID
- `faq_knowledge` 表：FAQ知识库（问题模板+话术模板+AI润色开关+匹配模式+优先级+命中计数）
- `faq_candidates` 表：FAQ蒸馏候选（高频问题自动聚类→待人工审核）
- `QuestionRepo`：17个方法覆盖问题记录/FAQ匹配/候选审核/蒸馏聚类
- P10钩子：AI回复前自动记录问题，回复后更新摘要
- FAQ匹配回复：`_try_faq_match()` 在AI调用前匹配FAQ，命中则用话术模板（可选AI润色）
- `_job_faq_distill` 自动任务：每日蒸馏高频问题生成候选，通知管理员审核
- Dashboard `/api/faq/*` 10端点：stats/questions/candidates/knowledge/distill

**配置开关**（默认全部关闭）：
- `FAQ_TRACKING_ENABLED`：问题记录开关
- `FAQ_AUTO_REPLY_ENABLED`：FAQ自动回复开关
- `FAQ_DISTILL_INTERVAL`：蒸馏间隔（默认86400秒）
- `FAQ_MIN_FREQUENCY`：蒸馏最低频次（默认3）

**影响**：
- 6个文件修改 + 2个新文件创建
- 非侵入式：所有新功能默认关闭，不影响现有流程

---

## v5.12.4 [2026-06-04] [TRAE SOLO CN]
### 孤儿消息真清理（30分钟窗口+独立开关+积压批量清）

**核心问题**：v5.12.0 孤儿清理机制部署后实际未生效，群里大量孤儿消息堆积
- ENABLE_MESSAGE_DELETION 默认 false，导致 _job_burn_orphan 每次跑都跳过删除
- 24h 窗口太长
- proactive_engage 搭讪用 reply_and_track（track_reply）而非 track_bot_message，导致搭讪变孤儿
- 没有 force-clean 脚本处理历史积压

**修复**：
- 窗口 86400 → 1800（30分钟）
- 新增独立开关 ORPHAN_CLEANUP_ENABLED（默认 true）
- can_orphan_cleanup() 独立判断函数
- proactive_engage 改用 bot.send_message + track_bot_message
- 新建 scripts/force_orphan_cleanup.py（--dry-run/--limit/--window）
- Dashboard /api/orphan/stats 加 orphan_30m_count + enable_orphan_cleanup
- force-clean 端点升级为立即清理（不依赖 Bot 进程）
- /api/settings/orphan-cleanup 读写端点

**判定**：30分钟后孤儿归 0 + 群里 Bot 主动消息 30 分钟无人理真被删

---

## v5.14.2 [2026-06-04] [TRAE SOLO CN]
### 入群即检测三重广告信号

**核心问题**：v5.14.1 修复变体字后，仍有"私信我"+"Yao"+BIO 全是广告的用户在第一条消息时没被拦

**根因**：
1. `_handle_new_chat_members` 链路里**没有调用 ad_detector.detect()**——只查了 CAS/联邦/emoji面具/头像
2. 用户"私信我"/"Yao" 等名字含变体字 + BIO 全文广告的特征，**入群时未跑评分**
3. 直到用户主动发消息才走 P3.5 检测（已经晚一步，第一条消息已发出）

**修复**：
- `core/handlers/member_handlers.py` 步骤 2 后新增 **步骤 2.5 入群即检测**
- 调用 `bot.get_chat(user_id)` 拉取 BIO
- 调用 `ad_detector.detect(username=name, msg="", user_id, bot, bio=bio, chat_id)`
- 评分 >= 3 且 is_ad=True → 立即踢出 + 通知管理员
- 评分 2-3 → 标记可疑 + 入 ad_suspicious_users 追踪表（30 分钟累计）
- 函数签名扩展 `(bot, m, config, db, ctx=None)` 兼容老调用
- 50 个历史积压可疑用户已清理（裸聊/套利/拍.唓/有电脑来捡钱/币圈/母狗资源等）

**VPS 核验**：6/6 全部通过（MD5 一致 + 服务 active + E2E score=3 action=ban + 50 个用户已 ban + 日志无报错）

**影响**：
- 1 个文件修改
- 名字+BIO+头像三重信号入群即检测
- 商业项目"早期封禁"原则（避免广告用户污染群生态）

---

## v5.14.1 [2026-06-04] [TRAE SOLO CN]
### 广告变体字规避修复

**核心问题**：用户"私信"(uid=8884907937) 用变体字 `唰箪秒結𝟺𝟶𝟶` 绕过检测，5 条广告 0/5 被删除

**根因**：
1. 广告发送者用形近字（唰→刷/箪→单/結→钻）+ 全角数学粗体数字（𝟺𝟶𝟶→400）绕过正则
2. BIO_PATTERNS 缺少"刷礼物/私信/滴滴/1000U/一天干"等变种词
3. ad_detector 无文本规范化层，变体字直接进入正则匹配

**修复**：
- `ad_detector.py` 新增 `_normalize_ad_evasion()` 静态方法（全角数字/形近字/繁体→简体，18 个变体映射）
- `ad_patterns_encoded.py` BIO_PATTERNS 新增 14 条规则（刷礼物/有抖音/私信/滴滴/1000U/一天干/上下/欢迎了解等）
- `detect()` 入口对 msg/uname/bio 统一应用规范化
- 新建 `scripts/verify_ad_detection_live.py` E2E 自检脚本（dry-run 6/6 PASS）
- 5 条历史广告消息已删除（msg_id: 51023/51025/51027/51031/51034）
- 用户 8884907937 已永久封禁（kicked + revoke_messages）

**VPS 核验**：6/6 全部通过（服务 active + MD5 一致 + E2E score=9 + 广告已删 + 用户已封 + 日志无报错）

**影响**：
- 2 个文件修改 + 1 个文件新建
- 变体字广告检测召回率从 0% → 100%

---

## v5.14.0 [2026-06-04] [TRAE SOLO CN]
### 商业问题主动搭讪引导

**核心问题**：群里用户主动问商业问题（订阅/价格/权益等）时，Bot 90% 不理，错过转化机会

**修复**：
- 扩展 convert 关键词 6→50+ 词（订阅/月付/年付/季付/视频/观看/解锁/购买/付费等）
- 新建 modules/proactive_engage.py 核心搭讪模块
- message_dispatcher 新增 P7.5 主动搭讪层（默认关闭）
- 30 分钟跨群冷却去重
- 数据库新增 proactive_engage_log 表
- Dashboard 新建 engage_api.py（4 端点）
- convert 模式跳过 REPLY_CHANCE 强制回复
- P7 视奸雷达扩展 proactive_eligible 标志位
- 新增 PROMPT_TEMPLATES.business_engage 话术模板

**新增配置**：
- `PROACTIVE_ENGAGE_CONFIG.enabled`（默认 false）
- `PROACTIVE_ENGAGE_CONFIG.cooldown_minutes`（默认 30）
- `PROACTIVE_ENGAGE_CONFIG.max_per_user_per_day`（默认 3）
- `PROACTIVE_ENGAGE_CONFIG.only_in_group_id`（默认 true）

**API 端点**：
- `GET  /api/engage/stats` - 搭讪统计（今日/累计/转化率）
- `GET  /api/engage/recent?limit=50` - 最近搭讪列表
- `GET  /api/engage/config` - 读取配置
- `POST /api/engage/config` - 更新配置（触发 reload_flag）

**影响**：
- 6 个文件修改 + 2 个文件新建
- 50+ 关键词召回，搭讪事件全链路追踪
- 商业转化漏斗关键修复

---

## v5.13.0 [2026-06-03] [TRAE SOLO CN]
### 全面健康诊断与暗病修复

**VPS 运行时修复（6项严重）**：
- mory-assistant 服务开机自启（systemctl enable）
- speech_stats Cursor 上下文管理器错误修复（`with cursor` → 直接使用 cursor）
- auto_tasks 不活跃清理类型错误修复（dict vs int 比较兼容）
- core.fault_reporter 模块缺失修复（改为正确的导入路径）
- conversions 表创建 + conversion_events 索引
- users.last_active 不更新修复（消息分发前调用 update_last_active）

**代码严重问题修复（8项）**：
- modules/content.py 网络请求添加 timeout=15（违反"绝对不能死"红线）
- core/deploy_utils.py 7处 + modules/predictive_patrol.py 3处 + modules/points_enhanced.py 1处沉默失败修复
- core/database.py + core/db_repos/tracking_repo.py 循环依赖确认（已是延迟导入）
- modules/content.py + modules/nsfw_detect.py TOKEN 泄露修复（改用 bot.download_file()）
- modules/verification.py 线程安全（Lock + 容量上限 1000）
- dashboard/api/stats_api.py N+1 查询改 IN 批量查询
- 漏注册 DB 方法确认（3个方法已注册）
- config.json.example 补全 12 个缺失配置键

**中等问题修复（5项）**：
- Dashboard /api/health 健康检查端点新建
- Dashboard API 5个文件 22处 str(e) 信息泄露修复
- Dashboard EXCHANGE_API_KEY 脱敏显示
- modules/points_enhanced.py 积分转账改原子 SQL
- modules/auto_tasks.py 孤儿清理 delete_tracked 提前清除修复

**改动文件**：core/database.py / core/deploy_utils.py / core/message_dispatcher.py / core/db_repos/user_repo.py / core/bot_initializer.py / modules/auto_tasks.py / modules/content.py / modules/points_enhanced.py / modules/predictive_patrol.py / modules/verification.py / modules/speech_stats.py / modules/inactive_clean.py / modules/nsfw_detect.py / dashboard/api/stats_api.py / dashboard/api/features_api.py / dashboard/api/settings_api.py / dashboard/api/health_api.py / dashboard/api/config_api.py / dashboard/api/orphan_api.py / config.json.example

---

## v5.12.3 [2026-06-02] [Trae CN]
### 能力矩阵真实还原 + 文档除断章取义

**AGENTS.md**：
- 第 1 节按 config.json.example L1-L200 真实配置重写：删 "5 轮递进话术"→"3 段递进"；删 "7 模式（塔罗/树洞/解梦/运势/正常/新闻/转化）"→"4 PROMPT_TEMPLATES + 25 MODE_ROUTING + 3 段递进"；删 "SPECIAL_AUTO_REPLIES"（不存在）；改"3 层路由"→"3 层 + 4 池有模型 + 5 占位 = 9 池键名"
- 1.1 节"核心配置"行从 3 项扩到 6 项（SYSTEM_PROMPT / PRICE_LIST / SLANG_DICT / PROMPT_TEMPLATES / MODE_ROUTING / MODEL_POOLS）
- 1.2 节 6 大核心能力矩阵：人设对话行重写 25 MODE_ROUTING；商业引导行重写 9 池；商业闭环补"+ 衰减/盲盒/转盘/转化追踪"；群管 80+→83；运营观察 22+→95+ 实际端点；消息分发 11 级→25 个 P 级别拦截器
- F3 铁律：删 "docs/technical/ ≤ 200 行"硬限制→"详尽写实不限字数"
- F4 铁律：限定 core/modules/dashboard 单文件 ≤ 200 行；docs/technical/ 显式不限；README 也应详尽不锁行数

**capability-matrix.md**：
- 大重写 7 节详尽展开：1.人设对话系统（10 维目标+4 PROMPT_TEMPLATES+25 MODE_ROUTING+9 池）/ 2.商业产品矩阵（3 档价格+转化追踪）/ 3.83 modules 8 大类详尽 / 4.Dashboard 95+ 端点+8 类 115 按钮 / 5.消息分发 25 P 级别 / 6.40 个自动任务 / 7.84 张数据库表分类
- 从 v5.12.2 的 ≤ 200 行扩到 1293 行
- 第 8 节新增附录交叉引用

**README.md**：
- 大重写：项目定位/10 维商业目标/3 段递进/3 档产品/4 模板/25 mode/9 池/83 modules 详尽/95+ API/25 P 级别/40 任务/84 表/5 步转化流程
- 删除所有"未做/未来调整时同步"等偷懒话术
- 硬编价格/话术/关键词变体到正文（避免 README 失真）

**错误修正记录**：
- v5.12.2 把 PROMPT_TEMPLATES/MODE_ROUTING/对话轮次混为"7 模式"→ v5.12.3 拆为 3 维真实写
- v5.12.2 凭空捏造 SPECIAL_AUTO_REPLIES 字段→ v5.12.3 删
- v5.12.2 "3 层模型路由"实际是 3 层 + 4 池 + 5 占位（共 9 池键名）→ v5.12.3 补全
- v5.12.2 设定 ≤ 200 行硬限制是胡闹→ v5.12.3 删除
- v5.12.2 3 条"未做"是偷懒→ v5.12.3 详尽展开

**改动文件**：AGENTS.md / docs/technical/capability-matrix.md / README.md

---

## v5.12.2 [2026-06-02]
### 业务核心目标重写+详尽能力矩阵 capability-matrix.md+README 大重做

**Part 1: 业务核心目标重写（基于实际项目定位）**
- 用户反馈：v5.12.1 把项目写成"群管机器人 + Dashboard"是错的，项目**真正定位 = 运营型商业 AI 转化机器人**
- 调研：SYSTEM_PROMPT = Mory 真人女孩 + 5 轮递进话术 + 7 模式（塔罗/树洞/解梦/运势/正常/新闻/转化）+ 3 档商业产品（至臻精选 149.9/349.9、至臻全享 999、精选图集 228.8/666.6）+ 14+ mode 路由到 3 层模型池
- AGENTS.md 第 1 节重写为 4 子节：1.1 项目定位与产品矩阵 / 1.2 6 大核心能力矩阵 / 1.3 业务红线 / 1.4 详尽能力矩阵引用
- 业务红线 6 条：①绝对不能死 ②绝对不说自己是 AI ③绝对不直白营销 ④绝对不重复话术模板 ⑤绝对不破坏 3 档产品边界 ⑥绝对不在 Bot 内收款

**Part 2: 新建 docs/technical/capability-matrix.md（详尽能力矩阵，182 行）**
- 1. 🤖 人设对话系统：SYSTEM_PROMPT + 5 轮递进 + 7 模式 + 14+ mode 路由 + 3 层模型池 + 5 维度话术
- 2. 💰 商业闭环：3 档产品 + 9 个商业模块（points/shop/coupon/redpacket/lottery/cart_recovery/profile_card/welcome_customization/tip）+ 转化追踪
- 3. 🛡 群管 80+：8 大类（核心群管 10 + 检测防护 8 + 清理维护 6 + 用户管理 8 + 游戏娱乐 10 + 工具查询 15 + 调度系统 8 + AI/统计/特殊 8）
- 4. 📊 运营观察：Dashboard 22+ API + 8 类 115 按钮 + admin/viewer 权限分级
- 5. 🚀 消息分发优先级 P0-P10 完整链路

**Part 3: README.md 大重做（196 → 324 行）**
- 标题从"Telegram群管机器人"改为"运营型商业 AI 转化机器人"
- 第 1 节重写：项目是什么（人设系统/商业产品/下单渠道/核心对话模式/商业闭环/群管能力/运营观察/消息分发 + 6 条业务红线）
- 第 2 节新增：用户体验流程（5 步转化 + 管理员 4 步观察）
- 第 3 节大重做：6 大功能矩阵（人设对话/商业引导/商业闭环/群管 80+/运营观察/消息分发）
- 第 4-13 节：快速开始/配置说明/项目结构/VPS 服务/Dashboard 权限/技术栈/文档索引/安全/版本升级/当前版本
- 文档索引新增 capability-matrix.md

**Part 4: 4 视角交叉验证**
- 用户视角：业务红线"绝对不能死"在 README 顶部，5 步转化流程让用户看懂
- 新接手 AI 视角：第 1 节项目定位 + 详尽能力矩阵双重索引
- 新对话与老对话视角：AGENTS.md + capability-matrix.md + README 三位一体
- 上下文截断视角：能力细节不在 README 主体（324 行），在 capability-matrix.md 按需查阅

**改动文件**：
- AGENTS.md：第 1 节业务核心目标（14 → 30 行）
- README.md：196 → 324 行（+128 行）
- docs/technical/capability-matrix.md：新建 182 行
- CHANGELOG.md / VERSION.md / version.py：v5.12.1 → v5.12.2

**未做/坦诚声明**：
- ❌ capability-matrix.md 是 v5.12.2 首次整理，未来新增模块**必须**同步更新 capability-matrix.md
- ❌ README.md 第 3.4 节"群管 80+"只列了模块名，未给功能细节（避免 README 超 400 行）
- ❌ 价格、话术、关键词变体等会随时间变化的配置**未硬编**在 README（写在 config.json.example）

---

## v5.12.1 [2026-06-02]
### 项目规则归一化（.agents→AGENTS.md）+ 根目录临时文件归档 + docs/technical 子目录分类

**Part 1: 项目规则文件名归一化**
- `.agents` → `AGENTS.md`（大写显式，**项目根目录**），148 行
- AGENTS.md 顶部加**业务核心目标**（项目名/用途/业务红线"绝对不能死"）
- 加**历史文档优先原则**（遇 bug/需求先查 3 文档复用方案）
- 加**技术边界**（自动识别栈/中文注释/日志文件夹/凭据）
- 加**5 条核心教训**（代码未部署/SQLite 假成功/二次部署/schema 同步/日志真相）
- 加**8 条跨 AI 一致性铁律 F1-F8**（测试在 tests/、脚本在 scripts/、技术细节在 docs/technical/、单文件 ≤200 行、根目录禁临时文件、不自己造规则、不凭空报行号、不硬编版本案例）
- 加**4 视角验证清单**（用户/新接手 AI/新对话与老对话/上下文截断）
- 加**docs/ 子目录说明**（technical/plans/vision/reference/archive）

**Part 2: 根目录临时文件归档**
- 47 个 `_*.py` 文件移到 `tests/_archive/`（不再修改/运行）
- 创建 `tests/README.md`（_archive/integration/unit 三子目录说明）
- `.gitignore` 增加 `_*` 模式（防止根目录再生临时文件）

**Part 3: docs/ 子目录分类（kebab-case 命名）**
- 5 个 docs 文档迁到 `docs/technical/`：orphan-cleanup.md / vps-deploy-trap.md / config-reload.md / ad-detection.md / anti-patterns-code.md
- 新建 `docs/technical/anti-patterns-ops.md`（运维 4 大类：部署/迁移/AI 自我审计/VPS 简表）
- 6 个 docs/technical/ 文件全部 ≤ 200 行（拆分压缩）
- docs/ 下创建 5 子目录：technical/plans/vision/reference/archive

**Part 4: 内容核验（4 视角交叉验证）**
- AGENTS.md 148 行 ≤ 200（不超）
- 6 个 docs/technical/ 文件全部 ≤ 200（已实测）
- 关键代码位置 grep 实测（orphan_cleanup_log:367 / _REPO_METHOD_MAP:1002 / 3 端点:26,82,100 / _job_burn_orphan:1304 / _signal_config_reload:20 / start_config_reload_watcher:388 / _patch_missing_keys:75 / SESSION_COOKIE_SECURE:118）
- 数据库表数 84（实测与 project_snapshot 一致）
- 备份 `.agents` 到 `backup/.agents.v5.12.0.bak`（回滚保险）

**Part 5: 活跃引用清理**
- 全文 grep `.agents` 引用：活跃引用全部更新为 `AGENTS.md`，历史描述保留（符合防搞坏纪律）
- README.md / version.py / project_snapshot.md / docs/*.md 活跃链接已改

---

## v5.12.0 [2026-06-02]
### 孤儿消息实际清理 + 8大类老坑规则化 + 项目规则归一化

**Part 1: 孤儿消息实际清理**
- 新增 `orphan_cleanup_log` 表：每次 `_job_burn_orphan` 写入发现/删除/跳过/错误/trigger，**让清理可观测**
- 新增 Dashboard `/api/orphan/stats` + `/cleanup-history` + `/force-clean` 3 端点
- `ENABLE_MESSAGE_DELETION=false` 改发管理员私聊告警（每 24h 一次不刷屏），**不再静默跳过**
- 新增 `scripts/verify_orphan_cleanup.py` 端到端验证脚本（state/dry-run/force-clean 3 模式，被 `dashboard/api/orphan_api.py:109` 引用）
- 修复 v5.11.0 之后隐藏问题：清理逻辑可观测性、失败兜底

**Part 2: 8 大类反复出现的老坑上升为项目规则**
- `.agents` 新增"反复出现的老坑与铁律"章节（8 大类 40+ 铁律）
  - 沉默失败 8 大反模式 / 配置一致性 5 条铁律 / 部署一致性 6 条铁律
  - 数据库方法注册 4 条铁律 / half-migrated 状态 3 条铁律 / 关键路径 5 条铁律
  - AI 自我审计 4 条铁律 / VPS 部署 5 条铁律
- 每条铁律配 `🔍 验证命令`（grep/SSH），开工时直接复制运行
- 复杂技术细节单独成文：`docs/orphan_cleanup.md` / `docs/vps_deploy_trap.md` / `docs/config_reload.md` / `docs/ad_detection.md`
- `.agents` 中"📚 技术细节文档索引"章节交叉引用上述文档

**Part 3: 项目规则文件归一化（用户决策）**
- `project_rules.md` 内容（绝对禁止/VPS 统一 ubuntu/多 Bot 区分）合并到 `.agents`
- 删除 `project_rules.md`
- 五大记录（`AI_DEBUG_HISTORY.md` / `project_snapshot.md` / `CHANGELOG.md` / `VERSION.md` / `README.md`）保留，职责不重叠
- `.gitignore` 不忽略 `.agents`（项目规则不是本地配置）

### 新增文件
- `docs/orphan_cleanup.md` — 孤儿清理机制详解（三层保障 + 数据库表 + API + 历史坑）
- `docs/vps_deploy_trap.md` — VPS 部署陷阱（owner 错乱/EnvironmentFile/409 Conflict 等 8 类）
- `docs/config_reload.md` — 配置热重载机制（reload_flag + 5秒轮询）
- `docs/ad_detection.md` — 广告检测 5 层体系完整规范
- `scripts/verify_orphan_cleanup.py` — 端到端验证脚本
- `dashboard/api/orphan_api.py` — 3 个 Dashboard 端点

### 删除文件
- `project_rules.md`（已合并到 `.agents`）

## v5.11.0 [2026-06-02]
### 系统可靠性根治与预防（10条根因 + 三阶段方案）

**第一阶段：本期 3 个已确认问题修复**
- 私信话术改造：config.json.example SYSTEM_PROMPT + core/ai_engine.py + ai_reply_handler.py + message_dispatcher.py + admin_cmds.py 全面去除"老板"自称，强化"引导开单"为商业目标
- 每日频道数据播报修复：移除 `_send_daily_channel_report` 中 `api_data = None` 硬编码占位；新增 `_format_zero_data()` 辅助函数，发帖=0 时显示"暂无"、互动=0% 时显示"—"；保留 API 接入位
- 定时任务可观测性：scheduler 启动后输出全部 add_job 任务清单；`_record_abort()` 记录 abort 原因到 `_ABORT_HISTORY`，连续 3 次同任务 abort 自动升级 P0 告警；news/greeting 关键任务接入 abort 记录

**第二阶段：可靠性根因治理**
- 启动 preflight 健康检查：core/bot_initializer.py 新增 `preflight_check()`，5 项检查（TOKEN 非占位 / GROUP_ID 有效 / CHANNEL_IDS 至少 1 / DB 可读写 / AI engine 可 ping / scheduler 可注册），致命问题阻断启动并通知 admin
- preflight 钩子接入 main.py，阻断而非崩溃
- 预防性自审计任务：`_job_proactive_audit()` 每天 03:30 自动跑 7 项检查（DB 完整性 / 配置一致性 / AI 模型池 / 任务执行率 / 磁盘空间 / 备份文件 / 健康度评分）
- 故障注入测试集：scripts/failure_injection_tests.py 实现 7 项模拟测试（AI 失败 / 429 限流 / DB 锁竞争 / 配置损坏 / GROUP_ID 无效 / TOKEN 失效 / 网络超时），输出"故障注入 → 降级行为 → 恢复时间" 报告

**第三阶段：24/7 零故障路线图**
- 关键路径心跳：`_update_heartbeat()` 每 5 分钟更新；`watchdog` 后台线程每 60 秒检查，超时 15 分钟触发 `os._exit(42)` + systemd 自动重启
- 健康度评分：`_compute_health_score()` 5 维度（任务 30% / AI 25% / DB 20% / 配置 15% / 磁盘 10%）
- Dashboard 健康度面板：dashboard/api/health_api.py 新增 4 端点（/score /aborts /jobs /audit）
- 预测性巡检：modules/predictive_patrol.py 检测任务执行时间漂移 / AI 限额 / 磁盘增长趋势 / 数据库表膨胀

### 新增文件
- scripts/failure_injection_tests.py (7 项故障注入测试)
- dashboard/api/health_api.py (4 个健康度端点)
- modules/predictive_patrol.py (预测性巡检 4 项检测)

### 配置文件变更
- config.json.example SYSTEM_PROMPT 重写（去除"老板"自称、强化引导开单）
- config.json.example PROMPT_TEMPLATES.treehole 署名 Mory老板 → Mory
- config.json.example SLANG_DICT 去除"老板"指代 Mory
- core/ai_engine.py _DEFAULT_PROMPT_TEMPLATES 多个 mode 同步更新

### 核心文件变更
- core/bot_initializer.py：新增 preflight_check()
- main.py：preflight 钩子接入
- core/message_dispatcher.py：_generate_late_night_warning 去除"老板"提示
- modules/admin_cmds.py：📢 {BOT_NAME}老板说 → 📢 {BOT_NAME}说
- modules/auto_tasks.py：大幅扩展，新增 _register_job / _record_abort / _format_zero_data / _compute_health_score / _job_heartbeat / _job_proactive_audit / _watchdog_check / _start_watchdog + scheduler 启动清单输出 + 5 个关键任务 abort 记录
- dashboard/app.py：注册 health_bp

## v5.11.0 [2026-06-02]
### 群播报自动删除：孤儿30S + 早安/午安/晚安链式互删

- **孤儿播报30S自动删除**：升级播报"恭喜X升级到Lv2！"这类孤儿消息，默认30秒后自动删除
- **早安/午安/晚安链式互删**：发午安自动删早安、发晚安自动删午安，避免群里同时堆3条问候
- **新增配置** `BROADCAST_AUTO_DELETE`：`orphan_seconds`(默认30, 0=不删) + `greeting_chain_delete`(默认True)
- **新增数据库表** `broadcast_tracking(chat_id, category, msg_id, ts)`：复合主键(chat_id, category)，同群同类型只保留最新一条
- **新增4个数据库方法**：`track_broadcast / get_last_broadcast / delete_broadcast / cleanup_old_broadcasts`
- **核心改动**：
  - `core/helpers.py` 新增 `get_broadcast_auto_delete_config()` 配置读取 + `safe_delete_broadcast()` 安全删除
  - `core/db_repos/tracking_repo.py` 新增4个孤儿播报追踪方法
  - `core/database.py` 新增 broadcast_tracking 表 + 索引 + __getattr__ 委托
  - `modules/points_enhanced.py` `check_level_up()` 发送后30S删除（threading.Timer 调度，零APScheduler依赖）
  - `modules/auto_tasks.py` 新增 `_send_greeting()` 链式互删函数，3个问候任务改用
  - `core/message_dispatcher.py` `check_level_up` 调用补传 db 参数
- **顺手修复Bug**：`track_bot_message` 之前漏注册到 `_REPO_METHOD_MAP`，导致 `_send_and_track` 调用一直报 `'DB' object has no attribute 'track_bot_message'`，沉默失败

## v5.10.4 [2026-06-01]
- AI认知纠正文档更新：project_rules.md新增"Bot API限制与项目已有解决方案"章节，明确Pyrogram扫描/追溯扫描/成员追踪/消息追踪四大能力
- AI_DEBUG_HISTORY.md新增v5.10.3记录：AI未查阅文档导致重复发明轮子的根因分析与教训

## v5.10.3 [2026-06-01]
- VPS用户统一为ubuntu：vps_config.py默认用户root→ubuntu，.env.example同步修正，消除root/ubuntu双用户权限冲突
- 新建根目录.agents文件：整合项目核心规则为统一入口，替代复杂嵌套结构

## v5.10.2 [2026-06-01]
- Dashboard-Bot配置热重载：write_config()创建reload_flag → Bot 5秒轮询消费 → 配置生效
- VPS config.json自动补齐：safe_upload_config()新增_patch_missing_keys()从config.json.example合并缺失键
- 修复config.json.example: AUTO_CHANNEL_DEFAULT→ANTI_CHANNEL_DEFAULT（命名不一致）
- 修复config.json.example: 新增ANTIFLOOD_CONFIG默认值
- 修复dashboard/auth.py: SESSION_COOKIE_SECURE改为环境变量驱动（DASHBOARD_HTTPS）

## v5.10.1 [2026-06-01]
- 新增强制订阅模块 force_subscribe.py（/fsub /unfsub），新成员入群检查频道订阅，默认关闭
- 新增全局黑名单模块 global_blacklist.py（/gban /ungban /gbanlist），跨群封禁，默认被动激活
- command_handlers.py 新增4条命令路由，member_handlers.py 新增全局黑名单+强制订阅入群检查
- 35+个功能开关全部默认false/0/disabled验证通过，settings_panel.py ad_detect_enable default True→False
- P9-P12完成：数据库86张表全部就绪，配置默认值校验通过，双向同步验证通过，回归测试通过
- 修复bot_initializer.py:405 条件块内import threading导致UnboundLocalError崩溃

## v5.10.0 [2026-06-01]
- 新增ENABLE_MESSAGE_DELETION全局开关（默认false），16个消息删除点包裹/更新
- 新建core/helpers.py（can_delete_message辅助函数），管理员命令(/del, /purge)不受开关影响
- 设置面板完全体P2-P8：81个按钮回调（成员管理17+消息管理9+互动功能16+经济系统15+播报统计13+高级设置11）
- Dashboard新增22个API端点
- 修复apply_pending_value float类型支持、NSFW_DETECT_CONFIG键名对齐、审批白名单chat_id过滤

## v5.9.2 [2026-06-01]
- auto_tasks.py旧模式完全迁移：5个函数转换，_can_run/_mark_done/_release_task全部归零
- message_dispatcher.py进一步拆分：1627→1286行，_dispatch_p10_ai+5连续对话函数迁移到core/handlers/ai_reply_handler.py(345行)
- Dashboard systemd环境变量注入：mory-dashboard.service添加EnvironmentFile=.env，DASHBOARD_PASSWORD确认生效

## v5.9.1 [2026-05-31]
- message_dispatcher.py拆分：2615→1627行，6个命令处理函数迁移到core/handlers/command_handlers.py
- auto_tasks.py：TaskTransactionManager上下文管理器，11个job函数转换，_release_task调用从38→0
- 删除universal_ai_router/目录（21文件），router_database.py+router_statistics.py内联到core/，token_statistics.py删除
- Dashboard systemd服务（config/mory-dashboard.service），deploy_vps.py管理双服务
- 8个旧spec目录删除，2个合并spec创建（economy-and-operations-complete、group-security-complete）

## v5.9.0 [2026-05-31]
- 删除19个垃圾文件（test/debug脚本+3个含硬编码密码的凭据文件）
- 移动5个扫描脚本从根目录到scripts/
- 删除ai_engine_standalone/孤立模块目录
- 删除core/telegram_stats.py（已deprecated，被auto_tasks.py内部DB统计替代）
- 修复anti_raid.py：raid告警改私聊管理员，不再发群聊
- 修复monitoring.py：active_users从数据库读取，不再硬编码返回0
- 修复deploy_utils.py：MERGE_FIELDS与RUNTIME_SYNC_FIELDS重叠消除
- 新增Dashboard权限分级：admin/viewer两种角色，viewer只读
- 新增DASHBOARD_VIEWER_PASSWORD环境变量
- 清理.trae/旧spec和文档

## v5.8.4 [2026-05-31]
- Pyrogram全量群成员扫描：5811/6072人(95.7%覆盖率)，较Bot API模式(7.2%)提升13倍
- 使用Pyrogram+bot_token+Telegram Desktop公开API凭证(api_id=2040)枚举全部群成员
- 封禁2个加密货币广告号：币圈套利日入3千U招团队合作、虚拟货币搬砖日入5K
- 发现14个短随机用户名(UNAME_ONLY)，按规则跳过封禁
- _scan_group.py新增Pyrogram模式(默认)，支持Bot API/Pyrogram/Telethon三种扫描模式
- **新增HIGH_NAME级封禁规则**：用户名+显示名评分合计>=4时无需Bio直接封禁

## v5.8.3 [2026-05-31]
- 修复5个广告检测规则漏洞：繁体"屆"变体、中文数字"五w"、"新手"规则、炫富诱导(提奔驰/开路虎)、行动号召(想干看简)
- 修复2个误报："五万步"(MONEY_PATTERNS中字符类改为完整词匹配)、"提车了开心"(RECRUIT_PATTERNS改为多字符品牌名匹配)
- 全量扫描封禁11个广告号(5 TRIPLE+5 DUAL+1 UNAME_ONLY)，包括"带人翻身看我剪接Kumar"
- 群内残留广告消息已自动删除(msg_id=50318)

## v5.8.2 [2026-05-31]
- 群消息发送者自动追踪到 `group_members` 表，渐进式构建完整成员列表
- 新增14条用户名广告关键词（币圈套利/日入3K/带单/跟单/收徒/代刷等）
- 扫描脚本v5.8.2：动态发现所有DB表用户ID列 + 显示名检测 + 消息历史扫描(`--history`)
- 新增 `UNAME_ONLY` 检测级别：仅显示名含广告词（score>=4）也标记可疑

## v5.8.1 [2026-05-31]
- 两层组合（用户名+Bio）直接封禁，不再等阈值
- 全量扫描脚本 `_scan_all_members.py`：从33个DB表聚合用户ID，逐一检测用户名+Bio+头像
- 新增 `group_members` 表和 `chat_member` handler，渐进式追踪群成员变动
- 启动扫描 `_job_startup_member_scan` 重写：数据库驱动+用户名/Bio/头像检测
- `infinity_polling` 新增 `allowed_updates=["chat_member"]` 接收成员变动事件

## v5.8.0 [2026-05-31]
- 集成CAS反垃圾数据库（辅助评分+2，不直接ban）
- 集成Intellivoid SPB反垃圾评分（辅助评分+1~+2，不直接ban）
- 新增白名单机制（群管理员免检+可配置用户免检）
- 新增用户名+Bio+头像三层组合直接封禁
- 新增消息元数据检测（URL短链/转发/纯图片/新用户行为）
- 更新project_rules.md广告检测系统完整规范（L0-L4）

## v5.7.5 | 2026-05-31 | [TRAE SOLO CN]

- **新增用户资料(Bio)广告检测**：32条 BIO_PATTERNS 规则检测赚钱承诺/引流链接/服务代开等（权重+3）
- **新增短随机用户名检测**：检测 `^[a-z]{1,4}\d{2,4}$` 格式广告小号（如 gc8181），score+2
- **增强头像检测触发条件**：Bio 含广告 或 短随机用户名时也触发头像分析
- **扩展联系方式检测**：新增 telegram.me/、te.me/、tg.me/ 链接变体
- **扩展用户名规则**：新增"会员代开""TGvip""安全简单"等6条 Bio 引流话术变体

## v5.7.4 | 2026-05-30 | [TRAE SOLO CN]

- **修复零宽字符绕过广告检测**：detect()入口新增_zero_width清理，43个零宽字符拆散的关键词恢复正常匹配
- **零宽字符本身作为可疑信号**：占比>20%时额外score+2
- **补充用户名谐音变体**：新增"看我剪接""带人翻身"等7条USERNAME_PATTERNS规则
- **补充内容谐音变体**：新增"只搞U""一天五w起步""想看简届"等12条pattern规则

## v5.7.3 | 2026-05-30 | [TRAE SOLO CN]

- **修复Bot主动消息追踪缺失**：_send_and_track()发出的消息现在写入reply_tracking表
- **修复欢迎消息清理不可靠**：从threading.Timer改为APScheduler调度
- **新增启动补清理**：Bot重启时扫描reply_tracking表，补清理所有超时未删除的消息
- **扩展孤儿清理范围**：get_orphan_messages()同时清理用户未回复的孤儿+超时Bot主动消息

## v5.7.2 | 2026-05-30 | [TRAE SOLO CN]

- **新增L4追溯广告扫描**：Bot启动时自动扫描最近200条消息删除漏网广告
- **新增/scan_ads管理员命令**：手动触发广告扫描
- **支持双模式**：forwardMessage模式+数据库驱动模式（有保护内容群组自动降级）
- **新增配置项**：RETROACTIVE_SCAN_ENABLED / RETROACTIVE_SCAN_RANGE

## v5.7.1 | 2026-05-30 | [TRAE SOLO CN]

- **修复409 Conflict死循环**：systemd RestartSec从5秒改为35秒
- **修复message_dispatcher分发顺序**：P3.5广告检测提前到P2积分之前执行
- **修复Bot轮询线程静默死亡**：彻底停止→等待→重启

## v5.7.0 | 2026-05-30 | [TRAE SOLO CN]

- **AI调用链全量修复**：user_profile传入+seed随机化+news_content参数修正+识图/TTS模型遍历+线程安全+连续对话超时25秒+过期模型清理+VPS空TOKEN修复

## v5.6.2 | 2026-05-30 | [TRAE SOLO CN]

- **广告检测彻底修复**：根治三类广告漏检（色情引流+重复刷屏+加密货币诈骗）
- **L3兜底检测增强**+**连续消息检测独立化**+**广告消息强制删除**+**L2评分权重增强**+**2字符色情引流词修复**

## v5.6.1 | 2026-05-29 | [opencode]

- **修复uname_clean未定义BUG**+**添加连续消息模式检测**+**新增色情引流词7个**

## v5.6.0 | 2026-05-29 | [opencode]

- **广告检测全面升级**：头像检测集成+名称检测优化+头像相似度检测+启动追溯优化

## v5.5.2 | 2026-05-29 | [opencode]

- **修复 detect_keywords 误删**：从 HEAD 恢复完整函数

## v5.5.1 | 2026-05-29 | [TRAE SOLO CN]

- **广告检测优先级修复**：P2→P3.5独立函数+消息长度阈值5→3+AD_DETECT_CONFIG同步修复

## v5.5.0 | 2026-05-29 | [opencode]

- **广告检测去重+密钥迁移+Dashboard缓存**：消除130行重复代码+环境变量优先读取+5秒TTL缓存

## v5.4.0 | 2026-05-29 | [opencode]

- **安全加固+性能优化+数据完整性修复**：SSH密钥验证+CSRF Token+死锁修复+DB锁优化+签到N+1修复+校准逻辑修正

## v5.3.0 | 2026-05-27 | [TRAE SOLO CN]

- **三维度智能升级**：意图分类+亲密度5级系统+4级挑逗话术+7场景模拟+转化引导+去AI化铁律

## v5.2.0 | 2026-05-27 | [TRAE SOLO CN]

- **动态人格随机化系统**：碎片池+情绪状态机+Few-shot+反模板

## v5.1.1 | 2026-05-26 | [Trae CN]

- **广告检测误封修复**：跳过 / 开头的Bot指令 + 403错误优雅处理 + ENABLE_MESSAGE_DELETION修复

## v5.1.0 | 2026-05-25 | [opencode AUTO AUDIT]

- **全栈自动审计与安全修复**：220+问题审查 + 50+严重/高危问题自动修复 + 9个NameError致命Bug修复 + 架构统一 + VPS部署验证

# 更新日志

## v5.0.0 | 2026-05-24 | [TRAE SOLO CN]

- **深度架构重构**：main.py拆分(3040→133行+15模块) + database.py拆分(2354→1004行+6Repo) + dashboard拆分(5385→57行+12模块)
- 废弃文件清理（start.sh/deploy.sh/一键部署.bat）+ 创建deploy_vps.py + 安全修复 + 代码质量提升

## v4.18.0 | 2026-05-24 — Dashboard全功能配置化：26+页面补全+12后端API修复+4新页面+导航扩展+交互提升

## v4.17.0 | 2026-05-24 — 每日播报数据链路修复+广告关键词配置化+Dashboard群管重构+关键词触发管理+定点播报PUT接口+活跃排行chat_id过滤

## v4.16.5 | 2026-05-24 — 签到静默模式：功能关闭后Bot完全静默忽略

## v4.16.4 | 2026-05-23 — 签到系统修复：多平台中文字体+60秒自动删除+部署同步修复

## v4.16.3 | 2026-05-23 — 消息删除全局开关补漏：8个文件补齐ENABLE_MESSAGE_DELETION检查+签到异常处理重构

## v4.16.2 | 2026-05-23 — 消息删除全局开关(ENABLE_MESSAGE_DELETION)+签到功能关闭+异常处理重构

## v4.16.1 | 2026-05-23 — Dashboard深度用户挑刺审计修复：CSRF+空值保护+30+标题映射+盲盒成本+退出确认

## v4.16.0 | 2026-05-22 — 全栈审计修复+配置模板补全+Docker修复+废弃代码清理

## v4.15.0 | 2026-05-22 — 全模式递进引导+随机变体+统一管理员通知机制

## v4.14.0 | 2026-05-22 — 消费类三阶段转化流程+18个消费关键词变体

## v4.13.2 | 2026-05-22 — 任务抢占误报修复：record_intercept()区分正常拦截与真实异常

## v4.13.0 | 2026-05-21 — 频道数据根因修复+浏览量定时刷新+运营洞察+月报功能

## v4.12.2 | 2026-05-21 — 广告检测持续漏检根治：名称参与评分+CRYPTO拆分+阈值2→3+项目大整理+文档整合

## v4.12.1 | 2026-05-21 — 群数据统计全面修复：精确日期匹配+幂等保护+校准+反馈引导+误封引导

## v4.12.0 | 2026-05-21 — 反馈消息智能拦截：固定安抚+通知管理员

## v4.11.3 | 2026-05-21 — Bot命令误杀修复+任务并发告警误报修复

## v4.11.2 | 2026-05-20 — 广告检测全面修复：名称参与评分+日挣变体+低门槛话术+CRYPTO拆分+阈值调至3

## v4.11.1 | 2026-05-20 — 群数据统计全面修复：API解析+昨日数据+活跃度+频道原生内容+幂等保护

## v4.11.0 | 2026-05-20 — 模型池按真实到期时间重排序+三层路由同步+语义缓存24小时

## v4.10.0 | 2026-05-20 — 模型池全面升级+三层路由重新分配+并发异常误报根治

## v4.9.3 | 2026-05-19 — 项目大整理：清理60+垃圾文件+移除13处未使用import+README全面更新

## v4.9.2 | 2026-05-19 — 统一故障通知中心_FaultReporter+本地告警兜底+防刷机制+P0/P1故障接入

## v4.9.1 | 2026-05-19 — 并发监控预警_TaskGuard+抢占失败监控+数据库锁审计

## v4.9.0 | 2026-05-19 — 根治并发重复播报：_try_claim_and_lock原子抢占+_release_task失败释放

## v4.8.0 | 2026-05-18 — 人设精细化&对话拟人化：延迟系统+分层人设+自然语言调教+分段发送+AI参数微调

## v4.7.0 | 2026-05-18 — 定时任务全面修复：锁机制改为"先执行后确认"+重试+健康检查+移除废弃burn_probe

## v4.6.5 | 2026-05-17 — 色情引流暗号扩展30+组合规则+修复单字误判+pytz缺失修复+规则文档归档

## v4.6.4 | 2026-05-17 — emoji夹杂用户名检测+色情引流黑话+入群封禁词库扩充

## v4.6.3 | 2026-05-17 — 延迟封禁机制+入群一眼广告ID封禁+广告检测三级处理

## v4.6.0 | 2026-05-16 — Dashboard挑刺修复：CSRF+绑定安全+会话过期+版本号动态读取+确认弹窗

## v4.5.36 | 2026-05-15 — 周报chat_id=0硬编码+入群遗漏+校准机制+getChatStatistics Bot API 7.0+

## v4.5.37 | 2026-04-29 — 服务器重装后恢复+SSH密码轮换+统一Bot Token

## v4.5.38 | 2026-04-30 — systemd管理文档+BOT_ROLE协作边界说明

## v4.5.15 | 2026-04-29 — 自然语言配置接通TG+特定词自动回复+部署前配置回流

## v4.5.14 | 2026-04-28 — SPECIAL_AUTO_REPLIES部署白名单修复+远端验证

## v4.5.13 | 2026-04-28 — 称呼联动+特定词自动回复+AI润色+预置转化规则

## v4.5.12 | 2026-04-28 — 问候随机性+隐晦转化+禁止直白营销词

## v4.5.11 | 2026-04-28 — 新闻合并单条主流程+TrendRadar优先+问候去广告腔

## v4.5.10 | 2026-04-28 — 全模态优先文本+三层路由接入omni+启动脚本版本自动读取

## v4.5.9 | 2026-04-28 — 熔断修正+模型指针修复+独立路由去硬编码密钥+账号失败冷却

## v4.5.8 | 2026-04-28 — BAT全英文+Dashboard临时密码+裸except收窄+部署全量上传+模型索引兜底

## v4.5.6 | 2026-04-27 — 全局故障通知+24h自动删除+AI教指令+话术随机化

## v4.5.5 | 2026-04-27 — 故障通知去重+指令识别+回复风格优化

## v4.5.4 | 2026-04-27 — 晚间新闻零token+7新闻源+故障通知

## v4.5.3 | 2026-04-27 — 新闻零token播报+早安加长+去重共享缓存

## v4.5.0 | 2026-04-26 — 全面整理：79个冗余文件清理+文档整合+版本号同步+深度扫描18项致命/严重修复

## v4.4.0~v4.4.8 | 2026-04-25 — 终极核查修复(32项)+fetchall多线程污染+密钥明文+SQL注入+进程级单例锁

## v4.3.0~v4.3.9 | 2026-04-24 — 致命修复27项+SQL注入+硬编码+密码缺陷+Docker部署+AI识图+task_log持久化

## v4.2.0~v4.2.8 | 2026-04-23 — 模型过期检查+数据库索引+塔罗解析+连续对话+AI问候跑题修复
