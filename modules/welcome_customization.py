"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/welcome_customization.py  ·  入群欢迎定制模块                ║
║  (参考 WilliamButcherBot)                                               ║
║                                                                        ║
║  功能：自定义欢迎消息、告别消息、群规展示等。                            ║
║
║  数据库表：                                                            ║
║    welcome_configs                                                     ║
║    - chat_id INTEGER                                                   ║
║    - welcome_text TEXT (欢迎消息模板)                                   ║
║    - goodbye_text TEXT (告别消息模板)                                   ║
║    - rules_text TEXT (群规模板)                                       ║
║    - enable_welcome INTEGER (是否启用欢迎)                              ║
║    - enable_goodbye INTEGER (是否启用告别)                              ║
║    - enable_rules INTEGER (是否启用群规)                                ║
║    - clean_welcome INTEGER (是否自动清理欢迎消息)                        ║
║    - media_file_id TEXT (欢迎媒体文件ID)                                ║
║                                                                        ║
║  模板变量：                                                            ║
║    {user} - 用户名                                                     ║
║    {mention} - 用户@提及                                               ║
║    {first_name} - 用户名                                              ║
║    {id} - 用户ID                                                      ║
║
║  被调用：main.py P0 新人入群处理                                       ║
══════════════════════════════════════════════════════════════════════════╝
"""

import re
from core.logging_util import get_logger

logger = get_logger("welcome_customization")


def get_welcome_config(db, chat_id: int) -> dict:
    """获取群组欢迎配置"""
    with db.conn:
        c = db.conn.cursor()
        c.execute("""
            SELECT welcome_text, goodbye_text, rules_text,
                   enable_welcome, enable_goodbye, enable_rules,
                   clean_welcome, media_file_id
            FROM welcome_configs WHERE chat_id=?
        """, (chat_id,))
        row = c.fetchone()
        if row:
            return {
                "welcome_text": row[0],
                "goodbye_text": row[1],
                "rules_text": row[2],
                "enable_welcome": row[3],
                "enable_goodbye": row[4],
                "enable_rules": row[5],
                "clean_welcome": row[6],
                "media_file_id": row[7],
            }
    # 默认配置
    return {
        "welcome_text": "👋 欢迎 {mention} 加入群组！",
        "goodbye_text": "👋 {first_name} 离开了群组",
        "rules_text": "📜 群规：\n1. 请文明交流\n2. 禁止广告\n3. 禁止刷屏",
        "enable_welcome": 1,
        "enable_goodbye": 1,
        "enable_rules": 1,
        "clean_welcome": 0,
        "media_file_id": None,
    }


def set_welcome_config(db, chat_id: int, **kwargs):
    """设置群组欢迎配置"""
    config = get_welcome_config(db, chat_id)  # 获取当前配置
    # 更新配置
    for key, value in kwargs.items():
        if key in config:
            config[key] = value

    with db.conn:
        db.conn.execute("""
            INSERT OR REPLACE INTO welcome_configs
            (chat_id, welcome_text, goodbye_text, rules_text,
             enable_welcome, enable_goodbye, enable_rules,
             clean_welcome, media_file_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            chat_id, config["welcome_text"], config["goodbye_text"], config["rules_text"],
            config["enable_welcome"], config["enable_goodbye"], config["enable_rules"],
            config["clean_welcome"], config["media_file_id"]
        ))
        db.conn.commit()


def format_welcome_message(template: str, user, chat_id: int) -> str:
    """格式化欢迎消息模板"""
    from telebot.types import User
    if not isinstance(user, User):
        raise TypeError("user must be telebot.types.User")

    # 获取用户名的各种形式
    first_name = user.first_name or "用户"
    full_name = (user.first_name or "") + (user.last_name or "")
    username = getattr(user, 'username', None)

    # 构造提及格式
    if username:
        mention = f"@{username}"
    else:
        # Telegram中没有用户名时，无法直接提及，只显示姓名
        mention = first_name

    # 替换模板变量
    message = template.replace("{user}", str(full_name))
    message = message.replace("{mention}", mention)
    message = message.replace("{first_name}", first_name)
    message = message.replace("{id}", str(user.id))
    message = message.replace("{chat_id}", str(chat_id))

    return message


