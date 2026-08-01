# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/db_migration_monitor.py  ·  DB 迁移时机指标监控（v5.24.0 阶段3-B）  ║
║                                                                            ║
║  功能：                                                                    ║
║    1. 检查 5 项数据库迁移触发指标（仅监控+告警，绝不自动迁移）            ║
║    2. 任一指标超阈值 → 调用 alert_bot.send_alert 推送警告                 ║
║    3. 提供 get_migration_status() 供 Dashboard API 实时查询               ║
║                                                                            ║
║  5 项指标（阈值来自 docs/technical/db-migration-blueprint.md + 任务要求）：║
║    A. max_write_qps_last_24h > 80      （从 write_queue 采样推算）         ║
║    B. sqlite_file_size_gb > 8.0        （os.path.getsize(mory.db)）        ║
║    C. average_write_queue_delay_seconds > 2.0（write_queue._stats 推算）   ║
║    D. write_queue_pending_often_gt_200 （采样统计，>30% 采样点 pending>200）║
║    E. read_connection_count > 50       （OS 级别进程计数，非 Linux 降级）  ║
║                                                                            ║
║  设计原则：                                                                ║
║    - 绝不做自动化迁移（只监控+告警）                                       ║
║    - 指标采集失败静默降级（返回 value=None, exceeded=False）              ║
║    - 采样数据线程安全（_samples_lock 保护 deque）                          ║
║    - 注释中文，变量名英文                                                  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import time
import threading
from collections import deque
from typing import Any

from core.logging_util import get_logger

logger = get_logger("db_migration_monitor")

# ── 阈值常量 ──────────────────────────────────────────────────────────────
# A: 单机持续写入并发峰值（Writes/sec > 80）
_THRESHOLD_MAX_WRITE_QPS = 80.0
# B: 数据库文件大小（任务要求 8.0 GB；蓝图原文 1 GB，以任务要求为准）
_THRESHOLD_DB_FILE_SIZE_GB = 8.0
# C: 平均写入队列延迟（秒）
_THRESHOLD_AVG_WQ_DELAY_SEC = 2.0
# D: WriteQueue 积压任务数阈值
_THRESHOLD_WQ_PENDING = 200
# D: "经常性"判定比例——采样中 pending>200 的占比超过此值视为经常性
_THRESHOLD_WQ_PENDING_RATIO = 0.3
# E: 并发读连接数
_THRESHOLD_READ_CONN_COUNT = 50

# ── 采样存储 ──────────────────────────────────────────────────────────────
# 保留最近 24h 的采样（每小时 1 次约 24 条，每分钟 1 次约 1440 条）
_SAMPLES_MAXLEN = 1440
_samples_lock = threading.Lock()
_samples: deque = deque(maxlen=_SAMPLES_MAXLEN)

# ── 告警消息模板 ──────────────────────────────────────────────────────────
_ALERT_MESSAGE = (
    "【DB迁移预警】系统当前写负载已接近单机 SQLite WAL 物理极限，"
    "建议执行 docs/technical/db-migration-blueprint.md 中的 5 阶段人工迁移方案。"
)


# ── 采样接口 ──────────────────────────────────────────────────────────────
def record_sample() -> None:
    """记录一次 WriteQueue 指标采样（供定时任务调用，检查函数内部也会调用）

    采样内容：(timestamp, write_queue total/success/failed/pending)
    用于推算 max_write_qps（指标 A）和 pending 频率（指标 D）。
    采集失败静默降级。
    """
    try:
        from core.write_queue import write_queue
        stats = write_queue.get_stats()
        with _samples_lock:
            _samples.append({
                "ts": time.time(),
                "total": stats.get("total", 0),
                "pending": stats.get("pending", 0),
                "success": stats.get("success", 0),
                "failed": stats.get("failed", 0),
            })
    except Exception as e:
        logger.debug(f"[record_sample] 采样失败（静默降级）: {e}")


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


# ── 5 项指标检查函数 ──────────────────────────────────────────────────────
def _check_max_write_qps_24h() -> dict:
    """指标 A: max_write_qps_last_24h > 80

    从采样数据推算：取最近 24h 内相邻采样的 (total差值 / 时间差值) 最大值。
    采样不足时返回 value=0, exceeded=False（静默降级）。
    """
    try:
        cutoff = time.time() - 86400  # 24h 前
        with _samples_lock:
            recent = [s for s in _samples if s["ts"] >= cutoff]

        if len(recent) < 2:
            return {
                "value": 0.0,
                "threshold": _THRESHOLD_MAX_WRITE_QPS,
                "exceeded": False,
                "message": "采样数据不足（<2 条），无法计算 max_write_qps",
            }

        max_qps = 0.0
        for i in range(1, len(recent)):
            dt = recent[i]["ts"] - recent[i - 1]["ts"]
            if dt <= 0:
                continue
            d_total = recent[i]["total"] - recent[i - 1]["total"]
            if d_total > 0:
                qps = d_total / dt
                if qps > max_qps:
                    max_qps = qps

        exceeded = max_qps > _THRESHOLD_MAX_WRITE_QPS
        return {
            "value": round(max_qps, 2),
            "threshold": _THRESHOLD_MAX_WRITE_QPS,
            "exceeded": exceeded,
            "message": (
                f"最近 24h 最大写入 QPS = {max_qps:.2f}/s"
                + ("（已超阈值）" if exceeded else "")
            ),
        }
    except Exception as e:
        logger.debug(f"[_check_max_write_qps_24h] 采集失败: {e}")
        return {
            "value": None,
            "threshold": _THRESHOLD_MAX_WRITE_QPS,
            "exceeded": False,
            "message": f"采集失败: {type(e).__name__}",
        }


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


