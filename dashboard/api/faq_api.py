# -*- coding: utf-8 -*-
"""
dashboard/api/faq_api.py  ·  FAQ 统计与管理 API

端点：
- GET  /api/faq/stats                        - 问题统计
- GET  /api/faq/questions                    - 问题列表（分页）
- GET  /api/faq/candidates                   - FAQ 候选列表
- POST /api/faq/candidates/<cid>/approve     - 批准候选
- POST /api/faq/candidates/<cid>/reject      - 拒绝候选
- GET  /api/faq/knowledge                    - FAQ 知识库列表
- POST /api/faq/knowledge                    - 新增 FAQ 条目
- PUT  /api/faq/knowledge/<faq_id>           - 更新 FAQ 条目
- DELETE /api/faq/knowledge/<faq_id>         - 删除 FAQ 条目
- POST /api/faq/distill                      - 手动触发 FAQ 蒸馏
"""
import logging
from flask import Blueprint, jsonify, request, session
from dashboard.helpers import login_required, admin_required, get_db

logger = logging.getLogger(__name__)

faq_bp = Blueprint("faq_api", __name__, url_prefix="/api/faq")


@faq_bp.route("/stats", methods=["GET"])
@login_required
def get_stats():
    """问题统计一站式查询"""
    try:
        db = get_db()
        if not db:
            return jsonify({"ok": False, "msg": "数据库未就绪"}), 503

        if not hasattr(db, "get_question_stats"):
            return jsonify({"ok": False, "msg": "方法未注册"}), 501

        stats = db.get_question_stats()
        return jsonify({"ok": True, "data": stats})
    except Exception as e:
        logger.exception("FAQ API 查询接口异常")
        return jsonify({"ok": False, "msg": "查询失败，请查看服务器日志获取详情"}), 500


@faq_bp.route("/questions", methods=["GET"])
@login_required
def get_questions():
    """问题列表（分页）"""
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
        category = request.args.get("category", "").strip() or None
        days = int(request.args.get("days", 7))

        # 参数安全限制
        page = max(1, page)
        per_page = min(max(1, per_page), 200)
        days = min(max(1, days), 90)

        db = get_db()
        if not db:
            return jsonify({"ok": False, "msg": "数据库未就绪"}), 503

        if not hasattr(db, "get_questions"):
            return jsonify({"ok": False, "msg": "方法未注册"}), 501

        limit = per_page
        offset = (page - 1) * per_page
        result = db.get_questions(
            limit,
            offset,
            category,
            days,
            include_total=True,
        )

        # 兼容返回值：可能是元组 (questions, total) 或仅列表
        if isinstance(result, tuple) and len(result) == 2:
            questions, total = result
        else:
            questions = result
            total = len(questions) if isinstance(questions, list) else 0

        return jsonify({
            "ok": True,
            "data": {
                "questions": questions,
                "page": page,
                "per_page": per_page,
                "total": total
            }
        })
    except Exception as e:
        logger.exception("FAQ API 查询接口异常")
        return jsonify({"ok": False, "msg": "查询失败，请查看服务器日志获取详情"}), 500


@faq_bp.route("/candidates", methods=["GET"])
@login_required
def get_candidates():
    """FAQ 候选列表"""
    try:
        status = request.args.get("status", "pending").strip()

        db = get_db()
        if not db:
            return jsonify({"ok": False, "msg": "数据库未就绪"}), 503

        # 根据状态筛选
        if status == "pending" and hasattr(db, "get_pending_candidates"):
            candidates = db.get_pending_candidates()
        elif hasattr(db, "get_candidates_by_status"):
            candidates = db.get_candidates_by_status(status)
        else:
            # 降级：直接查数据库
            conn = get_db()
            rows = conn.execute(
                "SELECT * FROM faq_candidates WHERE status = ? ORDER BY created_at DESC",
                (status,)
            ).fetchall()
            candidates = [dict(r) for r in rows]

        return jsonify({"ok": True, "data": {"candidates": candidates}})
    except Exception as e:
        logger.exception("FAQ API 查询接口异常")
        return jsonify({"ok": False, "msg": "查询失败，请查看服务器日志获取详情"}), 500


