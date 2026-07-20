"""群组迁移模块
参考阿福后台：群组迁移
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

GROUP_MIGRATION_CONFIG = config.get('GROUP_MIGRATION_CONFIG', {
    'enabled': False,
    'auto_invite': True,
    'message_forward': True,
    'batch_size': 100,
})


class GroupMigrationModule:
    def __init__(self):
        self._db = None
        self._compat = None

    async def start_migration(self, source_chat_id: int, target_chat_id: int) -> Dict[str, Any]:
        if not GROUP_MIGRATION_CONFIG.get('enabled', False):
            return {'status': 'disabled'}
        try:
            members = await self._compat.get_chat_members(source_chat_id)
            total_members = len(members)
            migrated_count = 0
            failed_count = 0
            for i, member in enumerate(members):
                if i % GROUP_MIGRATION_CONFIG.get('batch_size', 100) == 0 and i > 0:
                    import asyncio
                    await asyncio.sleep(1)
                try:
                    if GROUP_MIGRATION_CONFIG.get('auto_invite', True):
                        success = await self._invite_member(target_chat_id, member.user.id)
                        if success:
                            migrated_count += 1
                        else:
                            failed_count += 1
                    else:
                        migrated_count += 1
                except Exception as e:
                    failed_count += 1
                    logger.warning(f"[群组迁移] 邀请用户 {member.user.id} 失败: {e}")
            self._record_migration(source_chat_id, target_chat_id, total_members, migrated_count, failed_count)
            logger.info(f"[群组迁移] 完成 source={source_chat_id}, target={target_chat_id}, migrated={migrated_count}, failed={failed_count}")
            return {
                'status': 'completed',
                'total': total_members,
                'migrated': migrated_count,
                'failed': failed_count,
            }
        except Exception as e:
            logger.error(f"[群组迁移] 失败: {e}")
            return {'status': 'failed', 'error': 'internal_error'}

    async def _invite_member(self, chat_id: int, user_id: int) -> bool:
        """邀请单个用户，返回是否成功（修复统计失真：原实现吞异常导致 failed_count 永远为 0）"""
        try:
            await self._compat.unban_chat_member(chat_id, user_id)
            return True
        except Exception as e:
            logger.warning(f"[群组迁移] 邀请用户 {user_id} 到 {chat_id} 失败: {e}")
            return False

    def _record_migration(self, source_chat_id: int, target_chat_id: int,
                          total: int, migrated: int, failed: int):
        try:
            record = {
                'source_chat_id': source_chat_id,
                'target_chat_id': target_chat_id,
                'total_members': total,
                'migrated_count': migrated,
                'failed_count': failed,
                'created_at': datetime.now().isoformat(),
            }
            # 修复 P0 数据丢失：固定 id=1 存储单条 JSON 数组
            cursor = self._db.conn.execute(
                'SELECT data FROM migration_records WHERE id=1'
            )
            row = cursor.fetchone()
            if row:
                records = json.loads(row[0])
            else:
                records = []
            records.append(record)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO migration_records (id, data) VALUES (1, ?)',
                (json.dumps(records, ensure_ascii=False),)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[群组迁移] 记录迁移失败: {e}")

    async def forward_messages(self, source_chat_id: int, target_chat_id: int,
                               limit: int = 100) -> Dict[str, Any]:
        if not GROUP_MIGRATION_CONFIG.get('enabled', False):
            return {'status': 'disabled'}
        try:
            messages = await self._compat.get_history(source_chat_id, limit=limit)
            forwarded_count = 0
            for msg in reversed(messages):
                try:
                    await self._compat.forward_message(target_chat_id, source_chat_id, msg.message_id)
                    forwarded_count += 1
                    import asyncio
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.warning(f"[群组迁移] 转发消息失败 msg={msg.message_id}: {e}")
            logger.info(f"[群组迁移] 转发消息完成 source={source_chat_id}, target={target_chat_id}, forwarded={forwarded_count}")
            return {'status': 'completed', 'forwarded': forwarded_count}
        except Exception as e:
            logger.error(f"[群组迁移] 转发消息失败: {e}")
            return {'status': 'failed', 'error': str(e)}

    def get_migration_records(self) -> List[Dict[str, Any]]:
        try:
            # 修复 P0：固定 id=1 读取
            cursor = self._db.conn.execute('SELECT data FROM migration_records WHERE id=1')
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
        except Exception as e:
            logger.error(f"[群组迁移] 获取迁移记录失败: {e}")
        return []

    async def process(self, update):
        return None


group_migration_module = GroupMigrationModule()