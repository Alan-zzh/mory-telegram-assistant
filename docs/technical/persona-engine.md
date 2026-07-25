# Mory 人设引擎 v5.35.19 — 技术文档

> **被 [AGENTS.md](../../AGENTS.md) 索引引用 · 适用版本：v5.35.10+**
> **最后更新**：2026-07-25（v5.35.19 群验证数字前置降噪）

---

## 概述

人设引擎是 Mory 群聊/私聊的"情绪心脏"。v5.21.0 起，**单一的 ANTI_TEMPLATES 池升级为 4 桶情绪反模板 + 动态 LLM 参数矩阵**，让模型从底层参数到顶层 prompt 都能按场景切换。

### 核心目标
1. **去 AI 痕迹**：避免单一反模板池用久也变模板
2. **情绪拟真**：清冷 / 毒舌 / 撒娇按场景自适应切换
3. **参数动态化**：Temperature / Top_P / Penalty 不再写死，按亲密度+时段查表

---

## 1. 架构

```
用户消息
  ↓
ask(question, is_priv, user_profile, ...)
  ↓
├─ 1. 设置 context（_ctx_is_priv/_ctx_message/_ctx_intimacy_score/_ctx_intimacy_level）
├─ 2. _build_persona()
│   ├─ BASE_PERSONA + KNOWLEDGE
│   ├─ 动态人格碎片
│   ├─ 情绪状态机（按时段）
│   ├─ 4 桶反模板（v5.21.0 重写）★ 改造点
│   ├─ 亲密度 + 挑逗话术
│   ├─ 交互语境 + 转化引导 + 去 AI 化铁律
│   ├─ 最终正常聊天输出合同
│   └─ 私聊/群聊差异化
├─ 3. payload（v5.21.0 改造点）★ temperature/top_p/penalties 用动态查表
    └─ _get_dynamic_llm_params(is_priv, intimacy_level, hour)
       └─ _DEFAULT_EMOTION_TEMP_MAP[(scene, level, hour_bucket)]
└─ 4. 输出后置过滤
    ├─ AI 身份泄露过滤
    └─ 括号/星号动作、心理旁白、镜头描写过滤
```

---

## 2. 4 桶反模板机制

### 2.1 桶定义（`_DEFAULT_EMOTION_BUCKETS`）

| 桶 | 触发场景 | 比例 | 核心约束 |
|---|---|---|---|
| **cold** (清冷) | 默认底色，群聊常态 / 陌生 / 对方冷淡 | 群聊 70%+ | 句号收尾、≤15 字、禁社交润滑词 |
| **savage** (毒舌) | 调戏 / 擦边 / 反复质疑 / 敷衍短消息 | 25% | 反讽 + 转折词 + 高姿态 |
| **soft** (撒娇) | 私聊 + 熟人 + 22:00-04:00 | 15%（限私聊） | 含 '…' + 句尾嘛/呢/啊 + 半截话 |
| **common** (通用) | 每轮必抽 1 条 | 100% | 禁'我'开头 / 列表 / 排比 / 解释动机 |

### 2.2 桶选择算法（`_select_emotion_bucket`）

```python
scores = {"cold": 1.0, "savage": 0.0, "soft": 0.0}  # cold 是默认兜底

# 遍历触发器匹配规则
for rule in triggers_cfg.get(bucket, []):
    if rule 匹配当前 context（is_priv/intimacy/hour/keywords/msg_len）:
        scores[bucket] += rule.weight

return max(scores, key=scores.get)
```

**默认胜出 cold**（1.0 底分），只有触发器规则匹配到对应桶且得分超过 cold 时才会切换。

### 2.3 注入策略（`_get_anti_template_hint`）

```python
# 人设引擎开启时（PERSONA_ENGINE_ENABLED=true，默认）：
emotion_bucket = _select_emotion_bucket(triggers)            # 1. 选桶
parts.append(rng.choice(buckets_cfg[emotion_bucket]))        # 2. 抽情绪桶 1 条（80% 概率）
parts.append(rng.choice(buckets_cfg["common"]))              # 3. 抽通用桶 1 条（100%）
return f"【本轮人设指令 / 情绪桶：{emotion_bucket}】\n" + "\n".join(parts)

# 关闭时回退老逻辑：50% 概率从 ANTI_TEMPLATES 抽 1 条
```

**为什么 80% 而非 100% 注入情绪桶**？
- 100% 注入会让模型太"听话"，反模板本身也会变模板
- 80% 是平衡：保留随机性，同时不丢失情绪指导

---

## 3. 动态 LLM 参数矩阵

### 3.1 设计原则

