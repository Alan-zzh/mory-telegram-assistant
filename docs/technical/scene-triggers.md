# 场景化触发引擎（v5.19.0）

> [TRAE SOLO CN] v5.19.0 动态意图识别与场景触发引擎技术文档
> 最后更新：2026-06-17

## 1. 架构概览

```
消息进入 do_dispatch
  │
  ├─ P0-P3.5 安全层（不变）
  │
  ├─ P3.6 意图路由层（新增）
  │     ├─ Level 1: 规则引擎（零 TOKEN，复用 ai_engine._classify_intent）
  │     └─ Level 2: 大模型精分类（仅低置信度，走 llm_light 池）
  │
  ├─ P4-P9 功能层（不变）
  └─ P10 AI 回复（接收 dctx.intent，用于 stage_hint 增强）

后台触发器（APScheduler 注册）
  ├─ cold_group_breaker   每 5 分钟巡检，群组冷场破冰
  ├─ night_private_hint   每 30 分钟巡检，夜间高意向暗示
  └─ flood_mediate        事件驱动，antiflood 触发群级刷屏介入
```

## 2. 用户画像标签系统

### 2.1 表结构（user_profiles 扩展 6 列）

| 列名 | 类型 | 默认 | 语义 |
|------|------|------|------|
| activity_score | REAL | 0.0 | 活跃度 0-1（消息数/100 归一化） |
| flirt_affinity | REAL | 0.0 | 涩气偏好度 0-1（flirt 意图占比） |
| spend_tendency | REAL | 0.0 | 消费倾向 0-1（消费词+business 意图） |
| resistance_idx | REAL | 0.5 | 抗拒指数 0-1（抗拒词累计+衰减） |
| peak_hours | TEXT | '[]' | 高频时段 JSON [0-23] top3 |
| persona_tags | TEXT | '[]' | 复合标签 JSON |

### 2.2 复合标签派生规则

| 标签 | 条件 | 用途 |
|------|------|------|
| high_active | activity_score > 0.8 | 冷场破冰优先 @ |
| low_active | activity_score < 0.2 | 挽回优先级 |
| night_owl | 22/0/1 in peak_hours | 夜间暗示触发 |
| flirt_friendly | flirt_affinity > 0.6 | 挑逗话术层级 |
| vip_intent | spend_tendency > 0.7 | 转化引导强度 |
| resistant | resistance_idx > 0.7 | 降级话术 |

### 2.3 非侵入式采集

挂载点：`core/message_dispatcher.py:do_dispatch` 入口（last_active 更新之后）。

```python
if ctx.config.get("USER_PROFILE_ENABLED", False):
    profile_learner.learn_from_message(uid, msg_text, chat_id, int(time.time()))
```

采集维度：
1. 意图计数（复用 `_classify_intent`，零 TOKEN）
2. 时段分布（内存计数器，top3 小时）
3. 抗拒词检测（正则：不要/算了/太贵/不买...）
4. 消费信号检测（正则：下单/购买/续费/包年...）
5. 兴趣标签 + VIP/高价值（原有逻辑）
6. persona_tags 派生

## 3. 意图路由系统

### 3.1 两级分类

**Level 1（规则引擎，零 TOKEN）**：复用 `ai_engine._classify_intent`，6 类意图映射到 5 类标准：
- flirt → flirt
- business → purchase_intent
- complaint → complaint
- help → consult
- bored/chat → chat

置信度 = 命中数 × 权重，阈值 `INTENT_RULE_THRESHOLD=2.0`。

**Level 2（大模型精分类）**：仅当 Level 1 置信度 < 阈值且 `INTENT_LLM_ENABLED=true` 时触发。
- 走 `llm_light` 池（低成本模型）
- Function Calling：`classify_intent(text) → {intent, confidence}`
- 失败时降级到规则结果

### 3.2 路由分发

- 高置信度投诉（confidence > 0.6）→ 通知管理员（不拦截，继续 P10）
- dctx.intent 传递给 P10，`ai_reply_handler` 用它增强 stage_hint：
  - flirt → "保持清冷傲娇人设，适当回撩但不主动"
  - purchase_intent → "自然引导 @MorychannelBot 自助下单"
  - complaint → "先共情安抚，承诺转达 Mory"
  - consult → "简洁回答，必要时引导自助"

## 4. 场景化触发器

### 4.1 冷场破冰（cold_group_breaker）

