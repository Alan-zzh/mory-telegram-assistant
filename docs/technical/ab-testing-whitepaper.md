# A/B 测试与闭环优化白皮书

> 版本：v5.19.0 | 适用：Mory 小助理 | 更新：2026-06-17

---

## 1. 实验设计：萌化模板 vs 清冷傲娇

### 1.1 实验目标

对比两种人设话术在 **付费转化率、用户留存、交互深度** 上的差异：

| 维度 | 版本 A（萌化模板） | 版本 B（清冷傲娇） |
|------|-------------------|-------------------|
| 语气词 | 嘛、呢、呀、~ | 句号、省略号、转折词 |
| emoji | 高频 | 低频 |
| 毒舌比例 | 15% | 35% |
| 撒娇比例 | 25% | 10%（仅熟人） |
| 引导转化 | 直接热情 | 含蓄高冷 |

### 1.2 分流策略：稳定哈希 + 穿帮防护

**核心原则：同一群内的所有用户必须看到相同版本，避免"穿帮"。**

```
scope=broadcast  → 按 chat_id 哈希分流（群播报）
scope=private    → 按 user_id 哈希分流（私聊/群回复）
```

哈希算法：

```python
def _hash_entity(entity_id: int, experiment_id: str, salt: str = "mory_ab_v1") -> int:
    raw = f"{salt}:{experiment_id}:{entity_id}"
    return int(hashlib.md5(raw.encode("utf-8")).hexdigest(), 16)

# 桶位 0~99，traffic_split=50 时，0~49 为 B 组，50~99 为 A 组
```

**为何用 MD5 而非 random？**
- 保证同一用户每次进入同一分组，避免切换设备/重启后"变组"
- 无需持久化所有用户，新用户首次访问时实时计算即可

**穿帮防护三层机制：**

1. **群播报层**：`scope=broadcast` 按 `chat_id` 分流，同一群始终同一版本
2. **群回复层**：`scope=private` 按 `user_id` 分流，群内不同用户可不同版本（自然，因为是对话）
3. **持久化层**：首次分配后写入 `ab_user_assignments` 表，后续优先查表

### 1.3 实验生命周期

```
created → running → paused → stopped
   ↓
rolled_back（自动回滚后进入此状态）
```

- `rolled_back`：新用户全部分到 A（对照组），老用户保持原分组（避免体验突变）
- 状态变更由 Guardian 自动触发，或管理员通过 Dashboard 手动触发

---

## 2. 核心指标（KPI）与 Telemetry 系统

### 2.1 事件类型枚举

| 事件 | 说明 | 触发时机 |
|------|------|----------|
| `exposure` | 曝光 | 用户收到含实验变体的消息 |
| `engage` | 互动 | 用户主动发消息 |
| `button_click` | 按钮点击 | 点击内联按钮 |
| `consult` | 咨询 | 用户询问价格/产品 |
| `add_cart` | 加购 | 用户表达购买意向 |
| `conversion` | 付费转化 | 完成下单（需业务层调用） |
| `group_leave` | 退群 | 用户离开群组 |
| `complaint` | 投诉 | 用户表达强烈不满 |
| `cart_abandoned` | 购物车放弃 | 加购后 N 分钟未下单 |
| `cart_recovered` | 购物车挽回 | 挽回消息后完成下单 |

### 2.2 数据库表设计

#### ab_experiments（实验定义）

```sql
CREATE TABLE IF NOT EXISTS ab_experiments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    description TEXT DEFAULT '',
    variant_a_name TEXT DEFAULT 'A',
    variant_b_name TEXT DEFAULT 'B',
    variant_a_config TEXT DEFAULT '{}',
    variant_b_config TEXT DEFAULT '{}',
    traffic_split INTEGER DEFAULT 50,
    scope TEXT DEFAULT 'private',
    status TEXT DEFAULT 'running',
    start_time INTEGER DEFAULT 0,
    end_time INTEGER DEFAULT 0,
    rolled_back_at INTEGER DEFAULT 0,
    created_at INTEGER DEFAULT 0
);
```

#### telemetry_events（事件埋点）

```sql
CREATE TABLE IF NOT EXISTS telemetry_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER DEFAULT 0,
    experiment_id TEXT DEFAULT '',
    variant TEXT DEFAULT '',
    event_type TEXT NOT NULL,
    event_value REAL DEFAULT 0,
    event_meta TEXT DEFAULT '{}',
    ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_telemetry_exp ON telemetry_events(experiment_id, variant, event_type, ts);
CREATE INDEX IF NOT EXISTS idx_telemetry_user ON telemetry_events(user_id, ts);
```

#### conversation_telemetry（对话埋点）

