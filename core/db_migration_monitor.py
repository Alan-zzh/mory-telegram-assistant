# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/db_migration_monitor.py  ·  DB 迁移时机指标监控（v5.24.0 阶段3-B）  ║
║                                                                            ║
║  功能：                                                                    ║
║    1. 检查数据库迁移触发指标（仅监控+告警，绝不自动迁移）                  ║
║    2. 任一指标超阈值 → 调用 alert_bot.send_alert 推送警告                 ║
║    3. 提供 get_migration_status() 供 Dashboard API 实时查询               ║
║                                                                            ║
║  指标（阈值来自 docs/technical/db-migration-blueprint.md + 任务要求）：    ║
║    B. sqlite_file_size_gb > 8.0        （os.path.getsize(mory.db)）        ║
║    E. read_connection_count > 50       （OS 级别进程计数，非 Linux 降级）  ║
║                                                                            ║
║  历史（v5.41.0）：原指标 A/C/D 依赖 write_queue 写队列采样；               ║
║  写队列已于 v5.32 空壳化并于本版删除，三项死指标随之移除。                 ║
║  SQLite 写负载如需观测，以 task_execution_history 与 WAL checkpoint        ║
║  尺寸为准（见 docs/technical/db-migration-blueprint.md）。                ║
║                                                                            ║
║  设计原则：                                                                ║
║    - 绝不做自动化迁移（只监控+告警）                                       ║
║    - 指标采集失败静默降级（返回 value=None, exceeded=False）              ║
║    - 注释中文，变量名英文                                                  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import time
from typing import Any

from core.logging_util import get_logger

logger = get_logger("db_migration_monitor")

# ── 阈值常量 ──────────────────────────────────────────────────────────────
# B: 数据库文件大小（任务要求 8.0 GB；蓝图原文 1 GB，以任务要求为准）
_THRESHOLD_DB_FILE_SIZE_GB = 8.0
# E: 并发读连接数
_THRESHOLD_READ_CONN_COUNT = 50

# ── 告警消息模板 ──────────────────────────────────────────────────────────
_ALERT_MESSAGE = (
    "【DB迁移预警】系统当前写负载已接近单机 SQLite WAL 物理极限，"
    "建议执行 docs/technical/db-migration-blueprint.md 中的 5 阶段人工迁移方案。"
)


# ── 连接/路径辅助 ─────────────────────────────────────────────────────────
def _get_real_conn(db_conn) -> Any:
    """解包连接代理，获取真实 sqlite3 连接

    支持两种输入：
    - DB 对象（core/database.py）：有 _real_conn 属性（v5.32.0 起等同 self.conn）
    - 原始 sqlite3.Connection：直接返回
    """
    # DB 对象：有 _real_conn 属性（v5.32.0 移除 WriteQueueConnectionProxy 后保留的兼容引用）
    real = getattr(db_conn, "_real_conn", None)
    if real is not None:
        return real
    # 原始 sqlite3 连接
    return db_conn


def _get_db_file_path(db_conn) -> str:
    """获取数据库文件路径

    优先级：
    1. DB 对象的 db_file 属性
    2. PRAGMA database_list 查询结果
    3. 项目根目录 mory.db 回退
    """
    # DB 对象：有 db_file 属性
    db_file = getattr(db_conn, "db_file", None)
    if db_file:
        return db_file
    # 尝试从连接获取
    try:
        real = _get_real_conn(db_conn)
        row = real.execute("PRAGMA database_list").fetchone()
        if row and row[2]:
            return row[2]
    except Exception as e:
        logger.debug(f"PRAGMA database_list 失败，回退默认路径: {e}")
    # 回退到项目根目录的 mory.db
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "mory.db",
    )


# ── 指标检查函数 ──────────────────────────────────────────────────────────
def _check_db_file_size_gb(db_file: str) -> dict:
    """指标 B: sqlite_file_size_gb > 8.0

    直接 os.path.getsize 获取文件大小，转换为 GB。
    """
    try:
        size_bytes = os.path.getsize(db_file)
        size_gb = size_bytes / (1024 ** 3)
        exceeded = size_gb > _THRESHOLD_DB_FILE_SIZE_GB
        return {
            "value": round(size_gb, 3),
            "threshold": _THRESHOLD_DB_FILE_SIZE_GB,
            "exceeded": exceeded,
            "message": (
                f"mory.db 文件大小 = {size_gb:.3f} GB"
                + ("（已超阈值）" if exceeded else "")
            ),
        }
    except Exception as e:
        logger.debug(f"[_check_db_file_size_gb] 采集失败: {e}")
        return {
            "value": None,
            "threshold": _THRESHOLD_DB_FILE_SIZE_GB,
            "exceeded": False,
            "message": f"采集失败: {type(e).__name__}",
        }


