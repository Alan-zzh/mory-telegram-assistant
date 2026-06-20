# 广告检测系统完整规范

> **被 [AGENTS.md](../../AGENTS.md) 索引引用 · 适用版本：v5.0.0+**
> **最后更新**：2026-06-14（v5.16.5 [Codex] 反应清理 + Business 消息同步）

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
| L1 | 用户名+Bio+头像+Premium emoji 状态 | 用户资料 | 三层命中=直接处置 | ✅ | 高置信度组合；状态贴纸支持元数据+OCR |
| L2 | 消息内容关键词 | 消息文本 | 1~4/维度 | ❌ | 9 个维度权重 |
| L3 | 零宽字符+元数据 | 消息结构 | +1~+2 | ❌ | 零宽占比>20%额外+2 |
| L4 | 新用户行为+转发+短链 | 用户行为 | +1 | ❌ | 入群<5分钟+链接 |

### 二、评分规则

```
SCORE_THRESHOLD = 3
两层组合直接处置：用户名命中 + Bio 命中（无需等阈值）
累计评分机制：30 分钟窗口
```

### 二点五、处置策略（v5.16.2 [Codex] 当前口径）

广告账号**不踢出群**，广告链路不得调用踢人 API。统一复用 `modules/ad_enforcement.py:enforce_ad_user()`：

1. 删除当前消息（仅 `ENABLE_MESSAGE_DELETION=true` 时执行）
2. 永久禁言 `restrict_chat_member(can_send_messages=False)`
3. 写 `global_blacklist`
4. 写本地 `blacklist`
5. 删除 `message_snapshots` 中可追踪历史消息并标记 deleted
6. 通知管理员

投票踢人、验证码失败、僵尸清理、不活跃清理、管理员手动静默操作属于独立群管工具，不等同于广告处置。

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
- Telegram Bot API / Sticker 对象没有“图片中文字”的现成字段，不能只依赖元数据。
- 贴纸图片文字必须下载 thumbnail/file 后用视觉模型 OCR。
- 只有 `emoji_status_custom_emoji_id` 但元数据/OCR 未命中时，只作为低分可疑信号，不单独封禁，避免误封普通 Premium 用户。

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
| 数据库驱动模式 | 群组有保护内容 | 从 `ad_suspicious_users` 表获取已追踪的 msg_id 直接删除 |

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
3. 旧可疑追踪表中保存了 msg_id 的消息。

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

## 引用

- `AGENTS.md` 类别7（AI 自我审计 4 条铁律）→ 根目录 `AGENTS.md` 搜 `类别7`
- [orphan-cleanup.md](orphan-cleanup.md) — 孤儿清理机制
- [MEMBER_SCAN_METHOD.md](../reference/MEMBER_SCAN_METHOD.md) — 群成员扫描完整方案

## 更新历史

- 2026-06-12 (v5.16.2) — [Codex] 广告治理当前策略纠正为永久禁言+双黑名单+删消息，不踢人
- 2026-06-14 (v5.16.5) — [Codex] 广告反应清理(deleteAllMessageReactions) + Business deleted_business_messages 同步 message_snapshots.deleted
- 2026-06-13 (v5.16.4) — [Codex] Premium emoji 状态 OCR 识别与旧残留消息删除边界补充
- 2026-06-02 (v5.12.0) — 首次创建，记录广告检测 5 层体系完整规范
