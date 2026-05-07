"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/auto_tasks.py  ·  后台自动任务引擎（APScheduler版）        ║
║                                                                        ║
║  【架构重构 v4.5.0】                                                   ║
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

# 当日已推送的新闻标题缓存（防止早中晚重复）
_news_pushed_today = set()
_news_cache_lock = threading.Lock()

_last_task_run = {}
_task_lock = threading.Lock()

_scheduler_instance = None

# 时区：VPS默认UTC，强制用北京时间(UTC+8)
_CST = timezone(timedelta(hours=8))


def _get_scheduler():
    """获取全局APScheduler实例（供_schedule_auto_delete和_retry_task使用）"""
    return _scheduler_instance

def _try_claim_task(task_name: str, min_interval_sec: int = 7200) -> bool:
    """
    【v4.5.32】三层防重抢占（数据库→内存→APScheduler coalesce）
    
    第一层：数据库原子抢占（跨进程安全）
    第二层：内存锁（同进程安全，快速拦截）
    第三层：APScheduler max_instances=1 + coalesce=True
    
    Returns:
        True表示抢占成功可以执行，False表示已被其他实例抢占
    """
    now = int(time.time())
    with _task_lock:
        last = _last_task_run.get(task_name, 0)
        if now - last < min_interval_sec:
            logger.debug(f"⏳ 任务{task_name}跳过，距离上次运行{now-last}秒 < {min_interval_sec}秒")
            return False
        _last_task_run[task_name] = now
        return True


def _can_run(task_name: str, min_interval_sec: int = 300) -> bool:
    """
    检查任务是否可以运行（仅检查，不标记）
    注意：已被_try_claim_task替代，保留以兼容旧代码
    """
    now = int(time.time())
    with _task_lock:
        last = _last_task_run.get(task_name, 0)
        if now - last < min_interval_sec:
            logger.debug(f"⏳ 任务{task_name}跳过，距离上次运行{now-last}秒 < {min_interval_sec}秒")
            return False
        return True


def _mark_done(task_name: str):
    """标记任务为已成功完成（仅在实际成功后调用）"""
    now = int(time.time())
    with _task_lock:
        _last_task_run[task_name] = now


def _clear_news_cache_if_new_day():
    """每日凌晨自动清空新闻去重缓存（防止跨天失效），加锁防竞态"""
    today = datetime.now(_CST).strftime("%Y-%m-%d")
    with _news_cache_lock:
        if not getattr(_clear_news_cache_if_new_day, "last_day", None) == today:
            _news_pushed_today.clear()
            _clear_news_cache_if_new_day.last_day = today
            logger.info(" 新闻去重缓存已按日清空")


def _extract_news_key(line: str) -> str:
    """抽取新闻去重键，尽量忽略序号、来源和热度等包装字符"""
    text = line.strip()
    if not text:
        return ""

    if ". " in text[:4]:
        text = text.split(". ", 1)[-1].strip()

    if text.startswith("【") and "】" in text:
        text = text.split("】", 1)[-1].strip()

    if " 🔥" in text:
        text = text.split(" 🔥", 1)[0].strip()

    return text


def _prepare_news_lines(raw_news: str, source_hint: str = "", limit: int = 5) -> list[str]:
    """整理新闻标题，过滤当天已发送内容，但只在真正发送成功后再写入缓存"""
    _clear_news_cache_if_new_day()
    with _news_cache_lock:
        lines = [l.strip() for l in raw_news.split("\n") if l.strip()]
        unique_lines = []
        for line in lines:
            core = _extract_news_key(line)
            if core and core not in _news_pushed_today:
                unique_lines.append(line)
    if source_hint:
        logger.info(f"📰 {source_hint}: 过滤前{len(lines)}条 → 去重后{len(unique_lines)}条")
    return unique_lines[:limit]


def _remember_news_lines(lines: list[str]):
    """新闻真正发送成功后，再把标题写入当天去重缓存"""
    _clear_news_cache_if_new_day()
    with _news_cache_lock:
        for line in lines:
            core = _extract_news_key(line)
            if core:
                _news_pushed_today.add(core)


def _build_news_ai_mode(time_desc: str, source_name: str) -> str:
    """根据时段和新闻源选择对应的AI播报模式"""
    if source_name == "trendradar":
        mapping = {
            "早间": "trendradar_morning_news",
            "午间": "trendradar_noon_news",
            "晚间": "trendradar_evening_news",
        }
        return mapping.get(time_desc, "trendradar_morning_news")

    mapping = {
        "早间": "news",
        "午间": "afternoon_news",
        "晚间": "evening_news",
    }
    return mapping.get(time_desc, "news")


def _get_preferred_news_lines(time_desc: str) -> tuple[list[str], str]:
    """优先用 TrendRadar，失败后再降级到原多源新闻"""
    from core.trendradar_news import fetch_trendradar_news
    from core.ai_engine import fetch_real_news

    trendradar_news = fetch_trendradar_news() or ""
    lines = _prepare_news_lines(trendradar_news, f"{time_desc}新闻-TrendRadar")
    if lines:
        return lines, "trendradar"

    raw_news = fetch_real_news() or ""
    lines = _prepare_news_lines(raw_news, f"{time_desc}新闻-多源热点")
    if lines:
        return lines, "fallback"

    return [], "none"


def _retry_task(rm, task_func, task_name: str, delay_sec: int = 300):
    """5分钟后重试失败的任务，仍失败则通知管理员（使用APScheduler调度，避免线程无法取消）"""
    def _do_retry(rm_inner):
        with _task_lock:
            _last_task_run.pop(task_name, None)
        try:
            logger.info(f"🔄 重试任务: {task_name}")
            task_func(rm_inner)
        except Exception as e:
            logger.error(f"❌ 重试任务{task_name}仍失败: {e}")
            _notify_admin_failure(rm_inner, task_name, str(e))

    try:
        if HAS_APSCHEDULER and _get_scheduler():
            run_at = datetime.now(_CST) + timedelta(seconds=delay_sec)
            _get_scheduler().add_job(
                _do_retry, trigger='date', run_date=run_at,
                args=[rm], id=f"retry_{task_name}",
                max_instances=1, misfire_grace_time=300,
                replace_existing=True,
            )
        else:
            t = threading.Thread(target=_do_retry, args=(rm,), daemon=True, name=f"Retry-{task_name}")
            t.start()
    except Exception as e:
        logger.error(f"重试任务调度失败: {e}")
        t = threading.Thread(target=_do_retry, args=(rm,), daemon=True, name=f"Retry-{task_name}")
        t.start()
    logger.info(f"⏰ 已安排{task_name}在{delay_sec}秒后重试")


