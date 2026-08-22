# -*- coding: utf-8 -*-
"""
core/alert_bot.py  ·  独立告警 Bot 通道（v5.25.0 阶段2-B 告警风暴风险控制）

功能：
  1. 独立 Bot Token（ALERT_BOT_TOKEN），与业务 Bot 完全隔离
  2. 直接 requests 调 Telegram Bot API，不依赖 pyTelegramBotAPI
  3. 告警分级 WARNING / CRITICAL / INFO
  4. 滑动窗口计数器去重：5 分钟窗口内相同 fingerprint 首条即发，后续仅计数；
     窗口结束由 flush_alert_summary() 发送合并汇总，避免告警风暴刷屏
  5. 级联抑制：根因告警（如数据库锁）活跃时，下游告警（调度失败/队列积压）
     自动 mute（仅计数不发送），根因解除（5min 无新触发）后下游恢复
  6. 限流：每分钟最多 10 条（滑动窗口 deque）
  7. 优雅降级：Token 未配置时只写日志不发送

使用：
  from core.alert_bot import send_alert, get_alert_stats, flush_alert_summary
  send_alert("WARNING", "队列积压", "qsize=80", {"qsize": 80})
  flush_alert_summary()  # 由调度器 flush_alert_summary 任务每 5 分钟调用
"""

import os
import time
import json
import hashlib
import threading
from collections import deque

from core.logging_util import get_logger

logger = get_logger("alert_bot")

# 告警级别 emoji
_LEVEL_EMOJI = {"WARNING": "⚠️", "CRITICAL": "🔴", "INFO": "ℹ️"}
# 去重/计数窗口（秒）：相同告警 5 分钟内首条即发，后续计数
_DEDUP_WINDOW = 300
# 限流：每分钟最多 10 条
_RATE_LIMIT_MAX = 10
_RATE_LIMIT_WINDOW = 60
# 最近告警审计队列容量
_RECENT_ALERTS_MAXLEN = 100


# ── 级联抑制规则 ──────────────────────────────────────────────
# 根因告警类型 → [被抑制的下游告警类型]
# 当根因告警活跃（5min 内有触发）时，下游告警自动 mute（仅计数不发送）
_SUPPRESSION_MAP: dict = {
    "SYSTEM_DATABASE_LOCKED": ["SCHEDULER_JOB_FAILED", "WRITE_QUEUE_BACKLOG"],
}


def _normalize_alert_type(title: str) -> str:
    """将告警标题归一化为标准类型，用于级联抑制匹配（未匹配返回空串）"""
    if not title:
        return ""
    t = title.lower()
    # 数据库锁：SYSTEM_DATABASE_LOCKED
    if "数据库" in title and ("锁" in title or "lock" in t):
        return "SYSTEM_DATABASE_LOCKED"
    if "database" in t and "lock" in t:
        return "SYSTEM_DATABASE_LOCKED"
    # 写入队列积压：WRITE_QUEUE_BACKLOG
    if "writequeue" in t or "队列积压" in title or "写入队列" in title:
        return "WRITE_QUEUE_BACKLOG"
    # 调度任务失败：SCHEDULER_JOB_FAILED
    if "调度" in title and "失败" in title:
        return "SCHEDULER_JOB_FAILED"
    if "scheduler" in t and "fail" in t:
        return "SCHEDULER_JOB_FAILED"
    return ""


