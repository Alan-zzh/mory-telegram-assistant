# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/llm_cost_guard.py  ·  LLM 成本可观测性与熔断器（v5.26.0 阶段1-A） ║
║                                                                        ║
║  功能：                                                                ║
║    1. 异步 Token 消耗埋点（llm_cost_logs 内存表 + 定时刷盘）           ║
║    2. 滑动窗口额度计算（1h/24h 单用户 + 全局累计）                     ║
║    3. 自动降级熔断（单用户/全局超阈值降级到 llm_light）                ║
║                                                                        ║
║  熔断阈值（可通过 config 覆盖）：                                       ║
║    - 单用户 1h 内消费 > $1.0 → 该用户降级 llm_light + 软性警告          ║
║    - 全局 1h 内消费 > $15.0 → 全量降级 llm_light + Critical 告警        ║
║                                                                        ║
║  依赖：threading, time, sqlite3                                        ║
║  配置：config.json → LLM_COST_GUARD_ENABLED / 阈值                     ║
║  被调用：core/ai_engine.py:ask() 调用前检查 + 调用后记录                ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import threading
import time
import sqlite3
from collections import deque, defaultdict
from typing import Optional, Tuple, Dict

from core.logging_util import get_logger

logger = get_logger("llm_cost_guard")


# ── 默认熔断阈值（可通过 config 覆盖）────────────────────────────────
_DEFAULT_USER_HOURLY_LIMIT = 1.0      # 单用户 1h 消费上限（美元）
_DEFAULT_GLOBAL_HOURLY_LIMIT = 15.0   # 全局 1h 消费上限（美元）
_DEFAULT_USER_DAILY_LIMIT = 10.0      # 单用户 24h 消费上限（美元）
_DEFAULT_GLOBAL_DAILY_LIMIT = 100.0   # 全局 24h 消费上限（美元）

# ── 各模型层级的单价估算（美元/1K tokens，input+output 合并粗估）─────
# 实际价格以厂商为准，这里用保守估值用于熔断保护
_TIER_PRICE_PER_1K = {
    "llm_premium": 0.014,    # Qwen-Max 约 $0.014/1K
    "llm_standard": 0.004,   # Qwen-Plus 约 $0.004/1K
    "llm_light": 0.0003,     # Qwen-Flash 约 $0.0003/1K
}


