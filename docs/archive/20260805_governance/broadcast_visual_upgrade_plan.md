# 播报系统视觉与转化升级计划

> 目标：把现有 v4 图片卡能力接入生产流程，并提升所有播报类型（玄学/新闻/问候/定点）的视觉层次、个性化与转化入口。
> 版本：v1.0 | 日期：2026-08-03

---

## 1. Summary

当前项目已有：
- 精美的 v4 黄历图片卡 Demo（`runtime/demo_broadcast_card_v4.py`），但**未接入任何生产任务**。
- 文字播报走 HTML parse_mode + Rich Message 双路径，开关为 `RICH_MESSAGE_ENABLED` / `BROADCAST_FORMAT_VERSION`。
- Inline Keyboard 彩色按钮兼容层（`core/telebot_compat.py::create_colored_button`）。
- 玄学/新闻/问候/定点四条独立播报链路。

本次升级目标：
1. 把 v4 图片卡抽象成可复用生产模块。
2. 为**玄学、新闻、问候、定点播报**四类任务增加图片卡发送能力（图片下方带 Inline Keyboard 按钮）。
3. 保留配置灵活性：各类型独立开关，不强制全部用图片。
4. 统一视觉风格（墨绿/暖金/朱砂配色、圆角阴影、"Mory 沫沫的沫" 印章）。
5. 优化 CTA 文案池，避免歧义。

---

## 2. Current State Analysis

### 2.1 关键文件现状

| 文件 | 职责 | 当前问题 |
|------|------|---------|
| `runtime/demo_broadcast_card_v4.py` | v4 图片卡 Demo | 仅演示，不可复用；硬编码黄历数据；未接入任务 |
| `modules/scheduled_broadcast.py` | 定点播报主逻辑 | 只发 text/image/voice/poll/checklist/rich_message，未生成本地图片卡 |
| `tasks/broadcast/mystic_broadcast_task.py` | 玄学播报发送 | 发 HTML/Rich Message，无图片卡 |
| `tasks/support/mystic_content.py` | 玄学内容生成 | payload 含 blocks/insight/cta，适合被图片卡消费 |
| `tasks/support/common.py::execute_news_task` | 新闻播报发送 | 纯文字，无图片卡 |
| `tasks/broadcast/greeting_task.py` | 问候播报 | 纯文字，无图片卡 |
| `core/telebot_compat.py` | Bot API 兼容层 | 彩色按钮、Rich Message 已就绪 |
| `core/broadcast_formatter.py` | 文字排版器 | 新闻/问候/定点/玄学卡片均有现成函数 |

### 2.2 配置现状

config.json 已有：
- `RICH_MESSAGE_ENABLED: true`
- `BROADCAST_FORMAT_VERSION: "auto"`
- `BUTTON_STYLE_ENABLED: true`
- `BUTTON_COLOR_MAP`

缺少：
- 各播报类型的图片卡开关
- 图片卡全局开关
- 图片卡 CTA 随机池配置

### 2.3 Telegram 能力边界

- `sendPhoto` 支持 `reply_markup`（Inline Keyboard）—— 图片下方可以带按钮。
- `sendRichMessage` 也支持 `reply_markup`。
- 彩色按钮需要 `BUTTON_STYLE_ENABLED=true` 且 SDK/客户端支持。

---

## 3. Proposed Changes

### Phase 1：基础设施 + 玄学播报图片卡（优先落地）

#### 3.1 新建 `core/broadcast_image_card.py`

把 `runtime/demo_broadcast_card_v4.py` 中可复用的绘制逻辑迁移到这里，并解耦。

具体函数：
- `font(size, style)` — 字体加载兜底
- `ts(draw, text, font)` — 文字尺寸
- `wrap(draw, text, font, max_w)` — 自动换行
- `draw_cloud_pattern(draw, W, H)` — 背景云纹
- `draw_rounded_rect_with_shadow(...)` — 圆角阴影卡片
- `draw_brand_stamp(draw, x, y, ...)` — "Mory / 沫沫的沫" 右下角印章
- `draw_cta_button(draw, img, text, ...)` — 底部 CTA 按钮视觉
- `get_random_cta(rng, pool)` — 从文案池随机取 CTA

#### 3.2 新建 `core/broadcast_image_payload.py`

