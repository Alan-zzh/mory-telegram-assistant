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
║    12. 频道浏览量更新（每小时）                                        ║
║    13. 每日数据报告（9:10 私聊HTML）  ← v4.2.4                       ║
║    14. 每日塔罗搭讪（15:00 30%概率）← v4.2.5新增                    ║
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


def _generate_wakeup_message(uid: int, now: datetime, rm) -> str:
    """AI生成个性化叫醒语"""
    seed = uid + int(now.timestamp())
    hour = now.hour
    
    prompt = f"""你是Mory老板，一个贴心的小姐姐。现在是北京时间{hour}点。

给用户生成一条叫醒消息，要求：
1. 30-50字，撒娇撩人风格
2. 像闺蜜私聊一样自然
3. 随机选择一个场景/理由叫醒他
4. 结尾要有emoji
5. seed={seed}，每次必须不同

禁止：
- 不要太长，控制在50字以内
- 不要重复相同的开头"""

    try:
        with rm.locked('ai'):
            msg = rm.ai.ask(prompt, mode="wakeup", seed=seed)
        if msg and len(msg) > 10:
            return msg.strip()
    except:
        pass
    
    # 备用文案
    fallbacks = [
        "起床啦哥哥～ 太阳晒屁股了，新的一天也要充满活力哦！☀️",
        "嘿～该起来啦！再睡就要错过好运了哦～🌞",
        "哥哥醒醒～小Mory都醒了，你还在赖床吗？快起来嘛～💪",
        "早安呀哥哥！新的一天，新的运气，快起来迎接美好吧～✨",
    ]
    return random.choice(fallbacks)


def _job_wakeup_check(rm):
    """叫醒服务检查（每分钟）- AI生成个性化叫醒语"""
    try:
        now = datetime.now(_CST)
        time_str = now.strftime("%H:%M")
        
        with rm.locked_multi(['db', 'bot', 'config']):
            for uid, wake_time in rm.db.get_all_wake_ups():
                if wake_time == time_str:
                    try:
                        wake_msg = _generate_wakeup_message(uid, now, rm)
                        rm.bot.send_message(uid, wake_msg)
                        logger.info(f"⏰ 叫醒服务：uid={uid}")
                    except Exception as e:
                        logger.warning(f"叫醒服务发送失败 uid={uid}：{e}")
    except Exception as e:
        logger.error(f"叫醒服务检查失败：{e}")


def _job_burn_probe(rm):
    """
    阅后即焚探测（降级为被动清理版 - 彻底避免 API 封禁）
    
    【v4.0 架构师强制修复】
    废弃疯狂转发的竞态探测，直接依赖 main.py 的 global_reply_sniffer 实时标记。
    孤儿清理完全由 _job_burn_orphan 的 TTL 机制接管。
    """
    try:
        # 【降级策略】：不再用 forward_message 探测
        # 原因：每3分钟对20条消息做forward探测 = 每小时400次API调用
        #       → 必然触发 Telegram 429 Rate Limit → 整队卡死
        
        # 方案：直接跳过探测，依赖以下两个机制：
        # 1. main.py 的 global_reply_sniffer 实时标记 replied=1
        # 2. _job_burn_orphan 每小时清理 24小时未回复的孤儿
        
        logger.debug("🔄 _job_burn_probe 探测逻辑已由 v4.0 静默，将由 TTL 孤儿清理接管")
        return
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


def _generate_reactivate_message(uid: int, rm) -> str:
    """AI生成醋意挽回消息"""
    seed = uid + int(time.time()) // 86400  # 每天固定
    
    prompt = f"""你是Mory老板，一个有点小醋意的小姐姐。

一个用户已经3天没来聊天了，你要写一条消息把他叫回来。

要求：
1. 40-60字，撒娇吃醋风格
2. 像闺蜜私聊一样，带点小委屈小醋意
3. 不要太直白，要撩人要心痒痒
4. 可以暗示：你是不是有别人了/你是不是把我忘了/是不是我哪里不够好
5. 结尾要有emoji
6. seed={seed}，每次必须不同

禁止：
- 不要出现"3天"这个具体数字
- 不要太长，控制在60字以内"""

    try:
        with rm.locked('ai'):
            msg = rm.ai.ask(prompt, mode="reactivate", seed=seed)
        if msg and len(msg) > 10:
            return msg.strip()
    except:
        pass
    
    # 备用文案
    fallbacks = [
        "哥哥这几天去哪了呀？是不是有新欢了？Mory都想你了呢...快回来嘛～💕",
        "你是不是把人家忘了呀...好几天都不来找我，是不是外面有别的猫猫了？😢",
        "诶？哥哥是不是把我忘了...好伤心哦，有空回来陪Mory聊聊天嘛～🥺",
        "哼！都不来找我，是不是觉得我不可爱了？快回来让我看看你！👀",
    ]
    return random.choice(fallbacks)


