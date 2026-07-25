# 播报富文本与 Bot API 兼容说明

最后更新：2026-07-25（v5.35.12 新闻事实锚定、发送者署名与粉丝群问候纠偏）

## 目标

- 让早安/午安/晚安、定点播报在 Telegram 里更像"卡片消息"，更美观、更有层次。
- pyTelegramBotAPI 4.34.0 已支持 Bot API 10.1（Rich Message / sendRichMessage / InputRichMessage）。
- 双路径排版：HTML parse_mode（旧客户端兼容）+ Rich Message 块级标签（新客户端富文本）。
- v5.32：移除硬塞营销 footer/button，支持 `ai_generate:true` 动态生成 content。
- v5.35.6：新闻不展示内部聚合源；问候与新闻所有降级路径统一保留按钮；时段正文不再承担强制营销。
- v5.35.7：`@Moryfansbot` 负责联系 Mory，`@MorychannelBot` 负责自助下单/订阅；按钮按场景交替且文案与目标一致。
- v5.35.8：新闻统一为 10 条综合头条 + 第 11 行观察；科技最多 1 条、财经最多 2 条；移除稳定 403 直连，Telegram 轮询异常限域退避。
- v5.35.9：后台继续筛选 10 条候选，用户可见内容收紧为 5 条精炼头条 + 第 6 行观察；AI 从候选中二次选择，不机械截前 5 条。
- v5.35.12：第 6 行必须复用本卡片具体实体/事件，卡片署名固定 `@MoryMateBot`、订阅入口只留在独立按钮；问候继承主助理人设并拒绝技术/效率指导。
- v4.0：支持用户画像个性化播报（VIP 专属 emoji、高等级感谢话术、兴趣匹配）

## v5.32 双路径排版架构

### 路径 1：HTML parse_mode（旧版，所有客户端可用）
统一结构（`build_card_html`）：
```
<b><i>emoji 标题</i></b>

<i>角标</i>

正文段落1

正文段落2

<blockquote expandable>折叠补充</blockquote>
```
标签限制：仅内联标签 + blockquote，不支持 `<h1>`/`<ul>`/`<table>` 等块级标签。

### 路径 2：Rich Message（v5.32 新增，Bot API 10.1+）
统一结构（`build_rich_card_message`）：
```
<h2>emoji 标题</h2>
<p><i>角标</i></p>
<p>正文段落1</p>
<p>正文段落2</p>
<details><summary>更多</summary><p>footer</p></details>
```
支持块级标签：`<h1>`-`<h6>`/`<p>`/`<ul>`/`<ol>`/`<li>`/`<table>`/`<tr>`/`<td>`/`<th>`/`<details>`/`<summary>`/`<hr>`/`<blockquote>`/`<pullquote>`/`<footer>`
旧客户端降级为纯文本，新客户端展示富文本。

Rich Message 限制（官方 Bot API 10.1）：
- 嵌套 ≤16 层
- 块数 ≤500
- 表格列数 ≤20
- `<td>` 仅内联格式
- `<blockquote>` 不能嵌套
- `<table>` 内不能嵌套 `<table>`
- 最大 32768 UTF-8 字符
- 最多 50 个媒体附件

### 路径选择逻辑
`_send_formatted_text` 按配置决定路径：
- `RICH_MESSAGE_ENABLED=true` 且 `BROADCAST_FORMAT_VERSION ∈ {"rich","auto"}` → 优先 Rich Message，失败回退 HTML
- 其他情况 → HTML parse_mode

### v5.32 ai_generate 动态生成
SCHEDULED_BROADCASTS 配置项新增 `ai_generate: true` 字段：
- 启用时调用 `ai_engine.ask(mode=period, seed=确定性int)` 动态生成 content
- AI 失败自动回退静态 content（保证播报不中断）
- seed 用 `hashlib.md5(broadcast_id + date)` 确定性生成，同一天同一播报内容稳定

### v5.35.7 文案与用户界面边界