| 场景 | Temperature | Top_P | Freq Penalty | Pres Penalty | 理由 |
|---|---|---|---|---|---|
| 群聊陌生人 早 | 0.85 | 0.88 | 0.70 | 0.55 | 冷 + 高度去重（防止套话） |
| 群聊路人 午 | 0.92 | 0.92 | 0.60 | 0.45 | 适度发散 + 中度去重 |
| 私聊陌生人 | 0.90 | 0.92 | 0.60 | 0.45 | 基础好奇 + 中度去重 |
| 私聊熟人 夜 | 0.98 | 0.94 | 0.50 | 0.40 | 偏走心 |
| 私聊暧昧 深夜 | 1.10 | 0.95 | 0.40 | 0.30 | 高度发散 + 低去重（允许自然重复） |
| 私聊亲密 凌晨 | 1.15 | 0.96 | 0.40 | 0.30 | 极端发散（最深情绪） |

### 3.2 查表逻辑（`_get_dynamic_llm_params`）

```python
hour_bucket = _bucket_hour(hour)  # midnight/morning/noon/afternoon/evening/night/any
key = ("priv" if is_priv else "group", intimacy_level, hour_bucket)
return _DEFAULT_EMOTION_TEMP_MAP.get(key)
       or _DEFAULT_EMOTION_TEMP_MAP.get((scene, level, "any"))  # 退到 any 时段
       or (TEMPERATURE, TOP_P, FREQUENCY_PENALTY, PRESENCE_PENALTY)  # 最终兜底
```

**亲密度等级映射**（flirt_level 0-4 = 陌生人/路人/熟人/暧昧/亲密）

### 3.3 时段归一化

```python
0-4   → "midnight"     # 凌晨（最容易暧昧）
5-11  → "morning"      # 早
12-13 → "noon"         # 午
14-17 → "afternoon"    # 下午
18-20 → "evening"      # 傍晚
21-23 → "night"        # 夜
```

---

## 4. 12 条去 AI 痕迹铁律

落地在 `SYSTEM_PROMPT` 末尾。每条都是反 AI 体感的关键：

| # | 铁律 | 反例 | 正例 |
|---|------|------|------|
| 1 | 省略号当语气不用当符号 | "好的…" | "…行吧，看你。" |
| 2 | 波浪号 '～' 月配额 ≤ 5 条/天 | 群聊每条都带～ | 群聊零波浪号 |
| 3 | 感叹号 1 轮 ≤ 1 个 | "好的！！！" | "好。" |
| 4 | 整段 ≤ 2 行 30 字 | 一坨 200 字 | 三条连发：8+15+6 字 |
| 5 | 语气词只用 1 个层级 | "嗯嗯好的呢~" | "嗯。" |
| 6 | 偶尔错别字（5% 概率） | 每条字字斟酌 | "再考虑下吧" |
| 7 | 网络缩写穿插 | 永远书面语 | "这理由 6" |
| 8 | 主动留白+自我打断 | 每句说完整 | "我跟你说个事…算了" |
| 9 | 数字/英文/表情包穿插 | 纯中文 | "kkk" |
| 10 | 拒绝排比/工整对仗 | "我欣赏你的勇气、你的智慧、你的真诚" | "你胆子挺肥的" |
| 11 | 不解释动机 | "因为我觉得你可能想…" | "你想多了" |
| 12 | 永远不主动提价格/产品名 | "149.9 包月哦" | "想了解私我" |

### 4.1 正常聊天输出门禁（v5.35.10）

- 人设保留：清冷、傲娇、温柔、亲密度和群聊/私聊差异继续生效。
- 表达边界：人格碎片只描述语气、措辞和回应策略，不再注入肢体动作或虚构生活状态。
- 旧配置兼容：`BASE_PERSONA` / `SYSTEM_PROMPT` 中鼓励 `*动作*`、肢体暗示或舞台旁白的行会自动失效，其余人设和业务知识保持不变。
- 最终合同：每个非新闻回复在模型适配和记忆注入之后追加最高优先级约束，只允许输出正常聊天正文。
- 短消息边界：对“在吗”或普通问候直接回应并问来意；对方没有先调情时，不主动追加“想我了”等暧昧戏码。
- 后置兜底：`_strip_stage_directions()` 删除带动作线索的中文/英文/方括号和星号片段；正常事实括号与普通强调文本不受影响。
- 缓存边界：历史语义缓存命中后仍先过同一门禁；新结果只缓存过滤后的正文，旧舞台化内容不能绕过模型输出过滤重新出现。

### 4.2 粉丝群定时问候继承（v5.35.12）

