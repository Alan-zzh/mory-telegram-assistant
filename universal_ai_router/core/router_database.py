# 项目：universal_ai_router | 版本：v1.0.0 | 日期：2026-04-23 | 功能：路由数据库模块
"""
路由数据库模块 - 负责记录和查询AI模型调用产生的Token使用量
"""

import sqlite3
import threading
import os
import logging
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class RouterDatabase:
    """路由数据库类 - 管理AI模型调用记录"""

    _local = threading.local()

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化数据库连接
        :param db_path: 数据库文件路径，默认在 universal_ai_router/data/router_usage.db
        """
        if db_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(base_dir, "data", "router_usage.db")

        self.db_path = db_path
        self._ensure_directory()
        self._init_database()
        logger.info(f"路由数据库初始化完成: {self.db_path}")

    def _ensure_directory(self) -> None:
        """确保数据库目录存在"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

    def close(self):
        """关闭线程本地数据库连接，释放资源"""
        if hasattr(self._local, 'connection') and self._local.connection is not None:
            try:
                self._local.connection.close()
                self._local.connection = None
            except Exception as e:
                logger.warning(f"关闭路由数据库连接异常: {e}")

    def __del__(self):
        """析构时自动关闭连接"""
        self.close()

    @contextmanager
    def _get_connection(self):
        """
        获取线程安全的数据库连接
        :yield: sqlite3.Connection
        """
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0
            )
            self._local.connection.row_factory = sqlite3.Row
            self._local.connection.execute("PRAGMA journal_mode=WAL")
            self._local.connection.execute("PRAGMA busy_timeout=30000")

        try:
            yield self._local.connection
        except Exception as e:
            self._local.connection.rollback()
            raise e

    def _init_database(self) -> None:
        """初始化数据库表结构"""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            provider TEXT NOT NULL,
            model_name TEXT NOT NULL,
            account_name TEXT NOT NULL,
            task_type TEXT NOT NULL,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cost REAL DEFAULT 0.0,
            success INTEGER DEFAULT 1,
            error_message TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_token_usage_timestamp ON token_usage(timestamp);
        CREATE INDEX IF NOT EXISTS idx_token_usage_provider ON token_usage(provider);
        CREATE INDEX IF NOT EXISTS idx_token_usage_model ON token_usage(model_name);
        CREATE INDEX IF NOT EXISTS idx_token_usage_account ON token_usage(account_name);
        CREATE INDEX IF NOT EXISTS idx_token_usage_task_type ON token_usage(task_type);
        CREATE INDEX IF NOT EXISTS idx_token_usage_date ON token_usage(substr(timestamp, 1, 10));
        """

        with self._get_connection() as conn:
            conn.executescript(create_table_sql)
            conn.commit()

        logger.info("数据库表结构初始化完成")

    def record_usage(
        self,
        provider: str,
        model: str,
        account: str,
        task_type: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost: float = 0.0,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> Optional[int]:
        """
        记录一次Token使用
        :param provider: API来源（如 qwen/openai/anthropic）
        :param model: 模型名称
        :param account: 账号名称
        :param task_type: 任务类型（text/image/audio/video/embedding）
        :param input_tokens: 输入Token数
        :param output_tokens: 输出Token数
        :param cost: 成本
        :param success: 是否成功
        :param error_message: 错误信息（可选）
        :return: 记录ID或None
        """
        timestamp = datetime.now().isoformat()
        total_tokens = input_tokens + output_tokens

        insert_sql = """
        INSERT INTO token_usage
        (timestamp, provider, model_name, account_name, task_type,
         input_tokens, output_tokens, total_tokens, cost, success, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(insert_sql, (
                    timestamp, provider, model, account, task_type,
                    input_tokens, output_tokens, total_tokens, cost,
                    1 if success else 0, error_message
                ))
                conn.commit()
                record_id = cursor.lastrowid
                logger.debug(f"记录Token使用: {model} | 输入:{input_tokens} | 输出:{output_tokens} | 成本:{cost}")
                return record_id
        except Exception as e:
            logger.error(f"记录Token使用失败: {e}")
            return None

    def get_usage_by_model(self, model_name: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        按模型名称查询使用记录
        :param model_name: 模型名称
        :param limit: 返回记录数限制
        :return: 使用记录列表
        """
        query_sql = """
        SELECT * FROM token_usage
        WHERE model_name = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(query_sql, (model_name, limit))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"查询模型使用记录失败: {e}")
            return []

    def get_usage_by_provider(self, provider: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        按提供者查询使用记录
        :param provider: 提供者名称
        :param limit: 返回记录数限制
        :return: 使用记录列表
        """
        query_sql = """
        SELECT * FROM token_usage
        WHERE provider = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(query_sql, (provider, limit))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"查询提供者使用记录失败: {e}")
            return []

    def get_usage_by_date(self, start_date: str, end_date: str, limit: int = 1000) -> List[Dict[str, Any]]:
        """
        按日期范围查询使用记录
        :param start_date: 开始日期（YYYY-MM-DD格式）
        :param end_date: 结束日期（YYYY-MM-DD格式）
        :param limit: 返回记录数限制
        :return: 使用记录列表
        """
        query_sql = """
        SELECT * FROM token_usage
        WHERE substr(timestamp, 1, 10) >= ? AND substr(timestamp, 1, 10) <= ?
        ORDER BY timestamp DESC
        LIMIT ?
        """

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(query_sql, (start_date, end_date, limit))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"查询日期范围使用记录失败: {e}")
            return []

    def get_daily_usage(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        获取指定日期的使用统计
        :param target_date: 目标日期（YYYY-MM-DD格式），默认今天
        :return: 统计结果字典
        """
        if target_date is None:
            target_date = date.today().isoformat()

        query_sql = """
        SELECT
            COUNT(*) as total_calls,
            SUM(input_tokens) as total_input_tokens,
            SUM(output_tokens) as total_output_tokens,
            SUM(total_tokens) as total_tokens,
            SUM(cost) as total_cost,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failure_count
        FROM token_usage
        WHERE substr(timestamp, 1, 10) = ?
        """

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(query_sql, (target_date,))
                row = cursor.fetchone()
                if row:
                    result = dict(row)
                    result['date'] = target_date
                    result['avg_cost_per_call'] = result['total_cost'] / result['total_calls'] if result['total_calls'] > 0 else 0
                    return result
                return {}
        except Exception as e:
            logger.error(f"查询每日使用统计失败: {e}")
            return {}

    def get_weekly_usage(self, week_start_date: str) -> Dict[str, Any]:
        """
        获取指定周的使用统计（周一到周日）
        :param week_start_date: 周起始日期（周一，YYYY-MM-DD格式）
        :return: 统计结果字典
        """
        from datetime import timedelta
        week_end_date = (datetime.strptime(week_start_date, "%Y-%m-%d") + timedelta(days=6)).strftime("%Y-%m-%d")

        query_sql = """
        SELECT
            COUNT(*) as total_calls,
            SUM(input_tokens) as total_input_tokens,
            SUM(output_tokens) as total_output_tokens,
            SUM(total_tokens) as total_tokens,
            SUM(cost) as total_cost,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failure_count
        FROM token_usage
        WHERE substr(timestamp, 1, 10) >= ? AND substr(timestamp, 1, 10) <= ?
        """

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(query_sql, (week_start_date, week_end_date))
                row = cursor.fetchone()
                if row:
                    result = dict(row)
                    result['week_start'] = week_start_date
                    result['week_end'] = week_end_date
                    result['avg_cost_per_call'] = result['total_cost'] / result['total_calls'] if result['total_calls'] > 0 else 0
                    return result
                return {}
        except Exception as e:
            logger.error(f"查询每周使用统计失败: {e}")
            return {}

    def get_monthly_usage(self, month: Optional[str] = None) -> Dict[str, Any]:
        """
        获取指定月份的使用统计
        :param month: 月份（YYYY-MM格式），默认当前月份
        :return: 统计结果字典
        """
        if month is None:
            month = date.today().strftime("%Y-%m")

        query_sql = """
        SELECT
            COUNT(*) as total_calls,
            SUM(input_tokens) as total_input_tokens,
            SUM(output_tokens) as total_output_tokens,
            SUM(total_tokens) as total_tokens,
            SUM(cost) as total_cost,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failure_count
        FROM token_usage
        WHERE substr(timestamp, 1, 7) = ?
        """

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(query_sql, (month,))
                row = cursor.fetchone()
                if row:
                    result = dict(row)
                    result['month'] = month
                    result['avg_cost_per_call'] = result['total_cost'] / result['total_calls'] if result['total_calls'] > 0 else 0
                    return result
                return {}
        except Exception as e:
            logger.error(f"查询每月使用统计失败: {e}")
            return {}

    def get_provider_summary(self) -> List[Dict[str, Any]]:
        """
        获取各提供者的汇总统计
        :return: 各提供者统计列表
        """
        query_sql = """
        SELECT
            provider,
            COUNT(*) as total_calls,
            SUM(input_tokens) as total_input_tokens,
            SUM(output_tokens) as total_output_tokens,
            SUM(total_tokens) as total_tokens,
            SUM(cost) as total_cost,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failure_count
        FROM token_usage
        GROUP BY provider
        ORDER BY total_cost DESC
        """

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(query_sql)
                rows = cursor.fetchall()
                result = []
                for row in rows:
                    item = dict(row)
                    item['avg_cost_per_call'] = item['total_cost'] / item['total_calls'] if item['total_calls'] > 0 else 0
                    item['success_rate'] = item['success_count'] / item['total_calls'] * 100 if item['total_calls'] > 0 else 0
                    result.append(item)
                return result
        except Exception as e:
            logger.error(f"查询提供者汇总失败: {e}")
            return []

    def get_model_summary(self) -> List[Dict[str, Any]]:
        """
        获取各模型的汇总统计
        :return: 各模型统计列表
        """
        query_sql = """
        SELECT
            provider,
            model_name,
            COUNT(*) as total_calls,
            SUM(input_tokens) as total_input_tokens,
            SUM(output_tokens) as total_output_tokens,
            SUM(total_tokens) as total_tokens,
            SUM(cost) as total_cost,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failure_count
        FROM token_usage
        GROUP BY provider, model_name
        ORDER BY total_cost DESC
        """

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(query_sql)
                rows = cursor.fetchall()
                result = []
                for row in rows:
                    item = dict(row)
                    item['avg_cost_per_call'] = item['total_cost'] / item['total_calls'] if item['total_calls'] > 0 else 0
                    item['success_rate'] = item['success_count'] / item['total_calls'] * 100 if item['total_calls'] > 0 else 0
                    result.append(item)
                return result
        except Exception as e:
            logger.error(f"查询模型汇总失败: {e}")
            return []

    def get_account_summary(self) -> List[Dict[str, Any]]:
        """
        获取各账号的汇总统计
        :return: 各账号统计列表
        """
        query_sql = """
        SELECT
            provider,
            account_name,
            COUNT(*) as total_calls,
            SUM(input_tokens) as total_input_tokens,
            SUM(output_tokens) as total_output_tokens,
            SUM(total_tokens) as total_tokens,
            SUM(cost) as total_cost,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failure_count
        FROM token_usage
        GROUP BY provider, account_name
        ORDER BY total_cost DESC
        """

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(query_sql)
                rows = cursor.fetchall()
                result = []
                for row in rows:
                    item = dict(row)
                    item['avg_cost_per_call'] = item['total_cost'] / item['total_calls'] if item['total_calls'] > 0 else 0
                    item['success_rate'] = item['success_count'] / item['total_calls'] * 100 if item['total_calls'] > 0 else 0
                    result.append(item)
                return result
        except Exception as e:
            logger.error(f"查询账号汇总失败: {e}")
            return []

    def cleanup_old_records(self, days: int = 90) -> int:
        """
        清理旧的使用记录
        :param days: 保留最近N天的记录
        :return: 删除的记录数
        """
        from datetime import timedelta
        cutoff_date = (date.today() - timedelta(days=days)).isoformat()

        delete_sql = "DELETE FROM token_usage WHERE substr(timestamp, 1, 10) < ?"

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(delete_sql, (cutoff_date,))
                conn.commit()
                deleted = cursor.rowcount
                if deleted > 0:
                    logger.info(f"清理了 {deleted} 条超过 {days} 天的使用记录")
                return deleted
        except Exception as e:
            logger.error(f"清理旧记录失败: {e}")
            return 0


# 全局数据库实例
_db_instance: Optional[RouterDatabase] = None
_db_lock = threading.Lock()


def get_router_database(db_path: Optional[str] = None) -> RouterDatabase:
    """
    获取路由数据库单例
    :param db_path: 数据库路径（仅首次调用生效）
    :return: RouterDatabase实例
    """
    global _db_instance
    with _db_lock:
        if _db_instance is None:
            _db_instance = RouterDatabase(db_path)
        return _db_instance


def reset_router_database() -> None:
    """重置全局单例（用于测试）"""
    global _db_instance
    with _db_lock:
        _db_instance = None
        logger.info("路由数据库单例已重置")
