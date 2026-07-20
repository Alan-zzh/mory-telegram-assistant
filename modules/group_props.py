"""群组道具模块
参考阿福后台：管理和使用群组道具，如置顶卡、禁言豁免卡等
"""
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

from core.logging_util import get_logger
from core.settings import get_config

try:
    config = get_config()
except Exception:
    config = {}
logger = get_logger(__name__)

GROUP_PROPS_CONFIG = config.get('GROUP_PROPS_CONFIG', {
    'enabled': False,
    'props': [
        {'name': '置顶卡', 'description': '置顶一条消息', 'effect_type': 'pin'},
        {'name': '禁言豁免卡', 'description': '解除禁言状态', 'effect_type': 'unmute'},
        {'name': '发言加速卡', 'description': '减少发言间隔', 'effect_type': 'speed'},
        {'name': '防踢卡', 'description': '防止被踢出群', 'effect_type': 'protect'},
        {'name': '群名片修改卡', 'description': '修改群名片', 'effect_type': 'nickname'},
    ],
})


class GroupPropsModule:
    def __init__(self):
        self._db = None
        self._compat = None

    def grant_prop(self, user_id: int, prop_name: str, count: int = 1) -> bool:
        if not GROUP_PROPS_CONFIG.get('enabled', False):
            return False
        try:
            self._add_user_prop(user_id, prop_name, count)
            logger.info(f"[群组道具] 授予用户 {user_id}: {prop_name} x{count}")
            return True
        except Exception as e:
            logger.error(f"[群组道具] 授予失败: {e}")
            return False

    def use_prop(self, user_id: int, prop_name: str, chat_id: int = None,
                 message_id: int = None, custom_title: str = None) -> bool:
        if not GROUP_PROPS_CONFIG.get('enabled', False):
            return False
        if not self._has_prop(user_id, prop_name):
            return False
        try:
            self._consume_user_prop(user_id, prop_name)
            self._apply_prop_effect(user_id, prop_name, chat_id, message_id, custom_title)
            logger.info(f"[群组道具] 用户 {user_id} 使用: {prop_name}")
            return True
        except Exception as e:
            logger.error(f"[群组道具] 使用失败: {e}")
            return False

    def get_user_props(self, user_id: int) -> List[Dict[str, Any]]:
        if not GROUP_PROPS_CONFIG.get('enabled', False):
            return []
        try:
            return self._query_user_props(user_id)
        except Exception as e:
            logger.error(f"[群组道具] 查询失败: {e}")
            return []

    def get_all_props(self) -> List[Dict[str, Any]]:
        return GROUP_PROPS_CONFIG.get('props', [])

    def get_prop_info(self, prop_name: str) -> Optional[Dict[str, Any]]:
        props = GROUP_PROPS_CONFIG.get('props', [])
        return next((p for p in props if p['name'] == prop_name), None)

    def _add_user_prop(self, user_id: int, prop_name: str, count: int):
        try:
            self._db.conn.execute(
                'INSERT OR REPLACE INTO user_props (user_id, prop_name, count) VALUES (?, ?, COALESCE((SELECT count FROM user_props WHERE user_id = ? AND prop_name = ?), 0) + ?)',
                (user_id, prop_name, user_id, prop_name, count)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[群组道具] 添加道具失败: {e}")
            raise

    def _consume_user_prop(self, user_id: int, prop_name: str):
        try:
            cursor = self._db.conn.execute(
                'UPDATE user_props SET count = count - 1 WHERE user_id = ? AND prop_name = ? AND count > 0',
                (user_id, prop_name)
            )
            if cursor.rowcount == 0:
                raise ValueError(f"用户 {user_id} 没有可用的 {prop_name}")
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[群组道具] 消耗道具失败: {e}")
            raise

    def _has_prop(self, user_id: int, prop_name: str) -> bool:
        try:
            cursor = self._db.conn.execute(
                'SELECT count FROM user_props WHERE user_id = ? AND prop_name = ? AND count > 0',
                (user_id, prop_name)
            )
            row = cursor.fetchone()
            return row is not None and row[0] > 0
        except Exception as e:
            logger.error(f"[群组道具] 检查道具失败: {e}")
            return False

    def _apply_prop_effect(self, user_id: int, prop_name: str, chat_id: int,
                          message_id: int = None, custom_title: str = None):
        prop_info = self.get_prop_info(prop_name)
        if not prop_info:
            return
        effect_type = prop_info.get('effect_type', '')
        try:
            if effect_type == 'pin' and chat_id:
                # 修复 P1：原实现把 user_id 当 message_id 传给 pin_chat_message（API 签名错误）
                # pin_chat_message(chat_id, message_id) 需要 message_id 参数
                if not message_id:
                    logger.warning(f"[群组道具] pin 效果需要 message_id 参数，跳过 user={user_id}")
                    return
                if hasattr(self._compat, 'pin_chat_message'):
                    self._compat.pin_chat_message(chat_id, message_id)
                else:
                    logger.info(f"[群组道具] pin 效果未实现 _compat.pin_chat_message，跳过 user={user_id}")
            elif effect_type == 'unmute' and chat_id:
                if hasattr(self._compat, 'unban_chat_member'):
                    self._compat.unban_chat_member(chat_id, user_id)
                else:
                    logger.info(f"[群组道具] unmute 效果未实现 _compat.unban_chat_member，跳过 user={user_id}")
            elif effect_type == 'speed':
                # 发言加速卡：本地标记，由调用方按 user_props 表查询应用
                logger.info(f"[群组道具] speed 效果应用（本地标记）user={user_id}")
            elif effect_type == 'protect':
                # 防踢卡：本地标记，由调用方按 user_props 表查询应用
                logger.info(f"[群组道具] protect 效果应用（本地标记）user={user_id}")
            elif effect_type == 'nickname':
                # 修复 P1：原实现把 prop_name（道具名）当 custom_title 传，应使用用户提供的 custom_title
                if not custom_title:
                    logger.warning(f"[群组道具] nickname 效果需要 custom_title 参数，跳过 user={user_id}")
                    return
                if hasattr(self._compat, 'set_chat_administrator_custom_title'):
                    self._compat.set_chat_administrator_custom_title(chat_id, user_id, custom_title)
                else:
                    logger.info(f"[群组道具] nickname 效果未实现 _compat.set_chat_administrator_custom_title，跳过 user={user_id}")
        except Exception as e:
            logger.error(f"[群组道具] 应用效果失败: {e}")

    def _query_user_props(self, user_id: int) -> List[Dict[str, Any]]:
        try:
            cursor = self._db.conn.execute(
                'SELECT prop_name, count FROM user_props WHERE user_id = ? AND count > 0',
                (user_id,)
            )
            results = []
            for row in cursor.fetchall():
                prop_name, count = row
                prop_info = self.get_prop_info(prop_name)
                results.append({
                    'name': prop_name,
                    'count': count,
                    'description': prop_info.get('description', '') if prop_info else '',
                })
            return results
        except Exception as e:
            logger.error(f"[群组道具] 查询失败: {e}")
            return []

    async def process(self, update):
        return None


group_props_module = GroupPropsModule()