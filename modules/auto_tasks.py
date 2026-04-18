"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/auto_tasks.py  ·  后台自动任务引擎                           ║
║                                                                        ║
║  功能：以daemon线程运行，每60秒轮询一次，执行以下任务：                 ║
║                                                                        ║
║    1. 每日9点新闻播报+早安问候 -> ai.ask(mode="news") -> 发到主群        ║
║    1b. 每日13点新闻播报+午安问候 -> ai.ask(mode="afternoon_news") -> 主群  ║
║    1c. 每日20:30新闻播报+晚安问候 -> ai.ask(mode="evening_news") -> 主群    ║
║    2. 叫醒服务 -> 每分钟检查是否有用户设定的叫醒时间                   ║
║    3. 阅后即焚-孤儿清理 -> 24h未被回复的机器人消息自动删除             ║
║    4. 阅后即焚-原消息探测 -> 每3分钟对近10分钟的追踪消息做forward探测    ║
║       原消息已被删/撤回 -> 立即删除机器人对应回复                         ║
║       注意：pyTelegramBotAPI不支持deleted_messages_handler，               ║
║             因此用forward探测代替，延迟约3-5分钟，效果一致                   ║
║    5. 醋意挽回 -> 3天未活跃的用户，25%概率发送撩拨消息                 ║
║    6. 购物车挽回 -> 24h前触发过价格关键词的用户，发送私聊撩拨           ║
║    7. 背刺泄密 -> 每周最多1次，随机时间触发，AI生成绝对不重复的爆料    ║
║    8. 每小时数据备份 -> 复制mory.db到backup/，保留7天                 ║
║    9. 保存config -> 仅模型索引变化时保存（不在每次循环保存）           ║
║                                                                        ║
║  启动方式：main.py -> start_background(bot, config, db, ai, save_config)║
║  注意：此线程为daemon，主进程退出时自动终止。                          ║
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

# 记录上次保存的模型索引，避免重复写文件
_last_saved_model_idx = None


def _send_and_track(rm, chat_id, text, user_msg_id=0):
    """发送消息（主动消息不追踪，只有回复才追踪）
    
    注意：主动消息（如早安问候、新闻播报）不需要阅后即焚追踪，
    因为它们没有对应的"原消息"需要探测是否被删除。
    追踪只用于群聊中回复用户消息的场景（由main.py的monkey-patch处理）。
    """
    try:
        with rm.locked('bot'):
            sent = rm.bot.send_message(chat_id, text)
        # 【修复v21.44】主动消息不追踪，避免reply_tracking表充满无效记录
        return sent
    except Exception as e:
        logger.error(f"发送失败：{e}")
        return None


def start_background(bot, config: Dict[str, Any], db, ai, save_config_fn):
    """启动后台守护线程（线程安全版本）"""
    # 创建资源管理器实例
    rm = ResourceManager(bot=bot, ai=ai, db=db, config=config, save_config_fn=save_config_fn)
    
    t = threading.Thread(
        target=_task_loop,
        args=(rm,),
        daemon=True,
        name="AutoTasks"
    )
    t.start()
    logger.info("🚀 后台自动任务引擎启动（线程安全版）")


