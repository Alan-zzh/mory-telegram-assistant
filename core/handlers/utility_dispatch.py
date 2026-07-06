# -*- coding: utf-8 -*-
"""公共工具命令分发（消除 module_handlers 与 command_handlers 的重复路由）。

仅收纳两处 handler 中逐行重复的"工具类"命令（二维码/搜索/计算器/URL缩短/
Telegraph/贴纸工具/Echo/花式字体/强制订阅/置顶管理/提醒系统等）。
各 handler 独有的管理类命令（封禁、白名单、审批等）不在此列，仍留在原 handler。

调用方式（保持与原分支完全一致）：
    if dispatch_utility_commands(bot, msg, m, CONFIG, db):
        return True
其中 msg 为消息文本（dctx.text），m 为消息对象（dctx.msg）。
"""
from core.logging_util import clear_logging_context


def dispatch_utility_commands(bot, msg, m, CONFIG, db) -> bool:
    """分发公共工具命令；命中并返回 True（已处理），否则 False。"""
    if not msg:
        return False

    # 反频道转发
    if msg.startswith("/antichannel"):
        from modules.anti_channel import handle_antichannel
        handle_antichannel(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 二维码
    if msg.startswith("/qr"):
        from modules.qr_code import handle_qr_code
        handle_qr_code(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 搜索
    if msg.startswith("/google") or msg.startswith("搜索 "):
        from modules.search import handle_google
        handle_google(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg.startswith("/wiki") or msg.startswith("维基 "):
        from modules.search import handle_wiki
        handle_wiki(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 计算器
    if msg.startswith("/calc") or msg.startswith("计算 "):
        from modules.calculator import handle_calc
        handle_calc(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # URL缩短
    if msg.startswith("/shorten") or msg.startswith("短链 "):
        from modules.url_shortener import handle_shorten
        handle_shorten(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # Telegraph
    if msg.startswith("/telegraph"):
        from modules.telegraph import handle_telegraph
        handle_telegraph(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 贴纸工具
    if msg.startswith("/kang"):
        from modules.sticker_tools import handle_kang
        handle_kang(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg.startswith("/sticker2img") or msg.startswith("贴纸转图"):
        from modules.sticker_tools import handle_sticker2img
        handle_sticker2img(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # Echo复读
    if msg.startswith("/echo"):
        from modules.echo import handle_echo
        handle_echo(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 花式字体
    if msg.startswith("/fonts"):
        from modules.fancy_text import handle_font_list
        handle_font_list(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg.startswith("/font"):
        from modules.fancy_text import handle_fancy_text
        handle_fancy_text(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 强制订阅
    if msg.startswith("/fsub"):
        from modules.force_subscribe import handle_fsub
        handle_fsub(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 置顶管理
    if msg.startswith("/unpinall"):
        from modules.pin_manage import handle_unpinall
        handle_unpinall(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg.startswith("/unpin"):
        from modules.pin_manage import handle_unpin
        handle_unpin(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg.startswith("/pin"):
        from modules.pin_manage import handle_pin
        handle_pin(bot, m, CONFIG, db)
        clear_logging_context(); return True

    # 提醒系统
    if msg.startswith("/remind ") or msg.startswith("提醒 "):
        from modules.reminder import handle_remind
        handle_remind(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg.startswith("/reminders") or msg.startswith("提醒列表"):
        from modules.reminder import handle_reminders
        handle_reminders(bot, m, CONFIG, db)
        clear_logging_context(); return True
    if msg.startswith("/cancelremind") or msg.startswith("取消提醒"):
        from modules.reminder import handle_cancel_remind
        handle_cancel_remind(bot, m, CONFIG, db)
        clear_logging_context(); return True

    return False
