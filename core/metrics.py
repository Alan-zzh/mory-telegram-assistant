# -*- coding: utf-8 -*-
"""
core/metrics.py · Prometheus 业务指标定义与采集

指标清单：
  - conversion_total (Gauge): 当前数据库内转化事件累计值
  - write_queue_backlog (Gauge): 写队列当前积压任务数
  - llm_cost_cents (Gauge): LLM 成本熔断器当前累计成本（美分）

采集方式：
  由 auto_tasks 每 5 分钟调用 update_metrics() 刷新指标值
"""

from core.logging_util import get_logger

logger = get_logger("metrics")

# ============ Prometheus 指标定义 ============
try:
    from prometheus_client import Gauge

    # 数据库派生指标使用 Gauge.set()，避免定时任务重复累加同一批事件。
    conversion_total = Gauge(
        "mory_conversion_total",
        "Current total number of conversion events stored in database",
        ["event_type", "bot_id"]
    )

    # 写队列当前积压任务数（从 WriteQueue.get_stats() 获取）
    write_queue_backlog = Gauge(
        "mory_write_queue_backlog",
        "Current number of pending tasks in write queue"
    )

    llm_cost_cents = Gauge(
        "mory_llm_cost_cents",
        "Current LLM invocation cost in cents reported by LLMCostGuard",
        ["model_name", "task_type"]
    )

    PROMETHEUS_AVAILABLE = True
    logger.info("✅ Prometheus 指标初始化成功")

except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("⚠️ prometheus-client 未安装，指标监控功能禁用")

    # 提供空实现避免调用方报错
    class _DummyMetric:
        def labels(self, *args, **kwargs):
            return self

        def inc(self, *args, **kwargs):
            pass

        def set(self, *args, **kwargs):
            pass

    conversion_total = _DummyMetric()
    write_queue_backlog = _DummyMetric()
    llm_cost_cents = _DummyMetric()


def update_metrics():
    """
    定期更新 Prometheus 指标（由 auto_tasks 定时任务调用）

    采集逻辑：
    1. conversion_total: 查询 conversion_events 表累计事件数并 set
    2. write_queue_backlog: 从全局 WriteQueue 实例获取 pending 数
    3. llm_cost_cents: 从 LLMCostGuard 获取最近成本统计
    """
    if not PROMETHEUS_AVAILABLE:
        return

    try:
        # 1. 更新写队列积压
        _update_write_queue_backlog()

        # 2. 更新 LLM 成本
        _update_llm_cost()

        # 3. 更新转化计数（从数据库查询最近事件）
        _update_conversion_total()

        logger.debug("✅ Prometheus 指标更新完成")

    except Exception as e:
        logger.error(f"❌ Prometheus 指标更新失败: {e}")


def _update_write_queue_backlog():
    """从全局 WriteQueue 实例获取积压任务数"""
    try:
        from core.write_queue import write_queue
        if write_queue:
            stats = write_queue.get_stats()
            pending = stats.get("pending", 0)
            write_queue_backlog.set(pending)
    except Exception as e:
        logger.debug(f"写队列指标采集失败（非致命）: {e}")


def _update_llm_cost():
    """从 LLMCostGuard 获取成本统计"""
    try:
        from core.llm_cost_guard import get_guard
        guard = get_guard()
        if guard:
            stats = guard.get_stats()
            total_cost = stats.get("total_cost_cents", 0)
            llm_cost_cents.labels(model_name="default", task_type="general").set(total_cost)
    except Exception as e:
        logger.debug(f"LLM 成本指标采集失败（非致命）: {e}")


def _update_conversion_total():
    """从 conversion_events 表统计最近转化事件"""
    try:
        from dashboard.helpers import get_db
        conn = get_db()
        if conn:
            rows = conn.execute(
                "SELECT event, bot_id, COUNT(*) as cnt "
                "FROM conversion_events "
                "GROUP BY event, bot_id"
            ).fetchall()

            for event_type, bot_id, count in rows:
                conversion_total.labels(
                    event_type=event_type or "unknown",
                    bot_id=bot_id or "default"
                ).set(count)
    except Exception as e:
        logger.debug(f"转化事件指标采集失败（非致命）: {e}")