```sql
CREATE TABLE IF NOT EXISTS conversation_telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER DEFAULT 0,
    experiment_id TEXT DEFAULT '',
    variant TEXT DEFAULT '',
    message_text TEXT DEFAULT '',
    bot_reply_text TEXT DEFAULT '',
    intent TEXT DEFAULT '',
    sentiment TEXT DEFAULT '',
    round_num INTEGER DEFAULT 0,
    ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_telemetry_exp ON conversation_telemetry(experiment_id, variant, ts);
```

### 2.3 核心 SQL 报表

#### 转化漏斗（周度）

```sql
SELECT
    variant,
    COUNT(DISTINCT CASE WHEN event_type='exposure' THEN user_id END) AS exposed,
    COUNT(DISTINCT CASE WHEN event_type='engage' THEN user_id END) AS engaged,
    COUNT(DISTINCT CASE WHEN event_type='button_click' THEN user_id END) AS clicked,
    COUNT(DISTINCT CASE WHEN event_type='conversion' THEN user_id END) AS converted,
    COUNT(DISTINCT CASE WHEN event_type='group_leave' THEN user_id END) AS churned
FROM telemetry_events
WHERE experiment_id = 'persona_cute_vs_cool'
  AND ts >= strftime('%s', 'now', '-7 days')
GROUP BY variant;
```

#### 每日 KPI 时序

```sql
SELECT
    date(ts, 'unixepoch', 'localtime') AS day,
    variant,
    COUNT(DISTINCT user_id) AS dau,
    SUM(CASE WHEN event_type='button_click' THEN 1 ELSE 0 END) AS clicks,
    SUM(CASE WHEN event_type='conversion' THEN 1 ELSE 0 END) AS conversions,
    SUM(CASE WHEN event_type='group_leave' THEN 1 ELSE 0 END) AS leaves
FROM telemetry_events
WHERE experiment_id = 'persona_cute_vs_cool'
  AND ts >= strftime('%s', 'now', '-14 days')
GROUP BY day, variant
ORDER BY day, variant;
```

#### 单客交互价值（LTV 估算）

```sql
SELECT
    variant,
    AVG(conversion_value) AS avg_ltv,
    AVG(interaction_rounds) AS avg_rounds
FROM (
    SELECT
        variant,
        user_id,
        SUM(CASE WHEN event_type='conversion' THEN event_value ELSE 0 END) AS conversion_value,
        COUNT(CASE WHEN event_type='engage' THEN 1 END) AS interaction_rounds
    FROM telemetry_events
    WHERE experiment_id = 'persona_cute_vs_cool'
    GROUP BY variant, user_id
)
GROUP BY variant;
```

---

## 3. 闭环反馈优化漏斗

### 3.1 周度自动分析机制

**触发时间**：每周一凌晨 02:00（`ab_weekly_report` 定时任务）

**分析流程：**

```
1. 读取上周 telemetry_events & conversation_telemetry
2. 计算 A/B 两组核心指标（CTR、转化率、退群率）
3. 提取 Top 5 正向话术特征（高转化用户对话高频词）
4. 提取 Top 5 负向毒点词汇（流失用户对话高频词）
5. 生成运营建议并持久化到 weekly_ab_report
```

### 3.2 话术特征提取算法

无需 NLP 库，采用 **2-4 字滑动窗口 + 停用词过滤**：

```python
from collections import Counter

def get_top_features(texts: list, limit: int = 5) -> list:
    word_counter = Counter()
    stopwords = {"的", "了", "是", "我", "你", ...}  # 约 80 个高频虚词
    for text in texts:
        for length in (2, 3, 4):
            for i in range(len(text) - length + 1):
                word = text[i:i + length]
                if any(sw in word for sw in stopwords):
                    continue
                word_counter[word] += 1
    return [{"word": w, "count": c} for w, c in word_counter.most_common(limit)]
```

**正向特征来源**：`conversion` 事件用户的 `bot_reply_text`
**负向毒点来源**：`group_leave` 事件用户的 `bot_reply_text`

### 3.3 报告表示例

| 指标 | A组（萌化） | B组（清冷） | 差异 |
|------|------------|------------|------|
| 曝光→点击 CTR | 12.5% | 9.8% | A +27% |
| 点击→转化率 | 3.2% | 4.1% | B +28% |
| 整体转化率 | 0.40% | 0.40% | 持平 |
| 退群率 | 0.8% | 2.1% | B +162% |

**运营建议输出示例：**

```
B组表现更优：转化率4.10% > A组3.20%，且退群率可控。
建议将 B 组策略逐步全量推广。

高转化话术特征：私聊、精选、完整、质感、期待。
建议在下一轮 Prompt 中保留并强化这些表达。

流失用户高频触发词：太贵、骗子、犹豫、想想、对比。
建议下一轮实验中剔除或替换这些词汇。
```

---

## 4. 异常指标预警与自动回滚

### 4.1 阈值配置

在 `config.json` 的 `AB_TEST_CONFIG.experiments[].guardian` 中配置：