def _check_read_connection_count(db_file: str) -> dict:
    """指标 E: read_connection_count > 50

    SQLite 无原生连接计数，使用 OS 级别工具估算：
    - Linux: fuser 统计持有 db 文件的进程数
    - 非 Linux: 静默降级返回 0
    采集失败静默降级。
    """
    try:
        import sys
        if not sys.platform.startswith("linux"):
            return {
                "value": 0,
                "threshold": _THRESHOLD_READ_CONN_COUNT,
                "exceeded": False,
                "message": "非 Linux 环境，连接数采集降级为 0",
            }

        import subprocess
        # 用 fuser 统计持有 db 文件的进程 PID
        result = subprocess.run(
            ["fuser", db_file],
            capture_output=True, text=True, timeout=5,
        )
        # fuser 输出格式："<db_file>:  <pid1> <pid2> ..."
        tokens = result.stdout.strip().split()
        conn_count = 0
        for token in tokens:
            # 跳过文件名本身
            if token.endswith(".db") or token.endswith(".db-journal") or token.endswith(".db-wal"):
                continue
            # PID 可能带后缀（如 e/f/c），取前导数字
            num = ""
            for ch in token:
                if ch.isdigit():
                    num += ch
                else:
                    break
            if num:
                conn_count += 1

        exceeded = conn_count > _THRESHOLD_READ_CONN_COUNT
        return {
            "value": conn_count,
            "threshold": _THRESHOLD_READ_CONN_COUNT,
            "exceeded": exceeded,
            "message": (
                f"当前持有 db 文件的进程数 = {conn_count}"
                + ("（已超阈值）" if exceeded else "")
            ),
        }
    except Exception as e:
        logger.debug(f"[_check_read_connection_count] 采集失败（静默降级）: {e}")
        return {
            "value": 0,
            "threshold": _THRESHOLD_READ_CONN_COUNT,
            "exceeded": False,
            "message": f"采集失败，降级为 0: {type(e).__name__}",
        }


def _collect_indicators(db_file: str) -> dict:
    """组装当前全部迁移指标（check 与 status 共用）"""
    return {
        "sqlite_file_size_gb": _check_db_file_size_gb(db_file),
        "read_connection_count": _check_read_connection_count(db_file),
    }


# ── 主检查接口 ────────────────────────────────────────────────────────────
def check_migration_indicators(db_conn) -> dict:
    """检查数据库迁移时机指标

    任一指标超阈值时，自动调用 alert_bot.send_alert 推送警告。

    Args:
        db_conn: DB 对象 / 原始 sqlite3 连接

    Returns:
        {indicator_name: {value, threshold, exceeded, message}}
    """
    db_file = _get_db_file_path(db_conn)

    indicators = _collect_indicators(db_file)

    # 任一指标超阈值 → 推送告警
    exceeded_list = [
        name for name, info in indicators.items() if info.get("exceeded")
    ]
    if exceeded_list:
        try:
            from core.alert_bot import send_alert
            # 构造告警上下文（不含敏感信息）
            context = {
                "exceeded_indicators": exceeded_list,
                "all_indicators": {
                    k: {
                        "value": v.get("value"),
                        "threshold": v.get("threshold"),
                        "message": v.get("message"),
                    }
                    for k, v in indicators.items()
                },
                "db_file": db_file,
            }
            send_alert(
                level="WARNING",
                title="DB迁移时机预警",
                message=_ALERT_MESSAGE,
                context=context,
            )
            logger.warning(f"[DB迁移预警] 超阈值指标: {exceeded_list}")
        except Exception as e:
            logger.error(f"[check_migration_indicators] 告警发送失败: {e}")

    return indicators


def get_migration_status(db_conn) -> dict:
    """获取迁移指标状态（供 Dashboard API 调用，不触发告警）

    与 check_migration_indicators 的区别：
    - 本函数不发送告警（避免 Dashboard 查询触发告警风暴）

    Args:
        db_conn: DB 对象 / 原始 sqlite3 连接

    Returns:
        {ok, indicators, exceeded_count, exceeded_list, db_file, ts}
    """
    db_file = _get_db_file_path(db_conn)

    indicators = _collect_indicators(db_file)

    exceeded_count = sum(
        1 for info in indicators.values() if info.get("exceeded")
    )

    return {
        "ok": True,
        "indicators": indicators,
        "exceeded_count": exceeded_count,
        "exceeded_list": [
            k for k, v in indicators.items() if v.get("exceeded")
        ],
        "db_file": db_file,
        "ts": int(time.time()),
    }
