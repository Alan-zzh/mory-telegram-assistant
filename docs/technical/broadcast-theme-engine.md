# 播报多样性引擎技术文档

> 版本：v1.0 | 最后更新：2026-06-17

---

## 1. 概述

播报多样性引擎（theme_pools.py）是 Mory 小助理播报系统的核心组件，负责解决播报内容同质化、转化率低的问题。通过主题轮换、语气轮换、黑话软植入、图片关键词暗示和转化引导五大机制，实现播报内容的多样化和软营销。

### 1.1 核心能力

1. **主题池轮换**：4 时段 × 5 主题，按星期轮换
2. **语气池轮换**：4 时段 × 3 语气，按日期+时段轮换
3. **黑话软植入**：5 个黑话 × 3 模板，不直白说价格
4. **图片关键词暗示**：5 个关键词 × 3 模板，制造好奇
5. **转化引导**：10 条自然引导模板，用于底部折叠区
6. **种子随机机制**：基于日期+时段+播报ID的 MD5 种子，同一天同一时段内容一致，不同天自动轮换

### 1.2 设计原则

- 像朋友随口提到，不像推销
- 话说一半留一半，让对方自己脑补
- 禁止"想看更多？""要不要试试？"这种硬广句式

---

## 2. 架构设计

### 2.1 核心文件

```
core/
├── theme_pools.py              # 多样性引擎（主题+语气+黑话+图片+转化）
├── broadcast_formatter.py       # 富文本排版（HTML卡片构建）
└── scheduled_broadcast.py       # 定时播报（集成引擎）
```

### 2.2 数据流

```
1. 定时任务触发（10:00/14:30/19:00/22:30）
   ↓
2. scheduled_broadcast.py 调用 _render_broadcast_text()
   ↓
3. 调用 build_broadcast_context() 构建播报上下文
   ↓
4. theme_pools 生成：
   - 主题（theme）
   - 语气（tone）
   - 黑话暗示（slang_hint）
   - 图片暗示（photo_hint）
   - 转化引导（conversion_hint）
   ↓
5. 将暗示融入播报 footer
   ↓
6. broadcast_formatter.py 生成 HTML 卡片
   ↓
7. 发送到 Telegram
```

---

## 3. 主题池设计

### 3.1 早安播报（10:00）

**主题池**（5个）：
1. weather - 从天气聊起（关键词：阳光、温度、风）
2. life - 生活碎片（关键词：早餐、通勤、日常）
3. question - 反问开场（关键词：今天、计划、期待）
4. mood - 心情分享（关键词：醒来、状态、感觉）
5. story - 小故事（关键词：刚才、遇到、想到）

**语气池**（3个）：
1. fresh - 清新、期待、轻盈
2. lazy - 懒懒的、没睡醒、随意
3. confident - 小自信、状态好、积极

**轮换规则**：按星期几（0-6）选择主题，`weekday % 5`

### 3.2 午后播报（14:30）

**主题池**（5个）：
1. detail - 小细节（关键词：窗台、咖啡、光线）
2. lazy - 慵懒午后（关键词：犯困、发呆、休息）
3. curious - 制造好奇（关键词：刚才、发现、有趣）
4. life - 生活观察（关键词：午饭、同事、闲聊）
5. question - 提问互动（关键词：你们、下午、在忙）

**语气池**（3个）：
1. casual - 随意、放松、不强求
2. curious - 好奇、探索、想聊聊
3. sleepy - 犯困、慵懒、软软的

### 3.3 晚间播报（19:00）

**主题池**（5个）：
1. story - 故事感（关键词：今天、发生、想起）
2. emotion - 走心表达（关键词：辛苦、感受、心情）
3. memory - 回忆杀（关键词：以前、记得、那时候）
4. observation - 小观察（关键词：窗外、天色、安静）
5. mood - 情绪分享（关键词：放松、疲惫、满足）

**语气池**（3个）：
1. warm - 温暖、走心、共鸣
2. story - 故事感、沉浸、画面
3. cool - 高冷、距离、神秘

### 3.4 深夜播报（22:30）

**主题池**（5个）：
1. private - 私密语气（关键词：被子、安静、只有）
2. atmosphere - 氛围感（关键词：夜、灯光、影子）
3. emotion - 深夜情绪（关键词：想你、睡不着、心事）
4. hint - 暗示引导（关键词：有些、不太适合、私聊）
5. mystery - 神秘感（关键词：秘密、隐藏、专属）

