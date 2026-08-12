# 广告检测系统完整规范

> 本文档为独立技术说明，未被 AGENTS.md 直接索引 · 适用版本：v5.0.0+
> **最后更新**：2026-08-13（QQ群色情招揽模板补漏）

## 概述

Mory 小助理作为群管理 Bot，**反垃圾/广告检测**是核心功能之一。从 v5.6.0 至今已迭代到 5 层检测体系，配套 30+ 关键词规则集 + 双模式追溯扫描。

## 适用场景

- 排查"为什么用户被误封/漏封"时查阅
- 新增广告检测规则时参考此规范
- 写新群管功能时与广告检测联动

## 关键内容

### 一、5 层检测体系

| 层级 | 检测内容 | 信号来源 | 评分 | 直接处置 | 说明 |
|------|---------|---------|:----:|:-------:|------|
| L0 | CAS/SPB 外部数据库 | 外部 API | +1~+2 | ❌ | 仅辅助评分 |
| L1 | 显示名/username、Bio、头像、Premium emoji 状态 | 用户资料 | 任一明确高置信命中即处置 | ✅ | 头像尺寸、比例、文件大小、平均颜色只记录不定罪；状态贴纸支持元数据+OCR |
| L2 | 消息内容关键词 | 消息文本 | 1~4/维度 | ❌ | 9 个维度权重 |
| L3 | 零宽字符+元数据 | 消息结构 | +1~+2 | ❌ | 零宽占比>20%额外+2 |
| L4 | 新用户行为+转发+短链 | 用户行为 | +1 | ❌ | 入群<5分钟+链接 |

### 二、评分规则

```
SCORE_THRESHOLD = 3
两层组合直接处置：用户名命中 + Bio 命中（无需等阈值）
累计评分机制：30 分钟窗口
```

### 二点一、广告变体规范化与反误封边界（v5.38.7）

- 先用 Unicode NFKC 统一全角、花体字母/数字和兼容标点；不做全局 leetspeak 替换。
- O/o/I/l/| 只在“日/月周期或收益词 + 数字形近串 + 加号/金额单位”中转为数字，`BOSS+`、英文名和型号不会被改写。
- 六类高置信模板分别进入原有评分维度：收益、联系方式、兼职招聘、彩票交易、色情、跑分洗钱。数字/字母可拆开强关键词，但不跨类别共享一个宽泛万能规则。
- 裸聊、约炮、洗钱等强语义词允许拆字后直接命中；跑1分、刷1单、代收付、兼职、招聘、代理、特码等歧义词必须再出现交易、薪酬、联系方式、有量或找庄等第二锚点。
- 加号后紧跟步、米、公里、字、页、题、人、次、分钟、小时、卡路里等日常计量单位时放行；型号、游戏、运动、简历讨论和普通维修上门也作为强制反例。
- “上门”及“上门服务”不再单独作为色情证据，必须与按摩、特服、全套或明确色情身份组合。
- 此类消息仍通过 `security_handlers.check_ad_detection()` 调用统一 `enforce_ad_user()`，禁止新增仅删除或仅累计的旁路。

### 二点五、处置策略（v5.16.2 [Codex] 当前口径）

广告账号**不踢出群**，广告链路不得调用踢人 API。统一复用 `modules/ad_enforcement.py:enforce_ad_user()`：

1. 删除当前消息（仅 `ENABLE_MESSAGE_DELETION=true` 时执行）
2. 永久禁言 `restrict_chat_member(can_send_messages=False)`
3. 写 `global_blacklist`
4. 写本地 `blacklist`
5. 删除 `message_snapshots` 中可追踪历史消息并标记 deleted
6. 通知管理员

投票踢人、验证码失败、僵尸清理、不活跃清理、管理员手动静默操作属于独立群管工具，不等同于广告处置。

### 二点五补充、入群四信号统一入口与延迟补审（v5.38.8）

