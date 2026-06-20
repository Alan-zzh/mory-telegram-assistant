"""
投票创建 - 创建群组投票

命令：
  /poll 问题|选项1|选项2|... → handle_poll（匿名投票）
  /poll public 问题|选项1|选项2|... → handle_poll_public（公开投票）
"""
from core.logging_util import get_logger

logger = get_logger("poll_create")


def handle_poll(bot, m, config, db):
    """创建匿名投票"""
    _create_poll(bot, m, config, anonymous=True)


def handle_poll_public(bot, m, config, db):
    """创建公开投票"""
    _create_poll(bot, m, config, anonymous=False)


def _create_poll(bot, m, config, anonymous=True):
    """创建投票"""
    text = (m.text or "").strip()
    # 去掉命令部分
    parts = text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(m, "❌ 用法：/poll 问题|选项1|选项2|...\n示例：/poll 今天吃什么|火锅|烧烤|外卖")
        return

    content = parts[1].strip()

    # 如果有public关键字，去掉
    if content.lower().startswith("public"):
        anonymous = False
        content = content[6:].strip()

    # 解析问题和选项
    items = content.split("|")
    if len(items) < 3:
        bot.reply_to(m, "❌ 至少需要1个问题和2个选项\n格式：问题|选项1|选项2|...")
        return

    question = items[0].strip()
    options = [opt.strip() for opt in items[1:] if opt.strip()]

    if len(options) > 10:
        bot.reply_to(m, "❌ 选项最多10个")
        return

    if not question:
        bot.reply_to(m, "❌ 问题不能为空")
        return

    try:
        bot.send_poll(
            m.chat.id,
            question=question,
            options=options,
            is_anonymous=anonymous,
            reply_to_message_id=m.message_id
        )
        # 删除命令消息（受全局开关控制）
        if config.get("ENABLE_MESSAGE_DELETION", False):
            try:
                bot.delete_message(m.chat.id, m.message_id)
            except Exception as e:
                logger.debug(f"操作异常: {e}")
        poll_type = "匿名" if anonymous else "公开"
        logger.info(f"创建{poll_type}投票: question={question} options={len(options)}")

    except Exception as e:
        logger.error(f"创建投票异常: {e}")
        bot.reply_to(m, "❌ 创建投票失败")