**语气池**（3个）：
1. intimate - 私密、亲近、悄悄话
2. mysterious - 神秘、暗示、留白
3. seductive - 诱惑、氛围、画面感

---

## 4. 黑话软植入

### 4.1 黑话定义

| 黑话 | 含义 | 暗示场景 |
|------|------|----------|
| 门槛 | 入会价格 | 早安/午后（轻度暗示） |
| 至臻 | VIP系列 | 早安/午后（轻度暗示） |
| 全享 | 年费会员 | 晚间/深夜（强暗示） |
| 原味 | 贴身物品 | 晚间/深夜（强暗示） |
| 定制 | 1v1拍摄 | 晚间/深夜（强暗示） |

### 4.2 黑话模板示例

**门槛**：
- "有些人已经跨过那个门槛了，里面的世界不太一样"
- "关于那个门槛的事，私聊说更方便"
- "门槛不高，但里面的东西绝对超值"

**至臻**：
- "有些片段只放在至臻那边，群里不太方便发"
- "至臻系列刚更新了一些新内容"
- "想体验最完整的我，至臻那边有"

**全享**：
- "全享的用户能看到更多独家内容"
- "有些特权只有全享才有，你懂的"
- "全享那边刚上了新东西，性价比很高"

**原味**：
- "有些贴身的小物件，每件都是独一无二的"
- "刚整理了一些特别的收藏，数量有限"
- "有些东西只有我能给你，别的地方看不到"

**定制**：
- "刚收到一个定制请求，有点兴奋"
- "如果你想看什么特定的，可以私聊我写剧本"
- "定制的内容只属于你一个人"

### 4.3 时段分配策略

- **早安/午后**：轻度黑话（门槛、至臻）+ 轻度图片（照片、福利）
- **晚间/深夜**：暗示性强的黑话（全享、原味、定制）+ 暗示性强的图片（自拍、视频、看图）

---

## 5. 图片关键词暗示

### 5.1 关键词定义

| 关键词 | 暗示内容 | 使用场景 |
|--------|----------|----------|
| 照片 | 私密照片 | 早安/午后 |
| 福利 | 专属福利 | 早安/午后 |
| 自拍 | 私人自拍 | 晚间/深夜 |
| 视频 | 敏感视频 | 晚间/深夜 |
| 看图 | 更多选择 | 晚间/深夜 |

### 5.2 暗示模板示例

**照片**：
- "刚整理了一些照片，但有些不太适合发在群里"
- "有些照片只放在那边，想看的来找我"
- "照片太多了，有些私密的只给特定的人看"

**福利**：
- "今天有点小福利，但只给主动的人"
- "福利这种事，私聊说比较方便"
- "有些福利不能公开说，你懂的"

---

## 6. 转化引导

### 6.1 引导模板

1. "有些事私聊说更方便"
2. "来 @MorychannelBot 找我聊"
3. "那边有更多内容"
4. "主动的人能看到更多"
5. "有些话群里不方便说"
6. "想知道更多？来找我呀"
7. "详情私聊我说"
8. "有些内容只给主动的人"
9. "来解锁更多特权"
10. "有些惊喜只给特定的人"

### 6.2 使用位置

所有转化引导都放在 `<blockquote expandable>` 折叠区，不破坏正文阅读体验。

---

## 7. 种子随机机制

### 7.1 种子生成

```python
def _get_seed(date: datetime, period: str, item_id: str = "") -> str:
    """生成确定性种子，同一天同一时段内容一致。"""
    date_str = date.strftime("%Y-%m-%d")
    raw = f"{item_id}|{period}|{date_str}"
    return hashlib.md5(raw.encode()).hexdigest()
```

### 7.2 随机数生成器

```python
def _seeded_random(seed: str):
    """基于种子的伪随机数生成器。"""
    import random
    seed_int = int(seed[:8], 16)
    return random.Random(seed_int)
```

### 7.3 轮换规则

- **主题轮换**：`weekday % len(pool)`，同一天同一时段主题固定
- **语气轮换**：`(day + hour) % len(tone_keys)`，按日期+时段选择
- **黑话/图片轮换**：基于种子随机选择，按时段分配强度

---

## 8. 配置项

### 8.1 开关配置

```json
{
  "BROADCAST_THEME_ENABLED": true
}
```

