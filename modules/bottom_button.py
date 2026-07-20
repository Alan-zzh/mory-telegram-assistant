"""群组底部按钮模块
参考阿福后台：开启底部按钮、发送间隔小时数、底部键盘消息、删除键盘消息
"""
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

from core.logging_util import get_logger
from core.settings import get_config

try:
    config = get_config()
except Exception:
    config = {}
logger = get_logger(__name__)

BOTTOM_BUTTON_CONFIG = config.get('BOTTOM_BUTTON_CONFIG', {
    'enabled': False,
    'send_interval_hours': 12,
    'keyboard_messages': [],
    'delete_keyboard_message': True,
    'show_menu_button': True,
    'menu_title': '菜单',
})


class BottomButtonModule:
    def __init__(self):
        self._compat = None
        self._last_sent: Dict[int, datetime] = {}
        self._keyboard_message_ids: Dict[int, int] = {}

    async def send_bottom_button(self, chat_id: int):
        if not BOTTOM_BUTTON_CONFIG.get('enabled', False):
            return
        now = datetime.now()
        last_sent = self._last_sent.get(chat_id)
        if last_sent and (now - last_sent) < timedelta(hours=BOTTOM_BUTTON_CONFIG.get('send_interval_hours', 12)):
            return
        messages = BOTTOM_BUTTON_CONFIG.get('keyboard_messages', [])
        if not messages:
            return
        for msg_cfg in messages:
            text = msg_cfg.get('text', '')
            buttons = msg_cfg.get('buttons', [])
            if not text:
                continue
            keyboard = None
            if buttons:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(b.get('text', ''), url=b.get('url', ''), callback_data=b.get('callback', ''))]
                    for b in buttons
                ])
            try:
                msg = await self._compat.send_message(chat_id, text, reply_markup=keyboard)
                self._last_sent[chat_id] = now
                self._keyboard_message_ids[chat_id] = msg.message_id
                logger.info(f"[底部按钮] 发送到 chat={chat_id}: {text}")
            except Exception as e:
                logger.error(f"[底部按钮] 发送失败 chat={chat_id}: {e}")

    async def delete_keyboard(self, chat_id: int):
        if not BOTTOM_BUTTON_CONFIG.get('delete_keyboard_message', False):
            return
        msg_id = self._keyboard_message_ids.get(chat_id)
        if msg_id:
            try:
                await self._compat.delete_message(chat_id, msg_id)
                self._keyboard_message_ids.pop(chat_id, None)
                logger.info(f"[底部按钮] 删除键盘消息 chat={chat_id}")
            except Exception as e:
                logger.error(f"[底部按钮] 删除键盘失败 chat={chat_id}: {e}")
        else:
            try:
                await self._compat.send_message(chat_id, ' ', reply_markup=ReplyKeyboardRemove())
            except Exception as e:
                logger.error(f"[底部按钮] 删除键盘失败 chat={chat_id}: {e}")

    async def show_menu(self, chat_id: int):
        if not BOTTOM_BUTTON_CONFIG.get('show_menu_button', False):
            return
        menu_items = BOTTOM_BUTTON_CONFIG.get('menu_items', [])
        if not menu_items:
            return
        keyboard = ReplyKeyboardMarkup([[item] for item in menu_items], resize_keyboard=True)
        try:
            await self._compat.send_message(chat_id, BOTTOM_BUTTON_CONFIG.get('menu_title', '菜单'), reply_markup=keyboard)
            logger.info(f"[底部按钮] 显示菜单 chat={chat_id}")
        except Exception as e:
            logger.error(f"[底部按钮] 显示菜单失败 chat={chat_id}: {e}")

    async def hide_menu(self, chat_id: int):
        try:
            await self._compat.send_message(chat_id, ' ', reply_markup=ReplyKeyboardRemove())
            logger.info(f"[底部按钮] 隐藏菜单 chat={chat_id}")
        except Exception as e:
            logger.error(f"[底部按钮] 隐藏菜单失败 chat={chat_id}: {e}")

    async def process(self, update):
        return None


bottom_button_module = BottomButtonModule()