def _job_reactivate(rm):
    """醋意挽回（每小时）- AI生成个性化消息"""
    try:
        ts = int(time.time())
        three_days_ago = ts - 259200
        
        with rm.locked_multi(['db', 'bot', 'config']):
            inactive = rm.db.get_inactive_users(three_days_ago, rm.config.get("ADMIN_ID", 0))
            for uid, _name in inactive[:3]:
                if random.random() < 0.25:
                    try:
                        reactivate_msg = _generate_reactivate_message(uid, rm)
                        rm.bot.send_message(uid, reactivate_msg)
                        rm.db.reset_last_active(uid)
                        logger.info(f"💌 醋意挽回：{uid}")
                    except Exception as e:
                        logger.warning(f"醋意挽回发送失败 uid={uid}：{e}")
    except Exception as e:
        logger.error(f"醋意挽回失败：{e}")


def _generate_cart_recovery_message(uid: int, rm) -> str:
    """AI生成购物车挽回消息"""
    seed = uid + int(time.time()) // 43200  # 每半天固定
    
    prompt = f"""你是Mory老板，一个贴心的小姐姐。

一个用户昨天问了门槛/价格但没付费就走了，你要写一条消息把他叫回来。

要求：
1. 40-60字，撒娇但不卑微
2. 像闺蜜私聊一样自然撩人
3. 不要直接提"门槛"或"价格"，要隐晦表达
4. 可以暗示：是不是有什么顾虑/是不是钱不够/是不是不好意思
5. 要让人感觉来了会有好事发生
6. 结尾要有emoji
7. seed={seed}，每次必须不同

禁止：
- 不要出现"门槛"、"价格"、"付费"、"钱"这些词
- 不要太长，控制在60字以内"""

    try:
        with rm.locked('ai'):
            msg = rm.ai.ask(prompt, mode="cart_recovery", seed=seed)
        if msg and len(msg) > 10:
            return msg.strip()
    except:
        pass
    
    # 备用文案
    fallbacks = [
        "哥哥昨天问完就跑了...是不是有什么顾虑呀？有什么想问的尽管问嘛，Mory帮你解答～😊",
        "是不是钱不够呀？没关系呀，先来聊聊天嘛～说不定有惊喜哦！💕",
        "哥哥昨天是不是不好意思呀？放心，Mory很温柔的，来嘛来嘛～🌸",
        "昨天问了就不理人家了...Mory可是专门在想哥哥呢，快回来嘛～✨",
    ]
    return random.choice(fallbacks)


def _job_cart_recovery(rm):
    """购物车挽回（每小时）- AI生成个性化消息"""
    try:
        with rm.locked_multi(['db', 'bot', 'config']):
            for uid in rm.db.get_expired_carts(86400):
                try:
                    cart_msg = _generate_cart_recovery_message(uid, rm)
                    rm.bot.send_message(uid, cart_msg)
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