def send_welcome_message(bot, m, config: dict, db):
    """发送定制欢迎消息"""
    chat_id = m.chat.id
    welcome_config = get_welcome_config(db, chat_id)

    if not welcome_config["enable_welcome"]:
        return

    for user in m.new_chat_members:
        # 格式化欢迎消息
        welcome_msg = format_welcome_message(welcome_config["welcome_text"], user, chat_id)

        # 发送欢迎消息（带媒体或纯文本）
        sent_msg = None
        try:
            if welcome_config["media_file_id"]:
                sent_msg = bot.send_photo(chat_id, welcome_config["media_file_id"], caption=welcome_msg)
            else:
                sent_msg = bot.send_message(chat_id, welcome_msg)

            logger.info(f"👋 发送欢迎消息: uid={user.id} chat_id={chat_id}")

            # 如果启用自动清理，延时删除欢迎消息（受全局开关控制）
            if welcome_config["clean_welcome"]:
                if config.get("ENABLE_MESSAGE_DELETION", False):
                    import threading
                    try:
                        threading.Timer(60.0, bot.delete_message, args=[chat_id, sent_msg.message_id]).start()
                        logger.info(f"🗑 自动清理欢迎消息: mid={sent_msg.message_id}（60秒后删除）")
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
                else:
                    logger.warning(f"[欢迎消息清理] ENABLE_MESSAGE_DELETION 未开启，跳过自动清理")

        except Exception as e:
            logger.warning(f"发送欢迎消息失败: {e}")

    # 如果启用群规展示，发送群规
    if welcome_config["enable_rules"]:
        try:
            rules_msg = welcome_config["rules_text"]
            bot.send_message(chat_id, rules_msg)
        except Exception as e:
            logger.warning(f"发送群规失败: {e}")


def send_goodbye_message(bot, m, config: dict, db):
    """发送定制告别消息"""
    chat_id = m.chat.id
    welcome_config = get_welcome_config(db, chat_id)

    if not welcome_config["enable_goodbye"]:
        return

    user = m.left_chat_member

    # 格式化告别消息
    goodbye_msg = format_welcome_message(welcome_config["goodbye_text"], user, chat_id)

    try:
        bot.send_message(chat_id, goodbye_msg)
        logger.info(f"👋 发送告别消息: uid={user.id} chat_id={chat_id}")
    except Exception as e:
        logger.warning(f"发送告别消息失败: {e}")


def handle_set_welcome_command(bot, m, args: list, config: dict, db):
    """处理 /setwelcome 命令"""
    admin_id = config.get("ADMIN_ID", 0)
    if m.from_user.id != admin_id:
        bot.reply_to(m, "❌ 只有管理员可以设置欢迎消息")
        return

    if not args:
        bot.reply_to(m, "❌ 用法：/setwelcome <欢迎消息模板>")
        return

    new_welcome = " ".join(args)
    set_welcome_config(db, m.chat.id, welcome_text=new_welcome)

    bot.reply_to(m, f"✅ 已设置欢迎消息：\n{new_welcome}")


def handle_set_goodbye_command(bot, m, args: list, config: dict, db):
    """处理 /setgoodbye 命令"""
    admin_id = config.get("ADMIN_ID", 0)
    if m.from_user.id != admin_id:
        bot.reply_to(m, "❌ 只有管理员可以设置告别消息")
        return

    if not args:
        bot.reply_to(m, "❌ 用法：/setgoodbye <告别消息模板>")
        return

    new_goodbye = " ".join(args)
    set_welcome_config(db, m.chat.id, goodbye_text=new_goodbye)

    bot.reply_to(m, f"✅ 已设置告别消息：\n{new_goodbye}")


def handle_set_rules_command(bot, m, args: list, config: dict, db):
    """处理 /setrules 命令"""
    admin_id = config.get("ADMIN_ID", 0)
    if m.from_user.id != admin_id:
        bot.reply_to(m, "❌ 只有管理员可以设置群规")
        return

    if not args:
        bot.reply_to(m, "❌ 用法：/setrules <群规内容>")
        return

    new_rules = " ".join(args)
    set_welcome_config(db, m.chat.id, rules_text=new_rules)

    bot.reply_to(m, f"✅ 已设置群规：\n{new_rules}")


def handle_clean_welcome_command(bot, m, config: dict, db):
    """处理 /cleanwelcome 命令"""
    admin_id = config.get("ADMIN_ID", 0)
    if m.from_user.id != admin_id:
        bot.reply_to(m, "❌ 只有管理员可以设置自动清理")
        return

    current_config = get_welcome_config(db, m.chat.id)
    new_state = not bool(current_config["clean_welcome"])
    set_welcome_config(db, m.chat.id, clean_welcome=1 if new_state else 0)

    bot.reply_to(m, f"✅ 自动清理欢迎消息已{'开启' if new_state else '关闭'}")


def handle_get_welcome_command(bot, m, config: dict, db):
    """处理 /getwelcome 命令"""
    admin_id = config.get("ADMIN_ID", 0)
    if m.from_user.id != admin_id:
        bot.reply_to(m, "❌ 只有管理员可以查看配置")
        return

    welcome_config = get_welcome_config(db, m.chat.id)

    status = (
        f"📋 欢迎配置：\n"
        f"启用欢迎: {'是' if welcome_config['enable_welcome'] else '否'}\n"
        f"启用告别: {'是' if welcome_config['enable_goodbye'] else '否'}\n"
        f"启用群规: {'是' if welcome_config['enable_rules'] else '否'}\n"
        f"自动清理: {'是' if welcome_config['clean_welcome'] else '否'}\n\n"
        f"欢迎消息: {welcome_config['welcome_text']}\n"
        f"告别消息: {welcome_config['goodbye_text']}\n"
        f"群规: {welcome_config['rules_text']}"
    )

    bot.reply_to(m, status)