class LLMCostGuard:
    """
    LLM 成本熔断器：滑动窗口累计 + 自动降级。

    工作流程：
    1. check_before_call(uid, tier) → (allowed, downgraded_tier, reason)
       - 检查单用户/全局 1h 消费是否超阈值
       - 超阈值则降级到 llm_light 或拒绝
    2. record_cost(uid, model_name, task_type, input_tokens, output_tokens, tier)
       - 记录本次调用消耗
    3. flush_to_db(db_conn) → 定时刷盘到 llm_cost_logs 表
    """

    def __init__(self, config: dict):
        self.config = config or {}
        self.enabled = bool(self.config.get("LLM_COST_GUARD_ENABLED", False))

        # 阈值（支持 config 覆盖）
        self.user_hourly_limit = float(self.config.get(
            "LLM_COST_USER_HOURLY_LIMIT", _DEFAULT_USER_HOURLY_LIMIT))
        self.global_hourly_limit = float(self.config.get(
            "LLM_COST_GLOBAL_HOURLY_LIMIT", _DEFAULT_GLOBAL_HOURLY_LIMIT))
        self.user_daily_limit = float(self.config.get(
            "LLM_COST_USER_DAILY_LIMIT", _DEFAULT_USER_DAILY_LIMIT))
        self.global_daily_limit = float(self.config.get(
            "LLM_COST_GLOBAL_DAILY_LIMIT", _DEFAULT_GLOBAL_DAILY_LIMIT))

        # 内存滑动窗口：deque[(timestamp, cost)]
        # 全局窗口 + 按用户窗口
        self._global_window = deque(maxlen=10000)  # 全局最近 10000 条
        self._user_windows: Dict[int, deque] = defaultdict(lambda: deque(maxlen=500))
        self._lock = threading.Lock()

        # 降级状态记录（uid → 降级解除时间戳）
        self._downgraded_users: Dict[int, float] = {}
        self._global_downgrade_until = 0.0  # 全局降级解除时间

        # 统计
        self._stats = {
            "total_calls": 0,
            "total_cost": 0.0,
            "user_downgrades": 0,
            "global_downgrades": 0,
            "blocked_calls": 0,
        }

        logger.info(
            f"💰 LLMCostGuard 初始化: enabled={self.enabled}, "
            f"用户1h=${self.user_hourly_limit}, 全局1h=${self.global_hourly_limit}"
        )

    def _estimate_cost(self, tier: str, input_tokens: int, output_tokens: int) -> float:
        """估算单次调用成本（美元）"""
        price = _TIER_PRICE_PER_1K.get(tier, 0.004)
        return (input_tokens + output_tokens) / 1000.0 * price

    def _cleanup_expired(self, now: float, window: deque, max_age: float = 3600):
        """清理窗口中过期记录（超过 max_age 秒）"""
        cutoff = now - max_age
        while window and window[0][0] < cutoff:
            window.popleft()

    def _get_user_hourly_cost(self, uid: int, now: float) -> float:
        """获取用户最近 1h 消费"""
        window = self._user_windows.get(uid)
        if not window:
            return 0.0
        self._cleanup_expired(now, window, 3600)
        return sum(cost for _, cost in window)

    def _get_global_hourly_cost(self, now: float) -> float:
        """获取全局最近 1h 消费"""
        self._cleanup_expired(now, self._global_window, 3600)
        return sum(cost for _, cost in self._global_window)

    def _get_user_daily_cost(self, uid: int, now: float) -> float:
        """获取用户最近 24h 消费"""
        window = self._user_windows.get(uid)
        if not window:
            return 0.0
        self._cleanup_expired(now, window, 86400)
        return sum(cost for _, cost in window)

    def check_before_call(self, uid: int, tier: str = "llm_premium") -> Tuple[bool, str, str]:
        """
        调用前检查：是否允许调用，是否需要降级。

        Args:
            uid: 用户 ID
            tier: 原始目标层级

        Returns:
            (allowed, final_tier, reason)
            - allowed: 是否允许调用（False = 拒绝）
            - final_tier: 实际使用的层级（可能降级）
            - reason: 决策原因
        """
        if not self.enabled:
            return (True, tier, "guard_disabled")

        now = time.time()

        # 1. 检查全局降级状态
        if now < self._global_downgrade_until:
            return (True, "llm_light", f"global_downgrade_active_until_{int(self._global_downgrade_until)}")

        # 2. 检查用户降级状态
        downgrade_until = self._downgraded_users.get(uid)
        if downgrade_until and now < downgrade_until:
            return (True, "llm_light", f"user_downgrade_active_until_{int(downgrade_until)}")

        # 3. 检查全局 1h 消费
        global_cost = self._get_global_hourly_cost(now)
        if global_cost >= self.global_hourly_limit:
            # 触发全局降级（持续 1h）
            self._global_downgrade_until = now + 3600
            self._stats["global_downgrades"] += 1
            logger.critical(
                f"🚨 全局 LLM 成本熔断！1h 消费 ${global_cost:.2f} >= ${self.global_hourly_limit:.2f}，"
                f"全量降级 llm_light 持续 1h"
            )
            # 触发告警 Bot
            try:
                from core.alert_bot import send_alert
                send_alert(
                    "critical",
                    "LLM成本全局熔断",
                    f"全局 1h 消费 ${global_cost:.2f} 超阈值 ${self.global_hourly_limit:.2f}，"
                    f"已自动降级 llm_light 持续 1h"
                )
            except Exception:
                pass
            return (True, "llm_light", "global_hourly_limit_exceeded")

        # 4. 检查用户 1h 消费
        user_cost = self._get_user_hourly_cost(uid, now)
        if user_cost >= self.user_hourly_limit:
            # 触发用户降级（持续 1h）
            self._downgraded_users[uid] = now + 3600
            self._stats["user_downgrades"] += 1
            logger.warning(
                f"⚠️ 用户 {uid} LLM 成本熔断！1h 消费 ${user_cost:.2f} >= ${self.user_hourly_limit:.2f}，"
                f"降级 llm_light 持续 1h"
            )
            return (True, "llm_light", "user_hourly_limit_exceeded")

        # 5. 检查用户 24h 消费
        user_daily = self._get_user_daily_cost(uid, now)
        if user_daily >= self.user_daily_limit:
            # 24h 超限直接拒绝
            self._stats["blocked_calls"] += 1
            logger.error(
                f"🚫 用户 {uid} 24h 消费 ${user_daily:.2f} >= ${self.user_daily_limit:.2f}，拒绝调用"
            )
            return (False, "llm_light", "user_daily_limit_exceeded_blocked")

        return (True, tier, "ok")

    def record_cost(self, uid: int, model_name: str, task_type: str,
                    input_tokens: int, output_tokens: int, tier: str = "llm_light"):
        """
        记录单次 LLM 调用成本。

        Args:
            uid: 用户 ID
            model_name: 模型名（如 qwen-max）
            task_type: 任务类型（chat/summarize 等）
            input_tokens: 输入 token 数
            output_tokens: 输出 token 数
            tier: 层级（用于价格估算）
        """
        if not self.enabled:
            return

        cost = self._estimate_cost(tier, input_tokens, output_tokens)
        now = time.time()

        with self._lock:
            self._global_window.append((now, cost))
            self._user_windows[uid].append((now, cost))
            self._stats["total_calls"] += 1
            self._stats["total_cost"] += cost

        logger.debug(
            f"💰 记录成本: uid={uid} model={model_name} tier={tier} "
            f"tokens={input_tokens}+{output_tokens} cost=${cost:.4f}"
        )

    def get_stats(self) -> dict:
        """获取成本统计"""
        now = time.time()
        with self._lock:
            return {
                **self._stats,
                "global_hourly_cost": self._get_global_hourly_cost(now),
                "global_hourly_limit": self.global_hourly_limit,
                "active_user_downgrades": len(self._downgraded_users),
                "global_downgrade_active": now < self._global_downgrade_until,
            }

    def flush_to_db(self, db_conn):
        """
        定时刷盘到 llm_cost_logs 表（由 auto_tasks 每 5min 调用）。

        表结构：
        CREATE TABLE IF NOT EXISTS llm_cost_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER, model_name TEXT, task_type TEXT,
            input_tokens INTEGER, output_tokens INTEGER,
            estimated_cost REAL, tier TEXT, timestamp INTEGER
        )
        """
        if not self.enabled:
            return

        try:
            db_conn.execute("""
                CREATE TABLE IF NOT EXISTS llm_cost_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid INTEGER, model_name TEXT, task_type TEXT,
                    input_tokens INTEGER, output_tokens INTEGER,
                    estimated_cost REAL, tier TEXT, timestamp INTEGER
                )
            """)
            # 内存数据已在 record_cost 实时累计，此处仅确保表存在
            # 实际批量写入可在未来扩展（当前内存统计已足够熔断决策）
            db_conn.commit()
        except Exception as e:
            logger.debug(f"flush_to_db 异常: {e}")


