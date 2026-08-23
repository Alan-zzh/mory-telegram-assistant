# -*- coding: utf-8 -*-
"""
core/metrics.py · Prometheus 业务指标定义与采集

指标清单：
  - conversion_total (Gauge): 当前数据库内转化事件累计值
  - llm_cost_cents (Gauge): LLM 成本熔断器当前累计成本（美分）

历史（v5.41.0）：write_queue_backlog 指标随 write_queue 删除而移除。

采集方式：
  由 tasks/analytics/prometheus_metrics_task 调用 update_metrics() 刷新指标值
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
    llm_cost_cents = _DummyMetric()


def update_metrics():
    """
    定期更新 Prometheus 指标（由统一调度器定时任务调用）

    采集逻辑：
    1. llm_cost_cents: 从 LLMCostGuard 获取最近成本统计
    2. conversion_total: 查询 conversion_events 表累计事件数并 set
    """
    if not PROMETHEUS_AVAILABLE:
        return

    try:
        # 1. 更新 LLM 成本
        _update_llm_cost()

        # 2. 更新转化计数（从数据库查询最近事件）
        _update_conversion_total()

        logger.debug("✅ Prometheus 指标更新完成")

    except Exception as e:
        logger.error(f"❌ Prometheus 指标更新失败: {e}")


def _update_llm_cost():
    """从 LLMCostGuard 获取成本统计"""
    try:
        from core.llm_cost_guard import get_guard
        guard = get_guard()
        if guard:
            stats = guard.get_stats()
            # 【v5.31.2 修复】LLMCostGuard.get_stats() 返回 total_cost（美元），
            # 之前读取 total_cost_cents 字段不存在，导致 Prometheus 指标永远为 0
            total_cost_usd = stats.get("total_cost", 0.0)
            total_cost_cents = int(total_cost_usd * 100)
            llm_cost_cents.labels(model_name="default", task_type="general").set(total_cost_cents)
    except Exception as e:
        logger.debug(f"LLM 成本指标采集失败（非致命）: {e}")


def _update_conversion_total():
    """从 conversion_events 表统计最近转化事件

    【v5.31.2 修复】两个暗病：
    1. 原调用 dashboard.helpers.get_db() 使用 Flask 'g' 对象，在 Bot 进程 APScheduler
       任务中无 Flask 上下文会抛 RuntimeError，导致指标永远不被采集
    2. 原 SQL 查询 bot_id 字段，但 conversion_events 表只有 id/uid/event/ts/mode 五个字段，
       会抛 OperationalError
    修复：改用直接 sqlite3 连接 + SQL 去掉 bot_id，标签 bot_id 固定为 'default'
    """
    import sqlite3
    import os
    try:
        # 定位 mory.db 路径（core/ 的上一级目录）
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mory.db")
        if not os.path.exists(db_path):
            logger.debug(f"转化事件指标采集跳过：数据库不存在 {db_path}")
            return

        conn = sqlite3.connect(db_path, timeout=10.0)
        try:
            rows = conn.execute(
                "SELECT event, COUNT(*) as cnt "
                "FROM conversion_events "
                "GROUP BY event"
            ).fetchall()

            for event_type, count in rows:
                conversion_total.labels(
                    event_type=event_type or "unknown",
                    bot_id="default"
                ).set(count)
        finally:
            conn.close()
    except Exception as e:
        logger.debug(f"转化事件指标采集失败（非致命）: {e}")
