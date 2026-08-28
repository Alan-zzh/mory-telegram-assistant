# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/shared_db.py  ·  多 Bot 共享数据层（v5.23.0 P3-8）                  ║
║                                                                            ║
║  功能：                                                                    ║
║    通过 SQLite ATTACH DATABASE 机制，让 mory 和 mory-media 两个 Bot        ║
║    共享 user_profiles 和 conversion_events 两张表，实现跨 Bot 用户画像     ║
║    和转化状态共享。                                                        ║
║                                                                            ║
║  设计原则：                                                                ║
║    - 不合并数据库（保持各 Bot 独立性）                                     ║
║    - 只共享业务关键表（user_profiles + conversion_events）                 ║
║    - ATTACH 是只读挂载，写入通过专用连接                                   ║
║    - 失败静默降级，不影响主流程                                            ║
║                                                                            ║
║  使用：                                                                    ║
║    from core.shared_db import get_shared_profile, save_shared_profile      ║
║    profile = get_shared_profile(uid)                                       ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone, timedelta

from core.logging_util import get_logger

logger = get_logger("shared_db")

_CST = timezone(timedelta(hours=8))

# 共享数据库路径（默认 mory.db，media Bot 通过环境变量指向）
_SHARED_DB_PATH = None
_shared_conn = None
_shared_lock = threading.Lock()


def _get_shared_db_path() -> str:
    """获取共享数据库路径"""
    global _SHARED_DB_PATH
    if _SHARED_DB_PATH:
        return _SHARED_DB_PATH

    # 默认共享主 Bot 的 mory.db
    # media Bot 通过环境变量 SHARED_DB_PATH 指向主 Bot 的 mory.db
    path = os.environ.get("SHARED_DB_PATH", "")
    if not path:
        # 回退：默认 mory.db
        mory_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(mory_root, "mory.db")
    _SHARED_DB_PATH = path
    return path


def _get_shared_conn():
    """获取共享数据库连接（单例）"""
    global _shared_conn
    if _shared_conn:
        return _shared_conn

    with _shared_lock:
        if _shared_conn:
            return _shared_conn
        try:
            db_path = _get_shared_db_path()
            if not os.path.exists(db_path):
                logger.warning(f"共享数据库不存在: {db_path}")
                return None

            conn = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            _shared_conn = conn
            logger.info(f"✅ 共享数据库连接已建立: {db_path}")
            # schema 只由 core.database/Alembic 管理；共享连接仅验证所需列。
            ensure_version_column(conn)
            return conn
        except Exception as e:
            logger.warning(f"共享数据库连接失败（降级为独立模式）: {e}")
            return None


def ensure_version_column(conn=None) -> bool:
    """确认中央 schema 已提供 user_profiles 乐观锁所需列。

    历史版本会在此函数内建表/补列，导致共享 Bot 连接可绕过主数据库的
    schema 管理。旧库应先运行 Alembic 或由主 Bot 的 DB 初始化升级。

    Returns:
        True 成功，False 失败
    """
    try:
        if conn is None:
            conn = _get_shared_conn()
            if not conn:
                return False

        col_names = {row[1] for row in conn.execute("PRAGMA table_info(user_profiles)").fetchall()}
        required = {
            "user_id", "tags", "level", "interests", "last_interaction",
            "conversation_rounds", "activity_score", "flirt_affinity",
            "spend_tendency", "resistance_idx", "peak_hours", "persona_tags",
            "memory_summary", "version", "updated_at",
        }
        missing = required - col_names
        if missing:
            logger.warning("共享 user_profiles schema 缺列 %s；请先运行数据库初始化/迁移", sorted(missing))
            return False
        return True
    except Exception as e:
        logger.warning(f"ensure_version_column 失败: {e}")
        return False


