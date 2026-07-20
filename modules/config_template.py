"""群配置模板模块
参考阿福后台：导出群配置为模板、预览差异后应用到其他群、应用记录（成功/跳过/失败）
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

CONFIG_TEMPLATE_CONFIG = config.get('CONFIG_TEMPLATE_CONFIG', {
    'enabled': False,
})


class ConfigTemplateModule:
    def __init__(self):
        self._db = None
        self._templates: Dict[str, Dict[str, Any]] = {}
        self._apply_records: List[Dict[str, Any]] = []

    def export_template(self, chat_id: int, name: str) -> Dict[str, Any]:
        if not CONFIG_TEMPLATE_CONFIG.get('enabled', False):
            return {}
        try:
            config_data = self._get_group_config(chat_id)
            template = {
                'name': name,
                'export_time': datetime.now().isoformat(),
                'chat_id': chat_id,
                'config': config_data,
                'config_count': len(config_data) if isinstance(config_data, dict) else 0,
                'status': '启用',
            }
            self._templates[name] = template
            self._save_template_to_db(template)
            logger.info(f"[配置模板] 导出 chat={chat_id}, name={name}, count={template['config_count']}")
            return template
        except Exception as e:
            logger.error(f"[配置模板] 导出失败 chat={chat_id}: {e}")
            return {}

    def apply_template(self, template_name: str, target_chat_id: int,
                       mode: str = '覆盖已有配置') -> Dict[str, Any]:
        if not CONFIG_TEMPLATE_CONFIG.get('enabled', False):
            return {'success': 0, 'skip': 0, 'fail': 0, 'status': 'disabled'}
        template = self._get_template(template_name)
        if not template:
            return {'success': 0, 'skip': 0, 'fail': 0, 'status': 'not_found'}
        target_config = self._get_group_config(target_chat_id)
        source_config = template.get('config', {})
        success = 0
        skip = 0
        fail = 0
        new_count = 0
        overwrite_count = 0
        for key, value in source_config.items():
            try:
                if key in target_config:
                    if mode == '跳过已有配置':
                        skip += 1
                        continue
                    overwrite_count += 1
                else:
                    new_count += 1
                self._set_group_config(target_chat_id, key, value)
                success += 1
            except Exception:
                fail += 1
        record = self._save_apply_record(template_name, target_chat_id, mode,
                                         success, skip, fail, new_count, overwrite_count)
        logger.info(f"[配置模板] 应用 {template_name} -> chat={target_chat_id}: {success}/{skip}/{fail}")
        return {
            'success': success, 'skip': skip, 'fail': fail,
            'new': new_count, 'overwrite': overwrite_count,
            'status': 'completed' if fail == 0 else '部分成功',
            'record_id': record.get('id') if record else None,
        }

    def preview_diff(self, template_name: str, target_chat_id: int) -> Dict[str, Any]:
        template = self._get_template(template_name)
        if not template:
            return {'error': '模板不存在'}
        target_config = self._get_group_config(target_chat_id)
        source_config = template.get('config', {})
        diff = {
            'new_keys': [k for k in source_config if k not in target_config],
            'overwrite_keys': [k for k in source_config if k in target_config],
            'unchanged_keys': [],
            'total_source': len(source_config),
            'total_target': len(target_config),
        }
        return diff

    def list_templates(self) -> List[Dict[str, Any]]:
        return list(self._templates.values())

    def list_apply_records(self) -> List[Dict[str, Any]]:
        return self._apply_records

    def delete_template(self, name: str) -> bool:
        if name in self._templates:
            del self._templates[name]
            self._delete_template_from_db(name)
            logger.info(f"[配置模板] 删除 {name}")
            return True
        return False

    def _get_group_config(self, chat_id: int) -> Dict[str, Any]:
        try:
            cursor = self._db.conn.execute(
                'SELECT key, value FROM group_configs WHERE chat_id = ?',
                (chat_id,)
            )
            result = {}
            for row in cursor.fetchall():
                try:
                    result[row[0]] = json.loads(row[1])
                except:
                    result[row[0]] = row[1]
            return result
        except Exception:
            return {}

    def _set_group_config(self, chat_id: int, key: str, value: Any):
        try:
            value_json = json.dumps(value, ensure_ascii=False)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO group_configs (chat_id, key, value) VALUES (?, ?, ?)',
                (chat_id, key, value_json)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[配置模板] 设置配置失败 chat={chat_id}, key={key}: {e}")
            raise

    def _save_template_to_db(self, template: Dict[str, Any]):
        try:
            template_json = json.dumps(template, ensure_ascii=False)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO config_templates (name, data) VALUES (?, ?)',
                (template['name'], template_json)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[配置模板] 保存模板失败 {template['name']}: {e}")

    def _get_template(self, name: str) -> Optional[Dict[str, Any]]:
        if name in self._templates:
            return self._templates[name]
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM config_templates WHERE name = ?',
                (name,)
            )
            row = cursor.fetchone()
            if row:
                template = json.loads(row[0])
                self._templates[name] = template
                return template
        except Exception as e:
            logger.error(f"[配置模板] 获取模板失败 {name}: {e}")
        return None

    def _delete_template_from_db(self, name: str):
        try:
            self._db.conn.execute(
                'DELETE FROM config_templates WHERE name = ?',
                (name,)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[配置模板] 删除模板失败 {name}: {e}")

    def _save_apply_record(self, template_name: str, chat_id: int, mode: str,
                           success: int, skip: int, fail: int, new: int, overwrite: int) -> Dict[str, Any]:
        record = {
            'id': len(self._apply_records) + 1,
            'template_name': template_name,
            'chat_id': chat_id,
            'mode': mode,
            'success': success,
            'skip': skip,
            'fail': fail,
            'new': new,
            'overwrite': overwrite,
            'apply_time': datetime.now().isoformat(),
            'status': 'completed' if fail == 0 else '部分成功',
        }
        self._apply_records.append(record)
        try:
            record_json = json.dumps(record, ensure_ascii=False)
            self._db.conn.execute(
                'INSERT INTO config_template_applications (data) VALUES (?)',
                (record_json,)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[配置模板] 保存应用记录失败: {e}")
        return record

    async def process(self, update):
        return None


config_template_module = ConfigTemplateModule()