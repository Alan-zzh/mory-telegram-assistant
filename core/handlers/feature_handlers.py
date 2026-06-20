# -*- coding: utf-8 -*-
"""
功能关键词处理器 - P8.5 新功能关键词触发

包含：
- 签到/补签/签到排行/签到日历
- 商城/兑换/上架/下架/订单
- 红包/抽奖/邀请排行
- 排行榜/统计/天气/汇率
- 积分增强（转账/记录/等级）
- 打赏/AFK/每日任务/成就
- 资料卡/盲盒/幸运转盘
- 沉默用户/互动排行
"""

from core.logging_util import get_logger, clear_logging_context

logger = get_logger("feature_handlers")


# ═══════════════════════════════════════════════════════════════════════
#  P8.5：新功能关键词触发
# ═══════════════════════════════════════════════════════════════════════

def handle_feature_keywords(dctx) -> bool:
    """P8.5 新功能关键词触发（签到/商城/红包/抽奖/排行/统计等）

    返回 True 表示关键词命令已处理
    """
    msg = dctx.text
    if not dctx.is_group or not msg:
        return False

    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db
    uid = dctx.uid
    uname = dctx.uname
    chat_id = dctx.chat_id

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

    return False