- **默认值**：true（开启）
- **作用**：控制是否使用多样性引擎
- **关闭效果**：回退到旧的 `_pick_soft_template_variant()` 逻辑

### 8.2 配置位置

- **配置文件**：`config.json.example`
- **读取方式**：`config.get("BROADCAST_THEME_ENABLED", True)`

---

## 9. 集成方式

### 9.1 播报渲染流程

```python
def _render_broadcast_text(item: dict, user_profile: dict = None, config: dict = None):
    """按配置把播报渲染成更适合 Telegram 的 HTML 卡片（富文本升级版 v5.0，含多样性引擎）。"""
    
    # 1. 提取基础信息
    period = str(item.get("period", "") or "").strip()
    broadcast_id = str(item.get("id", "") or "").strip()
    footer = str(item.get("footer", "") or "").strip()
    
    # 2. 使用多样性引擎构建播报上下文
    theme_enabled = bool((config or {}).get("BROADCAST_THEME_ENABLED", True))
    if theme_enabled and period:
        try:
            ctx = build_broadcast_context(period=period, item_id=broadcast_id)
            
            # 3. 将黑话暗示和图片暗示融入折叠区
            theme_hints = []
            if ctx.get("slang_hint"):
                theme_hints.append(ctx["slang_hint"])
            if ctx.get("photo_hint"):
                theme_hints.append(ctx["photo_hint"])
            if ctx.get("conversion_hint"):
                theme_hints.append(ctx["conversion_hint"])
            
            if theme_hints:
                theme_footer = "\n\n".join(theme_hints)
                footer = _merge_footer_with_variant(footer, theme_footer)
        except Exception as e:
            logger.debug(f"多样性引擎异常（已忽略，回退默认）: {e}")
            footer = _merge_footer_with_variant(footer, _pick_soft_template_variant(item, config))
    
    # 4. 生成 HTML 卡片
    return build_rich_broadcast_html(
        title=title,
        body=content,
        footer=footer,
        badge=badge,
        period=period,
        user_profile=user_profile,
    ), "HTML"
```

### 9.2 异常处理

- 引擎异常时自动回退到旧逻辑
- 不影响播报发送
- 记录 debug 日志

---

## 10. 测试验证

### 10.1 语法检查

```bash
python -m py_compile core/theme_pools.py
python -m py_compile modules/scheduled_broadcast.py
```

### 10.2 功能验证

1. **主题轮换验证**：
   - 周一到周日，每天主题不同
   - 同一天同一时段主题固定

2. **黑话植入验证**：
   - 早安/午后用轻度黑话（门槛、至臻）
   - 晚间/深夜用暗示性强的黑话（全享、原味、定制）

3. **转化引导验证**：
   - 底部折叠区包含转化引导
   - 引导文案自然，不硬广

---

## 11. 部署清单

### 11.1 新增文件

- `core/theme_pools.py`（300行）

### 11.2 修改文件

- `modules/scheduled_broadcast.py`（集成引擎）
- `config.json.example`（新增配置项）

### 11.3 部署步骤

1. 上传 `core/theme_pools.py` 到 VPS
2. 更新 `modules/scheduled_broadcast.py`
3. 更新 `config.json`（新增 `BROADCAST_THEME_ENABLED: true`）
4. 重启 Bot 服务
5. 验证播报内容

---

## 12. 未来优化方向

1. **AI 生成话术**：使用 AI 引擎动态生成播报内容，替代静态模板
2. **用户画像融合**：根据用户兴趣自动调整主题和语气
3. **A/B 测试**：对比不同黑话策略的转化率
4. **数据追踪**：记录播报点击率、转化率，优化模板
5. **天气/热点融合**：接入天气 API 和热搜 API，实时调整内容

---

## 13. 相关文档

- [AGENTS.md](file:///d:/Documents/Syncdisk/Work/project/mory_assistant/AGENTS.md) - 项目规则
- [CHANGELOG.md](file:///d:/Documents/Syncdisk/Work/project/mory_assistant/CHANGELOG.md) - 变更日志
- [broadcast-rich-format.md](file:///d:/Documents/Syncdisk/Work/project/mory_assistant/docs/technical/broadcast-rich-format.md) - 富文本播报格式

---

**文档维护者**：Trae Solo CN  
**最后更新**：2026-06-17  
**版本号**：v5.19.0