```json
{
  "guardian": {
    "max_group_leave_rate_delta": 0.05,
    "max_complaint_rate": 0.03,
    "min_conversion_rate_ratio": 0.50
  }
}
```

| 阈值 | 说明 | 默认值 |
|------|------|--------|
| `max_group_leave_rate_delta` | B 组退群率相对 A 组的最大允许增幅 | 5% |
| `max_complaint_rate` | 单组投诉率上限 | 3% |
| `min_conversion_rate_ratio` | 实验组转化率不得低于对照组的比率 | 50% |

### 4.2 巡检机制

**触发频率**：每 5 分钟（`ab_guardian` 定时任务）

**检查逻辑**：取最近 24h 数据，逐实验比对 A/B 两组

```python
def check_all() -> list:
    alerts = []
    for exp in running_experiments:
        funnel = get_conversion_funnel(exp.id, last_24h)
        # 1. 退群率 delta 检查
        if b_churn > a_churn * (1 + max_leave_delta):
            alerts.append({"alert_type": "churn_rate", "bad_variant": "B"})
        # 2. 转化率 ratio 检查
        if b_conv < a_conv * min_conversion_ratio:
            alerts.append({"alert_type": "conversion_drop", "bad_variant": "B"})
    return alerts
```

### 4.3 自动回滚流程

```
Guardian 检测到异常
    → 触发 rollback(experiment_id)
    → 更新 ab_experiments.status = 'rolled_back'
    → 新用户全部分到 A 组
    → 老用户保持原分组（避免体验突变）
    → 记录 ab_guardian_log
    → 发送 TG 消息通知管理员
```

**管理员通知格式：**

```
🚨 A/B 测试自动回滚通知
实验ID: persona_cute_vs_cool
告警类型: churn_rate
原因: B组退群率(2.10%)显著高于A组(0.80%)
问题版本: B
动作: 已自动回滚至对照组(A组)，新用户将不再进入问题版本。
```

### 4.4 回滚后观察期

- 回滚后 Guardian 继续巡检，但只监控 A 组指标是否恢复正常
- 建议观察 24~48 小时后再决定是否重新启动实验（调整 variant_b 配置后）

---

## 5. 接入指南

### 5.1 启用实验

1. 修改 `config.json`：
   ```json
   "AB_TEST_CONFIG": {
     "enabled": true,
     "telemetry_enabled": true,
     "weekly_report_enabled": true,
     "experiments": [ ... ]
   }
   ```
2. 重启 Bot，实验自动同步到数据库
3. 在 `core/ai_engine.py` 中调用 `inject_prompt()` 注入实验 prompt

### 5.2 业务层埋点示例

```python
from core.telemetry import Telemetry

telemetry = Telemetry(db, config)

# 用户点击按钮
telemetry.log_button_click(user_id, chat_id, "buy_vip", "success")

# 用户完成付费
telemetry.log_conversion(user_id, chat_id, "persona_cute_vs_cool", "B", value=149.9)

# 用户退群（由群成员变更事件触发）
telemetry.log_group_leave(user_id, chat_id, "persona_cute_vs_cool", "B")
```

### 5.3 Dashboard 查看报告

周度报告写入 `weekly_ab_report` 表，可通过以下方式查看：

- SQLite 直接查询
- 后续可扩展 Dashboard API 页面展示

---

## 6. 文件索引

| 文件 | 职责 |
|------|------|
| `core/ab_testing.py` | A/B 引擎：哈希分流、Prompt 注入、实验管理 |
| `core/telemetry.py` | Telemetry 客户端：事件/对话埋点、情感分析 |
| `core/db_repos/ab_test_repo.py` | 数据层：实验 CRUD、漏斗统计、特征提取 |
| `modules/ab_insights.py` | 周度分析：Top 5 特征/毒点、生成运营建议 |
| `modules/ab_guardian.py` | 异常守护：阈值巡检、自动回滚、管理员通知 |
| `tasks/analytics/ab_guardian_task.py` / `ab_weekly_task.py` | BaseTask 自动发现：ab_guardian（5min）、ab_weekly（周一 02:00） |
| `core/database.py` | 表结构初始化：6 张 A/B 测试相关表 |
| `config.json.example` | 配置模板：AB_TEST_CONFIG 完整示例 |

---

## 7. 定价锚点参考

| 产品 | 价格 | 实验关注指标 |
|------|------|-------------|
| 至臻精选（月） | 149.9 元 | 月付转化率、首购客单价 |
| 精选图集（季） | 228.8 元 | 季付占比、订阅续费率 |
| 至臻全享（年） | 999 元 | 年付大单转化、高价值用户识别 |

建议在实验分析中按 **客单价分层** 观察：不同话术对高价产品（999 元年费）的转化影响可能显著不同于低价产品（149.9 元月费）。
