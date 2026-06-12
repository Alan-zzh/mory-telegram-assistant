"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/database.py  ·  SQLite线程安全数据层（精简版）                     ║
║                                                                        ║
║  功能：                                                                ║
║    统一管理所有持久化数据。所有模块通过 main.py 创建的 db 单例访问。     ║
║    业务方法已拆分到 core/db_repos/ 下的7个Repo类。                     ║
║    通过 __getattr__ 委托实现100%向后兼容。                             ║
║                                                                        ║
║  数据表清单：                                                          ║
║    users             → 用户画像（uid/名称/首次/最后活跃/消息数/关键词）  ║
║    wake_up           → 叫醒服务（uid/时间）                             ║
║    puzzle_scores     → 碎片寻宝积分（uid/分数）                         ║
║    puzzle_daily      → 碎片寻宝每日记录（uid/日期，防同日重复）          ║
║    cart_recovery     → 购物车挽回（uid/触发时间戳）                     ║
║    reply_tracking    → 阅后即焚追踪（机器人消息ID/群ID/用户消息ID/状态） ║
║    user_levels       → 等级积分（uid/等级/积分/加入时间）               ║
║    mute_records      → 禁言记录（uid/群ID/解禁时间/原因）               ║
║    blacklist         → 黑名单（uid/原因/日期）                          ║
║    conversion_funnel → 转化漏斗（uid/接触/感兴趣/咨询/已付）            ║
║    spam_track        → 反刷检测（uid/消息数/窗口起始时间）              ║
║                                                                        ║
║  线程安全：全局互斥锁 _db_lock，所有写操作都在锁内完成。                ║
║  被调用：main.py, modules/*.py → db.xxx()                              ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import sqlite3
import time
from threading import Lock
from datetime import datetime, timedelta, timezone

# 【修复v21.47】统一使用北京时间，避免时区混乱导致每日重置错误
_CST = timezone(timedelta(hours=8))
from core.logging_util import get_logger

logger = get_logger("database")

# 全局互斥锁，确保并发写入安全
_db_lock = Lock()


class DB:
    """
    统一数据管理器（线程安全）。
    所有模块通过单例 `db` 访问。
    业务方法已拆分到7个Repo，通过 __getattr__ 委托实现向后兼容。
    """

    def __init__(self, db_file: str):
        self.db_file = db_file
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self.lock = _db_lock  # 暴露全局锁给Repo使用
        # 【修复】：开启 WAL 模式，提升多线程下 SQLite 并发性能，杜绝 Locked 报错
        self.conn.execute("PRAGMA journal_mode=WAL;")
        # 【v4.3.2修复F-07】WAL自动checkpoint，防止WAL文件无限增长
        self.conn.execute("PRAGMA wal_autocheckpoint=1000;")
        self._init_tables()
        # 初始化7个Repo实例
        from core.db_repos import UserRepo, GroupRepo, PointsRepo, TrackingRepo, ConfigRepo, SocialRepo, QuestionRepo, RelayRepo
        self.users = UserRepo(self)
        self.groups = GroupRepo(self)
        self.points = PointsRepo(self)
        self.tracking = TrackingRepo(self)
        self.config = ConfigRepo(self)
        self.social = SocialRepo(self)
        self.questions = QuestionRepo(self)
        self.relay = RelayRepo(self)

    # 【v4.3.2修复F-05】添加close()方法，确保SQLite连接正确关闭
    def close(self):
        """关闭数据库连接，释放资源"""
        with _db_lock:
            try:
                if self.conn:
                    self.conn.close()
                    _logger = getattr(self, '_logger', logger)
                    _logger.info("✅ 数据库连接已关闭")
            except Exception as e:
                _logger = getattr(self, '_logger', logger)
                _logger.warning(f"数据库关闭异常：{e}")

    def __del__(self):
        """析构时自动关闭连接（安全版本：不引用模块级logger，避免shutdown时None）"""
        try:
            if self.conn:
                with _db_lock:
                    self.conn.close()
        except Exception:
            pass

    # ──────────────────────────── 异常处理辅助 ──────────────────────────
    def _log_db_error(self, operation: str, error: Exception, level: str = "warning", context: str = ""):
        """
        【v4.18 统一异常处理】数据库操作异常的集中日志记录

        Args:
            operation: 操作描述（如"ALTER TABLE", "INSERT INTO points_log"）
            error: 异常对象
            level: 日志级别（"warning", "error", "critical"）
            context: 额外上下文信息（如 uid、task_name 等）
        """
        msg = f"数据库操作失败: {operation}"
        if context:
            msg += f" | {context}"
        msg += f" | 错误: {str(error)[:100]}"

        if level == "warning":
            logger.warning(msg)
        elif level == "error":
            logger.error(msg)
        elif level == "critical":
            logger.critical(msg)
            # 严重故障上报管理员
            try:
                from modules.auto_tasks import report_fault
                report_fault("数据库严重错误", msg, "🚨")
            except Exception:
                pass
        else:
            logger.warning(msg)

    # ─────────────────────────────── 初始化 ──────────────────────────────
    def _init_tables(self):
        with _db_lock:
            c = self.conn.cursor()

            # 用户画像
            c.execute("""CREATE TABLE IF NOT EXISTS users (
                uid INTEGER PRIMARY KEY,
                name TEXT,
                first_seen INTEGER,
                last_active INTEGER,
                group_messages INTEGER DEFAULT 0,
                private_messages INTEGER DEFAULT 0,
                keywords TEXT DEFAULT '',
                conversion_status TEXT DEFAULT 'unknown'
            )""")

            # 叫醒服务
            c.execute("""CREATE TABLE IF NOT EXISTS wake_up (
                uid INTEGER PRIMARY KEY,
                wake_time TEXT
            )""")

            # 碎片寻宝积分
            c.execute("""CREATE TABLE IF NOT EXISTS puzzle_scores (
                uid INTEGER PRIMARY KEY,
                score INTEGER DEFAULT 0
            )""")

            # 碎片寻宝每日记录（防止同一天重复计分）
            c.execute("""CREATE TABLE IF NOT EXISTS puzzle_daily (
                uid INTEGER,
                date TEXT,
                ts INTEGER DEFAULT 0,
                PRIMARY KEY (uid, date)
            )""")

            # 购物车挽回
            c.execute("""CREATE TABLE IF NOT EXISTS cart_recovery (
                uid INTEGER PRIMARY KEY,
                ts INTEGER
            )""")

            # 阅后即焚追踪（【修复v21.33】复合主键，Telegram message_id跨群会重复）
            c.execute("""CREATE TABLE IF NOT EXISTS reply_tracking (
                bot_msg_id INTEGER,
                chat_id INTEGER,
                user_msg_id INTEGER,
                ts INTEGER,
                replied INTEGER DEFAULT 0,
                PRIMARY KEY (bot_msg_id, chat_id)
            )""")

            # 用户等级/积分
            c.execute("""CREATE TABLE IF NOT EXISTS user_levels (
                uid INTEGER PRIMARY KEY,
                level INTEGER DEFAULT 1,
                points INTEGER DEFAULT 0,
                join_date INTEGER,
                last_active INTEGER
            )""")

            # 禁言记录
            c.execute("""CREATE TABLE IF NOT EXISTS mute_records (
                uid INTEGER PRIMARY KEY,
                chat_id INTEGER,
                mute_until INTEGER,
                reason TEXT
            )""")

            # 黑名单
            c.execute("""CREATE TABLE IF NOT EXISTS blacklist (
                uid INTEGER PRIMARY KEY,
                reason TEXT,
                date INTEGER
            )""")

            # 全局黑名单（广告封禁专用，跨群生效）
            c.execute("""CREATE TABLE IF NOT EXISTS global_blacklist (
                user_id INTEGER PRIMARY KEY,
                reason TEXT,
                added_by INTEGER,
                added_at TEXT
            )""")

            # 转化漏斗（【修复v21.34】事件日志表，支持多次记录）
            c.execute("""CREATE TABLE IF NOT EXISTS conversion_events (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                uid   INTEGER,
                event TEXT,
                ts    INTEGER,
                mode  TEXT DEFAULT ''
            )""")
            # [TRAE SOLO CN] v5.12.3 新增：conversions 转化追踪表（AGENTS.md 商业闭环核心表）
            c.execute("""CREATE TABLE IF NOT EXISTS conversions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER,
                event TEXT,
                value REAL DEFAULT 0,
                chat_id INTEGER DEFAULT 0,
                ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_conversions_uid ON conversions(uid)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_conversions_event ON conversions(event)")
            # [TRAE SOLO CN] v5.12.3 补充：conversion_events 表索引（加速漏斗查询和用户维度查询）
            c.execute("CREATE INDEX IF NOT EXISTS idx_conversion_events_uid ON conversion_events(uid)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_conversion_events_event ON conversion_events(event)")

            # 垃圾信息/反刷记录
            c.execute("""CREATE TABLE IF NOT EXISTS spam_track (
                uid INTEGER PRIMARY KEY,
                msg_count INTEGER DEFAULT 0,
                window_start INTEGER
            )""")

            # 【架构重构v21.44】系统动态状态表
            # 替代 config.json 中的动态字段（如 CURRENT_MODEL_INDEX, IMAGE_POOL 等）
            c.execute("""CREATE TABLE IF NOT EXISTS system_states (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at INTEGER
            )""")

            # 【v4.2.3】群数据统计表
            c.execute("""CREATE TABLE IF NOT EXISTS group_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                chat_id INTEGER DEFAULT 0,
                joined_count INTEGER DEFAULT 0,
                left_count INTEGER DEFAULT 0,
                net_count INTEGER DEFAULT 0,
                total_members INTEGER DEFAULT 0,
                created_at INTEGER
            )""")

            # 【v4.9.5新增】入群/离群去重日志表（用于幂等性保护）
            c.execute("""CREATE TABLE IF NOT EXISTS group_join_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                chat_id INTEGER DEFAULT 0,
                user_id INTEGER,
                ts INTEGER
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_group_join_log ON group_join_log(date, chat_id, user_id)")
            c.execute("""CREATE TABLE IF NOT EXISTS group_left_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                chat_id INTEGER DEFAULT 0,
                user_id INTEGER,
                ts INTEGER
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_group_left_log ON group_left_log(date, chat_id, user_id)")

            # 【v4.2.3】频道内容追踪表（追踪机器人发的消息浏览量）
            c.execute("""CREATE TABLE IF NOT EXISTS channel_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                message_id INTEGER,
                content_type TEXT DEFAULT 'text',
                posted_at INTEGER,
                initial_views INTEGER DEFAULT 0,
                current_views INTEGER DEFAULT 0,
                last_checked_at INTEGER,
                UNIQUE(chat_id, message_id)
            )""")

            # 【v4.9.5新增】频道原生内容追踪表（追踪频道内所有消息，非仅Bot消息）
            c.execute("""CREATE TABLE IF NOT EXISTS channel_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                message_id INTEGER,
                posted_at INTEGER,
                views INTEGER DEFAULT 0,
                forwards INTEGER DEFAULT 0,
                content_type TEXT DEFAULT 'text',
                UNIQUE(chat_id, message_id)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_channel_posts_chat_date ON channel_posts(chat_id, posted_at)")

            # 【v4.9.6新增】频道成员快照表（用于日报/周报/月报的新增/离开计算）
            c.execute("""CREATE TABLE IF NOT EXISTS channel_member_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                member_count INTEGER,
                snapshot_date TEXT,
                created_at INTEGER,
                UNIQUE(chat_id, snapshot_date)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_channel_member_snapshot ON channel_member_snapshot(chat_id, snapshot_date)")

            # 【v4.13.1新增】验证码记录表
            c.execute("""CREATE TABLE IF NOT EXISTS verification_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                answer TEXT,
                ts INTEGER,
                verify_date TEXT,
                passed INTEGER DEFAULT 0,
                UNIQUE(chat_id, user_id, verify_date)
            )""")

            # 【v4.13.1新增】联邦封禁表
            c.execute("""CREATE TABLE IF NOT EXISTS federation_bans (
                user_id INTEGER PRIMARY KEY,
                banned_by INTEGER,
                reason TEXT,
                chat_id INTEGER,
                ts INTEGER
            )""")

            # 【v4.13.1新增】夜间模式设置表
            c.execute("""CREATE TABLE IF NOT EXISTS night_mode_settings (
                chat_id INTEGER PRIMARY KEY,
                start_hour INTEGER DEFAULT 23,
                end_hour INTEGER DEFAULT 7,
                enabled INTEGER DEFAULT 0
            )""")

            # 【v4.13.1新增】欢迎配置表
            c.execute("""CREATE TABLE IF NOT EXISTS welcome_configs (
                chat_id INTEGER PRIMARY KEY,
                welcome_text TEXT,
                goodbye_text TEXT,
                rules_text TEXT,
                enable_welcome INTEGER DEFAULT 1,
                enable_goodbye INTEGER DEFAULT 0,
                enable_rules INTEGER DEFAULT 0,
                clean_welcome INTEGER DEFAULT 0,
                media_file_id TEXT
            )""")

            # 【v4.3.0新增】用户勋章表
            c.execute("""CREATE TABLE IF NOT EXISTS user_badges (
                uid INTEGER,
                badge_id TEXT,
                earned_at INTEGER,
                PRIMARY KEY (uid, badge_id)
            )""")

            # 【v4.4.9新增】关键词自动回复表
            c.execute("""CREATE TABLE IF NOT EXISTS keyword_triggers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL,
                reply_text TEXT NOT NULL,
                reply_type TEXT DEFAULT 'static',
                action_type TEXT DEFAULT '',
                enabled INTEGER DEFAULT 1,
                created_at INTEGER,
                updated_at INTEGER
            )""")
            # 添加关键词索引，加速匹配
            c.execute("CREATE INDEX IF NOT EXISTS idx_keyword_trigger_enabled ON keyword_triggers(enabled)")

            # 【v5.12.0新增】孤儿播报追踪表（升级/早安午安晚安/定时播报等，30S或链式互删）
            # 复合主键 (chat_id, category)：每个群每个播报类型只保留最新一条
            # [Trae CN] 用于"发新消息删旧消息"互删机制和孤儿播报30S自动删除
            c.execute("""CREATE TABLE IF NOT EXISTS broadcast_tracking (
                chat_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                msg_id INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                PRIMARY KEY (chat_id, category)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_broadcast_tracking_ts ON broadcast_tracking(ts)")

            # 【v5.12.0新增】孤儿清理日志表 - 记录每次 _job_burn_orphan 执行的统计
            # [Trae CN] 用于 Dashboard /api/orphan/stats 可视化和运维审计
            c.execute("""CREATE TABLE IF NOT EXISTS orphan_cleanup_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at INTEGER NOT NULL,
                found_count INTEGER NOT NULL DEFAULT 0,
                deleted_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                error TEXT DEFAULT NULL,
                trigger TEXT DEFAULT 'scheduled'  -- scheduled / manual / force
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_orphan_cleanup_log_run_at ON orphan_cleanup_log(run_at)")

            c.execute("""CREATE TABLE IF NOT EXISTS task_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_key TEXT NOT NULL,
                exec_date TEXT NOT NULL,
                exec_ts REAL NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_task_log_key_date ON task_log(task_key, exec_date)")

            # [v5.14.0新增] 商业搭讪事件表 - 记录 Bot 主动搭讪用户的完整链路
            # 用于 Dashboard /api/engage/* 可视化、转化追踪、运营复盘
            c.execute("""CREATE TABLE IF NOT EXISTS proactive_engage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                uname TEXT NOT NULL DEFAULT '',
                msg TEXT NOT NULL DEFAULT '',
                matched_keyword TEXT NOT NULL DEFAULT '',
                reply_text TEXT NOT NULL DEFAULT '',
                ts INTEGER NOT NULL,
                converted INTEGER NOT NULL DEFAULT 0
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_proactive_engage_log_uid ON proactive_engage_log(uid)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_proactive_engage_log_ts ON proactive_engage_log(ts)")

            # 【v4.5.31】防连发：清理重复记录 + 添加UNIQUE约束
            try:
                c.execute("""DELETE FROM task_log WHERE id NOT IN (
                    SELECT MIN(id) FROM task_log GROUP BY task_key, exec_date
                )""")
                c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_task_log_unique ON task_log(task_key, exec_date)")
            except Exception as e:
                logger.debug(f"task_log唯一索引迁移: {e}")

            c.execute("""CREATE TABLE IF NOT EXISTS reply_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_msg_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                feedback TEXT NOT NULL,
                ts INTEGER NOT NULL,
                UNIQUE(bot_msg_id, chat_id, user_id)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_reply_feedback_ts ON reply_feedback(ts)")

            # ── 【v4.14新增】签到/商城/红包/抽奖/认证/标签/统计表 ──────
            c.execute("""CREATE TABLE IF NOT EXISTS checkin_records (
                uid INTEGER NOT NULL,
                date TEXT NOT NULL,
                continuous_days INTEGER DEFAULT 1,
                points_earned INTEGER DEFAULT 0,
                ts INTEGER NOT NULL,
                UNIQUE(uid, date)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_checkin_uid ON checkin_records(uid)")

            c.execute("""CREATE TABLE IF NOT EXISTS invite_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inviter_uid INTEGER NOT NULL,
                invitee_uid INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_invite_inviter ON invite_records(inviter_uid)")

            c.execute("""CREATE TABLE IF NOT EXISTS coupon_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'points',
                value INTEGER NOT NULL DEFAULT 0,
                days INTEGER NOT NULL DEFAULT 0,
                expires_at INTEGER NOT NULL DEFAULT 0,
                claimed_by INTEGER DEFAULT 0,
                claimed_at INTEGER DEFAULT 0,
                used_at INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL,
                UNIQUE(code)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_coupon_code ON coupon_claims(code)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_coupon_claimed_by ON coupon_claims(claimed_by)")

            c.execute("""CREATE TABLE IF NOT EXISTS shop_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                points_cost INTEGER NOT NULL,
                stock INTEGER DEFAULT -1,
                description TEXT DEFAULT '',
                category TEXT DEFAULT 'default',
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS exchange_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                item_name TEXT DEFAULT '',
                points_cost INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                status TEXT DEFAULT 'pending'
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_exchange_uid ON exchange_records(uid)")

            c.execute("""CREATE TABLE IF NOT EXISTS redpackets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                total_points INTEGER NOT NULL,
                count INTEGER NOT NULL,
                remaining INTEGER NOT NULL,
                mode TEXT DEFAULT 'random',
                msg_id INTEGER DEFAULT 0,
                expired INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS redpacket_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                redpacket_id INTEGER NOT NULL,
                uid INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                UNIQUE(redpacket_id, uid)
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS lotteries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                prize TEXT NOT NULL,
                prize_count INTEGER DEFAULT 1,
                duration_min INTEGER DEFAULT 60,
                end_ts INTEGER NOT NULL,
                msg_id INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS lottery_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lottery_id INTEGER NOT NULL,
                uid INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                UNIQUE(lottery_id, uid)
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS certified_users (
                uid INTEGER PRIMARY KEY,
                certified_by INTEGER NOT NULL,
                reason TEXT DEFAULT '',
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS user_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                tag TEXT NOT NULL,
                added_by INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                UNIQUE(uid, tag)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_usertags_uid ON user_tags(uid)")

            c.execute("""CREATE TABLE IF NOT EXISTS user_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                note TEXT NOT NULL,
                added_by INTEGER NOT NULL,
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_usernotes_uid ON user_notes(uid)")

            c.execute("""CREATE TABLE IF NOT EXISTS speech_daily (
                uid INTEGER NOT NULL,
                date TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (uid, date, chat_id)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_speech_uid_date ON speech_daily(uid, date)")
            # 【v4.17.0新增】日报按日期+群组查询的复合索引
            c.execute("CREATE INDEX IF NOT EXISTS idx_speech_date_chat ON speech_daily(date, chat_id)")

            # ── 【v4.15新增】积分增强/AFK/任务/成就/盲盒/转盘表 ──────
            c.execute("""CREATE TABLE IF NOT EXISTS points_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                change_amount INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                source TEXT NOT NULL,
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_points_log_uid ON points_log(uid)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_points_log_uid_ts ON points_log(uid, ts)")

            c.execute("""CREATE TABLE IF NOT EXISTS afk_status (
                uid INTEGER PRIMARY KEY,
                reason TEXT DEFAULT '',
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS daily_quests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                date TEXT NOT NULL,
                quest_type TEXT NOT NULL,
                completed INTEGER DEFAULT 0,
                ts INTEGER NOT NULL,
                UNIQUE(uid, date, quest_type)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_daily_quests_uid_date ON daily_quests(uid, date)")

            c.execute("""CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                achievement_id TEXT NOT NULL,
                earned_at INTEGER NOT NULL,
                UNIQUE(uid, achievement_id)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_achievements_uid ON achievements(uid)")

            c.execute("""CREATE TABLE IF NOT EXISTS blind_box_prizes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                probability REAL NOT NULL DEFAULT 1.0,
                prize_type TEXT NOT NULL DEFAULT 'points',
                value INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS lucky_wheel_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                date TEXT NOT NULL,
                reward INTEGER NOT NULL DEFAULT 0,
                spin_count INTEGER NOT NULL DEFAULT 1,
                ts INTEGER NOT NULL,
                UNIQUE(uid, date)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_lucky_wheel_uid_date ON lucky_wheel_results(uid, date)")
            # 兼容旧表：添加 spin_count 列
            try:
                c.execute("ALTER TABLE lucky_wheel_results ADD COLUMN spin_count INTEGER NOT NULL DEFAULT 1")
            except Exception as e:
                self._log_db_error("ALTER TABLE lucky_wheel_results ADD COLUMN spin_count", e, "warning", "表结构迁移")

            # ── 【v4.16新增】高级群管功能表 ──────
            c.execute("""CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                reason TEXT DEFAULT '',
                warned_by INTEGER NOT NULL,
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_warnings_uid_chat ON warnings(uid, chat_id)")

            c.execute("""CREATE TABLE IF NOT EXISTS message_locks (
                chat_id INTEGER NOT NULL,
                lock_type TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL,
                PRIMARY KEY (chat_id, lock_type)
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS group_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                note_name TEXT NOT NULL,
                content TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                UNIQUE(chat_id, note_name)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_group_notes_chat ON group_notes(chat_id)")

            c.execute("""CREATE TABLE IF NOT EXISTS custom_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                cmd_name TEXT NOT NULL,
                response TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                UNIQUE(chat_id, cmd_name)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_custom_cmds_chat ON custom_commands(chat_id)")

            c.execute("""CREATE TABLE IF NOT EXISTS scheduled_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                send_time TEXT NOT NULL,
                content TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                enabled INTEGER DEFAULT 1
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_chat ON scheduled_messages(chat_id)")

            c.execute("""CREATE TABLE IF NOT EXISTS vote_kicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                target_uid INTEGER NOT NULL,
                initiator_id INTEGER NOT NULL,
                reason TEXT DEFAULT '',
                yes_votes TEXT DEFAULT '',
                no_votes TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                msg_id INTEGER DEFAULT 0,
                end_ts INTEGER NOT NULL,
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_vote_kicks_chat ON vote_kicks(chat_id)")

            # ── 【v4.17新增】主流Bot功能补齐表 ──────
            c.execute("""CREATE TABLE IF NOT EXISTS clean_service_settings (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS disabled_commands (
                chat_id INTEGER NOT NULL,
                cmd_name TEXT NOT NULL,
                ts INTEGER NOT NULL,
                PRIMARY KEY (chat_id, cmd_name)
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                operator_uid INTEGER NOT NULL,
                target_uid INTEGER DEFAULT 0,
                action TEXT NOT NULL,
                reason TEXT DEFAULT '',
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_admin_logs_chat ON admin_logs(chat_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_admin_logs_ts ON admin_logs(ts)")

            c.execute("""CREATE TABLE IF NOT EXISTS deleted_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                uid INTEGER NOT NULL,
                content TEXT DEFAULT '',
                content_type TEXT DEFAULT 'text',
                msg_id INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_deleted_msgs_chat ON deleted_messages(chat_id)")

            # [TRAE SOLO CN] v5.15.3 新增：消息追踪表 message_snapshots（AGENTS.md 教训 #17 落实）
            # Bot API 无法枚举群历史消息，删除历史消息必须依赖此表的 msg_id 记录
            # 之前 v5.15.2 P1 拦截只 return True 静默吞了，没记 msg_id → 18:36 教白嫖消息删不掉
            c.execute("""CREATE TABLE IF NOT EXISTS message_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                msg_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                text TEXT DEFAULT '',
                ts INTEGER NOT NULL,
                is_ad INTEGER DEFAULT 0,
                deleted INTEGER DEFAULT 0,
                UNIQUE(chat_id, msg_id)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_msg_snapshots_chat_ts ON message_snapshots(chat_id, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_msg_snapshots_user ON message_snapshots(user_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_msg_snapshots_ad ON message_snapshots(is_ad, deleted)")

            c.execute("""CREATE TABLE IF NOT EXISTS connected_chats (
                uid INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                PRIMARY KEY (uid)
            )""")

            # ── 【v4.18新增】主流Bot完整功能补齐表 ──────
            c.execute("""CREATE TABLE IF NOT EXISTS antiflood_settings (
                chat_id INTEGER PRIMARY KEY,
                window INTEGER DEFAULT 5,
                threshold INTEGER DEFAULT 5,
                mute_duration INTEGER DEFAULT 60,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS approved_users (
                chat_id INTEGER NOT NULL,
                uid INTEGER NOT NULL,
                approved_by INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                PRIMARY KEY (chat_id, uid)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_approved_chat ON approved_users(chat_id)")

            c.execute("""CREATE TABLE IF NOT EXISTS blocklist_modes (
                chat_id INTEGER PRIMARY KEY,
                mode TEXT DEFAULT 'delete',
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS force_subscribe (
                chat_id INTEGER PRIMARY KEY,
                channel_username TEXT DEFAULT '',
                channel_id INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                trigger_ts INTEGER NOT NULL,
                content TEXT DEFAULT '',
                sent INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_reminders_uid ON reminders(uid)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_reminders_trigger ON reminders(trigger_ts)")

            c.execute("""CREATE TABLE IF NOT EXISTS anti_channel_settings (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS nsfw_settings (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                threshold REAL DEFAULT 0.7,
                ts INTEGER NOT NULL
            )""")

            # ── 【v5.0.0设置面板完全体新增】配置表补齐 ──────
            # 警告设置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS warning_settings (
                chat_id INTEGER PRIMARY KEY,
                warn_limit INTEGER DEFAULT 3,
                warn_action TEXT DEFAULT 'mute',
                warn_duration INTEGER DEFAULT 3600,
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            # 慢速模式（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS slow_mode_config (
                chat_id INTEGER PRIMARY KEY,
                interval INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            # 举报配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS report_settings (
                chat_id INTEGER PRIMARY KEY,
                cooldown INTEGER DEFAULT 300,
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            # 投票踢人配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS votekick_config (
                chat_id INTEGER PRIMARY KEY,
                min_yes INTEGER DEFAULT 5,
                min_ratio REAL DEFAULT 0.6,
                duration INTEGER DEFAULT 300,
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            # 反突袭配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS anti_raid_config (
                chat_id INTEGER PRIMARY KEY,
                threshold INTEGER DEFAULT 5,
                window INTEGER DEFAULT 60,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            # 盲盒配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS blind_box_config (
                chat_id INTEGER PRIMARY KEY,
                cost INTEGER DEFAULT 50,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            # 转盘配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS lucky_wheel_config (
                chat_id INTEGER PRIMARY KEY,
                cost INTEGER DEFAULT 30,
                free_spins INTEGER DEFAULT 1,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            # 红包配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS redpacket_config (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                min_amount INTEGER DEFAULT 1,
                max_amount INTEGER DEFAULT 100,
                ts INTEGER NOT NULL
            )""")

            # 抽奖配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS lottery_config (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            # 签到配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS checkin_config (
                chat_id INTEGER PRIMARY KEY,
                base_points INTEGER DEFAULT 5,
                streak_bonus TEXT DEFAULT '{"3":5,"7":15}',
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            # 商城配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS shop_config (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            # 优惠券配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS coupon_config (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            # 打赏配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS tip_config (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                min_amount INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            # 每日任务配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS daily_quest_config (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            # 成就配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS achievement_config (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            # 积分衰减配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS points_decay_config (
                chat_id INTEGER PRIMARY KEY,
                rate REAL DEFAULT 0.01,
                minimum INTEGER DEFAULT 10,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            # AFK配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS afk_config (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            # 【v5.0.0新增】广告检测追踪表（持久化可疑用户评分）
            c.execute("""CREATE TABLE IF NOT EXISTS ad_suspicious_users (
                user_id INTEGER PRIMARY KEY,
                score INTEGER DEFAULT 0,
                first_seen TEXT,
                messages TEXT DEFAULT '[]',
                updated_at INTEGER
            )""")

            # [TRAE SOLO CN] v5.8.1 新增：群成员追踪表（渐进式构建完整成员列表）
            c.execute("""CREATE TABLE IF NOT EXISTS group_members (
                uid INTEGER,
                chat_id INTEGER,
                username TEXT DEFAULT '',
                display_name TEXT DEFAULT '',
                bio TEXT DEFAULT '',
                status TEXT DEFAULT 'member',
                first_seen INTEGER,
                last_checked INTEGER,
                PRIMARY KEY (uid, chat_id)
            )""")

            # ── 兼容性迁移：旧数据库缺少的列自动补齐 ──────────────────
            try:
                self.conn.execute("SELECT replied FROM reply_tracking LIMIT 0")
            except Exception as e:
                self._log_db_error("SELECT replied FROM reply_tracking", e, "warning", "检查列是否存在")
                self.conn.execute("ALTER TABLE reply_tracking ADD COLUMN replied INTEGER DEFAULT 0")
                logger.info("🔄 数据库迁移：reply_tracking 补充 replied 列")

            # 【修复v21.33】reply_tracking 单主键 → 复合主键迁移
            try:
                c = self.conn.cursor()
                c.execute("PRAGMA table_info(reply_tracking)")
                cols = [r[1] for r in c.fetchall()]
                if "chat_id" not in cols:
                    self.conn.execute("ALTER TABLE reply_tracking ADD COLUMN chat_id INTEGER")
                    logger.info("🔄 数据库迁移：reply_tracking 补充 chat_id 列")
            except Exception as e:
                logger.warning(f"🔄 reply_tracking 迁移检查跳过：{e}")
            try:
                self.conn.execute("SELECT conversion_status FROM users LIMIT 0")
            except Exception as e:
                self._log_db_error("SELECT conversion_status FROM users", e, "warning", "检查列是否存在")
                self.conn.execute("ALTER TABLE users ADD COLUMN conversion_status TEXT DEFAULT 'unknown'")
                logger.info("🔄 数据库迁移：users 补充 conversion_status 列")

            try:
                c.execute("SELECT chat_id FROM group_stats LIMIT 1")
            except Exception as e:
                self._log_db_error("SELECT chat_id FROM group_stats", e, "warning", "检查列是否存在")
                c.execute("ALTER TABLE group_stats ADD COLUMN chat_id INTEGER DEFAULT 0")
                logger.info("✅ group_stats表已添加chat_id列")

            # checkin_records 补充 current_streak 列
            try:
                self.conn.execute("SELECT current_streak FROM checkin_records LIMIT 0")
            except Exception as e:
                self._log_db_error("SELECT current_streak FROM checkin_records", e, "warning", "检查列是否存在")
                self.conn.execute("ALTER TABLE checkin_records ADD COLUMN current_streak INTEGER DEFAULT 0")
                logger.info("🔄 数据库迁移：checkin_records 补充 current_streak 列")

            # ── [v5.15.0新增] 问题追踪与FAQ蒸馏表 ──────
            # 用户问题记录表（记录每条用户提问，用于FAQ蒸馏和问题分析）
            c.execute("""CREATE TABLE IF NOT EXISTS user_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                question_text TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL DEFAULT '',
                intent TEXT NOT NULL DEFAULT '',
                keyword_tag TEXT NOT NULL DEFAULT '',
                question_category TEXT NOT NULL DEFAULT 'other',
                is_convert INTEGER NOT NULL DEFAULT 0,
                ai_reply_summary TEXT NOT NULL DEFAULT '',
                faq_hit_id INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_user_questions_uid ON user_questions(uid)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_user_questions_ts ON user_questions(ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_user_questions_category ON user_questions(question_category)")

            # FAQ知识库表（审核通过的FAQ条目，用于智能匹配回复）
            c.execute("""CREATE TABLE IF NOT EXISTS faq_knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_pattern TEXT NOT NULL DEFAULT '',
                question_category TEXT NOT NULL DEFAULT 'other',
                answer_template TEXT NOT NULL DEFAULT '',
                ai_polish INTEGER NOT NULL DEFAULT 1,
                match_mode TEXT NOT NULL DEFAULT 'keyword',
                priority INTEGER NOT NULL DEFAULT 0,
                hit_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'approved',
                created_by TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_faq_knowledge_category ON faq_knowledge(question_category)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_faq_knowledge_status ON faq_knowledge(status)")

            # FAQ候选表（高频问题自动蒸馏生成，待人工审核）
            c.execute("""CREATE TABLE IF NOT EXISTS faq_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_pattern TEXT NOT NULL DEFAULT '',
                question_category TEXT NOT NULL DEFAULT 'other',
                sample_questions TEXT NOT NULL DEFAULT '',
                frequency INTEGER NOT NULL DEFAULT 0,
                mode TEXT NOT NULL DEFAULT '',
                intent TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                reviewed_by TEXT NOT NULL DEFAULT '',
                reviewed_at INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_faq_candidates_status ON faq_candidates(status)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_faq_candidates_category ON faq_candidates(question_category)")

            # 中继会话追踪（双向通信：管理员回复转发消息时查找原始用户）
            c.execute("""CREATE TABLE IF NOT EXISTS relay_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_chat_id INTEGER,
                admin_msg_id INTEGER,
                user_id INTEGER,
                user_chat_id INTEGER,
                source_type TEXT DEFAULT 'private',
                ts INTEGER DEFAULT 0
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_relay_admin_msg ON relay_sessions(admin_chat_id, admin_msg_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_relay_ts ON relay_sessions(ts)")

            self.conn.commit()

            # ── 性能索引（IF NOT EXISTS 幂等）【v4.2.8增强：添加replied索引防止全表扫描】─
            _indexes = [
                "CREATE INDEX IF NOT EXISTS idx_users_last_active ON users(last_active)",
                "CREATE INDEX IF NOT EXISTS idx_users_conv ON users(conversion_status)",
                "CREATE INDEX IF NOT EXISTS idx_levels_points ON user_levels(points DESC)",
                "CREATE INDEX IF NOT EXISTS idx_track_ts ON reply_tracking(ts)",
                "CREATE INDEX IF NOT EXISTS idx_track_chat ON reply_tracking(chat_id)",
                "CREATE INDEX IF NOT EXISTS idx_track_bot_chat ON reply_tracking(bot_msg_id, chat_id)",
                "CREATE INDEX IF NOT EXISTS idx_track_replied ON reply_tracking(ts, replied)",  # 【v4.2.8新增】加速孤儿消息查询
                "CREATE INDEX IF NOT EXISTS idx_cart_ts ON cart_recovery(ts)",
                "CREATE INDEX IF NOT EXISTS idx_mute_until ON mute_records(mute_until)",
                "CREATE INDEX IF NOT EXISTS idx_wake_uid ON wake_up(uid)",
                "CREATE INDEX IF NOT EXISTS idx_puzzle_uid ON puzzle_scores(uid)",
            ]
            for _idx_sql in _indexes:
                self.conn.execute(_idx_sql)
            self.conn.commit()

        logger.info("✅ 数据库初始化完成（含11个性能索引）")

    # ──────────────────────────── 向后兼容委托 ──────────────────────────
    _REPO_METHOD_MAP = {
        # user_repo
        'upsert_user': 'users', 'upsert_user_with_points': 'users', 'get_user': 'users',
        'add_keyword': 'users', 'get_active_users': 'users', 'get_inactive_users': 'users',
        'reset_last_active': 'users', 'update_last_active': 'users', 'earn_badge': 'users', 'get_user_badges': 'users',
        'get_all_badges_leaderboard': 'users', 'get_user_profile': 'users',
        'get_all_user_profiles': 'users', 'delete_user': 'users',
        # group_repo
        'record_group_join': 'groups', 'record_group_left': 'groups',
        'update_group_total_members': 'groups', 'get_group_stats': 'groups',
        'get_group_stats_by_date': 'groups', 'get_group_stats_by_chat_id': 'groups',
        'get_weekly_group_stats': 'groups', 'get_weekly_channel_member_stats': 'groups',
        'calibrate_group_stats': 'groups', 'get_group_total_members_latest': 'groups',
        'mute_user': 'groups', 'is_muted': 'groups',
        'blacklist_add': 'groups', 'blacklist_remove': 'groups', 'is_blacklisted': 'groups',
        'check_spam': 'groups',
        'record_channel_member_snapshot': 'groups', 'get_channel_member_changes': 'groups',
        'get_channel_weekly_member_changes': 'groups', 'get_channel_monthly_member_changes': 'groups',
        'upsert_group_member': 'groups', 'remove_group_member': 'groups',
        'get_group_member_count': 'groups', 'get_all_group_member_ids': 'groups',
        # points_repo
        'get_user_points': 'points', 'add_points': 'points',
        'get_points_log': 'points', 'get_today_speech_points': 'points',
        'get_leaderboard': 'points', 'get_daily_report': 'points',
        # tracking_repo
        'track_reply': 'tracking', 'mark_replied': 'tracking', 'get_replies_to': 'tracking',
        'track_bot_message': 'tracking',  # [Trae CN v5.12.0补] 之前漏注册，导致 _send_and_track 报属性错误
        'get_recent_unreplied': 'tracking', 'get_orphan_messages': 'tracking',
        'get_unreplied_messages': 'tracking', 'get_ignored_messages': 'tracking',
        'get_all_tracked_messages': 'tracking', 'get_unconfirmed_messages': 'tracking',
        'delete_tracked': 'tracking', 'get_tracking_stats': 'tracking',
        'cleanup_old_records': 'tracking',
        'track_channel_message': 'tracking', 'update_channel_views': 'tracking',
        'get_channel_tracking': 'tracking', 'get_channel_stats_summary': 'tracking',
        'get_daily_active_users': 'tracking', 'get_daily_bot_messages': 'tracking',
        'get_daily_replies': 'tracking',
        'track_channel_post': 'tracking', 'update_channel_post_views': 'tracking',
        'get_channel_post_stats': 'tracking', 'get_channel_recent_posts': 'tracking',
        'get_channel_top_posts': 'tracking', 'get_channel_avg_views': 'tracking',
        'get_channel_posts_in_range': 'tracking', 'get_channel_daily_stats': 'tracking',
        # tracking_repo - v5.11.0 孤儿播报追踪
        'track_broadcast': 'tracking', 'get_last_broadcast': 'tracking',
        'delete_broadcast': 'tracking', 'cleanup_old_broadcasts': 'tracking',
        # tracking_repo - v5.12.0 孤儿清理监控
        'log_orphan_cleanup': 'tracking', 'get_last_orphan_cleanup': 'tracking',
        'get_orphan_cleanup_history': 'tracking', 'get_orphan_stats': 'tracking',
        # tracking_repo - v5.14.0 商业搭讪事件
        'log_proactive_engage': 'tracking', 'get_recent_engages': 'tracking',
        'get_engaged_stats': 'tracking',
        # config_repo
        'get_system_state': 'config', 'set_system_state': 'config',
        'add_keyword_trigger': 'config', 'get_all_keyword_triggers': 'config',
        'delete_keyword_trigger': 'config', 'update_keyword_trigger': 'config',
        'match_keyword_trigger': 'config',
        'claim_task': 'config', 'is_task_executed_today': 'config',
        'cleanup_old_task_log': 'config',
        # social_repo
        'set_wake_up': 'social', 'get_all_wake_ups': 'social',
        'inc_puzzle_score': 'social', '_calc_consecutive_days': 'social',
        'set_cart': 'social', 'get_expired_carts': 'social',
        'log_conversion_event': 'social', 'get_user_consult_count': 'social',
        'get_funnel_summary': 'social',
        'record_feedback': 'social', 'get_feedback_stats': 'social', 'get_recent_feedback': 'social',
        # question_repo - v5.15.0 问题追踪与FAQ蒸馏
        'log_question': 'questions', 'update_question_reply': 'questions',
        'get_question_stats': 'questions', 'get_top_questions': 'questions',
        'get_category_distribution': 'questions', 'get_questions': 'questions',
        'search_faq': 'questions', 'increment_faq_hit': 'questions',
        'create_faq_candidate': 'questions', 'get_pending_candidates': 'questions',
        'approve_candidate': 'questions', 'reject_candidate': 'questions',
        'get_faq_knowledge': 'questions', 'add_faq_knowledge': 'questions',
        'update_faq_knowledge': 'questions', 'delete_faq_knowledge': 'questions',
        'distill_candidates': 'questions',
        # relay_repo
        'save_session': 'relay', 'find_by_admin_msg': 'relay', 'clean_expired': 'relay',
    }

    def __getattr__(self, name):
        repo_name = self._REPO_METHOD_MAP.get(name)
        if repo_name:
            return getattr(getattr(self, repo_name), name)
        raise AttributeError(f"'DB' object has no attribute '{name}'")
