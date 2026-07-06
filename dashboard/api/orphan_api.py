# -*- coding: utf-8 -*-
"""[Trae CN v5.12.0] Dashboard孤儿清理API

提供：
- GET /api/orphan/stats - 孤儿状态一站式查询（traced / bot_msg / unreplied / 24h 孤儿 / 最近清理）
- GET /api/orphan/cleanup-history - 最近 N 条清理历史（默认 20 条）
- POST /api/orphan/force-clean - 管理员手动触发一次清理（force trigger）
"""
import logging
import time
from datetime import datetime, timezone, timedelta
from flask import Blueprint, jsonify, request, session
from dashboard.helpers import login_required, admin_required, get_db, read_config, _CST

# 【v5.31.2 hotfix P1-4】修复 logger 未定义 bug（原代码 line 166/170/185 使用 logger 但未导入）
logger = logging.getLogger(__name__)

orphan_bp = Blueprint('orphan', __name__, url_prefix='/api/orphan')
_CST_TZ = timezone(timedelta(hours=8))


def _ts_to_cst_str(ts: int) -> str:
    """Unix时间戳转北京时间字符串"""
    try:
        return datetime.fromtimestamp(int(ts), _CST_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "—"


@orphan_bp.route("/stats")
@login_required
def api_orphan_stats():
    """孤儿清理状态一站式查询

    返回:
    {
        "ok": true,
        "data": {
            "tracked_count": 5,           # reply_tracking 总数
            "bot_msg_count": 4,           # Bot主动消息数
            "unreplied_count": 1,         # 用户未回复数
            "orphan_24h_count": 0,        # 24h 超时孤儿数
            "enable_deletion": true,      # ENABLE_MESSAGE_DELETION 开关
            "last_cleanup": {             # 最近一次清理记录
                "id": 12,
                "run_at": 1234567890,
                "run_at_str": "2026-06-02 11:00:00",
                "found_count": 0,
                "deleted_count": 0,
                "skipped_count": 0,
                "error": null,
                "trigger": "scheduled"
            } | null
        }
    }
    """
    try:
        db = get_db()
        if hasattr(db, "get_orphan_stats"):
            stats = db.get_orphan_stats()
        else:
            return jsonify({"ok": False, "msg": "DB method get_orphan_stats not registered"}), 500

        cfg = read_config()
        enable_deletion = bool(cfg.get("ENABLE_MESSAGE_DELETION", False))
        # [v5.12.4] 独立开关 ORPHAN_CLEANUP_ENABLED
        from core.helpers import can_orphan_cleanup
        enable_orphan_cleanup = can_orphan_cleanup(cfg)

        last_cleanup = stats.get("last_cleanup")
        if last_cleanup:
            last_cleanup["run_at_str"] = _ts_to_cst_str(last_cleanup["run_at"])

        return jsonify({
            "ok": True,
            "data": {
                "tracked_count": stats.get("tracked_count", 0),
                "bot_msg_count": stats.get("bot_msg_count", 0),
                "unreplied_count": stats.get("unreplied_count", 0),
                "orphan_24h_count": stats.get("orphan_24h_count", 0),
                "orphan_30m_count": stats.get("orphan_30m_count", 0),  # [v5.12.4] 新增
                "enable_deletion": enable_deletion,
                "enable_orphan_cleanup": enable_orphan_cleanup,  # [v5.12.4] 新增
                "last_cleanup": last_cleanup,
            }
        })
    except Exception:
        return jsonify({"ok": False, "msg": "内部错误，请稍后重试"}), 500


@orphan_bp.route("/cleanup-history")
@login_required
def api_orphan_cleanup_history():
    """最近 N 条清理历史（默认 20 条）"""
    try:
        limit = int(request.args.get("limit", 20))
        limit = max(1, min(limit, 200))
        db = get_db()
        if not hasattr(db, "get_orphan_cleanup_history"):
            return jsonify({"ok": False, "msg": "DB method get_orphan_cleanup_history not registered"}), 500
        rows = db.get_orphan_cleanup_history(limit=limit)
        for r in rows:
            r["run_at_str"] = _ts_to_cst_str(r["run_at"])
        return jsonify({"ok": True, "data": rows})
    except Exception:
        return jsonify({"ok": False, "msg": "内部错误，请稍后重试"}), 500


@orphan_bp.route("/force-clean", methods=["POST"])
@login_required
@admin_required  # 【TRAE SOLO CN v5.18.3审计修复】批量删除消息需管理员权限
def api_orphan_force_clean():
    """[v5.12.4] 管理员手动触发一次清理

    升级：v5.12.0 只写日志，Bot 进程最多 10 分钟后才跑。
    现在能立即在 Dashboard 进程内执行清理（不依赖 Bot 进程）。

    Returns:
        {
            "ok": true,
            "data": {
                "found": int,       # 发现孤儿数
                "deleted": int,     # 实际删除成功数
                "failed": int,      # 删除失败数
                "note": str
            }
        }
    """
    try:
        db = get_db()
        cfg = read_config()

        # [v5.12.4] 检查独立开关
        from core.helpers import can_orphan_cleanup
        if not can_orphan_cleanup(cfg):
            return jsonify({
                "ok": False,
                "msg": "ORPHAN_CLEANUP_ENABLED=False, 请先在设置中开启",
            }), 400

        # 1. 扫描孤儿
        orphans = db.get_orphan_messages(1800)  # 30分钟窗口
        found = len(orphans)
        if found == 0:
            return jsonify({
                "ok": True,
                "data": {
                    "found": 0,
                    "deleted": 0,
                    "failed": 0,
                    "note": "无超时孤儿",
                }
            })

        # 2. 立即清理（不依赖 Bot 进程）
        import telebot
        token = cfg.get("TOKEN", "")
        if not token or token == "YOUR_TELEGRAM_BOT_TOKEN":
            return jsonify({"ok": False, "msg": "config.json 中 TOKEN 无效"}), 500
        bot = telebot.TeleBot(token)

        success = 0
        fail = 0
        for i, (bot_mid, chat_id, user_mid) in enumerate(orphans, 1):
            try:
                bot.delete_message(chat_id, int(bot_mid))
                success += 1
            except Exception as del_err:
                fail += 1
                logger.debug(f"  force-clean 删除失败：bot_mid={bot_mid} err={del_err}")
            try:
                db.delete_tracked(bot_mid, chat_id)
            except Exception as e:
                logger.debug(f"操作异常: {e}")
            # 防 429：每 10 条 sleep 1s
            if i % 10 == 0:
                import time as _t
                _t.sleep(1)

        # 3. 写日志
        try:
            db.log_orphan_cleanup(
                found_count=found,
                deleted_count=success,
                skipped_count=fail,
                trigger="force_api",
            )
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        return jsonify({
            "ok": True,
            "data": {
                "found": found,
                "deleted": success,
                "failed": fail,
                "note": f"force-clean 完成：{success}/{found} 成功",
            }
        })
    except Exception:
        return jsonify({"ok": False, "msg": "内部错误，请稍后重试"}), 500