- `source_name` 只用于日志、故障定位和来源链路选择，禁止渲染“多源汇总”“均衡筛选”或供应方名称。
- `@Moryfansbot` 是联系 Mory 的入口；`@MorychannelBot` 是自助下单和自助订阅入口，禁止混用身份。
- 晨间、晚间问候使用联系入口；午间问候与新闻使用自助入口。Rich Message、HTML 与纯文本降级都必须保留正确按钮。
- 四个定点播报按联系/自助交替：晨间联系、午间自助、傍晚联系、夜间自助。
- 关键话题同样按目的分流：福利、开通去 `@MorychannelBot` 自助处理；需要本人判断的定制去 `@Moryfansbot` 联系 Mory。
- 时段正文控制在 1–2 句，不虚构天气、行程、刚发生的事或 Mory 本人经历，不固定复用咖啡/阳光/窗边场景。
- 正文负责自然陪伴，按钮按当前场景承担联系或自助入口；不再要求每条问候强塞营销钩子。
- AI 失败或返回引擎异常话术时，问候/定点播报都改用可信底稿；异常说明不能成为用户可见正文。
- 输出质量门禁同时拦截已确认的固定套话与抒情疗愈腔；不合格 AI 文案不发送，直接使用经过人工约束的时段底稿。
- 模型池用 `enable_thinking` 声明能力：实时问候、新闻与业务回复跳过仅思考模型，对兼容模型显式关闭思考，避免连续 30 秒超时。
- `SPECIAL_AUTO_REPLIES` 可为福利、定制等关键话题配置独立 `polish_prompt`、`required_terms` 与 `forbidden_terms`。AI 输出不合格时回退业务底稿；统计保留用户 ID 用于去重人数，但不保存用户原话。

### v5.35.9 新闻头条契约

- 抓取层以 NewsNow 头条、澎湃、早报和百度/头条可用直连为主干；微博、知乎、澎湃原站直连在 VPS 稳定返回 403，已从活跃源清单删除。不同域并行，但 NewsNow 同域最多 2 路，避免 8 路齐发触发整域超时/限流。
- 按来源权重、原榜单位置和类目轮选综合头条，常态单源最多 2 条；科技最多 1 条、财经最多 2 条，科技与财经合计最多 3 条。
- 首选源不足 10 条时不会立刻发送残缺卡片，而是继续后备源；两个来源都不足时按标题去重合并，合并后仍不足 10 条则本轮不发送并进入既有重试。候选充足但类目集中时逐级放宽类目/单源软限制，科技和财经硬上限不放宽。
- 后台始终把 10 条均衡候选交给 AI；AI 按公共影响、时效性和进展明确度二次挑出最重要 5 条，优先社会民生、国内、国际与公共事件，科技和财经合计最多 2 条且单类最多 1 条。
- AI 严格输出 5 条正文，第 6 行才是观察；输出条数不合格时不用残缺文案，直接回退前 5 条真实标题。
- `PROMPT_TEMPLATES` 新闻覆盖必须同时包含“从10条候选中”“严格只写5条 + 第6行”和科技财经限制；缺少任一项的旧模板会被自动忽略。
- HTML 使用 5 个 `📌`，Rich Message 使用 5 个 `<li>`；内部类目、来源名和聚合方式只参与选题与日志，不出现在用户消息。
- TeleBot 异常处理只接管 `getUpdates` 的 5xx、连接错误和超时，并按 1/2/4/8/15 秒退避；`sendMessage` 等业务发送失败不吞掉，继续进入现有 Rich→HTML→纯文本降级。

### v5.35.12 事实锚定、署名与粉丝群问候契约

- 新闻第 6 行必须与本卡片头条或真实候选共享具体实体/事件短语；“议题交织、现实关切、值得关注”等可套用到任意新闻的空话不合格。
- LLM 观察不合格时，真实标题兜底直接引用前两条完整事实分句，不再生成无依据的宏观概括。
- `@MoryMateBot` 只表示当前发送卡片的机器人身份；`@MorychannelBot` 只存在于“自助下单/订阅”按钮或业务文案，身份署名与 CTA 不再混用。
- 早午晚问候从 `BASE_PERSONA` 提取身份锚定与性格光谱，再叠加粉丝群专用要求；不加载业务知识、转化钩子或单人私聊记忆。
- 缺少“熟悉的粉丝群 / 延续主助理人设 / 不写AI、编程、运维或效率指导”契约的旧问候覆盖自动忽略；质量门禁和人工底稿都禁止多线程、任务、通知、窗口、待办等技术/效率表达。
- 局部 `MODE_ROUTING` 只覆盖明确配置项；问候请求跳过名称含 `code` / `coder` / `coding` 的专用模型，模型不可用时发送经过门禁的走心底稿。