def _job_channel_views(rm):
    """【v4.2.3→v4.3.2】更新群消息浏览量（每天1次，避免429限流）"""
    try:
        from core.logging_util import get_logger
        logger = get_logger("auto_tasks")
        
        # 【v4.3.2修复S-01】降低频率：每小时只查5条最新消息（原50条），避免429
        tracked = rm.db.get_channel_tracking(limit=5)
        
        for chat_id, msg_id, content_type, posted_at, current_views in tracked:
            try:
                # 尝试通过forward_message获取浏览量（频道消息才有浏览量）
                msg_info = rm.bot.forward_message(
                    rm.config.get("ADMIN_ID", 0), 
                    chat_id, 
                    msg_id,
                    disable_notification=True
                )
                if msg_info and hasattr(msg_info, 'views'):
                    new_views = msg_info.views
                    if new_views > current_views:
                        rm.db.update_channel_views(chat_id, msg_id, new_views)
                        logger.info(f"📊 频道浏览量更新: chat={chat_id} msg={msg_id} views={new_views}")
                # 删除转发消息，避免管理员聊天堆积
                try:
                    rm.bot.delete_message(rm.config.get("ADMIN_ID", 0), msg_info.message_id)
                except:
                    pass
            except Exception as e:
                logger.debug(f"获取浏览量失败: chat={chat_id} msg={msg_id} err={e}")
        
        logger.info("✅ 频道浏览量更新任务完成")
    except Exception as e:
        logger.error(f"频道浏览量更新失败：{e}")


def _job_daily_report(rm):
    """【v4.2.4】每日数据报告（私聊发送HTML格式）"""
    try:
        admin_id = rm.config.get("ADMIN_ID", 0)
        if not admin_id:
            return
        
        now = datetime.now(_CST)
        today = now.strftime("%Y-%m-%d")
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        
        # 获取群动态数据
        group_stats_today = rm.db.get_group_stats_by_date(today)
        group_stats_yesterday = rm.db.get_group_stats_by_date(yesterday)
        
        # 解析今日群数据
        joined_today = left_today = net_today = 0
        for row in group_stats_today:
            if len(row) >= 6:
                joined_today += row[2] or 0
                left_today += row[3] or 0
                net_today += row[4] or 0
        
        # 解析昨日群数据
        joined_yest = left_yest = net_yest = 0
        for row in group_stats_yesterday:
            if len(row) >= 6:
                joined_yest += row[2] or 0
                left_yest += row[3] or 0
                net_yest += row[4] or 0
        
        # 获取频道内容数据
        channel_stats = rm.db.get_channel_stats_summary()
        total_views = 0
        tracked_count = 0
        avg_views = 0
        if channel_stats:
            total_views = channel_stats.get("total_views", 0)
            tracked_count = channel_stats.get("tracked_count", 0)
            avg_views = channel_stats.get("avg_views", 0)
        
        # 构建HTML报告
        emoji_up = "🔼"
        emoji_down = "🔽"
        emoji_neutral = "➖"
        
        # 计算趋势
        join_trend = "📈" if joined_today > joined_yest else ("📉" if joined_today < joined_yest else "➖")
        left_trend = "📈" if left_today > left_yest else ("📉" if left_today < left_yest else "➖")
        net_trend = "📈" if net_today > net_yest else ("📉" if net_today < net_yest else "➖")
        
        html_report = f"""📊 <b>Mory数据日报</b> · {today}

━━━━━━━━━━━━━━━━━━

🏠 <b>群动态</b>
├ 今日入群：{joined_today} {join_trend}
├ 今日离群：{left_today} {left_trend}
└ 净增人数：{net_today:+d} {net_trend}

━━━━━━━━━━━━━━━━━━

📈 <b>内容表现</b>
├ 追踪消息：{tracked_count} 条
├ 总浏览量：{total_views:,}
└ 平均浏览：{avg_views:.0f}

━━━━━━━━━━━━━━━━━━

🌙 昨日同期参考
├ 入群 {joined_yest} / 离群 {left_yest}
└ 净增 {net_yest:+d}

━━━━━━━━━━━━━━━━━━
<i>系统自动生成 · Mory小助理 v4.2.4</i>"""
        
        # 发送私聊报告
        with rm.locked('bot'):
            rm.bot.send_message(admin_id, html_report, parse_mode="HTML")
        
        logger.info(f"✅ 每日数据报告已发送: 入群{joined_today} 离群{left_today} 净增{net_today} 浏览{total_views}")
    except Exception as e:
        logger.error(f"每日数据报告失败：{e}")


# ═══════════════════════════════════════════════════════════════════════════
# 塔罗缓存：同一人同一天结果固定（北京时间为准）
# ═══════════════════════════════════════════════════════════════════════════
_tarot_daily_cache: Dict[str, Dict] = {}  # {user_id_date: {...}}
_tarot_cache_last_date: str = ""  # 【v4.3.2修复M-03】上次缓存日期，用于清理


