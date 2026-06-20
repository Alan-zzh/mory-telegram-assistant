# Mory 人设引擎 v5.21.0 — 技术文档

> **被 [AGENTS.md](../../AGENTS.md) 索引引用 · 适用版本：v5.21.0+**
> **最后更新**：2026-06-17（v5.21.0 [Trae Solo CN] 人设引擎大改）

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
│   ├─ 场景模拟 + 转化引导 + 去 AI 化铁律
│   └─ 私聊/群聊差异化
└─ 3. payload（v5.21.0 改造点）★ temperature/top_p/penalties 用动态查表
    └─ _get_dynamic_llm_params(is_priv, intimacy_level, hour)
       └─ _DEFAULT_EMOTION_TEMP_MAP[(scene, level, hour_bucket)]
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
