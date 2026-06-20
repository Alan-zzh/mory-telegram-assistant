# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  dashboard/api/rbac_approval_api.py  ·  RBAC 审批流 API（阶段3-E）       ║
║                                                                            ║
║  接口清单：                                                                ║
║    POST /api/rbac/request         提交权限申请（需登录）                   ║
║    POST /api/rbac/approve         审批通过（需 admin）                     ║
║    POST /api/rbac/reject          审批拒绝（需 admin）                     ║
║    POST /api/rbac/cancel          取消申请（申请人本人）                   ║
║    GET  /api/rbac/requests        列出申请（需登录，admin 可查全部）       ║
║    GET  /api/rbac/requests/<id>   申请详情（需登录）                       ║
║                                                                            ║
║  鉴权：复用 dashboard.helpers.login_required / admin_required             ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from flask import Blueprint, jsonify, request, session
from dashboard.helpers import login_required, admin_required
from dashboard.rbac_approval import (
    create_request,
    approve_request,
    reject_request,
    cancel_request,
    list_requests,
    get_request,
    STATUS_PENDING,
)

rbac_approval_bp = Blueprint("rbac_approval", __name__)


@rbac_approval_bp.route("/api/rbac/request", methods=["POST"])
@login_required
def api_create_request():
    """提交权限变更申请（需登录）"""
    if not request.is_json:
        return jsonify({"ok": False, "msg": "请求体必须是 JSON"}), 400
    data = request.get_json(silent=True) or {}

    target_user_id = data.get("target_user_id")
    requested_role = data.get("requested_role")
    reason = data.get("reason", "")

    # 参数校验
    if not target_user_id or not isinstance(target_user_id, int):
        return jsonify({"ok": False, "msg": "target_user_id 必须为整数"}), 400
    if not requested_role or not isinstance(requested_role, str):
        return jsonify({"ok": False, "msg": "requested_role 必须为字符串"}), 400

    requester_id = session.get("uid", 0)
    if not requester_id:
        return jsonify({"ok": False, "msg": "会话缺少 uid"}), 401

    result = create_request(
        requester_id=requester_id,
        target_user_id=target_user_id,
        requested_role=requested_role,
        reason=reason,
    )
    code = 200 if result.get("ok") else 400
    return jsonify(result), code


@rbac_approval_bp.route("/api/rbac/approve", methods=["POST"])
@admin_required
def api_approve_request():
    """审批通过（需 admin）"""
    if not request.is_json:
        return jsonify({"ok": False, "msg": "请求体必须是 JSON"}), 400
    data = request.get_json(silent=True) or {}

    request_id = data.get("request_id")
    if not request_id or not isinstance(request_id, int):
        return jsonify({"ok": False, "msg": "request_id 必须为整数"}), 400

    approver_id = session.get("uid", 0)
    if not approver_id:
        return jsonify({"ok": False, "msg": "会话缺少 uid"}), 401

    result = approve_request(request_id=request_id, approver_id=approver_id)
    code = 200 if result.get("ok") else 400
    return jsonify(result), code


@rbac_approval_bp.route("/api/rbac/reject", methods=["POST"])
@admin_required
def api_reject_request():
    """审批拒绝（需 admin）"""
    if not request.is_json:
        return jsonify({"ok": False, "msg": "请求体必须是 JSON"}), 400
    data = request.get_json(silent=True) or {}

    request_id = data.get("request_id")
    if not request_id or not isinstance(request_id, int):
        return jsonify({"ok": False, "msg": "request_id 必须为整数"}), 400

    reason = data.get("reason", "")
    approver_id = session.get("uid", 0)
    if not approver_id:
        return jsonify({"ok": False, "msg": "会话缺少 uid"}), 401

    result = reject_request(request_id=request_id, approver_id=approver_id, reason=reason)
    code = 200 if result.get("ok") else 400
    return jsonify(result), code


@rbac_approval_bp.route("/api/rbac/cancel", methods=["POST"])
@login_required
def api_cancel_request():
    """取消申请（仅申请人本人）"""
    if not request.is_json:
        return jsonify({"ok": False, "msg": "请求体必须是 JSON"}), 400
    data = request.get_json(silent=True) or {}

    request_id = data.get("request_id")
    if not request_id or not isinstance(request_id, int):
        return jsonify({"ok": False, "msg": "request_id 必须为整数"}), 400

    requester_id = session.get("uid", 0)
    if not requester_id:
        return jsonify({"ok": False, "msg": "会话缺少 uid"}), 401

    result = cancel_request(request_id=request_id, requester_id=requester_id)
    code = 200 if result.get("ok") else 400
    return jsonify(result), code


@rbac_approval_bp.route("/api/rbac/requests", methods=["GET"])
@login_required
def api_list_requests():
    """列出权限变更申请（admin 可查全部状态，非 admin 仅查自己提交的）"""
    status = request.args.get("status", STATUS_PENDING)
    limit = min(int(request.args.get("limit", 50)), 200)

    role = session.get("role", "viewer")
    rows = list_requests(status=status, limit=limit)

    # 非 admin 仅能看自己提交的申请
    if role != "admin":
        uid = session.get("uid", 0)
        rows = [r for r in rows if r.get("requester_id") == uid]

    return jsonify({"ok": True, "data": rows, "count": len(rows)})


@rbac_approval_bp.route("/api/rbac/requests/<int:req_id>", methods=["GET"])
@login_required
def api_get_request(req_id: int):
    """查询申请详情（admin 可查任意，非 admin 仅查自己提交的）"""
    req = get_request(req_id)
    if not req:
        return jsonify({"ok": False, "msg": "申请不存在"}), 404

    role = session.get("role", "viewer")
    uid = session.get("uid", 0)
    if role != "admin" and req.get("requester_id") != uid:
        return jsonify({"ok": False, "msg": "无权查看此申请"}), 403

    return jsonify({"ok": True, "data": req})