把不同播报类型的业务数据统一转成图片卡 payload。

函数：
- `build_almanac_image_payload(mystic_payload)` — 黄历直接复用 v4 布局
- `build_tarot_image_payload(mystic_payload)` — 塔罗三牌阵卡片
- `build_iching_image_payload(mystic_payload)` — 易经卦象卡片
- `build_news_image_payload(news_content, time_desc)` — 新闻速览卡片
- `build_greeting_image_payload(period, body)` — 问候语卡片
- `build_scheduled_image_payload(item, user_profile)` — 定点播报卡片

#### 3.3 玄学播报接入图片卡

修改 `tasks/broadcast/mystic_broadcast_task.py`：
1. 新增 `build_mystic_image(mystic_payload, config)`：
   - 根据 mode（almanac/tarot/iching）选择 payload 适配器
   - 调用 `core/broadcast_image_card.py::draw_card` 生成 PNG
   - 保存到临时路径（如 `runtime/cache/broadcast/`）
2. 在 `execute_mystic_broadcast_task` 中：
   - 若 `MYSTIC_BROADCAST_CONFIG.image_card_enabled == true`，先生成图片
   - 使用 `send_photo_compat` 发送图片 + `reply_markup`
   - 失败回退到现有 HTML/Rich Message 路径

修改 `tasks/support/mystic_content.py`：
- `_build_cta` 增加更丰富的 CTA 文案池，随机抽取，避免歧义。
- 保持现有 payload 结构不变，图片卡消费同一 payload。

新增配置：
```json
"MYSTIC_BROADCAST_CONFIG": {
  "enabled": true,
  "cta_enabled": true,
  "image_card_enabled": true
}
```

#### 3.4 配置同步

- `config.json.example` 同步新增 `image_card_enabled`（默认 false）。
- 代码中使用 `.get("image_card_enabled", False)`。
- Dashboard 面板 `dashboard/api/settings_api.py` 同步字段。

### Phase 2：新闻 / 问候 / 定点播报图片卡

#### 3.5 新闻播报图片卡

修改 `tasks/support/common.py::execute_news_task`：
- 若 `NEWS_BROADCAST_CONFIG.image_card_enabled == true`：
  - 用 `build_news_image_payload` 把 5 条新闻转成卡片布局
  - 生成图片，走 `send_photo_compat`
  - 图片下方加 "👀 看看预览" 按钮（新闻允许带预览入口）
- 否则保持现有文字路径

#### 3.6 问候播报图片卡

修改 `tasks/broadcast/greeting_task.py`：
- 若 `GREETING_CONFIG.image_card_enabled == true`：
  - 用 AI 生成的问候语生成简约问候卡
  - 走 `send_photo_compat`
  - 午后/夜间附带 "👀 看看预览" 按钮

#### 3.7 定点播报图片卡

修改 `modules/scheduled_broadcast.py`：
- 对 `type == "text"` 的播报项：
  - 若 `SCHEDULED_BROADCASTS[i].image_card_enabled == true` 或全局 `BROADCAST_IMAGE_CARD_ENABLED == true`：
    - 把 title/body/footer 转成图片卡
    - 用 `send_photo_compat` 发送
    - 保留 `reply_markup`
- 不破坏原有 text/image/voice/poll/checklist 逻辑

### Phase 3：统一优化与验证

#### 3.8 CTA 文案池统一

在 `core/broadcast_image_card.py` 或 `tasks/support/message_templates.py` 中新增：
- `BROADCAST_CARD_CTA_VARIANTS`
- 按场景细分：
  - `mystic`："问 Mory 专属风水"、"找 Mory 单独抽牌" 等
  - `news`："👀 看看预览"
  - `greeting`：午后/夜间 "👀 看看预览"，早/晚无按钮
  - `scheduled`：使用配置项的 `button_text`

所有 CTA 文案不得出现 "原版详情" 等歧义表述。

#### 3.9 视觉统一收口

- 所有卡片使用同一套配色：`BG/INK/GREEN/GREEN_BG/RED/RED_BG/GOLD/GOLD_BG`
- 所有卡片右下角保留 "Mory / 沫沫的沫" 印章
- 所有卡片圆角半径统一：卡片 16px，按钮 18px，标签 8px
- 字体统一：标题用霞鹜文楷，正文用微软雅黑

