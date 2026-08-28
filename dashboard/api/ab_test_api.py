# -*- coding: utf-8 -*-
"""A/B 测试、按钮统计与用户画像 API。"""
import json
import time

from flask import Blueprint, jsonify, request

# Dashboard 使用请求级 SQLite 连接和同一份配置读取器；禁止从 Bot 进程
# 或 dashboard.app 反向导入并不存在的全局 db/config。
from dashboard.helpers import admin_required, get_db, login_required, read_config
from core.profile_learner import ProfileLearner
from core.logging_util import get_logger

logger = get_logger(__name__)

ab_test_bp = Blueprint("ab_test", __name__)
button_stats_bp = Blueprint("button_stats", __name__)


def _get_db():
    """返回 Dashboard 请求级数据库连接。"""
    return get_db()


def _get_config():
    """返回与 Dashboard 其他 API 一致的运行配置快照。"""
    return read_config()


_EMPTY_AB_STATS = {
    "html_sent": 0,
    "html_conversions": 0,
    "rich_sent": 0,
    "rich_conversions": 0,
}


def _as_int(value, default: int, minimum: int, maximum: int) -> int:
    """解析 URL/JSON 整数，避免坏输入把统计 API 变成 500。"""
    try:
        return min(maximum, max(minimum, int(value)))
    except (TypeError, ValueError):
        return default


def _load_json_list(value) -> list:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


class _DashboardProfileStore:
    """把请求级 SQLite 连接适配给 ProfileLearner 的最小持久化合同。"""

    def __init__(self, connection):
        self.connection = connection

    def get_user_persona_profile(self, user_id: int):
        row = self.connection.execute(
            """
            SELECT user_id, tags, level, interests, last_interaction, conversation_rounds,
                   activity_score, flirt_affinity, spend_tendency, resistance_idx,
                   peak_hours, persona_tags, memory_summary
            FROM user_profiles WHERE user_id=?
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "user_id": row[0],
            "tags": _load_json_list(row[1]),
            "level": row[2] or 0,
            "interests": _load_json_list(row[3]),
            "last_interaction": row[4],
            "conversation_rounds": row[5] or 0,
            "activity_score": row[6] or 0.0,
            "flirt_affinity": row[7] or 0.0,
            "spend_tendency": row[8] or 0.0,
            "resistance_idx": row[9] if row[9] is not None else 0.5,
            "peak_hours": _load_json_list(row[10]),
            "persona_tags": _load_json_list(row[11]),
            "memory_summary": row[12] or "",
        }

    def upsert_user_profile(self, profile: dict) -> None:
        self.connection.execute(
            """
            INSERT INTO user_profiles
                (user_id, tags, level, interests, last_interaction, conversation_rounds,
                 activity_score, flirt_affinity, spend_tendency, resistance_idx,
                 peak_hours, persona_tags, memory_summary, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                tags=excluded.tags, level=excluded.level, interests=excluded.interests,
                last_interaction=excluded.last_interaction,
                conversation_rounds=excluded.conversation_rounds,
                activity_score=excluded.activity_score,
                flirt_affinity=excluded.flirt_affinity,
                spend_tendency=excluded.spend_tendency,
                resistance_idx=excluded.resistance_idx,
                peak_hours=excluded.peak_hours,
                persona_tags=excluded.persona_tags,
                memory_summary=COALESCE(excluded.memory_summary, user_profiles.memory_summary),
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                profile["user_id"],
                json.dumps(profile.get("tags", []), ensure_ascii=False),
                profile.get("level", 0),
                json.dumps(profile.get("interests", []), ensure_ascii=False),
                profile.get("last_interaction"),
                profile.get("conversation_rounds", 0),
                profile.get("activity_score", 0.0),
                profile.get("flirt_affinity", 0.0),
                profile.get("spend_tendency", 0.0),
                profile.get("resistance_idx", 0.5),
                json.dumps(profile.get("peak_hours", []), ensure_ascii=False),
                json.dumps(profile.get("persona_tags", []), ensure_ascii=False),
                profile.get("memory_summary"),
            ),
        )
        self.connection.commit()


# ── A/B 测试 API ────────────────────────────────────────────