- 活入口是 `core/handlers/member_handlers.py`，不是仅在未启用验证码时调用的 `group_mgr.py`。
- 已有本地或全局广告黑名单账号重入时，在验证码和欢迎语之前直接复用 `enforce_ad_user()`。
- 白名单和群管理员免检先于显示名、Bio、Premium emoji 状态和头像审核，避免资料层误封。
- 首次入群调用 `get_chat(uid)`；若 Telegram 暂时不给 Bio，验证码通过产生的 `restricted → member` 更新会再次读取最新 Bio 并复审资料与头像。该更新不能只写 `group_members`。
- 四类资料任一明确命中都会短路验证码和欢迎语，并进入永久禁言、历史清理、本地 `blacklist`、`global_blacklist` 和 `mute_records` 同一处置链。
- 头像画面主体先由本地 NudeNet ONNX 识别。只采纳生殖器、肛门、女性胸部或臀部等明确暴露类别的高置信结果；covered、腹部、腋下、脚部以及阈值以下结果不封。营销文字继续走 OCR，通用视觉模型不确定时也不定罪。
- v5.38.10 起，旧 PIL 尺寸、比例、文件大小和平均颜色分析仅输出诊断信息，`member_handlers`、`group_mgr`、`security_handlers`、`auto_tasks` 均不得据此调用广告处置；兼容函数 `check_and_ban_if_porn_avatar()` 固定放行。高置信 NudeNet、明确头像广告文字/二维码和批量相似头像仍是独立证据。
- v5.38.11 起，`QQ/Q群/扣群/企鹅群/qqun + 6–12 位数字`按结构化联系方式计 3 分并进入统一处置；数字可包含有限空格、点、横线及 `O/I/l/|` 形近字符。`q裙/q郡/扣裙/扣郡`歧义更高，只有同一短消息中还出现长期关系、不粘人、不查岗、兼职、良家、无定、上门、资源或福利等广告锚点才计分。服装订单、算法讨论、动物数量、普通关系表达和不足 6 位的编号必须放行。
- v5.38.12 起，`六叔公/六彩盒/六彩和/六彩合/六合彩/六合/六肖/六肖码/六码`等彩票代称只有在代称前后各 40 字的局部窗口同时出现“单子/货量”和“有庄收/庄家收/找庄/找靠谱庄/庄家合作”等交易动作时计 4 分；允许有限空格、斜杠、字母和符号拆字及正反语序。报道/教学语境只有同时具备前置来源与后置查处、诈骗、灰产或非法结论才放行；没有澳门地域锚点的亲属水果、农庄收购、包装订单、工厂物流等实体履约冲突语境也放行。单独伪造“新闻曝光”“教学案例”“包装发货”等前后缀不能获得豁免。
- `q裙/q郡/扣裙/扣郡 + 6–12 位号码`除既有关系招揽、兼职和上门锚点外，也识别“户外露出 + 小癖好/可以约/私约”的色情招揽三要素；三类证据必须落在同一 80 字局部窗口。单独户外摄影、普通小癖好、服装订单号、约时间取货及没有群号的日常表达保持放行。
- `q裙/q郡/扣裙/扣郡 + 6–12 位号码`与“00后新下海”或“新下海 + 配合听话”落在同一 80 字局部窗口时，按成人招揽首条处置；潜水、游泳、海训、救援、航海、海钓、捕鱼及水下摄影等正常下海语境保持放行，除非同时出现“配合听话”这一额外招揽锚点。
- SpamProtection 仅是 L0 辅助信号。端点失败后以单调时钟开启 15 分钟进程内熔断；任一时刻只允许一个网络探针，其余消息立即以中性结果继续本地检测。冷却后也只允许一个半开探针，显式 `retry_times=0` 禁止统一 HTTP 客户端重试，外部失败不得阻断本地高置信处置。

### 二点六、Premium emoji 状态识别（v5.16.4 [Codex]）

截图中“名称旁边有看我简介”的情况，本质可能是 Telegram Premium emoji 状态贴纸。处理链路：

1. `core/telebot_compat.py:preserve_user_extra_fields()` 保留 pyTelegramBotAPI 未显式支持的新字段，尤其是 `emoji_status_custom_emoji_id`。
2. `modules/ad_profile_signals.py:detect_profile_ad_signal()` 合并检测：
   - first_name / last_name / username
   - BIO
   - emoji 状态 Sticker 元数据：`emoji` / `set_name` / `custom_emoji_id`
   - Sticker 缩略图 OCR 文本
