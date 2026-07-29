# -*- coding: utf-8 -*-
"""管理员权限统一校验工具。

提供 get_admin_ids / is_admin_user，同时支持 ADMIN_ID（单值）和 ADMIN_IDS（列表）。
各模块共用此函数，避免出现 "只校验 ADMIN_ID 单值" 的不一致问题。
"""


def get_admin_ids(config: dict) -> list[int]:
    """获取完整的管理员 ID 列表（合并 ADMIN_ID 和 ADMIN_IDS）。

    Args:
        config: bot 配置字典

    Returns:
        合并后的管理员 ID 列表（去重）
    """
    if not isinstance(config, dict):
        return []
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    if isinstance(admin_ids, int):
        admin_ids = [admin_ids]
    if not isinstance(admin_ids, list):
        admin_ids = []
    if admin_id and admin_id not in admin_ids:
        admin_ids = list(admin_ids) + [admin_id]
    return admin_ids


def is_admin_user(config: dict, uid: int) -> bool:
    """统一的 admin 校验，同时支持 ADMIN_ID 和 ADMIN_IDS。

    Args:
        config: bot 配置字典，需包含 ADMIN_ID 和/或 ADMIN_IDS
        uid: 待校验的用户 ID

    Returns:
        True 表示该用户是管理员，False 表示不是。
    """
    return uid in get_admin_ids(config)