#### 3.10 Demo / 验证脚本

- 保留 `runtime/demo_broadcast_card_v4.py`，但改为调用 `core/broadcast_image_card.py`
- 新增 `runtime/demo_broadcast_all_cards.py`，可一键生成四类卡片样张

---

## 4. Assumptions & Decisions

| 决策 | 选择 | 理由 |
|------|------|------|
| 图片卡开关策略 | 代码默认 `False`，本地验证后在 `config.json` 中设为 `True` | 遵守项目铁律 #8（新功能默认关闭），同时满足用户"测试通过后直接启用"的意图 |
| 是否所有类型都强制图片 | 不强制，各类型独立开关 | 用户明确说"并不是所有都强制图片卡" |
| 图片下方是否带按钮 | 是，使用 Inline Keyboard | 用户确认"图片下面可以带按钮" |
| 字体来源 | 复用现有 `assets/fonts/LXGWWenKai-Regular.ttf` + 系统微软雅黑 | 无需新增依赖 |
| 图片尺寸 | 玄学卡 800×1300，新闻/问候/定点卡 800×1000 左右 | 适配移动端竖屏一屏看完 |
| 失败回退 | 图片生成/发送失败时回退到文字 HTML/Rich Message | 保证播报不中断 |
| 临时图片存储 | `runtime/cache/broadcast/` | 与现有 runtime 目录一致，定时清理 |

---

## 5. Verification Steps

1. **本地图片生成验证**
   - 运行 `python runtime/demo_broadcast_all_cards.py`
   - 确认生成：almanac/tarot/iching/news/greeting/scheduled 六张样张
   - 检查：对齐、品牌印章、CTA 按钮、无 "原版详情" 等歧义文案

2. **单测验证**
   - 运行 `python -m pytest tests/unit/test_broadcast_format.py -q`
   - 运行 `python -m pytest tests/unit/test_mystic_broadcast.py -q`
   - 新增/更新图片卡相关单元测试

3. **导入与语法验证**
   - `python -m py_compile core/broadcast_image_card.py`
   - `python -m py_compile core/broadcast_image_payload.py`
   - `python -m py_compile tasks/broadcast/mystic_broadcast_task.py`

4. **配置一致性验证**
   - 运行 `python scripts/doc_consistency.py`
   - 确认 `config.json.example`、代码 `.get()` 默认值、Dashboard 面板三处一致

5. **端到端 Dry-run（可选）**
   - 使用测试群/私聊，临时开启开关，触发一次玄学播报
   - 确认：图片发送成功、按钮可点击、Rich Message/文字回退可用

---

## 6. 文件改动清单

### 新增文件
- `core/broadcast_image_card.py`
- `core/broadcast_image_payload.py`
- `runtime/demo_broadcast_all_cards.py`

### 修改文件
- `tasks/broadcast/mystic_broadcast_task.py`
- `tasks/support/mystic_content.py`
- `tasks/support/common.py`
- `tasks/broadcast/greeting_task.py`
- `modules/scheduled_broadcast.py`
- `config.json.example`
- `dashboard/api/settings_api.py`
- `runtime/demo_broadcast_card_v4.py`

### 文档同步
- `CHANGELOG.md`（新增条目）
- `project_snapshot.md`（更新 METRICS）
- 若踩坑：`AI_DEBUG_HISTORY.md`

---

## 7. 风险与回滚

| 风险 | 缓解 |
|------|------|
| 图片生成依赖字体/文件系统，VPS 上可能失败 | 失败自动回退文字路径；部署前在 VPS 上运行 demo 脚本验证 |
| 图片尺寸大，发送慢 | 控制分辨率；PNG 压缩；必要时启用 WebP |
| 彩色按钮客户端兼容性问题 | 依赖 `BUTTON_STYLE_ENABLED` 开关，关闭时回退普通按钮 |
| 配置字段遗漏导致 Dashboard 不同步 | 使用 `scripts/doc_consistency.py` 和新增单测覆盖 |

---

## 8. 下一步

待本计划确认后，按 Phase 1 → Phase 2 → Phase 3 顺序实施，每阶段完成后本地验证再进入下一阶段。
