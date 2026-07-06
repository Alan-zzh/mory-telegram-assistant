# -*- coding: utf-8 -*-
"""
模块命令路由处理器 - P8.7/P8.8 模块级命令路由

包含：
- P8.7 新增模块命令路由（管理员权限/僵尸清理/不活跃清理/服务消息清理/命令控制/管理日志/翻译/反撤回/CAS检查/群信息修改/备份恢复/远程连接/互动游戏）
- P8.8 新增17模块命令路由（反刷屏/白名单/黑名单模式/置顶/强制订阅/反频道/二维码/搜索/计算器/URL缩短/Telegraph/贴纸工具/Echo复读/花式字体/提醒系统/投票创建/静默操作/NSFW检测/商城订单）
"""

from core.logging_util import get_logger, clear_logging_context
from core.handlers.command_handlers import _extract_uid, _get_admin_ids
from core.handlers.utility_dispatch import dispatch_utility_commands

logger = get_logger("module_handlers")


# ═══════════════════════════════════════════════════════════════════════
#  P8.7：新增模块命令路由
# ═══════════════════════════════════════════════════════════════════════

def handle_module_commands(dctx) -> bool:
    """P8.7 新增模块命令路由（管理员权限/僵尸清理/不活跃清理等）

    返回 True 表示命令已处理
    """
    msg = dctx.text
    if not dctx.is_group or not msg:
        return False

    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db

    # 管理员权限
    if msg.startswith("/promote") or msg.startswith("promote "):
        from modules.admin_promote import handle_promote
        target_uid = _extract_uid(msg.split()[1] if len(msg.split()) > 1 else "", m)
        if target_uid: handle_promote(bot, m, CONFIG, db, target_uid)
        clear_logging_context(); return True
    if msg.startswith("/demote") or msg.startswith("demote "):
        from modules.admin_promote import handle_demote
        target_uid = _extract_uid(msg.split()[1] if len(msg.split()) > 1 else "", m)
        if target_uid: handle_demote(bot, m, CONFIG, db, target_uid)
        clear_logging_context(); return True

    # 僵尸清理
    if msg.startswith("/zombies"):
        from modules.zombie_clean import handle_zombies
        handle_zombies(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 不活跃清理
    if msg.startswith("/ghost") or msg.startswith("/清理不活跃"):
        from modules.inactive_clean import handle_ghost
        handle_ghost(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 服务消息清理
    if msg.startswith("/cleanservice"):
        from modules.clean_service import handle_cleanservice
        handle_cleanservice(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 命令启用/禁用
    if msg.startswith("/disable") or msg.startswith("禁用 "):
        from modules.cmd_control import handle_disable
        handle_disable(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg.startswith("/enable") or msg.startswith("启用 "):
        from modules.cmd_control import handle_enable
        handle_enable(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg.startswith("/disabled"):
        from modules.cmd_control import handle_disabled
        handle_disabled(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 管理日志
    if msg.startswith("/adminlog") or msg.startswith("/管理日志"):
        from modules.admin_log import handle_adminlog
        handle_adminlog(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 翻译
    if msg.startswith("/tr"):
        from modules.translate import handle_translate
        handle_translate(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 反撤回
    if msg.startswith("/snipe"):
        from modules.antidelete import handle_snipe
        handle_snipe(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # CAS检查
    if msg.startswith("/cascheck"):
        from modules.spam_watch import handle_cascheck
        handle_cascheck(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 群信息修改
    if msg.startswith("/setgtitle"):
        from modules.group_info import handle_setgtitle
        handle_setgtitle(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg.startswith("/setdesc"):
        from modules.group_info import handle_setdesc
        handle_setdesc(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg.startswith("/setgpic"):
        from modules.group_info import handle_setgpic
        handle_setgpic(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 备份/恢复
    if msg.startswith("/backup"):
        from modules.group_backup import handle_backup
        handle_backup(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg.startswith("/restore"):
        from modules.group_backup import handle_restore
        handle_restore(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 远程连接
    if msg.startswith("/connect"):
        from modules.remote_connect import handle_connect
        handle_connect(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg.startswith("/disconnect"):
        from modules.remote_connect import handle_disconnect
        handle_disconnect(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 互动游戏
    if "真心话大冒险" in msg or msg.startswith("/truthordare") or msg.startswith("/tod"):
        from modules.games import handle_truth_or_dare
        handle_truth_or_dare(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg.startswith("猜数字") or msg.startswith("/guess"):
        from modules.games import handle_guess_number
        handle_guess_number(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if "骰子" in msg or msg.startswith("/dice") or "掷骰子" in msg:
        from modules.games import handle_dice
        handle_dice(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if "选择" in msg and "还是" in msg:
        from modules.games import handle_choose
        handle_choose(bot, m, CONFIG, db)
        clear_logging_context(); return True

    return False


# ═══════════════════════════════════════════════════════════════════════
#  P8.8：新增17模块命令路由
# ═══════════════════════════════════════════════════════════════════════

def handle_extended_commands(dctx) -> bool:
    """P8.8 新增17模块命令路由（反刷屏/白名单/黑名单模式/置顶/强制订阅等）

    返回 True 表示命令已处理
    """
    msg = dctx.text
    if not dctx.is_group or not msg:
        return False

    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db

    # 反刷屏设置
    if msg.startswith("/antiflood"):
        from modules.antiflood import handle_antiflood
        handle_antiflood(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 白名单管理
    if msg.startswith("/approve") or msg.startswith("白名单添加"):
        from modules.approvals import handle_approve
        handle_approve(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg.startswith("/disapprove") or msg.startswith("白名单移除"):
        from modules.approvals import handle_disapprove
        handle_disapprove(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg.startswith("/approved") or msg.startswith("白名单列表"):
        from modules.approvals import handle_approved_list
        handle_approved_list(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 黑名单模式
    if msg.startswith("/blocklistmode") or msg.startswith("黑名单模式"):
        from modules.blocklist_modes import handle_blocklist_mode
        handle_blocklist_mode(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 公共工具命令（与 command_handlers 共用，消除重复路由）
    if dispatch_utility_commands(bot, msg, m, CONFIG, db):
        return True


    # 投票创建
    if msg.startswith("/poll public"):
        from modules.poll_create import handle_poll_public
        handle_poll_public(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg.startswith("/poll"):
        from modules.poll_create import handle_poll
        handle_poll(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 静默操作
    if msg.startswith("/sban"):
        from modules.silent_actions import handle_sban
        handle_sban(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg.startswith("/smute"):
        from modules.silent_actions import handle_smute
        handle_smute(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg.startswith("/skick"):
        from modules.silent_actions import handle_skick
        handle_skick(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # NSFW检测
    if msg.startswith("/nsfw"):
        from modules.nsfw_detect import handle_nsfw_check, handle_nsfw_toggle
        parts = msg.split()
        if len(parts) >= 2 and parts[1].lower() in ("on", "off"):
            handle_nsfw_toggle(bot, m, CONFIG, db)
        else:
            handle_nsfw_check(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 商城订单管理（重复路由）
    if msg.startswith("发货 "):
        from modules.shop import handle_ship_order
        handle_ship_order(bot, m, CONFIG, db, msg[3:].strip())
        clear_logging_context(); return True
    if msg.startswith("完成订单 "):
        from modules.shop import handle_complete_order
        handle_complete_order(bot, m, CONFIG, db, msg[5:].strip())
        clear_logging_context(); return True
    if msg.startswith("退款 "):
        from modules.shop import handle_refund_order
        handle_refund_order(bot, m, CONFIG, db, msg[3:].strip())
        clear_logging_context(); return True
    if msg == "我的订单":
        from modules.shop import handle_my_orders
        handle_my_orders(bot, m, CONFIG, db)
        clear_logging_context(); return True

    return False