def _task_loop(rm):
    global _last_saved_model_idx
    last_backup_hour = -1
    last_cleanup_hour = -1  # DB-2: TTL清理小时标记
    last_news_day = -1
    last_news_13_day = -1  # 午间新闻防重
    last_news_20_day = -1  # 晚间新闻防重
    last_morning_day = -1  # 早安防重
    last_afternoon_day = -1  # 午安防重
    last_evening_day = -1  # 晚安防重
    # 【修复v21.43】last_leak_week 已持久化到 config.json，不再使用模块级变量
    leak_history = []     # 已发送过的泄露内容哈希，防重复
    last_probe_time = 0   # 阅后即焚探测时间戳
    # 时区：VPS默认UTC，强制用北京时间(UTC+8)判断定时任务
    _CST = timezone(timedelta(hours=8))

    while True:
        try:
            now = datetime.now(_CST)
            ts = int(time.time())
            time_str = now.strftime("%H:%M")

            # ── 1. 每日新闻播报（实时获取，简短5条）───────────────
            global _news_cache
            with rm.locked('config'):
                gid = rm.config.get("GROUP_ID", 0)

            # 早间 9:00 - 实时获取新闻
            if now.hour == 9 and now.minute < 5 and now.day != last_news_day:
                if gid != 0:
                    logger.info("📰 触发早间新闻播报（实时获取）")
                    seed = random.randint(100000, 999999)
                    # 实时获取新闻，不要缓存
                    from core.ai_engine import fetch_real_news
                    raw_news = fetch_real_news() or ""
                    # 只取前5条
                    lines = [l for l in raw_news.split("\n") if l.strip()][:5]
                    news_input = "\n".join(lines) if lines else "今日热点"
                    
                    with rm.locked('ai'):
                        news = rm.ai.ask(news_input, mode="news", seed=seed)
                    if news:
                        try:
                            # 直接发送，不要前缀"总结"之类的
                            _send_and_track(rm, gid, news)
                            last_news_day = now.day
                            logger.info(f"✅ 早间新闻已发送")
                        except Exception as e:
                            logger.error(f"早间新闻播报失败：{e}")

            # ── 1b. 午间13点新闻（实时获取）─────────────────────────────
            if now.hour == 13 and now.minute < 5 and now.day != last_news_13_day:
                if gid != 0:
                    logger.info("📰 触发午间新闻播报（实时获取）")
                    seed = random.randint(100000, 999999)
                    from core.ai_engine import fetch_real_news
                    raw_news = fetch_real_news() or ""
                    lines = [l for l in raw_news.split("\n") if l.strip()][:5]
                    news_input = "\n".join(lines) if lines else "今日热门"
                    
                    with rm.locked('ai'):
                        news = rm.ai.ask(news_input, mode="afternoon_news", seed=seed)
                    if news:
                        try:
                            _send_and_track(rm, gid, news)
                            last_news_13_day = now.day
                            logger.info(f"✅ 午间新闻已发送")
                        except Exception as e:
                            logger.error(f"午间新闻播报失败：{e}")

            # ── 1c. 晚间20:30新闻（实时获取）──────────────────────────
            if now.hour == 20 and now.minute >= 28 and now.minute < 35 and now.day != last_news_20_day:
                if gid != 0:
                    logger.info("📰 触发晚间新闻播报（实时获取）")
                    seed = random.randint(100000, 999999)
                    from core.ai_engine import fetch_real_news
                    raw_news = fetch_real_news() or ""
                    lines = [l for l in raw_news.split("\n") if l.strip()][:5]
                    news_input = "\n".join(lines) if lines else "今日回顾"
                    
                    with rm.locked('ai'):
                        news = rm.ai.ask(news_input, mode="evening_news", seed=seed)
                    if news:
                        try:
                            _send_and_track(rm, gid, news)
                            last_news_20_day = now.day
                            logger.info(f"✅ 晚间新闻已发送")
                        except Exception as e:
                            logger.error(f"晚间新闻播报失败：{e}")

            # ── 1d. 早安问候(8:00) 含绿茶风隐晦引导 ────────────────────
            if now.hour == 8 and now.minute < 5 and now.day != last_morning_day:
                if gid != 0:
                    seed = random.randint(100000, 999999)
                    with rm.locked('ai'):
                        msg = rm.ai.ask("早安", mode="morning", seed=seed)
                    if msg:
                        msg = msg.replace("\n", " ").strip()[:100]  # 强制单行+截断
                        try:
                            _send_and_track(rm, gid, f"☀️ {msg}")
                            logger.info(f"☀️ 早安已发送：{msg}")
                            last_morning_day = now.day
                        except Exception as e:
                            logger.error(f"早安问候失败：{e}")

            # ── 1e. 午安问候(12:30) 含绿茶风隐晦引导 ───────────────────
            if now.hour == 12 and now.minute >= 28 and now.minute < 35 and now.day != last_afternoon_day:
                if gid != 0:
                    seed = random.randint(100000, 999999)
                    with rm.locked('ai'):
                        msg = rm.ai.ask("午安", mode="afternoon", seed=seed)
                    if msg:
                        msg = msg.replace("\n", " ").strip()[:100]  # 强制单行+截断
                        try:
                            _send_and_track(rm, gid, f"🍃 {msg}")
                            logger.info(f"🍃 午安已发送：{msg}")
                            last_afternoon_day = now.day
                        except Exception as e:
                            logger.error(f"午安问候失败：{e}")

            # ── 1f. 晚安问候(23:00) 含绿茶风隐晦引导 ───────────────────
            if now.hour == 23 and now.minute < 5 and now.day != last_evening_day:
                if gid != 0:
                    seed = random.randint(100000, 999999)
                    with rm.locked('ai'):
                        msg = rm.ai.ask("晚安", mode="evening", seed=seed)
                    if msg:
                        msg = msg.replace("\n", " ").strip()[:100]  # 强制单行+截断
                        try:
                            _send_and_track(rm, gid, f"🌙 {msg}")
                            logger.info(f"🌙 晚安已发送：{msg}")
                            last_evening_day = now.day
                        except Exception as e:
                            logger.error(f"晚安问候失败：{e}")

            # ── 2. 叫醒服务 ─────────────────────────────────────────────
            with rm.locked_multi(['db', 'bot', 'config']):
                for uid, wake_time in rm.db.get_all_wake_ups():
                    if wake_time == time_str:
                        try:
                            rm.bot.send_message(uid,
                                "起床啦哥哥～ 太阳晒屁股了，"
                                f"新的一天也要像爱{rm.config['BOT_NAME']}老板一样充满活力哦！☀️")
                        except Exception as e:
                            logger.warning(f"叫醒服务发送失败 uid={uid}：{e}")

            # ── 3. 阅后即焚：24h孤儿清理 ────────────────────────────────
            # 【修复v21.42】只清理数据库记录，不再删除bot消息
            # 超过24小时的消息，原消息可能还在群里作为上下文，删除bot消息可能影响阅读
            with rm.locked('db'):
                orphans = rm.db.get_orphan_messages(86400)
                if orphans:
                    logger.info(f"🗑️ 阅后即焚孤儿清理：{len(orphans)}条记录从DB清除（bot消息保留）")
                    for bot_mid, cid, user_mid in orphans:
                        rm.db.delete_tracked(bot_mid)

            # ── 4. 阅后即焚：原消息探测（每3分钟一次）────────────────────
            #    对近1小时未被回复的机器人消息，用 forward 探测原消息是否还在
            #    如果原消息已被删/撤回 → 立即删除机器人回复（最多重试3次）
            if ts - last_probe_time >= 180:  # 3分钟
                last_probe_time = ts
                with rm.locked('db'):
                    unconfirmed = rm.db.get_unconfirmed_messages(3600)  # 1小时窗口
                if unconfirmed:
                    logger.info(f"🔥 阅后即焚探测：{len(unconfirmed)}条消息待检查")

                flood_wait = False
                loop_start = time.time()
                MAX_PROBE_TIME = 30  # 单轮探测最多30秒
                # 【修复】限制单轮最多探测20条 + 总超时30s，防429假死
                for bot_mid, cid, user_mid in unconfirmed[:20]:
                    if time.time() - loop_start > MAX_PROBE_TIME:
                        logger.warning("⚠️ 阅后即焚探测超时(>30s)，提前退出")
                        break
                    if flood_wait:
                        break  # 触发流控，终止本轮
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
                            # 【修复v21.42】原消息还在，刷新追踪记录的时间戳
                            # 这样该消息就不会在孤儿清理窗口内被清理
                            with rm.locked('db'):
                                rm.db.refresh_tracked(bot_mid, cid)
                            delete_success = True
                            break  # 原消息还在，跳出重试
                        except Exception as e:
                            err = str(e).lower()

                            # 【修复】拦截429熔断，保护机器人不被Telegram封禁
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

                                # 【修复】删除成功后break外层retry，防止重复探测
                                if delete_success:
                                    break
                            else:
                                logger.warning(f"🔥 阅后即焚探测异常 bot={bot_mid}: {err[:200]}")
                                break

                    time.sleep(0.5)  # 【修复】探测间隙0.5s，防429

            # ── 5. 醋意挽回（3天未活跃）─────────────────────────────────
            three_days_ago = ts - 259200
            with rm.locked_multi(['db', 'bot', 'config']):
                inactive = rm.db.get_inactive_users(three_days_ago, rm.config.get("ADMIN_ID", 0))
                for uid, _name in inactive[:3]:  # 每轮最多3个，避免刷屏
                    if random.random() < 0.25:  # 25%概率
                        try:
                            rm.bot.send_message(uid,
                                f"哥哥，这几天去哪了？是不是去看别的妹妹了？"
                                f"{rm.config['BOT_NAME']}老板都问起你了哼！")
                            rm.db.reset_last_active(uid)
                            logger.info(f"💌 醋意挽回：{uid}")
                        except Exception as e:
                            logger.warning(f"醋意挽回发送失败 uid={uid}：{e}")

            # ── 6. 购物车挽回（24h后私信撩拨）───────────────────────────
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

            # ── 7. 背刺泄密（每周最多1次，随机时间，AI绝对不重复）────────
            # 【修复v21.43】持久化周号到config.json，避免代码热更新导致重置
            current_week = now.isocalendar()[1]  # ISO周号
            with rm.locked_multi(['config']):
                gid = rm.config.get("GROUP_ID", 0)
                # 从config.json读取上次触发周号，避免代码热更新导致重置
                last_leak_week = rm.config.get("_LAST_LEAK_WEEK", -1)
            
            # 【修复v21.43】真正的每周1次：本周未触发 + 周三~周日之间才触发
            if gid != 0 and current_week != last_leak_week and now.weekday() >= 2:
                # 构造独特的prompt，确保AI每次生成完全不同的内容
                seed = random.randint(100000, 999999)
                # hour_hint = random.choice(["早上", "中午", "下午", "傍晚", "深夜", "凌晨", "半夜"])  # 预留用于增强随机性
                scene_hint = random.choice([
                    "在便利店买东西", "一个人看电视剧", "刷手机的时候",
                    "发呆的时候", "跟闺蜜聊天", "自拍的时候", "做饭的时候",
                    "洗澡前", "刚睡醒", "走路的时候", "吃零食的时候",
                    "整理房间", "加班的时候", "逛街的时候", "坐地铁的时候",
                    "打视频电话", "化妆的时候", "喝奶茶的时候", "拍照片",
                    "换衣服的时候", "听歌的时候", "写日记", "敷面膜的时候",
                    "逛超市", "下雨天在家", "喝咖啡的时候", "吃火锅的时候",
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
                    # 哈希去重
                    content_hash = hashlib.md5(leak.encode()).hexdigest()[:8]
                    if content_hash not in leak_history:
                        leak_history.append(content_hash)
                        # 只保留最近20条哈希
                        if len(leak_history) > 20:
                            leak_history = leak_history[-20:]
                        try:
                            _send_and_track(rm, gid,
                                f"🤫 老板不在... 偷偷跟你们说：\n\n{leak}")
                            # 【修复v21.43】将周号持久化到config.json
                            rm.config["_LAST_LEAK_WEEK"] = current_week
                            rm.save_config_fn()
                            logger.info(f"🤫 背刺泄密触发(周{current_week})：{leak[:30]}")
                        except Exception as e:
                            logger.warning(f"背刺泄密发送失败：{e}")

            # ── 8. 每小时数据备份 ────────────────────────────────────────
            if now.hour != last_backup_hour:
                with rm.locked('db'):
                    _do_backup(rm.db.db_file)
                last_backup_hour = now.hour

            # ── 8b. 历史数据TTL清理（每小时一次，保留7天）──────────────────
            if now.hour != last_cleanup_hour:
                last_cleanup_hour = now.hour
                cutoff = ts - 7 * 86400  # 7天前
                try:
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
                    logger.warning(f"TTL清理失败：{e}")

            # ── 9. 保存config（仅模型索引变化时）────────────────────────
            with rm.locked('config'):
                current_idx = rm.config.get("CURRENT_MODEL_INDEX", 0)
            if _last_saved_model_idx is None or _last_saved_model_idx != current_idx:
                with rm.locked('config'):
                    rm.save_config_fn()
                _last_saved_model_idx = current_idx

        except Exception as e:
            logger.error(f"❌ 后台任务异常：{e}", exc_info=True)

        time.sleep(60)  # 每分钟一个循环


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
        # 只保留最近168份
        backups = sorted(glob.glob("backup/mory_backup_*.db"))
        for old in backups[:-168]:
            os.remove(old)
        logger.info(f"💾 备份完成：{dest}")
    except Exception as e:
        logger.error(f"备份失败：{e}")
