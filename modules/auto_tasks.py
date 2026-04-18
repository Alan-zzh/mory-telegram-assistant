"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/auto_tasks.py  ·  后台自动任务引擎（APScheduler版）        ║
║                                                                        ║
║  【架构重构 v21.44】                                                   ║
║    移除了 while True 阻塞循环，改为 APScheduler 独立 Job。            ║
║    各任务互不干扰，解决了「一个任务卡住导致整点新闻漏发」的问题。      ║
║                                                                        ║
║  功能清单：                                                            ║
║    1. 新闻播报（9:00/13:00/20:30）                                    ║
║    2. 早/午/晚安问候（8:00/12:30/23:00）                             ║
║    3. 叫醒服务（每分钟检查）                                           ║
║    4. 阅后即焚探测（每3分钟一次）                                      ║
║    5. 阅后即焚孤儿清理（每小时一次）                                   ║
║    6. 醋意挽回（每小时一次）                                           ║
║    7. 购物车挽回（每小时一次）                                         ║
║    8. 背刺泄密（每周一次）                                             ║
║    9. 数据库备份（每小时一次）                                         ║
║    10. TTL历史数据清理（每小时一次）                                    ║
║    11. 配置保存（仅模型索引变化时）                                     ║
║                                                                        ║
║  启动方式：start_background(bot, config, db, ai, save_config)         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
import random
import glob
import os
import threading
import hashlib
from typing import Any, Dict
from datetime import datetime, timedelta, timezone
from core.logging_util import get_logger
from core.resource_manager import ResourceManager

logger = get_logger("auto_tasks")

# 尝试导入 APScheduler（可选依赖，未安装则回退到旧版 while True）
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    logger.warning("⚠️ APScheduler 未安装，将使用旧版 while True 循环")

# 记录上次保存的模型索引，避免重复写文件
_last_saved_model_idx = None

# 时区：VPS默认UTC，强制用北京时间(UTC+8)
_CST = timezone(timedelta(hours=8))