3. 文字或 OCR 命中 `USERNAME_PATTERNS + BIO_PATTERNS` 后，复用 `enforce_ad_user()`。
4. 发言内容为 `1` 等 1 字符时，也必须先跑资料层检测；资料层未命中时才跳过内容评分。

**重要边界**：
- Telegram Bot API / Sticker 对象没有"图片中文字"的现成字段，不能只依赖元数据。
- 贴纸图片文字必须下载 thumbnail/file 后用 OCR 识别。
- OCR 优先级：API 视觉模型 > 本地 RapidOCR（CPU） > 评分累计降级
- 只有 `emoji_status_custom_emoji_id` 但元数据/OCR 未命中时，只作为低分可疑信号，不单独封禁，避免误封普通 Premium 用户。

**本地 OCR 引擎（RapidOCR）**：
- VPS 上安装 `rapidocr-onnxruntime`，基于 PaddleOCR 的 ONNX 版本，CPU 推理，模型约 9MB
- 当 `MODEL_POOLS.vision` 为空（无 API 视觉模型）时，自动 fallback 到本地 OCR
- 实测识别"看我简介""看我主页""进群了解"等中文文字准确率 100%，CPU 耗时 0.3-0.4 秒
- 识别出的文字仍需过 `USERNAME_PATTERNS + BIO_PATTERNS` 规则匹配才触发封禁，不会误封

### 三、9 维度关键词规则集

| 维度 | 标签 | 权重 | 规则文件 |
|------|------|:----:|---------|
| money_promise | 赚钱承诺 | 3 | MONEY_PATTERNS |
| low_barrier | 低门槛 | 1 | LOW_BARRIER_PATTERNS |
| contact_info | 联系方式/引流 | 3 | CONTACT_PATTERNS |
| profile_hint | 引流暗示 | 1 | PROFILE_HINT_PATTERNS |
| recruit | 招募/拉人 | 2 | RECRUIT_PATTERNS |
| crypto_money | 加密货币/洗钱 | 3 | CRYPTO_PATTERNS |
| crypto_neutral | 中性加密词汇 | 1 | CRYPTO_NEUTRAL_PATTERNS |
| adult_content | 色情引流 | 4 | ADULT_PATTERNS |
| gray_industry | 灰色产业 | 4 | GRAY_PATTERNS |

**每个维度只计一次最高分**（break 跳出）

### 四、关键代码

| 模块 | 文件 | 关键函数 |
|------|------|---------|
| 检测主逻辑 | [modules/ad_detector.py](../../modules/ad_detector.py) | `detect()` / `retroactive_scan()` / `track_suspicious_user()` |
| 关键词规则 | [modules/ad_patterns_encoded.py](../../modules/ad_patterns_encoded.py) | ADULT_PATTERNS / GRAY_PATTERNS / ... |
| 检测入口 | [core/handlers/security_handlers.py](../../core/handlers/security_handlers.py) | 白名单 + 元数据提取 + 三层组合封禁 |
| 头像检测 | [modules/avatar_detector.py](../../modules/avatar_detector.py) | 色情头像识别 |
| Emoji 面具 | [modules/emoji_mask_detector.py](../../modules/emoji_mask_detector.py) | emoji 绕过检测 |
| 资料状态检测 | [modules/ad_profile_signals.py](../../modules/ad_profile_signals.py) | 用户名/BIO/Premium emoji 状态元数据 + OCR |
| SDK 兼容补丁 | [core/telebot_compat.py](../../core/telebot_compat.py) | 保存 `User` 未知字段，防止 `emoji_status_custom_emoji_id` 被丢弃 |

### 五、敏感词存储

**所有敏感词必须用 Unicode 转义序列存储**（在 `ad_patterns_encoded.py` 中），原因：
- 平台安全审核会拦截直接输入的敏感中文
- Unicode 转义绕过审核

```python
# ❌ 错误：直接写中文会触发平台审核
r"壮阳药"

# ✅ 正确：用 Unicode 转义
r"\u58ee\u9633\u836f"  # 等效于"壮阳药"
```

**转换工具**：
```bash
python -c "print('中文关键词'.encode('unicode_escape').decode())"
```