## 当前已落地能力

### 1. HTML 卡片排版（v4.0 - 人物画像个性化版）

- 普通文本播报会自动包装为 HTML：
  - 标题：`<b><i>emoji 标题</i></b>` — 加粗斜体，更有温度
  - 角标：`<i>角标</i>` — 斜体，轻量标识
  - 主体：`content` — 正文内容，支持关键词加粗
  - 可折叠补充说明：`<blockquote expandable><i>footer</i></blockquote>` — 斜体 + 可折叠引用
- 如果 `content` 本身已经写了 HTML 标签，则直接按原样发送，不重复包裹。
- **v4.0 新增**：用户画像个性化支持
  - VIP 用户（level >= 5 或 tags 包含 "vip"）：显示专属 emoji（✨）和尊贵称呼
  - 高等级用户（level >= 3）：显示感谢话术（💝 感谢您的陪伴与支持）
  - 兴趣匹配：tarot 用户显示 🔮，treehole 用户显示 🌳
  - 高价值用户：标题追加"（精选推荐）"

### 2. 时段样式映射

根据 `period` 字段自动选择 emoji 和风格：

```python
PERIOD_STYLES = {
    "morning": {"emoji": "☀️", "accent": "温暖", "greeting": "早安"},
    "afternoon": {"emoji": "🍃", "accent": "轻松", "greeting": "午安"},
    "evening": {"emoji": "🌆", "accent": "陪伴", "greeting": "晚安"},
    "night": {"emoji": "🌙", "accent": "私密", "greeting": "晚安"},
}
```

### 3. 图片播报增强

- `caption` 也支持同样的 HTML 卡片风格。
- 支持 `show_caption_above_media=true`，让图文播报标题先展示在图片上方。

### 4. 链接按钮（v4.0 支持彩色按钮）

- 可选：
  - `button_text`
  - `button_url`
- 配了这两个字段后，会自动带一个单按钮；联系 Mory 使用 `@Moryfansbot`，自助下单/订阅使用 `@MorychannelBot`。
- **v4.0 新增**：彩色按钮支持
  - `button_style`：按钮样式（default/danger/success/primary）
  - `button_emoji_id`：Custom Emoji ID（可选）
  - 通过 `BUTTON_STYLE_ENABLED` 配置启用

### 5. 新参数兼容

当前项目通过 `core/telebot_compat.py` 兼容以下 Telegram Bot API 新参数：

- `show_caption_above_media`
- `allow_paid_broadcast`
- `message_effect_id`
- `suggested_post_parameters`
- `direct_messages_topic_id`
- `deleteAllMessageReactions`（广告反应清理）
- `sendPoll` 新参数（媒体投票、会员限定、追加选项、隐藏结果、随机选项等）
- `sendChecklist`（Telegram Business 清单）

另外已预留 `Rich Messages` 原始直通入口：

- `send_rich_message_compat()`
- 定点播报 `type = "rich_message"` 或直接带 `rich_message`
- **v4.0 新增**：HTML → Rich Message 自动转换（`_html_to_rich_components()`）

说明：

- 若当前 SDK 已支持，优先走 SDK。
- 若当前 SDK 还没暴露该参数，则退回原始 Bot API 请求。
- 当前项目可以先稳用 HTML 卡片，也可以在需要时直接透传官方 `rich_message` JSON。
- 定点文本播报在 `RICH_MESSAGE_ENABLED=true` 且 `BROADCAST_FORMAT_VERSION=rich/auto` 时会优先尝试 `sendRichMessage`，失败自动回退 HTML 卡片。
- 广告处置默认启用 `AD_CLEANUP_REACTIONS=true`，用于尝试清理广告用户在群内留下的反应。

