"""群组待办模块
参考阿福后台：待办任务管理、提醒、完成状态
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

GROUP_TODO_CONFIG = config.get('GROUP_TODO_CONFIG', {
    'enabled': False,
})


class GroupTodoModule:
    """Manage group todo items and reminders."""
    def __init__(self):
        """Initialize module state and runtime adapters."""
        self._db = None
        self._compat = None

    def add_todo(self, chat_id: int, title: str, description: str = '',
                 priority: str = 'medium', assignee_id: int = None,
                 due_date: str = None) -> int:
        """Handle this module operation."""
        if not GROUP_TODO_CONFIG.get('enabled', False):
            return 0
        try:
            todo = {
                'id': self._get_next_id(chat_id),
                'title': title,
                'description': description,
                'priority': priority,
                'assignee_id': assignee_id,
                'due_date': due_date,
                'status': 'pending',
                'created_at': datetime.now().isoformat(),
                'completed_at': None,
            }
            self._save_todo(chat_id, todo)
            logger.info(f"[群组待办] 添加待办 chat={chat_id}, title={title}")
            return todo['id']
        except Exception as e:
            logger.error(f"[群组待办] 添加待办失败: {e}")
            return 0

    def complete_todo(self, chat_id: int, todo_id: int) -> bool:
        """Handle this module operation."""
        if not GROUP_TODO_CONFIG.get('enabled', False):
            return False
        try:
            todos = self._load_todos(chat_id)
            for todo in todos:
                if todo.get('id') == todo_id:
                    todo['status'] = 'completed'
                    todo['completed_at'] = datetime.now().isoformat()
                    self._save_todos(chat_id, todos)
                    logger.info(f"[群组待办] 完成待办 chat={chat_id}, id={todo_id}")
                    return True
            return False
        except Exception as e:
            logger.error(f"[群组待办] 完成待办失败: {e}")
            return False

    def get_todos(self, chat_id: int, status: str = None) -> List[Dict[str, Any]]:
        """Return todo items for a group."""
        if not GROUP_TODO_CONFIG.get('enabled', False):
            return []
        todos = self._load_todos(chat_id)
        if status:
            return [t for t in todos if t.get('status') == status]
        return todos

    def get_todo(self, chat_id: int, todo_id: int) -> Optional[Dict[str, Any]]:
        """Return one todo item by identifier."""
        todos = self.get_todos(chat_id)
        return next((t for t in todos if t.get('id') == todo_id), None)

    def delete_todo(self, chat_id: int, todo_id: int) -> bool:
        """Handle this module operation."""
        if not GROUP_TODO_CONFIG.get('enabled', False):
            return False
        try:
            todos = self._load_todos(chat_id)
            todos = [t for t in todos if t.get('id') != todo_id]
            self._save_todos(chat_id, todos)
            logger.info(f"[群组待办] 删除待办 chat={chat_id}, id={todo_id}")
            return True
        except Exception as e:
            logger.error(f"[群组待办] 删除待办失败: {e}")
            return False

    def get_todo_stats(self, chat_id: int) -> Dict[str, Any]:
        """Summarize todo completion statistics."""
        if not GROUP_TODO_CONFIG.get('enabled', False):
            return {}
        todos = self._load_todos(chat_id)
        pending = len([t for t in todos if t.get('status') == 'pending'])
        completed = len([t for t in todos if t.get('status') == 'completed'])
        return {
            'total': len(todos),
            'pending': pending,
            'completed': completed,
            'completion_rate': (completed / len(todos) * 100) if todos else 0,
        }

    async def send_todo_reminder(self, chat_id: int, todo_id: int):
        """Send a reminder for an open todo item."""
        if not GROUP_TODO_CONFIG.get('enabled', False):
            return
        todo = self.get_todo(chat_id, todo_id)
        if not todo:
            return
        reminder_text = f"📝 待办提醒: {todo['title']}"
        if todo.get('due_date'):
            reminder_text += f"\n⏰ 截止日期: {todo['due_date']}"
        try:
            await self._compat.send_message(chat_id, reminder_text)
            logger.info(f"[群组待办] 发送提醒 chat={chat_id}, id={todo_id}")
        except Exception as e:
            logger.error(f"[群组待办] 发送提醒失败: {e}")

    def _get_next_id(self, chat_id: int) -> int:
        """Return the next todo identifier."""
        todos = self._load_todos(chat_id)
        if not todos:
            return 1
        return max(t.get('id', 0) for t in todos) + 1

    def _load_todos(self, chat_id: int) -> List[Dict[str, Any]]:
        """Load persisted todos for a group."""
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM group_todo WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
        except Exception as e:
            logger.error(f"[群组待办] 加载待办失败: {e}")
        return []

    def _save_todo(self, chat_id: int, todo: Dict[str, Any]):
        """Persist one todo item."""
        todos = self._load_todos(chat_id)
        todos.append(todo)
        self._save_todos(chat_id, todos)

    def _save_todos(self, chat_id: int, todos: List[Dict[str, Any]]):
        """Persist all todos for a group."""
        try:
            todos_json = json.dumps(todos, ensure_ascii=False)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO group_todo (chat_id, data) VALUES (?, ?)',
                (chat_id, todos_json)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[群组待办] 保存待办失败: {e}")

    async def process(self, update):
        """Handle an update for this module."""
        return None


group_todo_module = GroupTodoModule()
