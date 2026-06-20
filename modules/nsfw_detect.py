"""
NSFW检测 - 图片安全检测

功能：
  1. 自动检测图片NSFW评分
  2. 超阈值自动删除
  3. 手动检测命令

命令：
  /nsfw → handle_nsfw_check（回复图片检测）
  /nsfw on/off → handle_nsfw_toggle

数据表：nsfw_settings（chat_id, enabled, threshold, ts）
"""
import time
import json
import urllib.request
from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("nsfw_detect")


def _get_settings(db, chat_id):
    """获取NSFW设置"""
    try:
        row = db.conn.execute(
            "SELECT enabled, threshold FROM nsfw_settings WHERE chat_id=?",
            (chat_id,)
        ).fetchone()
        if row:
            return {"enabled": row[0], "threshold": row[1]}
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    return None


def check_nsfw_image(bot, m, config, db):
    """检查图片是否NSFW，返回True表示图片不安全（已删除）"""
    chat_id = m.chat.id

    # 检查是否开启
    settings = _get_settings(db, chat_id)
    if not settings or not settings.get("enabled"):
        nsfw_config = config.get("NSFW_DETECT_CONFIG", {})
        if not nsfw_config.get("enabled", False):
            return False

    threshold = settings.get("threshold", 0.7) if settings else config.get("NSFW_DETECT_CONFIG", {}).get("threshold", 0.7)

    # 获取图片
    photo = None
    if m.photo:
        photo = m.photo[-1]  # 最大尺寸
    elif m.document and m.document.mime_type and m.document.mime_type.startswith("image/"):
        photo = m.document
    else:
        return False

    # 管理员豁免
    uid = m.from_user.id
    try:
        member = bot.get_chat_member(chat_id, uid)
        if member.status in ("administrator", "creator"):
            return False
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    # 调用NSFW检测API
    try:
        score = _detect_nsfw(bot, photo, config)
        if score is not None and score >= threshold:
            if config.get("ENABLE_MESSAGE_DELETION", False):
                bot.delete_message(chat_id, m.message_id)
            else:
                logger.warning(f"[NSFW检测] ENABLE_MESSAGE_DELETION 未开启，跳过删除消息")
            bot.send_message(chat_id, f"🚫 图片因不安全内容被自动删除（NSFW评分：{score:.2f}）")
            logger.info(f"NSFW删除: chat={chat_id} uid={uid} score={score:.2f}")
            return True
    except Exception as e:
        logger.error(f"NSFW检测异常: {e}")

    return False


def _detect_nsfw(bot, photo, config):
    """调用NSFW检测API，返回评分0-1"""
    api_key = config.get("NSFW_DETECT_CONFIG", {}).get("api_key", "")
    if not api_key:
        return None

    try:
        # 下载图片到内存（避免将含 Token 的 URL 传给第三方或写入日志）
        file_info = bot.get_file(photo.file_id)
        img_bytes = bot.download_file(file_info.file_path)

        # 调用deepai NSFW检测API（上传图片字节，而非传URL）
        boundary = "----MoryNSFWBoundary7MA4YWxkTrZu0gW"
        body = (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"image\"; filename=\"image.jpg\"\r\n"
            f"Content-Type: image/jpeg\r\n\r\n"
        ).encode("utf-8") + img_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
        req = urllib.request.Request(
            "https://api.deepai.org/api/nsfw-detector",
            data=body,
            headers={
                "Api-Key": api_key,
                "Content-Type": f"multipart/form-data; boundary={boundary}"
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        return result.get("output", {}).get("nsfw_score", 0)

    except Exception as e:
        # [TRAE SOLO CN] 安全修复：异常日志不包含含 Token 的 URL
        logger.error(f"NSFW API调用异常: {e}")
        return None


def handle_nsfw_check(bot, m, config, db):
    """手动检测图片NSFW评分"""
    if not m.reply_to_message:
        bot.reply_to(m, "❌ 请回复一张图片")
        return

    reply = m.reply_to_message
    photo = None
    if reply.photo:
        photo = reply.photo[-1]
    elif reply.document and reply.document.mime_type and reply.document.mime_type.startswith("image/"):
        photo = reply.document
    else:
        bot.reply_to(m, "❌ 回复的消息中没有图片")
        return

    score = _detect_nsfw(bot, photo, config)
    if score is not None:
        level = "安全" if score < 0.3 else "可疑" if score < 0.7 else "不安全"
        bot.reply_to(m, f"🔍 NSFW评分：{score:.4f}\n📊 等级：{level}")
    else:
        bot.reply_to(m, "❌ 检测失败（可能未配置API密钥）")


def handle_nsfw_toggle(bot, m, config, db):
    """开关NSFW检测"""
    chat_id = m.chat.id
    uid = m.from_user.id
    text = (m.text or "").strip()
    parts = text.split()

    # 权限检查
    try:
        member = bot.get_chat_member(chat_id, uid)
        if member.status not in ("administrator", "creator"):
            bot.reply_to(m, "❌ 仅管理员可设置NSFW检测")
            return
    except Exception:
        return

    if len(parts) < 2:
        settings = _get_settings(db, chat_id)
        if settings:
            status = "开启" if settings["enabled"] else "关闭"
            bot.reply_to(m, f"📊 NSFW检测状态：{status}\n阈值：{settings['threshold']}")
        else:
            bot.reply_to(m, "📊 NSFW检测状态：关闭\n\n用法：/nsfw on/off")
        return

    action = parts[1].lower()
    now_ts = int(time.time())
    threshold = config.get("NSFW_DETECT_CONFIG", {}).get("threshold", 0.7)

    if action == "on":
        with _db_lock:
            db.conn.execute(
                "INSERT OR REPLACE INTO nsfw_settings (chat_id, enabled, threshold, ts) VALUES (?,?,?,?)",
                (chat_id, 1, threshold, now_ts)
            )
            db.conn.commit()
        bot.reply_to(m, f"✅ NSFW检测已开启（阈值：{threshold}）")
    elif action == "off":
        with _db_lock:
            db.conn.execute(
                "INSERT OR REPLACE INTO nsfw_settings (chat_id, enabled, threshold, ts) VALUES (?,?,?,?)",
                (chat_id, 0, threshold, now_ts)
            )
            db.conn.commit()
        bot.reply_to(m, "✅ NSFW检测已关闭")
    else:
        bot.reply_to(m, "用法：/nsfw on/off")