## v4.1 播报配置项

```json
{
  "RICH_MESSAGE_ENABLED": false,
  "BROADCAST_FORMAT_VERSION": "html",
  "BROADCAST_TEMPLATE_VARIATION_ENABLED": true,
  "RICH_MESSAGE_STYLE": {
    "title_bold": true,
    "badge_italic": true,
    "body_normal": true,
    "footer_expandable": true,
    "emoji_custom": false
  },
  "BUTTON_STYLE_ENABLED": false,
  "BUTTON_COLOR_MAP": {
    "buy": "success",
    "cancel": "danger",
    "info": "primary",
    "settings": "default"
  },
  "CUSTOM_EMOJI_ENABLED": false,
  "CUSTOM_EMOJI_POOL": {},
  "USER_PROFILE_ENABLED": false
}
```

`BROADCAST_TEMPLATE_VARIATION_ENABLED` 用于无缝升级旧模板：正文、标题、按钮保持旧配置不变，只在折叠补充里按日期和播报 ID 增加一句轻变化。这样每天看起来不会完全一模一样，又不会突然变成另一套话术。

## v4.0 新增数据库表

- `user_profiles`：用户画像表（user_id, tags, level, interests, last_interaction, conversation_rounds）
- `button_styles`：按钮样式表（button_id, style, icon_custom_emoji_id）

## v4.0 新增 Dashboard API

- `/api/config/broadcast-format`：播报格式配置
- `/api/config/button-style`：按钮样式配置
- `/api/config/custom-emoji`：Custom Emoji 池配置
- `/api/config/user-profile`：用户画像配置

## Telegram Bot API HTML 模式支持的标签

| 标签 | 效果 | 当前使用场景 |
|------|------|-------------|
| `<b>` / `<strong>` | **加粗** | 标题、关键词强调 |
| `<i>` / `<em>` | *斜体* | 角标、正文、折叠补充 |
| `<u>` / `<ins>` | <u>下划线</u> | 可选强调 |
| `<s>` / `<strike>` / `<del>` | ~~删除线~~ | 未使用 |
| `<tg-spoiler>` | 剧透（点击显示） | 私密提示 |
| `<a href="URL">` | 超链接 | 按钮链接 |
| `<blockquote>` | 引用块 | 未使用 |
| `<blockquote expandable>` | 可展开引用块 | 折叠补充 |

**嵌套规则**：
- `<b><i>加粗斜体</i></b>` ✅
- `<b><u>加粗下划线</u></b>` ✅
- `<i><s>斜体删除线</s></i>` ✅
- `<code>` 和 `<pre>` 内部不能嵌套其他格式
- `<blockquote>` 不能嵌套 `<blockquote>`

## SCHEDULED_BROADCASTS 可用字段

最小写法：

```json
{
  "id": "morning_card",
  "hour": 9,
  "minute": 30,
  "content": "今天群里有新活动，晚点我再来细说～",
  "type": "text",
  "enabled": true
}
```

增强写法（v3.1）：

```json
{
  "id": "morning_nudge",
  "hour": 10,
  "minute": 0,
  "type": "text",
  "period": "morning",
  "title": "早上好呀",
  "badge": "✨ Mory来报到啦",
  "content": "刚泡好一杯咖啡，窗边的光刚好照到桌上，突然想到你们了～\n\n今天上午也要顺顺利利的，有什么想聊的随时来找我，我都在。",
  "footer": "💬 想聊的随时来找我～懂的人自然知道怎么出现。",
  "button_text": "💌 找Mory聊聊",
  "button_url": "https://t.me/MorychannelBot",
  "silent": false,
  "protect_content": false,
  "enabled": true
}
```

字段说明：

- 时间：
  - 推荐 `hour` + `minute`
  - 兼容旧 `time: "HH:MM"`
- 文本相关：
  - `content` — 正文内容
  - `title` — 标题（自动加 emoji 和格式化）
  - `badge` — 角标（斜体显示）
  - `footer` — 折叠补充（可展开引用块）
  - `period` — 时段（morning/afternoon/evening/night，自动选择 emoji）
  - `parse_mode`