- `morning` / `afternoon` / `evening` / `night` 不再用孤立模板完全替掉主助理人设；运行时从 `BASE_PERSONA` 提取“身份锚定”和“性格光谱”，再叠加粉丝群专用短问候要求。
- 问候只继承性格和亲近感，不加载业务知识、转化钩子或单人记忆，避免群发消息变成销售私聊。
- 旧配置缺少粉丝群新契约时自动忽略；最终质量门禁拒绝多线程、任务、通知、窗口、待办、编程、代码、模型等技术/效率用语。
- 路由只选通用对话模型，名称含 `code` / `coder` / `coding` 的专用模型直接跳过；模型超时或输出不合格时使用同样走心、非技术化的人工底稿。

### 4.3 近期对话承接与单目标成交链（v5.35.16）

- 当前轮从 `conversation_telemetry` 读取同一 `user_id + chat_id` 最近30分钟的3轮问答，最多向模型传6条 `user/assistant` 消息；跨群、跨私聊和过期内容不进入当前上下文。
- `core.growth_optimizer.resolve_conversion_target()` 是成交目标唯一判定源：普通聊天、拒绝、取消和定制概念咨询为 `none`；价格、内容、权益和了解阶段为 `preview`；明确购买、套餐选择、确认看过预览或明确定制为 `subscribe`。
- “定制舞”可作为直接需求锚点，但“定制舞是什么/介绍一下”只解释；后续“就是这个味”“喜欢这种风格”“卡点变装”等承接短句结合近期上下文继续保持购买阶段。
- 最近 6 条助手历史已经给过下单入口时，后续确认和细节补充只承接内容，不重复链接或按钮；用户明确再次询问怎么买、下单链接或下单入口时才允许重发。
- 普通聊天不再按第 3/5/6 轮硬塞销售或另起无上下文追加回复。低频随机推进只改变是否在当前话题后自然带一次预览，不会直接跳到下单。
- 群商业承接只在当前群回复，不再额外轰炸用户私聊；私聊销售回复只用正文可点击入口且零按钮，群聊也只能生成一个与正文目标一致的按钮。未解决问题只给人工入口，预览、下单和人工入口不在同一轮混用。
- 模型输出只做最小入口校正，保留清冷、傲娇、温柔的人设化承接；禁止用固定模板整体覆盖，也禁止承诺未由业务真相源确认的定制表单、服务能力、价格、福利、交付或人工回访。
- 语义缓存键由“近期上下文 + 当前句 + mode”组成；相同短句在不同话题里不会命中同一缓存。

---

## 5. 配置开关

```json
{
  "PERSONA_ENGINE_ENABLED": true,   // 关闭后回退单一 ANTI_TEMPLATES 池
  "EMOTION_BUCKETS": {              // 可选：覆盖代码默认 4 桶内容
    "cold": [...],
    "savage": [...],
    "soft": [...],
    "common": [...]
  },
  "EMOTION_TRIGGERS": {             // 可选：覆盖默认触发规则
    "soft": [...],
    "savage": [...]
  },
  "EMOTION_TEMP_MAP": {             // 可选：覆盖默认 21 组参数
    "(scene, level, hour_bucket)": [temp, top_p, freq_pen, pres_pen]
  }
}
```

**3-处同步**（项目铁律）：
1. `config.json.example` — 默认配置模板
2. `core/ai_engine.py` — `self.config.get(KEY, DEFAULT)` 读取
3. `dashboard/api/config_api.py` — `ALLOWED_CONFIG_FIELDS` 白名单 + `dashboard/api/settings_api.py` 暴露 `/api/settings/persona` 读写

---

## 6. 风险与回滚

### 风险
- **人设引擎开启后所有 LLM 调用都查表**：每次多 2-3 次 dict.get + 4 桶随机，几乎无性能影响
- **温度升高 → 内容更发散**：深夜亲密度≥3 时 1.10-1.15，可能出现意外内容。已通过 4 桶约束降低风险
- **桶选择错位**：触发器规则没覆盖到的场景都走 cold（默认底色），不会失控

### 回滚
```json
{
  "PERSONA_ENGINE_ENABLED": false   // 一行回滚到 v5.18.6 行为
}
```

或者从 Git 回退 `_get_anti_template_hint` / `ask()` payload 两处。

---

## 7. 验证

- `python -m py_compile core/ai_engine.py` → OK
- `pytest tests/unit/test_v5_19_0_persona_engine.py` → 4 桶 + 触发器 + 温度矩阵 + savage 触发 + 动态参数查表 全部通过
- `pytest tests/unit/` → 131 passed, 7 skipped in 0.93s

---

## 8. 扩展方向

1. **桶内容可视化编辑**：Dashboard 暴露 4 桶编辑 UI
2. **A/B 测试桶效果**：对比 cold-only vs 4-bucket 的人设自然度
3. **情绪打点**：记录每轮实际命中的桶，做"哪种桶用户回应最好"分析
4. **桶选择 LLM 化**：当前是规则引擎，可升级为 LLM 精分类（参考 v5.20.0 intent_router 架构）