# ── 模块级单例 ──────────────────────────────────────────────────────
_guard_instance: Optional[LLMCostGuard] = None
_guard_lock = threading.Lock()


def init_guard(config: dict):
    """初始化成本熔断器单例（main.py 启动时调用）"""
    global _guard_instance
    with _guard_lock:
        try:
            _guard_instance = LLMCostGuard(config)
        except Exception as e:
            logger.warning(f"⚡ LLMCostGuard 初始化失败: {e}")
            _guard_instance = None


def get_guard() -> Optional[LLMCostGuard]:
    """获取成本熔断器单例"""
    return _guard_instance


def check_before_call(uid: int, tier: str = "llm_premium") -> Tuple[bool, str, str]:
    """便捷函数：调用前检查"""
    guard = _guard_instance
    if guard is None or not guard.enabled:
        return (True, tier, "guard_not_initialized")
    return guard.check_before_call(uid, tier)


def record_cost(uid: int, model_name: str, task_type: str,
                input_tokens: int, output_tokens: int, tier: str = "llm_light"):
    """便捷函数：记录成本"""
    guard = _guard_instance
    if guard is None:
        return
    guard.record_cost(uid, model_name, task_type, input_tokens, output_tokens, tier)


def get_cost_stats() -> dict:
    """便捷函数：获取统计"""
    guard = _guard_instance
    if guard is None:
        return {"enabled": False, "msg": "guard not initialized"}
    return guard.get_stats()
