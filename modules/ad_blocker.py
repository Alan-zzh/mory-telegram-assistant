"""广告封杀模块
参考阿福后台：广告封杀
"""
import json
from datetime import datetime
from typing import Dict, Any, List

from core.logging_util import get_logger
from core.settings import get_config

try:
    config = get_config()
except Exception:
    config = {}
logger = get_logger(__name__)

AD_BLOCKER_CONFIG = config.get('AD_BLOCKER_CONFIG', {
    'enabled': False,
    'global_blacklist': [],
    'ban_duration_days': 30,
    'delete_messages': True,
    'notify_admins': True,
})


class AdBlockerModule:
    def __init__(self):
        self._db = None
        self._compat = None

    async def check_ad_keywords(self, chat_id: int, user_id: int, text: str) -> Dict[str, Any]:
        if not AD_BLOCKER_CONFIG.get('enabled', False):
            return {'is_ad': False}
        keywords = AD_BLOCKER_CONFIG.get('global_blacklist', [])
        matched_keywords = []
        for keyword in keywords:
            if keyword.lower() in text.lower():
                matched_keywords.append(keyword)
        if matched_keywords:
            await self._block_user(chat_id, user_id, matched_keywords)
            logger.info(f"[广告封杀] 检测到广告 chat={chat_id}, user={user_id}, keywords={matched_keywords}")
            return {'is_ad': True, 'matched_keywords': matched_keywords}
        return {'is_ad': False}

    async def _block_user(self, chat_id: int, user_id: int, keywords: List[str]):
        from datetime import datetime, timedelta
        ban_until = datetime.now() + timedelta(days=AD_BLOCKER_CONFIG.get('ban_duration_days', 30))
        await self._compat.ban_chat_member(chat_id, user_id, until_date=ban_until)
        self._add_global_blacklist(user_id, keywords)
        if AD_BLOCKER_CONFIG.get('notify_admins', True):
            await self._notify_admins(chat_id, user_id, keywords)

    def _add_global_blacklist(self, user_id: int, keywords: List[str]):
        try:
            entry = {
                'user_id': user_id,
                'keywords': keywords,
                'added_at': datetime.now().isoformat(),
                'reason': '广告封杀',
            }
            # 修复 P0 数据丢失：表有 id 主键但 INSERT 不指定 → 每次新增行 → SELECT 无 WHERE 只读第一行
            # 修复方案：固定 id=1，INSERT 指定主键，SELECT 加 WHERE
            cursor = self._db.conn.execute(
                'SELECT data FROM global_ad_blacklist WHERE id=1'
            )
            row = cursor.fetchone()
            if row:
                blacklist = json.loads(row[0])
            else:
                blacklist = []
            blacklist.append(entry)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO global_ad_blacklist (id, data) VALUES (1, ?)',
                (json.dumps(blacklist, ensure_ascii=False),)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[广告封杀] 添加黑名单失败: {e}")

    async def _notify_admins(self, chat_id: int, user_id: int, keywords: List[str]):
        try:
            admins = await self._compat.get_chat_administrators(chat_id)
            admin_ids = [admin.user.id for admin in admins]
            message = f"🚫 广告封杀\n用户ID: {user_id}\n触发关键词: {', '.join(keywords)}"
            for admin_id in admin_ids:
                try:
                    await self._compat.send_message(admin_id, message)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"[广告封杀] 通知管理员失败: {e}")

    def add_keyword(self, keyword: str) -> bool:
        if not AD_BLOCKER_CONFIG.get('enabled', False):
            return False
        try:
            keywords = AD_BLOCKER_CONFIG.get('global_blacklist', [])
            if keyword not in keywords:
                keywords.append(keyword)
                AD_BLOCKER_CONFIG['global_blacklist'] = keywords
                logger.info(f"[广告封杀] 添加关键词: {keyword}")
            return True
        except Exception as e:
            logger.error(f"[广告封杀] 添加关键词失败: {e}")
            return False

    def remove_keyword(self, keyword: str) -> bool:
        if not AD_BLOCKER_CONFIG.get('enabled', False):
            return False
        try:
            keywords = AD_BLOCKER_CONFIG.get('global_blacklist', [])
            if keyword in keywords:
                keywords.remove(keyword)
                AD_BLOCKER_CONFIG['global_blacklist'] = keywords
                logger.info(f"[广告封杀] 移除关键词: {keyword}")
            return True
        except Exception as e:
            logger.error(f"[广告封杀] 移除关键词失败: {e}")
            return False

    def get_blacklist(self) -> List[Dict[str, Any]]:
        try:
            # 修复 P0：固定 id=1 读取
            cursor = self._db.conn.execute('SELECT data FROM global_ad_blacklist WHERE id=1')
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
        except Exception as e:
            logger.error(f"[广告封杀] 获取黑名单失败: {e}")
        return []

    def get_keywords(self) -> List[str]:
        return AD_BLOCKER_CONFIG.get('global_blacklist', [])

    async def process(self, update):
        return None


ad_blocker_module = AdBlockerModule()