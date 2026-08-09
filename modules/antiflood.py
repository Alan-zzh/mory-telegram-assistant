"""
反刷屏系统 - 消息频率限制，超频自动禁言

功能：
  1. 检测用户短时间内大量发送消息
  2. 超频自动禁言+删除超频消息
  3. 白名单/管理员豁免
  4. 可配置时间窗口、阈值、禁言时长

命令：
  /antiflood on/off/status → handle_antiflood

数据表：antiflood_settings（chat_id, window, threshold, mute_duration, enabled, ts）
"""
import time
from collections import defaultdict
from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("antiflood")

# 内存缓存：{chat_id: {uid: [timestamp1, timestamp2, ...]}}
_flood_cache = defaultdict(lambda: defaultdict(list))


def check_antiflood(bot, m, config, db):
    """检查用户是否刷屏，返回True表示触发刷屏（消息应被处理/删除）"""
    chat_id = m.chat.id
    uid = m.from_user.id

    # 管理员豁免（三态：unknown 不处罚）
    try:
        from modules.ad_enforcement import _is_chat_admin_member
        admin_status = _is_chat_admin_member(bot, chat_id, uid)
        if admin_status == "admin":
            return False
        if admin_status == "unknown":
            logger.debug(f"antiflood 群管查询失败，跳过处罚: uid={uid} chat={chat_id}")
            return False
    except Exception as e:
        logger.debug(f"antiflood 群管检查异常，跳过处罚: {e}")
        return False
    # 获取群设置
    settings = _get_settings(db, chat_id)
    if not settings or not settings.get("enabled"):
        return False

    window = settings.get("window", 5)
    threshold = settings.get("threshold", 5)

    now = time.time()
    # 清理过期记录
    cache = _flood_cache[chat_id][uid]
    _flood_cache[chat_id][uid] = [t for t in cache if now - t < window]

    # 添加当前消息时间
    _flood_cache[chat_id][uid].append(now)

    # 检查是否超频
    if len(_flood_cache[chat_id][uid]) > threshold:
        return True
    return False


def handle_flood_user(bot, m, config, db):
    """处理刷屏用户：禁言+删除消息"""
    chat_id = m.chat.id
    uid = m.from_user.id
    uname = m.from_user.first_name or "用户"

    settings = _get_settings(db, chat_id)
    mute_duration = settings.get("mute_duration", 60) if settings else 60

    try:
        # 禁言用户
        bot.restrict_chat_member(
            chat_id, uid,
            until_date=int(time.time()) + mute_duration,
            can_send_messages=False
        )
        # 删除触发消息（受全局开关控制）
        if config.get("ENABLE_MESSAGE_DELETION", False):
            try:
                bot.delete_message(chat_id, m.message_id)
            except Exception as e:
                logger.debug(f"操作异常: {e}")
        else:
            logger.warning(f"[反刷屏] ENABLE_MESSAGE_DELETION 未开启，跳过删除消息")
        # 发送警告
        bot.send_message(
            chat_id,
            f"🚫 {uname} 因刷屏被禁言{mute_duration}秒\n"
            f"💡 请勿在短时间内发送大量消息"
        )
        logger.info(f"刷屏禁言: uid={uid} chat={chat_id} 时长={mute_duration}s")
    except Exception as e:
        logger.error(f"刷屏处理异常: {e}")

    # [TRAE SOLO CN] v5.19.0 群级刷屏介入：5 分钟内 ≥3 用户刷屏 → 高冷平息
    try:
        now = time.time()
        window = 300  # 5 分钟
        # 统计窗口内不同刷屏用户数
        recent_users = set()
        for _uid, timestamps in _flood_cache.get(chat_id, {}).items():
            recent = [t for t in timestamps if now - t < window]
            if len(recent) > 1:  # 该用户至少 2 条消息
                recent_users.add(_uid)
        if len(recent_users) >= 3:
            # 触发刷屏介入
            from modules.triggers.flood_mediate import trigger_flood_mediate
            # ResourceManager 通过全局获取（antiflood 无 rm 引用，用 bot/db/config 临时构造）
            try:
                from core.bot_initializer import _get_global_ctx
                _gctx = _get_global_ctx()
                if _gctx and _gctx.resource_manager:
                    trigger_flood_mediate(_gctx.resource_manager, chat_id, list(recent_users))
            except ImportError:
                pass  # _get_global_ctx 不存在时静默跳过
    except Exception as e:
        logger.debug(f"群级刷屏介入异常: {e}")


