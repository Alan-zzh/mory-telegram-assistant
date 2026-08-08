# -*- coding: utf-8 -*-
"""
modules/bot_broadcast_cleanup.py  ·  机器人垃圾播报自动清理

功能：
  删除指定机器人（如改名/更名检测机器人）在群里发的通知播报，
  避免"用户改了个名字"这类流水账消息堆积成垃圾消息。
  默认关闭，未配置任何机器人身份时不做任何删除（零误删风险）。

配置 LINKED_CHANNEL_SYNC_CONFIG 同级：BOT_BROADCAST_CLEANUP_CONFIG
  enabled:              总开关（默认 False）
  bot_ids:              机器人 user_id 列表（int）
  bot_names:            机器人名字关键词（用户名匹配子串，宽松匹配）
  keywords:             播报文本关键词（命中任一即清理）
  delete_delay_seconds: 删除延迟（秒，0=立即删除）

触发点：core/message_dispatcher.py  P0.8
返回 True 表示该消息已处理（阻止其进入积分/AI 等后续链路）。
删除是否真正执行受全局 ENABLE_MESSAGE_DELETION 总闸约束。
"""

import threading
import time

from core.helpers import can_delete_message
from core.logging_util import get_logger

logger = get_logger("bot_broadcast_cleanup")

_DEFAULT_CONFIG = {
    "enabled": False,
    "bot_ids": [],
    "bot_names": [],
    "keywords": ["改名", "更名", "昵称", "用户名已修改", "username has been changed"],
    "delete_delay_seconds": 0,
}


def _load_config(config: dict) -> dict:
    """读取模块配置，未知键缺失键回退默认值，保证字段齐全。"""
    raw = config or {}
    section = raw.get("BOT_BROADCAST_CLEANUP_CONFIG", {})
    if not isinstance(section, dict):
        section = {}
    cfg = dict(_DEFAULT_CONFIG)
    cfg.update({k: v for k, v in section.items() if k in _DEFAULT_CONFIG})
    return cfg


def _is_target_bot(cfg: dict, bot_id: int, bot_name: str) -> bool:
    """机器人身份命中：ID 精确匹配 或 名字关键词子串匹配。"""
    bot_ids = [int(b) for b in (cfg.get("bot_ids") or []) if str(b).lstrip("-").isdigit()]
    if bot_ids and bot_id in bot_ids:
        return True
    bot_name_lower = (bot_name or "").lower()
    for name in (cfg.get("bot_names") or []):
        if name and name.lower() in bot_name_lower:
            return True
    return False


def _hit_keyword(cfg: dict, text: str) -> bool:
    """播报文本是否命中关键词。"""
    text = text or ""
    return any(kw and kw in text for kw in (cfg.get("keywords") or []))


def check_and_clean_bot_broadcast(bot, m, config: dict, db) -> bool:
    """检查并清理机器人垃圾播报，返回 True 表示消息已被处理。

    只处理群聊中、发送方为机器人、身份与文本关键词同时命中的消息。
    """
    if not m or not getattr(m, "chat", None):
        return False
    if m.chat.type not in ("group", "supergroup"):
        return False

    cfg = _load_config(config)
    if not cfg.get("enabled"):
        return False

    from_user = getattr(m, "from_user", None)
    if not from_user:
        return False

    # 身份白名单为空 → 不清理任何机器人（防误删）
    if not (cfg.get("bot_ids") or cfg.get("bot_names")):
        return False

    text = m.text or getattr(m, "caption", "") or ""
    if not from_user.is_bot:
        return False
    if not _is_target_bot(cfg, from_user.id, from_user.first_name or ""):
        return False
    if not _hit_keyword(cfg, text):
        return False

    chat_id = m.chat.id
    message_id = getattr(m, "message_id", 0) or 0

    def _delete():
        try:
            bot.delete_message(chat_id, message_id)
            logger.info(f"🗑️ 机器人播报已清理: chat={chat_id} bot={from_user.id} msg={message_id} text='{text[:30]}'")
        except Exception as e:
            logger.debug(f"机器人播报删除失败（可能已删除/权限不足）: chat={chat_id} msg={message_id}: {e}")

    if can_delete_message(config):
        delay = float(cfg.get("delete_delay_seconds") or 0)
        if delay > 0:
            timer = threading.Timer(delay, _delete)
            timer.daemon = True
            timer.start()
        else:
            _delete()
    else:
        logger.warning(f"⚠️ 机器人播报命中但 ENABLE_MESSAGE_DELETION 未开启，跳过删除: bot={from_user.id} msg={message_id}")

    # 已处理的播报不再进入积分/AI/画像链路
    return True