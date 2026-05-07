# -*- coding: utf-8 -*-
"""
core/token_statistics.py · Token统计报表系统

功能：
    - 提供Token消耗的多维度统计
    - 支持单次、每日、每周、每月的统计
    - 支持报表导出为CSV格式

依赖：
    - core.database
"""

import logging
from core.logging_util import get_logger
from core.database import get_db
from datetime import datetime, timedelta

logger = get_logger("token_statistics")

class TokenStatistics:
    """Token统计报表类"""
    
    def __init__(self):
        """初始化Token统计报表类"""
        self.db = get_db()
    
    def get_single_statistic(self, record_id):
        """
        获取单次token消耗统计
        
        Args:
            record_id: 记录ID
            
        Returns:
            单次token消耗统计数据
        """
        try:
            result = self.db.get_single_statistic(record_id)
            if result:
                logger.info(f"📊 获取单次统计成功: {record_id}")
            else:
                logger.warning(f"⚠️ 单次统计记录不存在: {record_id}")
            return result
        except Exception as e:
            logger.error(f"❌ 获取单次统计失败: {e}")
            return None
    
    def get_daily_statistic(self, date=None):
        """
        获取每日token消耗统计
        
        Args:
            date: 日期，格式为"YYYY-MM-DD"，默认为今天
            
        Returns:
            每日token消耗统计数据
        """
        try:
            if date is None:
                date = datetime.now().strftime("%Y-%m-%d")
            result = self.db.get_daily_statistic(date)
            if result:
                logger.info(f"📊 获取每日统计成功: {date}")
            else:
                logger.warning(f"⚠️ 每日统计数据不存在: {date}")
            return result
        except Exception as e:
            logger.error(f"❌ 获取每日统计失败: {e}")
            return None
    
    def get_weekly_statistic(self, week_start_date=None):
        """
        获取每周token消耗统计
        
        Args:
            week_start_date: 周开始日期，格式为"YYYY-MM-DD"，默认为本周一
            
        Returns:
            每周token消耗统计数据
        """
        try:
            if week_start_date is None:
                # 计算本周一
                today = datetime.now()
                week_start = today - timedelta(days=today.weekday())
                week_start_date = week_start.strftime("%Y-%m-%d")
            result = self.db.get_weekly_statistic(week_start_date)
            if result:
                logger.info(f"📊 获取每周统计成功: {week_start_date}")
            else:
                logger.warning(f"⚠️ 每周统计数据不存在: {week_start_date}")
            return result
        except Exception as e:
            logger.error(f"❌ 获取每周统计失败: {e}")
            return None
    
    def get_monthly_statistic(self, month=None):
        """
        获取每月token消耗统计
        
        Args:
            month: 月份，格式为"YYYY-MM"，默认为本月
            
        Returns:
            每月token消耗统计数据
        """
        try:
            if month is None:
                month = datetime.now().strftime("%Y-%m")
            result = self.db.get_monthly_statistic(month)
            if result:
                logger.info(f"📊 获取每月统计成功: {month}")
            else:
                logger.warning(f"⚠️ 每月统计数据不存在: {month}")
            return result
        except Exception as e:
            logger.error(f"❌ 获取每月统计失败: {e}")
            return None
    
    def export_report(self, report_type, period=None):
        """
        导出统计报表
        
        Args:
            report_type: 报表类型，可选值："daily", "weekly", "monthly"
            period: 时间段，根据报表类型格式不同，默认为当前时间
            
        Returns:
            CSV格式的报表数据
        """
        try:
            if period is None:
                if report_type == "daily":
                    period = datetime.now().strftime("%Y-%m-%d")
                elif report_type == "weekly":
                    # 计算本周一
                    today = datetime.now()
                    week_start = today - timedelta(days=today.weekday())
                    period = week_start.strftime("%Y-%m-%d")
                elif report_type == "monthly":
                    period = datetime.now().strftime("%Y-%m")
                else:
                    logger.error(f"❌ 不支持的报表类型: {report_type}")
                    return None
            
            result = self.db.export_report(report_type, period)
            if result:
                logger.info(f"📊 导出报表成功: {report_type} - {period}")
            else:
                logger.warning(f"⚠️ 报表数据不存在: {report_type} - {period}")
            return result
        except Exception as e:
            logger.error(f"❌ 导出报表失败: {e}")
            return None
    
    def get_summary_statistics(self):
        """
        获取汇总统计信息
        
        Returns:
            汇总统计数据
        """
        try:
            # 获取今日统计
            today_stat = self.get_daily_statistic()
            
            # 获取本周统计
            weekly_stat = self.get_weekly_statistic()
            
            # 获取本月统计
            monthly_stat = self.get_monthly_statistic()
            
            summary = {
                "today": today_stat,
                "week": weekly_stat,
                "month": monthly_stat
            }
            
            logger.info("📊 获取汇总统计成功")
            return summary
        except Exception as e:
            logger.error(f"❌ 获取汇总统计失败: {e}")
            return None

# 全局统计实例
stats_instance = None
def get_stats():
    """
    获取统计实例
    
    Returns:
        TokenStatistics实例
    """
    global stats_instance
    if stats_instance is None:
        stats_instance = TokenStatistics()
    return stats_instance
