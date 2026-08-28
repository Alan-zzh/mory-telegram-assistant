# -*- coding: utf-8 -*-
"""
core/user_lifecycle.py · 用户生命周期管理

5 个阶段定义：
  New     - 入群 < 3 天（created_at 在 3 天内）
  Active  - 3 天内有互动（last_interaction 在 3 天内，且非 New）
  Silent  - 4-7 天无互动
  Churning - 8-30 天无互动
  Lost    - 30 天以上无互动

核心方法：
  sync_lifecycle_buckets()    - 扫描 user_profiles，更新每人的 lifecycle_stage
  get_users_by_stage(stage)   - 获取指定阶段用户列表
  get_lifecycle_distribution() - 返回各阶段用户数量统计
"""
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from core.logging_util import get_logger

logger = get_logger("user_lifecycle")

# 北京时间
_CST = timezone(timedelta(hours=8))

# 生命周期阶段枚举
STAGE_NEW = "New"
STAGE_ACTIVE = "Active"
STAGE_SILENT = "Silent"
STAGE_CHURNING = "Churning"
STAGE_LOST = "Lost"

ALL_STAGES = (STAGE_NEW, STAGE_ACTIVE, STAGE_SILENT, STAGE_CHURNING, STAGE_LOST)

# 阈值（秒）
_NEW_THRESHOLD_SEC = 3 * 86400       # 3 天
_ACTIVE_THRESHOLD_SEC = 3 * 86400    # 3 天内互动
_SILENT_THRESHOLD_SEC = 7 * 86400    # 7 天
_CHURNING_THRESHOLD_SEC = 30 * 86400  # 30 天


def classify_lifecycle_stage(created_at_ts, last_interaction_ts, now_ts):
    """
    根据创建时间和最后互动时间判定生命周期阶段。

    Args:
        created_at_ts: 用户创建时间戳（int/float 或 None）
        last_interaction_ts: 最后互动时间戳（int/float 或 None）
        now_ts: 当前时间戳

    Returns:
        str: 阶段枚举（New/Active/Silent/Churning/Lost）
    """
    age_sec = now_ts - (created_at_ts or now_ts)

    # 入群 < 3 天 → New
    if age_sec < _NEW_THRESHOLD_SEC:
        return STAGE_NEW

    # 有互动记录时按互动间隔分类
    if last_interaction_ts:
        idle_sec = now_ts - last_interaction_ts
        if idle_sec < _ACTIVE_THRESHOLD_SEC:
            return STAGE_ACTIVE
        elif idle_sec < _SILENT_THRESHOLD_SEC:
            return STAGE_SILENT
        elif idle_sec < _CHURNING_THRESHOLD_SEC:
            return STAGE_CHURNING
        else:
            return STAGE_LOST

    # 无互动记录：按入群时长归入沉默/流失
    if age_sec < _SILENT_THRESHOLD_SEC:
        return STAGE_SILENT
    elif age_sec < _CHURNING_THRESHOLD_SEC:
        return STAGE_CHURNING
    else:
        return STAGE_LOST


class UserLifecycleManager:
    """用户生命周期管理器，通过 db 实例访问数据库。"""

    def __init__(self, db):
        """
        Args:
            db: DB 实例（core.database.DB），通过 db.conn / db.lock 访问
        """
        self._db = db

    @property
    def conn(self) -> Any:
        return self._db.conn

    @property
    def lock(self):
        return self._db.lock

    def sync_lifecycle_buckets(self) -> dict:
        """
        扫描 user_profiles 表，更新每个用户的 lifecycle_stage 标签。

        Returns:
            dict: 各阶段用户数量 {"New": n, "Active": n, ...}
        """
        now_ts = int(time.time())
        distribution = {s: 0 for s in ALL_STAGES}

        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT user_id, created_at, last_interaction FROM user_profiles")
            rows = c.fetchall()

            for row in rows:
                user_id, created_at_raw, last_interaction_raw = row

                # 解析时间字段（支持 TIMESTAMP 字符串或 Unix 时间戳）
                created_at_ts = _parse_ts(created_at_raw)
                last_interaction_ts = _parse_ts(last_interaction_raw)

                stage = classify_lifecycle_stage(created_at_ts, last_interaction_ts, now_ts)
                distribution[stage] += 1

                c.execute(
                    "UPDATE user_profiles SET lifecycle_stage=? WHERE user_id=?",
                    (stage, user_id)
                )

            self.conn.commit()

        logger.info(f"用户生命周期同步完成: {distribution}")
        return distribution

    def get_users_by_stage(self, stage: str, limit: int = 200) -> list:
        """
        获取指定生命周期阶段的用户列表。

        Args:
            stage: 阶段枚举（New/Active/Silent/Churning/Lost）
            limit: 最大返回数量

        Returns:
            list[dict]: 用户列表，每项包含 user_id / last_interaction / lifecycle_stage
        """
        if stage not in ALL_STAGES:
            return []

        with self.lock:
            c = self.conn.cursor()
            c.execute(
                "SELECT user_id, last_interaction, lifecycle_stage FROM user_profiles "
                "WHERE lifecycle_stage=? ORDER BY last_interaction DESC LIMIT ?",
                (stage, limit)
            )
            rows = c.fetchall()

        return [
            {
                "user_id": r[0],
                "last_interaction": r[1],
                "lifecycle_stage": r[2] or stage,
            }
            for r in rows
        ]

    def get_lifecycle_distribution(self) -> dict:
        """
        返回各阶段用户数量统计（直接读已同步的标签，不触发重新计算）。

        Returns:
            dict: {"New": n, "Active": n, "Silent": n, "Churning": n, "Lost": n, "total": n}
        """
        with self.lock:
            c = self.conn.cursor()
            c.execute(
                "SELECT lifecycle_stage, COUNT(*) FROM user_profiles GROUP BY lifecycle_stage"
            )
            rows = c.fetchall()

        result = {s: 0 for s in ALL_STAGES}
        for row in rows:
            stage_name = row[0] or STAGE_NEW
            if stage_name in result:
                result[stage_name] = row[1]
            else:
                result[stage_name] = row[1]
        result["total"] = sum(result[s] for s in ALL_STAGES)
        return result


def _parse_ts(raw: Any) -> Optional[int]:
    """
    解析 user_profiles 中的时间字段。
    支持 Unix 时间戳（int/float）、ISO 格式字符串、SQLite CURRENT_TIMESTAMP 格式。
    返回 Unix 时间戳（int），解析失败返回 None。
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None
        # 尝试纯数字字符串
        try:
            return int(float(raw))
        except ValueError:
            pass
        # SQLite CURRENT_TIMESTAMP 格式: "2026-06-18 10:30:00"（UTC）
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(raw, fmt)
                # SQLite CURRENT_TIMESTAMP 是 UTC，需转北京时间再转时间戳
                dt = dt.replace(tzinfo=timezone.utc)
                return int(dt.timestamp())
            except ValueError:
                continue
    return None
