# LLM 成本熔断器详解

> 本文档为独立技术说明，未被 AGENTS.md 直接索引 · 适用版本：v5.26.0+ / v5.31.2 审计整改
> **最后更新**：2026-07-06

## 概述

LLM 调用是项目最昂贵的运行时资源。一旦某用户高频调用、或全局限流失效，单日成本可能在数小时内失控。本文档详述 `core/llm_cost_guard.py` 实现的 **6 道闸熔断机制**，从单用户小时限额到全局日限额，逐级降级保护预算。

## 适用场景

- 排查"为什么 LLM 调用被降级到 llm_light"时查阅
- 调整熔断阈值（`LLM_COST_*_LIMIT` 配置项）时查阅
- 新增 LLM 调用入口时，确认是否接入 `check_before_call` + `record_cost`
- 排查 `global_daily_limit_exceeded` / `global_downgrade_active` 日志时查阅

## 6 道闸门（check_before_call 决策链）

`LLMCostGuard.check_before_call(uid, tier)` 按顺序检查 6 道闸，任一命中即返回降级决策：

| 闸门 | 检查内容 | 命中动作 | reason 字段 |
|------|---------|---------|-------------|
| 1 | 全局降级状态（`_global_downgrade_until`） | 直接降级 llm_light | `global_downgrade_active_until_<ts>` |
| 2 | 用户降级状态（`_downgraded_users[uid]`） | 该用户降级 llm_light | `user_downgrade_active_until_<ts>` |
| 3 | 全局 1h 消费 ≥ `global_hourly_limit` | 全局降级 1h | `global_hourly_limit_exceeded` |
| 4 | 单用户 1h 消费 ≥ `user_hourly_limit` | 该用户降级 1h | `user_hourly_limit_exceeded` |
| 5 | 单用户 24h 消费 ≥ `user_daily_limit` | **拒绝调用（return False）** | `user_daily_limit_exceeded_blocked` |
| **6** | **全局 24h 消费 ≥ `global_daily_limit`** | **全局降级 24h** | **`global_daily_limit_exceeded`** |

> **检查顺序说明**：先全局后用户（闸门 3→4→5→6）。全局熔断优先级高于单用户，避免在全局已超限时仍逐用户检查浪费资源。闸门 5 是唯一"拒绝调用"（return False）的闸门，其余均为"允许但降级到 llm_light"。

**第 6 道闸是 v5.31.2 审计整改新增**：之前只有 5 道闸，缺少全局日限额保护。如果攻击者用大量不同用户 ID 在 1h 内各自不超阈值，但 24h 累计可能远超预算。第 6 道闸兜底保护单日总预算。

## 配置项（config.json）

```json
{
  "LLM_COST_GUARD_ENABLED": true,
  "LLM_COST_USER_HOURLY_LIMIT": 1.0,
  "LLM_COST_GLOBAL_HOURLY_LIMIT": 5.0,
  "LLM_COST_USER_DAILY_LIMIT": 10.0,
  "LLM_COST_GLOBAL_DAILY_LIMIT": 50.0
}
```

默认值见 `core/llm_cost_guard.py` 顶部 `_DEFAULT_*` 常量。config.json 的值优先于默认值。

## 数据结构

### 内存滑动窗口

```python
self._global_window: deque[(timestamp, cost)]  # 全局消费窗口
self._user_windows: Dict[int, deque]            # 按用户窗口
```

`_cleanup_expired(window, max_age_seconds)` 自动清理超期记录。**只有 daily 方法（`_get_global_daily_cost` / `_get_user_daily_cost`）会调用 cleanup（max_age=86400）**；hourly 方法（`_get_global_hourly_cost` / `_get_user_hourly_cost`）只读不写，仅 `sum` 1h 内的元素。这种分工是为了避免 hourly cleanup 破坏 daily 窗口数据（详见下方"历史坑"）。

### 降级状态