@ab_test_bp.route("/api/ab-test/stats", methods=["GET"])
@login_required
def get_ab_test_stats():
    """获取 A/B 测试统计。"""
    try:
        rows = _get_db().execute(
            """
            SELECT format_version, COALESCE(SUM(sent_count), 0),
                   COALESCE(SUM(conversion_count), 0)
            FROM ab_test_stats GROUP BY format_version
            """
        ).fetchall()
        stats = dict(_EMPTY_AB_STATS)
        for format_version, sent, conversions in rows:
            if format_version in ("html", "rich"):
                stats[f"{format_version}_sent"] = sent or 0
                stats[f"{format_version}_conversions"] = conversions or 0
        return jsonify({"ok": True, "data": stats})
    except Exception as e:
        logger.warning(f"获取 A/B 测试统计失败: {e}")
        return jsonify({"ok": False, "msg": "统计数据暂不可用"}), 503


@ab_test_bp.route("/api/ab-test/record-sent", methods=["POST"])
@login_required
@admin_required  # 【TRAE SOLO CN v5.18.3审计修复】写操作需管理员权限
def record_ab_test_sent():
    """记录 A/B 测试发送数（内部调用）。"""
    data = request.get_json() or {}
    group_name = str(data.get("group_name", "default"))[:64]
    format_version = str(data.get("format_version", "html"))
    if format_version not in ("html", "rich"):
        return jsonify({"ok": False, "msg": "参数错误"}), 400
    count = _as_int(data.get("count", 1), 1, 1, 100_000)
    try:
        db = _get_db()
        ts = int(time.time())
        db.execute(
            """
            INSERT INTO ab_test_stats (group_name, format_version, sent_count, ts)
            VALUES (?, ?, ?, ?)
            """,
            (group_name, format_version, count, ts),
        )
        db.commit()
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception(f"[ab_test_api] record_ab_test_sent 失败: {e}")
        return jsonify({"ok": False, "msg": "internal_error"}), 500


@ab_test_bp.route("/api/ab-test/significance", methods=["GET"])
@login_required
def get_ab_test_significance():
    """获取 A/B 测试统计显著性检验结果

    Query 参数:
        days: 回溯天数（默认 7）
        alpha: 显著性水平阈值（默认 0.05，即 95% 置信度）

    返回:
        统计显著性结果，包含卡方检验（转化率）和 Z 检验（延迟），
        p-value < alpha 表示差异显著，并给出胜出组推荐。
    """
    try:
        from core.ab_test_router import get_significance_report
    except ImportError:
        return jsonify({"ok": False, "msg": "ab_test_router 模块不可用"}), 500

    days = min(90, max(1, int(request.args.get("days", 7))))
    alpha = float(request.args.get("alpha", 0.05))
    if alpha <= 0 or alpha >= 1:
        alpha = 0.05

    try:
        report = get_significance_report(days=days, alpha=alpha, db=_get_db())
        return jsonify({"ok": True, "data": report})
    except Exception as e:
        logger.exception(f"[ab_test_api] get_ab_test_significance 失败: {e}")
        return jsonify({"ok": False, "msg": "internal_error"}), 500


# ── 按钮统计 API ────────────────────────────────────────────

@button_stats_bp.route("/api/button-stats/stats", methods=["GET"])
@login_required
def get_button_stats():
    """获取按钮点击统计。"""
    try:
        rows = _get_db().execute(
            """
            SELECT button_id, style, impressions, clicks
            FROM button_click_stats
            WHERE impressions > 0 OR clicks > 0
            ORDER BY (clicks * 1.0 / MAX(impressions, 1)) DESC
            """
        ).fetchall()
        stats = [
            {
                "button_id": row[0],
                "style": row[1],
                "impressions": row[2] or 0,
                "clicks": row[3] or 0,
                "ctr": (row[3] or 0) / max(1, row[2] or 0),
            }
            for row in rows
        ]
        return jsonify({"ok": True, "data": {"stats": stats}})
    except Exception as e:
        logger.warning(f"获取按钮统计失败: {e}")
        return jsonify({"ok": False, "msg": "统计数据暂不可用"}), 503


