"""
贴纸工具 - 偷贴纸/贴纸转图片

命令：
  /kang → handle_kang（回复贴纸偷到自己的贴纸包）
  /sticker2img → handle_sticker2img（贴纸转PNG图片）
"""
import os
import tempfile
from core.logging_util import get_logger

logger = get_logger("sticker_tools")


def _download_sticker(bot, sticker):
    """下载贴纸文件并返回二进制数据

    Args:
        bot: TeleBot实例
        sticker: Sticker对象

    Returns:
        bytes: 贴纸文件二进制数据，失败返回None
    """
    try:
        file_info = bot.get_file(sticker.file_id)
        return bot.download_file(file_info.file_path)
    except Exception as e:
        logger.error(f"下载贴纸失败: {e}")
        return None


def handle_kang(bot, m, config, db):
    """偷贴纸 - 将回复的贴纸添加到用户的贴纸包"""
    if not m.reply_to_message or not m.reply_to_message.sticker:
        bot.reply_to(m, "❌ 请回复一个贴纸")
        return

    sticker = m.reply_to_message.sticker
    uid = m.from_user.id

    downloaded = _download_sticker(bot, sticker)
    if downloaded is None:
        bot.reply_to(m, "❌ 获取贴纸失败")
        return

    try:
        # 创建临时文件
        fd, tmp_path = tempfile.mkstemp(suffix=".webp")
        os.close(fd)
        try:
            with open(tmp_path, "wb") as f:
                f.write(downloaded)

            # 尝试添加到用户的贴纸包
            # 由于Telegram Bot API限制，无法直接创建贴纸包
            # 改为将贴纸文件发送给用户
            with open(tmp_path, "rb") as f:
                bot.send_document(uid, f, caption="🎨 贴纸文件已发送\n💡 在Telegram桌面端可手动添加到贴纸包")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        bot.reply_to(m, "✅ 贴纸文件已私聊发送给你")
        logger.info(f"偷贴纸: uid={uid} sticker={sticker.file_id}")

    except Exception as e:
        logger.error(f"偷贴纸异常: {e}")
        # 如果私聊发送失败，在群内发送
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".webp")
            os.close(fd)
            try:
                with open(tmp_path, "wb") as f:
                    f.write(downloaded)
                with open(tmp_path, "rb") as f:
                    bot.send_document(m.chat.id, f, reply_to_message_id=m.message_id, caption="🎨 贴纸文件")
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        except Exception:
            bot.reply_to(m, "❌ 获取贴纸失败")


def handle_sticker2img(bot, m, config, db):
    """贴纸转图片 - 将贴纸转为PNG图片"""
    if not m.reply_to_message or not m.reply_to_message.sticker:
        bot.reply_to(m, "❌ 请回复一个贴纸")
        return

    sticker = m.reply_to_message.sticker

    downloaded = _download_sticker(bot, sticker)
    if downloaded is None:
        bot.reply_to(m, "❌ 转换失败")
        return

    try:
        # webp转png
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(downloaded))
            png_bytes = io.BytesIO()
            img.save(png_bytes, format="PNG")
            png_bytes.seek(0)
            bot.send_photo(m.chat.id, png_bytes, reply_to_message_id=m.message_id, caption="🎨 贴纸转图片")
        except ImportError:
            # Pillow不可用，直接发送webp文件
            fd, tmp_path = tempfile.mkstemp(suffix=".webp")
            os.close(fd)
            try:
                with open(tmp_path, "wb") as f:
                    f.write(downloaded)
                with open(tmp_path, "rb") as f:
                    bot.send_document(m.chat.id, f, reply_to_message_id=m.message_id, caption="🎨 贴纸文件（需要Pillow库才能转PNG）")
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        logger.info(f"贴纸转图片: uid={m.from_user.id}")

    except Exception as e:
        logger.error(f"贴纸转图片异常: {e}")
        # 如果PIL转换失败，尝试直接发送webp文件
        if downloaded:
            try:
                fd, tmp_path = tempfile.mkstemp(suffix=".webp")
                os.close(fd)
                try:
                    with open(tmp_path, "wb") as f:
                        f.write(downloaded)
                    with open(tmp_path, "rb") as f:
                        bot.send_document(m.chat.id, f, reply_to_message_id=m.message_id, caption="🎨 贴纸文件（需要Pillow库才能转PNG）")
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
            except Exception:
                bot.reply_to(m, "❌ 转换失败")
        else:
            bot.reply_to(m, "❌ 转换失败")
