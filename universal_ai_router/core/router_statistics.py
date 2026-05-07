# 项目：universal_ai_router | 版本：v1.0.0 | 日期：2026-04-23 | 功能：Token统计报表模块
"""
Token统计报表模块 - 提供多维度的Token使用统计和CSV报表导出
"""

import csv
import io
import logging
import threading
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List

from .router_database import get_router_database, RouterDatabase

logger = logging.getLogger(__name__)


class RouterStatistics:
    """Token统计报表类"""

    def __init__(self, db_instance: Optional[RouterDatabase] = None):
        """
        初始化统计报表
        :param db_instance: 数据库实例，默认自动获取单例
        """
        self.db = db_instance or get_router_database()

    def get_single_statistic(self, record_id: int) -> Optional[Dict[str, Any]]:
        """
        获取单次调用的详细统计
        :param record_id: 记录ID
        :return: 单次统计信息字典
        """
        query_sql = "SELECT * FROM token_usage WHERE id = ?"

        try:
            rows = self.db.get_usage_by_model("")
            # 这里直接用record_id查询比较特殊，因为get_usage_by_model是按模型名查
            # 需要直接用SQL查询单条记录
            with self.db._get_connection() as conn:
                cursor = conn.execute(query_sql, (record_id,))
                row = cursor.fetchone()
                if row:
                    result = dict(row)
                    result['success_rate'] = result['success_count'] / result['total_calls'] * 100 if result['total_calls'] else 0
                    return result
                return None
        except Exception as e:
            logger.error(f"查询单次统计失败 (ID={record_id}): {e}")
            return None

    def get_daily_statistic(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        获取每日统计
        :param target_date: 目标日期（YYYY-MM-DD格式），默认今天
        :return: 每日统计数据字典
        """
        if target_date is None:
            target_date = date.today().isoformat()

        stats = self.db.get_daily_usage(target_date)

        # 如果当天有数据，补充详细统计
        if stats and stats.get('total_calls', 0) > 0:
            # 按小时分布
            hourly_stats = self._get_hourly_distribution(target_date)
            stats['hourly_distribution'] = hourly_stats

            # 按任务类型分布
            task_stats = self._get_task_type_distribution(target_date)
            stats['task_type_distribution'] = task_stats

            # 按模型分布
            model_stats = self._get_model_distribution(target_date)
            stats['model_distribution'] = model_stats

        return stats

    def _get_hourly_distribution(self, target_date: str) -> List[Dict[str, Any]]:
        """获取当天每小时的使用分布"""
        query_sql = """
        SELECT
            substr(timestamp, 12, 2) as hour,
            COUNT(*) as calls,
            SUM(total_tokens) as tokens,
            SUM(cost) as cost
        FROM token_usage
        WHERE substr(timestamp, 1, 10) = ?
        GROUP BY substr(timestamp, 12, 2)
        ORDER BY hour
        """

        try:
            with self.db._get_connection() as conn:
                cursor = conn.execute(query_sql, (target_date,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"查询小时分布失败: {e}")
            return []

    def _get_task_type_distribution(self, target_date: str) -> List[Dict[str, Any]]:
        """获取当天各任务类型的使用分布"""
        query_sql = """
        SELECT
            task_type,
            COUNT(*) as calls,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            SUM(total_tokens) as total_tokens,
            SUM(cost) as cost
        FROM token_usage
        WHERE substr(timestamp, 1, 10) = ?
        GROUP BY task_type
        ORDER BY cost DESC
        """

        try:
            with self.db._get_connection() as conn:
                cursor = conn.execute(query_sql, (target_date,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"查询任务类型分布失败: {e}")
            return []

    def _get_model_distribution(self, target_date: str) -> List[Dict[str, Any]]:
        """获取当天各模型的使用分布"""
        query_sql = """
        SELECT
            model_name,
            provider,
            COUNT(*) as calls,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            SUM(total_tokens) as total_tokens,
            SUM(cost) as cost
        FROM token_usage
        WHERE substr(timestamp, 1, 10) = ?
        GROUP BY model_name, provider
        ORDER BY cost DESC
        """

        try:
            with self.db._get_connection() as conn:
                cursor = conn.execute(query_sql, (target_date,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"查询模型分布失败: {e}")
            return []

    def get_weekly_statistic(self, week_start_date: Optional[str] = None) -> Dict[str, Any]:
        """
        获取每周统计（周一到周日）
        :param week_start_date: 周起始日期（周一，YYYY-MM-DD格式），默认本周一
        :return: 每周统计数据字典
        """
        if week_start_date is None:
            today = date.today()
            # 计算本周一
            week_start_date = (today - timedelta(days=today.weekday())).isoformat()

        stats = self.db.get_weekly_usage(week_start_date)

        if stats and stats.get('total_calls', 0) > 0:
            # 按天分布
            daily_stats = self._get_daily_distribution_in_week(week_start_date)
            stats['daily_distribution'] = daily_stats

            # 按任务类型分布
            task_stats = self._get_task_type_distribution_week(week_start_date)
            stats['task_type_distribution'] = task_stats

            # 按模型分布
            model_stats = self._get_model_distribution_week(week_start_date)
            stats['model_distribution'] = model_stats

        return stats

    def _get_daily_distribution_in_week(self, week_start_date: str) -> List[Dict[str, Any]]:
        """获取本周每天的使用分布"""
        week_end_date = (datetime.strptime(week_start_date, "%Y-%m-%d") + timedelta(days=6)).strftime("%Y-%m-%d")

        query_sql = """
        SELECT
            substr(timestamp, 1, 10) as day,
            COUNT(*) as calls,
            SUM(total_tokens) as tokens,
            SUM(cost) as cost
        FROM token_usage
        WHERE substr(timestamp, 1, 10) >= ? AND substr(timestamp, 1, 10) <= ?
        GROUP BY substr(timestamp, 1, 10)
        ORDER BY day
        """

        try:
            with self.db._get_connection() as conn:
                cursor = conn.execute(query_sql, (week_start_date, week_end_date))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"查询本周天分布失败: {e}")
            return []

    def _get_task_type_distribution_week(self, week_start_date: str) -> List[Dict[str, Any]]:
        """获取本周各任务类型的使用分布"""
        week_end_date = (datetime.strptime(week_start_date, "%Y-%m-%d") + timedelta(days=6)).strftime("%Y-%m-%d")

        query_sql = """
        SELECT
            task_type,
            COUNT(*) as calls,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            SUM(total_tokens) as total_tokens,
            SUM(cost) as cost
        FROM token_usage
        WHERE substr(timestamp, 1, 10) >= ? AND substr(timestamp, 1, 10) <= ?
        GROUP BY task_type
        ORDER BY cost DESC
        """

        try:
            with self.db._get_connection() as conn:
                cursor = conn.execute(query_sql, (week_start_date, week_end_date))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"查询本周任务类型分布失败: {e}")
            return []

    def _get_model_distribution_week(self, week_start_date: str) -> List[Dict[str, Any]]:
        """获取本周各模型的使用分布"""
        week_end_date = (datetime.strptime(week_start_date, "%Y-%m-%d") + timedelta(days=6)).strftime("%Y-%m-%d")

        query_sql = """
        SELECT
            model_name,
            provider,
            COUNT(*) as calls,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            SUM(total_tokens) as total_tokens,
            SUM(cost) as cost
        FROM token_usage
        WHERE substr(timestamp, 1, 10) >= ? AND substr(timestamp, 1, 10) <= ?
        GROUP BY model_name, provider
        ORDER BY cost DESC
        """

        try:
            with self.db._get_connection() as conn:
                cursor = conn.execute(query_sql, (week_start_date, week_end_date))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"查询本周模型分布失败: {e}")
            return []

    def get_monthly_statistic(self, month: Optional[str] = None) -> Dict[str, Any]:
        """
        获取每月统计
        :param month: 月份（YYYY-MM格式），默认当前月份
        :return: 每月统计数据字典
        """
        if month is None:
            month = date.today().strftime("%Y-%m")

        stats = self.db.get_monthly_usage(month)

        if stats and stats.get('total_calls', 0) > 0:
            # 按天分布
            daily_stats = self._get_daily_distribution_in_month(month)
            stats['daily_distribution'] = daily_stats

            # 按任务类型分布
            task_stats = self._get_task_type_distribution_month(month)
            stats['task_type_distribution'] = task_stats

            # 按模型分布
            model_stats = self._get_model_distribution_month(month)
            stats['model_distribution'] = model_stats

        return stats

    def _get_daily_distribution_in_month(self, month: str) -> List[Dict[str, Any]]:
        """获取本月每天的使用分布"""
        query_sql = """
        SELECT
            substr(timestamp, 1, 10) as day,
            COUNT(*) as calls,
            SUM(total_tokens) as tokens,
            SUM(cost) as cost
        FROM token_usage
        WHERE substr(timestamp, 1, 7) = ?
        GROUP BY substr(timestamp, 1, 10)
        ORDER BY day
        """

        try:
            with self.db._get_connection() as conn:
                cursor = conn.execute(query_sql, (month,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"查询本月天分布失败: {e}")
            return []

    def _get_task_type_distribution_month(self, month: str) -> List[Dict[str, Any]]:
        """获取本月各任务类型的使用分布"""
        query_sql = """
        SELECT
            task_type,
            COUNT(*) as calls,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            SUM(total_tokens) as total_tokens,
            SUM(cost) as cost
        FROM token_usage
        WHERE substr(timestamp, 1, 7) = ?
        GROUP BY task_type
        ORDER BY cost DESC
        """

        try:
            with self.db._get_connection() as conn:
                cursor = conn.execute(query_sql, (month,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"查询本月任务类型分布失败: {e}")
            return []

    def _get_model_distribution_month(self, month: str) -> List[Dict[str, Any]]:
        """获取本月各模型的使用分布"""
        query_sql = """
        SELECT
            model_name,
            provider,
            COUNT(*) as calls,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            SUM(total_tokens) as total_tokens,
            SUM(cost) as cost
        FROM token_usage
        WHERE substr(timestamp, 1, 7) = ?
        GROUP BY model_name, provider
        ORDER BY cost DESC
        """

        try:
            with self.db._get_connection() as conn:
                cursor = conn.execute(query_sql, (month,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"查询本月模型分布失败: {e}")
            return []

    def get_summary_statistics(self) -> Dict[str, Any]:
        """
        获取汇总统计数据（今日/本周/本月）
        :return: 汇总统计字典
        """
        today = date.today().isoformat()
        week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
        month = date.today().strftime("%Y-%m")

        return {
            "today": self.get_daily_statistic(today),
            "this_week": self.get_weekly_statistic(week_start),
            "this_month": self.get_monthly_statistic(month),
            "generated_at": datetime.now().isoformat()
        }

    def export_report(self, report_type: str, period: Optional[str] = None) -> str:
        """
        导出CSV报表
        :param report_type: 报表类型（daily/weekly/monthly/summary）
        :param period: 时间周期
            - daily: YYYY-MM-DD格式，默认今天
            - weekly: YYYY-MM-DD格式（周一），默认本周
            - monthly: YYYY-MM格式，默认本月
            - summary: 无需period参数
        :return: CSV格式字符串
        """
        output = io.StringIO()

        if report_type == "daily":
            target_date = period or date.today().isoformat()
            stats = self.get_daily_statistic(target_date)
            output = self._export_daily_csv(stats, target_date)

        elif report_type == "weekly":
            week_start = period or (date.today() - timedelta(days=date.today().weekday())).isoformat()
            stats = self.get_weekly_statistic(week_start)
            output = self._export_weekly_csv(stats, week_start)

        elif report_type == "monthly":
            month = period or date.today().strftime("%Y-%m")
            stats = self.get_monthly_statistic(month)
            output = self._export_monthly_csv(stats, month)

        elif report_type == "summary":
            stats = self.get_summary_statistics()
            output = self._export_summary_csv(stats)

        else:
            logger.warning(f"未知的报表类型: {report_type}")
            return ""

        return output.getvalue() if isinstance(output, io.StringIO) else output

    def _export_daily_csv(self, stats: Dict[str, Any], target_date: str) -> io.StringIO:
        """导出每日CSV报表"""
        output = io.StringIO()
        writer = csv.writer(output)

        # 写入标题
        writer.writerow([
            "日期", "总调用次数", "成功次数", "失败次数",
            "输入Token", "输出Token", "总Token", "总成本", "平均成本/次"
        ])

        # 写入数据行
        writer.writerow([
            target_date,
            stats.get('total_calls', 0),
            stats.get('success_count', 0),
            stats.get('failure_count', 0),
            stats.get('total_input_tokens', 0),
            stats.get('total_output_tokens', 0),
            stats.get('total_tokens', 0),
            f"{stats.get('total_cost', 0):.6f}",
            f"{stats.get('avg_cost_per_call', 0):.6f}"
        ])

        # 写入模型分布详情
        writer.writerow([])
        writer.writerow(["模型分布详情"])
        writer.writerow(["模型名称", "Provider", "调用次数", "输入Token", "输出Token", "总Token", "成本"])

        for model in stats.get('model_distribution', []):
            writer.writerow([
                model.get('model_name', ''),
                model.get('provider', ''),
                model.get('calls', 0),
                model.get('input_tokens', 0),
                model.get('output_tokens', 0),
                model.get('total_tokens', 0),
                f"{model.get('cost', 0):.6f}"
            ])

        return output

    def _export_weekly_csv(self, stats: Dict[str, Any], week_start: str) -> io.StringIO:
        """导出每周CSV报表"""
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "周起始", "周结束", "总调用次数", "成功次数", "失败次数",
            "输入Token", "输出Token", "总Token", "总成本", "平均成本/次"
        ])

        writer.writerow([
            stats.get('week_start', week_start),
            stats.get('week_end', ''),
            stats.get('total_calls', 0),
            stats.get('success_count', 0),
            stats.get('failure_count', 0),
            stats.get('total_input_tokens', 0),
            stats.get('total_output_tokens', 0),
            stats.get('total_tokens', 0),
            f"{stats.get('total_cost', 0):.6f}",
            f"{stats.get('avg_cost_per_call', 0):.6f}"
        ])

        # 每日分布
        writer.writerow([])
        writer.writerow(["每日分布"])
        writer.writerow(["日期", "调用次数", "Token数", "成本"])

        for day in stats.get('daily_distribution', []):
            writer.writerow([
                day.get('day', ''),
                day.get('calls', 0),
                day.get('tokens', 0),
                f"{day.get('cost', 0):.6f}"
            ])

        return output

    def _export_monthly_csv(self, stats: Dict[str, Any], month: str) -> io.StringIO:
        """导出每月CSV报表"""
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "月份", "总调用次数", "成功次数", "失败次数",
            "输入Token", "输出Token", "总Token", "总成本", "平均成本/次"
        ])

        writer.writerow([
            month,
            stats.get('total_calls', 0),
            stats.get('success_count', 0),
            stats.get('failure_count', 0),
            stats.get('total_input_tokens', 0),
            stats.get('total_output_tokens', 0),
            stats.get('total_tokens', 0),
            f"{stats.get('total_cost', 0):.6f}",
            f"{stats.get('avg_cost_per_call', 0):.6f}"
        ])

        # 每日分布
        writer.writerow([])
        writer.writerow(["每日分布"])
        writer.writerow(["日期", "调用次数", "Token数", "成本"])

        for day in stats.get('daily_distribution', []):
            writer.writerow([
                day.get('day', ''),
                day.get('calls', 0),
                day.get('tokens', 0),
                f"{day.get('cost', 0):.6f}"
            ])

        return output

    def _export_summary_csv(self, stats: Dict[str, Any]) -> io.StringIO:
        """导出汇总CSV报表"""
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(["Universal AI Router - Token使用汇总报表"])
        writer.writerow([f"生成时间: {stats.get('generated_at', '')}"])
        writer.writerow([])

        # 今日汇总
        today = stats.get('today', {})
        writer.writerow(["今日统计 ( {})".format(today.get('date', ''))])
        writer.writerow(["总调用", "输入Token", "输出Token", "总Token", "总成本", "平均成本/次"])
        writer.writerow([
            today.get('total_calls', 0),
            today.get('total_input_tokens', 0),
            today.get('total_output_tokens', 0),
            today.get('total_tokens', 0),
            f"{today.get('total_cost', 0):.6f}",
            f"{today.get('avg_cost_per_call', 0):.6f}"
        ])
        writer.writerow([])

        # 本周汇总
        week = stats.get('this_week', {})
        writer.writerow(["本周统计 ( {} ~ {})".format(week.get('week_start', ''), week.get('week_end', ''))])
        writer.writerow(["总调用", "输入Token", "输出Token", "总Token", "总成本", "平均成本/次"])
        writer.writerow([
            week.get('total_calls', 0),
            week.get('total_input_tokens', 0),
            week.get('total_output_tokens', 0),
            week.get('total_tokens', 0),
            f"{week.get('total_cost', 0):.6f}",
            f"{week.get('avg_cost_per_call', 0):.6f}"
        ])
        writer.writerow([])

        # 本月汇总
        month = stats.get('this_month', {})
        writer.writerow(["本月统计 ( {})".format(month.get('month', ''))])
        writer.writerow(["总调用", "输入Token", "输出Token", "总Token", "总成本", "平均成本/次"])
        writer.writerow([
            month.get('total_calls', 0),
            month.get('total_input_tokens', 0),
            month.get('total_output_tokens', 0),
            month.get('total_tokens', 0),
            f"{month.get('total_cost', 0):.6f}",
            f"{month.get('avg_cost_per_call', 0):.6f}"
        ])

        return output


# 全局统计实例
_stats_instance: Optional[RouterStatistics] = None
_stats_lock = threading.Lock()


def get_router_statistics(db_instance: Optional[RouterDatabase] = None) -> RouterStatistics:
    """
    获取路由统计单例
    :param db_instance: 数据库实例（仅首次调用生效）
    :return: RouterStatistics实例
    """
    global _stats_instance
    with _stats_lock:
        if _stats_instance is None:
            _stats_instance = RouterStatistics(db_instance)
        return _stats_instance


def reset_router_statistics() -> None:
    """重置全局单例（用于测试）"""
    global _stats_instance
    with _stats_lock:
        _stats_instance = None
        logger.info("路由统计单例已重置")
