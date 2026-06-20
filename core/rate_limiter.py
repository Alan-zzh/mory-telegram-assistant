# -*- coding: utf-8 -*-
"""
多层级限流与自愈机制

层级:
  1. 令牌桶（API调用层）—— 已存在于 core/optimizer.py，本模块不重复实现
  2. 用户级滑动窗口（私信/挽回发送）—— 本模块 UserRateLimiter
  3. 群级滑动窗口（反刷屏）—— 本模块 ChatRateLimiter
  4. 熔断器（模型级）—— 已存在于 core/optimizer.py，本模块提供增强版

自愈机制:
  - 指数退避重试（ExponentialBackoff）
  - 异常分类 → 不同恢复策略（可重试/不可重试/需冷却）
  - 故障上报（集成 report_fault）
"""

import time
import threading
from collections import defaultdict
from core.logging_util import get_logger

logger = get_logger("rate_limiter")


# ════════════════════════ 1. 用户级滑动窗口限流 ═════════════════════════════

class UserRateLimiter:
    """
    用户级滑动窗口限流器。
    用于限制每个用户在时间窗口内的私信/挽回发送次数。

    使用方式:
      limiter = UserRateLimiter(window_sec=3600, max_requests=2)
      if limiter.allow(uid):
          send_message(uid, msg)
    """

    def __init__(self, window_sec: int = 3600, max_requests: int = 2):
        self.window_sec = window_sec
        self.max_requests = max_requests
        self._buckets: dict[int, list] = defaultdict(list)  # uid → [timestamps]
        self._lock = threading.Lock()

    def allow(self, uid: int) -> bool:
        """检查是否允许请求，返回 True=放行"""
        now = time.time()
        with self._lock:
            timestamps = self._buckets[uid]
            # 清理过期记录
            cutoff = now - self.window_sec
            self._buckets[uid] = [t for t in timestamps if t > cutoff]
            if len(self._buckets[uid]) < self.max_requests:
                self._buckets[uid].append(now)
                return True
            return False

    def remaining(self, uid: int) -> int:
        """查询剩余配额"""
        now = time.time()
        with self._lock:
            timestamps = self._buckets[uid]
            cutoff = now - self.window_sec
            valid = [t for t in timestamps if t > cutoff]
            self._buckets[uid] = valid
            return max(0, self.max_requests - len(valid))

    def reset(self, uid: int):
        """重置用户配额"""
        with self._lock:
            self._buckets.pop(uid, None)

    def cleanup(self):
        """清理所有过期记录（定期调用）"""
        now = time.time()
        cutoff = now - self.window_sec
        with self._lock:
            for uid in list(self._buckets.keys()):
                self._buckets[uid] = [t for t in self._buckets[uid] if t > cutoff]
                if not self._buckets[uid]:
                    del self._buckets[uid]

    def get_stats(self) -> dict:
        """获取限流统计"""
        with self._lock:
            total_buckets = len(self._buckets)
            total_requests = sum(len(v) for v in self._buckets.values())
            blocked = sum(1 for v in self._buckets.values()
                         if len(v) >= self.max_requests)
            return {
                "active_users": total_buckets,
                "total_requests_in_window": total_requests,
                "blocked_users": blocked,
                "window_sec": self.window_sec,
                "max_requests": self.max_requests,
            }


# ════════════════════════ 2. 群级滑动窗口限流 ═══════════════════════════════

class ChatRateLimiter:
    """
    群级滑动窗口限流器。
    用于检测群聊刷屏/并发攻击。

    使用方式:
      limiter = ChatRateLimiter(window_sec=5, threshold=10)
      if limiter.is_flooding(chat_id):
          handle_flood(chat_id)
    """

    def __init__(self, window_sec: int = 5, threshold: int = 10):
        self.window_sec = window_sec
        self.threshold = threshold
        self._buckets: dict[int, list] = defaultdict(list)  # chat_id → [timestamps]
        self._lock = threading.Lock()

    def record(self, chat_id: int):
        """记录一条消息"""
        with self._lock:
            self._buckets[chat_id].append(time.time())

    def is_flooding(self, chat_id: int) -> bool:
        """检查是否在刷屏"""
        now = time.time()
        cutoff = now - self.window_sec
        with self._lock:
            timestamps = self._buckets[chat_id]
            valid = [t for t in timestamps if t > cutoff]
            self._buckets[chat_id] = valid
            return len(valid) >= self.threshold

    def get_rate(self, chat_id: int) -> float:
        """获取当前消息速率（条/秒）"""
        now = time.time()
        cutoff = now - self.window_sec
        with self._lock:
            timestamps = self._buckets[chat_id]
            valid = [t for t in timestamps if t > cutoff]
            self._buckets[chat_id] = valid
            if not valid:
                return 0.0
            elapsed = now - valid[0]
            return len(valid) / max(elapsed, 0.1)

    def cleanup(self):
        """清理过期记录"""
        now = time.time()
        cutoff = now - self.window_sec
        with self._lock:
            for chat_id in list(self._buckets.keys()):
                self._buckets[chat_id] = [t for t in self._buckets[chat_id] if t > cutoff]
                if not self._buckets[chat_id]:
                    del self._buckets[chat_id]