def _get_tarot_cache(uid: int, dt: datetime) -> Dict:
    """获取/生成某用户当日的塔罗运势（北京时间）"""
    global _tarot_daily_cache, _tarot_cache_last_date
    cst_now = dt.astimezone(_CST)
    date_key = cst_now.strftime("%Y-%m-%d")
    
    # 【v4.3.2修复M-03】每天凌晨清理前一天的缓存
    if date_key != _tarot_cache_last_date:
        _tarot_daily_cache = {k: v for k, v in _tarot_daily_cache.items() if date_key in k}
        _tarot_cache_last_date = date_key
    
    cache_key = f"{uid}_{date_key}"
    
    if cache_key not in _tarot_daily_cache:
        # 生成新数据并缓存
        _tarot_daily_cache[cache_key] = _generate_tarot_data(uid)
    
    return _tarot_daily_cache[cache_key]


def _get_fallback_hook(theme: str, uname: str) -> str:
    """撩人转化文案 - 绿茶口吻，引导VIP/赞助大哥"""
    # 绿茶风格变体库（高度随机组合）
    starters = [
        "哎呀哥哥~",
        "嘿嘿哥哥~",
        "诶嘿哥哥~",
        "呜呼哥哥~",
        "哈喽哥哥~",
        "悄悄说哥哥~",
    ]
    
    bodies = [
        "这运势还有后半段呢~",
        "说实话完整版比这准多了~",
        "你这牌其实还有隐藏信息~",
        "VIP版本待遇完全不一样哦~",
        "普通版只是开胃菜~",
        "赞助大哥说完整版才叫准~",
        "小Mory手里还有更准的版本呢~",
        "完整版只有赞助大哥才看得到~",
    ]
    
    endings = [
        "你懂我意思吧~",
        "你懂的~",
        "悄悄告诉你哦~",
        "别告诉别人嘿嘿~",
        "来嘛来嘛~",
        "害羞捂脸~",
        "等你哦~",
        "支持一下嘛~",
        "嘿嘿~",
        "好不好嘛~",
        "好不啦~",
        "帮帮忙嘛~",
    ]
    
    # 随机组合，高度个性化
    starter = random.choice(starters)
    body = random.choice(bodies)
    ending = random.choice(endings)
    
    # 30%概率只说两句，更简短随机
    if random.random() < 0.3:
        return f"{starter} {body} {ending}"
    else:
        # 三段式，但随机决定是否加"所以"
        connector = random.choice(["所以呀~", "所以嘛~", "所以呢~", "那你要不要~", ""])
        return f"{starter} {body} {connector}{ending}"


def _generate_tarot_data(seed_uid: int) -> Dict:
    """根据用户ID生成稳定的塔罗数据（牌名预设，其余由AI生成）"""
    rng = random.Random(seed_uid)  # 用用户ID做种子，同一人永远同结果
    
    # 牌名和主题预设（保持神秘感和随机性）
    themes = ["整体运势", "爱情运势", "财运", "工作运", "健康运", "桃花运"]
    fortune_theme = rng.choice(themes)
    
    major = ["愚者", "魔术师", "女祭司", "女皇", "皇帝", "教皇", "恋人", "战车",
             "力量", "隐士", "命运之轮", "正义", "吊人", "死神", "节制", "恶魔",
             "塔", "星星", "月亮", "太阳", "审判", "世界"]
    suits = ["权杖", "圣杯", "宝剑", "金币"]
    card_name = rng.choice(major + [f"{s}{rng.randint(1,10)}" for s in suits])
    card_position = rng.choice(["正位", "逆位"])
    
    # 基础数据（供AI prompt使用）
    return {
        "theme": fortune_theme,
        "card": card_name,
        "position": card_position,
        "seed": seed_uid,  # 传给AI用
    }