def _get_settings(db, chat_id):
    """获取群刷屏设置"""
    try:
        row = db.conn.execute(
            "SELECT window, threshold, mute_duration, enabled FROM antiflood_settings WHERE chat_id=?",
            (chat_id,)
        ).fetchone()
        if row:
            return {"window": row[0], "threshold": row[1], "mute_duration": row[2], "enabled": row[3]}
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    return None


def handle_antiflood(bot, m, config, db):
    """处理 /antiflood 命令"""
    chat_id = m.chat.id
    uid = m.from_user.id
    text = (m.text or "").strip()
    parts = text.split()

    # 权限检查
    try:
        member = bot.get_chat_member(chat_id, uid)
        if member.status not in ("administrator", "creator"):
            bot.reply_to(m, "❌ 仅管理员可设置反刷屏")
            return
    except Exception:
        return

    if len(parts) < 2:
        # 显示当前状态
        settings = _get_settings(db, chat_id)
        if settings and settings.get("enabled"):
            bot.reply_to(m, f"📊 反刷屏状态：开启\n⏱ 窗口：{settings['window']}秒\n📈 阈值：{settings['threshold']}条\n🔇 禁言：{settings['mute_duration']}秒")
        else:
            bot.reply_to(m, "📊 反刷屏状态：关闭")
        return

    action = parts[1].lower()
    now_ts = int(time.time())

    if action == "on":
        cfg = config.get("ANTIFLOOD_CONFIG", {})
        window = cfg.get("window", 5)
        threshold = cfg.get("threshold", 5)
        mute_duration = cfg.get("mute_duration", 60)
        with _db_lock:
            db.conn.execute(
                "INSERT OR REPLACE INTO antiflood_settings (chat_id, window, threshold, mute_duration, enabled, ts) VALUES (?,?,?,?,?,?)",
                (chat_id, window, threshold, mute_duration, 1, now_ts)
            )
            db.conn.commit()
        bot.reply_to(m, f"✅ 反刷屏已开启\n⏱ 窗口：{window}秒 | 阈值：{threshold}条 | 禁言：{mute_duration}秒")

    elif action == "off":
        with _db_lock:
            db.conn.execute(
                "INSERT OR REPLACE INTO antiflood_settings (chat_id, window, threshold, mute_duration, enabled, ts) VALUES (?,?,?,?,?,?)",
                (chat_id, 5, 5, 60, 0, now_ts)
            )
            db.conn.commit()
        bot.reply_to(m, "✅ 反刷屏已关闭")

    elif action == "set" and len(parts) >= 4:
        # /antiflood set window 10  or /antiflood set threshold 8
        try:
            param = parts[2].lower()
            value = int(parts[3])
            settings = _get_settings(db, chat_id) or {"window": 5, "threshold": 5, "mute_duration": 60}
            if param == "window":
                settings["window"] = value
            elif param == "threshold":
                settings["threshold"] = value
            elif param in ("mute", "duration"):
                settings["mute_duration"] = value
            else:
                bot.reply_to(m, "❌ 参数名：window / threshold / duration")
                return
            with _db_lock:
                db.conn.execute(
                    "INSERT OR REPLACE INTO antiflood_settings (chat_id, window, threshold, mute_duration, enabled, ts) VALUES (?,?,?,?,?,?)",
                    (chat_id, settings["window"], settings["threshold"], settings["mute_duration"], 1, now_ts)
                )
                db.conn.commit()
            bot.reply_to(m, f"✅ 已更新：{param}={value}")
        except ValueError:
            bot.reply_to(m, "❌ 值必须是数字")
    else:
        bot.reply_to(m, "用法：/antiflood on/off/set\n/antiflood set window 10\n/antiflood set threshold 8")


def cleanup_flood_cache(max_age: int = 60):
    """清理超过 max_age 秒未更新的刷屏缓存条目"""
    now = time.time()
    removed_count = 0
    expired_chats = []
    for chat_id, uid_cache in list(_flood_cache.items()):
        for uid, timestamps in list(uid_cache.items()):
            # 过滤掉最近 max_age 秒内无时间戳的条目
            recent = [t for t in timestamps if now - t <= max_age]
            if not recent:
                del uid_cache[uid]
                removed_count += 1
            else:
                uid_cache[uid] = recent
        if not uid_cache:
            expired_chats.append(chat_id)
    for chat_id in expired_chats:
        del _flood_cache[chat_id]
    if removed_count:
        logger.debug(f"🧹 清理 {removed_count} 个过期刷屏缓存条目")


def is_approved(db, chat_id, uid):
    """检查用户是否在白名单中"""
    try:
        row = db.conn.execute(
            "SELECT 1 FROM approved_users WHERE chat_id=? AND uid=?",
            (chat_id, uid)
        ).fetchone()
        return row is not None
    except Exception:
        return False
