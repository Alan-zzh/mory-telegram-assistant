"""
二维码生成 - 将文本转为二维码图片

命令：
  /qr 文本内容 → handle_qr_code
"""
import os
import tempfile
from core.logging_util import get_logger

try:
    import qrcode
    _HAS_QR = True
except ImportError:
    _HAS_QR = False

logger = get_logger("qr_code")


def handle_qr_code(bot, m, config, db):
    """生成二维码"""
    if not _HAS_QR:
        bot.reply_to(m, "❌ 二维码功能未安装依赖（qrcode库）")
        return

    text = (m.text or "").strip()
    # 去掉命令部分
    parts = text.split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(m, "❌ 用法：/qr 文本内容")
        return

    content = parts[1].strip()
    if len(content) > 2000:
        bot.reply_to(m, "❌ 文本过长，最多2000字符")
        return

    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(content)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        fd, tmp_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            img.save(tmp_path, "PNG")
            with open(tmp_path, "rb") as f:
                bot.send_photo(m.chat.id, f, reply_to_message_id=m.message_id, caption=f"📎 二维码内容：{content[:50]}{'...' if len(content) > 50 else ''}")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        logger.info(f"二维码生成: uid={m.from_user.id} len={len(content)}")
    except Exception as e:
        logger.error(f"二维码生成异常: {e}")
        bot.reply_to(m, "❌ 二维码生成失败")