### 六、追溯扫描双模式

群组启用"保护内容"时，Bot 无法用 `forwardMessage` 读取消息内容。提供双模式自动选择：

| 模式 | 触发条件 | 实现 |
|------|---------|------|
| `forwardMessage` 模式 | 群组无保护内容 | 逐条转发读取内容判断广告 |
| 数据库驱动模式 | 群组有保护内容 | 只处理当前追踪窗口内有逐条广告证据的 msg_id；普通追踪记录安全跳过 |

```python
# modules/ad_detector.py
def retroactive_scan(bot, chat_id, start_msg_id, end_msg_id, admin_id):
    """自动选择 forward / database 模式"""
    if is_protected_content(bot, chat_id):
        return _scan_via_database(bot, chat_id, admin_id)
    return _scan_via_forward(bot, chat_id, start_msg_id, end_msg_id)
```

### 六点五、历史消息删除边界

广告处置会删除：

1. 当前命中的消息；
2. `message_snapshots` 中该用户在该群可追踪到的历史消息；
3. 旧可疑追踪表中保存了 msg_id，且该条消息显式 `is_ad=true` 或单条评分达到阈值的消息。

`ad_suspicious_users` 会为连续消息模式记录 `score=0` 的正常消息，因此“被追踪”绝不等于“已确认广告”。保护内容群无法重新读取正文时，无逐条证据必须 fail-close；禁止按消息 ID 范围盲删。启动扫描从 `message_snapshots` 只读获取最后一条群消息 ID，不再向群发送后删除探针消息。

不能自动删除：

- 没有进入 `message_snapshots` 的旧消息；
- Bot 已消费且未保存 msg_id 的历史消息；
- 只知道 uid、昵称、截图但不知道 message_id 的群消息。

**v5.16.4 实测案例**：`5751488320 / 云间藏诗意` 已 restricted + 双黑名单，但 VPS `message_snapshots` 总数为 0，Bot API 最近消息转发探测也无法读取来源，因此不能安全自动删除旧残留。后续同类消息会因短消息资料层检测和快照追踪被自动处理。

### 七、白名单

```json
{
  "AD_WHITELIST": {
    "user_ids": [123456, 789012],
    "role_exempt": ["admin", "creator"]
  }
}
```

- 群管理员/群主自动免检（无需配置）
- 指定 user_id 免检（在 config.json 中配置）

### 八、误封防护

| 措施 | 说明 |
|------|------|
| CAS/SPB 仅辅助评分 | 外部数据库命中不直接处置 |
| 白名单机制 | 群管理员/群主 + 可配置 user_id |
| 阈值保护 | 总评分需 >=3 才处置 |
| 追溯证据门禁 | 数据库追溯只接受显式 `is_ad` 或单条评分达到阈值，普通追踪与无证据范围不删除 |
| 两层组合=直接处置 | 用户名+Bio 同时命中即直接处置 |
| API 查询容错 | CAS/SPB 查询失败不影响本地检测 |
| 延迟封禁 | 30 分钟窗口累计评分 |

### 九、历史坑

| 版本 | 现象 | 修复 |
|------|------|------|
| v5.6.2 | 三层广告漏检 | 强制删除 + 独立连续消息检测 |
| v5.7.4 | 零宽字符绕过 | 清理范围扩大 + 零宽占比>20%额外+2 |
| v5.7.5 | 短随机用户名漏检 | 格式 `^[a-z]{1,4}\d{2,4}$` 检测 |
| v5.8.4 | 95.7% 覆盖扫描 | Pyrogram 全量扫描 5811 人 |
| v5.10.0 | 误封修复 | 跳过 `/` 开头的 Bot 指令 + 403 错误优雅处理 |
| v5.16.5 | 广告反应残留 | 默认尝试 deleteAllMessageReactions 清理广告用户反应 |
| v5.16.4 | Premium emoji 状态漏检 | 保留 `emoji_status_custom_emoji_id` + 状态贴纸元数据/OCR + 短消息资料层检测 |
| v5.16.4 | 日志假删但群里残留 | 删除失败不标记 deleted；无 msg_id 的旧残留明确不能承诺自动删 |

### 八、新成员入群全维度检测（v5.38.8）