@faq_bp.route("/candidates/<int:cid>/approve", methods=["POST"])
@login_required
@admin_required  # 【TRAE SOLO CN v5.18.3审计修复】写操作需管理员权限
def approve_candidate(cid):
    """批准 FAQ 候选"""
    try:
        payload = request.get_json(silent=True) or {}
        answer_template = payload.get("answer_template", "").strip()
        if not answer_template:
            return jsonify({"ok": False, "msg": "answer_template 不能为空"}), 400

        ai_polish = int(payload.get("ai_polish", 1))
        question_category = payload.get("question_category", "").strip() or None
        reviewed_by = session.get("username", "dashboard")

        db = get_db()
        if not db:
            return jsonify({"ok": False, "msg": "数据库未就绪"}), 503

        if not hasattr(db, "approve_candidate"):
            return jsonify({"ok": False, "msg": "方法未注册"}), 501

        faq_id = db.approve_candidate(
            cid, answer_template, ai_polish,
            reviewed_by=reviewed_by,
            question_category=question_category
        )

        return jsonify({"ok": True, "data": {"faq_id": faq_id}})
    except Exception as e:
        logger.exception("FAQ API 批准候选异常")
        return jsonify({"ok": False, "msg": "批准失败，请查看服务器日志获取详情"}), 500


@faq_bp.route("/candidates/<int:cid>/reject", methods=["POST"])
@login_required
@admin_required  # 【TRAE SOLO CN v5.18.3审计修复】写操作需管理员权限
def reject_candidate(cid):
    """拒绝 FAQ 候选"""
    try:
        reviewed_by = session.get("username", "dashboard")

        db = get_db()
        if not db:
            return jsonify({"ok": False, "msg": "数据库未就绪"}), 503

        if not hasattr(db, "reject_candidate"):
            return jsonify({"ok": False, "msg": "方法未注册"}), 501

        db.reject_candidate(cid, reviewed_by=reviewed_by)

        return jsonify({"ok": True, "msg": "已拒绝"})
    except Exception as e:
        logger.exception("FAQ API 拒绝候选异常")
        return jsonify({"ok": False, "msg": "拒绝失败，请查看服务器日志获取详情"}), 500


@faq_bp.route("/knowledge", methods=["GET"])
@login_required
def get_knowledge():
    """FAQ 知识库列表"""
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
        category = request.args.get("category", "").strip() or None
        status = request.args.get("status", "approved").strip()

        # 参数安全限制
        page = max(1, page)
        per_page = min(max(1, per_page), 200)

        db = get_db()
        if not db:
            return jsonify({"ok": False, "msg": "数据库未就绪"}), 503

        if not hasattr(db, "get_faq_knowledge"):
            return jsonify({"ok": False, "msg": "方法未注册"}), 501

        limit = per_page
        offset = (page - 1) * per_page
        faqs = db.get_faq_knowledge(limit, offset, category, status)

        return jsonify({
            "ok": True,
            "data": {
                "faqs": faqs,
                "page": page,
                "per_page": per_page
            }
        })
    except Exception as e:
        logger.exception("FAQ API 查询接口异常")
        return jsonify({"ok": False, "msg": "查询失败，请查看服务器日志获取详情"}), 500


