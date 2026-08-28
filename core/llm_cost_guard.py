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

import os
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
        self._global_window = deque()
        self._user_windows: Dict[int, deque] = defaultdict(deque)
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()

        # 【v5.31.2 修复】待刷盘的详细日志队列
        # 之前 flush_to_db 只建表不写数据，llm_cost_logs 永远为空，重启后熔断器累计清零
        # 现在 record_cost 缓存详细日志，flush_to_db 批量写入数据库
        self._pending_logs = deque()

        # 降级状态记录（uid → 降级解除时间戳）
        self._downgraded_users: Dict[int, float] = {}
        self._global_downgrade_until = 0.0  # 全局降级解除时间

        # 【WARN-2 修复】低频 cleanup 时间戳：持续降级期间第 1/2 道闸直接 return，
        # _get_global_daily_cost 不会被调用，导致 _global_window 永不清理（内存泄漏风险）。
        # check_before_call 开头每 5 分钟做一次 daily cleanup，确保即使持续降级也定期清理。
        self._last_cleanup_ts: float = 0.0
        self._CLEANUP_INTERVAL_SEC = 300  # 5 分钟

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

    def load_recent_costs_from_db(self, db_path, hours: int = 24) -> int:
        """从持久化成本表回灌滑动窗口，避免服务重启后熔断累计清零。"""
        if not self.enabled or not db_path:
            return 0
        cutoff = time.time() - max(1, hours) * 3600
        loaded = 0
        try:
            conn = sqlite3.connect(db_path, timeout=30.0)
            try:
                rows = conn.execute(
                    """
                    SELECT uid, estimated_cost, timestamp
                    FROM llm_cost_logs
                    WHERE timestamp >= ?
                    ORDER BY timestamp ASC
                    """,
                    (cutoff,),
                ).fetchall()
            finally:
                conn.close()
            with self._lock:
                for uid, cost, ts in rows:
                    try:
                        uid_int = int(uid or 0)
                        cost_float = float(cost or 0.0)
                        ts_float = float(ts or 0.0)
                    except (TypeError, ValueError):
                        continue
                    self._global_window.append((ts_float, cost_float))
                    self._user_windows[uid_int].append((ts_float, cost_float))
                    loaded += 1
                now = time.time()
                self._cleanup_expired(now, self._global_window, 86400)
                for window in self._user_windows.values():
                    self._cleanup_expired(now, window, 86400)
            if loaded:
                logger.info(f"💰 LLMCostGuard 已从 llm_cost_logs 回灌最近 {hours}h 成本记录 {loaded} 条")
        except sqlite3.OperationalError as e:
            if "no such table" in str(e).lower():
                logger.info("💰 llm_cost_logs 尚不存在，成本熔断器从空窗口启动")
            else:
                logger.warning(f"LLMCostGuard 回灌成本日志失败: {e}")
        except Exception as e:
            logger.warning(f"LLMCostGuard 回灌成本日志异常: {e}")
        return loaded

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
        """获取用户最近 1h 消费

        [审计暗病修复] 原实现调用 _cleanup_expired(now, window, 3600) 会弹出
        所有 1h 前的元素，但 _user_windows[uid] 是 hourly 和 daily 共用的同一
        deque，hourly cleanup 会破坏 daily 窗口数据，导致 daily 熔断永远无法
        触发（check_before_call 先检查 hourly 把 24h 数据清空了）。
        现改为只读不写：sum 1h 内的元素，cleanup 交给 _get_user_daily_cost 统一处理。
        """
        window = self._user_windows.get(uid)
        if not window:
            return 0.0
        cutoff = now - 3600
        return sum(cost for ts, cost in window if ts >= cutoff)

    def _get_global_hourly_cost(self, now: float) -> float:
        """获取全局最近 1h 消费（不清理窗口，避免破坏 daily 数据）"""
        cutoff = now - 3600
        return sum(cost for ts, cost in self._global_window if ts >= cutoff)

    def _get_user_daily_cost(self, uid: int, now: float) -> float:
        """获取用户最近 24h 消费（统一清理 24h 前的过期数据）"""
        window = self._user_windows.get(uid)
        if not window:
            return 0.0
        self._cleanup_expired(now, window, 86400)
        return sum(cost for _, cost in window)

    def _get_global_daily_cost(self, now: float) -> float:
        """获取全局最近 24h 消费（统一清理 24h 前的过期数据）"""
        self._cleanup_expired(now, self._global_window, 86400)
        return sum(cost for _, cost in self._global_window)

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

        # 【WARN-2 修复】低频 cleanup：持续降级期间第 1/2 道闸直接 return，
        # _get_global_daily_cost 不会被调用，导致 _global_window/_user_windows 永不清理。
        # 这里在所有闸门检查之前，每 5 分钟做一次 daily cleanup，确保窗口不会无限增长。
        if now - self._last_cleanup_ts >= self._CLEANUP_INTERVAL_SEC:
            with self._lock:
                self._cleanup_expired(now, self._global_window, 86400)
                # 清理已解除降级的用户窗口（避免 _user_windows dict 无限增长）
                expired_uids = [
                    uid for uid, until in self._downgraded_users.items()
                    if now >= until
                ]
                for uid in expired_uids:
                    self._downgraded_users.pop(uid, None)
                    # 用户窗口保留（仍可能在 24h 内有新调用），由 daily cleanup 自然过期
                # 清理空窗口
                empty_uids = [
                    uid for uid, w in self._user_windows.items()
                    if not w
                ]
                for uid in empty_uids:
                    self._user_windows.pop(uid, None)
            self._last_cleanup_ts = now

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
            except Exception as e:
                # 【v5.31.2 修复】成本熔断告警链断裂会导致管理员无法感知成本失控
                logger.error(f"LLM成本全局熔断告警发送失败: {e}")
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

        # 6. [P0 修复] 检查全局 24h 消费（之前定义了阈值但未实现拦截，导致成本失控风险）
        global_daily = self._get_global_daily_cost(now)
        if global_daily >= self.global_daily_limit:
            # 全局 24h 超限：全量降级 llm_light 持续到当日结束（最长 24h）
            self._global_downgrade_until = now + 86400
            self._stats["global_downgrades"] += 1
            logger.critical(
                f"🚨 全局 LLM 成本日熔断！24h 消费 ${global_daily:.2f} >= ${self.global_daily_limit:.2f}，"
                f"全量降级 llm_light 持续 24h"
            )
            try:
                from core.alert_bot import send_alert
                send_alert(
                    "critical",
                    "LLM成本全局日熔断",
                    f"全局 24h 消费 ${global_daily:.2f} 超阈值 ${self.global_daily_limit:.2f}，"
                    f"已自动降级 llm_light 持续 24h"
                )
            except Exception as e:
                logger.error(f"LLM成本全局日熔断告警发送失败: {e}")
            return (True, "llm_light", "global_daily_limit_exceeded")

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
            # 【v5.31.2 修复】缓存详细日志供 flush_to_db 批量写入
            self._pending_logs.append((uid, model_name, task_type, input_tokens, output_tokens, cost, tier, now))

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
                "global_daily_cost": self._get_global_daily_cost(now),
                "global_daily_limit": self.global_daily_limit,
                "active_user_downgrades": len(self._downgraded_users),
                "global_downgrade_active": now < self._global_downgrade_until,
            }

    def flush_to_db(self, db_conn):
        """
        【v5.31.2 修复】定时刷盘到 llm_cost_logs 表（由调度器 flush_alert_summary 任务每 5 分钟调用）。

        之前只建表不写数据，llm_cost_logs 永远为空，重启后熔断器累计清零。
        现在批量写入 _pending_logs 队列中的详细日志，写入后清空队列。

        ``llm_cost_logs`` 由 ``core.database`` 和 Alembic 统一创建；这里仅写入。
        """
        if not self.enabled:
            return

        with self._flush_lock:
            conn = None
            close_conn = False
            batch = []
            with self._lock:
                if not self._pending_logs:
                    return
                while self._pending_logs:
                    batch.append(self._pending_logs.popleft())

            try:
                if isinstance(db_conn, (str, bytes, os.PathLike)):
                    conn = sqlite3.connect(db_conn, timeout=30.0)
                    close_conn = True
                else:
                    conn = db_conn

                # 不在业务请求路径创建表；缺少 schema 时下面的写入会失败并将
                # 队列放回，促使部署门禁/告警处理，而不是制造分叉结构。
                conn.execute("SELECT 1 FROM llm_cost_logs LIMIT 1")
                conn.executemany(
                    "INSERT INTO llm_cost_logs (uid, model_name, task_type, input_tokens, output_tokens, estimated_cost, tier, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    batch
                )
                conn.commit()
                logger.debug(f"💰 LLMCostGuard flush_to_db: 写入 {len(batch)} 条成本日志")
            except Exception as e:
                with self._lock:
                    for item in reversed(batch):
                        self._pending_logs.appendleft(item)
                # flush 失败应告警，否则成本日志表缺失无人感知
                logger.warning(f"flush_to_db 异常: {e}")
            finally:
                if close_conn and conn is not None:
                    try:
                        conn.close()
                    except Exception as e:
                        logger.debug(f"flush_to_db 关闭短连接失败: {e}")


# ── 模块级单例 ──────────────────────────────────────────────────────
_guard_instance: Optional[LLMCostGuard] = None
_guard_lock = threading.Lock()


def init_guard(config: dict, db_path=None):
    """初始化成本熔断器单例（main.py 启动时调用）"""
    global _guard_instance
    with _guard_lock:
        try:
            _guard_instance = LLMCostGuard(config)
            if db_path:
                _guard_instance.load_recent_costs_from_db(db_path, hours=24)
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
