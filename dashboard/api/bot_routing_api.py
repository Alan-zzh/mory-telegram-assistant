# -*- coding: utf-8 -*-
"""
dashboard/api/bot_routing_api.py · 多 Bot 路由管理 API（v5.24.0 阶段3-C）

端点：
  GET  /api/bot-routing/list                  - 列出所有路由（支持 ?chat_id= 过滤）
  POST /api/bot-routing/assign                - 分配/更新路由（需 admin 权限）
  POST /api/bot-routing/remove                - 删除路由（需 admin 权限）
  GET  /api/bot-routing/check                 - 查询是否放行 ?bot_id=&chat_id=&module=

权限：
  - 读操作（list/check）：登录用户可访问
  - 写操作（assign/remove）：需 admin 角色 + RBAC config:write 权限
"""
from flask import Blueprint, jsonify, request

from dashboard.helpers import login_required, admin_required, read_config

bot_routing_bp = Blueprint("bot_routing", __name__, url_prefix="/api/bot-routing")


def _get_router():
    """获取路由器单例（Dashboard 进程内独立初始化）

    Dashboard 与 Bot 是独立进程，Bot 进程的 _router_instance 不会自动同步到 Dashboard。
    这里在首次调用时按当前 config 初始化一个临时实例，仅用于读操作。
    写操作直接走 DB（与 Bot 进程共享同一张表）。
    """
    from core.bot_routing import BotRouter, get_router
    router = get_router()
    if router is not None:
        return router
    # Dashboard 进程首次访问：按当前 config 临时初始化
    cfg = read_config()
    return BotRouter(cfg)


@bot_routing_bp.route("/list", methods=["GET"])
@login_required
def api_bot_routing_list():
    """列出所有路由

    Query 参数：
        chat_id: 可选，按群组过滤

    Returns:
        {
            "ok": true,
            "data": [
                {
                    "bot_id": 123,
                    "chat_id": -100123,
                    "allowed_modules": ["group_chat"],
                    "is_active": true,
                    "created_at": "...",
                    "updated_at": "..."
                }
            ],
            "enabled": false,
            "default_policy": "allow"
        }
    """
    try:
        chat_id = request.args.get("chat_id", type=int)
        router = _get_router()
        data = router.list_routing(chat_id=chat_id)
        return jsonify({
            "ok": True,
            "data": data,
            "enabled": router.enabled,
            "default_policy": router.default_policy,
        })
    except Exception as e:
        return jsonify({"ok": False, "msg": f"内部错误：{e}"}), 500


@bot_routing_bp.route("/assign", methods=["POST"])
@login_required
@admin_required
def api_bot_routing_assign():
    """分配/更新路由（需 admin 权限）

    请求体 JSON：
        {
            "bot_id": 123,
            "chat_id": -100123,
            "allowed_modules": ["group_chat", "scheduled_broadcast"],
            "is_active": 1
        }

    Returns:
        { "ok": true, "msg": "路由已分配" }
    """
    try:
        payload = request.get_json(silent=True) or {}
        bot_id = payload.get("bot_id")
        chat_id = payload.get("chat_id")
        allowed_modules = payload.get("allowed_modules")
        is_active = payload.get("is_active", 1)

        # 参数校验
        if not isinstance(bot_id, int) or bot_id <= 0:
            return jsonify({"ok": False, "msg": "bot_id 必须为正整数"}), 400
        if not isinstance(chat_id, int):
            return jsonify({"ok": False, "msg": "chat_id 必须为整数"}), 400
        if not isinstance(allowed_modules, list) or not all(
            isinstance(m, str) for m in allowed_modules
        ):
            return jsonify({"ok": False, "msg": "allowed_modules 必须为字符串数组"}), 400
        if is_active not in (0, 1, True, False):
            return jsonify({"ok": False, "msg": "is_active 必须为 0/1"}), 400

        router = _get_router()
        ok = router.assign_bot(
            bot_id=bot_id,
            chat_id=chat_id,
            allowed_modules=allowed_modules,
            is_active=int(bool(is_active)),
        )
        if ok:
            return jsonify({"ok": True, "msg": "路由已分配"})
        return jsonify({"ok": False, "msg": "路由分配失败，请查看日志"}), 500
    except Exception as e:
        return jsonify({"ok": False, "msg": f"内部错误：{e}"}), 500


@bot_routing_bp.route("/remove", methods=["POST"])
@login_required
@admin_required
def api_bot_routing_remove():
    """删除路由（需 admin 权限）

    请求体 JSON：
        {
            "bot_id": 123,
            "chat_id": -100123
        }

    Returns:
        { "ok": true, "msg": "路由已删除" }
    """
    try:
        payload = request.get_json(silent=True) or {}
        bot_id = payload.get("bot_id")
        chat_id = payload.get("chat_id")

        if not isinstance(bot_id, int) or bot_id <= 0:
            return jsonify({"ok": False, "msg": "bot_id 必须为正整数"}), 400
        if not isinstance(chat_id, int):
            return jsonify({"ok": False, "msg": "chat_id 必须为整数"}), 400

        router = _get_router()
        ok = router.remove_routing(bot_id=bot_id, chat_id=chat_id)
        if ok:
            return jsonify({"ok": True, "msg": "路由已删除"})
        return jsonify({"ok": False, "msg": "路由删除失败，请查看日志"}), 500
    except Exception as e:
        return jsonify({"ok": False, "msg": f"内部错误：{e}"}), 500


@bot_routing_bp.route("/check", methods=["GET"])
@login_required
def api_bot_routing_check():
    """查询是否放行

    Query 参数：
        bot_id: Bot ID
        chat_id: 群组 chat_id
        module: 模块名

    Returns:
        {
            "ok": true,
            "data": {
                "allowed": true,
                "bot_id": 123,
                "chat_id": -100123,
                "module": "group_chat",
                "enabled": false,
                "default_policy": "allow"
            }
        }
    """
    try:
        bot_id = request.args.get("bot_id", type=int)
        chat_id = request.args.get("chat_id", type=int)
        module_name = request.args.get("module", type=str)

        if not bot_id or not chat_id or not module_name:
            return jsonify({"ok": False, "msg": "bot_id/chat_id/module 参数缺失"}), 400

        router = _get_router()
        allowed = router.should_handle(bot_id, chat_id, module_name)
        return jsonify({
            "ok": True,
            "data": {
                "allowed": allowed,
                "bot_id": bot_id,
                "chat_id": chat_id,
                "module": module_name,
                "enabled": router.enabled,
                "default_policy": router.default_policy,
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "msg": f"内部错误：{e}"}), 500