# ════════════════════════ 3. 指数退避重试器 ═════════════════════════════════

class ExponentialBackoff:
    """
    指数退避重试器。
    用于 API 调用失败后的自动重试，避免雪崩。

    使用方式:
      backoff = ExponentialBackoff(base_delay=1.0, max_delay=60.0, max_retries=3)
      result = backoff.execute(lambda: api_call(), "api_name")
    """

    def __init__(self, base_delay: float = 1.0, max_delay: float = 60.0,
                 max_retries: int = 3, jitter: bool = True):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self.jitter = jitter
        self._failures: dict[str, int] = defaultdict(int)  # key → 连续失败次数

    def execute(self, func, operation_name: str, *args, **kwargs):
        """
        执行函数，失败时指数退避重试。
        返回 (result, success)。
        """
        import random

        last_exception = None
        for attempt in range(self.max_retries + 1):
            try:
                result = func(*args, **kwargs)
                # 成功 → 重置失败计数
                self._failures[operation_name] = 0
                return result, True
            except Exception as e:
                last_exception = e
                self._failures[operation_name] += 1

                if attempt >= self.max_retries:
                    logger.error(
                        f"退避重试耗尽: {operation_name} "
                        f"attempt={attempt+1}/{self.max_retries+1}: {e}"
                    )
                    break

                # 计算退避延迟
                delay = min(
                    self.base_delay * (2 ** attempt),
                    self.max_delay
                )
                if self.jitter:
                    delay *= (0.5 + random.random())  # 0.5x ~ 1.5x 随机抖动

                logger.warning(
                    f"退避重试: {operation_name} "
                    f"attempt={attempt+1}/{self.max_retries+1} "
                    f"delay={delay:.1f}s: {e}"
                )
                time.sleep(delay)

        return None, False

    def get_failure_count(self, operation_name: str) -> int:
        """获取连续失败次数"""
        return self._failures.get(operation_name, 0)

    def reset(self, operation_name: str = None):
        """重置失败计数"""
        if operation_name:
            self._failures[operation_name] = 0
        else:
            self._failures.clear()


# ════════════════════════ 4. 异常分类与自愈策略 ═════════════════════════════

class ErrorCategory:
    """异常分类枚举"""
    RETRYABLE = "retryable"        # 可重试（网络超时、临时故障）
    COOL_DOWN = "cool_down"        # 需冷却后重试（429限流、503）
    FATAL = "fatal"                # 不可重试（权限错误、参数错误）
    DEGRADED = "degraded"          # 降级处理（非关键功能失败）


def classify_error(exception: Exception) -> str:
    """
    根据异常类型和内容分类，返回 ErrorCategory 值。
    """
    err_str = str(exception).lower()
    err_type = type(exception).__name__

    # 不可重试的错误
    if any(kw in err_str for kw in (
        "chat not found", "bot was blocked", "forbidden",
        "bot was kicked", "user is deactivated", "bot can't initiate"
    )):
        return ErrorCategory.FATAL

    # 权限类错误
    if any(kw in err_str for kw in (
        "unauthorized", "not enough rights", "admin required"
    )):
        return ErrorCategory.FATAL

    # 限流类错误
    if any(kw in err_str for kw in (
        "429", "too many requests", "rate limit", "flood", "retry after"
    )):
        return ErrorCategory.COOL_DOWN

    # 服务端错误
    if any(kw in err_str for kw in (
        "500", "502", "503", "504", "server error", "internal",
        "service unavailable", "gateway"
    )):
        return ErrorCategory.RETRYABLE

    # 网络类错误
    if any(kw in err_str for kw in (
        "timeout", "timed out", "connection", "network",
        "resolve", "refused", "reset"
    )):
        return ErrorCategory.RETRYABLE

    # 默认：可重试（保守策略）
    return ErrorCategory.RETRYABLE


