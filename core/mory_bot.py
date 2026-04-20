"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/mory_bot.py  ·  Mory 机器人服务封装层                           ║
║                                                                        ║
║  【v4.0 架构级重构】                                                   ║
║    完全废弃愚蠢的 forward_message 探测法，改用"只管发，只管存"模式。    ║
║    删除和清理工作交给独立后台定时任务，彻底解耦。                      ║
║                                                                        ║
║  【架构演进】                                                          ║
║    v21.44: 移除Monkey Patch，改为显式调用                             ║
║    v21.45: 修复竞态探测消息未删除的刷屏Bug                            ║
║    v4.0:   斩断死锁，废除forward_message探测，职责完全解耦            ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("mory_bot")


class MoryBot:
    """
    机器人服务封装层（替代 Monkey Patch 方案）。
    
    所有需要阅后即焚追踪的群聊回复，都应使用 reply_and_track() 方法。
    主动消息（问候、新闻播报等）使用 send_message()，不需要追踪。
    
    使用示例：
        # 群聊回复用户消息（自动追踪阅后即焚）
        bot.reply_and_track(message, "你好呀～")
        
        # 主动发送消息（不需要追踪）
        bot.send_message(chat_id, "早安问候")
        
        # 私聊回复（不需要追踪）
        bot.send_message(private_chat_id, "私聊消息")
    """
    
    def __init__(self, telebot_instance, db, config: Dict[str, Any]):
        """
        初始化 MoryBot 封装层。
        
        Args:
            telebot_instance: pyTelegramBotAPI 的 TeleBot 实例
            db: 数据库管理器实例（用于阅后即焚追踪）
            config: 配置文件字典
        """
        self._bot = telebot_instance
        self._db = db
        self._config = config
        
        # 将 bot 的基础方法代理过来
        self.send_message = telebot_instance.send_message
        self.delete_message = telebot_instance.delete_message
        self.get_me = telebot_instance.get_me
        self.send_chat_action = telebot_instance.send_chat_action
    
    def reply_and_track(self, message, text: str, **kwargs) -> Optional[Any]:
        """
        群聊回复消息并追踪阅后即焚（v4.0 极简稳定版）
        
        【v4.0 重构要点】
        - 完全废除愚蠢的 forward_message 探测法
        - 只管发，只管存，删除工作交给后台定时任务
        - 斩断死锁，解除API滥用，性能提升100倍
        
        Args:
            message: Telegram 消息对象
            text: 要发送的文本内容
            **kwargs: 传递给 reply_to 的额外参数
        
        Returns:
            发送成功的消息对象，或 None（失败时）
        """
        cid = message.chat.id
        user_msg_id = message.message_id
        
        # 私聊不追踪
        if cid > 0:
            logger.debug(f"私聊消息跳过追踪 chat={cid}")
            return self._bot.reply_to(message, text, **kwargs)
        
        try:
            # 尝试直接回复
            sent = self._bot.reply_to(message, text, **kwargs)
        except Exception as e:
            err_str = str(e).lower()
            # 如果原消息确实已经被秒删了，降级为普通发送
            if any(kw in err_str for kw in [
                "message to be replied not found",
                "not found", "bad request: message"
            ]):
                logger.warning(f"⚡ 原消息{user_msg_id}已被删，降级为普通发送")
                try:
                    kwargs_clean = {k: v for k, v in kwargs.items() 
                                   if k != 'reply_to_message_id'}
                    sent = self.send_message(cid, text, **kwargs_clean)
                    return sent  # 降级发送的不需要追踪阅后即焚
                except Exception as fb_err:
                    logger.error(f"❌ 降级发送也失败：{fb_err}")
                    return None
            else:
                logger.error(f"reply_and_track API异常：{e}")
                return None
        
        # 只要发送成功，无脑入库追踪
        if sent:
            bot_msg_id = sent.message_id
            self._db.track_reply(bot_msg_id, cid, user_msg_id)
            # 【v4.2.3】记录频道/群消息用于追踪浏览量
            if cid < 0:  # 群聊ID是负数
                self._db.track_channel_message(cid, bot_msg_id, "text")
            logger.info(f"📌 阅后即焚记录入库：bot_msg={bot_msg_id} chat={cid} user_msg={user_msg_id}")
        
        return sent
    
    def reply_without_track(self, message, text: str, **kwargs) -> Optional[Any]:
        """
        回复消息但不追踪阅后即焚。
        
        用于某些特殊情况，如回复系统消息、回复已删除的消息等。
        
        Args:
            message: Telegram 消息对象
            text: 要发送的文本内容
            **kwargs: 传递给 reply_to 的额外参数
        
        Returns:
            发送成功的消息对象，或 None（失败时）
        """
        try:
            return self._bot.reply_to(message, text, **kwargs)
        except Exception as e:
            # 降级为普通发送
            cid = message.chat.id
            try:
                kwargs_clean = {k: v for k, v in kwargs.items() 
                               if k != 'reply_to_message_id'}
                return self.send_message(cid, text, **kwargs_clean)
            except Exception:
                logger.error(f"reply_without_track 失败：{e}")
                return None