- 图片相关：
  - `caption`
  - `show_caption_above_media`
- 交互相关：
  - `button_text`
  - `button_url`
  - `button_style`
  - `button_emoji_id`
  - `rich_message`
  - `suggested_post_parameters`
- 投票相关：
  - `question`
  - `options`
  - `members_only`
  - `allow_adding_options`
  - `hide_results_until_closes`
  - `shuffle_options`
  - `allows_revoting`
  - `allows_changing_answer`
  - `media`
  - `description`
- 清单相关：
  - `business_connection_id`
  - `checklist`
  - `tasks`
- 发送控制：
  - `silent`
  - `protect_content`
  - `disable_preview`
  - `allow_paid_broadcast`
  - `message_effect_id`
  - `direct_messages_topic_id`

## 排版效果示例

### 定点播报（morning_nudge）

```
<b><i>☀️ 早上好呀</i></b>

<i>✨ Mory来报到啦</i>

刚泡好一杯咖啡，窗边的光刚好照到桌上，突然想到你们了～

今天上午也要顺顺利利的，有什么想聊的随时来找我，我都在。

<blockquote expandable><i>💬 想聊的随时来找我～懂的人自然知道怎么出现。</i></blockquote>
```

**Telegram 渲染效果**：
- 标题：**☀️ 早上好呀**（加粗斜体）
- 角标：*✨ Mory来报到啦*（斜体）
- 正文：普通文本
- 折叠补充：可展开的引用块，斜体

### 早安问候

```
<b><i>☀️ 早安呀</i></b>

<i>✨ Mory来报到啦</i>

<i>刚泡好一杯咖啡，窗边的光刚好照到桌上，突然想到你们了～</i>

<blockquote expandable><i>💬 想聊的随时来找我～懂的人自然知道怎么出现。</i></blockquote>
```

**Telegram 渲染效果**：
- 标题：**☀️ 早安呀**（加粗斜体）
- 角标：*✨ Mory来报到啦*（斜体）
- 正文：*斜体*（增加私密感）
- 折叠补充：可展开的引用块，斜体

## 已扩到的发送入口

- 早安 / 午安 / 晚安自动问候
- 定点播报 `SCHEDULED_BROADCASTS`
- 群内时消息 `scheduled_messages`
- 管理员代发私信 / 代发群 / 代发频道
- 管理员的投票命令和定点投票
- 管理员清单命令和定点清单

## 新版投票

定点投票示例：

```json
{
  "id": "night_poll",
  "hour": 22,
  "minute": 10,
  "type": "poll",
  "question": "今晚想看哪种内容？",
  "options": ["轻松聊天", "深夜故事"],
  "members_only": true,
  "allow_adding_options": true,
  "hide_results_until_closes": true,
  "enabled": true
}
```

管理员命令也支持 JSON 投票：

```text
投票 {"question":"今晚想看哪种内容？","options":["轻松聊天","深夜故事"],"members_only":true,"allow_adding_options":true}
```

## Telegram Business 清单

`sendChecklist` 属于 Telegram Business 能力，必须配置 `TELEGRAM_BUSINESS_CONNECTION_ID` 或在单条播报里提供 `business_connection_id`。

定点清单示例：

```json
{
  "id": "event_checklist",
  "hour": 18,
  "minute": 30,
  "type": "checklist",
  "title": "今晚活动清单",
  "tasks": ["确认素材", "检查入口", "复盘转化"],
  "enabled": true
}
```

管理员命令：

```text
清单 {"title":"今晚活动清单","tasks":["确认素材","检查入口","复盘转化"]}
```

未配置业务连接 ID 时会跳过并提示，不会影响 Bot 主流程。

## 更新入口修正

`main.py` 旧的 `allowed_updates` 只允许 `message`、`chat_member`、`my_chat_member`，会导致项目里已经注册的编辑消息检测、频道帖子追踪和新版反应/业务消息事件收不到 Telegram 更新。

现在默认打开：

- `edited_message`
- `channel_post`
- `edited_channel_post`
- `message_reaction`
- `message_reaction_count`
- `business_connection`
- `business_message`
- `edited_business_message`
- `deleted_business_messages`
- `guest_message`
- `purchased_paid_media`
- `managed_bot`