class _AlertBot:
    """告警 Bot 单例（懒加载，首次 send_alert 时初始化）"""

    def __init__(self):
        self.token = os.environ.get("ALERT_BOT_TOKEN", "").strip()
        self.chat_id = os.environ.get("ALERT_CHAT_ID", "").strip()
        self.enabled = bool(self.token and self.chat_id)
        self._lock = threading.Lock()
        # 滑动窗口计数器：{fingerprint: {first_ts, count, level, title, last_message, last_context, suppressed}}
        self._counters: dict = {}
        # 活跃根因告警：{alert_type: last_trigger_ts}
        self._active_root_causes: dict = {}
        # 最近告警审计队列：(fingerprint, timestamp)
        self._recent_alerts: deque = deque(maxlen=_RECENT_ALERTS_MAXLEN)
        # 限流滑动窗口：最近 1 分钟发送时间戳
        self._send_times: deque = deque()
        self._stats = {
            "total": 0, "sent": 0, "deduped": 0, "throttled": 0,
            "suppressed": 0, "summarized": 0, "last_error": "",
        }

    def send(self, level: str, title: str, message: str, context: dict = None) -> bool:
        """发送告警（线程安全）"""
        self._stats["total"] += 1
        level = level.upper() if level else "INFO"
        emoji = _LEVEL_EMOJI.get(level, "ℹ️")

        # 未配置 Token：只写日志，不发送
        if not self.enabled:
            logger.info(f"[告警降级] {level} {title} | {message}")
            return False

        dedup_key = hashlib.md5(f"{level}|{title}".encode("utf-8")).hexdigest()
        alert_type = _normalize_alert_type(title)
        now = time.time()

        # 锁内：判定去重/抑制/限流，收集待发送文本（网络 IO 留到锁外）
        # to_send 元素：(kind, key, text)  kind ∈ {"alert", "summary"}
        to_send: list = []
        with self._lock:
            self._gc_root_causes(now)
            is_suppressed = self._is_downstream_suppressed(alert_type, now)

            counter = self._counters.get(dedup_key)
            # 窗口已过期 或 抑制状态翻转（根因出现/解除）：收尾旧计数器
            # —— 保证根因解除后下游立即恢复发送，根因出现后下游立即静音
            if counter and (
                (now - counter["first_ts"]) >= _DEDUP_WINDOW
                or counter.get("suppressed") != is_suppressed
            ):
                old = self._counters.pop(dedup_key)
                if old["count"] > 1 and not old.get("suppressed"):
                    to_send.append(("summary", old["title"], self._build_summary_text(old)))
                counter = None

            if counter is None:
                # 窗口内首条：起计数器；非抑制则立即发送
                self._counters[dedup_key] = {
                    "first_ts": now, "count": 1, "level": level, "title": title,
                    "last_message": message, "last_context": context,
                    "suppressed": is_suppressed,
                }
                self._recent_alerts.append((dedup_key, now))
                # 根因告警标记活跃
                if alert_type in _SUPPRESSION_MAP:
                    self._active_root_causes[alert_type] = now
                if not is_suppressed:
                    self._gc_send_times(now)
                    if len(self._send_times) >= _RATE_LIMIT_MAX:
                        self._stats["throttled"] += 1
                        logger.warning(f"[告警限流] 每分钟 {_RATE_LIMIT_MAX} 条已达上限，丢弃: {level} {title}")
                    else:
                        self._send_times.append(now)
                        to_send.append(("alert", dedup_key, self._build_alert_text(emoji, level, title, message, context)))
                else:
                    self._stats["suppressed"] += 1
                    logger.debug(f"[告警级联抑制] {level} {title} 被根因告警静音")
            else:
                # 窗口内重复：计数 +1，不发送
                counter["count"] += 1
                counter["last_message"] = message
                counter["last_context"] = context
                # 根因告警刷新活跃时间
                if alert_type in _SUPPRESSION_MAP:
                    self._active_root_causes[alert_type] = now
                if is_suppressed:
                    self._stats["suppressed"] += 1
                else:
                    self._stats["deduped"] += 1
                    logger.debug(f"[告警去重] {level} {title} 5分钟窗口内已计数 {counter['count']} 次")

        # 锁外：实际发送（避免网络 IO 持锁）
        ok = False
        for kind, key, text in to_send:
            sent = self._call_telegram(text)
            if sent:
                self._stats["sent"] += 1
                if kind == "alert":
                    ok = True
                else:
                    self._stats["summarized"] += 1
            else:
                if kind == "alert":
                    # 首条告警发送失败：回滚计数器允许下次重试
                    with self._lock:
                        c = self._counters.get(key)
                        if c and c["count"] == 1:
                            self._counters.pop(key, None)
        return ok

    def flush_alert_summary(self) -> int:
        """
        定时汇总：遍历窗口内已过期的计数器，对 count>1 且未被抑制的告警
        发送合并汇总消息，清空已汇总的计数器。由调度器 flush_alert_summary 任务每 5 分钟调用。
        Returns: 本次发送的汇总条数
        """
        now = time.time()
        with self._lock:
            self._gc_root_causes(now)
            expired_keys = [
                k for k, c in self._counters.items()
                if (now - c["first_ts"]) >= _DEDUP_WINDOW
            ]
            summaries = []
            for k in expired_keys:
                c = self._counters.pop(k)
                if c["count"] > 1 and not c.get("suppressed"):
                    summaries.append(c)

        # 锁外发送汇总
        for c in summaries:
            text = self._build_summary_text(c)
            sent = self._call_telegram(text)
            if sent:
                self._stats["sent"] += 1
                self._stats["summarized"] += 1
            else:
                logger.warning(f"[告警汇总发送失败] {c['title']} count={c['count']}")

        if summaries:
            logger.info(f"[告警汇总] 本次发送 {len(summaries)} 条合并汇总")
        return len(summaries)

    # ── 文本构造 ──────────────────────────────────────────────
    def _build_alert_text(self, emoji: str, level: str, title: str, message: str, context: dict) -> str:
        """构造单条告警消息文本"""
        text = f"{emoji} [{level}] {title}\n\n{message}"
        if context:
            try:
                ctx_str = json.dumps(context, ensure_ascii=False, default=str)
                if len(ctx_str) > 800:
                    ctx_str = ctx_str[:800] + "...(截断)"
                text += f"\n\n📋 上下文:\n{ctx_str}"
            except Exception as e:
                logger.debug(f"上下文序列化失败: {e}")
        return text

    def _build_summary_text(self, counter: dict) -> str:
        """构造告警合并汇总文本"""
        return (
            f"📊 【告警合并】过去 5 分钟内共触发 {counter['count']} 次 "
            f"{counter['title']}，已自动静音该类报警"
        )

    # ── 级联抑制辅助 ──────────────────────────────────────────
    def _is_downstream_suppressed(self, alert_type: str, now: float) -> bool:
        """检查该告警类型是否被某个活跃的根因告警抑制"""
        if not alert_type:
            return False
        for root_type, downstream in _SUPPRESSION_MAP.items():
            if alert_type in downstream:
                last_ts = self._active_root_causes.get(root_type)
                if last_ts and (now - last_ts) < _DEDUP_WINDOW:
                    return True
        return False

    def _gc_root_causes(self, now: float):
        """清理过期的根因告警（5min 无新触发即解除，下游恢复发送）"""
        expired = [t for t, ts in self._active_root_causes.items() if (now - ts) >= _DEDUP_WINDOW]
        for t in expired:
            self._active_root_causes.pop(t, None)

    # ── 限流辅助 ──────────────────────────────────────────────
    def _gc_send_times(self, now: float):
        """清理滑动窗口外的时间戳"""
        while self._send_times and (now - self._send_times[0]) >= _RATE_LIMIT_WINDOW:
            self._send_times.popleft()

    # ── 统计 ──────────────────────────────────────────────────
    def get_stats(self) -> dict:
        """获取告警统计"""
        with self._lock:
            return {
                "enabled": self.enabled,
                **dict(self._stats),
                "active_counters": len(self._counters),
                "active_root_causes": len(self._active_root_causes),
                "rate_window_size": len(self._send_times),
                "recent_alerts": len(self._recent_alerts),
            }


