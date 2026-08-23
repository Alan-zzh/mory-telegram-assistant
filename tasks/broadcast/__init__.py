"""
tasks/broadcast/__init__.py - 播报类任务导出

旧版定向塔罗搭讪任务 TarotTask（tarot_flirt）已作为死功能移除：
其“哥哥～/在吗～”点名话术与编造运势细节违反人设红线，
现行玄学播报统一走 MysticBroadcastTask + mystic_content 本地引擎。
"""

from tasks.broadcast.greeting_task import GreetingTask
from tasks.broadcast.mystic_broadcast_task import MysticBroadcastTask

__all__ = ["GreetingTask", "MysticBroadcastTask"]