def _check_avg_write_queue_delay() -> dict:
    """指标 C: average_write_queue_delay_seconds > 2.0

    推算方法：avg_delay = pending / throughput_rate
    其中 throughput_rate 从最近两个采样点的 success 差值/时间差值推算。
    采样不足或吞吐为 0 时返回 value=0（静默降级）。
    """
    try:
        from core.write_queue import write_queue
        stats = write_queue.get_stats()
        pending = stats.get("pending", 0)

        with _samples_lock:
            recent = list(_samples)

        if len(recent) >= 2:
            # 用最近两个采样点推算吞吐率
            dt = recent[-1]["ts"] - recent[-2]["ts"]
            d_success = recent[-1]["success"] - recent[-2]["success"]
            if dt > 0 and d_success >= 0:
                throughput = d_success / dt  # 每秒处理数
                if throughput > 0:
                    avg_delay = pending / throughput
                else:
                    # 两次低频采样之间没有完成写入时，无法从一个 pending 瞬时值
                    # 推算等待时长。旧逻辑直接记 999 秒，会把刚入队的一条写入
                    # 误报成“SQLite 已到物理极限”。持续积压由指标 D 单独判断。
                    return {
                        "value": None,
                        "threshold": _THRESHOLD_AVG_WQ_DELAY_SEC,
                        "exceeded": False,
                        "message": (
                            "最近采样吞吐为 0，无法推算平均延迟"
                            f"（current_pending={pending}，交由持续积压指标判断）"
                        ),
                    }
            else:
                avg_delay = 0.0
        else:
            # 采样不足，无法推算吞吐
            avg_delay = 0.0

        avg_delay_display = round(avg_delay, 3)

        exceeded = avg_delay > _THRESHOLD_AVG_WQ_DELAY_SEC
        return {
            "value": avg_delay_display,
            "threshold": _THRESHOLD_AVG_WQ_DELAY_SEC,
            "exceeded": exceeded,
            "message": (
                f"平均写入队列延迟 ≈ {avg_delay_display}s (pending={pending})"
                + ("（已超阈值）" if exceeded else "")
            ),
        }
    except Exception as e:
        logger.debug(f"[_check_avg_write_queue_delay] 采集失败: {e}")
        return {
            "value": None,
            "threshold": _THRESHOLD_AVG_WQ_DELAY_SEC,
            "exceeded": False,
            "message": f"采集失败: {type(e).__name__}",
        }


def _check_pending_often_gt_200() -> dict:
    """指标 D: write_queue_pending_often_gt_200

    从采样数据统计：最近 24h 内 pending > 200 的采样占比 > 30% 视为"经常性"。
    采样不足时返回 exceeded=False（静默降级）。
    """
    try:
        cutoff = time.time() - 86400
        with _samples_lock:
            recent = [s for s in _samples if s["ts"] >= cutoff]

        if not recent:
            return {
                "value": {
                    "over_threshold_ratio": 0.0,
                    "over_count": 0,
                    "total_samples": 0,
                    "current_pending": 0,
                },
                "threshold": _THRESHOLD_WQ_PENDING,
                "exceeded": False,
                "message": "采样数据不足，无法判断 pending 频率",
            }

        over_count = sum(1 for s in recent if s["pending"] > _THRESHOLD_WQ_PENDING)
        ratio = over_count / len(recent)
        often = ratio > _THRESHOLD_WQ_PENDING_RATIO

        return {
            "value": {
                "over_threshold_ratio": round(ratio, 3),
                "over_count": over_count,
                "total_samples": len(recent),
                "current_pending": recent[-1]["pending"],
            },
            "threshold": _THRESHOLD_WQ_PENDING,
            "exceeded": often,
            "message": (
                f"最近 24h {over_count}/{len(recent)} 次采样 "
                f"pending>{_THRESHOLD_WQ_PENDING} ({ratio * 100:.1f}%)"
                + ("（经常性超阈值）" if often else "")
            ),
        }
    except Exception as e:
        logger.debug(f"[_check_pending_often_gt_200] 采集失败: {e}")
        return {
            "value": None,
            "threshold": _THRESHOLD_WQ_PENDING,
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


# ── 主检查接口 ────────────────────────────────────────────────────────────
def check_migration_indicators(db_conn) -> dict:
    """检查 5 项数据库迁移时机指标

    任一指标超阈值时，自动调用 alert_bot.send_alert 推送警告。

    Args:
        db_conn: DB 对象 / 原始 sqlite3 连接

    Returns:
        {indicator_name: {value, threshold, exceeded, message}}
    """
    # 先记录一次采样（确保当前数据被纳入）
    record_sample()

    db_file = _get_db_file_path(db_conn)

    indicators = {
        "max_write_qps_last_24h": _check_max_write_qps_24h(),
        "sqlite_file_size_gb": _check_db_file_size_gb(db_file),
        "average_write_queue_delay_seconds": _check_avg_write_queue_delay(),
        "write_queue_pending_often_gt_200": _check_pending_often_gt_200(),
        "read_connection_count": _check_read_connection_count(db_file),
    }

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
    - 仍会记录采样，确保数据连续性

    Args:
        db_conn: DB 对象 / 原始 sqlite3 连接

    Returns:
        {ok, indicators, exceeded_count, exceeded_list, db_file, ts}
    """
    # 记录采样
    record_sample()

    db_file = _get_db_file_path(db_conn)

    indicators = {
        "max_write_qps_last_24h": _check_max_write_qps_24h(),
        "sqlite_file_size_gb": _check_db_file_size_gb(db_file),
        "average_write_queue_delay_seconds": _check_avg_write_queue_delay(),
        "write_queue_pending_often_gt_200": _check_pending_often_gt_200(),
        "read_connection_count": _check_read_connection_count(db_file),
    }

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
