"""自动规则模块
参考阿福后台：自动警告、自动封禁、自动回复、自动删除、自动禁言
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

AUTO_RULES_CONFIG = config.get('AUTO_RULES_CONFIG', {
    'enabled': False,
    'auto_warning_enabled': False,
    'auto_ban_enabled': False,
    'auto_reply_enabled': False,
    'auto_delete_enabled': False,
    'auto_mute_enabled': False,
})


class AutoRulesModule:
    def __init__(self):
        self._db = None
        self._compat = None
        self._rules: Dict[str, List[Dict[str, Any]]] = {}

    async def check_auto_rules(self, chat_id: int, user_id: int, text: str) -> Optional[Dict[str, Any]]:
        if not AUTO_RULES_CONFIG.get('enabled', False):
            return None
        rules = self._load_rules(chat_id)
        for rule in rules:
            if not rule.get('enabled', False):
                continue
            rule_type = rule.get('rule_type', '')
            if rule_type == 'auto_warning' and AUTO_RULES_CONFIG.get('auto_warning_enabled', False):
                result = await self._check_auto_warning(chat_id, user_id, text, rule)
                if result:
                    return result
            elif rule_type == 'auto_ban' and AUTO_RULES_CONFIG.get('auto_ban_enabled', False):
                result = await self._check_auto_ban(chat_id, user_id, text, rule)
                if result:
                    return result
            elif rule_type == 'auto_reply' and AUTO_RULES_CONFIG.get('auto_reply_enabled', False):
                result = await self._check_auto_reply(chat_id, user_id, text, rule)
                if result:
                    return result
            elif rule_type == 'auto_delete' and AUTO_RULES_CONFIG.get('auto_delete_enabled', False):
                result = await self._check_auto_delete(chat_id, user_id, text, rule)
                if result:
                    return result
            elif rule_type == 'auto_mute' and AUTO_RULES_CONFIG.get('auto_mute_enabled', False):
                result = await self._check_auto_mute(chat_id, user_id, text, rule)
                if result:
                    return result
        return None

    async def _check_auto_warning(self, chat_id: int, user_id: int, text: str, rule: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        keywords = rule.get('keywords', [])
        for keyword in keywords:
            if keyword.lower() in text.lower():
                warning_message = rule.get('warning_message', '⚠️ 请注意发言规范')
                await self._compat.send_message(chat_id, warning_message)
                logger.info(f"[自动规则] 自动警告 chat={chat_id}, user={user_id}, keyword={keyword}")
                return {'action': 'warning', 'rule_type': 'auto_warning', 'keyword': keyword}
        return None

    async def _check_auto_ban(self, chat_id: int, user_id: int, text: str, rule: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        keywords = rule.get('keywords', [])
        for keyword in keywords:
            if keyword.lower() in text.lower():
                await self._compat.ban_chat_member(chat_id, user_id)
                ban_message = rule.get('ban_message', '🚫 用户因违规已被封禁')
                await self._compat.send_message(chat_id, ban_message)
                logger.info(f"[自动规则] 自动封禁 chat={chat_id}, user={user_id}, keyword={keyword}")
                return {'action': 'ban', 'rule_type': 'auto_ban', 'keyword': keyword}
        return None

    async def _check_auto_reply(self, chat_id: int, user_id: int, text: str, rule: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        keywords = rule.get('keywords', [])
        reply_text = rule.get('reply_text', '')
        if not reply_text:
            return None
        for keyword in keywords:
            if keyword.lower() in text.lower():
                await self._compat.send_message(chat_id, reply_text)
                logger.info(f"[自动规则] 自动回复 chat={chat_id}, keyword={keyword}")
                return {'action': 'reply', 'rule_type': 'auto_reply', 'keyword': keyword}
        return None

    async def _check_auto_delete(self, chat_id: int, user_id: int, text: str, rule: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        keywords = rule.get('keywords', [])
        for keyword in keywords:
            if keyword.lower() in text.lower():
                logger.info(f"[自动规则] 自动删除 chat={chat_id}, user={user_id}, keyword={keyword}")
                return {'action': 'delete', 'rule_type': 'auto_delete', 'keyword': keyword}
        return None

    async def _check_auto_mute(self, chat_id: int, user_id: int, text: str, rule: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        keywords = rule.get('keywords', [])
        mute_duration = rule.get('mute_duration', 3600)
        for keyword in keywords:
            if keyword.lower() in text.lower():
                from datetime import datetime, timedelta
                await self._compat.restrict_chat_member(chat_id, user_id, until_date=datetime.now() + timedelta(seconds=mute_duration))
                mute_message = rule.get('mute_message', f'🔇 用户已被禁言 {mute_duration // 60} 分钟')
                await self._compat.send_message(chat_id, mute_message)
                logger.info(f"[自动规则] 自动禁言 chat={chat_id}, user={user_id}, duration={mute_duration}s")
                return {'action': 'mute', 'rule_type': 'auto_mute', 'keyword': keyword, 'duration': mute_duration}
        return None

    def add_rule(self, chat_id: int, rule_type: str, keywords: List[str],
                 enabled: bool = True, **kwargs):
        if not AUTO_RULES_CONFIG.get('enabled', False):
            return False
        try:
            rule = {
                'id': len(self._rules.get(str(chat_id), [])) + 1,
                'rule_type': rule_type,
                'keywords': keywords,
                'enabled': enabled,
                'created_at': datetime.now().isoformat(),
                **kwargs,
            }
            if str(chat_id) not in self._rules:
                self._rules[str(chat_id)] = []
            self._rules[str(chat_id)].append(rule)
            self._save_rule(chat_id, rule)
            logger.info(f"[自动规则] 添加规则 chat={chat_id}, type={rule_type}")
            return True
        except Exception as e:
            logger.error(f"[自动规则] 添加规则失败: {e}")
            return False

    def get_rules(self, chat_id: int) -> List[Dict[str, Any]]:
        return self._load_rules(chat_id)

    def enable_rule(self, chat_id: int, rule_id: int, enabled: bool):
        try:
            rules = self._load_rules(chat_id)
            for rule in rules:
                if rule.get('id') == rule_id:
                    rule['enabled'] = enabled
                    self._save_rules(chat_id, rules)
                    logger.info(f"[自动规则] {'启用' if enabled else '禁用'}规则 chat={chat_id}, id={rule_id}")
                    return True
            return False
        except Exception as e:
            logger.error(f"[自动规则] 启用规则失败: {e}")
            return False

    def delete_rule(self, chat_id: int, rule_id: int) -> bool:
        try:
            rules = self._load_rules(chat_id)
            rules = [r for r in rules if r.get('id') != rule_id]
            self._save_rules(chat_id, rules)
            logger.info(f"[自动规则] 删除规则 chat={chat_id}, id={rule_id}")
            return True
        except Exception as e:
            logger.error(f"[自动规则] 删除规则失败: {e}")
            return False

    def _load_rules(self, chat_id: int) -> List[Dict[str, Any]]:
        if str(chat_id) in self._rules:
            return self._rules[str(chat_id)]
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM auto_rules WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                rules = json.loads(row[0])
                self._rules[str(chat_id)] = rules
                return rules
        except Exception as e:
            logger.error(f"[自动规则] 加载规则失败: {e}")
        return []

    def _save_rule(self, chat_id: int, rule: Dict[str, Any]):
        rules = self._load_rules(chat_id)
        rules.append(rule)
        self._save_rules(chat_id, rules)

    def _save_rules(self, chat_id: int, rules: List[Dict[str, Any]]):
        try:
            rules_json = json.dumps(rules, ensure_ascii=False)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO auto_rules (chat_id, data) VALUES (?, ?)',
                (chat_id, rules_json)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[自动规则] 保存规则失败: {e}")

    async def process(self, update):
        return None


auto_rules_module = AutoRulesModule()