def _send_and_track(rm, chat_id, text, user_msg_id=0):
    """发送消息（主动消息不追踪，只有回复才追踪）"""
    try:
        with rm.locked('bot'):
            sent = rm.bot.send_message(chat_id, text)
        return sent
    except Exception as e:
        logger.error(f"发送失败：{e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# APScheduler 版本：独立 Job，互不干扰
# ═══════════════════════════════════════════════════════════════════════════

def _job_news_morning(rm):
    """早间新闻播报（9:00）"""
    try:
        with rm.locked('config'):
            gid = rm.config.get("GROUP_ID", 0)
        if gid == 0:
            return
        
        logger.info("📰 触发早间新闻播报（实时获取）")
        seed = random.randint(100000, 999999)
        from core.ai_engine import fetch_real_news
        raw_news = fetch_real_news() or ""
        lines = [l for l in raw_news.split("\n") if l.strip()][:5]
        news_input = "\n".join(lines) if lines else "今日热点"
        
        with rm.locked('ai'):
            news = rm.ai.ask(news_input, mode="news", seed=seed)
        if news:
            _send_and_track(rm, gid, news)
            logger.info(f"✅ 早间新闻已发送")
    except Exception as e:
        logger.error(f"早间新闻播报失败：{e}")


def _job_news_afternoon(rm):
    """午间新闻播报（13:00）"""
    try:
        with rm.locked('config'):
            gid = rm.config.get("GROUP_ID", 0)
        if gid == 0:
            return
        
        logger.info("📰 触发午间新闻播报（实时获取）")
        seed = random.randint(100000, 999999)
        from core.ai_engine import fetch_real_news
        raw_news = fetch_real_news() or ""
        lines = [l for l in raw_news.split("\n") if l.strip()][:5]
        news_input = "\n".join(lines) if lines else "今日热门"
        
        with rm.locked('ai'):
            news = rm.ai.ask(news_input, mode="afternoon_news", seed=seed)
        if news:
            _send_and_track(rm, gid, news)
            logger.info(f"✅ 午间新闻已发送")
    except Exception as e:
        logger.error(f"午间新闻播报失败：{e}")


def _job_news_evening(rm):
    """晚间新闻播报（20:30）"""
    try:
        with rm.locked('config'):
            gid = rm.config.get("GROUP_ID", 0)
        if gid == 0:
            return
        
        logger.info("📰 触发晚间新闻播报（实时获取）")
        seed = random.randint(100000, 999999)
        from core.ai_engine import fetch_real_news
        raw_news = fetch_real_news() or ""
        lines = [l for l in raw_news.split("\n") if l.strip()][:5]
        news_input = "\n".join(lines) if lines else "今日回顾"
        
        with rm.locked('ai'):
            news = rm.ai.ask(news_input, mode="evening_news", seed=seed)
        if news:
            _send_and_track(rm, gid, news)
            logger.info(f"✅ 晚间新闻已发送")
    except Exception as e:
        logger.error(f"晚间新闻播报失败：{e}")


def _job_greeting_morning(rm):
    """早安问候（8:00）"""
    try:
        with rm.locked('config'):
            gid = rm.config.get("GROUP_ID", 0)
        if gid == 0:
            return
        
        seed = random.randint(100000, 999999)
        with rm.locked('ai'):
            msg = rm.ai.ask("早安", mode="morning", seed=seed)
        if msg:
            msg = msg.replace("\n", " ").strip()[:100]
            _send_and_track(rm, gid, f"☀️ {msg}")
            logger.info(f"☀️ 早安已发送：{msg}")
    except Exception as e:
        logger.error(f"早安问候失败：{e}")


def _job_greeting_afternoon(rm):
    """午安问候（12:30）"""
    try:
        with rm.locked('config'):
            gid = rm.config.get("GROUP_ID", 0)
        if gid == 0:
            return
        
        seed = random.randint(100000, 999999)
        with rm.locked('ai'):
            msg = rm.ai.ask("午安", mode="afternoon", seed=seed)
        if msg:
            msg = msg.replace("\n", " ").strip()[:100]
            _send_and_track(rm, gid, f"🍃 {msg}")
            logger.info(f"🍃 午安已发送：{msg}")
    except Exception as e:
        logger.error(f"午安问候失败：{e}")


def _job_greeting_evening(rm):
    """晚安问候（23:00）"""
    try:
        with rm.locked('config'):
            gid = rm.config.get("GROUP_ID", 0)
        if gid == 0:
            return
        
        seed = random.randint(100000, 999999)
        with rm.locked('ai'):
            msg = rm.ai.ask("晚安", mode="evening", seed=seed)
        if msg:
            msg = msg.replace("\n", " ").strip()[:100]
            _send_and_track(rm, gid, f"🌙 {msg}")
            logger.info(f"🌙 晚安已发送：{msg}")
    except Exception as e:
        logger.error(f"晚安问候失败：{e}")


def _job_wakeup_check(rm):
    """叫醒服务检查（每分钟）"""
    try:
        now = datetime.now(_CST)
        time_str = now.strftime("%H:%M")
        
        with rm.locked_multi(['db', 'bot', 'config']):
            for uid, wake_time in rm.db.get_all_wake_ups():
                if wake_time == time_str:
                    try:
                        rm.bot.send_message(uid,
                            "起床啦哥哥～ 太阳晒屁股了，"
                            f"新的一天也要像爱{rm.config['BOT_NAME']}老板一样充满活力哦！☀️")
                    except Exception as e:
                        logger.warning(f"叫醒服务发送失败 uid={uid}：{e}")
    except Exception as e:
        logger.error(f"叫醒服务检查失败：{e}")


def _job_burn_probe(rm):
    """阅后即焚探测（每3分钟）"""
    global _last_saved_model_idx
    try:
        ts = int(time.time())
        unconfirmed = rm.db.get_unconfirmed_messages()  # 【修复v21.47】24小时窗口，默认参数
        
        if unconfirmed:
            logger.info(f"🔥 阅后即焚探测：{len(unconfirmed)}条消息待检查")
        
        flood_wait = False
        loop_start = time.time()
        MAX_PROBE_TIME = 30  # 单轮探测最多30秒
        
        for bot_mid, cid, user_mid in unconfirmed[:20]:
            if time.time() - loop_start > MAX_PROBE_TIME:
                logger.warning("⚠️ 阅后即焚探测超时(>30s)，提前退出")
                break
            if flood_wait:
                break
            if user_mid == 0:
                continue
            
            delete_success = False
            for _retry in range(3):
                try:
                    with rm.locked_multi(['bot', 'config']):
                        probe = rm.bot.forward_message(
                            rm.config["ADMIN_ID"], cid, user_mid,
                            disable_notification=True
                        )
                        try:
                            rm.bot.delete_message(rm.config["ADMIN_ID"], probe.message_id)
                        except Exception as e:
                            logger.warning(f"清理探测转发消息失败：{e}")
                    delete_success = True
                    break
                except Exception as e:
                    err = str(e).lower()
                    
                    if "too many requests" in err:
                        logger.warning("⚠️ 触发Telegram频率限制，暂停本轮探测")
                        flood_wait = True
                        break
                    
                    forward_failed_keywords = [
                        "not found", "message_id_invalid", "bad request",
                        "forbidden", "chat", "deleted"
                    ]
                    if any(kw in err for kw in forward_failed_keywords):
                        for del_retry in range(3):
                            try:
                                with rm.locked_multi(['bot', 'db']):
                                    rm.bot.delete_message(cid, int(bot_mid))
                                    rm.db.delete_tracked(bot_mid)
                                logger.info(
                                    f"✅ 阅后即焚成功触发(第{del_retry+1}次) "
                                    f"bot_msg={bot_mid} chat={cid} "
                                    f"原因: 原消息{user_mid}已删 [{err[:80]}]"
                                )
                                delete_success = True
                                break
                            except Exception as del_err:
                                del_err_str = str(del_err).lower()
                                if any(kw in del_err_str for kw in [
                                    "not found", "message to delete not found",
                                    "message_id_invalid"
                                ]):
                                    with rm.locked('db'):
                                        rm.db.delete_tracked(bot_mid)
                                    logger.info(
                                        f"⚠️ 阅后即焚: bot_msg={bot_mid} 已不存在, "
                                        f"已清除追踪记录 (原消息{user_mid}已删)"
                                    )
                                    delete_success = True
                                    break
                                elif del_retry < 2:
                                    time.sleep(2 * (del_retry + 1))
                        
                        if delete_success:
                            break
                    else:
                        logger.warning(f"🔥 阅后即焚探测异常 bot={bot_mid}: {err[:200]}")
                        break
            
            time.sleep(0.5)
    except Exception as e:
        logger.error(f"阅后即焚探测失败：{e}")


def _job_burn_orphan(rm):
    """阅后即焚孤儿清理（每小时）"""
    try:
        with rm.locked_multi(['bot', 'db']):
            orphans = rm.db.get_orphan_messages(86400)
            if orphans:
                logger.info(f"🗑️ 阅后即焚孤儿清理：{len(orphans)}条消息待删除")
                for bot_mid, cid, user_mid in orphans:
                    try:
                        rm.bot.delete_message(cid, int(bot_mid))
                    except Exception as del_err:
                        logger.debug(f"阅后即焚孤儿消息已不存在: bot={bot_mid} err={del_err}")
                    rm.db.delete_tracked(bot_mid, cid)
    except Exception as e:
        logger.error(f"阅后即焚孤儿清理失败：{e}")


def _job_reactivate(rm):
    """醋意挽回（每小时）"""
    try:
        ts = int(time.time())
        three_days_ago = ts - 259200
        
        with rm.locked_multi(['db', 'bot', 'config']):
            inactive = rm.db.get_inactive_users(three_days_ago, rm.config.get("ADMIN_ID", 0))
            for uid, _name in inactive[:3]:
                if random.random() < 0.25:
                    try:
                        rm.bot.send_message(uid,
                            f"哥哥，这几天去哪了？是不是去看别的妹妹了？"
                            f"{rm.config['BOT_NAME']}老板都问起你了哼！")
                        rm.db.reset_last_active(uid)
                        logger.info(f"💌 醋意挽回：{uid}")
                    except Exception as e:
                        logger.warning(f"醋意挽回发送失败 uid={uid}：{e}")
    except Exception as e:
        logger.error(f"醋意挽回失败：{e}")


def _job_cart_recovery(rm):
    """购物车挽回（每小时）"""
    try:
        with rm.locked_multi(['db', 'bot', 'config']):
            for uid in rm.db.get_expired_carts(86400):
                try:
                    rm.bot.send_message(uid,
                        f"哥哥昨天问了门槛又没来，是{rm.config['BOT_NAME']}哪里不够好吗？"
                        f"来陪小助理聊聊天嘛～")
                    rm.db.log_conversion_event(uid, "interested")
                    logger.info(f"🛒 购物车挽回：{uid}")
                except Exception as e:
                    logger.warning(f"购物车挽回发送失败 uid={uid}：{e}")
    except Exception as e:
        logger.error(f"购物车挽回失败：{e}")


def _job_leak(rm):
    """背刺泄密（每周一次）"""
    global _last_saved_model_idx
    try:
        now = datetime.now(_CST)
        current_week = now.isocalendar()[1]
        
        with rm.locked_multi(['config']):
            gid = rm.config.get("GROUP_ID", 0)
            last_leak_week = rm.config.get("_LAST_LEAK_WEEK", -1)
        
        if gid == 0 or current_week == last_leak_week or now.weekday() < 2:
            return
        
        seed = random.randint(100000, 999999)
        scene_hint = random.choice([
            "在便利店买东西", "一个人看电视剧", "刷手机的时候",
            "发呆的时候", "跟闺蜜聊天", "自拍的时候", "做饭的时候",
            "洗澡前", "刚睡醒", "走路的时候", "吃零食的时候",
            "整理房间", "加班的时候", "逛街的时候", "坐地铁的时候",
            "打视频电话", "化妆的时候", "喝奶茶的时候", "拍照片",
        ])
        leak_prompt = (
            f"种子{seed}，场景：{scene_hint}。"
            f"用极度八卦、偷偷摸摸的语气，泄露一个关于Mory老板非常可爱、"
            f"生活化的小癖好或小秘密。要求：\n"
            f"1. 必须是全新的、独特的内容，绝对不能重复\n"
            f"2. 要有画面感和生活气息\n"
            f"3. 控制在25字以内\n"
            f"4. 不要出现任何编号、序号或列表格式"
        )
        
        with rm.locked('ai'):
            leak = rm.ai.ask(leak_prompt, mode="leak")
        
        if leak:
            try:
                _send_and_track(rm, gid, f"🤫 老板不在... 偷偷跟你们说：\n\n{leak}")
                rm.config["_LAST_LEAK_WEEK"] = current_week
                rm.save_config_fn()
                logger.info(f"🤫 背刺泄密触发(周{current_week})：{leak[:30]}")
            except Exception as e:
                logger.warning(f"背刺泄密发送失败：{e}")
    except Exception as e:
        logger.error(f"背刺泄密失败：{e}")


def _job_backup(rm):
    """数据库备份（每小时）。
    
    【修复v21.47】移除外层锁，利用SQLite自带的WAL热备机制。
    SQLite的.backup() API本身就是为不锁死业务而设计的，外层加锁反而会导致
    备份期间所有消息处理被阻塞（几秒到十几秒的卡顿）。
    """
    try:
        # 直接备份，不阻塞主业务
        _do_backup(rm.db.db_file)
    except Exception as e:
        logger.error(f"数据库备份失败：{e}")


def _job_ttl_cleanup(rm):
    """TTL历史数据清理（每小时）"""
    try:
        ts = int(time.time())
        cutoff = ts - 7 * 86400  # 7天前
        with rm.locked('db'):
            c = rm.db.conn.cursor()
            c.execute("DELETE FROM reply_tracking WHERE ts < ?", (cutoff,))
            deleted_track = c.rowcount
            c.execute("DELETE FROM spam_track WHERE COALESCE(window_start,0) < ?", (cutoff,))
            deleted_spam = c.rowcount
            c.execute("DELETE FROM puzzle_daily WHERE ts < ?", (cutoff,))
            deleted_puzzle = c.rowcount
            rm.db.conn.commit()
        if deleted_track or deleted_spam or deleted_puzzle:
            logger.info(f"🧹 TTL清理: 阅后即焚{deleted_track}条 + 反刷{deleted_spam}条 + 碎片{deleted_puzzle}条(>7天)")
    except Exception as e:
        logger.error(f"TTL清理失败：{e}")


def _job_save_config(rm):
    """配置保存（仅模型索引变化时）"""
    global _last_saved_model_idx
    try:
        with rm.locked('config'):
            current_idx = rm.config.get("CURRENT_MODEL_INDEX", 0)
        if _last_saved_model_idx is None or _last_saved_model_idx != current_idx:
            with rm.locked('config'):
                rm.save_config_fn()
            _last_saved_model_idx = current_idx
    except Exception as e:
        logger.error(f"配置保存失败：{e}")


def _do_backup(db_file: str):
    """执行数据库备份，保留最近7天（168份）"""
    os.makedirs("backup", exist_ok=True)
    ts_str = datetime.now().strftime("%Y%m%d_%H00")
    dest = f"backup/mory_backup_{ts_str}.db"
    try:
        import sqlite3 as _sqlite3
        src_conn = _sqlite3.connect(db_file)
        dst_conn = _sqlite3.connect(dest)
        src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()
        backups = sorted(glob.glob("backup/mory_backup_*.db"))
        for old in backups[:-168]:
            os.remove(old)
        logger.info(f"💾 备份完成：{dest}")
    except Exception as e:
        logger.error(f"备份失败：{e}")


def start_background(bot, config: Dict[str, Any], db, ai, save_config_fn):
    """启动后台任务引擎"""
    rm = ResourceManager(bot=bot, ai=ai, db=db, config=config, save_config_fn=save_config_fn)
    
    if HAS_APSCHEDULER:
        _start_with_apscheduler(rm)
    else:
        _start_with_legacy_loop(rm)


def _start_with_apscheduler(rm):
    """APScheduler 版本：独立 Job"""
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    
    # 新闻播报
    scheduler.add_job(_job_news_morning, "cron", hour=9, minute=5, args=[rm], id="news_morning")
    scheduler.add_job(_job_news_afternoon, "cron", hour=13, minute=5, args=[rm], id="news_afternoon")
    scheduler.add_job(_job_news_evening, "cron", hour=20, minute=35, args=[rm], id="news_evening")
    
    # 问候
    scheduler.add_job(_job_greeting_morning, "cron", hour=8, minute=5, args=[rm], id="greeting_morning")
    scheduler.add_job(_job_greeting_afternoon, "cron", hour=12, minute=35, args=[rm], id="greeting_afternoon")
    scheduler.add_job(_job_greeting_evening, "cron", hour=23, minute=5, args=[rm], id="greeting_evening")
    
    # 叫醒服务（每分钟）
    scheduler.add_job(_job_wakeup_check, "cron", minute="*", args=[rm], id="wakeup_check")
    
    # 阅后即焚（每3分钟）
    scheduler.add_job(_job_burn_probe, "cron", minute="*", args=[rm], id="burn_probe")
    
    # 每小时任务
    scheduler.add_job(_job_burn_orphan, "cron", minute=0, args=[rm], id="burn_orphan")
    scheduler.add_job(_job_reactivate, "cron", minute=5, args=[rm], id="reactivate")
    scheduler.add_job(_job_cart_recovery, "cron", minute=10, args=[rm], id="cart_recovery")
    scheduler.add_job(_job_backup, "cron", minute=15, args=[rm], id="backup")
    scheduler.add_job(_job_ttl_cleanup, "cron", minute=20, args=[rm], id="ttl_cleanup")
    scheduler.add_job(_job_save_config, "cron", minute=30, args=[rm], id="save_config")
    
    # 背刺泄密（每周三0点）
    scheduler.add_job(_job_leak, "cron", day_of_week="wed", hour=0, minute=0, args=[rm], id="leak")
    
    scheduler.start()
    logger.info("🚀 后台任务引擎启动（APScheduler版，各任务独立运行）")


def _start_with_legacy_loop(rm):
    """旧版 while True 循环（APScheduler 未安装时回退）"""
    t = threading.Thread(target=_legacy_task_loop, args=(rm,), daemon=True, name="AutoTasks-Legacy")
    t.start()
    logger.info("🚀 后台任务引擎启动（旧版循环，APScheduler未安装）")


def _legacy_task_loop(rm):
    """旧版 while True 循环（兼容备用）"""
    global _last_saved_model_idx
    last_backup_hour = -1
    last_cleanup_hour = -1
    
    while True:
        try:
            now = datetime.now(_CST)
            ts = int(time.time())
            
            # 叫醒服务
            _job_wakeup_check(rm)
            
            # 阅后即焚探测（每3分钟）
            if ts % 180 < 60:
                _job_burn_probe(rm)
            
            # 每小时任务
            if now.hour != last_backup_hour:
                _job_backup(rm)
                last_backup_hour = now.hour
            
            if now.hour != last_cleanup_hour:
                _job_ttl_cleanup(rm)
                last_cleanup_hour = now.hour
            
            # 醋意挽回、购物车挽回、背刺泄密（每小时随机触发）
            if now.minute == 5:
                _job_reactivate(rm)
            if now.minute == 10:
                _job_cart_recovery(rm)
            if now.minute == 30:
                _job_save_config(rm)
            
            # 背刺泄密（每周三）
            if now.weekday() == 2 and now.hour == 0 and now.minute == 0:
                _job_leak(rm)
            
            # 新闻和问候（整点附近）
            if now.hour == 9 and now.minute < 5:
                _job_news_morning(rm)
            if now.hour == 13 and now.minute < 5:
                _job_news_afternoon(rm)
            if now.hour == 20 and 28 <= now.minute < 35:
                _job_news_evening(rm)
            if now.hour == 8 and now.minute < 5:
                _job_greeting_morning(rm)
            if now.hour == 12 and 28 <= now.minute < 35:
                _job_greeting_afternoon(rm)
            if now.hour == 23 and now.minute < 5:
                _job_greeting_evening(rm)
            
        except Exception as e:
            logger.error(f"❌ 后台任务异常：{e}")
        
        time.sleep(60)
