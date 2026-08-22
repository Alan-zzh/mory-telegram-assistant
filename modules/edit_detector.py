"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/edit_detector.py  ·  编辑消息检测模块                          ║
║                                                                        ║
║  功能：监听用户编辑消息事件，重新跑广告检测。                            ║
║        防止"先正常消息后编辑成广告"的攻击。                              ║
║
║  流程：                                                                ║
║    1. 监听 edited_message 事件                                        ║
║    2. 保存原始消息快照（第一条消息）                                    ║
║    3. 编辑后重新跑广告检测                                              ║
║    4. 检测通过则放行，不通过则删除编辑后的消息                          ║
║
║  被调用：main.py edited_message_handler                                ║
══════════════════════════════════════════════════════════════════════════╝
"""

import threading
import time
from core.logging_util import get_logger

logger = get_logger("edit_detector")


# 原始消息快照存储（内存级）
# { (chat_id, message_id): { "original_text": str, "original_date": int } }
_message_snapshots = {}
_snapshots_lock = threading.Lock()


def snapshot_message(chat_id: int, message_id: int, text: str):
    """保存原始消息快照"""
    with _snapshots_lock:
        _message_snapshots[(chat_id, message_id)] = {
            "original_text": text,
            "original_date": int(time.time()),
        }


def get_snapshot(chat_id: int, message_id: int):
    """获取原始消息快照"""
    with _snapshots_lock:
        return _message_snapshots.get((chat_id, message_id))


def delete_snapshot(chat_id: int, message_id: int):
    """删除快照（消息被删除后清理）"""
    with _snapshots_lock:
        _message_snapshots.pop((chat_id, message_id), None)


def check_edited_message(bot, m, config: dict, db, ai, ad_detector=None) -> bool:
    """
    检查编辑后的消息
    返回 True 表示已处理（检测到广告并删除）
    """
    chat_id = m.chat.id
    message_id = m.message_id
    new_text = m.text or ""
    edited_date = m.edit_date

    if not new_text or len(new_text) < 5:
        return False

    # 跳过 Bot 命令（编辑后的 /cmd@bot 不检测广告）
    if new_text.startswith("/"):
        return False

    # 检查是否有原始快照
    snapshot = get_snapshot(chat_id, message_id)
    if not snapshot:
        # 没有快照，说明是Bot编辑的消息或其他情况，跳过
        return False

    original_text = snapshot["original_text"]

    # 如果内容没变化，跳过
    if original_text == new_text:
        return False

    # 重新跑广告检测
    if ad_detector is None:
        return False

    username = (m.from_user.first_name or "") + (m.from_user.last_name or "")
    uid = m.from_user.id
    result = ad_detector.detect(username=username, msg=new_text, user_id=uid, bot=bot, chat_id=chat_id)

    if result["is_ad"]:
        uid = m.from_user.id
        logger.warning(
            f"🚨 编辑消息检测命中广告: uid={uid} "
            f"原始={original_text[:50]}... → 编辑后={new_text[:50]}..."
        )

        # 删除编辑后的消息
        try:
            bot.delete_message(chat_id, message_id)
            logger.info(f"[编辑检测] 已删除消息 msg_id={message_id} uid={uid}")
        except Exception as e:
            logger.warning(f"删除编辑后的广告消息失败: {e}")

        # 加黑名单（封禁 = 加黑名单 + 删消息，两步缺一不可）
        if db:
            try:
                db.conn.execute(
                    "INSERT OR IGNORE INTO global_blacklist (user_id, reason, added_by, added_at) VALUES (?,?,?,datetime('now'))",
                    (uid, f"编辑消息广告: {new_text[:50]}", bot.get_me().id)
                )
                db.conn.commit()
                logger.info(f"[编辑检测] 已加入全局黑名单: uid={uid}")
            except Exception as e:
                logger.warning(f"加入全局黑名单失败: {e}")

        # 通知管理员
        admin_id = config.get("ADMIN_ID", 0)
        if admin_id:
            try:
                from modules.ad_enforcement import _build_unban_markup
                bot.send_message(
                    admin_id,
                    f"🚨 编辑消息检测\n"
                    f"👤 用户：{m.from_user.first_name or '未知'}(id={uid})\n"
                    f"📝 原始：{original_text[:100]}\n"
                    f"✏️ 编辑后：{new_text[:100]}\n"
                    f"🎯 检测结果：广告（{result['score']}分）\n"
                    f"📋 操作：删除消息 + 加黑名单",
                    reply_markup=_build_unban_markup(uid, chat_id),
                )
            except Exception as e:
                logger.debug(f"操作异常: {e}")
        return True

    # 检测通过，更新快照
    with _snapshots_lock:
        if (chat_id, message_id) in _message_snapshots:
            _message_snapshots[(chat_id, message_id)]["original_text"] = new_text
    return False


def cleanup_old_snapshots(max_age: int = 86400):
    """清理过期快照（默认保留24小时）"""
    now = time.time()
    with _snapshots_lock:
        expired = [
            k for k, v in _message_snapshots.items()
            if now - v["original_date"] > max_age
        ]
        for key in expired:
            del _message_snapshots[key]
    if expired:
        logger.info(f"🧹 清理 {len(expired)} 个过期消息快照")


# ── APScheduler 定时任务注册 ──────────────────────────────────────────
# 过期快照清理由统一调度器每小时任务调用
# 历史注记：v5.38.69 前需在 auto_tasks 定时列表手工添加，现走 BaseTask 自动发现：
#   ("edit_detector_cleanup", cleanup_old_snapshots, "interval", {"hours": 1})
_CRON_JOBS = [
    {
        "id": "edit_detector_cleanup",
        "func": cleanup_old_snapshots,
        "trigger": "interval",
        "kwargs": {"hours": 1},
        "description": "清理过期编辑消息快照",
    }
]