def safe_execute(func, operation_name: str, fallback_value=None,
                 report_fault_fn=None, *args, **kwargs):
    """
    安全执行函数，带异常分类 + 自动恢复 + 故障上报。

    参数:
      func: 要执行的函数
      operation_name: 操作名称（用于日志）
      fallback_value: 失败时返回的默认值
      report_fault_fn: 故障上报函数（可选）

    返回:
      (result, success, error_category)
    """
    try:
        result = func(*args, **kwargs)
        return result, True, None
    except Exception as e:
        category = classify_error(e)

        if category == ErrorCategory.FATAL:
            logger.error(f"致命错误 [{operation_name}]: {e}")
        elif category == ErrorCategory.COOL_DOWN:
            logger.warning(f"需冷却 [{operation_name}]: {e}")
        else:
            logger.warning(f"可重试错误 [{operation_name}]: {e}")

        # 故障上报
        if report_fault_fn:
            try:
                report_fault_fn(
                    f"{operation_name} 执行失败",
                    f"{category}: {str(e)[:80]}",
                    "⚠️" if category != ErrorCategory.FATAL else "🔴"
                )
            except Exception:
                pass

        return fallback_value, False, category


# ════════════════════════ 5. 统一限流管理器 ═════════════════════════════════

class RateLimitManager:
    """
    统一限流管理器，聚合所有限流器。

    使用方式:
      rlm = RateLimitManager()
      rlm.init(config)
      # 在消息处理前
      if not rlm.allow_user_message(uid):
          return  # 用户被限流
    """

    def __init__(self):
        self.user_limiter: UserRateLimiter = None
        self.chat_limiter: ChatRateLimiter = None
        self.backoff: ExponentialBackoff = None
        self._initialized = False

    def init(self, config: dict):
        """从配置初始化所有限流器"""
        if self._initialized:
            return

        # 用户级限流
        user_config = config.get("RATE_LIMIT_USER", {})
        self.user_limiter = UserRateLimiter(
            window_sec=user_config.get("window_sec", 3600),
            max_requests=user_config.get("max_requests", 2),
        )

        # 群级限流
        chat_config = config.get("RATE_LIMIT_CHAT", {})
        self.chat_limiter = ChatRateLimiter(
            window_sec=chat_config.get("window_sec", 5),
            threshold=chat_config.get("threshold", 10),
        )

        # 退避重试
        retry_config = config.get("RETRY_CONFIG", {})
        self.backoff = ExponentialBackoff(
            base_delay=retry_config.get("base_delay", 1.0),
            max_delay=retry_config.get("max_delay", 60.0),
            max_retries=retry_config.get("max_retries", 3),
        )

        self._initialized = True
        logger.info("限流管理器初始化完成")

    def allow_user_message(self, uid: int) -> bool:
        """检查用户是否可以发送私信/挽回消息"""
        if not self._initialized:
            return True  # 未初始化时默认放行
        return self.user_limiter.allow(uid)

    def record_chat_message(self, chat_id: int):
        """记录群聊消息（用于刷屏检测）"""
        if self._initialized and self.chat_limiter:
            self.chat_limiter.record(chat_id)

    def is_chat_flooding(self, chat_id: int) -> bool:
        """检查群聊是否在刷屏"""
        if not self._initialized:
            return False
        return self.chat_limiter.is_flooding(chat_id)

    def periodic_cleanup(self):
        """定期清理过期记录（建议每分钟调用一次）"""
        if self._initialized:
            if self.user_limiter:
                self.user_limiter.cleanup()
            if self.chat_limiter:
                self.chat_limiter.cleanup()

    def get_stats(self) -> dict:
        """获取所有限流器统计"""
        stats = {}
        if self._initialized:
            if self.user_limiter:
                stats["user"] = self.user_limiter.get_stats()
            if self.backoff:
                stats["backoff_failures"] = dict(self.backoff._failures)
        return stats


# ════════════════════════ 全局单例 ═════════════════════════════════════════

_rate_limit_manager: RateLimitManager = None


def get_rate_limit_manager() -> RateLimitManager:
    """获取全局限流管理器单例"""
    global _rate_limit_manager
    if _rate_limit_manager is None:
        _rate_limit_manager = RateLimitManager()
    return _rate_limit_manager