@faq_bp.route("/knowledge", methods=["POST"])
@login_required
@admin_required  # 【TRAE SOLO CN v5.18.3审计修复】写操作需管理员权限
def add_knowledge():
    """新增 FAQ 知识库条目"""
    try:
        payload = request.get_json(silent=True) or {}
        question_pattern = payload.get("question_pattern", "").strip()
        question_category = payload.get("question_category", "").strip() or None
        answer_template = payload.get("answer_template", "").strip()
        ai_polish = int(payload.get("ai_polish", 1))
        match_mode = payload.get("match_mode", "keyword").strip()
        priority = int(payload.get("priority", 0))

        # 必填字段校验
        if not question_pattern:
            return jsonify({"ok": False, "msg": "question_pattern 不能为空"}), 400
        if not answer_template:
            return jsonify({"ok": False, "msg": "answer_template 不能为空"}), 400

        db = get_db()
        if not db:
            return jsonify({"ok": False, "msg": "数据库未就绪"}), 503

        if not hasattr(db, "add_faq_knowledge"):
            return jsonify({"ok": False, "msg": "方法未注册"}), 501

        faq_id = db.add_faq_knowledge(
            question_pattern, question_category,
            answer_template, ai_polish,
            match_mode, priority
        )

        return jsonify({"ok": True, "data": {"id": faq_id}})
    except Exception as e:
        logger.exception("FAQ API 新增知识库条目异常")
        return jsonify({"ok": False, "msg": "新增失败，请查看服务器日志获取详情"}), 500


@faq_bp.route("/knowledge/<int:faq_id>", methods=["PUT"])
@login_required
@admin_required  # 【TRAE SOLO CN v5.18.3审计修复】写操作需管理员权限
def update_knowledge(faq_id):
    """更新 FAQ 知识库条目"""
    try:
        payload = request.get_json(silent=True) or {}

        # 允许更新的字段白名单
        allowed_fields = {
            "answer_template", "ai_polish", "match_mode",
            "priority", "status", "question_pattern", "question_category"
        }
        updates = {k: v for k, v in payload.items() if k in allowed_fields}

        if not updates:
            return jsonify({"ok": False, "msg": "无有效更新字段"}), 400

        # 类型转换
        if "ai_polish" in updates:
            updates["ai_polish"] = int(updates["ai_polish"])
        if "priority" in updates:
            updates["priority"] = int(updates["priority"])

        db = get_db()
        if not db:
            return jsonify({"ok": False, "msg": "数据库未就绪"}), 503

        if not hasattr(db, "update_faq_knowledge"):
            return jsonify({"ok": False, "msg": "方法未注册"}), 501

        db.update_faq_knowledge(faq_id, **updates)

        return jsonify({"ok": True, "msg": "已更新"})
    except Exception as e:
        logger.exception("FAQ API 更新知识库条目异常")
        return jsonify({"ok": False, "msg": "更新失败，请查看服务器日志获取详情"}), 500


@faq_bp.route("/knowledge/<int:faq_id>", methods=["DELETE"])
@login_required
@admin_required  # 【TRAE SOLO CN v5.18.3审计修复】写操作需管理员权限
def delete_knowledge(faq_id):
    """删除 FAQ 知识库条目"""
    try:
        db = get_db()
        if not db:
            return jsonify({"ok": False, "msg": "数据库未就绪"}), 503

        if not hasattr(db, "delete_faq_knowledge"):
            return jsonify({"ok": False, "msg": "方法未注册"}), 501

        db.delete_faq_knowledge(faq_id)

        return jsonify({"ok": True, "msg": "已删除"})
    except Exception as e:
        logger.exception("FAQ API 删除知识库条目异常")
        return jsonify({"ok": False, "msg": "删除失败，请查看服务器日志获取详情"}), 500


@faq_bp.route("/distill", methods=["POST"])
@login_required
@admin_required  # 【TRAE SOLO CN v5.18.3审计修复】触发蒸馏需管理员权限
def distill():
    """手动触发 FAQ 蒸馏"""
    try:
        db = get_db()
        if not db:
            return jsonify({"ok": False, "msg": "数据库未就绪"}), 503

        if not hasattr(db, "distill_candidates"):
            return jsonify({"ok": False, "msg": "方法未注册"}), 501

        new_count = db.distill_candidates()

        return jsonify({"ok": True, "data": {"new_candidates_count": new_count}})
    except Exception as e:
        logger.exception("FAQ API 蒸馏候选异常")
        return jsonify({"ok": False, "msg": "蒸馏失败，请查看服务器日志获取详情"}), 500