新人入群时，活入口 `core/handlers/member_handlers.py:_handle_new_chat_members()` 执行以下检测链：

```
1. 用户名关键词匹配（AUTO_MUTE_NAMES）
2. 用户名可疑检测（check_username_suspicious）
3. 显示名/username/Bio/Premium emoji 状态（`detect_profile_ad_signal` + `AdDetector.detect`）
4. 本地 NudeNet 明确暴露区域检测（`review_avatar_nsfw_local`）
5. 头像营销文字 OCR 与相似头像检测
6. 验证码解限后用最新 Bio/头像补审
```

**头像画面与 OCR 检测**：
- 下载用户头像图片 → NudeNet 本地 ONNX 先看画面主体 → 通用视觉/OCR 检查营销文字 → 不可用时 fallback 到本地 RapidOCR
- 命中"看我简介""点我主页""进群了解"等广告关键词 → 评分≥2 直接处置
- 解决了"看我简介"类视觉广告（emoji/贴纸叠加在头像图片上）无法被文本规则检测的问题

**BIO简介检测**：
- 调用 `bot.get_chat(user.id)` 获取用户 bio 字段
- 用 `BIO_PATTERNS` 正则匹配（零TOKEN消耗）
- 未命中时再调用 `detect_profile_ad_signal()` 做完整检测（含emoji状态）

**任一检测命中 → `enforce_ad_user()` 统一处置**

### 存量成员全量扫描（v5.38.39）

- `scripts/scan_group.py` 用 Pyrogram 枚举当前全群成员；资料只走专用资料强证据，历史消息逐条只跑内容字段，禁止普通 username/Bio 分数冒充消息直接证据；不再维护另一套阈值。
- 第一阶段仅写带版本、时效、覆盖率和 SHA-256 指纹的私有报告；覆盖率低于 90% 或限量调试报告不可应用。
- 第二阶段只处理报告中的高置信候选，并重新查询成员、管理员/白名单/黑名单、个人资料及关联频道帖子；状态未知一律跳过。
- 最终动作仍只走 `enforce_ad_user()`。默认不全员调用头像视觉模型，仅在已有弱信号时复核；低置信头像不处罚。
- 启动任务只覆盖数据库已知 UID，默认关闭且默认只报告；任何零覆盖或批量 API 故障必须失败，不能记零人成功。

### 九、删除消息能力验证（v5.30.2 铁律）

**Telegram Bot API 支持管理员删除群内任何消息**，包括其他用户发送的消息。

前置条件：
1. Bot 必须是群管理员，且 `can_delete_messages: true`
2. Bot Token 必须有效（`getMe` 返回 200）

排查删除失败的固定顺序：
1. **验证 Token 有效性**：`getMe` → 401 = Token 过期/撤销，去 @BotFather 重新获取
2. **验证 Bot 权限**：`getChatMember` → 确认 `can_delete_messages: true`
3. **验证 msg_id**：暴力扫描 msg_id 范围，`deleteMessage` 返回 200 = 成功

**永远不要对用户说"没办法删除"或"消息不存在"** —— 先验证上述 3 步。

## 引用

- `AGENTS.md` 类别7（AI 自我审计 4 条铁律）→ 根目录 `AGENTS.md` 搜 `类别7`
- [orphan-cleanup.md](orphan-cleanup.md) — 孤儿清理机制
- [MEMBER_SCAN_METHOD.md](../reference/MEMBER_SCAN_METHOD.md) — 群成员扫描完整方案

## 更新历史

- 2026-06-26 (v5.30.2) — [opencode] 新成员入群头像OCR+BIO广告检测 + 删除消息能力验证铁律
- 2026-06-12 (v5.16.2) — [Codex] 广告治理当前策略纠正为永久禁言+双黑名单+删消息，不踢人
- 2026-06-14 (v5.16.5) — [Codex] 广告反应清理(deleteAllMessageReactions) + Business deleted_business_messages 同步 message_snapshots.deleted
- 2026-06-13 (v5.16.4) — [Codex] Premium emoji 状态 OCR 识别与旧残留消息删除边界补充
- 2026-06-02 (v5.12.0) — 首次创建，记录广告检测 5 层体系完整规范