def _notify_admin_failure(rm, task_name: str, error_msg: str):
    """任务重试仍失败时私聊通知管理员"""
    try:
        admin_id = rm.config.get("ADMIN_ID", 0)
        if admin_id:
            with rm.locked('bot'):
                rm.bot.send_message(
                    admin_id,
                    f"️ 定时任务失败通知\n"
                    f"📋 任务：{task_name}\n"
                    f"❌ 错误：{error_msg[:200]}\n"
                    f"🕐 时间：{datetime.now(_CST).strftime('%Y-%m-%d %H:%M')}\n"
                    f"💡 请检查AI模型状态或手动触发"
                )
    except Exception as e:
        logger.error(f"管理员通知发送失败: {e}")


def _notify_admin_news_failure(rm, news_type: str, error_msg: str = ""):
    """新闻源全部失败时私聊通知管理员"""
    try:
        admin_id = rm.config.get("ADMIN_ID", 0)
        if admin_id:
            detail = f"\n❌ 错误：{error_msg[:200]}" if error_msg else ""
            with rm.locked('bot'):
                rm.bot.send_message(
                    admin_id,
                    f"📰 新闻源故障通知\n"
                    f"📋 类型：{news_type}\n"
                    f"⚠️ 所有新闻源（百度/微博/头条/知乎/抖音/36氪/澎湃）均无法获取{detail}\n"
                    f"🕐 时间：{datetime.now(_CST).strftime('%Y-%m-%d %H:%M')}\n"
                    f"💡 本次播报已跳过，请检查网络或新闻源可用性"
                )
    except Exception as e:
        logger.error(f"新闻故障通知发送失败: {e}")


def _notify_admin_system_failure(rm, failure_type: str, detail: str = "", severity: str = "⚠️"):
    """
    全局系统故障通知管理员（覆盖API/数据库/任务/Bot等所有故障）
    
    Args:
        rm: 资源管理器
        failure_type: 故障类型（如 "API全部不可用", "数据库异常", "Bot连接断开"）
        detail: 详细错误信息
        severity: 严重级别图标（⚠️/🚨/❌）
    """
    try:
        admin_id = rm.config.get("ADMIN_ID", 0)
        if not admin_id:
            return
        
        # 防重复通知：同一故障类型5分钟内只通知一次
        cache_key = f"sys_notify_{failure_type}"
        now = int(time.time())
        if not hasattr(_notify_admin_system_failure, "_cache"):
            _notify_admin_system_failure._cache = {}
        last_notify = _notify_admin_system_failure._cache
        if cache_key in last_notify and now - last_notify[cache_key] < 300:
            return
        last_notify[cache_key] = now
        expired = [k for k, v in last_notify.items() if now - v > 600]
        for k in expired:
            del last_notify[k]
        
        detail_text = f"\n🔍 详情：{detail[:300]}" if detail else ""
        msg = (
            f"{severity} 系统故障通知\n"
            f"📋 类型：{failure_type}\n"
            f"🕐 时间：{datetime.now(_CST).strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"{detail_text}\n"
            f"💡 请检查系统状态并及时处理"
        )
        with rm.locked('bot'):
            rm.bot.send_message(admin_id, msg)
        logger.info(f"📢 系统故障通知已发送: {failure_type}")
    except Exception as e:
        logger.error(f"系统故障通知发送失败: {e}")


def _send_and_track(rm, chat_id, text, user_msg_id=0):
    """发送消息并追踪浏览量（主动消息也入库channel_tracking）"""
    try:
        with rm.locked('bot'):
            sent = rm.bot.send_message(chat_id, text)
        if sent and hasattr(sent, 'message_id'):
            _schedule_auto_delete(rm, chat_id, sent.message_id, 24 * 3600)
            if chat_id < 0:
                rm.db.track_channel_message(chat_id, sent.message_id, "text")
        return sent
    except Exception as e:
        logger.error(f"发送失败：{e}")
        return None


def _schedule_auto_delete(rm, chat_id, message_id, delay_seconds):
    """定时消息24小时无人理自动删除（使用APScheduler调度，避免线程泄漏）"""
    try:
        if HAS_APSCHEDULER:
            run_at = datetime.now(_CST) + timedelta(seconds=delay_seconds)
            _get_scheduler().add_job(
                _do_delete_message, trigger='date', run_date=run_at,
                args=[rm, chat_id, message_id],
                id=f"auto_del_{chat_id}_{message_id}",
                max_instances=1, misfire_grace_time=300,
                replace_existing=False,
            )
        else:
            logger.warning("⚠️ APScheduler不可用，跳过定时删除（依赖孤儿清理机制处理）")
    except Exception as e:
        logger.error(f"定时删除调度失败: {e}")