def _ensure_funnel_state_schema(conn) -> bool:
    """确认中央 schema 已提供多 Bot 漏斗状态表。"""
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(funnel_state)").fetchall()}
        required = {"uid", "state", "state_ts", "version", "recovery_stage", "recovery_ts", "bot_id"}
        if not required.issubset(cols):
            logger.warning("共享 funnel_state schema 未就绪；请先运行数据库初始化/迁移")
            return False
        return True
    except Exception as e:
        logger.warning("检查共享 funnel_state schema 失败: %s", e)
        return False


def _merge_profiles(remote_row, local_profile: dict) -> dict:
    """合并远端与本地 profile（乐观锁冲突重试时使用）

    合并策略（v5.24.0 阶段2-A）：
    - tags / interests / persona_tags：取并集（去重）
    - activity_score / flirt_affinity / spend_tendency / resistance_idx：取平均值
    - memory_summary：本地优先（当前 Bot 刚生成），本地为空则取远端
    - 其他字段（level / last_interaction / conversation_rounds / peak_hours）：取本地（Last-Write-Wins）

    Args:
        remote_row: sqlite3.Row，远端最新记录（含 version/tags/interests/persona_tags/
                    activity_score/flirt_affinity/spend_tendency/resistance_idx/memory_summary）
        local_profile: dict，本地待写入的 profile

    Returns:
        合并后的 profile dict
    """
    import json

    def _parse_json(v):
        if not v:
            return []
        try:
            return json.loads(v)
        except Exception:
            return []

    # 解析远端 JSON 字段
    remote_tags = _parse_json(remote_row["tags"])
    remote_interests = _parse_json(remote_row["interests"])
    remote_persona_tags = _parse_json(remote_row["persona_tags"])
    # 远端数值字段
    remote_activity = remote_row["activity_score"] or 0.0
    remote_flirt = remote_row["flirt_affinity"] or 0.0
    remote_spend = remote_row["spend_tendency"] or 0.0
    remote_resistance = remote_row["resistance_idx"]
    if remote_resistance is None:
        remote_resistance = 0.5
    remote_memory = remote_row["memory_summary"] or ""

    # 合并：列表取并集（保留顺序：远端在前，本地新增追加）
    local_tags = local_profile.get("tags", []) or []
    local_interests = local_profile.get("interests", []) or []
    local_persona_tags = local_profile.get("persona_tags", []) or []
    merged_tags = list(dict.fromkeys(remote_tags + local_tags))
    merged_interests = list(dict.fromkeys(remote_interests + local_interests))
    merged_persona_tags = list(dict.fromkeys(remote_persona_tags + local_persona_tags))

    # 合并：数值取平均值
    local_activity = local_profile.get("activity_score", 0.0) or 0.0
    local_flirt = local_profile.get("flirt_affinity", 0.0) or 0.0
    local_spend = local_profile.get("spend_tendency", 0.0) or 0.0
    local_resistance = local_profile.get("resistance_idx", 0.5)
    if local_resistance is None:
        local_resistance = 0.5
    merged_activity = (remote_activity + local_activity) / 2.0
    merged_flirt = (remote_flirt + local_flirt) / 2.0
    merged_spend = (remote_spend + local_spend) / 2.0
    merged_resistance = (remote_resistance + local_resistance) / 2.0

    # memory_summary：本地优先（当前 Bot 刚生成更新），本地为空则取远端
    local_memory = local_profile.get("memory_summary", "") or ""
    merged_memory = local_memory if local_memory else remote_memory

    # 以本地为基础（Last-Write-Wins 字段保留本地值），覆盖合并字段
    merged = dict(local_profile)
    merged.update({
        "tags": merged_tags,
        "interests": merged_interests,
        "persona_tags": merged_persona_tags,
        "activity_score": merged_activity,
        "flirt_affinity": merged_flirt,
        "spend_tendency": merged_spend,
        "resistance_idx": merged_resistance,
        "memory_summary": merged_memory,
    })
    return merged