```python
self._downgraded_users: Dict[int, float]  # uid → 降级解除时间戳
self._global_downgrade_until: float       # 全局降级解除时间戳
```

降级期间 `check_before_call` 在第 1/2 道闸直接返回，不重复触发告警。

## 调用流程

```
ai_engine.ask(uid, mode)
  ├── guard.check_before_call(uid, tier)   # 调用前检查
  │     └── (allowed, final_tier, reason)
  ├── if allowed: requests.post(...)        # 实际调用 LLM
  └── guard.record_cost(uid, model, ...)    # 记录消费
        └── _global_window.append((now, cost))
            _user_windows[uid].append((now, cost))
```

`record_cost` 通过 `_estimate_cost(tier, input_tokens, output_tokens)` 估算成本（基于 `_TIER_PRICE_PER_1K` 单价表），不依赖厂商计费 API。

## 持久化

`flush_to_db(db_conn)` 由定时任务每 5 分钟调用一次，将 `_pending_logs` 批量写入 `llm_cost_logs` 表。服务异常重启最多丢失 5 分钟消费记录，但内存滑动窗口会从 0 重新累计（不影响已写入的日志）。

## Dashboard 监控

`get_stats()` 返回当前熔断器状态，供 Dashboard `/api/llm-cost/stats` 调用：

```python
{
    "enabled": True,
    "total_calls": 1234,
    "total_cost": 12.34,
    "global_hourly_cost": 1.23,
    "global_hourly_limit": 5.0,
    "global_daily_cost": 8.50,    # v5.31.2 新增
    "global_daily_limit": 50.0,   # v5.31.2 新增
    "user_downgrades": 3,
    "global_downgrades": 0,
    "blocked_calls": 12,
}
```

## 告警

- 第 3/4/5 道闸：`logger.warning` 软告警
- 第 6 道闸（全局日熔断）：`logger.critical` + `core/alert_bot.send_alert("critical", ...)` 独立告警通道

## 单元测试

`tests/unit/test_audit_fixes.py::TestLLMGlobalDailyCircuitBreaker` 覆盖：
- 未超阈值正常放行
- 全局 24h 超阈值触发降级
- 降级状态持续 24h
- 熔断器关闭时直接放行
- `_get_global_daily_cost` 24h 窗口清理与累计计算

## 历史坑

### [v5.31.2 审计整改] hourly cleanup 破坏 daily 窗口（暗病）

**现象**：`global_daily_limit_exceeded` 熔断实际上从未生效。即使 24h 累计消费远超 `global_daily_limit`，第 6 道闸也不会触发。

**根因**：`_global_window` 是 hourly 和 daily 共用的同一 deque。原实现中 `_get_global_hourly_cost` 调用 `_cleanup_expired(now, window, 3600)` 会弹出所有 1h 前的元素。由于 `check_before_call` 的检查顺序是 hourly（step 3/4）→ daily（step 5/6），hourly 检查时已经把 1h 前的元素全部弹出，到 daily 检查时 `_get_global_daily_cost` 只能看到 1h 内的数据，永远无法触发 daily 熔断。

**修复**：
- `_get_global_hourly_cost` / `_get_user_hourly_cost` 改为只读不写：`sum(cost for ts, cost in window if ts >= cutoff)`
- `_get_global_daily_cost` / `_get_user_daily_cost` 保留 cleanup（max_age=86400），统一负责过期数据清理

**发现方式**：补充单元测试 `test_global_daily_exceeded_triggers_downgrade` 时发现 — 测试数据 $50 在 100s 前同时满足 hourly 和 daily 阈值，但实际返回 `global_hourly_limit_exceeded` 而非 `global_daily_limit_exceeded`，深入排查发现是 hourly cleanup 把 daily 数据清空了。

## 相关文件

- `core/llm_cost_guard.py` — 主实现
- `core/ai_engine.py` — 调用方
- `core/alert_bot.py` — 告警通道
- `config.json.example` — 配置项
- `tests/unit/test_audit_fixes.py` — 单元测试