def _do_delete_message(rm, chat_id, message_id):
    """APScheduler回调：删除指定消息"""
    try:
        with rm.locked('bot'):
            rm.bot.delete_message(chat_id, message_id)
        logger.info(f"🗑️ 定时消息已自动删除: chat={chat_id}, msg={message_id}")
    except Exception as e:
        logger.debug(f"定时消息删除失败（可能已被手动删除）: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# APScheduler 版本：独立 Job，互不干扰
# ═══════════════════════════════════════════════════════════════════════════

def _execute_news_task(rm, task_name: str, time_desc: str):
    """
    执行新闻播报任务的公共函数
    
    Args:
        rm: 资源管理器
        task_name: 任务名称（如 "news_morning"）
        time_desc: 时段描述（如 "早间"）
    """
    if not _try_claim_task(task_name, 7200):
        return
    
    if not rm.db.claim_task(task_name):
        logger.info(f"✅ {task_name} 已被抢占（数据库），跳过")
        return
    
    try:
        with rm.locked('config'):
            gid = rm.config.get("GROUP_ID", 0)
        if gid == 0:
            return
        
        logger.info(f"📰 触发{time_desc}新闻播报（统一主流程）")
        seed = random.randint(100000, 999999)

        lines, source_name = _get_preferred_news_lines(time_desc)
        if not lines:
            logger.warning(f"{time_desc}新闻：所有源均失败，跳过发送")
            _notify_admin_news_failure(rm, f"{time_desc}新闻")
            return
        news_input = "\n".join(lines)

        ai_mode = _build_news_ai_mode(time_desc, source_name)
        with rm.locked('ai'):
            news = rm.ai.ask(news_input, mode=ai_mode, seed=seed)

        if news:
            sent = _send_and_track(rm, gid, news)
            if sent:
                _remember_news_lines(lines)
                logger.info(f"✅ {time_desc}新闻已发送（来源: {source_name}）")
    except Exception as e:
        logger.error(f"{time_desc}新闻播报失败：{e}")
        _retry_task(rm, lambda rm: _execute_news_task(rm, task_name, time_desc), task_name)


# ═══════════════════════════════════════════════════════════════════════════
# APScheduler 版本：独立 Job，互不干扰
# ═══════════════════════════════════════════════════════════════════════════

def _job_news_morning(rm):
    """早间新闻播报（9:00）"""
    _execute_news_task(rm, "news_morning", "早间")


def _job_news_afternoon(rm):
    """午间新闻播报（13:00）"""
    _execute_news_task(rm, "news_afternoon", "午间")


def _job_news_evening(rm):
    """晚间新闻播报（20:35）"""
    _execute_news_task(rm, "news_evening", "晚间")


def _job_trendradar_morning(rm):
    """旧的TrendRadar早间播报入口已停用，保留函数仅兼容历史调用"""
    logger.info("ℹ️ trendradar_morning 已并入 news_morning 统一主流程")


def _job_trendradar_noon(rm):
    """旧的TrendRadar午间播报入口已停用，保留函数仅兼容历史调用"""
    logger.info("ℹ️ trendradar_noon 已并入 news_afternoon 统一主流程")


def _job_trendradar_evening(rm):
    """旧的TrendRadar晚间播报入口已停用，保留函数仅兼容历史调用"""
    logger.info("ℹ️ trendradar_evening 已并入 news_evening 统一主流程")


def _job_greeting_morning(rm):
    """早安问候（8:00）"""
    if not _try_claim_task("greeting_morning", 7200):
        return
    if not rm.db.claim_task("greeting_morning"):
        logger.info(f"✅ greeting_morning 已被抢占（数据库），跳过")
        return
    try:
        with rm.locked('config'):
            gid = rm.config.get("GROUP_ID", 0)
        if gid == 0:
            return
        
        seed = random.randint(100000, 999999)
        with rm.locked('ai'):
            msg = rm.ai.ask("早安", mode="morning", seed=seed)
        if msg:
            msg = msg.replace("\n", " ").strip()[:250]
            sent = _send_and_track(rm, gid, f"☀️ {msg}")
            if sent:
                logger.info(f"☀️ 早安已发送：{msg}")
    except Exception as e:
        logger.error(f"早安问候失败：{e}")
        _retry_task(rm, _job_greeting_morning, "greeting_morning")


def _job_greeting_afternoon(rm):
    """午安问候（12:30）"""
    if not _try_claim_task("greeting_afternoon", 7200):
        return
    if not rm.db.claim_task("greeting_afternoon"):
        logger.info(f"✅ greeting_afternoon 已被抢占（数据库），跳过")
        return
    try:
        with rm.locked('config'):
            gid = rm.config.get("GROUP_ID", 0)
        if gid == 0:
            return
        
        seed = random.randint(100000, 999999)
        with rm.locked('ai'):
            msg = rm.ai.ask("午安", mode="afternoon", seed=seed)
        if msg:
            msg = msg.replace("\n", " ").strip()[:250]
            sent = _send_and_track(rm, gid, f"🍃 {msg}")
            if sent:
                logger.info(f"🍃 午安已发送：{msg}")
    except Exception as e:
        logger.error(f"午安问候失败：{e}")
        _retry_task(rm, _job_greeting_afternoon, "greeting_afternoon")


def _job_greeting_evening(rm):
    """晚安问候（23:00）"""
    if not _try_claim_task("greeting_evening", 7200):
        return
    if not rm.db.claim_task("greeting_evening"):
        logger.info(f"✅ greeting_evening 已被抢占（数据库），跳过")
        return
    try:
        with rm.locked('config'):
            gid = rm.config.get("GROUP_ID", 0)
        if gid == 0:
            return
        
        seed = random.randint(100000, 999999)
        with rm.locked('ai'):
            msg = rm.ai.ask("晚安", mode="evening", seed=seed)
        if msg:
            msg = msg.replace("\n", " ").strip()[:250]
            sent = _send_and_track(rm, gid, f"🌙 {msg}")
            if sent:
                logger.info(f"🌙 晚安已发送：{msg}")
    except Exception as e:
        logger.error(f"晚安问候失败：{e}")
        _retry_task(rm, _job_greeting_evening, "greeting_evening")


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
    except Exception:
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
    """阅后即焚孤儿清理（每10分钟）
    
    两阶段清理：
    Phase 1: 清理超过30分钟未回复的孤儿消息（直接删除Bot回复）
    Phase 2: 探测5-30分钟内的未回复消息，检测用户是否已删原消息
    """
    try:
        # ── Phase 1: 清理超时孤儿（30分钟窗口）──
        logger.info("🔍 [Phase1] 检查超时孤儿消息...")
        orphans = rm.db.get_orphan_messages(1800)
        if orphans:
            logger.info(f"🗑️ 发现{len(orphans)}条超时孤儿（>30分钟未回复），开始清理...")
            success_count = 0
            fail_count = 0
            for bot_mid, cid, user_mid in orphans:
                try:
                    with rm.locked('bot'):
                        rm.bot.delete_message(cid, int(bot_mid))
                    success_count += 1
                except Exception as del_err:
                    fail_count += 1
                    logger.debug(f"  删除失败：bot_mid={bot_mid}, err={del_err}")
                rm.db.delete_tracked(bot_mid, cid)
            logger.info(f"✅ Phase1完成：成功{success_count}条，失败{fail_count}条")
        else:
            logger.info("✅ Phase1：无超时孤儿")

        # ── Phase 2: 探测用户是否删了原消息 ──
        logger.info("🔍 [Phase2] 探测用户删消息情况...")
        recent = rm.db.get_recent_unreplied(300, 1800, limit=3)
        if not recent:
            logger.info("✅ Phase2：无近期未回复消息需要探测")
            return

        logger.info(f"🔍 Phase2：探测{len(recent)}条近期未回复消息...")
        deleted_count = 0
        admin_id = rm.config.get("ADMIN_ID", 0)

        for bot_mid, cid, user_mid in recent:
            try:
                with rm.locked('bot'):
                    forwarded = rm.bot.forward_message(
                        admin_id, cid, user_mid,
                        disable_notification=True
                    )
                if forwarded:
                    try:
                        with rm.locked('bot'):
                            rm.bot.delete_message(admin_id, forwarded.message_id)
                    except Exception:
                        pass
            except Exception as fwd_err:
                err_str = str(fwd_err).lower()
                if any(kw in err_str for kw in ["not found", "bad request", "message to forward not found"]):
                    logger.info(f"🗑️ 用户消息{user_mid}已被删，清理Bot回复{bot_mid}")
                    try:
                        with rm.locked('bot'):
                            rm.bot.delete_message(cid, int(bot_mid))
                    except Exception:
                        pass
                    rm.db.delete_tracked(bot_mid, cid)
                    deleted_count += 1
            time.sleep(0.5)

        if deleted_count > 0:
            logger.info(f"✅ Phase2完成：检测到{deleted_count}条用户删消息，已清理Bot回复")
        else:
            logger.info("✅ Phase2：未检测到用户删消息")

    except Exception as e:
        logger.error(f"❌ 阅后即焚孤儿清理失败：{e}", exc_info=True)


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
    except Exception:
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
    if not _try_claim_task("reactivate", 3600):
        return
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
    except Exception:
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
    if not _try_claim_task("cart_recovery", 3600):
        return
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
    if not _try_claim_task("leak", 86400):
        return
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
                sent = _send_and_track(rm, gid, f"🤫 老板不在... 偷偷跟你们说：\n\n{leak}")
                if sent:
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
    """TTL历史数据清理（每小时）+ 内存字典定期清理"""
    try:
        ts = int(time.time())
        cutoff = ts - 7 * 86400
        deleted_track, deleted_spam, deleted_puzzle = rm.db.cleanup_old_records(cutoff)
        if deleted_track or deleted_spam or deleted_puzzle:
            logger.info(f"🧹 TTL清理: 追踪{deleted_track}条/垃圾{deleted_spam}条/谜题{deleted_puzzle}条")
        rm.db.cleanup_old_task_log()
    except Exception as e:
        logger.error(f"TTL清理失败：{e}")
    try:
        from main import _cleanup_conv_tracker, _cleanup_radar_cooldown
        _cleanup_conv_tracker()
        _cleanup_radar_cooldown()
    except Exception as e:
        logger.debug(f"内存字典清理跳过：{e}")


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
    """【v4.2.3→v4.5.32】更新频道浏览量+多频道成员数统计"""
    try:
        tracked = rm.db.get_channel_tracking(limit=5)
        gid = rm.config.get("GROUP_ID", 0)
        
        for chat_id, msg_id, content_type, posted_at, current_views in tracked:
            try:
                with rm.locked('bot'):
                    msg_info = rm.bot.forward_message(
                        rm.config.get("ADMIN_ID", 0), 
                        chat_id, 
                        msg_id,
                        disable_notification=True
                    )
                new_views = getattr(msg_info, 'views', None) if msg_info else None
                if new_views is not None and new_views > current_views:
                    rm.db.update_channel_views(chat_id, msg_id, new_views)
                    logger.info(f"📊 频道浏览量更新: chat={chat_id} msg={msg_id} views={new_views}")
                try:
                    with rm.locked('bot'):
                        rm.bot.delete_message(rm.config.get("ADMIN_ID", 0), msg_info.message_id)
                except Exception:
                    pass
            except Exception as e:
                err_str = str(e).lower()
                if "not found" in err_str or "bad request" in err_str:
                    rm.db.update_channel_views(chat_id, msg_id, -1)
                logger.debug(f"获取浏览量失败: chat={chat_id} msg={msg_id} err={e}")
        
        if gid:
            try:
                with rm.locked('bot'):
                    member_count = rm.bot.get_chat_member_count(gid)
                rm.db.update_group_total_members(member_count, gid)
                logger.info(f"👥 群成员数更新: {member_count}")
            except Exception as e:
                logger.debug(f"群成员数获取失败: {e}")

        channel_ids = rm.config.get("CHANNEL_IDS", [])
        if channel_ids:
            _update_channel_member_counts(rm, channel_ids)
        
        logger.info("✅ 频道浏览量更新任务完成")
    except Exception as e:
        logger.error(f"频道浏览量更新失败：{e}")


def _update_channel_member_counts(rm, channel_ids: list):
    """获取多频道成员数并写入数据库"""
    for ch in channel_ids:
        cid = ch.get("id", 0) if isinstance(ch, dict) else ch
        cname = ch.get("name", str(cid)) if isinstance(ch, dict) else str(cid)
        try:
            with rm.locked('bot'):
                count = rm.bot.get_chat_member_count(cid)
            rm.db.update_group_total_members(count, cid)
            logger.info(f"📊 频道成员数: {cname}={count}")
        except Exception as e:
            logger.debug(f"频道成员数获取失败: {cname} err={e}")


def _job_daily_report(rm):
    """【v4.5.32】每日数据报告 - 拆分为群报告+频道报告，私聊发送"""
    if not _try_claim_task("daily_report", 7200):
        return
    if not rm.db.claim_task("daily_report"):
        logger.info(f"✅ daily_report 已被抢占（数据库），跳过")
        return
    try:
        admin_id = rm.config.get("ADMIN_ID", 0)
        if not admin_id:
            return
        
        now = datetime.now(_CST)
        today = now.strftime("%Y-%m-%d")
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        gid = rm.config.get("GROUP_ID", 0)
        
        def trend(cur, prev):
            if cur > prev: return "📈"
            if cur < prev: return "📉"
            return "➖"

        _send_daily_group_report(rm, admin_id, today, yesterday, gid, trend)
        _send_daily_channel_report(rm, admin_id, today, trend)
        
        logger.info(f"✅ 每日数据报告已发送（群+频道）")
    except Exception as e:
        logger.error(f"每日数据报告失败：{e}")


def _send_daily_group_report(rm, admin_id: int, today: str, yesterday: str, gid: int, trend_fn):
    """发送群数据日报"""
    group_stats_today = rm.db.get_group_stats_by_date(today)
    group_stats_yesterday = rm.db.get_group_stats_by_date(yesterday)
    
    joined_today = left_today = net_today = 0
    for row in group_stats_today:
        if len(row) >= 6:
            joined_today += row[2] or 0
            left_today += row[3] or 0
            net_today += row[4] or 0
    
    joined_yest = left_yest = net_yest = 0
    for row in group_stats_yesterday:
        if len(row) >= 6:
            joined_yest += row[2] or 0
            left_yest += row[3] or 0
            net_yest += row[4] or 0
    
    active_today = rm.db.get_daily_active_users(today)
    active_yest = rm.db.get_daily_active_users(yesterday)
    bot_msgs_today = rm.db.get_daily_bot_messages(today)
    bot_msgs_yest = rm.db.get_daily_bot_messages(yesterday)
    replies_today = rm.db.get_daily_replies(today)
    replies_yest = rm.db.get_daily_replies(yesterday)
    
    total_members = 0
    if gid:
        try:
            with rm.locked('bot'):
                total_members = rm.bot.get_chat_member_count(gid)
        except Exception:
            total_members = rm.db.get_group_total_members_latest(gid)
    
    reply_rate = (replies_today / max(bot_msgs_today, 1)) * 100
    
    html = f"""🏠 <b>群数据日报</b> · {today}

━━━━━━━━━━━━━━━━━━

📊 <b>群动态</b>
├ 今日入群：{joined_today} {trend_fn(joined_today, joined_yest)}
├ 今日离群：{left_today} {trend_fn(left_today, left_yest)}
├ 净增人数：{net_today:+d} {trend_fn(net_today, net_yest)}
└ 群成员数：{total_members}

━━━━━━━━━━━━━━━━━━

👥 <b>活跃度</b>
├ 活跃用户：{active_today} {trend_fn(active_today, active_yest)}
├ Bot消息数：{bot_msgs_today} {trend_fn(bot_msgs_today, bot_msgs_yest)}
├ 用户回复数：{replies_today} {trend_fn(replies_today, replies_yest)}
└ 互动率：{reply_rate:.0f}%

━━━━━━━━━━━━━━━━━━

🌙 <b>昨日同期</b>
├ 入群{joined_yest}/离群{left_yest}/净增{net_yest:+d}
├ 活跃{active_yest}/Bot消息{bot_msgs_yest}/回复{replies_yest}

━━━━━━━━━━━━━━━━━━
<i>系统自动生成 · Mory小助理</i>"""
    
    with rm.locked('bot'):
        rm.bot.send_message(admin_id, html, parse_mode="HTML")
    logger.info(f"✅ 群日报已发送: 入群{joined_today} 离群{left_today} 净增{net_today}")


def _send_daily_channel_report(rm, admin_id: int, today: str, trend_fn):
    """发送频道数据日报"""
    channel_ids = rm.config.get("CHANNEL_IDS", [])
    if not channel_ids:
        return
    
    channel_lines = []
    for ch in channel_ids:
        cid = ch.get("id", 0) if isinstance(ch, dict) else ch
        cname = ch.get("name", str(cid)) if isinstance(ch, dict) else str(cid)
        try:
            with rm.locked('bot'):
                ch_count = rm.bot.get_chat_member_count(cid)
            ch_views_data = rm.db.get_channel_tracking(chat_id=cid, limit=10)
            ch_total_views = sum(v[4] for v in ch_views_data if len(v) >= 5 and v[4] > 0)
            ch_post_count = len(ch_views_data)
            ch_avg = ch_total_views // max(ch_post_count, 1)
            channel_lines.append(f"├ {cname}：{ch_count}人 | 今日{ch_post_count}帖 | 均览{ch_avg}")
        except Exception:
            channel_lines.append(f"├ {cname}：获取失败")
    
    if channel_lines:
        channel_lines[-1] = channel_lines[-1].replace("├", "└", 1)
    
    channel_stats = rm.db.get_channel_stats_summary()
    tracked_count = channel_stats.get("total_posts", 0)
    total_views = max(channel_stats.get("total_views", 0), 0)
    avg_views = total_views // max(tracked_count, 1)
    
    html = f"""📡 <b>频道数据日报</b> · {today}

━━━━━━━━━━━━━━━━━━

📈 <b>各频道概况</b>
{chr(10).join(channel_lines)}

━━━━━━━━━━━━━━━━━━

📊 <b>整体内容</b>
├ 追踪消息：{tracked_count} 条
├ 总浏览量：{total_views:,}
└ 平均浏览：{avg_views}

━━━━━━━━━━━━━━━━━━
<i>系统自动生成 · Mory小助理</i>"""
    
    with rm.locked('bot'):
        rm.bot.send_message(admin_id, html, parse_mode="HTML")
    logger.info("✅ 频道日报已发送")


def _job_weekly_report(rm):
    """【v4.5.32】每周数据报告 - 群周报+频道周报，含趋势分析"""
    if not _try_claim_task("weekly_report", 86400):
        return
    if not rm.db.claim_task("weekly_report"):
        logger.info(f"✅ weekly_report 已被抢占（数据库），跳过")
        return
    try:
        admin_id = rm.config.get("ADMIN_ID", 0)
        if not admin_id:
            return
        
        now = datetime.now(_CST)
        today = now.strftime("%Y-%m-%d")
        week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        two_weeks_ago = (now - timedelta(days=14)).strftime("%Y-%m-%d")
        week_ago_ts = int((now - timedelta(days=7)).timestamp())
        now_ts = int(now.timestamp())
        
        _send_weekly_group_report(rm, admin_id, today, week_ago, two_weeks_ago)
        _send_weekly_channel_report(rm, admin_id, today, week_ago, week_ago_ts, now_ts)
        
        logger.info("✅ 每周数据报告已发送（群+频道）")
    except Exception as e:
        logger.error(f"每周数据报告失败：{e}")


def _send_weekly_group_report(rm, admin_id: int, today: str, week_ago: str, two_weeks_ago: str):
    """发送群数据周报"""
    gid = rm.config.get("GROUP_ID", 0)
    this_week = rm.db.get_weekly_group_stats(week_ago, today)
    last_week = rm.db.get_weekly_group_stats(two_weeks_ago, week_ago)
    
    total_members = 0
    if gid:
        try:
            with rm.locked('bot'):
                total_members = rm.bot.get_chat_member_count(gid)
        except Exception:
            total_members = rm.db.get_group_total_members_latest(gid)
    
    def pct(cur, prev):
        if prev == 0: return "🆕" if cur > 0 else "➖"
        diff = ((cur - prev) / prev) * 100
        if diff > 0: return f"📈+{diff:.0f}%"
        if diff < 0: return f"📉{diff:.0f}%"
        return "➖0%"
    
    def trend(cur, prev):
        if cur > prev: return "📈"
        if cur < prev: return "📉"
        return "➖"
    
    retention = 0
    if this_week["joined"] > 0:
        retention = max(0, (this_week["joined"] - this_week["left"]) / this_week["joined"] * 100)
    
    html = f"""🏠 <b>群数据周报</b> · {week_ago} ~ {today}

━━━━━━━━━━━━━━━━━━

📊 <b>本周群动态</b>
├ 入群：{this_week['joined']} {trend(this_week['joined'], last_week['joined'])}
├ 离群：{this_week['left']} {trend(this_week['left'], last_week['left'])}
├ 净增：{this_week['net']:+d} {trend(this_week['net'], last_week['net'])}
└ 当前成员：{total_members}

━━━━━━━━━━━━━━━━━━

📈 <b>周环比</b>
├ 入群变化：{pct(this_week['joined'], last_week['joined'])}
├ 离群变化：{pct(this_week['left'], last_week['left'])}
├ 净增变化：{pct(this_week['net'], last_week['net'])}
└ 留存率：{retention:.0f}%

━━━━━━━━━━━━━━━━━━

📉 <b>上周同期</b>
├ 入群{last_week['joined']}/离群{last_week['left']}/净增{last_week['net']:+d}
├ 周均成员：{last_week['avg_members']}

━━━━━━━━━━━━━━━━━━
<i>系统自动生成 · Mory小助理</i>"""
    
    with rm.locked('bot'):
        rm.bot.send_message(admin_id, html, parse_mode="HTML")
    logger.info("✅ 群周报已发送")


def _send_weekly_channel_report(rm, admin_id: int, today: str, week_ago: str, week_ago_ts: int, now_ts: int):
    """发送频道数据周报"""
    channel_ids = rm.config.get("CHANNEL_IDS", [])
    if not channel_ids:
        return
    
    channel_lines = []
    total_posts = 0
    total_views = 0
    for ch in channel_ids:
        cid = ch.get("id", 0) if isinstance(ch, dict) else ch
        cname = ch.get("name", str(cid)) if isinstance(ch, dict) else str(cid)
        try:
            with rm.locked('bot'):
                ch_count = rm.bot.get_chat_member_count(cid)
            ch_stats = rm.db.get_channel_posts_in_range(cid, week_ago_ts, now_ts)
            ch_member_stats = rm.db.get_weekly_channel_member_stats(cid, week_ago, today)
            member_growth = ch_member_stats["max"] - ch_member_stats["min"]
            total_posts += ch_stats["posts"]
            total_views += ch_stats["views"]
            channel_lines.append(f"├ {cname}：{ch_count}人(周+{member_growth}) | {ch_stats['posts']}帖 | 均览{ch_stats['avg_views']}")
        except Exception:
            channel_lines.append(f"├ {cname}：获取失败")
    
    if channel_lines:
        channel_lines[-1] = channel_lines[-1].replace("├", "└", 1)
    
    overall_avg = total_views // max(total_posts, 1)
    
    html = f"""📡 <b>频道数据周报</b> · {week_ago} ~ {today}

━━━━━━━━━━━━━━━━━━

📊 <b>各频道周数据</b>
{chr(10).join(channel_lines)}

━━━━━━━━━━━━━━━━━━

📈 <b>整体周表现</b>
├ 周发帖：{total_posts} 条
├ 周浏览：{total_views:,}
└ 周均浏览：{overall_avg}

━━━━━━━━━━━━━━━━━━
<i>系统自动生成 · Mory小助理</i>"""
    
    with rm.locked('bot'):
        rm.bot.send_message(admin_id, html, parse_mode="HTML")
    logger.info("✅ 频道周报已发送")


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
    
    if date_key != _tarot_cache_last_date:
        _tarot_daily_cache = {}
        _tarot_cache_last_date = date_key
    
    cache_key = f"{uid}_{date_key}"
    
    if cache_key not in _tarot_daily_cache:
        # 生成新数据并缓存
        _tarot_daily_cache[cache_key] = _generate_tarot_data(uid)
    
    return _tarot_daily_cache[cache_key]


def _get_fallback_hook(theme: str, uname: str) -> str:
    """撩人转化文案 - 绿茶口吻，隐晦引导（AI失败时的备用）"""
    hooks = [
        f"这牌还有更深层的意思呢，想知道吗",
        f"其实这张牌背面藏着另一段故事哦",
        f"有些话这里说不完，你懂的",
        f"今天这牌其实还有后半段没揭晓呢",
        f"你今天的运势其实还有隐藏玩法",
        f"有些惊喜光看这几行字可不够呢",
        f"这运势只是冰山一角，水面下才精彩",
        f"老粉都知道，这牌还有另一面",
        f"其实今天的好事不止这些，还有呢",
        f"这牌暗示的东西，可比表面深多了",
        f"想知道这张牌真正想告诉你的事吗",
        f"有些缘分，只有慢慢聊才能懂呢",
        f"今天这运势后面还跟着个彩蛋哦",
        f"这牌的解读嘛，三言两语可说不清",
        f"有些话得悄悄说才更有味道呢",
    ]
    return random.choice(hooks)


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
    """调用AI生成完整的塔罗运势内容（整卡控制在一屏内，约130字）"""
    seed_for_ai = seed or random.randint(100000, 999999)
    
    prompt = f"""你是Mory老板，一个撩人的塔罗师，像闺蜜一样亲切。

根据以下信息生成塔罗运势，全部要浓缩在一屏能看完的长度：

【运势类型】：{tarot['theme']}
【塔罗牌】：{tarot['card']} {tarot['position']}

请按以下格式生成：

1. 牌面描述（一句话，15-25字，有画面感，带一个emoji）
2. 今日解读（1-2句话，30-40字，有故事感，带emoji）
3. 今日建议（一句话，15字以内，带emoji）
4. 幸运色（只写颜色，2-4字）
5. 幸运方位（只写方位，2-4字）
6. 幸运数字（3个数字，如：7,23,45）
7. 贵人星座（只写星座名）
8. 幸运时段（如：上午9-11点）

seed={seed_for_ai}
要求：
- 语气温柔亲切，像闺蜜聊天
- 禁止空话套话，用画面感语言
- 解读要有故事感，别超过40字
- 每次seed不同，内容必须不同"""

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
    """【v4.2.5→v4.5.31】每日塔罗搭讪（30%概率，针对群里活跃用户）原子防重
    
    【特性】
    - 同一人同一天结果固定（北京时间为准）
    - 高度随机：40%短版 / 60%长版
    - 卡片式排版，手机一屏可看完
    """
    global _tarot_daily_cache, _tarot_cache_last_date
    today_key = datetime.now(_CST).strftime("%Y-%m-%d")
    if today_key != _tarot_cache_last_date:
        _tarot_daily_cache = {}
        _tarot_cache_last_date = today_key

    if not _try_claim_task("tarot_flirt", 7200):
        return
    
    # 30%概率触发（在claim前检查，避免占用名额）
    if random.random() > 0.30:
        return
    
    if not rm.db.claim_task("tarot_flirt"):
        logger.info(f"✅ tarot_flirt 已被抢占（数据库），跳过")
        return
    try:
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
        except Exception:
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
        convert_prompt = f"""你是Mory老板，一个撩人的塔罗师。

给刚测完「{tarot['theme']}」的「{uname}」写一句撩人引导语。

要求：
1. 20-30字，像闺蜜私聊一样自然
2. 暗示有更深度的解读等着他，勾起好奇心
3. 禁止：会员、付费、订阅、解锁、钱、开通、VIP、专属版、赞助、免费、完整版、私聊
4. 撩人但隐晦，让人心痒痒想追问
5. 每次seed不同，内容必须不重复
6. 不要emoji

seed={convert_seed}"""
        
        try:
            with rm.locked('ai'):
                convert_hint = rm.ai.ask(convert_prompt, mode="convert_hook", seed=convert_seed)
            if not convert_hint or len(convert_hint) < 10:
                convert_hint = _get_fallback_hook(tarot['theme'], uname)
        except Exception:
            convert_hint = _get_fallback_hook(tarot['theme'], uname)
        
        # 构建HTML卡片消息（高度随机：40%短版 / 60%长版）
        short_mode = random.random() < 0.4
        
        if short_mode:
            # ══ 短版：约70字，手机一屏看完
            html_reply = f"""🎴 <b>{tarot['card']} {tarot['position']}</b>

@{uname} {opener_text} {opener_action}「{user_msg[:10]}」~

📖 {tarot['meaning']}

🌈 {tarot['color']} · 📍 {tarot['dir']}

{convert_hint}"""
        else:
            # ══ 长版：约110字（控制在一屏内）
            html_reply = f"""🎴 <b>{tarot['theme']}</b> · {tarot['card']} {tarot['position']}

@{uname} {opener_text} {opener_action}「{user_msg[:10]}」~

📖 {tarot['meaning']}

💡 {tarot['advice']}

🌈 {tarot['color']} · 📍 {tarot['dir']} · 🔢 {tarot['nums']} · ⭐ {tarot['star']} · ⏰ {tarot['time']}

{convert_hint}"""
        
        # 发送HTML格式消息
        try:
            with rm.locked('bot'):
                rm.bot.send_message(gid, html_reply, parse_mode="HTML")
            logger.info(f" 塔罗搭讪成功: @{uname}")
        except Exception as e:
            logger.error(f"塔罗搭讪发送失败：{e}")
    except Exception as e:
        logger.error(f"塔罗搭讪任务失败：{e}")


def _do_backup(db_file: str):
    """执行数据库备份，保留最近7天（168份）"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    backup_dir = os.path.join(base_dir, "backup")
    os.makedirs(backup_dir, exist_ok=True)
    ts_str = datetime.now(_CST).strftime("%Y%m%d_%H00")
    dest = os.path.join(backup_dir, f"mory_backup_{ts_str}.db")
    try:
        import sqlite3 as _sqlite3
        src_conn = _sqlite3.connect(db_file)
        dst_conn = _sqlite3.connect(dest)
        src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()
        backups = sorted(glob.glob(os.path.join(backup_dir, "mory_backup_*.db")))
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
    global _scheduler_instance
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    _scheduler_instance = scheduler
    
    # 新闻播报（misfire_grace_time=60：1分钟内错过可补发，coalesce防堆积连发）
    scheduler.add_job(_job_news_morning, "cron", hour=9, minute=5, args=[rm], id="news_morning", max_instances=1, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(_job_news_afternoon, "cron", hour=13, minute=5, args=[rm], id="news_afternoon", max_instances=1, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(_job_news_evening, "cron", hour=20, minute=35, args=[rm], id="news_evening", max_instances=1, coalesce=True, misfire_grace_time=60)
    
    # 每日数据报告（v4.2.4）- 私聊发送
    scheduler.add_job(_job_daily_report, "cron", hour=9, minute=10, args=[rm], id="daily_report", max_instances=1, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(_job_weekly_report, "cron", day_of_week="mon", hour=9, minute=30, args=[rm], id="weekly_report", max_instances=1, coalesce=True, misfire_grace_time=3600)
    
    # 每日塔罗搭讪（v4.2.5）- 随机30%概率
    scheduler.add_job(_job_tarot_flirt, "cron", hour=15, minute=0, args=[rm], id="tarot_flirt", max_instances=1, coalesce=True, misfire_grace_time=60)
    
    # 问候
    scheduler.add_job(_job_greeting_morning, "cron", hour=8, minute=5, args=[rm], id="greeting_morning", max_instances=1, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(_job_greeting_afternoon, "cron", hour=12, minute=35, args=[rm], id="greeting_afternoon", max_instances=1, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(_job_greeting_evening, "cron", hour=23, minute=5, args=[rm], id="greeting_evening", max_instances=1, coalesce=True, misfire_grace_time=60)
    
    # 叫醒服务（每分钟）
    scheduler.add_job(_job_wakeup_check, "cron", minute="*", args=[rm], id="wakeup_check", max_instances=1, misfire_grace_time=60)
    
    # 阅后即焚探测（每5分钟 - v4.0.3降频以节省API配额）
    # 注意：_job_burn_probe 已降级为空操作，主要依赖孤儿清理TTL机制
    scheduler.add_job(_job_burn_probe, "cron", minute="*/5", args=[rm], id="burn_probe", max_instances=1, misfire_grace_time=300)
    
    # 每小时执行一次阅后即焚孤儿清理（v4.5.19降频：避免429限流）
    scheduler.add_job(_job_burn_orphan, "cron", minute="5", args=[rm], id="burn_orphan", max_instances=1, misfire_grace_time=300)
    scheduler.add_job(_job_reactivate, "cron", minute=5, args=[rm], id="reactivate", max_instances=1, misfire_grace_time=300)
    scheduler.add_job(_job_cart_recovery, "cron", minute=10, args=[rm], id="cart_recovery", max_instances=1, misfire_grace_time=300)
    scheduler.add_job(_job_backup, "cron", minute=15, args=[rm], id="backup", max_instances=1, misfire_grace_time=300)
    scheduler.add_job(_job_ttl_cleanup, "cron", minute=20, args=[rm], id="ttl_cleanup", max_instances=1, misfire_grace_time=300)
    scheduler.add_job(_job_save_config, "cron", minute=30, args=[rm], id="save_config", max_instances=1, misfire_grace_time=300)
    scheduler.add_job(_job_channel_views, "cron", minute=25, args=[rm], id="channel_views", max_instances=1, misfire_grace_time=300)
    
    # 背刺泄密（每周三0点）
    scheduler.add_job(_job_leak, "cron", day_of_week="wed", hour=0, minute=0, args=[rm], id="leak", max_instances=1, misfire_grace_time=3600)
    
    scheduler.start()
    logger.info("🚀 后台任务引擎启动（APScheduler版，各任务独立运行）")


def _start_with_legacy_loop(rm):
    """旧版 while True 循环（APScheduler 未安装时回退）"""
    t = threading.Thread(target=_legacy_task_loop, args=(rm,), daemon=True, name="AutoTasks-Legacy")
    t.start()
    logger.info("🚀 后台任务引擎启动（旧版循环，APScheduler未安装）")


def _legacy_task_loop(rm):
    """旧版 while True 循环（兼容备用）- 已迁移至 _can_run/_mark_done 节流"""
    global _last_saved_model_idx
    while True:
        try:
            now = datetime.now(_CST)

            _job_wakeup_check(rm)

            if _can_run("burn_probe", 180):
                try:
                    _job_burn_probe(rm)
                except Exception as e:
                    logger.error(f"burn_probe异常: {e}")
                _mark_done("burn_probe")

            if _can_run("burn_orphan", 600):
                try:
                    _job_burn_orphan(rm)
                except Exception as e:
                    logger.error(f"burn_orphan超时或异常: {e}")
                _mark_done("burn_orphan")

            if _can_run("backup", 3600):
                try:
                    _job_backup(rm)
                except Exception as e:
                    logger.error(f"backup异常: {e}")
                _mark_done("backup")

            if _can_run("ttl_cleanup", 3600):
                try:
                    _job_ttl_cleanup(rm)
                except Exception as e:
                    logger.error(f"ttl_cleanup异常: {e}")
                _mark_done("ttl_cleanup")

            try:
                _job_reactivate(rm)
            except Exception as e:
                logger.error(f"reactivate异常: {e}")
            try:
                _job_cart_recovery(rm)
            except Exception as e:
                logger.error(f"cart_recovery异常: {e}")
            try:
                _job_save_config(rm)
            except Exception as e:
                logger.error(f"save_config异常: {e}")

            if now.weekday() == 2 and now.hour == 0 and now.minute == 0:
                _job_leak(rm)

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