# 模块级单例（懒加载）
_instance: _AlertBot = None
_instance_lock = threading.Lock()


def _get_instance() -> _AlertBot:
    """懒加载单例"""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = _AlertBot()
                if _instance.enabled:
                    logger.info("✅ 告警 Bot 已启用（独立通道）")
                else:
                    logger.info("ℹ️ 告警 Bot 未配置 Token，降级为仅日志模式")
    return _instance


def send_alert(level: str, title: str, message: str, context: dict = None) -> bool:
    """
    发送告警（外部统一入口）。
    Returns: True 发送成功，False 表示被去重/限流/降级/抑制/发送失败
    """
    try:
        return _get_instance().send(level, title, message, context)
    except Exception as e:
        logger.error(f"[send_alert 兜底异常] {type(e).__name__}: {e}")  # 告警系统绝不能影响业务
        return False


def flush_alert_summary() -> int:
    """
    定时汇总告警（由调度器 flush_alert_summary 任务每 5 分钟调用）。
    对窗口内 count>1 的告警发送合并汇总消息，清空已汇总计数器。
    Returns: 本次发送的汇总条数
    """
    try:
        return _get_instance().flush_alert_summary()
    except Exception as e:
        logger.error(f"[flush_alert_summary 兜底异常] {type(e).__name__}: {e}")
        return 0


def get_alert_stats() -> dict:
    """获取告警统计（total/sent/deduped/throttled/suppressed/summarized/last_error）"""
    try:
        return _get_instance().get_stats()
    except Exception as e:
        logger.error(f"[get_alert_stats 兜底异常] {type(e).__name__}: {e}")
        return {"enabled": False, "error": str(e)[:200]}
