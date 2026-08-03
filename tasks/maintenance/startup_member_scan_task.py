"""
tasks/maintenance/startup_member_scan_task.py - 启动成员扫描任务

启动时扫描群成员，基于用户名/Bio/头像检测广告号并永久禁言。
"""

import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from core.task_transaction import TaskTransactionManager
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.startup_member_scan")

_CST = timezone(timedelta(hours=8))


class StartupMemberScanTask(BaseTask):
    """启动成员扫描任务（启动时执行一次，窗口内互斥）。"""

    @property
    def task_id(self) -> str:
        return "startup_member_scan"

    def schedule(self) -> List[Dict[str, Any]]:
        # 一次性启动任务，不在常规 cron 中注册
        return []

    def execute(self, ctx: TaskContext) -> None:
        try:
            _hour = datetime.now(_CST).strftime("%Y-%m-%d_%H")
            with TaskTransactionManager(f"startup_member_scan_{_hour}", self.rm.db,
                                        resources=None, min_interval_sec=3600) as tx:
                if not tx.claimed:
                    return

                logger.info("[启动扫描] 开始扫描群成员...")
                config = self.rm.config
                bot = self.rm.bot
                db = self.rm.db

                group_ids = []
                gid = config.get("GROUP_ID", 0)
                if gid:
                    group_ids = [gid]
                else:
                    try:
                        mg = config.get("MANAGED_GROUPS", [])
                        if isinstance(mg, int):
                            group_ids = [mg]
                        elif mg:
                            group_ids = mg
                    except Exception as e:
                        logger.error(f"读取管理群配置失败: {e}")
                        raise

                if not group_ids:
                    logger.info("[启动扫描] 未找到管理的群组，跳过成员扫描")
                    return

                from modules.ad_patterns_encoded import USERNAME_PATTERNS, BIO_PATTERNS

                admin_id = config.get("ADMIN_ID", 0)
                whitelist_cfg = config.get("AD_WHITELIST", {})
                whitelist_uids = set(whitelist_cfg.get("user_ids", []) if isinstance(whitelist_cfg, dict) else [])

                total_banned = 0
                total_scanned = 0
                failures = []

                for chat_id in group_ids:
                    try:
                        admins = bot.get_chat_administrators(chat_id)
                        admin_ids = {a.user.id for a in admins}
                        admin_ids.add(bot.get_me().id)
                    except Exception as e:
                        # 管理员集合不可知时继续扫描可能误禁管理员；该群本轮安全跳过并标记失败。
                        logger.error(f"[启动扫描] 群{chat_id}管理员列表读取失败: {e}")
                        failures.append(e)
                        continue

                    all_uids = set()
                    uid_queries = [
                        "SELECT uid FROM users",
                        "SELECT user_id FROM group_join_log",
                        "SELECT user_id FROM ad_suspicious_users",
                        "SELECT uid FROM user_levels",
                        "SELECT DISTINCT uid FROM speech_daily",
                        "SELECT DISTINCT uid FROM deleted_messages",
                        "SELECT DISTINCT uid FROM checkin_records",
                        "SELECT DISTINCT uid FROM points_log",
                        "SELECT uid FROM user_tags",
                        "SELECT uid FROM user_notes",
                        "SELECT DISTINCT uid FROM achievements",
                        "SELECT DISTINCT uid FROM redpacket_claims",
                        "SELECT DISTINCT uid FROM lottery_participants",
                    ]
                    for query in uid_queries:
                        try:
                            rows = db.conn.execute(query).fetchall()
                            for row in rows:
                                uid = row[0]
                                if uid and isinstance(uid, int) and uid > 0:
                                    all_uids.add(uid)
                        except Exception as e:
                            logger.error(f"[启动扫描] UID 聚合查询失败 query={query}: {e}")
                            failures.append(e)
                    try:
                        gm_rows = db.conn.execute("SELECT uid FROM group_members WHERE chat_id=?", (chat_id,)).fetchall()
                        for row in gm_rows:
                            all_uids.add(row[0])
                    except Exception as e:
                        logger.error(f"[启动扫描] group_members 查询失败 chat={chat_id}: {e}")
                        failures.append(e)
                    logger.info(f"[启动扫描] 群{chat_id}: 聚合{len(all_uids)}个用户ID")

                    for uid in all_uids:
                        if uid in admin_ids or uid in whitelist_uids:
                            continue

                        try:
                            # v5.38.14：加 request_timeout 防护单次 API 慢响应阻塞 scheduler
                            member = bot.get_chat_member(chat_id, uid, request_timeout=10)
                            if member.status in ("left", "kicked"):
                                continue
                            user = member.user
                            if user.is_bot:
                                continue
                        except Exception:
                            continue

                        total_scanned += 1
                        user_name = (user.first_name or "") + (user.last_name or "")
                        tg_username = getattr(user, 'username', None) or ""

                        uname_score = 0
                        for pat in USERNAME_PATTERNS:
                            try:
                                if re.search(pat, user_name + (" @" + tg_username if tg_username else ""), re.IGNORECASE):
                                    uname_score += 2
                                    break
                            except Exception as e:
                                logger.debug(f"操作异常: {e}")
                        if tg_username and re.match(r'^[a-z]{1,4}\d{2,4}$', tg_username, re.IGNORECASE):
                            uname_score += 2

                        bio_text = ""
                        try:
                            chat_info = bot.get_chat(user.id, request_timeout=10)
                            bio_text = getattr(chat_info, 'bio', None) or ""
                        except Exception as e:
                            logger.debug(f"操作异常: {e}")
                        bio_score = 0
                        if bio_text:
                            for pat in BIO_PATTERNS:
                                try:
                                    if re.search(pat, bio_text, re.IGNORECASE):
                                        bio_score += 3
                                        break
                                except Exception as e:
                                    logger.debug(f"操作异常: {e}")

                        should_ban = False
                        ban_reason = ""
                        if uname_score >= 1 and bio_score >= 3:
                            avatar_suspicious = False
                            try:
                                from modules.avatar_detector import check_user_avatar
                                avatar_suspicious, _ = check_user_avatar(bot, user.id)
                            except Exception as e:
                                logger.debug(f"操作异常: {e}")
                            if avatar_suspicious:
                                should_ban = True
                                ban_reason = "三层组合(用户名+Bio+头像)"
                            else:
                                should_ban = True
                                ban_reason = "两层组合(用户名+Bio)"

                        if should_ban:
                            try:
                                from modules.ad_enforcement import enforce_ad_user
                                enforce_ad_user(
                                    bot=bot,
                                    db=db,
                                    config=config,
                                    chat_id=chat_id,
                                    uid=user.id,
                                    uname=user_name,
                                    reason=f"启动扫描-{ban_reason}",
                                    notify_admin=False,
                                )
                                total_banned += 1
                                logger.warning(f"[启动扫描] 🚫 永久禁言: {user_name}({user.id}) {ban_reason}")

                            except Exception as e:
                                logger.error(f"[启动扫描] 封禁失败 {user_name}({user.id}): {e}")
                                failures.append(e)

                        if total_scanned % 30 == 0:
                            time.sleep(1.5)

                if admin_id and (total_banned > 0 or total_scanned > 0):
                    try:
                        bot.send_message(admin_id,
                            f"🔍 启动扫描完成\n"
                            f"📊 扫描群组：{len(group_ids)}个\n"
                            f"👥 检查成员：{total_scanned}人\n"
                            f"🚫 封禁广告号：{total_banned}人")
                    except Exception as e:
                        logger.error(f"[启动扫描] 管理员摘要发送失败: {e}")
                        failures.append(e)
                logger.info(f"[启动扫描] 完成：扫描{len(group_ids)}群/{total_scanned}人，封禁{total_banned}人")
                if failures:
                    raise ExceptionGroup("启动成员扫描任务失败", failures)
        except Exception as e:
            logger.error(f"启动成员扫描失败：{e}")
            raise
