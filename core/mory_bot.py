"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/mory_bot.py  ·  Mory 机器人服务封装层                           ║
║                                                                        ║
║  【架构重构 v21.44】                                                   ║
║    移除了危险的 Monkey Patch（bot.reply_to = xxx），改为显式调用。     ║
║    所有群聊回复使用 reply_and_track() 方法，职责分离，可追溯。        ║
║                                                                        ║
║  优势：                                                                ║
║    1. 代码可追溯：所有阅后即焚追踪都是显式调用，不再有隐式行为         ║
║    2. 易于调试：追踪逻辑出错时可以快速定位                             ║
║    3. 职责分离：发送消息和追踪逻辑独立，互不干扰                       ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
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
        self._admin_id = config.get("ADMIN_ID", 0)
        
        # 将 bot 的基础方法代理过来
        self.send_message = telebot_instance.send_message
        self.delete_message = telebot_instance.delete_message
        self.forward_message = telebot_instance.forward_message
        self.get_me = telebot_instance.get_me
        self.send_chat_action = telebot_instance.send_chat_action
    
    def reply_and_track(self, message, text: str, **kwargs) -> Optional[Any]:
        """
        群聊回复消息并追踪阅后即焚。
        
        这是 Monkey Patch 的替代方案。所有群聊回复用户消息的场景都应使用此方法。
        
        Args:
            message: Telegram 消息对象（包含 chat.id, message_id 等）
            text: 要发送的文本内容
            **kwargs: 传递给 send_message 的额外参数（如 parse_mode, disable_web_page_preview 等）
        
        Returns:
            发送成功的消息对象，或 None（失败时）
        
        注意：
            - 此方法只用于群聊回复（cid < 0）
            - 私聊消息使用 send_message()，不需要追踪
        """
        cid = message.chat.id
        user_msg_id = message.message_id
        
        # 私聊不追踪
        if cid > 0:
            logger.debug(f"私聊消息跳过追踪 chat={cid}")
            return self._bot.reply_to(message, text, **kwargs)
        
        try:
            sent = self._bot.reply_to(message, text, **kwargs)
        except Exception as e:
            err_str = str(e).lower()
            
            # 原消息已被删除 → 降级为普通发送
            if any(kw in err_str for kw in [
                "message to be replied not found",
                "not found", "bad request: message",
                "message_id_invalid"
            ]):
                logger.warning(f"⚡ 原消息{user_msg_id}已被删，降级为普通发送")
                try:
                    # 移除 reply_to_message_id 参数
                    kwargs_clean = {k: v for k, v in kwargs.items() 
                                   if k != 'reply_to_message_id'}
                    sent = self.send_message(cid, text, **kwargs_clean)
                    logger.info(f"⚡ 降级发送成功（原消息{user_msg_id}已删），跳过追踪")
                    return sent
                except Exception as fb_err:
                    logger.error(f"❌ 降级发送也失败：{fb_err}")
                    return None
            else:
                logger.error(f"reply_and_track 失败（非竞态）：{e}")
                return None
        
        if not sent:
            return sent
        
        bot_msg_id = sent.message_id
        
        # 追踪阅后即焚
        self._db.track_reply(bot_msg_id, cid, user_msg_id)
        logger.info(f"📌 阅后即焚追踪成功：bot_msg={bot_msg_id} chat={cid} user_msg={user_msg_id}")
        
        # 竞态兜底探测：立即检查原消息是否还在
        # 【修复v21.45】探测消息必须立即删除，防止骚扰管理员
        try:
            if self._admin_id:
                probe = self._bot.forward_message(
                    self._admin_id, cid, user_msg_id, 
                    disable_notification=True
                )
                # 【修复v21.45】：探测成功说明原消息还在，立刻删掉探测消息
                try:
                    self._bot.delete_message(self._admin_id, probe.message_id)
                except Exception:
                    pass  # 忽略探测消息删除失败（无影响）
        except Exception as race_err:
            err_str2 = str(race_err).lower()
            if any(kw in err_str2 for kw in [
                "not found", "message_id_invalid", 
                "bad request", "forbidden", 
                "chat", "deleted"
            ]):
                # 原消息已删 → 删掉刚发的机器人回复
                for r_try in range(3):
                    try:
                        self.delete_message(cid, int(bot_msg_id))
                        self._db.delete_tracked(bot_msg_id)
                        logger.info(f"⚡ 阅后即焚(竞态): 原消息{user_msg_id}已删→清理{bot_msg_id}")
                        break
                    except Exception as del_e2:
                        del_str = str(del_e2).lower()
                        if any(kw in del_str for kw in ["not found", "message to delete"]):
                            self._db.delete_tracked(bot_msg_id)
                            break
                        elif r_try < 2:
                            time.sleep(1 + r_try)
        
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