可通过 `TELEGRAM_ALLOWED_UPDATES` 追加自定义更新类型；项目会自动合并默认必需事件，避免旧配置误删关键入口。设为 `"all"` 时不限制更新类型。

注意：`allowed_updates` 只代表 Telegram 会推送这些事件，不代表当前 pyTelegramBotAPI 会自动分发。项目已在 `core/telebot_compat.py` 里补 `patch_telebot_business_update_dispatch()`，把 SDK 未分发的新事件交给 `core/handlers/business_handlers.py`。

Business 事件处理策略：

- `business_message`：映射进现有普通消息链路，保留 `_mory_update_type="business_message"`。
- `edited_business_message`：映射进现有编辑消息链路，保留 `_mory_update_type="edited_business_message"`。
- `business_connection`：只记录连接状态，不触发对话回复。
- `deleted_business_messages`：同步调用 `mark_message_deleted()`，把本地 `message_snapshots` 标为已删除。
- `guest_message` / `managed_bot`：先做轻量观测，避免误进普通对话。
- `purchased_paid_media`：只记录观测；项目仍遵守 Bot 内不收款红线，不接入 Telegram 付费媒体作为下单闭环。

`core/handlers/media_handlers.py` 已注册 `message_reaction_handler` 和 `message_reaction_count_handler`：

- 黑名单用户新增反应时，尝试删除该条反应，失败时再尝试清理该用户全部反应。
- 正常用户的反应计数只做轻量日志观测，不写库，避免高频事件压垮数据库。

Business updates 兼容：

- `business_message` 会映射进现有 `message` 处理链路。
- `edited_business_message` 会映射进现有 `edited_message` 处理链路。
- 原始字段仍保留在 `update.business_message` / `update.edited_business_message`，消息对象会带 `_mory_update_type` 标记。

## 已修正的历史问题

### 1. 定点播报串发

- 旧逻辑：某个播报任务触发时会遍历所有启用播报，存在串发风险。
- 新逻辑：只执行当前 `broadcast_id` 对应那一条。

### 2. 时间配置不一致

- 旧逻辑：注册任务读 `hour/minute`，执行模块主要读 `time`。
- 新逻辑：同时兼容两种写法，统一解析。

### 3. 排版过于复杂（v3.0 修正）

- 旧逻辑：使用 Unicode 分隔线（━ 和 ─），移动端显示效果差。
- 新逻辑：简洁排版，充分利用 Telegram 原生格式化能力（加粗、斜体、引用块）。

### 4. 问候话术重复（v3.1 修正）

- 旧逻辑：AI 生成失败时直接放弃发送。
- 新逻辑：新增 `_GREETING_FALLBACK_POOL` 话术池，AI 失败时随机选择预设话术，保证播报不中断。

### 5. 内部来源泄漏与问候缺按钮（v5.35.6 修正）

- 旧逻辑：新闻来源链路被映射成用户可见角标，问候发送函数不接受按钮，降级路径也可能丢失入口。
- 新逻辑：来源仅写内部日志；问候和新闻在 Rich Message、HTML、纯文本路径统一透传按钮。

### 6. 联系入口与自助售卖入口混用（v5.35.7 修正）

- 旧逻辑：所有按钮统一跳转 `@MorychannelBot`，但文案却写成“联系 Mory”，把自助售卖机器人伪装成本人联系入口。
- 新逻辑：按钮与关键话题文案都按目的路由；`@Moryfansbot` 只承担联系 Mory，`@MorychannelBot` 只承担自助下单和自助订阅。

## 风险边界

- 这里做的是"安全可运行"的 Bot API 薄兼容，不代表已经完整接入 Telegram 官方全部最新消息体系。
- 如果后续要直接上官方更重的 Rich Messages / Suggested Posts 全量能力，建议单独做一层结构化消息配置，而不是继续把所有能力塞进单个播报对象里。
- HTML 模式不支持 `<br>` 标签，换行请使用 `\n`。
- 不要过度嵌套格式化标签，保持简洁清晰。
