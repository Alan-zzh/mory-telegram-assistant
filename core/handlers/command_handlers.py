# -*- coding: utf-8 -*-
"""
命令处理器 - P5/P6 优先级命令路由

包含：
- P5 机器人过滤
- P5.5 命令禁用检查
- P6 管理员指令（admin_cmds）
- P6.3 自然语言配置（natural_cmd）
- P6.4 欢迎/联邦定制
- P6.5 自定义命令
- P6.6 关键词触发
- P6.6 管理员专属新功能指令（认证/标签/备注/优惠券）
- P8.5 新功能关键词触发（签到/商城/红包/抽奖/排行/统计等）
- P8.6 高级群管功能命令
- P8.7 新增模块命令路由
- P8.8 新增17模块命令路由
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from core.logging_util import get_logger, clear_logging_context

if TYPE_CHECKING:
    from core.message_dispatcher import DispatchContext

logger = get_logger("command_handlers")


# ═══════════════════════════════════════════════════════════════════════
#  P5：机器人过滤 + P5.5 命令禁用
# ═══════════════════════════════════════════════════════════════════════

def check_bot_filter(dctx) -> bool:
    """P5 过滤野生机器人（用户名匹配IGNORE_BOTS列表）

    返回 True 表示消息来自被过滤的机器人
    """
    CONFIG = dctx.ctx.config
    uname = dctx.uname

    if any(b.lower() in uname.lower() for b in CONFIG.get("IGNORE_BOTS", [])):
        clear_logging_context()
        return True
    return False


def check_command_disabled(dctx) -> bool:
    """P5.5 命令禁用检查

    返回 True 表示命令已被禁用
    """
    msg = dctx.text
    if not dctx.is_group or not msg or not msg.startswith("/"):
        return False

    from modules.cmd_control import is_command_disabled

    db = dctx.ctx.db
    chat_id = dctx.chat_id

    try:
        cmd_parts = msg.split()[0].lstrip("/").split("@")[0].lower()
        if is_command_disabled(db, chat_id, cmd_parts):
            clear_logging_context()
            return True
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    return False


# ═══════════════════════════════════════════════════════════════════════
#  P6：管理员指令 + 自然语言配置
# ═══════════════════════════════════════════════════════════════════════

def handle_admin_commands(dctx) -> bool:
    """P6 管理员专属指令（含绑定主人）

    返回 True 表示管理员指令已处理
    """
    from modules.admin_cmds import handle_admin

    bot = dctx.ctx.bot
    mory_bot = dctx.ctx.mory_bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db
    ai = dctx.ctx.ai
    uid = dctx.uid
    msg = dctx.text

    admin_result = handle_admin(bot, mory_bot, m, CONFIG, db, ai, dctx.ctx.save_config)
    if admin_result:
        logger.info(f"👑 管理员指令执行成功 uid={uid} msg={msg[:30]}")
        clear_logging_context()
        return True
    return False


def handle_natural_admin(dctx) -> bool:
    """P6.3 自然语言配置（管理员可直接在TG里改，普通用户可看说明）

    返回 True 表示自然语言配置已处理
    """
    from modules.natural_cmd import handle_natural_admin

    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    mory_bot = dctx.ctx.mory_bot
    ad_detector = dctx.ctx.ad_detector
    uid = dctx.uid
    msg = dctx.text

    try:
        admin_ids = _get_admin_ids(CONFIG)
        is_admin_user = uid in admin_ids
        if handle_natural_admin(bot, m, CONFIG, dctx.ctx.save_config, mory_bot=mory_bot, is_admin=is_admin_user, ad_detector=ad_detector):
            logger.info(f"🗣️ 自然语言配置已处理 uid={uid} msg={msg[:30]}")
            clear_logging_context()
            return True
    except Exception as e:
        logger.error(f"🗣️ 自然语言配置处理异常: {e}")

    return False


# ═══════════════════════════════════════════════════════════════════════
#  P6.4：欢迎定制/联邦封禁指令
# ═══════════════════════════════════════════════════════════════════════

def handle_welcome_fed_commands(dctx) -> bool:
    """P6.4 欢迎定制/联邦封禁指令

    返回 True 表示指令已处理
    """
    msg = dctx.text
    if not msg.startswith("/") or not dctx.is_group:
        return False

    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db
    uid = dctx.uid

    try:
        admin_id = CONFIG.get("ADMIN_ID", 0)
        is_admin = (uid == admin_id)
        parts = msg.split()
        cmd = parts[0].lower()
        args = parts[1:]

        from modules.welcome_customization import (
            handle_set_welcome_command, handle_set_goodbye_command,
            handle_set_rules_command, handle_clean_welcome_command, handle_get_welcome_command
        )
        from modules.federation import handle_fban_command, handle_unfban_command, handle_feds_command

        if cmd in ("/setwelcome", "/setgoodbye", "/setrules", "/cleanwelcome", "/getwelcome"):
            if not is_admin:
                bot.reply_to(m, "❌ 只有管理员可以操作")
                clear_logging_context()
                return True
            if cmd == "/setwelcome":
                handle_set_welcome_command(bot, m, args, CONFIG, db)
            elif cmd == "/setgoodbye":
                handle_set_goodbye_command(bot, m, args, CONFIG, db)
            elif cmd == "/setrules":
                handle_set_rules_command(bot, m, args, CONFIG, db)
            elif cmd == "/cleanwelcome":
                handle_clean_welcome_command(bot, m, CONFIG, db)
            elif cmd == "/getwelcome":
                handle_get_welcome_command(bot, m, CONFIG, db)
            clear_logging_context()
            return True
        elif cmd == "/fban":
            if not is_admin:
                bot.reply_to(m, "❌ 只有管理员可以执行联邦封禁")
                clear_logging_context()
                return True
            handle_fban_command(bot, m, args, CONFIG, db)
            clear_logging_context()
            return True
        elif cmd == "/unfban":
            if not is_admin:
                bot.reply_to(m, "❌ 只有管理员可以解除联邦封禁")
                clear_logging_context()
                return True
            handle_unfban_command(bot, m, args, CONFIG, db)
            clear_logging_context()
            return True
        elif cmd == "/feds":
            if not is_admin:
                bot.reply_to(m, "❌ 只有管理员可以查询联邦封禁")
                clear_logging_context()
                return True
            handle_feds_command(bot, m, args, CONFIG, db)
            clear_logging_context()
            return True
    except Exception as e:
        logger.error(f"📦 欢迎/联邦指令处理异常: {e}")

    return False


# ═══════════════════════════════════════════════════════════════════════
#  P6.5：自定义命令 + P6.6：关键词触发
# ═══════════════════════════════════════════════════════════════════════

def check_custom_command(dctx) -> bool:
    """P6.5 自定义命令检测

    返回 True 表示自定义命令已触发
    """
    msg = dctx.text
    if not dctx.is_group or not msg or not msg.startswith("/"):
        return False

    from modules.custom_commands import check_custom_command

    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db
    uid = dctx.uid

    try:
        if check_custom_command(bot, m, CONFIG, db):
            logger.info(f"🔧 自定义命令触发 uid={uid} msg={msg[:30]}")
            clear_logging_context()
            return True
    except Exception as e:
        logger.debug(f"自定义命令检测异常: {e}")

    return False


def check_keyword_trigger(dctx) -> bool:
    """P6.6 关键词触发回复

    返回 True 表示关键词触发已处理
    """
    msg = dctx.text
    if not msg:
        return False

    CONFIG = dctx.ctx.config
    bot = dctx.ctx.bot
    m = dctx.msg
    uid = dctx.uid
    chat_id = dctx.chat_id
    keyword_trigger = dctx.ctx.keyword_trigger

    try:
        admin_id = CONFIG.get("ADMIN_ID", 0)
        is_admin = (uid == admin_id)
        if keyword_trigger.handle_message(msg, chat_id, m, bot, is_admin=is_admin):
            logger.info(f"🔑 关键词触发回复成功 uid={uid} msg={msg[:30]}")
            clear_logging_context()
            return True
    except Exception as e:
        logger.error(f"🔑 关键词触发检测异常: {e}")

    return False


# ═══════════════════════════════════════════════════════════════════════
#  P6.6：管理员专属新功能指令（认证/标签/备注/优惠券）
# ═══════════════════════════════════════════════════════════════════════

def handle_admin_feature_commands(dctx) -> bool:
    """P6.6 管理员专属新功能指令

    返回 True 表示指令已处理
    """
    msg = dctx.text
    if not dctx.is_group or not msg:
        return False

    CONFIG = dctx.ctx.config
    uid = dctx.uid
    admin_ids = _get_admin_ids(CONFIG)
    if uid not in admin_ids:
        return False

    from modules.certify import handle_certify, handle_uncertify
    from modules.user_tags import handle_add_tag, handle_add_note, handle_view_tags
    from modules.coupon import handle_generate_coupon, handle_claim_coupon, handle_redeem_coupon

    bot = dctx.ctx.bot
    m = dctx.msg
    db = dctx.ctx.db

    # 认证
    if msg.startswith("/certify "):
        target_uid = _extract_uid(msg[9:].strip(), m)
        if target_uid:
            handle_certify(bot, m, CONFIG, db, target_uid)
        clear_logging_context()
        return True
    if msg.startswith("/uncertify "):
        target_uid = _extract_uid(msg[11:].strip(), m)
        if target_uid:
            handle_uncertify(bot, m, CONFIG, db, target_uid)
        clear_logging_context()
        return True

    # 标签/备注
    if msg.startswith("标签 "):
        parts = msg[3:].strip().split(None, 1)
        if len(parts) >= 2:
            target_uid = _extract_uid(parts[0], m)
            if target_uid:
                handle_add_tag(bot, m, CONFIG, db, target_uid, parts[1])
        clear_logging_context()
        return True
    if msg.startswith("备注 "):
        parts = msg[3:].strip().split(None, 1)
        if len(parts) >= 2:
            target_uid = _extract_uid(parts[0], m)
            if target_uid:
                handle_add_note(bot, m, CONFIG, db, target_uid, parts[1])
        clear_logging_context()
        return True
    if msg.startswith("查看标签 "):
        target_uid = _extract_uid(msg[5:].strip(), m)
        if target_uid:
            handle_view_tags(bot, m, CONFIG, db, target_uid)
        clear_logging_context()
        return True

    # 优惠券
    if msg.startswith("生成优惠券 "):
        handle_generate_coupon(bot, m, CONFIG, db, msg[6:].strip().split())
        clear_logging_context()
        return True
    if msg.startswith("领券 "):
        handle_claim_coupon(bot, m, CONFIG, db, msg[3:].strip())
        clear_logging_context()
        return True
    if msg.startswith("核券 "):
        handle_redeem_coupon(bot, m, CONFIG, db, msg[3:].strip())
        clear_logging_context()
        return True

    # [TRAE SOLO CN] 追溯广告扫描
    if msg.startswith("/scan_ads"):
        import threading
        ad_detector = dctx.ctx.ad_detector
        admin_id = CONFIG.get("ADMIN_ID", 0)
        group_id = dctx.chat_id
        parts = msg.split()

        if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
            start_id = int(parts[1])
            end_id = int(parts[2])
        else:
            scan_range = CONFIG.get("RETROACTIVE_SCAN_RANGE", 200)
            try:
                test_msg = bot.send_message(group_id, ".", disable_notification=True)
                current_msg_id = test_msg.message_id
                bot.delete_message(group_id, current_msg_id)
                start_id = max(1, current_msg_id - scan_range)
                end_id = current_msg_id - 1
            except Exception as e:
                bot.reply_to(m, f"❌ 获取消息ID失败: {e}")
                clear_logging_context()
                return True

        bot.reply_to(m, f"🔍 开始追溯扫描 msg_id {start_id}~{end_id}...")

        def _do_scan():
            try:
                scan_result = ad_detector.retroactive_scan(bot, group_id, start_id, end_id, admin_id)
                report = (
                    f"🔍 追溯扫描完成\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"📊 扫描范围: {start_id}~{end_id}\n"
                    f"📋 扫描消息: {scan_result['scanned']}条\n"
                    f"🚫 发现广告: {scan_result['ads_found']}条\n"
                    f"🗑️ 删除成功: {scan_result['deleted']}条\n"
                    f"⚠️ 删除失败: {scan_result['failed']}条\n"
                    f"⏭️ 正常跳过: {scan_result['skipped']}条\n"
                    f"📭 不存在: {scan_result['not_found']}条"
                )
                if scan_result["failed"] > 0:
                    failed_items = [d for d in scan_result.get("details", []) if not d.get("deleted")]
                    for item in failed_items[:5]:
                        report += f"\n  ⚠️ msg_id={item['msg_id']}: {item.get('error', '未知')}"
                try:
                    bot.send_message(group_id, report)
                except Exception as e:
                    logger.debug(f"操作异常: {e}")
            except Exception as e:
                try:
                    bot.send_message(group_id, f"❌ 追溯扫描失败: {e}")
                except Exception as e:
                    logger.debug(f"操作异常: {e}")
        t = threading.Thread(target=_do_scan, daemon=True, name="scan_ads")
        t.start()
        clear_logging_context()
        return True

    return False


# ═══════════════════════════════════════════════════════════════════════
#  内部辅助函数
# ═══════════════════════════════════════════════════════════════════════

def _extract_uid(text, m=None):
    """从文本中提取用户ID，支持纯数字和@username格式"""
    text = text.strip()
    if text.isdigit():
        return int(text)
    if text.startswith("@") and m and m.reply_to_message:
        return m.reply_to_message.from_user.id
    if m and m.reply_to_message:
        return m.reply_to_message.from_user.id
    return None


def _get_admin_ids(CONFIG: dict) -> set:
    """获取管理员ID集合（ADMIN_IDS + ADMIN_ID）"""
    admin_ids = set(CONFIG.get("ADMIN_IDS", []) or [])
    admin_id = CONFIG.get("ADMIN_ID", 0)
    if admin_id:
        admin_ids.add(admin_id)
    return admin_ids


# ═══════════════════════════════════════════════════════════════════════
#  从 message_dispatcher.py 提取的命令处理器（P6.4 ~ P8.8）
# ═══════════════════════════════════════════════════════════════════════

def _handle_welcome_fed_commands(dctx: DispatchContext) -> bool:
    """P6.4 欢迎定制/联邦封禁指令"""
    m = dctx.msg
    ctx = dctx.ctx
    CONFIG = ctx.config
    db = ctx.db
    bot = ctx.bot
    msg = dctx.text
    uid = dctx.uid
    chat_id = dctx.chat_id
    is_group = dctx.is_group

    try:
        admin_id = CONFIG.get("ADMIN_ID", 0)
        is_admin = (uid == admin_id)
        parts = msg.split()
        cmd = parts[0].lower()
        args = parts[1:]

        from modules.welcome_customization import (
            handle_set_welcome_command, handle_set_goodbye_command,
            handle_set_rules_command, handle_clean_welcome_command, handle_get_welcome_command
        )
        from modules.federation import handle_fban_command, handle_unfban_command, handle_feds_command

        if cmd in ("/setwelcome", "/setgoodbye", "/setrules", "/cleanwelcome", "/getwelcome"):
            if not is_admin:
                bot.reply_to(m, "❌ 只有管理员可以操作")
                clear_logging_context()
                return True
            if cmd == "/setwelcome":
                handle_set_welcome_command(bot, m, args, CONFIG, db)
            elif cmd == "/setgoodbye":
                handle_set_goodbye_command(bot, m, args, CONFIG, db)
            elif cmd == "/setrules":
                handle_set_rules_command(bot, m, args, CONFIG, db)
            elif cmd == "/cleanwelcome":
                handle_clean_welcome_command(bot, m, CONFIG, db)
            elif cmd == "/getwelcome":
                handle_get_welcome_command(bot, m, CONFIG, db)
            clear_logging_context()
            return True
        elif cmd == "/fban":
            if not is_admin:
                bot.reply_to(m, "❌ 只有管理员可以执行联邦封禁")
                clear_logging_context()
                return True
            handle_fban_command(bot, m, args, CONFIG, db)
            clear_logging_context()
            return True
        elif cmd == "/unfban":
            if not is_admin:
                bot.reply_to(m, "❌ 只有管理员可以解除联邦封禁")
                clear_logging_context()
                return True
            handle_unfban_command(bot, m, args, CONFIG, db)
            clear_logging_context()
            return True
        elif cmd == "/feds":
            if not is_admin:
                bot.reply_to(m, "❌ 只有管理员可以查询联邦封禁")
                clear_logging_context()
                return True
            handle_feds_command(bot, m, args, CONFIG, db)
            clear_logging_context()
            return True
    except Exception as e:
        logger.error(f"📦 欢迎/联邦指令处理异常: {e}")

    return False


def _handle_admin_feature_commands(dctx: DispatchContext) -> bool:
    """P6.6 管理员专属新功能指令（认证/标签/备注/优惠券）"""
    m = dctx.msg
    ctx = dctx.ctx
    CONFIG = ctx.config
    db = ctx.db
    bot = ctx.bot
    msg = dctx.text
    uid = dctx.uid

    admin_ids = set(CONFIG.get("ADMIN_IDS", []) or [])
    admin_id = CONFIG.get("ADMIN_ID", 0)
    if admin_id:
        admin_ids.add(admin_id)
    is_admin_user = uid in admin_ids

    if not is_admin_user:
        return False

    from modules.certify import handle_certify, handle_uncertify
    from modules.user_tags import handle_add_tag, handle_add_note, handle_view_tags
    from modules.coupon import handle_generate_coupon, handle_claim_coupon, handle_redeem_coupon

    # 认证
    if msg.startswith("/certify "):
        target_uid = _extract_uid(msg[9:].strip(), m)
        if target_uid:
            handle_certify(bot, m, CONFIG, db, target_uid)
        clear_logging_context()
        return True
    if msg.startswith("/uncertify "):
        target_uid = _extract_uid(msg[11:].strip(), m)
        if target_uid:
            handle_uncertify(bot, m, CONFIG, db, target_uid)
        clear_logging_context()
        return True

    # 标签/备注
    if msg.startswith("标签 "):
        parts = msg[3:].strip().split(None, 1)
        if len(parts) >= 2:
            target_uid = _extract_uid(parts[0], m)
            if target_uid:
                handle_add_tag(bot, m, CONFIG, db, target_uid, parts[1])
        clear_logging_context()
        return True
    if msg.startswith("备注 "):
        parts = msg[3:].strip().split(None, 1)
        if len(parts) >= 2:
            target_uid = _extract_uid(parts[0], m)
            if target_uid:
                handle_add_note(bot, m, CONFIG, db, target_uid, parts[1])
        clear_logging_context()
        return True
    if msg.startswith("查看标签 "):
        target_uid = _extract_uid(msg[5:].strip(), m)
        if target_uid:
            handle_view_tags(bot, m, CONFIG, db, target_uid)
        clear_logging_context()
        return True

    # 优惠券
    if msg.startswith("生成优惠券 "):
        handle_generate_coupon(bot, m, CONFIG, db, msg[6:].strip().split())
        clear_logging_context()
        return True
    if msg.startswith("领券 "):
        handle_claim_coupon(bot, m, CONFIG, db, msg[3:].strip())
        clear_logging_context()
        return True
    if msg.startswith("核券 "):
        handle_redeem_coupon(bot, m, CONFIG, db, msg[3:].strip())
        clear_logging_context()
        return True

    return False


def _handle_feature_keywords(dctx: DispatchContext) -> bool:
    """P8.5 新功能关键词触发（签到/商城/红包/抽奖/排行/统计等）"""
    m = dctx.msg
    ctx = dctx.ctx
    CONFIG = ctx.config
    db = ctx.db
    bot = ctx.bot
    msg = dctx.text
    uid = dctx.uid
    uname = dctx.uname
    chat_id = dctx.chat_id
    is_group = dctx.is_group

    # 签到
    if msg in ("签到", "/签到", "打卡", "/checkin"):
        from modules.checkin import handle_checkin
        from modules.daily_quest import check_quest_completion
        handle_checkin(bot, m, CONFIG, db)
        try:
            check_quest_completion(db, uid, "checkin", CONFIG, bot, chat_id, uname)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        clear_logging_context()
        return True
    if msg in ("签到排行", "签到排名"):
        from modules.checkin import handle_checkin_rank
        handle_checkin_rank(bot, m, CONFIG, db)
        clear_logging_context()
        return True
    if msg == "补签":
        from modules.checkin import handle_makeup_checkin
        handle_makeup_checkin(bot, m, CONFIG, db)
        clear_logging_context()
        return True
    if msg == "签到日历":
        from modules.checkin import handle_checkin_calendar
        handle_checkin_calendar(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 商城
    if msg in ("商城", "/shop", "积分商城"):
        from modules.shop import handle_shop_list
        handle_shop_list(bot, m, CONFIG, db)
        clear_logging_context()
        return True
    if msg.startswith("兑换 "):
        from modules.shop import handle_exchange
        from modules.daily_quest import check_quest_completion
        handle_exchange(bot, m, CONFIG, db, msg[3:].strip())
        try:
            check_quest_completion(db, uid, "shop", CONFIG, bot, chat_id, uname)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        clear_logging_context()
        return True
    if msg.startswith("上架 "):
        from modules.shop import handle_shop_admin
        handle_shop_admin(bot, m, CONFIG, db, "add", msg[3:].strip().split())
        clear_logging_context()
        return True
    if msg.startswith("下架 "):
        from modules.shop import handle_shop_admin
        handle_shop_admin(bot, m, CONFIG, db, "remove", [msg[3:].strip()])
        clear_logging_context()
        return True
    if msg == "兑换记录":
        from modules.shop import handle_shop_admin
        handle_shop_admin(bot, m, CONFIG, db, "orders", [])
        clear_logging_context()
        return True
    if msg.startswith("发货 "):
        from modules.shop import handle_ship_order
        handle_ship_order(bot, m, CONFIG, db, msg[3:].strip())
        clear_logging_context()
        return True
    if msg.startswith("完成订单 "):
        from modules.shop import handle_complete_order
        handle_complete_order(bot, m, CONFIG, db, msg[5:].strip())
        clear_logging_context()
        return True
    if msg.startswith("退款 "):
        from modules.shop import handle_refund_order
        handle_refund_order(bot, m, CONFIG, db, msg[3:].strip())
        clear_logging_context()
        return True
    if msg == "我的订单":
        from modules.shop import handle_my_orders
        handle_my_orders(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 红包
    if msg.startswith("红包 "):
        from modules.redpacket import handle_send_redpacket
        handle_send_redpacket(bot, m, CONFIG, db, msg[3:].strip().split())
        clear_logging_context()
        return True

    # 抽奖
    if msg.startswith("抽奖 "):
        from modules.lottery import handle_create_lottery
        handle_create_lottery(bot, m, CONFIG, db, msg[3:].strip().split())
        clear_logging_context()
        return True

    # 邀请排行
    if msg in ("邀请排行", "邀请排名"):
        from modules.invite import handle_invite_rank
        handle_invite_rank(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 排行榜
    if msg.startswith("排行"):
        from modules.ranking import handle_ranking
        dimension = msg[2:].strip() if len(msg) > 2 else ""
        handle_ranking(bot, m, CONFIG, db, dimension)
        clear_logging_context()
        return True

    # 统计
    if msg in ("我的统计", "/mystats"):
        from modules.speech_stats import handle_my_stats
        handle_my_stats(bot, m, CONFIG, db)
        clear_logging_context()
        return True
    if msg in ("群统计", "/groupstats"):
        from modules.speech_stats import handle_group_stats
        handle_group_stats(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 天气查询
    if msg.endswith("天气") and len(msg) > 2:
        from modules.weather import handle_weather_query
        city = msg[:-2].strip()
        handle_weather_query(bot, m, CONFIG, db, city)
        clear_logging_context()
        return True

    # 汇率查询
    if "汇率" in msg:
        from modules.exchange_rate import handle_exchange_rate
        handle_exchange_rate(bot, m, CONFIG, db, msg.replace("汇率", "").strip())
        clear_logging_context()
        return True

    # 积分增强
    if msg.startswith("转账 "):
        from modules.points_enhanced import handle_transfer
        handle_transfer(bot, m, CONFIG, db, msg[3:].strip().split())
        clear_logging_context()
        return True
    if msg in ("积分记录", "积分日志"):
        from modules.points_enhanced import handle_points_log
        handle_points_log(bot, m, CONFIG, db)
        clear_logging_context()
        return True
    if msg in ("等级", "我的等级"):
        from modules.points_enhanced import handle_level_info
        handle_level_info(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 打赏
    if msg.startswith("打赏 ") or msg.startswith("打赏"):
        from modules.tip import handle_tip
        from modules.daily_quest import check_quest_completion
        handle_tip(bot, m, CONFIG, db, msg[3:].strip() if len(msg) > 3 else "")
        try:
            check_quest_completion(db, uid, "tip", CONFIG, bot, chat_id, uname)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        clear_logging_context()
        return True
    if msg in ("打赏排行", "打赏排名"):
        from modules.tip import handle_tip_rank
        handle_tip_rank(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # AFK
    if msg.startswith("afk") or msg.startswith("AFK") or msg.startswith("Afk"):
        from modules.afk import handle_set_afk
        reason = msg[3:].strip() if len(msg) > 3 else ""
        handle_set_afk(bot, m, CONFIG, db, reason)
        clear_logging_context()
        return True

    # 每日任务
    if msg in ("每日任务", "任务", "/quest"):
        from modules.daily_quest import handle_daily_quest
        handle_daily_quest(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 成就
    if msg in ("我的成就", "成就", "/achievements"):
        from modules.achievement import handle_my_achievements
        handle_my_achievements(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 资料卡
    if msg in ("我的", "资料卡", "/profile"):
        from modules.profile_card import handle_profile_card
        handle_profile_card(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 盲盒
    if msg in ("盲盒", "扭蛋", "/blindbox"):
        from modules.blind_box import handle_blind_box
        handle_blind_box(bot, m, CONFIG, db)
        clear_logging_context()
        return True
    if msg.startswith("盲盒设置 "):
        from modules.blind_box import handle_blind_box_admin
        handle_blind_box_admin(bot, m, CONFIG, db, msg[5:].strip().split())
        clear_logging_context()
        return True

    # 幸运转盘
    if msg.startswith("转盘"):
        from modules.lucky_wheel import handle_lucky_wheel
        args = msg[2:].strip() if len(msg) > 2 else ""
        handle_lucky_wheel(bot, m, CONFIG, db, args)
        clear_logging_context()
        return True
    if msg in ("转盘记录", "转盘历史"):
        from modules.lucky_wheel import handle_wheel_history
        handle_wheel_history(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 补签（重复路由）
    if msg in ("补签", "/makeup"):
        from modules.checkin import handle_makeup_checkin
        handle_makeup_checkin(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 签到日历（重复路由）
    if msg in ("签到日历", "签到记录"):
        from modules.checkin import handle_checkin_calendar
        handle_checkin_calendar(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 沉默用户
    if msg in ("沉默用户", "/silent"):
        from modules.speech_stats import handle_silent_users
        handle_silent_users(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 互动排行
    if msg in ("互动排行", "互动排名"):
        from modules.speech_stats import handle_interaction_rank
        handle_interaction_rank(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # ── P8.6：高级群管功能命令 ──
    if _handle_group_admin_commands(dctx):
        return True

    # ── P8.7：新增模块命令路由 ──
    if _handle_module_commands(dctx):
        return True

    # ── P8.8：新增17模块命令路由 ──
    if _handle_extended_commands(dctx):
        return True

    # 商城订单管理（重复路由）
    if msg.startswith("发货 "):
        from modules.shop import handle_ship_order
        handle_ship_order(bot, m, CONFIG, db, msg[3:].strip())
        clear_logging_context()
        return True
    if msg.startswith("完成订单 "):
        from modules.shop import handle_complete_order
        handle_complete_order(bot, m, CONFIG, db, msg[5:].strip())
        clear_logging_context()
        return True
    if msg.startswith("退款 "):
        from modules.shop import handle_refund_order
        handle_refund_order(bot, m, CONFIG, db, msg[3:].strip())
        clear_logging_context()
        return True
    if msg == "我的订单":
        from modules.shop import handle_my_orders
        handle_my_orders(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    return False


def _handle_group_admin_commands(dctx: DispatchContext) -> bool:
    """P8.6 高级群管功能命令（警告/消息删除/锁群/慢速/举报/群规等）"""
    m = dctx.msg
    ctx = dctx.ctx
    CONFIG = ctx.config
    db = ctx.db
    bot = ctx.bot
    msg = dctx.text
    uid = dctx.uid
    chat_id = dctx.chat_id

    # 警告系统
    if msg.startswith("警告 ") or msg.startswith("/warn "):
        from modules.warning import handle_warn
        parts = msg.split(None, 2)
        target_uid = _extract_uid(parts[1] if len(parts) > 1 else "", m)
        reason = parts[2] if len(parts) > 2 else ""
        if target_uid:
            handle_warn(bot, m, CONFIG, db, target_uid, reason)
        else:
            bot.reply_to(m, "❌ 无法识别目标用户，请回复用户消息或使用 @用户名")
        clear_logging_context()
        return True
    if msg.startswith("查看警告 "):
        from modules.warning import handle_warn_list
        target_uid = _extract_uid(msg[5:].strip(), m)
        if target_uid:
            handle_warn_list(bot, m, CONFIG, db, target_uid)
        clear_logging_context()
        return True
    if msg.startswith("清除警告 "):
        from modules.warning import handle_warn_reset
        target_uid = _extract_uid(msg[5:].strip(), m)
        if target_uid:
            handle_warn_reset(bot, m, CONFIG, db, target_uid)
        clear_logging_context()
        return True

    # 消息删除
    if msg.startswith("/purge ") and m.reply_to_message:
        from modules.message_clean import handle_purge
        handle_purge(bot, m, CONFIG, db, msg[7:].strip())
        clear_logging_context()
        return True
    if msg == "/del" and m.reply_to_message:
        from modules.message_clean import handle_del
        handle_del(bot, m, CONFIG, db)
        clear_logging_context()
        return True
    if msg == "/purgeto" and m.reply_to_message:
        from modules.message_clean import handle_purge_to
        handle_purge_to(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 锁群
    if msg.startswith("锁 "):
        from modules.message_locks import handle_lock
        handle_lock(bot, m, CONFIG, db, msg[2:].strip())
        clear_logging_context()
        return True
    if msg.startswith("解锁 "):
        from modules.message_locks import handle_unlock
        handle_unlock(bot, m, CONFIG, db, msg[3:].strip())
        clear_logging_context()
        return True
    if msg in ("锁定列表", "/locktypes"):
        from modules.message_locks import handle_lock_list
        handle_lock_list(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 慢速模式
    if msg.startswith("慢速 "):
        from modules.slow_mode import handle_slow_mode
        handle_slow_mode(bot, m, CONFIG, db, msg[3:].strip())
        clear_logging_context()
        return True

    # 举报
    from modules.report import check_report_command, handle_report
    if check_report_command(m):
        handle_report(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 群规
    if msg in ("/rules", "群规"):
        try:
            row = db.conn.execute("SELECT rules_text FROM welcome_configs WHERE chat_id=?", (chat_id,)).fetchone()
            if row and row[0]:
                bot.reply_to(m, f"📋 群规\n\n{row[0]}")
            else:
                bot.reply_to(m, "📋 暂未设置群规，管理员可使用 /setrules 设置")
        except Exception:
            bot.reply_to(m, "📋 暂未设置群规")
        clear_logging_context()
        return True

    # 用户信息
    if msg in ("/info", "/whois") and m.reply_to_message:
        from modules.user_info import handle_user_info
        handle_user_info(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 置顶管理
    if msg == "/pin" and m.reply_to_message:
        try:
            bot.pin_chat_message(chat_id, m.reply_to_message.message_id, disable_notification=True)
            bot.reply_to(m, "📌 已置顶")
        except Exception as e:
            bot.reply_to(m, f"❌ 置顶失败：{e}")
        clear_logging_context()
        return True
    if msg == "/unpin":
        try:
            bot.unpin_chat_message(chat_id)
            bot.reply_to(m, "📌 已取消置顶")
        except Exception as e:
            bot.reply_to(m, f"❌ 取消置顶失败：{e}")
        clear_logging_context()
        return True
    if msg == "/unpinall":
        try:
            bot.unpin_all_chat_messages(chat_id)
            bot.reply_to(m, "📌 已取消所有置顶")
        except Exception as e:
            bot.reply_to(m, f"❌ 取消所有置顶失败：{e}")
        clear_logging_context()
        return True

    # 投票踢人
    if msg.startswith("/votekick "):
        from modules.vote_kick import handle_vote_kick
        parts = msg.split(None, 2)
        target_uid = _extract_uid(parts[1] if len(parts) > 1 else "", m)
        reason = parts[2] if len(parts) > 2 else ""
        if target_uid:
            handle_vote_kick(bot, m, CONFIG, db, target_uid, reason)
        else:
            bot.reply_to(m, "❌ 无法识别目标用户")
        clear_logging_context()
        return True

    # 群组笔记
    if msg.startswith("#save "):
        from modules.group_notes import handle_save_note
        parts = msg[6:].strip().split(None, 1)
        if len(parts) >= 2:
            handle_save_note(bot, m, CONFIG, db, parts[0], parts[1])
        else:
            bot.reply_to(m, "❌ 格式：#save 笔记名 内容")
        clear_logging_context()
        return True
    if msg.startswith("#get "):
        from modules.group_notes import handle_get_note
        handle_get_note(bot, m, CONFIG, db, msg[5:].strip())
        clear_logging_context()
        return True
    if msg in ("#notes", "#列表"):
        from modules.group_notes import handle_notes_list
        handle_notes_list(bot, m, CONFIG, db)
        clear_logging_context()
        return True
    if msg.startswith("#del "):
        from modules.group_notes import handle_del_note
        handle_del_note(bot, m, CONFIG, db, msg[5:].strip())
        clear_logging_context()
        return True
    # #笔记名 快捷获取
    if msg.startswith("#") and len(msg) > 1 and not msg.startswith("#save") and not msg.startswith("#del"):
        from modules.group_notes import handle_get_note
        note_name = msg[1:].strip()
        if note_name and note_name not in ("notes", "列表"):
            handle_get_note(bot, m, CONFIG, db, note_name)
            clear_logging_context()
            return True

    # 定时消息
    if msg.startswith("定时 "):
        from modules.scheduled_msg import handle_schedule_msg
        parts = msg[3:].strip().split(None, 1)
        if len(parts) >= 2:
            handle_schedule_msg(bot, m, CONFIG, db, parts[0], parts[1])
        else:
            bot.reply_to(m, "❌ 格式：定时 HH:MM 内容")
        clear_logging_context()
        return True
    if msg == "定时列表":
        from modules.scheduled_msg import handle_schedule_list
        handle_schedule_list(bot, m, CONFIG, db)
        clear_logging_context()
        return True
    if msg.startswith("定时删除 "):
        from modules.scheduled_msg import handle_schedule_delete
        handle_schedule_delete(bot, m, CONFIG, db, msg[5:].strip())
        clear_logging_context()
        return True

    # 自定义命令
    if msg.startswith("创建命令 "):
        from modules.custom_commands import handle_create_command
        parts = msg[5:].strip().split(None, 1)
        if len(parts) >= 2:
            handle_create_command(bot, m, CONFIG, db, parts[0], parts[1])
        else:
            bot.reply_to(m, "❌ 格式：创建命令 /命令名 回复内容")
        clear_logging_context()
        return True
    if msg.startswith("删除命令 "):
        from modules.custom_commands import handle_delete_command
        handle_delete_command(bot, m, CONFIG, db, msg[5:].strip())
        clear_logging_context()
        return True
    if msg == "命令列表":
        from modules.custom_commands import handle_commands_list
        handle_commands_list(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 可视化数据面板
    if msg in ("数据面板", "/dashboard"):
        from modules.visual_dashboard import handle_group_dashboard
        handle_group_dashboard(bot, m, CONFIG, db)
        clear_logging_context()
        return True
    if msg == "我的数据":
        from modules.visual_dashboard import handle_personal_dashboard
        handle_personal_dashboard(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    return False


def _handle_module_commands(dctx: DispatchContext) -> bool:
    """P8.7 新增模块命令路由（管理员权限/僵尸清理/不活跃清理等）"""
    m = dctx.msg
    ctx = dctx.ctx
    CONFIG = ctx.config
    db = ctx.db
    bot = ctx.bot
    msg = dctx.text
    uid = dctx.uid

    # 管理员权限
    if msg and (msg.startswith("/promote") or msg.startswith("promote ")):
        from modules.admin_promote import handle_promote
        target_uid = _extract_uid(msg.split()[1] if len(msg.split()) > 1 else "", m)
        if target_uid: handle_promote(bot, m, CONFIG, db, target_uid)
        clear_logging_context(); return True
    if msg and (msg.startswith("/demote") or msg.startswith("demote ")):
        from modules.admin_promote import handle_demote
        target_uid = _extract_uid(msg.split()[1] if len(msg.split()) > 1 else "", m)
        if target_uid: handle_demote(bot, m, CONFIG, db, target_uid)
        clear_logging_context(); return True

    # 僵尸清理
    if msg and msg.startswith("/zombies"):
        from modules.zombie_clean import handle_zombies
        handle_zombies(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 不活跃清理
    if msg and (msg.startswith("/ghost") or msg.startswith("/清理不活跃")):
        from modules.inactive_clean import handle_ghost
        handle_ghost(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 服务消息清理
    if msg and msg.startswith("/cleanservice"):
        from modules.clean_service import handle_cleanservice
        handle_cleanservice(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 命令启用/禁用
    if msg and (msg.startswith("/disable") or msg.startswith("禁用 ")):
        from modules.cmd_control import handle_disable
        handle_disable(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and (msg.startswith("/enable") or msg.startswith("启用 ")):
        from modules.cmd_control import handle_enable
        handle_enable(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and msg.startswith("/disabled"):
        from modules.cmd_control import handle_disabled
        handle_disabled(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 管理日志
    if msg and (msg.startswith("/adminlog") or msg.startswith("/管理日志")):
        from modules.admin_log import handle_adminlog
        handle_adminlog(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 翻译
    if msg and msg.startswith("/tr"):
        from modules.translate import handle_translate
        handle_translate(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 反撤回
    if msg and msg.startswith("/snipe"):
        from modules.antidelete import handle_snipe
        handle_snipe(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # CAS检查
    if msg and msg.startswith("/cascheck"):
        from modules.spam_watch import handle_cascheck
        handle_cascheck(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 群信息修改
    if msg and msg.startswith("/setgtitle"):
        from modules.group_info import handle_setgtitle
        handle_setgtitle(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and msg.startswith("/setdesc"):
        from modules.group_info import handle_setdesc
        handle_setdesc(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and msg.startswith("/setgpic"):
        from modules.group_info import handle_setgpic
        handle_setgpic(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 备份/恢复
    if msg and msg.startswith("/backup"):
        from modules.group_backup import handle_backup
        handle_backup(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and msg.startswith("/restore"):
        from modules.group_backup import handle_restore
        handle_restore(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 远程连接
    if msg and msg.startswith("/connect"):
        from modules.remote_connect import handle_connect
        handle_connect(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and msg.startswith("/disconnect"):
        from modules.remote_connect import handle_disconnect
        handle_disconnect(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 互动游戏
    if msg and ("真心话大冒险" in msg or msg.startswith("/truthordare") or msg.startswith("/tod")):
        from modules.games import handle_truth_or_dare
        handle_truth_or_dare(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and (msg.startswith("猜数字") or msg.startswith("/guess")):
        from modules.games import handle_guess_number
        handle_guess_number(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and ("骰子" in msg or msg.startswith("/dice") or "掷骰子" in msg):
        from modules.games import handle_dice
        handle_dice(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and ("选择" in msg and "还是" in msg):
        from modules.games import handle_choose
        handle_choose(bot, m, CONFIG, db)
        clear_logging_context(); return True

    return False


def _handle_extended_commands(dctx: DispatchContext) -> bool:
    """P8.8 新增17模块命令路由（反刷屏/白名单/黑名单模式/置顶/强制订阅等）"""
    m = dctx.msg
    ctx = dctx.ctx
    CONFIG = ctx.config
    db = ctx.db
    bot = ctx.bot
    msg = dctx.text

    # 反刷屏设置
    if msg and msg.startswith("/antiflood"):
        from modules.antiflood import handle_antiflood
        handle_antiflood(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 白名单管理
    if msg and (msg.startswith("/approve") or msg.startswith("白名单添加")):
        from modules.approvals import handle_approve
        handle_approve(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and (msg.startswith("/disapprove") or msg.startswith("白名单移除")):
        from modules.approvals import handle_disapprove
        handle_disapprove(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and (msg.startswith("/approved") or msg.startswith("白名单列表")):
        from modules.approvals import handle_approved_list
        handle_approved_list(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 黑名单模式
    if msg and (msg.startswith("/blocklistmode") or msg.startswith("黑名单模式")):
        from modules.blocklist_modes import handle_blocklist_mode
        handle_blocklist_mode(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 误封解封：支持回复、用户ID、@username
    if msg and (
        msg.startswith("/unban")
        or msg.startswith("/解封")
        or msg.startswith("解封 ")
        or msg == "解封"
        or msg.startswith("解除封禁")
    ):
        from modules.ad_enforcement import handle_unban_command
        handle_unban_command(bot, m, CONFIG, db, ad_detector=getattr(ctx, "ad_detector", None))
        clear_logging_context(); return True

    # 置顶管理
    if msg and msg.startswith("/unpinall"):
        from modules.pin_manage import handle_unpinall
        handle_unpinall(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and msg.startswith("/unpin"):
        from modules.pin_manage import handle_unpin
        handle_unpin(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and msg.startswith("/pin"):
        from modules.pin_manage import handle_pin
        handle_pin(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 强制订阅
    if msg and msg.startswith("/fsub"):
        from modules.force_subscribe import handle_fsub
        handle_fsub(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and msg.startswith("/unfsub"):
        from modules.force_subscribe import handle_unforce_subscribe
        handle_unforce_subscribe(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 全局黑名单
    if msg and msg.startswith("/gbanlist"):
        from modules.global_blacklist import handle_gban_list
        handle_gban_list(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and msg.startswith("/gban"):
        from modules.global_blacklist import handle_gban
        handle_gban(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and msg.startswith("/ungban"):
        from modules.global_blacklist import handle_ungban
        handle_ungban(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 反频道转发
    if msg and msg.startswith("/antichannel"):
        from modules.anti_channel import handle_antichannel
        handle_antichannel(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 二维码
    if msg and msg.startswith("/qr"):
        from modules.qr_code import handle_qr_code
        handle_qr_code(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 搜索
    if msg and (msg.startswith("/google") or msg.startswith("搜索 ")):
        from modules.search import handle_google
        handle_google(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and (msg.startswith("/wiki") or msg.startswith("维基 ")):
        from modules.search import handle_wiki
        handle_wiki(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 计算器
    if msg and (msg.startswith("/calc") or msg.startswith("计算 ")):
        from modules.calculator import handle_calc
        handle_calc(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # URL缩短
    if msg and (msg.startswith("/shorten") or msg.startswith("短链 ")):
        from modules.url_shortener import handle_shorten
        handle_shorten(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # Telegraph
    if msg and msg.startswith("/telegraph"):
        from modules.telegraph import handle_telegraph
        handle_telegraph(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 贴纸工具
    if msg and msg.startswith("/kang"):
        from modules.sticker_tools import handle_kang
        handle_kang(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and (msg.startswith("/sticker2img") or msg.startswith("贴纸转图")):
        from modules.sticker_tools import handle_sticker2img
        handle_sticker2img(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # Echo复读
    if msg and msg.startswith("/echo"):
        from modules.echo import handle_echo
        handle_echo(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 花式字体
    if msg and msg.startswith("/fonts"):
        from modules.fancy_text import handle_font_list
        handle_font_list(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and msg.startswith("/font"):
        from modules.fancy_text import handle_fancy_text
        handle_fancy_text(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 提醒系统
    if msg and (msg.startswith("/remind ") or msg.startswith("提醒 ")):
        from modules.reminder import handle_remind
        handle_remind(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and (msg.startswith("/reminders") or msg.startswith("提醒列表")):
        from modules.reminder import handle_reminders
        handle_reminders(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and (msg.startswith("/cancelremind") or msg.startswith("取消提醒")):
        from modules.reminder import handle_cancel_remind
        handle_cancel_remind(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 投票创建
    if msg and msg.startswith("/poll public"):
        from modules.poll_create import handle_poll_public
        handle_poll_public(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and msg.startswith("/poll"):
        from modules.poll_create import handle_poll
        handle_poll(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 静默操作
    if msg and msg.startswith("/sban"):
        from modules.silent_actions import handle_sban
        handle_sban(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and msg.startswith("/smute"):
        from modules.silent_actions import handle_smute
        handle_smute(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg and msg.startswith("/skick"):
        from modules.silent_actions import handle_skick
        handle_skick(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # NSFW检测
    if msg and msg.startswith("/nsfw"):
        from modules.nsfw_detect import handle_nsfw_check, handle_nsfw_toggle
        parts = msg.split()
        if len(parts) >= 2 and parts[1].lower() in ("on", "off"):
            handle_nsfw_toggle(bot, m, CONFIG, db)
        else:
            handle_nsfw_check(bot, m, CONFIG, db)
        clear_logging_context(); return True

    return False