- **触发条件**：群组超过 `COLD_GROUP_THRESHOLD_MIN`（默认 45）分钟无人发言
- **数据源**：复用 `message_snapshots` 表（v5.15.3 已强制所有消息入库）
- **防刷**：`broadcast_tracking` 表记录，`COLD_GROUP_COOLDOWN_MIN`（默认 180）分钟内同群不重复
- **限流**：单次最多 `COLD_GROUP_MAX_PER_RUN`（默认 1）个群
- **话术**：mode='cold_breaker'，走 llm_light 池

### 4.2 夜间高意向暗示（night_private_hint）

- **触发条件**：
  - 当前小时在夜间窗口（22-2 点）
  - 用户 conversion_status='interested'
  - persona_tags 含 vip_intent + night_owl
  - 当前小时在用户 peak_hours 内
- **防刷**：`broadcast_tracking` 记录，`NIGHT_HINT_COOLDOWN_HOURS`（默认 24）小时内不重复
- **限流**：单次最多 `NIGHT_HINT_MAX_PER_RUN`（默认 2）个用户
- **话术**：mode='night_hint'，传入 user_profile 个性化

### 4.3 刷屏介入（flood_mediate）

- **触发方式**：事件驱动（不轮询），由 `antiflood.handle_flood_user` 检测到群级刷屏后调用
- **群级刷屏判定**：5 分钟内 ≥3 用户刷屏（基于 `_flood_cache` 统计）
- **防刷**：同群 5 分钟内不重复介入
- **话术**：mode='flood_mediate'，高冷平息语

## 5. 配置项

| 配置项 | 默认 | 说明 |
|--------|------|------|
| USER_PROFILE_ENABLED | false | 画像采集总开关 |
| INTENT_ROUTING_ENABLED | false | 意图路由总开关 |
| INTENT_LLM_ENABLED | false | LLM 精分类开关 |
| INTENT_RULE_THRESHOLD | 2.0 | 规则置信度阈值 |
| COLD_GROUP_TRIGGER_ENABLED | false | 冷场破冰开关 |
| COLD_GROUP_THRESHOLD_MIN | 30 | 冷场阈值（分钟） |
| COLD_GROUP_COOLDOWN_MIN | 120 | 冷场破冰冷却（分钟） |
| COLD_GROUP_MAX_PER_RUN | 3 | 单次最多破冰群数 |
| NIGHT_HINT_TRIGGER_ENABLED | false | 夜间暗示开关 |
| NIGHT_HINT_COOLDOWN_HOURS | 24 | 夜间暗示冷却（小时） |
| NIGHT_HINT_MAX_PER_RUN | 2 | 单次最多暗示用户数 |
| FLOOD_MEDiate_TRIGGER_ENABLED | false | 刷屏介入开关 |

## 6. 关键文件

| 文件 | 作用 |
|------|------|
| core/profile_learner.py | 画像学习器（多维采集） |
| core/intent_router.py | 意图路由器（两级分类） |
| core/message_dispatcher.py | P3.6 挂载点 + 画像采集挂载 |
| core/handlers/ai_reply_handler.py | stage_hint 联动 intent |
| core/database.py | _safe_add_column 幂等迁移 |
| core/db_repos/user_repo.py | 画像读写扩展 6 列 |
| core/bot_initializer.py | BotContext + _GLOBAL_CTX |
| modules/triggers/base.py | 触发器基类 |
| modules/triggers/cold_group.py | 冷场破冰 |
| modules/triggers/night_hint.py | 夜间暗示 |
| modules/triggers/flood_mediate.py | 刷屏介入 |
| modules/antiflood.py | 群级刷屏事件触发 |
| tasks/task_scheduler.py | 触发器注册到 APScheduler；热重载由 bot_initializer 重新编排 |
| dashboard/api/config_api.py | /config/scene-triggers API |

## 7. 设计原则

1. **复用优先**：扩展 user_profiles 表，不新建画像表；复用 message_snapshots 做冷场检测
2. **零侵入收集**：画像学习挂在 do_dispatch 入口，不改变现有 P0-P10 链路
3. **规则+大模型混合**：意图分类先用规则兜底（零 TOKEN），命中阈值再调大模型
4. **默认关闭**：所有新功能 `config.get('XXX_ENABLED', False)`
5. **单文件 ≤200 行**：触发器按场景拆分到 modules/triggers/ 子目录
