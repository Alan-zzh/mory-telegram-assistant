"""群聊举报模块
参考阿福后台：群聊举报配置
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

GROUP_REPORT_CONFIG = config.get('GROUP_REPORT_CONFIG', {
    'enabled': False,
    'trigger_keywords': ['举报', 'report'],
    'delete_trigger_message': False,
    'report_format_hint': '请使用 /举报 @用户名 理由 格式',
    'success_message': '✅ 举报已提交，管理员将尽快处理',
    'duplicate_message': '⚠️ 您已举报过此消息',
    'review_message': '🔍 举报已收到，正在审核中',
    'processed_message': '✅ 举报已处理',
    'rejected_message': '❌ 举报已驳回',
})


class GroupReportModule:
    def __init__(self):
        self._db = None
        self._compat = None

    async def process_report(self, chat_id: int, reporter_id: int, reported_user_id: int,
                             message_id: int, reason: str = '') -> Dict[str, Any]:
        if not GROUP_REPORT_CONFIG.get('enabled', False):
            return {}
        try:
            if self._is_duplicate_report(chat_id, reporter_id, reported_user_id, message_id):
                if GROUP_REPORT_CONFIG.get('duplicate_message'):
                    await self._compat.send_message(chat_id, GROUP_REPORT_CONFIG['duplicate_message'])
                return {'status': 'duplicate'}
            report = {
                'id': self._get_next_id(chat_id),
                'reporter_id': reporter_id,
                'reported_user_id': reported_user_id,
                'message_id': message_id,
                'reason': reason,
                'status': 'pending',
                'created_at': datetime.now().isoformat(),
                'processed_at': None,
                'processed_by': None,
                'result': '',
            }
            self._save_report(chat_id, report)
            if GROUP_REPORT_CONFIG.get('delete_trigger_message', False):
                try:
                    await self._compat.delete_message(chat_id, message_id)
                except Exception as e:
                    logger.debug(f"[群聊举报] 删除触发消息失败 chat={chat_id} msg={message_id}: {e}")
            if GROUP_REPORT_CONFIG.get('success_message'):
                await self._compat.send_message(chat_id, GROUP_REPORT_CONFIG['success_message'])
            if GROUP_REPORT_CONFIG.get('review_message'):
                await self._notify_admins(chat_id, report)
            logger.info(f"[群聊举报] 提交举报 chat={chat_id}, reporter={reporter_id}, reported={reported_user_id}")
            return {'status': 'success', 'report': report}
        except Exception as e:
            logger.error(f"[群聊举报] 处理举报失败: {e}")
            return {'status': 'error', 'error': 'internal_error'}

    def get_reports(self, chat_id: int, status: str = None) -> List[Dict[str, Any]]:
        if not GROUP_REPORT_CONFIG.get('enabled', False):
            return []
        reports = self._load_reports(chat_id)
        if status:
            return [r for r in reports if r.get('status') == status]
        return reports

    async def process_report_action(self, chat_id: int, report_id: int, action: str,
                                    processed_by: int = None, result: str = '') -> bool:
        if not GROUP_REPORT_CONFIG.get('enabled', False):
            return False
        try:
            reports = self._load_reports(chat_id)
            for report in reports:
                if report.get('id') == report_id:
                    report['status'] = action
                    report['processed_at'] = datetime.now().isoformat()
                    report['processed_by'] = processed_by
                    report['result'] = result
                    self._save_reports(chat_id, reports)
                    message = GROUP_REPORT_CONFIG.get('processed_message') if action == 'approved' else \
                              GROUP_REPORT_CONFIG.get('rejected_message')
                    if message:
                        # 修复 P1：原实现缺 await（协程不执行）+ 缺 try/except（异常中断流程）
                        try:
                            await self._compat.send_message(chat_id, message)
                        except Exception as send_err:
                            logger.warning(f"[群聊举报] 发送处理结果消息失败 chat={chat_id}: {send_err}")
                    logger.info(f"[群聊举报] 处理举报 chat={chat_id}, report={report_id}, action={action}")
                    return True
            return False
        except Exception as e:
            logger.error(f"[群聊举报] 处理举报失败: {e}")
            return False

    def check_trigger_keyword(self, text: str) -> bool:
        keywords = GROUP_REPORT_CONFIG.get('trigger_keywords', [])
        for keyword in keywords:
            if keyword.lower() in text.lower():
                return True
        return False

    def _is_duplicate_report(self, chat_id: int, reporter_id: int, reported_user_id: int,
                             message_id: int) -> bool:
        reports = self._load_reports(chat_id)
        for report in reports:
            if report.get('reporter_id') == reporter_id and \
               report.get('reported_user_id') == reported_user_id and \
               report.get('message_id') == message_id and \
               report.get('status') != 'rejected':
                return True
        return False

    async def _notify_admins(self, chat_id: int, report: Dict[str, Any]):
        try:
            admins = await self._compat.get_chat_administrators(chat_id)
            admin_ids = [admin.user.id for admin in admins]
            review_msg = GROUP_REPORT_CONFIG.get('review_message', '')
            for admin_id in admin_ids:
                try:
                    await self._compat.send_message(admin_id, f"{review_msg}\n\n"
                        f"举报ID: {report['id']}\n"
                        f"举报用户: {report['reporter_id']}\n"
                        f"被举报用户: {report['reported_user_id']}\n"
                        f"理由: {report.get('reason', '')}")
                except Exception as e:
                    logger.warning(f"[群聊举报] 通知管理员 {admin_id} 失败: {e}")
        except Exception as e:
            logger.error(f"[群聊举报] 通知管理员失败: {e}")

    def _get_next_id(self, chat_id: int) -> int:
        reports = self._load_reports(chat_id)
        if not reports:
            return 1
        return max(r.get('id', 0) for r in reports) + 1

    def _load_reports(self, chat_id: int) -> List[Dict[str, Any]]:
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM group_report WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
        except Exception as e:
            logger.error(f"[群聊举报] 加载举报失败: {e}")
        return []

    def _save_report(self, chat_id: int, report: Dict[str, Any]):
        reports = self._load_reports(chat_id)
        reports.append(report)
        self._save_reports(chat_id, reports)

    def _save_reports(self, chat_id: int, reports: List[Dict[str, Any]]):
        try:
            reports_json = json.dumps(reports, ensure_ascii=False)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO group_report (chat_id, data) VALUES (?, ?)',
                (chat_id, reports_json)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[群聊举报] 保存举报失败: {e}")

    async def process(self, update):
        return None


group_report_module = GroupReportModule()