def _generate_tarot_ai_content(tarot: Dict, seed: int, rm) -> Dict:
    """调用AI生成完整的塔罗运势内容"""
    seed_for_ai = seed or random.randint(100000, 999999)
    
    prompt = f"""你是Mory老板，一个神秘又懂人心的塔罗师。

根据以下信息，为用户生成一段塔罗运势：

【运势类型】：{tarot['theme']}
【塔罗牌】：{tarot['card']} {tarot['position']}

请生成以下内容（严格按格式，emoji和内容都不能为空）：

1. 牌面描述（一句话，15-25字，带emoji）
2. 今日解读（2-3句话，50-80字，有画面感，带emoji）
3. 今日建议（一句话行动指引，20字以内，带emoji）
4. 幸运色（只写颜色，2-4字）
5. 幸运方位（只写方位，2-4字）
6. 幸运数字（3个数字，用逗号隔开，如：7, 23, 45）
7. 贵人星座（只写星座名，2-4字）
8. 幸运时段（只写时间段，5-8字，如：上午9-11点）

seed={seed_for_ai}
要求：每次seed不同，生成内容必须完全不同。"""

    try:
        with rm.locked('ai'):
            ai_response = rm.ai.ask(prompt, mode="tarot_interpret", seed=seed_for_ai)
        
        if not ai_response or len(ai_response) < 50:
            raise ValueError("AI返回内容太短")
        
        # 解析AI返回的内容
        content = _parse_tarot_ai_response(ai_response, tarot)
        return content
    except Exception as e:
        logger.warning(f"AI生成塔罗内容失败，使用备用方案: {e}")
        return _get_fallback_tarot_content(tarot)


