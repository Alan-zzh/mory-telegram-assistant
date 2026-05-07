# -*- coding: utf-8 -*-
"""
core/token_statistics.py · Token统计报表系统

功能：
    - 提供Token消耗的多维度统计（单次/每日/每周/每月）
    - 支持报表导出为CSV格式
    - 底层委托给 universal_ai_router 的 RouterStatistics 实现

依赖：
    - universal_ai_router.core.router_database.RouterDatabase
    - universal_ai_router.core.router_statistics.RouterStatistics
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from core.logging_util import get_logger
from universal_ai_router.core.router_database import RouterDatabase
from universal_ai_router.core.router_statistics import RouterStatistics

logger = get_logger("token_statistics")

_CST = timezone(timedelta(hours=8))

_router_db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "router.db")


class TokenStatistics:

    def __init__(self, db_path: Optional[str] = None):
        _path = db_path or _router_db_path
        self._router_db = RouterDatabase(_path)
        self._stats = RouterStatistics(self._router_db)

    def get_single_statistic(self, record_id: int) -> Optional[Dict[str, Any]]:
        try:
            result = self._stats.get_single_statistic(record_id)
            if result:
                logger.info(f"📊 获取单次统计成功: {record_id}")
            else:
                logger.warning(f"⚠️ 单次统计记录不存在: {record_id}")
            return result
        except Exception as e:
            logger.error(f"❌ 获取单次统计失败: {e}")
            return None

    def get_daily_statistic(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        try:
            if date_str is None:
                date_str = datetime.now(_CST).strftime("%Y-%m-%d")
            result = self._stats.get_daily_statistic(date_str)
            if result and result.get("total_calls", 0) > 0:
                logger.info(f"📊 获取每日统计成功: {date_str}")
            else:
                logger.warning(f"⚠️ 每日统计数据不存在: {date_str}")
            return result
        except Exception as e:
            logger.error(f"❌ 获取每日统计失败: {e}")
            return {}

    def get_weekly_statistic(self, week_start_date: Optional[str] = None) -> Dict[str, Any]:
        try:
            if week_start_date is None:
                today = datetime.now(_CST)
                week_start = today - timedelta(days=today.weekday())
                week_start_date = week_start.strftime("%Y-%m-%d")
            result = self._stats.get_weekly_statistic(week_start_date)
            if result and result.get("total_calls", 0) > 0:
                logger.info(f"📊 获取每周统计成功: {week_start_date}")
            else:
                logger.warning(f"⚠️ 每周统计数据不存在: {week_start_date}")
            return result
        except Exception as e:
            logger.error(f"❌ 获取每周统计失败: {e}")
            return {}

    def get_monthly_statistic(self, month: Optional[str] = None) -> Dict[str, Any]:
        try:
            if month is None:
                month = datetime.now(_CST).strftime("%Y-%m")
            result = self._stats.get_monthly_statistic(month)
            if result and result.get("total_calls", 0) > 0:
                logger.info(f"📊 获取每月统计成功: {month}")
            else:
                logger.warning(f"⚠️ 每月统计数据不存在: {month}")
            return result
        except Exception as e:
            logger.error(f"❌ 获取每月统计失败: {e}")
            return {}

    def export_report(self, report_type: str, period: Optional[str] = None) -> str:
        try:
            if period is None:
                if report_type == "daily":
                    period = datetime.now(_CST).strftime("%Y-%m-%d")
                elif report_type == "weekly":
                    today = datetime.now(_CST)
                    week_start = today - timedelta(days=today.weekday())
                    period = week_start.strftime("%Y-%m-%d")
                elif report_type == "monthly":
                    period = datetime.now(_CST).strftime("%Y-%m")
                else:
                    logger.error(f"❌ 不支持的报表类型: {report_type}")
                    return ""
            result = self._stats.export_report(report_type, period)
            if result:
                logger.info(f"📊 导出报表成功: {report_type} - {period}")
            else:
                logger.warning(f"⚠️ 报表数据不存在: {report_type} - {period}")
            return result
        except Exception as e:
            logger.error(f"❌ 导出报表失败: {e}")
            return ""

    def get_summary_statistics(self) -> Dict[str, Any]:
        try:
            result = self._stats.get_summary_statistics()
            logger.info("📊 获取汇总统计成功")
            return result
        except Exception as e:
            logger.error(f"❌ 获取汇总统计失败: {e}")
            return {}

    def close(self):
        if self._router_db:
            self._router_db.close()


_stats_instance = None


def get_stats(db_path: Optional[str] = None) -> TokenStatistics:
    global _stats_instance
    if _stats_instance is None:
        _stats_instance = TokenStatistics(db_path)
    return _stats_instance