@button_stats_bp.route("/api/button-stats/record", methods=["POST"])
@login_required
@admin_required  # 【TRAE SOLO CN v5.18.3审计修复】写操作需管理员权限
def record_button_event():
    """记录按钮事件（impression/click）。"""
    data = request.get_json() or {}
    button_id = str(data.get("button_id", "")).strip()
    style = str(data.get("style", "default")).strip()
    event = str(data.get("event", "")).strip()  # "impression" or "click"
    if not button_id or event not in ("impression", "click"):
        return jsonify({"ok": False, "msg": "参数错误"}), 400
    try:
        db = _get_db()
        impressions, clicks = (1, 0) if event == "impression" else (0, 1)
        db.execute(
            """
            INSERT INTO button_click_stats (button_id, style, impressions, clicks)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(button_id, style) DO UPDATE SET
                impressions=impressions + excluded.impressions,
                clicks=clicks + excluded.clicks,
                last_updated=CURRENT_TIMESTAMP
            """,
            (button_id, style, impressions, clicks),
        )
        db.commit()
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception(f"[ab_test_api] record_button_event 失败: {e}")
        return jsonify({"ok": False, "msg": "internal_error"}), 500


# ── 用户画像 API（v5.18.0） ────────────────────────────────────────────

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/api/profile/learn", methods=["POST"])
@login_required
@admin_required  # 【TRAE SOLO CN v5.18.3审计修复】写操作需管理员权限
def learn_profile():
    """从消息学习用户画像（内部调用）。"""
    db = _get_db()
    config = _get_config()
    if not db:
        return jsonify({"ok": False, "msg": "数据库不可用"}), 500
    data = request.get_json() or {}
    user_id = data.get("user_id")
    text = data.get("text", "")
    if not user_id or not text:
        return jsonify({"ok": False, "msg": "参数错误"}), 400
    try:
        learner = ProfileLearner(_DashboardProfileStore(db), config)
        profile = learner.learn_from_message(int(user_id), text)
        return jsonify({"ok": True, "data": profile})
    except Exception as e:
        logger.exception(f"[ab_test_api] learn_profile 失败: {e}")
        return jsonify({"ok": False, "msg": "internal_error"}), 500


@profile_bp.route("/api/profile/list", methods=["GET"])
@login_required
@admin_required
def list_profiles():
    """列出用户画像。"""
    db = _get_db()
    min_level = _as_int(request.args.get("min_level", 0), 0, 0, 10)
    tag = request.args.get("tag", "").strip()
    limit = _as_int(request.args.get("limit", 100), 100, 1, 500)
    try:
        query = """
            SELECT user_id, tags, level, interests, last_interaction, conversation_rounds
            FROM user_profiles WHERE level >= ?
        """
        params = [min_level]
        if tag:
            query += " AND tags LIKE ?"
            params.append(f'%"{tag}"%')
        query += " ORDER BY level DESC, last_interaction DESC LIMIT ?"
        params.append(limit)
        rows = db.execute(query, params).fetchall()
        profiles = [
            {
                "user_id": row[0], "tags": _load_json_list(row[1]),
                "level": row[2] or 0, "interests": _load_json_list(row[3]),
                "last_interaction": row[4], "conversation_rounds": row[5] or 0,
            }
            for row in rows
        ]
        return jsonify({"ok": True, "data": {"profiles": profiles, "count": len(profiles)}})
    except Exception as e:
        logger.exception(f"[ab_test_api] list_profiles 失败: {e}")
        return jsonify({"ok": False, "msg": "internal_error"}), 500


@profile_bp.route("/api/profile/<int:user_id>", methods=["GET"])
@login_required
@admin_required  # 【TRAE SOLO CN v5.18.3审计修复】查看任意用户画像需管理员权限
def get_profile(user_id: int):
    """获取单个用户画像。"""
    try:
        profile = _DashboardProfileStore(_get_db()).get_user_persona_profile(user_id)
        return jsonify({"ok": True, "data": profile})
    except Exception as e:
        logger.exception(f"[ab_test_api] get_profile 失败: {e}")
        return jsonify({"ok": False, "msg": "internal_error"}), 500