def get_shared_profile(uid: int) -> dict:
    """获取共享用户画像

    从共享数据库（主 Bot 的 mory.db）读取用户画像，
    让 media Bot 也能感知用户在主 Bot 的画像数据。

    Returns:
        画像字典，失败返回空字典
    """
    try:
        conn = _get_shared_conn()
        if not conn:
            return {}

        with _shared_lock:
            if not ensure_version_column(conn):
                return {}
            row = conn.execute(
                "SELECT * FROM user_profiles WHERE user_id=?", (uid,)
            ).fetchone()

            if not row:
                return {}

            import json
            profile = dict(row)
            # 解析 JSON 字段
            for k in ("tags", "interests", "peak_hours", "persona_tags"):
                if profile.get(k):
                    try:
                        profile[k] = json.loads(profile[k])
                    except Exception:
                        profile[k] = []
                else:
                    profile[k] = []
            return profile
    except Exception as e:
        logger.debug(f"获取共享画像失败 uid={uid}: {e}")
        return {}


def save_shared_profile(uid: int, profile: dict) -> bool:
    """保存共享用户画像（v5.24.0 阶段2-A 乐观锁版）

    将用户画像写入共享数据库，让两个 Bot 都能读到最新画像。
    通过 SQL 乐观锁（version 字段 + WHERE version=?）确保多 Bot 并发写不脏写。

    乐观锁工作流程：
    1. 读取当前记录的 version（无记录则直接 INSERT version=1）
    2. UPDATE ... WHERE user_id=? AND version=?，version=version+1
    3. cursor.rowcount == 1 → 写入成功
    4. rowcount == 0 → 版本冲突（被其他 Bot 修改），重新读取远端最新 profile
    5. 内存合并（tags/interests/persona_tags 并集，数值平均，memory_summary 取较新）
    6. 用新 version 重试 UPDATE，最多重试 3 次
    7. 3 次仍失败 → 记录警告日志，返回 False（本地数据不丢失，下次调用会再尝试）

    调用方无需改动（profile_learner.py 仍按 save_shared_profile(uid, profile) 调用）。

    Returns:
        True 成功，False 失败（冲突重试耗尽或异常）
    """
    try:
        conn = _get_shared_conn()
        if not conn:
            return False

        import json
        with _shared_lock:
            if not ensure_version_column(conn):
                return False

            max_retries = 3  # 最大重试次数（不含首次尝试）

            for attempt in range(max_retries + 1):
                # 读取当前版本和远端 profile（用于冲突时合并）
                row = conn.execute("""
                    SELECT version, tags, interests, persona_tags,
                           activity_score, flirt_affinity, spend_tendency, resistance_idx,
                           memory_summary
                    FROM user_profiles WHERE user_id=?
                """, (uid,)).fetchone()

                # 记录不存在：直接 INSERT（version=1，无冲突可能）
                if not row:
                    tags_json = json.dumps(profile.get("tags", []), ensure_ascii=False)
                    interests_json = json.dumps(profile.get("interests", []), ensure_ascii=False)
                    peak_hours_json = json.dumps(profile.get("peak_hours", []), ensure_ascii=False)
                    persona_tags_json = json.dumps(profile.get("persona_tags", []), ensure_ascii=False)
                    try:
                        conn.execute("""
                            INSERT INTO user_profiles
                            (user_id, tags, level, interests, last_interaction, conversation_rounds,
                             activity_score, flirt_affinity, spend_tendency, resistance_idx,
                             peak_hours, persona_tags, memory_summary, version, updated_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,CURRENT_TIMESTAMP)
                        """, (
                            uid,
                            tags_json,
                            profile.get("level", 0),
                            interests_json,
                            profile.get("last_interaction"),
                            profile.get("conversation_rounds", 0),
                            profile.get("activity_score", 0.0),
                            profile.get("flirt_affinity", 0.0),
                            profile.get("spend_tendency", 0.0),
                            profile.get("resistance_idx", 0.5),
                            peak_hours_json,
                            persona_tags_json,
                            profile.get("memory_summary", ""),
                        ))
                        conn.commit()
                        return True
                    except sqlite3.IntegrityError:
                        # 并发下另一 Bot 刚插入了记录，回退走 UPDATE 路径
                        conn.rollback()
                        continue

                old_version = row["version"]

                # 冲突重试时：合并远端最新 profile 与本地 profile
                if attempt > 0:
                    profile = _merge_profiles(row, profile)
                    logger.debug(f"乐观锁合并重试 uid={uid} attempt={attempt}")

                # 序列化待写字段
                tags_json = json.dumps(profile.get("tags", []), ensure_ascii=False)
                interests_json = json.dumps(profile.get("interests", []), ensure_ascii=False)
                peak_hours_json = json.dumps(profile.get("peak_hours", []), ensure_ascii=False)
                persona_tags_json = json.dumps(profile.get("persona_tags", []), ensure_ascii=False)

                # 乐观锁 UPDATE：WHERE version=? 确保未被其他 Bot 修改
                cur = conn.execute("""
                    UPDATE user_profiles SET
                        tags=?,
                        level=?,
                        interests=?,
                        last_interaction=?,
                        conversation_rounds=?,
                        activity_score=?,
                        flirt_affinity=?,
                        spend_tendency=?,
                        resistance_idx=?,
                        peak_hours=?,
                        persona_tags=?,
                        memory_summary=?,
                        version=version+1,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE user_id=? AND version=?
                """, (
                    tags_json,
                    profile.get("level", 0),
                    interests_json,
                    profile.get("last_interaction"),
                    profile.get("conversation_rounds", 0),
                    profile.get("activity_score", 0.0),
                    profile.get("flirt_affinity", 0.0),
                    profile.get("spend_tendency", 0.0),
                    profile.get("resistance_idx", 0.5),
                    peak_hours_json,
                    persona_tags_json,
                    profile.get("memory_summary", ""),
                    uid,
                    old_version,
                ))

                if cur.rowcount == 1:
                    # rowcount=1 表示 WHERE 命中且 version 匹配，写入成功
                    conn.commit()
                    return True

                # rowcount=0 表示版本冲突（被其他 Bot 修改），回滚当前事务，进入下一轮重试
                conn.rollback()
                logger.debug(f"乐观锁版本冲突 uid={uid} attempt={attempt+1}/{max_retries+1} old_version={old_version}")

            # 重试耗尽：记录警告，保留本地数据（调用方下次再尝试同步）
            logger.warning(
                f"⚠️ 乐观锁重试 {max_retries} 次仍冲突 uid={uid}，放弃本次同步（本地数据保留）"
            )
            return False
    except Exception as e:
        logger.debug(f"保存共享画像失败 uid={uid}: {e}")
        return False