def _parse_tarot_ai_response(ai_response: str, tarot: Dict) -> Dict:
    """
    解析AI返回的塔罗内容（正则增强版）
    
    【v4.2.8修复】采用正则表达式精准捕获，防止AI输出格式不标准导致的解析失败
    """
    import re
    
    lines = ai_response.strip().split('\n')
    full_text = ai_response.strip()
    
    result = {
        "theme": tarot['theme'],
        "card": tarot['card'],
        "position": tarot['position'],
        "mood": "✨ 今日牌面呈现吉祥之象",  # 默认
        "meaning": "今日运势平稳，保持积极心态...",  # 默认
        "advice": "保持好心情，顺势而为",  # 默认
        "result": "会有好事发生",  # 默认
        "color": None,  # 待解析
        "dir": None,   # 待解析
        "nums": None,  # 待解析
        "star": None,  # 待解析
        "time": None,  # 待解析
    }
    
    # ─── 正则表达式精准匹配 ─────────────────────────────────────────────
    
    # 1. 牌面描述：匹配 "牌面：" 或 "描述：" 后面的内容
    mood_match = re.search(r'(?:牌面描述?|[:：].*?)[:：]\s*(.+?)(?:\n|$)', full_text)
    if mood_match:
        result["mood"] = mood_match.group(1).strip()
    else:
        # 容错：找包含🌟或✨的长句
        for line in lines:
            if ('🌟' in line or '✨' in line) and len(line) > 15:
                result["mood"] = line.strip()
                break
    
    # 2. 今日解读：匹配 "解读：" 或 "今日解读：" 后面的内容
    meaning_match = re.search(r'(?:今日)?(?:解读?|💫|📖)[:：]\s*(.+?)(?:\n|$)', full_text)
    if meaning_match:
        result["meaning"] = meaning_match.group(1).strip()
    else:
        # 容错：找最长的句子作为解读
        candidates = [l.strip() for l in lines if 30 < len(l.strip()) < 100]
        if candidates:
            result["meaning"] = candidates[0]
    
    # 3. 建议：匹配 "建议：" 后面的内容
    advice_match = re.search(r'(?:今日)?(?:建议?|💡|🌱)[:：]\s*(.+?)(?:\n|$)', full_text)
    if advice_match:
        result["advice"] = advice_match.group(1).strip()
    else:
        # 容错：找短句
        for line in lines:
            if len(line.strip()) < 30 and ('💡' in line or '🌱' in line):
                result["advice"] = line.strip()
                break
    
    # 4. 幸运色：匹配 "色：" 后面的颜色词
    color_match = re.search(r'(?:幸运)?(?:色|🌈|🎨)[:：]\s*(\S{1,4})', full_text)
    if not color_match:
        # 直接在全文中找颜色词
        colors = ["白色", "黑色", "红色", "蓝色", "绿色", "紫色", "粉色", "金色", "橙色", "黄色", "青色", "棕色"]
        for c in colors:
            if c in full_text:
                result["color"] = c
                break
    if color_match:
        result["color"] = color_match.group(1).strip()
    if not result["color"]:
        result["color"] = "蓝色"  # 最终兜底
    
    # 5. 幸运方位
    dir_match = re.search(r'(?:幸运)?(?:方位?|方向?|📍|🧭)[:：]\s*(\S{1,4})', full_text)
    if not dir_match:
        dirs = ["东方", "西方", "南方", "北方", "东南", "东北", "西南", "西北", "东", "南", "西", "北"]
        for d in dirs:
            if d in full_text:
                result["dir"] = d
                break
    if dir_match:
        result["dir"] = dir_match.group(1).strip()
    if not result["dir"]:
        result["dir"] = "东方"  # 最终兜底
    
    # 6. 幸运数字：提取3个数字
    nums = re.findall(r'\b(\d{1,3})\b', full_text)
    nums = [n for n in nums if 1 <= int(n) <= 99][:3]  # 只取1-99范围内的数字，最多3个
    if len(nums) >= 3:
        result["nums"] = f"{nums[0]}, {nums[1]}, {nums[2]}"
    else:
        result["nums"] = "7, 23, 45"  # 兜底
    
    # 7. 贵人星座
    star_match = re.search(r'(?:贵人)?(?:星座?|⭐|🌟)[:：]\s*(\S{2,4}座?)', full_text)
    if not star_match:
        stars = ["白羊座", "金牛座", "双子座", "巨蟹座", "狮子座", "处女座", 
                 "天秤座", "天蝎座", "射手座", "摩羯座", "水瓶座", "双鱼座",
                 "白羊", "金牛", "双子", "巨蟹", "狮子", "处女", 
                 "天秤", "天蝎", "射手", "摩羯", "水瓶", "双鱼"]
        for s in stars:
            if s in full_text:
                result["star"] = s if "座" in s else s + "座"
                break
    if star_match:
        result["star"] = star_match.group(1).strip()
    if not result["star"]:
        result["star"] = "天秤座"  # 兜底
    
    # 8. 幸运时段
    time_match = re.search(r'(?:幸运)?(?:时段?|时间?|⏰|🕐)[:：]\s*(.+?)(?:\n|$)', full_text)
    if time_match:
        result["time"] = time_match.group(1).strip()
    else:
        # 容错：找包含时间关键词的行
        for line in lines:
            if any(x in line for x in ['点', '时', '早', '午', '晚', '上', '下']):
                if len(line.strip()) < 15:
                    result["time"] = line.strip()
                    break
    if not result["time"]:
        result["time"] = "上午9-11点"  # 兜底
    
    return result


def _get_fallback_tarot_content(tarot: Dict) -> Dict:
    """备用塔罗内容（AI失败时使用）"""
    rng = random.Random(tarot.get('seed', 42))
    
    meanings = {
        "正位": ["内心充满希望，适合开展新计划", "感情上可能有惊喜", 
                "财运上升，适合投资", "人际关系和谐"],
        "逆位": ["有些迷茫，需要冷静思考", "感情上可能有误会",
                "财务上要谨慎", "工作上可能遇小阻碍"]
    }
    
    colors = ["白色", "黑色", "红色", "蓝色", "绿色", "紫色", "粉色", "金色"]
    dirs = ["东方", "西方", "南方", "北方", "东南", "东北"]
    stars = ["白羊座", "金牛座", "双子座", "巨蟹座", "狮子座", "处女座", "天秤座", "天蝎座"]
    
    return {
        "theme": tarot['theme'],
        "card": tarot['card'],
        "position": tarot['position'],
        "mood": "✨ 牌面呈现吉祥之象",
        "meaning": rng.choice(meanings[tarot['position']]),
        "advice": rng.choice(["大胆尝试新事物", "多倾听少说话", "主动出击别犹豫"]),
        "result": rng.choice(["会有意外收获", "会有贵人相助", "会有好运降临"]),
        "color": rng.choice(colors),
        "dir": rng.choice(dirs),
        "nums": f"{rng.randint(1,99)}, {rng.randint(1,99)}, {rng.randint(1,99)}",
        "star": rng.choice(stars),
        "time": rng.choice(["早上9-11点", "下午15-17点", "晚上19-21点"]),
    }


def _job_tarot_flirt(rm):
    """【v4.2.5】每日塔罗搭讪（30%概率，针对群里活跃用户）
    
    【特性】
    - 同一人同一天结果固定（北京时间为准）
    - 高度随机：40%短版 / 60%长版
    - 卡片式排版，手机一屏可看完
    """
    try:
        # 30%概率触发
        if random.random() > 0.30:
            return
        
        gid = rm.config.get("GROUP_ID", 0)
        admin_id = rm.config.get("ADMIN_ID", 0)
        if not gid or not admin_id:
            return
        
        logger.info("🎴 触发每日塔罗搭讪任务")
        
        # 获取群成员
        try:
            members = rm.bot.get_chat_member_count(gid)
            if members < 5:
                return
        except:
            pass
        
        # 获取最近活跃用户（替代不存在的get_chat_history）
        recent_users = {}
        try:
            ts_1h_ago = int(time.time()) - 3600
            active_users = rm.db.get_active_users(ts_1h_ago)
            for uid, uname, keywords in active_users[:20]:
                if uid != admin_id:
                    recent_users[uid] = (uname or "哥哥", keywords or "")
        except Exception as e:
            logger.debug(f"获取活跃用户失败：{e}")
            return
        
        if not recent_users:
            return
        
        # 随机选一个用户和消息
        uid, (uname, user_msg) = random.choice(list(recent_users.items()))
        
        logger.info(f"🎴 塔罗搭讪目标: {uname} 说: {user_msg[:30]}")
        
        # 获取该用户今日运势（北京时间缓存）
        tarot_base = _get_tarot_cache(uid, datetime.now())
        
        # 调用AI生成完整运势内容
        tarot = _generate_tarot_ai_content(tarot_base, uid, rm)
        
        # 开场白
        opener_text = random.choice(['哥哥～', '嘿～', '在吗～', '哎～', '诶～'])
        opener_action = random.choice(['看到你说的', '刷到你这句', '你刚才说'])
        
        # AI生成隐晦撩人转化结尾（绝不能提会员/付费/订阅）
        convert_seed = random.randint(10000, 99999)
        convert_prompt = f"""你是Mory老板，一个神秘又懂人心的塔罗师。

给刚测完「{tarot['theme']}」的「{uname}」写一句撩人私信引导语。

要求（必须全部满足）：
1. 30-45字，像闺蜜私聊一样自然暧昧
2. 暗示有专属的、更准的、只有老粉才知道的东西
3. 绝对不能出现：会员、付费、订阅、解锁、钱、开通、VIP、专属版 这些词
4. 要撩人，让人心痒痒的想追问
5. 每次seed不同，生成内容必须不重复
6. 不要emoji结尾

seed={convert_seed}"""
        
        try:
            with rm.locked('ai'):
                convert_hint = rm.ai.ask(convert_prompt, mode="convert_hook", seed=convert_seed)
            if not convert_hint or len(convert_hint) < 10:
                convert_hint = _get_fallback_hook(tarot['theme'], uname)
        except:
            convert_hint = _get_fallback_hook(tarot['theme'], uname)
        
        # 构建HTML卡片消息（高度随机：40%短版 / 60%长版）
        short_mode = random.random() < 0.4
        
        if short_mode:
            # ══ 短版：极简卡片，约100字
            html_reply = f"""🎴 <b>{tarot['card']} {tarot['position']}</b>

@{uname} {opener_text} {opener_action}「{user_msg[:10]}」~

📖 {tarot['meaning']}

🌈 {tarot['color']} · 📍 {tarot['dir']} · 🔢 {tarot['nums'].split(',')[0]}

{convert_hint}"""
        else:
            # ══ 长版：完整卡片，约150字
            html_reply = f"""🎴 <b>{tarot['theme']}</b> · {tarot['card']} {tarot['position']}

@{uname} {opener_text} {opener_action}「{user_msg[:10]}」~

📖 <b>牌面</b>：{tarot['mood']}，{tarot['meaning']}

💡 <b>今日建议</b>：{tarot['advice']}，{tarot['result']}

🌈 <b>幸运色</b>：{tarot['color']}
📍 <b>方位</b>：{tarot['dir']}
🔢 <b>数字</b>：{tarot['nums']}
⭐ <b>贵人</b>：{tarot['star']}
⏰ <b>时段</b>：{tarot['time']}

{convert_hint}"""
        
        # 发送HTML格式消息
        try:
            with rm.locked('bot'):
                rm.bot.send_message(gid, html_reply, parse_mode="HTML")
            logger.info(f"🎴 塔罗搭讪成功: @{uname}")
        except Exception as e:
            logger.error(f"塔罗搭讪发送失败：{e}")


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
    
    # 每日数据报告（v4.2.4）- 私聊发送
    scheduler.add_job(_job_daily_report, "cron", hour=9, minute=10, args=[rm], id="daily_report")
    
    # 每日塔罗搭讪（v4.2.5）- 随机30%概率
    scheduler.add_job(_job_tarot_flirt, "cron", hour=15, minute=0, args=[rm], id="tarot_flirt")
    
    # 问候
    scheduler.add_job(_job_greeting_morning, "cron", hour=8, minute=5, args=[rm], id="greeting_morning")
    scheduler.add_job(_job_greeting_afternoon, "cron", hour=12, minute=35, args=[rm], id="greeting_afternoon")
    scheduler.add_job(_job_greeting_evening, "cron", hour=23, minute=5, args=[rm], id="greeting_evening")
    
    # 叫醒服务（每分钟）
    scheduler.add_job(_job_wakeup_check, "cron", minute="*", args=[rm], id="wakeup_check")
    
    # 阅后即焚探测（每5分钟 - v4.0.3降频以节省API配额）
    # 注意：_job_burn_probe 已降级为空操作，主要依赖孤儿清理TTL机制
    scheduler.add_job(_job_burn_probe, "cron", minute="*/5", args=[rm], id="burn_probe")
    
    # 每小时任务
    scheduler.add_job(_job_burn_orphan, "cron", minute=0, args=[rm], id="burn_orphan")
    scheduler.add_job(_job_reactivate, "cron", minute=5, args=[rm], id="reactivate")
    scheduler.add_job(_job_cart_recovery, "cron", minute=10, args=[rm], id="cart_recovery")
    scheduler.add_job(_job_backup, "cron", minute=15, args=[rm], id="backup")
    scheduler.add_job(_job_ttl_cleanup, "cron", minute=20, args=[rm], id="ttl_cleanup")
    scheduler.add_job(_job_save_config, "cron", minute=30, args=[rm], id="save_config")
    scheduler.add_job(_job_channel_views, "cron", minute=25, args=[rm], id="channel_views")  # 【v4.2.3】浏览量更新
    
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
    # 【v4.3.2修复S-14】改用时间戳差判断，不再用 % 运算
    _last_backup_ts = 0
    _last_cleanup_ts = 0
    _last_reactivate_ts = 0
    _last_cart_ts = 0
    _last_config_ts = 0
    
    while True:
        try:
            now = datetime.now(_CST)
            ts = int(time.time())
            
            # 叫醒服务
            _job_wakeup_check(rm)
            
            # 阅后即焚探测（每3分钟）
            if ts - _last_cleanup_ts > 180:
                _job_burn_probe(rm)
                _last_cleanup_ts = ts
            
            # 每小时任务（用时间戳差判断）
            if ts - _last_backup_ts > 3600:
                _job_backup(rm)
                _last_backup_ts = ts
            
            if ts - _last_cleanup_ts > 3600:
                _job_ttl_cleanup(rm)
            
            if ts - _last_reactivate_ts > 3600:
                _job_reactivate(rm)
                _last_reactivate_ts = ts
            
            if ts - _last_cart_ts > 3600:
                _job_cart_recovery(rm)
                _last_cart_ts = ts
            
            if ts - _last_config_ts > 3600:
                _job_save_config(rm)
                _last_config_ts = ts
            
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