def get_shared_conversion_state(uid: int, bot_id: str = "mory") -> str:
    """获取共享转化状态

    从共享数据库读取用户的转化漏斗状态，
    让 media Bot 能感知用户在主 Bot 的转化阶段。

    [v5.24.0 阶段2-D] bot_id 参数：默认读主 Bot(mory) 的状态，
    media Bot 传自身 bot_id 可读自己的状态。

    Returns:
        状态字符串（touched/interested/carted/converted），失败返回 "unknown"
    """
    try:
        conn = _get_shared_conn()
        if not conn:
            return "unknown"

        with _shared_lock:
            if not _ensure_funnel_state_schema(conn):
                return "unknown"
            row = conn.execute(
                "SELECT state FROM funnel_state WHERE uid=? AND bot_id=?",
                (uid, bot_id)
            ).fetchone()
            return row[0] if row else "unknown"
    except Exception as e:
        logger.debug(f"获取共享转化状态失败 uid={uid}: {e}")
        return "unknown"


def close_shared_conn():
    """关闭共享数据库连接（程序退出时调用）"""
    global _shared_conn
    with _shared_lock:
        if _shared_conn:
            try:
                _shared_conn.close()
                logger.info("✅ 共享数据库连接已关闭")
            except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
                logging.getLogger(__name__).debug(f'非致命忽略: {_e}')
            _shared_conn = None
